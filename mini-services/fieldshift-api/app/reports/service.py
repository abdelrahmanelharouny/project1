"""Report job lifecycle service (P3 W5) — synchronous, Session-based.

Flow: ``create_report_job`` validates access + entitlements and queues a
``report_jobs`` row → an executor (inline for small formats, or the
integrator's background worker via ``core.jobs``) runs
``execute_report_job`` which gathers data section-by-section (each section
wrapped — a failing data source degrades to ``provenance: "missing"``
instead of failing the whole report), renders bytes with the pure renderers,
writes the artifact under ``settings.reports_dir`` and finalizes the row.

Honesty contract (P3 §6.2): every section/KPI carries provenance; missing
data is reported as missing, never fabricated. The ``title`` argument on
create is recorded on the activity timeline (the current ``report_jobs``
schema has no title column); the rendered title comes from the report-type
registry (localized).

Error hygiene: failed jobs store ``Type: message`` (truncated) — no SQL,
no environment, no secrets.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.billing import entitlements
from app.core.config import settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.models import CropHistory, Farm, Field, Observation, Organization
from app.db.models_ai import AIRecommendation
from app.db.models_m6bc_m7 import SoilMeasurement
from app.db.models import WaterPlan
from app.db.models_p3 import ReportJob
from app.domains.identity.service import (
    Principal,
    get_field_for_principal,
    get_farm_for_principal,
)
from app.geospatial.objectstore import NotFoundError as ArtifactNotFoundError
from app.geospatial.objectstore import StorageError as ArtifactStorageError
from app.geospatial.postgres_objectstore import PostgresStorage
from app.reports import contracts, renderers

logger = logging.getLogger("croptwist.reports")

PROVENANCE_OBSERVED = contracts.PROVENANCE_OBSERVED
PROVENANCE_MODEL = contracts.PROVENANCE_MODEL
PROVENANCE_MISSING = contracts.PROVENANCE_MISSING

# Hard cap on rows gathered per section (background-safety, mirrors the
# renderer's PDF preview cap).
SECTION_ROW_CAP = 500

# Localized section headings (table column headers remain English machine
# labels in v1 — declared in the payload limitations for locale=ar).
_SECTION_HEADINGS: dict[str, tuple[str, str]] = {
    "overview": ("Overview", "نظرة عامة"),
    "field_breakdown": ("Field breakdown", "تفصيل الحقول"),
    "crop_cycles": ("Crop cycles", "الدورات الزراعية"),
    "water": ("Water", "المياه"),
    "soil": ("Soil measurements", "قياسات التربة"),
    "recommendations": ("Active recommendations", "التوصيات النشطة"),
    "seasonality": ("Seasonal observations", "الملاحظات الموسمية"),
    "risk": ("Exposure & freshness", "التعرض وحداثة البيانات"),
    "data_quality": ("Data quality", "جودة البيانات"),
    # P07 — satellite / spatial / environmental intelligence sections
    "data_availability": ("Data availability & coverage", "توفر البيانات والتغطية"),
    "satellite": ("Satellite observations & vegetation indices", "المشاهدات الفضائية ومؤشرات الغطاء النباتي"),
    "spatial": ("Spatial variation & anomaly signals", "التباين المكاني وإشارات الشذوذ"),
    "environmental": ("Environmental observations", "المشاهدات البيئية"),
    "methodology": ("Methodology & sources", "المنهجية والمصادر"),
}

# P07: recorded on every generated payload so consumers can trace exactly
# which report-generation code produced a file.
REPORT_GENERATION_VERSION = "fieldshift-reports-p07-1.0.0"

_VARIABLE_FAMILY = (
    "precipitation",
    "air_temperature_max",
    "air_temperature_min",
    "soil_moisture",
    "ndvi",
)


def _heading(key: str, locale: str) -> str:
    en, ar = _SECTION_HEADINGS.get(key, (key.replace("_", " "), key))
    return ar if locale == "ar" else en


# ------------------------------------------------------------------ payloads
def job_payload(job: ReportJob) -> dict[str, Any]:
    """API shape for a report job. The server-side artifact path is NOT
    exposed; clients use the download endpoint."""
    return {
        "id": str(job.id),
        "organization_id": str(job.organization_id),
        "farm_id": str(job.farm_id) if job.farm_id else None,
        "field_id": str(job.field_id) if job.field_id else None,
        "requested_by": str(job.requested_by) if job.requested_by else None,
        "report_type": job.report_type,
        "output_format": job.output_format,
        "locale": job.locale,
        "date_from": job.date_from.isoformat(),
        "date_to": job.date_to.isoformat(),
        "status": job.status,
        "file_size_bytes": job.file_size_bytes,
        "error": job.error,
        "retention_until": job.retention_until.isoformat() if job.retention_until else None,
        "interval_days": job.interval_days,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "background_job_id": str(job.background_job_id) if job.background_job_id else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ------------------------------------------------------------------ creation
def create_report_job(
    session: Session,
    principal: Principal,
    *,
    report_type: str,
    output_format: str,
    locale: str = "en",
    farm_id: uuid.UUID | None = None,
    field_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    title: str | None = None,
) -> ReportJob:
    """Validate, gate and queue a report job.

    Access: the caller needs an ACTIVE membership with role >= viewer on the
    target organization (explicitly via farm/field/org scope, or implicitly
    when the principal belongs to exactly one organization).

    Entitlements are resolved for every organization; organizations without
    a paid subscription receive the catalog's Free-plan limits.
    """
    if report_type not in contracts.REPORT_TYPES:
        raise ValidationFailed(
            f"Unknown report type '{report_type}'.",
            details=[{"field": "report_type", "reason": sorted(contracts.REPORT_TYPES)}],
        )
    if output_format not in contracts.REPORT_FORMATS:
        raise ValidationFailed(
            f"Unknown report format '{output_format}'.",
            details=[{"field": "output_format", "reason": list(contracts.REPORT_FORMATS)}],
        )
    if locale not in contracts.REPORT_LOCALES:
        raise ValidationFailed(
            f"Unknown locale '{locale}'.",
            details=[{"field": "locale", "reason": list(contracts.REPORT_LOCALES)}],
        )
    if title is not None and len(title) > 300:
        raise ValidationFailed("title must be at most 300 characters.")

    # ---- scope resolution + viewer-level access
    resolved_org_id: uuid.UUID
    farm: Farm | None = None
    if farm_id is not None:
        farm = get_farm_for_principal(session, principal, farm_id)
        principal.require_org_role(farm.organization_id, "viewer")
        resolved_org_id = farm.organization_id
        if field_id is not None:
            field = get_field_for_principal(session, principal, field_id)
            if field.farm_id != farm.id:
                raise ValidationFailed("field_id must belong to the selected farm_id.")
    elif field_id is not None:
        field = get_field_for_principal(session, principal, field_id)
        farm = session.get(Farm, field.farm_id)
        principal.require_org_role(farm.organization_id, "viewer")
        resolved_org_id = farm.organization_id
    elif organization_id is not None:
        principal.require_org_role(organization_id, "viewer")
        resolved_org_id = organization_id
    else:
        org_ids = principal.org_ids()
        if len(org_ids) == 1:
            resolved_org_id = next(iter(org_ids))
        else:
            raise ValidationFailed(
                "Provide farm_id, field_id or organization_id to scope the report."
            )

    # ---- date range (model check: date_to >= date_from)
    if date_from is None and date_to is None:
        date_from, date_to = contracts.default_date_range()
    elif date_from is None or date_to is None:
        raise ValidationFailed("Provide both date_from and date_to, or neither.")
    if date_from > date_to:
        raise ValidationFailed(
            "date_from must be on or before date_to.",
            details=[{"field": "date_from", "reason": str(date_from)}],
        )

    # ---- resolve plan entitlements even without a paid subscription (Free)
    entitlements.require_flag(session, resolved_org_id, entitlements.KEY_EXPORTS_ENABLED)
    entitlements.check_quota(session, resolved_org_id, entitlements.KEY_REPORTS_PER_MONTH)

    job = ReportJob(
        organization_id=resolved_org_id,
        farm_id=farm.id if farm is not None else None,
        field_id=field_id,
        requested_by=principal.id,
        report_type=report_type,
        output_format=output_format,
        locale=locale,
        date_from=date_from,
        date_to=date_to,
        status=contracts.REPORT_STATUS_QUEUED,
    )
    session.add(job)
    session.flush()

    activity.record_event(
        session,
        organization_id=resolved_org_id,
        event_type=activity.EVENT_REPORT_CREATED,
        summary=f"Report '{report_type}' queued ({output_format}, {locale}).",
        farm_id=job.farm_id,
        actor_user_id=principal.id,
        entity_kind="report_job",
        entity_id=str(job.id),
        details={
            "report_type": report_type,
            "output_format": output_format,
            "locale": locale,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "title": title,
        },
    )
    session.commit()
    return job


# ----------------------------------------------------------------- execution
def execute_report_job(
    session: Session,
    job_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """Render one report under a report-id advisory fence; return (success,error).

    The scheduler, inline entry points, and background worker all converge
    here. A PostgreSQL session advisory lock serializes them across processes;
    status is re-read after acquiring it, so a caller waiting behind a completed
    render observes ``succeeded`` and cannot meter usage or emit ``report.ready``
    again. A legacy ``running`` row fails closed because its effects are unknown.
    """
    import hashlib

    from sqlalchemy import text

    from app.core.database import engine

    lock_key = int.from_bytes(
        hashlib.blake2b(job_id.bytes, digest_size=8, person=b"report-exec").digest(),
        byteorder="big",
        signed=True,
    )
    connection = engine.connect()
    acquired = False
    try:
        if connection.dialect.name != "postgresql":
            return False, "report execution requires PostgreSQL advisory locking"
        connection.execute(
            text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": lock_key}
        )
        connection.commit()
        acquired = True

        # Lock the domain row after obtaining the cross-process fence and force
        # a fresh read: callers may have loaded a queued identity-map object
        # before waiting for another executor to finish.
        job = session.scalar(
            select(ReportJob).where(ReportJob.id == job_id).with_for_update()
        )
        if job is None:
            raise NotFound("Report job not found.")
        session.refresh(job)
        if job.status == contracts.REPORT_STATUS_SUCCEEDED:
            return True, None
        if job.status == contracts.REPORT_STATUS_EXPIRED:
            return False, "Report job has expired; regenerate it first."
        if job.status == contracts.REPORT_STATUS_RUNNING:
            return False, "Report job is already running; replay refused."

        now = now or datetime.now(UTC)
        job.status = contracts.REPORT_STATUS_RUNNING
        job.error = None
        session.commit()

        try:
            spec = contracts.get_report_type(job.report_type)
            payload = _build_payload(session, job, spec, now)
            blob = renderers.render(payload, job.output_format, job.locale)
            artifact_path = _write_artifact(job, blob)
            job.file_path = str(artifact_path)
            job.file_size_bytes = len(blob)
            job.status = contracts.REPORT_STATUS_SUCCEEDED
            job.error = None
            job.retention_until = contracts.retention_until_for(now)
            # The report terminal state and meter increment share one commit.
            # Re-entry observes succeeded before any later side effect.
            entitlements.increment_usage(
                session, job.organization_id, entitlements.KEY_REPORTS_PER_MONTH
            )
            session.commit()
            if payload.get("rendering_notes"):
                logger.info(
                    "report %s rendering notes: %s", job.id, payload["rendering_notes"]
                )
            # Event emission is intentionally after the terminal/meter commit.
            # A crash can leave a missing ready event, but a retry will never
            # duplicate it or charge usage again.
            try:
                from app.publicapi.emitters import emit_event

                emit_event(
                    session,
                    job.organization_id,
                    "report.ready",
                    payload_id=str(job.id),
                    data={
                        "report_job_id": str(job.id),
                        "report_type": job.report_type,
                        "format": job.output_format,
                        "locale": job.locale,
                    },
                )
                session.commit()
            except Exception:  # noqa: BLE001 — notification delivery is best-effort
                session.rollback()
            return True, None
        except Exception as exc:  # noqa: BLE001 — job failure must never raise
            session.rollback()
            job = session.get(ReportJob, job_id)
            if job is None:  # pragma: no cover — row deleted mid-flight
                return False, str(exc)
            job.status = contracts.REPORT_STATUS_FAILED
            job.error = _safe_error(exc)
            job.retention_until = contracts.retention_until_for(
                now, contracts.FAILED_JOB_RETENTION_DAYS
            )
            session.commit()
            logger.warning("report job %s failed: %s", job_id, job.error)
            return False, job.error
    finally:
        if acquired:
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
                connection.commit()
            except Exception:  # noqa: BLE001 — don't return a potentially locked connection
                connection.invalidate()
        connection.close()


def _safe_error(exc: Exception) -> str:
    """Storage-safe error line: type + message only, truncated."""
    message = f"{type(exc).__name__}: {exc}"
    return message[:2000]


def _reports_backend() -> str:
    """Return the configured report backend without requiring config changes."""
    return str(getattr(settings, "reports_storage_backend", "local") or "local").lower()


def _report_artifact_key(job: ReportJob) -> str:
    """Stable tenant-scoped key shared by report writes, reads, and deletes."""
    return f"org/{job.organization_id}/reports/{job.id}.{job.output_format}"


def _report_content_type(output_format: str) -> str:
    return {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv; charset=utf-8",
    }.get(output_format, "application/octet-stream")


def _write_artifact(job: ReportJob, blob: bytes) -> Path | str:
    if _reports_backend() == "postgres":
        stored = PostgresStorage().put_bytes(
            _report_artifact_key(job),
            blob,
            content_type=_report_content_type(job.output_format),
            overwrite=True,
        )
        return stored.key
    base = Path(settings.reports_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{job.id}.{job.output_format}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)  # atomic-ish publication
    return path


# ------------------------------------------------------------- data gathering
def _build_payload(
    session: Session, job: ReportJob, spec: contracts.ReportTypeSpec, now: datetime
) -> dict[str, Any]:
    organization = session.get(Organization, job.organization_id)
    farm = session.get(Farm, job.farm_id) if job.farm_id else None
    fields = _scope_fields(session, farm, job.organization_id, job.field_id)
    locale = job.locale
    if farm is not None:
        farm_count = 1
    else:
        farm_count = int(
            session.scalar(
                select(func.count())
                .select_from(Farm)
                .where(Farm.organization_id == job.organization_id)
            ) or 0
        )

    sections: list[dict[str, Any]] = []
    sections.append(_overview_section(job, spec, farm, fields, farm_count))

    builder_by_section: dict[str, Any] = {
        "field_breakdown": lambda: _field_breakdown_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        "water": lambda: _water_section(session, fields, job.date_from, job.date_to, locale),
        "soil": lambda: _soil_section(session, fields, locale),
        "recommendations": lambda: _recommendations_section(session, fields, locale),
        "crop_cycles": lambda: _crop_cycles_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        "seasonality": lambda: _seasonality_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        "risk": lambda: _risk_section(session, fields, locale),
        "data_quality": lambda: _data_quality_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        # P07 builders
        "data_availability": lambda: _data_availability_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        "satellite": lambda: _satellite_section(session, fields, locale),
        "spatial": lambda: _spatial_section(session, fields, locale),
        "environmental": lambda: _environmental_section(
            session, fields, job.date_from, job.date_to, locale
        ),
        "methodology": lambda: _methodology_section(session, fields, locale),
    }
    for key in spec.default_sections:
        if key == "overview":
            continue
        builder = builder_by_section.get(key)
        if builder is None:
            sections.append(
                contracts.missing_section(_heading(key, locale), "Section not implemented.")
            )
            continue
        try:
            sections.append(builder())
        except Exception as exc:  # noqa: BLE001 — degrade the section, not the report
            logger.warning("report %s section '%s' failed: %s", job.id, key, exc)
            sections.append(
                contracts.missing_section(
                    _heading(key, locale),
                    f"Section could not be gathered ({type(exc).__name__}); "
                    "shown as missing rather than estimated.",
                )
            )

    field_ids = [f.id for f in fields]
    limitations = [
        "Yield, input costs and profit are not recorded by the platform and "
        "are never estimated in this report.",
        "Irrigation volumes are not metered platform-wide; water figures "
        "derive from precipitation observations only.",
        "PDF v1 contains no charts — tables and key figures only.",
        "This report summarizes platform data; it is not an agronomic or "
        "financial certification.",
    ]
    if locale == "ar":
        limitations.append(
            "v1 يترجم عناوين التقرير والأقسام؛ تظل رؤوس أعمدة الجداول "
            "بأسمائها الإنجليزية الآلية."
        )

    return {
        "title": spec.title_ar if locale == "ar" else spec.title_en,
        "report_type": spec.key,
        "primary_section": spec.primary_section,
        "report_generation_version": REPORT_GENERATION_VERSION,
        "org_name": organization.name if organization else "",
        "farm_name": farm.name if farm else None,
        "generated_at": now.isoformat(),
        "date_range": {"from": job.date_from.isoformat(), "to": job.date_to.isoformat()},
        "sections": sections,
        "provenance_legend": list(renderers.DEFAULT_LEGEND),
        "assumptions": [
            "Water volumes derive from precipitation observations × registered "
            "field area (1 mm over 1 ha = 10 m³); effective rainfall is NOT deducted.",
            "Period filters use observation timestamps compared in UTC.",
            "Field areas are the user-registered geometry areas, not surveyed values.",
        ],
        "limitations": limitations,
        "sources": [
            "observations — data-platform provider ingests",
            "crop_history — farmer records",
            "AI recommendations — platform engines (rules / rules+llm)",
            "water plans — seasonal water intelligence snapshots",
            "soil measurements — laboratory and farmer-reported samples",
        ] + ([f"fields in scope: {len(field_ids)}"] if field_ids else []),
        "rendering_notes": [],
    }


def _scope_fields(
    session: Session,
    farm: Farm | None,
    organization_id: uuid.UUID,
    field_id: uuid.UUID | None = None,
) -> list[Field]:
    stmt = select(Field).join(Farm, Field.farm_id == Farm.id)
    stmt = stmt.where(Farm.organization_id == organization_id)
    if field_id is not None:
        # Defense in depth: stored selectors must remain in the report org.
        stmt = stmt.where(Field.id == field_id)
        if farm is not None:
            stmt = stmt.where(Field.farm_id == farm.id)
    elif farm is not None:
        stmt = stmt.where(Field.farm_id == farm.id)
    else:
        stmt = stmt.where(Farm.organization_id == organization_id)
    return list(session.scalars(stmt.order_by(Farm.name, Field.name)).all())


def _overview_section(
    job: ReportJob,
    spec: contracts.ReportTypeSpec,
    farm: Farm | None,
    fields: list[Field],
    farm_count: int | None = None,
) -> dict[str, Any]:
    locale = job.locale
    total_area = round(sum(f.area_ha for f in fields), 2) if fields else None
    period_days = (job.date_to - job.date_from).days + 1
    return contracts.make_section(
        _heading("overview", locale),
        prose=spec.description,
        kpis=[
            contracts.make_kpi(
                "Farms in scope",
                1 if farm is not None else farm_count,
                "count", PROVENANCE_OBSERVED,
                note="Farm-scoped report." if farm is not None else
                "Organization-scoped report (all farms).",
            ),
            contracts.make_kpi(
                "Fields in scope", len(fields) or None, "count", PROVENANCE_OBSERVED
            ),
            contracts.make_kpi(
                "Total area", total_area, "ha", PROVENANCE_OBSERVED,
                note="Sum of registered field areas.",
            ),
            contracts.make_kpi(
                "Period length", period_days, "days", PROVENANCE_OBSERVED
            ),
        ],
        provenance=PROVENANCE_OBSERVED,
    )


def _field_breakdown_section(
    session: Session, fields: list[Field], date_from: date, date_to: date, locale: str
) -> dict[str, Any]:
    start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
    end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC)
    rows: list[list[Any]] = []
    for field in fields:
        obs = int(
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(
                    Observation.field_id == field.id,
                    Observation.observed_at >= start,
                    Observation.observed_at <= end,
                )
            ) or 0
        )
        recs = int(
            session.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(
                    AIRecommendation.field_id == field.id,
                    AIRecommendation.status == "active",
                )
            ) or 0
        )
        cycles = int(
            session.scalar(
                select(func.count())
                .select_from(CropHistory)
                .where(
                    CropHistory.field_id == field.id,
                    CropHistory.sowing_date >= date_from,
                    CropHistory.sowing_date <= date_to,
                )
            ) or 0
        )
        rows.append([field.name, round(field.area_ha, 2), obs, recs, cycles])
    return contracts.make_section(
        _heading("field_breakdown", locale),
        prose="Per-field activity counts for the selected period.",
        table=contracts.make_table(
            ["Field", "Area", "Observations", "Active recommendations", "Crop cycles"],
            rows,
            units=[None, "ha", "count", "count", "count"],
        ),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "No fields in scope.",
    )


def _water_section(
    session: Session, fields: list[Field], date_from: date, date_to: date, locale: str
) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
    end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC)
    area_by_field = {f.id: f for f in fields}
    field_names = {f.id: f.name for f in fields}

    plan_rows: list[list[Any]] = []
    if field_ids:
        plans = list(
            session.scalars(
                select(WaterPlan)
                .where(
                    WaterPlan.field_id.in_(field_ids),
                    WaterPlan.created_at >= start,
                    WaterPlan.created_at <= end,
                )
                .order_by(WaterPlan.created_at.desc())
                .limit(SECTION_ROW_CAP)
            ).all()
        )
        for plan in plans:
            plan_rows.append([
                field_names.get(plan.field_id, str(plan.field_id)),
                plan.label,
                plan.status,
                len(plan.seasons or []),
                plan.water_allocation_m3,
                plan.created_at.date().isoformat() if plan.created_at else None,
            ])

    # Precipitation-derived volumes (same formula as app.analytics: honest,
    # model_derived, effective rainfall NOT deducted).
    volume_m3: float | None = None
    if field_ids:
        precip = session.execute(
            select(Observation.field_id, func.sum(Observation.value))
            .where(
                Observation.field_id.in_(field_ids),
                Observation.variable_code == "precipitation",
                Observation.unit.in_(("mm", "kg/m^2")),
                Observation.observed_at >= start,
                Observation.observed_at <= end,
            )
            .group_by(Observation.field_id)
        ).all()
        total = 0.0
        for field_id, mm_sum in precip:
            if mm_sum is None or field_id not in area_by_field:
                continue
            total += float(mm_sum) * 10.0 * area_by_field[field_id].area_ha
        volume_m3 = round(total, 1) if precip else None

    has_plans = bool(plan_rows)
    return contracts.make_section(
        _heading("water", locale),
        prose=(
            "Water plans created in the period and precipitation-derived "
            "volumes. Irrigation metering is not implemented platform-wide."
        ),
        table=contracts.make_table(
            ["Field", "Plan", "Status", "Seasons", "Allocation", "Created"],
            plan_rows,
            units=[None, None, None, "count", "m3", None],
        )
        if plan_rows
        else None,
        kpis=[
            contracts.make_kpi(
                "Precipitation volume (model-derived)", volume_m3, "m3", PROVENANCE_MODEL,
                note="1 mm over 1 ha = 10 m³; effective rainfall NOT deducted.",
            ),
            contracts.make_kpi(
                "Irrigation volume", None, "m3", PROVENANCE_MISSING,
                note="Irrigation is not metered by the platform yet.",
            ),
        ],
        provenance=PROVENANCE_MODEL if volume_m3 is not None or has_plans else PROVENANCE_MISSING,
        note=None if (volume_m3 is not None or has_plans) else
        "No water plans and no precipitation observations in this period.",
    )


def _soil_section(session: Session, fields: list[Field], locale: str) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    rows: list[list[Any]] = []
    if field_ids:
        measured = session.execute(
            select(
                SoilMeasurement.variable_code,
                SoilMeasurement.unit,
                func.count(),
                func.avg(SoilMeasurement.value),
                func.min(SoilMeasurement.value),
                func.max(SoilMeasurement.value),
                func.max(SoilMeasurement.observed_at),
            )
            .where(
                SoilMeasurement.field_id.in_(field_ids),
                SoilMeasurement.value.is_not(None),
            )
            .group_by(SoilMeasurement.variable_code, SoilMeasurement.unit)
            .order_by(SoilMeasurement.variable_code)
        ).all()
        for variable, unit, count, avg, lo, hi, latest in measured:
            rows.append([
                variable,
                int(count),
                round(float(avg), 3) if avg is not None else None,
                round(float(lo), 3) if lo is not None else None,
                round(float(hi), 3) if hi is not None else None,
                unit,
                latest.isoformat() if latest else None,
            ])
    return contracts.make_section(
        _heading("soil", locale),
        prose="Aggregated laboratory/farmer-reported soil measurements for the scope.",
        table=contracts.make_table(
            ["Variable", "Measurements", "Mean", "Min", "Max", "Unit", "Latest"],
            rows,
            units=[None, "count", None, None, None, None, None],
        ),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else
        "No soil measurements recorded for this scope. Import laboratory "
        "results or connect a soil provider to populate this section.",
    )


def _recommendations_section(
    session: Session, fields: list[Field], locale: str
) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    rows: list[list[Any]] = []
    truncated = 0
    if field_ids:
        field_names = {f.id: f.name for f in fields}
        recs = list(
            session.scalars(
                select(AIRecommendation)
                .where(
                    AIRecommendation.field_id.in_(field_ids),
                    AIRecommendation.status == "active",
                )
                .order_by(
                    AIRecommendation.severity.desc(),
                    AIRecommendation.created_at.desc(),
                )
            ).all()
        )
        truncated = max(0, len(recs) - SECTION_ROW_CAP)
        for rec in recs[:SECTION_ROW_CAP]:
            rows.append([
                field_names.get(rec.field_id, str(rec.field_id)),
                rec.domain,
                rec.severity,
                rec.title,
                rec.confidence,
                rec.generated_by,
                rec.created_at.date().isoformat() if rec.created_at else None,
            ])
    return contracts.make_section(
        _heading("recommendations", locale),
        prose=(
            "Active AI recommendations. Recommendation content is "
            "model-generated; confidence is the engine's own estimate."
        ),
        table=contracts.make_table(
            ["Field", "Domain", "Severity", "Title", "Confidence", "Engine", "Created"],
            rows,
            units=[None, None, None, None, None, None, None],
        ),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=(
            (f"{truncated} further rows omitted ({SECTION_ROW_CAP} row cap). " if truncated else "")
            + ("" if rows else "No active recommendations for this scope.")
        ),
    )


def _crop_cycles_section(
    session: Session, fields: list[Field], date_from: date, date_to: date, locale: str
) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    rows: list[list[Any]] = []
    if field_ids:
        field_names = {f.id: f.name for f in fields}
        cycles = list(
            session.scalars(
                select(CropHistory)
                .where(
                    CropHistory.field_id.in_(field_ids),
                    CropHistory.sowing_date.is_not(None),
                    CropHistory.sowing_date <= date_to,
                    (
                        CropHistory.harvest_date.is_(None)
                        | (CropHistory.harvest_date >= date_from)
                    ),
                )
                .order_by(CropHistory.sowing_date.desc())
                .limit(SECTION_ROW_CAP)
            ).all()
        )
        for cycle in cycles:
            rows.append([
                field_names.get(cycle.field_id, str(cycle.field_id)),
                cycle.crop_label,
                cycle.season_label,
                cycle.sowing_date.isoformat() if cycle.sowing_date else None,
                cycle.harvest_date.isoformat() if cycle.harvest_date else None,
                cycle.source,
            ])
    return contracts.make_section(
        _heading("crop_cycles", locale),
        prose="Crop cycles recorded by farmers, active or harvested within the period.",
        table=contracts.make_table(
            ["Field", "Crop", "Season", "Sowing", "Harvest", "Source"],
            rows,
        ),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "No crop cycles recorded in this period.",
    )


def _seasonality_section(
    session: Session, fields: list[Field], date_from: date, date_to: date, locale: str
) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
    end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC)
    rows: list[list[Any]] = []
    if field_ids:
        month = func.date_trunc("month", Observation.observed_at).label("month")
        grouped = session.execute(
            select(
                month,
                Observation.variable_code,
                Observation.unit,
                func.count(),
                func.sum(Observation.value),
                func.avg(Observation.value),
            )
            .where(
                Observation.field_id.in_(field_ids),
                Observation.value.is_not(None),
                Observation.observed_at >= start,
                Observation.observed_at <= end,
            )
            .group_by(month, Observation.variable_code, Observation.unit)
            .order_by(month, Observation.variable_code)
        ).all()
        for month_dt, variable, unit, count, total, avg in grouped:
            rows.append([
                month_dt.strftime("%Y-%m") if month_dt is not None else None,
                variable,
                int(count),
                round(float(total), 2) if total is not None else None,
                round(float(avg), 3) if avg is not None else None,
                unit,
            ])
    return contracts.make_section(
        _heading("seasonality", locale),
        prose="Monthly observation totals per variable across the period.",
        table=contracts.make_table(
            ["Month", "Variable", "Observations", "Sum", "Mean", "Unit"],
            rows,
            units=[None, None, "count", None, None, None],
        ),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "No observations ingested in this period.",
    )


def _risk_section(session: Session, fields: list[Field], locale: str) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    rows: list[list[Any]] = []
    synthetic_total = total = 0
    if field_ids:
        now = datetime.now(UTC)
        for variable in _VARIABLE_FAMILY:
            count = int(
                session.scalar(
                    select(func.count())
                    .select_from(Observation)
                    .where(
                        Observation.field_id.in_(field_ids),
                        Observation.variable_code == variable,
                    )
                ) or 0
            )
            last = session.scalar(
                select(func.max(Observation.observed_at)).where(
                    Observation.field_id.in_(field_ids),
                    Observation.variable_code == variable,
                )
            )
            if count == 0 or last is None:
                rows.append([variable, 0, None, None, "missing"])
                continue
            age_days = round((now - last).total_seconds() / 86400, 1)
            status = "fresh" if age_days <= 3 else ("stale" if age_days <= 14 else "very_stale")
            rows.append([variable, count, last.date().isoformat(), age_days, status])
        total = int(
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.field_id.in_(field_ids))
            ) or 0
        )
        synthetic_total = int(
            session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(
                    Observation.field_id.in_(field_ids),
                    Observation.is_synthetic.is_(True),
                )
            ) or 0
        )
    synthetic_share = round(synthetic_total / total, 4) if total else None
    return contracts.make_section(
        _heading("risk", locale),
        prose=(
            "Data-driven exposure view: how fresh and how complete the "
            "underlying observations are. NOT an agronomic risk assessment."
        ),
        table=contracts.make_table(
            ["Variable", "Observations", "Last observed", "Age (days)", "Status"],
            rows,
            units=[None, "count", None, "days", None],
        ),
        kpis=[
            contracts.make_kpi(
                "Synthetic observation share", synthetic_share, "ratio", PROVENANCE_MODEL,
                note="Fraction of observations flagged synthetic in the scope.",
            ),
        ],
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "No observations in scope.",
    )


def _data_quality_section(
    session: Session, fields: list[Field], date_from: date, date_to: date, locale: str
) -> dict[str, Any]:
    field_ids = [f.id for f in fields]
    start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
    end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC)
    rows: list[list[Any]] = []
    if field_ids:
        grouped = session.execute(
            select(Observation.quality_status, func.count())
            .where(
                Observation.field_id.in_(field_ids),
                Observation.observed_at >= start,
                Observation.observed_at <= end,
            )
            .group_by(Observation.quality_status)
        ).all()
        rows = [[status, int(count)] for status, count in grouped]
    return contracts.make_section(
        _heading("data_quality", locale),
        prose="Observation counts by recorded quality status within the period.",
        table=contracts.make_table(["Quality status", "Observations"], rows, units=[None, "count"]),
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "No observations ingested in this period.",
    )


# ------------------------------------------------------------------ queries
def get_report_job(session: Session, principal: Principal, job_id: uuid.UUID) -> ReportJob:
    """Tenant-safe single fetch (any active member, viewer+)."""
    job = session.get(ReportJob, job_id)
    if job is None:
        raise NotFound("Report job not found.")
    principal.require_org_role(job.organization_id, "viewer")
    return job


def list_report_jobs(
    session: Session,
    principal: Principal,
    *,
    status: str | None = None,
    report_type: str | None = None,
    farm_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ReportJob], int]:
    """Org-scoped library listing, newest first, with hard limits."""
    org_ids = principal.org_ids()
    if not org_ids:
        return [], 0
    if status is not None and status not in contracts.REPORT_STATUSES:
        raise ValidationFailed(
            f"Unknown status '{status}'.",
            details=[{"field": "status", "reason": list(contracts.REPORT_STATUSES)}],
        )
    if report_type is not None and report_type not in contracts.REPORT_TYPES:
        raise ValidationFailed(
            f"Unknown report type '{report_type}'.",
            details=[{"field": "report_type", "reason": sorted(contracts.REPORT_TYPES)}],
        )
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conditions = [ReportJob.organization_id.in_(org_ids)]
    if status is not None:
        conditions.append(ReportJob.status == status)
    if report_type is not None:
        conditions.append(ReportJob.report_type == report_type)
    if farm_id is not None:
        conditions.append(ReportJob.farm_id == farm_id)
    total = int(
        session.scalar(select(func.count()).select_from(ReportJob).where(*conditions)) or 0
    )
    rows = list(
        session.scalars(
            select(ReportJob)
            .where(*conditions)
            .order_by(ReportJob.created_at.desc(), ReportJob.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


# ------------------------------------------------------------------ download
def read_report_file(session: Session, principal: Principal, job_id: uuid.UUID) -> Path | bytes:
    """Read a report artifact after the authenticated tenant check.

    PostgreSQL mode returns durable bytes from the shared artifact table;
    local mode retains the historical traversal-safe Path contract.
    """
    job = get_report_job(session, principal, job_id)
    if job.status != contracts.REPORT_STATUS_SUCCEEDED or not job.file_path:
        raise NotFound("Report artifact is not available for this job.")
    now = datetime.now(UTC)
    if job.retention_until is not None and job.retention_until <= now:
        raise NotFound("Report artifact has expired and is no longer downloadable.")
    if _reports_backend() == "postgres":
        if job.file_path != _report_artifact_key(job):
            raise NotFound("Report artifact is not available for this job.")
        try:
            return PostgresStorage().read_bytes(job.file_path)
        except (ArtifactNotFoundError, ArtifactStorageError) as exc:
            raise NotFound("Report artifact is not available for this job.") from exc
    base = Path(settings.reports_dir).resolve()
    candidate = Path(job.file_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        candidate = candidate.resolve()
    except OSError as exc:  # pragma: no cover — defensive
        raise NotFound("Report artifact path could not be resolved.") from exc
    if candidate.parent != base or candidate.stem != str(job.id):
        raise NotFound("Report artifact path is invalid.")
    if not candidate.is_file():
        raise NotFound("Report artifact file is missing from storage.")
    return candidate


# ------------------------------------------------------------------ delete
def delete_report_job(session: Session, principal: Principal, job_id: uuid.UUID) -> None:
    """Manager+ deletion: removes the artifact and the library row."""
    job = session.get(ReportJob, job_id)
    if job is None:
        raise NotFound("Report job not found.")
    principal.require_org_role(job.organization_id, "manager")
    if job.file_path:
        if _reports_backend() == "postgres":
            try:
                if job.file_path == _report_artifact_key(job):
                    PostgresStorage().delete(job.file_path)
            except (ArtifactNotFoundError, ArtifactStorageError):
                logger.warning("could not delete durable artifact for report %s", job.id)
        else:
            try:
                path = Path(job.file_path)
                if path.is_file() and Path(settings.reports_dir).resolve() in path.resolve().parents:
                    path.unlink()
            except OSError:  # pragma: no cover — storage hiccup must not block
                logger.warning("could not delete artifact for report %s", job.id)
    session.delete(job)
    session.commit()


# ----------------------------------------------------------------- retention
def purge_expired_reports(session: Session, now: datetime | None = None) -> int:
    """Retention sweep: expired artifacts lose their file and the job row is
    marked ``expired`` (kept as a library stub). Returns rows transitioned."""
    now = now or datetime.now(UTC)
    due = list(
        session.scalars(
            select(ReportJob).where(
                ReportJob.status.in_(
                    (contracts.REPORT_STATUS_SUCCEEDED, contracts.REPORT_STATUS_FAILED)
                ),
                ReportJob.retention_until.is_not(None),
                ReportJob.retention_until <= now,
            )
        ).all()
    )
    # Rows that never got a retention stamp (e.g. written by older code):
    # terminal and older than the default window are also purge-eligible.
    threshold = now - timedelta(days=contracts.REPORT_RETENTION_DAYS_DEFAULT)
    unstamped = list(
        session.scalars(
            select(ReportJob).where(
                ReportJob.status.in_(
                    (contracts.REPORT_STATUS_SUCCEEDED, contracts.REPORT_STATUS_FAILED)
                ),
                ReportJob.retention_until.is_(None),
                ReportJob.updated_at <= threshold,
            )
        ).all()
    )
    purged = 0
    for job in due + unstamped:
        if job.file_path:
            if _reports_backend() == "postgres":
                try:
                    if job.file_path == _report_artifact_key(job):
                        PostgresStorage().delete(job.file_path)
                except (ArtifactNotFoundError, ArtifactStorageError):
                    logger.warning("retention sweep could not delete durable artifact for report %s", job.id)
            else:
                try:
                    base = Path(settings.reports_dir).resolve()
                    path = Path(job.file_path)
                    if path.is_file() and base in path.resolve().parents:
                        path.unlink()
                except OSError:  # pragma: no cover
                    logger.warning("retention sweep could not delete local report artifact")
        job.file_path = None
        job.file_size_bytes = None
        job.status = contracts.REPORT_STATUS_EXPIRED
        purged += 1
    if purged:
        session.commit()
    return purged


# ----------------------------------------------------------------- schedule
def set_report_schedule(
    session: Session,
    principal: Principal,
    job_id: uuid.UUID,
    *,
    interval_days: int | None,
) -> ReportJob:
    """Attach (or clear) a recurrence on a report template (manager+).

    Setting an interval arms ``next_run_at`` = now + interval; clearing
    (``interval_days=None``) makes the job one-off again.
    """
    job = session.get(ReportJob, job_id)
    if job is None:
        raise NotFound("Report job not found.")
    principal.require_org_role(job.organization_id, "manager")
    if interval_days is not None:
        if (
            interval_days < contracts.MIN_INTERVAL_DAYS
            or interval_days > contracts.MAX_INTERVAL_DAYS
        ):
            raise ValidationFailed(
                f"interval_days must be between {contracts.MIN_INTERVAL_DAYS} "
                f"and {contracts.MAX_INTERVAL_DAYS}.",
                details=[{"field": "interval_days", "reason": interval_days}],
            )
        job.interval_days = interval_days
        job.next_run_at = datetime.now(UTC) + timedelta(days=interval_days)
    else:
        job.interval_days = None
        job.next_run_at = None
    session.commit()
    return job


def advance_recurring(session: Session, now: datetime | None = None) -> list[ReportJob]:
    """Recurring sweep: for every due template job, roll its ``next_run_at``
    forward and enqueue a ONE-OFF copy carrying the next contiguous date
    window. The template keeps the schedule; copies never re-schedule.

    Missed periods are caught up by advancing ``next_run_at`` interval-by-
    interval, but at most ONE catch-up copy is created per template per sweep
    (a delayed worker must not fan out unbounded backfills silently).
    """
    now = now or datetime.now(UTC)
    due = list(
        session.scalars(
            select(ReportJob).where(
                ReportJob.interval_days.is_not(None),
                ReportJob.next_run_at.is_not(None),
                ReportJob.next_run_at <= now,
            )
        ).all()
    )
    created: list[ReportJob] = []
    for template in due:
        interval = max(1, int(template.interval_days or 1))
        window_days = max(1, (template.date_to - template.date_from).days + 1)
        copy = ReportJob(
            organization_id=template.organization_id,
            farm_id=template.farm_id,
            requested_by=template.requested_by,
            report_type=template.report_type,
            output_format=template.output_format,
            locale=template.locale,
            # Rolling contiguous window immediately after the previous one.
            date_from=template.date_to + timedelta(days=1),
            date_to=template.date_to + timedelta(days=window_days),
            status=contracts.REPORT_STATUS_QUEUED,
            interval_days=None,
            next_run_at=None,
        )
        session.add(copy)
        # Catch-up: advance past every missed period without fanning out.
        next_run = template.next_run_at
        while next_run is not None and next_run <= now:
            next_run = next_run + timedelta(days=interval)
        template.next_run_at = next_run
        activity.record_event(
            session,
            organization_id=template.organization_id,
            event_type=activity.EVENT_REPORT_CREATED,
            summary=f"Recurring report '{template.report_type}' re-enqueued.",
            farm_id=template.farm_id,
            actor_user_id=template.requested_by,
            entity_kind="report_job",
            entity_id=str(copy.id),
            details={
                "template_job_id": str(template.id),
                "interval_days": interval,
                "report_type": template.report_type,
            },
        )
        created.append(copy)
    if created:
        session.commit()
    return created


__all__ = [
    "advance_recurring",
    "create_report_job",
    "delete_report_job",
    "execute_report_job",
    "get_report_job",
    "job_payload",
    "list_report_jobs",
    "purge_expired_reports",
    "read_report_file",
    "set_report_schedule",
]


# ==================================================== P07 section builders ==
# Every builder follows the P3 honesty contract: sections degrade to
# provenance="missing" with a note when their data does not exist; no
# section fabricates values, and satellite/spatial rows always carry the
# provenance written by the processing pipeline.


def _data_availability_section(
    session: Session,
    fields: list[Field],
    date_from: date,
    date_to: date,
    locale: str,
) -> dict[str, Any]:
    """Observation coverage + missing periods per variable (honest gaps)."""
    from app.db.models import Observation

    rows: list[list[Any]] = []
    kpis: list[dict[str, Any]] = []
    for field in fields[:20]:
        var_rows = session.execute(
            select(Observation.variable_code, func.count(), func.min(Observation.observed_at), func.max(Observation.observed_at))
            .where(Observation.field_id == field.id)
            .group_by(Observation.variable_code)
        ).all()
        if not var_rows:
            rows.append([field.name, "—", 0, "", "", "no observations ingested"])
            continue
        for variable_code, count, first, last in var_rows:
            rows.append(
                [
                    field.name,
                    variable_code,
                    int(count),
                    first.date().isoformat() if first else "",
                    last.date().isoformat() if last else "",
                    "",
                ]
            )
        kpis.append(
            contracts.make_kpi(
                f"{field.name} variables", len(var_rows), "variables", PROVENANCE_OBSERVED
            )
        )
    return contracts.make_section(
        _heading("data_availability", locale),
        prose=(
            "Observation coverage by variable over the full record (not only "
            "the report window). Missing periods are shown as gaps; the "
            "platform does not interpolate missing satellite observations."
        ),
        table=contracts.make_table(
            ["Field", "Variable", "Observations", "First", "Latest", "Note"],
            rows,
        ),
        kpis=kpis[:6],
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "no observations in scope",
    )


def _satellite_section(
    session: Session, fields: list[Field], locale: str
) -> dict[str, Any]:
    """Satellite acquisition history + index statistics with provenance."""
    from app.db.models import Observation
    from app.db.models_p2 import SatelliteScene

    rows: list[list[Any]] = []
    scenes = session.scalars(
        select(SatelliteScene)
        .where(SatelliteScene.field_id.in_([f.id for f in fields[:20]]))
        .order_by(SatelliteScene.acquired_at.desc())
        .limit(60)
    ).all()
    for scene in scenes:
        field_name = next((f.name for f in fields if f.id == scene.field_id), "")
        rows.append(
            [
                field_name,
                scene.scene_id,
                scene.provider_code,
                scene.product_code,
                scene.acquired_at.date().isoformat() if scene.acquired_at else "",
                "" if scene.cloud_cover_pct is None else scene.cloud_cover_pct,
                "" if scene.spatial_resolution_m is None else scene.spatial_resolution_m,
                scene.acquisition_status,
                "yes" if scene.is_synthetic else "no",
            ]
        )

    index_rows: list[list[Any]] = []
    for field in fields[:20]:
        obs = session.scalars(
            select(Observation)
            .where(Observation.field_id == field.id)
            .where(Observation.variable_code.in_(["ndvi", "evi", "ndmi", "ndwi", "bsi"]))
            .where(Observation.value.is_not(None))
            .order_by(Observation.observed_at.desc())
            .limit(40)
        ).all()
        for obs in obs:
            meta = obs.metadata or {}
            zonal = meta.get("zonal") or {}
            index_rows.append(
                [
                    field.name,
                    obs.variable_code,
                    obs.observed_at.date().isoformat() if obs.observed_at else "",
                    round(float(obs.value), 4),
                    "" if obs.processing_version is None else obs.processing_version,
                    "" if meta.get("cloud_cover_pct") is None else meta["cloud_cover_pct"],
                    "" if zonal.get("valid_pixels") is None else zonal["valid_pixels"],
                    obs.evidence_class or "",
                ]
            )

    note = (
        "Index values are field-mean spectral statistics produced by the "
        "CRS-correct preprocessing pipeline (windowed reads, HLS scaling, "
        "Fmask cloud/shadow/snow exclusion). They are measurements, not "
        "diagnoses of crop condition."
    )
    return _two_table_section(
        _heading("satellite", locale),
        note,
        scenes_table=contracts.make_table(
            ["Field", "Scene", "Provider", "Product", "Acquired", "Cloud %", "Res (m)", "Acquisition", "Synthetic"],
            rows,
            units=[None, None, None, None, None, "%", "m", None, None],
        ),
        index_table=contracts.make_table(
            ["Field", "Index", "Date", "Mean", "Processing version", "Cloud %", "Valid px", "Evidence class"],
            index_rows,
            units=[None, None, None, None, None, "%", "px", None],
        ),
        scenes_present=bool(rows),
        indices_present=bool(index_rows),
        locale=locale,
    )


def _two_table_section(
    heading: str,
    prose: str,
    *,
    scenes_table: dict[str, Any] | None,
    index_table: dict[str, Any] | None,
    scenes_present: bool,
    indices_present: bool,
    locale: str,
) -> dict[str, Any]:
    """Satellite section carrying both the scene ledger and index table.

    The normalized section schema supports one table; the index table is
    the primary CSV surface, so it takes the table slot and the scene
    ledger is serialized into the prose-free `note` as a compact summary
    when present (never fabricated).
    """
    if not scenes_present and not indices_present:
        return contracts.missing_section(
            heading, "no satellite scenes or derived index observations in scope"
        )
    extra = ""
    if scenes_present and scenes_table:
        # columns: Field, Scene, Provider, Product, Acquired, ...
        ledger = [
            f"{row[1]} {row[3]} {row[4]}".strip()
            for row in scenes_table["rows"][:10]
        ]
        extra = f" Recent scenes: {'; '.join(ledger)}."
    return contracts.make_section(
        heading,
        prose=prose + extra,
        table=index_table if indices_present else None,
        kpis=[],
        provenance=PROVENANCE_OBSERVED if (indices_present or scenes_present) else PROVENANCE_MISSING,
        note=(
            "Full scene ledger rows: "
            + str(len(scenes_table["rows"]) if scenes_table else 0)
            + " (bounded to the 60 most recent)."
            if scenes_present
            else None
        ),
    )


def _spatial_section(session: Session, fields: list[Field], locale: str) -> dict[str, Any]:
    """Spatial variation, statistical zones and gated anomaly signals."""
    from app.geospatial.spatial_analytics import detect_spatial_anomalies

    rows: list[list[Any]] = []
    notes: list[str] = []
    anomaly_count = 0
    for field in fields[:20]:
        result = detect_spatial_anomalies(session, field, index_code="ndvi")
        for anomaly in result.get("anomalies", []):
            anomaly_count += 1
            rows.append(
                [
                    field.name,
                    anomaly["type"],
                    anomaly["severity"],
                    anomaly.get("confidence"),
                    anomaly.get("observed_at") or "",
                    anomaly.get("spatial_resolution_m") or "",
                    anomaly.get("valid_pixel_fraction") or "",
                    anomaly.get("scene_id") or "",
                    "; ".join(anomaly.get("reasons", []))[:180],
                ]
            )
        for reason in result.get("insufficient_evidence", []):
            notes.append(f"{field.name}: {reason}")
    if not rows:
        prose = (
            "No anomaly signals passed the quality gates for this scope. "
            "Failed gates are listed below — the report does not lower "
            "thresholds to produce findings."
        )
    else:
        prose = (
            "Signals passed explicit minimum-sample, coverage, freshness and "
            "baseline gates. Signals are NOT diagnoses: disease, pest, "
            "nutrient-deficiency or irrigation-failure claims require "
            "independent evidence."
        )
    if notes:
        prose += " Insufficient evidence: " + "; ".join(notes[:8]) + "."
    return contracts.make_section(
        _heading("spatial", locale),
        prose=prose,
        table=contracts.make_table(
            ["Field", "Signal", "Severity", "Confidence", "Observed", "Res (m)", "Valid px frac", "Scene", "Reasons"],
            rows,
        )
        if rows
        else None,
        kpis=[contracts.make_kpi("signals emitted", anomaly_count, "signals", PROVENANCE_OBSERVED)] if rows or not notes else [],
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=(
            "Statistical tercile zones are data-description strata, not "
            "agronomic management zones."
        ),
    )


def _environmental_section(
    session: Session,
    fields: list[Field],
    date_from: date,
    date_to: date,
    locale: str,
) -> dict[str, Any]:
    """Environmental observation summary for the report window (real data)."""
    from app.db.models import Observation

    start_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(date_to, datetime.max.time(), tzinfo=UTC)
    variables = ("precipitation", "soil_moisture_surface", "air_temperature_mean", "air_temperature_max", "air_temperature_min", "reference_et0")
    rows: list[list[Any]] = []
    for field in fields[:20]:
        stats = session.execute(
            select(
                Observation.variable_code,
                func.count(Observation.id),
                func.sum(Observation.value),
                func.avg(Observation.value),
                func.max(Observation.observed_at),
            )
            .where(
                Observation.field_id == field.id,
                Observation.variable_code.in_(variables),
                Observation.observed_at >= start_dt,
                Observation.observed_at <= end_dt,
                Observation.value.is_not(None),
            )
            .group_by(Observation.variable_code)
        ).all()
        for variable_code, count, total, avg, last in stats:
            rows.append(
                [
                    field.name,
                    variable_code,
                    int(count),
                    round(float(total), 2) if total is not None and variable_code in ("precipitation", "reference_et0") else "",
                    round(float(avg), 3) if avg is not None and variable_code not in ("precipitation", "reference_et0") else "",
                    last.date().isoformat() if last else "",
                ]
            )
    return contracts.make_section(
        _heading("environmental", locale),
        prose=(
            "Real ingested observations for the report window only. Variables "
            "with no provider ingestion for this field are absent — they are "
            "never estimated. ECOSTRESS land-surface temperature and terrain "
            "elevation/slope have no ingestion pipeline in the platform yet."
        ),
        table=contracts.make_table(
            ["Field", "Variable", "Days", "Sum", "Mean", "Latest"],
            rows,
            units=[None, None, "d", None, None, None],
        )
        if rows
        else None,
        kpis=[],
        provenance=PROVENANCE_OBSERVED if rows else PROVENANCE_MISSING,
        note=None if rows else "no environmental observations in the report window",
    )


def _methodology_section(session: Session, fields: list[Field], locale: str) -> dict[str, Any]:
    """Methodology + source appendix (reproducibility metadata)."""
    from app.geospatial.preprocessing import PROCESSING_SOFTWARE_VERSION
    from app.vegetation.indices import INDEX_FORMULAS
    from app.vegetation.field_profile import PROFILE_VERSION
    from app.geospatial.spatial_analytics import SPATIAL_ANALYTICS_VERSION

    formula_rows = [
        [code, formula, "documented valid range normalized colormap"]
        for code, formula in INDEX_FORMULAS.items()
    ]
    return contracts.make_section(
        _heading("methodology", locale),
        prose=(
            "Reproducibility appendix. Satellite products are derived with "
            "windowed COG reads, HLS surface-reflectance scaling (DN x "
            "0.0001) and Fmask exclusion of cloud/cirrus/shadow/snow pixels; "
            "nodata is never rendered as zero. Zonal statistics are "
            "pixel-centre masked and tercile zones are rank-based statistical "
            "strata — not agronomic zones. Anomaly signals are threshold-"
            "gated (baseline >= 3 observations, freshness <= 45 days, valid "
            "pixels >= 5, coverage >= 0.4, |z| >= 1.5 for decline) and carry "
            "machine-readable reasons."
        ),
        table=contracts.make_table(
            ["Index", "Formula", "Rendering"],
            formula_rows,
        ),
        kpis=[
            contracts.make_kpi("processing software version", PROCESSING_SOFTWARE_VERSION, "version", PROVENANCE_MODEL),
            contracts.make_kpi("field profile version", PROFILE_VERSION, "version", PROVENANCE_MODEL),
            contracts.make_kpi("spatial analytics version", SPATIAL_ANALYTICS_VERSION, "version", PROVENANCE_MODEL),
            contracts.make_kpi("report generation version", REPORT_GENERATION_VERSION, "version", PROVENANCE_MODEL),
        ],
        provenance=PROVENANCE_MODEL,
        note=(
            "Data sources: NASA HLS (HLSL30/HLSS30) via NASA LP DAAC CMR "
            "STAC; environmental observations from registered data-platform "
            "providers; crop history and recommendations from platform "
            "engines. No LLM participates in any calculation in this report."
        ),
    )

"""Versioned read-only public API (P3 W6) — ``/public/v1``.

Auth: ``require_api_key`` dependency with per-route scopes. EVERY query is
scoped by the key's ``organization_id`` — that value never comes from the
client; this is the tenant isolation boundary. Pagination shape is
``{items, total, limit, offset}`` (limit <= 100, default 25).

``X-Request-Id`` is added to every response (including structured errors) by
the app-wide request-id middleware in ``app/main.py`` — no per-route work
needed. Registration in router.py is done by the integrator.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import service as analytics_service
from app.core.database import get_db
from app.core.errors import InvalidDateRange, NotFound, ValidationFailed
from app.db.models import CropHistory, Farm, Field, Observation, Organization
from app.db.models_ai import AIRecommendation
from app.db.models_p3 import ReportJob
from app.domains.identity.service import get_principal  # noqa: F401 (route style parity)
from app.publicapi.api_keys import ApiKeyPrincipal, require_api_key

router = APIRouter(prefix="/public/v1", tags=["public-api"])

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_ENV_RANGE_DAYS = 366


def _pagination(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(int(limit), MAX_PAGE_SIZE)), max(0, int(offset))


def _page(items: list[dict[str, Any]], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# --------------------------------------------------------------- org:read
@router.get("/org")
def get_org(
    key: ApiKeyPrincipal = Depends(require_api_key("org:read")),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, key.organization_id)
    if org is None:  # pragma: no cover — key org deleted ⇒ cascade would kill keys
        raise NotFound("Organization not found.")
    return {
        "id": str(org.id),
        "name": org.name,
        "type": org.organization_type,
        "country_code": org.country_code,
    }


# ------------------------------------------------------------- farms:read
@router.get("/farms")
def list_public_farms(
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    key: ApiKeyPrincipal = Depends(require_api_key("farms:read")),
    db: Session = Depends(get_db),
) -> dict:
    limit, offset = _pagination(limit, offset)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(Farm)
            .where(Farm.organization_id == key.organization_id)
        )
        or 0
    )
    farms = db.scalars(
        select(Farm)
        .where(Farm.organization_id == key.organization_id)
        .order_by(Farm.created_at)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        {
            "id": str(farm.id),
            "name": farm.name,
            "country_code": farm.country_code,
            "admin_region": farm.admin_region,
            "timezone": farm.timezone,
            "currency_code": farm.currency_code,
            "unit_system": farm.unit_system,
            "created_at": farm.created_at.isoformat() if farm.created_at else None,
        }
        for farm in farms
    ]
    return _page(items, total, limit, offset)


def _org_farm(db: Session, key: ApiKeyPrincipal, farm_id: uuid.UUID) -> Farm:
    """Tenant-scoped farm fetch: cross-org ids are 404s (never 403s — do not
    leak existence across tenants)."""
    farm = db.get(Farm, farm_id)
    if farm is None or farm.organization_id != key.organization_id:
        raise NotFound("Farm not found.")
    return farm


@router.get("/farms/{farm_id}")
def get_public_farm(
    farm_id: uuid.UUID,
    key: ApiKeyPrincipal = Depends(require_api_key("farms:read")),
    db: Session = Depends(get_db),
) -> dict:
    farm = _org_farm(db, key, farm_id)
    return {
        "id": str(farm.id),
        "name": farm.name,
        "country_code": farm.country_code,
        "admin_region": farm.admin_region,
        "timezone": farm.timezone,
        "currency_code": farm.currency_code,
        "unit_system": farm.unit_system,
        "preferred_language": farm.preferred_language,
        "created_at": farm.created_at.isoformat() if farm.created_at else None,
    }


# ------------------------------------------------------------ fields:read
def _org_field(db: Session, key: ApiKeyPrincipal, field_id: uuid.UUID) -> Field:
    row = db.execute(
        select(Field)
        .join(Farm, Field.farm_id == Farm.id)
        .where(Field.id == field_id, Farm.organization_id == key.organization_id)
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Field not found.")
    return row


@router.get("/fields")
def list_public_fields(
    farm_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    key: ApiKeyPrincipal = Depends(require_api_key("fields:read")),
    db: Session = Depends(get_db),
) -> dict:
    limit, offset = _pagination(limit, offset)
    conditions = [Farm.organization_id == key.organization_id]
    if farm_id is not None:
        _org_farm(db, key, farm_id)  # 404 when the farm is not ours
        conditions.append(Field.farm_id == farm_id)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(Field)
            .join(Farm, Field.farm_id == Farm.id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(Field)
        .join(Farm, Field.farm_id == Farm.id)
        .where(*conditions)
        .order_by(Field.created_at)
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    items = [
        {
            "id": str(field.id),
            "farm_id": str(field.farm_id),
            "name": field.name,
            "area_ha": float(field.area_ha),
            "status": field.status,
            "created_at": field.created_at.isoformat() if field.created_at else None,
        }
        for field in rows
    ]
    return _page(items, total, limit, offset)


# ------------------------------------------------------------- crops:read
# Crop cycles are represented by CropHistory ("what actually grew on a field"
# — sowing/harvest dates + season label); active cycles have a sowing date and
# no harvest date yet (same definition as the analytics executive dashboard).
def _active_cycle_condition():
    return (CropHistory.sowing_date.is_not(None)) & (CropHistory.harvest_date.is_(None))


@router.get("/crop-cycles")
def list_public_crop_cycles(
    field_id: uuid.UUID | None = None,
    active: bool | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    key: ApiKeyPrincipal = Depends(require_api_key("crops:read")),
    db: Session = Depends(get_db),
) -> dict:
    limit, offset = _pagination(limit, offset)
    conditions = [Farm.organization_id == key.organization_id]
    if field_id is not None:
        _org_field(db, key, field_id)
        conditions.append(CropHistory.field_id == field_id)
    if active is True:
        conditions.append(_active_cycle_condition())
    elif active is False:
        conditions.append(~_active_cycle_condition())
    total = int(
        db.scalar(
            select(func.count())
            .select_from(CropHistory)
            .join(Field, CropHistory.field_id == Field.id)
            .join(Farm, Field.farm_id == Farm.id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(CropHistory)
        .join(Field, CropHistory.field_id == Field.id)
        .join(Farm, Field.farm_id == Farm.id)
        .where(*conditions)
        .order_by(CropHistory.sowing_date.desc().nullslast(), CropHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    items = [
        {
            "id": str(cycle.id),
            "field_id": str(cycle.field_id),
            "crop_id": str(cycle.crop_id) if cycle.crop_id else None,
            "crop_label": cycle.crop_label,
            "variety_id": str(cycle.variety_id) if cycle.variety_id else None,
            "sowing_date": cycle.sowing_date.isoformat() if cycle.sowing_date else None,
            "harvest_date": cycle.harvest_date.isoformat() if cycle.harvest_date else None,
            "season_label": cycle.season_label,
            "area_ha": float(cycle.area_ha) if cycle.area_ha is not None else None,
            "source": cycle.source,
        }
        for cycle in rows
    ]
    return _page(items, total, limit, offset)


# -------------------------------------------------- recommendations:read
@router.get("/recommendations")
def list_public_recommendations(
    farm_id: uuid.UUID | None = None,
    field_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    key: ApiKeyPrincipal = Depends(require_api_key("recommendations:read")),
    db: Session = Depends(get_db),
) -> dict:
    limit, offset = _pagination(limit, offset)
    conditions = [Farm.organization_id == key.organization_id, AIRecommendation.status == "active"]
    if field_id is not None:
        _org_field(db, key, field_id)
        conditions.append(AIRecommendation.field_id == field_id)
    if farm_id is not None:
        _org_farm(db, key, farm_id)
        conditions.append(Field.farm_id == farm_id)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(AIRecommendation)
            .join(Field, AIRecommendation.field_id == Field.id)
            .join(Farm, Field.farm_id == Farm.id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(AIRecommendation)
        .join(Field, AIRecommendation.field_id == Field.id)
        .join(Farm, Field.farm_id == Farm.id)
        .where(*conditions)
        .order_by(AIRecommendation.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    items = [
        {
            "id": str(rec.id),
            "field_id": str(rec.field_id),
            "domain": rec.domain,
            "severity": rec.severity,
            "title": rec.title,
            "summary": rec.summary,
            "actions": list(rec.actions or []),
            "confidence": rec.confidence,
            "confidence_kind": rec.confidence_kind,
            "status": rec.status,
            "generated_by": rec.generated_by,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        }
        for rec in rows
    ]
    return _page(items, total, limit, offset)


# --------------------------------------------------------- analytics:read
@router.get("/analytics/executive")
def public_executive_dashboard(
    farm_id: uuid.UUID | None = None,
    season: str | None = None,
    key: ApiKeyPrincipal = Depends(require_api_key("analytics:read")),
    db: Session = Depends(get_db),
) -> dict:
    """Reuses the analytics executive dashboard; the ApiKeyPrincipal satisfies
    the service's ``require_member_of`` gate (key org only)."""
    return analytics_service.executive_dashboard(
        db, key, organization_id=key.organization_id, farm_id=farm_id, season=season
    )


# ------------------------------------------------------------ reports:read
@router.get("/reports")
def list_public_reports(
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    key: ApiKeyPrincipal = Depends(require_api_key("reports:read")),
    db: Session = Depends(get_db),
) -> dict:
    """Completed report jobs for the org (metadata only — no file paths)."""
    limit, offset = _pagination(limit, offset)
    conditions = [ReportJob.organization_id == key.organization_id, ReportJob.status == "succeeded"]
    total = int(
        db.scalar(select(func.count()).select_from(ReportJob).where(*conditions)) or 0
    )
    rows = db.scalars(
        select(ReportJob)
        .where(*conditions)
        .order_by(ReportJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        {
            "id": str(job.id),
            "farm_id": str(job.farm_id) if job.farm_id else None,
            "report_type": job.report_type,
            "output_format": job.output_format,
            "locale": job.locale,
            "date_from": job.date_from.isoformat() if job.date_from else None,
            "date_to": job.date_to.isoformat() if job.date_to else None,
            "file_size_bytes": job.file_size_bytes,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
        for job in rows
    ]
    return _page(items, total, limit, offset)


# ------------------------------------------------------- environment:read
@router.get("/environmental-metrics")
def public_environmental_metrics(
    field_id: uuid.UUID,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    key: ApiKeyPrincipal = Depends(require_api_key("environment:read")),
    db: Session = Depends(get_db),
) -> dict:
    """Per-variable observation aggregates for one org field and date window.

    Read-only view over the canonical ``observations`` table (the same data
    the environmental/vegetation/water summaries are built from); rows with
    null values or invalid/missing quality are excluded.
    """
    field = _org_field(db, key, field_id)
    end_date = to or date.today()
    start_date = from_ or (end_date - timedelta(days=30))
    if start_date > end_date:
        raise InvalidDateRange("'from' must be on or before 'to'.")
    if (end_date - start_date).days > MAX_ENV_RANGE_DAYS:
        raise InvalidDateRange(f"Date range may not exceed {MAX_ENV_RANGE_DAYS} days.")
    from_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
    to_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)

    rows = db.execute(
        select(
            Observation.variable_code,
            Observation.unit,
            func.count().label("samples"),
            func.min(Observation.value).label("min_value"),
            func.avg(Observation.value).label("mean_value"),
            func.max(Observation.value).label("max_value"),
            func.min(Observation.observed_at).label("first_observed_at"),
            func.max(Observation.observed_at).label("last_observed_at"),
        )
        .where(
            Observation.field_id == field.id,
            Observation.observed_at >= from_dt,
            Observation.observed_at < to_dt,
            Observation.value.is_not(None),
            Observation.quality_status.not_in(("invalid", "missing")),
        )
        .group_by(Observation.variable_code, Observation.unit)
        .order_by(Observation.variable_code)
    ).all()
    variables = [
        {
            "variable_code": row.variable_code,
            "unit": row.unit,
            "samples": int(row.samples),
            "min": float(row.min_value) if row.min_value is not None else None,
            "mean": round(float(row.mean_value), 6) if row.mean_value is not None else None,
            "max": float(row.max_value) if row.max_value is not None else None,
            "first_observed_at": row.first_observed_at.isoformat() if row.first_observed_at else None,
            "last_observed_at": row.last_observed_at.isoformat() if row.last_observed_at else None,
        }
        for row in rows
    ]
    return {
        "field_id": str(field.id),
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "variables": variables,
    }

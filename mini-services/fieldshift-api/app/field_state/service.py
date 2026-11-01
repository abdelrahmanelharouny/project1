"""Field state assembly service (Milestone 7.1).

Assembles an immutable, checksummed field-state snapshot BY REFERENCE from
already-versioned artifacts. It never duplicates domain data and never
computes agronomy: every dimension either pins an existing artifact or is
reported honestly as missing / not_evaluated / not_implemented.

Immutability contract (same idiom as water plans):
- assembly always creates a NEW row; nothing is rewritten;
- idempotency keys are field-scoped and replay-safe (202 pattern);
- referenced artifacts are protected by FK RESTRICT (F-13);
- the checksum covers every scientifically material stored input;
- `created_by`/`created_at` are provenance and are excluded from the hash.

Temporal discipline (F-02): the state carries an explicit reference period;
each dimension's coverage of that period is computed and recorded in
`period_compatibility`. A pinned environmental run that does not overlap the
period at all is REFUSED (it cannot qualify the state); a water plan with
zero overlap is allowed but recorded as `period_mismatch` with a warning —
never silently mixed.
"""

import hashlib
import json
import uuid as uuid_mod
from datetime import date as date_cls
from datetime import datetime, timezone as dt_timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as dbm
from app.field_state import contracts as fsc
from app.field_state.manifest import (
    MANIFEST_FORMAT_VERSION,
    build_manifest,
    sha256_of_document,
)


# --------------------------------------------------------------- helpers
def _as_utc(value: Any, field_name: str) -> datetime:
    """Parse an ISO datetime/date into an aware UTC datetime.

    Naive datetimes are interpreted as UTC (platform rule: TIMESTAMPTZ
    everywhere; naive input can only come from unzoned JSON). Plain dates
    are interpreted as UTC midnight of that date.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date_cls):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                d = date_cls.fromisoformat(text)
            except ValueError:
                raise ValidationFailed(
                    f"{field_name} must be an ISO-8601 date or datetime.",
                    details=[{"field": field_name, "reason": value}],
                ) from None
            parsed = datetime(d.year, d.month, d.day)
    else:
        raise ValidationFailed(
            f"{field_name} must be an ISO-8601 date or datetime.",
            details=[{"field": field_name, "reason": str(value)}],
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(dt_timezone.utc).isoformat() if value else None


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def _latest_succeeded_feature_run(db: Session, field_id: uuid_mod.UUID) -> dbm.FeatureRun | None:
    return db.scalar(
        select(dbm.FeatureRun)
        .where(
            dbm.FeatureRun.field_id == field_id,
            dbm.FeatureRun.status == "succeeded",
        )
        .order_by(
            dbm.FeatureRun.completed_at.desc().nullslast(),
            dbm.FeatureRun.created_at.desc(),
        )
        .limit(1)
    )


def _latest_succeeded_water_plan(db: Session, field_id: uuid_mod.UUID) -> dbm.WaterPlan | None:
    return db.scalar(
        select(dbm.WaterPlan)
        .where(
            dbm.WaterPlan.field_id == field_id,
            dbm.WaterPlan.status == "succeeded",
        )
        .order_by(dbm.WaterPlan.created_at.desc())
        .limit(1)
    )


def _resolve_environmental_run(
    db: Session, field: dbm.Field, requested: Any, availability: dict[str, Any]
) -> dbm.FeatureRun | None:
    if requested is None:
        run = _latest_succeeded_feature_run(db, field.id)
        if run is None:
            availability["environmental"] = {
                "status": fsc.MISSING,
                "reason": "No succeeded feature run exists for this field; "
                "create one via POST /fields/{id}/feature-runs.",
                "snapshot_id": None,
            }
        return run
    run = db.scalar(
        select(dbm.FeatureRun).where(
            dbm.FeatureRun.id == requested, dbm.FeatureRun.field_id == field.id
        )
    )
    if run is None:
        raise NotFound(f"Feature run {requested} not found for this field.")
    if run.status != "succeeded":
        raise ValidationFailed(
            "Pinned feature run has not succeeded; a state cannot pin a "
            "non-succeeded run.",
            details=[{"field": "environmental_feature_run_id", "reason": run.status}],
        )
    return run


def _resolve_water_plan(
    db: Session, field: dbm.Field, requested: Any, availability: dict[str, Any]
) -> dbm.WaterPlan | None:
    if requested is None:
        plan = _latest_succeeded_water_plan(db, field.id)
        if plan is None:
            availability["water"] = {
                "status": fsc.MISSING,
                "reason": "No water plan exists for this field; plans are only "
                "created on explicit request (F-05) — absence is expressed, "
                "never fabricated.",
                "snapshot_id": None,
            }
        return plan
    plan = db.scalar(
        select(dbm.WaterPlan).where(
            dbm.WaterPlan.id == requested, dbm.WaterPlan.field_id == field.id
        )
    )
    if plan is None:
        raise NotFound(f"Water plan {requested} not found for this field.")
    if plan.status != "succeeded":
        raise ValidationFailed(
            "Pinned water plan has not succeeded.",
            details=[{"field": "water_plan_id", "reason": plan.status}],
        )
    return plan


def _resolve_rotation_run(
    db: Session, field: dbm.Field, requested: Any, strategy_key: Any
) -> tuple[dbm.RotationRun | None, str | None]:
    if requested is None:
        if strategy_key:
            raise ValidationFailed(
                "rotation_strategy_key requires rotation_run_id.",
                details=[{"field": "rotation_strategy_key"}],
            )
        # No default: rotation runs are optimization experiments, not a
        # general state (M7.0 F-06) — they are pinned explicitly only.
        return None, None
    run = db.scalar(
        select(dbm.RotationRun).where(
            dbm.RotationRun.id == requested, dbm.RotationRun.field_id == field.id
        )
    )
    if run is None:
        raise NotFound(f"Rotation run {requested} not found for this field.")
    if run.status != "succeeded":
        raise ValidationFailed(
            "Pinned rotation run has not succeeded.",
            details=[{"field": "rotation_run_id", "reason": run.status}],
        )
    if strategy_key is not None:
        keys = {s.strategy_key for s in run.strategies}
        if strategy_key not in keys:
            raise ValidationFailed(
                "rotation_strategy_key is not part of the pinned rotation run.",
                details=[{"field": "rotation_strategy_key", "reason": str(strategy_key)}],
            )
    return run, strategy_key


def _crop_history_ids_asof(db: Session, field_id: uuid_mod.UUID, asof: datetime) -> list[dict[str, Any]]:
    """Pin crop-history rows whose sowing_date is on/before the reference time.

    Rows are immutable (no update path) so pinning ids + key attributes by
    value is sufficient for reconstruction without duplicating the table.
    """
    rows = (
        db.execute(
            select(dbm.CropHistory)
            .where(dbm.CropHistory.field_id == field_id)
            .order_by(dbm.CropHistory.sowing_date.asc().nullslast(), dbm.CropHistory.created_at.asc())
        )
        .scalars()
        .all()
    )
    pinned = []
    for row in rows:
        if row.sowing_date is None:
            continue  # undated rows cannot be placed as-of T — never guessed
        sowing_dt = datetime(
            row.sowing_date.year, row.sowing_date.month, row.sowing_date.day, tzinfo=dt_timezone.utc
        )
        if sowing_dt > asof:
            continue
        pinned.append(
            {
                "id": str(row.id),
                "crop_label": row.crop_label,
                "season_label": row.season_label,
                "sowing_date": row.sowing_date.isoformat(),
                "harvest_date": row.harvest_date.isoformat() if row.harvest_date else None,
                "source": row.source,
            }
        )
    return pinned


def _seasons_interval(plan: dbm.WaterPlan | None) -> tuple[datetime, datetime] | None:
    if not plan or not plan.seasons:
        return None
    starts: list[datetime] = []
    ends: list[datetime] = []
    for season in plan.seasons:
        try:
            s = date_cls.fromisoformat(str(season.get("start_date")))
            e = date_cls.fromisoformat(str(season.get("end_date")))
        except (TypeError, ValueError):
            continue
        starts.append(datetime(s.year, s.month, s.day, tzinfo=dt_timezone.utc))
        ends.append(
            datetime(e.year, e.month, e.day, tzinfo=dt_timezone.utc).replace(
                hour=23, minute=59, second=59
            )
        )
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _compat_record(
    artifact_start: datetime | None,
    artifact_end: datetime | None,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    if artifact_start is None or artifact_end is None:
        return {"status": fsc.NOT_EVALUATED, "reason": "artifact has no recorded period"}
    fraction = fsc.period_overlap_fraction(artifact_start, artifact_end, period_start, period_end)
    if fraction is None:
        return {"status": fsc.NOT_EVALUATED, "reason": "artifact has no recorded period"}
    record: dict[str, Any] = {
        "artifact_period": {"start": _iso(artifact_start), "end": _iso(artifact_end)},
        "overlap_fraction": fraction,
    }
    if fraction <= 0.0:
        record["status"] = fsc.OUTSIDE_PERIOD
    elif fraction >= 1.0:
        record["status"] = fsc.COVERS_PERIOD
    else:
        record["status"] = fsc.PARTIAL_COVER
    return record


def _state_manifest(db: Session, run: dbm.FeatureRun | None, field_id: uuid_mod.UUID) -> tuple[dict[str, Any], str]:
    """The state's observation manifest: a verbatim copy of the pinned run's
    manifest when available; otherwise an explicit, honestly empty document.

    Pre-M7.1 runs have no stored manifest — the state never fabricates one;
    it records the gap with reason `unavailable_pre_m7_1_run`.
    """
    if run is not None and run.observation_manifest is not None:
        document = dict(run.observation_manifest)
        stored_hash = run.observation_manifest_sha256
        recomputed = sha256_of_document(document)
        if stored_hash and stored_hash != recomputed:
            raise Conflict(
                "Stored observation manifest of the pinned feature run does not "
                "match its checksum; the run artifact is not intact."
            )
        return document, recomputed
    document = build_manifest(
        [],
        field_id=str(field_id),
        purpose="field_state_environmental",
        processing_configuration={
            "manifest_status": "unavailable_pre_m7_1_run"
            if run is not None
            else "no_environmental_run_pinned",
        },
    )
    return document, sha256_of_document(document)


def _evidence_summary(
    *,
    run: dbm.FeatureRun | None,
    plan: dbm.WaterPlan | None,
    rotation: dbm.RotationRun | None,
    strategy_key: str | None,
    crop_history: list[dict[str, Any]],
    manifest_document: dict[str, Any],
    availability: dict[str, Any],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    if run is not None:
        source_products = []
        for variable, selection in sorted((run.source_selection or {}).items()):
            if isinstance(selection, dict):
                source_products.append(
                    {
                        "variable": variable,
                        "product_id": selection.get("dataset_product_id"),
                        "product_code": selection.get("product_code"),
                        "product_version": selection.get("product_version"),
                        "is_synthetic": selection.get("is_synthetic"),
                    }
                )
        evidence["environmental"] = {
            "feature_run_id": str(run.id),
            "feature_engine_version": run.feature_engine_version,
            "feature_catalog_version": run.feature_catalog_version,
            "is_synthetic": run.is_synthetic,
            "source_products": source_products,
            "observation_count": manifest_document.get("observation_count", 0),
            "synthetic_observation_count": manifest_document.get("synthetic_observation_count", 0),
        }
    else:
        evidence["environmental"] = {"feature_run_id": None}

    if plan is not None:
        evidence["water"] = {
            "water_plan_id": str(plan.id),
            "water_engine_version": plan.water_engine_version,
            "methods_version": plan.methods_version,
            "season_labels": sorted(s.get("label") for s in (plan.seasons or []) if s.get("label")),
            "checksum_sha256": plan.checksum_sha256,
        }
    else:
        evidence["water"] = {"water_plan_id": None}

    if rotation is not None:
        evidence["rotation"] = {
            "rotation_run_id": str(rotation.id),
            "rotation_engine_version": rotation.rotation_engine_version,
            "solver_name": rotation.solver_name,
            "solver_version": rotation.solver_version,
            "strategy_key": strategy_key,
            "solver_status": rotation.solver_status,
        }
    else:
        evidence["rotation"] = {"rotation_run_id": None}

    evidence["crop_history"] = {
        "count": len(crop_history),
        "crop_labels": sorted({c["crop_label"] for c in crop_history}),
        "season_labels": sorted({c["season_label"] for c in crop_history if c["season_label"]}),
    }
    evidence["soil"] = {"assessment_run_id": None, "status": fsc.NOT_IMPLEMENTED}
    evidence["management"] = {"management_plan_id": None, "status": fsc.NOT_IMPLEMENTED}
    return evidence


def _feature_value_quality_counts(db: Session, run_id: uuid_mod.UUID) -> dict[str, int]:
    rows = db.execute(
        select(dbm.FeatureValue.quality_status).where(dbm.FeatureValue.run_id == run_id)
    ).all()
    counts: dict[str, int] = {}
    for (quality,) in rows:
        counts[quality] = counts.get(quality, 0) + 1
    return counts


def _quality_summary(
    *,
    run: dbm.FeatureRun | None,
    plan: dbm.WaterPlan | None,
    rotation: dbm.RotationRun | None,
    manifest_document: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    quality: dict[str, Any] = {}
    if run is not None:
        quality["environmental"] = {
            "feature_value_quality_counts": _feature_value_quality_counts(db, run.id),
            "manifest_quality_status_counts": _manifest_quality_counts(manifest_document),
            "run_warnings_count": len(run.warnings or []),
        }
    else:
        quality["environmental"] = None
    if plan is not None:
        quality["water"] = {
            "warnings_count": len(plan.warnings or []),
            "not_evaluated_seasons": sorted((plan.not_evaluated or {}).keys()),
        }
    else:
        quality["water"] = None
    quality["rotation"] = (
        {"solver_status": rotation.solver_status} if rotation is not None else None
    )
    return quality


def _manifest_quality_counts(document: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in document.get("observations", []):
        status = entry.get("quality_status")
        counts[status] = counts.get(status, 0) + 1
    return counts


def state_checksum_payload(state: dbm.FieldState) -> dict[str, Any]:
    """The exact checksum input for a persisted field state.

    Everything scientifically material, nothing ephemeral: timestamps of
    assembly (created_at) and the actor (created_by) are provenance, not
    content, and are excluded. All other stored fields participate.
    """
    return {
        "assembly_version": (state.source_versions or {}).get("field_state_assembly_version"),
        "manifest_format_version": state.manifest_format_version,
        "field_id": str(state.field_id),
        "boundary_version": state.boundary_version,
        "state_reference_time": _iso(state.state_reference_time),
        "period_start": _iso(state.period_start),
        "period_end": _iso(state.period_end),
        "timezone": state.timezone,
        "calendar_context": state.calendar_context,
        "environmental_feature_run_id": (
            str(state.environmental_feature_run_id) if state.environmental_feature_run_id else None
        ),
        "water_plan_id": str(state.water_plan_id) if state.water_plan_id else None,
        "rotation_run_id": str(state.rotation_run_id) if state.rotation_run_id else None,
        "rotation_strategy_key": state.rotation_strategy_key,
        "crop_history_ids": sorted(state.crop_history_ids or []),
        "knowledge_pack_refs": sorted(
            state.knowledge_pack_refs or [], key=lambda r: _canonical(r)
        ),
        "observation_manifest_sha256": state.observation_manifest_sha256,
        "domain_availability": state.domain_availability,
        "evidence_summary": state.evidence_summary,
        "quality_summary": state.quality_summary,
        "period_compatibility": state.period_compatibility,
    }


def compute_state_checksum(state: dbm.FieldState) -> str:
    return hashlib.sha256(_canonical(state_checksum_payload(state)).encode("utf-8")).hexdigest()


# ------------------------------------------------------------- assembly
def assemble_field_state(
    db: Session,
    *,
    field: dbm.Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.FieldState:
    """Create (or idempotently return) a field state for `field`."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.FieldState).where(
                dbm.FieldState.idempotency_key == idempotency_key,
                dbm.FieldState.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    warnings: list[str] = []
    not_evaluated: dict[str, Any] = {}

    label = str(payload.get("label") or f"Field state {field.name}").strip() or "field state"
    if len(label) > fsc.STATE_LABEL_MAX:
        label = label[: fsc.STATE_LABEL_MAX]

    reference_raw = payload.get("state_reference_time")
    reference_time = (
        _as_utc(reference_raw, "state_reference_time") if reference_raw else datetime.now(dt_timezone.utc)
    )

    availability = fsc.baseline_domain_availability()

    # ---- resolve dimensions -------------------------------------------------
    run = _resolve_environmental_run(db, field, payload.get("environmental_feature_run_id"), availability)
    plan = _resolve_water_plan(db, field, payload.get("water_plan_id"), availability)
    rotation, strategy_key = _resolve_rotation_run(
        db, field, payload.get("rotation_run_id"), payload.get("rotation_strategy_key")
    )
    crop_history = _crop_history_ids_asof(db, field.id, reference_time)
    if not crop_history:
        availability["crop_history"] = {
            "status": fsc.MISSING,
            "reason": "No dated crop-history rows on or before the reference time.",
            "snapshot_id": None,
        }
    else:
        availability["crop_history"] = {
            "status": fsc.AVAILABLE,
            "reason": None,
            "snapshot_id": None,
        }

    if run is not None:
        availability["environmental"] = {
            "status": fsc.AVAILABLE,
            "reason": None,
            "snapshot_id": str(run.id),
        }
    if plan is not None:
        availability["water"] = {
            "status": fsc.AVAILABLE,
            "reason": None,
            "snapshot_id": str(plan.id),
        }
    if rotation is not None:
        availability["rotation"] = {
            "status": fsc.AVAILABLE,
            "reason": None,
            "snapshot_id": str(rotation.id),
        }

    # ---- period -------------------------------------------------------------
    period_start_raw = payload.get("period_start")
    period_end_raw = payload.get("period_end")
    if period_start_raw is not None and period_end_raw is None:
        raise ValidationFailed(
            "period_end is required when period_start is given.",
            details=[{"field": "period_end"}],
        )
    if period_end_raw is not None and period_start_raw is None:
        raise ValidationFailed(
            "period_start is required when period_end is given.",
            details=[{"field": "period_start"}],
        )
    if period_start_raw is not None:
        period_start = _as_utc(period_start_raw, "period_start")
        period_end = _as_utc(period_end_raw, "period_end")
    elif run is not None:
        # Default: the environmental run's own window — the only artifact
        # whose period is always explicit and machine-comparable.
        period_start = run.period_start
        period_end = run.period_end
    else:
        raise ValidationFailed(
            "period_start/period_end are required when no environmental "
            "feature run is pinned (the state must declare the period it "
            "qualifies).",
            details=[{"field": "period_start"}],
        )
    if period_end < period_start:
        raise ValidationFailed(
            "period_end must be on or after period_start.",
            details=[{"field": "period_end"}],
        )

    # ---- period compatibility (F-02) — recorded, never silently mixed -------
    period_compatibility: dict[str, Any] = {}
    if run is not None:
        record = _compat_record(run.period_start, run.period_end, period_start, period_end)
        period_compatibility["environmental"] = record
        if record["status"] == fsc.OUTSIDE_PERIOD:
            raise ValidationFailed(
                "The pinned feature run's period does not overlap the state "
                "period at all — an environmental snapshot cannot qualify a "
                "period it does not touch.",
                details=[
                    {"field": "period_start", "reason": record["artifact_period"]["start"]},
                    {"field": "period_end", "reason": record["artifact_period"]["end"]},
                ],
            )
        if record["status"] == fsc.PARTIAL_COVER:
            availability["environmental"]["status"] = fsc.PERIOD_MISMATCH
            warnings.append(
                "Environmental feature run only partially covers the state "
                "period (overlap fraction recorded in period_compatibility)."
            )
    else:
        period_compatibility["environmental"] = {
            "status": fsc.NOT_EVALUATED,
            "reason": "no environmental run pinned",
        }

    if plan is not None:
        interval = _seasons_interval(plan)
        record = _compat_record(interval[0] if interval else None, interval[1] if interval else None, period_start, period_end)
        period_compatibility["water"] = record
        if record["status"] == fsc.OUTSIDE_PERIOD:
            availability["water"] = {
                "status": fsc.PERIOD_MISMATCH,
                "reason": "Water plan seasons lie entirely outside the state period; "
                "the plan is pinned as provenance but does not qualify this period.",
                "snapshot_id": str(plan.id),
            }
            warnings.append(
                "Water plan seasons do not overlap the state period — recorded "
                "as period_mismatch, never silently mixed."
            )
        elif record["status"] == fsc.PARTIAL_COVER:
            warnings.append(
                "Water plan seasons only partially cover the state period."
            )
    else:
        period_compatibility["water"] = {
            "status": fsc.NOT_EVALUATED,
            "reason": "no water plan pinned",
        }

    if rotation is not None:
        seasons = rotation.seasons or []
        if seasons:
            try:
                starts = [
                    datetime(*date_cls.fromisoformat(str(s.get("start_date"))).timetuple()[:3], tzinfo=dt_timezone.utc)
                    for s in seasons
                    if s.get("start_date")
                ]
                ends = [
                    datetime(*date_cls.fromisoformat(str(s.get("end_date"))).timetuple()[:3], tzinfo=dt_timezone.utc)
                    .replace(hour=23, minute=59, second=59)
                    for s in seasons
                    if s.get("end_date")
                ]
            except (TypeError, ValueError):
                starts, ends = [], []
            if starts and ends:
                record = _compat_record(min(starts), max(ends), period_start, period_end)
                period_compatibility["rotation"] = record
                if record["status"] != fsc.COVERS_PERIOD:
                    warnings.append(
                        "Rotation run seasons do not fully cover the state period."
                    )
            else:
                period_compatibility["rotation"] = {
                    "status": fsc.NOT_EVALUATED,
                    "reason": "rotation run seasons unparseable",
                }
        else:
            period_compatibility["rotation"] = {
                "status": fsc.NOT_EVALUATED,
                "reason": "rotation run has no seasons",
            }
    else:
        period_compatibility["rotation"] = {
            "status": fsc.NOT_EVALUATED,
            "reason": "no rotation run pinned",
        }

    period_compatibility["crop_history"] = {
        "status": fsc.NOT_EVALUATED,
        "reason": "crop history spans arbitrary past seasons; each row carries "
        "its own dates — as-of rule: sowing_date <= state_reference_time",
    }
    period_compatibility["soil"] = {"status": fsc.NOT_EVALUATED, "reason": fsc.SOIL_NOT_IMPLEMENTED_REASON}
    period_compatibility["management"] = {
        "status": fsc.NOT_EVALUATED,
        "reason": fsc.MANAGEMENT_NOT_IMPLEMENTED_REASON,
    }

    # ---- calendar context ----------------------------------------------------
    calendar_context: dict[str, Any] = {
        "farm_timezone": field.farm.timezone if field.farm else None,
        "hemisphere": run.hemisphere if run is not None else None,
        "season_labels": sorted(
            {
                *(s.get("label") for s in ((plan.seasons or []) if plan is not None else []) if s.get("label")),
                *(c["season_label"] for c in crop_history if c["season_label"]),
            }
        ),
    }

    # ---- manifest ------------------------------------------------------------
    manifest_document, manifest_hash = _state_manifest(db, run, field.id)

    # ---- knowledge pack set resolved at assembly time (F-08) -----------------
    from app.knowledge.service import load_knowledge

    knowledge = load_knowledge(db)
    pack_refs = [dict(ref) for ref in knowledge.pack_refs]

    # ---- summaries + versions ------------------------------------------------
    evidence_summary = _evidence_summary(
        run=run,
        plan=plan,
        rotation=rotation,
        strategy_key=strategy_key,
        crop_history=crop_history,
        manifest_document=manifest_document,
        availability=availability,
    )
    quality_summary = _quality_summary(
        run=run, plan=plan, rotation=rotation, manifest_document=manifest_document, db=db
    )
    source_versions = {
        "field_state_assembly_version": fsc.FIELD_STATE_ASSEMBLY_VERSION,
        "manifest_format_version": MANIFEST_FORMAT_VERSION,
        "feature_engine_version": run.feature_engine_version if run else None,
        "feature_catalog_version": run.feature_catalog_version if run else None,
        "water_engine_version": plan.water_engine_version if plan else None,
        "water_methods_version": plan.methods_version if plan else None,
        "rotation_engine_version": rotation.rotation_engine_version if rotation else None,
    }

    # ---- persist (new row; nothing rewritten) ---------------------------------
    state = dbm.FieldState(
        field_id=field.id,
        status="running",
        label=label,
        boundary_version=field.boundary_version,
        state_reference_time=reference_time,
        period_start=period_start,
        period_end=period_end,
        timezone=field.farm.timezone if field.farm else "UTC",
        calendar_context=calendar_context,
        environmental_feature_run_id=run.id if run is not None else None,
        water_plan_id=plan.id if plan is not None else None,
        rotation_run_id=rotation.id if rotation is not None else None,
        rotation_strategy_key=strategy_key,
        crop_history_ids=[c["id"] for c in crop_history],
        knowledge_pack_refs=pack_refs,
        observation_manifest=manifest_document,
        observation_manifest_sha256=manifest_hash,
        manifest_format_version=MANIFEST_FORMAT_VERSION,
        domain_availability=availability,
        evidence_summary=evidence_summary,
        quality_summary=quality_summary,
        period_compatibility=period_compatibility,
        source_versions=source_versions,
        request_parameters={
            k: (v.isoformat() if isinstance(v, (datetime, date_cls)) else v)
            for k, v in (payload.items() if isinstance(payload, dict) else [])
        },
        warnings=warnings,
        not_evaluated=not_evaluated,
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=datetime.now(dt_timezone.utc),
    )
    db.add(state)
    try:
        db.commit()
    except Exception:
        db.rollback()
        state.status = "failed"
        state.error_summary = "assembly failed"
        db.add(state)
        db.commit()
        raise
    try:
        state.checksum_sha256 = compute_state_checksum(state)
        state.status = "succeeded"
        state.completed_at = datetime.now(dt_timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — job failure accounting
        db.rollback()
        state.status = "failed"
        state.error_summary = f"{type(exc).__name__}: {exc}"
        db.commit()
        raise
    return state


# ------------------------------------------------------------- reads
def get_field_state(db: Session, state_id: uuid_mod.UUID) -> dbm.FieldState | None:
    return db.get(dbm.FieldState, state_id)


def list_field_states(db: Session, field_id: uuid_mod.UUID) -> list[dbm.FieldState]:
    return (
        db.execute(
            select(dbm.FieldState)
            .where(dbm.FieldState.field_id == field_id)
            .order_by(dbm.FieldState.created_at.desc())
        )
        .scalars()
        .all()
    )


def verify_field_state(db: Session, state: dbm.FieldState) -> dict[str, Any]:
    """Independently re-verify a state from its stored content.

    Checks: (1) state checksum recomputed from stored fields; (2) manifest
    checksum recomputed from the stored manifest document; (3) referenced
    artifacts still exist and (where the artifact has its own checksum) are
    intact; (4) the pinned boundary version row exists in the append-only
    boundary history.
    """
    checksum_valid = (
        state.checksum_sha256 is not None
        and state.checksum_sha256 == compute_state_checksum(state)
    )
    manifest_valid = state.observation_manifest_sha256 is not None and (
        state.observation_manifest_sha256
        == sha256_of_document(state.observation_manifest or {})
    )

    referenced: dict[str, Any] = {}
    if state.environmental_feature_run_id is not None:
        run = db.get(dbm.FeatureRun, state.environmental_feature_run_id)
        referenced["feature_run"] = {
            "exists": run is not None,
            "intact": run is not None and run.status == "succeeded",
        }
    if state.water_plan_id is not None:
        plan = db.get(dbm.WaterPlan, state.water_plan_id)
        intact = False
        if plan is not None and plan.status == "succeeded":
            if plan.checksum_sha256 is None:
                intact = True  # legacy plan without checksum — existence only
            else:
                from app.water.service import _plan_snapshot_checksum

                intact = plan.checksum_sha256 == _plan_snapshot_checksum(plan.result or {}, plan)
        referenced["water_plan"] = {"exists": plan is not None, "intact": intact}
    if state.rotation_run_id is not None:
        rotation = db.get(dbm.RotationRun, state.rotation_run_id)
        referenced["rotation_run"] = {"exists": rotation is not None, "intact": rotation is not None}

    boundary_row = db.scalar(
        select(dbm.FieldBoundaryVersion).where(
            dbm.FieldBoundaryVersion.field_id == state.field_id,
            dbm.FieldBoundaryVersion.version_number == state.boundary_version,
        )
    )
    return {
        "state_id": str(state.id),
        "checksum_valid": checksum_valid,
        "manifest_checksum_valid": manifest_valid,
        "referenced_artifacts": referenced,
        "boundary_version_record_exists": boundary_row is not None,
        "verified_at": datetime.now(dt_timezone.utc).isoformat(),
    }


def compare_field_states(db: Session, state_ids: list[uuid_mod.UUID]) -> dict[str, Any]:
    """Compare 2+ states — compatibility is assessed, never implied."""
    if len(state_ids) < 2:
        raise ValidationFailed(
            "At least two state ids are required to compare.",
            details=[{"field": "state_ids"}],
        )
    states: list[dbm.FieldState] = []
    for sid in state_ids:
        state = get_field_state(db, sid)
        if state is None:
            raise NotFound(f"Field state {sid} not found.")
        states.append(state)

    field_ids = {str(s.field_id) for s in states}
    same_field = len(field_ids) == 1
    if not same_field:
        raise ValidationFailed(
            "Field states from different fields cannot be compared for "
            "temporal/spatial compatibility.",
            details=[{"field": "state_ids", "reason": ",".join(sorted(field_ids))}],
        )

    dimension_refs = ("environmental_feature_run_id", "water_plan_id", "rotation_run_id")
    dimensions: dict[str, Any] = {}
    for dim in dimension_refs:
        values = [getattr(s, dim) for s in states]
        dimensions[dim] = {
            "consistent": len({str(v) for v in values if v is not None}) <= 1 and all(v is not None for v in values),
            "values": [str(v) if v else None for v in values],
        }
    dimensions["boundary_version"] = {
        "consistent": len({s.boundary_version for s in states}) == 1,
        "values": [s.boundary_version for s in states],
    }
    dimensions["observation_manifest_sha256"] = {
        "consistent": len({s.observation_manifest_sha256 for s in states}) == 1,
        "values": [s.observation_manifest_sha256 for s in states],
    }

    pair_overlaps: list[dict[str, Any]] = []
    for i in range(len(states)):
        for j in range(i + 1, len(states)):
            a, b = states[i], states[j]
            fraction = fsc.period_overlap_fraction(a.period_start, a.period_end, b.period_start, b.period_end)
            pair_overlaps.append(
                {
                    "state_a": str(a.id),
                    "state_b": str(b.id),
                    "period_overlap_fraction": fraction,
                    "compatible_periods": (fraction or 0.0) > 0.0,
                }
            )

    return {
        "state_ids": [str(s.id) for s in states],
        "same_field": same_field,
        "field_id": str(states[0].field_id),
        "boundary_versions_consistent": dimensions["boundary_version"]["consistent"],
        "dimension_comparison": dimensions,
        "pairwise_period_overlap": pair_overlaps,
        "note": (
            "Comparison reports facts about the stored snapshots; states with "
            "different boundary versions or non-overlapping periods are NOT "
            "interchangeable and must not be treated as a time series without "
            "explicit qualification."
        ),
    }


# ------------------------------------------------------------- serializer
def state_payload(state: dbm.FieldState, *, include_manifest: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(state.id),
        "field_id": str(state.field_id),
        "status": state.status,
        "label": state.label,
        "boundary_version": state.boundary_version,
        "state_reference_time": _iso(state.state_reference_time),
        "period": {"start": _iso(state.period_start), "end": _iso(state.period_end)},
        "timezone": state.timezone,
        "calendar_context": state.calendar_context,
        "environmental_feature_run_id": (
            str(state.environmental_feature_run_id) if state.environmental_feature_run_id else None
        ),
        "water_plan_id": str(state.water_plan_id) if state.water_plan_id else None,
        "rotation_run_id": str(state.rotation_run_id) if state.rotation_run_id else None,
        "rotation_strategy_key": state.rotation_strategy_key,
        "crop_history_ids": state.crop_history_ids,
        "knowledge_pack_refs": state.knowledge_pack_refs,
        "observation_manifest_sha256": state.observation_manifest_sha256,
        "manifest_format_version": state.manifest_format_version,
        "domain_availability": state.domain_availability,
        "evidence_summary": state.evidence_summary,
        "quality_summary": state.quality_summary,
        "period_compatibility": state.period_compatibility,
        "source_versions": state.source_versions,
        "warnings": state.warnings,
        "not_evaluated": state.not_evaluated,
        "error_summary": state.error_summary,
        "checksum_sha256": state.checksum_sha256,
        "created_by": str(state.created_by) if state.created_by else None,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        "field_state_assembly_version": (state.source_versions or {}).get(
            "field_state_assembly_version"
        ),
        "verify_url": f"/api/v1/field-states/{state.id}/verify",
        "manifest_url": f"/api/v1/field-states/{state.id}/manifest",
    }
    if include_manifest:
        data["observation_manifest"] = state.observation_manifest
    return data

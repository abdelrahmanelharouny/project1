"""Evidence dependency map + decision recalculation (P2.E / integration).

The declarative dependency graph states which downstream artifacts depend on
which evidence domains, so a change invalidates ONLY what actually depends
on it (no full-pipeline recomputation):

    evidence domain            -> stale downstream artifacts
    ----------------------------------------------------------------
    weather observations       -> feature runs (climate features),
                                  water plans (ETc basis), rotation runs
                                  (climate evidence), scenario executions
                                  (parent manifest), recommendations
                                  (climate domain), forecast verification
    vegetation (ndvi scenes)   -> vegetation summaries, recommendations
                                  (vegetation domain)
    soil measurements/samples  -> soil profile/assessments, SOC runs,
                                  water plans with PTF soil basis,
                                  soil memory snapshots, recommendations
                                  (soil domain)
    water plan inputs          -> water plan result, rotation water
                                  coefficients, recommendations (water)
    crop history               -> rotation baseline, candidates, rotation
                                  runs, recommendations (rotation)
    farm constraints/resources -> portfolio runs, operations schedules,
                                  rotation farm context

Staleness is computed DYNAMICALLY by comparing artifact timestamps against
the latest evidence timestamps in their dependency domain — no staleness
state table to drift out of sync.

`apply_new_evidence` orchestrates: validate the submitted evidence reference,
mark acquisition actions resolved, recompute the SAFE artifacts inline
(feature runs are immutable - a new run is appended; recommendations refresh
diffs fingerprints so unchanged rows survive), and return a change report
built from recommendation fingerprint diffs (what changed and why).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.db.models_m6bc_m7 import SoilMeasurement
from app.db.models_p2 import (
    EvidenceAcquisitionAction,
    EvidenceAcquisitionEvent,
    SatelliteScene,
    WeatherForecast,
)

logger = logging.getLogger("croptwist.evidence.recalc")

EVIDENCE_DEPENDENCIES_VERSION = "evidence-dependencies-1.0.0"

# Declarative dependency graph (documented in the module docstring).
DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "weather": ["feature_runs", "water_plans", "rotation_runs", "scenario_executions", "recommendations:climate", "forecast_verification"],
    "vegetation": ["vegetation_summaries", "recommendations:vegetation"],
    "soil": ["soil_profile", "soil_assessments", "soc_runs", "water_plans_ptf_basis", "soil_memory_snapshots", "recommendations:soil"],
    "water_records": ["water_plans", "recommendations:water"],
    "crop_history": ["rotation_runs", "recommendations:rotation"],
    "farm_constraints": ["portfolio_runs", "operation_schedules", "recommendations:rotation"],
    "forecasts": ["forecast_risks", "recommendations:climate"],
}

# Which feature variable groups each domain feeds (for feature-run staleness).
DOMAIN_VARIABLE_GROUPS: dict[str, list[str]] = {
    "weather": [
        "air_temperature_mean", "air_temperature_min", "air_temperature_max",
        "precipitation", "reference_et0", "soil_moisture_surface", "wind_speed_10m", "wind_speed_2m",
    ],
    "vegetation": ["ndvi", "evi", "savi", "ndmi", "ndwi"],
    "soil": [],  # soil feeds non-feature engines
}


def latest_evidence_time(db: Session, field_id: uuid.UUID, domain: str) -> datetime | None:
    """The newest evidence timestamp in a domain (ingestion-time based)."""
    codes = DOMAIN_VARIABLE_GROUPS.get(domain, [])
    latest: datetime | None = None

    def _take(candidate: datetime | None) -> None:
        nonlocal latest
        if candidate is None:
            return
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=UTC)
        if latest is None or candidate > latest:
            latest = candidate

    if codes:
        obs_latest = db.scalar(
            select(dbm.Observation.ingested_at if hasattr(dbm.Observation, "ingested_at") else dbm.Observation.retrieved_at)
            .where(
                dbm.Observation.field_id == field_id,
                dbm.Observation.variable_code.in_(codes),
            )
            .order_by(dbm.Observation.retrieved_at.desc())
            .limit(1)
        )
        _take(obs_latest)
    if domain == "soil":
        soil_latest = db.scalar(
            select(SoilMeasurement.created_at)
            .where(SoilMeasurement.field_id == field_id)
            .order_by(SoilMeasurement.created_at.desc())
            .limit(1)
        )
        _take(soil_latest)
    if domain == "vegetation":
        scene_latest = db.scalar(
            select(SatelliteScene.created_at)
            .where(SatelliteScene.field_id == field_id)
            .order_by(SatelliteScene.created_at.desc())
            .limit(1)
        )
        _take(scene_latest)
    if domain == "forecasts":
        forecast_latest = db.scalar(
            select(WeatherForecast.retrieved_at)
            .where(WeatherForecast.field_id == field_id)
            .order_by(WeatherForecast.retrieved_at.desc())
            .limit(1)
        )
        _take(forecast_latest)
    return latest


def staleness_report(db: Session, field: dbm.Field) -> dict[str, Any]:
    """Which downstream artifacts are older than the newest evidence in each
    domain they depend on (dynamic staleness — no state table)."""
    report: dict[str, Any] = {"domains": {}, "version": EVIDENCE_DEPENDENCIES_VERSION}
    for domain, downstream in sorted(DEPENDENCY_GRAPH.items()):
        evidence_time = latest_evidence_time(db, field.id, domain)
        domain_report: dict[str, Any] = {
            "latest_evidence_at": evidence_time.isoformat() if evidence_time else None,
            "downstream": {},
        }
        for artifact in downstream:
            artifact_time = _artifact_time(db, field, artifact)
            stale = (
                evidence_time is not None
                and artifact_time is not None
                and artifact_time < evidence_time
            )
            domain_report["downstream"][artifact] = {
                "artifact_updated_at": artifact_time.isoformat() if artifact_time else None,
                "stale": stale,
                "status": (
                    "stale" if stale
                    else "current" if artifact_time is not None
                    else "not_built"
                ),
            }
        report["domains"][domain] = domain_report
    return report


def _artifact_time(db: Session, field: dbm.Field, artifact: str) -> datetime | None:
    base = artifact.split(":")[0]
    if base == "feature_runs":
        return db.scalar(
            select(dbm.FeatureRun.created_at)
            .where(dbm.FeatureRun.field_id == field.id)
            .order_by(dbm.FeatureRun.created_at.desc())
            .limit(1)
        )
    if base == "water_plans":
        return db.scalar(
            select(dbm.WaterPlan.created_at)
            .where(dbm.WaterPlan.field_id == field.id)
            .order_by(dbm.WaterPlan.created_at.desc())
            .limit(1)
        )
    if base == "rotation_runs":
        return db.scalar(
            select(dbm.RotationRun.created_at)
            .where(dbm.RotationRun.field_id == field.id)
            .order_by(dbm.RotationRun.created_at.desc())
            .limit(1)
        )
    if base == "soil_profile":
        return db.scalar(
            select(SoilMeasurement.created_at)
            .where(SoilMeasurement.field_id == field.id)
            .order_by(SoilMeasurement.created_at.desc())
            .limit(1)
        )
    if base == "soil_memory_snapshots":
        from app.db.models_p2 import SoilStateSnapshot

        return db.scalar(
            select(SoilStateSnapshot.created_at)
            .where(SoilStateSnapshot.field_id == field.id)
            .order_by(SoilStateSnapshot.created_at.desc())
            .limit(1)
        )
    if base == "vegetation_summaries":
        # computed on read — freshness = the newest ndvi observation
        return db.scalar(
            select(dbm.Observation.retrieved_at)
            .where(dbm.Observation.field_id == field.id, dbm.Observation.variable_code == "ndvi")
            .order_by(dbm.Observation.retrieved_at.desc())
            .limit(1)
        )
    if base == "recommendations":
        from app.db.models_ai import AIRecommendation

        return db.scalar(
            select(AIRecommendation.created_at)
            .where(AIRecommendation.field_id == field.id)
            .order_by(AIRecommendation.created_at.desc())
            .limit(1)
        )
    if base == "portfolio_runs":
        from app.db.models_p2 import PortfolioRun

        return db.scalar(
            select(PortfolioRun.created_at).order_by(PortfolioRun.created_at.desc()).limit(1)
        )
    return None


def apply_new_evidence(
    db: Session,
    field: dbm.Field,
    principal: Any,
    *,
    ref_kind: str,
    ref_id: uuid.UUID | None,
    action_id: uuid.UUID | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Orchestrate recalculation after new evidence arrives.

    1. Validate the evidence reference exists (per kind).
    2. Mark the linked acquisition action resolved (append-only event).
    3. Recalculate the affected engines that are SAFE to recompute inline:
       - feature runs: a NEW run is appended (immutable runs are preserved);
       - recommendations: refresh diffs fingerprints (stable rows survive).
    4. Return a change report: which artifacts were recomputed and which
       recommendation fingerprints changed (the "which decision changed and
       why" record).
    """
    from app.recommendations.service import refresh_field_recommendations

    ref_valid, ref_detail = _validate_ref(db, field, ref_kind, ref_id)
    if not ref_valid:
        from app.core.errors import ValidationFailed

        raise ValidationFailed(
            f"Evidence reference of kind '{ref_kind}' was not found for this field.",
            details=[{"ref_kind": ref_kind, "ref_id": str(ref_id) if ref_id else None}],
        )

    resolved_action = None
    if action_id is not None:
        action = db.scalar(
            select(EvidenceAcquisitionAction).where(
                EvidenceAcquisitionAction.id == action_id,
                EvidenceAcquisitionAction.field_id == field.id,
            )
        )
        if action is not None:
            previous = action.status
            action.status = "resolved"
            action.resolved_at = datetime.now(UTC)
            action.submitted_ref_kind = ref_kind
            action.submitted_ref_id = ref_id
            db.add(
                EvidenceAcquisitionEvent(
                    action_id=action.id,
                    from_status=previous,
                    to_status="resolved",
                    note=note or f"resolved via {ref_kind}",
                    actor_id=getattr(principal, "id", None),
                )
            )
            resolved_action = str(action.id)

    recomputed: list[dict[str, Any]] = []
    before_fingerprints = _active_fingerprints(db, field.id)

    # 1) append a fresh feature run when weather/vegetation evidence moved
    staleness = staleness_report(db, field)
    feature_stale = any(
        d["downstream"].get("feature_runs", {}).get("stale")
        for d in staleness["domains"].values()
    )
    if feature_stale:
        try:
            from app.features.service import start_feature_run

            run = start_feature_run(db, field=field, payload={"request_parameters": {"trigger": "evidence_apply"}})
            recomputed.append(
                {"artifact": "feature_runs", "action": "appended_new_run", "ref": str(getattr(run, "id", ""))}
            )
        except Exception as exc:  # noqa: BLE001 — never fail the apply on one engine
            recomputed.append(
                {"artifact": "feature_runs", "action": "failed", "detail": f"{type(exc).__name__}: {exc}"}
            )

    # 2) recommendation refresh (fingerprint diff provides the change record)
    changed_fingerprints: list[str] = []
    try:
        refresh = refresh_field_recommendations(db, field, locale="en")
        after_fingerprints = _active_fingerprints(db, field.id)
        changed_fingerprints = sorted(
            set(after_fingerprints.values()) - set(before_fingerprints.values())
        )
        recomputed.append(
            {
                "artifact": "recommendations",
                "action": "refreshed",
                "ref": None,
                "counts": refresh.get("counts") if isinstance(refresh, dict) else None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        recomputed.append(
            {"artifact": "recommendations", "action": "failed", "detail": f"{type(exc).__name__}: {exc}"}
        )

    db.commit()
    report = {
        "field_id": str(field.id),
        "evidence_ref": {"kind": ref_kind, "id": str(ref_id) if ref_id else None, "detail": ref_detail},
        "resolved_action_id": resolved_action,
        "recomputed": recomputed,
        "changed_recommendation_fingerprints": changed_fingerprints,
        "changed_count": len(changed_fingerprints),
        "note": (
            "Fingerprints are content hashes of recommendation material: a "
            "fingerprint appearing for the first time IS the record of a "
            "changed decision. Unchanged decisions keep their rows (no churn)."
        ),
        "version": EVIDENCE_DEPENDENCIES_VERSION,
    }
    logger.info(
        "evidence applied",
        extra={"field_id": str(field.id), "ref_kind": ref_kind, "changed": len(changed_fingerprints)},
    )
    return report


def _validate_ref(
    db: Session, field: dbm.Field, ref_kind: str, ref_id: uuid.UUID | None
) -> tuple[bool, str]:
    if ref_kind == "ingestion_job":
        if ref_id is None:
            return False, "ingestion_job requires ref_id"
        row = db.scalar(
            select(dbm.IngestionJob).where(
                dbm.IngestionJob.id == ref_id, dbm.IngestionJob.field_id == field.id
            )
        )
        return (row is not None and row.status == "succeeded"), f"ingestion job status: {getattr(row, 'status', None)}"
    if ref_kind == "soil_sample":
        if ref_id is None:
            return False, "soil_sample requires ref_id"
        row = db.scalar(
            select(SoilMeasurement).where(
                SoilMeasurement.id == ref_id, SoilMeasurement.field_id == field.id
            )
        )
        return row is not None, "soil measurement" if row else "not found"
    if ref_kind == "crop_history":
        if ref_id is None:
            return False, "crop_history requires ref_id"
        row = db.scalar(
            select(dbm.CropHistory).where(
                dbm.CropHistory.id == ref_id, dbm.CropHistory.field_id == field.id
            )
        )
        return row is not None, "crop history row" if row else "not found"
    if ref_kind == "water_plan":
        if ref_id is None:
            return False, "water_plan requires ref_id"
        row = db.scalar(
            select(dbm.WaterPlan).where(
                dbm.WaterPlan.id == ref_id, dbm.WaterPlan.field_id == field.id
            )
        )
        return row is not None, "water plan" if row else "not found"
    if ref_kind == "field_state":
        if ref_id is None:
            return False, "field_state requires ref_id"
        row = db.scalar(
            select(dbm.FieldState).where(
                dbm.FieldState.id == ref_id, dbm.FieldState.field_id == field.id
            )
        )
        return row is not None, "field state" if row else "not found"
    return False, f"unknown evidence ref kind '{ref_kind}'"


def _active_fingerprints(db: Session, field_id: uuid.UUID) -> dict[str, str]:
    from app.db.models_ai import AIRecommendation

    rows = db.scalars(
        select(AIRecommendation).where(
            AIRecommendation.field_id == field_id,
            AIRecommendation.status == "active",
        )
    )
    return {str(r.id): (r.fingerprint or "") for r in rows}

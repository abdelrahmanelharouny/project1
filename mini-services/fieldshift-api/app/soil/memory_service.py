"""Soil Memory service (P2.C) — DB bridge for snapshots, change estimates,
timeline and alerts.

Reads the EXISTING immutable soil tables (measurements, management events,
nutrient applications/removals, crop history, SOC stock runs, nutrient
budget runs, erosion assessments), assembles checksummed snapshots, computes
conservative change estimates between snapshots and derives alerts. Rows are
never modified: snapshots are append-only and idempotent by checksum.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.db.models_m6bc_m7 import (
    NutrientApplication,
    NutrientBudgetRun,
    NutrientRemoval,
    SocStockRun,
    SoilManagementEvent,
    SoilMeasurement,
)
from app.db.models_p2 import SoilChangeEstimate, SoilStateSnapshot
from app.soil import memory as memory_core
from app.soil.chemistry import salinity_class_for_ece

logger = logging.getLogger("croptwist.soil.memory")

SNAPSHOT_VARIABLE_FAMILY = "soil"


def _measurement_rows(
    db: Session, field_id: uuid.UUID, as_of: date
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(SoilMeasurement)
            .where(SoilMeasurement.field_id == field_id, SoilMeasurement.observed_at <= as_of)
            .order_by(SoilMeasurement.observed_at.asc())
        )
    )
    return [
        {
            "variable_code": r.variable_code,
            "value": r.value,
            "unit": r.unit,
            "top_depth_cm": r.top_depth_cm,
            "bottom_depth_cm": r.bottom_depth_cm,
            "evidence_class": r.evidence_class,
            "source_kind": r.source_kind,
            "quality_status": r.quality_status,
            "observed_at": r.observed_at.isoformat(),
            "method_id": str(r.method_id) if r.method_id else None,
            "is_synthetic": r.is_synthetic,
        }
        for r in rows
    ]


def _management_rows(db: Session, field_id: uuid.UUID, as_of: date) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(SoilManagementEvent)
            .where(SoilManagementEvent.field_id == field_id, SoilManagementEvent.event_date <= as_of)
            .order_by(SoilManagementEvent.event_date.asc())
        )
    )
    return [
        {
            "event_type": r.event_type,
            "title": r.title,
            "event_date": r.event_date.isoformat(),
            "details": r.details,
            "id": str(r.id),
        }
        for r in rows
    ]


def _nutrient_rows(db: Session, field_id: uuid.UUID, as_of: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    apps = list(
        db.scalars(
            select(NutrientApplication)
            .where(NutrientApplication.field_id == field_id, NutrientApplication.application_date <= as_of)
            .order_by(NutrientApplication.application_date.asc())
        )
    )
    rems = list(
        db.scalars(
            select(NutrientRemoval)
            .where(NutrientRemoval.field_id == field_id, NutrientRemoval.removal_date <= as_of)
            .order_by(NutrientRemoval.removal_date.asc())
        )
    )
    inputs = [
        {
            "id": str(a.id),
            "application_date": a.application_date.isoformat(),
            "product_id": str(a.product_id) if a.product_id else None,
            "input_kind": getattr(a, "input_kind", None),
            "details": a.metadata,
        }
        for a in apps
    ]
    outputs = [
        {
            "id": str(r.id),
            "removal_date": r.removal_date.isoformat(),
            "output_kind": r.output_kind,
            "details": r.metadata,
        }
        for r in rems
    ]
    return inputs, outputs


def _crop_history_rows(db: Session, field_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(dbm.CropHistory)
            .where(dbm.CropHistory.field_id == field_id)
            .order_by(dbm.CropHistory.sowing_date.asc().nullslast())
        )
    )
    return [
        {
            "crop_label": h.crop_label,
            "sowing_date": h.sowing_date.isoformat() if h.sowing_date else None,
            "harvest_date": h.harvest_date.isoformat() if h.harvest_date else None,
            "season_label": h.season_label,
        }
        for h in rows
    ]


def _soc_stock_rows(db: Session, field_id: uuid.UUID) -> list[dict[str, Any]]:
    """Succeeded single_profile SOC stock runs → comparable stock points."""
    rows = list(
        db.scalars(
            select(SocStockRun)
            .where(
                SocStockRun.field_id == field_id,
                SocStockRun.status == "succeeded",
                SocStockRun.comparison_mode == "single_profile",
            )
            .order_by(SocStockRun.created_at.asc())
        )
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        result = r.result or {}
        total = (result.get("profile_total") or {}).get("soc_stock_mg_ha")
        observed_at = result.get("as_of") or (r.created_at.date().isoformat() if r.created_at else None)
        comparable_key = json.dumps(
            sorted((result.get("depth_coverage") or {}).keys())
            if isinstance(result.get("depth_coverage"), dict)
            else [],
            sort_keys=True,
        )
        out.append(
            {
                "observed_at": observed_at,
                "total_stock_mg_ha": total,
                "comparable_key": f"depths:{comparable_key}",
                "run_id": str(r.id),
                "source_ref": {"type": "soc_stock_run", "id": str(r.id), "label": "SOC stock run"},
            }
        )
    return out


def _latest_budget_summary(db: Session, field_id: uuid.UUID) -> dict[str, Any] | None:
    runs = list(
        db.scalars(
            select(NutrientBudgetRun)
            .where(NutrientBudgetRun.field_id == field_id, NutrientBudgetRun.status == "succeeded")
            .order_by(NutrientBudgetRun.created_at.desc())
            .limit(1)
        )
    )
    if not runs:
        return None
    run = runs[0]
    result = run.result or {}
    cumulative = result.get("cumulative_balance_kg_ha") or result.get("balance") or {}
    elements = {}
    for element, key in (("n", "N"), ("p", "P"), ("k", "K")):
        value = cumulative.get(key)
        if value is not None:
            elements[element] = {"net_kg_ha": float(value)}
    return {
        "elements": elements,
        "source_ref": {"type": "nutrient_budget_run", "id": str(run.id), "label": "nutrient budget run"},
    }


def _salinity_context(db: Session, field_id: uuid.UUID) -> dict[str, Any] | None:
    """Latest ECe-family measurement → FAO salinity class (ECe only)."""
    rows = list(
        db.scalars(
            select(SoilMeasurement)
            .where(
                SoilMeasurement.field_id == field_id,
                SoilMeasurement.variable_code.ilike("%electrical_conductivity%"),
            )
            .order_by(SoilMeasurement.observed_at.desc())
            .limit(1)
        )
    )
    if not rows:
        return None
    row = rows[0]
    if row.value is None:
        return None
    # FAO classes are ECe (saturated paste); other methods are refused
    # upstream by the chemistry engine — honour that here.
    method_params = row.method_params or {}
    if str(method_params.get("extract_type", "")).lower() not in ("saturated_paste", "ece"):
        return {
            "class": None,
            "note": (
                "latest EC measurement is not ECe (saturated paste); FAO salinity "
                "classification refused rather than approximated"
            ),
        }
    classified = salinity_class_for_ece(float(row.value))
    return {
        "class": classified.get("salinity_class"),
        "ec_ds_m": classified.get("ec_value"),
        "source_ref": {"type": "soil_measurement", "id": str(row.id), "label": "soil ECe measurement"},
    }


def _erosion_context(db: Session, field_id: uuid.UUID) -> dict[str, Any] | None:
    runs = list(
        db.scalars(
            select(dbm.ErosionAssessmentRun)
            .where(dbm.ErosionAssessmentRun.field_id == field_id, dbm.ErosionAssessmentRun.status == "succeeded")
            .order_by(dbm.ErosionAssessmentRun.created_at.desc())
            .limit(1)
        )
    )
    if not runs:
        return None
    run = runs[0]
    result = run.result or {}
    concern = bool(result.get("concern")) or bool(result.get("risk_flags"))
    return {
        "concern": concern,
        "severity": "advisory",
        "detail": (
            "The erosion screening run flags risk factors for this field "
            "(see the erosion assessment for the factor breakdown)."
        ),
        "source_ref": {"type": "erosion_assessment_run", "id": str(run.id), "label": "erosion assessment"},
    }


def create_snapshot(
    db: Session,
    field: dbm.Field,
    *,
    as_of: date,
    created_by: Any = None,
) -> dict[str, Any]:
    """Assemble + persist one immutable soil state snapshot."""
    if as_of > date.today():
        raise ValidationFailed(
            "as_of cannot be in the future.",
            details=[{"field": "as_of", "reason": as_of.isoformat()}],
        )
    measurements = _measurement_rows(db, field.id, as_of)
    management = _management_rows(db, field.id, as_of)
    nutrient_inputs, nutrient_outputs = _nutrient_rows(db, field.id, as_of)
    crop_history = _crop_history_rows(db, field.id)

    missing: list[str] = []
    if not measurements:
        missing.append("no soil measurements exist on or before as_of")
    if not nutrient_inputs and not nutrient_outputs:
        missing.append("no nutrient application/removal records")
    if not crop_history:
        missing.append("no crop history rows")

    document = memory_core.build_snapshot_document(
        field_id=str(field.id),
        as_of=as_of,
        measurements=measurements,
        management_events=management,
        nutrient_inputs=nutrient_inputs,
        nutrient_outputs=nutrient_outputs,
        crop_history=crop_history,
        missing_evidence=missing,
    )
    checksum = memory_core.snapshot_checksum(document)
    existing = db.scalar(
        select(SoilStateSnapshot).where(
            SoilStateSnapshot.field_id == field.id,
            SoilStateSnapshot.checksum_sha256 == checksum,
        )
    )
    if existing is not None:
        return snapshot_payload(db, existing)

    snapshot = SoilStateSnapshot(
        field_id=field.id,
        as_of=datetime.combine(as_of, datetime.min.time()).replace(tzinfo=UTC),
        snapshot=document,
        source_refs=_source_refs(db, field.id),
        missing_evidence=missing,
        engine_version=memory_core.SOIL_MEMORY_VERSION,
        checksum_sha256=checksum,
        created_by=getattr(created_by, "id", None),
    )
    db.add(snapshot)
    db.flush()
    db.commit()
    logger.info("soil snapshot created", extra={"field_id": str(field.id), "checksum": checksum[:12]})
    return snapshot_payload(db, snapshot)


def _source_refs(db: Session, field_id: uuid.UUID) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    runs = list(
        db.scalars(
            select(SocStockRun.id)
            .where(SocStockRun.field_id == field_id, SocStockRun.status == "succeeded")
            .order_by(SocStockRun.created_at.desc())
            .limit(5)
        )
    )
    refs.extend({"type": "soc_stock_run", "id": str(r)} for r in runs)
    budgets = list(
        db.scalars(
            select(NutrientBudgetRun.id)
            .where(NutrientBudgetRun.field_id == field_id, NutrientBudgetRun.status == "succeeded")
            .order_by(NutrientBudgetRun.created_at.desc())
            .limit(5)
        )
    )
    refs.extend({"type": "nutrient_budget_run", "id": str(r)} for r in budgets)
    return refs


def create_change_estimate(
    db: Session,
    field: dbm.Field,
    *,
    start_snapshot_id: uuid.UUID,
    end_snapshot_id: uuid.UUID,
) -> dict[str, Any]:
    """Compute + persist conservative change estimates between two snapshots."""
    start = db.scalar(select(SoilStateSnapshot).where(SoilStateSnapshot.id == start_snapshot_id))
    end = db.scalar(select(SoilStateSnapshot).where(SoilStateSnapshot.id == end_snapshot_id))
    if start is None or end is None or start.field_id != field.id or end.field_id != field.id:
        raise NotFound(
            "Snapshots not found for this field.",
            details=[{"start": str(start_snapshot_id), "end": str(end_snapshot_id)}],
        )
    if end.as_of <= start.as_of:
        raise ValidationFailed(
            "end snapshot must be later than start snapshot.",
            details=[{"start": start.as_of.isoformat(), "end": end.as_of.isoformat()}],
        )

    # SOC trajectory from the SOC stock runs (documented two-point model).
    soc_rows = _soc_stock_rows(db, field.id)
    soc_trajectory = memory_core.soc_fixed_depth_trajectory(soc_stocks=soc_rows)

    budget = _latest_budget_summary(db, field.id)
    salinity = _salinity_context(db, field.id)
    erosion = _erosion_context(db, field.id)
    alerts = memory_core.soil_alerts(
        nutrient_budget=budget,
        salinity=salinity,
        soc_trajectory=soc_trajectory,
        erosion=erosion,
    )

    result = {
        "soc_trajectory": soc_trajectory,
        "nutrient_budget_context": budget,
        "estimated": True,
        "window": {
            "start": start.as_of.date().isoformat(),
            "end": end.as_of.date().isoformat(),
        },
        "note": (
            "Change estimates are MODEL outputs over documented evidence — "
            "the platform never presents them as measured field improvement."
        ),
    }
    assumptions = list(soc_trajectory.get("assumptions") or [])
    payload = {
        "method": "soil_change_conservative_v1",
        "result": result,
        "window": result["window"],
    }
    checksum = memory_core.snapshot_checksum(payload)
    existing = db.scalar(
        select(SoilChangeEstimate).where(
            SoilChangeEstimate.field_id == field.id,
            SoilChangeEstimate.start_snapshot_id == start.id,
            SoilChangeEstimate.end_snapshot_id == end.id,
            SoilChangeEstimate.method == "soil_change_conservative_v1",
            SoilChangeEstimate.checksum_sha256 == checksum,
        )
    )
    if existing is not None:
        return estimate_payload(existing, alerts)
    estimate = SoilChangeEstimate(
        field_id=field.id,
        start_snapshot_id=start.id,
        end_snapshot_id=end.id,
        method="soil_change_conservative_v1",
        model_version=memory_core.SOIL_MEMORY_VERSION,
        result=result,
        assumptions=assumptions,
        uncertainty=soc_trajectory.get("uncertainty"),
        checksum_sha256=checksum,
    )
    db.add(estimate)
    db.flush()
    db.commit()
    return estimate_payload(estimate, alerts)


def timeline(db: Session, field: dbm.Field) -> dict[str, Any]:
    """The soil memory timeline: measurements, interventions, snapshots,
    missing evidence — ordered by time, evidence classes preserved."""
    snapshots = list(
        db.scalars(
            select(SoilStateSnapshot)
            .where(SoilStateSnapshot.field_id == field.id)
            .order_by(SoilStateSnapshot.as_of.asc())
        )
    )
    measurements = _measurement_rows(db, field.id, date.today())
    management = _management_rows(db, field.id, date.today())
    events: list[dict[str, Any]] = []
    for m in measurements:
        events.append(
            {
                "kind": "measurement",
                "date": m["observed_at"],
                "variable_code": m["variable_code"],
                "value": m["value"],
                "unit": m["unit"],
                "depth": [m["top_depth_cm"], m["bottom_depth_cm"]],
                "evidence_class": m["evidence_class"],
                "source_kind": m["source_kind"],
            }
        )
    for e in management:
        events.append({"kind": "management", "date": e["event_date"], "event_type": e["event_type"], "title": e.get("title")})
    for s in snapshots:
        events.append(
            {
                "kind": "snapshot",
                "date": s.as_of.date().isoformat(),
                "snapshot_id": str(s.id),
                "checksum": s.checksum_sha256[:12],
            }
        )
    events.sort(key=lambda e: str(e["date"]))
    return {
        "field_id": str(field.id),
        "events": events,
        "snapshots": [
            {
                "id": str(s.id),
                "as_of": s.as_of.date().isoformat(),
                "checksum_sha256": s.checksum_sha256,
                "missing_evidence": s.missing_evidence,
                "variable_count": len((s.snapshot or {}).get("variables", [])),
            }
            for s in snapshots
        ],
        "engine_version": memory_core.SOIL_MEMORY_VERSION,
        "note": "History is append-only: measurements are never overwritten, snapshots are checksummed.",
    }


def estimate_payload(estimate: SoilChangeEstimate, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(estimate.id),
        "field_id": str(estimate.field_id),
        "start_snapshot_id": str(estimate.start_snapshot_id),
        "end_snapshot_id": str(estimate.end_snapshot_id),
        "method": estimate.method,
        "model_version": estimate.model_version,
        "result": estimate.result,
        "assumptions": estimate.assumptions,
        "uncertainty": estimate.uncertainty,
        "checksum_sha256": estimate.checksum_sha256,
        "created_at": estimate.created_at.isoformat() if estimate.created_at else None,
        "alerts": alerts,
    }


def snapshot_payload(db: Session, snapshot: SoilStateSnapshot) -> dict[str, Any]:
    alerts = current_alerts(db, snapshot.field_id)
    return {
        "id": str(snapshot.id),
        "field_id": str(snapshot.field_id),
        "as_of": snapshot.as_of.date().isoformat(),
        "snapshot": snapshot.snapshot,
        "source_refs": snapshot.source_refs,
        "missing_evidence": snapshot.missing_evidence,
        "engine_version": snapshot.engine_version,
        "checksum_sha256": snapshot.checksum_sha256,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "alerts": alerts,
    }


def current_alerts(db: Session, field_id: uuid.UUID) -> list[dict[str, Any]]:
    soc_trajectory = memory_core.soc_fixed_depth_trajectory(soc_stocks=_soc_stock_rows(db, field_id))
    budget = _latest_budget_summary(db, field_id)
    salinity = _salinity_context(db, field_id)
    erosion = _erosion_context(db, field_id)
    return memory_core.soil_alerts(
        nutrient_budget=budget,
        salinity=salinity,
        soc_trajectory=soc_trajectory,
        erosion=erosion,
    )

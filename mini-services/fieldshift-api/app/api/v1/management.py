"""Field management endpoints (M6C).

Increment 3 exposes the soil-cover surface: observations (tenant-scoped
CRUD), the computed timeline and the cover metrics. Later increments add
cover-crop planning, residue ledger, erosion, operations and management plans
to the same router.
"""

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal
from app.management import soil_cover as sc_engine

router = APIRouter(tags=["management"])

_COVER_STATES = (
    "living_main_crop", "living_cover_crop", "surface_residue",
    "mulch", "bare", "unknown", "mixed",
)
_MEASUREMENT_BASES = (
    "visual_estimate", "line_point_transect", "canopy_scope",
    "quadrat", "remote_sensing_index", "unknown",
)


def _parse_date(value: Any, name: str) -> Any:
    from datetime import date as _date

    try:
        return _date.fromisoformat(str(value))
    except ValueError:
        raise ValidationFailed(
            f"{name} must be an ISO date (YYYY-MM-DD).",
            details=[{"field": name}],
        ) from None


# ------------------------------------------------------------- soil cover
@router.post("/fields/{field_id}/soil-cover/observations", status_code=status.HTTP_201_CREATED)
def create_cover_observation(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    cover_state = str(body.get("cover_state") or "unknown")
    if cover_state not in _COVER_STATES:
        raise ValidationFailed(
            f"unknown cover_state '{cover_state}' (allowed: {', '.join(_COVER_STATES)}).",
            details=[{"field": "cover_state"}],
        )
    basis = str(body.get("measurement_basis") or "visual_estimate")
    if basis not in _MEASUREMENT_BASES:
        raise ValidationFailed(
            f"unknown measurement_basis '{basis}'.",
            details=[{"field": "measurement_basis"}],
        )
    fraction = body.get("cover_fraction")
    if fraction is not None:
        try:
            fraction = float(fraction)
        except (TypeError, ValueError):
            raise ValidationFailed(
                "cover_fraction must be a number in [0, 1].",
                details=[{"field": "cover_fraction"}],
            ) from None
        if not (0.0 <= fraction <= 1.0):
            raise ValidationFailed(
                "cover_fraction must be within [0, 1] — out-of-range values are "
                "rejected, never clamped.",
                details=[{"field": "cover_fraction"}],
            )
    index_type = body.get("index_type")
    index_value = body.get("index_value")
    if (index_type is None) != (index_value is None):
        raise ValidationFailed(
            "index_type and index_value must be provided together (an index "
            "reading without its kind carries no meaning).",
            details=[{"field": "index_type"}],
        )
    evidence_class = str(body.get("evidence_class") or "farmer_reported_record")
    if basis == "remote_sensing_index" and evidence_class == "farmer_reported_record":
        evidence_class = "remote_sensing_estimate"

    obs = dbm.SoilCoverObservation(
        field_id=field.id,
        observed_date=_parse_date(body.get("observed_date"), "observed_date"),
        cover_state=cover_state,
        cover_fraction=fraction,
        measurement_basis=basis,
        index_type=index_type,
        index_value=float(index_value) if index_value is not None else None,
        evidence_class=evidence_class,
        notes=body.get("notes"),
        metadata=dict(body.get("metadata") or {}),
        created_by=principal.id,
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return _observation_payload(obs)


@router.get("/fields/{field_id}/soil-cover/observations")
def list_cover_observations(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.SoilCoverObservation)
        .where(dbm.SoilCoverObservation.field_id == field.id)
        .order_by(dbm.SoilCoverObservation.observed_date.desc())
        .limit(365)
    ).all()
    return {"field_id": str(field.id), "items": [_observation_payload(r) for r in rows]}


def _observation_payload(obs: dbm.SoilCoverObservation) -> dict[str, Any]:
    return {
        "id": str(obs.id),
        "observed_date": obs.observed_date.isoformat(),
        "cover_state": obs.cover_state,
        "cover_fraction": obs.cover_fraction,
        "measurement_basis": obs.measurement_basis,
        "index_type": obs.index_type,
        "index_value": obs.index_value,
        "evidence_class": obs.evidence_class,
        "notes": obs.notes,
        "metadata": obs.metadata,
    }


def _load_timeline_inputs(db: Session, field_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    crops = db.scalars(
        select(dbm.CropHistory).where(dbm.CropHistory.field_id == field_id)
    ).all()
    covers = db.scalars(
        select(dbm.CoverCropPlanItem).where(dbm.CoverCropPlanItem.field_id == field_id)
    ).all()
    events = db.scalars(
        select(dbm.SoilManagementEvent).where(dbm.SoilManagementEvent.field_id == field_id)
    ).all()
    observations = db.scalars(
        select(dbm.SoilCoverObservation).where(dbm.SoilCoverObservation.field_id == field_id)
    ).all()
    return {
        "crop_history": [
            {"id": str(c.id), "crop_label": c.crop_label, "sowing_date": c.sowing_date, "harvest_date": c.harvest_date, "evidence_class": c.evidence_class}
            for c in crops
        ],
        "cover_crop_items": [
            {"id": str(c.id), "crop_label": c.crop_label, "intended_sowing_start": c.intended_sowing_start, "intended_termination_window_start": c.intended_termination_window_start, "established_date": (c.metadata or {}).get("established_date"), "terminated_date": (c.metadata or {}).get("terminated_date"), "evidence_class": c.evidence_class}
            for c in covers
        ],
        "management_events": [
            {"id": str(e.id), "event_date": e.event_date, "event_type": e.event_type, "title": e.title, "details": e.details}
            for e in events
        ],
        "cover_observations": [
            {"id": str(o.id), "observed_date": o.observed_date, "cover_state": o.cover_state, "cover_fraction": o.cover_fraction, "measurement_basis": o.measurement_basis, "index_type": o.index_type, "index_value": o.index_value, "evidence_class": o.evidence_class}
            for o in observations
        ],
    }


def _window_from_request(
    request: dict[str, Any] | None, body: dict[str, Any] | None = None
) -> tuple[Any, Any]:
    src = body or request or {}
    start = src.get("window_start")
    end = src.get("window_end")
    if not start or not end:
        raise ValidationFailed(
            "window_start and window_end (ISO dates) are required — the "
            "timeline is computed over an explicit window.",
            details=[{"field": "window_start"}],
        )
    return _parse_date(start, "window_start"), _parse_date(end, "window_end")


@router.get("/fields/{field_id}/soil-cover/timeline")
def get_cover_timeline(
    field_id: uuid.UUID,
    window_start: str = Query(...),
    window_end: str = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    start = _parse_date(window_start, "window_start")
    end = _parse_date(window_end, "window_end")
    if end < start:
        raise ValidationFailed(
            "window_end before window_start.", details=[{"field": "window_end"}]
        )
    if (end - start).days > 760:
        raise ValidationFailed(
            "cover timeline window is limited to ~2 years per request.",
            details=[{"field": "window_end"}],
        )
    inputs = _load_timeline_inputs(db, field.id)
    result = sc_engine.build_cover_timeline(
        window_start=start,
        window_end=end,
        crop_history=inputs["crop_history"],
        cover_crop_items=inputs["cover_crop_items"],
        management_events=inputs["management_events"],
        cover_observations=inputs["cover_observations"],
    )
    result["field_id"] = str(field.id)
    result["inputs_summary"] = {
        "crop_history_rows": len(inputs["crop_history"]),
        "cover_crop_items": len(inputs["cover_crop_items"]),
        "management_events": len(inputs["management_events"]),
        "cover_observations": len(inputs["cover_observations"]),
    }
    return result


@router.get("/fields/{field_id}/soil-cover/metrics")
def get_cover_metrics(
    field_id: uuid.UUID,
    window_start: str = Query(...),
    window_end: str = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    result = get_cover_timeline(
        field_id=field_id,
        window_start=window_start,
        window_end=window_end,
        principal=principal,
        db=db,
    )
    return {
        "field_id": result["field_id"],
        "window": result["window"],
        "metrics": result["metrics"],
        "thresholds": result["thresholds"],
        "method": result["method"],
        "evidence_notes": result["evidence_notes"],
        "inputs_summary": result["inputs_summary"],
    }


# ---------------------------------------------------------- cover-crop plans
def _cover_plan_checksum(result: dict[str, Any], params: dict[str, Any], run: dbm.CoverCropPlan) -> str:
    import hashlib
    import json

    payload = {
        "engine": run.engine_version,
        "methods": run.methods_version,
        "window": [run.window_start.isoformat() if run.window_start else None,
                   run.window_end.isoformat() if run.window_end else None],
        "next_crop": run.next_crop_label,
        "request": params,
        "result": result,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cover_plan_payload(plan: dbm.CoverCropPlan, *, include_result: bool = True) -> dict[str, Any]:
    out = {
        "id": str(plan.id),
        "field_id": str(plan.field_id),
        "status": plan.status,
        "label": plan.label,
        "window": {
            "start": plan.window_start.isoformat() if plan.window_start else None,
            "end": plan.window_end.isoformat() if plan.window_end else None,
        },
        "next_crop_label": plan.next_crop_label,
        "engine_version": plan.engine_version,
        "methods_version": plan.methods_version,
        "knowledge_pack_refs": plan.knowledge_pack_refs,
        "feature_run_ids": plan.feature_run_ids,
        "water_plan_ids": plan.water_plan_ids,
        "warnings": plan.warnings,
        "not_evaluated": plan.not_evaluated,
        "request_parameters": plan.request_parameters,
        "checksum_sha256": plan.checksum_sha256,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "error_summary": plan.error_summary,
    }
    if include_result:
        out["result"] = plan.result
    return out


@router.post("/fields/{field_id}/cover-crop-plans", status_code=status.HTTP_201_CREATED)
def create_cover_crop_plan(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Evaluate cover-crop candidates for a window and snapshot the result
    (immutable; recomputation creates a NEW plan row)."""
    from app.knowledge.service import load_knowledge
    from app.rotation.service import _pick_evidence_run, _season_climate, _soil_evidence
    from app.management.contracts import MANAGEMENT_ENGINE_VERSION, MANAGEMENT_METHODS_VERSION

    field = get_field_for_principal(db, principal, field_id)
    window_start = _parse_date(body.get("window_start"), "window_start")
    window_end = _parse_date(body.get("window_end"), "window_end")
    if window_end < window_start:
        raise ValidationFailed("window_end before window_start.", details=[{"field": "window_end"}])
    if (window_end - window_start).days > 500:
        raise ValidationFailed(
            "cover-crop plan window is limited to ~16 months per plan.",
            details=[{"field": "window_end"}],
        )
    next_crop_label = body.get("next_crop_label")
    next_crop_sowing = (
        _parse_date(body["next_crop_sowing_date"], "next_crop_sowing_date")
        if body.get("next_crop_sowing_date") else None
    )
    farmer_excluded = [str(c) for c in (body.get("excluded_crop_codes") or [])]
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.CoverCropPlan).where(
                dbm.CoverCropPlan.field_id == field.id,
                dbm.CoverCropPlan.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            return _cover_plan_payload(existing)

    farm = field.farm
    knowledge = load_knowledge(db)
    run = _pick_evidence_run(db, field.id, body.get("feature_run_id"))
    evidence = _season_climate(run, SeasonSpecForCover(window_start, window_end)) if run is not None else None
    soil, soil_warning = _soil_evidence(db, field.id)

    from app.management.cover_crops import evaluate_cover_candidates

    evaluation = evaluate_cover_candidates(
        knowledge,
        window_start=window_start,
        window_end=window_end,
        hemisphere="south" if farm.timezone and _south_hemisphere(farm.country_code) else "north",
        country_code=farm.country_code,
        evidence=evidence,
        soil=soil,
        soil_warning=soil_warning,
        rules=list(knowledge.rules),
        next_crop_sowing=next_crop_sowing,
        next_crop_label=next_crop_label,
        farmer_excluded_codes=farmer_excluded,
    )

    warnings: list[str] = []
    if evidence is not None and evidence.is_synthetic:
        warnings.append(
            "Climate evidence comes from the SYNTHETIC test fixture — never "
            "real farm evidence; candidate outcomes are demonstration only."
        )
    if evidence is None:
        warnings.append(
            "No succeeded feature run for this field — climate dimensions are "
            "unevaluated (create one in the Features tab)."
        )
    if run is not None:
        warnings.append(
            "Climate aggregates are a month-of-year climatology (historical "
            "proxy), NOT a forecast."
        )

    plan = dbm.CoverCropPlan(
        field_id=field.id,
        status="succeeded",
        label=str(body.get("label") or "Cover-crop plan"),
        window_start=window_start,
        window_end=window_end,
        next_crop_label=next_crop_label,
        engine_version=MANAGEMENT_ENGINE_VERSION,
        methods_version=MANAGEMENT_METHODS_VERSION,
        result=evaluation,
        warnings=warnings,
        not_evaluated=evaluation.get("global_gaps", {}),
        request_parameters={
            "window": [window_start.isoformat(), window_end.isoformat()],
            "next_crop_label": next_crop_label,
            "next_crop_sowing_date": next_crop_sowing.isoformat() if next_crop_sowing else None,
            "excluded_crop_codes": farmer_excluded,
            "feature_run_id": str(run.id) if run is not None else None,
        },
        knowledge_pack_refs=evaluation.get("knowledge_pack_refs", []),
        feature_run_ids=[str(run.id)] if run is not None else [],
        idempotency_key=str(idempotency_key) if idempotency_key else None,
        created_by=principal.id,
    )
    plan.checksum_sha256 = _cover_plan_checksum(evaluation, plan.request_parameters, plan)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _cover_plan_payload(plan)


class SeasonSpecForCover:
    """Adapter giving the rotation climate bridge its SeasonSpec interface."""

    def __init__(self, start: Any, end: Any) -> None:
        from datetime import date as _date

        self.label = "cover_window"
        self.start_date = start if isinstance(start, _date) else _date.fromisoformat(str(start))
        self.end_date = end if isinstance(end, _date) else _date.fromisoformat(str(end))

    @property
    def length_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def _south_hemisphere(country_code: str) -> bool:
    # Temporary narrow mapping for hemisphere defaulting; the field's farm
    # timezone offset is the actual signal used by feature runs. Documented in
    # the method doc — never a claim about a specific country's climate.
    return country_code in {"AU", "NZ", "ZA", "AR", "CL", "UY", "PY", "BO", "PE"}


@router.get("/fields/{field_id}/cover-crop-plans")
def list_cover_crop_plans(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.CoverCropPlan)
        .where(dbm.CoverCropPlan.field_id == field.id)
        .order_by(dbm.CoverCropPlan.created_at.desc())
        .limit(50)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [_cover_plan_payload(p, include_result=False) for p in rows],
        "total": len(rows),
    }


@router.get("/cover-crop-plans/{plan_id}")
def get_cover_crop_plan(
    plan_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    plan = db.get(dbm.CoverCropPlan, plan_id)
    if plan is None:
        raise NotFound("Cover-crop plan not found.")
    get_field_for_principal(db, principal, plan.field_id)  # tenant gate
    return _cover_plan_payload(plan)


# ------------------------------------------------------ cover-crop plan items
@router.post("/fields/{field_id}/cover-crop-plan-items", status_code=status.HTTP_201_CREATED)
def create_cover_crop_plan_item(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Adopt a cover-crop decision (the durable object the cover timeline
    consumes). Establishment/termination events stay in the soil management
    ledger."""
    field = get_field_for_principal(db, principal, field_id)
    crop_label = str(body.get("crop_label") or "").strip()
    if not crop_label:
        raise ValidationFailed("crop_label is required.", details=[{"field": "crop_label"}])
    composition = list(body.get("mixture_composition") or [])
    if composition:
        total = 0.0
        for entry in composition:
            try:
                total += float(entry.get("fraction", 0))
            except (TypeError, ValueError):
                raise ValidationFailed(
                    "mixture_composition entries need numeric fractions.",
                    details=[{"field": "mixture_composition"}],
                ) from None
        if total > 1.0 + 1e-9:
            raise ValidationFailed(
                "mixture fractions must sum to ≤ 1.0 — the remainder stays "
                "'unknown' and is never silently renormalized.",
                details=[{"field": "mixture_composition", "reason": f"sum={total}"}],
            )
    plan_run_id = body.get("plan_run_id")
    if plan_run_id:
        ref = db.get(dbm.CoverCropPlan, uuid.UUID(str(plan_run_id)))
        if ref is None or str(ref.field_id) != str(field.id):
            raise ValidationFailed(
                "plan_run_id does not reference a plan of this field.",
                details=[{"field": "plan_run_id"}],
            )
    item = dbm.CoverCropPlanItem(
        field_id=field.id,
        plan_run_id=uuid.UUID(str(plan_run_id)) if plan_run_id else None,
        crop_label=crop_label,
        is_mixture=bool(composition) or bool(body.get("is_mixture")),
        mixture_composition=composition,
        season_label=body.get("season_label"),
        intended_sowing_start=_parse_date(body["intended_sowing_start"], "intended_sowing_start") if body.get("intended_sowing_start") else None,
        intended_sowing_end=_parse_date(body["intended_sowing_end"], "intended_sowing_end") if body.get("intended_sowing_end") else None,
        intended_termination_window_start=_parse_date(body["intended_termination_window_start"], "intended_termination_window_start") if body.get("intended_termination_window_start") else None,
        intended_termination_window_end=_parse_date(body["intended_termination_window_end"], "intended_termination_window_end") if body.get("intended_termination_window_end") else None,
        intended_termination_method=body.get("intended_termination_method"),
        intended_functions=list(body.get("intended_functions") or []),
        seeding_rate=float(body["seeding_rate"]) if body.get("seeding_rate") is not None else None,
        seeding_rate_unit=body.get("seeding_rate_unit"),
        status=str(body.get("status") or "planned"),
        evidence_class=str(body.get("evidence_class") or "farmer_reported_record"),
        notes=body.get("notes"),
        created_by=principal.id,
        metadata={},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": str(item.id),
        "field_id": str(field.id),
        "crop_label": item.crop_label,
        "is_mixture": item.is_mixture,
        "mixture_composition": item.mixture_composition,
        "status": item.status,
        "season_label": item.season_label,
        "evidence_class": item.evidence_class,
    }


@router.get("/fields/{field_id}/cover-crop-plan-items")
def list_cover_crop_plan_items(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.CoverCropPlanItem)
        .where(dbm.CoverCropPlanItem.field_id == field.id)
        .order_by(dbm.CoverCropPlanItem.created_at.desc())
        .limit(100)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [
            {
                "id": str(i.id),
                "crop_label": i.crop_label,
                "is_mixture": i.is_mixture,
                "mixture_composition": i.mixture_composition,
                "season_label": i.season_label,
                "intended_sowing_start": i.intended_sowing_start.isoformat() if i.intended_sowing_start else None,
                "intended_sowing_end": i.intended_sowing_end.isoformat() if i.intended_sowing_end else None,
                "intended_termination_window_start": i.intended_termination_window_start.isoformat() if i.intended_termination_window_start else None,
                "intended_termination_window_end": i.intended_termination_window_end.isoformat() if i.intended_termination_window_end else None,
                "intended_termination_method": i.intended_termination_method,
                "intended_functions": i.intended_functions,
                "seeding_rate": i.seeding_rate,
                "seeding_rate_unit": i.seeding_rate_unit,
                "status": i.status,
                "plan_run_id": str(i.plan_run_id) if i.plan_run_id else None,
                "evidence_class": i.evidence_class,
            }
            for i in rows
        ],
    }


# ------------------------------------------------------------- residue ledger
def _residue_record_payload(r: dbm.ResidueRecord) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "field_id": str(r.field_id),
        "crop_label": r.crop_label,
        "season_label": r.season_label,
        "basis": r.basis,
        "produced_dm_kg": r.produced_dm_kg,
        "production_status": r.production_status,
        "coefficient_provenance": r.coefficient_provenance,
        "harvested_product_dm_kg": r.harvested_product_dm_kg,
        "harvested_product_status": r.harvested_product_status,
        "notes": r.notes,
        "metadata": r.metadata,
    }


@router.post("/fields/{field_id}/residue-records", status_code=status.HTTP_201_CREATED)
def create_residue_record(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.management.residue import PRODUCTION_STATUSES, ResidueLedgerError

    field = get_field_for_principal(db, principal, field_id)
    production_status = str(body.get("production_status") or "missing")
    if production_status not in PRODUCTION_STATUSES:
        raise ValidationFailed(
            f"unknown production_status '{production_status}'.",
            details=[{"field": "production_status"}],
        )
    provenance = dict(body.get("coefficient_provenance") or {})
    if production_status == "coefficient_estimate":
        if not provenance.get("coefficient") or not provenance.get("source_reference"):
            raise ValidationFailed(
                "coefficient_estimate production requires provenance with at "
                "least the coefficient value and its source reference — "
                "residue production is never inferred from yield without a "
                "sourced, record-specific ratio.",
                details=[{"field": "coefficient_provenance"}],
            )
    produced = body.get("produced_dm_kg")
    if produced is not None:
        produced = float(produced)
        if produced < 0:
            raise ValidationFailed(
                "produced_dm_kg must be >= 0.", details=[{"field": "produced_dm_kg"}]
            )
        if production_status == "missing":
            raise ValidationFailed(
                "production_status 'missing' contradicts a supplied mass — "
                "declare the mass as measured or farmer_reported instead.",
                details=[{"field": "production_status"}],
            )
    crop_label = str(body.get("crop_label") or "").strip()
    if not crop_label:
        raise ValidationFailed("crop_label is required.", details=[{"field": "crop_label"}])
    basis = str(body.get("basis") or "dry_matter")
    if basis not in ("dry_matter", "fresh_weight"):
        raise ValidationFailed("basis must be dry_matter or fresh_weight.", details=[{"field": "basis"}])
    record = dbm.ResidueRecord(
        field_id=field.id,
        crop_id=uuid.UUID(str(body["crop_id"])) if body.get("crop_id") else None,
        crop_label=crop_label,
        season_label=body.get("season_label"),
        basis=basis,
        produced_dm_kg=produced,
        production_status=production_status,
        coefficient_provenance=provenance,
        harvested_product_dm_kg=float(body["harvested_product_dm_kg"]) if body.get("harvested_product_dm_kg") is not None else None,
        harvested_product_status=body.get("harvested_product_status"),
        notes=body.get("notes"),
        metadata=dict(body.get("metadata") or {}),
        created_by=principal.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _residue_record_payload(record)


@router.post("/residue-records/{record_id}/flows", status_code=status.HTTP_201_CREATED)
def create_residue_flow(
    record_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.management.residue import FLOW_TYPES, ResidueLedgerError, _flow_dm_kg

    record = db.get(dbm.ResidueRecord, record_id)
    if record is None:
        raise NotFound("Residue record not found.")
    get_field_for_principal(db, principal, record.field_id)
    flow_type = str(body.get("flow_type") or "")
    if flow_type not in FLOW_TYPES:
        raise ValidationFailed(
            f"unknown flow_type '{flow_type}' (allowed: {', '.join(FLOW_TYPES)}).",
            details=[{"field": "flow_type"}],
        )
    try:
        kg, dm_status = _flow_dm_kg(body)
    except ResidueLedgerError as exc:
        raise ValidationFailed(str(exc), details=[{"field": "dm_kg"}]) from None
    flow = dbm.ResidueFlowEvent(
        residue_record_id=record.id,
        flow_type=flow_type,
        flow_date=_parse_date(body["flow_date"], "flow_date") if body.get("flow_date") else None,
        dm_kg=kg,
        dm_kg_status=dm_status,
        soil_management_event_id=uuid.UUID(str(body["soil_management_event_id"])) if body.get("soil_management_event_id") else None,
        evidence_class=str(body.get("evidence_class") or "farmer_reported_record"),
        notes=body.get("notes"),
        metadata=dict(body.get("metadata") or {}),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return {
        "id": str(flow.id),
        "residue_record_id": str(record.id),
        "flow_type": flow.flow_type,
        "dm_kg": flow.dm_kg,
        "dm_kg_status": flow.dm_kg_status,
        "soil_management_event_id": str(flow.soil_management_event_id) if flow.soil_management_event_id else None,
    }


@router.post("/residue-records/{record_id}/quality", status_code=status.HTTP_201_CREATED)
def create_residue_quality(
    record_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(dbm.ResidueRecord, record_id)
    if record is None:
        raise NotFound("Residue record not found.")
    get_field_for_principal(db, principal, record.field_id)

    def _frac(key: str, hi: float) -> float | None:
        v = body.get(key)
        if v is None:
            return None
        v = float(v)
        if not (0 <= v <= hi):
            raise ValidationFailed(
                f"{key} must be within [0, {hi}].", details=[{"field": key}]
            )
        return v

    quality = dbm.ResidueQualityMeasurement(
        residue_record_id=record.id,
        measured_date=_parse_date(body["measured_date"], "measured_date") if body.get("measured_date") else None,
        carbon_fraction=_frac("carbon_fraction", 100.0),
        nitrogen_pct=_frac("nitrogen_pct", 100.0),
        cn_ratio=_frac("cn_ratio", 10000.0),
        lignin_pct=_frac("lignin_pct", 100.0),
        evidence_class=str(body.get("evidence_class") or "laboratory_measured"),
        method_notes=body.get("method_notes"),
        metadata=dict(body.get("metadata") or {}),
    )
    db.add(quality)
    db.commit()
    db.refresh(quality)
    return {
        "id": str(quality.id),
        "residue_record_id": str(record.id),
        "carbon_fraction": quality.carbon_fraction,
        "nitrogen_pct": quality.nitrogen_pct,
        "cn_ratio": quality.cn_ratio,
        "lignin_pct": quality.lignin_pct,
        "evidence_class": quality.evidence_class,
    }


@router.get("/fields/{field_id}/residue-ledger")
def get_residue_ledger(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.management.residue import build_residue_ledger

    field = get_field_for_principal(db, principal, field_id)
    records = db.scalars(
        select(dbm.ResidueRecord).where(dbm.ResidueRecord.field_id == field.id)
        .order_by(dbm.ResidueRecord.created_at.asc())
    ).all()
    flows = db.scalars(
        select(dbm.ResidueFlowEvent)
        .join(dbm.ResidueRecord, dbm.ResidueFlowEvent.residue_record_id == dbm.ResidueRecord.id)
        .where(dbm.ResidueRecord.field_id == field.id)
        .order_by(dbm.ResidueFlowEvent.created_at.asc())
    ).all()
    qualities = db.scalars(
        select(dbm.ResidueQualityMeasurement)
        .join(dbm.ResidueRecord, dbm.ResidueQualityMeasurement.residue_record_id == dbm.ResidueRecord.id)
        .where(dbm.ResidueRecord.field_id == field.id)
        .order_by(dbm.ResidueQualityMeasurement.created_at.asc())
    ).all()
    flows_by_record: dict[str, list[dict[str, Any]]] = {}
    for f in flows:
        flows_by_record.setdefault(str(f.residue_record_id), []).append(
            {"id": str(f.id), "flow_type": f.flow_type, "flow_date": f.flow_date.isoformat() if f.flow_date else None,
             "dm_kg": f.dm_kg, "dm_kg_status": f.dm_kg_status,
             "soil_management_event_id": str(f.soil_management_event_id) if f.soil_management_event_id else None,
             "evidence_class": f.evidence_class}
        )
    quality_by_record: dict[str, list[dict[str, Any]]] = {}
    for q in qualities:
        quality_by_record.setdefault(str(q.residue_record_id), []).append(
            {"carbon_fraction": q.carbon_fraction, "nitrogen_pct": q.nitrogen_pct,
             "cn_ratio": q.cn_ratio, "lignin_pct": q.lignin_pct, "evidence_class": q.evidence_class}
        )
    result = build_residue_ledger(
        [_residue_record_payload(r) for r in records], flows_by_record, quality_by_record
    )
    result["field_id"] = str(field.id)
    return result


# --------------------------------------------------------- erosion screening
def _erosion_run_payload(run: dbm.ErosionAssessmentRun, *, include_result: bool = True) -> dict[str, Any]:
    out = {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "label": run.label,
        "engine_version": run.engine_version,
        "methods_version": run.methods_version,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "request_parameters": run.request_parameters,
        "checksum_sha256": run.checksum_sha256,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_result:
        out["result"] = run.result
    return out


@router.post("/fields/{field_id}/erosion-assessments", status_code=status.HTTP_201_CREATED)
def create_erosion_assessment(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.management.contracts import MANAGEMENT_ENGINE_VERSION, MANAGEMENT_METHODS_VERSION
    from app.management.erosion import run_erosion_assessment
    from app.management.practices import active_practices
    from app.management.soil_cover import build_cover_timeline

    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.ErosionAssessmentRun).where(
                dbm.ErosionAssessmentRun.field_id == field.id,
                dbm.ErosionAssessmentRun.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            return _erosion_run_payload(existing)

    # Cover metrics over the requested (or default trailing) window.
    window_end = _parse_date(body.get("window_end") or dt_date_today(), "window_end")
    window_start = _parse_date(
        body.get("window_start") or (window_end - dt.timedelta(days=365)),
        "window_start",
    )
    inputs = _load_timeline_inputs(db, field.id)
    cover = build_cover_timeline(
        window_start=window_start,
        window_end=window_end,
        crop_history=inputs["crop_history"],
        cover_crop_items=inputs["cover_crop_items"],
        management_events=inputs["management_events"],
        cover_observations=inputs["cover_observations"],
    )
    cover_metrics = {
        "days_known_bare": cover["metrics"]["days_known_bare"],
        "longest_bare_interval_days": cover["metrics"]["longest_bare_interval_days"],
        "days_unknown": cover["metrics"]["days_unknown"],
    }

    # Rainfall climatology from the latest succeeded feature run (amount only —
    # explicitly NOT an erosivity factor).
    rainfall_evidence = None
    run = db.scalar(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field.id, dbm.FeatureRun.status == "succeeded")
        .order_by(dbm.FeatureRun.completed_at.desc())
        .limit(1)
    )
    if run is not None:
        monthly = [
            (row.period_start.month, row.value)
            for row in run.values
            if row.aggregation_level == "monthly" and row.value is not None
            and row.feature_code == "precipitation_total_monthly"
        ]
        if monthly:
            by_month: dict[int, list[float]] = {}
            for m, v in monthly:
                by_month.setdefault(m, []).append(v)
            means = {m: sum(v) / len(v) for m, v in by_month.items()}
            wettest = max(means, key=lambda m: means[m])
            rainfall_evidence = {
                "wettest_month": wettest,
                "wettest_month_mm": round(means[wettest], 1),
                "feature_run_id": str(run.id),
                "is_synthetic": bool(run.is_synthetic),
            }

    # Management flags from the ledger (qualitative, evidence-carrying).
    management_flags: list[dict[str, Any]] = []
    for event in inputs["management_events"]:
        if event["event_type"] == "residue_removal":
            management_flags.append({
                "code": "residue_removal",
                "processes": ["sheet_interrill", "wind"],
                "message": "residue removal recorded "
                f"({event['event_date']}) — surface protection reduced",
            })
        elif event["event_type"] == "tillage":
            management_flags.append({
                "code": "tillage_disturbance",
                "processes": ["sheet_interrill"],
                "message": f"tillage recorded ({event['event_date']}) — soil "
                "disturbance and temporary cover loss",
            })

    slope_evidence = body.get("slope_evidence")
    if slope_evidence is not None:
        slope_class = str(slope_evidence.get("slope_class") or "unknown")
        if slope_class not in ("flat", "gentle", "moderate", "steep", "unknown"):
            raise ValidationFailed(
                f"unknown slope_class '{slope_class}'.",
                details=[{"field": "slope_evidence.slope_class"}],
            )

    request_params = {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "rusle_factors": body.get("rusle_factors"),
        "slope_evidence": slope_evidence,
        "observed_signs": body.get("observed_signs") or [],
        "feature_run_id": str(run.id) if run is not None else None,
    }

    result = run_erosion_assessment(
        rusle_factors=body.get("rusle_factors"),
        slope_evidence=slope_evidence,
        soil_evidence=body.get("soil_evidence"),
        cover_metrics=cover_metrics,
        rainfall_evidence=rainfall_evidence,
        management_flags=management_flags,
        observed_signs=body.get("observed_signs") or [],
        practices=active_practices(db),
    )
    if rainfall_evidence and rainfall_evidence.get("is_synthetic"):
        result["warnings"].append(
            "Rainfall evidence comes from a SYNTHETIC fixture — screening "
            "flags are demonstration only."
        )

    import hashlib
    import json as _json

    checksum = hashlib.sha256(
        _json.dumps(
            {"result": result, "request": request_params,
             "engine": MANAGEMENT_ENGINE_VERSION, "methods": MANAGEMENT_METHODS_VERSION},
            sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")
    ).hexdigest()

    erosion_run = dbm.ErosionAssessmentRun(
        field_id=field.id,
        status="succeeded",
        label=str(body.get("label") or "Erosion assessment"),
        engine_version=MANAGEMENT_ENGINE_VERSION,
        methods_version=MANAGEMENT_METHODS_VERSION,
        result=result,
        warnings=result["warnings"],
        not_evaluated=result["not_evaluated"],
        request_parameters=request_params,
        idempotency_key=str(idempotency_key) if idempotency_key else None,
        checksum_sha256=checksum,
        created_by=principal.id,
    )
    db.add(erosion_run)
    db.commit()
    db.refresh(erosion_run)
    return _erosion_run_payload(erosion_run)


def dt_date_today():
    from datetime import date

    return date.today().isoformat()


@router.get("/fields/{field_id}/erosion-assessments")
def list_erosion_assessments(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.ErosionAssessmentRun)
        .where(dbm.ErosionAssessmentRun.field_id == field.id)
        .order_by(dbm.ErosionAssessmentRun.created_at.desc())
        .limit(50)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [_erosion_run_payload(r, include_result=False) for r in rows],
        "total": len(rows),
    }


@router.get("/erosion-assessments/{run_id}")
def get_erosion_assessment(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(dbm.ErosionAssessmentRun, run_id)
    if run is None:
        raise NotFound("Erosion assessment not found.")
    get_field_for_principal(db, principal, run.field_id)
    return _erosion_run_payload(run)


@router.get("/fields/{field_id}/erosion-readiness")
def get_erosion_readiness(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """What the erosion pathways could use today — honest data readiness."""
    field = get_field_for_principal(db, principal, field_id)
    inputs = _load_timeline_inputs(db, field.id)
    has_cover = bool(inputs["crop_history"] or inputs["cover_observations"] or inputs["management_events"])
    run = db.scalar(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field.id, dbm.FeatureRun.status == "succeeded")
        .limit(1)
    )
    return {
        "field_id": str(field.id),
        "qualitative_screening": {
            "available": has_cover,
            "inputs_present": {
                "crop_history": len(inputs["crop_history"]),
                "cover_observations": len(inputs["cover_observations"]),
                "management_events": len(inputs["management_events"]),
            },
            "missing_inputs": [] if has_cover else ["cover evidence (crop history, observations or events)"],
        },
        "rusle_family": {
            "available": False,
            "missing_inputs": [
                "R, K, LS, C, P factors with local provenance (farmer/sourced; "
                "the platform ships none)",
                "no DEM exists in the platform — LS must be supplied, never "
                "computed from the field polygon",
            ],
            "note": "The model pathway activates only when ALL five factors "
            "arrive with provenance and one unit convention.",
        },
        "processes_out_of_scope": [
            "ephemeral_gully", "classical_gully", "wind (quantitative)",
            "streambank", "sediment_delivery",
        ],
    }


# ------------------------------------------------- resources & operations
@router.post("/farms/{farm_id}/resources", status_code=status.HTTP_201_CREATED)
def create_farm_resource(
    farm_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = db.get(dbm.Farm, farm_id)
    if farm is None:
        raise NotFound("Farm not found.")
    principal.require_member_of(farm.organization_id)
    resource_type = str(body.get("resource_type") or "")
    allowed = {"tractor", "implement", "seeder", "sprayer", "harvester", "baler",
               "irrigation_equipment", "contractor", "labor_crew", "storage",
               "transport", "other"}
    if resource_type not in allowed:
        raise ValidationFailed(
            f"unknown resource_type '{resource_type}'.", details=[{"field": "resource_type"}]
        )
    availability = list(body.get("availability_calendar") or [])
    for w in availability:
        if not w.get("from") or not w.get("to"):
            raise ValidationFailed(
                "availability windows need from/to dates.",
                details=[{"field": "availability_calendar"}],
            )
    efficiency = body.get("field_efficiency")
    if efficiency is not None and not (0 < float(efficiency) <= 1):
        raise ValidationFailed(
            "field_efficiency must be within (0, 1].", details=[{"field": "field_efficiency"}]
        )
    resource = dbm.FarmResource(
        farm_id=farm.id,
        resource_type=resource_type,
        name=str(body.get("name") or resource_type),
        capacity_value=float(body["capacity_value"]) if body.get("capacity_value") is not None else None,
        capacity_unit=body.get("capacity_unit"),
        working_width_m=float(body["working_width_m"]) if body.get("working_width_m") is not None else None,
        field_efficiency=float(efficiency) if efficiency is not None else None,
        availability_calendar=availability,
        compatibility=dict(body.get("compatibility") or {}),
        notes=body.get("notes"),
        created_by=principal.id,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return {
        "id": str(resource.id),
        "farm_id": str(farm.id),
        "resource_type": resource.resource_type,
        "name": resource.name,
        "capacity_value": resource.capacity_value,
        "capacity_unit": resource.capacity_unit,
        "availability_calendar": resource.availability_calendar,
    }


@router.get("/farms/{farm_id}/resources")
def list_farm_resources(
    farm_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = db.get(dbm.Farm, farm_id)
    if farm is None:
        raise NotFound("Farm not found.")
    principal.require_member_of(farm.organization_id)
    rows = db.scalars(
        select(dbm.FarmResource).where(dbm.FarmResource.farm_id == farm.id)
        .order_by(dbm.FarmResource.resource_type, dbm.FarmResource.name)
    ).all()
    return {
        "farm_id": str(farm.id),
        "items": [
            {
                "id": str(r.id),
                "resource_type": r.resource_type,
                "name": r.name,
                "capacity_value": r.capacity_value,
                "capacity_unit": r.capacity_unit,
                "working_width_m": r.working_width_m,
                "field_efficiency": r.field_efficiency,
                "availability_calendar": r.availability_calendar,
                "compatibility": r.compatibility,
                "notes": r.notes,
            }
            for r in rows
        ],
        "total": len(rows),
    }


def _operation_payload(op: dbm.FieldOperation, *, include_status_reason: bool = True) -> dict[str, Any]:
    out = {
        "id": str(op.id),
        "field_id": str(op.field_id),
        "template_code": op.template_code,
        "operation_type": op.operation_type,
        "title": op.title,
        "crop_label": op.crop_label,
        "season_label": op.season_label,
        "earliest_start": op.earliest_start.isoformat() if op.earliest_start else None,
        "latest_finish": op.latest_finish.isoformat() if op.latest_finish else None,
        "preferred_start": op.preferred_start.isoformat() if op.preferred_start else None,
        "preferred_end": op.preferred_end.isoformat() if op.preferred_end else None,
        "duration_estimate_hours": op.duration_estimate_hours,
        "duration_basis": op.duration_basis,
        "area_ha": op.area_ha,
        "resource_requirements": op.resource_requirements,
        "restrictions": op.restrictions,
        "priority": op.priority,
        "status": op.status,
        "scheduled_start": op.scheduled_start.isoformat() if op.scheduled_start else None,
        "scheduled_end": op.scheduled_end.isoformat() if op.scheduled_end else None,
        "assigned_resource_ids": op.assigned_resource_ids,
        "schedule_run_id": str(op.schedule_run_id) if op.schedule_run_id else None,
        "status_reason": op.status_reason,
        "completion_date": op.completion_date.isoformat() if op.completion_date else None,
        "completed_soil_management_event_id": str(op.completed_soil_management_event_id) if op.completed_soil_management_event_id else None,
        "template_source": op.template_source,
    }
    return out


@router.post("/fields/{field_id}/operations", status_code=status.HTTP_201_CREATED)
def create_field_operation(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    operation_type = str(body.get("operation_type") or "").strip()
    if not operation_type:
        raise ValidationFailed("operation_type is required.", details=[{"field": "operation_type"}])
    template_source: dict[str, Any] = {}
    template_code = body.get("template_code")
    if template_code:
        template = db.scalar(
            select(dbm.OperationTemplate)
            .join(dbm.KnowledgePack, dbm.OperationTemplate.pack_id == dbm.KnowledgePack.id)
            .where(
                dbm.OperationTemplate.template_code == str(template_code),
                dbm.KnowledgePack.status == "active",
                dbm.OperationTemplate.status == "active",
            )
            .order_by(dbm.KnowledgePack.pack_version.desc())
            .limit(1)
        )
        if template is None:
            raise ValidationFailed(
                f"template_code '{template_code}' has no active template.",
                details=[{"field": "template_code"}],
            )
        template_source = {
            "template_code": template.template_code,
            "operation_type": template.operation_type,
            "provenance": "active knowledge pack template",
        }
        operation_type = operation_type or template.operation_type
    op = dbm.FieldOperation(
        field_id=field.id,
        template_code=str(template_code) if template_code else None,
        operation_type=operation_type,
        title=str(body.get("title") or operation_type),
        crop_label=body.get("crop_label"),
        season_label=body.get("season_label"),
        cover_crop_item_id=uuid.UUID(str(body["cover_crop_item_id"])) if body.get("cover_crop_item_id") else None,
        earliest_start=_parse_date(body["earliest_start"], "earliest_start") if body.get("earliest_start") else None,
        latest_finish=_parse_date(body["latest_finish"], "latest_finish") if body.get("latest_finish") else None,
        preferred_start=_parse_date(body["preferred_start"], "preferred_start") if body.get("preferred_start") else None,
        preferred_end=_parse_date(body["preferred_end"], "preferred_end") if body.get("preferred_end") else None,
        duration_estimate_hours=float(body["duration_estimate_hours"]) if body.get("duration_estimate_hours") is not None else None,
        duration_basis=body.get("duration_basis") or ("farmer_entered" if body.get("duration_estimate_hours") is not None else None),
        area_ha=float(body["area_ha"]) if body.get("area_ha") is not None else None,
        resource_requirements=list(body.get("resource_requirements") or []),
        restrictions=list(body.get("restrictions") or []),
        priority=int(body.get("priority") or 3),
        status="planned",
        template_source=template_source,
        created_by=principal.id,
    )
    db.add(op)
    db.flush()
    for dep in body.get("depends_on") or []:
        db.add(
            dbm.OperationDependency(
                field_id=field.id,
                operation_id=op.id,
                depends_on_operation_id=uuid.UUID(str(dep)),
                dependency_type="finish_to_start",
                lag_days=0,
            )
        )
    db.commit()
    db.refresh(op)
    return _operation_payload(op)


@router.post("/fields/{field_id}/operations/generate", status_code=status.HTTP_201_CREATED)
def generate_operations(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Derive planned operations for a crop context from ACTIVE templates.

    Templates carry NO durations and NO capacities — generated operations are
    `planned` with unknown duration until the farmer supplies one. Windows
    come from the crop's calendar windows (evidence-classed) when available;
    precedence follows the templates' cited typical_predecessors."""
    from app.management.practices import active_operation_templates

    field = get_field_for_principal(db, principal, field_id)
    crop_label = str(body.get("crop_label") or "").strip()
    if not crop_label:
        raise ValidationFailed("crop_label is required.", details=[{"field": "crop_label"}])
    season_label = body.get("season_label")
    templates = active_operation_templates(db)
    if not templates:
        raise ValidationFailed(
            "no active operation templates in the knowledge base.",
            details=[{"field": "operation_templates"}],
        )

    # resolve crop category (from the knowledge base) for applicability
    crop_row = db.scalar(
        select(dbm.Crop).join(dbm.KnowledgePack, dbm.Crop.pack_id == dbm.KnowledgePack.id)
        .where(dbm.Crop.crop_code == crop_label, dbm.KnowledgePack.status == "active")
        .order_by(dbm.KnowledgePack.pack_version.desc())
        .limit(1)
    )
    crop_category = crop_row.crop_category if crop_row is not None else None

    applicable = []
    for t in templates:
        payload = t["payload"]
        cats = payload.get("applies_to_crop_categories") or []
        codes = payload.get("applies_to_crop_codes") or []
        if codes and crop_label not in codes:
            continue
        if cats and crop_category and crop_category not in cats:
            continue
        applicable.append(t)

    # calendar windows for the crop (earliest/latest for planting & harvest)
    window: dict[str, Any] = {}
    if crop_row is not None:
        farm = field.farm
        hemisphere = "south" if _south_hemisphere(farm.country_code) else "north"
        w = db.scalar(
            select(dbm.CropCalendarWindow)
            .where(
                dbm.CropCalendarWindow.crop_id == crop_row.id,
                dbm.CropCalendarWindow.hemisphere == hemisphere,
            )
            .order_by(dbm.CropCalendarWindow.region_code.asc().nulls_last())
            .limit(1)
        )
        if w is not None:
            year = int(str(body.get("window_year") or dt.date.today().year))
            def mmdd(y: int, s: str) -> dt.date:
                mth, dy = s.split("-")
                return dt.date(y, int(mth), int(dy))
            we_year = year + 1 if w.planting_end <= w.planting_start else year
            window = {
                "planting": [mmdd(year, w.planting_start), mmdd(we_year, w.planting_end)],
                "harvest": (
                    [mmdd(year, w.harvest_start), mmdd(year, w.harvest_end)]
                    if w.harvest_start and w.harvest_end else None
                ),
                "evidence_class": w.evidence_class,
            }

    created: list[dbm.FieldOperation] = []
    by_code: dict[str, dbm.FieldOperation] = {}
    for t in applicable:
        code = t["template_code"]
        otype = t["operation_type"]
        earliest = latest = None
        if otype == "planting" and window.get("planting"):
            earliest, latest = window["planting"]
        elif otype == "harvest" and window.get("harvest"):
            earliest, latest = window["harvest"]
        op = dbm.FieldOperation(
            field_id=field.id,
            template_code=code,
            operation_type=otype,
            title=t["name"] + (f" — {crop_label}" if crop_label else ""),
            crop_label=crop_label,
            season_label=season_label,
            area_ha=field.area_ha,
            earliest_start=earliest,
            latest_finish=latest,
            status="planned",
            template_source={
                "template_code": code,
                "operation_type": otype,
                "provenance": "generated from active knowledge pack template",
            },
            created_by=principal.id,
        )
        db.add(op)
        created.append(op)
        by_code[code] = op
    db.flush()

    dep_edges = []
    for t in applicable:
        op = by_code[t["template_code"]]
        for pred in t["payload"].get("typical_predecessors") or []:
            pred_op = by_code.get(pred.get("template_code"))
            if pred_op is not None and pred_op.id != op.id:
                db.add(
                    dbm.OperationDependency(
                        field_id=field.id,
                        operation_id=op.id,
                        depends_on_operation_id=pred_op.id,
                        dependency_type="finish_to_start",
                        lag_days=0,
                    )
                )
                dep_edges.append({"operation": t["template_code"], "depends_on": pred["template_code"]})
    db.commit()
    for op in created:
        db.refresh(op)
    return {
        "field_id": str(field.id),
        "crop_label": crop_label,
        "generated": [_operation_payload(op) for op in created],
        "dependencies": dep_edges,
        "calendar_window": {
            "planting": [d.isoformat() for d in window["planting"]] if window.get("planting") else None,
            "harvest": [d.isoformat() for d in window["harvest"]] if window.get("harvest") else None,
            "evidence_class": window.get("evidence_class"),
        },
        "note": (
            "Generated operations are planned with UNKNOWN durations — supply "
            "duration estimates (farmer/resource data) before scheduling. "
            "Weather/soil checks stay pending; no forecast exists."
        ),
    }


@router.get("/fields/{field_id}/operations")
def list_field_operations(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.FieldOperation)
        .where(dbm.FieldOperation.field_id == field.id)
        .order_by(dbm.FieldOperation.priority.asc(), dbm.FieldOperation.created_at.asc())
        .limit(300)
    ).all()
    deps = db.scalars(
        select(dbm.OperationDependency).where(dbm.OperationDependency.field_id == field.id)
    ).all()
    dep_map: dict[str, list[str]] = {}
    for d in deps:
        dep_map.setdefault(str(d.operation_id), []).append(str(d.depends_on_operation_id))
    return {
        "field_id": str(field.id),
        "items": [_operation_payload(op) for op in rows],
        "dependencies": dep_map,
        "total": len(rows),
    }


@router.patch("/operations/{operation_id}")
def update_field_operation(
    operation_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Status transitions + completion logging. Completion links the agronomic
    event it produced (soil_management_events stays the event ledger)."""
    op = db.get(dbm.FieldOperation, operation_id)
    if op is None:
        raise NotFound("Field operation not found.")
    field = get_field_for_principal(db, principal, op.field_id)
    if "status" in body:
        new_status = str(body["status"])
        allowed = {"planned", "scheduled", "started", "completed", "delayed", "cancelled", "blocked"}
        if new_status not in allowed:
            raise ValidationFailed(
                f"unknown status '{new_status}'.", details=[{"field": "status"}]
            )
        op.status = new_status
    if "status_reason" in body:
        op.status_reason = body["status_reason"]
    if "priority" in body:
        op.priority = int(body["priority"])
    if body.get("status") == "completed":
        op.completion_date = _parse_date(
            body.get("completion_date") or dt.date.today().isoformat(), "completion_date"
        )
        if body.get("completed_soil_management_event_id"):
            event = db.get(
                dbm.SoilManagementEvent,
                uuid.UUID(str(body["completed_soil_management_event_id"])),
            )
            if event is None or str(event.field_id) != str(field.id):
                raise ValidationFailed(
                    "completed_soil_management_event_id does not reference an "
                    "event of this field.",
                    details=[{"field": "completed_soil_management_event_id"}],
                )
            op.completed_soil_management_event_id = event.id
        if body.get("completion_notes"):
            op.completion_notes = body["completion_notes"]
    db.commit()
    db.refresh(op)
    return _operation_payload(op)


@router.post("/fields/{field_id}/operation-schedule-runs", status_code=status.HTTP_201_CREATED)
def create_schedule_run(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.management.contracts import MANAGEMENT_ENGINE_VERSION, MANAGEMENT_METHODS_VERSION
    from app.management.scheduling import (
        SCHEDULING_ENGINE_VERSION,
        SCHEDULING_METHODS_VERSION,
        merge_schedule_result,
        prepare_operations,
        solve_schedule,
    )

    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.OperationScheduleRun).where(
                dbm.OperationScheduleRun.field_id == field.id,
                dbm.OperationScheduleRun.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            return _schedule_run_payload(existing)

    ops_rows = db.scalars(
        select(dbm.FieldOperation).where(
            dbm.FieldOperation.field_id == field.id,
            dbm.FieldOperation.status.in_(("planned", "scheduled", "delayed")),
        )
    ).all()
    deps_rows = db.scalars(
        select(dbm.OperationDependency).where(dbm.OperationDependency.field_id == field.id)
    ).all()
    farm = field.farm
    resources = db.scalars(
        select(dbm.FarmResource).where(dbm.FarmResource.farm_id == farm.id)
    ).all()

    operations = [
        {
            "id": str(op.id),
            "title": op.title,
            "priority": op.priority,
            "earliest_start": op.earliest_start,
            "latest_finish": op.latest_finish,
            "duration_days": None,  # conversion handled by prepare_operations
            "duration_estimate_hours": op.duration_estimate_hours,
            "resource_requirements": op.resource_requirements,
        }
        for op in ops_rows
    ]
    dependencies = [
        {
            "operation_id": str(d.operation_id),
            "depends_on_operation_id": str(d.depends_on_operation_id),
            "dependency_type": d.dependency_type,
            "lag_days": d.lag_days,
        }
        for d in deps_rows
    ]
    resources_data = [
        {
            "id": str(r.id),
            "resource_type": r.resource_type,
            "name": r.name,
            "availability_calendar": r.availability_calendar,
        }
        for r in resources
    ]

    horizon_start = _parse_date(body.get("horizon_start") or dt.date.today().isoformat(), "horizon_start")
    horizon_end = _parse_date(body.get("horizon_end") or (dt.date.today() + dt.timedelta(days=180)).isoformat(), "horizon_end")
    hours_per_workday = body.get("hours_per_workday")

    prepared = prepare_operations(
        operations, dependencies,
        horizon_start=horizon_start, horizon_end=horizon_end,
        resources=resources_data, hours_per_workday=hours_per_workday,
    )
    solve = solve_schedule(prepared, dependencies, resources_data)
    merged = merge_schedule_result(prepared, solve, operations)

    # write-back: scheduled operations get their dates + assignment (provenance)
    run_row = dbm.OperationScheduleRun(
        field_id=field.id,
        status="succeeded" if merged["solver"]["status"] in ("scheduled", "no_schedulable_operations") else (
            "infeasible" if merged["solver"]["status"] == "infeasible" else "failed"
        ),
        label=str(body.get("label") or "Operations schedule"),
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        engine_version=SCHEDULING_ENGINE_VERSION,
        methods_version=SCHEDULING_METHODS_VERSION,
        result=merged,
        warnings=[],
        not_evaluated={
            "weather": "no forecast provider exists — weather checks stay "
            "pending; historical climate is never used as a forecast",
            "soil_trafficability": "no universal threshold exists — field "
            "readiness is a manual check before each operation",
        },
        request_parameters={
            "horizon": [horizon_start.isoformat(), horizon_end.isoformat()],
            "hours_per_workday": hours_per_workday,
            "operation_count": len(operations),
            "resource_count": len(resources_data),
        },
        idempotency_key=str(idempotency_key) if idempotency_key else None,
        created_by=principal.id,
    )
    import hashlib
    import json as _json

    run_row.checksum_sha256 = hashlib.sha256(
        _json.dumps({"result": merged, "request": run_row.request_parameters,
                     "engine": SCHEDULING_ENGINE_VERSION}, sort_keys=True,
                    separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    db.add(run_row)
    db.flush()
    if merged["solver"]["status"] == "scheduled":
        for entry in merged["entries"]:
            if entry["status"] == "scheduled":
                op = db.get(dbm.FieldOperation, uuid.UUID(entry["operation_id"]))
                if op is None:
                    continue
                op.status = "scheduled"
                op.scheduled_start = dt.date.fromisoformat(entry["scheduled_start"])
                op.scheduled_end = dt.date.fromisoformat(entry["scheduled_end"])
                op.assigned_resource_ids = list(entry["assigned_resources"].values())
                op.schedule_run_id = run_row.id
    db.commit()
    db.refresh(run_row)
    return _schedule_run_payload(run_row)


def _schedule_run_payload(run: dbm.OperationScheduleRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "label": run.label,
        "horizon": [run.horizon_start.isoformat() if run.horizon_start else None,
                    run.horizon_end.isoformat() if run.horizon_end else None],
        "engine_version": run.engine_version,
        "methods_version": run.methods_version,
        "result": run.result,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "request_parameters": run.request_parameters,
        "checksum_sha256": run.checksum_sha256,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/operation-schedule-runs/{run_id}")
def get_schedule_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(dbm.OperationScheduleRun, run_id)
    if run is None:
        raise NotFound("Schedule run not found.")
    get_field_for_principal(db, principal, run.field_id)
    return _schedule_run_payload(run)


@router.get("/fields/{field_id}/resource-conflicts")
def get_resource_conflicts(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Currently scheduled operations sharing a resource on overlapping days."""
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.FieldOperation)
        .where(
            dbm.FieldOperation.field_id == field.id,
            dbm.FieldOperation.status == "scheduled",
        )
        .order_by(dbm.FieldOperation.scheduled_start.asc())
    ).all()
    conflicts: list[dict[str, Any]] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            shared = set(map(str, a.assigned_resource_ids or [])) & set(map(str, b.assigned_resource_ids or []))
            overlaps = (
                a.scheduled_start is not None and b.scheduled_start is not None
                and a.scheduled_start <= b.scheduled_end and b.scheduled_start <= a.scheduled_end
            )
            if shared and overlaps:
                conflicts.append(
                    {
                        "resource_ids": sorted(shared),
                        "operations": [
                            {"id": str(a.id), "title": a.title,
                             "window": [a.scheduled_start.isoformat(), a.scheduled_end.isoformat()]},
                            {"id": str(b.id), "title": b.title,
                             "window": [b.scheduled_start.isoformat(), b.scheduled_end.isoformat()]},
                        ],
                        "message": "two scheduled operations share an exclusive "
                        "resource on overlapping days — reschedule one",
                    }
                )
    return {"field_id": str(field.id), "conflicts": conflicts, "total": len(conflicts)}


# --------------------------------------------------------- management plans
def _management_plan_payload(plan: dbm.ManagementPlan, *, include_result: bool = True) -> dict[str, Any]:
    out = {
        "id": str(plan.id),
        "field_id": str(plan.field_id),
        "status": plan.status,
        "label": plan.label,
        "season_label": plan.season_label,
        "engine_version": plan.engine_version,
        "methods_version": plan.methods_version,
        "warnings": plan.warnings,
        "not_evaluated": plan.not_evaluated,
        "request_parameters": plan.request_parameters,
        "knowledge_pack_refs": plan.knowledge_pack_refs,
        "checksum_sha256": plan.checksum_sha256,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }
    if include_result:
        out["result"] = plan.result
    return out


@router.post("/fields/{field_id}/management-plans", status_code=status.HTTP_201_CREATED)
def create_management_plan(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregate every M6C surface (plus rotation/water context) into one
    explainable seasonal plan snapshot. Sections without evidence appear with
    explicit missing-data status — a section is never dropped."""
    from app.management.contracts import MANAGEMENT_ENGINE_VERSION, MANAGEMENT_METHODS_VERSION
    from app.management.cover_crops import evaluate_cover_candidates
    from app.management.erosion import run_erosion_assessment
    from app.management.practices import active_practices
    from app.management.soil_cover import build_cover_timeline
    from app.knowledge.service import load_knowledge
    from app.rotation.service import _pick_evidence_run, _season_climate, _soil_evidence

    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.ManagementPlan).where(
                dbm.ManagementPlan.field_id == field.id,
                dbm.ManagementPlan.idempotency_key == str(idempotency_key),
            )
        )
        if existing is not None:
            return _management_plan_payload(existing)

    window_end = _parse_date(body.get("window_end") or dt.date.today().isoformat(), "window_end")
    window_start = _parse_date(
        body.get("window_start") or (window_end - dt.timedelta(days=365)), "window_start"
    )
    season_label = body.get("season_label")
    warnings: list[str] = []

    # --- rotation / crop context -------------------------------------------
    history = db.scalars(
        select(dbm.CropHistory)
        .where(dbm.CropHistory.field_id == field.id)
        .order_by(dbm.CropHistory.sowing_date.desc().nulls_last())
        .limit(5)
    ).all()
    season_context = {
        "recent_crop_history": [
            {"crop_label": h.crop_label, "sowing_date": h.sowing_date.isoformat() if h.sowing_date else None,
             "harvest_date": h.harvest_date.isoformat() if h.harvest_date else None,
             "season_label": h.season_label, "evidence_class": h.evidence_class}
            for h in history
        ],
        "status": "evaluated" if history else "not_evaluated",
        "message": None if history else "no crop history recorded for this field",
    }

    # --- soil cover ----------------------------------------------------------
    inputs = _load_timeline_inputs(db, field.id)
    cover = build_cover_timeline(
        window_start=window_start, window_end=window_end,
        crop_history=inputs["crop_history"], cover_crop_items=inputs["cover_crop_items"],
        management_events=inputs["management_events"],
        cover_observations=inputs["cover_observations"],
    )
    soil_cover = {
        "metrics": cover["metrics"],
        "thresholds": cover["thresholds"],
        "window": cover["window"],
    }

    # --- cover-crop status ----------------------------------------------------
    cover_items = db.scalars(
        select(dbm.CoverCropPlanItem)
        .where(dbm.CoverCropPlanItem.field_id == field.id)
        .order_by(dbm.CoverCropPlanItem.created_at.desc())
        .limit(10)
    ).all()
    latest_cover_plan = db.scalar(
        select(dbm.CoverCropPlan)
        .where(dbm.CoverCropPlan.field_id == field.id, dbm.CoverCropPlan.status == "succeeded")
        .order_by(dbm.CoverCropPlan.created_at.desc())
        .limit(1)
    )
    cover_crop = {
        "plan_items": [
            {"id": str(i.id), "crop_label": i.crop_label, "status": i.status,
             "season_label": i.season_label,
             "intended_sowing_start": i.intended_sowing_start.isoformat() if i.intended_sowing_start else None,
             "intended_termination_window_start": i.intended_termination_window_start.isoformat() if i.intended_termination_window_start else None}
            for i in cover_items
        ],
        "latest_plan": (
            {"id": str(latest_cover_plan.id),
             "created_at": latest_cover_plan.created_at.isoformat() if latest_cover_plan.created_at else None,
             "candidate_statuses": {
                 c["crop_code"]: c["status"]
                 for c in latest_cover_plan.result.get("candidates", [])
             }}
            if latest_cover_plan else None
        ),
        "status": "evaluated" if (cover_items or latest_cover_plan) else "not_evaluated",
        "message": None if (cover_items or latest_cover_plan) else (
            "no cover-crop plan evaluated yet — open the Cover Crop Studio"
        ),
    }

    # --- residue status ---------------------------------------------------------
    residue_records = db.scalars(
        select(dbm.ResidueRecord).where(dbm.ResidueRecord.field_id == field.id)
    ).all()
    flows = db.scalars(
        select(dbm.ResidueFlowEvent)
        .join(dbm.ResidueRecord, dbm.ResidueFlowEvent.residue_record_id == dbm.ResidueRecord.id)
        .where(dbm.ResidueRecord.field_id == field.id)
    ).all()
    from app.management.residue import build_residue_ledger

    flows_by_record: dict[str, list[dict[str, Any]]] = {}
    for f in flows:
        flows_by_record.setdefault(str(f.residue_record_id), []).append(
            {"id": str(f.id), "flow_type": f.flow_type, "dm_kg": f.dm_kg, "dm_kg_status": f.dm_kg_status}
        )
    residue_ledger = build_residue_ledger(
        [{"id": str(r.id), "crop_label": r.crop_label, "season_label": r.season_label,
          "produced_dm_kg": r.produced_dm_kg, "production_status": r.production_status,
          "coefficient_provenance": r.coefficient_provenance} for r in residue_records],
        flows_by_record, {},
    )
    residue_status = {
        "totals": residue_ledger["totals"],
        "warnings": residue_ledger["warnings"],
        "status": "evaluated" if residue_records else "not_evaluated",
        "message": None if residue_records else "no residue records yet — open the Residue Ledger",
    }

    # --- erosion status ------------------------------------------------------------
    latest_erosion = db.scalar(
        select(dbm.ErosionAssessmentRun)
        .where(dbm.ErosionAssessmentRun.field_id == field.id, dbm.ErosionAssessmentRun.status == "succeeded")
        .order_by(dbm.ErosionAssessmentRun.created_at.desc())
        .limit(1)
    )
    erosion_status: dict[str, Any]
    if latest_erosion is not None:
        screening = latest_erosion.result.get("screening", {})
        rusle = latest_erosion.result.get("rusle", {})
        erosion_status = {
            "latest_run_id": str(latest_erosion.id),
            "created_at": latest_erosion.created_at.isoformat() if latest_erosion.created_at else None,
            "screening_concern_count": len(screening.get("concerns", [])),
            "screening_processes": screening.get("processes_assessed", []),
            "rusle_status": rusle.get("status"),
            "status": "evaluated",
        }
    else:
        erosion_status = {
            "status": "not_evaluated",
            "message": "no erosion assessment yet — open Erosion & Conservation",
        }

    # --- operations -------------------------------------------------------------------
    ops = db.scalars(
        select(dbm.FieldOperation)
        .where(dbm.FieldOperation.field_id == field.id)
        .order_by(dbm.FieldOperation.earliest_start.asc().nulls_last())
        .limit(100)
    ).all()
    conflicts = _resource_conflicts_for(db, field.id)
    next_ops = [
        {"id": str(o.id), "title": o.title, "operation_type": o.operation_type,
         "status": o.status,
         "scheduled_start": o.scheduled_start.isoformat() if o.scheduled_start else None,
         "scheduled_end": o.scheduled_end.isoformat() if o.scheduled_end else None,
         "earliest_start": o.earliest_start.isoformat() if o.earliest_start else None,
         "latest_finish": o.latest_finish.isoformat() if o.latest_finish else None,
         "status_reason": o.status_reason}
        for o in ops
    ]
    operations_status = {
        "next_operations": next_ops[:12],
        "counts": {
            "total": len(ops),
            "planned": sum(1 for o in ops if o.status == "planned"),
            "scheduled": sum(1 for o in ops if o.status == "scheduled"),
            "blocked": sum(1 for o in ops if o.status == "blocked"),
            "completed": sum(1 for o in ops if o.status == "completed"),
        },
        "conflicts": conflicts,
        "status": "evaluated" if ops else "not_evaluated",
        "message": None if ops else (
            "no operations yet — generate them from templates in the Operations Calendar"
        ),
    }

    # --- practice guidance (cited, active pack) ----------------------------------------
    practices = active_practices(db)
    practice_guidance = {
        "practices": [
            {"practice_code": p["practice_code"], "name": p["name"],
             "practice_family": p["practice_family"],
             "validation_status": p["validation_status"],
             "mechanism_count": len(p["payload"].get("mechanisms", [])),
             "trade_off_dimensions": sorted({
                 t.get("dimension") for t in p["payload"].get("trade_offs", [])
             })}
            for p in practices
        ],
        "note": "Full cited mechanisms and trade-offs in the knowledge base; "
        "nothing here is confirmed_regional — practices are reference knowledge.",
    }

    # --- water context (M6A reference, not recomputed) ----------------------------------
    latest_water = db.scalar(
        select(dbm.WaterPlan)
        .where(dbm.WaterPlan.field_id == field.id, dbm.WaterPlan.status == "succeeded")
        .order_by(dbm.WaterPlan.created_at.desc())
        .limit(1)
    )
    water_status = (
        {"latest_plan_id": str(latest_water.id),
         "engine_version": latest_water.water_engine_version,
         "status": "evaluated"}
        if latest_water is not None
        else {"status": "not_evaluated", "message": "no water plan for this field"}
    )

    # --- unresolved agronomic checks -------------------------------------------------------
    checks: list[dict[str, Any]] = []
    if not history:
        checks.append({"code": "no_crop_history", "severity": "warning",
                       "message": "Record crop history so cover windows and bare periods mean something."})
    if not inputs["cover_observations"]:
        checks.append({"code": "no_cover_observations", "severity": "info",
                       "message": "No soil-cover observations — cover metrics rely on crop/management records only."})
    if cover["metrics"]["days_unknown"] == cover["metrics"]["window_days"]:
        checks.append({"code": "cover_entirely_unknown", "severity": "warning",
                       "message": "The whole plan window is without cover evidence."})
    for w in residue_ledger["warnings"]:
        checks.append({"code": "residue_warning", "severity": "warning", "message": w})
    if operations_status["counts"]["planned"] and not operations_status["counts"]["scheduled"]:
        checks.append({"code": "operations_unscheduled", "severity": "info",
                       "message": "Planned operations exist but none are scheduled — run the scheduler (durations needed)."})
    if latest_cover_plan is None:
        checks.append({"code": "cover_plan_missing", "severity": "info",
                       "message": "No cover-crop evaluation for this field yet."})

    result = {
        "season_context": season_context,
        "soil_cover": soil_cover,
        "cover_crop": cover_crop,
        "residue": residue_status,
        "erosion": erosion_status,
        "operations": operations_status,
        "practice_guidance": practice_guidance,
        "water": water_status,
        "checks": checks,
    }
    if not history:
        warnings.append("Season context is built without crop history — several sections stay unevaluated.")

    import hashlib
    import json as _json

    request_params = {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "season_label": season_label,
    }
    plan = dbm.ManagementPlan(
        field_id=field.id,
        status="succeeded",
        label=str(body.get("label") or "Management plan"),
        season_label=season_label,
        engine_version=MANAGEMENT_ENGINE_VERSION,
        methods_version=MANAGEMENT_METHODS_VERSION,
        result=result,
        warnings=warnings,
        not_evaluated={
            "weather": "no forecast — operations carry pending weather checks",
            "confirmed_regional_knowledge": "nothing in the active packs is "
            "confirmed regional; all guidance is reference knowledge",
        },
        request_parameters=request_params,
        knowledge_pack_refs=[p["practice_code"] for p in practices][:0],  # refs set below
        cover_crop_plan_ids=[str(latest_cover_plan.id)] if latest_cover_plan else [],
        erosion_run_ids=[str(latest_erosion.id)] if latest_erosion else [],
        water_plan_ids=[str(latest_water.id)] if latest_water else [],
        idempotency_key=str(idempotency_key) if idempotency_key else None,
        created_by=principal.id,
    )
    plan.knowledge_pack_refs = [
        {"pack_code": pr["pack_code"], "pack_version": pr["pack_version"]}
        for pr in _active_pack_refs_for_field(db)
    ]
    plan.checksum_sha256 = hashlib.sha256(
        _json.dumps({"result": result, "request": request_params,
                     "engine": MANAGEMENT_ENGINE_VERSION}, sort_keys=True,
                    separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _management_plan_payload(plan)


def _resource_conflicts_for(db: Session, field_id: Any) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(dbm.FieldOperation)
        .where(dbm.FieldOperation.field_id == field_id, dbm.FieldOperation.status == "scheduled")
        .order_by(dbm.FieldOperation.scheduled_start.asc())
    ).all()
    conflicts = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            shared = set(map(str, a.assigned_resource_ids or [])) & set(map(str, b.assigned_resource_ids or []))
            overlaps = (
                a.scheduled_start is not None and b.scheduled_start is not None
                and a.scheduled_start <= b.scheduled_end and b.scheduled_start <= a.scheduled_end
            )
            if shared and overlaps:
                conflicts.append({
                    "resource_ids": sorted(shared),
                    "operations": [str(a.id), str(b.id)],
                })
    return conflicts


def _active_pack_refs_for_field(db: Session) -> list[dict[str, Any]]:
    from app.management.practices import active_pack_refs

    return active_pack_refs(db)


@router.get("/fields/{field_id}/management-plans")
def list_management_plans(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.ManagementPlan)
        .where(dbm.ManagementPlan.field_id == field.id)
        .order_by(dbm.ManagementPlan.created_at.desc())
        .limit(50)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [_management_plan_payload(p, include_result=False) for p in rows],
        "total": len(rows),
    }


@router.get("/management-plans/{plan_id}")
def get_management_plan(
    plan_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    plan = db.get(dbm.ManagementPlan, plan_id)
    if plan is None:
        raise NotFound("Management plan not found.")
    get_field_for_principal(db, principal, plan.field_id)
    return _management_plan_payload(plan)


class PlanFeedbackRequest(BaseModel):
    author_role: str = "farmer"
    rating: int | None = None
    accepted: bool | None = None
    comment: str | None = None


@router.post("/management-plans/{plan_id}/feedback", status_code=status.HTTP_201_CREATED)
def create_plan_feedback(
    plan_id: uuid.UUID,
    body: PlanFeedbackRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    plan = db.get(dbm.ManagementPlan, plan_id)
    if plan is None:
        raise NotFound("Management plan not found.")
    get_field_for_principal(db, principal, plan.field_id)
    if body.author_role not in ("farmer", "agronomist", "other"):
        raise ValidationFailed("author_role must be farmer, agronomist or other.",
                               details=[{"field": "author_role"}])
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise ValidationFailed("rating must be within [1, 5].", details=[{"field": "rating"}])
    feedback = dbm.ManagementPlanFeedback(
        management_plan_id=plan.id,
        author_role=body.author_role,
        rating=body.rating,
        accepted=body.accepted,
        comment=body.comment,
        created_by=principal.id,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {
        "id": str(feedback.id),
        "management_plan_id": str(plan.id),
        "author_role": feedback.author_role,
        "rating": feedback.rating,
        "accepted": feedback.accepted,
    }

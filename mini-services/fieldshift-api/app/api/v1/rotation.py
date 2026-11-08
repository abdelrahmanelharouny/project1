"""Rotation & candidate endpoints (Milestone 5): crop history, candidate
generation, rotation runs (create/status/strategies/comparison-ready
snapshots). All endpoints are tenant-scoped through the field's farm."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal, require_farm_role
from app.knowledge.service import load_knowledge
from app.rotation import candidates as candidates_mod
from app.rotation import service as rotation_service
from app.rotation.problem import SeasonSpec

router = APIRouter(tags=["rotation"])


# ------------------------------------------------------------ crop history
class CropHistoryCreate(BaseModel):
    crop_code: str | None = Field(default=None, description="Knowledge-base crop code, if known.")
    crop_label: str = Field(min_length=1, max_length=160)
    sowing_date: str | None = None
    harvest_date: str | None = None
    season_label: str | None = Field(default=None, max_length=60)
    area_ha: float | None = Field(default=None, gt=0)
    source: str = Field(default="farmer", max_length=40)
    evidence_class: str = Field(default="farmer_reported_record", max_length=60)


@router.get("/fields/{field_id}/crop-history")
def list_crop_history(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.CropHistory)
        .where(dbm.CropHistory.field_id == field.id)
        .order_by(dbm.CropHistory.sowing_date.asc().nullslast())
    ).all()
    crop_by_id = {c.id: c for c in db.scalars(select(dbm.Crop)).all()}
    return {
        "field_id": str(field.id),
        "items": [
            {
                "id": str(h.id),
                "crop_code": crop_by_id[h.crop_id].crop_code if h.crop_id in crop_by_id else None,
                "crop_label": h.crop_label,
                "sowing_date": h.sowing_date.isoformat() if h.sowing_date else None,
                "harvest_date": h.harvest_date.isoformat() if h.harvest_date else None,
                "season_label": h.season_label,
                "area_ha": h.area_ha,
                "source": h.source,
                "evidence_class": h.evidence_class,
            }
            for h in rows
        ],
    }


@router.post("/fields/{field_id}/crop-history", status_code=status.HTTP_201_CREATED)
def add_crop_history(
    field_id: uuid.UUID,
    body: CropHistoryCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    crop_id = None
    if body.crop_code:
        crop = db.scalar(select(dbm.Crop).where(dbm.Crop.crop_code == body.crop_code))
        if crop is None:
            raise ValidationFailed(
                f"Unknown crop_code '{body.crop_code}' — the knowledge base has no such crop.",
                details=[{"field": "crop_code", "reason": body.crop_code}],
            )
        crop_id = crop.id

    def _parse(name: str, value: str | None):
        if value is None:
            return None
        from datetime import date as _date

        try:
            return _date.fromisoformat(value)
        except ValueError:
            raise ValidationFailed(
                f"{name} must be an ISO date.",
                details=[{"field": name, "reason": value}],
            ) from None

    row = dbm.CropHistory(
        field_id=field.id,
        crop_id=crop_id,
        crop_label=body.crop_label,
        sowing_date=_parse("sowing_date", body.sowing_date),
        harvest_date=_parse("harvest_date", body.harvest_date),
        season_label=body.season_label,
        area_ha=body.area_ha,
        source=body.source,
        evidence_class=body.evidence_class,
    )
    db.add(row)
    db.add(
        dbm.AuditEvent(
            actor_id=principal.id,
            entity_type="crop_history",
            entity_id=None,
            action="created",
            after_snapshot={
                "field_id": str(field.id),
                "crop_label": body.crop_label,
                "crop_code": body.crop_code,
                "sowing_date": body.sowing_date,
            },
        )
    )
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "crop_label": row.crop_label,
        "crop_code": body.crop_code,
        "sowing_date": row.sowing_date.isoformat() if row.sowing_date else None,
        "harvest_date": row.harvest_date.isoformat() if row.harvest_date else None,
        "season_label": row.season_label,
    }


# ------------------------------------------------------ candidate generation
class SeasonIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    start_date: str
    end_date: str


class CandidatesRequest(BaseModel):
    seasons: list[SeasonIn] = Field(min_length=1, max_length=4)
    hemisphere: str = Field(default="north", pattern="^(north|south)$")
    evidence_run_id: str | None = None


@router.post("/fields/{field_id}/crop-candidates")
def generate_candidates(
    field_id: uuid.UUID,
    body: CandidatesRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-season candidate generation (M5.3) — no optimization, pure
    eligibility assessment with explanations."""
    field = get_field_for_principal(db, principal, field_id)
    # RBAC (P0-2): candidate generation drives the rotation engine — agronomist+.
    require_farm_role(db, principal, db.get(dbm.Farm, field.farm_id), "agronomist")
    knowledge = load_knowledge(db)
    if not knowledge.crops:
        raise ValidationFailed(
            "No active knowledge pack with crops — import a knowledge pack first.",
            details=[{"field": "knowledge"}],
        )
    try:
        seasons = rotation_service._validate_seasons(
            [s.model_dump() for s in body.seasons]
        )
    except ValidationFailed:
        raise
    farm, warnings, _history_ids, evidence_run = rotation_service.build_farm_context(
        db, field, seasons, body.evidence_run_id, body.hemisphere
    )
    assessments = candidates_mod.generate_candidates(knowledge, farm)
    return {
        "field_id": str(field.id),
        "evidence_run_id": str(evidence_run.id) if evidence_run else None,
        "hemisphere": body.hemisphere,
        "knowledge_pack_refs": [dict(r) for r in knowledge.pack_refs],
        "warnings": warnings,
        "seasons": [
            rotation_service.candidate_payload(label, season_assessments)
            for label, season_assessments in assessments.items()
        ],
        "counts_by_season": {
            label: {
                "eligible": sum(1 for a in s_a.values() if a.status == "eligible"),
                "conditionally_eligible": sum(
                    1 for a in s_a.values() if a.status == "conditionally_eligible"
                ),
                "excluded": sum(1 for a in s_a.values() if a.status == "excluded"),
                "unevaluated": sum(1 for a in s_a.values() if a.status == "unevaluated"),
            }
            for label, s_a in assessments.items()
        },
    }


# ------------------------------------------------------------- rotation runs
class RotationRunRequest(BaseModel):
    seasons: list[SeasonIn] = Field(min_length=1, max_length=4)
    hemisphere: str = Field(default="north", pattern="^(north|south)$")
    evidence_run_id: str | None = None
    strategy_profiles: list[str] | None = None
    custom_weights: dict[str, float] | None = None
    water_allocation_m3: float | None = Field(default=None, gt=0)
    idempotency_key: str | None = None
    request_parameters: dict[str, Any] | None = None


@router.post("/fields/{field_id}/rotation-runs", status_code=status.HTTP_202_ACCEPTED)
def create_rotation_run(
    field_id: uuid.UUID,
    body: RotationRunRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    # RBAC (P0-2): heavy engine creation is an agronomist+ mutation. Enforced
    # BEFORE any engine/knowledge work (403 precedes payload validation).
    require_farm_role(db, principal, db.get(dbm.Farm, field.farm_id), "agronomist")
    run = rotation_service.start_rotation_run(
        db,
        field=field,
        payload={
            "seasons": [s.model_dump() for s in body.seasons],
            "hemisphere": body.hemisphere,
            "evidence_run_id": body.evidence_run_id,
            "strategy_profiles": body.strategy_profiles,
            "custom_weights": body.custom_weights,
            "water_allocation_m3": body.water_allocation_m3,
            "idempotency_key": body.idempotency_key,
            "request_parameters": body.request_parameters,
        },
        created_by=principal,
    )
    db.commit()
    db.refresh(run)
    return rotation_service.run_payload(run)


@router.get("/fields/{field_id}/rotation-runs")
def list_rotation_runs(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.RotationRun)
        .where(dbm.RotationRun.field_id == field.id)
        .order_by(dbm.RotationRun.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "field_id": str(field.id),
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "solver_status": r.solver_status,
                "seasons": r.seasons,
                "strategy_profiles": r.strategy_profiles,
                "rotation_engine_version": r.rotation_engine_version,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "n_strategies": len(r.strategies),
            }
            for r in rows
        ],
    }


def _get_run_for_principal(db: Session, run_id: uuid.UUID, principal: Any) -> dbm.RotationRun:
    run = db.get(dbm.RotationRun, run_id)
    if run is None:
        raise NotFound("Rotation run not found.")
    # tenant check via the field's farm organization
    get_field_for_principal(db, principal, run.field_id)
    return run


@router.get("/rotation-runs/{run_id}")
def get_rotation_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_for_principal(db, run_id, principal)
    return rotation_service.run_payload(run, include_strategies=True)


@router.get("/rotation-runs/{run_id}/strategies")
def list_run_strategies(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_for_principal(db, run_id, principal)
    return {
        "run_id": str(run.id),
        "solver_status": run.solver_status,
        "infeasibility_details": run.infeasibility_details,
        "strategies": [
            rotation_service.strategy_payload(s)
            for s in sorted(run.strategies, key=lambda s: (not s.is_baseline, s.strategy_key))
        ],
    }


@router.get("/rotation-runs/{run_id}/comparison")
def compare_run_strategies(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Criterion-level comparison across all strategies of one run (the
    trade-off table powering the UI)."""
    run = _get_run_for_principal(db, run_id, principal)
    strategies = sorted(run.strategies, key=lambda s: (not s.is_baseline, s.strategy_key))
    criterion_codes = sorted({c["criterion_code"] for s in strategies for c in s.criteria})
    rows = []
    for s in strategies:
        crit_by_code = {c["criterion_code"]: c for c in s.criteria}
        rows.append(
            {
                "strategy_key": s.strategy_key,
                "is_baseline": s.is_baseline,
                "objective_value": s.objective_value,
                "on_pareto_front": s.pareto.get("on_front", False),
                "dominated_by": s.pareto.get("dominated_by", []),
                "evidence_coverage": s.evidence_coverage,
                "criteria": {
                    code: {
                        "raw_value": crit_by_code[code]["raw_value"] if code in crit_by_code else None,
                        "normalized": crit_by_code[code]["normalized"] if code in crit_by_code else None,
                        "evaluable": crit_by_code[code]["evaluable"] if code in crit_by_code else False,
                    }
                    for code in criterion_codes
                },
            }
        )
    return {
        "run_id": str(run.id),
        "criterion_codes": criterion_codes,
        "strategies": rows,
        "note": "Normalized scores are min-max WITHIN this run's strategy set "
        "(ADR-0018); criteria flagged evaluable=false carry missing-evidence "
        "lists instead of zeros.",
    }

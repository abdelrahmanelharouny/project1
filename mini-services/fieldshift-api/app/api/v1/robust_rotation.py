"""Robust rotation endpoints (Milestone 7.5).

- POST /fields/{field_id}/scenario-sets          — create + compatibility validation
- GET  /fields/{field_id}/scenario-sets          — the field's sets
- GET  /scenario-sets/{set_id}                   — detail (members + compatibility)
- DELETE /scenario-sets/{set_id}                 — delete a set without results
- POST /scenario-sets/{set_id}/verify            — BY-VALUE member pin verification
- POST /scenario-sets/{set_id}/robust-runs       — create + run (idempotent)
- GET  /scenario-sets/{set_id}/robust-runs       — the set's runs
- GET  /robust-runs/{run_id}                     — run detail (strategies + diagnostics)
- GET  /robust-runs/{run_id}/strategies          — shared plans + aggregates
- GET  /robust-runs/{run_id}/evaluations         — per-scenario evaluations
- POST /robust-runs/{run_id}/verify              — checksum + pin verification

Every endpoint is tenant-scoped through the set/run's field → farm; ownership
claims from the client are never trusted. No endpoint mutates a result-bearing
run (application + database trigger enforce this). Scenario ET0 and scenario
water feasibility are structurally unavailable: water allocations are rejected
with WATER_ALLOCATION_UNSUPPORTED, never silently dropped.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal
from app.robust_rotation import contracts as rc
from app.robust_rotation import service as robust_service

router = APIRouter(tags=["robust-rotation"])


def _get_set_scoped(
    db: Session, set_id: uuid.UUID, principal: Any
) -> dbm.ScenarioSet:
    row = db.get(dbm.ScenarioSet, set_id)
    if row is None:
        raise NotFound("Scenario set not found.")
    get_field_for_principal(db, principal, row.field_id)  # tenant scoping
    return row


def _get_run_scoped(
    db: Session, run_id: uuid.UUID, principal: Any
) -> dbm.RobustRotationRun:
    row = db.get(dbm.RobustRotationRun, run_id)
    if row is None:
        raise NotFound("Robust rotation run not found.")
    get_field_for_principal(db, principal, row.field_id)  # tenant scoping
    return row


@router.post("/fields/{field_id}/scenario-sets")
def create_scenario_set(
    field_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    row = robust_service.create_scenario_set(
        db, field=field, payload=payload or {}, created_by=principal.user
    )
    return robust_service.set_payload(row)


@router.get("/fields/{field_id}/scenario-sets")
def list_scenario_sets(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    rows = (
        db.execute(
            select(dbm.ScenarioSet)
            .where(dbm.ScenarioSet.field_id == field_id)
            .order_by(dbm.ScenarioSet.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "field_id": str(field_id),
        "items": [robust_service.set_payload(r) for r in rows],
        "count": len(rows),
        "note": (
            "A scenario set bundles result-bearing M7.3 executions of the SAME field "
            f"and parent Field State (1-{rc.MAX_SCENARIO_SET_SIZE} members, distinct scenarios)."
        ),
    }


@router.get("/scenario-sets/{set_id}")
def get_scenario_set(
    set_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_set_scoped(db, set_id, principal)
    return robust_service.set_payload(row)


@router.delete("/scenario-sets/{set_id}")
def delete_scenario_set(
    set_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_set_scoped(db, set_id, principal)
    runs = (
        db.execute(
            select(dbm.RobustRotationRun.id).where(dbm.RobustRotationRun.scenario_set_id == row.id)
        )
        .scalars()
        .all()
    )
    if runs:
        raise Conflict(
            "The scenario set has robust runs referencing it and cannot be deleted.",
            details=[{"robust_run_ids": [str(r) for r in runs]}],
        )
    db.delete(row)
    db.commit()
    return {"deleted": str(set_id)}


@router.post("/scenario-sets/{set_id}/verify")
def verify_scenario_set(
    set_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_set_scoped(db, set_id, principal)
    # Verification is a RESULT, not an error: pin drift is reported as data.
    try:
        result = robust_service.verify_scenario_set_members(db, row)
        drift = []
    except Conflict as exc:
        result = {"verified_members": 0, "drift": "see findings"}
        drift = list(exc.details or [])
    return {
        "scenario_set_id": str(row.id),
        "set_checksum": row.set_checksum,
        **result,
        "findings": drift,
        "usable_for_robust_runs": not drift,
        "note": (
            "Re-compares every BY-VALUE member pin (output checksums, parent pins, "
            "engine versions) against the live M7.3 execution rows. Robust runs are "
            "refused while any pin has drifted."
        ),
    }


@router.post("/scenario-sets/{set_id}/robust-runs")
def create_robust_run(
    set_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_set_scoped(db, set_id, principal)
    field = get_field_for_principal(db, principal, row.field_id)
    run = robust_service.start_robust_rotation_run(
        db, row, field, payload=payload or {}, created_by=principal.user
    )
    strategies = (
        db.execute(
            select(dbm.RobustRotationStrategy)
            .where(dbm.RobustRotationStrategy.run_id == run.id)
            .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
        )
        .scalars()
        .all()
    )
    return {
        **robust_service.run_payload(run),
        "strategies": [robust_service.strategy_payload(s) for s in strategies],
    }


@router.get("/scenario-sets/{set_id}/robust-runs")
def list_robust_runs(
    set_id: uuid.UUID,
    run_status: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_set_scoped(db, set_id, principal)
    query = (
        select(dbm.RobustRotationRun)
        .where(dbm.RobustRotationRun.scenario_set_id == row.id)
        .order_by(dbm.RobustRotationRun.created_at.desc())
    )
    if run_status:
        if run_status not in rc.RUN_STATUSES:
            raise ValidationFailed(
                "Unknown run_status filter.",
                details=[{"field": "run_status", "reason": run_status}],
            )
        query = query.where(dbm.RobustRotationRun.run_status == run_status)
    runs = db.execute(query).scalars().all()
    return {
        "scenario_set_id": str(row.id),
        "items": [robust_service.run_payload(r) for r in runs],
        "count": len(runs),
        "note": (
            "Robust runs are append-only: a changed design (seasons, profiles, "
            "regret flag), set content or engine version creates a new run."
        ),
    }


@router.get("/robust-runs/{run_id}")
def get_robust_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    strategies = (
        db.execute(
            select(dbm.RobustRotationStrategy)
            .where(dbm.RobustRotationStrategy.run_id == run.id)
            .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
        )
        .scalars()
        .all()
    )
    return {
        **robust_service.run_payload(run),
        "strategies": [robust_service.strategy_payload(s) for s in strategies],
    }


@router.get("/robust-runs/{run_id}/strategies")
def list_run_strategies(
    run_id: uuid.UUID,
    strategy_key: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    query = (
        select(dbm.RobustRotationStrategy)
        .where(dbm.RobustRotationStrategy.run_id == run.id)
        .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
    )
    if strategy_key:
        query = query.where(dbm.RobustRotationStrategy.strategy_key == strategy_key)
    rows = db.execute(query).scalars().all()
    return {
        "run_id": str(run.id),
        "items": [robust_service.strategy_payload(s) for s in rows],
        "count": len(rows),
    }


@router.get("/robust-runs/{run_id}/evaluations")
def list_run_evaluations(
    run_id: uuid.UUID,
    scenario_id: uuid.UUID | None = None,
    strategy_key: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    query = (
        select(dbm.RobustScenarioEvaluation)
        .where(dbm.RobustScenarioEvaluation.run_id == run.id)
        .order_by(dbm.RobustScenarioEvaluation.scenario_id.asc())
    )
    strategy_ids: list[uuid.UUID] | None = None
    if strategy_key:
        srow = db.scalar(
            select(dbm.RobustRotationStrategy).where(
                dbm.RobustRotationStrategy.run_id == run.id,
                dbm.RobustRotationStrategy.strategy_key == strategy_key,
            )
        )
        if srow is None:
            raise NotFound("Strategy key not found for this run.")
        strategy_ids = [srow.id]
        query = query.where(dbm.RobustScenarioEvaluation.strategy_id.in_(strategy_ids))
    if scenario_id is not None:
        query = query.where(dbm.RobustScenarioEvaluation.scenario_id == scenario_id)
    rows = db.execute(query).scalars().all()
    return {
        "run_id": str(run.id),
        "items": [robust_service.evaluation_payload(r) for r in rows],
        "count": len(rows),
        "note": (
            "One row per (shared plan, scenario): criteria with units and missing "
            "evidence, constraint checks, per-season crop admissibility under that "
            "scenario, scenario-normalized objective, Pareto flag and regret."
        ),
    }


@router.post("/robust-runs/{run_id}/verify")
def verify_robust_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    return robust_service.verify_run(db, run)

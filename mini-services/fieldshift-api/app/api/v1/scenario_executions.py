"""Scenario execution endpoints (Milestone 7.3).

- POST /scenarios/{scenario_id}/executions         — execute a FINALIZED scenario (idempotent)
- GET  /scenarios/{scenario_id}/executions         — the scenario's execution history
- GET  /scenario-executions/{run_id}               — run detail (status, checksums, provenance)
- GET  /scenario-executions/{run_id}/features      — derived feature rows (?evidence_status=)
- GET  /scenario-executions/{run_id}/observations  — derived observation rows (?variable_code=)
- GET  /scenario-executions/{run_id}/compare       — baseline vs scenario comparison
- POST /scenario-executions/{run_id}/verify        — independent checksum/parent verification

Every endpoint is tenant-scoped through the run/scenario's field → farm;
ownership claims from the client are never trusted. There is no way to
execute a non-finalized, invalid, unsupported or reference-only scenario, and
no endpoint mutates a result-bearing run.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal, require_farm_role
from app.scenario_execution import contracts as exc
from app.scenario_execution import service as execution_service
from app.scenarios import service as scenario_service

router = APIRouter(tags=["scenario-executions"])


def _get_run_scoped(db: Session, run_id: uuid.UUID, principal: Any) -> dbm.ScenarioExecutionRun:
    run = db.get(dbm.ScenarioExecutionRun, run_id)
    if run is None:
        raise NotFound("Scenario execution not found.")
    get_field_for_principal(db, principal, run.field_id)  # tenant scoping
    return run


@router.post("/scenarios/{scenario_id}/executions")
def execute_scenario(
    scenario_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = scenario_service.get_scenario(db, scenario_id)
    if scenario is None:
        raise NotFound("Scenario not found.")
    get_field_for_principal(db, principal, scenario.field_id)  # tenant scoping
    # RBAC (P0-2): executing a scenario runs the heavy engine — agronomist+.
    field = db.get(dbm.Field, scenario.field_id)
    require_farm_role(db, principal, db.get(dbm.Farm, field.farm_id), "agronomist")
    idempotency_key = (payload or {}).get("idempotency_key") or None
    try:
        run = execution_service.start_scenario_execution(
            db, scenario, idempotency_key=idempotency_key, created_by=principal.user
        )
    except exc.ExecutionBlockedError as blocked:
        raise ValidationFailed(
            str(blocked),
            details=blocked.findings,
            code="SCENARIO_EXECUTION_BLOCKED",
        ) from None
    return execution_service.run_payload(run, scenario=scenario)


@router.get("/scenarios/{scenario_id}/executions")
def list_scenario_executions(
    scenario_id: uuid.UUID,
    run_status: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = scenario_service.get_scenario(db, scenario_id)
    if scenario is None:
        raise NotFound("Scenario not found.")
    get_field_for_principal(db, principal, scenario.field_id)  # tenant scoping
    query = (
        select(dbm.ScenarioExecutionRun)
        .where(dbm.ScenarioExecutionRun.scenario_id == scenario.id)
        .order_by(dbm.ScenarioExecutionRun.created_at.desc())
    )
    if run_status:
        if run_status not in exc.RUN_STATUSES:
            raise ValidationFailed(
                "Unknown run_status filter.",
                details=[{"field": "run_status", "reason": run_status}],
            )
        query = query.where(dbm.ScenarioExecutionRun.run_status == run_status)
    runs = db.execute(query).scalars().all()
    return {
        "scenario_id": str(scenario.id),
        "items": [execution_service.run_payload(r, scenario=scenario) for r in runs],
        "note": (
            "Executions are derived hypothetical calculations. A result-bearing "
            "run is immutable; re-execution with any changed input or engine "
            "version creates a new run."
        ),
    }


@router.get("/scenario-executions/{run_id}")
def get_scenario_execution(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    return execution_service.run_payload(run)


@router.get("/scenario-executions/{run_id}/features")
def list_execution_features(
    run_id: uuid.UUID,
    evidence_status: str | None = None,
    feature_code: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    query = (
        select(dbm.ScenarioDerivedFeature)
        .where(dbm.ScenarioDerivedFeature.execution_run_id == run.id)
        .order_by(
            dbm.ScenarioDerivedFeature.feature_code,
            dbm.ScenarioDerivedFeature.aggregation_level,
            dbm.ScenarioDerivedFeature.period_label,
        )
    )
    if evidence_status:
        if evidence_status not in exc.FEATURE_EVIDENCE_STATUSES:
            raise ValidationFailed(
                "Unknown evidence_status filter.",
                details=[{"field": "evidence_status", "reason": evidence_status}],
            )
        query = query.where(dbm.ScenarioDerivedFeature.evidence_status == evidence_status)
    if feature_code:
        query = query.where(dbm.ScenarioDerivedFeature.feature_code == feature_code)
    rows = db.execute(query).scalars().all()
    return {
        "run_id": str(run.id),
        "items": [execution_service.derived_feature_payload(r) for r in rows],
        "count": len(rows),
    }


@router.get("/scenario-executions/{run_id}/observations")
def list_execution_observations(
    run_id: uuid.UUID,
    variable_code: str | None = None,
    limit: int = 200,
    offset: int = 0,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    if limit < 1 or limit > 1000 or offset < 0:
        raise ValidationFailed(
            "Pagination out of range (limit 1-1000, offset >= 0).",
            details=[{"field": "limit"}],
        )
    query = (
        select(dbm.ScenarioDerivedObservation)
        .where(dbm.ScenarioDerivedObservation.execution_run_id == run.id)
        .order_by(
            dbm.ScenarioDerivedObservation.variable_code,
            dbm.ScenarioDerivedObservation.period_start,
            dbm.ScenarioDerivedObservation.source_observation_id,
        )
    )
    if variable_code:
        query = query.where(dbm.ScenarioDerivedObservation.variable_code == variable_code)
    rows = db.execute(query.limit(limit).offset(offset)).scalars().all()
    return {
        "run_id": str(run.id),
        "items": [execution_service.derived_observation_payload(r) for r in rows],
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "total_transformed": run.transformed_observation_count,
        "note": (
            "Transformed values are scenario-derived hypothetical calculations "
            "— never observations of the real world. Baseline values are kept "
            "beside every transformed value."
        ),
    }


@router.get("/scenario-executions/{run_id}/compare")
def compare_execution(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    rows = db.execute(
        select(dbm.ScenarioDerivedFeature)
        .where(dbm.ScenarioDerivedFeature.execution_run_id == run.id)
        .order_by(
            dbm.ScenarioDerivedFeature.feature_code,
            dbm.ScenarioDerivedFeature.aggregation_level,
            dbm.ScenarioDerivedFeature.period_label,
        )
    ).scalars().all()
    return execution_service.comparison_payload(list(rows), run)


@router.post("/scenario-executions/{run_id}/verify")
def verify_execution(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    return execution_service.verify_execution(db, run)

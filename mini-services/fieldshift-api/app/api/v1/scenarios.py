"""Scenario endpoints (Milestone 7.2).

- POST   /fields/{field_id}/scenarios          — create a draft definition (or idempotent replay)
- GET    /fields/{field_id}/scenarios          — list the field's scenarios
- GET    /scenarios/types                      — versioned taxonomy + capability matrix (static)
- GET    /scenarios/capabilities               — platform scenario capabilities (static, honest)
- GET    /scenarios/{scenario_id}              — definition detail
- PATCH  /scenarios/{scenario_id}              — edit a non-finalized definition (resets validation)
- DELETE /scenarios/{scenario_id}              — delete a DRAFT only (else archive)
- POST   /scenarios/{scenario_id}/validate     — run the pure validation engine (immutable record)
- POST   /scenarios/{scenario_id}/finalize     — freeze the definition (immutable thereafter)
- POST   /scenarios/{scenario_id}/archive      — terminal, checksum-preserving retirement
- POST   /scenarios/{scenario_id}/versions     — new version of a FINALIZED scenario
- GET    /scenarios/{scenario_id}/versions     — the revision chain
- GET    /scenarios/{scenario_id}/lineage      — ancestors + children + revision chain
- GET    /scenarios/{scenario_id}/verify       — independent checksum/parent verification
- GET    /scenarios/{scenario_id}/compare      — definition-level comparison (?against=)

There is NO run/execute endpoint: M7.2 defines scenarios, it does not
simulate them (M7.3 does not exist). Every dynamic endpoint is tenant-scoped
through the field's farm; ownership claims from the client are never
trusted.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ValidationFailed
from app.domains.identity.service import get_field_for_principal, get_principal
from app.scenarios import service as scenario_service

router = APIRouter(tags=["scenarios"])


def _get_scenario_scoped(
    db: Session, scenario_id: uuid.UUID, principal: Any
):
    scenario = scenario_service.get_scenario(db, scenario_id)
    if scenario is None:
        from app.core.errors import NotFound

        raise NotFound("Scenario not found.")
    get_field_for_principal(db, principal, scenario.field_id)  # tenant scoping
    return scenario


@router.post("/fields/{field_id}/scenarios")
def create_scenario(
    field_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)  # tenant scoping
    scenario = scenario_service.create_scenario(
        db, field=field, payload=payload, created_by=principal.user
    )
    return scenario_service.scenario_payload(scenario)


@router.get("/fields/{field_id}/scenarios")
def list_scenarios(
    field_id: uuid.UUID,
    scenario_type: str | None = None,
    scenario_status: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)  # tenant scoping
    items = scenario_service.list_scenarios(
        db, field.id, scenario_type=scenario_type, scenario_status=scenario_status
    )
    return {"items": [scenario_service.scenario_payload(s) for s in items]}


@router.get("/scenarios/types")
def scenario_types() -> dict:
    """Static taxonomy: types, capability status, evidence classes, bounds."""
    return scenario_service.taxonomy_payload()


@router.get("/scenarios/capabilities")
def scenario_capabilities() -> dict:
    """Static capability report: what exists, what is unavailable, and why."""
    return scenario_service.capabilities_payload()


@router.get("/scenarios/{scenario_id}")
def get_scenario(
    scenario_id: uuid.UUID,
    include_validation_history: bool = False,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    return scenario_service.scenario_payload(
        scenario, db=db, include_validation_history=include_validation_history
    )


@router.patch("/scenarios/{scenario_id}")
def patch_scenario(
    scenario_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    updated = scenario_service.patch_scenario(db, scenario, payload)
    return scenario_service.scenario_payload(updated)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    scenario_service.delete_scenario(db, scenario)
    return {"deleted": True, "scenario_id": str(scenario_id)}


@router.post("/scenarios/{scenario_id}/validate")
def validate_scenario(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    return scenario_service.validate_scenario(db, scenario, created_by=principal.user)


@router.post("/scenarios/{scenario_id}/finalize")
def finalize_scenario(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    finalized = scenario_service.finalize_scenario(db, scenario, created_by=principal.user)
    return scenario_service.scenario_payload(finalized)


@router.post("/scenarios/{scenario_id}/archive")
def archive_scenario(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    archived = scenario_service.archive_scenario(db, scenario)
    return scenario_service.scenario_payload(archived)


@router.post("/scenarios/{scenario_id}/versions")
def create_scenario_version(
    scenario_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    version = scenario_service.create_scenario_version(
        db, scenario, payload, created_by=principal.user
    )
    return scenario_service.scenario_payload(version)


@router.get("/scenarios/{scenario_id}/versions")
def list_scenario_versions(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    return scenario_service.list_versions(db, scenario)


@router.get("/scenarios/{scenario_id}/lineage")
def scenario_lineage(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    return scenario_service.get_lineage(db, scenario)


@router.get("/scenarios/{scenario_id}/verify")
def verify_scenario(
    scenario_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    return scenario_service.verify_scenario(db, scenario)


@router.get("/scenarios/{scenario_id}/compare")
def compare_scenarios(
    scenario_id: uuid.UUID,
    against: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    scenario = _get_scenario_scoped(db, scenario_id, principal)
    if not against:
        raise ValidationFailed(
            "Query parameter 'against' (another scenario id) is required.",
            details=[{"field": "against"}],
        )
    try:
        against_id = uuid.UUID(str(against))
    except (TypeError, ValueError):
        raise ValidationFailed(
            "'against' must be a scenario UUID.",
            details=[{"field": "against"}],
        ) from None
    other = scenario_service.get_scenario(db, against_id)
    if other is None:
        from app.core.errors import NotFound

        raise NotFound("Scenario not found.")
    get_field_for_principal(db, principal, other.field_id)  # tenant-scope the second side
    return scenario_service.compare_scenarios(db, scenario, other)

"""Adaptive Evidence Acquisition endpoints (P2.E).

- GET  /fields/{id}/evidence-gaps          — detect + VoI + acquisition plans
- GET  /fields/{id}/evidence/staleness     — dependency-graph staleness report
- GET  /fields/{id}/evidence-actions       — acquisition action list
- POST /fields/{id}/evidence-actions       — create an acquisition action
- POST /evidence-actions/{action_id}/transition — lifecycle transition
- GET  /evidence-actions/{action_id}       — action + append-only event history
- POST /fields/{id}/evidence/apply         — recalculation after new evidence

All field-scoped endpoints are tenant-scoped through the field's farm.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.identity.service import get_field_for_principal, get_principal
from app.evidence_gaps import service as gaps_service
from app.intelligence import dependencies

router = APIRouter(tags=["evidence-gaps"])


class ActionCreateRequest(BaseModel):
    gap_code: str
    action_type: str
    title: str
    plan: dict[str, Any] | None = None


class ActionTransitionRequest(BaseModel):
    to_status: str = Field(..., description="suggested|in_progress|submitted|resolved|dismissed")
    note: str | None = None


class EvidenceApplyRequest(BaseModel):
    ref_kind: str = Field(..., description="ingestion_job|soil_sample|crop_history|water_plan|field_state")
    ref_id: uuid.UUID | None = None
    action_id: uuid.UUID | None = None
    note: str | None = None


@router.get("/fields/{field_id}/evidence-gaps")
def field_evidence_gaps(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Detect evidence gaps against the live platform state, with a
    decision-aware (structural, non-monetary) Value-of-Information estimate
    and actionable acquisition plans."""
    field = get_field_for_principal(db, principal, field_id)
    return gaps_service.refresh_gap_report(db, field)


@router.get("/fields/{field_id}/evidence/staleness")
def field_evidence_staleness(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Which downstream artifacts are older than the newest evidence in the
    domains they depend on (declarative dependency graph; dynamic staleness
    — invalidates only what actually depends on changed evidence)."""
    field = get_field_for_principal(db, principal, field_id)
    return dependencies.staleness_report(db, field)


@router.get("/fields/{field_id}/evidence-actions")
def list_evidence_actions(
    field_id: uuid.UUID,
    status: str | None = Query(None),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return {
        "field_id": str(field.id),
        "actions": gaps_service.list_actions(db, field, status=status),
    }


@router.post("/fields/{field_id}/evidence-actions")
def create_evidence_action(
    field_id: uuid.UUID,
    request: ActionCreateRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return gaps_service.create_action(
        db,
        field,
        principal,
        gap_code=request.gap_code,
        action_type=request.action_type,
        title=request.title,
        plan=request.plan,
    )


@router.post("/evidence-actions/{action_id}/transition")
def transition_evidence_action(
    action_id: uuid.UUID,
    request: ActionTransitionRequest,
    field_id: uuid.UUID = Query(..., description="Tenant-scoping field id"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return gaps_service.transition_action(
        db, field, principal, action_id=action_id, to_status=request.to_status, note=request.note
    )


@router.get("/evidence-actions/{action_id}")
def evidence_action_history(
    action_id: uuid.UUID,
    field_id: uuid.UUID = Query(..., description="Tenant-scoping field id"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return gaps_service.action_history(db, field, action_id)


@router.post("/fields/{field_id}/evidence/apply")
def apply_evidence(
    field_id: uuid.UUID,
    request: EvidenceApplyRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Recalculate the affected downstream engines after new evidence
    arrives: validate the reference, resolve the linked acquisition action,
    append a fresh feature run when needed, refresh recommendations, and
    return a fingerprint-diff change report (which decisions changed)."""
    field = get_field_for_principal(db, principal, field_id)
    return dependencies.apply_new_evidence(
        db,
        field,
        principal,
        ref_kind=request.ref_kind,
        ref_id=request.ref_id,
        action_id=request.action_id,
        note=request.note,
    )

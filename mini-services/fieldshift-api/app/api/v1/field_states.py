"""Field State endpoints (Milestone 7.1).

- POST /fields/{id}/field-states        — assemble an immutable state (202-style)
- GET  /fields/{id}/field-states        — list the field's states
- GET  /field-states/{id}               — state detail (immutable snapshot)
- GET  /field-states/{id}/verify        — independent checksum/artifact verification
- GET  /field-states/{id}/manifest      — the stored observation manifest document
- POST /field-states/compare            — compare compatible states (explicit only)

All endpoints are tenant-scoped through the field's farm. Soil (M6B) and
management (M6C) dimensions are reported as `not_implemented` — they do not
exist in this repository and are never fabricated.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.field_state import service as field_state_service
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["field-state"])


@router.post("/fields/{field_id}/field-states", status_code=status.HTTP_202_ACCEPTED)
def create_field_state(
    field_id: uuid.UUID,
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Assemble a new field-state snapshot (or idempotently return the
    existing one for a repeated idempotency key). The state is a by-reference
    composition of existing artifacts — recomputation creates a NEW row."""
    field = get_field_for_principal(db, principal, field_id)  # tenant scoping
    state = field_state_service.assemble_field_state(db, field=field, payload=payload, created_by=principal.user)
    return field_state_service.state_payload(state)


@router.get("/fields/{field_id}/field-states")
def list_field_states(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)  # tenant scoping
    states = field_state_service.list_field_states(db, field_id)
    return {"items": [field_state_service.state_payload(s) for s in states]}


def _get_state_scoped(db: Session, state_id: uuid.UUID, principal: Any):
    state = field_state_service.get_field_state(db, state_id)
    if state is None:
        from app.core.errors import NotFound

        raise NotFound("Field state not found.")
    get_field_for_principal(db, principal, state.field_id)  # tenant scoping
    return state


@router.get("/field-states/{state_id}")
def get_field_state(
    state_id: uuid.UUID,
    include_manifest: bool = False,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    state = _get_state_scoped(db, state_id, principal)
    return field_state_service.state_payload(state, include_manifest=include_manifest)


@router.get("/field-states/{state_id}/verify")
def verify_field_state(
    state_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    state = _get_state_scoped(db, state_id, principal)
    return field_state_service.verify_field_state(db, state)


@router.get("/field-states/{state_id}/manifest")
def get_state_manifest(
    state_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    state = _get_state_scoped(db, state_id, principal)
    return {
        "state_id": str(state.id),
        "manifest_format_version": state.manifest_format_version,
        "observation_manifest_sha256": state.observation_manifest_sha256,
        "observation_manifest": state.observation_manifest,
    }


@router.post("/field-states/compare")
def compare_field_states(
    payload: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    state_ids = payload.get("state_ids") or []
    try:
        parsed = [uuid.UUID(str(sid)) for sid in state_ids]
    except (TypeError, ValueError):
        from app.core.errors import ValidationFailed

        raise ValidationFailed(
            "state_ids must be a list of UUIDs.", details=[{"field": "state_ids"}]
        ) from None
    # Tenant-scope every state before comparison.
    for sid in parsed:
        _get_state_scoped(db, sid, principal)
    return field_state_service.compare_field_states(db, parsed)

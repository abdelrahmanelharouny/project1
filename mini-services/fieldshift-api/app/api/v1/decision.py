"""Decision comparison endpoints (Milestone 7.6).

- POST /fields/{field_id}/decision-comparisons   — generate (idempotent)
- GET  /fields/{field_id}/decision-comparisons   — list
- GET  /decision-comparisons/{id}                — detail (full document)
- POST /decision-comparisons/{id}/verify         — checksum + source pins

Every endpoint is tenant-scoped through the document's field → farm. No
endpoint mutates a result-bearing document (application + database trigger).
The document contains no composite scores, probabilities or recommendations —
only evidence-linked findings and explicitly unavailable sections.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.decision import contracts as dc
from app.decision import service as decision_service
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["decision"])


def _get_comparison_scoped(
    db: Session, comparison_id: uuid.UUID, principal: Any
) -> dbm.DecisionComparison:
    row = db.get(dbm.DecisionComparison, comparison_id)
    if row is None:
        raise NotFound("Decision comparison not found.")
    get_field_for_principal(db, principal, row.field_id)  # tenant scoping
    return row


@router.post("/fields/{field_id}/decision-comparisons")
def create_decision_comparison(
    field_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    row = decision_service.generate_decision_comparison(
        db, field, payload=payload or {}, created_by=principal.user
    )
    return decision_service.comparison_payload(row)


@router.get("/fields/{field_id}/decision-comparisons")
def list_decision_comparisons(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    rows = (
        db.execute(
            select(dbm.DecisionComparison)
            .where(dbm.DecisionComparison.field_id == field_id)
            .order_by(dbm.DecisionComparison.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "field_id": str(field_id),
        "items": [decision_service.comparison_payload(r, include_document=False) for r in rows],
        "count": len(rows),
        "note": (
            "Documents are append-only: a changed scope or generator version "
            "creates a new document; identical scope regenerates the same row."
        ),
    }


@router.get("/decision-comparisons/{comparison_id}")
def get_decision_comparison(
    comparison_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_comparison_scoped(db, comparison_id, principal)
    return decision_service.comparison_payload(row)


@router.post("/decision-comparisons/{comparison_id}/verify")
def verify_decision_comparison(
    comparison_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_comparison_scoped(db, comparison_id, principal)
    return decision_service.verify_comparison(db, row)

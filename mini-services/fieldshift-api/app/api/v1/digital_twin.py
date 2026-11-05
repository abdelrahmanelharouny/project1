"""Digital twin endpoints (Milestone 7.7).

- GET  /fields/{field_id}/digital-twin           — unified field-level view
- POST /fields/{field_id}/digital-twin/validate  — bounded integrity walk (persisted)
- GET  /fields/{field_id}/digital-twin/validations — validation history

Every endpoint is tenant-scoped through the field → farm. The view is
read-only assembly; validation reuses the existing per-artifact verifiers.
No predictive, autonomous or forecasting capability is claimed anywhere.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db import models as dbm
from app.digital_twin import service as twin_service
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["digital-twin"])


@router.get("/fields/{field_id}/digital-twin")
def get_field_twin(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return twin_service.build_field_twin(db, field)


@router.post("/fields/{field_id}/digital-twin/validate")
def validate_field_twin(
    field_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    row = twin_service.run_twin_validation(
        db,
        field,
        created_by=principal.user,
        idempotency_key=(payload or {}).get("idempotency_key"),
    )
    return twin_service.validation_payload(row)


@router.get("/fields/{field_id}/digital-twin/validations")
def list_twin_validations(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    rows = (
        db.execute(
            select(dbm.DigitalTwinValidation)
            .where(dbm.DigitalTwinValidation.field_id == field_id)
            .order_by(dbm.DigitalTwinValidation.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return {
        "field_id": str(field_id),
        "items": [
            {
                "id": str(r.id),
                "overall_status": r.overall_status,
                "artifacts_checked": r.artifacts_checked,
                "artifacts_failed": r.artifacts_failed,
                "report_checksum": r.report_checksum,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
        "note": (
            "Validations are append-only, checksummed re-verification walks over "
            "the field's twin artifacts (bounded to the newest of each class)."
        ),
    }

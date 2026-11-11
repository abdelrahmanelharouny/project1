"""Onboarding endpoints (P3 W4): resumable, non-blocking progress machine.

Wraps `app/onboarding/service.py`. All routes are USER-scoped (the progress
row belongs to the authenticated caller) — no organization gate.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.identity.service import get_principal
from app.onboarding import service as onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class StepComplete(BaseModel):
    data: dict[str, Any] | None = None


class AccountTypeSet(BaseModel):
    account_type: str = Field(pattern="^(individual|business|farm_org)$")


@router.get("/progress")
def get_progress(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """The caller's onboarding progress (creates the row on first access)."""
    row = onboarding_service.get_or_create_progress(db, principal.id)
    return onboarding_service.progress_payload(row)


@router.post("/steps/{step}/complete")
def complete_step(
    step: str,
    payload: StepComplete | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Mark a step complete (unknown steps are rejected by the service)."""
    row = onboarding_service.complete_step(
        db,
        principal.id,
        step=step,
        data=payload.data if payload else None,
    )
    return onboarding_service.progress_payload(row)


@router.post("/skip/{step}")
def skip_step(
    step: str,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Skip an optional step (required steps cannot be skipped)."""
    row = onboarding_service.skip_step(db, principal.id, step=step)
    return onboarding_service.progress_payload(row)


@router.post("/account-type")
def set_account_type(
    payload: AccountTypeSet,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Record the account type (individual / business / farm_org)."""
    row = onboarding_service.set_account_type(
        db, principal.id, account_type=payload.account_type
    )
    return onboarding_service.progress_payload(row)


@router.post("/dismiss")
def dismiss_tour(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = onboarding_service.dismiss_tour(db, principal.id)
    return onboarding_service.progress_payload(row)

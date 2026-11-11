"""User preference endpoints (P3 W9.2): global product configuration.

Wraps `app/preferences/service.py`. Preferences are USER-scoped (no
organization gate); internal units stay SI/metric — this setting governs
PRESENTATION conversions only.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.identity.service import get_principal
from app.preferences import service as preferences_service

router = APIRouter(prefix="/preferences", tags=["preferences"])


class PreferencesUpdate(BaseModel):
    """All fields optional — partial updates. Validation (locale set, unit
    systems, week start, ISO codes, timezone shape) lives in the service."""

    locale: str | None = Field(default=None, min_length=2, max_length=10)
    timezone: str | None = Field(default=None, min_length=1, max_length=60)
    unit_system: str | None = Field(default=None, pattern="^(metric|imperial)$")
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    week_start: str | None = Field(
        default=None, pattern="^(monday|sunday|saturday)$"
    )
    agricultural_calendar: str | None = Field(default=None, max_length=60)
    notify_in_app: bool | None = None
    notify_email: bool | None = None


@router.get("")
def get_preferences(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """The caller's preferences (defaults are created on first access)."""
    row = preferences_service.get_preferences(db, principal.id)
    return preferences_service.preferences_payload(row)


@router.put("")
def update_preferences(
    payload: PreferencesUpdate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Partial update: only the fields present in the request body change
    (explicit nulls clear nullable fields such as country_code)."""
    changes = payload.model_dump(exclude_unset=True)
    row = preferences_service.update_preferences(db, principal.id, **changes)
    return preferences_service.preferences_payload(row)

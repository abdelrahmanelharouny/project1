"""Farms endpoints (Master §41 — farms and fields group)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.farms_fields import service as farm_service
from app.domains.identity.service import get_principal, require_farm_role

router = APIRouter(prefix="/farms", tags=["farms"])


class FarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country_code: str = Field(min_length=2, max_length=2)
    admin_region: str | None = Field(default=None, max_length=200)
    timezone: str = Field(default="UTC", max_length=60)
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    unit_system: str = Field(default="metric", pattern="^(metric|imperial)$")
    preferred_language: str = Field(default="en", max_length=10)


class FarmPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    admin_region: str | None = None
    timezone: str | None = None
    currency_code: str | None = None
    unit_system: str | None = Field(default=None, pattern="^(metric|imperial)$")
    preferred_language: str | None = None


@router.post("", status_code=201)
def create_farm(
    payload: FarmCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = farm_service.create_farm(db, principal, payload.model_dump())
    return farm_service.farm_payload(db, farm)


@router.get("")
def list_farms(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    items = farm_service.list_farms(db, principal)
    return {"items": items, "total": len(items)}


@router.get("/{farm_id}")
def get_farm(
    farm_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.domains.identity.service import get_farm_for_principal

    farm = get_farm_for_principal(db, principal, farm_id)
    return farm_service.farm_payload(db, farm)


@router.patch("/{farm_id}")
def patch_farm(
    farm_id: uuid.UUID,
    payload: FarmPatch,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.domains.identity.service import get_farm_for_principal

    farm = get_farm_for_principal(db, principal, farm_id)
    # RBAC (P0-2): farm edits are manager+ mutations.
    require_farm_role(db, principal, farm, "manager")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(farm, key, value)
    db.commit()
    return farm_service.farm_payload(db, farm)

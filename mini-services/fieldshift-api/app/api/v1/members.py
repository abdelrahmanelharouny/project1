"""Organization membership management endpoints (auth hardening P0-2).

All routes are farm-scoped: the farm is resolved through
get_farm_for_principal first (tenant check), then the role gate is enforced
inside the identity service (GET manager+, mutations owner-only).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db.models import Membership
from app.domains.identity.service import (
    add_member,
    get_farm_for_principal,
    get_principal,
    list_members,
    remove_member,
    update_member_role,
)

router = APIRouter(tags=["members"])


class MemberAdd(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role_code: str = Field(pattern="^(owner|manager|agronomist|viewer)$")


class MemberPatch(BaseModel):
    role_code: str = Field(pattern="^(owner|manager|agronomist|viewer)$")


def _member_payload(membership: Membership) -> dict[str, Any]:
    user = membership.user
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": user.email,
        "display_name": user.display_name,
        "role_code": membership.role_code,
        "status": membership.status,
        "created_at": membership.created_at.isoformat(),
    }


@router.get("/farms/{farm_id}/members")
def list_farm_members(
    farm_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    items = list_members(db, principal, farm)
    return {"items": items, "total": len(items)}


@router.post("/farms/{farm_id}/members", status_code=status.HTTP_201_CREATED)
def add_farm_member(
    farm_id: uuid.UUID,
    payload: MemberAdd,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    membership = add_member(
        db, principal, farm, email=payload.email, role_code=payload.role_code
    )
    return _member_payload(membership)


@router.patch("/farms/{farm_id}/members/{membership_id}")
def patch_farm_member(
    farm_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberPatch,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    membership = update_member_role(
        db, principal, farm, membership_id, payload.role_code
    )
    return _member_payload(membership)


@router.delete("/farms/{farm_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_farm_member(
    farm_id: uuid.UUID,
    membership_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    farm = get_farm_for_principal(db, principal, farm_id)
    remove_member(db, principal, farm, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

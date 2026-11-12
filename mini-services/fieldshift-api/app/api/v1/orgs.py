"""Organization lifecycle, member directory, ownership transfer, invitations.

P3 Workstream A — wraps `app/orgs/service.py`. Authorization checks live
INSIDE the service (`principal.require_org_role` / `require_member_of`);
routes only resolve path parameters and serialize (Master rule 16).

Role set (migration 0020, 7 roles): viewer / analyst / agronomist / operator
/ manager / org_admin / owner. `owner` and `org_admin` share rank 3; only
the owner can transfer ownership.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db.models import Membership, Organization
from app.domains.identity.service import ROLE_ORDER, get_principal
from app.core.errors import Forbidden, NotFound
from app.orgs import service as orgs_service

router = APIRouter(tags=["orgs"])


# --------------------------------------------------------------- helpers
def _org_payload(org: Organization, my_role: str | None = None) -> dict[str, Any]:
    return {
        "id": str(org.id),
        "name": org.name,
        "organization_type": org.organization_type,
        "country_code": org.country_code,
        "created_at": org.created_at.isoformat(),
        "updated_at": org.updated_at.isoformat(),
        "my_role": my_role,
    }


def _invitation_payload(invitation: Any, token: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(invitation.id),
        "organization_id": str(invitation.organization_id),
        "email": invitation.email,
        "role_code": invitation.role_code,
        "status": invitation.status,
        "invited_by": str(invitation.invited_by) if invitation.invited_by else None,
        "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
        "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
        "revoked_at": invitation.revoked_at.isoformat() if invitation.revoked_at else None,
        "created_at": invitation.created_at.isoformat(),
    }
    if token is not None:
        # Plaintext token is returned ONCE (out-of-band delivery); only the
        # hash is stored. Email transport is a channel-adapter concern and is
        # NOT claimed operational (P3 §7.3).
        payload["token"] = token
        payload["note"] = (
            "Invite token is shown once — deliver it to the invitee out-of-band."
        )
    return payload


def _membership_by_user(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID
) -> Membership:
    """Resolve a member directory entry by USER id (the org routes address
    members by user; the service layer works with membership ids)."""
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise NotFound("Member not found in this organization.")
    return membership


def _oldest_active_org_id(principal: Any) -> uuid.UUID | None:
    active = [m for m in principal.memberships if m.status == "active"]
    if not active:
        return None
    active.sort(key=lambda m: (m.created_at or datetime.now(UTC), m.organization_id))
    return active[0].organization_id


# ------------------------------------------------------------ request models
class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    organization_type: str = Field(pattern="^(individual|business|farm_org)$")
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class OrgPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    organization_type: str | None = Field(
        default=None, pattern="^(individual|business|farm_org)$"
    )
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class MemberRolePatch(BaseModel):
    role_code: str

    @field_validator("role_code")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in ROLE_ORDER:
            raise ValueError(
                "role_code must be one of: " + ", ".join(sorted(ROLE_ORDER))
            )
        return v


class OwnershipTransfer(BaseModel):
    target_user_id: uuid.UUID


class InvitationCreate(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role_code: str

    @field_validator("role_code")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in ROLE_ORDER:
            raise ValueError(
                "role_code must be one of: " + ", ".join(sorted(ROLE_ORDER))
            )
        return v


class InvitationAccept(BaseModel):
    token: str = Field(min_length=16, max_length=200)


# ------------------------------------------------------------------- routes
@router.post("/orgs", status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrgCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new organization with the caller as owner (onboarding)."""
    org = orgs_service.create_organization_for_user(
        db,
        principal,
        name=payload.name,
        organization_type=payload.organization_type,
        country_code=payload.country_code,
    )
    return _org_payload(org, my_role="owner")


@router.get("/orgs")
def list_my_organizations(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Organizations the caller actively belongs to, with their role."""
    items = []
    for membership in principal.memberships:
        if membership.status != "active":
            continue
        org = db.get(Organization, membership.organization_id)
        if org is None:  # pragma: no cover — membership FK guarantees org
            continue
        items.append(_org_payload(org, my_role=membership.role_code))
    items.sort(key=lambda o: o["created_at"])
    return {"items": items, "total": len(items)}


@router.get("/orgs/{org_id}")
def get_organization(
    org_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    membership = principal.require_org_role(org_id, "viewer")  # member gate
    org = db.get(Organization, org_id)
    if org is None:  # pragma: no cover — membership FK guarantees org
        raise NotFound("Organization not found.")
    return _org_payload(org, my_role=membership.role_code)


@router.patch("/orgs/{org_id}")
def patch_organization(
    org_id: uuid.UUID,
    payload: OrgPatch,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # org_admin+ (service re-checks and audits).
    data = payload.model_dump(exclude_unset=True)
    org = orgs_service.update_organization(db, principal, organization_id=org_id, **data)
    membership = principal.membership_in(org_id)
    return _org_payload(org, my_role=membership.role_code if membership else None)


@router.get("/orgs/{org_id}/members")
def list_organization_members(
    org_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    items = orgs_service.list_org_members(db, principal, organization_id=org_id)
    return {"items": items, "total": len(items)}


@router.patch("/orgs/{org_id}/members/{user_id}")
def change_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRolePatch,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # org_admin+ gate; the service enforces "only owner grants owner/org_admin"
    # and the last-owner guard.
    gate = principal.require_org_role(org_id, "org_admin")
    membership = _membership_by_user(db, org_id, user_id)
    # Route policy (Task 3): ownership is managed via the ownership-transfer
    # flow — a non-owner admin cannot change an owner's role through this
    # route. The organization owner retains owner-management rights here.
    if membership.role_code == "owner" and gate.role_code != "owner":
        raise Forbidden(
            "Only the organization owner can change an owner's role here; "
            "use the ownership-transfer flow to move ownership."
        )
    return orgs_service.update_org_member_role(
        db,
        principal,
        organization_id=org_id,
        membership_id=membership.id,
        new_role=payload.role_code,
    )


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_organization_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    # org_admin+ (service gate). The service refuses self-removal (Conflict)
    # and protects the last owner; see P3-3 notes for the self-serve
    # "leave organization" deviation.
    membership = _membership_by_user(db, org_id, user_id)
    orgs_service.remove_org_member(
        db, principal, organization_id=org_id, membership_id=membership.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orgs/{org_id}/ownership-transfer")
def transfer_ownership(
    org_id: uuid.UUID,
    payload: OwnershipTransfer,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # Authorize the ACTOR first (exact owner gate), then resolve the target.
    # Resolving the target before the gate would leak membership existence
    # (404) to callers who must never learn anything about this org (403).
    orgs_service._require_owner(principal, org_id)
    membership = _membership_by_user(db, org_id, payload.target_user_id)
    return orgs_service.transfer_ownership(
        db,
        principal,
        organization_id=org_id,
        target_membership_id=membership.id,
    )


@router.post("/orgs/{org_id}/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    org_id: uuid.UUID,
    payload: InvitationCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    invitation, token = orgs_service.create_invitation(
        db,
        principal,
        organization_id=org_id,
        email=payload.email,
        role_code=payload.role_code,
    )
    return _invitation_payload(invitation, token=token)


@router.get("/orgs/{org_id}/invitations")
def list_invitations(
    org_id: uuid.UUID,
    invitation_status: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # org_admin+ (service gate).
    rows = orgs_service.list_invitations(
        db, principal, organization_id=org_id, status=invitation_status
    )
    return {
        "items": [_invitation_payload(row) for row in rows],
        "total": len(rows),
    }


@router.delete(
    "/orgs/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    # org_admin+ (service gate); pending invitations only.
    orgs_service.revoke_invitation(
        db, principal, organization_id=org_id, invitation_id=invitation_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/accept")
def accept_invitation(
    payload: InvitationAccept,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Accept a pending invitation as the AUTHENTICATED user (invite email
    must match the caller's account email — enforced in the service)."""
    membership = orgs_service.accept_invitation(db, principal, token=payload.token)
    return {
        "id": str(membership.id),
        "organization_id": str(membership.organization_id),
        "user_id": str(membership.user_id),
        "role_code": membership.role_code,
        "status": membership.status,
        "joined_at": membership.created_at.isoformat(),
    }

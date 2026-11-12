"""Organization lifecycle services (P3 W3).

Invitations (single-use hashed tokens, expiry, revoke), organization-level
member directory, ownership transfer with last-owner and cross-tenant
guards. Every mutation writes BOTH an auth audit event (integrity surface)
and an activity timeline event (user-facing history).

Tenant isolation rules enforced here:
- Invitations are created only by owner/org_admin of THAT organization.
- Accepting requires an authenticated user whose email matches the invite.
- Ownership transfer requires the current owner; the target must be an
  active member of the same organization.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.billing import entitlements
from app.core.config import settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.security import generate_token
from app.db.models import Farm, Membership, Organization, User
from app.db.models_p3 import Invitation
from app.domains.identity.service import (
    ASSIGNABLE_ROLES,
    ROLE_ORDER,
    Principal,
    record_auth_audit,
)

INVITATION_TTL_SECONDS = 7 * 24 * 3600

# Roles a member may be granted. owner is only grantable by an owner
# (enforced in invite/update paths below).
_GRANTABLE = set(ASSIGNABLE_ROLES)


def _require_org_admin(db: Session, principal: Principal, organization_id: uuid.UUID) -> Membership:
    """owner or org_admin gate for organization administration."""
    return principal.require_org_role(organization_id, "org_admin")


def _require_owner(principal: Principal, organization_id: uuid.UUID) -> Membership:
    return principal.require_owner(organization_id)


# ------------------------------------------------------------- invitations
def create_invitation(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    email: str,
    role_code: str,
) -> tuple[Invitation, str]:
    """Invite an email to the organization. Returns (invitation, plain_token).

    The plaintext token is returned ONCE for out-of-band delivery (email in
    production; dev convenience in the sandbox) — only the SHA-256 hash is
    stored. Sending email is a provider-adapter concern and is NOT claimed
    operational (P3 §7.3).
    """
    membership = _require_org_admin(db, principal, organization_id)
    if membership.role_code != "owner" and role_code == "owner":
        raise Forbidden("Only an owner can create owner invitations.")
    if role_code not in _GRANTABLE:
        raise ValidationFailed(
            f"Unknown role '{role_code}'.",
            details=[{"field": "role_code", "reason": role_code}],
        )
    email_normalized = email.strip().lower()
    # Cannot invite someone who is already an active member.
    existing_user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if existing_user is not None:
        already = db.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == existing_user.id,
                Membership.status == "active",
            )
        )
        if already is not None:
            raise Conflict("This user is already a member of this organization.")
    # One pending invitation per (org, email).
    pending = db.scalar(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            func.lower(Invitation.email) == email_normalized,
            Invitation.status == "pending",
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if pending is not None:
        raise Conflict("A pending invitation for this email already exists.")

    plain, token_hash, _ = generate_token(ttl_seconds=INVITATION_TTL_SECONDS)
    invitation = Invitation(
        organization_id=organization_id,
        email=email_normalized,
        role_code=role_code,
        token_hash=token_hash,
        status="pending",
        invited_by=principal.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=INVITATION_TTL_SECONDS),
    )
    db.add(invitation)
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=organization_id,
        action="invitation.create",
        entity_type="invitation",
        entity_id=str(invitation.id),
        meta={"email": email_normalized, "role_code": role_code},
    )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_MEMBER_INVITED,
        summary=f"Invited {email_normalized} as {role_code}",
        actor_user_id=principal.id,
        entity_kind="invitation",
        entity_id=str(invitation.id),
        details={"email": email_normalized, "role_code": role_code},
    )
    db.commit()
    db.refresh(invitation)
    return invitation, plain


def list_invitations(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    status: str | None = None,
) -> list[Invitation]:
    _require_org_admin(db, principal, organization_id)
    conditions = [Invitation.organization_id == organization_id]
    if status:
        if status not in ("pending", "accepted", "revoked", "expired"):
            raise ValidationFailed("Unknown invitation status filter.")
        conditions.append(Invitation.status == status)
    return list(
        db.scalars(
            select(Invitation)
            .where(*conditions)
            .order_by(Invitation.created_at.desc())
            .limit(200)
        ).all()
    )


def revoke_invitation(
    db: Session, principal: Principal, *, organization_id: uuid.UUID, invitation_id: uuid.UUID
) -> Invitation:
    _require_org_admin(db, principal, organization_id)
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.organization_id == organization_id
        )
    )
    if invitation is None:
        raise NotFound("Invitation not found.")
    if invitation.status != "pending":
        raise Conflict(f"Invitation is {invitation.status}, cannot revoke.")
    invitation.status = "revoked"
    invitation.revoked_at = datetime.now(UTC)
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=organization_id,
        action="invitation.revoke",
        entity_type="invitation",
        entity_id=str(invitation.id),
        meta={"email": invitation.email},
    )
    db.commit()
    db.refresh(invitation)
    return invitation


def accept_invitation(db: Session, principal: Principal, *, token: str) -> Membership:
    """Accept a pending invitation as the AUTHENTICATED user.

    The invite email must match the caller's account email — invitation
    tokens are not transferable credentials (they only authorize joining as
    the invited address).
    """
    from app.core.security import hash_token

    token_hash = hash_token(token)
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash))
    if invitation is None:
        raise NotFound("Invitation not found.")
    if invitation.status != "pending":
        raise Conflict(f"Invitation is {invitation.status}.")
    if invitation.expires_at < datetime.now(UTC):
        invitation.status = "expired"
        db.commit()
        raise Conflict("Invitation has expired.")
    if principal.user.email.strip().lower() != invitation.email:
        raise Forbidden("This invitation was issued to a different email address.")
    already = db.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == principal.id,
        )
    )
    if already is not None:
        if already.status == "active":
            raise Conflict("You are already a member of this organization.")
        already.status = "active"
        already.role_code = invitation.role_code
        membership = already
    else:
        # Seat cap enforcement (P3 §4.2): activating a membership consumes a
        # seat. Same conditionality contract as the farm/field gates — the
        # limit bites ONLY when the target organization carries a live
        # subscription, so org-less / legacy personal accounts (P1/P2 golden
        # flows, seed/demo users) pass through untouched. REACTIVATION of a
        # lapsed membership never counts (the seat was already held).
        if entitlements.get_live_subscription(db, invitation.organization_id) is not None:
            active_members = int(
                db.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(
                        Membership.organization_id == invitation.organization_id,
                        Membership.status == "active",
                    )
                )
                or 0
            )
            entitlements.assert_within_limit(
                db, invitation.organization_id, entitlements.KEY_MAX_ORG_MEMBERS, active_members
            )
        membership = Membership(
            organization_id=invitation.organization_id,
            user_id=principal.id,
            role_code=invitation.role_code,
            status="active",
        )
        db.add(membership)
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(UTC)
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=invitation.organization_id,
        action="invitation.accept",
        entity_type="membership",
        entity_id=str(membership.id),
        meta={"role_code": membership.role_code},
    )
    activity.record_event(
        db,
        organization_id=invitation.organization_id,
        event_type=activity.EVENT_MEMBER_JOINED,
        summary=f"{principal.user.display_name} joined as {membership.role_code}",
        actor_user_id=principal.id,
        entity_kind="membership",
        entity_id=str(membership.id),
    )
    db.commit()
    db.refresh(membership)
    return membership


# ------------------------------------------------------- members (org level)
def list_org_members(
    db: Session, principal: Principal, *, organization_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Org-wide member directory (any active member may view)."""
    principal.require_member_of(organization_id)
    rows = db.execute(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.organization_id == organization_id, Membership.status == "active")
        .order_by(Membership.created_at)
    ).all()
    return [
        {
            "id": str(m.id),
            "user_id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role_code": m.role_code,
            "joined_at": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


def update_org_member_role(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    new_role: str,
) -> dict[str, Any]:
    membership_gate = _require_org_admin(db, principal, organization_id)
    if membership_gate.role_code != "owner" and new_role in ("owner", "org_admin"):
        raise Forbidden("Only an owner can grant owner or org_admin roles.")
    if new_role not in ROLE_ORDER:
        raise ValidationFailed(
            f"Unknown role '{new_role}'.",
            details=[{"field": "role_code", "reason": new_role}],
        )
    membership = db.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.organization_id == organization_id
        )
    )
    if membership is None or membership.status != "active":
        raise NotFound("Membership not found.")
    if membership.role_code == "owner" and new_role != "owner":
        others = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.organization_id == organization_id,
                Membership.role_code == "owner",
                Membership.status == "active",
                Membership.id != membership.id,
            )
        ) or 0
        if int(others) < 1:
            raise Conflict(
                "Cannot demote the last owner of this organization — "
                "promote another member to owner first."
            )
    previous = membership.role_code
    membership.role_code = new_role
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=organization_id,
        action="membership.role_change",
        entity_type="membership",
        entity_id=str(membership.id),
        meta={"user_id": str(membership.user_id), "from": previous, "to": new_role},
    )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_MEMBER_ROLE_CHANGED,
        summary=f"Role changed from {previous} to {new_role}",
        actor_user_id=principal.id,
        entity_kind="membership",
        entity_id=str(membership.id),
        details={"from_role": previous, "to_role": new_role},
    )
    db.commit()
    user = db.get(User, membership.user_id)
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": user.email if user else None,
        "display_name": user.display_name if user else None,
        "role_code": membership.role_code,
        "joined_at": membership.created_at.isoformat(),
    }


def remove_org_member(
    db: Session, principal: Principal, *, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> None:
    membership_gate = _require_org_admin(db, principal, organization_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.organization_id == organization_id
        )
    )
    if membership is None or membership.status != "active":
        raise NotFound("Membership not found.")
    if membership.user_id == principal.id:
        raise Conflict("Use account deletion to leave the organization you own.")
    if membership.role_code == "owner" and membership_gate.role_code != "owner":
        raise Forbidden("Only an owner can remove another owner.")
    if membership.role_code == "owner":
        others = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.organization_id == organization_id,
                Membership.role_code == "owner",
                Membership.status == "active",
                Membership.id != membership.id,
            )
        ) or 0
        if int(others) < 1:
            raise Conflict("Cannot remove the last owner of this organization.")
    removed_user_id = str(membership.user_id)
    db.delete(membership)
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=organization_id,
        action="membership.remove",
        entity_type="membership",
        entity_id=str(membership_id),
        meta={"user_id": removed_user_id},
    )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_MEMBER_REMOVED,
        summary="Removed a member from the organization",
        actor_user_id=principal.id,
        entity_kind="membership",
        entity_id=str(membership_id),
    )
    db.commit()


# ------------------------------------------------------ ownership transfer
def transfer_ownership(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    target_membership_id: uuid.UUID,
) -> dict[str, Any]:
    """Transfer organization ownership to an existing active member.

    Owner-only. The previous owner becomes org_admin (never dropped, so the
    operation is always recoverable). Audited + activity-logged.
    """
    _require_owner(principal, organization_id)
    target = db.scalar(
        select(Membership).where(
            Membership.id == target_membership_id,
            Membership.organization_id == organization_id,
            Membership.status == "active",
        )
    )
    if target is None:
        raise NotFound("Target membership not found in this organization.")
    if target.user_id == principal.id:
        raise ValidationFailed("You already own this organization.")
    current = principal.membership_in(organization_id)
    assert current is not None  # guaranteed by the owner gate
    previous_owner_role = current.role_code
    current.role_code = "org_admin"
    target.role_code = "owner"
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=organization_id,
        action="ownership.transfer",
        entity_type="organization",
        entity_id=str(organization_id),
        meta={"to_membership": str(target.id), "to_user": str(target.user_id)},
    )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_OWNERSHIP_TRANSFERRED,
        summary="Organization ownership was transferred",
        actor_user_id=principal.id,
        entity_kind="organization",
        entity_id=str(organization_id),
        details={"to_membership_id": str(target.id)},
    )
    db.commit()
    target_user = db.get(User, target.user_id)
    return {
        "organization_id": str(organization_id),
        "new_owner_membership_id": str(target.id),
        "new_owner_user_id": str(target.user_id),
        "new_owner_email": target_user.email if target_user else None,
        "previous_owner_role": previous_owner_role,
    }


# ------------------------------------------------------------- org settings
def update_organization(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    name: str | None = None,
    organization_type: str | None = None,
    country_code: str | None = None,
) -> Organization:
    membership = _require_org_admin(db, principal, organization_id)
    org = db.get(Organization, organization_id)
    if org is None:  # pragma: no cover — membership FK guarantees org
        raise NotFound("Organization not found.")
    changed: dict[str, Any] = {}
    if name is not None:
        name = name.strip()
        if not (1 <= len(name) <= 200):
            raise ValidationFailed("Organization name must be 1-200 characters.")
        if name != org.name:
            org.name = name
            changed["name"] = name
    if organization_type is not None:
        if organization_type not in ("individual", "business", "farm_org"):
            raise ValidationFailed("Unknown organization type.")
        org.organization_type = organization_type
        changed["organization_type"] = organization_type
    if country_code is not None:
        cc = country_code.strip().upper()
        if len(cc) != 2 or not cc.isalpha():
            raise ValidationFailed("country_code must be a 2-letter ISO code.")
        org.country_code = cc
        changed["country_code"] = cc
    if changed:
        record_auth_audit(
            db,
            actor_id=principal.id,
            organization_id=organization_id,
            action="organization.update",
            entity_type="organization",
            entity_id=str(organization_id),
            meta=changed,
        )
        activity.record_event(
            db,
            organization_id=organization_id,
            event_type=activity.EVENT_SETTING_CHANGED,
            summary=f"Organization settings updated: {', '.join(sorted(changed))}",
            actor_user_id=principal.id,
            entity_kind="organization",
            entity_id=str(organization_id),
            details=changed,
        )
        db.commit()
        db.refresh(org)
    return org


def list_org_farms(
    db: Session, principal: Principal, *, organization_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> tuple[list[Farm], int]:
    """Farm directory for the org (any active member may view)."""
    principal.require_member_of(organization_id)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = db.scalar(
        select(func.count()).select_from(Farm).where(Farm.organization_id == organization_id)
    ) or 0
    farms = list(
        db.scalars(
            select(Farm)
            .where(Farm.organization_id == organization_id)
            .order_by(Farm.created_at)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return farms, int(total)


def create_organization_for_user(
    db: Session, principal: Principal, *, name: str, organization_type: str, country_code: str | None
) -> Organization:
    """Create a new organization and make the caller its owner (onboarding)."""
    if organization_type not in ("individual", "business", "farm_org"):
        raise ValidationFailed("Unknown organization type.")
    org = Organization(
        name=name.strip()[:200],
        organization_type=organization_type,
        country_code=(country_code.strip().upper() if country_code else None),
    )
    db.add(org)
    db.flush()
    db.add(
        Membership(
            organization_id=org.id, user_id=principal.id, role_code="owner", status="active"
        )
    )
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=org.id,
        action="organization.create",
        entity_type="organization",
        entity_id=str(org.id),
        meta={"name": org.name, "organization_type": org.organization_type},
    )
    activity.record_event(
        db,
        organization_id=org.id,
        event_type=activity.EVENT_SETTING_CHANGED,
        summary=f"Organization '{org.name}' created",
        actor_user_id=principal.id,
        entity_kind="organization",
        entity_id=str(org.id),
    )
    db.commit()
    db.refresh(org)
    return org

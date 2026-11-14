"""Identity domain: registration, login, token auth, tenant authorization.

Tenant rule (Master rule 17 / §17.1): every farm/field/data resource access is
authorized against the requesting user's organization membership.

Auth hardening (P0-2): account lockout after repeated failed logins, email
verification gate, refresh-token rotation with family reuse detection,
single-use credential challenge tokens (password reset / email verification)
and role-based membership management (viewer < agronomist < manager < owner).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import (
    AccountLocked,
    Conflict,
    EmailNotVerified,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationFailed,
)
from app.core.security import (
    generate_refresh_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.domains.identity.delivery import (
    EmailDeliveryAdapter,
    require_email_delivery_adapter,
    send_or_rollback,
)
from app.db.models import (
    AuthToken,
    AuditEvent,
    CredentialToken,
    Farm,
    Membership,
    Organization,
    User,
)

bearer_scheme = HTTPBearer(auto_error=False)

# HttpOnly cookie carrying the access token for browser sessions (see
# get_principal). The refresh token lives in a sibling cookie handled by the
# Next.js /api/auth/* route handlers and is never read by this backend.
SESSION_COOKIE_NAME = "fs_token"

# RBAC hierarchy (Master §17): the numeric order defines "at least as
# privileged as" comparisons for role gates.
#
# P3 widened the role set (migration 0020): org_admin administrates the
# organization at owner level but cannot transfer ownership; operator works
# at manager level for field operations; analyst reads at agronomist level.
# Existing codes keep their historical ranks.
ROLE_ORDER: dict[str, int] = {
    "viewer": 0,
    "analyst": 1,
    "agronomist": 1,
    "operator": 2,
    "manager": 2,
    "org_admin": 3,
    "owner": 3,
}

# Role codes offered by the invitation / member-management UI (stable order).
ASSIGNABLE_ROLES: list[str] = [
    "owner",
    "org_admin",
    "manager",
    "operator",
    "agronomist",
    "analyst",
    "viewer",
]


def role_at_least(role_code: str, minimum: str) -> bool:
    """True when `role_code` grants at least the privileges of `minimum`."""
    if role_code not in ROLE_ORDER or minimum not in ROLE_ORDER:
        return False
    return ROLE_ORDER[role_code] >= ROLE_ORDER[minimum]


class Principal:
    """Authenticated user + their memberships, resolved once per request."""

    def __init__(self, user: User, memberships: list[Membership]) -> None:
        self.user = user
        self.memberships = memberships
        self._org_ids = {m.organization_id for m in memberships if m.status == "active"}

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    def is_member_of(self, organization_id: uuid.UUID) -> bool:
        return organization_id in self._org_ids

    def require_member_of(self, organization_id: uuid.UUID) -> None:
        if not self.is_member_of(organization_id):
            raise Forbidden("You do not have access to this organization's resources.")

    def org_ids(self) -> set[uuid.UUID]:
        return set(self._org_ids)

    def membership_in(self, organization_id: uuid.UUID) -> Membership | None:
        """The principal's ACTIVE membership in the organization, or None."""
        for membership in self.memberships:
            if membership.organization_id == organization_id and membership.status == "active":
                return membership
        return None

    def require_org_role(self, organization_id: uuid.UUID, minimum: str) -> Membership:
        """Return the active membership after verifying the minimum role."""
        membership = self.membership_in(organization_id)
        if membership is None:
            raise Forbidden("You do not have access to this organization's resources.")
        if not role_at_least(membership.role_code, minimum):
            raise Forbidden(
                f"This action requires the '{minimum}' role or higher on this organization."
            )
        return membership

    def require_owner(self, organization_id: uuid.UUID) -> Membership:
        """Ownership actions (transfer, owner invitations, owner removal)
        require the EXACT 'owner' role — org_admin shares owner's rank for
        administrative gates but must never pass an ownership gate."""
        membership = self.membership_in(organization_id)
        if membership is None:
            raise Forbidden("You do not have access to this organization's resources.")
        if membership.role_code != "owner":
            raise Forbidden("This action requires the organization owner role.")
        return membership

    def require_any_org_role(self, minimum: str) -> Membership:
        """Role gate for GLOBAL-context mutations (no single organization
        scope, e.g. platform-level knowledge packs): require at least one
        active membership with the minimum role in ANY of the principal's
        organizations. Tenant-scoped endpoints should use require_org_role
        or require_farm_role instead."""
        for membership in self.memberships:
            if membership.status == "active" and role_at_least(membership.role_code, minimum):
                return membership
        raise Forbidden(
            f"This action requires the '{minimum}' role or higher on at least one organization."
        )


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve the caller's principal from an access token.

    Accepted credential transports (P1 server-side sessions):
      1. ``Authorization: Bearer <token>`` header (API clients);
      2. ``fs_token`` HttpOnly cookie (browser session set by the Next.js
         auth route handlers — the token itself never touches JS-readable
         storage).
    """
    token_value: str | None = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token_value = credentials.credentials
    if not token_value:
        token_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not token_value:
        raise Unauthorized("Missing bearer token.")
    token_hash = hash_token(token_value)
    row = db.execute(
        select(AuthToken, User)
        .join(User, AuthToken.user_id == User.id)
        .where(AuthToken.token_hash == token_hash, AuthToken.kind == "access")
    ).first()
    if row is None:
        raise Unauthorized("Invalid or expired token.")
    token, user = row
    now = datetime.now(UTC)
    if token.revoked_at is not None or token.expires_at < now:
        raise Unauthorized("Token expired or revoked.")
    if not user.is_active:
        raise Unauthorized("Account disabled.")
    if not user.email_verified:
        raise EmailNotVerified("Verify your email before signing in.")
    memberships = list(
        db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    )
    return Principal(user=user, memberships=memberships)


# ---------------------------------------------------------------- audit
def record_auth_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    organization_id: uuid.UUID | None = None,
    action: str,
    entity_type: str = "auth",
    entity_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append an audit event for an auth/membership action. Caller commits."""
    db.add(
        AuditEvent(
            actor_id=actor_id,
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            after_snapshot=meta,
        )
    )


# ------------------------------------------------------- credential tokens
def _issue_credential_token(db: Session, user_id: uuid.UUID, kind: str) -> tuple[str, datetime]:
    """Create a single-use CredentialToken row; returns (plain_token, expires_at).

    Only the SHA-256 hash is stored; the plaintext is delivered out-of-band
    by the caller (email in production, dev convenience field in sandboxes).
    """
    ttl = (
        settings.password_reset_ttl_seconds
        if kind == "password_reset"
        else settings.email_verification_ttl_seconds
    )
    plain, token_hash, expires_at = generate_token(ttl_seconds=ttl)
    db.add(
        CredentialToken(user_id=user_id, kind=kind, token_hash=token_hash, expires_at=expires_at)
    )
    return plain, expires_at


def _challenge_delivery_text(kind: str, plain_token: str, expires_at: datetime) -> tuple[str, str]:
    """Compose a text-only challenge email without putting tokens in logs."""
    if kind == "email_verification":
        subject = "Verify your FieldShift email address"
        purpose = "email verification"
    else:
        subject = "Reset your FieldShift password"
        purpose = "password reset"
    return subject, (
        f"Your FieldShift {purpose} token is:\n\n{plain_token}\n\n"
        f"This token expires at {expires_at.isoformat()} and can be used once. "
        "If you did not request this, you can ignore this message.\n"
    )


def _issue_token_pair(db: Session, user_id: uuid.UUID, family_id: uuid.UUID | None) -> tuple[str, datetime, str, datetime]:
    """Issue an access+refresh AuthToken pair; returns (access, access_exp, refresh, refresh_exp)."""
    access, access_hash, access_expires_at = generate_token()
    db.add(
        AuthToken(
            user_id=user_id,
            token_hash=access_hash,
            expires_at=access_expires_at,
            kind="access",
            family_id=family_id,
        )
    )
    refresh, refresh_hash, refresh_expires_at = generate_refresh_token()
    db.add(
        AuthToken(
            user_id=user_id,
            token_hash=refresh_hash,
            expires_at=refresh_expires_at,
            kind="refresh",
            family_id=family_id,
        )
    )
    return access, access_expires_at, refresh, refresh_expires_at


def _revoke_family(db: Session, family_id: uuid.UUID | None, now: datetime) -> None:
    """Revoke every not-yet-revoked token in a refresh rotation family."""
    if family_id is None:
        return
    rows = db.scalars(
        select(AuthToken).where(
            AuthToken.family_id == family_id, AuthToken.revoked_at.is_(None)
        )
    ).all()
    for token in rows:
        token.revoked_at = now


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    delivery_adapter: EmailDeliveryAdapter | None = None,
) -> tuple[User, Organization, str | None, datetime | None, str | None, datetime | None]:
    """Create a user + personal organization and issue a session only in dev.

    Unverified non-development registrations receive no usable access or
    refresh token. They must verify before logging in; configured email delivery
    is required to complete that flow outside development.
    """
    # Fail before adding an account or challenge when production cannot send
    # the verification message. Development keeps its established test flow.
    adapter = None if settings.dev_mode else require_email_delivery_adapter(delivery_adapter)
    email_normalized = email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if existing is not None:
        raise Conflict("An account with this email already exists.")
    user = User(
        email=email_normalized,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email_normalized.split("@")[0],
        email_verified=settings.dev_mode,
    )
    db.add(user)
    org = Organization(name=f"{user.display_name}'s organization")
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role_code="owner", status="active"))
    db.flush()
    if not settings.dev_mode:
        plain, expires_at = _issue_credential_token(db, user.id, "email_verification")
        subject, text_body = _challenge_delivery_text("email_verification", plain, expires_at)
        send_or_rollback(db, adapter, user.email, subject, text_body)
        access = access_expires_at = refresh = refresh_expires_at = None
    else:
        family_id = uuid.uuid4()
        access, access_expires_at, refresh, refresh_expires_at = _issue_token_pair(
            db, user.id, family_id
        )
    record_auth_audit(
        db,
        actor_id=user.id,
        organization_id=org.id,
        action="auth.register",
        entity_id=str(user.id),
        meta={"email": user.email, "email_verified": user.email_verified},
    )
    db.commit()
    return user, org, access, access_expires_at, refresh, refresh_expires_at


def login_user(
    db: Session, *, email: str, password: str
) -> tuple[User, str, datetime, str, datetime]:
    """Authenticate a user; returns (user, access, access_exp, refresh, refresh_exp).

    Hardening: temporary lockout after `auth_max_failed_logins` consecutive
    failures, email-verification gate, audit trail on every outcome.
    """
    email_normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    now = datetime.now(UTC)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry_after = max(int((user.locked_until - now).total_seconds()), 1)
        record_auth_audit(
            db,
            actor_id=user.id,
            action="auth.login.locked",
            entity_id=email_normalized,
            meta={"retry_after_seconds": retry_after},
        )
        db.commit()
        raise AccountLocked(
            "Account temporarily locked due to failed sign-in attempts.",
            retry_after_seconds=retry_after,
        )
    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.auth_max_failed_logins:
                user.locked_until = now + timedelta(seconds=settings.auth_lockout_seconds)
                user.failed_login_count = 0
            record_auth_audit(
                db,
                actor_id=user.id,
                action="auth.login.failure",
                entity_id=email_normalized,
            )
        else:
            # Unknown email: audit with no actor (no account enumeration side
            # channel — identical client-visible response either way).
            record_auth_audit(
                db,
                actor_id=None,
                action="auth.login.failure",
                entity_id=email_normalized,
            )
        db.commit()
        raise Unauthorized("Invalid email or password.")
    # Correct credentials: reset the lockout counters.
    user.failed_login_count = 0
    user.locked_until = None
    if not user.is_active:
        db.commit()
        raise Unauthorized("Account disabled.")
    if not user.email_verified:
        record_auth_audit(
            db,
            actor_id=user.id,
            action="auth.login.unverified",
            entity_id=email_normalized,
        )
        db.commit()
        raise EmailNotVerified("Verify your email before signing in.")
    family_id = uuid.uuid4()
    access, access_expires_at, refresh, refresh_expires_at = _issue_token_pair(
        db, user.id, family_id
    )
    first_membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id, Membership.status == "active")
        .order_by(Membership.created_at)
    )
    record_auth_audit(
        db,
        actor_id=user.id,
        organization_id=first_membership.organization_id if first_membership else None,
        action="auth.login.success",
        entity_id=str(user.id),
    )
    db.commit()
    return user, access, access_expires_at, refresh, refresh_expires_at


def rotate_refresh_token(
    db: Session, refresh_plain: str
) -> tuple[User, str, datetime, str, datetime]:
    """Rotate a refresh token: returns (user, access, access_exp, refresh, refresh_exp).

    Reuse of an already-revoked refresh token is treated as a compromised
    session family: every token in the family is revoked and the request is
    rejected. Refresh tokens never authenticate API calls (kind=access filter
    in get_principal) — they only mint new token pairs here.
    """
    token_hash = hash_token(refresh_plain)
    token = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == token_hash, AuthToken.kind == "refresh"
        ).with_for_update()
    )
    if token is None:
        raise Unauthorized("Invalid refresh token.")
    user = db.get(User, token.user_id)
    if user is None:  # pragma: no cover — FK guarantees the user row
        raise Unauthorized("Invalid refresh token.")
    now = datetime.now(UTC)
    if not user.is_active:
        raise Unauthorized("Account disabled.")
    if not user.email_verified:
        raise EmailNotVerified("Verify your email before refreshing a session.")
    if token.revoked_at is not None:
        # REUSE DETECTED: a rotated (revoked) token came back. Revoke the
        # whole family — all tokens minted from this login/rotation chain.
        _revoke_family(db, token.family_id, now)
        record_auth_audit(
            db,
            actor_id=user.id,
            action="auth.token.reuse_detected",
            entity_id=str(token.family_id) if token.family_id else None,
        )
        db.commit()
        raise Unauthorized("Refresh token reuse detected — session family revoked.")
    if token.expires_at < now:
        token.revoked_at = now
        db.commit()
        raise Unauthorized("Refresh token expired.")
    family_id = token.family_id or uuid.uuid4()
    token.revoked_at = now
    access, access_expires_at, refresh, refresh_expires_at = _issue_token_pair(
        db, user.id, family_id
    )
    record_auth_audit(
        db,
        actor_id=user.id,
        action="auth.token.refresh",
        entity_id=str(family_id),
    )
    db.commit()
    return user, access, access_expires_at, refresh, refresh_expires_at


# ------------------------------------------------------- password reset
def request_password_reset(
    db: Session,
    email: str,
    *,
    delivery_adapter: EmailDeliveryAdapter | None = None,
) -> str | None:
    """Create a reset challenge and deliver it outside development.

    Unknown emails return None WITHOUT creating a token or audit row — no
    account enumeration side channel. Delivery readiness is checked before
    lookup so an absent adapter never creates an unusable challenge.
    """
    adapter = None if settings.dev_mode else require_email_delivery_adapter(delivery_adapter)
    email_normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if user is None:
        return None
    plain, expires_at = _issue_credential_token(db, user.id, "password_reset")
    record_auth_audit(
        db,
        actor_id=user.id,
        action="auth.password.reset_requested",
        entity_id=email_normalized,
    )
    if adapter is not None:
        subject, text_body = _challenge_delivery_text("password_reset", plain, expires_at)
        send_or_rollback(db, adapter, user.email, subject, text_body)
    db.commit()
    return plain


def confirm_password_reset(db: Session, token_plain: str, new_password: str) -> User:
    """Consume a password-reset challenge, set the new password and revoke
    every live session token of the user."""
    token_hash = hash_token(token_plain)
    row = db.scalar(
        select(CredentialToken).where(
            CredentialToken.token_hash == token_hash,
            CredentialToken.kind == "password_reset",
        )
    )
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at < now:
        raise ValidationFailed("Invalid or expired reset token.")
    row.used_at = now
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(new_password)
    live_tokens = db.scalars(
        select(AuthToken).where(
            AuthToken.user_id == user.id, AuthToken.revoked_at.is_(None)
        )
    ).all()
    for token in live_tokens:
        token.revoked_at = now
    record_auth_audit(
        db,
        actor_id=user.id,
        action="auth.password.reset_confirmed",
        entity_id=str(user.id),
    )
    db.commit()
    return user


# ---------------------------------------------------- email verification
def request_email_verification(
    db: Session,
    email: str,
    *,
    delivery_adapter: EmailDeliveryAdapter | None = None,
) -> str | None:
    """Create and deliver an email-verification challenge.

    Unknown emails and already-verified accounts return None (no new
    challenge, no enumeration side channel). Delivery readiness is checked
    before lookup so an absent adapter never stores an unusable challenge.
    """
    adapter = None if settings.dev_mode else require_email_delivery_adapter(delivery_adapter)
    email_normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if user is None or user.email_verified:
        return None
    plain, expires_at = _issue_credential_token(db, user.id, "email_verification")
    record_auth_audit(
        db,
        actor_id=user.id,
        action="auth.email.verification_requested",
        entity_id=email_normalized,
    )
    if adapter is not None:
        subject, text_body = _challenge_delivery_text("email_verification", plain, expires_at)
        send_or_rollback(db, adapter, user.email, subject, text_body)
    db.commit()
    return plain


def confirm_email_verification(db: Session, token_plain: str) -> User:
    """Consume an email-verification challenge and mark the account verified."""
    token_hash = hash_token(token_plain)
    row = db.scalar(
        select(CredentialToken).where(
            CredentialToken.token_hash == token_hash,
            CredentialToken.kind == "email_verification",
        )
    )
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at < now:
        raise ValidationFailed("Invalid or expired verification token.")
    row.used_at = now
    user = db.get(User, row.user_id)
    user.email_verified = True
    record_auth_audit(
        db,
        actor_id=user.id,
        action="auth.email.verified",
        entity_id=str(user.id),
    )
    db.commit()
    return user


def revoke_token(db: Session, principal: Principal, token_plain: str) -> None:
    token_hash = hash_token(token_plain)
    row = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == token_hash,
            AuthToken.user_id == principal.id,
            AuthToken.kind == "access",
        )
    )
    if row is None or row.revoked_at is not None:
        return
    now = datetime.now(UTC)
    if row.family_id is None:
        row.revoked_at = now
    else:
        _revoke_family(db, row.family_id, now)
    db.commit()


# ------------------------------------------------- membership management
def require_farm_role(db: Session, principal: Principal, farm: Farm, minimum: str) -> Membership:
    """Role gate scoped to a farm's organization (farm is already tenant-resolved)."""
    return principal.require_org_role(farm.organization_id, minimum)


def list_members(db: Session, principal: Principal, farm: Farm) -> list[dict[str, Any]]:
    """All memberships of the farm's organization (manager+), with status."""
    require_farm_role(db, principal, farm, "manager")
    rows = db.execute(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.organization_id == farm.organization_id)
        .order_by(Membership.created_at)
    ).all()
    return [
        {
            "id": str(m.id),
            "user_id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role_code": m.role_code,
            "status": m.status,
            "created_at": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


def _count_other_active_owners(
    db: Session, organization_id: uuid.UUID, excluded_membership_id: uuid.UUID
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role_code == "owner",
                Membership.status == "active",
                Membership.id != excluded_membership_id,
            )
        )
        or 0
    )


def _lock_organization_for_membership_change(db: Session, organization_id: uuid.UUID) -> None:
    """Take the common organization-first serialization lock for seat writes."""
    organization = db.scalar(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    )
    if organization is None:
        raise NotFound("Organization not found.")


def add_member(
    db: Session, principal: Principal, farm: Farm, *, email: str, role_code: str
) -> Membership:
    """Add an existing CropTwist account to the farm's organization (owner-only)."""
    principal.require_owner(farm.organization_id)
    _lock_organization_for_membership_change(db, farm.organization_id)
    email_normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if user is None:
        raise NotFound("No CropTwist account exists with this email.")
    existing = db.scalar(
        select(Membership).where(
            Membership.organization_id == farm.organization_id,
            Membership.user_id == user.id,
        )
    )
    if existing is not None:
        raise Conflict("This user is already a member of this organization.")
    if role_code not in ROLE_ORDER:
        raise ValidationFailed(
            f"Unknown role '{role_code}'.",
            details=[{"field": "role_code", "reason": role_code}],
        )
    from app.billing import entitlements

    active_members = int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == farm.organization_id,
                Membership.status == "active",
            )
        )
        or 0
    )
    entitlements.assert_within_limit(
        db,
        farm.organization_id,
        entitlements.KEY_MAX_ORG_MEMBERS,
        active_members,
    )
    membership = Membership(
        organization_id=farm.organization_id,
        user_id=user.id,
        role_code=role_code,
        status="active",
    )
    db.add(membership)
    db.flush()
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=farm.organization_id,
        action="membership.create",
        entity_type="membership",
        entity_id=str(membership.id),
        meta={"user_id": str(user.id), "email": user.email, "role_code": role_code},
    )
    db.commit()
    return membership


def update_member_role(
    db: Session, principal: Principal, farm: Farm, membership_id: uuid.UUID, new_role: str
) -> Membership:
    """Change a member's role (owner-only) with a last-owner guard."""
    principal.require_owner(farm.organization_id)
    if new_role not in ROLE_ORDER:
        raise ValidationFailed(
            f"Unknown role '{new_role}'.",
            details=[{"field": "role_code", "reason": new_role}],
        )
    membership = db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.organization_id == farm.organization_id,
        )
    )
    if membership is None:
        raise NotFound("Membership not found.")
    # LAST-OWNER GUARD: the organization must always keep at least one
    # active owner, otherwise no one could manage members again.
    if membership.role_code == "owner" and new_role != "owner":
        if _count_other_active_owners(db, farm.organization_id, membership.id) < 1:
            raise Conflict(
                "Cannot demote the last owner of this organization — promote another "
                "member to owner first."
            )
    membership.role_code = new_role
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=farm.organization_id,
        action="membership.update",
        entity_type="membership",
        entity_id=str(membership.id),
        meta={"user_id": str(membership.user_id), "new_role": new_role},
    )
    db.commit()
    return membership


def remove_member(db: Session, principal: Principal, farm: Farm, membership_id: uuid.UUID) -> None:
    """Remove a member from the farm's organization (owner-only, last-owner guard)."""
    principal.require_owner(farm.organization_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.organization_id == farm.organization_id,
        )
    )
    if membership is None:
        raise NotFound("Membership not found.")
    if membership.role_code == "owner":
        if _count_other_active_owners(db, farm.organization_id, membership.id) < 1:
            raise Conflict(
                "Cannot remove the last owner of this organization — promote another "
                "member to owner first."
            )
    audit_meta = {"user_id": str(membership.user_id), "role_code": membership.role_code}
    db.delete(membership)
    record_auth_audit(
        db,
        actor_id=principal.id,
        organization_id=farm.organization_id,
        action="membership.delete",
        entity_type="membership",
        entity_id=str(membership_id),
        meta=audit_meta,
    )
    db.commit()


# ------------------------------------------------- tenant authorization
def get_farm_for_principal(db: Session, principal: Principal, farm_id: uuid.UUID) -> Farm:
    farm = db.get(Farm, farm_id)
    if farm is None:
        raise NotFound("Farm not found.")
    principal.require_member_of(farm.organization_id)
    return farm


def get_field_for_principal(db: Session, principal: Principal, field_id: uuid.UUID) -> Any:
    from app.db.models import Field

    field = db.get(Field, field_id)
    if field is None:
        raise NotFound("Field not found.")
    farm = db.get(Farm, field.farm_id)
    if farm is None:  # pragma: no cover — FK guarantees farm
        raise NotFound("Field has no farm.")
    principal.require_member_of(farm.organization_id)
    return field

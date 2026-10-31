"""Identity domain: registration, login, token auth, tenant authorization.

Tenant rule (Master rule 17 / §17.1): every farm/field/data resource access is
authorized against the requesting user's organization membership.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.db.models import AuthToken, Farm, Membership, Organization, User

bearer_scheme = HTTPBearer(auto_error=False)


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


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized("Missing bearer token.")
    token_hash = hash_token(credentials.credentials)
    row = db.execute(
        select(AuthToken, User)
        .join(User, AuthToken.user_id == User.id)
        .where(AuthToken.token_hash == token_hash)
    ).first()
    if row is None:
        raise Unauthorized("Invalid or expired token.")
    token, user = row
    now = datetime.now(UTC)
    if token.revoked_at is not None or token.expires_at < now:
        raise Unauthorized("Token expired or revoked.")
    if not user.is_active:
        raise Unauthorized("Account disabled.")
    memberships = list(
        db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    )
    return Principal(user=user, memberships=memberships)


def register_user(
    db: Session, *, email: str, password: str, display_name: str
) -> tuple[User, Organization, str, datetime]:
    email_normalized = email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if existing is not None:
        raise Conflict("An account with this email already exists.")
    user = User(
        email=email_normalized,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email_normalized.split("@")[0],
    )
    db.add(user)
    org = Organization(name=f"{user.display_name}'s organization")
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role_code="owner", status="active"))
    db.flush()
    token, token_hash, expires_at = generate_token()
    db.add(AuthToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return user, org, token, expires_at


def login_user(db: Session, *, email: str, password: str) -> tuple[User, str, datetime]:
    email_normalized = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_normalized))
    if user is None or not verify_password(password, user.password_hash):
        raise Unauthorized("Invalid email or password.")
    if not user.is_active:
        raise Unauthorized("Account disabled.")
    token, token_hash, expires_at = generate_token()
    db.add(AuthToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return user, token, expires_at


def revoke_token(db: Session, principal: Principal, token_plain: str) -> None:
    token_hash = hash_token(token_plain)
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == token_hash))
    if row is not None:
        row.revoked_at = datetime.now(UTC)
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

"""Auth + identity endpoints (Master §41; auth hardening P0-2).

Login/register/logout/me keep their original response shapes (backward
compatible); login and register additionally return `refresh_token` and
`refresh_expires_at`. New endpoints: /auth/refresh (rotation with family
reuse detection), /auth/password-reset (+ /confirm), /auth/verify-email
(+ /confirm).

Auth endpoints are rate limited per client IP with a sliding window
(bucket "auth"); the limiter is disabled entirely when
`settings.auth_rate_limit_per_minute` <= 0.
"""

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import settings
from app.core.database import get_db
from app.domains.identity.service import (
    confirm_email_verification,
    confirm_password_reset,
    get_principal,
    login_user,
    register_user,
    request_email_verification,
    request_password_reset,
    revoke_token,
    rotate_refresh_token,
)
from app.db.models import Membership, Organization, User

router = APIRouter(tags=["auth"])

# Pragmatic email shape check. Full deliverability validation (email-validator)
# rejects reserved domains such as .local which we legitimately use for fixtures
# and demo accounts (see docs/implementation/DECISIONS_AND_ASSUMPTIONS.md).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(v: str) -> str:
    if not _EMAIL_RE.match(v):
        raise ValueError("not a valid email address")
    return v.lower()


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _check_email(v)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _check_email(v)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=200)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _check_email(v)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class EmailVerificationRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _check_email(v)


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)


def _client_ip(request: Request) -> str:
    return request.client.host if (request.client and request.client.host) else "unknown"


def _limit_auth(request: Request) -> None:
    """Sliding-window rate limit keyed by client IP (bucket "auth").

    Reads `settings.auth_rate_limit_per_minute` at call time; <= 0 disables
    the limiter entirely (tests, dedicated sandboxes).
    """
    if settings.auth_rate_limit_per_minute <= 0:
        return
    rate_limit.check("auth", _client_ip(request))


def _principal_payload(principal: Any) -> dict[str, Any]:
    user = principal.user
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "preferred_language": user.preferred_language,
        },
        "organizations": [
            {"id": str(m.organization_id), "role": m.role_code, "status": m.status}
            for m in principal.memberships
        ],
    }


def _session_payload(
    db: Session, user: User, token: str, expires_at: datetime,
    refresh_token: str, refresh_expires_at: datetime,
) -> dict[str, Any]:
    """Login/refresh response shape (superset of the register response)."""
    memberships = [
        {"id": str(m.organization_id), "role": m.role_code, "status": m.status}
        for m in db.query(Membership).filter(Membership.user_id == user.id).all()
    ]
    # Primary organization object for clients that read `organization.name`
    # (same shape as the register response; None only when the account has
    # no memberships at all).
    organization: dict[str, str] | None = None
    if memberships:
        org_row = db.get(Organization, uuid.UUID(memberships[0]["id"]))
        if org_row is not None:
            organization = {"id": str(org_row.id), "name": org_row.name}
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "refresh_token": refresh_token,
        "refresh_expires_at": refresh_expires_at.isoformat(),
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "organization": organization,
        "organizations": memberships,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    _limit_auth(request)
    user, org, token, expires_at, refresh_token, refresh_expires_at = register_user(
        db, email=payload.email, password=payload.password, display_name=payload.display_name
    )
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "refresh_token": refresh_token,
        "refresh_expires_at": refresh_expires_at.isoformat(),
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "organization": {"id": str(org.id), "name": org.name},
    }


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    _limit_auth(request)
    user, token, expires_at, refresh_token, refresh_expires_at = login_user(
        db, email=payload.email, password=payload.password
    )
    return _session_payload(db, user, token, expires_at, refresh_token, refresh_expires_at)


@router.post("/auth/refresh")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    _limit_auth(request)
    user, token, expires_at, refresh_token, refresh_expires_at = rotate_refresh_token(
        db, payload.refresh_token
    )
    return _session_payload(db, user, token, expires_at, refresh_token, refresh_expires_at)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    auth_header = request.headers.get("authorization", "")
    token_plain = auth_header.removeprefix("Bearer ").strip()
    revoke_token(db, principal, token_plain)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(principal: Any = Depends(get_principal)) -> dict:
    return _principal_payload(principal)


@router.post("/auth/password-reset", status_code=status.HTTP_202_ACCEPTED)
def password_reset(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Request a password reset. Always the same generic response shape — no
    account enumeration. In dev_mode the plaintext reset token is included as
    a sandbox/testing convenience (documented); production delivers it
    out-of-band via email."""
    _limit_auth(request)
    body: dict[str, str] = {
        "status": "queued",
        "message": "If the account exists, a password reset has been initiated.",
    }
    reset_token = request_password_reset(db, payload.email)
    if settings.dev_mode and reset_token is not None:
        body["reset_token"] = reset_token
    return body


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_200_OK)
def password_reset_confirm(
    payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)
) -> dict:
    confirm_password_reset(db, payload.token, payload.new_password)
    return {"status": "ok"}


@router.post("/auth/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
def verify_email_request(
    payload: EmailVerificationRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Request an email verification challenge (generic response shape; in
    dev_mode the plaintext token is included as a sandbox convenience)."""
    _limit_auth(request)
    body: dict[str, str] = {
        "status": "queued",
        "message": "If the account exists, an email verification has been initiated.",
    }
    verification_token = request_email_verification(db, payload.email)
    if settings.dev_mode and verification_token is not None:
        body["verification_token"] = verification_token
    return body


@router.post("/auth/verify-email/confirm", status_code=status.HTTP_200_OK)
def verify_email_confirm(
    payload: EmailVerificationConfirmRequest, db: Session = Depends(get_db)
) -> dict:
    confirm_email_verification(db, payload.token)
    return {"status": "ok"}

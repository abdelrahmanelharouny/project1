"""Auth + identity endpoints (Master §41)."""

from datetime import UTC, datetime
from typing import Any

import re

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Unauthorized
from app.domains.identity.service import (
    get_principal,
    login_user,
    register_user,
    revoke_token,
)
from app.db.models import Membership, Organization

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


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    user, org, token, expires_at = register_user(
        db, email=payload.email, password=payload.password, display_name=payload.display_name
    )
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "organization": {"id": str(org.id), "name": org.name},
    }


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user, token, expires_at = login_user(db, email=payload.email, password=payload.password)
    memberships = [
        {"id": str(m.organization_id), "role": m.role_code, "status": m.status}
        for m in db.query(Membership).filter(Membership.user_id == user.id).all()
    ]
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "organizations": memberships,
    }


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

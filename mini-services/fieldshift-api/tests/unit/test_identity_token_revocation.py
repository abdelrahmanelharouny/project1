from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from app.core.security import hash_token
from app.db.models import AuthToken
from app.domains.identity.service import revoke_token


def test_revoke_token_invalidates_the_authenticated_session_family() -> None:
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    access = AuthToken(
        user_id=user_id,
        token_hash=hash_token("access-token"),
        expires_at=expires_at,
        kind="access",
        family_id=family_id,
    )
    refresh = AuthToken(
        user_id=user_id,
        token_hash=hash_token("refresh-token"),
        expires_at=expires_at,
        kind="refresh",
        family_id=family_id,
    )
    db = Mock()
    db.scalar.return_value = access
    db.scalars.return_value.all.return_value = [access, refresh]

    revoke_token(db, SimpleNamespace(id=user_id), "access-token")

    assert access.revoked_at is not None
    assert refresh.revoked_at is not None
    db.commit.assert_called_once_with()

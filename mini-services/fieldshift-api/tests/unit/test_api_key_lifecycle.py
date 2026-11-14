"""Pure API-key lifecycle and local limiter regression tests.

The PostgreSQL race and shared-worker tests live in tests/integration and are
not run without the parent-provided isolated test DSN.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import Conflict, Forbidden
from app.publicapi import api_keys


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class Principal:
    id = USER_ID

    def org_ids(self):
        return {ORG_ID}

    def require_member_of(self, organization_id):
        assert organization_id == ORG_ID

    def require_org_role(self, organization_id, minimum):
        assert organization_id == ORG_ID
        assert minimum == "org_admin"


class Session:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_disabled_plan_blocks_rotation_before_state_or_secret_changes(monkeypatch):
    key = SimpleNamespace(
        id=uuid.uuid4(), organization_id=ORG_ID, status="active", revoked_at=None,
        name="synthetic", scopes=["org:read"], rate_limit_per_minute=5,
    )
    monkeypatch.setattr(api_keys, "_lock_organization", lambda *_: None)
    monkeypatch.setattr(api_keys, "_locked_api_key", lambda *_: key)

    def disabled(*_args, **_kwargs):
        raise Forbidden("API access disabled")

    monkeypatch.setattr(api_keys.entitlements, "require_flag", disabled)
    monkeypatch.setattr(
        api_keys, "generate_api_key",
        lambda: pytest.fail("rotation must not mint a secret when API access is disabled"),
    )
    with pytest.raises(Forbidden):
        api_keys.rotate_api_key(Session(), Principal(), key_id=key.id)
    assert key.status == "active"
    assert key.revoked_at is None


def test_revoked_key_cannot_be_rotated(monkeypatch):
    key = SimpleNamespace(
        id=uuid.uuid4(), organization_id=ORG_ID, status="revoked",
        revoked_at=datetime.now(UTC), name="synthetic", scopes=["org:read"],
        rate_limit_per_minute=5,
    )
    monkeypatch.setattr(api_keys, "_lock_organization", lambda *_: None)
    monkeypatch.setattr(api_keys, "_locked_api_key", lambda *_: key)
    monkeypatch.setattr(api_keys.entitlements, "require_flag", lambda *_args, **_kwargs: None)
    with pytest.raises(Conflict):
        api_keys.rotate_api_key(Session(), Principal(), key_id=key.id)
    assert key.status == "revoked"


def test_local_limiter_prunes_expired_buckets_and_bounds_bucket_count():
    limiter = api_keys.SlidingWindowLimiter(window_seconds=10, max_buckets=3)
    for index in range(30):
        limiter.check(f"synthetic-{index}", 5, now=float(index))
        assert limiter.bucket_count <= 3
    # All timestamps from the existing buckets have aged out.
    limiter.check("fresh", 5, now=100.0)
    assert limiter.bucket_count == 1


def test_unlimited_local_limiter_retains_no_timestamps():
    limiter = api_keys.SlidingWindowLimiter(max_buckets=2)
    for _ in range(50):
        limiter.check("unlimited", 0, now=1.0)
        limiter.check("negative", -1, now=1.0)
    assert limiter.bucket_count == 0


def test_local_limiter_caps_timestamps_even_if_plan_limit_is_huge(monkeypatch):
    monkeypatch.setattr(api_keys, "MAX_RATE_WINDOW_EVENTS", 2)
    limiter = api_keys.SlidingWindowLimiter(window_seconds=60)
    limiter.check("high-limit", 999_999, now=1.0)
    limiter.check("high-limit", 999_999, now=2.0)
    with pytest.raises(api_keys.TooManyRequests):
        limiter.check("high-limit", 999_999, now=3.0)
    assert limiter.bucket_count == 1


def test_revoke_evicts_fallback_limiter_state(monkeypatch):
    api_keys.key_rate_limiter.reset()
    key = SimpleNamespace(
        id=uuid.uuid4(), organization_id=ORG_ID, status="revoked",
        revoked_at=datetime.now(UTC), name="synthetic", prefix="ctk_test",
    )
    session = Session()
    monkeypatch.setattr(api_keys, "_lock_organization", lambda *_: None)
    monkeypatch.setattr(api_keys, "_locked_api_key", lambda *_: key)
    api_keys.key_rate_limiter.check(str(key.id), 3, now=1.0)
    assert api_keys.key_rate_limiter.bucket_count >= 1
    api_keys.revoke_api_key(session, Principal(), key_id=key.id)
    assert api_keys.key_rate_limiter.bucket_count == 0
    assert session.commits == 1
    api_keys.key_rate_limiter.reset()

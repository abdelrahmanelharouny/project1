"""P3 W6 public API keys — unit tests (pure logic + fake Session, no DB).

Coverage: key generation shape (ctk_ prefix / 12-char prefix / sha256 hash),
plaintext NEVER persisted, scope validation + enforcement, org resolution and
role gates, revoke/rotate lifecycle, daily usage upsert accounting, per-key
rate limiting (window expiry + Retry-After) and authenticate() order of
checks. DB-dependent paths (entitlement gate) are exercised with a fake
Session + monkeypatched entitlement lookups, following the pure-logic
conventions of tests/unit/test_recommendation_fingerprint.py.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from app.core import config
from app.core.errors import Conflict, Forbidden, NotFound, TooManyRequests, Unauthorized, ValidationFailed
from app.db.models_p3 import ApiKey, ApiKeyUsage, PlanEntitlement
from app.publicapi import api_keys

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
USER_ID = uuid.uuid4()

_ROLE_RANK = {"viewer": 0, "analyst": 1, "agronomist": 1, "manager": 2, "org_admin": 3, "owner": 3}


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _stmt_entity(stmt):
    try:
        return stmt.column_descriptions[0]["entity"]
    except Exception:  # pragma: no cover — non-select statements
        return None


def _clause_matches(obj, clause) -> bool:
    """Tiny WHERE evaluator: ANDed simple equality only (enough for the
    service's selects); unknown clause shapes match everything."""
    if clause is None:
        return True
    if isinstance(clause, BooleanClauseList):
        return all(_clause_matches(obj, child) for child in clause.clauses)
    if isinstance(clause, BinaryExpression):
        name = getattr(clause.left, "key", None)
        if name is None:
            return True
        expected = getattr(clause.right, "value", None)
        return getattr(obj, name, None) == expected
    return True


class _FakeNested:
    """SAVEPOINT stand-in: on exception, objects added inside are discarded."""

    def __init__(self, session):
        self._session = session
        self._mark = len(session.objects)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            del self._session.objects[self._mark:]
        return False  # propagate to the service's except


class FakeSession:
    """Minimal sync Session stand-in: object registry + tiny SELECT evaluator."""

    def __init__(self):
        self.objects: list = []
        self.commits = 0

    # -- writes
    def add(self, obj):
        # Emulate the column default (_uuid) applied at INSERT: objects get a
        # PK as soon as they are persisted, so identity-map lookups behave.
        if getattr(obj, "id", None) is None and hasattr(type(obj), "id"):
            obj.id = uuid.uuid4()
        self.objects.append(obj)

    def flush(self):
        self._check_unique()

    def _check_unique(self):
        seen_usage, seen_delivery = set(), set()
        for obj in self.objects:
            if isinstance(obj, ApiKeyUsage):
                k = (obj.api_key_id, obj.day)
                if k in seen_usage:
                    raise IntegrityError("uq_api_key_usage", {}, Exception("duplicate"))
                seen_usage.add(k)
            elif hasattr(obj, "endpoint_id") and hasattr(obj, "event_id"):
                k = (obj.endpoint_id, obj.event_id)
                if k in seen_delivery:
                    raise IntegrityError("uq_webhook_delivery_event", {}, Exception("duplicate"))
                seen_delivery.add(k)

    def begin_nested(self):
        return _FakeNested(self)

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)

    # -- reads
    def get(self, entity, pk):
        for obj in self.objects:
            if isinstance(obj, entity) and getattr(obj, "id", None) == pk:
                return obj
        return None

    def scalar(self, stmt):
        entity = _stmt_entity(stmt)
        if entity is None:  # e.g. select(func.count()) → treat as zero
            return 0
        rows = [o for o in self.objects if isinstance(o, entity) and _clause_matches(o, stmt.whereclause)]
        return rows[0] if rows else None

    def scalars(self, stmt):
        entity = _stmt_entity(stmt)
        rows = [o for o in self.objects if isinstance(o, entity) and _clause_matches(o, stmt.whereclause)]
        return FakeResult(rows)


class FakePrincipal:
    """Principal stand-in for one active membership (role configurable)."""

    def __init__(self, org_ids=(ORG_A,), role="owner", user_id=None):
        self._org_ids = set(org_ids)
        self._role = role
        self.id = user_id or USER_ID

    def org_ids(self):
        return set(self._org_ids)

    def require_member_of(self, organization_id):
        if organization_id not in self._org_ids:
            raise Forbidden("no access")

    def require_org_role(self, organization_id, minimum):
        self.require_member_of(organization_id)
        if _ROLE_RANK[self._role] < _ROLE_RANK[minimum]:
            raise Forbidden(f"requires {minimum}")
        return SimpleNamespace(organization_id=organization_id, role_code=self._role)


@pytest.fixture(autouse=True)
def no_subscription(monkeypatch):
    """Default fake plan: API enabled with a positive rate for service tests."""
    monkeypatch.setattr(api_keys, "get_live_subscription", lambda session, org_id: None)
    monkeypatch.setattr(api_keys.entitlements, "require_flag", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_keys.entitlements, "limit_for", lambda *args, **kwargs: 100)
    monkeypatch.setattr(
        api_keys,
        "resolve_entitlements",
        lambda session, org_id: {
            api_keys.KEY_API_RATE_LIMIT_PER_MINUTE: {"value": 100, "kind": "int"}
        },
    )


def make_key(session: FakeSession, *, scopes=("farms:read", "org:read"), status="active",
             rate=10, org=ORG_A, expires_at=None) -> tuple[ApiKey, str]:
    raw = f"{config.settings.api_key_prefix}{secrets.token_urlsafe(32)}"
    key = ApiKey(
        organization_id=org,
        name="unit key",
        prefix=raw[:12],
        key_hash=api_keys.hash_api_key(raw),
        scopes=list(scopes),
        status=status,
        rate_limit_per_minute=rate,
        expires_at=expires_at,
    )
    session.add(key)
    return key, raw


# ---------------------------------------------------------------------------
# key material
# ---------------------------------------------------------------------------
def test_generate_api_key_shape_and_hash():
    plaintext, prefix, key_hash = api_keys.generate_api_key()
    assert plaintext.startswith(config.settings.api_key_prefix)
    assert prefix == plaintext[:12] and len(prefix) == 12
    assert key_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert len(key_hash) == 64
    # 256 bits of randomness: two keys never collide
    assert plaintext != api_keys.generate_api_key()[0]


def test_hash_api_key_is_sha256():
    assert api_keys.hash_api_key("abc") == hashlib.sha256(b"abc").hexdigest()


def test_validate_scopes_normalizes_and_rejects():
    assert api_keys.validate_scopes(["farms:read", "org:read", "farms:read"]) == [
        "farms:read", "org:read",
    ]
    with pytest.raises(ValidationFailed):
        api_keys.validate_scopes([])
    with pytest.raises(ValidationFailed):
        api_keys.validate_scopes(["org:read", "admin:everything"])
    with pytest.raises(ValidationFailed):
        api_keys.validate_scopes(None)


def test_api_key_payload_never_leaks_hash():
    session = FakeSession()
    key, plaintext = make_key(session)
    payload = api_keys.api_key_payload(key)
    assert "key_hash" not in payload
    assert plaintext not in json.dumps(payload)
    assert payload["prefix"] == plaintext[:12]


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def test_create_api_key_stores_only_hash_and_audits(monkeypatch):
    session = FakeSession()
    principal = FakePrincipal(role="org_admin")
    key, plaintext = api_keys.create_api_key(
        session, principal, name=" Integration key ", scopes=["org:read", "farms:read"]
    )
    stored = [o for o in session.objects if isinstance(o, ApiKey)][-1]
    assert stored is key
    assert stored.key_hash == api_keys.hash_api_key(plaintext)
    assert plaintext not in json.dumps([str(o.__dict__.get("key_hash", "")) for o in session.objects])
    assert stored.key_hash != plaintext
    assert stored.prefix == plaintext[:12]
    assert stored.name == "Integration key"  # trimmed
    assert stored.scopes == ["farms:read", "org:read"]  # sorted, deduped
    assert stored.status == "active"
    assert stored.rate_limit_per_minute == 100
    assert stored.organization_id == ORG_A
    assert stored.created_by == USER_ID
    assert session.commits == 1
    # audit trail: one auth-audit + one activity event
    from app.db.models import AuditEvent
    from app.db.models_p3 import ActivityEvent

    assert any(isinstance(o, AuditEvent) for o in session.objects)
    assert any(
        isinstance(o, ActivityEvent) and o.event_type == "developer.api_key_created"
        for o in session.objects
    )


def test_create_api_key_validates_name():
    session = FakeSession()
    principal = FakePrincipal(role="org_admin")
    with pytest.raises(ValidationFailed):
        api_keys.create_api_key(session, principal, name="   ", scopes=["org:read"])
    with pytest.raises(ValidationFailed):
        api_keys.create_api_key(session, principal, name="x" * 121, scopes=["org:read"])


def test_create_api_key_requires_org_admin():
    session = FakeSession()
    with pytest.raises(Forbidden):
        api_keys.create_api_key(
            session, FakePrincipal(role="manager"), name="k", scopes=["org:read"]
        )
    # cross-org request is a Forbidden (membership gate), not a 404
    with pytest.raises(Forbidden):
        api_keys.create_api_key(
            session, FakePrincipal(role="owner"), name="k", scopes=["org:read"],
            organization_id=ORG_B,
        )


def test_resolve_org_id_requires_disambiguation_for_multi_org():
    single = FakePrincipal(org_ids=(ORG_A,))
    assert api_keys.resolve_org_id(single) == ORG_A
    assert api_keys.resolve_org_id(single, ORG_A) == ORG_A
    multi = FakePrincipal(org_ids=(ORG_A, ORG_B))
    with pytest.raises(ValidationFailed):
        api_keys.resolve_org_id(multi)
    assert api_keys.resolve_org_id(multi, ORG_B) == ORG_B
    with pytest.raises(Forbidden):
        api_keys.resolve_org_id(multi, uuid.uuid4())


def test_api_key_gate_bites_only_when_plan_defines_limit(monkeypatch):
    """The optional active-key count cap applies only when a plan defines it.

    Key issuance/authentication are separately gated by api_enabled and the
    current rate entitlement.
    """
    session = FakeSession()
    recorded = []

    monkeypatch.setattr(
        api_keys, "assert_within_limit",
        lambda db, org, key, count: recorded.append((key, count)),
    )

    # no subscription (fixture default) → pass-through
    api_keys._assert_api_keys_within_limit(session, ORG_A, 99)
    assert recorded == []

    # subscription, but the plan has no max_api_keys row → pass-through
    sub = SimpleNamespace(plan_id=uuid.uuid4())
    monkeypatch.setattr(api_keys, "get_live_subscription", lambda db, org: sub)
    api_keys._assert_api_keys_within_limit(session, ORG_A, 99)
    assert recorded == []

    # plan defines max_api_keys=2 → enforced through assert_within_limit
    session.add(PlanEntitlement(plan_id=sub.plan_id, key=api_keys.KEY_MAX_API_KEYS, value_int=2))
    api_keys._assert_api_keys_within_limit(session, ORG_A, 2)
    assert recorded == [(api_keys.KEY_MAX_API_KEYS, 2)]


def test_create_api_key_denied_when_plan_disables_public_api(monkeypatch):
    session = FakeSession()

    def deny(*_args, **_kwargs):
        raise Forbidden("API access is not included in this plan.")

    monkeypatch.setattr(api_keys.entitlements, "require_flag", deny)
    with pytest.raises(Forbidden):
        api_keys.create_api_key(
            session,
            FakePrincipal(),
            name="disabled plan key",
            scopes=["farms:read"],
        )
    assert not any(isinstance(obj, ApiKey) for obj in session.objects)


def test_resolve_rate_limit_from_plan_entitlement(monkeypatch):
    session = FakeSession()
    # A positive resolved Free/paid plan rate is used; no hidden fallback.
    assert api_keys._resolve_rate_limit(session, ORG_A) == 100

    sub = SimpleNamespace(plan_id=uuid.uuid4())
    monkeypatch.setattr(api_keys, "get_live_subscription", lambda db, org: sub)
    monkeypatch.setattr(
        api_keys, "resolve_entitlements",
        lambda db, org: {
            "api_rate_limit_per_minute": {"value": 300, "kind": "int", "unlimited": False},
        },
    )
    assert api_keys._resolve_rate_limit(session, ORG_A) == 300

    # zero is a denial, never converted into a usable default-rate key
    monkeypatch.setattr(
        api_keys, "resolve_entitlements",
        lambda db, org: {"api_rate_limit_per_minute": {"value": 0, "kind": "int"}},
    )
    with pytest.raises(Forbidden):
        api_keys._resolve_rate_limit(session, ORG_A)


# ---------------------------------------------------------------------------
# revoke / rotate / tenant guard
# ---------------------------------------------------------------------------
def test_revoke_api_key_marks_revoked_and_is_idempotent():
    session = FakeSession()
    principal = FakePrincipal(role="org_admin")
    key, _ = make_key(session)
    revoked = api_keys.revoke_api_key(session, principal, key_id=key.id)
    assert revoked.status == "revoked" and revoked.revoked_at is not None
    again = api_keys.revoke_api_key(session, principal, key_id=key.id)
    assert again.status == "revoked" and again.revoked_at == revoked.revoked_at


def test_revoke_api_key_tenant_and_role_guards():
    session = FakeSession()
    key, _ = make_key(session, org=ORG_B)
    with pytest.raises(NotFound):
        api_keys.revoke_api_key(session, FakePrincipal(role="owner"), key_id=key.id)
    with pytest.raises(Forbidden):
        api_keys.revoke_api_key(
            session, FakePrincipal(role="viewer"), key_id=key.id, organization_id=ORG_B
        )


def test_rotate_api_key_revokes_old_and_issues_new_secret():
    session = FakeSession()
    principal = FakePrincipal(role="org_admin")
    old, old_plaintext = make_key(session, scopes=("farms:read",), rate=42)
    new, new_plaintext = api_keys.rotate_api_key(session, principal, key_id=old.id)

    assert old.status == "revoked" and old.revoked_at is not None  # grace: none
    assert new.id != old.id
    assert new.key_hash == api_keys.hash_api_key(new_plaintext)
    assert new_plaintext != old_plaintext
    assert new.key_hash != old.key_hash
    assert new.scopes == ["farms:read"]
    assert new.rate_limit_per_minute == 42
    assert new.organization_id == ORG_A
    with pytest.raises(Conflict):
        api_keys.rotate_api_key(session, principal, key_id=old.id)  # already revoked


# ---------------------------------------------------------------------------
# usage accounting
# ---------------------------------------------------------------------------
def test_record_usage_upserts_daily_counter():
    session = FakeSession()
    key_id = uuid.uuid4()
    day = date(2026, 5, 1)
    row = api_keys.record_usage(session, key_id, "/public/v1/farms", 200, day=day)
    assert row.request_count == 1
    row2 = api_keys.record_usage(session, key_id, "/public/v1/farms", 200, day=day)
    assert row2 is row and row2.request_count == 2
    # a different day starts a fresh counter
    other = api_keys.record_usage(session, key_id, "/x", 404, day=date(2026, 5, 2))
    assert other.request_count == 1 and other.day == date(2026, 5, 2)


def test_record_usage_survives_insert_race():
    """Concurrent first-insert: the pre-check misses the other connection's
    row, the INSERT hits uq_api_key_usage inside the SAVEPOINT, and the upsert
    falls back to incrementing the winner's row (background-safe)."""
    session = FakeSession()
    key_id = uuid.uuid4()
    day = date(2026, 5, 1)
    existing = ApiKeyUsage(api_key_id=key_id, day=day, request_count=7)
    session.add(existing)

    # Simulate losing the race: the pre-check select returns None once, then
    # behaves normally (so the post-error re-select finds the winner row).
    original_scalar = session.scalar
    calls = {"pre_check": 0}

    def racing_scalar(stmt):
        if _stmt_entity(stmt) is ApiKeyUsage and calls["pre_check"] == 0:
            calls["pre_check"] += 1
            return None
        return original_scalar(stmt)

    session.scalar = racing_scalar  # type: ignore[method-assign]
    row = api_keys.record_usage(session, key_id, "/p", 200, day=day)
    assert row is existing and row.request_count == 8
    # the losing insert was rolled back with the savepoint
    assert sum(isinstance(o, ApiKeyUsage) for o in session.objects) == 1


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------
def test_authenticate_rejects_missing_or_malformed_keys():
    session = FakeSession()
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, None)
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, "")
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, "not-a-fieldshift-key")


def test_authenticate_rejects_unknown_revoked_expired():
    session = FakeSession()
    now = datetime.now(UTC)
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, "ctk_unknown", now=now)

    _, revoked_raw = make_key(session, status="revoked")
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, revoked_raw, now=now)

    _, expired_raw = make_key(session, expires_at=now - timedelta(seconds=1))
    with pytest.raises(Unauthorized):
        api_keys.authenticate_api_key(session, expired_raw, now=now)


def test_authenticate_enforces_all_required_scopes():
    session = FakeSession()
    _, raw = make_key(session, scopes=("farms:read", "org:read"))
    principal = api_keys.authenticate_api_key(session, raw, ("farms:read", "org:read"))
    assert principal.organization_id == ORG_A
    assert principal.has_scopes(["farms:read", "org:read"])
    with pytest.raises(Forbidden) as excinfo:
        api_keys.authenticate_api_key(session, raw, ("org:read", "reports:read", "crops:read"))
    assert "reports:read" in str(excinfo.value) and "crops:read" in str(excinfo.value)


def test_authenticate_stamps_last_used_and_records_usage():
    session = FakeSession()
    key, raw = make_key(session)
    now = datetime.now(UTC)
    api_keys.authenticate_api_key(session, raw, limiter=api_keys.SlidingWindowLimiter(), now=now)
    api_keys.authenticate_api_key(session, raw, limiter=api_keys.SlidingWindowLimiter(), now=now)
    assert key.last_used_at == now
    usage = [o for o in session.objects if isinstance(o, ApiKeyUsage)]
    assert len(usage) == 1  # one per-day row...
    assert usage[0].request_count == 2  # ...incremented across both requests
    assert usage[0].day == now.date()
    assert session.commits >= 2  # usage is committed inline (survives later errors)


def test_authenticate_rate_limits_per_key():
    session = FakeSession()
    _, raw = make_key(session, rate=2)
    limiter = api_keys.SlidingWindowLimiter()
    api_keys.authenticate_api_key(session, raw, limiter=limiter, now=datetime.now(UTC))
    api_keys.authenticate_api_key(session, raw, limiter=limiter, now=datetime.now(UTC))
    with pytest.raises(TooManyRequests) as excinfo:
        api_keys.authenticate_api_key(session, raw, limiter=limiter, now=datetime.now(UTC))
    assert excinfo.value.retry_after_seconds >= 1


def test_rate_limiter_window_and_retry_after():
    limiter = api_keys.SlidingWindowLimiter()
    for i in range(5):
        limiter.check("k", 5, now=float(i))  # 0..4 ok
    with pytest.raises(TooManyRequests) as excinfo:
        limiter.check("k", 5, now=5.0)
    assert excinfo.value.retry_after_seconds >= 1
    limiter.check("k", 5, now=61.0)  # window slid past the early hits
    # independent buckets
    limiter.check("other", 5, now=61.0)


def test_rate_limiter_zero_or_negative_limit_disables():
    limiter = api_keys.SlidingWindowLimiter()
    for _ in range(50):
        limiter.check("k", 0)
    limiter.check("k", -1)


def test_scopes_catalog_matches_contract():
    assert set(api_keys.API_KEY_SCOPES) == {
        "org:read", "farms:read", "fields:read", "crops:read", "analytics:read",
        "recommendations:read", "reports:read", "environment:read",
    }

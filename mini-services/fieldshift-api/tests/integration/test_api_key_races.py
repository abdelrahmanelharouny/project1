"""PostgreSQL integration regressions for API-key state shared across workers.

Run only against the isolated test DSN after migrations 0027/0028 are wired;
these tests intentionally use independent sessions and never call real
providers, mail, or payment services.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.core.errors import Conflict, Forbidden, PaymentRequired, TooManyRequests
from app.db.models import AuditEvent, Membership, Organization, User
from app.db.models_p3 import (
    ApiKey,
    ApiKeyUsage,
    Plan,
    PlanEntitlement,
    Subscription,
)
from app.db.models_api_rate import ApiKeyRateWindow
from app.domains.identity.service import Principal
from app.publicapi import api_keys


def _new_org(db, *, with_owner: bool = False):
    suffix = uuid.uuid4().hex
    org = Organization(name=f"Synthetic API-key test {suffix}", organization_type="farm")
    db.add(org)
    user = membership = None
    if with_owner:
        user = User(
            email=f"api-key-{suffix}@test.invalid",
            password_hash="synthetic-not-a-real-password-hash",
            display_name="Synthetic API-key owner",
        )
        db.add(user)
    db.flush()
    if with_owner:
        membership = Membership(
            organization_id=org.id,
            user_id=user.id,
            role_code="owner",
            status="active",
        )
        db.add(membership)
    db.flush()
    return org, user, membership


def _new_key(db, org, *, rate: int = 100) -> ApiKey:
    raw = f"ctk_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    key = ApiKey(
        organization_id=org.id,
        name="Synthetic race key",
        prefix=raw[:12],
        key_hash=api_keys.hash_api_key(raw),
        scopes=["org:read"],
        status="active",
        rate_limit_per_minute=rate,
    )
    db.add(key)
    db.flush()
    return key


def _principal(db, user_id, org_id):
    user = db.get(User, user_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == org_id,
        )
    )
    assert user is not None and membership is not None
    return Principal(user, [membership])


def _api_plan(db, org, *, max_api_keys: int, rate_limit: int):
    """Attach a minimal live API-enabled plan and return mutable entitlements."""
    suffix = uuid.uuid4().hex[:10]
    plan = Plan(code=f"api-rotation-{suffix}", name="Synthetic API rotation plan")
    db.add(plan)
    db.flush()
    api_enabled = PlanEntitlement(
        plan_id=plan.id, key=api_keys.KEY_API_ENABLED, value_bool=True
    )
    rate = PlanEntitlement(
        plan_id=plan.id,
        key=api_keys.KEY_API_RATE_LIMIT_PER_MINUTE,
        value_int=rate_limit,
    )
    key_cap = PlanEntitlement(
        plan_id=plan.id, key=api_keys.KEY_MAX_API_KEYS, value_int=max_api_keys
    )
    db.add_all([api_enabled, rate, key_cap])
    now = datetime.now(UTC)
    db.add(
        Subscription(
            organization_id=org.id,
            plan_id=plan.id,
            status="active",
            billing_period="monthly",
            provider="sandbox",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=30),
        )
    )
    db.flush()
    return rate, key_cap


def test_parallel_usage_upserts_do_not_lose_existing_row_increments(db):
    org, _, _ = _new_org(db)
    key = _new_key(db, org)
    usage_day = date.today()
    row = ApiKeyUsage(api_key_id=key.id, day=usage_day, request_count=7)
    db.add(row)
    db.commit()
    key_id = key.id

    request_count = 18
    barrier = threading.Barrier(request_count)

    def increment():
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            api_keys.record_usage(session, key_id, "/synthetic", 200, day=usage_day)
            session.commit()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=request_count) as pool:
        list(pool.map(lambda _: increment(), range(request_count)))

    check = SessionLocal()
    try:
        actual = check.scalar(
            select(ApiKeyUsage.request_count).where(
                ApiKeyUsage.api_key_id == key_id,
                ApiKeyUsage.day == usage_day,
            )
        )
        assert actual == 7 + request_count
    finally:
        check.close()


def test_two_create_calls_at_one_key_cap_serialize_on_organization(db):
    org, user, _ = _new_org(db, with_owner=True)
    suffix = uuid.uuid4().hex[:10]
    plan = Plan(code=f"api-key-cap-{suffix}", name="Synthetic one-key cap")
    db.add(plan)
    db.flush()
    db.add_all(
        [
            PlanEntitlement(plan_id=plan.id, key=api_keys.KEY_API_ENABLED, value_bool=True),
            PlanEntitlement(
                plan_id=plan.id,
                key=api_keys.KEY_API_RATE_LIMIT_PER_MINUTE,
                value_int=100,
            ),
            PlanEntitlement(plan_id=plan.id, key=api_keys.KEY_MAX_API_KEYS, value_int=1),
        ]
    )
    now = datetime.now(UTC)
    db.add(
        Subscription(
            organization_id=org.id,
            plan_id=plan.id,
            status="active",
            billing_period="monthly",
            provider="sandbox",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=30),
        )
    )
    db.commit()
    user_id, org_id = user.id, org.id

    barrier = threading.Barrier(2)

    def create_one(index):
        session = SessionLocal()
        try:
            principal = _principal(session, user_id, org_id)
            barrier.wait(timeout=10)
            try:
                _, secret = api_keys.create_api_key(
                    session,
                    principal,
                    name=f"Synthetic concurrent create {index}",
                    scopes=["org:read"],
                    organization_id=org_id,
                )
                return ("created", secret)
            except PaymentRequired:
                session.rollback()
                return ("cap", None)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create_one, (1, 2)))
    assert [outcome[0] for outcome in outcomes].count("created") == 1
    assert [outcome[0] for outcome in outcomes].count("cap") == 1
    assert sum(bool(secret) for _, secret in outcomes) == 1

    check = SessionLocal()
    try:
        active = check.scalar(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.organization_id == org_id,
                ApiKey.status == "active",
            )
        )
        assert active == 1
    finally:
        check.close()


def test_parallel_rotations_issue_only_one_replacement(db):
    org, user, _ = _new_org(db, with_owner=True)
    _api_plan(db, org, max_api_keys=1, rate_limit=100)
    original = _new_key(db, org)
    db.commit()
    user_id, org_id, original_id = user.id, org.id, original.id
    barrier = threading.Barrier(2)

    def rotate_one():
        session = SessionLocal()
        try:
            principal = _principal(session, user_id, org_id)
            barrier.wait(timeout=10)
            try:
                replacement, secret = api_keys.rotate_api_key(
                    session, principal, key_id=original_id, organization_id=org_id
                )
                return ("rotated", replacement.id, secret)
            except Conflict:
                session.rollback()
                return ("conflict", None, None)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: rotate_one(), range(2)))
    assert [result[0] for result in outcomes].count("rotated") == 1
    assert [result[0] for result in outcomes].count("conflict") == 1
    assert sum(bool(result[2]) for result in outcomes) == 1

    check = SessionLocal()
    try:
        active = list(
            check.scalars(
                select(ApiKey).where(
                    ApiKey.organization_id == org_id,
                    ApiKey.status == "active",
                )
            ).all()
        )
        assert len(active) == 1
        rotate_audits = check.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.organization_id == org_id,
                AuditEvent.action == "api_key.rotate",
            )
        )
        assert rotate_audits == 1
    finally:
        check.close()


def test_rotation_rechecks_downgraded_key_cap_without_revoking_original(db):
    org, user, _ = _new_org(db, with_owner=True)
    _, key_cap = _api_plan(db, org, max_api_keys=2, rate_limit=100)
    original = _new_key(db, org)
    _new_key(db, org)
    db.commit()
    user_id, org_id, original_id = user.id, org.id, original.id

    # Plan downgrade leaves more active keys than the replacement-adjusted cap.
    key_cap.value_int = 1
    db.commit()
    principal = _principal(db, user_id, org_id)
    with pytest.raises(PaymentRequired):
        api_keys.rotate_api_key(db, principal, key_id=original_id, organization_id=org_id)
    db.rollback()

    check = SessionLocal()
    try:
        active = list(
            check.scalars(
                select(ApiKey).where(
                    ApiKey.organization_id == org_id,
                    ApiKey.status == "active",
                )
            ).all()
        )
        assert len(active) == 2
        assert any(key.id == original_id for key in active)
        assert check.scalar(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.organization_id == org_id,
                ApiKey.status == "revoked",
            )
        ) == 0
    finally:
        check.close()


def test_rotation_uses_fresh_rate_and_succeeds_at_key_cap(db):
    org, user, _ = _new_org(db, with_owner=True)
    rate, _ = _api_plan(db, org, max_api_keys=1, rate_limit=100)
    original = _new_key(db, org, rate=100)
    db.commit()
    user_id, org_id, original_id = user.id, org.id, original.id

    rate.value_int = 23
    db.commit()
    principal = _principal(db, user_id, org_id)
    replacement, _ = api_keys.rotate_api_key(
        db, principal, key_id=original_id, organization_id=org_id
    )

    assert original.status == "revoked"
    assert replacement.status == "active"
    assert replacement.rate_limit_per_minute == 23
    assert db.scalar(
        select(func.count()).select_from(ApiKey).where(
            ApiKey.organization_id == org_id,
            ApiKey.status == "active",
        )
    ) == 1


def test_rotation_denied_by_current_rate_authorization_keeps_original(db):
    org, user, _ = _new_org(db, with_owner=True)
    rate, _ = _api_plan(db, org, max_api_keys=1, rate_limit=100)
    original = _new_key(db, org)
    db.commit()
    user_id, org_id, original_id = user.id, org.id, original.id

    rate.value_int = 0
    db.commit()
    principal = _principal(db, user_id, org_id)
    with pytest.raises(Forbidden):
        api_keys.rotate_api_key(db, principal, key_id=original_id, organization_id=org_id)
    db.rollback()

    check = SessionLocal()
    try:
        persisted = check.get(ApiKey, original_id)
        assert persisted is not None
        assert persisted.status == "active" and persisted.revoked_at is None
        assert check.scalar(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.organization_id == org_id,
                ApiKey.status == "active",
            )
        ) == 1
    finally:
        check.close()


def test_rotation_racing_revoke_has_one_serialized_transition(db, monkeypatch):
    org, user, _ = _new_org(db, with_owner=True)
    _api_plan(db, org, max_api_keys=1, rate_limit=100)
    original = _new_key(db, org)
    db.commit()
    user_id, org_id, original_id = user.id, org.id, original.id
    barrier = threading.Barrier(2)

    def rotate():
        session = SessionLocal()
        try:
            principal = _principal(session, user_id, org_id)
            barrier.wait(timeout=10)
            try:
                api_keys.rotate_api_key(
                    session, principal, key_id=original_id, organization_id=org_id
                )
                return "rotated"
            except Conflict:
                session.rollback()
                return "conflict"
        finally:
            session.close()

    def revoke():
        session = SessionLocal()
        try:
            principal = _principal(session, user_id, org_id)
            barrier.wait(timeout=10)
            api_keys.revoke_api_key(
                session, principal, key_id=original_id, organization_id=org_id
            )
            return "revoked"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rotate_future = pool.submit(rotate)
        revoke_future = pool.submit(revoke)
        rotation_result = rotate_future.result(timeout=30)
        revoke_result = revoke_future.result(timeout=30)
    assert revoke_result == "revoked"

    check = SessionLocal()
    try:
        active_count = check.scalar(
            select(func.count()).select_from(ApiKey).where(
                ApiKey.organization_id == org_id,
                ApiKey.status == "active",
            )
        )
        revokes = check.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.organization_id == org_id,
                AuditEvent.action == "api_key.revoke",
            )
        )
        rotations = check.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.organization_id == org_id,
                AuditEvent.action == "api_key.rotate",
            )
        )
        if rotation_result == "rotated":
            # Rotation committed first; revoking its predecessor must not
            # silently revoke the replacement key.
            assert active_count == 1
            assert rotations == 1 and revokes == 0
        else:
            # Revoke committed first; the losing rotation must create nothing.
            assert active_count == 0
            assert rotations == 0 and revokes == 1
    finally:
        check.close()


def test_shared_rate_window_is_enforced_across_independent_sessions(db):
    org, _, _ = _new_org(db)
    key = _new_key(db, org, rate=3)
    db.commit()
    key_id = key.id
    workers = 8
    barrier = threading.Barrier(workers)

    def hit_shared_window():
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            try:
                api_keys._check_shared_rate_window(session, key_id, 3)
                session.commit()
                return "accepted"
            except TooManyRequests:
                session.rollback()
                return "limited"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda _: hit_shared_window(), range(workers)))
    assert outcomes.count("accepted") == 3
    assert outcomes.count("limited") == workers - 3

    check = SessionLocal()
    try:
        row = check.get(ApiKeyRateWindow, key_id)
        assert row is not None
        assert len(row.timestamps) == 3
    finally:
        check.close()


def test_purge_helper_deletes_bounded_expired_usage_and_idle_rate_rows(db):
    # The maintenance helper is intentionally bounded per table; isolate its
    # rowcount assertion from synthetic usage left by preceding API tests.
    db.execute(delete(ApiKeyUsage))
    db.execute(delete(ApiKeyRateWindow))
    db.commit()
    org, _, _ = _new_org(db)
    first = _new_key(db, org)
    second = _new_key(db, org)
    cutoff = date(2026, 1, 1)
    now = datetime.now(UTC)
    db.add_all(
        [
            ApiKeyUsage(api_key_id=first.id, day=cutoff - timedelta(days=2), request_count=4),
            ApiKeyUsage(api_key_id=second.id, day=cutoff - timedelta(days=1), request_count=5),
            ApiKeyUsage(api_key_id=first.id, day=cutoff + timedelta(days=1), request_count=6),
            ApiKeyRateWindow(
                api_key_id=first.id,
                timestamps=[1.0],
                updated_at=now - timedelta(days=1),
            ),
            ApiKeyRateWindow(
                api_key_id=second.id,
                timestamps=[now.timestamp()],
                updated_at=now,
            ),
        ]
    )
    db.commit()

    counts = api_keys.purge_api_key_usage(db, before=cutoff, batch_size=1)
    assert counts == {"usage_rows": 1, "rate_rows": 1}
    db.flush()
    assert db.scalar(select(func.count()).select_from(ApiKeyUsage).where(ApiKeyUsage.day < cutoff)) == 1
    assert db.scalar(select(func.count()).select_from(ApiKeyUsage).where(ApiKeyUsage.day >= cutoff)) == 1
    assert db.get(ApiKeyRateWindow, second.id) is not None

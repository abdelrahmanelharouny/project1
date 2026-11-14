"""Pure unit coverage for scenario quota reservation policy and SQL shape."""
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.billing import entitlements
from app.core.errors import PaymentRequired


def test_scenario_quota_bucket_is_calendar_month_even_for_yearly_billing():
    yearly = SimpleNamespace(billing_period="yearly")
    instant = datetime(2026, 11, 14, 22, 30, tzinfo=UTC)

    assert entitlements.scenario_quota_period_start(instant) == date(2026, 11, 1)
    assert entitlements._period_for_key(
        entitlements.KEY_SCENARIO_RUNS_PER_MONTH, yearly, instant
    ) == date(2026, 11, 1)
    # Unrelated counters retain their established yearly cadence.
    assert entitlements._period_for_key("reports_per_month", yearly, instant) == date(2026, 1, 1)


def test_scenario_quota_bucket_normalizes_naive_and_offset_instants():
    assert entitlements.scenario_quota_period_start(datetime(2026, 2, 28, 23)) == date(2026, 2, 1)
    # This instant is March 1 in UTC, so the accounting month is March.
    offset = datetime.fromisoformat("2026-02-28T23:30:00-02:00")
    assert entitlements.scenario_quota_period_start(offset) == date(2026, 3, 1)


def test_reservation_denies_at_cap_without_incrementing(monkeypatch):
    organization_id = uuid.uuid4()
    db = Mock()
    incremented = Mock(return_value=2)
    monkeypatch.setattr(entitlements, "lock_organization_for_quota", Mock())
    monkeypatch.setattr(entitlements, "limit_for", lambda *_args: 2)
    monkeypatch.setattr(entitlements, "_usage_for_period", lambda *_args: 2)
    monkeypatch.setattr(entitlements, "_atomic_increment_usage", incremented)

    with pytest.raises(PaymentRequired, match="scenario_runs_per_month.*2/2"):
        entitlements.reserve_scenario_run(db, organization_id)

    entitlements.lock_organization_for_quota.assert_called_once_with(db, organization_id)
    incremented.assert_not_called()


def test_reservation_uses_atomic_postgresql_upsert_and_month_bucket(monkeypatch):
    organization_id = uuid.uuid4()
    db = Mock()
    db.scalar.return_value = 1
    monkeypatch.setattr(entitlements, "get_live_subscription", Mock())

    result = entitlements.increment_usage(
        db, organization_id, entitlements.KEY_SCENARIO_RUNS_PER_MONTH
    )

    assert result == 1
    entitlements.get_live_subscription.assert_not_called()
    statement = db.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "ON CONFLICT" in compiled
    assert "DO UPDATE SET used_value" in compiled
    assert "usage_counters.used_value +" in compiled
    assert "RETURNING usage_counters.used_value" in compiled
    assert params["period_start"] == entitlements.scenario_quota_period_start()


def test_unlimited_scenario_plan_still_reserves_atomically(monkeypatch):
    organization_id = uuid.uuid4()
    db = Mock()
    incremented = Mock(return_value=501)
    monkeypatch.setattr(entitlements, "lock_organization_for_quota", Mock())
    monkeypatch.setattr(entitlements, "limit_for", lambda *_args: entitlements.UNLIMITED)
    monkeypatch.setattr(entitlements, "_usage_for_period", lambda *_args: 500)
    monkeypatch.setattr(entitlements, "_atomic_increment_usage", incremented)

    assert entitlements.reserve_scenario_run(db, organization_id) == 501
    incremented.assert_called_once()

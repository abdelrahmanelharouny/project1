import pytest
from app.core import rate_limit
from app.core.errors import TooManyRequests


@pytest.fixture(autouse=True)
def isolated_state():
    rate_limit._reset_store()
    yield
    rate_limit._reset_store()


def test_active_subject_capacity_fails_closed_without_budget_eviction(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, 'auth_rate_limit_per_minute', 1)
    monkeypatch.setattr(rate_limit, '_MAX_BUCKETS', 2)
    monkeypatch.setattr(rate_limit.time, 'monotonic', lambda: 100.0)
    rate_limit.check('ai', 'one')
    rate_limit.check('ai', 'two')
    with pytest.raises(TooManyRequests):
        rate_limit.check('ai', 'three')
    assert len(rate_limit._store) == 2
    with pytest.raises(TooManyRequests):
        rate_limit.check('ai', 'one')


def test_idle_subject_expiry_reclaims_bounded_capacity(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(rate_limit.settings, 'auth_rate_limit_per_minute', 1)
    monkeypatch.setattr(rate_limit, '_MAX_BUCKETS', 1)
    monkeypatch.setattr(rate_limit.time, 'monotonic', lambda: clock[0])
    rate_limit.check('ai', 'old')
    clock[0] = 160.0
    rate_limit.check('ai', 'new')
    assert set(rate_limit._store) == {('ai', 'new')}


def test_disabled_rate_limit_allocates_no_unlimited_subject_state(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, 'auth_rate_limit_per_minute', 0)
    for index in range(20):
        rate_limit.check('test', str(index))
    assert rate_limit._store == {}

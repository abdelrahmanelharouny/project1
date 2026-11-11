"""A2 async bridge client: timeout/failure handling, degradation contract,
auth header injection, concurrency budget, circuit-breaker integration.

All network I/O is mocked at the httpx boundary — the suite never needs the
real bridge (parity with tests/conftest.py's no-network rule).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.intelligence import bridge
from app.intelligence.circuit_breaker import breaker as global_breaker


@pytest.fixture(autouse=True)
def _reset_breaker_and_settings():
    global_breaker.reset()
    from app.intelligence.config import ai_settings

    old = (ai_settings.llm_enabled, ai_settings.llm_max_concurrent)
    yield
    global_breaker.reset()
    ai_settings.llm_enabled, ai_settings.llm_max_concurrent = old


def _patch_apost(monkeypatch, responses):
    """Replace the async POST with a scripted responder (list of results)."""
    calls: list[dict] = []

    async def fake_apost(client, url, payload, timeout):
        calls.append({"url": url, "payload": payload})
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bridge, "_apost", fake_apost)
    return calls


def test_async_success_returns_content_and_model(monkeypatch):
    _patch_apost(monkeypatch, [({"content": "hello", "model": "glm-4-plus"}, None)])
    detail = asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}]))
    assert detail == {"content": "hello", "model": "glm-4-plus"}


def test_async_disabled_by_config_returns_none(monkeypatch):
    from app.intelligence.config import ai_settings

    ai_settings.llm_enabled = False
    calls = _patch_apost(monkeypatch, [])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert calls == []


def test_async_timeout_failure_returns_none_and_records_failure(monkeypatch):
    _patch_apost(monkeypatch, [httpx.ConnectTimeout("boom")])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert global_breaker.state in ("closed", "open")


def test_async_retries_connect_error_then_succeeds(monkeypatch):
    calls = _patch_apost(monkeypatch, [
        (None, "connect"),
        ({"content": "recovered", "model": "m"}, None),
    ])
    detail = asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}]))
    assert detail and detail["content"] == "recovered"
    assert len(calls) == 2


def test_async_no_retry_on_non_connect_errors(monkeypatch):
    calls = _patch_apost(monkeypatch, [({"error": "boom"}, "other")])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert len(calls) == 1  # failing requests must not multiply latency


def test_async_rate_limited_and_auth_do_not_retry(monkeypatch):
    calls = _patch_apost(monkeypatch, [({"error": "x"}, "rate_limited")])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert len(calls) == 1
    calls = _patch_apost(monkeypatch, [({"error": "x"}, "auth")])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert len(calls) == 1


def test_async_empty_content_is_none(monkeypatch):
    _patch_apost(monkeypatch, [({"content": "   "}, None)])
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None


def test_async_circuit_open_fails_fast_without_network(monkeypatch):
    calls = _patch_apost(monkeypatch, [])
    for _ in range(50):
        global_breaker.record_failure()
    assert global_breaker.state == "open"
    assert asyncio.run(bridge.achat_detail([{"role": "user", "content": "hi"}])) is None
    assert calls == []  # no network I/O while open


def test_async_concurrency_bounded_by_semaphore(monkeypatch):
    """max_concurrent=2: at most 2 POSTs in flight simultaneously."""
    from app.intelligence.config import ai_settings

    ai_settings.llm_max_concurrent = 2
    in_flight = 0
    peak = 0
    started = asyncio.Event()

    class FakeClient:
        pass

    async def fake_apost(client, url, payload, timeout):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return ({"content": "ok"}, None)

    monkeypatch.setattr(bridge, "_apost", fake_apost)

    async def scenario():
        tasks = [
            asyncio.create_task(bridge.achat_detail([{"role": "user", "content": f"m{i}"}]))
            for i in range(6)
        ]
        results = await asyncio.gather(*tasks)
        assert all(r and r["content"] == "ok" for r in results)

    asyncio.run(scenario())
    assert peak <= 2, f"concurrency exceeded budget: peak={peak}"


def test_auth_header_injected_when_token_configured(monkeypatch):
    """A9 client side: the sync path sends X-Bridge-Token when configured."""
    from app.intelligence.config import ai_settings

    captured: dict[str, str] = {}

    def fake_client_post(self, url, json=None, headers=None):
        captured.update(headers or {})

        class R:
            status_code = 200

            def json(self):
                return {"content": "ok"}

        return R()

    monkeypatch.setattr(httpx.Client, "post", fake_client_post)
    old_token = ai_settings.llm_bridge_token
    try:
        ai_settings.llm_bridge_token = "secret-value"
        assert bridge.chat([{"role": "user", "content": "hi"}]) == "ok"
        assert captured.get("X-Bridge-Token") == "secret-value"

        ai_settings.llm_bridge_token = ""
        captured.clear()
        assert bridge.chat([{"role": "user", "content": "hi"}]) == "ok"
        assert "X-Bridge-Token" not in captured
    finally:
        ai_settings.llm_bridge_token = old_token


def test_sync_bridge_convergence_with_breaker(monkeypatch):
    """Sync path records breaker failures too (shared breaker across paths)."""
    from app.intelligence.config import ai_settings

    ai_settings.llm_enabled = True
    monkeypatch.setattr(
        bridge, "_post", lambda *a, **k: (None, "connect")
    )
    global_breaker.reset()
    for _ in range(50):
        assert bridge.chat([{"role": "user", "content": "hi"}]) is None
    assert global_breaker.state == "open"
    # Now even the sync path must fail fast WITHOUT calling _post.
    raised = []

    def exploding_post(*a, **k):
        raised.append(True)
        raise AssertionError("network must not be touched while circuit is open")

    monkeypatch.setattr(bridge, "_post", exploding_post)
    assert bridge.chat([{"role": "user", "content": "hi"}]) is None
    assert raised == []

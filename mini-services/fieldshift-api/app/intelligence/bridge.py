"""LLM bridge client (A2: async + sync, circuit breaker, budgets, auth).

Contract with the bridge mini-service:
    POST {base_url}/chat        {"messages": [{"role", "content"}, ...],
                                 "temperature"?: float, "max_tokens"?: int}
    200 →                       {"content": "...", "model"?: "..."}
    401/413/429/502/504 →       {"error": "..."}

Headers: `X-Bridge-Token: <shared secret>` when CROPTWIST_LLM_BRIDGE_TOKEN is
configured (A9 service-to-service auth). The token is never logged.

Architecture notes (A2):
- `achat_detail` is the async path for async endpoints (httpx.AsyncClient,
  one client per call is avoided via a module-level client; created lazily so
  tests and forked workers never share an uninitialized loop).
- `chat_detail` stays available for sync/threadpool callers (background jobs,
  evaluation scripts) via httpx.Client.
- Both paths share ONE CircuitBreaker (`breaker`): open circuit => instant
  None without any network I/O. Recovery probes go through the same breaker.
- Budgets (config): connect timeout, total timeout, max retries (connect
  errors only, exponential backoff capped), max_tokens, max concurrent
  requests (semaphore on the async path; the sync path is threadpool-bound
  and respects the same limit via the bridge's own 429 handling).
- Degradation policy unchanged (docs/architecture/AI_LAYERS.md): ANY failure
  — disabled, open circuit, unreachable, timeout, non-200, malformed body,
  empty content — returns None and logs a warning; callers fall back to
  deterministic rules output. This module never raises toward its callers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.intelligence import metrics
from app.intelligence.circuit_breaker import CircuitOpenError, breaker
from app.intelligence.config import ai_settings

logger = logging.getLogger("croptwist.intelligence.bridge")

_ASYNC_CLIENT: httpx.AsyncClient | None = None
_ASYNC_CLIENT_LOCK = asyncio.Lock()


def _headers() -> dict[str, str]:
    headers = {"accept": "application/json"}
    token = ai_settings.llm_bridge_token
    if token:
        headers["X-Bridge-Token"] = token
    return headers


async def _get_async_client() -> httpx.AsyncClient:
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None or _ASYNC_CLIENT.is_closed:
        async with _ASYNC_CLIENT_LOCK:
            if _ASYNC_CLIENT is None or _ASYNC_CLIENT.is_closed:
                _ASYNC_CLIENT = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        ai_settings.llm_timeout_seconds,
                        connect=ai_settings.llm_connect_timeout_seconds,
                    ),
                    limits=httpx.Limits(
                        max_connections=ai_settings.llm_max_concurrent,
                        max_keepalive_connections=ai_settings.llm_max_concurrent,
                    ),
                )
    return _ASYNC_CLIENT


async def aclose_async_client() -> None:
    """Close the shared async client (test/teardown helper)."""
    global _ASYNC_CLIENT
    async with _ASYNC_CLIENT_LOCK:
        if _ASYNC_CLIENT is not None and not _ASYNC_CLIENT.is_closed:
            await _ASYNC_CLIENT.aclose()
        _ASYNC_CLIENT = None


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff for connect-error retries: 0.25s, 0.5s, 1s…"""
    return min(0.25 * (2 ** max(0, attempt - 1)), 2.0)


def _validate_body(body: dict[str, Any]) -> dict[str, Any] | None:
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.warning("LLM bridge response has no usable content — falling back to rules.")
        return None
    detail: dict[str, Any] = {"content": content}
    model = body.get("model")
    if isinstance(model, str) and model.strip():
        detail["model"] = model.strip()
    return detail


async def _apost(
    client: httpx.AsyncClient, url: str, payload: dict[str, Any], timeout: float
) -> tuple[dict[str, Any] | None, str | None]:
    """One async POST → (parsed_json, error_kind); exactly one is non-None.

    error_kind: "connect" (retryable), "rate_limited" (bridge 429 — do not
    retry, the bridge is protecting itself), "auth" (401 — misconfiguration),
    "other" for every other failure.
    """
    try:
        response = await client.post(
            url, json=payload, headers=_headers(), timeout=timeout
        )
    except httpx.ConnectError as exc:
        logger.warning("LLM bridge connection failed: %s", exc)
        return None, "connect"
    except httpx.ConnectTimeout as exc:
        logger.warning("LLM bridge connect timed out: %s", exc)
        return None, "connect"
    except httpx.HTTPError as exc:
        logger.warning("LLM bridge request failed: %s", exc)
        return None, "other"
    if response.status_code == 401:
        metrics.incr("bridge_error_total_auth")
        logger.error("LLM bridge rejected the auth token (401) — check CROPTWIST_LLM_BRIDGE_TOKEN.")
        return None, "auth"
    if response.status_code == 429:
        metrics.incr("bridge_error_total_rate_limited")
        logger.warning("LLM bridge is at capacity (429) — falling back to rules.")
        return None, "rate_limited"
    if response.status_code != 200:
        logger.warning(
            "LLM bridge returned HTTP %s — falling back to rules.", response.status_code
        )
        return None, "other"
    try:
        body = response.json()
    except ValueError:
        logger.warning("LLM bridge returned a non-JSON body — falling back to rules.")
        return None, "other"
    if not isinstance(body, dict):
        logger.warning("LLM bridge returned a non-object JSON body — falling back to rules.")
        return None, "other"
    return body, None


async def achat_detail(
    messages: list[dict[str, str]], temperature: float | None = None, max_tokens: int | None = None
) -> dict[str, Any] | None:
    """Async chat with the bridge; {"content", "model"?} or None (never raises)."""
    if not ai_settings.llm_enabled:
        logger.info("LLM bridge disabled by configuration — rules-only mode.")
        return None
    temp = ai_settings.llm_temperature if temperature is None else temperature
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens if max_tokens is not None else ai_settings.llm_max_tokens,
    }
    base_url = ai_settings.llm_bridge_url.rstrip("/")
    url = f"{base_url}/chat"
    timeout = ai_settings.llm_timeout_seconds

    async def _attempt() -> tuple[dict[str, Any] | None, str | None]:
        client = await _get_async_client()
        return await _apost(client, url, payload, timeout)

    started = time.perf_counter()
    try:
        await breaker.aacquire()
    except CircuitOpenError:
        logger.warning("LLM bridge circuit open — returning None without network call.")
        return None
    try:
        sem = _concurrency_semaphore()
        body: dict[str, Any] | None = None
        error: str | None = "other"
        for attempt in range(max(1, ai_settings.llm_max_retries + 1)):
            async with sem:
                body, error = await _attempt()
            if body is not None or error != "connect":
                break
            if attempt < ai_settings.llm_max_retries:
                await asyncio.sleep(_backoff_delay(attempt + 1))
    except CircuitOpenError:
        return None
    except Exception as exc:  # noqa: BLE001 — degradation contract: never raise
        metrics.incr("bridge_errors_total")
        logger.warning("LLM bridge async call failed unexpectedly: %s", exc)
        breaker.record_failure()
        return None

    metrics.incr("bridge_requests_total")
    metrics.record_latency_sample("bridge_latency_seconds", time.perf_counter() - started)
    if body is None:
        metrics.incr("bridge_errors_total")
        breaker.record_failure()
        return None
    breaker.record_success()
    return _validate_body(body)


_SEMAPHORE: asyncio.Semaphore | None = None
_SEMAPHORE_SIZE = 0


def _concurrency_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE, _SEMAPHORE_SIZE
    size = ai_settings.llm_max_concurrent
    if _SEMAPHORE is None or _SEMAPHORE_SIZE != size:
        _SEMAPHORE = asyncio.Semaphore(size)
        _SEMAPHORE_SIZE = size
    return _SEMAPHORE


# --------------------------------------------------------------------------
# Sync path (threadpool callers: background jobs, evaluation scripts).
# --------------------------------------------------------------------------
def _post(url: str, payload: dict[str, Any], timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    """One POST. Returns (parsed_json, error_kind); exactly one is non-None."""
    try:
        response = httpx.Client(timeout=timeout).post(url, json=payload, headers=_headers())
    except httpx.ConnectError as exc:
        logger.warning("LLM bridge connection failed: %s", exc)
        return None, "connect"
    except httpx.HTTPError as exc:
        logger.warning("LLM bridge request failed: %s", exc)
        return None, "other"
    if response.status_code == 401:
        metrics.incr("bridge_error_total_auth")
        logger.error("LLM bridge rejected the auth token (401) — check CROPTWIST_LLM_BRIDGE_TOKEN.")
        return None, "auth"
    if response.status_code == 429:
        metrics.incr("bridge_error_total_rate_limited")
        logger.warning("LLM bridge is at capacity (429) — falling back to rules.")
        return None, "rate_limited"
    if response.status_code != 200:
        logger.warning("LLM bridge returned HTTP %s — falling back to rules.", response.status_code)
        return None, "other"
    try:
        body = response.json()
    except ValueError:
        logger.warning("LLM bridge returned a non-JSON body — falling back to rules.")
        return None, "other"
    if not isinstance(body, dict):
        logger.warning("LLM bridge returned a non-object JSON body — falling back to rules.")
        return None, "other"
    return body, None


def chat_detail(
    messages: list[dict[str, str]], temperature: float | None = None, max_tokens: int | None = None
) -> dict[str, Any] | None:
    """Sync chat with the bridge; {"content", "model"?} or None (never raises)."""
    if not ai_settings.llm_enabled:
        logger.info("LLM bridge disabled by configuration — rules-only mode.")
        return None
    temp = ai_settings.llm_temperature if temperature is None else temperature
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens if max_tokens is not None else ai_settings.llm_max_tokens,
    }
    base_url = ai_settings.llm_bridge_url.rstrip("/")
    url = f"{base_url}/chat"

    try:
        breaker.acquire()
    except CircuitOpenError:
        logger.warning("LLM bridge circuit open — returning None without network call.")
        return None

    metrics.incr("bridge_requests_total")
    started = time.perf_counter()
    body: dict[str, Any] | None = None
    error: str | None = "other"
    # Connect-error retries with capped backoff (timeout failures never retry:
    # a retry would multiply an already-failing request's latency).
    for attempt in range(max(1, ai_settings.llm_max_retries + 1)):
        body, error = _post(url, payload, ai_settings.llm_timeout_seconds)
        if body is not None or error != "connect":
            break
        if attempt < ai_settings.llm_max_retries:
            time.sleep(_backoff_delay(attempt + 1))
    metrics.record_latency_sample("bridge_latency_seconds", time.perf_counter() - started)

    if body is None:
        metrics.incr("bridge_errors_total")
        breaker.record_failure()
        return None
    breaker.record_success()
    return _validate_body(body)


def chat(messages: list[dict[str, str]], temperature: float | None = None) -> str | None:
    """Bridge chat returning the assistant text, or None on ANY failure.

    This is the module's public sync contract; `chat_detail` additionally
    exposes the bridge-reported model name for provenance fields.
    """
    detail = chat_detail(messages, temperature=temperature)
    return detail["content"] if detail else None

"""LLM bridge client (sync httpx — FieldShift endpoints are sync `def` and
FastAPI runs them in its threadpool, so blocking calls are safe here).

Contract with the bridge mini-service:
    POST {base_url}/chat        {"messages": [{"role", "content"}, ...],
                                 "temperature": float}
    200 →                       {"content": "...", "model"?: "..."}

Degradation policy (docs/architecture/AI_LAYERS.md): the bridge is best-effort.
ANY failure — disabled by config, unreachable, timeout, non-200, malformed
body, empty content — returns None and logs a warning; callers fall back to
deterministic rules output. Exactly one retry, on connection error only (the
transient failure mode). This module never raises toward its callers.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.intelligence.config import ai_settings

logger = logging.getLogger("fieldshift.intelligence.bridge")


def _post(url: str, payload: dict[str, Any], timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    """One POST. Returns (parsed_json, error_kind); exactly one is non-None.

    error_kind is "connect" for connection errors (the retryable kind) or
    "other" for every other failure (timeout, HTTP error, non-200, bad body).
    """
    try:
        response = httpx.Client(timeout=timeout).post(
            url, json=payload, headers={"accept": "application/json"}
        )
    except httpx.ConnectError as exc:
        logger.warning("LLM bridge connection failed: %s", exc)
        return None, "connect"
    except httpx.HTTPError as exc:
        logger.warning("LLM bridge request failed: %s", exc)
        return None, "other"
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
    messages: list[dict[str, str]], temperature: float = 0.3
) -> dict[str, Any] | None:
    """Chat with the bridge; return {"content", "model"?} or None.

    `model` is surfaced only when the bridge reports it (engine provenance for
    `generated_by` / `engine.model` fields downstream).
    """
    if not ai_settings.llm_enabled:
        logger.info("LLM bridge disabled by configuration — rules-only mode.")
        return None
    base_url = ai_settings.llm_bridge_url.rstrip("/")
    url = f"{base_url}/chat"
    payload = {"messages": messages, "temperature": temperature}
    body, error = _post(url, payload, ai_settings.llm_timeout_seconds)
    if body is None and error == "connect":
        # Exactly one retry, on connection error only.
        body, error = _post(url, payload, ai_settings.llm_timeout_seconds)
    if body is None:
        return None

    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.warning("LLM bridge response has no usable content — falling back to rules.")
        return None
    detail: dict[str, Any] = {"content": content}
    model = body.get("model")
    if isinstance(model, str) and model.strip():
        detail["model"] = model.strip()
    return detail


def chat(messages: list[dict[str, str]], temperature: float = 0.3) -> str | None:
    """Bridge chat returning the assistant text, or None on ANY failure.

    This is the module's public contract; `chat_detail` additionally exposes
    the bridge-reported model name for provenance fields.
    """
    detail = chat_detail(messages, temperature=temperature)
    return detail["content"] if detail else None

"""Documented HTTP adapters and the CropTwist provider failover policy.

No adapter performs network I/O at import time. Secrets stay in environment
settings, provider errors are normalized, and field-sensitive content is held
inside CropTwist unless an operator explicitly enables the relevant data gate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from time import perf_counter
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

import httpx

from app.intelligence.config import AISettings, ai_settings
from app.intelligence.orchestration.provider import (
    LLMProvider,
    ProviderCapabilities,
    ProviderGeneration,
    ProviderRegistry,
    ProviderStreamEvent,
    ProviderCapabilityUnavailable,
)

logger = logging.getLogger("croptwist.intelligence.providers")


@dataclass(frozen=True)
class ProviderFailure(Exception):
    """Normalized provider failure; never carries provider body or prompt text."""

    category: str
    retryable: bool
    http_status: int | None = None
    retry_after_seconds: float | None = None
    partial_output: bool = False
    attempts: tuple[dict[str, Any], ...] = ()

    def __str__(self) -> str:
        return self.category


class ProviderCircuit:
    """Small per-provider circuit breaker with one recovery probe."""

    def __init__(self, threshold: int, recovery_seconds: float) -> None:
        self.threshold = threshold
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_until = 0.0
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._opened_until > now:
                return False
            if self._opened_until:
                if self._probe_in_flight:
                    return False
                self._probe_in_flight = True
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0
            self._probe_in_flight = False

    def failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures += 1
            self._probe_in_flight = False
            if self._failures >= self.threshold:
                self._opened_until = now + self.recovery_seconds

    def status(self) -> str:
        with self._lock:
            if self._opened_until > time.monotonic():
                return "open"
            if self._opened_until:
                return "half_open"
            return "closed"


class _HTTPProvider:
    name = ""
    capabilities = ProviderCapabilities()
    base_url = ""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        connect_timeout_seconds: float,
        max_retries: int,
        max_concurrent: int,
        circuit_threshold: int,
        circuit_recovery_seconds: float,
        max_backoff_seconds: float,
        client_factory: Callable[[httpx.Timeout], httpx.AsyncClient] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key.strip()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_retries = max_retries
        self.max_backoff_seconds = max_backoff_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._circuit = ProviderCircuit(circuit_threshold, circuit_recovery_seconds)
        self._client_factory = client_factory or self._default_client
        self._sleep = sleep

    @staticmethod
    def _default_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    @property
    def circuit_status(self) -> str:
        return self._circuit.status()

    def _headers(self, request_id: str | None) -> dict[str, str]:
        headers = {"accept": "application/json", "content-type": "application/json"}
        headers.update(self._auth_headers())
        if request_id and len(request_id) <= 128 and all(ord(ch) >= 32 for ch in request_id):
            headers["X-Client-Request-Id"] = request_id
        return headers

    def _auth_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}"}

    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _endpoint(self, *, stream: bool) -> str:
        return self.base_url

    def _parse_response(self, body: dict[str, Any]) -> ProviderGeneration:
        raise NotImplementedError

    def _parse_stream_event(self, body: dict[str, Any]) -> list[ProviderStreamEvent]:
        raise NotImplementedError

    def _status_failure(self, response: httpx.Response) -> ProviderFailure:
        status = response.status_code
        retry_after: float | None = None
        value = response.headers.get("retry-after")
        if value:
            try:
                retry_after = max(0.0, min(float(value), self.max_backoff_seconds))
            except (TypeError, ValueError):
                retry_after = None

        if status in (408, 429, 498, 500, 502, 503, 504):
            return ProviderFailure("provider_transient_http", True, status, retry_after)
        # OpenRouter 402 is a transient in-flight-budget case only when the
        # provider explicitly supplies Retry-After and the bounded response
        # body identifies that case. Ordinary credits/billing failures do not retry.
        if self.name == "openrouter" and status == 402 and retry_after is not None:
            try:
                payload = response.json()
                message = json.dumps(payload, ensure_ascii=False).casefold()
                if "in-flight" in message or "in flight" in message:
                    return ProviderFailure("provider_capacity_limited", True, status, retry_after)
            except (ValueError, TypeError):
                pass
        if status in (401, 403):
            return ProviderFailure("provider_credentials_or_permission", False, status)
        if status == 402:
            return ProviderFailure("provider_billing_required", False, status)
        if status in (400, 404, 413, 422):
            return ProviderFailure("provider_invalid_request_or_model", False, status)
        if status >= 500:
            return ProviderFailure("provider_server_error", True, status, retry_after)
        return ProviderFailure("provider_http_error", False, status)

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout_seconds, connect=self.connect_timeout_seconds)

    async def _acquire_slot(self) -> None:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise ProviderFailure("provider_concurrency_timeout", True) from exc

    async def _post_json(
        self,
        *,
        payload: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        await self._acquire_slot()
        try:
            async with self._client_factory(self._timeout()) as client:
                response = await client.post(
                    self._endpoint(stream=False),
                    json=payload,
                    headers=self._headers(request_id),
                    timeout=self._timeout(),
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise self._status_failure(response)
            if len(response.content) > 2_000_000:
                raise ProviderFailure("provider_response_too_large", False, response.status_code)
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderFailure("provider_invalid_json_response", True, response.status_code) from exc
            if not isinstance(body, dict):
                raise ProviderFailure("provider_invalid_response_shape", True, response.status_code)
            if body.get("error"):
                raise ProviderFailure("provider_reported_error", False, response.status_code)
            return body
        except httpx.TimeoutException as exc:
            raise ProviderFailure("provider_timeout", True) from exc
        except httpx.ConnectError as exc:
            raise ProviderFailure("provider_connection_error", True) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("provider_transport_error", True) from exc
        finally:
            self._semaphore.release()

    async def _json_with_retries(
        self,
        payload: dict[str, Any],
        request_id: str | None,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], int]:
        if not self.configured:
            raise ProviderFailure("provider_unconfigured", False)
        if not self._circuit.acquire():
            raise ProviderFailure("provider_circuit_open", True)
        attempts: list[dict[str, Any]] = []
        started = perf_counter()
        for attempt_number in range(self.max_retries + 1):
            one_started = perf_counter()
            try:
                body = await self._post_json(payload=payload, request_id=request_id)
            except ProviderFailure as exc:
                attempts.append({
                    "provider": self.name,
                    "model": self.model,
                    "status": "failed",
                    "error_category": exc.category,
                    "latency_ms": max(0, round((perf_counter() - one_started) * 1000)),
                })
                if not exc.retryable:
                    raise ProviderFailure(
                        exc.category, False, exc.http_status,
                        attempts=tuple(attempts),
                    ) from exc
                if attempt_number >= self.max_retries:
                    self._circuit.failure()
                    raise ProviderFailure(
                        exc.category, True, exc.http_status,
                        exc.retry_after_seconds, attempts=tuple(attempts),
                    ) from exc
                await self._backoff(attempt_number, exc.retry_after_seconds)
            else:
                attempts.append({
                    "provider": self.name,
                    "model": self.model,
                    "status": "succeeded",
                    "latency_ms": max(0, round((perf_counter() - one_started) * 1000)),
                })
                self._circuit.success()
                return body, tuple(attempts), max(0, round((perf_counter() - started) * 1000))
        raise ProviderFailure("provider_request_failed", True, attempts=tuple(attempts))

    async def _backoff(self, attempt_number: int, retry_after: float | None) -> None:
        exponential = min(0.2 * (2**attempt_number), self.max_backoff_seconds)
        jitter = random.uniform(0.0, min(0.15, self.max_backoff_seconds / 4))
        delay = min(self.max_backoff_seconds, max(exponential + jitter, retry_after or 0.0))
        if delay > 0:
            await self._sleep(delay)

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None:
        payload = self._payload(
            messages, temperature=temperature, max_tokens=max_tokens, schema=None, stream=False
        )
        body, attempts, elapsed = await self._json_with_retries(payload, request_id)
        generation = self._parse_response(body)
        return ProviderGeneration(
            content=generation.content,
            provider=self.name,
            model=generation.model or self.model,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            attempts=attempts,
            provider_latency_ms=elapsed,
        )

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None:
        payload = self._payload(
            messages, temperature=temperature, max_tokens=max_tokens, schema=schema, stream=False
        )
        body, attempts, elapsed = await self._json_with_retries(payload, request_id)
        generation = self._parse_response(body)
        try:
            json.loads(generation.content)
        except (TypeError, ValueError) as exc:
            raise ProviderFailure("provider_structured_output_invalid_json", False, attempts=attempts) from exc
        return ProviderGeneration(
            content=generation.content,
            provider=self.name,
            model=generation.model or self.model,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            attempts=attempts,
            provider_latency_ms=elapsed,
        )

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None:
        # Vendor/model tool-calling support is not used or asserted until its
        # exact availability is separately verified; CropTwist tools remain
        # server-selected by the deterministic planner.
        raise ProviderCapabilityUnavailable("Native model tool calling is not enabled for this provider chain.")

    async def _stream_once(
        self,
        payload: dict[str, Any],
        request_id: str | None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        await self._acquire_slot()
        try:
            async with self._client_factory(self._timeout()) as client:
                async with client.stream(
                    "POST",
                    self._endpoint(stream=True),
                    json=payload,
                    headers=self._headers(request_id),
                    timeout=self._timeout(),
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        await response.aread()
                        raise self._status_failure(response)
                    async for line in response.aiter_lines():
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            body = json.loads(data)
                        except ValueError as exc:
                            raise ProviderFailure("provider_invalid_stream_frame", True) from exc
                        if not isinstance(body, dict):
                            continue
                        if body.get("error"):
                            raise ProviderFailure("provider_stream_error", False)
                        for event in self._parse_stream_event(body):
                            yield event
        except httpx.TimeoutException as exc:
            raise ProviderFailure("provider_timeout", True) from exc
        except httpx.ConnectError as exc:
            raise ProviderFailure("provider_connection_error", True) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("provider_transport_error", True) from exc
        finally:
            self._semaphore.release()

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if not self.configured:
            raise ProviderFailure("provider_unconfigured", False)
        if not self._circuit.acquire():
            raise ProviderFailure("provider_circuit_open", True)
        payload = self._payload(
            messages, temperature=temperature, max_tokens=max_tokens, schema=None, stream=True
        )
        attempts: list[dict[str, Any]] = []
        for attempt_number in range(self.max_retries + 1):
            one_started = perf_counter()
            emitted_text = False
            try:
                async for event in self._stream_once(payload, request_id):
                    if event.text:
                        emitted_text = True
                    yield event
            except ProviderFailure as exc:
                attempts.append({
                    "provider": self.name,
                    "model": self.model,
                    "status": "failed",
                    "error_category": exc.category,
                    "latency_ms": max(0, round((perf_counter() - one_started) * 1000)),
                })
                if emitted_text or exc.partial_output:
                    self._circuit.failure()
                    raise ProviderFailure(
                        "provider_stream_interrupted", False,
                        exc.http_status, partial_output=True, attempts=tuple(attempts),
                    ) from exc
                if not exc.retryable:
                    raise ProviderFailure(exc.category, False, exc.http_status, attempts=tuple(attempts)) from exc
                if attempt_number >= self.max_retries:
                    self._circuit.failure()
                    raise ProviderFailure(exc.category, True, exc.http_status,
                                          exc.retry_after_seconds, attempts=tuple(attempts)) from exc
                await self._backoff(attempt_number, exc.retry_after_seconds)
            else:
                attempts.append({
                    "provider": self.name,
                    "model": self.model,
                    "status": "succeeded",
                    "latency_ms": max(0, round((perf_counter() - one_started) * 1000)),
                })
                self._circuit.success()
                return
        raise ProviderFailure("provider_stream_failed", True, attempts=tuple(attempts))


class GeminiProvider(_HTTPProvider):
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/models"
    capabilities = ProviderCapabilities(
        text_generation=True,
        native_structured_output=True,
        tool_calling=False,
        streaming=True,
        token_usage_reporting=True,
        structured_output_mode="native_json_schema_subset",
    )

    def _auth_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key}

    def _endpoint(self, *, stream: bool) -> str:
        suffix = ":streamGenerateContent?alt=sse" if stream else ":generateContent"
        return f"{self.base_url}/{self.model}{suffix}"

    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in ("system", "user", "assistant") or not isinstance(content, str):
                raise ProviderFailure("provider_invalid_message_contract", False)
            if role == "system":
                system_parts.append({"text": content})
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        if not contents:
            raise ProviderFailure("provider_empty_messages", False)
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = schema
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _parse_response(self, body: dict[str, Any]) -> ProviderGeneration:
        feedback = body.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise ProviderFailure("provider_safety_block", False)
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderFailure("provider_empty_response", False)
        texts: list[str] = []
        finish_reasons: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            finish = candidate.get("finishReason")
            if isinstance(finish, str):
                finish_reasons.append(finish.upper())
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                texts.extend(part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
        if "SAFETY" in finish_reasons or "RECITATION" in finish_reasons:
            raise ProviderFailure("provider_safety_block", False)
        text = "".join(texts).strip()
        if not text:
            raise ProviderFailure("provider_empty_response", False)
        usage = body.get("usageMetadata") if isinstance(body.get("usageMetadata"), dict) else {}
        return ProviderGeneration(
            content=text,
            provider=self.name,
            model=self.model,
            input_tokens=_nonnegative_int(usage.get("promptTokenCount")),
            output_tokens=_nonnegative_int(usage.get("candidatesTokenCount")),
        )

    def _parse_stream_event(self, body: dict[str, Any]) -> list[ProviderStreamEvent]:
        candidates = body.get("candidates")
        usage = body.get("usageMetadata") if isinstance(body.get("usageMetadata"), dict) else {}
        if not isinstance(candidates, list):
            if usage:
                return [ProviderStreamEvent(
                    input_tokens=_nonnegative_int(usage.get("promptTokenCount")),
                    output_tokens=_nonnegative_int(usage.get("candidatesTokenCount")),
                    model=self.model,
                )]
            return []
        output: list[ProviderStreamEvent] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            finish = candidate.get("finishReason")
            if isinstance(finish, str) and finish.upper() in ("SAFETY", "RECITATION"):
                raise ProviderFailure("provider_safety_block", False)
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    output.append(ProviderStreamEvent(
                        text=part["text"],
                        input_tokens=_nonnegative_int(usage.get("promptTokenCount")),
                        output_tokens=_nonnegative_int(usage.get("candidatesTokenCount")),
                        model=self.model,
                        finish_reason=finish if isinstance(finish, str) else None,
                    ))
        if not output and usage:
            output.append(ProviderStreamEvent(
                input_tokens=_nonnegative_int(usage.get("promptTokenCount")),
                output_tokens=_nonnegative_int(usage.get("candidatesTokenCount")),
                model=self.model,
            ))
        return output


def _strict_json_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize the subset required by Groq strict JSON Schema mode."""
    schema = json.loads(json.dumps(value))

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
                node["additionalProperties"] = False
                for child in properties.values():
                    visit(child)
        items = node.get("items")
        if isinstance(items, dict):
            visit(items)
        for key in ("anyOf", "oneOf", "allOf"):
            choices = node.get(key)
            if isinstance(choices, list):
                for choice in choices:
                    visit(choice)

    visit(schema)
    return schema


class _OpenAICompatibleProvider(_HTTPProvider):
    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        if not messages or any(
            message.get("role") not in ("system", "user", "assistant")
            or not isinstance(message.get("content"), str)
            for message in messages
        ):
            raise ProviderFailure("provider_invalid_message_contract", False)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "croptwist_response",
                    "strict": True,
                    "schema": _strict_json_schema(schema),
                },
            }
        return payload

    def _parse_response(self, body: dict[str, Any]) -> ProviderGeneration:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderFailure("provider_empty_response", False)
        choice = choices[0]
        finish = str(choice.get("finish_reason") or "").casefold()
        if finish in ("content_filter", "safety"):
            raise ProviderFailure("provider_safety_block", False)
        if finish == "error":
            raise ProviderFailure("provider_reported_error", False)
        message = choice.get("message")
        content = _content_text(message.get("content")) if isinstance(message, dict) else ""
        if not content:
            raise ProviderFailure("provider_empty_response", False)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return ProviderGeneration(
            content=content,
            provider=self.name,
            model=(body.get("model") if isinstance(body.get("model"), str) else self.model),
            input_tokens=_nonnegative_int(usage.get("prompt_tokens")),
            output_tokens=_nonnegative_int(usage.get("completion_tokens")),
        )

    def _parse_stream_event(self, body: dict[str, Any]) -> list[ProviderStreamEvent]:
        if body.get("error"):
            raise ProviderFailure("provider_stream_error", False)
        choices = body.get("choices")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        if not isinstance(choices, list):
            # OpenRouter may send a content-free usage frame; preserve it for
            # backend metering without mistaking it for a terminal content event.
            if usage:
                return [ProviderStreamEvent(
                    input_tokens=_nonnegative_int(usage.get("prompt_tokens")),
                    output_tokens=_nonnegative_int(usage.get("completion_tokens")),
                    model=self.model,
                )]
            return []
        result: list[ProviderStreamEvent] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish = str(choice.get("finish_reason") or "").casefold()
            if finish == "error":
                raise ProviderFailure("provider_stream_error", False)
            if finish in ("content_filter", "safety"):
                raise ProviderFailure("provider_safety_block", False)
            delta = choice.get("delta")
            text = _content_text(delta.get("content")) if isinstance(delta, dict) else ""
            result.append(ProviderStreamEvent(
                text=text,
                input_tokens=_nonnegative_int(usage.get("prompt_tokens")),
                output_tokens=_nonnegative_int(usage.get("completion_tokens")),
                model=self.model,
                finish_reason=finish or None,
            ))
        return result


class GroqProvider(_OpenAICompatibleProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"
    capabilities = ProviderCapabilities(
        text_generation=True,
        native_structured_output=True,
        tool_calling=False,
        streaming=True,
        token_usage_reporting=True,
        structured_output_mode="native_strict_json_schema",
    )


class OpenRouterProvider(_OpenAICompatibleProvider):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1/chat/completions"
    capabilities = ProviderCapabilities(
        text_generation=True,
        native_structured_output=False,
        tool_calling=False,
        streaming=True,
        token_usage_reporting=True,
        structured_output_mode="conditional_provider_parameter_required",
        privacy_note="The requested free model may log prompts; field-data use requires explicit operator approval.",
    )

    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload = super()._payload(
            messages, temperature=temperature, max_tokens=max_tokens, schema=schema, stream=stream
        )
        if schema is not None:
            payload["provider"] = {"require_parameters": True}
        return payload


class ProviderFailoverChain:
    """Application-level priority chain; only transient failures advance."""

    name = "provider-failover-chain"

    def __init__(
        self,
        providers: list[LLMProvider],
        *,
        allow_sensitive_data: bool,
        prefer_streaming: bool = True,
    ) -> None:
        self.providers = providers
        self.allow_sensitive_data = allow_sensitive_data
        self.prefer_streaming = prefer_streaming
        self.last_attempts: list[dict[str, Any]] = []
        self.capabilities = ProviderCapabilities(
            text_generation=any(item.configured for item in providers),
            native_structured_output=any(item.capabilities.native_structured_output for item in providers),
            tool_calling=False,
            streaming=any(item.capabilities.streaming for item in providers),
            token_usage_reporting=any(item.capabilities.token_usage_reporting for item in providers),
            structured_output_mode="mixed_provider_modes",
        )

    @property
    def configured(self) -> bool:
        return any(item.configured for item in self.providers)

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None:
        if not self.allow_sensitive_data:
            return None
        all_attempts = self.last_attempts
        previous_provider_failed = False
        chain_started = perf_counter()
        for provider in self.providers:
            if not provider.configured:
                continue
            started = perf_counter()
            try:
                if self.prefer_streaming and provider.capabilities.streaming:
                    generation = await self._collect_stream(
                        provider,
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        request_id=request_id,
                    )
                else:
                    generation = await provider.generate(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        request_id=request_id,
                    )
            except ProviderFailure as exc:
                all_attempts.extend(exc.attempts)
                if not exc.attempts:
                    all_attempts.append({
                        "provider": provider.name,
                        "model": getattr(provider, "model", None),
                        "status": "failed",
                        "error_category": exc.category,
                        "latency_ms": max(0, round((perf_counter() - started) * 1000)),
                    })
                # Invalid credentials, request/schema errors, safety blocks and
                # caller-policy failures are configuration/action issues; do
                # not cascade or charge additional vendors.
                if not exc.retryable or exc.partial_output:
                    raise ProviderFailure(
                        exc.category,
                        False,
                        exc.http_status,
                        exc.retry_after_seconds,
                        partial_output=exc.partial_output,
                        attempts=tuple(all_attempts),
                    ) from exc
                previous_provider_failed = True
                continue
            if generation is None or not generation.content.strip():
                all_attempts.extend(generation.attempts if generation else ())
                continue
            success_attempts = list(generation.attempts)
            if not success_attempts:
                success_attempts.append({
                    "provider": generation.provider,
                    "model": generation.model,
                    "status": "succeeded",
                    "latency_ms": max(0, round((perf_counter() - started) * 1000)),
                })
            all_attempts.extend(success_attempts)
            if previous_provider_failed:
                try:
                    from app.intelligence import metrics
                    metrics.incr("ai_provider_failover_total")
                except Exception:  # telemetry must not block a valid answer
                    pass
            return ProviderGeneration(
                content=generation.content,
                provider=generation.provider,
                model=generation.model,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
                attempts=tuple(all_attempts),
                provider_latency_ms=max(0, round((perf_counter() - chain_started) * 1000)),
            )
        return None

    async def _collect_stream(
        self,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        request_id: str | None,
    ) -> ProviderGeneration:
        started = perf_counter()
        chunks: list[str] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        model: str | None = None
        try:
            async for event in provider.stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                request_id=request_id,
            ):
                if event.text:
                    chunks.append(event.text)
                if event.input_tokens is not None:
                    input_tokens = event.input_tokens
                if event.output_tokens is not None:
                    output_tokens = event.output_tokens
                if event.model:
                    model = event.model
        except ProviderFailure as exc:
            raise ProviderFailure(
                exc.category,
                exc.retryable and not chunks,
                exc.http_status,
                exc.retry_after_seconds,
                partial_output=bool(chunks) or exc.partial_output,
                attempts=exc.attempts,
            ) from exc
        content = "".join(chunks).strip()
        if not content:
            raise ProviderFailure("provider_empty_response", False)
        return ProviderGeneration(
            content=content,
            provider=provider.name,
            model=model or getattr(provider, "model", None),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            attempts=({
                "provider": provider.name,
                "model": model or getattr(provider, "model", None),
                "status": "succeeded",
                "latency_ms": max(0, round((perf_counter() - started) * 1000)),
            },),
            provider_latency_ms=max(0, round((perf_counter() - started) * 1000)),
        )

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None:
        if not self.allow_sensitive_data:
            return None
        all_attempts: list[dict[str, Any]] = []
        for provider in self.providers:
            if not provider.configured:
                continue
            mode = provider.capabilities.structured_output_mode
            if mode == "unsupported":
                continue
            try:
                generation = await provider.generate_structured(
                    messages,
                    schema=schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_id=request_id,
                )
            except ProviderFailure as exc:
                all_attempts.extend(exc.attempts)
                if not exc.retryable:
                    raise
                continue
            if generation is not None:
                return ProviderGeneration(
                    content=generation.content,
                    provider=generation.provider,
                    model=generation.model,
                    input_tokens=generation.input_tokens,
                    output_tokens=generation.output_tokens,
                    attempts=tuple([*all_attempts, *generation.attempts]),
                    provider_latency_ms=generation.provider_latency_ms,
                )
        raise ProviderCapabilityUnavailable("No configured provider can safely return structured JSON output.")

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None:
        raise ProviderCapabilityUnavailable(
            "Native model tool calling is intentionally disabled; the deterministic server planner owns tool selection."
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if not self.allow_sensitive_data:
            raise ProviderFailure("provider_data_policy_blocked", False)
        prior_text = False
        for provider in self.providers:
            if not provider.configured:
                continue
            try:
                async for event in provider.stream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_id=request_id,
                ):
                    if event.text:
                        prior_text = True
                    yield event
                return
            except ProviderFailure as exc:
                if prior_text or exc.partial_output or not exc.retryable:
                    raise ProviderFailure(
                        exc.category,
                        False,
                        exc.http_status,
                        partial_output=prior_text or exc.partial_output,
                        attempts=exc.attempts,
                    ) from exc
                continue
        raise ProviderFailure("provider_chain_unavailable", True)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in ("text", "output_text") and isinstance(item.get("text"), str)
        ]
        return "".join(parts).strip()
    return ""


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _secret_value(value: Any) -> str:
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def _build_kwargs(settings: AISettings) -> dict[str, Any]:
    return {
        "timeout_seconds": settings.ai_provider_timeout_seconds,
        "connect_timeout_seconds": settings.ai_provider_connect_timeout_seconds,
        "max_retries": settings.ai_provider_max_retries,
        "max_concurrent": settings.ai_provider_max_concurrent,
        "circuit_threshold": settings.ai_provider_cb_failure_threshold,
        "circuit_recovery_seconds": settings.ai_provider_cb_recovery_seconds,
        "max_backoff_seconds": settings.ai_provider_max_backoff_seconds,
    }


def register_default_providers(registry: ProviderRegistry) -> None:
    settings = ai_settings
    common = _build_kwargs(settings)
    registry.register(GeminiProvider(
        api_key=_secret_value(settings.gemini_api_key),
        model=settings.gemini_model,
        **common,
    ))
    registry.register(GroqProvider(
        api_key=_secret_value(settings.groq_api_key),
        model=settings.groq_model,
        **common,
    ))
    registry.register(OpenRouterProvider(
        api_key=_secret_value(settings.openrouter_api_key),
        model=settings.openrouter_model,
        **common,
    ))


def _legacy_bridge_is_local() -> bool:
    host = (urlparse(ai_settings.llm_bridge_url).hostname or "").casefold()
    return host in {"localhost", "127.0.0.1", "::1"}


def _allowed_for_sensitive_data(name: str) -> bool:
    if name == "legacy-llm-bridge":
        return _legacy_bridge_is_local() or ai_settings.ai_allow_field_data_to_providers
    if not ai_settings.ai_allow_field_data_to_providers:
        return False
    if name == "openrouter" and not ai_settings.openrouter_allow_field_data:
        return False
    return True


def get_provider_chain(*, field_sensitive: bool = True, prefer_streaming: bool = True) -> ProviderFailoverChain:
    providers: list[LLMProvider] = []
    for name in ai_settings.provider_order:
        try:
            provider = provider_registry.get(name)
        except LookupError:
            continue
        if field_sensitive and not _allowed_for_sensitive_data(name):
            continue
        providers.append(provider)
    return ProviderFailoverChain(
        providers,
        allow_sensitive_data=(not field_sensitive or any(_allowed_for_sensitive_data(p.name) for p in providers)),
        prefer_streaming=prefer_streaming,
    )


def get_provider_statuses() -> list[dict[str, Any]]:
    """Return configuration/readiness evidence, never make live provider calls."""
    items: list[dict[str, Any]] = []
    for priority, name in enumerate(ai_settings.provider_order, start=1):
        try:
            provider = provider_registry.get(name)
        except LookupError:
            items.append({"name": name, "priority": priority, "status": "unregistered"})
            continue
        configured = provider.configured
        allowed = _allowed_for_sensitive_data(name)
        if not configured:
            status = "missing_credentials_or_disabled"
        elif not allowed:
            status = "blocked_by_field_data_policy"
        else:
            status = "configured_live_unverified"
        model = getattr(provider, "model", None)
        items.append({
            "name": name,
            "priority": priority,
            "model": model,
            "status": status,
            "configured": configured,
            "circuit": getattr(provider, "circuit_status", "not_applicable"),
            "capabilities": {
                "text_generation": provider.capabilities.text_generation,
                "structured_output_mode": provider.capabilities.structured_output_mode,
                "tool_calling": provider.capabilities.tool_calling,
                "streaming": provider.capabilities.streaming,
                "token_usage_reporting": provider.capabilities.token_usage_reporting,
            },
            "privacy_note": provider.capabilities.privacy_note,
        })
    return items


from app.intelligence.orchestration.provider import provider_registry  # noqa: E402

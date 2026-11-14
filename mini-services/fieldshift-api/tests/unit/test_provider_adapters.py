"""Mock-only tests for external provider adapters; never call a live vendor."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.intelligence.orchestration.provider import (
    ProviderCapabilities,
    ProviderGeneration,
    ProviderStreamEvent,
)
from app.intelligence.orchestration.provider_adapters import (
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
    ProviderFailoverChain,
    ProviderFailure,
    get_provider_statuses,
)


def _provider_kwargs(transport: httpx.AsyncBaseTransport) -> dict[str, Any]:
    return {
        "api_key": "unit-test-key",
        "model": "unit-test-model",
        "timeout_seconds": 2,
        "connect_timeout_seconds": 1,
        "max_retries": 0,
        "max_concurrent": 1,
        "circuit_threshold": 2,
        "circuit_recovery_seconds": 0.1,
        "max_backoff_seconds": 0,
        "client_factory": lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    }


def test_gemini_exact_rest_shape_usage_and_request_correlation():
    observed: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "Grounded answer."}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 31, "candidatesTokenCount": 8, "totalTokenCount": 39},
        })

    provider = GeminiProvider(**_provider_kwargs(httpx.MockTransport(handle)))
    result = asyncio.run(provider.generate(
        [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}],
        temperature=0.1,
        max_tokens=100,
        request_id="req-1",
    ))
    assert result is not None
    assert result.provider == "gemini"
    assert result.input_tokens == 31 and result.output_tokens == 8
    assert observed["url"].endswith("/unit-test-model:generateContent")
    assert observed["headers"]["x-goog-api-key"] == "unit-test-key"
    assert observed["headers"]["x-client-request-id"] == "req-1"
    assert observed["body"]["systemInstruction"]["parts"][0]["text"] == "rules"
    assert observed["body"]["contents"][0]["role"] == "user"


def test_groq_strict_schema_and_openrouter_required_provider_parameter():
    captured: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "served-model",
            "choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        })

    schema = {"type": "object", "properties": {
        "answer": {"type": "string"},
        "detail": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
    }}
    transport = httpx.MockTransport(handle)
    groq = GroqProvider(**_provider_kwargs(transport))
    result = asyncio.run(groq.generate_structured(
        [{"role": "user", "content": "return JSON"}], schema=schema, request_id="req-g"
    ))
    assert result is not None and result.model == "served-model"
    strict = captured[-1]["response_format"]["json_schema"]
    assert strict["strict"] is True
    assert strict["schema"]["required"] == ["answer", "detail"]
    assert strict["schema"]["additionalProperties"] is False
    assert strict["schema"]["properties"]["detail"]["required"] == ["ok"]

    router = OpenRouterProvider(**_provider_kwargs(transport))
    asyncio.run(router.generate_structured(
        [{"role": "user", "content": "return JSON"}], schema={"type": "object", "properties": {"answer": {"type": "string"}}}
    ))
    payload = captured[-1]
    assert payload["model"] == "unit-test-model"
    assert payload["provider"] == {"require_parameters": True}
    assert router.capabilities.structured_output_mode == "conditional_provider_parameter_required"


def test_groq_and_openrouter_stream_parsers_retain_tokens_and_usage():
    body = {
        "choices": [{"delta": {"content": "hello"}, "finish_reason": None}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }
    groq = GroqProvider(**_provider_kwargs(httpx.MockTransport(lambda req: httpx.Response(200))))
    event = groq._parse_stream_event(body)[0]
    assert event.text == "hello" and event.input_tokens == 5 and event.output_tokens == 1

    router = OpenRouterProvider(**_provider_kwargs(httpx.MockTransport(lambda req: httpx.Response(200))))
    usage_frame = router._parse_stream_event({"usage": {"prompt_tokens": 6, "completion_tokens": 2}})
    assert usage_frame[0].text == ""
    assert usage_frame[0].input_tokens == 6
    with pytest.raises(ProviderFailure, match="provider_stream_error"):
        router._parse_stream_event({"choices": [{"delta": {}, "finish_reason": "error"}]})


def test_failover_advances_only_after_retryable_failure():
    class FakeProvider:
        def __init__(self, name: str, outcome: Any):
            self.name = name
            self.model = f"{name}-model"
            self.outcome = outcome
            self.calls = 0
            self.capabilities = ProviderCapabilities(streaming=False)
            self.configured = True

        async def generate(self, messages, **kwargs):
            self.calls += 1
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("not used")

        async def call_tools(self, *args, **kwargs):
            raise AssertionError("not used")

        async def stream(self, *args, **kwargs):
            if False:
                yield ProviderStreamEvent()

    primary = FakeProvider("gemini", ProviderFailure("provider_timeout", True))
    fallback = FakeProvider("groq", ProviderGeneration("answer", "groq", "gpt-oss"))
    chain = ProviderFailoverChain([primary, fallback], allow_sensitive_data=True)
    result = asyncio.run(chain.generate([{"role": "user", "content": "hi"}], request_id="r-1"))
    assert result is not None and result.provider == "groq"
    assert primary.calls == 1 and fallback.calls == 1
    assert result.attempts[-1]["provider"] == "groq"

    blocked = FakeProvider("gemini", ProviderFailure("provider_credentials_or_permission", False))
    never = FakeProvider("groq", ProviderGeneration("should-not-run", "groq"))
    with pytest.raises(ProviderFailure, match="provider_credentials_or_permission"):
        asyncio.run(ProviderFailoverChain([blocked, never], allow_sensitive_data=True).generate([]))
    assert never.calls == 0


def test_failover_never_splices_after_provider_stream_emits_text():
    class StreamingProvider:
        def __init__(self, name: str, *, fails_after_text: bool):
            self.name = name
            self.model = name
            self.fails_after_text = fails_after_text
            self.configured = True
            self.capabilities = ProviderCapabilities(streaming=True)
            self.calls = 0

        async def generate(self, *args, **kwargs):
            raise AssertionError("streaming path expected")

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("not used")

        async def call_tools(self, *args, **kwargs):
            raise AssertionError("not used")

        async def stream(self, *args, **kwargs):
            self.calls += 1
            yield ProviderStreamEvent(text="partial")
            if self.fails_after_text:
                raise ProviderFailure("provider_stream_interrupted", False, partial_output=True)
            yield ProviderStreamEvent(text=" complete")

    first = StreamingProvider("gemini", fails_after_text=True)
    second = StreamingProvider("groq", fails_after_text=False)
    chain = ProviderFailoverChain([first, second], allow_sensitive_data=True)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(chain.generate([{"role": "user", "content": "hi"}], request_id="r-2"))
    assert caught.value.partial_output
    assert first.calls == 1 and second.calls == 0


def test_provider_status_reports_unverified_configuration_without_secrets():
    statuses = get_provider_statuses()
    assert [row["name"] for row in statuses[:3]] == ["gemini", "groq", "openrouter"]
    assert statuses[0]["model"] == "gemini-3.6-flash"
    assert statuses[1]["model"] == "openai/gpt-oss-120b"
    assert statuses[2]["model"] == "nvidia/nemotron-3.5-super-vl:free"
    serialized = json.dumps(statuses)
    assert "unit-test-key" not in serialized
    assert "api_key" not in serialized

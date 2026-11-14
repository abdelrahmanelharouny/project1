"""Deterministic, network-free tests for provider reliability boundaries."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest

from app.intelligence.config import ai_settings
from app.intelligence.orchestration.provider import ProviderCapabilities, ProviderGeneration, ProviderStreamEvent
from app.intelligence.orchestration.provider_adapters import (
    GeminiProvider,
    GroqProvider,
    ProviderFailoverChain,
    ProviderFailure,
)


MESSAGES = [{"role": "user", "content": "hello"}]


def _run_bounded(awaitable: Any, timeout_seconds: float = 5.0) -> Any:
    async def bounded() -> Any:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)

    return asyncio.run(bounded())


def _kwargs(
    transport: httpx.AsyncBaseTransport,
    **overrides: Any,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "api_key": "unit-test-key",
        "model": "unit-test-model",
        "timeout_seconds": 2,
        "connect_timeout_seconds": 1,
        "max_retries": 0,
        "max_concurrent": 1,
        "circuit_threshold": 1,
        "circuit_recovery_seconds": 1,
        "max_backoff_seconds": 0,
        "client_factory": lambda timeout: httpx.AsyncClient(transport=transport, timeout=timeout),
    }
    values.update(overrides)
    return values


def _body_response(body: dict[str, Any], *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_direct_adapter_import_has_no_registry_cycle():
    project = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = project
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.intelligence.orchestration.provider_adapters import GeminiProvider; "
            "from app.intelligence.orchestration.provider import provider_registry; "
            "assert GeminiProvider.__name__ == 'GeminiProvider'; "
            "assert provider_registry.get('gemini').name == 'gemini'",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_gemini_ignores_thoughts_and_uses_a_complete_candidate_without_trimming():
    provider = GeminiProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(200))))
    result = provider._parse_response({
        "candidates": [
            {
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": "incomplete"}]},
            },
            {
                "finishReason": "STOP",
                "content": {"parts": [
                    {"text": "internal reasoning", "thought": True},
                    {"text": "  grounded answer\n"},
                ]},
            },
        ],
        "usageMetadata": {
            "promptTokenCount": 9,
            "candidatesTokenCount": 7,
            "thoughtsTokenCount": 3,
        },
    })
    assert result.content == "  grounded answer\n"
    assert result.input_tokens == 9 and result.output_tokens == 7


def test_gemini_safety_and_nonterminal_finish_reasons_fail_closed():
    provider = GeminiProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(200))))
    safety = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    with pytest.raises(ProviderFailure, match="provider_safety_block"):
        provider._parse_response(safety)
    blocked_prompt = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
    with pytest.raises(ProviderFailure, match="provider_safety_block"):
        provider._parse_response(blocked_prompt)
    truncated = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "x"}]}}]}
    with pytest.raises(ProviderFailure, match="provider_output_truncated"):
        provider._parse_response(truncated)


def test_gemini_stream_ignores_thought_parts_and_inspects_finish_reason():
    provider = GeminiProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(200))))
    events = provider._parse_stream_event({
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [
                {"text": "do not expose", "thought": True},
                {"text": " visible "},
            ]},
        }],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
    })
    assert [event.text for event in events] == [" visible "]
    assert events[0].input_tokens == 3
    with pytest.raises(ProviderFailure, match="provider_safety_block"):
        provider._parse_stream_event({
            "candidates": [{"finishReason": "RECITATION", "content": {"parts": []}}]
        })


def test_sse_stream_preserves_content_whitespace_end_to_end():
    stream_body = (
        'data: {"choices":[{"delta":{"content":" hello "},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: [DONE]\n\n'
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200,
        content=stream_body.encode(),
        headers={"content-type": "text/event-stream"},
    ))
    provider = GroqProvider(**_kwargs(transport))

    async def collect() -> list[ProviderStreamEvent]:
        return [event async for event in provider.stream(MESSAGES)]

    events = _run_bounded(collect())
    assert events[0].text == " hello "


def test_sse_frame_and_total_output_limits_are_enforced():
    huge_frame = 'data: {"choices":[{"delta":{"content":"' + ("x" * 100) + '"}}]}\n\n'
    frame_provider = GroqProvider(**_kwargs(
        httpx.MockTransport(lambda request: httpx.Response(
            200, content=huge_frame.encode(), headers={"content-type": "text/event-stream"}
        )),
        max_stream_frame_bytes=64,
    ))

    async def drain(provider: GroqProvider) -> None:
        async for _ in provider.stream(MESSAGES):
            pass

    with pytest.raises(ProviderFailure, match="provider_stream_frame_too_large"):
        _run_bounded(drain(frame_provider))

    output_body = (
        'data: {"choices":[{"delta":{"content":"ab"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"cd"},"finish_reason":null}]}\n\n'
    )
    output_provider = GroqProvider(**_kwargs(
        httpx.MockTransport(lambda request: httpx.Response(
            200, content=output_body.encode(), headers={"content-type": "text/event-stream"}
        )),
        max_output_chars=3,
    ))
    with pytest.raises(ProviderFailure, match="provider_stream_interrupted") as caught:
        _run_bounded(drain(output_provider))
    assert caught.value.partial_output


def test_structured_generation_checks_nested_schema_locally():
    response = {"choices": [{
        "message": {"content": '{"answer":"ok","details":{"count":2}}'},
        "finish_reason": "stop",
    }]}
    provider = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: _body_response(response))))
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "minLength": 2},
            "details": {
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1}},
                "required": ["count"],
                "additionalProperties": False,
            },
        },
        "required": ["answer", "details"],
        "additionalProperties": False,
    }
    result = _run_bounded(provider.generate_structured(MESSAGES, schema=schema))
    assert result is not None
    assert json.loads(result.content)["details"]["count"] == 2

    invalid_response = {"choices": [{
        "message": {"content": '{"answer":"x","details":{"count":0,"extra":true}}'},
        "finish_reason": "stop",
    }]}
    invalid_provider = GroqProvider(**_kwargs(
        httpx.MockTransport(lambda request: _body_response(invalid_response))
    ))
    with pytest.raises(ProviderFailure, match="provider_structured_output_schema_mismatch"):
        _run_bounded(invalid_provider.generate_structured(MESSAGES, schema=schema))


def test_safe_request_id_is_bounded_to_header_safe_characters():
    provider = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(200))))
    assert "X-Client-Request-Id" not in provider._headers("bad\r\nheader")
    assert provider._headers("req-12.abc")["X-Client-Request-Id"] == "req-12.abc"
    assert "X-Client-Request-Id" not in provider._headers("é" * 10)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422, 501])
def test_invalid_auth_and_application_statuses_do_not_fail_over(status: int):
    primary = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(status))))

    class Backup:
        name = "backup"
        model = "backup-model"
        configured = True
        capabilities = ProviderCapabilities(streaming=False)
        calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            return ProviderGeneration("should not run", self.name)

        async def stream(self, *args, **kwargs):
            if False:
                yield ProviderStreamEvent()

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("not used")

        async def call_tools(self, *args, **kwargs):
            raise AssertionError("not used")

    backup = Backup()
    chain = ProviderFailoverChain([primary, backup], allow_sensitive_data=True, prefer_streaming=False)
    with pytest.raises(ProviderFailure) as caught:
        _run_bounded(chain.generate(MESSAGES))
    assert not caught.value.retryable
    assert backup.calls == 0


def test_half_open_probe_is_released_after_nonretryable_json_and_stream_errors():
    for provider, stream in (
        (GroqProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(401)))), False),
        (GroqProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(401)))), True),
    ):
        provider._circuit._opened_until = time.monotonic() - 1
        provider._circuit._probe_in_flight = False
        if stream:
            async def call_stream() -> None:
                async for _ in provider.stream(MESSAGES):
                    pass
            with pytest.raises(ProviderFailure):
                _run_bounded(call_stream())
        else:
            with pytest.raises(ProviderFailure):
                _run_bounded(provider.generate(MESSAGES))
        assert provider._circuit._probe_in_flight is False
        assert provider._circuit.acquire() is True
        provider._circuit.release()


@pytest.mark.parametrize("stream", [False, True])
def test_half_open_probe_is_released_when_retry_backoff_is_cancelled(stream: bool):
    async def run_cancelled() -> None:
        entered_backoff = asyncio.Event()

        async def hold(delay: float) -> None:
            entered_backoff.set()
            await asyncio.Event().wait()

        provider = GroqProvider(**_kwargs(
            httpx.MockTransport(lambda request: httpx.Response(503)),
            max_retries=1,
            max_backoff_seconds=0.1,
            sleep=hold,
        ))
        provider._circuit._opened_until = time.monotonic() - 1
        provider._circuit._probe_in_flight = False

        async def request() -> None:
            if stream:
                async for _ in provider.stream(MESSAGES):
                    pass
            else:
                await provider.generate(MESSAGES)

        task = asyncio.create_task(request())
        await asyncio.wait_for(entered_backoff.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider._circuit._probe_in_flight is False
        assert provider._circuit.acquire() is True
        provider._circuit.release()

    _run_bounded(run_cancelled())


def test_chain_timeout_is_end_to_end_and_retry_telemetry_is_request_local():
    class Slow:
        name = "gemini"
        model = "gemini-model"
        configured = True
        capabilities = ProviderCapabilities(streaming=False)
        calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.1)
            return ProviderGeneration("late", self.name)

        async def stream(self, *args, **kwargs):
            if False:
                yield ProviderStreamEvent()

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("not used")

        async def call_tools(self, *args, **kwargs):
            raise AssertionError("not used")

    class Never:
        name = "groq"
        model = "groq-model"
        configured = True
        capabilities = ProviderCapabilities(streaming=False)
        calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            return ProviderGeneration("unexpected", self.name)

        async def stream(self, *args, **kwargs):
            if False:
                yield ProviderStreamEvent()

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("not used")

        async def call_tools(self, *args, **kwargs):
            raise AssertionError("not used")

    slow, never = Slow(), Never()
    chain = ProviderFailoverChain(
        [slow, never], allow_sensitive_data=True, prefer_streaming=False,
        chain_timeout_seconds=0.01,
    )
    assert _run_bounded(chain.generate(MESSAGES)) is None
    assert slow.calls == 1 and never.calls == 0
    assert chain.last_attempts[-1]["error_category"] == "provider_chain_timeout"
    assert len(chain.last_attempts) <= 12

    responses = iter((503, 200, 503, 200))

    def handle(request: httpx.Request) -> httpx.Response:
        status = next(responses)
        if status == 503:
            return httpx.Response(status)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]
        })

    primary = GroqProvider(**_kwargs(httpx.MockTransport(handle), max_retries=1))
    success_chain = ProviderFailoverChain([primary], allow_sensitive_data=True, prefer_streaming=False)
    first_result = _run_bounded(success_chain.generate(MESSAGES))
    assert first_result is not None
    first_attempts = list(success_chain.last_attempts)
    second_result = _run_bounded(success_chain.generate(MESSAGES))
    assert second_result is not None
    assert success_chain.last_attempts is not first_attempts
    assert len(first_attempts) == len(success_chain.last_attempts) == 2
    assert [item["status"] for item in first_attempts] == ["failed", "succeeded"]
    assert "prompt" not in json.dumps(success_chain.last_attempts)


def test_llm_enabled_disables_provider_chain_and_reports_disabled_status(monkeypatch):
    from app.intelligence.orchestration.provider_adapters import get_provider_chain, get_provider_statuses

    monkeypatch.setattr(ai_settings, "llm_enabled", False)
    chain = get_provider_chain(field_sensitive=False)
    assert not chain.configured
    assert _run_bounded(chain.generate(MESSAGES)) is None
    statuses = get_provider_statuses()
    assert statuses
    assert all(row["status"] == "disabled_by_configuration" for row in statuses)



def test_nonstream_response_body_is_bounded_before_json_decode():
    provider = GroqProvider(**_kwargs(
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"{" + b"x" * 10_000)),
        max_response_bytes=32,
    ))
    with pytest.raises(ProviderFailure, match="provider_response_too_large"):
        _run_bounded(provider.generate(MESSAGES))


def test_sse_reader_stops_at_oversized_unterminated_frame():
    class ChunkedBody(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.chunks_read = 0

        async def __aiter__(self):
            self.chunks_read += 1
            yield b"data: " + b"x" * 1000
            self.chunks_read += 1
            yield b"\ndata: [DONE]\n"

        async def aclose(self) -> None:
            return None

    body = ChunkedBody()
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, stream=body, headers={"content-type": "text/event-stream"}
    ))
    provider = GroqProvider(**_kwargs(transport, max_stream_frame_bytes=64))

    async def drain() -> None:
        async for _ in provider.stream(MESSAGES):
            pass

    with pytest.raises(ProviderFailure, match="provider_stream_frame_too_large"):
        _run_bounded(drain())
    assert body.chunks_read == 1


def test_sse_eof_without_terminal_marker_is_not_a_success():
    stream_body = 'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
    provider = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: httpx.Response(
        200, content=stream_body.encode(), headers={"content-type": "text/event-stream"}
    ))))

    async def drain() -> None:
        async for _ in provider.stream(MESSAGES):
            pass

    with pytest.raises(ProviderFailure, match="provider_stream_interrupted") as caught:
        _run_bounded(drain())
    assert caught.value.partial_output
    assert provider.circuit_status == "open"


def test_unsupported_schema_keyword_fails_closed_before_provider_call():
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    provider = GroqProvider(**_kwargs(httpx.MockTransport(handle)))
    schema = {"type": "object", "properties": {"date": {"type": "string", "format": "date"}}}
    with pytest.raises(ProviderFailure, match="provider_schema_unsupported_or_invalid"):
        _run_bounded(provider.generate_structured(MESSAGES, schema=schema))
    assert requests == []


def test_structured_output_rejects_nonstandard_nan_constant():
    response = {"choices": [{"message": {"content": "NaN"}, "finish_reason": "stop"}]}
    provider = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: _body_response(response))))
    with pytest.raises(ProviderFailure, match="provider_structured_output_invalid_json"):
        _run_bounded(provider.generate_structured(MESSAGES, schema={"type": "number"}))


@pytest.mark.parametrize(
    ("content", "schema", "expected_category"),
    [
        ("1", {"const": True}, "provider_structured_output_schema_mismatch"),
        ('{"answer":"safe","answer":2}', {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }, "provider_structured_output_invalid_json"),
    ],
)
def test_structured_json_rejects_python_equality_and_duplicate_key_traps(
    content: str, schema: dict[str, Any], expected_category: str
):
    response = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    provider = GroqProvider(**_kwargs(httpx.MockTransport(lambda request: _body_response(response))))
    with pytest.raises(ProviderFailure, match=expected_category):
        _run_bounded(provider.generate_structured(MESSAGES, schema=schema))

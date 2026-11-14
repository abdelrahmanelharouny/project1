"""Provider-neutral contracts and registry for CropTwist AI.

The legacy bridge remains available as an explicit compatibility adapter,
but the configured default order is Gemini, Groq, then OpenRouter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, AsyncIterator, Protocol


class ProviderCapabilityUnavailable(RuntimeError):
    """Raised when an adapter does not implement a requested mode."""


@dataclass(frozen=True)
class ProviderCapabilities:
    text_generation: bool = True
    native_structured_output: bool = False
    tool_calling: bool = False
    streaming: bool = False
    token_usage_reporting: bool = False
    structured_output_mode: str = "unsupported"
    privacy_note: str | None = None


@dataclass(frozen=True)
class ProviderStreamEvent:
    """A normalized event from a provider's streaming response."""

    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class ProviderGeneration:
    content: str
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provider_latency_ms: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def as_legacy_detail(self) -> dict[str, Any]:
        """Bridge-compatible detail for existing advisor validation code."""
        result: dict[str, Any] = {"content": self.content, "provider": self.provider}
        if self.model:
            result["model"] = self.model
        if self.input_tokens is not None:
            result["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            result["output_tokens"] = self.output_tokens
        if self.attempts:
            result["provider_attempts"] = list(self.attempts)
        if self.provider_latency_ms is not None:
            result["provider_latency_ms"] = self.provider_latency_ms
        return result


class LLMProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    @property
    def configured(self) -> bool: ...

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None: ...

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None: ...

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None: ...

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]: ...


class LegacyBridgeProvider:
    """Delegates transport/auth/timeouts/circuit breaking to the old bridge."""

    name = "legacy-llm-bridge"
    capabilities = ProviderCapabilities(
        text_generation=True,
        native_structured_output=False,
        tool_calling=False,
        streaming=False,
        token_usage_reporting=False,
        structured_output_mode="unsupported",
    )

    @property
    def configured(self) -> bool:
        from app.intelligence.config import ai_settings

        return ai_settings.llm_enabled

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> ProviderGeneration | None:
        from app.intelligence.bridge import achat_detail

        detail = await achat_detail(messages, temperature=temperature, max_tokens=max_tokens)
        if detail is None:
            return None
        content = detail.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        model = detail.get("model")
        input_tokens = detail.get("input_tokens")
        output_tokens = detail.get("output_tokens")
        return ProviderGeneration(
            content=content,
            provider=self.name,
            model=model[:100] if isinstance(model, str) and model else None,
            input_tokens=input_tokens
            if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) and input_tokens >= 0
            else None,
            output_tokens=output_tokens
            if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0
            else None,
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
        raise ProviderCapabilityUnavailable(
            "The current bridge has no native JSON-schema structured-output mode."
        )

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None:
        raise ProviderCapabilityUnavailable(
            "Model tool calling is not used; server-side tools are selected by the deterministic planner."
        )

    async def _unsupported_stream(self) -> AsyncIterator[ProviderStreamEvent]:
        raise ProviderCapabilityUnavailable("The current bridge does not support streaming.")
        yield ProviderStreamEvent()  # pragma: no cover - makes this an async iterator

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        return self._unsupported_stream()


class ProviderRegistry:
    """Explicit adapter registry; provider selection is performed separately."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        if not provider.name or provider.name in self._providers:
            raise ValueError(f"provider already registered or invalid: {provider.name!r}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider:
        if self is provider_registry and name in _DEFAULT_PROVIDER_NAMES:
            _register_default_providers()
        try:
            return self._providers[name]
        except KeyError as exc:
            raise LookupError(f"LLM provider is not registered: {name}") from exc

    def list(self) -> list[LLMProvider]:
        return [self._providers[name] for name in sorted(self._providers)]


provider_registry = ProviderRegistry()
provider_registry.register(LegacyBridgeProvider())

_DEFAULT_PROVIDER_NAMES = frozenset({"gemini", "groq", "openrouter"})
_DEFAULT_PROVIDER_LOCK = Lock()
_DEFAULT_PROVIDERS_LOADED = False


def _register_default_providers() -> None:
    """Load HTTP adapters only on first registry lookup, without import cycles."""
    global _DEFAULT_PROVIDERS_LOADED
    if _DEFAULT_PROVIDERS_LOADED:
        return
    with _DEFAULT_PROVIDER_LOCK:
        if _DEFAULT_PROVIDERS_LOADED:
            return
        # provider_adapters imports the contracts above; it intentionally does
        # not import the registry back at module scope.
        from app.intelligence.orchestration.provider_adapters import register_default_providers

        register_default_providers(provider_registry)
        _DEFAULT_PROVIDERS_LOADED = True

"""Provider-neutral LLM interfaces; the legacy bridge remains the adapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


class ProviderCapabilityUnavailable(RuntimeError):
    """Raised when an adapter does not actually implement a requested mode."""


@dataclass(frozen=True)
class ProviderCapabilities:
    text_generation: bool = True
    native_structured_output: bool = False
    tool_calling: bool = False
    streaming: bool = False
    token_usage_reporting: bool = False


@dataclass(frozen=True)
class ProviderGeneration:
    content: str
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

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
        return result


class LLMProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderGeneration | None: ...

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderGeneration | None: ...

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None: ...

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class LegacyBridgeProvider:
    """Delegates transport/auth/timeouts/circuit breaking to the existing bridge."""

    name = "legacy-llm-bridge"
    capabilities = ProviderCapabilities(
        text_generation=True,
        native_structured_output=False,
        tool_calling=False,
        streaming=False,
        token_usage_reporting=False,
    )

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderGeneration | None:
        from app.intelligence.bridge import achat_detail

        detail = await achat_detail(messages, temperature=temperature, max_tokens=max_tokens)
        if detail is None:
            return None
        content = detail.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        model = detail.get("model")
        return ProviderGeneration(
            content=content,
            provider=self.name,
            model=model[:100] if isinstance(model, str) and model else None,
            input_tokens=detail.get("input_tokens")
            if isinstance(detail.get("input_tokens"), int) and not isinstance(detail.get("input_tokens"), bool) and detail["input_tokens"] >= 0
            else None,
            output_tokens=detail.get("output_tokens")
            if isinstance(detail.get("output_tokens"), int) and not isinstance(detail.get("output_tokens"), bool) and detail["output_tokens"] >= 0
            else None,
        )

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderGeneration | None:
        raise ProviderCapabilityUnavailable(
            "The current bridge has no native JSON-schema structured-output mode."
        )

    async def call_tools(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]]
    ) -> ProviderGeneration | None:
        raise ProviderCapabilityUnavailable(
            "The current bridge does not expose model tool calling; server-side tools are selected by the deterministic planner."
        )

    async def _unsupported_stream(self) -> AsyncIterator[str]:
        raise ProviderCapabilityUnavailable("The current bridge does not support streaming.")
        yield ""  # pragma: no cover - makes this function an async iterator

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        return self._unsupported_stream()


class ProviderRegistry:
    """Explicit provider registry; selection policy/fallback remains future work."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        if not provider.name or provider.name in self._providers:
            raise ValueError(f"provider already registered or invalid: {provider.name!r}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise LookupError(f"LLM provider is not registered: {name}") from exc

    def list(self) -> list[LLMProvider]:
        return [self._providers[name] for name in sorted(self._providers)]


provider_registry = ProviderRegistry()
provider_registry.register(LegacyBridgeProvider())

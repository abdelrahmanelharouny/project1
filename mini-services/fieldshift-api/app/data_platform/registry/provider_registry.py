"""Provider registry/factory keyed by provider_code (Master §12).

Only the synthetic provider is registered in this slice. NASA/Open-Meteo/
CHIRPS/SoilGrids adapters are future milestones; they will register here
without changing business logic (Master rule 8).
"""

from typing import Any

from app.core.errors import NotFound
from app.data_platform.providers.synthetic.provider import SyntheticProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def register(
        self, provider: Any, *, kind: str, status: str = "active", details: dict[str, Any] | None = None
    ) -> None:
        code = provider.provider_code
        self._providers[code] = provider
        self._metadata[code] = {
            "provider_code": code,
            "kind": kind,  # synthetic | api | file_import | raster
            "status": status,
            "details": details or {},
        }

    def get(self, provider_code: str) -> Any:
        provider = self._providers.get(provider_code)
        if provider is None:
            raise NotFound(
                f"Provider '{provider_code}' is not registered.",
                details=[{
                    "field": "provider_code",
                    "reason": f"available providers: {', '.join(sorted(self._providers))}",
                }],
            )
        return provider

    def health(self) -> list[dict[str, Any]]:
        return [dict(m) for _, m in sorted(self._metadata.items())]

    def codes(self) -> list[str]:
        return sorted(self._providers.keys())


_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        registry = ProviderRegistry()
        synthetic = SyntheticProvider()
        registry.register(
            synthetic,
            kind="synthetic",
            status="active",
            details={
                "profiles": synthetic.profiles(),
                "is_synthetic": True,
                "note": "Software fixture for tests and demos. Never real-world data.",
            },
        )
        _registry = registry
    return _registry

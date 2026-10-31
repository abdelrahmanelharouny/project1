"""Provider registry/factory keyed by provider_code (Master §12).

Registered in Milestone 3:
- synthetic      — deterministic fixture provider (always available)
- open_meteo     — REAL archive API (ERA5-Land / ERA5)
- chirps_import  — file import + raster extraction workflow (needs rasterio)
- soilgrids      — optional WCS provider with graceful degradation
- farmer_csv     — controlled CSV import pipeline

Each provider can carry a `probe` callable for the health view. Probes are
best-effort, short-timeout and cached; they never raise and never block
ingestion of other providers.
"""

import threading
import time
from typing import Any, Callable

from app.core.config import settings
from app.core.errors import NotFound
from app.data_platform.providers.chirps.registry_info import (
    PROVIDER_CODE as CHIRPS_CODE,
    PROVIDER_NAME as CHIRPS_NAME,
    documented_limitations as chirps_limitations,
    stub_fetch_message as chirps_stub_message,
)
from app.data_platform.providers.open_meteo.provider import OpenMeteoProvider, health_probe as om_probe
from app.data_platform.providers.soilgrids.provider import SoilGridsProvider, health_probe as sg_probe
from app.data_platform.providers.synthetic.provider import SyntheticProvider


class _ChirpsImportStub:
    """Registry handle for the file-import workflow (fetch is not meaningful)."""

    provider_code = CHIRPS_CODE

    def supported_variables(self) -> list[str]:
        return ["precipitation"]

    def fetch_observations(self, **_kwargs) -> None:
        raise NotFound(chirps_stub_message())


class _FarmerCsvStub:
    """Registry handle for the CSV import workflow (fetch happens via upload)."""

    provider_code = "farmer_csv"

    def supported_variables(self) -> list[str]:
        return sorted(
            v
            for v in (
                "precipitation",
                "air_temperature_mean",
                "air_temperature_min",
                "air_temperature_max",
                "reference_et0",
                "soil_moisture_surface",
                "wind_speed_2m",
                "wind_speed_10m",
            )
        )

    def fetch_observations(self, **_kwargs) -> None:
        from app.core.errors import NotFound

        raise NotFound(
            "Farmer CSV import is an upload workflow: POST the CSV to "
            "/fields/{field_id}/imports/observations-csv."
        )


def _rasterio_available() -> bool:
    try:
        import rasterio  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._probes: dict[str, Callable[[], dict[str, Any]]] = {}
        self._probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        provider: Any,
        *,
        kind: str,
        status: str = "active",
        details: dict[str, Any] | None = None,
        probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        code = provider.provider_code
        detail_copy = dict(details or {})
        # Uniform variable-availability metadata for every provider (UI + fail fast).
        if "supported_variables" not in detail_copy and hasattr(provider, "supported_variables"):
            detail_copy["supported_variables"] = provider.supported_variables()
        self._providers[code] = provider
        self._metadata[code] = {
            "provider_code": code,
            "kind": kind,  # synthetic | api | api_wcs | raster_import | file_import
            "status": status,
            "details": detail_copy,
        }
        if probe is not None:
            self._probes[code] = probe

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

    def _run_probe(self, code: str) -> dict[str, Any]:
        probe = self._probes.get(code)
        if probe is None:
            return {}
        now = time.monotonic()
        with self._lock:
            cached = self._probe_cache.get(code)
            if cached and now - cached[0] < settings.provider_probe_cache_seconds:
                return cached[1]
        try:
            result = probe()
        except Exception as exc:  # noqa: BLE001 — probes must never raise
            result = {"status": "unreachable", "detail": f"{type(exc).__name__}"}
        with self._lock:
            self._probe_cache[code] = (time.monotonic(), result)
        return result

    def health(self, *, with_probes: bool = True) -> list[dict[str, Any]]:
        entries = [dict(m) for _, m in sorted(self._metadata.items())]
        if with_probes:
            for entry in entries:
                probe_result = self._run_probe(entry["provider_code"])
                if probe_result:
                    entry["probe"] = probe_result
        return entries

    def supported_variables(self, provider_code: str) -> list[str]:
        provider = self.get(provider_code)
        if hasattr(provider, "supported_variables"):
            return provider.supported_variables()
        return []

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

        open_meteo = OpenMeteoProvider()
        registry.register(
            open_meteo,
            kind="api",
            status="active",
            details={
                "models": open_meteo.models(),
                "default_model": "era5_land",
                "is_synthetic": False,
                "note": "Real historical reanalysis archive. Gridded estimates, not field sensors.",
            },
            probe=om_probe,
        )

        rasterio_ok = _rasterio_available()
        registry.register(
            _ChirpsImportStub(),
            kind="raster_import",
            status="active" if rasterio_ok else "degraded",
            details={
                "is_synthetic": False,
                "workflow": "POST /fields/{field_id}/chirps-extractions (GeoTIFF upload)",
                "rasterio_available": rasterio_ok,
                "known_limitations": chirps_limitations(),
                **({} if rasterio_ok else {"degradation_reason": "rasterio is not installed"}),
            },
        )

        registry.register(
            SoilGridsProvider(),
            kind="api_wcs",
            status="optional",
            details={
                "is_synthetic": False,
                "depth": "0-5cm",
                "note": (
                    "Optional global soil-property predictions with graceful degradation; "
                    "never a substitute for lab analysis."
                ),
            },
            probe=sg_probe,
        )

        registry.register(
            _FarmerCsvStub(),
            kind="file_import",
            status="active",
            details={
                "is_synthetic": False,
                "workflow": "POST /fields/{field_id}/imports/observations-csv",
                "evidence_class": "farmer_reported_record",
            },
        )

        _registry = registry
    return _registry

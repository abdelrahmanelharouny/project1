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
from app.data_platform.providers.nasa_hls.provider import NasaHlsProvider
from app.data_platform.providers.nasa_hls.registry_info import (
    KNOWN_LIMITATIONS as NASA_HLS_LIMITATIONS,
    PROVIDER_CODE as NASA_HLS_CODE,
)
from app.data_platform.providers.open_meteo.provider import OpenMeteoProvider, health_probe as om_probe
from app.data_platform.providers.open_meteo_forecast.provider import OpenMeteoForecastProvider
from app.data_platform.providers.satellite_sim.provider import SatelliteSimProvider
from app.data_platform.providers.sentinel2.provider import Sentinel2StacProvider
from app.data_platform.providers.soilgrids.provider import SoilGridsProvider, health_probe as sg_probe
from app.data_platform.providers.synthetic.provider import SyntheticProvider


def _sentinel2_probe() -> dict[str, Any]:
    """Best-effort STAC reachability probe (never raises, never blocks)."""
    import httpx

    from app.core.config import settings as s

    started = time.time()
    try:
        response = httpx.get(
            s.sentinel2_stac_base_url.rstrip("/"),
            timeout=s.provider_probe_timeout_seconds,
        )
        latency = int((time.time() - started) * 1000)
        if response.status_code < 500:
            return {"status": "ok", "latency_ms": latency, "detail": f"STAC responded HTTP {response.status_code}"}
        return {"status": "degraded", "latency_ms": latency, "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unreachable",
            "latency_ms": int((time.time() - started) * 1000),
            "detail": f"external network unavailable: {exc}",
        }


def _nasa_hls_probe() -> dict[str, Any]:
    """Best-effort CMR STAC reachability probe (never raises, never blocks).

    CMR STAC discovery is unauthenticated by design, so the probe can verify
    catalog reachability without Earthdata credentials; it says nothing about
    authenticated asset-download availability.
    """
    import httpx

    from app.core.config import settings as s

    started = time.time()
    try:
        response = httpx.get(
            s.nasa_hls_stac_base_url.rstrip("/"),
            timeout=s.provider_probe_timeout_seconds,
        )
        latency = int((time.time() - started) * 1000)
        if response.status_code < 500:
            return {"status": "ok", "latency_ms": latency, "detail": f"CMR STAC responded HTTP {response.status_code}"}
        return {"status": "degraded", "latency_ms": latency, "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unreachable",
            "latency_ms": int((time.time() - started) * 1000),
            "detail": f"external network unavailable: {exc}",
        }


def _forecast_probe() -> dict[str, Any]:
    """Best-effort forecast API probe (1-day request)."""
    import httpx

    from app.core.config import settings as s

    started = time.time()
    try:
        response = httpx.get(
            s.open_meteo_forecast_base_url,
            params={
                "latitude": 31.05,
                "longitude": 31.1,
                "daily": "temperature_2m_max",
                "forecast_days": 1,
                "timezone": "UTC",
            },
            timeout=s.provider_probe_timeout_seconds,
        )
        latency = int((time.time() - started) * 1000)
        if response.status_code == 200 and not response.json().get("error"):
            return {"status": "ok", "latency_ms": latency, "detail": "forecast API responded"}
        return {"status": "degraded", "latency_ms": latency, "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unreachable",
            "latency_ms": int((time.time() - started) * 1000),
            "detail": f"external network unavailable: {exc}",
        }


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

        # ------------------------------------------------ P2.A satellite
        sim = SatelliteSimProvider()
        registry.register(
            sim,
            kind="synthetic",
            status="active",
            details={
                "profiles": sim.profiles(),
                "is_synthetic": True,
                "variables": sim.supported_variables(),
                "note": (
                    "Synthetic satellite scene fixture for tests/demos. "
                    "Never real-world data."
                ),
            },
        )

        s2 = Sentinel2StacProvider()
        registry.register(
            s2,
            kind="api_stac",
            status="optional",
            details={
                "collections": s2.collections(),
                "variables": s2.supported_variables(),
                "is_synthetic": False,
                "note": (
                    "Sentinel-2 L2A via STAC (Copernicus Data Space). "
                    "Requires external network; CDSE credentials optional "
                    "for asset reads. Live availability BLOCKED in this "
                    "sandbox deployment."
                ),
            },
            probe=_sentinel2_probe,
        )

        # ------------------------------------------------ P04 NASA HLS
        # Real NASA satellite acquisition: CMR STAC discovery (public) +
        # LP DAAC asset reads via /vsicurl/ (Earthdata Login required).
        nasa_hls = NasaHlsProvider()
        registry.register(
            nasa_hls,
            kind="api_stac",
            status="optional",
            details={
                "collections": nasa_hls.collections(),
                "variables": nasa_hls.supported_variables(),
                "is_synthetic": False,
                "workflow": (
                    "POST /fields/{field_id}/satellite/discovery -> "
                    "POST /fields/{field_id}/satellite/acquisitions"
                ),
                "known_limitations": NASA_HLS_LIMITATIONS,
                "earthdata_credentials_configured": bool(
                    settings.earthdata_bearer_token
                    or (settings.earthdata_username and settings.earthdata_password)
                ),
                "note": (
                    "NASA HLS (Landsat+Sentinel-2 harmonized SR, 30 m) via "
                    "CMR STAC + LP DAAC COGs. Catalog discovery is public; "
                    "asset reads need NASA Earthdata Login credentials "
                    "(env-injected). Status 'optional': the adapter and "
                    "tests run fully mocked; live use needs connectivity + "
                    "credentials only."
                ),
            },
            probe=_nasa_hls_probe,
        )

        # ------------------------------------------------ P2.B forecast
        omf = OpenMeteoForecastProvider()
        registry.register(
            omf,
            kind="api_forecast",
            status="optional",
            details={
                "models": omf.models(),
                "variables": omf.supported_variables(),
                "forecast_class": "short_range_forecast",
                "is_synthetic": False,
                "note": (
                    "Short-range deterministic forecast (<=16 days). Stored in "
                    "weather_forecasts with issue/valid separation; never "
                    "blended into observations."
                ),
            },
            probe=_forecast_probe,
        )

        _registry = registry
    return _registry

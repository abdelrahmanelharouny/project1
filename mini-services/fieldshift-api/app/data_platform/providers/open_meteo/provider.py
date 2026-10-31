"""Open-Meteo Historical Weather API provider (Master §11.1-A, Milestone 3).

The first REAL environmental source. Requests the explicit historical archive
product — default ERA5-Land, optionally ERA5 — never a silently changing
"best_match" series, because multi-decadal climate trend analysis requires a
consistent reanalysis product (Master rule: explicit product selection).

Honesty properties:
- Gridded reanalysis estimate (evidence class `reanalysis_model_estimate`),
  NEVER presented as a field sensor observation.
- Timezone basis is UTC for every value; the API's native offset (always 0
  here) and the request basis are recorded per observation.
- Null values in the upstream payload become `quality_status="missing"`
  observations with an OPENMETEO_NULL flag — never fabricated zeros (rule 11).
- Unit conversions are explicit and recorded in observation metadata.
- Model name, grid cell, elevation, native variable names, request chunk and
  retrieval window are stored in provenance/metadata (Master §11.1-A).
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.core.config import settings
from app.core.errors import InvalidDateRange, ProviderRequestError, ProviderUnavailable, UnsupportedVariable
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    TimeSupport,
    validate_provider_request,
)
from app.data_platform.contracts.variables import variable_definition

logger = logging.getLogger("fieldshift.providers.open_meteo")

PROVIDER_CODE = "open_meteo"
PROVIDER_NAME = "Open-Meteo Historical Weather API"
PRODUCT_VERSION = "openmeteo-archive-2026.10"
COVERAGE_START = datetime(1940, 1, 1, tzinfo=UTC)

DEFAULT_MODEL = "era5_land"


class ModelDefinition(BaseModel):
    code: str
    open_meteo_model_param: str
    description: str
    spatial_resolution_m: float
    land_only: bool


MODELS: dict[str, ModelDefinition] = {
    "era5_land": ModelDefinition(
        code="era5_land",
        open_meteo_model_param="era5_land",
        description="ERA5-Land reanalysis (~9-11 km grid, land-only, hourly -> daily).",
        spatial_resolution_m=11132.0,
        land_only=True,
    ),
    "era5": ModelDefinition(
        code="era5",
        open_meteo_model_param="era5",
        description="ERA5 reanalysis (~28 km grid, global, hourly -> daily).",
        spatial_resolution_m=27830.0,
        land_only=False,
    ),
}

# Variables each model actually publishes on the archive daily endpoint
# (verified against the live API, 2026-10-30): ERA5-Land publishes temperature
# and surface soil moisture only; derived precipitation/ET0 and wind are
# ERA5-only. The UI and route use this matrix to fail fast with a clear reason.
MODEL_VARIABLES: dict[str, set[str]] = {
    "era5_land": {
        "air_temperature_mean",
        "air_temperature_min",
        "air_temperature_max",
        "soil_moisture_surface",
    },
    "era5": {
        "air_temperature_mean",
        "air_temperature_min",
        "air_temperature_max",
        "precipitation",
        "reference_et0",
        "soil_moisture_surface",
        "wind_speed_10m",
    },
}

# Canonical variable -> (open-meteo daily name, native unit, conversion to catalog unit)
DAILY_VARIABLE_MAP: dict[str, tuple[str, str, Any]] = {
    "air_temperature_mean": ("temperature_2m_mean", "degC", None),
    "air_temperature_min": ("temperature_2m_min", "degC", None),
    "air_temperature_max": ("temperature_2m_max", "degC", None),
    "precipitation": ("precipitation_sum", "mm", None),
    "reference_et0": ("et0_fao_evapotranspiration", "mm", None),
    "soil_moisture_surface": ("soil_moisture_0_to_7cm_mean", "m3/m3", None),
    "wind_speed_10m": ("wind_speed_10m_mean", "km/h", ("div", 3.6)),
}

SUPPORTED_VARIABLES = sorted(DAILY_VARIABLE_MAP.keys())

# The archive API publishes recent days with a delay; be conservative.
ARCHIVE_LAG_DAYS = 6


def _centroid(geom: BaseGeometry) -> tuple[float, float]:
    c = geom.centroid
    return round(float(c.x), 4), round(float(c.y), 4)


def _year_chunks(start: datetime, end: datetime, max_years: int) -> list[tuple[datetime, datetime]]:
    """Split [start, end] into chunks of at most `max_years` calendar-aligned spans."""
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor <= end:
        limit = min(end, datetime(cursor.year + max_years - 1, 12, 31, tzinfo=UTC))
        chunks.append((cursor, limit))
        cursor = limit + timedelta(days=1)
    return chunks


class OpenMeteoProvider:
    """Real Open-Meteo archive client implementing the provider contract."""

    provider_code = PROVIDER_CODE

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base_url = base_url or settings.open_meteo_base_url
        self._timeout = timeout or settings.open_meteo_timeout_seconds
        self._provenance_by_model: dict[str, SourceProvenance] = {
            code: SourceProvenance(
                provider_code=PROVIDER_CODE,
                provider_name=PROVIDER_NAME,
                product_code=code,
                product_version=PRODUCT_VERSION,
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution_text=(
                    "Weather data by Open-Meteo.com (CC BY 4.0), built on "
                    "ERA5 / ERA5-Land reanalysis (Copernicus Climate Change Service / ECMWF)."
                ),
                documentation_url="https://open-meteo.com/en/docs/historical-weather-api",
                known_limitations=(
                    "Gridded reanalysis estimate, not a field sensor observation. "
                    "ERA5-Land is land-only with ~9-11 km effective cells; ERA5 is ~28 km. "
                    "Daily values are aggregates of hourly model output. Suitability for "
                    "daily rainfall extremes is limited by the model grid."
                ),
                retrieval_method="https_archive_api",
            )
            for code in MODELS
        }

    # ------------------------------------------------------------------ api
    def supported_variables(self) -> list[str]:
        return list(SUPPORTED_VARIABLES)

    def models(self) -> list[dict[str, Any]]:
        items = []
        for m in MODELS.values():
            d = m.model_dump()
            d["variables"] = sorted(MODEL_VARIABLES[m.code])
            items.append(d)
        return items

    def validate_request(self, *, variables: list[str], options: dict[str, Any] | None = None) -> None:
        """Fail-fast request check used by the API route (no network)."""
        options = options or {}
        model_code = options.get("model", DEFAULT_MODEL)
        if model_code not in MODELS:
            raise UnsupportedVariable(
                f"Unknown Open-Meteo model '{model_code}'.",
                details=[{"field": "model", "reason": f"choose one of {', '.join(sorted(MODELS))}"}],
            )
        available = [v for v in variables if v in MODEL_VARIABLES[model_code]]
        if variables and not available:
            raise UnsupportedVariable(
                f"Model '{model_code}' does not publish the requested variables.",
                details=[{
                    "field": "variables",
                    "reason": (
                        f"unavailable in {model_code}: {', '.join(sorted(set(variables)))}; "
                        f"available models: {', '.join(sorted(MODELS))}"
                    ),
                }],
            )

    def fetch_observations(
        self,
        *,
        area_of_interest: AreaOfInterest,
        variables: list[str],
        start: datetime,
        end: datetime,
        options: dict[str, Any] | None = None,
    ) -> ProviderFetchResult:
        options = options or {}
        validate_provider_request(variables, start, end)

        model_code = options.get("model", DEFAULT_MODEL)
        if model_code not in MODELS:
            raise UnsupportedVariable(
                f"Unknown Open-Meteo model '{model_code}'.",
                details=[{"field": "model", "reason": f"choose one of {', '.join(sorted(MODELS))}"}],
            )
        model = MODELS[model_code]

        requested = sorted(variables)
        supported = [v for v in requested if v in DAILY_VARIABLE_MAP]
        unsupported = [v for v in requested if v not in DAILY_VARIABLE_MAP]
        if not supported:
            raise UnsupportedVariable(
                "None of the requested variables are provided by the Open-Meteo archive.",
                details=[{"field": "variables", "reason": f"supported: {', '.join(SUPPORTED_VARIABLES)}"}],
            )
        warnings: list[str] = []
        if unsupported:
            warnings.append(
                "Variables not provided by the Open-Meteo archive were skipped: "
                + ", ".join(unsupported)
                + "."
            )
        # Variables the archive provides but the SELECTED MODEL does not publish
        # (e.g. wind is ERA5-only). Fail fast if that is all the user asked for.
        unavailable_in_model = [v for v in supported if v not in MODEL_VARIABLES[model_code]]
        if unavailable_in_model:
            other = next(iter(set(MODELS) - {model_code}), None)
            hint = f" Switch the model option to '{other}'." if other else ""
            warnings.append(
                "Variables not published by model "
                + model_code
                + " were NOT requested (no observations recorded for them): "
                + ", ".join(unavailable_in_model)
                + "."
                + hint
            )
            if len(unavailable_in_model) == len(supported):
                raise UnsupportedVariable(
                    f"Model '{model_code}' does not publish the requested variables.",
                    details=[{
                        "field": "variables",
                        "reason": (
                            f"unavailable in {model_code}: {', '.join(unavailable_in_model)}; "
                            f"available models: {', '.join(sorted(MODELS))}"
                        ),
                    }],
                )
        # Never request variables the selected model does not natively publish.
        # Relying on upstream nulls is fragile: if the archive ever backfills
        # those series from the other reanalysis, values would be ingested under
        # the wrong product label — a silent ERA5/ERA5-Land mix. Dropping them
        # here keeps the product label deterministic.
        fetch_variables = [v for v in supported if v in MODEL_VARIABLES[model_code]]

        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start < COVERAGE_START:
            raise InvalidDateRange(
                "Open-Meteo archive coverage starts 1940-01-01.",
                details=[{"field": "date_range", "reason": f"requested start {start.date()}"}],
            )

        # Clamp end to the archive publication lag.
        latest = datetime.now(UTC) - timedelta(days=ARCHIVE_LAG_DAYS)
        clamped_end = end
        if clamped_end > latest:
            clamped_end = latest
            warnings.append(
                f"Requested end {end.date()} is behind the archive publication lag; "
                f"clamped to {latest.date()}."
            )
        if start > clamped_end:
            raise InvalidDateRange("Start date is after the archive's latest published day.")

        geom = shape(area_of_interest.geometry_geojson)
        lon, lat = _centroid(geom)
        if model.land_only and abs(lat) > 85:
            warnings.append(
                "Field centroid is in a high-latitude area where ERA5-Land coverage is not "
                "guaranteed; values may be missing."
            )

        chunks = _year_chunks(start, clamped_end, settings.open_meteo_max_years_per_request)
        observations: list[CanonicalObservation] = []
        grid_info: dict[str, Any] | None = None

        for chunk_start, chunk_end in chunks:
            payload = self._fetch_chunk(
                lat=lat,
                lon=lon,
                start=chunk_start,
                end=chunk_end,
                model=model.open_meteo_model_param,
                variables=fetch_variables,
            )
            grid_info = {
                "grid_latitude": payload.get("latitude"),
                "grid_longitude": payload.get("longitude"),
                "elevation_m": payload.get("elevation"),
                "timezone_basis": payload.get("timezone", "GMT"),
                "utc_offset_seconds": payload.get("utc_offset_seconds", 0),
            }
            observations.extend(
                self._to_canonical(
                    payload=payload,
                    variables=fetch_variables,
                    model=model,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                )
            )

        warnings.append(
            "These are gridded reanalysis estimates for the field centroid cell, "
            "not measurements taken in the field."
        )

        return ProviderFetchResult(
            provider_code=PROVIDER_CODE,
            provenance=self._provenance_by_model[model_code],
            observations=observations,
            warnings=warnings,
            coverage={
                "requested_start": start.date().isoformat(),
                "requested_end": end.date().isoformat(),
                "effective_end": clamped_end.date().isoformat(),
                "model": model.code,
                "grid": grid_info,
                "chunks": [
                    {"start": s.date().isoformat(), "end": e.date().isoformat()}
                    for s, e in chunks
                ],
                "unsupported_variables_requested": unsupported,
                "variables_not_requested": unavailable_in_model,
            },
            provider_request_id=f"openmeteo:{model.code}:{start.date()}:{clamped_end.date()}:{lat},{lon}",
            raw_reference=self._base_url,
        )

    # -------------------------------------------------------------- internals
    def _fetch_chunk(
        self,
        *,
        lat: float,
        lon: float,
        start: datetime,
        end: datetime,
        model: str,
        variables: list[str],
    ) -> dict[str, Any]:
        daily = sorted({DAILY_VARIABLE_MAP[v][0] for v in variables})
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "daily": ",".join(daily),
            "timezone": "UTC",
            "models": model,
        }
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.get(self._base_url, params=params, timeout=self._timeout)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("open-meteo request failed (attempt %d): %s", attempt + 1, exc)
                self._sleep_backoff(attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_exc = ProviderRequestError(
                    f"Open-Meteo returned HTTP {response.status_code}.",
                    details=[{"field": "upstream", "reason": response.text[:300]}],
                )
                self._sleep_backoff(attempt)
                continue
            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if body.get("error"):
                    raise ProviderRequestError(
                        f"Open-Meteo rejected the request: {body.get('reason', 'unknown reason')}",
                        details=[{"field": "upstream", "reason": str(body)[:300]}],
                    )
                raise ProviderRequestError(
                    f"Open-Meteo returned HTTP {response.status_code}.",
                    details=[{"field": "upstream", "reason": response.text[:300]}],
                )
            body = response.json()
            if body.get("error"):
                raise ProviderRequestError(
                    f"Open-Meteo rejected the request: {body.get('reason', 'unknown reason')}",
                    details=[{"field": "upstream", "reason": str(body)[:300]}],
                )
            return body
        raise ProviderUnavailable(
            "Open-Meteo archive is unreachable after retries.",
            details=[{"field": "upstream", "reason": str(last_exc)}],
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        import time

        time.sleep(min(2.0, 0.4 * (2**attempt)))

    def _to_canonical(
        self,
        *,
        payload: dict[str, Any],
        variables: list[str],
        model: ModelDefinition,
        chunk_start: datetime,
        chunk_end: datetime,
    ) -> list[CanonicalObservation]:
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        grid = {
            "grid_latitude": payload.get("latitude"),
            "grid_longitude": payload.get("longitude"),
            "elevation_m": payload.get("elevation"),
            "timezone_basis": payload.get("timezone", "GMT"),
            "utc_offset_seconds": payload.get("utc_offset_seconds", 0),
        }
        native_units = payload.get("daily_units") or {}

        observations: list[CanonicalObservation] = []
        for vcode in variables:
            native_name, native_unit, conversion = DAILY_VARIABLE_MAP[vcode]
            vdef = variable_definition(vcode)
            values = daily.get(native_name)
            if values is None:
                raise ProviderRequestError(
                    f"Open-Meteo response is missing daily series '{native_name}'.",
                    details=[{"field": "upstream", "reason": "variable absent from payload"}],
                )
            for i, day_iso in enumerate(times):
                raw = values[i] if i < len(values) else None
                missing = raw is None
                value: float | None = None
                conversion_desc = "identity"
                if not missing:
                    candidate = float(raw)
                    if math.isnan(candidate):
                        missing = True
                    else:
                        value = candidate
                        if conversion is not None:
                            op, factor = conversion
                            if op == "div":
                                value = value / factor
                                conversion_desc = (
                                    f"{native_unit} -> {vdef.unit if vdef else vcode}: divide by {factor}"
                                )
                observed = datetime.fromisoformat(day_iso).replace(tzinfo=UTC)
                flags = []
                if missing:
                    flags.append(
                        {
                            "flag_code": "OPENMETEO_NULL",
                            "severity": "info",
                            "message": "Upstream archive reported no value for this day.",
                            "details": {"native_variable": native_name},
                        }
                    )
                observations.append(
                    CanonicalObservation(
                        variable_code=vcode,
                        value=None if missing else round(value, 4),
                        unit=vdef.unit if vdef else "unknown",
                        observed_at=observed,
                        period_start=observed,
                        period_end=observed + timedelta(days=1) - timedelta(seconds=1),
                        time_support=TimeSupport.daily,
                        spatial_support_type="grid_cell",
                        spatial_resolution_m=model.spatial_resolution_m,
                        quality_status=QualityStatus.missing if missing else QualityStatus.valid,
                        uncertainty_value=None,
                        uncertainty_type="unknown",
                        evidence_class=EvidenceClass.reanalysis_model_estimate,
                        is_synthetic=False,
                        processing_version="openmeteo-normalizer-v1",
                        metadata={
                            "model": model.code,
                            "model_description": model.description,
                            "native_variable": native_name,
                            "native_unit": native_unit,
                            "native_daily_unit": native_units.get(native_name, native_unit),
                            "conversion": conversion_desc,
                            **grid,
                            "chunk_start": chunk_start.date().isoformat(),
                            "chunk_end": chunk_end.date().isoformat(),
                            "retrieved_at_basis": "archive_api_v1",
                        },
                        quality_flags=flags,
                    )
                )
        return observations


def health_probe() -> dict[str, Any]:
    """Light live probe used by the registry health view (cheap 1-day request)."""
    started = datetime.now(UTC)
    try:
        response = httpx.get(
            settings.open_meteo_base_url,
            params={
                "latitude": 31.05,
                "longitude": 31.1,
                "start_date": "2024-01-01",
                "end_date": "2024-01-01",
                "daily": "temperature_2m_mean",
                "timezone": "UTC",
                "models": "era5_land",
            },
            timeout=settings.provider_probe_timeout_seconds,
        )
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        if response.status_code == 200 and not response.json().get("error"):
            return {"status": "ok", "latency_ms": latency, "detail": "archive API responded"}
        return {"status": "degraded", "latency_ms": latency, "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        return {"status": "unreachable", "latency_ms": None, "detail": f"{type(exc).__name__}"}

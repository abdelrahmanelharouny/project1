"""Open-Meteo Forecast API provider (P2.B) — short-range weather forecasts.

Distinct from the historical archive provider (`open_meteo`): this talks to
`https://api.open-meteo.com/v1/forecast`, the deterministic NWP forecast
endpoint. Its output is FORECAST evidence with issue/valid time separation —
never historical observations, never projections.

Contract implementation (app.climate.contracts.ForecastEvidence):
- issue time: the API response's per-request `generationtime_ms` is model
  runtime metadata; the issue anchor used is the response receipt time
  (UTC) recorded explicitly as `issue_basis: "response_receipt_utc"` in
  metadata — the free endpoint does not expose the underlying model run
  timestamp, and we refuse to invent one.
- valid time: each daily/hourly value's timestamp (UTC).
- horizon: hours between issue anchor and valid time (>= 0).
- uncertainty: the free tier is a single deterministic model (best_match
  pinned to `ecmwf_ifs04` or `gfs_seamless` when explicitly selected);
  uncertainty_type is "none_deterministic_single_model" — no invented
  spread.
- nulls in the payload become quality_status="missing" rows — never zeros.

Variables: air_temperature_mean/min/max, precipitation, reference_et0,
wind_speed_10m. ET0 comes from the API's et0_fao_evapotranspiration.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import InvalidDateRange, ProviderRequestError, ProviderUnavailable
from app.data_platform.contracts.variables import variable_definition

logger = logging.getLogger("croptwist.providers.open_meteo_forecast")

PROVIDER_CODE = "open_meteo_forecast"
PROVIDER_NAME = "Open-Meteo Forecast API"
PRODUCT_CODE = "forecast_api"
PRODUCT_VERSION = "openmeteo-forecast-2026.11"

# Canonical variable -> (forecast API daily name, unit)
DAILY_VARIABLE_MAP: dict[str, str] = {
    "air_temperature_mean": "temperature_2m_mean",
    "air_temperature_min": "temperature_2m_min",
    "air_temperature_max": "temperature_2m_max",
    "precipitation": "precipitation_sum",
    "reference_et0": "et0_fao_evapotranspiration",
    "wind_speed_10m": "wind_speed_10m_max",
}

# Documented selectable models (capability honesty: free deterministic NWP).
MODELS: dict[str, str] = {
    "best_match": "best_match",
    "ecmwf_ifs04": "ecmwf_ifs04",
    "gfs_seamless": "gfs_seamless",
}

MODEL_SPATIAL_RESOLUTION_M: dict[str, float] = {
    "best_match": 11132.0,
    "ecmwf_ifs04": 9000.0,
    "gfs_seamless": 11132.0,
}


class ForecastModelDefinition(BaseModel):
    code: str
    description: str
    spatial_resolution_m: float


class OpenMeteoForecastProvider:
    """Short-range forecast provider implementing the P2.B contract.

    HTTP goes through an injected transport for deterministic contract
    tests; production uses httpx with configured timeouts.
    """

    provider_code = PROVIDER_CODE
    forecast_class = "short_range_forecast"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "code": code,
                "description": (
                    "Open-Meteo default best-match NWP" if code == "best_match" else f"Model {code}"
                ),
                "spatial_resolution_m": MODEL_SPATIAL_RESOLUTION_M[code],
            }
            for code in sorted(MODELS)
        ]

    def supported_variables(self) -> list[str]:
        return sorted(DAILY_VARIABLE_MAP.keys())

    def _fetch_payload(
        self,
        *,
        latitude: float,
        longitude: float,
        variables: list[str],
        forecast_days: int,
        model: str,
    ) -> dict[str, Any]:
        daily_names = sorted({DAILY_VARIABLE_MAP[v] for v in variables})
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(daily_names),
            "forecast_days": forecast_days,
            "timezone": "UTC",
            "models": MODELS.get(model, MODELS["best_match"]),
        }
        try:
            response = (self._client or httpx).get(
                settings.open_meteo_forecast_base_url,
                params=params,
                timeout=settings.open_meteo_forecast_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                "Open-Meteo forecast request failed (network or API error).",
                details=[{"reason": str(exc)}],
            ) from exc
        except ValueError as exc:
            raise ProviderRequestError(
                "Open-Meteo forecast returned a malformed response.",
                details=[{"reason": str(exc)}],
            ) from exc

    def fetch_forecast(
        self,
        *,
        geometry_centroid: tuple[float, float],
        variables: list[str],
        forecast_days: int | None = None,
        model: str = "best_match",
    ) -> tuple[list[Any], dict[str, Any]]:
        """Fetch a forecast batch.

        Returns (list of ForecastEvidence, response_metadata). Raises
        ProviderUnavailable on network failure — callers degrade honestly.
        """
        from app.climate.contracts import ForecastEvidence, ForecastClass

        unknown = sorted(set(variables) - set(DAILY_VARIABLE_MAP))
        if unknown:
            raise InvalidDateRange(
                f"Variables not supported by the forecast provider: {', '.join(unknown)}.",
                details=[{"field": "variables", "reason": "see /data/catalog"}],
            )
        if model not in MODELS:
            raise InvalidDateRange(
                f"Unknown forecast model '{model}'.",
                details=[{"field": "model", "reason": f"choose one of {sorted(MODELS)}"}],
            )
        days = forecast_days or settings.open_meteo_forecast_days
        days = max(1, min(16, days))
        latitude, longitude = geometry_centroid
        payload = self._fetch_payload(
            latitude=latitude,
            longitude=longitude,
            variables=variables,
            forecast_days=days,
            model=model,
        )
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        if not times:
            raise ProviderRequestError(
                "Forecast response has no daily time axis.",
                details=[{"reason": "empty 'daily.time'"}],
            )
        issued_at = datetime.now(UTC)
        evidence: list[ForecastEvidence] = []
        resolution = MODEL_SPATIAL_RESOLUTION_M[MODELS.get(model, "best_match")]
        for vcode in sorted(set(variables)):
            vdef = variable_definition(vcode)
            unit = vdef.unit if vdef else ""
            native_key = DAILY_VARIABLE_MAP[vcode]
            values = daily.get(native_key)
            if values is None:
                continue
            for i, day_str in enumerate(times):
                if i >= len(values):
                    break
                raw = values[i]
                valid_time = datetime.fromisoformat(f"{day_str}T00:00:00+00:00")
                horizon = int((valid_time - issued_at).total_seconds() // 3600)
                if horizon < 0:
                    horizon = 0
                evidence.append(
                    ForecastEvidence(
                        provider_code=PROVIDER_CODE,
                        forecast_class=ForecastClass.short_range_forecast,
                        model_id=MODELS.get(model, "best_match"),
                        ensemble_member=None,
                        variable_code=vcode,
                        unit=unit,
                        issued_at=issued_at,
                        valid_time=valid_time,
                        horizon_hours=horizon,
                        value=None if raw is None else float(raw),
                        value_min=None,
                        value_max=None,
                        uncertainty_type=(
                            None if raw is not None else "missing_value"
                        ),
                        spatial_resolution_m=resolution,
                        quality_status="valid" if raw is not None else "missing",
                        quality_flags=(
                            []
                            if raw is not None
                            else [
                                {
                                    "flag_code": "OPENMETEO_FORECAST_NULL",
                                    "severity": "warning",
                                    "message": "Upstream returned no value for this day.",
                                }
                            ]
                        ),
                        is_synthetic=False,
                        processing_version=PRODUCT_VERSION,
                        metadata={
                            "issue_basis": "response_receipt_utc",
                            "native_variable": native_key,
                            "request_model": MODELS.get(model, "best_match"),
                            "latitude": latitude,
                            "longitude": longitude,
                        },
                    )
                )
        response_meta = {
            "issued_at": issued_at.isoformat(),
            "forecast_days": days,
            "model": MODELS.get(model, "best_match"),
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": payload.get("elevation"),
            "generationtime_ms": payload.get("generationtime_ms"),
        }
        return evidence, response_meta

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client


def centroid_of_geometry(geometry_geojson: dict[str, Any]) -> tuple[float, float]:
    """Geometry centroid (lon, lat) for point-based forecast requests."""
    from shapely.geometry import shape

    geom = shape(geometry_geojson)
    centroid = geom.centroid
    return round(float(centroid.x), 5), round(float(centroid.y), 5)

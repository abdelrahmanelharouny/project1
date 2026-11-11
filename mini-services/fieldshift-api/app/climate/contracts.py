"""Forecast & projection evidence contracts (P2.B).

The forecast contract separates ISSUE time from VALID time — the core
honesty rule of P2.B. A forecast is an estimate issued at `issued_at` about
`valid_time` with `horizon_hours`; historical observations are never
overwritten or blended with forecast rows (they live in separate tables and
carry separate evidence classes).

Classification vocabulary (provider capability matrix, §4.A of the P2 spec):
- historical_observation      — measured/observed values.
- reanalysis                  — ERA5-family model estimates of the past
                                (what the existing Open-Meteo archive is).
- short_range_forecast        — deterministic NWP, hours..~16 days.
- seasonal_forecast           — probabilistic outlooks (weeks..months) —
                                NOT implemented by any current provider.
- climate_projection          — CMIP6-style scenario ensembles (decades).

Providers MUST declare their class; the platform refuses to ingest a
forecast into a historical slot or a projection into a forecast slot.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

FORECAST_CONTRACT_VERSION = "forecast-contract-1.0.0"


class ForecastClass(StrEnum):
    historical_observation = "historical_observation"
    reanalysis = "reanalysis"
    short_range_forecast = "short_range_forecast"
    seasonal_forecast = "seasonal_forecast"
    climate_projection = "climate_projection"


class ForecastVariable(BaseModel):
    """One forecast variable value with its uncertainty representation."""

    variable_code: str
    unit: str
    value: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    uncertainty_type: str | None = None  # e.g. "model_spread", "ensemble_range", "none"

    @field_validator("variable_code")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("variable_code must be non-empty")
        return v.strip()


class ForecastEvidence(BaseModel):
    """Normalized forecast evidence record (the P2.B normalized contract).

    Every field is provenance the UI must be able to display: issue/valid
    time, horizon, provider, model, ensemble identity, units, spatial
    resolution, quality and uncertainty metadata.
    """

    provider_code: str
    forecast_class: ForecastClass = ForecastClass.short_range_forecast
    model_id: str | None = None
    ensemble_member: str | None = None
    variable_code: str
    unit: str
    issued_at: datetime
    valid_time: datetime
    horizon_hours: int
    value: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    uncertainty_type: str | None = None
    spatial_resolution_m: float | None = None
    quality_status: str = "valid"
    quality_flags: list[dict[str, Any]] = Field(default_factory=list)
    is_synthetic: bool = False
    processing_version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("horizon_hours")
    @classmethod
    def _horizon_nonneg(cls, v: int) -> int:
        if v < 0:
            raise ValueError("horizon_hours must be >= 0")
        return v

    def to_row(self) -> dict[str, Any]:
        return {
            "provider_code": self.provider_code,
            "model_id": self.model_id,
            "ensemble_member": self.ensemble_member,
            "variable_code": self.variable_code,
            "unit": self.unit,
            "issued_at": self.issued_at,
            "valid_time": self.valid_time,
            "horizon_hours": self.horizon_hours,
            "value": self.value,
            "value_min": self.value_min,
            "value_max": self.value_max,
            "uncertainty_type": self.uncertainty_type,
            "spatial_resolution_m": self.spatial_resolution_m,
            "quality_status": self.quality_status,
            "quality_flags": self.quality_flags,
            "is_synthetic": self.is_synthetic,
            "processing_version": self.processing_version,
            "metadata": self.metadata,
        }


class ProjectionEvidence(BaseModel):
    """Normalized climate-projection record (decadal scale, scenario-based).

    Scenario identity (SSP), model identity, ensemble size, bias-correction
    status and uncertainty bands are mandatory provenance; a projection
    without scenario/model identity is refused rather than silently stored.
    """

    provider_code: str
    source_product: str | None = None
    model_id: str | None = None
    scenario_id: str | None = None
    ensemble_size: int | None = None
    bias_correction: str | None = None  # "raw" | "bias_corrected:<method>" | None
    variable_code: str
    unit: str
    period_start: datetime
    period_end: datetime
    baseline_period: str | None = None
    statistic: str
    value: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    is_synthetic: bool = False
    processing_version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("statistic")
    @classmethod
    def _statistic_known(cls, v: str) -> str:
        allowed = {"mean", "median", "p10", "p90", "min", "max", "ensemble_mean", "ensemble_spread"}
        if v not in allowed:
            raise ValueError(f"statistic must be one of {sorted(allowed)}")
        return v


class ForecastFreshness(BaseModel):
    """Freshness verdict for the latest forecast issue of a field."""

    variable_code: str
    latest_issued_at: datetime | None
    age_hours: float | None
    max_age_hours: float
    fresh: bool
    detail: str


# Verified provider capability matrix (§4.A). Each entry states what the
# provider's product ACTUALLY does — the platform refuses to claim more.
PROVIDER_CAPABILITY_MATRIX: list[dict[str, Any]] = [
    {
        "provider_code": "open_meteo",
        "products": ["era5_land", "era5"],
        "forecast_class": ForecastClass.reanalysis.value,
        "temporal_horizon": "1940-01-01 .. now-6d (historical)",
        "spatial_resolution_m": 11132.0,
        "update_frequency": "archive (delayed ~5-6 days)",
        "variables": [
            "air_temperature_mean",
            "air_temperature_min",
            "air_temperature_max",
            "precipitation",
            "reference_et0",
            "soil_moisture_surface",
            "wind_speed_10m",
        ],
        "licensing": "CC BY 4.0 (Open-Meteo) on ECMWF/Copernicus data",
        "authentication": "none",
        "known_limitations": "Gridded reanalysis; not field sensors; never a forecast.",
    },
    {
        "provider_code": "open_meteo_forecast",
        "products": ["forecast_api"],
        "forecast_class": ForecastClass.short_range_forecast.value,
        "temporal_horizon": "now .. +16 days (deterministic NWP)",
        "spatial_resolution_m": 11132.0,
        "update_frequency": "hourly model runs; platform ingests on demand",
        "variables": [
            "air_temperature_mean",
            "air_temperature_min",
            "air_temperature_max",
            "precipitation",
            "reference_et0",
            "wind_speed_10m",
        ],
        "licensing": "CC BY 4.0 (Open-Meteo)",
        "authentication": "none",
        "known_limitations": (
            "Deterministic single-model forecast without ensemble spread in "
            "the free tier; skill degrades with horizon; not a projection."
        ),
    },
    {
        "provider_code": "sentinel2",
        "products": ["sentinel-2-l2a"],
        "forecast_class": ForecastClass.historical_observation.value,
        "temporal_horizon": "2017+ revisit ~5 days (observations)",
        "spatial_resolution_m": 10.0,
        "update_frequency": "per acquisition",
        "variables": ["ndvi", "evi", "savi", "ndmi", "ndwi"],
        "licensing": "Copernicus free/open licence",
        "authentication": "optional CDSE OAuth (assets); anonymous search",
        "known_limitations": "Cloud cover; 10-20 m grid; no forecast capability.",
    },
    {
        "provider_code": "cmip6_projection",
        "products": ["cmip6-scenario"],
        "forecast_class": ForecastClass.climate_projection.value,
        "temporal_horizon": "2015..2100 (scenario ensembles)",
        "spatial_resolution_m": None,
        "update_frequency": "static dataset releases",
        "variables": [
            "air_temperature_mean",
            "precipitation",
        ],
        "licensing": "CMIP6 model-output licences vary per model",
        "authentication": "provider-dependent (Planetary Computer STAC key)",
        "known_limitations": (
            "ADAPTER SEAM ONLY — no CMIP6 dataset is wired in this deployment; "
            "records may exist only from explicitly labelled synthetic fixtures. "
            "Projections are never deterministic future weather."
        ),
        "status": "blocked_pending_credentials",
    },
]


def capability_matrix() -> list[dict[str, Any]]:
    return [dict(entry) for entry in PROVIDER_CAPABILITY_MATRIX]

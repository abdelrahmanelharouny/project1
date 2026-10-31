"""Canonical observation contracts and the provider protocol (Master §12-13).

Providers map external payloads into these canonical DTOs — never ORM entities.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from app.core.errors import InvalidDateRange, UnsupportedVariable
from app.data_platform.contracts.variables import SUPPORTED_VARIABLE_CODES


class QualityStatus(StrEnum):
    valid = "valid"
    suspect = "suspect"
    invalid = "invalid"
    missing = "missing"
    estimated = "estimated"
    not_assessed = "not_assessed"


class SpatialSupportType(StrEnum):
    point = "point"
    grid_cell = "grid_cell"
    polygon_average = "polygon_average"
    field_intersection = "field_intersection"
    station = "station"
    lab_sample = "lab_sample"


class TimeSupport(StrEnum):
    instant = "instant"
    hourly = "hourly"
    daily = "daily"
    pentadal = "pentadal"
    dekadal = "dekadal"
    monthly = "monthly"
    seasonal = "seasonal"
    annual = "annual"


class EvidenceClass(StrEnum):
    direct_field_measurement = "direct_field_measurement"
    farmer_reported_record = "farmer_reported_record"
    station_observation = "station_observation"
    satellite_derived_estimate = "satellite_derived_estimate"
    reanalysis_model_estimate = "reanalysis_model_estimate"
    global_soil_prediction = "global_soil_prediction"
    curated_agronomic_reference = "curated_agronomic_reference"
    synthetic_test_data = "synthetic_test_data"


class SourceProvenance(BaseModel):
    """Product-level provenance attached to every provider result (Master §12-13.2)."""

    provider_code: str
    provider_name: str
    product_code: str
    product_version: str
    license_name: str | None = None
    license_url: str | None = None
    attribution_text: str | None = None
    documentation_url: str | None = None
    known_limitations: str | None = None
    retrieval_method: str = "api"


class CanonicalObservation(BaseModel):
    """Provider-independent observation record (Master §13.1).

    `value` is None exactly when quality_status is `missing` (nodata must be
    flagged, never replaced by zero — Master rule 11).
    """

    variable_code: str
    value: float | None = None
    unit: str
    observed_at: datetime  # instant/day anchor, UTC
    period_start: datetime
    period_end: datetime
    time_support: TimeSupport = TimeSupport.daily
    spatial_support_type: SpatialSupportType = SpatialSupportType.field_intersection
    spatial_resolution_m: float | None = None
    quality_status: QualityStatus = QualityStatus.valid
    uncertainty_value: float | None = None
    uncertainty_type: str | None = None
    evidence_class: EvidenceClass = EvidenceClass.reanalysis_model_estimate
    is_synthetic: bool = False
    processing_version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)
    quality_flags: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("observed_at", "period_start", "period_end")
    @classmethod
    def _require_tz_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must carry UTC timezone")
        return v.astimezone(UTC)


class ProviderFetchResult(BaseModel):
    """Normalized provider outcome (Master §12)."""

    provider_code: str
    provenance: SourceProvenance
    observations: list[CanonicalObservation]
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    provider_request_id: str | None = None
    raw_reference: str | None = None  # retained payload/file reference where permitted
    # Optional upstream count of received input records (file imports: CSV/GeoTIFF
    # rows or files read). Defaults to len(observations) for fetch-style providers.
    input_record_count: int | None = None


class AreaOfInterest(BaseModel):
    """Field AOI passed to providers. Geometry is GeoJSON (EPSG:4326)."""

    field_id: str | None = None
    geometry_geojson: dict[str, Any]
    area_ha: float | None = None

    @field_validator("geometry_geojson")
    @classmethod
    def _require_geojson_object(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict) or "type" not in v:
            raise ValueError("geometry_geojson must be a GeoJSON geometry object")
        return v


@runtime_checkable
class EnvironmentalDataProvider(Protocol):
    """Provider contract (Master §12).

    Implementations must be deterministic where practical (synthetic provider),
    validate inputs, flag missing values, and never raise for out-of-scope data
    that can be represented as a structured warning instead.
    """

    provider_code: str

    def fetch_observations(
        self,
        *,
        area_of_interest: AreaOfInterest,
        variables: list[str],
        start: datetime,
        end: datetime,
        options: dict[str, Any] | None = None,
    ) -> ProviderFetchResult: ...


def validate_provider_request(
    variables: list[str], start: datetime, end: datetime
) -> None:
    """Shared request validation used by all providers (contract suite item)."""
    if not variables:
        raise UnsupportedVariable("No variables requested.")
    unknown = [v for v in variables if v not in SUPPORTED_VARIABLE_CODES]
    if unknown:
        raise UnsupportedVariable(
            "Requested variables are not in the canonical catalog.",
            details=[{"field": "variables", "reason": f"unsupported: {', '.join(unknown)}"}],
        )
    if start > end:
        raise InvalidDateRange("start must be before or equal to end.")
    if end - start > timedelta_days(366 * 30):
        raise InvalidDateRange("Requested range exceeds 30 years.")


def timedelta_days(n: int):
    from datetime import timedelta

    return timedelta(days=n)

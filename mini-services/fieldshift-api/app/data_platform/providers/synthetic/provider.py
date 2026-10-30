"""Deterministic synthetic environmental provider (software fixture, Master §11.1-G / §53).

This provider generates *labelled synthetic* weather time series for testing
application behavior — they are NOT real-world measurements and carry no
agronomic validity. Every observation produced here is flagged
`is_synthetic=True` with generator version, seed, profile and purpose recorded
in provenance and per-row metadata.

Determinism: the same (seed, profile, variables, date range, AOI geometry)
always yields byte-identical series. Generation uses only Python's `random`
module seeded from a hash of the request, never wall-clock time.

Profiles (shape parameters are fixture constants, not agronomic claims):
  temperate_seasonal        — mid-latitude four-season cycle
  mediterranean_dry_summer  — wet winter / dry summer
  semi_arid                 — low, erratic rainfall
  tropical_seasonal         — wet/dry seasons, small thermal amplitude
  arid_irrigated            — very low rainfall, high ET0 (irrigation context)
"""

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from app.core.errors import InvalidDateRange
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

PROVIDER_CODE = "synthetic"
PROVIDER_NAME = "FieldShift Synthetic Fixture Provider"
GENERATOR_VERSION = "synthetic-v1.0"
PRODUCT_CODE = "synthetic_environment"
PRODUCT_VERSION = "v1"
COVERAGE_START = datetime(2015, 1, 1, tzinfo=UTC)
COVERAGE_END = datetime(2024, 12, 31, tzinfo=UTC)


class ProfileParameters(BaseModel):
    """Fixture shape parameters. These are synthetic-test constants only."""

    base_temperature_c: float
    annual_amplitude_c: float
    mean_precip_mm: float
    precip_seasonality: float  # 0 = uniform, 1 = strongly seasonal
    wet_day_probability: float
    mean_et0_mm: float
    et0_seasonality: float
    soil_moisture_mean: float
    data_gap_probability: float  # deterministic injected gaps for missing-data paths
    description: str


PROFILES: dict[str, ProfileParameters] = {
    "temperate_seasonal": ProfileParameters(
        base_temperature_c=11.0,
        annual_amplitude_c=11.0,
        mean_precip_mm=2.4,
        precip_seasonality=0.35,
        wet_day_probability=0.38,
        mean_et0_mm=3.0,
        et0_seasonality=0.6,
        soil_moisture_mean=0.28,
        data_gap_probability=0.01,
        description="Synthetic temperate seasonal fixture (four-season cycle).",
    ),
    "mediterranean_dry_summer": ProfileParameters(
        base_temperature_c=17.5,
        annual_amplitude_c=9.5,
        mean_precip_mm=1.6,
        precip_seasonality=0.85,
        wet_day_probability=0.25,
        mean_et0_mm=3.8,
        et0_seasonality=0.7,
        soil_moisture_mean=0.22,
        data_gap_probability=0.015,
        description="Synthetic mediterranean dry-summer fixture (wet winter, dry summer).",
    ),
    "semi_arid": ProfileParameters(
        base_temperature_c=20.0,
        annual_amplitude_c=8.0,
        mean_precip_mm=0.9,
        precip_seasonality=0.6,
        wet_day_probability=0.15,
        mean_et0_mm=4.6,
        et0_seasonality=0.5,
        soil_moisture_mean=0.15,
        data_gap_probability=0.02,
        description="Synthetic semi-arid fixture (low, erratic rainfall).",
    ),
    "tropical_seasonal": ProfileParameters(
        base_temperature_c=25.5,
        annual_amplitude_c=3.0,
        mean_precip_mm=4.2,
        precip_seasonality=0.9,
        wet_day_probability=0.4,
        mean_et0_mm=4.4,
        et0_seasonality=0.3,
        soil_moisture_mean=0.30,
        data_gap_probability=0.015,
        description="Synthetic tropical wet/dry fixture (small thermal amplitude).",
    ),
    "arid_irrigated": ProfileParameters(
        base_temperature_c=23.0,
        annual_amplitude_c=10.0,
        mean_precip_mm=0.25,
        precip_seasonality=0.2,
        wet_day_probability=0.05,
        mean_et0_mm=5.6,
        et0_seasonality=0.55,
        soil_moisture_mean=0.12,
        data_gap_probability=0.01,
        description="Synthetic arid irrigated fixture (very low rainfall, high ET0).",
    ),
}

PROFILE_CODES = sorted(PROFILES.keys())


def _request_rng(seed: int, profile: str, aoi: AreaOfInterest, variables: list[str],
                 start: datetime, end: datetime) -> random.Random:
    """Deterministic RNG derived from the full request signature."""
    payload = json.dumps(
        {
            "seed": seed,
            "profile": profile,
            "aoi": aoi.geometry_geojson,
            "variables": sorted(variables),
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _day_of_year_fraction(day: datetime) -> float:
    """0..1 position within the year (seasonality phase)."""
    doy = day.timetuple().tm_yday
    return (doy - 1) / 365.0


def _seasonal_phase(day: datetime, hemisphere_shift_days: int = 0) -> float:
    """Return a cosine phase in [-1, 1]; peak on ~15 July shifted by profile."""
    doy = (day.timetuple().tm_yday - hemisphere_shift_days) % 365
    import math

    return math.cos(2.0 * math.pi * (doy - 196) / 365.0)  # peak at day 196 (~Jul 15)


def generate_daily_series(
    profile: str,
    variable_code: str,
    day: datetime,
    rng_stream: random.Random,
    params: ProfileParameters,
) -> tuple[float | None, list[dict[str, Any]]]:
    """Generate one synthetic daily value + quality flags for a variable/day.

    Pure function of (profile, variable, day, rng_stream). Returns (value|None, flags).
    """
    phase_temp = _seasonal_phase(day)
    import math

    flags: list[dict[str, Any]] = []

    # Deterministic injected data gaps exercise missing-data handling.
    if rng_stream.random() < params.data_gap_probability:
        flags.append(
            {
                "flag_code": "SYNTHETIC_GAP",
                "severity": "info",
                "message": "Deterministic synthetic data gap (fixture).",
                "details": {"profile": profile},
            }
        )
        return None, flags

    doy_frac = _day_of_year_fraction(day)

    if variable_code in ("air_temperature_mean", "air_temperature_min", "air_temperature_max"):
        base = params.base_temperature_c + params.annual_amplitude_c * phase_temp
        noise = rng_stream.gauss(0, 1.4)
        if variable_code == "air_temperature_mean":
            value = base + noise
        elif variable_code == "air_temperature_min":
            value = base - 3.5 + noise * 0.8
        else:
            value = base + 3.5 + noise * 0.8
        return round(value, 2), flags

    if variable_code == "precipitation":
        season_weight = 1.0 + params.precip_seasonality * (-phase_temp)  # wetter in winter half
        wet_p = min(0.95, params.wet_day_probability * max(0.05, season_weight))
        if rng_stream.random() < wet_p:
            value = rng_stream.expovariate(1.0 / max(0.2, params.mean_precip_mm))
            if rng_stream.random() < 0.03:  # occasional heavy day
                value *= 6.0
            return round(value, 2), flags
        return 0.0, flags  # a dry day is a valid zero, not missing data

    if variable_code == "reference_et0":
        value = params.mean_et0_mm * (1.0 + params.et0_seasonality * phase_temp) + rng_stream.gauss(0, 0.4)
        return round(max(0.0, value), 2), flags

    if variable_code == "soil_moisture_mean" or variable_code == "soil_moisture_surface":
        # Crude sinusoid + noise; NOT a soil-water balance model (fixture only).
        value = params.soil_moisture_mean * (1.0 + 0.3 * (-phase_temp)) + rng_stream.gauss(0, 0.02)
        value = min(0.55, max(0.02, value))
        return round(value, 4), flags

    if variable_code == "wind_speed_2m":
        value = 2.0 + 1.2 * abs(math.sin(2 * math.pi * doy_frac)) + rng_stream.gauss(0, 0.5)
        return round(max(0.1, value), 2), flags

    # Unknown variable should have been rejected upstream; guard anyway.
    raise InvalidDateRange(f"Variable '{variable_code}' is not implemented by the synthetic generator.")


class SyntheticProvider:
    """Deterministic synthetic EnvironmentalDataProvider implementation."""

    provider_code = PROVIDER_CODE

    def __init__(self) -> None:
        self._provenance = SourceProvenance(
            provider_code=PROVIDER_CODE,
            provider_name=PROVIDER_NAME,
            product_code=PRODUCT_CODE,
            product_version=PRODUCT_VERSION,
            license_name="MIT (fixture code)",
            license_url="https://opensource.org/licenses/MIT",
            attribution_text=(
                "SYNTHETIC TEST FIXTURE — generated by FieldShift; not real-world data; "
                "no agronomic validity."
            ),
            documentation_url="https://github.com/fieldshift/docs/data_platform/provider-contracts.md",
            known_limitations=(
                "Profiles are software fixtures with invented shape parameters. "
                "Do not use for any real-world agronomic conclusion."
            ),
            retrieval_method="in_process_generator",
        )

    def profiles(self) -> list[dict[str, Any]]:
        return [
            {"code": code, "description": p.description}
            for code, p in sorted(PROFILES.items())
        ]

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

        profile = options.get("profile", "temperate_seasonal")
        if profile not in PROFILES:
            raise InvalidDateRange(
                f"Unknown synthetic profile '{profile}'.",
                details=[{"field": "profile", "reason": f"choose one of {', '.join(PROFILE_CODES)}"}],
            )
        seed = int(options.get("seed", 42))
        params = PROFILES[profile]

        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start < COVERAGE_START or end > COVERAGE_END:
            raise InvalidDateRange(
                "Synthetic fixture coverage is 2015-01-01..2024-12-31.",
                details=[
                    {
                        "field": "date_range",
                        "reason": f"requested {start.date()}..{end.date()} outside provider coverage",
                    }
                ],
            )
        if (end - start).days > 366 * 4:
            raise InvalidDateRange("Synthetic fixture requests are limited to 4 years per job.")

        rng = _request_rng(seed, profile, area_of_interest, variables, start, end)

        observations: list[CanonicalObservation] = []
        warnings: list[str] = [
            "All observations from this provider are SYNTHETIC software fixtures; "
            "they must never be presented as real measurements."
        ]

        # Iterate variables in sorted order so the RNG stream is independent of
        # the caller's variable ordering (contract: deterministic given the request).
        for vcode in sorted(variables):
            vdef = variable_definition(vcode)
            evidence = (
                EvidenceClass.synthetic_test_data
            )
            day = start.replace(hour=0, minute=0, second=0, microsecond=0)
            while day <= end:
                value, flags = generate_daily_series(profile, vcode, day, rng, params)
                missing = value is None
                observations.append(
                    CanonicalObservation(
                        variable_code=vcode,
                        value=None if missing else value,
                        unit=vdef.unit if vdef else "unknown",
                        observed_at=day,
                        period_start=day,
                        period_end=day + timedelta(days=1) - timedelta(seconds=1),
                        time_support=TimeSupport.daily,
                        spatial_support_type="field_intersection",
                        spatial_resolution_m=None,  # generator is field-resolved by construction
                        quality_status=QualityStatus.missing if missing else QualityStatus.valid,
                        uncertainty_value=None,  # unknown, never zero-fabricated
                        uncertainty_type="unknown",
                        evidence_class=evidence,
                        is_synthetic=True,
                        processing_version=GENERATOR_VERSION,
                        metadata={
                            "generator_version": GENERATOR_VERSION,
                            "seed": seed,
                            "profile": profile,
                            "purpose": "software_testing_fixture",
                        },
                        quality_flags=flags,
                    )
                )
                day += timedelta(days=1)

        return ProviderFetchResult(
            provider_code=PROVIDER_CODE,
            provenance=self._provenance,
            observations=observations,
            warnings=warnings,
            coverage={
                "start": COVERAGE_START.date().isoformat(),
                "end": COVERAGE_END.date().isoformat(),
                "requested_start": start.date().isoformat(),
                "requested_end": end.date().isoformat(),
                "profile": profile,
                "seed": seed,
            },
            provider_request_id=f"synthetic-{seed}-{profile}",
            raw_reference=None,
        )

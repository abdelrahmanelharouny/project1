"""Provider contract suite (Master §12 'Provider contract tests').

Every provider implementation must pass this suite. The synthetic provider is
the first implementation; future providers (Open-Meteo, CHIRPS, SoilGrids) will
be validated against the same suite without modification.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.errors import FieldShiftError
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    EnvironmentalDataProvider,
)
from app.data_platform.contracts.variables import SUPPORTED_VARIABLE_CODES, VARIABLE_CATALOG
from app.data_platform.providers.synthetic.provider import SyntheticProvider

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)

START = datetime(2023, 6, 1, tzinfo=UTC)
END = datetime(2023, 6, 30, tzinfo=UTC)


@pytest.fixture()
def provider():
    return SyntheticProvider()


@pytest.fixture()
def result(provider):
    return provider.fetch_observations(
        area_of_interest=AOI,
        variables=["air_temperature_mean", "precipitation", "reference_et0"],
        start=START,
        end=END,
        options={"profile": "temperate_seasonal", "seed": 7},
    )


class TestContractSuite:
    """Shared contract items from Master Engineering Prompt §12."""

    def test_implements_provider_protocol(self, provider):
        assert isinstance(provider, EnvironmentalDataProvider)

    def test_returns_valid_canonical_objects(self, result):
        assert len(result.observations) == 30 * 3  # 30 days x 3 variables
        for obs in result.observations:
            # Pydantic re-validation: canonical object shape, tz-aware timestamps.
            obs.model_validate(obs.model_dump())
            assert obs.observed_at.tzinfo is not None
            assert obs.period_start <= obs.observed_at <= obs.period_end

    def test_includes_provenance(self, result):
        p = result.provenance
        assert p.provider_code == "synthetic"
        assert p.product_code and p.product_version
        assert p.attribution_text  # synthetic attribution mandatory
        assert p.known_limitations

    def test_includes_units_matching_catalog(self, result):
        for obs in result.observations:
            assert obs.unit == VARIABLE_CATALOG[obs.variable_code].unit

    def test_preserves_native_temporal_support(self, result):
        assert all(o.time_support == "daily" for o in result.observations)

    def test_flags_missing_and_nodata_values(self, result):
        for obs in result.observations:
            if obs.value is None:
                assert obs.quality_status == "missing"
            if obs.quality_status == "missing":
                assert obs.value is None

    def test_no_zero_fabrication_for_unknown(self, provider):
        # Missing entries must be None, never a fabricated 0.
        big = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["air_temperature_mean"],
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end=datetime(2023, 12, 31, tzinfo=UTC),
            options={"profile": "semi_arid", "seed": 3},
        )
        zeros = [o for o in big.observations if o.value == 0.0]
        for obs in zeros:
            assert obs.quality_status != "missing"  # 0 is a valid temperature only if present
        # uncertainty unknown stays None, never 0
        assert all(o.uncertainty_value is None for o in big.observations)

    def test_rejects_invalid_date_ranges(self, provider):
        with pytest.raises(FieldShiftError):
            provider.fetch_observations(
                area_of_interest=AOI, variables=["precipitation"],
                start=END, end=START, options={"seed": 1},
            )

    def test_rejects_unsupported_variables(self, provider):
        with pytest.raises(FieldShiftError):
            provider.fetch_observations(
                area_of_interest=AOI, variables=["not_a_variable"],
                start=START, end=END, options={"seed": 1},
            )

    def test_safe_to_rerun_idempotently(self, provider):
        r1 = provider.fetch_observations(
            area_of_interest=AOI, variables=["precipitation"], start=START, end=END,
            options={"profile": "semi_arid", "seed": 11},
        )
        r2 = provider.fetch_observations(
            area_of_interest=AOI, variables=["precipitation"], start=START, end=END,
            options={"profile": "semi_arid", "seed": 11},
        )
        assert [o.model_dump() for o in r1.observations] == [o.model_dump() for o in r2.observations]

    def test_synthetic_label_mandatory(self, result):
        assert all(o.is_synthetic for o in result.observations)
        assert result.provider_code == "synthetic"

    def test_coverage_diagnostics_present(self, result):
        cov = result.coverage
        assert cov["requested_start"] == "2023-06-01"
        assert cov["requested_end"] == "2023-06-30"
        assert cov["profile"] == "temperate_seasonal"

    def test_provider_request_identifier(self, result):
        assert result.provider_request_id

"""Unit tests: canonical variable catalog + synthetic provider determinism."""

from datetime import UTC, datetime

import pytest

from app.core.errors import InvalidDateRange, UnsupportedVariable
from app.data_platform.contracts.observations import AreaOfInterest, validate_provider_request
from app.data_platform.contracts.variables import SUPPORTED_VARIABLE_CODES, VARIABLE_CATALOG
from app.data_platform.providers.synthetic.provider import (
    COVERAGE_END,
    COVERAGE_START,
    PROFILE_CODES,
    SyntheticProvider,
)

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)


class TestVariableCatalog:
    def test_codes_unique_and_sorted(self):
        assert len(SUPPORTED_VARIABLE_CODES) == len(set(SUPPORTED_VARIABLE_CODES))

    def test_core_variables_have_expected_units(self):
        assert VARIABLE_CATALOG["air_temperature_mean"].unit == "degC"
        assert VARIABLE_CATALOG["precipitation"].unit == "mm"
        assert VARIABLE_CATALOG["reference_et0"].unit == "mm"
        assert VARIABLE_CATALOG["soil_moisture_surface"].unit == "m3/m3"


class TestRequestValidation:
    def test_rejects_unsupported_variable(self):
        with pytest.raises(UnsupportedVariable):
            validate_provider_request(
                ["air_temperature_mean", "made_up_variable"],
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2023, 2, 1, tzinfo=UTC),
            )

    def test_rejects_inverted_range(self):
        with pytest.raises(InvalidDateRange):
            validate_provider_request(
                ["precipitation"],
                datetime(2023, 2, 1, tzinfo=UTC),
                datetime(2023, 1, 1, tzinfo=UTC),
            )

    def test_rejects_empty_variables(self):
        with pytest.raises(UnsupportedVariable):
            validate_provider_request(
                [], datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 2, 1, tzinfo=UTC)
            )


class TestSyntheticDeterminism:
    def _fetch(self, provider, **kw):
        return provider.fetch_observations(
            area_of_interest=kw.get("aoi", AOI),
            variables=kw.get("variables", ["air_temperature_mean", "precipitation"]),
            start=kw.get("start", datetime(2023, 3, 1, tzinfo=UTC)),
            end=kw.get("end", datetime(2023, 3, 31, tzinfo=UTC)),
            options=kw.get(
                "options", {"profile": "temperate_seasonal", "seed": 123}
            ),
        )

    def test_same_request_yields_identical_series(self):
        p1 = self._fetch(SyntheticProvider())
        p2 = self._fetch(SyntheticProvider())
        assert [o.model_dump() for o in p1.observations] == [o.model_dump() for o in p2.observations]

    def test_variable_order_does_not_change_output(self):
        a = self._fetch(SyntheticProvider(), variables=["air_temperature_mean", "precipitation"])
        b = self._fetch(SyntheticProvider(), variables=["precipitation", "air_temperature_mean"])
        a_temp = [o.model_dump() for o in a.observations if o.variable_code == "air_temperature_mean"]
        b_temp = [o.model_dump() for o in b.observations if o.variable_code == "air_temperature_mean"]
        assert a_temp == b_temp

    def test_different_seed_changes_values(self):
        a = self._fetch(SyntheticProvider(), options={"profile": "temperate_seasonal", "seed": 1})
        b = self._fetch(SyntheticProvider(), options={"profile": "temperate_seasonal", "seed": 2})
        a_vals = [o.value for o in a.observations if o.variable_code == "air_temperature_mean"]
        b_vals = [o.value for o in b.observations if o.variable_code == "air_temperature_mean"]
        assert a_vals != b_vals

    def test_all_rows_labelled_synthetic(self):
        result = self._fetch(SyntheticProvider())
        assert all(o.is_synthetic for o in result.observations)
        assert all(o.metadata["purpose"] == "software_testing_fixture" for o in result.observations)
        assert all(o.metadata["generator_version"] for o in result.observations)
        assert "SYNTHETIC" in result.provenance.attribution_text.upper()

    def test_missing_values_are_none_with_missing_status(self):
        # Large range ensures the deterministic gap generator fires.
        result = self._fetch(
            SyntheticProvider(),
            start=datetime(2022, 1, 1, tzinfo=UTC),
            end=datetime(2022, 12, 31, tzinfo=UTC),
            variables=["precipitation"],
        )
        missing = [o for o in result.observations if o.quality_status == "missing"]
        assert missing, "expected deterministic synthetic gaps"
        assert all(o.value is None for o in missing)
        assert all(o.quality_flags for o in missing)

    def test_profiles_differ_meaningfully(self):
        # Arid fixture must have far less rainfall than temperate (fixture sanity).
        def annual_total(profile):
            r = SyntheticProvider().fetch_observations(
                area_of_interest=AOI,
                variables=["precipitation"],
                start=datetime(2023, 1, 1, tzinfo=UTC),
                end=datetime(2023, 12, 31, tzinfo=UTC),
                options={"profile": profile, "seed": 9},
            )
            return sum(o.value or 0 for o in r.observations)

        assert annual_total("arid_irrigated") < annual_total("temperate_seasonal") * 0.35

    def test_outside_coverage_rejected(self):
        with pytest.raises(InvalidDateRange):
            self._fetch(SyntheticProvider(), start=datetime(2014, 12, 31, tzinfo=UTC))
        with pytest.raises(InvalidDateRange):
            self._fetch(SyntheticProvider(), end=datetime(2025, 1, 2, tzinfo=UTC))

    def test_unknown_profile_rejected(self):
        with pytest.raises(InvalidDateRange, match="profile"):
            self._fetch(SyntheticProvider(), options={"profile": "moon_base", "seed": 1})

    def test_range_longer_than_four_years_rejected(self):
        with pytest.raises(InvalidDateRange, match="4 years"):
            self._fetch(
                SyntheticProvider(),
                start=datetime(2016, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 1, tzinfo=UTC),
            )

    def test_all_five_profiles_available(self):
        assert PROFILE_CODES == sorted(
            ["temperate_seasonal", "mediterranean_dry_summer", "semi_arid", "tropical_seasonal", "arid_irrigated"]
        )

    def test_daily_time_support_preserved(self):
        result = self._fetch(SyntheticProvider())
        assert all(o.time_support == "daily" for o in result.observations)
        assert result.provenance.product_version == "v1"
        assert result.provenance.provider_code == "synthetic"

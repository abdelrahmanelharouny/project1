"""Open-Meteo provider contract suite (Master §12).

The same contract items the synthetic provider passes — verified for the
first REAL provider, with httpx mocked so the suite never needs a network.
A separate opt-in live smoke test exists for the real API.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.errors import CropTwistError
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    EnvironmentalDataProvider,
)
from app.data_platform.contracts.variables import VARIABLE_CATALOG
from app.data_platform.providers.open_meteo import provider as om_module
from app.data_platform.providers.open_meteo.provider import OpenMeteoProvider

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)
START = datetime(2023, 6, 1, tzinfo=UTC)
END = datetime(2023, 6, 30, tzinfo=UTC)


def _payload(start: datetime, end: datetime) -> dict[str, Any]:
    days = []
    cursor = start.replace(hour=0)
    while cursor <= end:
        days.append(cursor.date().isoformat())
        cursor += __import__("datetime").timedelta(days=1)
    return {
        "latitude": 31.0369,
        "longitude": 31.0676,
        "elevation": 3.0,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "daily_units": {"temperature_2m_mean": "°C", "precipitation_sum": "mm", "et0_fao_evapotranspiration": "mm"},
        "daily": {
            "time": days,
            "temperature_2m_mean": [16.0 for _ in days],
            "precipitation_sum": [1.5 for _ in days],
            "et0_fao_evapotranspiration": [3.1 for _ in days],
        },
    }


@pytest.fixture()
def provider(monkeypatch):
    def responder(params):
        import datetime as dt

        start = dt.date.fromisoformat(params["start_date"])
        end = dt.date.fromisoformat(params["end_date"])
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "text": "{}",
                "headers": {"content-type": "application/json"},
                "json": staticmethod(lambda: _payload(
                    datetime(start.year, start.month, start.day, tzinfo=UTC),
                    datetime(end.year, end.month, end.day, tzinfo=UTC),
                )),
            },
        )()

    monkeypatch.setattr(om_module.httpx, "get", lambda url, params=None, timeout=None: responder(params))
    return OpenMeteoProvider()


@pytest.fixture()
def result(provider):
    return provider.fetch_observations(
        area_of_interest=AOI,
        variables=["air_temperature_mean", "precipitation", "reference_et0"],
        start=START,
        end=END,
        options={"model": "era5"},
    )


class TestOpenMeteoContractSuite:
    def test_implements_provider_protocol(self, provider):
        assert isinstance(provider, EnvironmentalDataProvider)

    def test_returns_valid_canonical_objects(self, result):
        assert len(result.observations) == 30 * 3
        for obs in result.observations:
            obs.model_validate(obs.model_dump())
            assert obs.observed_at.tzinfo is not None
            assert obs.period_start <= obs.observed_at <= obs.period_end

    def test_includes_provenance(self, result):
        p = result.provenance
        assert p.provider_code == "open_meteo"
        assert p.product_code in ("era5_land", "era5")
        assert p.product_version
        assert "Open-Meteo" in p.attribution_text
        assert p.known_limitations
        assert p.license_name

    def test_includes_units_matching_catalog(self, result):
        for obs in result.observations:
            assert obs.unit == VARIABLE_CATALOG[obs.variable_code].unit

    def test_preserves_native_temporal_support(self, result):
        assert all(o.time_support == "daily" for o in result.observations)

    def test_records_explicit_product_selection(self, result):
        # Model choice is explicit and recorded per observation (Master §11.1-A).
        assert all(o.metadata["model"] == "era5" for o in result.observations)
        assert all("native_variable" in o.metadata for o in result.observations)
        assert all("conversion" in o.metadata for o in result.observations)
        assert all(o.metadata["timezone_basis"] == "GMT" for o in result.observations)

    def test_missing_never_zero_fabricated(self, provider, monkeypatch):
        def responder(params):
            body = _payload(START, END)
            body["daily"]["precipitation_sum"] = [None] * len(body["daily"]["time"])
            return type(
                "R",
                (),
                {
                    "status_code": 200,
                    "text": "{}",
                    "headers": {"content-type": "application/json"},
                    "json": staticmethod(lambda: body),
                },
            )()

        monkeypatch.setattr(om_module.httpx, "get", lambda url, params=None, timeout=None: responder(params))
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["precipitation"], start=START, end=END, options={"model": "era5"}
        )
        assert all(o.value is None for o in result.observations)
        assert all(o.quality_status == "missing" for o in result.observations)
        assert all(
            any(f["flag_code"] == "OPENMETEO_NULL" for f in o.quality_flags) for o in result.observations
        )

    def test_rejects_invalid_date_ranges(self, provider):
        with pytest.raises(CropTwistError):
            provider.fetch_observations(
                area_of_interest=AOI, variables=["precipitation"], start=END, end=START
            )

    def test_rejects_unsupported_variables(self, provider):
        with pytest.raises(CropTwistError):
            provider.fetch_observations(
                area_of_interest=AOI, variables=["not_a_variable"], start=START, end=END
            )

    def test_safe_to_rerun_idempotently(self, provider):
        r1 = provider.fetch_observations(
            area_of_interest=AOI, variables=["precipitation"], start=START, end=END, options={"model": "era5"}
        )
        r2 = provider.fetch_observations(
            area_of_interest=AOI, variables=["precipitation"], start=START, end=END, options={"model": "era5"}
        )
        assert [o.model_dump() for o in r1.observations] == [o.model_dump() for o in r2.observations]

    def test_real_data_is_not_labelled_synthetic(self, result):
        assert all(not o.is_synthetic for o in result.observations)
        assert all(o.evidence_class == "reanalysis_model_estimate" for o in result.observations)

    def test_coverage_diagnostics_present(self, result):
        cov = result.coverage
        assert cov["requested_start"] == "2023-06-01"
        assert cov["requested_end"] == "2023-06-30"
        assert cov["chunks"]
        assert cov["grid"]["grid_latitude"] is not None

    def test_provider_request_identifier(self, result):
        assert result.provider_request_id

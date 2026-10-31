"""Unit tests for the Open-Meteo provider — no network (httpx is mocked)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.errors import InvalidDateRange, ProviderRequestError, UnsupportedVariable
from app.data_platform.contracts.observations import AreaOfInterest
from app.data_platform.providers.open_meteo import provider as om_module
from app.data_platform.providers.open_meteo.provider import (
    DAILY_VARIABLE_MAP,
    MODELS,
    OpenMeteoProvider,
    _year_chunks,
)

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 3, tzinfo=UTC)


def sample_payload(start: datetime, end: datetime, *, null_wind_on: set[str] | None = None) -> dict[str, Any]:
    null_wind_on = null_wind_on or set()
    days = []
    cursor = start.replace(hour=0)
    while cursor <= end:
        days.append(cursor.date().isoformat())
        cursor += timedelta(days=1)
    return {
        "latitude": 31.0369,
        "longitude": 31.0676,
        "elevation": 3.0,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "daily_units": {
            "time": "iso8601",
            "temperature_2m_mean": "°C",
            "precipitation_sum": "mm",
            "wind_speed_10m_mean": "km/h",
        },
        "daily": {
            "time": days,
            "temperature_2m_mean": [16.6 for _ in days],
            "temperature_2m_min": [10.5 for _ in days],
            "temperature_2m_max": [22.7 for _ in days],
            "precipitation_sum": [0.2 for _ in days],
            "et0_fao_evapotranspiration": [2.2 for _ in days],
            "soil_moisture_0_to_7cm_mean": [0.14 for _ in days],
            "wind_speed_10m_mean": [
                None if d in null_wind_on else 5.8 for d in days
            ],
        },
    }


class _FakeResponse:
    def __init__(self, body: dict[str, Any], status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.text = str(body)
        self.headers = {"content-type": "application/json"}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _install_mock(monkeypatch, responder):
    calls: list[dict[str, Any]] = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return responder(params)

    monkeypatch.setattr(om_module.httpx, "get", fake_get)
    return calls


class TestChunking:
    def test_short_range_single_chunk(self):
        chunks = _year_chunks(START, END, max_years=10)
        assert chunks == [(START, END)]

    def test_multi_year_range_chunked_by_calendar(self):
        start = datetime(2020, 5, 10, tzinfo=UTC)
        end = datetime(2024, 2, 1, tzinfo=UTC)
        chunks = _year_chunks(start, end, max_years=2)
        assert chunks[0][0] == start
        assert chunks[0][1] == datetime(2021, 12, 31, tzinfo=UTC)
        assert chunks[-1][1] == end
        # adjacent, no overlap, no gap
        for (s1, e1), (s2, _e2) in zip(chunks, chunks[1:]):
            assert (s2 - e1).days == 1

    def test_max_years_one(self):
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end = datetime(2022, 12, 31, tzinfo=UTC)
        chunks = _year_chunks(start, end, max_years=1)
        assert len(chunks) == 3


class TestVariableMap:
    def test_all_catalog_units_match(self):
        from app.data_platform.contracts.variables import VARIABLE_CATALOG

        for vcode in DAILY_VARIABLE_MAP:
            assert vcode in VARIABLE_CATALOG, f"{vcode} missing from catalog"

    def test_wind_conversion_factor(self):
        _native, native_unit, conversion = DAILY_VARIABLE_MAP["wind_speed_10m"]
        assert native_unit == "km/h"
        assert conversion == ("div", 3.6)


class TestFetchWithMockedHttp:
    def test_happy_path_mapping_and_conversion(self, monkeypatch):
        calls = _install_mock(monkeypatch, lambda params: _FakeResponse(sample_payload(START, END)))
        provider = OpenMeteoProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["air_temperature_mean", "precipitation", "wind_speed_10m"],
            start=START,
            end=END,
            options={"model": "era5"},
        )
        assert len(result.observations) == 3 * 3  # 3 days x 3 variables
        temps = [o for o in result.observations if o.variable_code == "air_temperature_mean"]
        assert all(o.value == 16.6 for o in temps)
        assert all(o.unit == "degC" for o in temps)
        winds = [o for o in result.observations if o.variable_code == "wind_speed_10m"]
        assert all(abs(o.value - 5.8 / 3.6) < 1e-3 for o in winds)
        assert all(o.unit == "m/s" for o in winds)
        assert all(o.evidence_class == "reanalysis_model_estimate" for o in result.observations)
        assert all(not o.is_synthetic for o in result.observations)
        assert all(o.spatial_support_type == "grid_cell" for o in result.observations)
        # one call because range is short; request used the explicit model
        assert len(calls) == 1
        assert calls[0]["params"]["models"] == "era5"
        assert calls[0]["params"]["timezone"] == "UTC"
        # provenance + coverage diagnostics
        assert result.provenance.provider_code == "open_meteo"
        assert result.provenance.product_code == "era5"
        assert result.provenance.attribution_text and result.provenance.known_limitations
        assert result.coverage["model"] == "era5"
        assert result.coverage["grid"]["grid_latitude"] == 31.0369
        assert result.coverage["grid"]["timezone_basis"] == "GMT"

    def test_null_becomes_missing_with_flag(self, monkeypatch):
        def responder(params):
            body = sample_payload(START, END)
            body["daily"]["temperature_2m_mean"] = [None if d == "2024-01-02" else 16.6 for d in body["daily"]["time"]]
            return _FakeResponse(body)

        _install_mock(monkeypatch, responder)
        provider = OpenMeteoProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["air_temperature_mean"],
            start=START,
            end=END,
            options={},
        )
        missing = [o for o in result.observations if o.value is None]
        assert len(missing) == 1
        assert missing[0].quality_status == "missing"
        assert missing[0].quality_flags[0]["flag_code"] == "OPENMETEO_NULL"
        assert missing[0].observed_at.date().isoformat() == "2024-01-02"

    def test_upstream_error_body_raises_structured(self, monkeypatch):
        _install_mock(
            monkeypatch,
            lambda params: _FakeResponse({"error": True, "reason": "Invalid value: out of range"}, 400),
        )
        with pytest.raises(ProviderRequestError):
            OpenMeteoProvider().fetch_observations(
                area_of_interest=AOI, variables=["precipitation"], start=START, end=END, options={"model": "era5"}
            )

    def test_out_of_coverage_start_rejected(self):
        with pytest.raises(InvalidDateRange):
            OpenMeteoProvider().fetch_observations(
                area_of_interest=AOI,
                variables=["precipitation"],
                start=datetime(1939, 1, 1, tzinfo=UTC),
                end=datetime(1939, 2, 1, tzinfo=UTC),
                options={"model": "era5"},
            )

    def test_unknown_model_rejected(self):
        with pytest.raises(UnsupportedVariable):
            OpenMeteoProvider().fetch_observations(
                area_of_interest=AOI,
                variables=["precipitation"],
                start=START,
                end=END,
                options={"model": "best_match"},
            )

    def test_unsupported_variables_only_rejected(self):
        with pytest.raises(UnsupportedVariable):
            OpenMeteoProvider().fetch_observations(
                area_of_interest=AOI,
                variables=["soil_ph"],
                start=START,
                end=END,
            )

    def test_partial_support_warns_but_ingests(self, monkeypatch):
        _install_mock(monkeypatch, lambda params: _FakeResponse(sample_payload(START, END)))
        result = OpenMeteoProvider().fetch_observations(
            area_of_interest=AOI,
            variables=["precipitation", "soil_ph"],
            start=START,
            end=END,
            options={"model": "era5"},
        )
        assert any("soil_ph" in w for w in result.warnings)
        assert result.coverage["unsupported_variables_requested"] == ["soil_ph"]

    def test_models_metadata(self):
        provider = OpenMeteoProvider()
        models = {m["code"] for m in provider.models()}
        assert models == set(MODELS)
        assert provider.supported_variables() == sorted(DAILY_VARIABLE_MAP)


class TestModelVariableAvailability:
    def test_wind_with_era5_land_only_fails_fast(self):
        with pytest.raises(UnsupportedVariable):
            OpenMeteoProvider().fetch_observations(
                area_of_interest=AOI,
                variables=["wind_speed_10m"],
                start=START,
                end=END,
                options={"model": "era5_land"},
            )

    def test_wind_with_era5_land_mixed_is_never_requested(self, monkeypatch):
        """Audit regression: variables the selected model does not natively
        publish must NOT be requested — relying on upstream nulls would ingest
        ERA5-backed values under the era5_land product label if the archive
        ever backfills them. Only model-native variables may be fetched."""
        calls = _install_mock(monkeypatch, lambda params: _FakeResponse(sample_payload(START, END)))
        result = OpenMeteoProvider().fetch_observations(
            area_of_interest=AOI,
            variables=["air_temperature_mean", "wind_speed_10m"],
            start=START,
            end=END,
            options={"model": "era5_land"},
        )
        assert any(
            "not published by model era5_land" in w and "wind_speed_10m" in w for w in result.warnings
        )
        # the non-native series is absent from the upstream request entirely
        for call in calls:
            daily = call["params"]["daily"].split(",")
            assert "wind_speed_10m_mean" not in daily
            assert "temperature_2m_mean" in daily
        # and no wind observations are fabricated or recorded
        assert all(o.variable_code != "wind_speed_10m" for o in result.observations)
        assert result.coverage["variables_not_requested"] == ["wind_speed_10m"]

    def test_native_variables_requested_for_selected_model(self, monkeypatch):
        calls = _install_mock(monkeypatch, lambda params: _FakeResponse(sample_payload(START, END)))
        result = OpenMeteoProvider().fetch_observations(
            area_of_interest=AOI,
            variables=["precipitation", "reference_et0", "wind_speed_10m"],
            start=START,
            end=END,
            options={"model": "era5"},
        )
        codes = {o.variable_code for o in result.observations}
        assert {"precipitation", "reference_et0", "wind_speed_10m"} <= codes
        for call in calls:
            daily = call["params"]["daily"].split(",")
            assert "precipitation_sum" in daily
            assert "et0_fao_evapotranspiration" in daily
            assert "wind_speed_10m_mean" in daily
        assert result.coverage["variables_not_requested"] == []

    def test_chunks_never_overlap_nor_gap(self):
        """Audit regression: aggregation must never double-count overlapping
        request windows; chunks are contiguous and calendar-aligned."""
        start = datetime(2015, 3, 14, tzinfo=UTC)
        end = datetime(2024, 7, 2, tzinfo=UTC)
        chunks = _year_chunks(start, end, max_years=3)
        assert chunks[0][0] == start and chunks[-1][1] == end
        for (s1, e1), (s2, _e2) in zip(chunks, chunks[1:]):
            assert (s2 - e1).days == 1
            assert e1 <= s2

    def test_models_report_per_model_variables(self):
        items = {m["code"]: set(m["variables"]) for m in OpenMeteoProvider().models()}
        assert "wind_speed_10m" not in items["era5_land"]
        assert "precipitation" not in items["era5_land"]
        assert "soil_moisture_surface" in items["era5_land"]
        assert items["era5"] == {
            "air_temperature_mean",
            "air_temperature_min",
            "air_temperature_max",
            "precipitation",
            "reference_et0",
            "soil_moisture_surface",
            "wind_speed_10m",
        }

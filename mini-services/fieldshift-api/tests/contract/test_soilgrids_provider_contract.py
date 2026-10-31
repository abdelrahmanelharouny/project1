"""SoilGrids WCS provider contract tests (M3) — network fully mocked.

The WCS responses are synthesized as real GeoTIFF bytes built with rasterio,
so the provider's parsing path (MemoryFile, nodata, quantiles) is exercised
end to end without touching ISRIC servers.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.core.errors import FieldShiftError, ProviderRequestError, ProviderUnavailable, UnsupportedVariable
from app.data_platform.contracts.observations import AreaOfInterest, EnvironmentalDataProvider
from app.data_platform.contracts.variables import VARIABLE_CATALOG
from app.data_platform.providers.soilgrids import provider as sg_module
from app.data_platform.providers.soilgrids.provider import COVERAGE_BY_VARIABLE, SoilGridsProvider

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)
START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2020, 1, 1, tzinfo=UTC)

# constant raster values per quantile (native units)
Q_VALUES = {"Qmean": 12.0, "Q005": 8.0, "Q095": 16.0}


def _tiff_bytes(value: float, nodata: float = -32768.0) -> bytes:
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            width=8,
            height=8,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(31.3975, 31.1225, 0.0025, 0.0025),
            nodata=nodata,
        ) as dst:
            dst.write(np.full((8, 8), value, dtype=np.float32), 1)
        return memfile.read()


def _install_mock_client(monkeypatch, handler):
    real_client = httpx.Client

    def fake_client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(**kwargs)

    monkeypatch.setattr(sg_module.httpx, "Client", fake_client)


@pytest.fixture()
def provider(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        coverage_id = dict(request.url.params).__getitem__("coverageId")
        for suffix, value in Q_VALUES.items():
            if coverage_id.endswith(suffix):
                return httpx.Response(
                    200, content=_tiff_bytes(value), headers={"content-type": "image/tiff; subtype=geotiff"}
                )
        return httpx.Response(404, text="unknown coverage")

    _install_mock_client(monkeypatch, handler)
    return SoilGridsProvider()


class TestSoilGridsContract:
    def test_implements_provider_protocol(self, provider):
        assert isinstance(provider, EnvironmentalDataProvider)

    def test_supported_variables_are_in_catalog(self, provider):
        assert provider.supported_variables() == sorted(COVERAGE_BY_VARIABLE)
        assert all(v in VARIABLE_CATALOG for v in provider.supported_variables())

    def test_fetch_records_prediction_with_interval(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.value == pytest.approx(12.0, abs=1e-4)
        assert obs.unit == "g/kg"
        assert obs.evidence_class == "global_soil_prediction"
        assert obs.is_synthetic is False
        assert obs.spatial_support_type == "grid_cell"
        assert obs.metadata["depth"] == "0-5cm"
        assert obs.metadata["snapshot"].startswith("SoilGrids 2.0")
        # interval: (16 - 8) / 2 = 4
        assert obs.uncertainty_value == pytest.approx(4.0, abs=1e-4)
        assert obs.uncertainty_type == "prediction_interval_90_halfwidth"

    def test_ph_conversion_divides_by_ten(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_ph"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(1.2, abs=1e-4)  # 12.0 / 10
        assert obs.unit == "pH"
        assert "divide by 10" in obs.metadata["conversion"]

    def test_bulk_density_conversion(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_bulk_density"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(0.12, abs=1e-4)  # 12 cg/cm3 / 100
        assert obs.unit == "kg/dm3"

    def test_unsupported_variables_rejected(self, provider):
        with pytest.raises(UnsupportedVariable):
            provider.fetch_observations(
                area_of_interest=AOI, variables=["precipitation"], start=START, end=END
            )

    def test_partial_support_warns(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["soil_ph", "precipitation"],
            start=START,
            end=END,
        )
        assert len(result.observations) == 1
        assert any("precipitation" in w for w in result.warnings)

    def test_provenance_honest(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_clay_content"], start=START, end=END
        )
        p = result.provenance
        assert p.provider_code == "soilgrids"
        assert p.product_code == "soilgrids_2020_isric"
        assert "ISRIC" in p.attribution_text
        assert "not a soil sample" in p.known_limitations

    def test_wcs_unreachable_degrades_gracefully(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        _install_mock_client(monkeypatch, handler)
        with pytest.raises(ProviderUnavailable):
            SoilGridsProvider().fetch_observations(
                area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
            )

    def test_wcs_404_is_request_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="no such coverage")

        _install_mock_client(monkeypatch, handler)
        with pytest.raises(ProviderRequestError):
            SoilGridsProvider().fetch_observations(
                area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
            )

    def test_idempotent_rerun(self, provider):
        r1 = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_ph"], start=START, end=END
        )
        r2 = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_ph"], start=START, end=END
        )
        assert [o.model_dump() for o in r1.observations] == [o.model_dump() for o in r2.observations]

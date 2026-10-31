"""SoilGrids WCS provider contract tests (M3 audit revision) — network mocked.

The mock answers the WCS 1.0.0 GetCoverage shape the live maps.isric.org
service was verified to accept (2026-10-31): per-property `map` file,
`COVERAGE=<family>_0-5cm_<mean|Q0.05|Q0.95>`, `CRS`/`RESPONSE_CRS=EPSG:4326`,
`BBOX` in degrees and an explicit WIDTH/HEIGHT. Rasters are synthesized with
rasterio over exactly the requested bbox so masking, nodata accounting and
unit conversion are exercised end to end without touching ISRIC servers.
"""

from datetime import UTC, datetime
from typing import Callable

import httpx
import numpy as np
import pytest
import rasterio  # noqa: F401 — ensures rasterio backend present for the provider
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from app.core.errors import ProviderRequestError, ProviderUnavailable, UnsupportedVariable
from app.data_platform.contracts.observations import AreaOfInterest, EnvironmentalDataProvider
from app.data_platform.contracts.variables import VARIABLE_CATALOG
from app.data_platform.providers.soilgrids import provider as sg_module
from app.data_platform.providers.soilgrids.provider import (
    COVERAGE_BY_VARIABLE,
    COVERAGE_SUFFIXES,
    SoilGridsProvider,
)

AOI = AreaOfInterest(
    geometry_geojson={
        "type": "Polygon",
        "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
    }
)
START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2020, 1, 1, tzinfo=UTC)

# native (wire) values per coverage suffix, in the property's native unit
Q_VALUES = {"mean": 120.0, "Q0.05": 80.0, "Q0.95": 160.0}


def _tiff_bytes_for_request(value_fn: Callable[[float, float], float | None], bbox, width, height, epsg=4326) -> bytes:
    """Build a GeoTIFF over `bbox` with value_fn(x_center, y_center) per cell."""
    minx, miny, maxx, maxy = bbox
    tx = from_bounds(minx, miny, maxx, maxy, width=width, height=height)
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    xs = tx.c + (cols + 0.5) * tx.a
    ys = tx.f + (rows + 0.5) * tx.e
    values = np.full((height, width), -32768.0, dtype=np.float32)
    for row in range(height):
        for col in range(width):
            v = value_fn(float(xs[row, col]), float(ys[row, col]))
            if v is not None:
                values[row, col] = float(v)
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            crs=f"EPSG:{epsg}",
            transform=tx,
            nodata=-32768.0,
        ) as dst:
            dst.write(values, 1)
        return memfile.read()


def _install_mock_client(monkeypatch, handler):
    real_client = httpx.Client

    def fake_client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real_client(**kwargs)

    monkeypatch.setattr(sg_module.httpx, "Client", fake_client)


def _constant_value_fn(suffix: str) -> Callable[[float, float], float | None]:
    return lambda x, y: Q_VALUES[suffix]


@pytest.fixture()
def provider(monkeypatch):
    """Standard handler: constant per-quantile rasters; records every request."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = dict(request.url.params)
        coverage = params.get("COVERAGE", "")
        for suffix in COVERAGE_SUFFIXES:
            if coverage.endswith(f"_{suffix}"):
                bbox = tuple(float(v) for v in params["BBOX"].split(","))
                content = _tiff_bytes_for_request(
                    _constant_value_fn(suffix), bbox, int(params["WIDTH"]), int(params["HEIGHT"])
                )
                return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})
        return httpx.Response(404, text="unknown coverage")

    _install_mock_client(monkeypatch, handler)
    p = SoilGridsProvider()
    p._recorded_requests = requests  # type: ignore[attr-defined]
    return p


class TestSoilGridsRequestShape:
    def test_wcs_request_matches_live_service(self, provider):
        provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        reqs = provider._recorded_requests
        assert reqs, "provider must issue coverage requests"
        coverage_ids = []
        for r in reqs:
            params = dict(r.url.params)
            # live-verified request shape
            assert params["map"] == "/map/soc.map"
            assert params["SERVICE"] == "WCS"
            assert params["VERSION"] == "1.0.0"
            assert params["REQUEST"] == "GetCoverage"
            assert params["CRS"] == "EPSG:4326"
            assert params["RESPONSE_CRS"] == "EPSG:4326"
            assert params["FORMAT"] == "image/tiff"
            assert int(params["WIDTH"]) >= 1 and int(params["HEIGHT"]) >= 1
            coverage_ids.append(params["COVERAGE"])
        # live coverage-id naming (audit fix): <family>_<depth>_<suffix>
        assert set(coverage_ids) == {"soc_0-5cm_mean", "soc_0-5cm_Q0.05", "soc_0-5cm_Q0.95"}

    def test_ph_uses_phh2o_map_and_family(self, provider):
        provider.fetch_observations(area_of_interest=AOI, variables=["soil_ph"], start=START, end=END)
        maps = {dict(r.url.params)["map"] for r in provider._recorded_requests}
        ids = {dict(r.url.params)["COVERAGE"] for r in provider._recorded_requests}
        assert maps == {"/map/phh2o.map"}
        assert ids == {"phh2o_0-5cm_mean", "phh2o_0-5cm_Q0.05", "phh2o_0-5cm_Q0.95"}


class TestSoilGridsContract:
    def test_implements_provider_protocol(self, provider):
        assert isinstance(provider, EnvironmentalDataProvider)

    def test_supported_variables_are_in_catalog(self, provider):
        assert provider.supported_variables() == sorted(COVERAGE_BY_VARIABLE)
        assert all(v in VARIABLE_CATALOG for v in provider.supported_variables())

    def test_soc_unit_conversion_dgkg_to_gkg(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        assert len(result.observations) == 1
        obs = result.observations[0]
        # wire value 120 dg/kg -> 12.0 g/kg (audit fix: soc is dg/kg on the wire)
        assert obs.value == pytest.approx(12.0, abs=1e-4)
        assert obs.unit == "g/kg"
        assert obs.metadata["native_unit"] == "dg/kg"
        assert "divide by 10" in obs.metadata["conversion"]
        assert obs.evidence_class == "global_soil_prediction"
        assert obs.is_synthetic is False
        assert obs.spatial_support_type == "grid_cell"
        assert obs.spatial_resolution_m == 250.0
        assert obs.metadata["depth"] == "0-5cm"
        assert obs.metadata["snapshot"].startswith("SoilGrids 2.0")

    def test_prediction_interval_from_q005_q095(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        obs = result.observations[0]
        # raw interval 80..160 dg/kg -> 8..16 g/kg -> halfwidth 4.0
        assert obs.uncertainty_value == pytest.approx(4.0, abs=1e-4)
        # Deepening F-08: the value is the half-width of the MEAN of per-pixel
        # Q0.05..Q0.95 ranges — the honest label must not claim a formal
        # field-level 90% prediction interval.
        assert (
            obs.uncertainty_type
            == "mean_of_pixel_q05_q95_halfwidth_not_a_field_level_pi"
        )
        assert "NOT a formal field-level" in obs.metadata["uncertainty_semantics"]
        # quantile fractions are 0.05/0.95 (audit fix), not 0.005/0.095
        assert obs.metadata["quantiles_used"] == {"Q0.05": 0.05, "Q0.95": 0.95}
        assert obs.processing_version == "soilgrids-wcs-normalizer-v3"

    def test_ph_conversion_divides_by_ten(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_ph"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(12.0, abs=1e-4)  # 120 raw pH*10 / 10
        assert obs.unit == "pH"
        assert "divide by 10" in obs.metadata["conversion"]

    def test_bulk_density_conversion(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_bulk_density"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(1.2, abs=1e-4)  # 120 cg/cm3 / 100
        assert obs.unit == "kg/dm3"

    def test_sand_identity_no_conversion(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_sand_content"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(120.0, abs=1e-4)
        assert obs.unit == "g/kg"
        assert obs.metadata["conversion"] == "identity"

    def test_mean_clipped_to_field_polygon(self, monkeypatch):
        """Cells outside the field carry a different value; the field mean must
        never blend them in (audit fix: bbox dilution)."""
        inside = {"type": "Polygon", "coordinates": AOI.geometry_geojson["coordinates"]}

        def value_fn(x: float, y: float) -> float | None:
            minx, miny, maxx, maxy = 31.40, 31.10, 31.42, 31.12
            if minx < x < maxx and miny < y < maxy:
                return 100.0
            return 9999.0  # valid but clearly outside-field value

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            coverage = params.get("COVERAGE", "")
            if coverage.endswith("_mean"):
                fn = value_fn
            else:
                fn = _constant_value_fn(coverage.split("_")[-1])
            bbox = tuple(float(v) for v in params["BBOX"].split(","))
            content = _tiff_bytes_for_request(fn, bbox, int(params["WIDTH"]), int(params["HEIGHT"]))
            return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})

        _install_mock_client(monkeypatch, handler)
        result = SoilGridsProvider().fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        obs = result.observations[0]
        # 100 dg/kg inside -> 10 g/kg; 9999 outside must not contribute
        assert obs.value == pytest.approx(10.0, abs=0.5)
        cells = obs.metadata["cells"]
        assert cells["cells_in_field"] >= 1
        assert cells["valid_cell_ratio"] == 1.0
        assert cells["cell_selection"] == "cell_centre_in_polygon"

    def test_subcell_field_uses_all_touched_and_flags(self, monkeypatch):
        # ~20 m square — far below one native ~250 m cell, and positioned away
        # from any served-cell centre so the centre-in-polygon pass finds 0 cells
        tiny = AreaOfInterest(
            geometry_geojson={
                "type": "Polygon",
                "coordinates": [
                    [[31.4050, 31.1050], [31.4052, 31.1050], [31.4052, 31.1052], [31.4050, 31.1052], [31.4050, 31.1050]]
                ],
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            coverage = params.get("COVERAGE", "")
            suffix = next(s for s in COVERAGE_SUFFIXES if coverage.endswith(f"_{s}"))
            bbox = tuple(float(v) for v in params["BBOX"].split(","))
            content = _tiff_bytes_for_request(
                _constant_value_fn(suffix), bbox, int(params["WIDTH"]), int(params["HEIGHT"])
            )
            return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})

        _install_mock_client(monkeypatch, handler)
        result = SoilGridsProvider().fetch_observations(
            area_of_interest=tiny, variables=["soil_organic_carbon"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.metadata["cells"]["cell_selection"] == "all_touched (sub-grid field)"
        assert any(f["flag_code"] == "SOILGRIDS_SUBCELL_FIELD" for f in obs.quality_flags)
        assert any("smaller than one native" in w for w in result.warnings)

    def test_partial_nodata_flags_low_coverage(self, monkeypatch):
        """Nodata over most of the field -> low-coverage flag, mean over valid cells."""
        def value_fn(x: float, y: float) -> float | None:
            # right-hand three-quarters of the field columns are nodata
            if x > 31.4050:
                return None
            return 120.0

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            coverage = params.get("COVERAGE", "")
            suffix = next(s for s in COVERAGE_SUFFIXES if coverage.endswith(f"_{s}"))
            bbox = tuple(float(v) for v in params["BBOX"].split(","))
            content = _tiff_bytes_for_request(value_fn, bbox, int(params["WIDTH"]), int(params["HEIGHT"]))
            return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})

        _install_mock_client(monkeypatch, handler)
        result = SoilGridsProvider().fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        obs = result.observations[0]
        assert obs.value is not None
        cells = obs.metadata["cells"]
        assert cells["nodata_cells"] > 0
        assert cells["valid_cell_ratio"] < 0.5
        assert any(f["flag_code"] == "SOILGRIDS_LOW_CELL_COVERAGE" for f in obs.quality_flags)

    def test_all_nodata_is_warning_not_fabrication(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            bbox = tuple(float(v) for v in params["BBOX"].split(","))
            content = _tiff_bytes_for_request(lambda x, y: None, bbox, int(params["WIDTH"]), int(params["HEIGHT"]))
            return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})

        _install_mock_client(monkeypatch, handler)
        result = SoilGridsProvider().fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        assert result.observations == []
        assert any("no value recorded" in w for w in result.warnings)

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

    def test_metadata_records_native_crs_and_response_crs(self, provider):
        result = provider.fetch_observations(
            area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
        )
        obs = result.observations[0]
        assert "152160" in obs.metadata["native_crs"]
        assert obs.metadata["raster"]["response_crs"] == "EPSG:4326"

    def test_non_4326_response_rejected(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            bbox = tuple(float(v) for v in params["BBOX"].split(","))
            content = _tiff_bytes_for_request(
                lambda x, y: 120.0, bbox, int(params["WIDTH"]), int(params["HEIGHT"]), epsg=32633
            )
            return httpx.Response(200, content=content, headers={"content-type": "image/tiff"})

        _install_mock_client(monkeypatch, handler)
        with pytest.raises(ProviderRequestError, match="EPSG:4326"):
            SoilGridsProvider().fetch_observations(
                area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
            )

    def test_mapserver_xml_exception_is_request_error(self, monkeypatch):
        xml = (
            '<?xml version="1.0"?><ows:ExceptionReport>'
            "<ows:Exception><ows:ExceptionText>msWCSGetCoverage20(): error</ows:ExceptionText>"
            "</ows:Exception></ows:ExceptionReport>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=xml, headers={"content-type": "text/xml; charset=UTF-8"})

        _install_mock_client(monkeypatch, handler)
        with pytest.raises(ProviderRequestError):
            SoilGridsProvider().fetch_observations(
                area_of_interest=AOI, variables=["soil_organic_carbon"], start=START, end=END
            )

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

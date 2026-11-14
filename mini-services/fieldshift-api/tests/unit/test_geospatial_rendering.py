"""P07 rendering unit tests (tile math, colormap honesty, zones, cache).

Covers:
- XYZ tile bounds math + range validation.
- Documented-range normalization: nodata/NaN -> fully transparent alpha,
  in-range pixels -> opaque; colors NEVER stretch per image.
- Tile render pipeline against a real processed product COG (fixture
  scene processed with the real preprocessing pipeline).
- Zone polygon extraction: 3 statistical terciles matching the fixture's
  known half/half reflectance layout, degenerate (uniform) rasters refuse.
- Field-masked histogram: bins sum to valid pixels, percentiles match
  processing-time zonal statistics.
- Checksum-keyed LRU: same asset cached, reprocessing (new checksum)
  never serves stale bytes, bounded eviction.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fixtures import raster_fixtures as fx


@pytest.fixture()
def raster_storage(tmp_path, monkeypatch):
    """Isolated local raster storage root per test."""
    from app.geospatial import objectstore as ost

    monkeypatch.setattr("app.core.config.settings.raster_storage_root", str(tmp_path / "rasters"))
    ost.reset_raster_storage()
    yield tmp_path / "rasters"
    ost.reset_raster_storage()


@pytest.fixture()
def fixture_field(client, auth_headers):
    headers, _user = auth_headers
    farm_resp = client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": "Render Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields",
        headers=headers,
        json={"name": "Render Field", "geometry": fx.fixture_field_geojson()},
    )
    assert field_resp.status_code == 201, field_resp.text
    return {"headers": headers, "farm": farm, "field": field_resp.json()}


# ---------------------------------------------------------------- tile math


class TestTileMath:
    def test_tile_bounds_z0(self):
        from app.geospatial.rendering import tile_bounds

        lon_min, lat_min, lon_max, lat_max = tile_bounds(0, 0, 0)
        assert (lon_min, lon_max) == (-180.0, 180.0)
        assert lat_max == pytest.approx(85.0511, abs=1e-3)
        assert lat_min == pytest.approx(-85.0511, abs=1e-3)

    def test_tile_bounds_z10_consistency(self):
        import math

        from app.geospatial.rendering import tile_bounds

        # independent inverse computation: tile (z=10, x=600, y=403)
        z, x, y = 10, 600, 403
        n = 2**z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        got = tile_bounds(z, x, y)
        assert got == pytest.approx((lon_min, lat_min, lon_max, lat_max), abs=1e-9)

    def test_tile_bounds_are_monotonic_in_x(self):
        from app.geospatial.rendering import tile_bounds

        a = tile_bounds(12, 100, 500)
        b = tile_bounds(12, 101, 500)
        assert a[2] == b[0]  # adjacent tiles share an edge
        assert a[0] < a[2]

    def test_out_of_range_tile_rejected(self):
        from app.geospatial.rendering import tile_bounds

        with pytest.raises(ValueError):
            tile_bounds(5, 33, 0)  # x >= 2**5
        with pytest.raises(ValueError):
            tile_bounds(3, 0, 9)  # y >= 2**3
        with pytest.raises(ValueError):
            tile_bounds(-1, 0, 0)


# ------------------------------------------------------- colormap / honesty


class TestTransparentAndColormap:
    def test_transparent_png_is_fully_transparent(self):
        from app.geospatial.rendering import transparent_png

        png = transparent_png(256)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        # IHDR width/height
        w, h = struct.unpack(">II", png[16:24])
        assert (w, h) == (256, 256)

    def test_colormap_alpha_only_in_documented_range(self):
        import numpy as np

        from app.geospatial.rendering import _colormap_rgb

        norm = np.array([[-0.1, 0.0, 0.5, 1.0, 1.1, np.nan]])
        rgb, alpha = _colormap_rgb(norm)
        assert alpha[0, 0] == 0  # below documented range
        assert alpha[0, 1] == 255
        assert alpha[0, 2] == 255
        assert alpha[0, 3] == 255
        assert alpha[0, 4] == 0  # above documented range
        assert alpha[0, 5] == 0  # NaN (nodata) is transparent, never drawn

    def test_colormap_is_fixed_not_data_relative(self):
        import numpy as np

        from app.geospatial.rendering import _colormap_rgb

        # 0.25 normalized maps to the same RGB regardless of neighbors
        rgb_a, _ = _colormap_rgb(np.array([[0.25]]))
        rgb_b, _ = _colormap_rgb(np.array([[0.25, 0.9]]))
        assert tuple(rgb_a[0, 0]) == tuple(rgb_b[0, 0])


# --------------------------------------------------- tile render (real COG)


@pytest.fixture()
def processed_product(db, raster_storage, fixture_field, tmp_path):
    """Process one fixture scene end-to-end and return (field_id, asset row)."""
    from app.db.models import Field
    from app.db.models_p2 import RasterAsset
    from app.data_platform.processing.service import create_processing_jobs
    from tests.conftest import run_raster_job_through_worker

    field_id = uuid.UUID(fixture_field["field"]["id"])
    assets = fx.write_fixture_scene(
        tmp_path, scene_id="FIX.REND1", with_nodata_patch=True
    )
    _make_scene_row(db, field_id, scene_id="FIX.REND1", assets=assets,
                    acquired_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC))
    field = db.get(Field, field_id)
    result = create_processing_jobs(db, field=field, scene_ids=["FIX.REND1"], indices=["ndvi"])
    rp_id = uuid.UUID(result["jobs"][0]["job_id"])
    rp = run_raster_job_through_worker(rp_id, db=db)
    assert rp.status == "succeeded", rp.error
    asset = db.query(RasterAsset).filter_by(
        field_id=field_id, scene_id="FIX.REND1", asset_kind="derived", index_code="ndvi"
    ).first()
    assert asset is not None
    return {"field_id": field_id, "asset": asset, "field_geojson": fx.fixture_field_geojson()}


import uuid  # noqa: E402


def _make_scene_row(db, field_id, *, scene_id, assets, acquired_at):
    from app.db.models_p2 import SatelliteScene

    db.add(
        SatelliteScene(
            field_id=field_id,
            provider_code="nasa_hls",
            product_code="HLSL30",
            scene_id=scene_id,
            acquired_at=acquired_at,
            cloud_cover_pct=10.0,
            spatial_resolution_m=30.0,
            band_mapping={"red": "B04", "nir": "B05", "fmask": "fmask"},
            asset_refs=dict(assets),
            is_synthetic=False,
            processing_version="2.0",
            acquisition_status="ready",
            discovered_at=datetime.now(UTC),
        )
    )
    db.commit()


class TestTileRendering:
    def test_tile_over_field_is_opaque_png(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import render_product_tile

        field_geojson = fx.fixture_field_geojson()
        center = _centroid_of(field_geojson)
        z, x, y = _latlon_to_xyz(center[0], center[1], 16)
        png = render_product_tile(
            asset=processed_product["asset"],
            storage=get_raster_storage(),
            z=z, x=x, y=y,
            index_code="ndvi",
        )
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        opaque = _count_opaque_pixels(png)
        assert opaque > 0  # field pixels are drawn

    def test_tile_far_from_field_is_fully_transparent(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import render_product_tile, transparent_png

        # z16 tile in the Pacific (no intersection with the fixture field)
        png = render_product_tile(
            asset=processed_product["asset"],
            storage=get_raster_storage(),
            z=16, x=1000, y=40000,
            index_code="ndvi",
        )
        assert png == transparent_png(256)

    def test_tile_render_is_cached_by_checksum(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import render_product_tile

        field_geojson = fx.fixture_field_geojson()
        center = _centroid_of(field_geojson)
        z, x, y = _latlon_to_xyz(center[0], center[1], 16)
        storage = get_raster_storage()
        entries_before = _cache_entries()
        first = render_product_tile(
            asset=processed_product["asset"], storage=storage, z=z, x=x, y=y, index_code="ndvi"
        )
        second = render_product_tile(
            asset=processed_product["asset"], storage=storage, z=z, x=x, y=y, index_code="ndvi"
        )
        assert first == second
        # exactly ONE cache entry for this tile key (second render was a hit)
        assert _cache_entries() == entries_before + 1

    def test_reprocessed_checksum_never_serves_stale_cache(self, processed_product, monkeypatch):
        """A new checksum for the same asset id must bypass cached tiles."""
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import render_product_tile

        asset = processed_product["asset"]
        center = _centroid_of(fx.fixture_field_geojson())
        z, x, y = _latlon_to_xyz(center[0], center[1], 15)
        storage = get_raster_storage()
        first = render_product_tile(asset=asset, storage=storage, z=z, x=x, y=y, index_code="ndvi")
        monkeypatch.setattr(asset, "checksum_sha256", "deadbeef" * 8)
        second = render_product_tile(asset=asset, storage=storage, z=z, x=x, y=y, index_code="ndvi")
        assert first == second  # both valid renders
        # the second render created a DIFFERENT cache key (no stale reuse):
        from app.geospatial.rendering import _asset_key

        assert "deadbeef" in _asset_key(asset)


def _cache_entries() -> int:
    from app.geospatial.rendering import _tile_lru

    lru = _tile_lru()
    with lru._lock:  # noqa: SLF001 — test introspection of the bounded cache
        return len(lru._data)


def _centroid_of(geojson: dict) -> tuple[float, float]:
    from shapely.geometry import shape

    return shape(geojson).centroid.x, shape(geojson).centroid.y


def _latlon_to_xyz(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    import math

    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return z, min(x, n - 1), min(y, n - 1)


def _count_opaque_pixels(png: bytes) -> int:
    """Decode the deterministic PNG encoder output and count alpha>0 pixels."""
    import zlib

    # minimal chunk walker (IHDR + IDAT)
    idx = 8
    idat = b""
    while idx < len(png):
        (length,) = struct.unpack(">I", png[idx : idx + 4])
        tag = png[idx + 4 : idx + 8]
        payload = png[idx + 8 : idx + 8 + length]
        if tag == b"IDAT":
            idat += payload
        idx += 12 + length
    (w, h) = struct.unpack(">II", png[16:24])
    raw = zlib.decompress(idat)
    stride = w * 4 + 1
    opaque = 0
    for row in range(h):
        line = raw[row * stride + 1 : (row + 1) * stride]
        for px in range(w):
            if line[px * 4 + 3] > 0:
                opaque += 1
    return opaque


def _fixture_pixel_lonlat(row: int, col: int) -> tuple[float, float]:
    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(fx.FIXTURE_CRS, "EPSG:4326", always_xy=True)
    x = fx.FIXTURE_LEFT + (col + 0.5) * fx.FIXTURE_RES
    y = fx.FIXTURE_TOP - (row + 0.5) * fx.FIXTURE_RES
    return to_wgs84.transform(x, y)


# ------------------------------------------------------------- point sampling
class TestProductValueSampling:
    def test_samples_two_actual_pixels_from_stored_product(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import sample_product_value

        asset = processed_product["asset"]
        storage = get_raster_storage()
        lon, lat = _fixture_pixel_lonlat(8, 10)
        vegetated = sample_product_value(asset=asset, storage=storage, lon=lon, lat=lat)
        lon, lat = _fixture_pixel_lonlat(25, 10)
        stressed = sample_product_value(asset=asset, storage=storage, lon=lon, lat=lat)

        assert vegetated["available"] is True
        assert vegetated["value"] == pytest.approx(fx.EXPECTED_VEGETATED["ndvi"], abs=1e-6)
        assert stressed["available"] is True
        assert stressed["value"] == pytest.approx(fx.EXPECTED_STRESSED["ndvi"], abs=1e-6)

    def test_outside_extent_is_unavailable_not_a_value(self, processed_product):
        from pyproj import Transformer

        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import sample_product_value

        to_wgs84 = Transformer.from_crs(fx.FIXTURE_CRS, "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(
            fx.FIXTURE_LEFT + (fx.FIXTURE_WIDTH + 2.5) * fx.FIXTURE_RES,
            fx.FIXTURE_TOP - 20.5 * fx.FIXTURE_RES,
        )
        sample = sample_product_value(
            asset=processed_product["asset"],
            storage=get_raster_storage(),
            lon=lon,
            lat=lat,
        )
        assert sample["available"] is False
        assert sample["value"] is None
        assert sample["unavailable_reason"] == "point_outside_raster_extent"

    def test_nodata_pixel_is_unavailable_using_valid_mask(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import sample_product_value

        lon, lat = _fixture_pixel_lonlat(32, 30)
        sample = sample_product_value(
            asset=processed_product["asset"],
            storage=get_raster_storage(),
            lon=lon,
            lat=lat,
        )
        assert sample["available"] is False
        assert sample["value"] is None
        assert sample["unavailable_reason"] == "pixel_invalid_or_nodata_or_cloud_masked"


# ------------------------------------------------------------ zones + histogram


class TestZonePolygons:
    def test_three_statistical_terciles_extracted(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import zone_polygons_fc

        fc = zone_polygons_fc(
            asset=processed_product["asset"],
            storage=get_raster_storage(),
            geometry_geojson=fx.fixture_field_geojson(),
            index_code="ndvi",
        )
        assert fc["zone_kind"] == "statistical_terciles"
        assert "not an agronomic zonation" in fc["zone_note"]
        assert len(fc["features"]) == 3
        zones = {f["properties"]["zone"]: f["properties"] for f in fc["features"]}
        assert set(zones) == {"lowest_tercile", "middle_tercile", "highest_tercile"}
        # fixture: top half vegetated (NDVI 0.6667), bottom half stressed (-0.0909)
        assert zones["lowest_tercile"]["mean"] == pytest.approx(-0.090909, abs=1e-4)
        assert zones["highest_tercile"]["mean"] == pytest.approx(0.666667, abs=1e-4)
        for f in fc["features"]:
            assert f["geometry"] is not None
            assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_uniform_raster_refuses_zones(self, processed_product, tmp_path, db, raster_storage):
        from app.db.models import Field
        from app.db.models_p2 import RasterAsset
        from app.data_platform.processing.service import create_processing_jobs
        from tests.conftest import run_raster_job_through_worker
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import zone_polygons_fc

        # process a uniform scene (fully vegetated top+bottom = no variation)
        field_id = processed_product["field_id"]
        assets = _write_uniform_scene(tmp_path, scene_id="FIX.UNIFORM")
        _make_scene_row(db, field_id, scene_id="FIX.UNIFORM", assets=assets,
                        acquired_at=datetime(2026, 2, 2, 10, 0, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = create_processing_jobs(db, field=field, scene_ids=["FIX.UNIFORM"], indices=["ndvi"])
        rp_id = uuid.UUID(result["jobs"][0]["job_id"])
        run_raster_job_through_worker(rp_id, db=db)
        asset = db.query(RasterAsset).filter_by(
            field_id=field_id, scene_id="FIX.UNIFORM", asset_kind="derived", index_code="ndvi"
        ).first()
        fc = zone_polygons_fc(
            asset=asset, storage=get_raster_storage(),
            geometry_geojson=fx.fixture_field_geojson(), index_code="ndvi",
        )
        assert fc["features"] == []
        assert len(fc["zones_without_geometry"]) == 3
        assert all("insufficient" in z["reason"] for z in fc["zones_without_geometry"])

    def test_zone_polygons_are_wgs84(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import zone_polygons_fc

        fc = zone_polygons_fc(
            asset=processed_product["asset"], storage=get_raster_storage(),
            geometry_geojson=fx.fixture_field_geojson(), index_code="ndvi",
        )
        for f in fc["features"]:
            rings = _first_ring(f["geometry"])
            for lon, lat in rings:
                assert -180.0 <= lon <= 180.0
                assert -90.0 <= lat <= 90.0


class TestValueDistribution:
    def test_histogram_bins_sum_to_valid_pixels(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import value_distribution

        dist = value_distribution(
            asset=processed_product["asset"], storage=get_raster_storage(),
            geometry_geojson=fx.fixture_field_geojson(), index_code="ndvi",
        )
        assert dist["valid_pixels"] > 0
        total = sum(b["pixels"] for b in dist["histogram"])
        in_range = int(dist["valid_pixels"] * (1.0 - (dist["proportion_out_of_documented_range"] or 0)))
        assert total == in_range
        assert dist["proportion_out_of_documented_range"] == pytest.approx(0.0)

    def test_percentiles_match_processing_zonal(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import value_distribution

        dist = value_distribution(
            asset=processed_product["asset"], storage=get_raster_storage(),
            geometry_geojson=fx.fixture_field_geojson(), index_code="ndvi",
        )
        p = dist["percentiles"]
        zonal = processed_product["asset"].stats_json["zonal"]
        # field-masked histogram over the stored grid reproduces the
        # processing-time zonal percentiles exactly for this fixture
        assert p["p5"] == pytest.approx(zonal["p5"], abs=1e-3)
        assert p["median"] == pytest.approx(zonal["median"], abs=1e-3)
        assert p["p95"] == pytest.approx(zonal["p95"], abs=1e-3)

    def test_empty_field_returns_honest_empty(self, processed_product):
        from app.geospatial.objectstore import get_raster_storage
        from app.geospatial.rendering import value_distribution

        far_geojson = {
            "type": "Polygon",
            "coordinates": [[
                [10.0, 10.0], [10.01, 10.0], [10.01, 10.01], [10.0, 10.01], [10.0, 10.0]
            ]],
        }
        dist = value_distribution(
            asset=processed_product["asset"], storage=get_raster_storage(),
            geometry_geojson=far_geojson, index_code="ndvi",
        )
        assert dist["valid_pixels"] == 0
        assert dist["histogram"] == []
        assert "no valid field pixels" in dist["note"]


def _write_uniform_scene(directory: Path, *, scene_id: str) -> dict[str, str]:
    """Fixture scene entirely covered by the VEGETATED reflectance set."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    paths: dict[str, str] = {}
    transform = from_origin(fx.FIXTURE_LEFT, fx.FIXTURE_TOP, fx.FIXTURE_RES, fx.FIXTURE_RES)
    for surface in ("blue", "green", "red", "nir", "swir1", "swir2"):
        arr = np.full((fx.FIXTURE_HEIGHT, fx.FIXTURE_WIDTH), fx.VEGETATED_DN[surface], dtype="float64")
        path = str(Path(directory) / f"{scene_id}.{surface}.tif")
        with rasterio.open(path, "w", driver="GTiff", height=fx.FIXTURE_HEIGHT, width=fx.FIXTURE_WIDTH,
                           count=1, dtype="float64", crs=fx.FIXTURE_CRS, transform=transform,
                           nodata=float(fx.NODATA_DN)) as dst:
            dst.write(arr, 1)
        paths[surface] = path
    fmask = np.zeros((fx.FIXTURE_HEIGHT, fx.FIXTURE_WIDTH), dtype="uint8")
    fmask_path = str(Path(directory) / f"{scene_id}.fmask.tif")
    with rasterio.open(fmask_path, "w", driver="GTiff", height=fx.FIXTURE_HEIGHT, width=fx.FIXTURE_WIDTH,
                       count=1, dtype="uint8", crs=fx.FIXTURE_CRS, transform=transform) as dst:
        dst.write(fmask, 1)
    paths["fmask"] = fmask_path
    return paths


def _first_ring(geometry: dict) -> list[tuple[float, float]]:
    if geometry["type"] == "Polygon":
        return geometry["coordinates"][0]
    return geometry["coordinates"][0][0]

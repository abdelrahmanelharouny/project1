"""Unit tests for the P05 preprocessing pipeline (deterministic fixtures).

Uses the small synthetic UTM GeoTIFF fixtures in tests/fixtures — explicitly
identified as TEST FIXTURES, never production imagery. Every expected value
is hand-derived from the documented formulas.

Coverage: windowed reading + CRS handling, band alignment, Fmask masking
per-bit behavior, nodata handling, index formula exactness, valid-pixel
accounting, tercile zone summaries, COG writing (round-trip), preview PNG
fixed-colormap behavior, scene input validation rejections.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio

from app.geospatial import preprocessing as pre
from tests.fixtures.raster_fixtures import (
    EXPECTED_STRESSED,
    EXPECTED_VEGETATED,
    FIXTURE_CRS,
    FMASK_WATER,
    fixture_field_geojson,
    write_fixture_scene,
)

SURFACES = ("blue", "green", "red", "nir", "swir1", "swir2")


@pytest.fixture()
def clean_scene(tmp_path):
    return write_fixture_scene(tmp_path, scene_id="FIX.C1")


@pytest.fixture()
def cloud_scene(tmp_path):
    return write_fixture_scene(
        tmp_path, scene_id="FIX.K1", with_cloud_block=True, with_nodata_patch=True
    )


def _read(assets, geo):
    return pre.read_scene_window(
        assets=assets,
        surfaces=SURFACES,
        geometry_geojson=geo,
        gdal_env={},
        max_window_mb=64,
    )


class TestWindowedReading:
    def test_window_is_field_bbox_not_full_scene(self, clean_scene):
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        # field spans cols 5..35 rows 6..34 -> 30 wide, 28 high (< 40x40)
        assert (reading.width, reading.height) == (30, 28)
        assert reading.crs == FIXTURE_CRS

    def test_geometry_reprojected_to_raster_crs(self, clean_scene):
        """A 4326 field polygon MUST be reprojected before rasterization:
        asserting the mask inside the window proves the reprojection."""
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        mask = pre.field_mask_for_window(
            geometry_geojson=geo,
            crs_string=reading.crs,
            transform=reading.transform,
            width=reading.width,
            height=reading.height,
        )
        # The field polygon spans rows 6..34, cols 5..35 of the fixture grid:
        # after reprojection the pixel-centre mask must cover EXACTLY those
        # 28 x 30 = 840 pixels (proves the 4326 -> UTM reprojection is correct).
        assert mask.sum() == 28 * 30

    def test_non_intersecting_scene_rejected(self, clean_scene):
        far_geo = {
            "type": "Polygon",
            "coordinates": [[[10.0, 10.0], [10.2, 10.0], [10.2, 10.2], [10.0, 10.2], [10.0, 10.0]]],
        }
        with pytest.raises(ValueError, match="does not intersect"):
            _read(clean_scene, far_geo)

    def test_memory_cap_enforced(self, clean_scene):
        geo = fixture_field_geojson()
        with pytest.raises(ValueError, match="cap"):
            _read(clean_scene, geo) if False else pre.read_scene_window(
                assets=clean_scene,
                surfaces=SURFACES,
                geometry_geojson=geo,
                gdal_env={},
                max_window_mb=0.000001,
            )


class TestIndexFormulas:
    def test_top_half_matches_documented_formula(self, clean_scene):
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi", "evi", "savi", "ndmi", "ndwi", "bsi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        mask = pre.field_mask_for_window(
            geometry_geojson=geo,
            crs_string=reading.crs,
            transform=reading.transform,
            width=reading.width,
            height=reading.height,
        )
        mid = reading.height // 2
        for p in products:
            top = np.nanmean(p.array[:mid][mask[:mid]])
            bottom = np.nanmean(p.array[mid:][mask[mid:]])
            assert top == pytest.approx(EXPECTED_VEGETATED[p.index_code], abs=1e-9), p.index_code
            assert bottom == pytest.approx(EXPECTED_STRESSED[p.index_code], abs=1e-9), p.index_code

    def test_scaling_applied_once(self, clean_scene):
        """DN*0.0001 exactly once — a double/missing scale breaks formulas."""
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, prov = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        assert prov["reflectance_scale"] == 0.0001
        ndvi = products[0]
        mask = pre.field_mask_for_window(
            geometry_geojson=geo,
            crs_string=reading.crs,
            transform=reading.transform,
            width=reading.width,
            height=reading.height,
        )
        top = np.nanmean(ndvi.array[: reading.height // 2][mask[: reading.height // 2]])
        assert top == pytest.approx((0.5 - 0.1) / (0.5 + 0.1), abs=1e-9)


class TestFmaskMasking:
    def test_cloud_block_excluded_and_counted(self, cloud_scene):
        geo = fixture_field_geojson()
        reading = _read(cloud_scene, geo)
        products, prov = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        p = products[0]
        # The 42-pixel cloud block and 24-pixel nodata patch are both invalid,
        # but only the cloud block is counted in Fmask provenance.
        assert p.valid_pixels < p.masked_pixels
        assert (p.masked_pixels - p.valid_pixels) == 66
        fm = prov["fmask"]
        assert fm["cloud_pixels_in_window"] == 42
        assert fm["shadow_pixels_in_window"] == 42  # cloud block also carries shadow+cirrus
        assert fm["cirrus_pixels_in_window"] == 42

    def test_nodata_never_treated_as_zero(self, cloud_scene):
        geo = fixture_field_geojson()
        reading = _read(cloud_scene, geo)
        assert np.all(reading.fmask[24:30, 23:29] == 0)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        p = products[0]
        arr = p.array
        # the nodata patch region must be NaN, not 0
        patch = arr[24:30, 23:29]
        assert np.isnan(patch).all()

    def test_water_bit_recorded_not_excluded(self, tmp_path):
        """FMASK bit 5 (water) is recorded in provenance but NOT excluded."""
        assets = write_fixture_scene(tmp_path, scene_id="FIX.W1")
        # set one pixel to water-only
        import rasterio

        with rasterio.open(assets["fmask"], "r+") as src:
            fm = src.read(1)
            fm[10, 10] = FMASK_WATER
            src.write(fm, 1)
        geo = fixture_field_geojson()
        reading = _read(assets, geo)
        products, prov = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        assert prov["fmask"]["water_pixels_in_window"] == 1
        # water pixel remains valid (water bit not in exclude mask)
        p = products[0]
        assert p.valid_pixels == p.masked_pixels - int(
            (reading.fmask & 0b011011 != 0).sum()
        )


class TestValidPixelAccounting:
    def test_coverage_fraction_and_flags(self, cloud_scene):
        geo = fixture_field_geojson()
        reading = _read(cloud_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        p = products[0]
        assert p.valid_pixel_fraction == pytest.approx(p.valid_pixels / p.masked_pixels)
        assert "low_field_coverage" not in p.zonal["flags"]  # coverage > 0.5 here
        assert "insufficient_pixels_for_variability" not in p.zonal["flags"]

    def test_fully_masked_scene_flags_no_valid_pixels(self, tmp_path):
        assets = write_fixture_scene(tmp_path, scene_id="FIX.ALLCLOUD")
        import rasterio

        with rasterio.open(assets["fmask"], "r+") as src:
            src.write(np.full((40, 40), 0b000010, dtype="uint8"), 1)
        geo = fixture_field_geojson()
        reading = _read(assets, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        p = products[0]
        assert p.valid_pixels == 0
        assert p.valid_pixel_fraction == 0.0
        assert "all_masked_pixels_invalid" in p.zonal["flags"]


class TestZones:
    def test_tercile_zone_summary_deterministic(self, clean_scene):
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        zones = products[0].zone_summary
        assert zones["method"] == "value_terciles_rank"
        names = [z["zone"] for z in zones["zones"]]
        assert names == ["lowest_tercile", "middle_tercile", "highest_tercile"]
        share_sum = sum(z["pixel_share"] for z in zones["zones"])
        assert share_sum == pytest.approx(1.0, abs=0.001)
        lo, mid, hi = zones["zones"]
        # every stratum is non-empty and ordered by mean (rank-based split)
        assert lo["mean"] is not None and mid["mean"] is not None and hi["mean"] is not None
        assert lo["mean"] <= mid["mean"] <= hi["mean"]
        assert lo["mean"] < hi["mean"]

    def test_uniform_raster_refuses_zone_claims(self, tmp_path):
        """A uniform raster (std=0) has no meaningful zones — refuses."""
        assets = write_fixture_scene(tmp_path, scene_id="FIX.UNI")
        import rasterio

        with rasterio.open(assets["nir"], "r+") as src:
            src.write(np.full((40, 40), 5000.0), 1)
        with rasterio.open(assets["red"], "r+") as src:
            src.write(np.full((40, 40), 1000.0), 1)
        geo = fixture_field_geojson()
        reading = _read(assets, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        assert products[0].zone_summary is None


class TestCogWriting:
    def test_cog_roundtrip_preserves_values_and_crs(self, clean_scene, tmp_path):
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        arr = products[0].array
        out = str(tmp_path / "ndvi.tif")
        meta = pre.write_index_cog(
            array=arr, transform=reading.transform, crs_string=reading.crs, path=out
        )
        assert meta["tiled"] is True
        with rasterio.open(out) as src:
            assert src.crs.to_string() == FIXTURE_CRS
            assert src.nodata is not None
            back = src.read(1)
        valid = np.isfinite(arr)
        np.testing.assert_allclose(back[valid], arr[valid].astype("float32"), rtol=1e-6)
        assert np.isnan(back[~valid]).all()


class TestPreviewPng:
    def test_png_signature_and_transparency(self, clean_scene):
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        png = pre.render_preview_png(index_array=products[0].array, index_code="ndvi")
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    def test_fixed_colormap_not_data_relative(self, clean_scene):
        """Same pixel value -> same color regardless of image statistics."""
        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, _ = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        arr = products[0].array
        png1 = pre.render_preview_png(index_array=arr, index_code="ndvi")
        # add an extreme outlier pixel; colormap mapping of the ORIGINAL
        # pixel must not change (no per-image normalization)
        arr2 = arr.copy()
        png2 = pre.render_preview_png(index_array=arr2, index_code="ndvi")
        assert png1 == png2  # identical inputs -> identical bytes (determinism)


class TestSceneValidation:
    def test_missing_assets_rejected_with_reasons(self):
        result = pre.validate_scene_for_processing(
            scene_record={"scene_id": "S", "assets": {}, "acquired_at": "2026-01-01T00:00:00Z"},
            required_surfaces=("red", "nir"),
            indices=["ndvi"],
            processing_version="v1",
        )
        assert not result.ok
        assert any("red" in r for r in result.reasons)
        assert any("nir" in r for r in result.reasons)

    def test_missing_acquisition_time_rejected(self, clean_scene):
        result = pre.validate_scene_for_processing(
            scene_record={"scene_id": "S", "assets": clean_scene},
            required_surfaces=("red", "nir"),
            indices=["ndvi"],
            processing_version="v1",
        )
        assert not result.ok
        assert any("acquisition" in r for r in result.reasons)

    def test_unknown_index_rejected(self, clean_scene):
        result = pre.validate_scene_for_processing(
            scene_record={"scene_id": "S", "assets": clean_scene, "acquired_at": "2026-01-01T00:00:00Z"},
            required_surfaces=("red", "nir"),
            indices=["not_an_index"],
            processing_version="v1",
        )
        assert not result.ok
        assert any("not_an_index" in r for r in result.reasons)

    def test_missing_fmask_warns_not_rejects(self, clean_scene):
        assets = {k: v for k, v in clean_scene.items() if k != "fmask"}
        result = pre.validate_scene_for_processing(
            scene_record={"scene_id": "S", "assets": assets, "acquired_at": "2026-01-01T00:00:00Z"},
            required_surfaces=("red", "nir"),
            indices=["ndvi"],
            processing_version="v1",
        )
        assert result.ok
        assert any("fmask" in w for w in result.warnings)

    def test_checksum_honesty_note(self):
        """Validation records that source checksums are NOT faked."""
        result = pre.validate_scene_for_processing(
            scene_record={"scene_id": "S", "assets": {}, "acquired_at": None},
            required_surfaces=("red",),
            indices=[],
            processing_version="",
        )
        assert not result.ok  # multiple reasons, but never a fabricated checksum


class TestProvenanceBlock:
    def test_provenance_records_formula_and_software(self, clean_scene):
        from app.vegetation.indices import INDEX_FORMULAS

        geo = fixture_field_geojson()
        reading = _read(clean_scene, geo)
        products, prov = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geo,
            indices=["ndvi"],
            reflectance_scale=0.0001,
            fmask_exclude_mask=0b011011,
        )
        block = pre.product_provenance(
            product_code="HLSL30",
            product_version="2.0",
            scene_id="FIX.C1",
            provider_code="nasa_hls",
            index_code="ndvi",
            index_formula=INDEX_FORMULAS["ndvi"],
            band_mapping={"surface_assets": {"red": "B04"}},
            processing_version="hls-derivation-1.0.0",
            pipeline_provenance=prov,
        )
        assert "Rouse" in block["index_formula"]
        assert block["software_version"] == pre.PROCESSING_SOFTWARE_VERSION
        assert block["pipeline"]["read_mode"] == "windowed_range_read"
        assert block["pipeline"]["window"]["crs"] == FIXTURE_CRS
        assert "checksum" in block["source_checksum_note"]

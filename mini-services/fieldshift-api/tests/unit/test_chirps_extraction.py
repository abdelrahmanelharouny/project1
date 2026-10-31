"""CHIRPS v3 GeoTIFF import + field extraction tests (M3).

Builds tiny in-memory GeoTIFF fixtures with rasterio — no network, no large
files — and validates the extraction, nodata accounting and error paths.
"""

from datetime import UTC, datetime

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.core.errors import ValidationFailed
from app.data_platform.providers.chirps.extractor import extract_field_precipitation

FIELD_GEOM = {
    "type": "Polygon",
    "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
}


def build_geotiff(
    values: np.ndarray,
    *,
    west: float = 31.40,
    north: float = 31.12,
    cell: float = 0.002,
    nodata: float = -9999.0,
    epsg: int = 4326,
) -> bytes:
    height, width = values.shape
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            crs=f"EPSG:{epsg}",
            transform=from_origin(west, north, cell, cell),
            nodata=nodata,
        ) as dst:
            dst.write(values.astype(np.float32), 1)
        return memfile.read()


class TestChirpsExtraction:
    def test_full_coverage_field_mean(self):
        values = np.full((10, 10), 4.0)
        data = build_geotiff(values)
        result = extract_field_precipitation(
            data,
            file_name="chirps-v3.0-daily.2024-01-31.tif",
            field_geometry_geojson=FIELD_GEOM,
            observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            period_kind="daily",
            product_status="final",
        )
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.variable_code == "precipitation"
        assert obs.value == pytest.approx(4.0, abs=1e-6)
        assert obs.evidence_class == "satellite_derived_estimate"
        assert obs.spatial_support_type == "polygon_average"
        assert obs.time_support == "daily"
        assert obs.metadata["valid_cells"] == 100
        assert obs.metadata["nodata_cells"] == 0
        assert obs.metadata["product_status"] == "final"
        assert obs.metadata["file_sha256"]
        assert result.provenance.product_code == "chirps_v3_daily"
        assert result.provenance.product_version == "v3.0-final"
        assert "not global" in result.provenance.known_limitations

    def test_partial_nodata_flags_low_coverage(self):
        values = np.full((10, 10), 2.0)
        values[:8, :] = -9999.0  # 80% nodata -> coverage 20%
        data = build_geotiff(values)
        result = extract_field_precipitation(
            data,
            file_name="chirps.tif",
            field_geometry_geojson=FIELD_GEOM,
            observed_at=datetime(2024, 1, 31, tzinfo=UTC),
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(2.0, abs=1e-6)
        flags = [f["flag_code"] for f in obs.quality_flags]
        assert "CHIRPS_LOW_CELL_COVERAGE" in flags
        assert obs.metadata["nodata_cells"] == 80

    def test_all_nodata_is_structured_error_not_zero(self):
        values = np.full((10, 10), -9999.0)
        data = build_geotiff(values)
        with pytest.raises(ValidationFailed):
            extract_field_precipitation(
                data,
                file_name="chirps.tif",
                field_geometry_geojson=FIELD_GEOM,
                observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            )

    def test_non_epsg4326_rejected(self):
        values = np.full((10, 10), 3.0)
        data = build_geotiff(values, epsg=32633)
        with pytest.raises(ValidationFailed):
            extract_field_precipitation(
                data,
                file_name="chirps.tif",
                field_geometry_geojson=FIELD_GEOM,
                observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            )

    def test_field_outside_raster_rejected(self):
        values = np.full((10, 10), 3.0)
        data = build_geotiff(values, west=10.0, north=5.0)
        with pytest.raises(ValidationFailed):
            extract_field_precipitation(
                data,
                file_name="chirps.tif",
                field_geometry_geojson=FIELD_GEOM,
                observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            )

    def test_preliminary_status_flagged(self):
        values = np.full((10, 10), 1.0)
        data = build_geotiff(values)
        result = extract_field_precipitation(
            data,
            file_name="chirps.tif",
            field_geometry_geojson=FIELD_GEOM,
            observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            product_status="preliminary",
        )
        obs = result.observations[0]
        assert result.provenance.product_version == "v3.0-preliminary"
        assert any(f["flag_code"] == "CHIRPS_PRELIMINARY" for f in obs.quality_flags)

    def test_monthly_period_bounds(self):
        values = np.full((10, 10), 1.0)
        data = build_geotiff(values)
        result = extract_field_precipitation(
            data,
            file_name="chirps.tif",
            field_geometry_geojson=FIELD_GEOM,
            observed_at=datetime(2024, 2, 15, tzinfo=UTC),
            period_kind="monthly",
        )
        obs = result.observations[0]
        assert obs.time_support == "monthly"
        assert obs.period_start.day == 1 and obs.period_start.month == 2
        assert obs.period_end.day == 29 and obs.period_end.month == 2  # 2024 leap year

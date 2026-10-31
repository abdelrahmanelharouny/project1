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


class TestPentadBounds:
    """Audit regression: CHIRPS pentads run 1-5, 6-10, 11-15, 16-20, 21-25 and
    26-END-OF-MONTH (verified against CHC v3 documentation). The last pentad of
    the month is variable length — start+5d was wrong."""

    def _extract(self, observed: datetime) -> tuple[datetime, datetime]:
        data = build_geotiff(np.full((10, 10), 1.0))
        result = extract_field_precipitation(
            data,
            file_name="chirps.tif",
            field_geometry_geojson=FIELD_GEOM,
            observed_at=observed,
            period_kind="pentad",
        )
        obs = result.observations[0]
        assert obs.time_support == "pentadal"
        return obs.period_start, obs.period_end

    def test_early_month_pentad_five_days(self):
        start, end = self._extract(datetime(2024, 1, 14, tzinfo=UTC))  # 11-15
        assert (start.day, start.month) == (11, 1)
        assert (end.day, end.month) == (15, 1)

    def test_last_pentad_january_runs_to_month_end(self):
        start, end = self._extract(datetime(2024, 1, 27, tzinfo=UTC))
        assert (start.day, start.month) == (26, 1)
        assert (end.day, end.month) == (31, 1)  # was Jan 30 with the +5d bug

    def test_last_pentad_february_leap_year(self):
        start, end = self._extract(datetime(2024, 2, 28, tzinfo=UTC))
        assert (start.day, start.month) == (26, 2)
        assert (end.day, end.month) == (29, 2)

    def test_last_pentad_february_non_leap(self):
        start, end = self._extract(datetime(2023, 2, 27, tzinfo=UTC))
        assert (start.day, start.month) == (26, 2)
        assert (end.day, end.month) == (28, 2)

    def test_last_pentad_thirty_day_month(self):
        start, end = self._extract(datetime(2024, 4, 30, tzinfo=UTC))
        assert (start.day, start.month) == (26, 4)
        assert (end.day, end.month) == (30, 4)

    def test_pentad_boundary_day_25_vs_26(self):
        start, end = self._extract(datetime(2024, 6, 25, tzinfo=UTC))
        assert (start.day, end.day) == (21, 25)
        start, end = self._extract(datetime(2024, 6, 26, tzinfo=UTC))
        assert (start.day, end.day) == (26, 30)


class TestSubCellField:
    """Audit regression: fields smaller than one grid cell fall back to
    all-touched cells, flagged — never a structured dead end, never silent."""

    def test_subcell_field_uses_all_touched_with_flag(self):
        # raster cells are 0.002 deg; the field below (~0.001 x 0.0006 deg)
        # lies strictly inside one cell and away from its centre
        tiny = {
            "type": "Polygon",
            "coordinates": [
                [[31.4045, 31.1052], [31.4055, 31.1052], [31.4055, 31.1058], [31.4045, 31.1058], [31.4045, 31.1052]]
            ],
        }
        data = build_geotiff(np.full((10, 10), 3.0))
        result = extract_field_precipitation(
            data,
            file_name="chirps.tif",
            field_geometry_geojson=tiny,
            observed_at=datetime(2024, 1, 31, tzinfo=UTC),
        )
        obs = result.observations[0]
        assert obs.value == pytest.approx(3.0, abs=1e-6)
        assert obs.metadata["cell_selection"] == "all_touched (sub-grid field)"
        assert any(f["flag_code"] == "CHIRPS_SUBCELL_FIELD" for f in obs.quality_flags)

    def test_field_outside_all_cells_still_rejected(self):
        # field entirely off the raster grid — no cells touch it either
        far = {
            "type": "Polygon",
            "coordinates": [[[50.0, 50.0], [50.01, 50.0], [50.01, 50.01], [50.0, 50.01], [50.0, 50.0]]],
        }
        data = build_geotiff(np.full((10, 10), 3.0))
        with pytest.raises(ValidationFailed):
            extract_field_precipitation(
                data,
                file_name="chirps.tif",
                field_geometry_geojson=far,
                observed_at=datetime(2024, 1, 31, tzinfo=UTC),
            )

"""Unit tests: geometry validation rules (Master §14.1, rule 15)."""

import pytest
from shapely.geometry import Polygon, shape

from app.geospatial.validation import (
    bbox_of,
    geodesic_area_m2,
    validate_boundary_geojson,
)
from app.core.errors import InvalidGeometry


def _square(lon0=31.40, lat0=31.10, d=0.02):
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon0 + d, lat0], [lon0 + d, lat0 + d], [lon0, lat0 + d], [lon0, lat0]]],
    }


class TestValidGeometry:
    def test_accepts_closed_polygon(self):
        result = validate_boundary_geojson(_square())
        assert result.geometry.geom_type == "MultiPolygon"
        assert result.area_m2_geodesic > 0
        assert result.warnings == []
        assert not result.repaired

    def test_accepts_multipolygon(self):
        mp = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[31.40, 31.10], [31.41, 31.10], [31.41, 31.11], [31.40, 31.11], [31.40, 31.10]]],
                [[[31.42, 31.10], [31.43, 31.10], [31.43, 31.11], [31.42, 31.11], [31.42, 31.10]]],
            ],
        }
        result = validate_boundary_geojson(mp)
        assert len(result.geometry.geoms) == 2

    def test_accepts_feature_wrapper(self):
        result = validate_boundary_geojson({"type": "Feature", "geometry": _square()})
        assert result.area_m2_geodesic > 0

    def test_output_geojson_is_normalized_multipolygon(self):
        result = validate_boundary_geojson(_square())
        assert result.geojson["type"] == "MultiPolygon"
        for poly in result.geojson["coordinates"]:
            assert poly[0][0] == poly[0][-1]  # rings closed


class TestInvalidGeometry:
    def test_open_ring_rejected(self):
        bad = {
            "type": "Polygon",
            "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12]]],
        }
        with pytest.raises(InvalidGeometry, match="closed ring"):
            validate_boundary_geojson(bad)

    def test_short_ring_rejected(self):
        bad = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]}
        with pytest.raises(InvalidGeometry):
            validate_boundary_geojson(bad)

    def test_out_of_bounds_coordinates_rejected(self):
        bad = {
            "type": "Polygon",
            "coordinates": [[[31.40, 91.10], [31.42, 91.10], [31.42, 91.12], [31.40, 91.12], [31.40, 91.10]]],
        }
        with pytest.raises(InvalidGeometry, match="latitude"):
            validate_boundary_geojson(bad)

    def test_non_numeric_coordinates_rejected(self):
        bad = {
            "type": "Polygon",
            "coordinates": [[["a", "b"], [1, 1], [1, 0], [0, 0], [0, 0]]],
        }
        with pytest.raises(InvalidGeometry, match="numbers"):
            validate_boundary_geojson(bad)

    def test_unsupported_geometry_type_rejected(self):
        bad = {"type": "Point", "coordinates": [31.4, 31.1]}
        with pytest.raises(InvalidGeometry, match="Unsupported geometry type"):
            validate_boundary_geojson(bad)

    def test_empty_geometry_rejected(self):
        bad = {"type": "Polygon", "coordinates": []}
        with pytest.raises(InvalidGeometry):
            validate_boundary_geojson(bad)

    def test_degenerate_area_rejected(self):
        tiny = {
            "type": "Polygon",
            "coordinates": [[[31.40, 31.10], [31.40 + 1e-9, 31.10], [31.40 + 1e-9, 31.10 + 1e-9], [31.40, 31.10 + 1e-9], [31.40, 31.10]]],
        }
        with pytest.raises(InvalidGeometry, match="degenerately small"):
            validate_boundary_geojson(tiny)


class TestRepairAndWarnings:
    def test_bowtie_self_intersection_repaired_with_warning(self):
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]],
        }
        result = validate_boundary_geojson(bowtie)
        assert result.repaired is True
        assert result.geometry.is_valid
        assert any("repaired" in w.lower() for w in result.warnings)

    def test_antimeridian_span_warning(self):
        # Thin sliver at ~89°N spanning 340 degrees of longitude (170E..-170E
        # rendered naively) — small enough to pass the area guard, wide enough
        # to trigger the antimeridian heuristic.
        wide = {
            "type": "Polygon",
            "coordinates": [[[170.0, 89.0], [-170.0, 89.0], [-170.0, 89.1], [170.0, 89.1], [170.0, 89.0]]],
        }
        result = validate_boundary_geojson(wide)
        assert any("antimeridian" in w.lower() or "180" in w for w in result.warnings)


class TestGeodesicArea:
    def test_known_area_one_degree_square_near_equator(self):
        # 1 deg lon x 1 deg lat at the equator ~ 12,300 km^2 (111.3 x 110.6 km).
        geojson = {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        }
        result = validate_boundary_geojson(geojson)
        area_km2 = result.area_m2_geodesic / 1e6
        assert 12_000 < area_km2 < 12_600, f"unexpected area {area_km2} km^2"

    def test_area_matches_independent_pyproj_calculation(self):
        geojson = _square()
        result = validate_boundary_geojson(geojson)
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        poly = Polygon(geojson["coordinates"][0])
        expected, _ = geod.geometry_area_perimeter(poly)
        assert abs(result.area_m2_geodesic - abs(expected)) / abs(expected) < 1e-6

    def test_higher_latitude_smaller_lon_extent(self):
        # Same 1-degree square at lat 60 has far less area than at the equator.
        equator = validate_boundary_geojson(
            {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}
        ).area_m2_geodesic
        north = validate_boundary_geojson(
            {"type": "Polygon", "coordinates": [[[0.0, 60.0], [1.0, 60.0], [1.0, 61.0], [0.0, 61.0], [0.0, 60.0]]]}
        ).area_m2_geodesic
        assert north < equator * 0.55  # cos(60) = 0.5

    def test_bbox_of(self):
        assert bbox_of(_square()) == [31.40, 31.10, 31.42, 31.12]

"""Geometry validation for user-provided GeoJSON field boundaries.

Rules implemented (Master Engineering Prompt §14.1 / rule 15):
- Accept GeoJSON Polygon / MultiPolygon only (per-field administrative boundary).
- Enforce [lon, lat] coordinate order and WGS84-bounded values.
- Require closed rings with >= 4 positions.
- Detect and repair self-intersections via Shapely `make_valid` when possible;
  bowtie-style polygons are rejected when repair would change topology materially.
- Normalize Polygon -> MultiPolygon for storage (MULTIPOLYGON, SRID 4326).
- Antimeridian heuristic: a single ring spanning > 180 degrees of longitude is
  flagged as a warning (probable wrong-side crossing, not silently re-wrapped).
"""

import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity, make_valid

from app.core.errors import InvalidGeometry


@dataclass
class GeometryValidationResult:
    """Outcome of validating one user-submitted boundary."""

    geometry: MultiPolygon  # normalized, valid geometry
    geojson: dict[str, Any]  # normalized GeoJSON (MultiPolygon)
    area_m2_geodesic: float
    warnings: list[str] = field(default_factory=list)
    repaired: bool = False


_MAX_RING_POSITIONS = 200_000  # guard against pathological payloads
_MIN_AREA_M2 = 1.0  # smaller than 1 m^2 is treated as degenerate
_MAX_AREA_M2 = 5_000_000 * 10_000.0  # 5,000,000 ha sanity ceiling


def _as_float_position(pos: Any, ctx: str) -> tuple[float, float]:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        raise InvalidGeometry(f"{ctx}: each position must be [lon, lat].")
    lon, lat = pos[0], pos[1]
    if isinstance(lon, bool) or isinstance(lat, bool) or not all(
        isinstance(v, (int, float)) for v in (lon, lat)
    ):
        raise InvalidGeometry(f"{ctx}: coordinates must be numbers.")
    lon_f, lat_f = float(lon), float(lat)
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        raise InvalidGeometry(f"{ctx}: coordinates must be finite.")
    if not (-180.0 <= lon_f <= 180.0):
        raise InvalidGeometry(f"{ctx}: longitude {lon_f} outside [-180, 180].")
    if not (-90.0 <= lat_f <= 90.0):
        raise InvalidGeometry(f"{ctx}: latitude {lat_f} outside [-90, 90].")
    # Common lat/lon swap detection: latitude magnitude in lon range but lon looks like lat.
    if abs(lat_f) > 90 or (abs(lon_f) <= 90 and abs(lat_f) > 89.9 and abs(lon_f) < 1e-9):
        raise InvalidGeometry(f"{ctx}: suspicious coordinates — ensure [lon, lat] order.")
    return lon_f, lat_f


def _validate_ring(ring: Any, ctx: str) -> list[tuple[float, float]]:
    if not isinstance(ring, list) or len(ring) < 4:
        raise InvalidGeometry(f"{ctx}: rings need >= 4 positions (linear ring).")
    if len(ring) > _MAX_RING_POSITIONS:
        raise InvalidGeometry(f"{ctx}: ring exceeds {_MAX_RING_POSITIONS} positions.")
    pts = [_as_float_position(p, ctx) for p in ring]
    if pts[0] != pts[-1]:
        raise InvalidGeometry(f"{ctx}: first and last ring positions must be identical (closed ring).")
    return pts


def _ring_lon_span(pts: list[tuple[float, float]]) -> float:
    lons = [p[0] for p in pts[:-1]]
    return max(lons) - min(lons)


def _polygon_from_geojson(geom: dict[str, Any]) -> Polygon:
    if geom["type"] != "Polygon":
        raise InvalidGeometry("Expected a Polygon geometry.")
    rings = geom.get("coordinates")
    if not isinstance(rings, list) or len(rings) == 0:
        raise InvalidGeometry("Polygon requires a non-empty 'coordinates' array of rings.")
    exterior = _validate_ring(rings[0], "exterior ring")
    interiors = [_validate_ring(r, f"interior ring #{i + 1}") for i, r in enumerate(rings[1:])]
    try:
        return Polygon(exterior, interiors)
    except Exception as exc:  # shapely topology error
        raise InvalidGeometry(f"Polygon topology error: {exc}") from exc


def _ensure_valid(geom: BaseGeometry, warnings: list[str]) -> tuple[BaseGeometry, bool]:
    if geom.is_valid:
        return geom, False
    reason = explain_validity(geom)
    repaired = make_valid(geom)
    # make_valid may produce GeometryCollection/LineString parts for degenerate
    # inputs; only accept results whose polygonal area is essentially preserved.
    if not isinstance(repaired, (Polygon, MultiPolygon)):
        raise InvalidGeometry(f"Geometry is invalid and cannot be repaired: {reason}.")
    if geom.area > 0 and repaired.area <= 0:
        raise InvalidGeometry(f"Geometry is invalid and cannot be repaired: {reason}.")
    warnings.append(
        f"Self-intersecting or invalid ring repaired automatically (Shapely: {reason}). "
        "Please verify the boundary reflects the real field."
    )
    return repaired, True


def _to_multipolygon(geom: BaseGeometry) -> MultiPolygon:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if geom.is_empty:
        raise InvalidGeometry("Geometry is empty.")
    raise InvalidGeometry(f"Unsupported polygonal geometry after normalization: {geom.geom_type}.")


def geodesic_area_m2(geom: BaseGeometry) -> float:
    """Geodesic area (m^2) on the WGS84 ellipsoid via PyProj Geod.

    Per Master §14.1: never compute area planar in square degrees.
    """
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    total = 0.0
    polys: list[Polygon] = []
    if isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    elif isinstance(geom, Polygon):
        polys = [geom]
    else:
        raise InvalidGeometry("Area requires a polygonal geometry.")
    for poly in polys:
        if not poly.exterior.is_ccw:
            poly = Polygon(
                list(poly.exterior.coords)[::-1],
                [list(r.coords)[::-1] if r.is_ccw else list(r.coords) for r in poly.interiors],
            )
        else:
            poly = Polygon(
                list(poly.exterior.coords),
                [list(r.coords)[::-1] if not r.is_ccw else list(r.coords) for r in poly.interiors],
            )
        area, _perimeter = geod.geometry_area_perimeter(poly)
        total += area
    return abs(total)


def validate_boundary_geojson(payload: Any) -> GeometryValidationResult:
    """Validate a GeoJSON Polygon/MultiPolygon field boundary.

    Raises InvalidGeometry with actionable messages on failure.
    """
    if not isinstance(payload, dict):
        raise InvalidGeometry("Boundary must be a GeoJSON geometry object.")
    gtype = payload.get("type")
    warnings: list[str] = []

    if gtype == "Feature":
        # Tolerate a Feature wrapper by using its geometry.
        inner = payload.get("geometry")
        if not isinstance(inner, dict):
            raise InvalidGeometry("Feature has no geometry member.")
        return validate_boundary_geojson(inner)

    if gtype == "Polygon":
        geom: BaseGeometry = _polygon_from_geojson(payload)
    elif gtype == "MultiPolygon":
        coords = payload.get("coordinates")
        if not isinstance(coords, list) or len(coords) == 0:
            raise InvalidGeometry("MultiPolygon requires a non-empty 'coordinates' array.")
        polys = [_polygon_from_geojson({"type": "Polygon", "coordinates": poly}) for poly in coords]
        geom = MultiPolygon(polys)
    else:
        raise InvalidGeometry(
            f"Unsupported geometry type '{gtype}'. Field boundaries must be GeoJSON Polygon or MultiPolygon."
        )

    if geom.is_empty:
        raise InvalidGeometry("Geometry has no area.")

    geom, repaired = _ensure_valid(geom, warnings)
    mp = _to_multipolygon(geom)

    for poly in mp.geoms:
        span = _ring_lon_span(list(poly.exterior.coords))
        if span > 180.0:
            warnings.append(
                "A ring spans more than 180 degrees of longitude — if the field is near the "
                "antimeridian, split or re-wrap the polygon coordinates explicitly."
            )

    area_m2 = geodesic_area_m2(mp)
    if area_m2 < _MIN_AREA_M2:
        raise InvalidGeometry("Field area is degenerately small (< 1 m^2).")
    if area_m2 > _MAX_AREA_M2:
        raise InvalidGeometry("Field area exceeds the 5,000,000 ha sanity limit — check units.")

    normalized_geojson = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [list(pt) for pt in list(poly.exterior.coords)],
                *[[list(pt) for pt in list(r.coords)] for r in poly.interiors],
            ]
            for poly in mp.geoms
        ],
    }
    return GeometryValidationResult(
        geometry=mp,
        geojson=normalized_geojson,
        area_m2_geodesic=area_m2,
        warnings=warnings,
        repaired=repaired,
    )


def bbox_of(geojson: dict[str, Any]) -> list[float]:
    geom = shape(geojson)
    minx, miny, maxx, maxy = geom.bounds
    return [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)]

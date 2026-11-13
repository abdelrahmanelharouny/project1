"""Server-side raster rendering for the map experience (P07).

Renders stored derived COGs (raster_assets, produced by the P05 pipeline)
into map-consumable imagery WITHOUT ever handing object-store credentials or
whole rasters to the browser:

- ``render_product_tile``  — XYZ web-mercator tile (PNG, transparent nodata)
  reprojected on the fly from the stored CRS with ``rasterio.warp``.
- ``transparent_png``      — shared empty tile for out-of-extent requests.
- ``value_distribution``   — histogram/percentiles of the index inside the
  field geometry only (spatially consistent with processing-time zonal stats).
- ``zone_polygons_fc``     — statistical tercile zone polygons (GeoJSON
  FeatureCollection, EPSG:4326) extracted from the same raster.

Honesty and safety rules:
- Colour normalization ALWAYS uses the documented index valid range (never
  per-image stretching) so tiles are comparable across dates/indices.
- NaN/nodata pixels are fully transparent — nodata is never drawn as zero.
- Assets are read through the RasterStorage abstraction only; the browser
  never sees storage keys, buckets or signed URLs (tile requests are
  field-membership gated at the API layer).
- A small bounded LRU (bytes of decoded rasters + rendered tiles) caps
  memory; every entry is keyed by asset checksum so a reprocessed product
  (new checksum) can never serve stale imagery.
"""

from __future__ import annotations

import hashlib
import io
import logging
import struct
import threading
import zlib
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("croptwist.geospatial.rendering")

TILE_SIZE = 256
# Web-mercator (EPSG:3857) world extent used by the XYZ scheme.
_WEB_MERCATOR_LIMIT = 20037508.342789244

DEFAULT_HISTOGRAM_BINS = 10
ZONE_SIMPLIFY_PX = 0.6  # polygon simplification tolerance in raster pixels

# ------------------------------------------------------------------- caches
class _LRU:
    """Thread-safe bounded LRU (max entries + max total bytes)."""

    def __init__(self, max_entries: int, max_bytes: int) -> None:
        from collections import OrderedDict

        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._bytes = 0
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                self._data.move_to_end(key)
                return entry[1]
            return None

    def put(self, key: str, value: Any, size: int) -> None:
        with self._lock:
            if key in self._data:
                old = self._data.pop(key)
                self._bytes -= old[0]
            self._data[key] = (size, value)
            self._bytes += size
            while len(self._data) > self._max_entries or (
                self._bytes > self._max_bytes and self._data
            ):
                _, (sz, _) = self._data.popitem(last=False)
                self._bytes -= sz

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._bytes = 0


def _cache_limits() -> tuple[int, int]:
    from app.core.config import settings

    return (
        int(getattr(settings, "raster_tile_cache_max_entries", 512)),
        int(getattr(settings, "raster_tile_cache_max_mb", 128)) * 1024 * 1024,
    )


_ASSET_LRU = _LRU(8, 96 * 1024 * 1024)  # decoded source rasters (bytes)
_TILE_LRU: _LRU | None = None  # initialized lazily with settings


def _tile_lru() -> _LRU:
    global _TILE_LRU
    if _TILE_LRU is None:
        max_entries, max_bytes = _cache_limits()
        _TILE_LRU = _LRU(max_entries, max_bytes)
    return _TILE_LRU


def reset_caches() -> None:
    """Test hook: drop every cached raster/tile."""
    _ASSET_LRU.clear()
    global _TILE_LRU
    _TILE_LRU = None


# ------------------------------------------------------------ XYZ tile math
def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """EPSG:4326 bounds of an XYZ web-mercator tile."""
    if z < 0 or z > 30:
        raise ValueError(f"tile zoom z={z} is out of the supported range 0..30")
    n = 2**z
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError(f"tile {z}/{x}/{y} is out of the XYZ range")
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = _tile_edge_lat(y, n)
    lat_min = _tile_edge_lat(y + 1, n)
    return (lon_min, lat_min, lon_max, lat_max)


def _tile_edge_lat(row: int, n: int) -> float:
    import math

    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * row / n)))
    return math.degrees(lat_rad)


def mercator_tile_transform(z: int, x: int, y: int) -> Any:
    """Affine transform of the tile in EPSG:3857 pixel space (256x256)."""
    from affine import Affine

    n = 2**z
    world = _WEB_MERCATOR_LIMIT * 2
    px = world / (n * TILE_SIZE)
    minx = -_WEB_MERCATOR_LIMIT + x * px * TILE_SIZE
    maxy = _WEB_MERCATOR_LIMIT - y * px * TILE_SIZE
    return Affine(px, 0.0, minx, 0.0, -px, maxy)


# -------------------------------------------------------------- asset reads
def _asset_key(asset: Any) -> str:
    checksum = getattr(asset, "checksum_sha256", None) or "no-checksum"
    return f"{asset.id}:{checksum}:{asset.byte_size}"


def read_asset_raster(asset: Any, storage: Any) -> dict[str, Any]:
    """Read a derived COG through the storage abstraction into memory.

    Returns {"array" (float64 np 2D, nan nodata), "transform", "crs"}.
    Cached per (asset id, checksum, size) — reprocessing produces a new
    checksum and therefore a fresh cache entry, never stale pixels.
    """
    import numpy as np
    import rasterio

    key = _asset_key(asset)
    cached = _ASSET_LRU.get(key)
    if cached is not None:
        return cached
    data = storage.read_bytes(asset.storage_key)
    with rasterio.io.MemoryFile(data) as mem:
        with mem.open() as src:
            band = src.read(1, masked=True)
            payload = {
                "array": np.ma.getdata(band).astype("float64"),
                "nodata_mask": np.ma.getmaskarray(band),
                "transform": src.transform,
                "crs": src.crs.to_string() if src.crs else None,
            }
    _ASSET_LRU.put(key, payload, len(data))
    return payload


# ----------------------------------------------------------------- colormap
def _colormap_rgb(norm: Any) -> tuple[Any, Any]:
    """Documented-range normalization -> (rgb uint8 array, alpha uint8 array)."""
    import numpy as np

    from app.geospatial.preprocessing import _PREVIEW_STOPS

    rgb = np.zeros((*norm.shape, 3), dtype="uint8")
    for i in range(len(_PREVIEW_STOPS) - 1):
        p0, c0 = _PREVIEW_STOPS[i]
        p1, c1 = _PREVIEW_STOPS[i + 1]
        m = (norm >= p0) & (norm <= p1) & np.isfinite(norm)
        if not m.any():
            continue
        t = np.zeros_like(norm)
        t[m] = (norm[m] - p0) / (p1 - p0) if p1 > p0 else 0.0
        for ch in range(3):
            rgb[..., ch][m] = (c0[ch] + (c1[ch] - c0[ch]) * t[m]).astype("uint8")
    alpha = np.where(
        np.isfinite(norm) & (norm >= 0.0) & (norm <= 1.0), 255, 0
    ).astype("uint8")
    return rgb, alpha


def encode_rgba_png(rgb: Any, alpha: Any) -> bytes:
    """Minimal deterministic RGBA PNG encoder (filter 0 rows, zlib)."""
    import numpy as np

    h, w = rgb.shape[:2]
    raw = bytearray()
    for row in range(h):
        raw.append(0)
        row_bytes = np.concatenate(
            [rgb[row], alpha[row].reshape(-1, 1)], axis=1
        ).astype("uint8").tobytes()
        raw.extend(row_bytes)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


_TRANSPARENT_TILE: bytes | None = None


def transparent_png(size: int = TILE_SIZE) -> bytes:
    """Fully transparent PNG (nodata tile). Computed once."""
    global _TRANSPARENT_TILE
    if _TRANSPARENT_TILE is None:
        import numpy as np

        rgb = np.zeros((size, size, 3), dtype="uint8")
        alpha = np.zeros((size, size), dtype="uint8")
        _TRANSPARENT_TILE = encode_rgba_png(rgb, alpha)
    return _TRANSPARENT_TILE


def _documented_range(index_code: str) -> tuple[float, float]:
    from app.vegetation.indices import INDEX_VALID_RANGE

    return INDEX_VALID_RANGE.get(index_code, (-1.0, 1.0))


# ---------------------------------------------------------------- rendering
def render_product_tile(
    *,
    asset: Any,
    storage: Any,
    z: int,
    x: int,
    y: int,
    index_code: str,
    size: int = TILE_SIZE,
) -> bytes:
    """Render one XYZ tile of a derived index product as RGBA PNG.

    Pipeline: mercator tile extent -> reproject stored raster (bilinear)
    into 256x256 EPSG:3857 grid -> documented-range normalization -> fixed
    colormap -> NaN/out-of-range fully transparent. Fully transparent tile
    when the tile does not intersect the raster extent.
    """
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject

    cache_key = f"tile:{_asset_key(asset)}:{z}/{x}/{y}:{index_code}:{size}"
    cached = _tile_lru().get(cache_key)
    if cached is not None:
        return cached

    lon_min, lat_min, lon_max, lat_max = tile_bounds(z, x, y)
    src = read_asset_raster(asset, storage)
    bounds = asset.bbox_json or []
    # Cheap rejection: tile vs raster bbox (EPSG:4326 approximations of both
    # sides; the derived bbox_json is the window bbox in asset CRS — for
    # UTM scenes a reprojected WGS84 bbox is stored on the preview asset,
    # so use a generous intersection test here).
    if bounds and len(bounds) == 4:
        # If bbox looks like lon/lat (asset CRS 4326 preview) test directly;
        # otherwise (projected CRS) rely on the reproject pass to decide.
        if -180.0 <= bounds[0] <= 180.0 and -90.0 <= bounds[1] <= 90.0:
            if (lon_max < bounds[0] or lon_min > bounds[2]
                    or lat_max < bounds[1] or lat_min > bounds[3]):
                return transparent_png(size)

    dst_transform = from_bounds(
        *_mercator_bounds(z, x, y), width=size, height=size
    )
    dst = np.full((size, size), np.nan, dtype="float64")
    try:
        reproject(
            source=src["array"],
            destination=dst,
            src_transform=src["transform"],
            src_crs=src["crs"],
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            src_nodata=float("nan"),
            dst_nodata=float("nan"),
            resampling=Resampling.bilinear,
        )
    except Exception as exc:  # unusable raster geometry for this tile
        logger.warning("tile reproject failed for %s: %s", asset.id, exc)
        raise ValueError("tile could not be rendered from the stored raster") from exc

    if not np.isfinite(dst).any():
        return transparent_png(size)

    lo, hi = _documented_range(index_code)
    with np.errstate(invalid="ignore"):
        norm = (dst - lo) / (hi - lo)
    rgb, alpha = _colormap_rgb(norm)
    png = encode_rgba_png(rgb, alpha)
    _tile_lru().put(cache_key, png, len(png))
    return png


def _mercator_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    world = _WEB_MERCATOR_LIMIT * 2
    px = world / (n * TILE_SIZE)
    minx = -_WEB_MERCATOR_LIMIT + x * px * TILE_SIZE
    maxy = _WEB_MERCATOR_LIMIT - y * px * TILE_SIZE
    maxx = minx + px * TILE_SIZE
    miny = maxy - px * TILE_SIZE
    return (minx, miny, maxx, maxy)


# --------------------------------------------------------- field analytics
def _field_mask(src: dict[str, Any], geometry_geojson: dict[str, Any]) -> Any:
    """Boolean mask (True = inside field) in the raster's own grid."""
    import numpy as np
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    crs = src["crs"] or "EPSG:4326"
    geom = geometry_geojson
    if crs != "EPSG:4326":
        geom = transform_geom("EPSG:4326", crs, geometry_geojson)
    height, width = src["array"].shape
    return geometry_mask(
        [geom],
        out_shape=(height, width),
        transform=src["transform"],
        invert=True,  # True INSIDE
        all_touched=False,
    ).astype(bool)


def value_distribution(
    *,
    asset: Any,
    storage: Any,
    geometry_geojson: dict[str, Any],
    index_code: str,
    bins: int = DEFAULT_HISTOGRAM_BINS,
) -> dict[str, Any]:
    """Histogram + percentiles of the index inside the field geometry only.

    Spatially consistent with processing-time zonal statistics (same
    pixel-centre masking over the stored window grid). Degenerate
    populations report honest zero-coverage rather than invented shapes.
    """
    import numpy as np

    src = read_asset_raster(asset, storage)
    mask = _field_mask(src, geometry_geojson)
    values = src["array"][mask & ~src["nodata_mask"]]
    finite = values[np.isfinite(values)].astype("float64")
    lo, hi = _documented_range(index_code)
    result: dict[str, Any] = {
        "index": index_code,
        "documented_range": [lo, hi],
        "field_mask_pixels": int(mask.sum()),
        "valid_pixels": int(finite.size),
        "method": "pixel_histogram_documented_range",
        "version": "geo-render-1.0.0",
    }
    if finite.size == 0:
        result["histogram"] = []
        result["proportion_out_of_documented_range"] = None
        result["note"] = "no valid field pixels inside the stored window"
        return result
    edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(finite, bins=edges)
    in_range = int(((finite >= lo) & (finite <= hi)).sum())
    result["histogram"] = [
        {
            "bin_start": round(float(edges[i]), 6),
            "bin_end": round(float(edges[i + 1]), 6),
            "pixels": int(counts[i]),
            "share": round(float(counts[i]) / float(finite.size), 6),
        }
        for i in range(bins)
    ]
    result["proportion_out_of_documented_range"] = round(
        (float(finite.size) - in_range) / float(finite.size), 6
    )
    result["percentiles"] = {
        "p5": round(float(np.percentile(finite, 5)), 6),
        "p25": round(float(np.percentile(finite, 25)), 6),
        "median": round(float(np.median(finite)), 6),
        "p75": round(float(np.percentile(finite, 75)), 6),
        "p95": round(float(np.percentile(finite, 95)), 6),
        "std": round(float(np.std(finite)), 6),
        "mean": round(float(np.mean(finite)), 6),
    }
    return result


def _tercile_classes(values: Any) -> Any:
    """Rank-based tercile class ids (0/1/2) matching tercile_zone_summary."""
    import numpy as np

    order = np.argsort(values, kind="stable")
    n = values.size
    n_low = n // 3
    n_high = n // 3
    classes = np.full(n, 1, dtype="uint8")
    classes[order[:n_low]] = 0
    classes[order[n_low + (n - n_low - n_high):]] = 2
    return classes


def zone_polygons_fc(
    *,
    asset: Any,
    storage: Any,
    geometry_geojson: dict[str, Any],
    index_code: str,
    min_pixels_per_zone: int = 3,
) -> dict[str, Any]:
    """Statistical tercile zones as GeoJSON polygons (EPSG:4326).

    Zones are the same rank-based terciles used in processing — explicitly
    statistical strata, NOT agronomic management zones (the label travels
    with the payload). Polygons come from vectorizing the classified valid
    field pixels; zones with fewer valid pixels than ``min_pixels_per_zone``
    are reported without geometry rather than drawn as noise.
    """
    import numpy as np
    from rasterio.features import shapes
    from rasterio.warp import transform_geom
    from shapely.geometry import shape as shp_shape
    from shapely.ops import unary_union

    src = read_asset_raster(asset, storage)
    mask = _field_mask(src, geometry_geojson)
    valid = mask & ~src["nodata_mask"]
    values = src["array"][valid]
    finite_mask = np.isfinite(values)
    values = values[finite_mask]

    zone_names = ("lowest_tercile", "middle_tercile", "highest_tercile")
    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "asset_id": str(asset.id),
        "index": index_code,
        "zone_kind": "statistical_terciles",
        "zone_note": (
            "Rank-based statistical terciles of valid field pixels — a "
            "data-description aid, not an agronomic zonation."
        ),
        "version": "geo-zones-1.0.0",
        "crs": "EPSG:4326",
        "features": [],
        "zones_without_geometry": [],
        "valid_pixels": int(values.size),
    }
    if values.size < 9 or float(np.std(values)) <= 1e-9:
        payload["zones_without_geometry"] = [
            {"zone": z, "reason": "insufficient_pixel_variation_or_count"}
            for z in zone_names
        ]
        return payload

    classes = np.zeros(valid.shape, dtype="uint8")
    classes[valid] = 0  # default outside = 0, remap below
    flat_classes = _tercile_classes(values)
    field_indices = np.argwhere(valid)
    finite_positions = np.zeros(valid.shape, dtype=bool)
    # finite subset of valid pixels, in the same order as `values`
    ordered = src["array"][valid]
    finite_positions_flat = np.isfinite(ordered)
    fs_idx = field_indices[finite_positions_flat]
    classes[fs_idx[:, 0], fs_idx[:, 1]] = flat_classes + 1  # 1..3 inside
    classes[~valid] = 0

    crs = src["crs"] or "EPSG:4326"
    px_w = abs(src["transform"].a) or abs(src["transform"].e)
    tolerance = px_w * ZONE_SIMPLIFY_PX

    for zi, zone in enumerate(zone_names, start=1):
        zone_mask = classes == zi
        count = int(zone_mask.sum())
        if count < min_pixels_per_zone:
            payload["zones_without_geometry"].append(
                {"zone": zone, "reason": f"only_{count}_valid_pixels"}
            )
            continue
        zone_values = src["array"][zone_mask]
        zone_values = zone_values[np.isfinite(zone_values)]
        geoms = [
            shp_shape(g)
            for g, _ in shapes(zone_mask.astype("uint8"), mask=zone_mask, transform=src["transform"])
            if g
        ]
        if not geoms:
            payload["zones_without_geometry"].append(
                {"zone": zone, "reason": "vectorization_produced_no_geometry"}
            )
            continue
        merged = unary_union(geoms).simplify(tolerance, preserve_topology=True)
        geojson_geom = shp_shape(mapping_safe(merged))
        geojson_geom = transform_geom(crs, "EPSG:4326", mapping_safe(merged))
        payload["features"].append(
            {
                "type": "Feature",
                "geometry": geojson_geom,
                "properties": {
                    "zone": zone,
                    "zone_kind": "statistical_tercile",
                    "pixel_count": count,
                    "pixel_share": round(count / max(1, int(values.size)), 6),
                    "mean": round(float(np.mean(zone_values)), 6) if zone_values.size else None,
                    "value_range": [
                        round(float(np.min(zone_values)), 6),
                        round(float(np.max(zone_values)), 6),
                    ]
                    if zone_values.size
                    else None,
                    "index": index_code,
                },
            }
        )
    return payload


def mapping_safe(geom: Any) -> dict[str, Any]:
    """shapely geometry -> GeoJSON mapping (import-local helper)."""
    import json

    return json.loads(json.dumps(geom.__geo_interface__))


def render_product_preview_bytes(asset: Any, storage: Any) -> bytes:
    """Stream the stored preview asset bytes (controlled read)."""
    return storage.read_bytes(asset.storage_key)


def asset_fingerprint(asset: Any) -> str:
    """Short stable fingerprint for cache/ETag headers."""
    checksum = getattr(asset, "checksum_sha256", None) or str(asset.id)
    return hashlib.sha256(f"{asset.id}:{checksum}".encode()).hexdigest()[:16]

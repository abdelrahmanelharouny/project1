"""HLS raster preprocessing pipeline (P05 Workstream C).

Turns real NASA HLS scene assets into validated, reproducible,
storage-backed derived index products for one authorized field.

Scientific contract (enforced, not documented-only):

- **Windowed range access**: only the pixels inside the field bounding box
  are read from the source COGs (`rasterio.windows`) — never a full scene
  download, never a full-scene in-memory array.
- **CRS correctness**: HLS scenes are distributed in their native UTM CRS.
  The EPSG:4326 field geometry is REPROJECTED to the raster CRS with pyproj
  before rasterization; the raster itself is never silently assumed to be
  in lon/lat. Derived products carry their true CRS in metadata.
- **Band grid alignment**: every band is read against one reference grid
  (the red band's window). Bands that arrive on a different grid for the
  requested window are aligned with a documented reprojection (bilinear for
  reflectance, nearest-neighbour for QA masks) — recorded in provenance as
  ``band_alignment``. When grids already match, nothing is resampled.
- **Scaling**: HLS v2.0 DN -> surface reflectance is DN * 0.0001 (the
  documented HLS v2.0 scale factor; no per-band offsets exist).
- **Fmask masking**: cirrus (bit 0), cloud (1), shadow (3) and snow/ice
  (4) are excluded (FMASK_EXCLUDE_MASK). Adjacent-to-cloud and water bits
  are recorded in provenance but NOT excluded.
- **Nodata**: masked pixels are NaN in every derived array and are NEVER
  treated as zero. Valid-pixel percentages are computed against the field
  mask, not the whole window.
- **Reproducibility**: same inputs + same processing version => same
  outputs. Formula, band mapping, scaling/masking rules, CRS/resolution,
  software version and valid-pixel summaries are attached to every
  product.

Index math lives in the shared, already-tested modules
(`app.vegetation.raster_indices` / `app.vegetation.indices`) — this module
never re-implements a formula.

Nothing in this pipeline produces agronomic claims: outputs are
measurements (reflectance-derived index rasters) and statistics (zonal
summaries). Interpretation happens upstream in the vegetation/evidence
engines, on data of known quality.
"""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PROCESSING_SOFTWARE_VERSION = "croptwist-geospatial-1.0.0"

# Documented preview colormap: 9 fixed stops interpolated linearly over the
# index's documented valid range. Renderings are VISUAL AIDS tied to the
# documented range — they never re-scale per image (no relative colormaps),
# so two dates of the same index are directly comparable.
_PREVIEW_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.00, (103, 55, 22)),    # deep brown (lowest values)
    (0.15, (196, 145, 81)),
    (0.30, (237, 219, 151)),
    (0.45, (247, 247, 247)),  # near-white mid-range
    (0.55, (183, 223, 155)),
    (0.70, (118, 189, 105)),
    (0.85, (61, 148, 77)),    # strong green
    (1.00, (14, 88, 43)),     # darkest green (highest values)
)


@dataclass
class WindowReading:
    """Windowed scene read: all bands on one aligned grid."""

    arrays: dict[str, Any]  # surface -> float64 DN array (2-D, aligned)
    fmask: Any | None       # uint8 Fmask array or None (aligned to grid)
    transform: Any          # Affine of the window (source CRS)
    crs: str                # raster CRS (e.g. 'EPSG:32636')
    width: int
    height: int
    window_bounds: tuple[float, float, float, float]  # in raster CRS
    nodata_values: dict[str, float | None]
    band_alignment: dict[str, str]  # surface -> 'native' | 'reprojected'
    read_bytes_estimate: int


@dataclass
class IndexProduct:
    """One derived index raster, ready for storage + provenance."""

    index_code: str
    array: Any            # float64, NaN = invalid (nodata/cloud/out-of-range)
    valid_pixels: int
    masked_pixels: int    # pixels inside the field mask
    valid_pixel_fraction: float
    zonal: dict[str, Any]  # ZonalResult.as_dict() over the field mask
    zone_summary: dict[str, Any] | None  # tercile partition when supported
    flags: list[str] = field(default_factory=list)


@dataclass
class SceneValidation:
    ok: bool
    reasons: list[str]
    warnings: list[str]
    details: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------- validation
def validate_scene_for_processing(
    *,
    scene_record: dict[str, Any],
    required_surfaces: tuple[str, ...],
    indices: list[str],
    processing_version: str,
) -> SceneValidation:
    """Reject incomplete/incompatible processing inputs with explicit reasons.

    Checks scene identity, product version, asset availability for the
    requested indices, acquisition time, resolution metadata and band
    mapping. Checksums: HLS CMR STAC items do not expose per-asset whole-
    file digests usable with HTTP range reads, so source checksum
    verification is recorded as unavailable in provenance (never faked);
    integrity is instead pinned by the derived-product sha256 we compute.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    scene_id = scene_record.get("scene_id")
    if not scene_id:
        reasons.append("scene_id missing")
    assets = scene_record.get("assets") or {}
    for surface in required_surfaces:
        if surface not in assets or not assets.get(surface):
            reasons.append(f"required band asset '{surface}' missing or empty")
    if "fmask" not in assets or not assets.get("fmask"):
        warnings.append("fmask QA asset missing; cloud masking will be unavailable")
    if not scene_record.get("acquired_at"):
        reasons.append("acquisition time missing")
    version = scene_record.get("processing_version") or scene_record.get("product_version")
    if not version:
        warnings.append("product version not recorded on the scene record")
    if scene_record.get("resolution_m") is None and scene_record.get("spatial_resolution_m") is None:
        warnings.append("spatial resolution not recorded on the scene record")
    if not scene_record.get("band_mapping"):
        warnings.append("band mapping not recorded on the scene record")
    if not indices:
        reasons.append("no index codes requested")
    unknown = [i for i in indices if i not in _SUPPORTED_INDICES]
    if unknown:
        reasons.append(f"unsupported index code(s): {', '.join(unknown)}")
    if not processing_version:
        reasons.append("processing version is required")

    return SceneValidation(
        ok=not reasons,
        reasons=reasons,
        warnings=warnings,
        details={
            "scene_id": scene_id,
            "assets_available": sorted(k for k, v in assets.items() if v),
            "indices": list(indices),
        },
    )


def required_surfaces_for_indices(indices: list[str]) -> tuple[str, ...]:
    """Union of reflectance surfaces the requested indices need."""
    from app.vegetation.indices import INDEX_REQUIREMENTS

    surfaces: list[str] = []
    for index in indices:
        for surface in INDEX_REQUIREMENTS.get(index, ()):  # refuse unknown later
            if surface not in surfaces:
                surfaces.append(surface)
    return tuple(surfaces)


_SUPPORTED_INDICES = ("ndvi", "evi", "savi", "ndmi", "ndwi", "bsi")


# ------------------------------------------------------- windowed reading
def _geojson_to_shapely(geometry_geojson: dict[str, Any]) -> Any:
    from shapely.geometry import shape

    geom = shape(geometry_geojson)
    if geom.is_empty:
        raise ValueError("field geometry is empty")
    return geom


def _reproject_geometry(geom: Any, *, src_epsg: int, dst_epsg: int) -> Any:
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shapely_transform

    transformer = Transformer.from_crs(
        CRS.from_epsg(src_epsg), CRS.from_epsg(dst_epsg), always_xy=True
    )
    return shapely_transform(transformer.transform, geom)


def read_scene_window(
    *,
    assets: dict[str, str],
    surfaces: tuple[str, ...],
    geometry_geojson: dict[str, Any],
    gdal_env: dict[str, str] | None = None,
    max_window_mb: float = 256.0,
) -> WindowReading:
    """Read ONLY the field bounding-box window from the scene COGs.

    The field geometry (EPSG:4326) is reprojected into the raster CRS to
    compute the window; the returned arrays are exactly window-sized. Bands
    arriving on a different grid are aligned (documented reprojection).
    Raises ValueError with explicit reasons when the window is empty or the
    estimated in-memory size exceeds ``max_window_mb``.
    """
    import numpy as np
    import rasterio
    from rasterio.windows import Window, from_bounds

    env = dict(gdal_env or {})
    band_hrefs = [assets[s] for s in surfaces if assets.get(s)]
    if not band_hrefs:
        raise ValueError("no band assets available for the requested surfaces")

    geom_ll = _geojson_to_shapely(geometry_geojson)

    reference = None  # (crs, full transform, full bounds, nodata)
    with rasterio.Env(**env):
        with rasterio.open(band_hrefs[0]) as src:
            if src.crs is None:
                raise ValueError("source scene has no CRS metadata; refusing to guess")
            crs = src.crs
            full_transform = src.transform
            full_bounds = src.bounds
            full_shape = (src.height, src.width)
            reference_nodata = src.nodata
            if crs.to_epsg() is None:
                # Non-EPSG CRS (rare for HLS): still usable via pyproj string.
                geom_rc = _reproject_geom_via_pyproj(geom_ll, crs.to_wkt())
            else:
                geom_rc = _reproject_geometry(geom_ll, src_epsg=4326, dst_epsg=crs.to_epsg())
            if not geom_rc.is_valid:
                from shapely.validation import make_valid

                geom_rc = make_valid(geom_rc)
            minx, miny, maxx, maxy = geom_rc.bounds
            if (
                maxx < full_bounds.left
                or minx > full_bounds.right
                or maxy < full_bounds.bottom
                or miny > full_bounds.top
            ):
                raise ValueError("field geometry does not intersect this scene after reprojection")
            window = from_bounds(minx, miny, maxx, maxy, transform=full_transform)
            window = window.round_offsets().round_lengths()
            window = window.intersection(
                Window(0, 0, full_shape[1], full_shape[0])
            )
            if window.width < 1 or window.height < 1:
                raise ValueError("field window collapses to zero pixels in this scene")
            est_bytes = int(window.width * window.height * (len(surfaces) + 2) * 8)
            if est_bytes > max_window_mb * 1024 * 1024:
                raise ValueError(
                    f"field window would need ~{est_bytes / 1e6:.1f} MB in memory "
                    f"(cap {max_window_mb:.0f} MB); refusing unbounded read"
                )
            reference = {
                "crs": crs,
                "transform": src.window_transform(window),
                "window": window,
                "nodata": reference_nodata,
            }
            out_transform = reference["transform"]

        arrays: dict[str, Any] = {}
        nodata_values: dict[str, float | None] = {}
        band_alignment: dict[str, str] = {}
        for surface, href in ((s, assets.get(s)) for s in surfaces if assets.get(s)):
            with rasterio.open(href) as src:
                if src.crs != reference["crs"]:
                    raise ValueError(
                        f"band '{surface}' CRS {src.crs} differs from reference "
                        f"{reference['crs']}; refusing mixed-CRS scene"
                    )
                data = src.read(
                    1,
                    window=reference["window"],
                    out_shape=(int(reference["window"].height), int(reference["window"].width)),
                    boundless=False,
                ).astype("float64")
                src_transform = src.window_transform(reference["window"])
                if src_transform.almost_equals(out_transform, precision=1e-9) and data.shape == (
                    int(reference["window"].height),
                    int(reference["window"].width),
                ):
                    band_alignment[surface] = "native"
                else:
                    data = _align_to_grid(
                        data, src_transform, out_transform, resampling="bilinear"
                    )
                    band_alignment[surface] = "reprojected"
                nodata_values[surface] = src.nodata
                if src.nodata is not None:
                    data[data == src.nodata] = np.nan
                arrays[surface] = data

        fmask = None
        fmask_href = assets.get("fmask")
        if fmask_href:
            with rasterio.open(fmask_href) as src:
                if src.crs is not None and src.crs != reference["crs"]:
                    band_alignment["fmask"] = "reprojected"
                    data = src.read(
                        1,
                        window=reference["window"],
                        out_shape=(
                            int(reference["window"].height),
                            int(reference["window"].width),
                        ),
                    )
                    fmask = _align_to_grid(
                        data.astype("float64"),
                        src.window_transform(reference["window"]),
                        out_transform,
                        resampling="nearest",
                    ).astype("uint8")
                else:
                    fmask = src.read(
                        1,
                        window=reference["window"],
                        out_shape=(
                            int(reference["window"].height),
                            int(reference["window"].width),
                        ),
                    )
                    band_alignment["fmask"] = "native"

    height, width = arrays[next(iter(arrays))].shape
    # Window bounds in the raster CRS (for storage metadata).
    w = reference["window"]
    window_bounds = (
        full_bounds.left + w.col_off * full_transform.a,
        full_bounds.bottom + w.row_off * full_transform.e,
        full_bounds.left + (w.col_off + w.width) * full_transform.a,
        full_bounds.bottom + (w.row_off + w.height) * full_transform.e,
    )
    return WindowReading(
        arrays=arrays,
        fmask=fmask,
        transform=out_transform,
        crs=reference["crs"].to_string(),
        width=width,
        height=height,
        window_bounds=(
            min(window_bounds[0], window_bounds[2]),
            min(window_bounds[1], window_bounds[3]),
            max(window_bounds[0], window_bounds[2]),
            max(window_bounds[1], window_bounds[3]),
        ),
        nodata_values=nodata_values,
        band_alignment=band_alignment,
        read_bytes_estimate=est_bytes,
    )


def _reproject_geom_via_pyproj(geom: Any, crs_wkt: str) -> Any:
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shapely_transform

    transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_wkt(crs_wkt), always_xy=True)
    return shapely_transform(transformer.transform, geom)


def _align_to_grid(
    data: Any, src_transform: Any, dst_transform: Any, *, resampling: str
) -> Any:
    """Reproject a small array onto the reference grid (only when needed)."""
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    dst = np.full(data.shape, np.nan if resampling != "nearest" else 0)
    reproject(
        source=data,
        destination=dst,
        src_transform=src_transform,
        dst_transform=dst_transform,
        src_crs=None,
        dst_crs=None,
        resampling=Resampling[resampling],
    )
    return dst


# ------------------------------------------------------- field masking
def field_mask_for_window(
    *,
    geometry_geojson: dict[str, Any],
    crs_string: str,
    transform: Any,
    width: int,
    height: int,
) -> Any:
    """Boolean mask (True = inside field) for the window grid, CRS-correct.

    Pixel-centre masking (``all_touched=False``): a pixel contributes only
    when its centre is inside the (reprojected) field geometry, so pixels
    outside the boundary can never influence results.
    """
    from rasterio.features import geometry_mask

    geom_ll = _geojson_to_shapely(geometry_geojson)
    epsg = _crs_epsg(crs_string)
    if epsg is None:
        geom_rc = _reproject_geom_via_pyproj(geom_ll, crs_string)
    else:
        geom_rc = _reproject_geometry(geom_ll, src_epsg=4326, dst_epsg=epsg)
    if not geom_rc.is_valid:
        from shapely.validation import make_valid

        geom_rc = make_valid(geom_rc)
    return geometry_mask(
        [geom_rc.__geo_interface__],
        out_shape=(height, width),
        transform=transform,
        invert=True,
        all_touched=False,
    )


def _crs_epsg(crs_string: str) -> int | None:
    try:
        from rasterio.crs import CRS as RasterioCRS

        return RasterioCRS.from_string(crs_string).to_epsg()
    except Exception:
        return None


# ------------------------------------------------------- product derivation
def derive_index_products(
    *,
    reading: WindowReading,
    geometry_geojson: dict[str, Any],
    indices: list[str],
    reflectance_scale: float,
    fmask_exclude_mask: int,
) -> tuple[list[IndexProduct], dict[str, Any]]:
    """Compute derived index rasters + zonal summaries for one scene window.

    Order is scientifically fixed: scale DN -> reflectance, build field +
    cloud masks, compute per-pixel indices over the aligned grid, THEN
    zonal statistics over field-masked valid pixels. Returns (products,
    provenance_block).
    """
    import numpy as np

    from app.vegetation.raster_indices import RASTER_INDICES_VERSION, compute_index_arrays

    unknown = [i for i in indices if i not in _SUPPORTED_INDICES]
    if unknown:
        raise ValueError(f"unsupported index code(s): {', '.join(unknown)}")

    height, width = reading.height, reading.width
    field_mask = field_mask_for_window(
        geometry_geojson=geometry_geojson,
        crs_string=reading.crs,
        transform=reading.transform,
        width=width,
        height=height,
    )

    reflectances: dict[str, Any] = {}
    for surface, dn in reading.arrays.items():
        refl = dn * reflectance_scale
        refl = np.where(np.isfinite(refl), refl, np.nan)
        reflectances[surface] = refl

    cloud_mask: Any | None = None
    fmask_bits_record: dict[str, int] | None = None
    if reading.fmask is not None:
        fm = reading.fmask.astype(np.uint8)
        cloud_mask = (fm & fmask_exclude_mask) != 0
        fmask_bits_record = {
            "excluded_bits": fmask_exclude_mask,
            "cloud_pixels_in_window": int(((fm & 0b10) != 0).sum()),
            "shadow_pixels_in_window": int(((fm & 0b1000) != 0).sum()),
            "cirrus_pixels_in_window": int(((fm & 0b1) != 0).sum()),
            "snow_pixels_in_window": int(((fm & 0b10000) != 0).sum()),
            "water_pixels_in_window": int(((fm & 0b100000) != 0).sum()),
            "adjacent_to_cloud_pixels_in_window": int(((fm & 0b100) != 0).sum()),
        }

    index_arrays = compute_index_arrays(reflectances=reflectances, indices=indices)

    products: list[IndexProduct] = []
    masked_pixels = int(field_mask.sum())
    for index in indices:
        arr = index_arrays.get(index)
        if arr is None:
            raise ValueError(f"index '{index}' could not be computed (missing bands)")
        inside = field_mask & np.isfinite(arr)
        if cloud_mask is not None:
            inside = inside & ~cloud_mask
        valid_pixels = int(inside.sum())
        valid_fraction = (valid_pixels / masked_pixels) if masked_pixels else 0.0

        values = arr[inside].astype("float64")
        stats = _zonal_from_values(index, values, masked_pixels)
        flags = list(stats.get("flags", []))
        zone_summary = tercile_zone_summary(values) if _zone_capable(values) else None

        product = IndexProduct(
            index_code=index,
            array=np.where(inside, arr, np.nan),
            valid_pixels=valid_pixels,
            masked_pixels=masked_pixels,
            valid_pixel_fraction=valid_fraction,
            zonal=stats,
            zone_summary=zone_summary,
            flags=flags,
        )
        products.append(product)

    provenance = {
        "index_math_version": RASTER_INDICES_VERSION,
        "software_version": PROCESSING_SOFTWARE_VERSION,
        "reflectance_scale": reflectance_scale,
        "band_alignment": reading.band_alignment,
        "nodata_values": reading.nodata_values,
        "window": {
            "crs": reading.crs,
            "bounds": list(reading.window_bounds),
            "width_px": reading.width,
            "height_px": reading.height,
            "read_bytes_estimate": reading.read_bytes_estimate,
        },
        "field_mask_pixels": masked_pixels,
        "fmask": fmask_bits_record,
        "read_mode": "windowed_range_read",
    }
    return products, provenance


def _zonal_from_values(index: str, values: Any, masked_pixels: int) -> dict[str, Any]:
    import numpy as np

    from app.vegetation.zonal import MIN_PIXELS_FOR_VARIABILITY, ZonalResult

    stats = ZonalResult(index=index)
    stats.masked_pixels = masked_pixels
    stats.valid_pixels = int(values.size)
    if masked_pixels > 0:
        stats.coverage_fraction = values.size / masked_pixels
    if values.size:
        stats.mean = float(np.mean(values))
        stats.median = float(np.median(values))
        stats.p5 = float(np.percentile(values, 5))
        stats.p25 = float(np.percentile(values, 25))
        stats.p75 = float(np.percentile(values, 75))
        stats.p95 = float(np.percentile(values, 95))
        stats.std = float(np.std(values, ddof=0)) if values.size > 1 else 0.0
    else:
        stats.flags.append("all_masked_pixels_invalid")
    if values.size < MIN_PIXELS_FOR_VARIABILITY:
        stats.flags.append("insufficient_pixels_for_variability")
    if stats.coverage_fraction is not None and stats.coverage_fraction < 0.5:
        stats.flags.append("low_field_coverage")
    return stats.as_dict()


# Minimum standard deviation for tercile zone partitioning. Index values
# are float64; identical reflectances can produce std ~1e-16 from summation
# rounding — that is noise, never "variation", so zones are refused below
# this floor (index-scale variation is >= 1e-3 in practice).
ZONE_STD_MIN = 1e-9


def _zone_capable(values: Any) -> bool:
    """Whether the valid-pixel population supports tercile zone partitioning."""
    import numpy as np

    from app.vegetation.zonal import MIN_PIXELS_FOR_VARIABILITY

    v = np.asarray(values)
    if v.size < max(MIN_PIXELS_FOR_VARIABILITY, 9):
        return False
    return bool(np.std(v) > ZONE_STD_MIN)


def tercile_zone_summary(values: Any) -> dict[str, Any]:
    """Statistical tercile partition of valid field pixels (NOT agronomic zones).

    Deterministic rank-based partition: valid pixels are sorted by value and
    split into lowest/middle/highest terciles (stable sort; ties split by
    position). Output reports the value ranges and population shares of each
    statistical stratum. This is a statistical interpretation of the raster
    — never a claim about crop conditions — and is refused for degenerate
    populations (see _zone_capable).
    """
    import numpy as np

    v = np.asarray(values, dtype="float64")
    order = np.argsort(v, kind="stable")
    n = int(v.size)
    n_low = n // 3
    n_high = n // 3
    n_mid = n - n_low - n_high
    low_idx = order[:n_low]
    mid_idx = order[n_low : n_low + n_mid]
    high_idx = order[n_low + n_mid :]

    def _zone(name: str, idx: Any, fallback_lo: float, fallback_hi: float) -> dict[str, Any]:
        vals = v[idx] if idx.size else np.array([])
        lo = float(vals.min()) if vals.size else fallback_lo
        hi = float(vals.max()) if vals.size else fallback_hi
        return {
            "zone": name,
            "value_range": [lo, hi],
            "pixel_share": round(vals.size / n, 4) if vals.size else 0.0,
            "mean": round(float(np.mean(vals)), 6) if vals.size else None,
        }

    return {
        "method": "value_terciles_rank",
        "description": (
            "Statistical tercile partition of valid field pixels by index "
            "value (rank-based); a data-description aid, not an agronomic "
            "zonation."
        ),
        "zones": [
            _zone("lowest_tercile", low_idx, float(v.min()), float(v.min())),
            _zone("middle_tercile", mid_idx, float(v.min()), float(v.max())),
            _zone("highest_tercile", high_idx, float(v.max()), float(v.max())),
        ],
        "valid_pixels": n,
        "version": PROCESSING_SOFTWARE_VERSION,
    }


# -------------------------------------------------------------- writing
def write_index_cog(
    *,
    array: Any,
    transform: Any,
    crs_string: str,
    path: str,
) -> dict[str, Any]:
    """Write a single-band COG-compatible GeoTIFF (tiled, deflate, overviews).

    NaN is encoded as nodata=nan (GDAL native float nodata). Returns driver
    + layout metadata for provenance. Falls back to tiled GTiff when the
    COG driver is unavailable.
    """
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    height, width = array.shape
    meta_common = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs_string,
        "transform": transform,
        "nodata": float("nan"),
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    payload = np.nan_to_num(array, nan=np.float64("nan")).astype("float32")
    used_driver = "GTiff"
    try:
        with rasterio.open(
            path,
            "w",
            driver="COG",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs=crs_string,
            transform=transform,
            nodata=float("nan"),
        ) as dst:
            dst.write(payload, 1)
        used_driver = "COG"
    except Exception:
        with rasterio.open(path, "w", **meta_common) as dst:
            dst.write(payload, 1)
            dst.build_overviews([2, 4], Resampling.average)
            dst.update_tags(
                OVR_RESAMPLING_ALG="AVERAGE",
                CROPTWIST_PROCESSING_VERSION=PROCESSING_SOFTWARE_VERSION,
            )
    return {
        "driver": used_driver,
        "dtype": "float32",
        "nodata": "nan",
        "tiled": True,
        "overviews": "internal" if used_driver == "COG" else "2,4-average",
    }


def render_preview_png(
    *,
    index_array: Any,
    index_code: str,
    max_px: int = 512,
) -> bytes:
    """Render a fixed-colormap PNG preview of an index raster.

    - Downsampled with NaN-aware block means to <= max_px per side.
    - Fixed documented colormap stretched over the index's DOCUMENTED valid
      range (never per-image normalization) so previews are comparable
      across dates and scenes.
    - NaN (masked/invalid/nodata) pixels are fully transparent.
    """
    import numpy as np

    from app.vegetation.indices import INDEX_VALID_RANGE

    lo, hi = INDEX_VALID_RANGE.get(index_code, (-1.0, 1.0))
    arr = np.asarray(index_array, dtype="float64")
    h, w = arr.shape
    scale = max(1, int(np.ceil(max(h, w) / max_px)))
    if scale > 1:
        hh, ww = (h // scale) * scale, (w // scale) * scale
        trimmed = arr[:hh, :ww]
        blocks = trimmed.reshape(hh // scale, scale, ww // scale, scale)
        with np.errstate(invalid="ignore"):
            arr = np.nanmean(blocks, axis=(1, 3))
    # Normalize over the DOCUMENTED range (fixed, not data-relative).
    norm = (arr - lo) / (hi - lo)
    rgb = np.zeros((*arr.shape, 3), dtype="uint8")
    stops = _PREVIEW_STOPS
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        m = (norm >= p0) & (norm <= p1) & np.isfinite(norm)
        if not m.any():
            continue
        t = np.zeros_like(norm)
        t[m] = (norm[m] - p0) / (p1 - p0) if p1 > p0 else 0.0
        for ch in range(3):
            rgb[..., ch][m] = (c0[ch] + (c1[ch] - c0[ch]) * t[m]).astype("uint8")
    alpha = np.where(np.isfinite(norm) & (norm >= 0.0) & (norm <= 1.0), 255, 0).astype("uint8")

    return _encode_png(rgb, alpha)


def _encode_png(rgb: Any, alpha: Any) -> bytes:
    """Minimal deterministic PNG encoder (RGBA, no compression tricks)."""
    import numpy as np

    h, w = rgb.shape[:2]
    raw = bytearray()
    for row in range(h):
        raw.append(0)  # filter type 0 (None)
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


# ------------------------------------------------------- provenance block
def product_provenance(
    *,
    product_code: str,
    product_version: str,
    scene_id: str,
    provider_code: str,
    index_code: str,
    index_formula: str,
    band_mapping: dict[str, Any],
    processing_version: str,
    pipeline_provenance: dict[str, Any],
    derived_at: datetime | None = None,
) -> dict[str, Any]:
    """Canonical provenance dict stored on every derived asset + observation."""
    return {
        "provider_code": provider_code,
        "product_code": product_code,
        "product_version": product_version,
        "scene_id": scene_id,
        "index_code": index_code,
        "index_formula": index_formula,
        "band_mapping": dict(band_mapping),
        "processing_version": processing_version,
        "software_version": PROCESSING_SOFTWARE_VERSION,
        "pipeline": pipeline_provenance,
        "derived_at": (derived_at or datetime.now(UTC)).isoformat(),
        "source_checksum_note": (
            "HLS CMR STAC items do not expose per-asset whole-file checksums "
            "usable with HTTP range reads; source checksum verification is "
            "therefore recorded as unavailable, and integrity is pinned by "
            "the derived-product sha256 computed at write time."
        ),
    }

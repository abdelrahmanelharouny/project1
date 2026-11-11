"""Field-level zonal statistics over raster vegetation-index rasters (P2.A).

Approach (consistent with the CHIRPS extractor precedent):
- EPSG:4326 GeoTIFF rasters opened with rasterio (in-memory or file).
- Field boundary (GeoJSON geometry, EPSG:4326) rasterized to a boolean mask
  with `rasterio.features.geometry_mask`.
- Statistics computed ONLY over valid (nodata-free) masked pixels:
  mean, median, p5/p25/p75/p95, valid pixel count, coverage fraction.
- Cloud/shadow invalidation is the caller's mask-construction job: this
  module accepts an optional `extra_invalid_mask` (same shape) for cloud
  masks and combines it with the nodata mask.
- Honesty: pixel counts are reported so small fields (a handful of pixels at
  10-30 m) cannot hide behind a single "mean"; `subfield_statistics_ok`
  states whether the pixel count supports sub-field zone claims.
- Unweighted means (not area-weighted): each masked pixel contributes
  equally. For 10-20 m pixels over fields of >= 0.5 ha this is the
  documented CHIRPS-precedent trade-off; fields smaller than that carry the
  CHIRPS_SUBCELL_FIELD-equivalent warning raised by the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import rasterio
from rasterio.features import geometry_mask

ZONAL_STATS_VERSION = "veg-zonal-1.0.0"

# Below this masked-pixel count, "spatial variability" claims are refused —
# percentiles over <5 pixels are noise dressed as distribution.
MIN_PIXELS_FOR_VARIABILITY = 5


@dataclass
class ZonalResult:
    index: str
    mean: float | None = None
    median: float | None = None
    p5: float | None = None
    p25: float | None = None
    p75: float | None = None
    p95: float | None = None
    std: float | None = None
    valid_pixels: int = 0
    masked_pixels: int = 0
    coverage_fraction: float | None = None
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "mean": self.mean,
            "median": self.median,
            "p5": self.p5,
            "p25": self.p25,
            "p75": self.p75,
            "p95": self.p95,
            "std": self.std,
            "valid_pixels": self.valid_pixels,
            "masked_pixels": self.masked_pixels,
            "coverage_fraction": self.coverage_fraction,
            "flags": list(self.flags),
            "version": ZONAL_STATS_VERSION,
        }


def subfield_statistics_ok(valid_pixels: int) -> bool:
    """Whether the pixel count supports sub-field spatial-variability claims."""
    return valid_pixels >= MIN_PIXELS_FOR_VARIABILITY


def zonal_statistics(
    *,
    index: str,
    raster: Any,
    geometry_geojson: dict[str, Any],
    extra_invalid: np.ndarray | None = None,
    all_touched: bool = False,
) -> ZonalResult:
    """Compute zonal statistics of an index raster over a field geometry.

    Parameters
    ----------
    index : canonical index code (ndvi/evi/savi/ndmi/ndwi) — used for labels.
    raster : an open rasterio dataset (1 band, index values as float32/64).
    geometry_geojson : EPSG:4326 GeoJSON of the field boundary.
    extra_invalid : optional boolean array (True = invalid, e.g. cloud/shadow)
        with the raster's (height, width) shape.
    all_touched : include pixels touched by the boundary (CHIRPS fallback
        precedent for tiny fields). Default False (pixel-centre masking).
    """
    transform = raster.transform
    invert = True  # geometry_mask: True INSIDE the geometry
    try:
        mask = geometry_mask(
            [geometry_geojson],
            out_shape=(raster.height, raster.width),
            transform=transform,
            invert=invert,
            all_touched=all_touched,
        )
    except Exception as exc:  # malformed geometry reaching raster stage
        raise ValueError(f"Field geometry could not be rasterized: {exc}") from exc

    band = raster.read(1, masked=True)
    nodata_invalid = np.ma.getmaskarray(band)
    values = np.ma.getdata(band)

    valid = mask & ~nodata_invalid
    if extra_invalid is not None:
        if extra_invalid.shape != (raster.height, raster.width):
            raise ValueError("extra_invalid mask shape does not match raster shape")
        valid = valid & ~np.asarray(extra_invalid, dtype=bool)

    masked_pixels = int(mask.sum())
    valid_values = values[valid].astype("float64")
    result = ZonalResult(index=index, masked_pixels=masked_pixels)
    if masked_pixels > 0:
        result.coverage_fraction = float(len(valid_values)) / float(masked_pixels)
    else:
        result.flags.append("no_field_pixels_in_raster")
        return result

    finite = valid_values[np.isfinite(valid_values)]
    if finite.size == 0:
        result.flags.append("all_masked_pixels_nodata")
        return result

    result.valid_pixels = int(finite.size)
    result.mean = float(np.mean(finite))
    result.median = float(np.median(finite))
    result.p5 = float(np.percentile(finite, 5))
    result.p25 = float(np.percentile(finite, 25))
    result.p75 = float(np.percentile(finite, 75))
    result.p95 = float(np.percentile(finite, 95))
    result.std = float(np.std(finite, ddof=0)) if finite.size > 1 else 0.0
    if not math.isfinite(result.mean):
        result.flags.append("nonfinite_mean")
    if result.valid_pixels < MIN_PIXELS_FOR_VARIABILITY:
        result.flags.append("insufficient_pixels_for_variability")
    if result.coverage_fraction is not None and result.coverage_fraction < 0.5:
        result.flags.append("low_field_coverage")
    return result

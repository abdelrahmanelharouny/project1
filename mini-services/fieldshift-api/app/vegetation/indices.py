"""Vegetation index mathematics (P2.A) — pure, deterministic, sensor-aware.

Scientific basis (documented formulas, no invented coefficients):

- NDVI  = (NIR - Red) / (NIR + Red)                    [Rouse et al. 1974]
- EVI   = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)
          with MODIS/Landsat-standard coefficients G=2.5, C1=6.0, C2=7.5,
          L=1.0 for reflectance in [0,1]                [Huete et al. 2002]
- SAVI  = ((NIR - Red) / (NIR + Red + L)) * (1 + L), L=0.5
          for low-biomass/soil-background conditions     [Huete 1988]
- NDMI  = (NIR - SWIR1) / (NIR + SWIR1)                [Gao 1996]
- NDWI  = (Green - NIR) / (Green + NIR)                [McFeeters 1996]

Honesty rules enforced here:
- An index is computed ONLY when the sensor actually provides the required
  bands (`INDEX_REQUIREMENTS`); the caller asks, this module refuses.
- Division-by-zero / ~zero denominators yield None (missing), never a
  fabricated value.
- Inputs must be SURFACE REFLECTANCE in [0, 1] (scaled). Raw DN scaling is
  the provider's job (Sentinel-2 L2A: DN * 0.0001; Landsat C2 L2:
  DN * 2.75e-05 - 0.2) and is recorded in observation provenance there.
- Values outside the physical range of an index are returned as None with a
  reason flag — never clamped silently. EVI's documented practical range
  extends above 1 (dense canopies); pure ratio indices are bounded [-1, 1].
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

VEGETATION_INDEX_VERSION = "veg-indices-1.0.0"

# Sentinel-2 L2A DN -> surface reflectance [0,1]
SENTINEL2_REFLECTANCE_SCALE = 0.0001
# Landsat Collection 2 Level-2 DN -> surface reflectance
LANDSAT_C2_L2_SCALE = 2.75e-05
LANDSAT_C2_L2_OFFSET = -0.2


@dataclass(frozen=True)
class BandMap:
    """Sensor-specific surface -> band-name mapping.

    `scale`/`offset` convert native DN to surface reflectance [0,1].
    """

    sensor: str
    red: str
    nir: str
    blue: str | None
    green: str | None
    swir1: str | None
    scale: float
    offset: float
    spatial_resolution_m: float
    product: str


SENTINEL2_L2A = BandMap(
    sensor="sentinel2",
    red="B04",
    nir="B08",
    blue="B02",
    green="B03",
    swir1="B11",
    scale=SENTINEL2_REFLECTANCE_SCALE,
    offset=0.0,
    spatial_resolution_m=10.0,
    product="sentinel-2-l2a",
)

# Per-band native resolution (used in provenance; SWIR is coarser than VNIR).
SENTINEL2_BAND_RESOLUTION_M = {
    "B02": 10.0,
    "B03": 10.0,
    "B04": 10.0,
    "B08": 10.0,
    "B11": 20.0,
    "B8A": 20.0,
}

LANDSAT89_C2_L2 = BandMap(
    sensor="landsat",
    red="SR_B4",
    nir="SR_B5",
    blue="SR_B2",
    green="SR_B3",
    swir1="SR_B6",
    scale=LANDSAT_C2_L2_SCALE,
    offset=LANDSAT_C2_L2_OFFSET,
    spatial_resolution_m=30.0,
    product="landsat-c2l2-sr",
)

BAND_MAPS: dict[str, BandMap] = {
    "sentinel2": SENTINEL2_L2A,
    "landsat": LANDSAT89_C2_L2,
}

# Which reflectance surfaces each index requires. An index is refused (with
# reason) when a surface is unavailable for the sensor — never computed with
# a substitute band.
INDEX_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "ndvi": ("red", "nir"),
    "evi": ("red", "nir", "blue"),
    "savi": ("red", "nir"),
    "ndmi": ("nir", "swir1"),
    "ndwi": ("green", "nir"),
    # Bare Soil Index: normalized difference of (SWIR1+Red) vs (NIR+Blue).
    # Valid for HLS L30/S30 (both provide B02 blue, B04 red, B05/B08 NIR,
    # B06/B11 SWIR1 at 30 m) and Sentinel-2 L2A. Computed only when the
    # sensor provides ALL four surfaces — never with substitutes.
    "bsi": ("swir1", "red", "nir", "blue"),
}

# Documented formula per index (citation strings reused in provenance).
INDEX_FORMULAS: dict[str, str] = {
    "ndvi": "NDVI = (NIR - Red) / (NIR + Red) [Rouse et al. 1974]",
    "evi": "EVI = 2.5*(NIR - Red) / (NIR + 6.0*Red - 7.5*Blue + 1.0) [Huete et al. 2002]",
    "savi": "SAVI = ((NIR - Red) / (NIR + Red + 0.5)) * 1.5 [Huete 1988]",
    "ndmi": "NDMI = (NIR - SWIR1) / (NIR + SWIR1) [Gao 1996]",
    "ndwi": "NDWI = (Green - NIR) / (Green + NIR) [McFeeters 1996]",
    "bsi": (
        "BSI = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue)) "
        "[Rikimaru et al. 2002 / Chen et al. 2004; bare soil exposure]"
    ),
}

# Physical validity bounds (outside -> None + flag, never clamped).
INDEX_VALID_RANGE: dict[str, tuple[float, float]] = {
    "ndvi": (-1.0, 1.0),
    "evi": (-1.0, 3.0),
    "savi": (-1.5, 1.5),
    "ndmi": (-1.0, 1.0),
    "ndwi": (-1.0, 1.0),
    "bsi": (-1.0, 1.0),
}

# Reflectance validity: physically meaningful surface reflectance after
# atmospheric correction sits in [0, 1]. Values above 1 occur over very
# bright targets — tolerated up to 1.6 with a flag; beyond that invalid.
REFLECTANCE_MIN = -0.05
REFLECTANCE_MAX_WARN = 1.0
REFLECTANCE_MAX_INVALID = 1.6


@dataclass
class IndexComputation:
    """Result of computing indices for one pixel (or scene-bundle) set."""

    values: dict[str, float | None] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def supported_indices() -> list[str]:
    return sorted(INDEX_REQUIREMENTS.keys())


def bands_for_index(index: str, sensor: str) -> dict[str, str]:
    """Resolve the concrete band names an index needs for a sensor.

    Raises ValueError when the sensor lacks a required surface — the honest
    refusal path (e.g. NDMI on a sensor without SWIR1).
    """
    try:
        band_map = BAND_MAPS[sensor]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown sensor '{sensor}'") from exc
    required = INDEX_REQUIREMENTS.get(index)
    if required is None:
        raise ValueError(f"Unknown index '{index}'")
    resolved: dict[str, str] = {}
    for surface in required:
        band_name = getattr(band_map, surface)
        if band_name is None:
            raise ValueError(
                f"Index '{index}' requires the '{surface}' band which sensor "
                f"'{sensor}' does not provide; refusing to compute with a substitute."
            )
        resolved[surface] = band_name
    return resolved


def compute_indices(
    *,
    sensor: str,
    reflectances: dict[str, float],
    indices: list[str] | None = None,
) -> IndexComputation:
    """Compute vegetation indices from SURFACE REFLECTANCES in [0, 1].

    `reflectances` keys are SURFACES ("red", "nir", "blue", "green", "swir1"),
    not band names, and values must ALREADY be surface reflectance — the
    provider resolves sensor band names -> surfaces and applies DN scaling
    (BandMap.scale/offset) before calling this function. This module never
    re-scales: double-scaling would silently corrupt indices.

    Any index whose inputs are missing/outside physical reflectance bounds or
    whose denominator is ~0 yields None for that index with a flag; other
    indices are still computed. No value is ever clamped into validity.
    """
    if sensor not in BAND_MAPS:
        raise ValueError(f"Unknown sensor '{sensor}'")
    wanted = indices if indices is not None else supported_indices()
    for index in wanted:
        if index not in INDEX_REQUIREMENTS:
            raise ValueError(f"Unknown index '{index}'")

    values: dict[str, float | None] = {}
    flags: list[str] = []

    scaled: dict[str, float] = {}
    for surface, value in reflectances.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            flags.append(f"{surface}_missing")
            continue
        if value < REFLECTANCE_MIN or value > REFLECTANCE_MAX_INVALID:
            flags.append(f"{surface}_out_of_physical_range")
            continue
        if value > REFLECTANCE_MAX_WARN:
            flags.append(f"{surface}_above_unity")
        scaled[surface] = value

    def _diff_ratio(a: float | None, b: float | None) -> float | None:
        """(a - b) / (a + b) with a zero-denominator guard — the shape of
        NDVI/NDMI/NDWI (difference normalized by sum)."""
        if a is None or b is None:
            return None
        denom = a + b
        if abs(denom) < 1e-9:
            return None
        return (a - b) / denom

    for index in wanted:
        required = INDEX_REQUIREMENTS[index]
        missing = [s for s in required if s not in scaled]
        if missing:
            values[index] = None
            flags.append(f"{index}_missing_bands:" + ",".join(missing))
            continue
        red = scaled.get("red")
        nir = scaled.get("nir")
        blue = scaled.get("blue")
        green = scaled.get("green")
        swir1 = scaled.get("swir1")
        value: float | None
        if index == "ndvi":
            value = _diff_ratio(nir, red)
        elif index == "evi":
            denom = nir + 6.0 * red - 7.5 * blue + 1.0
            value = 2.5 * (nir - red) / denom if abs(denom) >= 1e-9 else None
        elif index == "savi":
            denom = nir + red + 0.5
            value = 1.5 * (nir - red) / denom if abs(denom) >= 1e-9 else None
        elif index == "ndmi":
            value = _diff_ratio(nir, swir1)
        elif index == "ndwi":
            value = _diff_ratio(green, nir)
        elif index == "bsi":
            pos = swir1 + red
            neg = nir + blue
            if abs(pos + neg) < 1e-9:
                value = None
            else:
                value = (pos - neg) / (pos + neg)
        if value is not None and not math.isfinite(value):
            values[index] = None
            flags.append(f"{index}_nonfinite")
            continue
        lo, hi = INDEX_VALID_RANGE[index]
        if value is not None and not (lo <= value <= hi):
            values[index] = None
            flags.append(f"{index}_outside_valid_range")
            continue
        values[index] = value

    return IndexComputation(values=values, flags=sorted(set(flags)))

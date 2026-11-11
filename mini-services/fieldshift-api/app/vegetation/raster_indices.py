"""Vectorized (2-D array) vegetation index computation (P2.A).

Mirrors `app.vegetation.indices.compute_indices` elementwise for whole
rasters: index first per pixel, then zonal statistics — the scientifically
correct order (index-of-mean ≠ mean-of-index). Validity rules are identical:

- reflectance outside [-0.05, 1.6] -> invalid pixel for that surface
- ~zero denominator -> invalid (None) for that pixel
- index outside its documented range -> invalid pixel
- NoData / cloud masks combine with surface validity before statistics.

`agree_with_scalar` cross-validates the vectorized path against the scalar
path elementwise (used by unit tests to pin formula equivalence).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.vegetation.indices import INDEX_REQUIREMENTS, INDEX_VALID_RANGE

RASTER_INDICES_VERSION = "veg-raster-1.0.0"

REFLECTANCE_MIN = -0.05
REFLECTANCE_MAX_INVALID = 1.6

_EPS = 1e-9


def compute_index_arrays(
    *,
    reflectances: dict[str, np.ndarray],
    indices: list[str] | None = None,
) -> dict[str, np.ndarray]:
    """Compute index rasters from 2-D surface-reflectance arrays.

    Returns {index: array} where invalid pixels are np.nan (missing) —
    statistics downstream must skip NaNs explicitly.
    """
    wanted = indices if indices is not None else sorted(INDEX_REQUIREMENTS.keys())
    unknown = [i for i in wanted if i not in INDEX_REQUIREMENTS]
    if unknown:
        raise ValueError(f"Unknown index(es): {', '.join(unknown)}")
    if not reflectances:
        raise ValueError("reflectances must not be empty")

    shape = next(iter(reflectances.values())).shape
    clean: dict[str, np.ndarray] = {}
    for surface, arr in reflectances.items():
        a = np.asarray(arr, dtype="float64")
        if a.shape != shape:
            raise ValueError(f"reflectance array '{surface}' shape mismatch")
        valid = (a >= REFLECTANCE_MIN) & (a <= REFLECTANCE_MAX_INVALID) & np.isfinite(a)
        clean[surface] = np.where(valid, a, np.nan)

    def _ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        denom = a + b
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(np.abs(denom) >= _EPS, a / denom, np.nan)
        return out

    out: dict[str, np.ndarray] = {}
    for index in wanted:
        required = INDEX_REQUIREMENTS[index]
        missing = [s for s in required if s not in clean]
        if missing:
            out[index] = np.full(shape, np.nan)
            continue
        if index == "ndvi":
            value = _ratio(clean["nir"], clean["red"])
        elif index == "evi":
            nir, red, blue = clean["nir"], clean["red"], clean["blue"]
            denom = nir + 6.0 * red - 7.5 * blue + 1.0
            with np.errstate(invalid="ignore", divide="ignore"):
                value = np.where(np.abs(denom) >= _EPS, 2.5 * (nir - red) / denom, np.nan)
        elif index == "savi":
            nir, red = clean["nir"], clean["red"]
            denom = nir + red + 0.5
            with np.errstate(invalid="ignore", divide="ignore"):
                value = np.where(np.abs(denom) >= _EPS, 1.5 * (nir - red) / denom, np.nan)
        elif index == "ndmi":
            value = _ratio(clean["nir"], clean["swir1"])
        else:  # ndwi
            value = _ratio(clean["green"], clean["nir"])
        value = np.asarray(value, dtype="float64")
        lo, hi = INDEX_VALID_RANGE[index]
        value = np.where(np.isfinite(value) & (value >= lo) & (value <= hi), value, np.nan)
        out[index] = value
    return out


def agree_with_scalar(
    *,
    sensor: str,
    reflectances: dict[str, float],
    index: str,
) -> bool:
    """Cross-validate the vectorized formula against the scalar formula."""
    from app.vegetation.indices import compute_indices

    arrays = {s: np.array([[v]], dtype="float64") for s, v in reflectances.items()}
    vectorized = compute_index_arrays(reflectances=arrays, indices=[index])[index][0, 0]
    scalar = compute_indices(sensor=sensor, reflectances=reflectances, indices=[index]).values[index]
    v = float(vectorized) if np.isfinite(vectorized) else None
    if v is None and scalar is None:
        return True
    if v is None or scalar is None:
        return False
    return abs(v - scalar) <= 1e-9

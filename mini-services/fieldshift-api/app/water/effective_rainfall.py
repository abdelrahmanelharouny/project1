"""Effective rainfall (Milestone 6A — Phase 3, ADR-0021).

"Effective rainfall" (Pe) is the fraction of precipitation usable by the crop
(runoff, evaporation of intercepted water and deep percolation excluded —
FAO I&D Paper 33 §4.2). It is NOT "P − ET0": that climatic balance is a
different quantity implemented as a feature (`water_balance_p_minus_et0_monthly`)
and never used here.

Methods are versioned in WATER_METHODS_VERSION; the selected method, its
citation and its conditions are returned with every computed value. Unverified
formulae are NOT implemented (USDA-SCS is backlog W-5).
"""

from __future__ import annotations

from typing import Any

from app.water.contracts import (
    EFFECTIVE_RAINFALL_METHOD_INFO,
    EFFECTIVE_RAINFALL_METHODS,
    FAO_AGLW_SLOPE_CONDITION,
)

# FAO I&D Paper 33 §4.2 thresholds (verified M6A Phase 0 against the primary
# source, including the six worked examples 35→11, 90→47, 116→68, 5→0,
# 260→183, 75→35). The source rounds its printed answers to whole mm
# (e.g. 0.8·116 − 25 = 67.8 is printed as 68); the exact formula values are
# the golden expectations here (67.8), with the source's rounding disclosed.
FAO_AGLW_THRESHOLD_MM = 75.0
FAO_AGLW_HIGH_COEFF = 0.8
FAO_AGLW_HIGH_OFFSET = 25.0
FAO_AGLW_LOW_COEFF = 0.6
FAO_AGLW_LOW_OFFSET = 10.0


class EffectiveRainfallError(ValueError):
    pass


def effective_rainfall_mm(
    precip_mm: float,
    method: str,
    *,
    fraction: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Effective rainfall for ONE period total (a calendar month for the FAO
    method — its native scope).

    Returns (value | None, info) where `value is None` means "not evaluated"
    (never zero-unless-genuinely-zero: a true 0 is returned with the info
    explaining which branch produced it)."""
    if method not in EFFECTIVE_RAINFALL_METHODS:
        raise EffectiveRainfallError(
            f"unknown effective-rainfall method '{method}' "
            f"(known: {', '.join(EFFECTIVE_RAINFALL_METHODS)})"
        )
    if precip_mm < 0:
        raise EffectiveRainfallError("negative precipitation")

    if method == "none":
        return None, {
            **EFFECTIVE_RAINFALL_METHOD_INFO["none"],
            "reason": "no effective-rainfall method selected — rainfall credit unknown",
        }

    if method == "constant_fraction":
        if fraction is None:
            raise EffectiveRainfallError(
                "constant_fraction requires an explicit fraction (0..1); it is never defaulted"
            )
        if not 0.0 <= fraction <= 1.0:
            raise EffectiveRainfallError("constant_fraction must be within [0, 1]")
        return round(max(0.0, fraction * precip_mm), 4), {
            **EFFECTIVE_RAINFALL_METHOD_INFO["constant_fraction"],
            "fraction": fraction,
        }

    # fao_aglw_1986 (verified): continuous at the 75 mm threshold
    # (0.8·75 − 25 == 0.6·75 − 10 == 35).
    if precip_mm > FAO_AGLW_THRESHOLD_MM:
        pe = FAO_AGLW_HIGH_COEFF * precip_mm - FAO_AGLW_HIGH_OFFSET
    else:
        pe = FAO_AGLW_LOW_COEFF * precip_mm - FAO_AGLW_LOW_OFFSET
    return round(max(0.0, pe), 4), {
        **EFFECTIVE_RAINFALL_METHOD_INFO["fao_aglw_1986"],
        "slope_condition": FAO_AGLW_SLOPE_CONDITION,
    }


def monthly_effective_rainfall(
    monthly_precip: tuple[tuple[int, int, float], ...],
    method: str,
    *,
    fraction: float | None = None,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], dict[str, Any]], list[str]]:
    """Pe for each (year, month) with precipitation evidence.

    Months ABSENT from the input are unknown — they are omitted from the
    result dicts (never zero-filled) and listed in `missing_months` by the
    caller that knows the season window."""
    values: dict[tuple[int, int], float] = {}
    infos: dict[tuple[int, int], dict[str, Any]] = {}
    for y, m, p in monthly_precip:
        v, info = effective_rainfall_mm(p, method, fraction=fraction)
        if v is None:
            continue
        values[(y, m)] = v
        infos[(y, m)] = info
    return values, infos, []

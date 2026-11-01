"""Root-zone soil-water balance (Milestone 6A — Phase 3).

FAO-56-style accounting over the effective root zone. REQUIRED inputs are the
soil water-holding characteristics (θFC, θWP), the root-zone depth (Zr) and
optionally the depletion fraction p. The balance is NEVER claimed from surface
soil moisture (ERA5-Land 0–7 cm is a surface wetness estimate, not root-zone
storage — deepening rule), and missing inputs keep the balance dimension
honestly unevaluated.

Pedotransfer function: Saxton & Rawls (2006), "Soil water characteristic
estimates by texture and organic matter for hydrologic solutions", Soil Sci
Soc Am J 70:1569–1578. Coefficients were verified during the M6A Phase-0
programme against two independent secondary sources quoting the equations
(both cross-checked against the SPAW model reference implementation). The
validity domain published with the equations is enforced: estimates outside
it are REFUSED, never extrapolated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.water.contracts import PTF_VERSION

# Saxton & Rawls (2006) validity domain (as published with the equations).
PTF_MAX_SAND = 0.80
PTF_MAX_CLAY = 0.60
PTF_MAX_OM_PERCENT = 8.0

# van Bemmelen (1890) factor: organic matter ≈ organic carbon × 1.724.
VAN_BEMMELEN_OC_TO_OM = 1.724


class SoilBalanceError(ValueError):
    pass


class PTFDomainError(ValueError):
    """Requested estimate is outside the PTF's published validity domain."""


# ------------------------------------------------------------------- PTF


def saxton_rawls_2006(
    sand_fraction: float,
    clay_fraction: float,
    organic_matter_percent: float,
) -> dict[str, float]:
    """θ at 33 kPa (field capacity) and θ at 1500 kPa (wilting point), m3/m3.

    Equations (verified transcription; S = sand fraction 0-1, C = clay
    fraction 0-1, OM = organic matter percent):

      θ1500t = -0.024·S + 0.487·C + 0.006·OM + 0.005·S·OM - 0.013·C·OM
               + 0.068·S·C + 0.031
      θ1500  = θ1500t + (0.14·θ1500t − 0.02)

      θ33t   = -0.251·S + 0.195·C + 0.011·OM + 0.006·S·OM - 0.027·C·OM
               + 0.452·S·C + 0.299
      θ33    = θ33t + (1.283·θ33t² − 0.374·θ33t − 0.015)

    The density-correction variant (DF ≠ 1) is NOT implemented: no compaction
    evidence exists; the correction is documented as absent (backlog S-5).
    """
    for name, value in (
        ("sand", sand_fraction), ("clay", clay_fraction),
        ("organic_matter_percent", organic_matter_percent),
    ):
        if value is None or not math.isfinite(value):
            raise PTFDomainError(f"{name} must be a finite number")
    if sand_fraction < 0 or clay_fraction < 0 or organic_matter_percent < 0:
        raise PTFDomainError("sand, clay and OM must be non-negative")
    if sand_fraction + clay_fraction > 1.0:
        raise PTFDomainError("sand + clay fractions exceed 1.0")
    if sand_fraction > PTF_MAX_SAND:
        raise PTFDomainError(
            f"sand fraction {sand_fraction} above the PTF validity domain "
            f"(max {PTF_MAX_SAND}) — refusing to extrapolate"
        )
    if clay_fraction > PTF_MAX_CLAY:
        raise PTFDomainError(
            f"clay fraction {clay_fraction} above the PTF validity domain "
            f"(max {PTF_MAX_CLAY}) — refusing to extrapolate"
        )
    if organic_matter_percent > PTF_MAX_OM_PERCENT:
        raise PTFDomainError(
            f"organic matter {organic_matter_percent}% above the PTF validity "
            f"domain (max {PTF_MAX_OM_PERCENT}%) — refusing to extrapolate"
        )

    s, c, om = sand_fraction, clay_fraction, organic_matter_percent

    theta_1500t = (
        -0.024 * s + 0.487 * c + 0.006 * om + 0.005 * (s * om)
        - 0.013 * (c * om) + 0.068 * (s * c) + 0.031
    )
    theta_1500 = theta_1500t + (0.14 * theta_1500t - 0.02)

    theta_33t = (
        -0.251 * s + 0.195 * c + 0.011 * om + 0.006 * (s * om)
        - 0.027 * (c * om) + 0.452 * (s * c) + 0.299
    )
    theta_33 = theta_33t + (1.283 * theta_33t**2 - 0.374 * theta_33t - 0.015)

    out = {
        "theta_fc_33kPa": round(theta_33, 4),
        "theta_wp_1500kPa": round(theta_1500, 4),
    }
    if not (0.01 <= out["theta_fc_33kPa"] <= 0.60):
        raise PTFDomainError(
            f"estimated θFC {out['theta_fc_33kPa']} outside the plausible "
            "range [0.01, 0.60] — refusing the estimate"
        )
    if not (0.005 <= out["theta_wp_1500kPa"] <= 0.45):
        raise PTFDomainError(
            f"estimated θWP {out['theta_wp_1500kPa']} outside the plausible "
            "range [0.005, 0.45] — refusing the estimate"
        )
    if out["theta_fc_33kPa"] <= out["theta_wp_1500kPa"]:
        raise PTFDomainError(
            "estimated θFC must exceed θWP — refusing the estimate"
        )
    return out


def organic_carbon_to_om_percent(organic_carbon_g_kg: float) -> float:
    """SoilGrids SOC (g/kg) → organic matter percent via the van Bemmelen
    factor. The conversion is disclosed wherever the PTF is used."""
    oc_percent = organic_carbon_g_kg / 10.0  # g/kg → %, the SoilGrids convention
    return oc_percent * VAN_BEMMELEN_OC_TO_OM


# ----------------------------------------------------------- TAW / RAW / Ks


def taw_mm(theta_fc: float, theta_wp: float, zr_m: float) -> float:
    """Total available water: TAW = 1000·(θFC − θWP)·Zr (FAO-56 ch. 8)."""
    for name, v in (("theta_fc", theta_fc), ("theta_wp", theta_wp), ("zr_m", zr_m)):
        if v is None or not math.isfinite(v):
            raise SoilBalanceError(f"{name} missing or non-finite — balance not evaluable")
    if theta_fc <= theta_wp:
        raise SoilBalanceError(
            f"θFC ({theta_fc}) must exceed θWP ({theta_wp}) — inputs not usable"
        )
    if theta_wp < 0 or zr_m <= 0:
        raise SoilBalanceError("θWP must be ≥ 0 and Zr > 0")
    return round(1000.0 * (theta_fc - theta_wp) * zr_m, 4)


def raw_mm(taw: float, p_fraction: float) -> float:
    """Readily available water: RAW = p · TAW (FAO-56 ch. 8)."""
    if not 0 < p_fraction <= 1.0:
        raise SoilBalanceError(
            f"depletion fraction p must be within (0, 1] (got {p_fraction})"
        )
    return round(p_fraction * taw, 4)


def adjust_p_for_etc(p_table: float, etc_mean_mm_per_day: float) -> float:
    """FAO-56 Table 22 footnote 2 (verified): p = p_table + 0.04·(5 − ETc),
    clamped to (0, 1]."""
    from app.water.contracts import P_ETC_ADJUSTMENT_REFERENCE, P_ETC_ADJUSTMENT_SLOPE

    if p_table is None or not math.isfinite(p_table) or not 0 < p_table <= 1:
        raise SoilBalanceError(f"p_table out of range: {p_table}")
    if etc_mean_mm_per_day is None or not math.isfinite(etc_mean_mm_per_day):
        raise SoilBalanceError("ETc mean missing — p adjustment not evaluable")
    p = p_table + P_ETC_ADJUSTMENT_SLOPE * (
        P_ETC_ADJUSTMENT_REFERENCE - etc_mean_mm_per_day
    )
    return round(min(max(p, 0.01), 1.0), 4)


def ks_coefficient(dr_mm: float, taw: float, raw: float) -> float:
    """Water-stress coefficient Ks (FAO-56 Eq. 84): 1 while Dr ≤ RAW, then
    (TAW − Dr)/(TAW − RAW), floored at 0."""
    if raw >= taw:
        raise SoilBalanceError("RAW must be < TAW (p < 1)")
    if dr_mm <= raw:
        return 1.0
    return round(max(0.0, (taw - dr_mm) / (taw - raw)), 4)


@dataclass(frozen=True)
class DrState:
    day: object          # date
    dr_start_mm: float
    dr_end_mm: float
    inflow_mm: float     # Pe + irrigation
    etc_mm: float
    ks: float | None     # None when p (and hence RAW) is not evaluable


def daily_root_zone_balance(
    days: list,
    etc_by_day: list[float],
    pe_by_day: list[float | None],
    irrigation_by_day: list[float] | None,
    taw: float,
    raw: float | None,
    *,
    dr_initial_mm: float = 0.0,
) -> list[DrState]:
    """Daily root-zone depletion recurrence over the season window.

        Dr,i = min(TAW, max(0, Dr,i−1 − (Pe,i + I,i) + ETc,i))

    Simplified form: runoff and deep percolation are handled UPSTREAM by the
    effective-rainfall method (FAO-33) and by the TAW cap; capillary rise and
    groundwater contribution are NOT modelled and their absence is disclosed
    with every plan. A None entry in pe_by_day is a MISSING value — the day is
    computed WITHOUT a rainfall credit (a conservative upper bound on
    depletion) and the caller must disclose it; missing ETc raises.

    `raw=None` (p not evaluable) tracks Dr but reports Ks=None.
    """
    if len(days) != len(etc_by_day) or len(days) != len(pe_by_day):
        raise SoilBalanceError("day series length mismatch")
    if raw is not None and raw >= taw:
        raise SoilBalanceError("RAW must be < TAW (p < 1)")

    states: list[DrState] = []
    dr = dr_initial_mm
    for i, day in enumerate(days):
        etc = etc_by_day[i]
        if etc is None or math.isnan(etc):
            raise SoilBalanceError(f"ETc missing for {day} — balance not evaluable (missing ≠ zero)")
        inflow = 0.0
        if pe_by_day[i] is not None:
            inflow += pe_by_day[i]
        if irrigation_by_day is not None:
            inflow += irrigation_by_day[i]
        dr_start = dr
        dr = min(taw, max(0.0, dr - inflow + etc))
        states.append(
            DrState(
                day=day,
                dr_start_mm=round(dr_start, 4),
                dr_end_mm=round(dr, 4),
                inflow_mm=round(inflow, 4),
                etc_mm=round(etc, 4),
                ks=None if raw is None else ks_coefficient(dr, taw, raw),
            )
        )
    return states


def deficit_windows(
    states: list[DrState], raw: float
) -> list[dict[str, object]]:
    """Maximal runs of days with Dr > RAW (stress windows)."""
    windows: list[dict[str, object]] = []
    current: list[DrState] = []
    for state in states:
        if state.dr_end_mm > raw:
            current.append(state)
        else:
            if current:
                windows.append(_window_of(current))
                current = []
    if current:
        windows.append(_window_of(current))
    return windows


def _window_of(run: list[DrState]) -> dict[str, object]:
    return {
        "start_date": run[0].day.isoformat(),
        "end_date": run[-1].day.isoformat(),
        "days": len(run),
        "max_dr_mm": round(max(s.dr_end_mm for s in run), 2),
        "max_dr_date": max(run, key=lambda s: s.dr_end_mm).day.isoformat(),
        "min_ks": round(min(s.ks for s in run if s.ks is not None), 4)
        if any(s.ks is not None for s in run)
        else None,
    }

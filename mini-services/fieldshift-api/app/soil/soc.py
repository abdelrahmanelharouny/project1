"""Soil organic carbon stock engine (Milestone 6B.4 — Step 5, ADR-0024).

FAO GSOC MRV-convention layer stock (dimensional identity verified
analytically in docs/m6b/M6B_GAP_ANALYSIS.md §8):

    SOC_layer [Mg C/ha] = OC [g C/kg fine earth] × BD_fine [g/cm³]
                          × (1 − vCF [m³/m³]) × d [cm] × 0.1

Derivation (independent of this implementation, property-tested):
  mass fine earth per cm²  = BD_fine × d                     [g/cm²]
  carbon per cm²           = OC/1000 × BD_fine × d           [g C/cm²]
  carbon per ha            = × 10⁸ cm²/ha                    [g C/ha]
  Mg                       = ÷ 10⁶
  ⇒ OC × BD_fine × d × 10⁸ / (1000 × 10⁶) = OC × BD × d × 0.1  [Mg C/ha]
  coarse fragments remove soil volume: × (1 − vCF) — applied EXACTLY ONCE.

Hard rules:
- Every layer needs OC + BD + thickness (and vCF unless both are explicitly
  declared absent-from-basis — see coarse_fragment_policy). A missing input
  makes THAT layer's stock not_evaluated; it is never zero-filled.
- Bulk-density basis (whole_soil vs fine_earth) is explicit per layer. The
  (1 − vCF) correction is applied exactly once: whole-soil BD gets the
  correction; fine-earth BD must NOT be corrected again (double correction
  is a hard error, not a warning).
- Profile total = Σ layers over contiguous non-overlapping coverage; gaps
  are reported and the total is labelled by its covered depth.
- Fixed-depth vs equivalent-soil-mass comparisons are method-aware: ESM is
  REFUSED without the required per-layer masses (no partial ESM claims).
- SoilGrids-derived inputs keep the F-8 prediction label; a field-level 90%
  PI aggregated from pixel quantiles remains unavailable and is reported as
  such (never averaged-and-relabeled).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from app.soil.contracts import SOC_STOCK_VERSION, SOIL_METHODS_VERSION, SoilValidationError
from app.soil.layers import DepthInterval, validate_layer_set

SOC_FORMULA = (
    "SOC_stock [Mg C/ha] = OC [g/kg] × BD_fine [g/cm³] × (1 − vCF) × d [cm] × 0.1"
)


class SocStockError(SoilValidationError):
    pass


@dataclass(frozen=True)
class LayerStockInput:
    interval: DepthInterval
    oc_g_kg: float | None                  # organic carbon concentration
    bulk_density_g_cm3: float | None
    bd_basis: str | None                   # whole_soil | fine_earth
    coarse_fragment_vol_fraction: float | None   # m³/m³, 0..1
    oc_uncertainty_g_kg: float | None = None     # measurement uncertainty (1σ), if supplied
    bd_uncertainty_g_cm3: float | None = None
    evidence_class: str = "direct_field_measurement"
    is_prediction: bool = False            # SoilGrids-style mapped input
    source_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LayerStockResult:
    interval: DepthInterval
    soc_stock_mg_ha: float | None
    not_evaluated_reason: str | None
    inputs_used: dict[str, Any]
    is_prediction: bool


def _finite(value: float | None, name: str) -> float:
    if value is None or not math.isfinite(float(value)):
        raise SocStockError(f"{name} must be a finite number")
    return float(value)


def layer_soc_stock(layer: LayerStockInput) -> LayerStockResult:
    """SOC stock for ONE layer (ADR-0024). Refusals are explicit reasons on
    the result, not zero stocks."""
    interval = layer.interval
    inputs_used: dict[str, Any] = {
        "oc_g_kg": layer.oc_g_kg,
        "bulk_density_g_cm3": layer.bulk_density_g_cm3,
        "bd_basis": layer.bd_basis,
        "coarse_fragment_vol_fraction": layer.coarse_fragment_vol_fraction,
    }

    if layer.oc_g_kg is None:
        return LayerStockResult(interval, None, "OC concentration missing — stock refused", inputs_used, layer.is_prediction)
    if layer.bulk_density_g_cm3 is None:
        return LayerStockResult(interval, None, "bulk density missing — stock refused (no assumed density)", inputs_used, layer.is_prediction)
    if layer.bd_basis is None:
        return LayerStockResult(interval, None, "bulk-density basis not recorded — stock refused", inputs_used, layer.is_prediction)
    if layer.bd_basis not in ("whole_soil", "fine_earth"):
        return LayerStockResult(interval, None, f"unknown bulk-density basis '{layer.bd_basis}'", inputs_used, layer.is_prediction)

    oc = _finite(layer.oc_g_kg, "oc_g_kg")
    bd = _finite(layer.bulk_density_g_cm3, "bulk_density")
    if oc < 0:
        return LayerStockResult(interval, None, "negative OC — inputs not usable", inputs_used, layer.is_prediction)
    if bd <= 0 or bd >= 2.65:
        return LayerStockResult(interval, None, f"bulk density {bd} outside the plausible (0, 2.65) range", inputs_used, layer.is_prediction)

    vcf = layer.coarse_fragment_vol_fraction
    if layer.bd_basis == "whole_soil":
        if vcf is None:
            return LayerStockResult(
                interval, None,
                "whole-soil bulk density requires the coarse-fragment fraction "
                "for the single (1 − vCF) correction — stock refused",
                inputs_used, layer.is_prediction,
            )
        v = _finite(vcf, "coarse_fragment_vol_fraction")
        if not 0.0 <= v < 1.0:
            return LayerStockResult(interval, None, f"coarse-fragment fraction {v} outside [0, 1)", inputs_used, layer.is_prediction)
        correction = (1.0 - v)
        correction_note = "vCF applied once (whole-soil BD → fine-earth basis)"
    else:  # fine_earth
        if vcf is not None:
            return LayerStockResult(
                interval, None,
                "fine-earth bulk density must NOT be coarse-fragment corrected again "
                "(double correction is a hard error) — supply the vCF with whole-soil BD "
                "instead, or omit vCF for the fine-earth basis",
                inputs_used, layer.is_prediction,
            )
        correction = 1.0
        correction_note = "fine-earth BD — no vCF correction (already corrected upstream)"

    stock = oc * bd * correction * interval.thickness_cm * 0.1
    return LayerStockResult(
        interval=interval,
        soc_stock_mg_ha=round(stock, 6),
        not_evaluated_reason=None,
        inputs_used={**inputs_used, "correction_note": correction_note},
        is_prediction=layer.is_prediction,
    )


def profile_soc_stock(layers: list[LayerStockInput]) -> dict[str, Any]:
    """Layer-wise SOC stocks + profile total over contiguous complete coverage.

    Returns the run-ready result block (per-layer rows, totals, gaps,
    not-evaluated list, disclosure). Overlapping intervals REFUSE the total;
    gaps are listed and the total is labelled with the covered depth."""
    layer_rows: list[dict[str, Any]] = []
    not_evaluated: list[dict[str, Any]] = []
    warnings: list[str] = []

    intervals = [l.interval for l in layers]
    check = validate_layer_set(intervals)
    if check["overlaps"]:
        raise SocStockError(
            "layer depth intervals overlap — profile aggregation refused "
            "(never deduplicated silently)"
        )

    total = 0.0
    complete_intervals: list[DepthInterval] = []
    for layer in layers:
        result = layer_soc_stock(layer)
        row = {
            "top_cm": result.interval.top_cm,
            "bottom_cm": result.interval.bottom_cm,
            "thickness_cm": result.interval.thickness_cm,
            "soc_stock_mg_ha": result.soc_stock_mg_ha,
            "evidence_class": layer.evidence_class,
            "is_prediction": layer.is_prediction,
            "inputs_used": result.inputs_used,
        }
        if result.soc_stock_mg_ha is None:
            row["status"] = "not_evaluated"
            row["reason"] = result.not_evaluated_reason
            not_evaluated.append({
                "layer": f"{result.interval.top_cm}-{result.interval.bottom_cm} cm",
                "reason": result.not_evaluated_reason,
            })
        else:
            row["status"] = "evaluated"
            total += result.soc_stock_mg_ha
            complete_intervals.append(result.interval)
        if result.is_prediction:
            warnings.append(
                f"layer {result.interval.top_cm}-{result.interval.bottom_cm} cm uses "
                "mapped (SoilGrids-style) inputs — prediction, not a field measurement"
            )
        layer_rows.append(row)

    if complete_intervals:
        ccheck = validate_layer_set(complete_intervals)
        coverage = ccheck["coverage"]
        complete_total = sum(
            r["soc_stock_mg_ha"] for r in layer_rows if r["status"] == "evaluated"
        )
        if ccheck["gaps"]:
            warnings.append(
                "complete layers are not contiguous — the total covers the measured "
                "intervals only; gaps are NOT interpolated"
            )
        total_block = {
            "soc_stock_mg_ha": round(complete_total, 6),
            "coverage_cm": [coverage[0], coverage[1]],
            "covered_thickness_cm": round(sum(i.thickness_cm for i in complete_intervals), 4),
            "contiguous": not ccheck["gaps"],
        }
    else:
        total_block = {
            "soc_stock_mg_ha": None,
            "coverage_cm": None,
            "covered_thickness_cm": 0.0,
            "contiguous": False,
            "reason": "no layer has the complete OC+BD(+basis) input set",
        }

    return {
        "formula": SOC_FORMULA,
        "layers": layer_rows,
        "profile_total": total_block,
        "not_evaluated": not_evaluated,
        "warnings": warnings,
        "gaps": check["gaps"],
        "soc_stock_version": SOC_STOCK_VERSION,
        "methods_version": SOIL_METHODS_VERSION,
    }


# ------------------------------------------------------------ comparisons

def fixed_depth_comparison(
    baseline: list[LayerStockInput],
    follow_up: list[LayerStockInput],
) -> dict[str, Any]:
    """Fixed-depth SOC stock comparison over the COMMON depth support.

    Both profiles must be internally complete (per-layer) over the overlap;
    the comparison is refused otherwise. A bulk-density change between the
    two events is disclosed (fixed-depth stock changes can reflect mass
    redistribution rather than carbon change)."""
    def _by_depth(layers: list[LayerStockInput]) -> dict[tuple[float, float], LayerStockInput]:
        out: dict[tuple[float, float], LayerStockInput] = {}
        for l in layers:
            key = (l.interval.top_cm, l.interval.bottom_cm)
            if key in out:
                raise SocStockError(f"duplicate depth interval {key} in one profile")
            out[key] = l
        return out

    base_map = _by_depth(baseline)
    follow_map = _by_depth(follow_up)
    common = sorted(set(base_map) & set(follow_map))
    if not common:
        return {
            "comparison": "fixed_depth",
            "status": "not_evaluated",
            "reason": "no common depth intervals between the two sampling events",
        }

    base_stocks = profile_soc_stock([base_map[k] for k in common])
    follow_stocks = profile_soc_stock([follow_map[k] for k in common])
    if base_stocks["profile_total"]["soc_stock_mg_ha"] is None or follow_stocks["profile_total"]["soc_stock_mg_ha"] is None:
        return {
            "comparison": "fixed_depth",
            "status": "not_evaluated",
            "reason": "one or both profiles have incomplete layer inputs over the common support",
            "not_evaluated": base_stocks["not_evaluated"] + follow_stocks["not_evaluated"],
        }

    delta = follow_stocks["profile_total"]["soc_stock_mg_ha"] - base_stocks["profile_total"]["soc_stock_mg_ha"]
    bd_changed = any(
        (base_map[k].bulk_density_g_cm3 is not None
         and follow_map[k].bulk_density_g_cm3 is not None
         and abs(base_map[k].bulk_density_g_cm3 - follow_map[k].bulk_density_g_cm3) > 1e-9)
        for k in common
    )
    caveats: list[str] = []
    if bd_changed:
        caveats.append(
            "layer bulk density differs between the events — a fixed-depth stock "
            "difference can reflect soil mass redistribution, not only carbon change "
            "(equivalent-soil-mass comparison refines this when the required data exist)"
        )
    return {
        "comparison": "fixed_depth",
        "status": "evaluated",
        "common_depths_cm": [list(k) for k in common],
        "baseline_stock_mg_ha": base_stocks["profile_total"]["soc_stock_mg_ha"],
        "follow_up_stock_mg_ha": follow_stocks["profile_total"]["soc_stock_mg_ha"],
        "delta_mg_ha": round(delta, 6),
        "caveats": caveats,
        "comparison_version": SOC_STOCK_VERSION,
    }


def equivalent_soil_mass_comparison(
    baseline: list[LayerStockInput],
    follow_up: list[LayerStockInput],
) -> dict[str, Any]:
    """ESM comparison (soil-mass basis) — implemented ONLY with the data it
    requires: per-layer fine-earth masses for both events over a shared depth
    support (BD + thickness per layer). Without them the comparison is
    REFUSED with the reason (no partial ESM claims). Method: cumulative
    fine-earth mass matching on the follow-up profile, evaluated against the
    baseline's cumulative stock curve (linear-within-layer interpolation)."""
    base_map = {(l.interval.top_cm, l.interval.bottom_cm): l for l in baseline}
    follow_map = {(l.interval.top_cm, l.interval.bottom_cm): l for l in follow_up}
    common = sorted(set(base_map) & set(follow_map))
    if not common:
        return {
            "comparison": "equivalent_soil_mass",
            "status": "not_evaluated",
            "reason": "no common depth intervals between the two sampling events",
        }
    missing = []
    for k in common:
        for tag, layer in (("baseline", base_map[k]), ("follow_up", follow_map[k])):
            if layer.bulk_density_g_cm3 is None or layer.bd_basis is None:
                missing.append(f"{tag} {k}: bulk density")
            if layer.oc_g_kg is None:
                missing.append(f"{tag} {k}: OC")
            if layer.bd_basis == "whole_soil" and layer.coarse_fragment_vol_fraction is None:
                missing.append(f"{tag} {k}: coarse fragments (needed for fine-earth mass)")
    if missing:
        return {
            "comparison": "equivalent_soil_mass",
            "status": "not_evaluated",
            "reason": "equivalent-soil-mass comparison requires per-layer bulk density and "
            "OC for both events (with coarse fragments where the whole-soil basis is used)",
            "missing_inputs": sorted(set(missing)),
        }

    def _fine_bd(layer: LayerStockInput) -> float:
        bd = float(layer.bulk_density_g_cm3)
        if layer.bd_basis == "whole_soil":
            v = float(layer.coarse_fragment_vol_fraction or 0.0)
            return bd * (1.0 - v)
        return bd

    # cumulative mass (Mg fine earth/ha) and cumulative SOC (Mg C/ha) profiles
    def _cumulative(layers_map: dict[tuple[float, float], LayerStockInput]) -> tuple[list[float], list[float]]:
        masses = [0.0]
        stocks = [0.0]
        for k in common:
            layer = layers_map[k]
            bd_fine = _fine_bd(layer)
            # mass per ha for this layer: BD [g/cm³] × d [cm] × 10⁸ cm²/ha ÷ 10⁶ g/Mg
            mass = bd_fine * (k[1] - k[0]) * 100.0  # Mg/ha (100 = 1e8/1e6)
            stock = float(layer_soc_stock(layer).soc_stock_mg_ha or 0.0)
            masses.append(masses[-1] + mass)
            stocks.append(stocks[-1] + stock)
        return masses, stocks

    base_mass, base_stock = _cumulative(base_map)
    follow_mass, follow_stock = _cumulative(follow_map)

    # match the follow-up cumulative MASS on the baseline curve
    target_mass = follow_mass[-1]
    if target_mass > base_mass[-1] + 1e-9:
        return {
            "comparison": "equivalent_soil_mass",
            "status": "not_evaluated",
            "reason": "the follow-up profile's fine-earth mass exceeds the baseline's "
            "covered mass — the ESM reference depth cannot be matched from these layers",
        }

    def _stock_at_mass(masses: list[float], stocks: list[float], m: float) -> float:
        for i in range(1, len(masses)):
            if masses[i] >= m - 1e-9:
                if masses[i] - masses[i - 1] < 1e-12:
                    return stocks[i]
                frac = (m - masses[i - 1]) / (masses[i] - masses[i - 1])
                return stocks[i - 1] + frac * (stocks[i] - stocks[i - 1])
        return stocks[-1]

    base_at = _stock_at_mass(base_mass, base_stock, target_mass)
    follow_at = follow_stock[-1]
    return {
        "comparison": "equivalent_soil_mass",
        "status": "evaluated",
        "reference_mass_mg_ha": round(target_mass, 6),
        "baseline_stock_mg_ha": round(base_at, 6),
        "follow_up_stock_mg_ha": round(follow_at, 6),
        "delta_mg_ha": round(follow_at - base_at, 6),
        "method_note": (
            "cumulative fine-earth mass matching; baseline stock interpolated "
            "linearly within the layer containing the reference mass"
        ),
        "comparison_version": SOC_STOCK_VERSION,
    }


def soc_run_checksum(result: dict[str, Any]) -> str:
    payload = {
        "engine": SOC_STOCK_VERSION,
        "methods": SOIL_METHODS_VERSION,
        "profile_total": result.get("profile_total"),
        "layers": result.get("layers"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

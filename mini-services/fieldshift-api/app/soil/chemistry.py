"""Soil chemistry policies (Milestone 6B.3 — Step 4, ADR-0023).

Method-awareness rules enforced by code, not convention:

- pH: medium (water, CaCl2, ...) and soil:solution ratio are part of the
  measurement identity. No conversion between pH media exists that the
  platform endorses — values are never merged into one series. Crop-optimum
  comparisons are labelled screening (EcoCrop optima are low-confidence
  references; backlog S-3 local calibration).
- EC: ECe (saturated paste) is the standard salinity measure (FAO Soils
  Bulletin 62). EC at other soil:water ratios (1:1, 1:2.5, 1:5) is a
  DIFFERENT measurement: no texture-generic conversion is implemented in
  M6B (conversions are texture- and dilution-specific — backlog W-9), so
  cross-ratio comparison is refused. Salinity class interpretation is
  offered ONLY for ECe, with the cited FAO classes, labelled indicative.
- Nutrient reporting forms: elemental (P, K) vs oxide (P2O5, K2O) are
  distinct reporting bases; conversions are exact stoichiometric functions
  (see app.soil.nutrients) — never ad-hoc factors.
- Concentration vs stock: concentration rows (g/kg, mg/kg) never become a
  stock without layer thickness + bulk density (that is SOC §5 / nutrient
  stock discipline, computed elsewhere).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.soil.contracts import SoilValidationError

PH_MEDIA = ("water", "cacl2", "kcl", "saturation_paste", "other")

# FAO Soils Bulletin 62 (Abrol, Yadav & Massoud 1988), Table: standard
# salinity classes on the ECe scale. Indicative only; local agronomic
# interpretation stays with the farmer/agronomist.
EC_E_SALINITY_CLASSES: tuple[dict[str, Any], ...] = (
    {"range_dS_m": (0.0, 2.0), "class": "non_saline", "citation": "FAO Soils Bulletin 62, Table 4 (ECe classes)"},
    {"range_dS_m": (2.0, 4.0), "class": "slightly_saline", "citation": "FAO Soils Bulletin 62, Table 4 (ECe classes)"},
    {"range_dS_m": (4.0, 8.0), "class": "moderately_saline", "citation": "FAO Soils Bulletin 62, Table 4 (ECe classes)"},
    {"range_dS_m": (8.0, 16.0), "class": "strongly_saline", "citation": "FAO Soils Bulletin 62, Table 4 (ECe classes)"},
    {"range_dS_m": (16.0, float("inf")), "class": "very_strongly_saline", "citation": "FAO Soils Bulletin 62, Table 4 (ECe classes)"},
)


@dataclass(frozen=True)
class PhMeasurement:
    value: float
    medium: str
    soil_solution_ratio: str | None
    method_note: str | None


def validate_ph_measurement(
    value: float,
    medium: str,
    soil_solution_ratio: str | None = None,
) -> PhMeasurement:
    """pH measurement identity check (never merged across media)."""
    v = float(value)
    if not 0.0 < v <= 14.0:
        raise SoilValidationError(f"pH {v} outside the (0, 14] range — refusing")
    if medium not in PH_MEDIA:
        raise SoilValidationError(
            f"pH medium '{medium}' must be recorded (one of {', '.join(PH_MEDIA)}) "
            "— measurements without a medium are not accepted"
        )
    return PhMeasurement(value=v, medium=medium, soil_solution_ratio=soil_solution_ratio, method_note=None)


def ph_series_comparable(a: PhMeasurement, b: PhMeasurement) -> bool:
    """True only when two pH measurements share medium + ratio identity."""
    return a.medium == b.medium and (a.soil_solution_ratio or None) == (b.soil_solution_ratio or None)


def ph_screening_against_optimum(
    ph: PhMeasurement,
    optimum_min: float,
    optimum_max: float,
    *,
    source_citation: str,
) -> dict[str, Any]:
    """Labelled SCREENING comparison of a pH measurement against a crop
    optimum range (e.g. EcoCrop ph_opt_min/max, confidence low).

    Never a suitability verdict: the medium caveat is explicit (optima are
    usually water-pH context; a CaCl2 measurement reads systematically lower
    — the screening label covers this rather than 'converting')."""
    if ph.medium != "water":
        note = (
            f"pH measured in {ph.medium} — not directly comparable to water-pH "
            "optima; screening only (no endorsed conversion exists)"
        )
    else:
        note = "screening against a reference optimum (confidence low), not a verdict"
    inside = optimum_min <= ph.value <= optimum_max
    return {
        "status": "within_reference_optimum" if inside else "outside_reference_optimum",
        "ph_value": ph.value,
        "ph_medium": ph.medium,
        "optimum_range": [optimum_min, optimum_max],
        "optimum_source": source_citation,
        "screening_note": note,
    }


def salinity_class_for_ece(ec_ds_m: float) -> dict[str, Any]:
    """FAO Soils Bulletin 62 salinity class — ECe ONLY."""
    v = float(ec_ds_m)
    if v < 0:
        raise SoilValidationError("negative EC — refusing")
    for entry in EC_E_SALINITY_CLASSES:
        lo, hi = entry["range_dS_m"]
        if lo <= v < hi:
            return {
                "ec_value": v,
                "ec_type": "ECe (saturated paste extract)",
                "salinity_class": entry["class"],
                "citation": entry["citation"],
                "indicative": True,
                "note": (
                    "indicative FAO class on the ECe scale; local crop response "
                    "depends on crop, soil, climate and management"
                ),
            }
    raise SoilValidationError("unreachable salinity class lookup")


def check_ec_method_compatibility(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """EC measurements are comparable only with the SAME extraction ratio and
    temperature reference. Cross-ratio comparison is refused (no generic
    conversion is endorsed in M6B)."""
    return (
        (a.get("soil_solution_ratio") or None) == (b.get("soil_solution_ratio") or None)
        and (a.get("temperature_note") or None) == (b.get("temperature_note") or None)
        and (a.get("ec_type") or None) == (b.get("ec_type") or None)
    )

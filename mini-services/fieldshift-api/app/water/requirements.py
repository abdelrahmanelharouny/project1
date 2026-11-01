"""Irrigation requirements ladder (Milestone 6A — Phase 4).

The seven quantities of the water ladder, each first-class and labelled:

  1. crop evapotranspiration            ETc
  2. effective rainfall                 Pe
  3. soil-water contribution            ΔSW   (from the root-zone balance;
                                              "not evaluated" without soil inputs)
  4. net irrigation requirement         NIR = max(0, ETc − Pe − ΔSW)
  5. gross irrigation requirement       GIR = NIR / Ea   (only when Ea exists)
  6. actual irrigation applied          farmer records (usually unknown)
  7. available water allocation         farmer-supplied (never inferred)

Without soil-water inputs the ladder falls back to the FAO I&D Paper 33
seasonal method (IN = ET crop − Pe) — disclosed, and an upper bound because
ΔSW ≥ 0 in that mode.

Unit rules (hard identities, property-tested):
  1 mm over 1 m² = 1 L   → litres = mm × area_m²
  1 mm over 1 ha = 10 m³ → m³ = mm × area_ha × 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.water.contracts import MM_PER_HA_TO_M3


def mm_to_m3(mm: float, area_ha: float) -> float:
    """Convert a depth (mm) over an area (ha) to a volume (m³). Exact identity
    1 mm·ha = 10 m³; non-positive areas are rejected."""
    if area_ha <= 0:
        raise ValueError("area_ha must be positive")
    if mm < 0:
        raise ValueError("depth must be non-negative")
    return mm * area_ha * MM_PER_HA_TO_M3


def litres_from_mm_m2(mm: float, area_m2: float) -> float:
    """1 mm over 1 m² = 1 L (the solver's exact-litre identity)."""
    if area_m2 <= 0:
        raise ValueError("area_m2 must be positive")
    if mm < 0:
        raise ValueError("depth must be non-negative")
    return mm * area_m2


@dataclass(frozen=True)
class RequirementStep:
    quantity: str            # etc | effective_rainfall | soil_water_contribution | ...
    value_mm: float | None
    status: str              # evaluated | not_evaluated | unknown | not_supplied
    basis: str               # formula/method actually used
    detail: str | None = None
    source_refs: tuple[dict[str, Any], ...] = ()


def build_requirements_ladder(
    *,
    etc_mm: float | None,
    pe_mm: float | None,
    pe_basis: str,
    soil_water_contribution_mm: float | None,
    soil_contribution_basis: str | None,
    efficiency: Any | None,     # EfficiencyInput | None
    actual_applied_mm: float | None,
    area_ha: float,
) -> dict[str, Any]:
    """Evaluate the ladder with honest statuses. Returns a dict of
    RequirementStep-shaped entries plus the derived volumes in m³."""

    def step(quantity, value, status, basis, detail=None) -> dict[str, Any]:
        return {
            "quantity": quantity,
            "value_mm": None if value is None else round(float(value), 4),
            "status": status,
            "basis": basis,
            "detail": detail,
        }

    # 1) ETc — must be evaluated for any requirement at all
    if etc_mm is None:
        nir = None
        nir_basis = "not evaluated"
        ladder = [
            step("crop_evapotranspiration", None, "not_evaluated", "ETc = Kc × ET0 "
                 "(ET0/Kc evidence missing — requirement not evaluated)"),
            step("effective_rainfall", pe_mm, "evaluated" if pe_mm is not None else "not_evaluated",
                 pe_basis),
            step("soil_water_contribution", None, "not_evaluated",
                 soil_contribution_basis or "no soil water-holding inputs"),
            step("net_irrigation_requirement", None, "not_evaluated", "not evaluated"),
        ]
    else:
        # 2/3) Pe and ΔSW
        if pe_mm is None:
            used_pe = 0.0
            pe_status = "not_evaluated"
            pe_note = (
                "effective rainfall not evaluable — NO rainfall credit assumed "
                "(conservative: the requirement is never under-stated)"
            )
        else:
            used_pe = pe_mm
            pe_status = "evaluated"
            pe_note = None
        dsw_known = soil_water_contribution_mm is not None
        used_dsw = soil_water_contribution_mm if dsw_known else 0.0

        nir_value = max(0.0, etc_mm - used_pe - used_dsw)
        if dsw_known and pe_mm is not None:
            nir_basis = "NIR = max(0, ETc − Pe − ΔSW) — full water balance"
        elif dsw_known:
            nir_basis = "NIR = max(0, ETc − ΔSW) — no rainfall credit (conservative)"
        elif pe_mm is not None:
            nir_basis = (
                "NIR = max(0, ETc − Pe) — FAO I&D Paper 33 seasonal method "
                "(IN = ET crop − Pe); soil-water contribution not evaluated, so "
                "this is an upper bound"
            )
        else:
            nir_basis = (
                "NIR = ETc — neither rainfall credit nor soil-water contribution "
                "evaluable; this is the conservative upper bound"
            )
        nir = round(nir_value, 4)

        ladder = [
            step("crop_evapotranspiration", etc_mm, "evaluated", "ETc = Kc × ET0"),
            step("effective_rainfall", pe_mm, pe_status, pe_basis, pe_note),
            step(
                "soil_water_contribution",
                soil_water_contribution_mm,
                "evaluated" if dsw_known else "not_evaluated",
                soil_contribution_basis or "no soil water-holding inputs supplied — "
                "the FAO-33 no-storage fallback is used (disclosed)",
            ),
            step("net_irrigation_requirement", nir, "evaluated", nir_basis),
        ]

    # 4) volumes (exact unit identities)
    volumes: dict[str, Any] = {}
    if nir is not None:
        volumes["net_irrigation_requirement_m3"] = round(mm_to_m3(nir, area_ha), 4)
    if etc_mm is not None:
        volumes["crop_evapotranspiration_m3"] = round(mm_to_m3(etc_mm, area_ha), 4)
    if pe_mm is not None:
        volumes["effective_rainfall_m3"] = round(mm_to_m3(pe_mm, area_ha), 4)

    # 5) gross requirement — ONLY when application efficiency exists
    gir = None
    if nir is not None and efficiency is not None and efficiency.value > 0:
        gir = round(nir / efficiency.value, 4)
        volumes["gross_irrigation_requirement_m3"] = round(mm_to_m3(gir, area_ha), 4)
        ladder.append(step(
            "gross_irrigation_requirement", gir, "evaluated",
            f"GIR = NIR / Ea with Ea = {efficiency.value} "
            f"({efficiency.evidence_class})",
            efficiency.citation_text,
        ))
    else:
        ladder.append(step(
            "gross_irrigation_requirement", None, "not_evaluated",
            "no applicable field application efficiency supplied — the gross "
            "requirement is never assumed from a default",
        ))

    # 6) actual applied — farmer records
    ladder.append(step(
        "actual_irrigation_applied", actual_applied_mm,
        "not_supplied" if actual_applied_mm is None else "evaluated",
        "farmer irrigation records",
        "actual application is unknown unless the farmer supplies records — "
        "it is never inferred from the allocation or the requirement",
    ))

    return {"steps": ladder, "volumes_m3": volumes}

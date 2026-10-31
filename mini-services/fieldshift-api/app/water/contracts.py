"""Water Intelligence Engine — decision core (Milestone 6A, ADR-0015/0019).

Pure module: no ORM, no HTTP, no I/O (the same independence rule as
`app/rotation`). Versioned surfaces:

- WATER_ENGINE_VERSION  — the calculation engine (this package)
- WATER_METHODS_VERSION — the methodology catalog (effective-rainfall methods,
  soil sources, efficiency classes and their citations)
- PTF_VERSION           — the Saxton & Rawls (2006) pedotransfer implementation

Honesty contract (inherits the deepening rules): missing ≠ zero; a missing
month never lowers a reported requirement; unknown allocation is never
unlimited; surface soil moisture is never a root-zone claim; synthetic
evidence is labelled end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

WATER_ENGINE_VERSION = "water-engine-1.0.0"
WATER_METHODS_VERSION = "water-methods-1.0.0"
PTF_VERSION = "saxton-rawls-2006-ptf-1.0.0"

# Unit identities (hard rules; property-tested):
#   1 mm over 1 m2 = 1 L   ->  mm * area_m2 = litres
#   1 mm over 1 ha = 10 m3 ->  mm * area_ha * 10 = m3
MM_PER_HA_TO_M3 = 10.0

# FAO-56 Table 22 footnote 2 (verified M6A Phase 0): p = p_table + 0.04*(5-ETc)
P_ETC_ADJUSTMENT_SLOPE = 0.04
P_ETC_ADJUSTMENT_REFERENCE = 5.0

# FAO I&D Paper 33 §4.2 (verified M6A Phase 0): the effective-rainfall formulae
# apply in areas with a maximum slope of 4-5%.
FAO_AGLW_SLOPE_CONDITION = "maximum slope 4-5%"

EFFECTIVE_RAINFALL_METHODS: tuple[str, ...] = (
    "fao_aglw_1986", "constant_fraction", "none",
)

SOIL_SOURCES: tuple[str, ...] = ("none", "farmer_measured", "ptf_texture")

# FAO Training Manual 1 (Brouwer, Goffeau & Heibloem 1985), Annex I Table 8
# (indicative field application efficiencies, verified M6A Phase 0).
IRRIGATION_EFFICIENCY_CLASSES: tuple[dict[str, Any], ...] = (
    {
        "method_class": "surface",
        "efficiency": 0.60,
        "applies_to": "border, furrow, basin",
        "evidence_class": "curated_agronomic_reference",
        "citation_text": (
            "Brouwer, C., Goffeau, A. & Heibloem, M. (1985). Irrigation Water "
            "Management: Training Manual No. 1 — Introduction to Irrigation, "
            "Annex I, Table 8. FAO, Rome."
        ),
    },
    {
        "method_class": "sprinkler",
        "efficiency": 0.75,
        "applies_to": "sprinkler systems",
        "evidence_class": "curated_agronomic_reference",
        "citation_text": (
            "Brouwer, C., Goffeau, A. & Heibloem, M. (1985). Irrigation Water "
            "Management: Training Manual No. 1 — Introduction to Irrigation, "
            "Annex I, Table 8. FAO, Rome."
        ),
    },
    {
        "method_class": "drip",
        "efficiency": 0.90,
        "applies_to": "drip / micro systems",
        "evidence_class": "curated_agronomic_reference",
        "citation_text": (
            "Brouwer, C., Goffeau, A. & Heibloem, M. (1985). Irrigation Water "
            "Management: Training Manual No. 1 — Introduction to Irrigation, "
            "Annex I, Table 8. FAO, Rome."
        ),
    },
)

EFFECTIVE_RAINFALL_METHOD_INFO: dict[str, dict[str, Any]] = {
    "fao_aglw_1986": {
        "code": "fao_aglw_1986",
        "scope": "monthly precipitation totals",
        "formula": "Pe = 0.8·P − 25 for P > 75 mm/month; Pe = 0.6·P − 10 for P ≤ 75; Pe floored at 0",
        "conditions": (
            "Indicative estimation for areas with a maximum slope of 4-5%; "
            "monthly totals (the FAO-33 basis). Daily variants are NOT implemented."
        ),
        "evidence_class": "curated_agronomic_reference",
        "citation_text": (
            "Brouwer, C. & Heibloem, M. (1986). Irrigation Water Management: "
            "Training Manual No. 3 — Irrigation Water Needs, §4.2 (effective "
            "rainfall). FAO Irrigation and Drainage Paper 33. Rome."
        ),
    },
    "constant_fraction": {
        "code": "constant_fraction",
        "scope": "any precipitation aggregation",
        "formula": "Pe = f · P with 0 ≤ f ≤ 1 supplied by the farmer/region",
        "conditions": "The fraction must be supplied explicitly; it is never defaulted.",
        "evidence_class": "farmer_reported_record",
        "citation_text": (
            "Generic constant-fraction approximation; the fraction is a "
            "farmer/region-supplied parameter recorded with the plan."
        ),
    },
    "none": {
        "code": "none",
        "scope": "—",
        "formula": "no effective-rainfall credit",
        "conditions": (
            "Selecting 'none' treats the rainfall credit as unknown; the net "
            "irrigation requirement then equals crop ETc (an upper bound) with "
            "the fallback disclosed."
        ),
        "evidence_class": "curated_agronomic_reference",
        "citation_text": "Explicit no-method selection; recorded for transparency.",
    },
}


# ------------------------------------------------------------------ evidence


@dataclass(frozen=True)
class WaterEvidence:
    """Climate evidence for water calculations, derived from ONE feature run.

    Monthly values are month-of-year climatological means (historical proxy,
    never a forecast). Months absent from the tuples are unknown — they are
    never zero-filled."""

    feature_run_id: str
    is_synthetic: bool
    monthly_et0: tuple[tuple[int, int, float], ...] = ()
    monthly_precip: tuple[tuple[int, int, float], ...] = ()
    coverage_ratio: float = 1.0
    years_used: tuple[int, ...] = ()
    basis: str = (
        "month-of-year climatology from the evidence feature run "
        "(historical proxy, not a forecast)"
    )


@dataclass(frozen=True)
class SoilWaterInputs:
    """Root-zone water-holding inputs with per-item evidence classes.

    Missing items stay None — the dependent balance dimension is reported as
    "(not evaluated)". Volumetric contents are m3/m3."""

    theta_fc: float | None = None                 # field capacity, m3/m3
    theta_fc_evidence_class: str | None = None
    theta_wp: float | None = None                 # wilting point, m3/m3
    theta_wp_evidence_class: str | None = None
    zr_m: float | None = None                     # root-zone depth, m
    zr_evidence_class: str | None = None
    p_table: float | None = None                  # FAO-56 T22 depletion fraction
    p_evidence_class: str | None = None
    source_label: str = "none"                    # none | farmer_measured | ptf_texture
    source_notes: tuple[str, ...] = field(default_factory=tuple)

    def complete_for_balance(self) -> bool:
        return (
            self.theta_fc is not None
            and self.theta_wp is not None
            and self.zr_m is not None
        )


@dataclass(frozen=True)
class EfficiencyInput:
    """Field application efficiency Ea (0 < Ea <= 1) with its provenance."""

    value: float
    evidence_class: str            # farmer_reported_record | curated_agronomic_reference
    citation_text: str | None = None
    method_class: str | None = None


@dataclass(frozen=True)
class WaterPlanRequest:
    season_label: str
    start_date: date
    end_date: date
    crop_code: str
    sowing_date: date | None
    pe_method: str = "fao_aglw_1986"
    pe_fraction: float | None = None
    soil: SoilWaterInputs | None = None
    efficiency: EfficiencyInput | None = None
    water_allocation_m3: float | None = None
    area_ha: float = 0.0

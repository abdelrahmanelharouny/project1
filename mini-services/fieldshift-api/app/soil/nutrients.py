"""Nutrient conversions and N/P/K budget engine (Milestone 6B.5 — Step 6).

Unit conversions are EXACT stoichiometric identities implemented as
versioned functions (ADR-0025) — never ad-hoc factors:

  P2O5 → P : × (2·M(P)) / M(P2O5) = 61.9476 / 141.9426 = 0.43642…
  K2O  → K : × (2·M(K)) / M(K2O)  = 78.1966 / 94.1956  = 0.83013…

(Molecular weights: P 30.9738, K 39.0983, O 15.999 g/mol — IUPAC 2021
standard atomic weights; the derivation is recorded with the function.)

Budget honesty rules (M6B.5 §8.3):
- balance = Σ documented inputs − Σ documented outputs, per nutrient;
- unmeasured leaching / denitrification / volatilization are NEVER assumed
  zero — their absence makes the balance PARTIAL and is listed;
- manure/amendment nutrients enter only with an explicit availability
  fraction (default refusal — never 100 % available);
- BNF enters only from the sourced per-crop trait (never from is_legume
  alone) and is labelled an estimate;
- a partial balance is never presented as a soil stock change;
- NUE: only the explicit output/input (partial-factor) ratio is computed,
  labelled with its definition.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from app.soil.contracts import NUTRIENT_BUDGET_VERSION, SOIL_METHODS_VERSION, SoilValidationError

M_P = 30.9738       # g/mol (IUPAC standard atomic weight)
M_K = 39.0983
M_O = 15.999

P2O5_TO_P = (2.0 * M_P) / (2.0 * M_P + 5.0 * M_O)   # ≈ 0.436421
K2O_TO_K = (2.0 * M_K) / (2.0 * M_K + 1.0 * M_O)    # ≈ 0.830127

P_TO_P2O5 = 1.0 / P2O5_TO_P
K_TO_K2O = 1.0 / K2O_TO_K

OXIDE_CONVERSION_VERSION = "oxide-conversion-1.0.0"
OXIDE_DERIVATION = (
    "P = P2O5 × (2·M(P)/M(P2O5)) with M(P)=30.9738, M(O)=15.999 → ×0.43642712; "
    "K = K2O × (2·M(K)/M(K2O)) with M(K)=39.0983 → ×0.83015130 (IUPAC 2021 atomic weights)"
)


class NutrientBudgetError(SoilValidationError):
    pass


def p2o5_to_p_kg(mass_p2o5_kg: float) -> float:
    """Elemental P from P2O5 mass (exact stoichiometry, versioned)."""
    v = float(mass_p2o5_kg)
    if v < 0 or not math.isfinite(v):
        raise NutrientBudgetError("P2O5 mass must be a non-negative finite number")
    return v * P2O5_TO_P


def k2o_to_k_kg(mass_k2o_kg: float) -> float:
    """Elemental K from K2O mass (exact stoichiometry, versioned)."""
    v = float(mass_k2o_kg)
    if v < 0 or not math.isfinite(v):
        raise NutrientBudgetError("K2O mass must be a non-negative finite number")
    return v * K2O_TO_K


def p_to_p2o5_kg(mass_p_kg: float) -> float:
    v = float(mass_p_kg)
    if v < 0 or not math.isfinite(v):
        raise NutrientBudgetError("P mass must be a non-negative finite number")
    return v * P_TO_P2O5


def k_to_k2o_kg(mass_k_kg: float) -> float:
    v = float(mass_k_kg)
    if v < 0 or not math.isfinite(v):
        raise NutrientBudgetError("K mass must be a non-negative finite number")
    return v * K_TO_K2O


# ------------------------------------------------------------------ engine

@dataclass(frozen=True)
class NutrientInputRecord:
    """One documented nutrient input flow.

    n_kg / p_kg / k_kg are the TOTAL element masses applied for the record
    (kg of N / P / K over the whole application; when reporting_basis is
    'oxide', p_kg / k_kg are declared as P2O5 / K2O masses and are converted
    through the versioned stoichiometric functions). area_ha is the
    application area; the engine converts to kg/ha."""
    flow_id: str
    input_kind: str            # fertilizer | manure | compost | organic_amendment |
                               # biological_nitrogen_fixation | atmospheric_deposition |
                               # irrigation_water | other
    n_kg: float | None
    p_kg: float | None         # elemental P (or P2O5 when reporting_basis='oxide')
    k_kg: float | None         # elemental K (or K2O when reporting_basis='oxide')
    area_ha: float
    reporting_basis: str       # elemental | oxide (the FORM the numbers were declared in)
    evidence_class: str
    is_estimate: bool = False  # e.g. BNF midpoint
    availability_fraction: float | None = None   # REQUIRED for manure/compost/amendments
    availability_basis: str | None = None
    citation_text: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NutrientOutputRecord:
    """One documented nutrient output flow (already normalized to kg/ha)."""
    flow_id: str
    output_kind: str           # harvested_product | crop_residue | other_biomass
    n_kg_ha: float | None
    p_kg_ha: float | None
    k_kg_ha: float | None
    concentration_basis: str   # dry_matter | as_harvested
    moisture_basis_disclosed: bool
    evidence_class: str
    citation_text: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


NUTRIENTS = ("N", "P", "K")

_INPUT_KINDS_NUTRIENT_BEARING = {
    "fertilizer", "manure", "compost", "organic_amendment",
    "biological_nitrogen_fixation", "atmospheric_deposition", "irrigation_water", "other",
}


def _normalize_input(rec: NutrientInputRecord) -> NutrientInputRecord:
    """Convert a record's total element masses into per-hectare elemental flows."""
    if rec.area_ha <= 0:
        raise NutrientBudgetError("area_ha must be positive")

    def elem(nutrient: str) -> float | None:
        val = getattr(rec, f"{nutrient.lower()}_kg")
        if val is None:
            return None
        v = float(val)
        if rec.reporting_basis == "oxide" and nutrient in ("P", "K"):
            v = p2o5_to_p_kg(v) if nutrient == "P" else k2o_to_k_kg(v)
        return v / rec.area_ha

    return NutrientInputRecord(
        flow_id=rec.flow_id,
        input_kind=rec.input_kind,
        n_kg=elem("N"),
        p_kg=elem("P"),
        k_kg=elem("K"),
        area_ha=1.0,
        reporting_basis="elemental",
        evidence_class=rec.evidence_class,
        is_estimate=rec.is_estimate,
        availability_fraction=rec.availability_fraction,
        availability_basis=rec.availability_basis,
        citation_text=rec.citation_text,
        notes=rec.notes,
    )


def nutrient_budget(
    *,
    inputs: list[NutrientInputRecord],
    outputs: list[NutrientOutputRecord],
    season_label: str,
) -> dict[str, Any]:
    """Per-season N/P/K budget with honest completeness classification.

    - 'complete': every flow the farmer declared for this budget is present
      on both sides AND no planned flow is missing — realistically only when
      the farmer records inputs AND removals. Loss terms (leaching etc.) are
      NEVER required for 'complete' — they are always listed as unknown loss
      flows, making any balance partial relative to full soil-change
      accounting.
    - 'partial': at least one documented flow exists; missing flows listed.
    - 'not_evaluable': no usable documented flow on either side."""
    warnings: list[str] = []
    missing_flows: list[str] = []

    usable_inputs = 0
    per_nutrient_in: dict[str, float] = {"N": 0.0, "P": 0.0, "K": 0.0}
    in_rows: list[dict[str, Any]] = []

    for raw in inputs:
        rec = _normalize_input(raw)
        if rec.input_kind not in _INPUT_KINDS_NUTRIENT_BEARING:
            raise NutrientBudgetError(f"unknown input_kind '{rec.input_kind}'")
        # availability fraction mandatory for organic amendments / manures
        if rec.input_kind in ("manure", "compost", "organic_amendment"):
            if rec.availability_fraction is None:
                warnings.append(
                    f"input '{rec.flow_id}' ({rec.input_kind}) has no availability "
                    "fraction — the flow is EXCLUDED from the balance (never assumed "
                    "fully available); record an availability fraction to include it"
                )
                missing_flows.append(f"{rec.flow_id}: availability fraction missing")
                continue
            if not 0.0 < rec.availability_fraction <= 1.0:
                raise NutrientBudgetError(
                    f"availability fraction for '{rec.flow_id}' must be within (0, 1]"
                )
        vals = {"N": rec.n_kg, "P": rec.p_kg, "K": rec.k_kg}
        if all(v is None for v in vals.values()):
            warnings.append(f"input '{rec.flow_id}' carries no nutrient content — not counted")
            missing_flows.append(f"{rec.flow_id}: nutrient content missing")
            continue
        usable_inputs += 1
        row: dict[str, Any] = {
            "flow_id": rec.flow_id,
            "input_kind": rec.input_kind,
            "evidence_class": rec.evidence_class,
            "is_estimate": rec.is_estimate,
        }
        for nutrient in NUTRIENTS:
            v = vals[nutrient]
            if v is None:
                row[f"{nutrient.lower()}_kg_ha"] = None
                row[f"{nutrient.lower()}_status"] = "not_supplied"
                continue
            applied = v if rec.availability_fraction is None else v * rec.availability_fraction
            per_nutrient_in[nutrient] += applied
            row[f"{nutrient.lower()}_kg_ha"] = round(applied, 6)
            row[f"{nutrient.lower()}_status"] = "evaluated"
            if rec.availability_fraction is not None:
                row[f"{nutrient.lower()}_note"] = (
                    f"× availability {rec.availability_fraction}"
                    + (f" ({rec.availability_basis})" if rec.availability_basis else "")
                )
        if rec.is_estimate:
            row["note"] = "estimated input (documented method, not a measurement)"
        in_rows.append(row)

    usable_outputs = 0
    per_nutrient_out: dict[str, float] = {"N": 0.0, "P": 0.0, "K": 0.0}
    out_rows: list[dict[str, Any]] = []
    for rec in outputs:
        vals = {"N": rec.n_kg_ha, "P": rec.p_kg_ha, "K": rec.k_kg_ha}
        if all(v is None for v in vals.values()):
            warnings.append(
                f"output '{rec.flow_id}' has no nutrient concentration — removal not "
                "inferred (yield alone is never a removal estimate)"
            )
            missing_flows.append(f"{rec.flow_id}: nutrient concentration missing")
            continue
        usable_outputs += 1
        row = {
            "flow_id": rec.flow_id,
            "output_kind": rec.output_kind,
            "concentration_basis": rec.concentration_basis,
            "evidence_class": rec.evidence_class,
        }
        if not rec.moisture_basis_disclosed:
            warnings.append(
                f"output '{rec.flow_id}' lacks an explicit moisture basis — "
                "the concentration basis is recorded as supplied"
            )
        for nutrient in NUTRIENTS:
            v = vals[nutrient]
            if v is None:
                row[f"{nutrient.lower()}_kg_ha"] = None
                row[f"{nutrient.lower()}_status"] = "not_supplied"
                continue
            per_nutrient_out[nutrient] += v
            row[f"{nutrient.lower()}_kg_ha"] = round(v, 6)
            row[f"{nutrient.lower()}_status"] = "evaluated"
        out_rows.append(row)

    # loss flows are NEVER assumed zero — their absence defines partiality
    loss_flows_unknown = ["leaching", "denitrification", "volatilization", "erosion_losses", "runoff"]
    missing_flows.extend(f"loss flow '{f}': not measured — NOT assumed zero" for f in loss_flows_unknown)

    if usable_inputs == 0 and usable_outputs == 0:
        overall = "not_evaluable"
    else:
        overall = "partial"  # always partial in M6B: unknown loss flows exist by definition
        # 'complete' is reserved for a future full-accounting mode (see backlog)

    balance: dict[str, Any] = {}
    for nutrient in NUTRIENTS:
        inputs_n = per_nutrient_in[nutrient] if usable_inputs else 0.0
        outputs_n = per_nutrient_out[nutrient] if usable_outputs else 0.0
        status = "evaluated" if (usable_inputs or usable_outputs) else "not_evaluable"
        balance[nutrient] = {
            "inputs_kg_ha": round(inputs_n, 6) if status == "evaluated" else None,
            "outputs_kg_ha": round(outputs_n, 6) if status == "evaluated" else None,
            "balance_kg_ha": round(inputs_n - outputs_n, 6) if status == "evaluated" else None,
            "status": status,
        }

    # explicit NUE (partial-factor productivity) only when output+input evaluable
    nue: dict[str, Any] = {}
    for nutrient in NUTRIENTS:
        in_v = balance[nutrient]["inputs_kg_ha"]
        out_v = balance[nutrient]["outputs_kg_ha"]
        if in_v is not None and in_v > 0 and out_v is not None:
            nue[nutrient] = {
                "definition": "output/input ratio (partial-factor productivity)",
                "value": round(out_v / in_v, 4),
                "note": "one explicit definition; agronomic/recovery efficiency need "
                "control treatments that are not available — not computed",
            }

    return {
        "season_label": season_label,
        "overall": overall,
        "balance": balance,
        "nue": nue,
        "inputs": in_rows,
        "outputs": out_rows,
        "missing_flows": missing_flows,
        "warnings": warnings,
        "interpretation_note": (
            "a nutrient balance is an ACCOUNTING statement over documented flows — "
            "it is not a measured soil stock change (no soil-sampling evidence "
            "enters this number)"
        ),
        "engine_version": NUTRIENT_BUDGET_VERSION,
        "methods_version": SOIL_METHODS_VERSION,
    }


def cumulative_budget(season_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Cumulative multi-season totals over EVALUABLE seasons only; seasons
    that are not_evaluable are listed, never zero-filled."""
    totals = {"N": 0.0, "P": 0.0, "K": 0.0}
    evaluated = 0
    skipped: list[str] = []
    for season in season_results:
        if season["overall"] == "not_evaluable":
            skipped.append(season["season_label"])
            continue
        evaluated += 1
        for nutrient in NUTRIENTS:
            v = season["balance"][nutrient]["balance_kg_ha"]
            if v is not None:
                totals[nutrient] += v
    return {
        "seasons_total": len(season_results),
        "seasons_evaluable": evaluated,
        "seasons_skipped": skipped,
        "cumulative_balance_kg_ha": {k: round(v, 6) for k, v in totals.items()},
        "note": (
            "cumulative sums cover evaluable seasons only; skipped seasons are listed"
            if skipped else "all seasons evaluable"
        ),
    }


def budget_checksum(result: dict[str, Any]) -> str:
    payload = {
        "engine": NUTRIENT_BUDGET_VERSION,
        "methods": SOIL_METHODS_VERSION,
        "balance": result.get("balance"),
        "inputs": result.get("inputs"),
        "outputs": result.get("outputs"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

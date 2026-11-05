"""Multi-domain soil health assessment (Milestone 6B.7 — Step 7, ADR-0026/0027).

The assessment is a TRANSPARENT PROFILE of five domains — physical,
chemical, biological, hydrological, organic-matter & nutrient cycling —
each listing available/missing indicators, data quality, trends (only
through the comparability gate) and plain-language interpretation.

Hard rules:
- NO composite score: no validated weighting methodology exists in M6B;
  a single "soil health score" would be an unsupported claim (ADR-0026).
- Temporal trends pass the COMPARABILITY GATE (ADR-0027): same variable,
  same unit, compatible method identity (pH medium/ratio; EC ratio; BD
  basis; extraction method), same depth support. Incompatible history is
  reported as not-comparable WITH the reason — never connected silently.
- Missing biological/other measurements are UNKNOWN, never "poor health".
- Every interpretation cites the reference methodology that grounds it and
  states its local-applicability status (reference-grade until an
  agronomist confirms regionally).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.soil.contracts import SOIL_ENGINE_VERSION, SOIL_METHODS_VERSION

ASSESSMENT_VERSION = "soil-health-profile-1.0.0"

DOMAINS: tuple[str, ...] = (
    "physical", "chemical", "biological", "hydrological", "organic_matter_nutrient_cycling",
)

# variable → domain mapping (the assessment grouping)
DOMAIN_VARIABLES: dict[str, tuple[str, ...]] = {
    "physical": (
        "soil_sand_content", "soil_silt_content", "soil_clay_content",
        "soil_bulk_density", "soil_coarse_fragments", "soil_particle_density",
    ),
    "chemical": (
        "soil_ph", "soil_electrical_conductivity",
        "soil_available_phosphorus", "soil_extractable_potassium",
        "soil_cation_exchange_capacity", "soil_total_nitrogen",
        "soil_nitrate_n", "soil_ammonium_n",
    ),
    "biological": (
        "soil_microbial_biomass_c", "soil_microbial_biomass_n", "soil_respiration",
        "soil_mineralizable_n", "soil_earthworm_abundance", "soil_enzyme_activity",
        "soil_particulate_organic_matter",
    ),
    "hydrological": (
        "soil_water_content_fc", "soil_water_content_pwp",
    ),
    "organic_matter_nutrient_cycling": (
        "soil_organic_carbon", "soil_organic_matter",
    ),
}

VARIABLE_DOMAIN: dict[str, str] = {
    var: domain for domain, vars_ in DOMAIN_VARIABLES.items() for var in vars_
}

# Indicator context for plain-language interpretation (no thresholds —
# descriptive only). Method-comparison keys define the comparability gate.
INDICATOR_NOTES: dict[str, str] = {
    "soil_organic_carbon": (
        "organic carbon is central to soil function (structure, water holding, "
        "nutrient supply); the STOCK needs bulk density and depth — concentration "
        "alone is not a stock"
    ),
    "soil_ph": (
        "pH controls nutrient availability; interpret only against method-matched "
        "references (medium + ratio), never a universal scale"
    ),
    "soil_electrical_conductivity": (
        "EC indicates soluble salts; ECe (saturated paste) is the standard salinity "
        "measure — other extraction ratios are different measurements"
    ),
    "soil_bulk_density": (
        "bulk density reflects compaction/porosity context; compare only within the "
        "same basis (whole-soil vs fine-earth) and moisture conditions"
    ),
    "soil_water_content_fc": "field capacity bounds the plant-available water window (FAO-56 context)",
    "soil_water_content_pwp": "wilting point bounds the plant-available water window (FAO-56 context)",
}

COMPARABILITY_KEYS = (
    "method_code", "medium", "soil_solution_ratio", "bd_basis", "unit",
)


def _method_key(measurement: dict[str, Any]) -> tuple:
    params = measurement.get("method_params") or {}
    return (
        params.get("code"),
        params.get("medium"),
        params.get("soil_solution_ratio"),
        params.get("bd_basis"),
        measurement.get("unit"),
    )


def comparability_gate(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """ADR-0027 gate: history points are comparable only when variable, unit
    and method identity match. Returns {comparable: bool, reason, groups}."""
    if len(history) < 2:
        return {"comparable": False, "reason": "fewer than two measurements — no trend"}
    keys = {_method_key(m) for m in history}
    depths = {(m.get("top_depth_cm"), m.get("bottom_depth_cm")) for m in history}
    if len(keys) > 1:
        return {
            "comparable": False,
            "reason": (
                "measurements differ in method identity (method/medium/ratio/basis/unit) "
                "— analytically different measurements are not merged into a trend "
                "(ADR-0023/0027)"
            ),
            "groups": [str(sorted(k, key=str)) for k in keys],
        }
    if len(depths) > 1:
        return {
            "comparable": False,
            "reason": "measurements cover different depth intervals — cross-depth trends are not computed",
            "groups": [str(sorted(d)) for d in depths],
        }
    return {"comparable": True, "reason": "method + depth identity match", "groups": []}


def _trend(history: list[dict[str, Any]]) -> dict[str, Any]:
    gate = comparability_gate(history)
    if not gate["comparable"]:
        return {"status": "not_comparable", "reason": gate["reason"], "points": len(history)}
    ordered = sorted(history, key=lambda m: m["observed_at"])
    first, last = ordered[0], ordered[-1]
    delta = None
    if first["value"] is not None and last["value"] is not None:
        delta = round(last["value"] - first["value"], 6)
    return {
        "status": "measured_change",
        "first": {"date": first["observed_at"], "value": first["value"], "unit": first["unit"]},
        "last": {"date": last["observed_at"], "value": last["value"], "unit": last["unit"]},
        "delta": delta,
        "caveat": (
            "measured change over compatible measurements; temporal association with "
            "management events is not causation"
        ),
    }


def assess_domains(
    measurements: list[dict[str, Any]],
    *,
    field_id: str,
) -> dict[str, Any]:
    """The multi-domain assessment payload (no score, ADR-0026)."""
    by_var: dict[str, list[dict[str, Any]]] = {}
    for m in measurements:
        if m.get("value") is None and m.get("result_qualifier") is None:
            continue
        by_var.setdefault(m["variable_code"], []).append(m)

    domain_rows: list[dict[str, Any]] = []
    for domain in DOMAINS:
        domain_vars = DOMAIN_VARIABLES[domain]
        available: list[dict[str, Any]] = []
        missing: list[str] = []
        for var in domain_vars:
            history = by_var.get(var, [])
            if not history:
                missing.append(var)
                continue
            latest = sorted(history, key=lambda m: m["observed_at"])[-1]
            entry: dict[str, Any] = {
                "variable_code": var,
                "latest_value": latest["value"],
                "unit": latest["unit"],
                "observed_at": latest["observed_at"],
                "evidence_class": latest["evidence_class"],
                "source_kind": latest.get("source_kind"),
                "quality_status": latest.get("quality_status"),
                "method": (latest.get("method_params") or {}).get("code"),
                "uncertainty": latest.get("uncertainty_value"),
                "depth": [latest.get("top_depth_cm"), latest.get("bottom_depth_cm")],
                "interpretation_note": INDICATOR_NOTES.get(var),
                "local_applicability": (
                    "reference-grade — no regional confirmation; agronomist review "
                    "required for local claims"
                ),
            }
            if len(history) >= 2:
                entry["trend"] = _trend(history)
            available.append(entry)
        synthetic = any(
            m.get("is_synthetic") for hist in by_var.values() for m in hist
        )
        domain_rows.append({
            "domain": domain,
            "available": available,
            "missing": missing,
            "available_count": len(available),
            "missing_count": len(missing),
            "data_quality_note": (
                "indicator rows keep their evidence class; mapped predictions are "
                "listed but never mixed into measured series"
            ),
            "synthetic_flag": synthetic,
        })

    return {
        "field_id": field_id,
        "assessment_version": ASSESSMENT_VERSION,
        "engine_version": SOIL_ENGINE_VERSION,
        "methods_version": SOIL_METHODS_VERSION,
        "domains": domain_rows,
        "composite_score": None,
        "composite_note": (
            "no composite index is computed: no validated weighting methodology is "
            "available to the platform; a transparent per-domain profile is the "
            "decision surface (ADR-0026)"
        ),
        "missing_is_not_bad_note": (
            "missing indicators are UNKNOWN — their absence is not evidence of "
            "poor soil health"
        ),
    }


def assessment_checksum(result: dict[str, Any]) -> str:
    payload = {
        "engine": result.get("engine_version"),
        "assessment": result.get("assessment_version"),
        "domains": result.get("domains"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------- VOI

# Decision-linked, QUALITATIVE data-collection priorities (M6B.10, ADR-0028).
# Each entry states the DECISION a measurement unblocks — never a fabricated
# cost/benefit/confidence number.
VOI_RULES: tuple[dict[str, str], ...] = (
    {
        "variable_code": "soil_electrical_conductivity",
        "trigger": "any field without salinity evidence",
        "decision_unblocked": (
            "salinity screening for crop choice (ECe classes; FAO Soils Bulletin 62)"
        ),
        "priority_basis": "salinity is crop-limiting where present and invisible to the other indicators",
    },
    {
        "variable_code": "soil_organic_carbon",
        "trigger": "concentration present without bulk density",
        "decision_unblocked": "SOC stock accounting (needs OC + BD + depth + coarse fragments)",
        "priority_basis": "concentration rows exist but the stock stays not-evaluated without BD",
    },
    {
        "variable_code": "soil_bulk_density",
        "trigger": "SOC stock not evaluable",
        "decision_unblocked": "SOC stock + porosity + fixed-depth vs ESM comparisons",
        "priority_basis": "single measurement unlocking three stock-level calculations",
    },
    {
        "variable_code": "soil_water_content_fc",
        "trigger": "no water-retention evidence",
        "decision_unblocked": (
            "measured root-zone AWC feeding the M6A water balance (replacing the "
            "texture-PTF estimate with a measurement)"
        ),
        "priority_basis": "measured θFC/θWP upgrade the water plan's soil layer from estimate to measurement",
    },
    {
        "variable_code": "soil_water_content_pwp",
        "trigger": "no water-retention evidence",
        "decision_unblocked": "measured AWC (θFC − θWP) for the M6A water balance",
        "priority_basis": "AWC needs both potentials",
    },
    {
        "variable_code": "soil_available_phosphorus",
        "trigger": "no P evidence",
        "decision_unblocked": "P availability context for fertility decisions (extractant-specific)",
        "priority_basis": "P is the most method-sensitive major nutrient",
    },
    {
        "variable_code": "soil_ph",
        "trigger": "no pH evidence",
        "decision_unblocked": "crop pH screening against EcoCrop optima (labelled screening)",
        "priority_basis": "pH gates nutrient availability interpretation",
    },
)


def data_readiness(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    """Qualitative, decision-linked VOI ranking (ADR-0028)."""
    present = {
        m["variable_code"]
        for m in measurements
        if m.get("value") is not None
    }
    bd_basis_known = any(
        (m.get("method_params") or {}).get("bd_basis")
        for m in measurements
        if m["variable_code"] == "soil_bulk_density"
    )
    priorities: list[dict[str, str]] = []
    for rule in VOI_RULES:
        var = rule["variable_code"]
        if var in present:
            continue
        if var == "soil_organic_carbon" and var not in present:
            continue  # OC concentration itself is suggested by the BD rule context
        if var == "soil_bulk_density" and bd_basis_known:
            continue
        priorities.append({
            "variable_code": var,
            "trigger": rule["trigger"],
            "decision_unblocked": rule["decision_unblocked"],
            "priority_basis": rule["priority_basis"],
        })
    return {
        "priorities": priorities,
        "collected_note": (
            "record newly collected measurements through the sampling domain — the "
            "ranking re-evaluates automatically"
        ),
        "policy": (
            "qualitative, decision-linked ranking only: no sampling costs, expected "
            "benefits or statistical confidence are invented (ADR-0028)"
        ),
        "engine_version": SOIL_ENGINE_VERSION,
    }

"""Cover-crop candidate & planning engine (M6C Increment 4).

A transparent candidate evaluation over the ACTIVE knowledge packs — not a
universal species ranking. REUSES the platform's existing engines (red line:
no parallel water model):

- knowledge loading: `app.knowledge.service.load_knowledge` (active packs)
- climate evidence: the M5 feature-run bridge (`app.rotation.service`),
  month-of-year climatology explicitly labelled a historical proxy
- water: the versioned M6A engine's shared FAO-56 single-Kc curve +
  FAO-33 effective rainfall (`app.rotation.candidates.estimate_*` wrap
  `app.water.curve`); faba_bean's deliberate Kc gap stays unevaluated
- rotation compatibility: `rotation_rules` (cover_crop_suitability /
  host_pathogen / host_pest) — reference rules inform conditions, nothing
  is hard-blocked without confirmed_regional status

Candidate classes: eligible | conditional | excluded | not_evaluated.
Missing evidence NEVER becomes eligibility: a candidate with unevaluated
water or termination knowledge is `conditional` with the unmet conditions
listed, never `eligible` (spec §4.2/4.4).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.rotation.candidates import (
    estimate_net_irrigation_mm,
    estimate_water_requirement_mm,
)
from app.rotation.problem import SeasonSpec

# Dimensions that must be EVALUATED (not merely informational) for a
# candidate to reach `eligible`. Missing any of these keeps the candidate
# conditional with the named conditions.
CRITICAL_DIMENSIONS = ("sowing_window", "water_trade_off", "termination")


def _reason(kind: str, code: str, message: str, *, severity: str = "info",
            source_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    reason = {"kind": kind, "code": code, "message": message, "severity": severity}
    if source_refs:
        reason["source_refs"] = source_refs
    return reason


def _trait_ref(trait: Any) -> dict[str, Any]:
    return {
        "type": "knowledge_trait",
        "trait_code": trait.trait_code,
        "pack_code": trait.pack_code,
        "pack_version": trait.pack_version,
        "source_key": trait.source_key,
        "citation_text": trait.citation_text,
        "evidence_class": trait.evidence_class,
        "confidence": trait.confidence,
    }


def _mmdd_to_date(year: int, mmdd: str) -> dt.date:
    month, day = mmdd.split("-")
    return dt.date(year, int(month), int(day))


def _sowing_overlap(
    window_start: dt.date, window_end: dt.date,
    planting_start: str, planting_end: str,
) -> tuple[dt.date, dt.date] | None:
    """Overlap of the recurring MM-DD planting window with the available
    cover window, handling year-wrapping windows."""
    years = {window_start.year, window_start.year - 1, window_start.year + 1}
    for base_year in sorted(years):
        try:
            ws = _mmdd_to_date(base_year, planting_start)
        except ValueError:
            continue
        we_year = base_year + 1 if planting_end <= planting_start else base_year
        try:
            we = _mmdd_to_date(we_year, planting_end)
        except ValueError:
            continue
        lo, hi = max(ws, window_start), min(we, window_end)
        if lo <= hi:
            return lo, hi
    return None


def _cover_windows(crop: Any, hemisphere: str, country_code: str):
    return [
        w for w in crop.calendar_windows
        if w.hemisphere == hemisphere and (w.region_code is None or w.region_code == country_code)
    ]


def _functions_for(crop: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Intended functions from EXISTING trait evidence only — family
    membership never implies a function (spec §4.1). Returns (functions,
    unevaluated function notes)."""
    functions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    nfix = crop.trait("n_fixation_capacity_kg_ha")
    if nfix is not None and (
        nfix.value_numeric is not None or nfix.value_low is not None
    ):
        if nfix.value_numeric is not None:
            value_out: dict[str, Any] = {"value": nfix.value_numeric, "unit": nfix.unit or "kg/ha"}
        else:
            value_out = {
                "value_range": [nfix.value_low, nfix.value_high],
                "unit": nfix.unit or "kg/ha",
            }
        functions.append(
            {
                "function_code": "nitrogen_fixation",
                "basis": (
                    "sourced n_fixation_capacity_kg_ha trait (order-of-magnitude "
                    "estimate; subject to species, inoculation, biomass and "
                    "management conditions)"
                ),
                **value_out,
                "confidence": nfix.confidence,
                "source_refs": [_trait_ref(nfix)],
            }
        )
    else:
        gaps.append(
            {
                "function_code": "nitrogen_fixation",
                "message": "no sourced N-fixation trait for this species — the "
                "function is not claimed (family membership alone is not evidence)",
            }
        )
    biomass = crop.trait("cover_biomass_potential_note")
    if biomass is not None and biomass.value_text:
        functions.append(
            {
                "function_code": "soil_cover_biomass",
                "basis": "sourced cover_biomass_potential_note trait",
                "value": biomass.value_text,
                "confidence": biomass.confidence,
                "source_refs": [_trait_ref(biomass)],
            }
        )
    scavenging = crop.trait("cover_n_scavenging_note")
    if scavenging is not None and scavenging.value_text:
        functions.append(
            {
                "function_code": "nutrient_scavenging",
                "basis": "sourced cover_n_scavenging_note trait",
                "value": scavenging.value_text,
                "confidence": scavenging.confidence,
                "source_refs": [_trait_ref(scavenging)],
            }
        )
    return functions, gaps


def evaluate_candidate(
    crop: Any,
    *,
    window_start: dt.date,
    window_end: dt.date,
    next_crop_sowing: dt.date | None,
    next_crop_label: str | None,
    hemisphere: str,
    country_code: str,
    evidence: Any | None,
    soil: Any | None,
    soil_warning: str | None,
    rules: list[Any],
    farmer_excluded: bool,
) -> dict[str, Any]:
    """Evaluate one cover-crop candidate. Pure function over the loaded
    knowledge + field evidence."""
    reasons: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    dimensions: dict[str, dict[str, Any]] = {}
    functions, function_gaps = _functions_for(crop)

    if farmer_excluded:
        return {
            "crop_code": crop.crop_code,
            "crop_label": crop.common_name or crop.crop_code,
            "status": "excluded",
            "reasons": [_reason("farmer_constraint", "farmer_excluded",
                                "Excluded by an explicit farmer exclusion for this plan.", severity="hard")],
            "conditions": [],
            "functions": functions,
            "dimensions": {"sowing_window": {"status": "not_evaluated", "message": "excluded before evaluation"}},
            "missing_inputs": [],
        }

    # ---- sowing window (critical) -----------------------------------------
    windows = _cover_windows(crop, hemisphere, country_code)
    sowing: tuple[dt.date, dt.date] | None = None
    if not windows:
        dimensions["sowing_window"] = {
            "status": "not_evaluated",
            "message": "no regional sowing window for this species in the "
            "knowledge base — the candidate is not evaluated (spec §4.4)",
        }
        return {
            "crop_code": crop.crop_code,
            "crop_label": crop.common_name or crop.crop_code,
            "status": "not_evaluated",
            "reasons": [_reason("knowledge_gap", "no_regional_calendar",
                                "No sourced sowing window exists for this region — "
                                "no agronomic recommendation is generated.")],
            "conditions": [],
            "functions": functions,
            "dimensions": dimensions,
            "missing_inputs": ["regional sowing window"],
        }
    best: tuple[dt.date, dt.date] | None = None
    best_window: Any | None = None
    for w in windows:
        overlap = _sowing_overlap(window_start, window_end, w.planting_start, w.planting_end)
        if overlap and (best is None or (overlap[1] - overlap[0]) > (best[1] - best[0])):
            best = overlap
            best_window = w
    if best is None or best_window is None:
        dimensions["sowing_window"] = {
            "status": "not_evaluated",
            "message": "the species' sowing window does not overlap the available "
            "cover window in this hemisphere/region context",
        }
        return {
            "crop_code": crop.crop_code,
            "crop_label": crop.common_name or crop.crop_code,
            "status": "not_evaluated",
            "reasons": [_reason("window", "sowing_window_no_overlap",
                                "The knowledge base's sowing window for this species "
                                "does not overlap the available window.")],
            "conditions": [],
            "functions": functions,
            "dimensions": dimensions,
            "missing_inputs": [],
        }
    sowing = best
    sowing_evidence = best_window
    dimensions["sowing_window"] = {
        "status": "evaluated",
        "sowing_window": [sowing[0].isoformat(), sowing[1].isoformat()],
        "evidence_class": sowing_evidence.evidence_class,
        "validation_status": sowing_evidence.validation_status,
        "message": (
            "Reference calendar window (evidence class "
            f"'{sowing_evidence.evidence_class}') — requires regional "
            "calibration before operational use."
        ),
    }
    if sowing_evidence.evidence_class == "reference_synthesized":
        reasons.append(
            _reason("evidence", "reference_synthesized_window",
                    "The sowing window is a coarse reference synthesis, not a "
                    "station-verified regional calendar.",
                    severity="warning",
                    source_refs=[{
                        "type": "calendar_window",
                        "pack_code": sowing_evidence.pack_code,
                        "pack_version": sowing_evidence.pack_version,
                        "evidence_class": sowing_evidence.evidence_class,
                    }])
        )

    # ---- time available vs typical duration (informational) ----------------
    duration_days = crop.numeric_trait("duration_days_total")
    days_available = (next_crop_sowing or window_end) - sowing[0]
    days_available = days_available.days
    if duration_days is not None:
        typical = int(duration_days)
        if days_available < typical:
            conditions.append(
                {
                    "code": "window_shorter_than_duration",
                    "message": f"Available window ({days_available} days) is shorter "
                    f"than the species' typical growth duration ({typical} days). "
                    "Early-termination suitability is NOT evaluated — no sourced "
                    "termination knowledge exists, so the engine cannot claim a "
                    "short cycle is acceptable.",
                    "source_refs": [_trait_ref(crop.trait("duration_days_total"))],
                }
            )
            dimensions["growth_duration"] = {
                "status": "conditional",
                "message": f"{days_available} days available vs {typical} days typical duration",
            }
        else:
            dimensions["growth_duration"] = {
                "status": "evaluated",
                "message": f"{days_available} days available for a species whose "
                f"typical duration is {typical} days (cover use may end the cycle "
                "early — see termination dimension)",
            }
    else:
        dimensions["growth_duration"] = {
            "status": "not_evaluated",
            "message": "no sourced growth-duration trait",
        }

    # ---- climate fit (EcoCrop ranges vs window climatology) ----------------
    if evidence is not None and evidence.season_mean_temp_degC is not None:
        tmin_v = crop.numeric_trait("temperature_opt_min") or crop.numeric_trait("temperature_abs_min")
        tmax_v = crop.numeric_trait("temperature_opt_max") or crop.numeric_trait("temperature_abs_max")
        if tmin_v is not None and tmax_v is not None:
            lo, hi = tmin_v, tmax_v
            t = evidence.season_mean_temp_degC
            if lo <= t <= hi:
                dimensions["climate_temperature"] = {
                    "status": "evaluated",
                    "message": f"Window mean temperature {t}°C within the sourced "
                    f"range {lo}–{hi}°C",
                }
            else:
                conditions.append(
                    {
                        "code": "temperature_outside_sourced_range",
                        "message": f"Window mean temperature {t}°C outside the "
                        f"sourced range {lo}–{hi}°C — establishment risk is "
                        "unquantified (no response-curve evidence).",
                    }
                )
                dimensions["climate_temperature"] = {
                    "status": "conditional",
                    "message": f"{t}°C outside {lo}–{hi}°C",
                }
        else:
            dimensions["climate_temperature"] = {
                "status": "not_evaluated", "message": "no sourced temperature range",
            }
    else:
        dimensions["climate_temperature"] = {
            "status": "not_evaluated",
            "message": "no climate evidence run for this field/window "
            "(create a feature run in the Features tab)",
        }

    # ---- soil fit (pH vs EcoCrop optimum, evidence-classed) ----------------
    if soil is not None and soil.ph is not None:
        ph_value, ph_evidence_class = soil.ph
        ph_min = crop.numeric_trait("ph_opt_min")
        ph_max = crop.numeric_trait("ph_opt_max")
        if ph_min is not None and ph_max is not None:
            lo, hi = ph_min, ph_max
            if lo <= ph_value <= hi:
                dimensions["soil_ph"] = {
                    "status": "evaluated",
                    "message": f"Soil pH {ph_value} ({ph_evidence_class}) within the "
                    f"sourced optimum {lo}–{hi}",
                }
            else:
                conditions.append(
                    {
                        "code": "ph_outside_sourced_optimum",
                        "message": f"Soil pH {ph_value} ({ph_evidence_class}) outside "
                        f"the sourced optimum {lo}–{hi} — amelioration or species "
                        "choice needs local advice.",
                    }
                )
                dimensions["soil_ph"] = {
                    "status": "conditional",
                    "message": f"pH {ph_value} outside {lo}–{hi}",
                }
        else:
            dimensions["soil_ph"] = {"status": "not_evaluated", "message": "no sourced pH optimum"}
    else:
        dimensions["soil_ph"] = {
            "status": "not_evaluated",
            "message": soil_warning or "no soil pH evidence for this field",
        }

    # ---- water trade-off via the M6A engine (critical) ----------------------
    season = SeasonSpec(label="cover_window", start_date=sowing[0],
                        end_date=next_crop_sowing or window_end)
    etc, etc_assumptions = estimate_water_requirement_mm(crop, evidence, season) if evidence is not None else (None, ["no climate evidence"])
    nir, nir_basis, nir_why = (
        estimate_net_irrigation_mm(crop, evidence, season) if evidence is not None else (None, None, ["no climate evidence"])
    )
    water: dict[str, Any] = {"status": "not_evaluated"}
    if etc is not None:
        water = {
            "status": "evaluated",
            "etc_mm": etc,
            "net_irrigation_mm": nir,
            "nir_basis": nir_basis,
            "assumptions": list(etc_assumptions),
            "message": (
                "Cover-season water demand as a FAO-56 single-Kc screening "
                "estimate by the versioned M6A engine — a cover crop CONSUMES "
                "this water; the benefit side is not automatically positive "
                "(spec non-negotiable 5)."
            ),
        }
        conditions.append(
            {
                "code": "cover_consumes_water",
                "message": f"Estimated cover water demand {etc} mm "
                + (f"(net of rainfall credit ≈ {nir} mm) " if nir is not None else "")
                + "before the following crop — weigh against expected cover "
                "benefits; no automatic water benefit is assumed.",
            }
        )
    else:
        water["message"] = "; ".join(etc_assumptions) or "water estimate not evaluable"
        conditions.append(
            {
                "code": "water_trade_off_not_evaluated",
                "message": "Cover water demand is NOT evaluated (" + water["message"] + ") "
                "— the water dimension cannot support an eligibility claim.",
            }
        )
    dimensions["water_trade_off"] = water

    # ---- termination (critical) --------------------------------------------
    term_trait = crop.trait("cover_termination_methods")
    if term_trait is not None and term_trait.value_text:
        dimensions["termination"] = {
            "status": "evaluated",
            "methods": term_trait.value_text,
            "message": "Termination methods from the sourced trait; the WINDOW "
            "remains a decision for the farmer/agronomist (no universal lead "
            "time is encoded).",
            "source_refs": [_trait_ref(term_trait)],
        }
    else:
        dimensions["termination"] = {
            "status": "not_evaluated",
            "message": "no sourced termination knowledge for this species — the "
            "termination window and method must be planned with local "
            "agronomist input (never a default lead time)",
        }
        conditions.append(
            {
                "code": "termination_not_evaluated",
                "message": "Termination options and timing are unknown from the "
                "knowledge base — establish only with a locally planned "
                "termination approach.",
            }
        )

    # ---- following-crop compatibility (rules) --------------------------------
    if next_crop_label:
        applicable = [
            r for r in rules
            if r.rule_type in ("cover_crop_suitability", "host_pathogen", "host_pest")
            and (
                (r.predecessor_kind == "crop" and r.predecessor_key == crop.crop_code)
                or (r.predecessor_kind == "family" and crop.family_key is not None and r.predecessor_key == crop.family_key)
            )
            and (not r.applies_to_regions or country_code in r.applies_to_regions)
        ]
        for rule in applicable:
            hard = rule.validation_status == "confirmed_regional"
            conditions.append(
                {
                    "code": f"rotation_rule_{rule.rule_type}",
                    "message": (
                        f"{rule.rule_type} rule ({rule.mechanism}) — "
                        + ("HARD constraint (confirmed regional)."
                           if hard else
                           "reference knowledge: informs the decision, not a "
                           "hard constraint until locally validated.")
                    ),
                    "severity": "hard" if hard else "advisory",
                    "source_refs": [{
                        "type": "rotation_rule",
                        "rule_code": rule.rule_code,
                        "pack_code": rule.pack_code,
                        "pack_version": rule.pack_version,
                        "citation_text": rule.citation_text,
                        "validation_status": rule.validation_status,
                    }],
                }
            )
        dimensions["following_crop_compatibility"] = {
            "status": "evaluated" if applicable else "not_evaluated",
            "message": (
                f"{len(applicable)} applicable rule(s) against the following crop"
                if applicable
                else "no rotation rule in the knowledge base covers this "
                "cover→following-crop pair (no compatibility claim is made)"
            ),
        }
    else:
        dimensions["following_crop_compatibility"] = {
            "status": "not_evaluated",
            "message": "no following-crop context supplied for this plan",
        }

    # ---- establishment requirements (from practice knowledge, qualitative) ---
    dimensions["establishment_requirements"] = {
        "status": "not_evaluated",
        "message": "establishment requirements (seed rate, sowing technique) are "
        "not sourced for this species — see the cover_cropping practice for "
        "the qualitative requirements",
    }

    # ---- classification -------------------------------------------------------
    critical_missing = [
        d for d in CRITICAL_DIMENSIONS
        if dimensions.get(d, {}).get("status") != "evaluated"
    ]
    if critical_missing:
        status = "conditional"
    else:
        status = "eligible"
    status_reasons = list(reasons)
    if status == "conditional":
        status_reasons.append(
            _reason(
                "knowledge_gap",
                "critical_dimensions_unevaluated",
                "Conditional because critical dimension(s) "
                f"{', '.join(critical_missing)} are not evaluable from current "
                "knowledge — missing evidence is not eligibility (spec §4.2).",
                severity="warning",
            )
        )

    return {
        "crop_code": crop.crop_code,
        "crop_label": crop.common_name or crop.crop_code,
        "status": status,
        "reasons": status_reasons,
        "conditions": conditions,
        "functions": functions,
        "function_gaps": function_gaps,
        "dimensions": dimensions,
        "sowing_window": [sowing[0].isoformat(), sowing[1].isoformat()] if sowing else None,
        "missing_inputs": sorted(
            code for code, dim in dimensions.items()
            if dim.get("status") == "not_evaluated"
        ),
        "trade_off_note": (
            "A cover crop protects soil and can recycle nutrients while also "
            "consuming water and competing with the following crop — this "
            "candidate is presented as a trade-off, never a universal win."
        ),
    }


def evaluate_cover_candidates(
    knowledge: Any,
    *,
    window_start: dt.date,
    window_end: dt.date,
    hemisphere: str,
    country_code: str,
    evidence: Any | None,
    soil: Any | None,
    soil_warning: str | None,
    rules: list[Any],
    next_crop_sowing: dt.date | None = None,
    next_crop_label: str | None = None,
    farmer_excluded_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate every cover-crop-capable crop in the ACTIVE knowledge base."""
    excluded = set(farmer_excluded_codes or [])
    candidates = []
    for crop in sorted(knowledge.crops.values(), key=lambda c: c.crop_code):
        if not crop.is_cover_crop_capable:
            continue
        candidates.append(
            evaluate_candidate(
                crop,
                window_start=window_start,
                window_end=window_end,
                next_crop_sowing=next_crop_sowing,
                next_crop_label=next_crop_label,
                hemisphere=hemisphere,
                country_code=country_code,
                evidence=evidence,
                soil=soil,
                soil_warning=soil_warning,
                rules=rules,
                farmer_excluded=crop.crop_code in excluded,
            )
        )
    global_gaps: dict[str, Any] = {
        "cover_species_count": len(candidates),
        "note": (
            "Only species the knowledge base explicitly marks cover-crop-"
            "capable are evaluated; mixtures are representable in plan items "
            "but no mixture-composition knowledge is bundled, so mixture "
            "candidates are not generated."
        ),
    }
    if not any(c["status"] in ("eligible", "conditional") for c in candidates):
        global_gaps["no_evaluable_candidates"] = (
            "no cover-crop candidate could be evaluated with the current "
            "knowledge — this is an honest result, not a failure"
        )
    return {
        "candidates": candidates,
        "global_gaps": global_gaps,
        "knowledge_pack_refs": list(knowledge.pack_refs),
    }

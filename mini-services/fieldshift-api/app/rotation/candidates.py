"""Candidate generation (Milestone 5.3, ADR-0016; water via M6A engine).

Pure evaluation of knowledge-base crops for the planning seasons of one field.
Outcomes are first-class: `eligible`, `conditionally_eligible`, `excluded`,
`unevaluated` — each with the reasons and the evidence that produced them.
Missing evidence never becomes zero and never becomes an exclusion.

Water requirement is a FAO-56 single-Kc screening estimate (ADR-0017) computed
only when BOTH monthly ET0 evidence and sourced Kc anchors exist; its
assumptions are returned with the estimate. M6A adds the NET IRRIGATION
REQUIREMENT (ETc − Pe, FAO I&D 33 method) when monthly precipitation evidence
exists; the allocation constraint uses the most precise evaluable demand.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.rotation.problem import (
    CandidateAssessment,
    ClimateEvidence,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    SeasonSpec,
    TraitValue,
)
from app.water.curve import (
    KcCurve,
    build_curve,
    season_etc_mm,
)
from app.water.effective_rainfall import effective_rainfall_mm

DURATION_SPILL_TOLERANCE_DAYS = 14  # documented harvest-spill tolerance

# M6A: the effective-rainfall method used for candidate-level net irrigation
# requirements (FAO I&D 33 monthly formula; verified during the M6A Phase-0
# programme). An explicit method parameter per run arrives with the water
# planner; candidates keep the verified default.
CANDIDATE_PE_METHOD = "fao_aglw_1986"


def _reason(
    kind: str, code: str, message: str, *, severity: str = "info",
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reason = {"kind": kind, "code": code, "message": message, "severity": severity}
    if source_refs:
        reason["source_refs"] = source_refs
    return reason


def _missing_dimension(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _trait_ref(trait: TraitValue) -> dict[str, Any]:
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


def _mmdd_to_date(year: int, mmdd: str) -> date:
    month, day = mmdd.split("-")
    return date(year, int(month), int(day))


def _window_planting_overlap(
    season: SeasonSpec, planting_start: str, planting_end: str
) -> tuple[date, date] | None:
    """Overlap of the recurring (MM-DD) planting window with the season,
    handling year-wrapping windows (start > end)."""
    y0, y1 = season.start_date.year, season.end_date.year
    for base_year in (y0, y0 - 1, y0 + 1):
        try:
            ws = _mmdd_to_date(base_year, planting_start)
        except ValueError:
            continue
        we_year = base_year + 1 if planting_end <= planting_start else base_year
        try:
            we = _mmdd_to_date(we_year, planting_end)
        except ValueError:
            continue
        lo = max(ws, season.start_date)
        hi = min(we, season.end_date)
        if lo <= hi:
            return lo, hi
    return None


def _windows_for_field(crop: KnowledgeCrop, hemisphere: str, country_code: str):
    return [
        w
        for w in crop.calendar_windows
        if w.hemisphere == hemisphere and (w.region_code is None or w.region_code == country_code)
    ]


def estimate_water_requirement_mm(
    crop: KnowledgeCrop,
    evidence: ClimateEvidence,
    season: SeasonSpec,
    country_code: str | None = None,
) -> tuple[float | None, list[str]]:
    """FAO-56 single-Kc screening estimate (ADR-0017).

    Returns (mm, assumptions) or (None, [why not evaluable]).

    M6A: the curve construction and season summation live in the versioned
    water engine (`app.water.curve`) — the arithmetic is shared so the
    optimizer coefficients and the water planner can never drift apart."""
    missing: list[str] = []
    if crop.water_params is None:
        missing.append("no sourced Kc parameters in the knowledge base — water "
                       "requirement intentionally not estimated (never guessed)")
        return None, missing
    if evidence.season_et0_mm is None or not evidence.monthly_et0:
        missing.append("no reference ET0 evidence for the season")
        return None, missing

    stage_lengths = {
        "initial": crop.numeric_trait("stage_init_days", country_code),
        "development": crop.numeric_trait("stage_dev_days", country_code),
        "mid": crop.numeric_trait("stage_mid_days", country_code),
        "late": crop.numeric_trait("stage_late_days", country_code),
    }
    missing_stages = [s for s, v in stage_lengths.items() if v is None]
    if missing_stages:
        missing.append("crop stage lengths missing from the knowledge base")
        return None, missing

    wp = crop.water_params
    try:
        curve: KcCurve = build_curve(
            stage_lengths=stage_lengths,
            kc_initial=wp.kc_initial,
            kc_mid=wp.kc_mid,
            kc_late=wp.kc_late,
            source_key=wp.source_key,
            citation_text=wp.citation_text,
            evidence_class=wp.evidence_class,
            pack_code=wp.pack_code,
            pack_version=wp.pack_version,
        )
    except ValueError as exc:
        missing.append(f"curve refused: {exc}")
        return None, missing

    total, _months_used, absent = season_etc_mm(
        curve, season.start_date, season.end_date, season.start_date,
        evidence.monthly_et0,
    )
    if total is None:
        # Deepening F-07: a month of the season without ET0 evidence makes the
        # whole estimate unevaluable — dropping the month would UNDER-report
        # the requirement (a silent partial estimate), and partial compliance
        # must never be labelled as a full estimate.
        missing.extend(
            f"ET0 missing for {label} — the screening estimate is refused "
            "rather than under-reported (no month is silently dropped)"
            for label in absent
        )
        return None, missing

    assumptions = [
        "Sowing assumed at the planning-season start (no farmer sowing date supplied).",
        "FAO-56 single-Kc curve reconstructed from sourced stage anchors "
        "(linear ramp across development and late stages).",
        "Monthly ET0 totals distributed uniformly within each calendar month "
        "(screening estimate — computed by the versioned water engine).",
    ]
    return total, assumptions


def estimate_net_irrigation_mm(
    crop: KnowledgeCrop,
    evidence: ClimateEvidence,
    season: SeasonSpec,
    country_code: str | None = None,
) -> tuple[float | None, str | None, list[str]]:
    """Net irrigation requirement at candidate level (M6A, ADR-0019/0021).

    NIR = max(0, ETc − Pe) with the FAO I&D Paper 33 effective-rainfall
    method on monthly precipitation climatology. The soil-water contribution
    is NOT evaluated at candidate level (no soil inputs here) — the estimate
    is therefore an upper bound, and its basis string says so.

    Returns (nir_mm | None, basis | None, why_not)."""
    if not evidence.monthly_precip:
        return None, None, [
            "no monthly precipitation evidence in the feature run — the net "
            "irrigation requirement is not evaluable (rainfall credit unknown, "
            "never assumed)"
        ]
    etc, etc_assumptions = estimate_water_requirement_mm(crop, evidence, season, country_code)
    if etc is None:
        return None, None, list(etc_assumptions)

    # months of the season
    months: list[tuple[int, int]] = []
    y, m = season.start_date.year, season.start_date.month
    while (y, m) <= (season.end_date.year, season.end_date.month):
        months.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    p_by_month = {(yy, mm): v for yy, mm, v in evidence.monthly_precip}
    absent = [f"{yy:04d}-{mm:02d}" for yy, mm in months if (yy, mm) not in p_by_month]

    pe_total = 0.0
    conservative_months: list[str] = []
    for yy, mm in months:
        p = p_by_month.get((yy, mm))
        if p is None:
            # no rainfall credit for the month (conservative, disclosed)
            conservative_months.append(f"{yy:04d}-{mm:02d}")
            continue
        pe, _info = effective_rainfall_mm(p, CANDIDATE_PE_METHOD)
        if pe is not None:
            pe_total += pe

    nir = max(0.0, etc - pe_total)
    basis = (
        f"NIR = max(0, ETc − Pe), Pe via '{CANDIDATE_PE_METHOD}' on monthly "
        "precipitation climatology; soil-water contribution not evaluated at "
        "candidate level (upper bound)"
    )
    if conservative_months:
        basis += f"; no rainfall credit for {', '.join(conservative_months)} (evidence missing)"
    return round(nir, 2), basis, []


def assess_crop(
    crop: KnowledgeCrop,
    season: SeasonSpec,
    knowledge: KnowledgeBaseData,
    farm: FarmContext,
    evidence: ClimateEvidence | None,
    previous_crop_code: str | None,
) -> CandidateAssessment:
    """Evaluate one crop for one planning season."""
    country = farm.country_code
    reasons: list[dict[str, Any]] = []
    unevaluated: list[dict[str, Any]] = []

    # 0) synthetic-evidence honesty label
    if evidence is not None and evidence.is_synthetic:
        reasons.append(
            _reason(
                "evidence",
                "synthetic_climate_evidence",
                "Climate evidence comes from the SYNTHETIC test fixture — "
                "never real farm evidence; outcomes are demonstration only.",
                severity="warning",
            )
        )

    # 1) farmer market exclusions (hard, farmer authority)
    if crop.crop_code in farm.market_exclusions:
        return CandidateAssessment(
            crop_code=crop.crop_code,
            status="excluded",
            reasons=(
                _reason(
                    "farmer_constraint",
                    "market_exclusion",
                    "Excluded by an explicit farmer market exclusion.",
                    severity="hard",
                ),
            ),
        )

    # 2) equipment limits (hard): only when the knowledge base lists a
    #    requirement trait; absent trait ⇒ no equipment restriction claimed.
    equipment_trait = crop.trait("equipment_required")
    if equipment_trait is not None and equipment_trait.value_text:
        required = equipment_trait.value_text
        if required in farm.equipment_limits:
            return CandidateAssessment(
                crop_code=crop.crop_code,
                status="excluded",
                reasons=(
                    _reason(
                        "farmer_constraint",
                        "equipment_restriction",
                        f"Crop requires '{required}', which the farm flags as unavailable.",
                        severity="hard",
                        source_refs=[_trait_ref(equipment_trait)],
                    ),
                ),
            )

    # 3) calendar compatibility
    windows = _windows_for_field(crop, farm.hemisphere, country)
    if not windows:
        unevaluated.append(
            _missing_dimension(
                "crop_calendar",
                f"No calendar window for hemisphere '{farm.hemisphere}' in the active "
                "knowledge packs — calendar compatibility not evaluated.",
            )
        )
        window_matched = None
        overlap = None
    else:
        window_matched = None
        overlap = None
        for w in windows:
            ov = _window_planting_overlap(season, w.planting_start, w.planting_end)
            if ov is not None:
                window_matched = w
                overlap = ov
                break
        if window_matched is None:
            return CandidateAssessment(
                crop_code=crop.crop_code,
                status="excluded",
                reasons=(
                    _reason(
                        "crop_calendar",
                        "planting_window_outside_season",
                        "No planting window overlaps this planning season "
                        f"(known windows: {', '.join(w.planting_start + '..' + w.planting_end for w in windows)}).",
                        severity="hard",
                        source_refs=[
                            {
                                "type": "crop_calendar_window",
                                "pack_code": w.pack_code,
                                "pack_version": w.pack_version,
                                "source_key": w.source_key,
                                "citation_text": w.citation_text,
                                "evidence_class": w.evidence_class,
                            }
                            for w in windows
                        ],
                    ),
                ),
            )

    # 4) duration fit
    duration = crop.numeric_trait("duration_days_total", country)
    duration_trait = crop.resolve_trait("duration_days_total", country)
    if duration is not None and window_matched is not None:
        overflow = int(duration) - season.length_days
        if overflow <= 0:
            reasons.append(
                _reason(
                    "crop_calendar",
                    "duration_fits",
                    f"Crop duration {int(duration)} d fits the {season.length_days}-d season.",
                    source_refs=[_trait_ref(duration_trait)] if duration_trait else None,
                )
            )
        elif overflow <= DURATION_SPILL_TOLERANCE_DAYS:
            reasons.append(
                _reason(
                    "crop_calendar",
                    "duration_spills",
                    f"Crop duration {int(duration)} d exceeds the season by {overflow} d "
                    f"(within the {DURATION_SPILL_TOLERANCE_DAYS}-d harvest-spill tolerance) "
                    "— conditionally eligible.",
                    severity="conditional",
                    source_refs=[_trait_ref(duration_trait)] if duration_trait else None,
                )
            )
        else:
            return CandidateAssessment(
                crop_code=crop.crop_code,
                status="excluded",
                reasons=(
                    _reason(
                        "crop_calendar",
                        "duration_exceeds_season",
                        f"Crop duration {int(duration)} d exceeds the {season.length_days}-d "
                        f"season by {overflow} d (beyond tolerance).",
                        severity="hard",
                        source_refs=[_trait_ref(duration_trait)] if duration_trait else None,
                    ),
                ),
            )
    elif duration is None and window_matched is not None:
        unevaluated.append(
            _missing_dimension(
                "crop_duration",
                "Crop duration absent from the knowledge base — season fit not verified.",
            )
        )
        reasons.append(
            _reason(
                "crop_calendar",
                "window_matched_duration_unknown",
                "Planting window overlaps the season; duration unknown.",
                severity="conditional",
            )
        )

    # 5) climate suitability (EcoCrop-style ranges vs season aggregates)
    if evidence is None:
        unevaluated.append(
            _missing_dimension(
                "climate_evidence",
                "No feature run available for this field — climate suitability not "
                "evaluated (missing evidence is never treated as zero).",
            )
        )
    else:
        temp_opt_min = crop.numeric_trait("temp_opt_min_degC", country)
        temp_min_abs = crop.numeric_trait("temp_min_abs_degC", country)
        temp_opt_max = crop.numeric_trait("temp_opt_max_degC", country)
        mean_t = evidence.season_mean_temp_degC
        if mean_t is not None and temp_min_abs is not None:
            t_trait_min = crop.resolve_trait("temp_min_abs_degC", country)
            if mean_t < temp_min_abs:
                return CandidateAssessment(
                    crop_code=crop.crop_code,
                    status="excluded",
                    reasons=(
                        _reason(
                            "climate",
                            "temperature_below_absolute_minimum",
                            f"Season mean temperature {mean_t} degC is below the crop's "
                            f"absolute minimum {temp_min_abs} degC.",
                            severity="hard",
                            source_refs=[
                                _trait_ref(t_trait_min) if t_trait_min else {"type": "knowledge_trait", "trait_code": "temp_min_abs_degC"}
                            ],
                        ),
                    ),
                    unevaluated_dimensions=tuple(unevaluated),
                )
        if mean_t is not None and temp_opt_min is not None and temp_opt_max is not None:
            if temp_opt_min <= mean_t <= temp_opt_max:
                reasons.append(
                    _reason(
                        "climate",
                        "temperature_within_optimum",
                        f"Season mean temperature {mean_t} degC within the optimum "
                        f"{temp_opt_min}..{temp_opt_max} degC.",
                        source_refs=[
                            _trait_ref(crop.resolve_trait("temp_opt_min_degC", country))
                        ],
                    )
                )
            else:
                marginal = mean_t >= temp_min_abs if temp_min_abs is not None else True
                reasons.append(
                    _reason(
                        "climate",
                        "temperature_outside_optimum",
                        f"Season mean temperature {mean_t} degC outside the optimum "
                        f"{temp_opt_min}..{temp_opt_max} degC — marginal, needs local "
                        "confirmation.",
                        severity="conditional" if marginal else "warning",
                        source_refs=[
                            _trait_ref(crop.resolve_trait("temp_opt_min_degC", country))
                        ],
                    )
                )

        precip = evidence.season_precipitation_mm
        annual_min = crop.resolve_trait("precip_min_annual_mm", country)
        annual_max = crop.resolve_trait("precip_max_annual_mm", country)
        if precip is not None and (annual_min is not None or annual_max is not None):
            unevaluated.append(
                _missing_dimension(
                    "precipitation_temporal_support",
                    "Seasonal precipitation is not compared with annual crop reference "
                    "ranges; temporal support is incompatible without a matched annual total.",
                )
            )
        # hot days (generic index, NOT crop-specific heat stress)
        if evidence.season_hot_days_35c:
            reasons.append(
                _reason(
                    "climate",
                    "hot_days_observed",
                    f"{evidence.season_hot_days_35c} days >=35 degC in the evidence window "
                    "(generic meteorological index; crop-specific heat stress needs the "
                    "sourced crop thresholds — not applied here).",
                    severity="info",
                )
            )

    # 6) soil pH (evidence class surfaced — SoilGrids is a prediction)
    soil = farm.soil
    ph_opt_min = crop.numeric_trait("ph_opt_min", country)
    ph_opt_max = crop.numeric_trait("ph_opt_max", country)
    if soil is not None and soil.ph is not None and ph_opt_min is not None and ph_opt_max is not None:
        ph_value, ph_evidence_class = soil.ph
        ph_trait = crop.resolve_trait("ph_opt_min", country)
        if ph_opt_min <= ph_value <= ph_opt_max:
            reasons.append(
                _reason(
                    "soil",
                    "ph_within_optimum",
                    f"Soil pH {ph_value} within crop optimum {ph_opt_min}..{ph_opt_max} "
                    f"(soil evidence class: {ph_evidence_class}).",
                    source_refs=[_trait_ref(ph_trait)] if ph_trait else None,
                )
            )
        else:
            reasons.append(
                _reason(
                    "soil",
                    "ph_outside_optimum",
                    f"Soil pH {ph_value} outside crop optimum {ph_opt_min}..{ph_opt_max} "
                    f"— marginal (soil evidence class: {ph_evidence_class}; a 0-5 cm "
                    "model prediction is not a lab measurement).",
                    severity="conditional",
                    source_refs=[_trait_ref(ph_trait)] if ph_trait else None,
                )
            )
    elif soil is None or soil.ph is None:
        unevaluated.append(
            _missing_dimension(
                "soil_ph",
                "No soil pH evidence for the field — soil suitability not evaluated.",
            )
        )

    # 7) water requirement estimate (screening, ADR-0017) + net irrigation
    #    requirement (M6A, ADR-0019/0021)
    water_mm: float | None = None
    water_assumptions: tuple[str, ...] = ()
    nir_mm: float | None = None
    demand_basis: str | None = None
    if evidence is not None:
        water_mm, why_not = estimate_water_requirement_mm(crop, evidence, season, country)
        if water_mm is None:
            unevaluated.append(
                _missing_dimension("water_requirement", " ".join(why_not))
            )
        else:
            water_assumptions = tuple(why_not)  # assumptions when estimated
        nir_mm, demand_basis, nir_why_not = estimate_net_irrigation_mm(
            crop, evidence, season, country
        )
        if nir_mm is None and water_mm is not None:
            demand_basis = (
                "demand basis: ETc screening (net irrigation requirement not "
                f"evaluable — {' '.join(nir_why_not)}); ETc is a conservative "
                "upper bound of irrigation need"
            )
            water_assumptions = water_assumptions + (demand_basis,)

    # 8) rotation history (rule-gated, region-scoped)
    if previous_crop_code is not None:
        from app.knowledge.service import rules_between

        rules = rules_between(knowledge, previous_crop_code, crop.crop_code, country)
        for rule in rules:
            if rule.min_break_seasons < 1:
                reasons.append(
                    _reason(
                        "rotation_knowledge",
                        f"rule_{rule.rule_code}",
                        f"Favourable succession after {previous_crop_code}: {rule.mechanism}",
                        source_refs=[{
                            "type": "rotation_rule",
                            "rule_code": rule.rule_code,
                            "validation_status": rule.validation_status,
                            "source_key": rule.source_key,
                            "citation_text": rule.citation_text,
                        }],
                    )
                )
                continue
            if rule.is_hard_enforceable:
                return CandidateAssessment(
                    crop_code=crop.crop_code,
                    status="excluded",
                    reasons=(
                        _reason(
                            "rotation_knowledge",
                            f"rule_{rule.rule_code}",
                            f"Regionally CONFIRMED rotation rule forbids {previous_crop_code} "
                            f"→ {crop.crop_code} within {rule.min_break_seasons} season(s): "
                            f"{rule.mechanism}",
                            severity="hard",
                            source_refs=[{
                                "type": "rotation_rule",
                                "rule_code": rule.rule_code,
                                "validation_status": rule.validation_status,
                                "source_key": rule.source_key,
                                "citation_text": rule.citation_text,
                            }],
                        ),
                    ),
                )
            reasons.append(
                _reason(
                    "rotation_knowledge",
                    f"rule_{rule.rule_code}",
                    f"REFERENCE rule suggests a break after {previous_crop_code} "
                    f"({rule.mechanism}) — not regionally confirmed; candidate is "
                    "conditionally eligible and the rule is NOT enforced.",
                    severity="conditional",
                    source_refs=[{
                        "type": "rotation_rule",
                        "rule_code": rule.rule_code,
                        "validation_status": rule.validation_status,
                        "source_key": rule.source_key,
                        "citation_text": rule.citation_text,
                    }],
                )
            )

    # ---- resolve status
    hard_excluded = any(r["severity"] == "hard" for r in reasons)
    if hard_excluded:
        status = "excluded"
    elif any(
        dimension["code"] in {"crop_calendar", "climate_evidence"}
        for dimension in unevaluated
    ):
        status = "unevaluated"
    elif unevaluated:
        # Secondary missing dimensions (e.g. soil pH or Kc) are disclosed in
        # unevaluated_dimensions but do not erase other screening evidence.
        # Keep the assessment explicitly conditional rather than fully eligible.
        status = "conditionally_eligible"
    elif any(r["severity"] == "conditional" for r in reasons):
        status = "conditionally_eligible"
    else:
        status = "eligible"

    matched_labels = tuple(
        f"{w.planting_start}..{w.planting_end}" for w in _windows_for_field(crop, farm.hemisphere, country)
    )
    return CandidateAssessment(
        crop_code=crop.crop_code,
        status=status,
        reasons=tuple(r for r in reasons if r is not None),
        unevaluated_dimensions=tuple(unevaluated),
        water_requirement_mm=water_mm,
        water_estimate_assumptions=water_assumptions,
        net_irrigation_requirement_mm=nir_mm,
        water_demand_basis=demand_basis,
        calendar_windows_matched=matched_labels,
    )


def generate_candidates(
    knowledge: KnowledgeBaseData,
    farm: FarmContext,
) -> dict[str, dict[str, CandidateAssessment]]:
    """Evaluate every knowledge-base crop for EVERY planning season.

    Season 0 checks rotation rules against the last history crop; later
    seasons have no known predecessor at candidate time — pairwise rotation
    rules across planned seasons are enforced by the optimizer constraints
    (confirmed rules only) and surfaced as reference evidence in explanations.
    """
    result: dict[str, dict[str, CandidateAssessment]] = {}
    history_codes = [h.get("crop_code") for h in farm.history if h.get("crop_code")]
    for idx, season in enumerate(farm.seasons):
        evidence = farm.climate_by_season.get(season.label)
        previous_crop = history_codes[-1] if (history_codes and idx == 0) else None
        assessments: dict[str, CandidateAssessment] = {}
        for crop_code in sorted(knowledge.crops):
            crop = knowledge.crops[crop_code]
            assessments[crop_code] = assess_crop(
                crop, season, knowledge, farm, evidence, previous_crop
            )
        result[season.label] = assessments
    return result

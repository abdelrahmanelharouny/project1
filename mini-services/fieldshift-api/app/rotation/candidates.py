"""Candidate generation (Milestone 5.3, ADR-0016).

Pure evaluation of knowledge-base crops for the planning seasons of one field.
Outcomes are first-class: `eligible`, `conditionally_eligible`, `excluded`,
`unevaluated` — each with the reasons and the evidence that produced them.
Missing evidence never becomes zero and never becomes an exclusion.

Water requirement is a FAO-56 single-Kc screening estimate (ADR-0017) computed
only when BOTH monthly ET0 evidence and sourced Kc anchors exist; its
assumptions are returned with the estimate.
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

DURATION_SPILL_TOLERANCE_DAYS = 14  # documented harvest-spill tolerance


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
    crop: KnowledgeCrop, evidence: ClimateEvidence, season: SeasonSpec
) -> tuple[float | None, list[str]]:
    """FAO-56 single-Kc screening estimate (ADR-0017).

    Returns (mm, assumptions) or (None, [why not evaluable])."""
    missing: list[str] = []
    if crop.water_params is None:
        missing.append("no sourced Kc parameters in the knowledge base — water "
                       "requirement intentionally not estimated (never guessed)")
        return None, missing
    if evidence.season_et0_mm is None or not evidence.monthly_et0:
        missing.append("no reference ET0 evidence for the season")
        return None, missing

    stage_lengths = {
        "init": crop.numeric_trait("stage_init_days"),
        "dev": crop.numeric_trait("stage_dev_days"),
        "mid": crop.numeric_trait("stage_mid_days"),
        "late": crop.numeric_trait("stage_late_days"),
    }
    if any(v is None for v in stage_lengths.values()):
        missing.append("crop stage lengths missing from the knowledge base")
        return None, missing

    wp = crop.water_params
    init_len = int(stage_lengths["init"])
    dev_len = int(stage_lengths["dev"])
    mid_len = int(stage_lengths["mid"])
    late_len = int(stage_lengths["late"])

    def kc_on_day(day_index: int) -> float:
        if day_index < init_len:
            return wp.kc_initial
        if day_index < init_len + dev_len:
            t = (day_index - init_len) / max(dev_len, 1)
            return wp.kc_initial + t * (wp.kc_mid - wp.kc_initial)
        if day_index < init_len + dev_len + mid_len:
            return wp.kc_mid
        t = (day_index - init_len - dev_len - mid_len) / max(late_len, 1)
        t = min(max(t, 0.0), 1.0)
        return wp.kc_mid + t * (wp.kc_late - wp.kc_mid)

    # Monthly ET0 totals; each month assumed uniform per day (documented).
    et0_by_month = {(y, m): v for y, m, v in evidence.monthly_et0}
    total = 0.0
    y, m = season.start_date.year, season.start_date.month
    while (y, m) <= (season.end_date.year, season.end_date.month):
        et0_month = et0_by_month.get((y, m))
        if et0_month is None:
            missing.append(f"ET0 missing for {y:04d}-{m:02d} — month excluded from estimate")
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
            continue
        if y == season.start_date.year and m == season.start_date.month:
            month_start = season.start_date
        else:
            month_start = date(y, m, 1)
        if y == season.end_date.year and m == season.end_date.month:
            month_end = season.end_date
        else:
            # last day of month
            if m == 12:
                month_end = date(y, 12, 31)
            else:
                month_end = date(y, m + 1, 1).toordinal() - 1
                month_end = date.fromordinal(month_end)
        import calendar as _cal

        days_in_month = _cal.monthrange(y, m)[1]
        month_len = (month_end - month_start).days + 1
        et0_daily = et0_month / days_in_month
        d = month_start
        while d <= month_end:
            day_index = (d - season.start_date).days
            total += kc_on_day(day_index) * et0_daily
            d = date.fromordinal(d.toordinal() + 1)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

    assumptions = [
        "Sowing assumed at the planning-season start (no farmer sowing date supplied).",
        "FAO-56 single-Kc curve reconstructed from sourced stage anchors "
        "(linear ramp across development and late stages).",
        "Monthly ET0 totals distributed uniformly within each calendar month "
        "(screening estimate — the daily water balance arrives in Milestone 7).",
    ]
    return round(total, 2), assumptions


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
    duration = crop.numeric_trait("duration_days_total")
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
        temp_opt_min = crop.numeric_trait("temp_opt_min_degC")
        temp_min_abs = crop.numeric_trait("temp_min_abs_degC")
        temp_opt_max = crop.numeric_trait("temp_opt_max_degC")
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

        precip_min = crop.numeric_trait("precip_min_annual_mm")
        precip_max = crop.numeric_trait("precip_max_annual_mm")
        precip = evidence.season_precipitation_mm
        if precip is not None and precip_min is not None and precip_max is not None:
            if precip < precip_min:
                reasons.append(
                    _reason(
                        "climate",
                        "precipitation_below_reference_range",
                        f"Season precipitation {precip} mm is below the crop's annual "
                        f"reference minimum {precip_min} mm — rainfed deficit likely; "
                        "irrigation-dependent. Compared against an ANNUAL range — a "
                        "coarse screening signal, not a water budget.",
                        severity="conditional",
                        source_refs=[_trait_ref(crop.resolve_trait("precip_min_annual_mm", country))],
                    )
                )
            elif precip > precip_max:
                reasons.append(
                    _reason(
                        "climate",
                        "precipitation_above_reference_range",
                        f"Season precipitation {precip} mm exceeds the crop's annual "
                        f"reference maximum {precip_max} mm — excess-moisture risk.",
                        severity="conditional",
                        source_refs=[_trait_ref(crop.resolve_trait("precip_max_annual_mm", country))],
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
    ph_opt_min = crop.numeric_trait("ph_opt_min")
    ph_opt_max = crop.numeric_trait("ph_opt_max")
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

    # 7) water requirement estimate (screening, ADR-0017)
    water_mm: float | None = None
    water_assumptions: tuple[str, ...] = ()
    if evidence is not None:
        water_mm, why_not = estimate_water_requirement_mm(crop, evidence, season)
        if water_mm is None:
            unevaluated.append(
                _missing_dimension("water_requirement", " ".join(why_not))
            )
        else:
            water_assumptions = tuple(why_not)  # assumptions when estimated

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
    elif unevaluated and any(
        d["code"] == "crop_calendar" for d in unevaluated
    ):
        status = "unevaluated"
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

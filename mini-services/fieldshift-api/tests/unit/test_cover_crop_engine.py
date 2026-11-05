"""Unit: cover-crop candidate & planning engine (M6C Increment 4).

Golden water case is hand-computed independently (uniform Kc=1.0 curve over
120 days with 4 mm/day ET0 → ETc = 480 mm). Honesty properties enforce the
spec red lines: missing evidence never becomes eligibility; functions never
inferred from family membership; no engine-generated termination dates.
"""

import datetime as dt

from app.management.cover_crops import evaluate_candidate, evaluate_cover_candidates
from app.rotation.problem import (
    CalendarWindow,
    ClimateEvidence,
    KnowledgeCrop,
    RotationRuleData,
    SeasonSpec,
    SoilEvidence,
    TraitValue,
    WaterParams,
)
from app.water.curve import season_etc_mm, build_curve  # noqa: F401  (used for cross-ref only)


def _trait(code, value=None, text=None, *, confidence="moderate", evidence="published_reference"):
    return TraitValue(
        trait_code=code, value_numeric=value, value_text=text,
        value_low=None, value_high=None, unit=None, region_code=None,
        evidence_class=evidence, confidence=confidence,
        validation_status="reference", source_key="s1", citation_text="S (2026)",
        pack_code="kp-test", pack_version="v1",
    )


def _crop(**kw) -> KnowledgeCrop:
    base = dict(
        crop_code="test_cover",
        pack_code="kp-test",
        pack_version="v1",
        family_key=None,
        scientific_name=None,
        common_name="Test Cover",
        crop_category=None,
        life_cycle_type=None,
        is_legume=False,
        is_cover_crop_capable=True,
    )
    base.update(kw)
    return KnowledgeCrop(**base)


def _window(crop: KnowledgeCrop, start="09-01", end="11-30", hemi="north"):
    crop.calendar_windows = (
        CalendarWindow(
            region_code=None, hemisphere=hemi, season_code=None,
            planting_start=start, planting_end=end,
            evidence_class="reference_synthesized", validation_status="reference",
            source_key="s1", citation_text="S (2026)",
            pack_code="kp-test", pack_version="v1",
        ),
    )


def _evidence(mean_temp=None, et0_monthly=(), precip_monthly=(), synthetic=False,
              season_et0=None) -> ClimateEvidence:
    return ClimateEvidence(
        feature_run_id="run1",
        is_synthetic=synthetic,
        season_precipitation_mm=None,
        season_mean_temp_degC=mean_temp,
        season_mean_tmax_degC=None,
        season_hot_days_35c=None,
        season_et0_mm=season_et0,
        monthly_et0=et0_monthly,
        coverage_ratio=1.0,
        years_used=(2020, 2024),
        monthly_precip=precip_monthly,
    )


W0, W1 = dt.date(2026, 9, 1), dt.date(2026, 12, 20)


def _rule(**kw) -> RotationRuleData:
    base = dict(
        rule_code="r1", rule_type="cover_crop_suitability",
        predecessor_kind="crop", predecessor_key="test_cover",
        successor_kind="crop", successor_key="maize",
        min_break_seasons=0, mechanism="test mechanism", scope_note=None,
        applies_to_regions=(), validation_status="reference", severity="advisory",
        source_key="s1", citation_text="S (2026)", pack_code="kp-test", pack_version="v1",
    )
    base.update(kw)
    return RotationRuleData(**base)


class TestEligibilityHonesty:
    def test_no_calendar_window_not_evaluated(self):
        crop = _crop()
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        assert out["status"] == "not_evaluated"
        assert "regional sowing window" in out["missing_inputs"]

    def test_window_no_overlap_not_evaluated(self):
        crop = _crop()
        _window(crop, start="03-01", end="04-30")
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        assert out["status"] == "not_evaluated"

    def test_missing_evidence_is_conditional_never_eligible(self):
        """A candidate with valid calendar but NO water/termination knowledge
        must be conditional with named conditions — never eligible."""
        crop = _crop()
        _window(crop)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        assert out["status"] == "conditional"
        codes = {c["code"] for c in out["conditions"]}
        assert "water_trade_off_not_evaluated" in codes
        assert "termination_not_evaluated" in codes
        assert out["dimensions"]["water_trade_off"]["status"] == "not_evaluated"
        assert out["dimensions"]["termination"]["status"] == "not_evaluated"

    def test_farmer_exclusion_hard(self):
        crop = _crop()
        _window(crop)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=True,
        )
        assert out["status"] == "excluded"
        assert out["reasons"][0]["severity"] == "hard"


class TestGoldenWater:
    def test_water_estimate_hand_computed_uniform_curve(self):
        """Uniform Kc=1.0 over 120 days with 4 mm/day ET0 → ETc = 480 mm
        (hand arithmetic, independent of the implementation)."""
        crop = _crop()
        _window(crop)
        for stage, days in (("stage_init_days", 30), ("stage_dev_days", 30),
                            ("stage_mid_days", 30), ("stage_late_days", 30)):
            crop.traits[stage] = _trait(stage, days)
        crop.water_params = WaterParams(
            kc_initial=1.0, kc_mid=1.0, kc_late=1.0,
            evidence_class="published_reference", source_key="s1",
            citation_text="S (2026)", pack_code="kp-test", pack_version="v1",
        )
        # 2026-09-01..2026-12-29 = 120 season days; ET0 = 4 mm/day every day.
        # monthly_et0 values are CALENDAR-MONTH TOTALS (the estimator scales
        # by the in-season fraction), so December = 4 × 31 = 124.
        monthly = tuple(
            (2026, m, 4.0 * days) for m, days in ((9, 30), (10, 31), (11, 30), (12, 31))
        )
        evidence = _evidence(et0_monthly=monthly, season_et0=4.0 * 122)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=dt.date(2026, 12, 29),
            next_crop_sowing=None, next_crop_label=None,
            hemisphere="north", country_code="EG",
            evidence=evidence, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        water = out["dimensions"]["water_trade_off"]
        assert water["status"] == "evaluated"
        assert water["etc_mm"] == 480.0  # 120 days × 4 mm/day, Kc ≡ 1.0
        codes = {c["code"] for c in out["conditions"]}
        assert "cover_consumes_water" in codes
        # termination knowledge still missing → conditional overall
        assert out["status"] == "conditional"

    def test_faba_bean_style_kc_gap_stays_unevaluated(self):
        crop = _crop()
        _window(crop)
        monthly = ((2026, 9, 120.0), (2026, 10, 124.0), (2026, 11, 120.0), (2026, 12, 116.0))
        evidence = _evidence(et0_monthly=monthly)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=evidence, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        assert out["dimensions"]["water_trade_off"]["status"] == "not_evaluated"
        assert "no sourced Kc" in out["dimensions"]["water_trade_off"]["message"]


class TestFunctionsNeverInferred:
    def test_legume_flag_without_trait_claims_nothing(self):
        crop = _crop(is_legume=True)
        _window(crop)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        fn_codes = {f["function_code"] for f in out["functions"]}
        assert "nitrogen_fixation" not in fn_codes
        assert any(
            g["function_code"] == "nitrogen_fixation" for g in out["function_gaps"]
        )

    def test_sourced_nfix_trait_is_claimed_with_conditions(self):
        crop = _crop(is_legume=True)
        crop.traits["n_fixation_capacity_kg_ha"] = _trait(
            "n_fixation_capacity_kg_ha", 80.0, confidence="low"
        )
        _window(crop)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        nfix = next(f for f in out["functions"] if f["function_code"] == "nitrogen_fixation")
        assert nfix["confidence"] == "low"
        assert "management conditions" in nfix["basis"]


class TestRotationRules:
    def test_crop_scoped_reference_rule_is_advisory(self):
        crop = _crop()
        _window(crop)
        rule = _rule()
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label="maize", hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[rule],
            farmer_excluded=False,
        )
        cond = next(c for c in out["conditions"] if c["code"].startswith("rotation_rule"))
        assert cond["severity"] == "advisory"
        assert "not a hard constraint" in cond["message"]

    def test_confirmed_rule_is_hard(self):
        crop = _crop()
        _window(crop)
        rule = _rule(validation_status="confirmed_regional")
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label="maize", hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[rule],
            farmer_excluded=False,
        )
        cond = next(c for c in out["conditions"] if c["code"].startswith("rotation_rule"))
        assert cond["severity"] == "hard"

    def test_region_scoped_rule_ignored_elsewhere(self):
        crop = _crop()
        _window(crop)
        rule = _rule(applies_to_regions=("US",))
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label="maize", hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[rule],
            farmer_excluded=False,
        )
        assert not any(c["code"].startswith("rotation_rule") for c in out["conditions"])

    def test_family_scoped_rule_matches(self):
        crop = _crop(family_key="fabaceae")
        _window(crop)
        rule = _rule(predecessor_kind="family", predecessor_key="fabaceae")
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label="maize", hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[rule],
            farmer_excluded=False,
        )
        assert any(c["code"].startswith("rotation_rule") for c in out["conditions"])


class TestTerminationRedLine:
    def test_engine_never_emits_termination_dates(self):
        """Metamorphic honesty: the engine produces NO termination date at all —
        timing is a farmer/agronomist decision, so 'increasing cover duration'
        can never silently move an engine-generated termination (spec §14.7)."""
        crop = _crop()
        _window(crop)
        blob = str(
            evaluate_candidate(
                crop, window_start=W0, window_end=W1, next_crop_sowing=None,
                next_crop_label="maize", hemisphere="north", country_code="EG",
                evidence=None, soil=None, soil_warning=None, rules=[],
                farmer_excluded=False,
            )
        )
        assert "termination_window" not in blob
        assert "termination_lead_days" not in blob

    def test_sourced_termination_methods_are_surfaced(self):
        crop = _crop()
        _window(crop)
        crop.traits["cover_termination_methods"] = _trait(
            "cover_termination_methods", None, "roller-crimping; herbicide; mowing"
        )
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        term = out["dimensions"]["termination"]
        assert term["status"] == "evaluated"
        assert "roller-crimping" in term["methods"]
        assert "no universal lead time" in term["message"]


class TestSoilAndClimate:
    def test_ph_outside_optimum_is_conditional(self):
        crop = _crop()
        _window(crop)
        crop.traits["ph_opt_min"] = _trait("ph_opt_min", 6.0)
        crop.traits["ph_opt_max"] = _trait("ph_opt_max", 7.5)
        soil = SoilEvidence(ph=(8.4, "direct_field_measurement"))
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=soil, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        assert out["dimensions"]["soil_ph"]["status"] == "conditional"
        assert any(c["code"] == "ph_outside_sourced_optimum" for c in out["conditions"])

    def test_no_soil_evidence_stays_unevaluated(self):
        crop = _crop()
        _window(crop)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=None, soil=None, soil_warning="no soil observations",
            rules=[], farmer_excluded=False,
        )
        assert out["dimensions"]["soil_ph"]["status"] == "not_evaluated"
        assert "no soil observations" in out["dimensions"]["soil_ph"]["message"]


class TestEligibilityImpliesEvaluated:
    def test_eligible_only_when_all_critical_dimensions_evaluated(self):
        """Property: status==eligible ⇒ every critical dimension evaluated.
        Constructed via a fully-known crop (termination methods trait +
        water params + evidence)."""
        crop = _crop()
        _window(crop)
        for stage, days in (("stage_init_days", 20), ("stage_dev_days", 30),
                            ("stage_mid_days", 40), ("stage_late_days", 30)):
            crop.traits[stage] = _trait(stage, days)
        crop.water_params = WaterParams(
            kc_initial=0.3, kc_mid=1.1, kc_late=0.8,
            evidence_class="published_reference", source_key="s1",
            citation_text="S (2026)", pack_code="kp-test", pack_version="v1",
        )
        crop.traits["cover_termination_methods"] = _trait(
            "cover_termination_methods", None, "mowing"
        )
        monthly = tuple((2026, m, 120.0) for m in (9, 10, 11, 12))
        evidence = _evidence(et0_monthly=monthly, season_et0=480.0)
        out = evaluate_candidate(
            crop, window_start=W0, window_end=W1, next_crop_sowing=None,
            next_crop_label=None, hemisphere="north", country_code="EG",
            evidence=evidence, soil=None, soil_warning=None, rules=[],
            farmer_excluded=False,
        )
        from app.management.cover_crops import CRITICAL_DIMENSIONS

        assert out["status"] == "eligible", out["dimensions"]
        assert all(
            out["dimensions"][d]["status"] == "evaluated" for d in CRITICAL_DIMENSIONS
        )


class TestEngineBatch:
    def test_batch_skips_non_cover_crops(self):
        kb = type("KB", (), {})()
        kb.crops = {
            "maize": _crop(crop_code="maize", is_cover_crop_capable=False),
            "cover1": _crop(crop_code="cover1"),
            "cover2": _crop(crop_code="cover2"),
        }
        kb.pack_refs = ()
        kb.rules = ()
        out = evaluate_cover_candidates(
            kb, window_start=W0, window_end=W1, hemisphere="north",
            country_code="EG", evidence=None, soil=None, soil_warning=None,
            rules=[],
        )
        codes = {c["crop_code"] for c in out["candidates"]}
        assert codes == {"cover1", "cover2"}
        assert "maize" not in codes

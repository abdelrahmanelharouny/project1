"""Unit: rotation decision core — candidate generation, constraints, optimizer
determinism, infeasibility reporting, Pareto + preferences (Milestone 5).

All tests construct the pure dataclasses directly — no database, no HTTP
(ADR-0015: the decision core is independent of ORM/HTTP).
"""

from dataclasses import replace
from datetime import date

import pytest

from app.knowledge.packs.seed_pack_v1 import get_seed_pack
from app.knowledge.contracts import KnowledgePackIn
from app.rotation.problem import (
    CalendarWindow,
    CandidateAssessment,
    ClimateEvidence,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    RotationProblem,
    RotationRuleData,
    SeasonSpec,
    SoilEvidence,
    StrategySolution,
    TraitValue,
    WaterParams,
)

PACK_VERSION = "kp-test-1.0"


def _crop(code, family=None, *, legume=False, cover=False, kc=None, duration=120,
          temp_opt=(15, 28), temp_min_abs=5, ph=None, windows=None, traits_extra=None):
    traits: dict[str, TraitValue] = {}

    def t(code_, value=None, low=None, high=None, unit=None):
        traits[code_] = TraitValue(
            trait_code=code_, value_numeric=value, value_text=None, value_low=low,
            value_high=high, unit=unit, region_code=None,
            evidence_class="published_reference", confidence="moderate",
            validation_status="reference", source_key="s", citation_text="citation",
            pack_code="kp", pack_version=PACK_VERSION,
        )

    if duration is not None:
        t("duration_days_total", value=duration, unit="d")
    if kc is not None:
        t("stage_init_days", value=20, unit="d")
        t("stage_dev_days", value=30, unit="d")
        t("stage_mid_days", value=40, unit="d")
        t("stage_late_days", value=30, unit="d")
    if temp_opt:
        t("temp_opt_min_degC", value=temp_opt[0], unit="degC")
        t("temp_opt_max_degC", value=temp_opt[1], unit="degC")
    if temp_min_abs is not None:
        t("temp_min_abs_degC", value=temp_min_abs, unit="degC")
    if ph:
        t("ph_opt_min", value=ph[0], unit="pH")
        t("ph_opt_max", value=ph[1], unit="pH")
    for code_, value in (traits_extra or {}).items():
        t(code_, value=value)
    return KnowledgeCrop(
        crop_code=code, pack_code="kp", pack_version=PACK_VERSION, family_key=family,
        scientific_name=None, common_name=code, crop_category=None,
        life_cycle_type="annual", is_legume=legume, is_cover_crop_capable=cover,
        traits=traits,
        calendar_windows=tuple(windows or ()),
        water_params=WaterParams(
            kc_initial=kc[0], kc_mid=kc[1], kc_late=kc[2],
            evidence_class="published_reference", source_key="s",
            citation_text="citation", pack_code="kp", pack_version=PACK_VERSION,
        ) if kc else None,
    )


def _window(start, end, hemisphere="north", region=None):
    return CalendarWindow(
        region_code=region, hemisphere=hemisphere, season_code=None,
        planting_start=start, planting_end=end, evidence_class="reference_synthesized",
        validation_status="reference", source_key="s", citation_text="citation",
        pack_code="kp", pack_version=PACK_VERSION,
    )


def _rule(code, pred, succ, *, kind="crop", min_break=1, status="reference",
          regions=(), severity="recommended"):
    return RotationRuleData(
        rule_code=code, rule_type="rotation_break",
        predecessor_kind=kind, predecessor_key=pred,
        successor_kind=kind, successor_key=succ,
        min_break_seasons=min_break, mechanism="test mechanism", scope_note=None,
        applies_to_regions=tuple(regions), validation_status=status,
        severity=severity, source_key="s", citation_text="citation",
        pack_code="kp", pack_version=PACK_VERSION,
    )


def _evidence(**kw):
    base = dict(
        feature_run_id="run-1", is_synthetic=False,
        season_precipitation_mm=120.0, season_mean_temp_degC=18.0,
        season_mean_tmax_degC=None, season_hot_days_35c=2.0, season_et0_mm=420.0,
        # Deepening F-07: the estimator refuses partial ET0 coverage (a month
        # dropped from the total would under-report the requirement), so the
        # fixture provides EVERY month of the May 1 - Sep 15 season.
        monthly_et0=(
            (2025, 5, 150.0), (2025, 6, 140.0), (2025, 7, 130.0),
            (2025, 8, 120.0), (2025, 9, 90.0),
        ),
        coverage_ratio=1.0,
    )
    base.update(kw)
    return ClimateEvidence(**base)


def _farm(seasons=None, history=(), *, hemisphere="north", country="EG",
          soil=None, climate=None, exclusions=(), equipment=(), allocation=None,
          margins=None, synthetic=False):
    seasons = seasons or [SeasonSpec(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))]
    return FarmContext(
        field_id="f1", farm_id="farm1", area_ha=10.0, country_code=country,
        hemisphere=hemisphere, seasons=tuple(seasons), soil=soil,
        climate_by_season=climate or {s.label: _evidence() for s in seasons},
        climate_run_refs={s.label: "run-1" for s in seasons},
        history=tuple(history), market_exclusions=tuple(exclusions),
        equipment_limits=tuple(equipment), water_allocation_m3=allocation,
        margin_index_by_crop=dict(margins or {}),
        synthetic_evidence_in_use=synthetic, soil_evidence_class=None,
    )


def _knowledge(crops, rules=()):
    return KnowledgeBaseData(
        pack_refs=({"pack_code": "kp", "pack_version": PACK_VERSION},),
        crops={c.crop_code: c for c in crops},
        rules=tuple(rules),
        confirmed_rule_count=sum(1 for r in rules if r.is_hard_enforceable),
        reference_rule_count=sum(1 for r in rules if not r.is_hard_enforceable),
    )


SUMMER = SeasonSpec(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
WINTER = SeasonSpec(label="w2024", start_date=date(2024, 12, 1), end_date=date(2025, 3, 31))


# ------------------------------------------------------------ candidates


class TestCandidateGeneration:
    def test_calendar_exclusion_with_cited_window(self):
        kb = _knowledge([_crop("maize", "poaceae", duration=140, windows=[_window("04-15", "06-15")])])
        farm = _farm(seasons=[WINTER])
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["w2024"]["maize"]
        assert assessment.status == "excluded"
        codes = {r["code"] for r in assessment.reasons}
        assert "planting_window_outside_season" in codes

    def test_calendar_unevaluated_when_no_window_for_hemisphere(self):
        kb = _knowledge([_crop("maize", "poaceae", duration=140, windows=[_window("11-01", "12-15", hemisphere="south")])])
        farm = _farm(seasons=[SUMMER])
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["maize"]
        assert assessment.status == "unevaluated"
        assert any(d["code"] == "crop_calendar" for d in assessment.unevaluated_dimensions)

    def test_duration_exceeding_season_excluded(self):
        kb = _knowledge([_crop("long", "poaceae", duration=300, windows=[_window("04-01", "05-31")])])
        farm = _farm(seasons=[SUMMER])
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["long"].status == "excluded"

    def test_duration_within_spill_tolerance_is_conditional(self):
        kb = _knowledge([_crop("slightly_long", "poaceae", duration=145, windows=[_window("05-01", "05-31")])])
        farm = _farm(seasons=[SUMMER])
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["slightly_long"].status == "conditionally_eligible"

    def test_market_exclusion_is_hard(self):
        kb = _knowledge([_crop("cotton", "malvaceae", duration=180, windows=[_window("04-15", "06-01")])])
        farm = _farm(exclusions=("cotton",))
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["cotton"]
        assert assessment.status == "excluded"
        assert any(r["kind"] == "farmer_constraint" for r in assessment.reasons)

    def test_missing_climate_evidence_is_unevaluated_not_zero(self):
        kb = _knowledge([_crop("maize", "poaceae", duration=140, windows=[_window("05-01", "06-01")], temp_opt=(15, 28))])
        farm = _farm()  # climate present
        farm.climate_by_season.clear()
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["maize"]
        dims = [d["code"] for d in assessment.unevaluated_dimensions]
        assert "climate_evidence" in dims
        assert assessment.water_requirement_mm is None

    def test_temperature_below_absolute_minimum_excluded(self):
        cold = _evidence(season_mean_temp_degC=2.0)
        kb = _knowledge([_crop("tropical", "poaceae", duration=120, windows=[_window("05-01", "06-01")], temp_min_abs=10)])
        farm = _farm(climate={"s2025": cold})
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["tropical"].status == "excluded"

    def test_water_estimate_present_only_with_kc_and_et0(self):
        kb = _knowledge([
            _crop("with_kc", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
            _crop("no_kc", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=None),
        ])
        farm = _farm()
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["with_kc"].water_requirement_mm is not None
        assert result["s2025"]["with_kc"].water_estimate_assumptions
        assert result["s2025"]["no_kc"].water_requirement_mm is None
        dims = [d["code"] for d in result["s2025"]["no_kc"].unevaluated_dimensions]
        assert "water_requirement" in dims

    def test_reference_rotation_rule_makes_candidate_conditional_not_excluded(self):
        kb = _knowledge(
            [_crop("maize", "poaceae", duration=140, windows=[_window("05-01", "06-01")])],
            rules=[_rule("r_maize_maize", "maize", "maize", status="reference")],
        )
        history = ({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},)
        farm = _farm(history=history)
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["maize"]
        assert assessment.status == "conditionally_eligible"
        rot_reasons = [r for r in assessment.reasons if r["kind"] == "rotation_knowledge"]
        assert rot_reasons and "NOT enforced" in rot_reasons[0]["message"]

    def test_confirmed_regional_rule_excludes_candidate(self):
        kb = _knowledge(
            [_crop("maize", "poaceae", duration=140, windows=[_window("05-01", "06-01")])],
            rules=[_rule("r_confirmed", "maize", "maize", status="confirmed_regional")],
        )
        history = ({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},)
        farm = _farm(history=history)
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["maize"].status == "excluded"

    def test_regional_rule_does_not_apply_to_other_regions(self):
        kb = _knowledge(
            [_crop("maize", "poaceae", duration=140, windows=[_window("05-01", "06-01")])],
            rules=[_rule("r_fr_only", "maize", "maize", status="confirmed_regional", regions=("FR",))],
        )
        history = ({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},)
        farm = _farm(history=history, country="EG")
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assert result["s2025"]["maize"].status != "excluded"

    def test_synthetic_evidence_labelled_on_every_candidate(self):
        kb = _knowledge([_crop("maize", "poaceae", duration=140, windows=[_window("05-01", "06-01")])])
        farm = _farm(synthetic=True, climate={"s2025": _evidence(is_synthetic=True)})
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["maize"]
        assert any(r["code"] == "synthetic_climate_evidence" for r in assessment.reasons)

    def test_soil_ph_outside_optimum_is_conditional_with_evidence_class(self):
        soil = SoilEvidence(ph=(8.6, "global_soil_prediction"))
        kb = _knowledge([_crop("acid_lover", "poaceae", duration=120, windows=[_window("05-01", "06-01")], ph=(5.0, 6.5))])
        farm = _farm(soil=soil)
        from app.rotation.candidates import generate_candidates
        result = generate_candidates(kb, farm)
        assessment = result["s2025"]["acid_lover"]
        assert assessment.status == "conditionally_eligible"
        ph_reason = next(r for r in assessment.reasons if r["code"] == "ph_outside_optimum")
        assert "global_soil_prediction" in ph_reason["message"]

    def test_numeric_trait_uses_region_override_and_keeps_global_fallback(self):
        crop = _crop("maize", duration=140)
        global_trait = crop.traits["duration_days_total"]
        crop.traits["duration_days_total@EG"] = replace(
            global_trait, value_numeric=90, region_code="EG", pack_version="kp-eg-2"
        )
        assert crop.numeric_trait("duration_days_total", "EG") == 90
        assert crop.numeric_trait("duration_days_total", "US") == 140

    def test_seasonal_precipitation_is_not_compared_to_annual_reference(self):
        crop = _crop(
            "maize",
            duration=120,
            windows=[_window("05-01", "06-01")],
            traits_extra={"precip_min_annual_mm": 700.0},
        )
        from app.rotation.candidates import generate_candidates

        assessment = generate_candidates(_knowledge([crop]), _farm())["s2025"]["maize"]
        reason_codes = {reason["code"] for reason in assessment.reasons}
        missing_codes = {dimension["code"] for dimension in assessment.unevaluated_dimensions}
        assert "precipitation_below_reference_range" not in reason_codes
        assert "precipitation_temporal_support" in missing_codes
        assert assessment.status != "eligible"


# ------------------------------------------------------------- optimizer


def _problem(crops, rules=(), *, seasons=(SUMMER,), farm=None, allocation=None):
    kb = _knowledge(crops, rules)
    farm = farm or _farm(seasons=list(seasons))
    from app.rotation.candidates import generate_candidates

    candidates = generate_candidates(kb, farm)
    return RotationProblem(
        field_id="f1", seasons=tuple(seasons), candidates=candidates, knowledge=kb,
        farm=farm, water_allocation_m3=allocation,
        baseline_assignment=tuple((s.label, None) for s in seasons),
        synthetic_evidence=farm.synthetic_evidence_in_use,
    )


class TestOptimizerConstraints:
    def _admissible_two(self):
        return [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25)),
            _crop("wheat", "poaceae", duration=135, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.35)),
        ]

    def test_deterministic_reproducibility(self):
        crops = self._admissible_two()
        p1 = _problem(crops)
        p2 = _problem(crops)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        s1 = optimize_strategy(p1, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        s2 = optimize_strategy(p2, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assert s1.assignment == s2.assignment
        assert s1.objective_value == s2.objective_value

    def test_water_allocation_respected(self):
        crops = [
            _crop("thirsty", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.2, 0.6)),
            _crop("frugal", "fabaceae", duration=110, windows=[_window("05-01", "06-01")], kc=(0.3, 1.0, 0.3), legume=True),
        ]
        # 10 ha with FULL season ET0 (F-07 fixture): frugal ≈386.6 mm →
        # ≈38,659 m3; thirsty ≈497.8 mm → ≈49,780 m3. The allocation sits
        # strictly between the two so only the frugal crop is feasible.
        problem = _problem(crops, allocation=45000.0)
        assert problem.candidates["s2025"]["thirsty"].water_requirement_mm > problem.candidates["s2025"]["frugal"].water_requirement_mm
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        solution = optimize_strategy(problem, "water_priority", dict(PROFILE_WEIGHTS["water_priority"]))
        assignment = dict(solution.assignment)
        assert assignment["s2025"] == "frugal"

    def test_infeasible_when_allocation_too_small(self):
        crops = [
            _crop("thirsty", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.2, 0.6)),
        ]
        problem = _problem(crops, allocation=100.0)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        result = optimize_strategy(problem, "water_priority", dict(PROFILE_WEIGHTS["water_priority"]))
        from app.rotation.optimizer import InfeasibleResult
        assert isinstance(result, InfeasibleResult)
        assert any(c["constraint"] == "water_allocation" for c in result.conflicts)

    def test_water_scores_average_all_seasons_instead_of_reusing_first(self):
        crops = self._admissible_two()
        second = SeasonSpec(label="s2026", start_date=date(2026, 5, 1), end_date=date(2026, 9, 15))
        problem = _problem(crops, seasons=(SUMMER, second))
        from app.rotation.optimizer import _per_crop_scores

        for season_label, values in {
            "s2025": {"barley": 10.0, "wheat": 60.0},
            "s2026": {"barley": 90.0, "wheat": 60.0},
        }.items():
            for crop_code, water_value in values.items():
                problem.candidates[season_label][crop_code] = CandidateAssessment(
                    crop_code=crop_code,
                    status="eligible",
                    water_requirement_mm=water_value,
                )
        scores, _ = _per_crop_scores(problem, ["barley", "wheat"])
        assert scores["water_requirement_mm"]["barley"] > scores["water_requirement_mm"]["wheat"]

    def test_incomplete_water_evidence_omits_weighted_criterion(self):
        crops = [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25)),
            _crop("wheat", "poaceae", duration=135, windows=[_window("05-01", "06-01")], kc=None),
        ]
        problem = _problem(crops)
        from app.rotation.optimizer import _per_crop_scores

        scores, skipped = _per_crop_scores(problem, ["barley", "wheat"])
        assert "water_requirement_mm" not in scores
        assert "water_requirement_mm" in skipped

    def test_confirmed_rotation_break_enforced_pairwise(self):
        crops = [
            _crop("maize", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True),
        ]
        rules = [_rule("r_mm", "maize", "maize", status="confirmed_regional")]
        seasons = (SUMMER, SeasonSpec(label="s2026", start_date=date(2026, 5, 1), end_date=date(2026, 9, 15)))
        problem = _problem(crops, rules, seasons=seasons)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        solution = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assignment = dict(solution.assignment)
        assert assignment["s2025"] != "maize" or assignment["s2026"] != "maize"

    def test_confirmed_rotation_break_enforced_across_history_boundary(self):
        crops = [
            _crop("maize", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True),
        ]
        rules = [_rule("r_mm", "maize", "maize", status="confirmed_regional")]
        farm = _farm(history=({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},))
        problem = _problem(crops, rules, farm=farm)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        solution = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assignment = dict(solution.assignment)
        assert assignment["s2025"] != "maize"

    def test_reference_rules_never_bind_the_solver(self):
        """The seed pack's reference rules must NOT hard-constrain: the same
        problem with a reference-only maize→maize rule still allows maize."""
        crops = [
            _crop("maize", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True),
        ]
        rules = [_rule("r_mm_ref", "maize", "maize", status="reference")]
        farm = _farm(history=({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},))
        problem = _problem(crops, rules, farm=farm)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        solution = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assert isinstance(solution, StrategySolution)

    def test_family_scoped_confirmed_rule(self):
        """A family-level confirmed rule binds BOTH poaceae crops (evidence
        must explicitly justify family scope — here the test rule does)."""
        crops = [
            _crop("maize", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
            _crop("wheat", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.35)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True),
        ]
        rules = [_rule("r_poaceae", "poaceae", "poaceae", kind="family", status="confirmed_regional")]
        farm = _farm(history=({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},))
        problem = _problem(crops, rules, farm=farm)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS
        solution = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assignment = dict(solution.assignment)
        assert assignment["s2025"] not in ("maize", "wheat")


# ------------------------------------------------------------- objectives


class TestObjectivesAndPareto:
    def _solutions(self):
        crops = [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25), traits_extra={"root_depth_effective_m": 0.6}),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True, cover=True, traits_extra={"root_depth_effective_m": 1.2, "n_fixation_capacity_kg_ha": 120}),
        ]
        problem = _problem(crops)
        from app.rotation import objectives as obj
        s1 = StrategySolution(
            strategy_key="a", strategy_kind="optimized", is_baseline=False,
            profile_weights={"soil_health_index": 1.0}, weights_effective={}, skipped_weights={},
            assignment=(("s2025", "soybean"),), objective_value=None, criteria=(),
            constraints_checked=(), evidence_coverage=None,
        )
        s2 = StrategySolution(
            strategy_key="b", strategy_kind="optimized", is_baseline=False,
            profile_weights={"soil_health_index": 1.0}, weights_effective={}, skipped_weights={},
            assignment=(("s2025", "barley"),), objective_value=None, criteria=(),
            constraints_checked=(), evidence_coverage=None,
        )
        out = []
        for s in (s1, s2):
            criteria = obj.evaluate_criteria(problem, dict(s.assignment))
            out.append(StrategySolution(
                strategy_key=s.strategy_key, strategy_kind=s.strategy_kind,
                is_baseline=s.is_baseline, profile_weights=s.profile_weights,
                weights_effective=s.weights_effective, skipped_weights=s.skipped_weights,
                assignment=s.assignment, objective_value=s.objective_value,
                criteria=criteria, constraints_checked=s.constraints_checked,
                evidence_coverage=None,
            ))
        obj.normalize_within_set(out)
        final = []
        for sol in out:
            objective, effective, skipped = obj.weighted_objective(sol)
            final.append(StrategySolution(
                strategy_key=sol.strategy_key, strategy_kind=sol.strategy_kind,
                is_baseline=sol.is_baseline, profile_weights=sol.profile_weights,
                weights_effective=effective, skipped_weights=skipped,
                assignment=sol.assignment, objective_value=objective,
                criteria=sol.criteria, constraints_checked=sol.constraints_checked,
                evidence_coverage=obj.evidence_coverage_of(sol),
            ))
        obj.compute_pareto(final)
        return problem, final

    def test_legume_strategy_wins_soil_health(self):
        _problem, solutions = self._solutions()
        by_key = {s.strategy_key: s for s in solutions}
        soy = next(c for c in by_key["a"].criteria if c.criterion_code == "soil_health_index")
        bar = next(c for c in by_key["b"].criteria if c.criterion_code == "soil_health_index")
        assert soy.raw_value > bar.raw_value

    def test_pareto_marks_dominated_solution(self):
        _problem, solutions = self._solutions()
        by_key = {s.strategy_key: s for s in solutions}
        # 'a' (soybean) is better on soil health; 'b' better on water? barley lower ETc.
        # Both must be on the front UNLESS one strictly dominates on all shared criteria.
        fronts = [s.strategy_key for s in solutions if s.on_pareto_front]
        assert fronts  # at least one non-dominated
        for s in solutions:
            if not s.on_pareto_front:
                assert s.dominated_by

    def test_weight_change_changes_ranking(self):
        """Preference change must be able to change the recommended strategy."""
        crops = [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.0, 0.25), traits_extra={"root_depth_effective_m": 0.6}),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.5, 1.3, 0.6), legume=True, cover=True, traits_extra={"root_depth_effective_m": 1.2, "n_fixation_capacity_kg_ha": 120}),
        ]
        problem = _problem(crops)
        from app.rotation.optimizer import optimize_strategy
        s_water = optimize_strategy(problem, "water_priority", {
            "water_requirement_mm": 1.0, "soil_health_index": 0.0,
            "crop_family_diversity": 0.0, "climate_resilience_index": 0.0,
            "erosion_reduction_index": 0.0, "cover_crop_opportunity": 0.0,
        })
        s_soil = optimize_strategy(problem, "soil_health_priority", {
            "water_requirement_mm": 0.0, "soil_health_index": 1.0,
            "crop_family_diversity": 0.0, "climate_resilience_index": 0.0,
            "erosion_reduction_index": 0.0, "cover_crop_opportunity": 0.0,
        })
        assert dict(s_water.assignment)["s2025"] == "barley"
        assert dict(s_soil.assignment)["s2025"] == "soybean"

    def test_incomplete_soil_data_omits_weighted_criterion(self):
        crops = [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.0, 0.25)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.5, 1.3, 0.6), traits_extra={"root_depth_effective_m": 1.2}),
        ]
        problem = _problem(crops)
        from app.rotation.optimizer import _per_crop_scores

        scores, skipped = _per_crop_scores(problem, ["barley", "soybean"])
        assert "soil_health_index" not in scores
        assert "soil_health_index" in skipped

    def test_missing_economics_never_zero(self):
        crops = [_crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25))]
        problem = _problem(crops)
        from app.rotation import objectives as obj
        criteria = obj.evaluate_criteria(problem, {"s2025": "barley"})
        margin = next(c for c in criteria if c.criterion_code == "economic_margin_index")
        assert not margin.evaluable
        assert margin.raw_value is None
        assert margin.missing_evidence

    def test_farmer_economics_evaluated_when_supplied(self):
        crops = [_crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25))]
        farm = _farm(margins={"barley": 70.0})
        problem = _problem(crops, farm=farm)
        from app.rotation import objectives as obj
        criteria = obj.evaluate_criteria(problem, {"s2025": "barley"})
        margin = next(c for c in criteria if c.criterion_code == "economic_margin_index")
        assert margin.evaluable
        assert margin.raw_value == 70.0


# ------------------------------------------------------------ constraints


class TestConstraintValidator:
    def test_baseline_violation_detected_without_solver(self):
        crops = [
            _crop("maize", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.2, 0.6)),
        ]
        rules = [_rule("r_mm", "maize", "maize", status="confirmed_regional")]
        farm = _farm(history=({"season_label": "s2024", "crop_code": "maize", "crop_label": "Maize"},))
        problem = _problem(crops, rules, farm=farm)
        from app.rotation.constraints import check_all, all_satisfied
        checks = check_all(problem, {"s2025": "maize"})
        assert not all_satisfied(checks)
        assert any(c.status == "violated" and c.constraint_code == "rotation_break_confirmed_regional" for c in checks)

    def test_unevaluated_candidate_rejected_by_validator(self):
        kb = _knowledge([_crop("no_window", "poaceae", duration=120)])
        farm = _farm()
        from app.rotation.candidates import generate_candidates
        candidates = generate_candidates(kb, farm)
        problem = RotationProblem(
            field_id="f1", seasons=(SUMMER,), candidates=candidates,
            knowledge=kb, farm=farm, water_allocation_m3=None,
            baseline_assignment=(("s2025", "no_window"),),
            synthetic_evidence=False,
        )
        from app.rotation.constraints import check_all
        checks = check_all(problem, {"s2025": "no_window"})
        assert any(c.status == "violated" for c in checks)


# ----------------------------------------------------------- explanations


class TestExplanations:
    def test_explanation_blocks_complete(self):
        crops = [
            _crop("barley", "poaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.3, 1.15, 0.25)),
            _crop("soybean", "fabaceae", duration=120, windows=[_window("05-01", "06-01")], kc=(0.4, 1.15, 0.5), legume=True),
        ]
        rules = [_rule("r_ref", "barley", "barley", status="reference")]
        problem = _problem(crops, rules)
        from app.rotation.optimizer import optimize_strategy, PROFILE_WEIGHTS, build_baseline_solution
        from app.rotation.constraints import check_all
        from app.rotation import objectives as obj
        from app.rotation.explain import build_explanations

        sols = [build_baseline_solution(problem, "baseline")]
        for key in ("water_priority", "soil_health_priority"):
            res = optimize_strategy(problem, key, dict(PROFILE_WEIGHTS[key]))
            assert isinstance(res, StrategySolution)
            sols.append(res)
        evaluated = []
        for s in sols:
            criteria = obj.evaluate_criteria(problem, dict(s.assignment))
            evaluated.append(StrategySolution(
                strategy_key=s.strategy_key, strategy_kind=s.strategy_kind,
                is_baseline=s.is_baseline, profile_weights=s.profile_weights,
                weights_effective={}, skipped_weights={}, assignment=s.assignment,
                objective_value=s.objective_value, criteria=criteria,
                constraints_checked=tuple(check_all(problem, dict(s.assignment))),
                evidence_coverage=None,
            ))
        obj.normalize_within_set(evaluated)
        final = []
        for s in evaluated:
            objective, eff, skip = obj.weighted_objective(s)
            final.append(StrategySolution(
                strategy_key=s.strategy_key, strategy_kind=s.strategy_kind,
                is_baseline=s.is_baseline, profile_weights=s.profile_weights,
                weights_effective=eff, skipped_weights=skip, assignment=s.assignment,
                objective_value=objective, criteria=s.criteria,
                constraints_checked=s.constraints_checked,
                evidence_coverage=obj.evidence_coverage_of(s),
            ))
        obj.compute_pareto(final)
        for s in final:
            exp = build_explanations(problem, s, final)
            for block in (
                "why_generated", "recommendation", "constraints_checked",
                "criteria_evaluation", "evidence_references", "data_limitations",
                "expected_benefits", "risks_trade_offs",
                "local_expert_validation_required",
            ):
                assert block in exp, f"missing explanation block {block}"
            assert exp["evidence_references"]
            assert any("screening estimate" in l for l in exp["data_limitations"])
        soil = next(s for s in final if s.strategy_key == "soil_health_priority")
        exp = build_explanations(problem, soil, final)
        assert exp["local_expert_validation_required"]

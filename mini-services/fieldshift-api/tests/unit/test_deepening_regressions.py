"""Scientific deepening regression tests (Pre-M6 deepening program).

Each test targets a finding from docs/deepening/SCIENTIFIC_AUDIT.md (F-xx).
Pure-layer tests only — no database, no HTTP (ADR-0015).
"""

from datetime import date, datetime, timezone

import pytest

from app.features.engine import build_daily_series, compute_feature_drafts
from app.features.catalog import FEATURE_CATALOG
from app.knowledge.contracts import (
    CropIn,
    KnowledgePackIn,
    SourceIn,
    WaterParameterIn,
    validate_pack_cross_references,
)
from app.rotation.candidates import estimate_water_requirement_mm
from app.rotation.constraints import check_all
from app.rotation.objectives import (
    CRITERION_FUNCS,
    compute_pareto,
    evaluate_criteria,
    normalize_within_set,
    weighted_objective,
)
from app.rotation.optimizer import (
    InfeasibleResult,
    optimize_strategy,
    PROFILE_WEIGHTS,
    build_baseline_solution,
)
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

PACK_VERSION = "kp-deepening-1.0"
SEASON = SeasonSpec(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))


# ------------------------------------------------------------------ helpers
def _trait(code, value=None, low=None, high=None, unit=None):
    return TraitValue(
        trait_code=code, value_numeric=value, value_text=None, value_low=low,
        value_high=high, unit=unit, region_code=None,
        evidence_class="published_reference", confidence="moderate",
        validation_status="reference", source_key="s", citation_text="citation",
        pack_code="kp", pack_version=PACK_VERSION,
    )


def _crop(code, family=None, *, legume=False, cover=False, kc=None, duration=120,
          temp_opt=(15, 28), temp_min_abs=5, windows=None):
    traits: dict[str, TraitValue] = {}
    if duration is not None:
        traits["duration_days_total"] = _trait("duration_days_total", value=duration, unit="d")
    if kc is not None:
        for st, dv in (("init", 20), ("dev", 30), ("mid", 40), ("late", 30)):
            traits[f"stage_{st}_days"] = _trait(f"stage_{st}_days", value=dv, unit="d")
    if temp_opt:
        traits["temp_opt_min_degC"] = _trait("temp_opt_min_degC", value=temp_opt[0], unit="degC")
        traits["temp_opt_max_degC"] = _trait("temp_opt_max_degC", value=temp_opt[1], unit="degC")
    if temp_min_abs is not None:
        traits["temp_min_abs_degC"] = _trait("temp_min_abs_degC", value=temp_min_abs, unit="degC")
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


def _evidence(**kw):
    base = dict(
        feature_run_id="run-1", is_synthetic=False,
        season_precipitation_mm=300.0, season_mean_temp_degC=22.0,
        season_mean_tmax_degC=None, season_hot_days_35c=2.0, season_et0_mm=630.0,
        monthly_et0=((2025, 5, 150.0), (2025, 6, 140.0), (2025, 7, 130.0),
                     (2025, 8, 120.0), (2025, 9, 90.0)),
        coverage_ratio=1.0, years_used=(2015, 2024),
    )
    base.update(kw)
    return ClimateEvidence(**base)


def _farm(crops, *, history=(), allocation=None, soil=None):
    knowledge = KnowledgeBaseData(
        pack_refs=({"pack_code": "kp", "pack_version": PACK_VERSION},),
        crops={c.crop_code: c for c in crops},
        rules=(),
    )
    return FarmContext(
        field_id="f1", farm_id="farm1", area_ha=10.0, country_code="EG",
        hemisphere="north", seasons=(SEASON,), soil=soil,
        climate_by_season={SEASON.label: _evidence()},
        climate_run_refs={SEASON.label: "run-1"},
        history=history, market_exclusions=(), equipment_limits=(),
        water_allocation_m3=allocation, margin_index_by_crop={},
        synthetic_evidence_in_use=False, soil_evidence_class=None,
    )


def _problem(crops, *, rules=(), history=(), allocation=None):
    farm = _farm(crops, history=history, allocation=allocation)
    knowledge = KnowledgeBaseData(
        pack_refs=({"pack_code": "kp", "pack_version": PACK_VERSION},),
        crops={c.crop_code: c for c in crops},
        rules=tuple(rules),
        confirmed_rule_count=sum(1 for r in rules if r.is_hard_enforceable),
        reference_rule_count=sum(1 for r in rules if not r.is_hard_enforceable),
    )
    candidates = {
        season.label: {
            code: CandidateAssessment(
                crop_code=code,
                status="conditionally_eligible",
                reasons=({"code": "temperature_within_optimum"},),
                water_requirement_mm=400.0 if "thirsty" in code else 300.0,
            )
            for code in sorted(knowledge.crops)
        }
        for season in farm.seasons
    }
    return RotationProblem(
        field_id="f1", seasons=farm.seasons, candidates=candidates,
        knowledge=knowledge, farm=farm, water_allocation_m3=allocation,
        baseline_assignment=((SEASON.label, None),),
        synthetic_evidence=False,
    )


# ================= F-02: quality filtering in the feature engine =================
class TestF02QualityFilter:
    def _obs(self, *, status, value=5.0, day=15):
        return {
            "id": f"obs-{status}-{day}", "variable_code": "air_temperature_mean",
            "observed_at": datetime(2025, 5, day, 12, tzinfo=timezone.utc),
            "period_start": datetime(2025, 5, day, 12, tzinfo=timezone.utc),
            "period_end": datetime(2025, 5, day, 13, tzinfo=timezone.utc),
            "value": value, "quality_status": status, "time_support": "daily",
            "dataset_product_id": "p1", "processing_version": "v1",
            "evidence_class": "reanalysis_model_estimate", "is_synthetic": False,
        }

    def test_suspect_and_invalid_observations_never_contribute_values(self):
        obs = [
            self._obs(status="valid", value=10.0, day=10),
            self._obs(status="suspect", value=999.0, day=11),
            self._obs(status="invalid", value=-999.0, day=12),
            self._obs(status="valid", value=12.0, day=13),
        ]
        from zoneinfo import ZoneInfo
        series = build_daily_series(obs, "air_temperature_mean", ZoneInfo("Africa/Cairo"))
        assert len(series.cells) == 2  # suspect/invalid days absent
        assert all(c.value < 100 for c in series.cells.values())
        assert series.excluded_quality_statuses == {"suspect": 1, "invalid": 1}

    def test_exclusion_reported_in_engine_warnings(self):
        from zoneinfo import ZoneInfo
        obs = [self._obs(status="suspect", value=999.0, day=10)]
        obs += [self._obs(status="valid", value=10.0, day=d) for d in range(2, 31)]
        drafts, not_evaluated, warnings = compute_feature_drafts(
            observations=obs,
            specs=[FEATURE_CATALOG["air_temperature_mean_monthly"]],
            tz=ZoneInfo("Africa/Cairo"),
            hemisphere="north",
            window_start=datetime(2025, 5, 1, tzinfo=timezone.utc),
            window_end=datetime(2025, 5, 31, tzinfo=timezone.utc),
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test",
            definition_version="test",
        )
        assert any("quality_status 'suspect'" in w for w in warnings)
        computed = [d for d in drafts if d.value is not None]
        assert len(computed) == 1
        # the suspect 999 degC row must not shift the mean
        assert computed[0].value == pytest.approx(10.0)


# ================= F-05: partial Kc anchors are never zero-filled =================
class TestF05KcAnchors:
    def _pack(self, water_parameters):
        return KnowledgePackIn(
            pack_code="kp-x", pack_version="1.0", name="test pack",
            license_name="CC BY 4.0", attribution_text="test attribution line",
            sources=[SourceIn(
                source_key="fao56", publisher="FAO", title="FAO Irrigation and Drainage Paper 56",
                publication_year=1998, citation_text="Allen et al., 1998, FAO-56.",
            )],
            crops=[CropIn(
                crop_code="test_crop", family_key=None, water_parameters=water_parameters,
            )],
        )

    def test_incomplete_anchor_set_rejected_at_import(self):
        pack = self._pack([
            WaterParameterIn(growth_stage="initial", kc_value=0.3, source_key="fao56",
                             evidence_class="published_reference"),
            WaterParameterIn(growth_stage="mid", kc_value=1.15, source_key="fao56",
                             evidence_class="published_reference"),
        ])
        report = validate_pack_cross_references(pack)
        assert not report.ok
        assert any("incomplete Kc anchor set" in e for e in report.errors)

    def test_invalid_stage_vocabulary_rejected(self):
        with pytest.raises(Exception):
            WaterParameterIn(growth_stage="vegetative", kc_value=1.0, source_key="fao56")

    def test_complete_anchor_set_accepted(self):
        pack = self._pack([
            WaterParameterIn(growth_stage=st, kc_value=v, source_key="fao56",
                             evidence_class="published_reference")
            for st, v in (("initial", 0.3), ("mid", 1.15), ("late", 0.5))
        ])
        report = validate_pack_cross_references(pack)
        assert report.ok


# ================= F-07: partial ET0 coverage refuses the estimate =================
class TestF07WaterRefusal:
    def test_missing_month_refuses_estimate_rather_than_under_reporting(self):
        crop = _crop("maize", "poaceae", kc=(0.3, 1.15, 0.5))
        ev = _evidence(monthly_et0=((2025, 5, 150.0), (2025, 6, 140.0)))  # Jul-Sep missing
        mm, why = estimate_water_requirement_mm(crop, ev, SEASON)
        assert mm is None
        assert any("refused" in w for w in why)
        assert any("2025-07" in w for w in why)

    def test_full_coverage_still_estimates(self):
        crop = _crop("maize", "poaceae", kc=(0.3, 1.15, 0.5))
        mm, why = estimate_water_requirement_mm(crop, _evidence(), SEASON)
        assert mm is not None
        assert mm > 400


# ================= F-06: deep rotation-break rules fully enforced =================
class TestF06DeepBreakRules:
    def _rule5(self):
        return RotationRuleData(
            rule_code="deep_break", rule_type="rotation_break",
            predecessor_kind="crop", predecessor_key="maize",
            successor_kind="crop", successor_key="maize",
            min_break_seasons=5, mechanism="deep test mechanism", scope_note=None,
            applies_to_regions=(), validation_status="confirmed_regional",
            severity="required", source_key="s", citation_text="citation",
            pack_code="kp", pack_version=PACK_VERSION,
        )

    def test_checker_enforces_beyond_old_cap_of_three(self):
        crops = [_crop("maize", "poaceae", windows=[_window("05-01", "06-01")])]
        seasons = tuple(
            SeasonSpec(label=f"s{i}", start_date=date(2025 + i, 5, 1), end_date=date(2025 + i, 9, 15))
            for i in range(6)
        )
        farm = _farm(crops)
        farm = FarmContext(
            **{**farm.__dict__, "seasons": seasons}
        )
        problem = _problem(crops, rules=[self._rule5()])
        problem = RotationProblem(
            field_id=problem.field_id, seasons=seasons, candidates=problem.candidates,
            knowledge=problem.knowledge, farm=farm, water_allocation_m3=None,
            baseline_assignment=tuple((s.label, None) for s in seasons),
            synthetic_evidence=False,
        )
        assignment = {s.label: "maize" for s in seasons}
        checks = check_all(problem, assignment)
        break_checks = [c for c in checks if c.constraint_code == "rotation_break_confirmed_regional"]
        assert break_checks and all(c.status == "violated" for c in break_checks)
        # gap of 3 seasons (back=4) must be caught — the old cap(3) missed it
        assert any("gap 3" in (c.detail or "") for c in break_checks)

    def test_optimizer_enforces_beyond_old_window_of_four(self):
        crops = [_crop("maize", "poaceae", windows=[_window("05-01", "06-01")])]
        seasons = tuple(
            SeasonSpec(label=f"s{i}", start_date=date(2025 + i, 5, 1), end_date=date(2025 + i, 9, 15))
            for i in range(6)
        )
        problem = _problem(crops, rules=[self._rule5()])
        farm = FarmContext(
            field_id=problem.farm.field_id, farm_id=problem.farm.farm_id,
            area_ha=problem.farm.area_ha, country_code=problem.farm.country_code,
            hemisphere=problem.farm.hemisphere, seasons=seasons,
            soil=problem.farm.soil, climate_by_season=problem.farm.climate_by_season,
            climate_run_refs=problem.farm.climate_run_refs,
            history=problem.farm.history, market_exclusions=(),
            equipment_limits=(), water_allocation_m3=None,
            margin_index_by_crop={}, synthetic_evidence_in_use=False,
            soil_evidence_class=None,
        )
        knowledge = KnowledgeBaseData(
            pack_refs=problem.knowledge.pack_refs, crops=problem.knowledge.crops,
            rules=problem.knowledge.rules, confirmed_rule_count=1,
            reference_rule_count=0,
        )
        candidates = {
            season.label: {
                "maize": CandidateAssessment(
                    crop_code="maize", status="conditionally_eligible",
                    reasons=({"code": "temperature_within_optimum"},),
                    water_requirement_mm=400.0,
                )
            }
            for season in seasons
        }
        problem = RotationProblem(
            field_id=problem.field_id, seasons=seasons, candidates=candidates,
            knowledge=knowledge, farm=farm, water_allocation_m3=None,
            baseline_assignment=tuple((s.label, None) for s in seasons),
            synthetic_evidence=False,
        )
        result = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        # all-maize is infeasible under a 5-season break; any solution must
        # honour the gap (only one crop exists → the profile is infeasible)
        assert isinstance(result, InfeasibleResult)
        assert result.status == "infeasible"
        assert any(c["constraint"] == "rotation_break_confirmed_regional" for c in result.conflicts)


# ================= F-04: solver status semantics =================
class TestF04SolverSemantics:
    def test_infeasible_result_carries_explicit_status(self):
        result = InfeasibleResult([{"constraint": "water_allocation", "detail": "x"}])
        assert result.status == "infeasible"
        result2 = InfeasibleResult([{"constraint": "solver_model_invalid", "detail": "x"}],
                                   status="model_invalid")
        assert result2.status == "model_invalid"
        assert result2.status != "infeasible"

    def test_no_evaluable_criteria_yields_feasibility_only_solution(self):
        # every criterion skipped: no traits, no Kc, no evidence — the solver
        # must still return a solution (feasibility-only), never crash
        crop = _crop("bare", None, duration=None, temp_opt=None, temp_min_abs=None,
                     windows=[_window("05-01", "06-01")])
        problem = _problem([crop])
        # strip candidates' water + temperature reason
        problem.candidates[SEASON.label]["bare"] = CandidateAssessment(
            crop_code="bare", status="conditionally_eligible", reasons=(),
        )
        result = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assert not isinstance(result, InfeasibleResult)
        assert result.solver_status in ("optimal", "feasible")


# ================= F-10: criteria carry source references =================
class TestF10CriteriaSourceRefs:
    def test_criteria_populate_source_refs_from_knowledge(self):
        crops = [_crop("maize", "poaceae", kc=(0.3, 1.15, 0.5))]
        problem = _problem(crops)
        criteria = evaluate_criteria(problem, {SEASON.label: "maize"})
        by_code = {c.criterion_code: c for c in criteria}
        assert by_code["water_requirement_mm"].source_refs, "water criterion cites Kc/stage evidence"
        assert by_code["water_requirement_mm"].source_refs[0]["citation_text"] == "citation"
        assert by_code["erosion_reduction_index"].source_refs
        soil = by_code["soil_health_index"]
        assert soil.evaluable is False or soil.source_refs  # refs or honest missing
        margin = by_code["economic_margin_index"]
        assert margin.source_refs == ()  # farmer-supplied only: no knowledge citation to fake


# ================= F-11: baseline classification =================
class TestF11BaselineClassification:
    def test_short_record_baseline_labelled_exploratory(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Cairo")
        obs = []
        for year in range(2020, 2025):  # 5 years — exploratory range
            for day in range(1, 26):  # 25 of 31 days: above the 0.8 coverage floor
                obs.append({
                    "id": f"o-{year}-{day}", "variable_code": "air_temperature_mean",
                    "observed_at": datetime(year, 5, day, 12, tzinfo=timezone.utc),
                    "period_start": datetime(year, 5, day, 12, tzinfo=timezone.utc),
                    "period_end": datetime(year, 5, day, 13, tzinfo=timezone.utc),
                    "value": 20.0 + (year - 2020), "quality_status": "valid",
                    "time_support": "daily", "dataset_product_id": "p1",
                    "processing_version": "v1",
                    "evidence_class": "reanalysis_model_estimate", "is_synthetic": False,
                })
        drafts, _ne, _w = compute_feature_drafts(
            observations=obs,
            specs=[FEATURE_CATALOG["air_temperature_mean_monthly"],
                   FEATURE_CATALOG["air_temperature_anomaly_monthly"]],
            tz=tz, hemisphere="north",
            window_start=datetime(2020, 5, 1, tzinfo=timezone.utc),
            window_end=datetime(2024, 5, 31, tzinfo=timezone.utc),
            aggregation_levels=["monthly"], crop_seasons=[],
            engine_version="test", definition_version="test",
        )
        with_baseline = [d for d in drafts if d.baseline_reference]
        assert with_baseline, "anomaly values carry baseline provenance"
        baseline = with_baseline[0].baseline_reference
        assert baseline["baseline_class"] == "short_record_exploratory"
        assert baseline["includes_evaluated_period"] is True

    def test_catalog_stopped_calling_baselines_climatology(self):
        for spec in FEATURE_CATALOG.values():
            assert "climatology" not in spec.description.lower(), spec.feature_code


# ================= Pareto property tests (Phase H §10.2) =================
class TestParetoProperties:
    def _sol(self, key, values, evaluable=None):
        from app.rotation.problem import CriterionResult
        crits = []
        for code, raw in values.items():
            evaluable_flag = True if evaluable is None else code in evaluable
            crits.append(CriterionResult(
                criterion_code=code, raw_value=raw,
                unit="u", direction="minimize" if code == "water_requirement_mm" else "maximize",
                normalized=raw if evaluable_flag else None,
                evaluable=evaluable_flag,
            ))
        return StrategySolution(
            strategy_key=key, strategy_kind="optimized", is_baseline=False,
            profile_weights={}, weights_effective={}, skipped_weights={},
            assignment=(("s", None),), objective_value=None, criteria=tuple(crits),
            constraints_checked=(), evidence_coverage=None,
        )

    def test_dominated_solution_never_on_front(self):
        a = self._sol("a", {"water_requirement_mm": 0.2, "soil_health_index": 0.9})
        b = self._sol("b", {"water_requirement_mm": 0.8, "soil_health_index": 0.3})
        sols = [a, b]
        compute_pareto(sols)
        by = {s.strategy_key: s for s in sols}
        assert by["b"].dominated_by == ("a",)
        assert not by["b"].on_pareto_front
        assert by["a"].on_pareto_front

    def test_identical_solutions_both_on_front(self):
        a = self._sol("a", {"water_requirement_mm": 0.5, "soil_health_index": 0.5})
        b = self._sol("b", {"water_requirement_mm": 0.5, "soil_health_index": 0.5})
        sols = [a, b]
        compute_pareto(sols)
        assert all(s.on_pareto_front for s in sols)
        assert all(not s.dominated_by for s in sols)

    def test_disjoint_evaluable_sets_non_comparable(self):
        a = self._sol("a", {"water_requirement_mm": 0.1, "soil_health_index": 0.1},
                      evaluable={"water_requirement_mm"})
        b = self._sol("b", {"water_requirement_mm": 0.9, "soil_health_index": 0.9},
                      evaluable={"soil_health_index"})
        sols = [a, b]
        compute_pareto(sols)
        assert all(s.on_pareto_front for s in sols)
        assert all(not s.dominated_by for s in sols)

    def test_weighted_objective_renormalizes_and_reports_skipped(self):
        sol = self._sol("s", {"water_requirement_mm": 0.4})
        sol.profile_weights = {
            "water_requirement_mm": 0.5, "economic_margin_index": 0.5,
        }
        objective, effective, skipped = weighted_objective(sol)
        assert objective is not None
        assert list(effective) == ["water_requirement_mm"]
        assert "economic_margin_index" in skipped
        assert skipped["economic_margin_index"]

    def test_normalization_within_set_neutral_for_single_solution(self):
        sol = self._sol("s", {"water_requirement_mm": 0.7, "soil_health_index": 0.2})
        sols = [sol]
        normalize_within_set(sols)
        norms = {c.criterion_code: c.normalized for c in sols[0].criteria}
        assert norms["water_requirement_mm"] == 0.5  # neutral, documented
        assert norms["soil_health_index"] == 0.5


# ================= Reproducibility (Phase H §10.2) =================
class TestReproducibility:
    def test_same_inputs_same_solution(self):
        crops = [
            _crop("maize", "poaceae", kc=(0.3, 1.15, 0.5), windows=[_window("05-01", "06-01")]),
            _crop("soybean", "fabaceae", legume=True, kc=(0.4, 1.1, 0.5),
                  windows=[_window("05-01", "06-01")]),
        ]
        p1 = _problem(crops)
        p2 = _problem(crops)
        s1 = optimize_strategy(p1, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        s2 = optimize_strategy(p2, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        assert s1.assignment == s2.assignment
        assert s1.objective_value == s2.objective_value

    def test_baseline_never_claims_solver_status(self):
        crops = [_crop("maize", "poaceae", windows=[_window("05-01", "06-01")])]
        sol = build_baseline_solution(_problem(crops))
        assert sol.solver_status == "not_attempted"
        assert sol.is_baseline

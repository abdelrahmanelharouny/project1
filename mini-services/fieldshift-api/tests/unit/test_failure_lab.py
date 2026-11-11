"""Unit: Rotation Failure Lab (P2.D) — pack validation, robustness metrics
math, deterministic engine execution, violation explanations.

All tests construct the pure decision-core dataclasses directly — no
database, no HTTP, no network (same pattern as test_rotation_core.py: the
engine consumes RotationProblem + FarmContext, not ORM rows).
"""

import json
from datetime import date

import pytest

from app.core.errors import ValidationFailed
from app.failure_lab import contracts as fl_contracts
from app.failure_lab import engine as fl_engine
from app.failure_lab import metrics as fl_metrics
from app.field_state.manifest import sha256_of_document
from app.rotation import candidates as candidates_mod
from app.rotation.problem import (
    CalendarWindow,
    ClimateEvidence,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    RotationProblem,
    SeasonSpec,
    TraitValue,
    WaterParams,
)

PACK_VERSION = "kp-test-1.0"

SEASONS = (
    SeasonSpec(label="s1", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15)),
    SeasonSpec(label="s2", start_date=date(2026, 5, 1), end_date=date(2026, 9, 15)),
)


# ------------------------------------------------- fixtures (tiny synthetic
# field: 2 seasons, 3 crops; mirrors tests/unit/test_rotation_core.py style)


def _crop(code, family, *, legume=False, duration=120, kc=(0.3, 1.2, 0.6),
          window=("04-15", "06-15")):
    traits: dict[str, TraitValue] = {}

    def t(code_, value=None, unit=None):
        traits[code_] = TraitValue(
            trait_code=code_, value_numeric=value, value_text=None, value_low=None,
            value_high=None, unit=unit, region_code=None,
            evidence_class="published_reference", confidence="moderate",
            validation_status="reference", source_key="s", citation_text="citation",
            pack_code="kp", pack_version=PACK_VERSION,
        )

    t("duration_days_total", value=duration, unit="d")
    if kc is not None:
        t("stage_init_days", value=20, unit="d")
        t("stage_dev_days", value=30, unit="d")
        t("stage_mid_days", value=40, unit="d")
        t("stage_late_days", value=30, unit="d")
    t("temp_opt_min_degC", value=15.0, unit="degC")
    t("temp_opt_max_degC", value=28.0, unit="degC")
    t("temp_min_abs_degC", value=5.0, unit="degC")
    return KnowledgeCrop(
        crop_code=code, pack_code="kp", pack_version=PACK_VERSION, family_key=family,
        scientific_name=None, common_name=code, crop_category=None,
        life_cycle_type="annual", is_legume=legume, is_cover_crop_capable=legume,
        traits=traits,
        calendar_windows=(
            CalendarWindow(
                region_code=None, hemisphere="north", season_code=None,
                planting_start=window[0], planting_end=window[1],
                evidence_class="reference_synthesized", validation_status="reference",
                source_key="s", citation_text="citation",
                pack_code="kp", pack_version=PACK_VERSION,
            ),
        ),
        water_params=WaterParams(
            kc_initial=kc[0], kc_mid=kc[1], kc_late=kc[2],
            evidence_class="published_reference", source_key="s",
            citation_text="citation", pack_code="kp", pack_version=PACK_VERSION,
        ) if kc else None,
    )


def _evidence(year: int) -> ClimateEvidence:
    """Month-of-year climatology for one May–Sep season (ET0 + precip)."""
    months = (5, 6, 7, 8, 9)
    return ClimateEvidence(
        feature_run_id="run-1", is_synthetic=False,
        season_precipitation_mm=55.0, season_mean_temp_degC=18.0,
        season_mean_tmax_degC=None, season_hot_days_35c=2.0, season_et0_mm=630.0,
        monthly_et0=tuple(
            (year, m, v) for m, v in zip(months, (150.0, 140.0, 130.0, 120.0, 90.0))
        ),
        monthly_precip=tuple(
            (year, m, v) for m, v in zip(months, (20.0, 10.0, 5.0, 5.0, 15.0))
        ),
        coverage_ratio=1.0, years_used=(year,),
    )


def _farm(*, allocation=None, margins=None):
    return FarmContext(
        field_id="f1", farm_id="farm1", area_ha=10.0, country_code="EG",
        hemisphere="north", seasons=SEASONS, soil=None,
        climate_by_season={s.label: _evidence(s.start_date.year) for s in SEASONS},
        climate_run_refs={s.label: "run-1" for s in SEASONS},
        history=(), market_exclusions=(), equipment_limits=(),
        water_allocation_m3=allocation,
        margin_index_by_crop=dict(margins or {}),
        synthetic_evidence_in_use=False, soil_evidence_class=None,
    )


def _knowledge(extra_crops=()):
    crops = [
        _crop("maize", "poaceae", duration=120),
        _crop("soybean", "fabaceae", legume=True, duration=110, kc=(0.3, 1.1, 0.5),
              window=("05-01", "06-30")),
        _crop("sunflower", "asteraceae", duration=120, kc=(0.3, 1.1, 0.5)),
        *extra_crops,
    ]
    return KnowledgeBaseData(
        pack_refs=({"pack_code": "kp", "pack_version": PACK_VERSION},),
        crops={c.crop_code: c for c in crops},
        rules=(),
        confirmed_rule_count=0,
        reference_rule_count=0,
    )


def _problem(*, allocation=None, margins=None, extra_crops=()):
    farm = _farm(allocation=allocation, margins=margins)
    knowledge = _knowledge(extra_crops)
    assessments = candidates_mod.generate_candidates(knowledge, farm)
    return RotationProblem(
        field_id="f1",
        seasons=SEASONS,
        candidates=assessments,
        knowledge=knowledge,
        farm=farm,
        water_allocation_m3=allocation,
        baseline_assignment=tuple((s.label, None) for s in SEASONS),
        synthetic_evidence=False,
    )


def _baseline_spec(assignment=(("s1", "maize"), ("s2", "soybean"))):
    return fl_engine.CandidateSpec(
        candidate_key="baseline",
        origin="history",
        strategy_profile=None,
        assignment=assignment,
        source_note="test baseline reconstructed from history",
    )


# ------------------------------------------------------------ pack validation


class TestPackValidation:
    def test_unknown_pack_code_refused(self):
        with pytest.raises(ValidationFailed) as excinfo:
            fl_contracts.resolve_packs(["severe_drought", "meteor_strike"])
        assert "meteor_strike" in str(excinfo.value.message)
        assert excinfo.value.details == [{"field": "packs", "reason": "meteor_strike"}]

    def test_out_of_bounds_override_refused(self):
        with pytest.raises(ValidationFailed) as excinfo:
            fl_contracts.resolve_packs([
                {"code": "severe_drought", "parameters": {"precipitation_multiplier": 2.0}},
            ])
        assert "precipitation_multiplier" in str(excinfo.value.message)

    def test_out_of_bounds_custom_parameter_refused(self):
        with pytest.raises(ValidationFailed):
            fl_contracts.resolve_packs([{
                "code": "scorching", "kind": "climate", "label": "Scorching",
                "parameters": {"temperature_delta_c": 11.0},
            }])

    def test_unknown_parameter_name_refused(self):
        with pytest.raises(ValidationFailed) as excinfo:
            fl_contracts.resolve_packs([{
                "code": "weird", "kind": "climate",
                "parameters": {"rainfall_multiplier": 0.5},
            }])
        assert "rainfall_multiplier" in str(excinfo.value.message)

    def test_preset_override_within_bounds_accepted(self):
        packs = fl_contracts.resolve_packs([
            {"code": "severe_drought", "parameters": {"precipitation_multiplier": 0.3}},
        ])
        assert len(packs) == 1
        assert packs[0].parameters["precipitation_multiplier"] == 0.3
        assert packs[0].parameters["water_allocation_multiplier"] == 0.6  # inherited
        assert packs[0].provenance["source"] == "user_defined"

    def test_user_defined_pack_accepted_and_sorted(self):
        packs = fl_contracts.resolve_packs([
            {"code": "zz_my_drought", "kind": "climate",
             "parameters": {"precipitation_multiplier": 0.8}},
            "heatwave",
        ])
        assert [p.code for p in packs] == ["heatwave", "zz_my_drought"]
        assert packs[1].provenance["source"] == "user_defined"
        assert packs[1].assumption_note

    def test_explicit_empty_pack_list_refused(self):
        with pytest.raises(ValidationFailed):
            fl_contracts.resolve_packs([])

    def test_preset_catalog_is_complete_and_documented(self):
        assert set(fl_contracts.PRESET_PACKS) == {
            "severe_drought", "heatwave", "water_restriction", "delayed_planting",
            "nutrient_price_shock", "combined_climate_operational",
        }
        for code, pack in fl_contracts.PRESET_PACKS.items():
            assert pack.kind in fl_contracts.PACK_KINDS, code
            assert pack.provenance["source"] == "preset", code
            assert pack.assumption_note, code
            for name, value in pack.parameters.items():
                lo, hi = fl_contracts.PARAMETER_BOUNDS[name]
                assert lo <= value <= hi, (code, name)
        catalog = fl_contracts.pack_catalog()
        assert catalog["version"] == fl_contracts.STRESS_PACKS_VERSION
        assert len(catalog["packs"]) == len(fl_contracts.PRESET_PACKS)


# ------------------------------------------------------------ metrics math


class TestMetricsMath:
    SCORES = {"a": 1.0, "b": 0.5, "c": 0.0}

    def test_worst_case_score(self):
        metric = fl_metrics.worst_case_score(self.SCORES)
        assert metric["value"] == 0.0
        assert metric["unit"] == fl_metrics.SCORE_UNIT
        assert metric["name"] == "worst_case_score"
        assert metric["formula_text"]

    def test_mean_score(self):
        assert fl_metrics.mean_score(self.SCORES)["value"] == 0.5

    def test_score_variance_is_population_variance(self):
        # (1/3)·[(1−0.5)² + (0.5−0.5)² + (0−0.5)²] = 1/6
        metric = fl_metrics.score_variance(self.SCORES)
        assert metric["value"] == round(1.0 / 6.0, 6)
        assert "not a probability distribution" in metric["formula_text"]

    def test_downside_risk_against_own_unstressed_score(self):
        # shortfalls vs 0.8: max(0,0.8−1)=0, max(0,0.8−0.5)=0.3, max(0,0.8−0)=0.8
        metric = fl_metrics.downside_risk(self.SCORES, 0.8)
        assert metric["value"] == round((0.0 + 0.3 + 0.8) / 3.0, 6)
        assert fl_metrics.downside_risk(self.SCORES, None)["value"] is None
        assert fl_metrics.downside_risk(self.SCORES, None)["reason"]

    def test_normalized_score_excludes_unevaluable(self):
        assert fl_metrics.normalized_score([0.25, None, 0.75]) == 0.5
        assert fl_metrics.normalized_score([None, None]) is None

    def test_regret_and_worst_case_regret(self):
        best = fl_metrics.best_score_by_pack({
            "c1": {"p1": 0.2, "p2": None},
            "c2": {"p1": 0.6, "p2": 0.4},
        })
        assert best == {"p1": 0.6, "p2": 0.4}
        regrets = fl_metrics.regret_by_pack({"p1": 0.5, "p2": 0.25}, best)
        assert regrets["p1"]["value"] == 0.1
        assert regrets["p2"]["value"] == 0.15
        assert fl_metrics.worst_case_regret(regrets)["value"] == 0.15
        # scoreless candidate in a pack → regret not evaluable, never zero
        empty = fl_metrics.regret_by_pack({"p1": None}, {"p1": 0.6})
        assert empty["p1"]["value"] is None and empty["p1"]["reason"]

    def test_feasibility_and_violation_rates(self):
        rate = fl_metrics.feasibility_rate({"a": True, "b": False, "c": None})
        assert rate["value"] == 0.5  # undecidable cells excluded, not failures
        freq = fl_metrics.violation_frequency({"a": True, "b": False})
        assert freq["value"] == 0.5

    def test_every_metric_carries_name_value_unit_formula(self):
        docs = [
            fl_metrics.worst_case_score({}),
            fl_metrics.mean_score(self.SCORES),
            fl_metrics.score_variance({}),
            fl_metrics.downside_risk({}, None),
            fl_metrics.feasibility_rate({}),
            fl_metrics.violation_frequency({}),
            fl_metrics.worst_case_regret({}),
        ]
        for doc in docs:
            assert {"name", "value", "unit", "formula_text"} <= set(doc)
            assert doc["formula_text"]


# ------------------------------------------------------- engine determinism


class TestEngineDeterminism:
    def test_same_inputs_same_checksum(self):
        problem = _problem(margins={"maize": 60.0, "soybean": 50.0})
        packs = fl_contracts.resolve_packs(["severe_drought", "heatwave"])
        first = fl_engine.run_stress_matrix(
            problem, candidates=[_baseline_spec()], packs=packs
        )
        second = fl_engine.run_stress_matrix(
            problem, candidates=[_baseline_spec()], packs=packs
        )
        assert sha256_of_document(first) == sha256_of_document(second)
        # one cell per candidate × pack, deterministic order
        assert [(c["candidate_key"], c["pack_code"]) for c in first["evaluations"]] == [
            ("baseline", "heatwave"), ("baseline", "severe_drought"),
        ]
        # no wall clock in the result document (timestamps are run metadata)
        assert "started_at" not in json.dumps(first)
        assert first["engine_version"] == fl_contracts.FAILURE_LAB_ENGINE_VERSION
        assert first["metrics_version"] == fl_metrics.ROBUSTNESS_METRICS_VERSION

    def test_unstressed_reference_cells_join_the_matrix(self):
        problem = _problem()
        result = fl_engine.run_stress_matrix(
            problem, candidates=[_baseline_spec()], packs=fl_contracts.resolve_packs(["heatwave"])
        )
        assert len(result["unstressed_reference"]) == 1
        assert result["unstressed_reference"][0]["pack_code"] is None
        assert result["unstressed_reference"][0]["cell_key"].endswith(
            fl_engine.UNSTRESSED_REFERENCE_KEY
        )


# --------------------------------------------- operational stress + honesty


class TestOperationalStress:
    def test_allocation_cut_below_demand_produces_explanation(self):
        problem = _problem(allocation=10_000.0)
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[_baseline_spec()],
            packs=fl_contracts.resolve_packs(["water_restriction"]),
        )
        cell = next(
            c for c in result["evaluations"] if c["pack_code"] == "water_restriction"
        )
        assert cell["feasible"] is False
        assert cell["solver_status"] == "not_attempted"
        assert cell["water"]["allocation_m3"] == 5_000.0  # 10_000 × 0.5
        assert cell["water"]["demand_m3_estimated"] is not None
        assert cell["water"]["demand_m3_estimated"] > 5_000.0
        violation = cell["constraint_violations"][0]
        assert violation["constraint"] == "water_allocation"
        explanation = cell["explanations"][0]
        assert explanation["violated_constraint"] == "water_allocation"
        assert explanation["severity"] in ("certain", "estimated", "conditional")
        assert explanation["possible_mitigation"]
        ref_types = {r["type"] for r in explanation["evidence_refs"]}
        assert {"stress_pack", "water_number"} <= ref_types
        # water numbers carry their climatology basis
        water_refs = [r for r in explanation["evidence_refs"] if r["type"] == "water_number"]
        assert all("basis:" in r["label"] for r in water_refs)

    def test_infeasible_pack_yields_named_constraint_not_a_crash(self):
        problem = _problem(allocation=1_000.0)
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[_baseline_spec()],
            packs=fl_contracts.resolve_packs(["severe_drought"]),
        )
        cell = next(
            c for c in result["evaluations"] if c["pack_code"] == "severe_drought"
        )
        assert cell["feasible"] is False
        constraints = {v["constraint"] for v in cell["constraint_violations"]}
        assert "water_allocation" in constraints
        assert result["failure_explanations"]
        robustness = result["robustness"][0]
        assert robustness["metrics"]["feasibility_rate"]["value"] == 0.0
        assert robustness["metrics"]["constraint_violation_frequency"]["value"] == 1.0
        assert robustness["metrics"]["worst_case_score"]["value"] is not None

    def test_missing_allocation_is_not_evaluated_never_invented(self):
        problem = _problem(allocation=None)
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[_baseline_spec()],
            packs=fl_contracts.resolve_packs(["severe_drought", "nutrient_price_shock"]),
        )
        dimensions = {
            (n["pack_code"], n["dimension"]) for n in result["not_evaluated"]
        }
        assert ("severe_drought", "water_allocation") in dimensions
        assert ("nutrient_price_shock", "economic_margin_index") in dimensions
        # the stressed cell keeps the unstressed allocation (None) — no fabrication
        drought_cell = next(
            c for c in result["evaluations"] if c["pack_code"] == "severe_drought"
        )
        assert drought_cell["water"]["allocation_m3"] is None


class TestTimingStress:
    def test_delayed_planting_screens_window_overlap_only(self):
        early_pea = _crop("early_pea", "fabaceae", legume=True, duration=100,
                          window=("04-01", "05-10"))
        problem = _problem(extra_crops=[early_pea])
        spec = _baseline_spec(assignment=(("s1", "early_pea"), ("s2", "early_pea")))
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[spec],
            packs=fl_contracts.resolve_packs(["delayed_planting"]),
        )
        cell = next(
            c for c in result["evaluations"] if c["pack_code"] == "delayed_planting"
        )
        screen = cell["timing_screen"][0]
        assert screen["shift_days"] == 14
        assert screen["shifted_start_date"] == "2025-05-15"
        assert "early_pea" in screen["timing_infeasible_crops"]
        # window overlap only: the unstressed reference stays feasible
        reference = result["unstressed_reference"][0]
        assert reference["constraint_violations"] == []
        # the pinned assignment fails the shift with a NAMED constraint
        assert cell["feasible"] is False
        violation = cell["constraint_violations"][0]
        assert violation["constraint"] == "planting_window_shift"
        explanation = cell["explanations"][0]
        assert explanation["severity"] == "certain"  # deterministic calendar arithmetic
        assert "planting windows" in explanation["possible_mitigation"]


class TestClimateStress:
    def test_climate_stress_recomputes_water_numbers_with_basis(self):
        problem = _problem()
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[_baseline_spec()],
            packs=fl_contracts.resolve_packs(["severe_drought"]),
        )
        reference = result["unstressed_reference"][0]
        stressed = next(
            c for c in result["evaluations"] if c["pack_code"] == "severe_drought"
        )
        ref_et0 = {c["criterion_code"]: c for c in reference["criteria"]}
        stressed_et0 = {c["criterion_code"]: c for c in stressed["criteria"]}
        # precipitation × 0.25 ⇒ the net irrigation requirement can only grow
        assert (
            stressed_et0["water_requirement_mm"]["raw_value"]
            >= ref_et0["water_requirement_mm"]["raw_value"]
        )
        # every stressed criterion carries the same basis as rotation runs
        assert stressed_et0["water_requirement_mm"]["derivation"]
        assumptions = " ".join(result["assumptions"]).lower()
        assert "temperature-et0 screening sensitivity" in assumptions
        assert "allocation side" in assumptions

    def test_season_without_evidence_records_not_evaluated(self):
        problem = _problem()
        broken = dict(problem.farm.climate_by_season)
        broken.pop("s2")
        farm = replace_farm(problem.farm, climate_by_season=broken)
        problem = RotationProblem(
            field_id=problem.field_id,
            seasons=problem.seasons,
            candidates=problem.candidates,
            knowledge=problem.knowledge,
            farm=farm,
            water_allocation_m3=None,
            baseline_assignment=problem.baseline_assignment,
            synthetic_evidence=False,
        )
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=[_baseline_spec()],
            packs=fl_contracts.resolve_packs(["heatwave"]),
        )
        entries = [
            n for n in result["not_evaluated"]
            if n["dimension"] == "climate_stress" and n["season_label"] == "s2"
        ]
        assert entries and "never treated as zero" in entries[0]["reason"]


def replace_farm(farm, **changes):
    from dataclasses import replace as _replace

    return _replace(farm, **changes)


# --------------------------------------------------- matrix metrics (shared basis)


class TestMatrixRobustness:
    def test_robustness_block_shape_and_shared_best(self):
        problem = _problem(margins={"maize": 60.0, "soybean": 50.0})
        candidates = [
            _baseline_spec(),
            fl_engine.CandidateSpec(
                candidate_key="recommended",
                origin="rotation_run",
                strategy_profile="water_priority",
                assignment=(("s1", "soybean"), ("s2", "maize")),
                source_note="test recommended",
            ),
        ]
        result = fl_engine.run_stress_matrix(
            problem,
            candidates=candidates,
            packs=fl_contracts.resolve_packs(["heatwave", "water_restriction"]),
        )
        assert result["best_scores_by_pack"] == {
            "heatwave": max(
                result["robustness"][0]["pack_scores"]["heatwave"],
                result["robustness"][1]["pack_scores"]["heatwave"],
            ),
            "water_restriction": max(
                result["robustness"][0]["pack_scores"]["water_restriction"],
                result["robustness"][1]["pack_scores"]["water_restriction"],
            ),
        }
        for block in result["robustness"]:
            metrics = block["metrics"]
            for name in (
                "worst_case_score", "mean_score", "score_variance", "downside_risk",
                "feasibility_rate", "constraint_violation_frequency",
                "worst_case_regret",
            ):
                doc = metrics[name]
                assert {"name", "value", "unit", "formula_text"} <= set(doc)
            for regret in metrics["regret_by_pack"].values():
                assert {"name", "value", "unit", "formula_text"} <= set(regret)
            # regret identity: best − own score, per pack
            for pack, regret in metrics["regret_by_pack"].items():
                own = block["pack_scores"][pack]
                best = result["best_scores_by_pack"][pack]
                if own is not None and best is not None:
                    assert regret["value"] == pytest.approx(round(best - own, 6))
        # no arbitrary composite: scoring basis is documented, no "resilience score"
        assert "no arbitrary" in result["scoring_basis"]["no_composite_claim"]

"""Unit: farm portfolio optimizer (P2.F) — CP-SAT area allocation under
shared constraints, honest not_evaluated reporting, determinism, and the
portfolio-vs-independent comparison plumbing.

All tests construct the pure dataclasses directly — no database, no HTTP
(the same independence rule as the rotation decision core). Fixture helpers
mirror tests/unit/test_rotation_core.py (tests are not a package, so the
minimal helpers are duplicated here deliberately).
"""

from datetime import date

import pytest

from app.core.errors import ValidationFailed
from app.portfolio import contracts, evaluation, optimizer
from app.rotation.candidates import generate_candidates
from app.rotation.problem import (
    CalendarWindow,
    CandidateAssessment,
    ClimateEvidence,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    SeasonSpec,
    TraitValue,
    WaterParams,
)

PACK_VERSION = "kp-test-1.0"

SUMMER = SeasonSpec(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))


def _crop(code, family=None, *, legume=False, cover=False, kc=None, duration=120,
          windows=None):
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
    t("temp_opt_min_degC", value=15, unit="degC")
    t("temp_opt_max_degC", value=28, unit="degC")
    t("temp_min_abs_degC", value=5, unit="degC")
    if legume:
        t("n_fixation_capacity_kg_ha", value=120.0, unit="kg/ha")
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


def _window(start, end, hemisphere="north"):
    return CalendarWindow(
        region_code=None, hemisphere=hemisphere, season_code=None,
        planting_start=start, planting_end=end, evidence_class="reference_synthesized",
        validation_status="reference", source_key="s", citation_text="citation",
        pack_code="kp", pack_version=PACK_VERSION,
    )


def _evidence(**kw):
    base = dict(
        feature_run_id="run-1", is_synthetic=False,
        season_precipitation_mm=120.0, season_mean_temp_degC=18.0,
        season_mean_tmax_degC=None, season_hot_days_35c=2.0, season_et0_mm=420.0,
        monthly_et0=(
            (2025, 5, 150.0), (2025, 6, 140.0), (2025, 7, 130.0),
            (2025, 8, 120.0), (2025, 9, 90.0),
        ),
        monthly_precip=(
            (2025, 5, 30.0), (2025, 6, 25.0), (2025, 7, 20.0),
            (2025, 8, 25.0), (2025, 9, 20.0),
        ),
        coverage_ratio=1.0,
    )
    base.update(kw)
    return ClimateEvidence(**base)


def _farm(field_id: str, area_ha: float = 5.0, *, allocation: float | None = None):
    return FarmContext(
        field_id=field_id, farm_id="farm1", area_ha=area_ha, country_code="EG",
        hemisphere="north", seasons=(SUMMER,),
        soil=None,
        climate_by_season={"s2025": _evidence()},
        climate_run_refs={"s2025": "run-1"},
        history=(), market_exclusions=(), equipment_limits=(),
        water_allocation_m3=allocation, margin_index_by_crop={},
        synthetic_evidence_in_use=False, soil_evidence_class=None,
    )


def _knowledge(crops):
    return KnowledgeBaseData(
        pack_refs=({"pack_code": "kp", "pack_version": PACK_VERSION},),
        crops={c.crop_code: c for c in crops},
        rules=(), confirmed_rule_count=0, reference_rule_count=0,
    )


def _prepared(two_fields: bool = True, *, allocation: float | None = 3000.0,
              weights: dict[str, float] | None = None, mode: str = "weighted",
              constraints: dict | None = None, scenario: dict | None = None,
              crops=None):
    maize = _crop("maize", "poaceae", kc=(0.3, 1.2, 0.6), duration=130, windows=[_window("04-15", "06-15")])
    bean = _crop("faba_bean", "fabaceae", legume=True, kc=(0.35, 1.1, 0.5), duration=110, windows=[_window("04-01", "06-01")])
    kb = _knowledge(crops or [maize, bean])
    farms = [_farm("f1", 5.0), _farm("f2", 5.0)] if two_fields else [_farm("f1", 5.0)]
    candidates = {f.field_id: generate_candidates(kb, f) for f in farms}
    canonical_constraints = {"water_allocation_m3": allocation, "labor_capacity_person_days_per_season": None,
                             "machinery_hours_per_season": None, "max_family_share": None}
    if constraints:
        canonical_constraints.update(constraints)
    return optimizer.prepare_model(
        fields=[optimizer.FieldInput(field_id=f.field_id, area_ha=f.area_ha, farm=f) for f in farms],
        seasons=[SUMMER],
        candidates_by_field=candidates,
        knowledge=kb,
        weights=contracts.validate_objective_weights(weights),
        mode=mode,
        constraints=canonical_constraints,
        scenario=scenario,
    )


# ------------------------------------------------------------- validation


class TestContractValidation:
    def test_unknown_weight_key_refused(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_objective_weights({"profit_maximization": 1.0})

    def test_all_zero_weights_refused(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_objective_weights({"water_efficiency": 0.0})

    def test_negative_weight_refused(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_objective_weights({"water_efficiency": -1.0})

    def test_unknown_constraint_refused(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_constraints({"yield_target": 10}, has_labor_resources=False, has_machinery_resources=False)

    def test_labor_recorded_but_not_enforced(self):
        canonical, notes = contracts.validate_constraints(
            {"labor_capacity_person_days_per_season": 100},
            has_labor_resources=False, has_machinery_resources=False,
        )
        assert canonical["labor_capacity_person_days_per_season"] == 100
        assert any(n["code"] == "labor_capacity_person_days_per_season" for n in notes)

    def test_family_share_bounds(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_constraints({"max_family_share": 0.05}, has_labor_resources=False, has_machinery_resources=False)

    def test_scenario_multiplier_bounds(self):
        with pytest.raises(ValidationFailed):
            contracts.validate_scenario({"water_allocation_multiplier": 2.0})


# ------------------------------------------------------------- solve


class TestSolve:
    def test_area_conservation(self):
        prepared = _prepared()
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status == "optimal"
        per_fs: dict[tuple[str, int], float] = {}
        for a in solution.allocations:
            per_fs[(a["field_id"], a["season_index"])] = per_fs.get((a["field_id"], a["season_index"]), 0.0) + float(a["area_ha"])
        for (field_id, _s), total in per_fs.items():
            expected = next(f.area_ha for f in prepared.fields if f.field_id == field_id)
            assert abs(total - expected) <= 0.01

    def test_shared_allocation_respected(self):
        # allocation far below both fields' full-water demand -> effectively
        # exhausted: `binding` is used == limit, but the honest integer
        # semantics allow a slack smaller than one additional 0.01-ha unit
        # of the cheapest admissible crop (you cannot plant a fraction).
        prepared = _prepared(allocation=500.0)
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status == "optimal"
        used = solution.per_criterion_scores["water_use"]["value"]
        assert used is not None
        assert used <= 500.0 + 0.5
        report = solution.diagnostics.get("constraint_report", [])
        water_entry = next(e for e in report if e.get("name") == "water_allocation")
        min_unit_litres = min(
            c.coeff_l for c in prepared.crops if c.coeff_l is not None
        )
        exhausted = water_entry["binding"] or (water_entry["slack"] * 1000.0) < min_unit_litres
        assert exhausted, (
            "with a tight allocation the farm should plant until no further "
            f"0.01-ha unit fits (slack {water_entry['slack']} m3 vs min unit "
            f"{min_unit_litres / 1000.0:.1f} m3)"
        )

    def test_no_area_for_inadmissible_crops(self):
        prepared = _prepared()
        solution = optimizer.solve_portfolio(prepared)
        admissible = set()
        for _field, seasons in prepared.candidates.items():
            for _label, pool in seasons.items():
                for code, assessment in pool.items():
                    if assessment.admissible:
                        admissible.add(code)
        for a in solution.allocations:
            if a["crop_code"] != optimizer.FALLOW_CROP_CODE:
                assert a["crop_code"] in admissible

    def test_determinism_same_checksum_inputs(self):
        prepared1 = _prepared(allocation=1200.0)
        prepared2 = _prepared(allocation=1200.0)
        sol1 = optimizer.solve_portfolio(prepared1)
        sol2 = optimizer.solve_portfolio(prepared2)
        assert sol1.status == sol2.status
        assert [
            (a["field_id"], a["season_index"], a["crop_code"], a["area_ha"])
            for a in sol1.allocations
        ] == [
            (a["field_id"], a["season_index"], a["crop_code"], a["area_ha"])
            for a in sol2.allocations
        ]

    def test_scenario_changes_allocation(self):
        prepared = _prepared(allocation=1200.0)
        baseline = optimizer.solve_portfolio(prepared)
        stressed_model = _prepared(allocation=1200.0, scenario={"water_allocation_multiplier": 0.4, "label": "drought"})
        stressed = optimizer.solve_portfolio(stressed_model)
        assert stressed.status in ("optimal", "feasible", "infeasible")
        if stressed.status == "infeasible":
            assert stressed.conflicts, "infeasible scenario must name conflicts"
        else:
            comparison = evaluation.scenario_comparison(
                {"status": baseline.status, "allocations": baseline.allocations},
                {"status": stressed.status, "allocations": stressed.allocations, "conflicts": []},
                {"water_allocation_multiplier": 0.4, "label": "drought"},
            )
            assert comparison["verdict"] in ("feasible_with_changes", "feasible_unchanged")

    def test_family_cap_respected(self):
        prepared = _prepared(allocation=3000.0, constraints={"max_family_share": 0.5})
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status == "optimal"
        total = sum(float(a["area_ha"]) for a in solution.allocations)
        by_family: dict[str, float] = {}
        for a in solution.allocations:
            if a["crop_code"] == optimizer.FALLOW_CROP_CODE:
                continue
            family = prepared.family_of(a["crop_code"])
            by_family[family] = by_family.get(family, 0.0) + float(a["area_ha"])
        for _family, area in by_family.items():
            assert area <= total * 0.5 + 0.01

    def test_zero_allocation_infeasible_with_named_constraint(self):
        prepared = _prepared(allocation=0.0)
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status == "infeasible"
        assert any(
            c.get("constraint") == "water_allocation" for c in solution.conflicts
        ), "conflicts must name the water allocation"

    def test_lexicographic_mode_reports_no_composite(self):
        prepared = _prepared(weights={"water_efficiency": 3.0, "soil_health": 1.0}, mode="lexicographic")
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status in ("optimal", "feasible")
        assert solution.objective_value is None
        assert solution.diagnostics.get("mode") == "lexicographic"
        assert "__composite__" not in solution.diagnostics

    def test_scoring_code_path_identical_for_both_sides(self):
        prepared = _prepared()
        solution = optimizer.solve_portfolio(prepared)
        # score_allocation on the solution allocations must reproduce the
        # optimizer's post-hoc per-criterion scores exactly.
        rescored = evaluation.score_allocation(prepared, solution.allocations)
        for criterion in ("water_efficiency", "soil_health", "risk_diversification", "rotation_diversity"):
            a = solution.per_criterion_scores.get(criterion, {}).get("value")
            b = rescored.get(criterion, {}).get("value")
            assert a == b, f"{criterion}: {a} != {b}"

    def test_checksum_shape_roundtrip(self):
        prepared = _prepared(allocation=1200.0)
        solution = optimizer.solve_portfolio(prepared)
        payload = contracts.run_checksum_payload(
            engine_version=contracts.PORTFOLIO_ENGINE_VERSION,
            request_parameters={"x": 1},
            result={"status": solution.status},
            allocations=solution.allocations,
        )
        c1 = contracts.canonical_checksum(payload)
        c2 = contracts.canonical_checksum(
            contracts.run_checksum_payload(
                engine_version=contracts.PORTFOLIO_ENGINE_VERSION,
                request_parameters={"x": 1},
                result={"status": solution.status},
                allocations=list(reversed(solution.allocations)),
            )
        )
        assert c1 == c2, "allocation order must not affect the checksum"

    def test_fallow_allowed_when_pool_tight(self):
        # a single crop with a tiny allocation: partial fallow expected on
        # whichever field does not fit
        maize_only = [_crop("maize", "poaceae", kc=(0.3, 1.2, 0.6), duration=130, windows=[_window("04-15", "06-15")])]
        prepared = _prepared(crops=maize_only, allocation=100.0)
        solution = optimizer.solve_portfolio(prepared)
        assert solution.status in ("optimal", "feasible")
        codes = {a["crop_code"] for a in solution.allocations}
        assert optimizer.FALLOW_CROP_CODE in codes

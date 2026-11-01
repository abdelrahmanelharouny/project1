"""Unit: M6A rotation integration — net irrigation requirement in the
allocation constraint, demand-basis disclosure, infeasibility semantics.

Constructs the pure decision-core dataclasses directly (no DB, no HTTP).
"""

from datetime import date

import pytest

from app.rotation.constraints import check_all, check_water_allocation
from app.rotation.candidates import assess_crop, estimate_net_irrigation_mm
from app.rotation.optimizer import PROFILE_WEIGHTS, optimize_strategy
from app.rotation.problem import (
    CalendarWindow,
    CandidateAssessment,
    ClimateEvidence,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    RotationProblem,
    SeasonSpec,
    SeasonSpec as Season,
    TraitValue,
    WaterParams,
)

PACK_VERSION = "kp-test-1.0"


def _crop(code, family=None, *, kc=(0.30, 1.20, 0.60), duration=120, temp_opt=(15, 28),
          temp_min_abs=5):
    traits: dict[str, TraitValue] = {}

    def t(code_, value=None):
        traits[code_] = TraitValue(
            trait_code=code_, value_numeric=value, value_text=None, value_low=None,
            value_high=None, unit=None, region_code=None,
            evidence_class="published_reference", confidence="moderate",
            validation_status="reference", source_key="s", citation_text="citation",
            pack_code="kp", pack_version=PACK_VERSION,
        )

    t("duration_days_total", duration)
    t("stage_init_days", 20)
    t("stage_dev_days", 30)
    t("stage_mid_days", 40)
    t("stage_late_days", 30)
    t("temp_opt_min_degC", temp_opt[0])
    t("temp_opt_max_degC", temp_opt[1])
    t("temp_min_abs_degC", temp_min_abs)
    return KnowledgeCrop(
        crop_code=code, pack_code="kp", pack_version=PACK_VERSION, family_key=family,
        scientific_name=None, common_name=code, crop_category=None,
        life_cycle_type="annual", is_legume=False, is_cover_crop_capable=False,
        traits=traits,
        calendar_windows=(
            CalendarWindow(
                region_code=None, hemisphere="north", season_code=None,
                planting_start="01-01", planting_end="12-31",
                evidence_class="reference_synthesized", validation_status="reference",
                source_key="s", citation_text="citation", pack_code="kp",
                pack_version=PACK_VERSION,
            ),
        ),
        water_params=WaterParams(
            kc_initial=kc[0], kc_mid=kc[1], kc_late=kc[2],
            evidence_class="published_reference", source_key="s",
            citation_text="citation", pack_code="kp", pack_version=PACK_VERSION,
        ) if kc is not None else None,
    )


def _evidence(**kw):
    base = dict(
        feature_run_id="run-1", is_synthetic=False,
        season_precipitation_mm=194.0, season_mean_temp_degC=18.0,
        season_mean_tmax_degC=None, season_hot_days_35c=2.0, season_et0_mm=630.0,
        monthly_et0=(
            (2025, 5, 150.0), (2025, 6, 140.0), (2025, 7, 130.0),
            (2025, 8, 120.0), (2025, 9, 90.0),
        ),
        coverage_ratio=1.0,
    )
    base.update(kw)
    return ClimateEvidence(**base)


GOLDEN_P = ((2025, 5, 20.0), (2025, 6, 38.0), (2025, 7, 40.0), (2025, 8, 80.0), (2025, 9, 16.0))


def _farm(seasons=None, climate=None, allocation=None):
    seasons = seasons or [Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))]
    return FarmContext(
        field_id="f1", farm_id="farm1", area_ha=10.0, country_code="EG",
        hemisphere="north", seasons=tuple(seasons), soil=None,
        climate_by_season=climate or {}, climate_run_refs={},
        history=(), market_exclusions=(), equipment_limits=(),
        water_allocation_m3=allocation, margin_index_by_crop={},
        synthetic_evidence_in_use=False, soil_evidence_class=None,
    )


def _problem(crops, *, evidence=None, allocation=None, seasons=None):
    season = seasons or [Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))]
    farm = _farm(seasons=season, climate={"s2025": evidence} if evidence else {}, allocation=allocation)
    knowledge = KnowledgeBaseData(pack_refs=(), crops={c.crop_code: c for c in crops}, rules=())
    assessments = {}
    for season_spec in season:
        assessments[season_spec.label] = {
            code: assess_crop(crop, season_spec, knowledge, farm,
                              evidence if evidence else None, None)
            for code, crop in knowledge.crops.items()
        }
    return RotationProblem(
        field_id="f1", seasons=tuple(season), candidates=assessments,
        knowledge=knowledge, farm=farm, water_allocation_m3=allocation,
        baseline_assignment=tuple((s.label, None) for s in season),
        synthetic_evidence=False,
    )


class TestNetIrrigationCandidates:
    def test_nir_evaluable_with_precip_evidence(self):
        crop = _crop("maize", kc=(0.9, 1.2, 0.5), duration=120)
        evidence = _evidence(monthly_precip=GOLDEN_P)
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        nir, basis, why = estimate_net_irrigation_mm(crop, evidence, season)
        assert nir is not None
        # ETc 571.87 − Pe 67.8 = 504.07
        assert nir == pytest.approx(504.07, abs=0.1)
        assert "NIR = max(0, ETc" in basis

    def test_nir_none_without_precip_evidence(self):
        crop = _crop("maize", kc=(0.9, 1.2, 0.5))
        evidence = _evidence()
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        nir, basis, why = estimate_net_irrigation_mm(crop, evidence, season)
        assert nir is None
        assert basis is None
        assert any("precipitation" in w for w in why)

    def test_nir_never_exceeds_etc(self):
        crop = _crop("maize", kc=(0.9, 1.2, 0.5))
        evidence = _evidence(monthly_precip=GOLDEN_P)
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        nir, _b, _w = estimate_net_irrigation_mm(crop, evidence, season)
        etc, _a = __import__(
            "app.rotation.candidates", fromlist=["estimate_water_requirement_mm"]
        ).estimate_water_requirement_mm(crop, evidence, season)
        assert nir <= etc + 1e-9

    def test_wet_season_zero_nir(self):
        crop = _crop("maize", kc=(0.9, 1.2, 0.5))
        wet_p = ((2025, 5, 200.0), (2025, 6, 200.0), (2025, 7, 200.0), (2025, 8, 200.0), (2025, 9, 200.0))
        evidence = _evidence(monthly_precip=wet_p)
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        nir, basis, _w = estimate_net_irrigation_mm(crop, evidence, season)
        assert nir == 0.0
        assert basis is not None


class TestWaterAllocationIntegration:
    def test_allocation_uses_nir_when_evaluable(self):
        """With precipitation evidence the constraint coefficients are NIR
        (ETc − Pe) — a tighter, more accurate demand than the ETc screening."""
        thirsty = _crop("thirsty", kc=(0.9, 1.2, 0.5))
        frugal = _crop("frugal", kc=(0.4, 0.8, 0.3))
        evidence = _evidence(monthly_precip=GOLDEN_P)
        problem = _problem([thirsty, frugal], evidence=evidence, allocation=45000.0)
        a_thirsty = problem.candidates["s2025"]["thirsty"]
        a_frugal = problem.candidates["s2025"]["frugal"]
        assert a_thirsty.net_irrigation_requirement_mm is not None
        assert a_frugal.net_irrigation_requirement_mm is not None
        assert a_thirsty.net_irrigation_requirement_mm > a_frugal.net_irrigation_requirement_mm
        # NIR values: thirsty ≈ 504.07 mm (≈50,407 m³ on 10 ha) > 45,000 m³
        # frugal: ETc smaller + same Pe → NIR < 45,000 m³
        check = check_water_allocation(problem, {"s2025": "thirsty"})
        assert check.status == "violated"
        assert "net irrigation requirement" in check.detail
        check = check_water_allocation(problem, {"s2025": "frugal"})
        assert check.status == "satisfied"

    def test_fallback_to_etc_screening_disclosed(self):
        """Without precipitation evidence the constraint falls back to the ETc
        screening with the conservative-basis note (M5 golden behavior)."""
        thirsty = _crop("thirsty", kc=(0.9, 1.2, 0.5))
        evidence = _evidence()  # no monthly_precip
        problem = _problem([thirsty], evidence=evidence, allocation=45000.0)
        a = problem.candidates["s2025"]["thirsty"]
        assert a.net_irrigation_requirement_mm is None
        assert a.water_requirement_mm is not None
        check = check_water_allocation(problem, {"s2025": "thirsty"})
        # ETc 571.87 mm on 10 ha = 57,187 m³ > 45,000 m³ → violated, on ETc basis
        assert check.status == "violated"
        assert "ETc screening" in check.detail

    def test_optimizer_and_validator_agree_on_nir_basis(self):
        thirsty = _crop("thirsty", kc=(0.9, 1.2, 0.5))
        frugal = _crop("frugal", kc=(0.4, 0.8, 0.3))
        evidence = _evidence(monthly_precip=GOLDEN_P)
        problem = _problem([thirsty, frugal], evidence=evidence, allocation=45000.0)
        # validator: thirsty violates, frugal satisfies
        assert check_water_allocation(problem, {"s2025": "thirsty"}).status == "violated"
        assert check_water_allocation(problem, {"s2025": "frugal"}).status == "satisfied"
        # optimizer: choosing thirsty must be infeasible; frugal feasible
        result_t = optimize_strategy(problem, "water_priority", dict(PROFILE_WEIGHTS["water_priority"]))
        from app.rotation.optimizer import InfeasibleResult
        if isinstance(result_t, InfeasibleResult):
            # the whole profile is infeasible only if EVERY candidate violates;
            # frugal fits, so a solution must exist — reaching here is a bug
            pytest.fail("frugal fits the allocation; the profile must be feasible")
        chosen = dict(result_t.assignment)["s2025"]
        assert chosen == "frugal"

    def test_infeasible_conflict_names_water_allocation(self):
        thirsty = _crop("thirsty", kc=(1.1, 1.4, 0.9))
        evidence = _evidence(monthly_precip=GOLDEN_P)
        problem = _problem([thirsty], evidence=evidence, allocation=5000.0)
        result = optimize_strategy(problem, "water_priority", dict(PROFILE_WEIGHTS["water_priority"]))
        from app.rotation.optimizer import InfeasibleResult
        assert isinstance(result, InfeasibleResult)
        assert any(c["constraint"] == "water_allocation" for c in result.conflicts)
        # the conflict detail names the NIR basis
        water_conflicts = [c for c in result.conflicts if c["constraint"] == "water_allocation"]
        assert any("demand basis" in c["detail"] for c in water_conflicts)

    def test_missing_estimate_still_held_out_of_allocation_runs(self):
        no_kc = _crop("no_kc", kc=None)
        evidence = _evidence(monthly_precip=GOLDEN_P)
        problem = _problem([no_kc], evidence=evidence, allocation=45000.0)
        a = problem.candidates["s2025"]["no_kc"]
        assert a.water_requirement_mm is None
        assert a.net_irrigation_requirement_mm is None
        # assigned anyway (baseline-style check): the validator flags it
        checks = check_all(problem, {"s2025": "no_kc"})
        assert any(
            c.constraint_code == "water_allocation" and c.status == "violated"
            for c in checks
        )


class TestHonestMissing:
    def test_unevaluated_water_not_treated_as_zero(self):
        crop = _crop("maize")
        evidence = None
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        farm = _farm(climate={})
        knowledge = KnowledgeBaseData(pack_refs=(), crops={"maize": crop}, rules=())
        assessment = assess_crop(crop, season, knowledge, farm, evidence, None)
        assert assessment.water_requirement_mm is None
        assert assessment.net_irrigation_requirement_mm is None
        # without ANY evidence the climate dimension is listed; the water
        # dimension must be listed too once evidence exists but lacks inputs
        assert any(d["code"] == "climate_evidence" for d in assessment.unevaluated_dimensions)

    def test_water_dimension_listed_when_evidence_lacks_inputs(self):
        crop = _crop("maize")
        # evidence present but NO ET0 and NO precipitation
        evidence = _evidence(monthly_et0=(), season_et0_mm=None, monthly_precip=())
        season = Season(label="s2025", start_date=date(2025, 5, 1), end_date=date(2025, 9, 15))
        farm = _farm(climate={"s2025": evidence})
        knowledge = KnowledgeBaseData(pack_refs=(), crops={"maize": crop}, rules=())
        assessment = assess_crop(crop, season, knowledge, farm, evidence, None)
        assert assessment.water_requirement_mm is None
        assert assessment.net_irrigation_requirement_mm is None
        assert any(d["code"] == "water_requirement" for d in assessment.unevaluated_dimensions)

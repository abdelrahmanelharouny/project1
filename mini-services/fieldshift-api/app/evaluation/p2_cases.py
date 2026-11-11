"""P2 golden cases (P2 §14) — deterministic checks over the six workstreams.

Extends the P1 evaluation framework with a `p2` section. These cases run the
PURE decision cores (no database, no network, no LLM) against fixed synthetic
inputs and check mathematical/scientific contracts:

- satellite:  index formula correctness, same-month baseline semantics,
              dormancy labeling, stress-signal not-supported honesty
- climate:    forecast risk thresholds (ETCCDI/WMO), verification math,
              capability-matrix honesty (blocked adapters declared)
- soil:       SOC trajectory math + refusal below 2 measurements, alert
              labeling (PARTIAL balance, ESTIMATED trajectory)
- failure-lab: stress-pack validation, robustness metric math on
              hand-computed inputs
- evidence:   VoI honesty (never monetary), gap action completeness
- portfolio:  weight/constraint validation, checksum order-insensitivity

They verify ALGORITHMIC correctness of the P2 cores over synthetic fixtures.
They are NOT real-world agronomic validation and never reported as such.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger("croptwist.evaluation.p2")

P2_EVALUATION_VERSION = "p2-eval-1.0.0"


def _check(name: str, fn: Callable[[], None]) -> dict[str, Any]:
    try:
        fn()
        return {"name": name, "passed": True, "detail": ""}
    except AssertionError as exc:
        return {"name": name, "passed": False, "detail": str(exc) or "assertion failed"}
    except Exception as exc:  # noqa: BLE001 — a crashing check is a failed check
        return {"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------- satellite
def _satellite_cases() -> list[dict[str, Any]]:
    from app.vegetation.indices import compute_indices
    from app.vegetation.raster_indices import agree_with_scalar
    from app.vegetation.stress import build_stress_signals
    from app.vegetation.temporal import MonthlyStat, detect_temporal_findings, same_month_baseline

    def ndvi_formula():
        result = compute_indices(sensor="sentinel2", reflectances={"red": 0.2, "nir": 0.6}, indices=["ndvi"])
        assert abs(result.values["ndvi"] - 0.5) < 1e-9, "NDVI(0.2, 0.6) must be 0.5"

    def evi_coefficients():
        red, nir, blue = 0.1, 0.5, 0.05
        expected = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
        result = compute_indices(sensor="sentinel2", reflectances={"red": red, "nir": nir, "blue": blue}, indices=["evi"])
        assert abs(result.values["evi"] - expected) < 1e-9

    def baseline_prior_years_only():
        def s(year, mean):
            return MonthlyStat(year=year, month=7, mean=mean, n_valid=5, n_excluded=0)

        stats = [s(2020, 0.58), s(2021, 0.60), s(2022, 0.62), s(2023, 0.30)]
        baseline = same_month_baseline(stats, 7, exclude_year=2023)
        assert baseline.n_years == 3 and abs(baseline.mean - 0.6) < 1e-9

    def dormancy_labeling():
        def s(year, mean):
            return MonthlyStat(year=year, month=1, mean=mean, n_valid=5, n_excluded=0)

        stats = [s(2020, 0.09), s(2021, 0.11), s(2022, 0.10), s(2023, 0.02)]
        findings = detect_temporal_findings(stats=stats, index="ndvi", dormancy_months={1})
        anomalies = [f for f in findings if f["kind"] == "anomaly"]
        assert anomalies and all(f.get("context") == "seasonal_dormancy_or_harvest" for f in anomalies)

    def stress_signal_not_supported_honesty():
        finding = {
            "kind": "anomaly", "period": {"year": 2023, "month": 7}, "value": 0.3,
            "z": -2.5, "direction": "below_baseline", "detail": "decline", "baseline": {"n_years": 3},
        }
        signals = build_stress_signals(
            index="ndvi", findings=[finding], evidence={}, anomalies=[]
        )
        assert signals and signals[0]["possible_context"] == []
        assert "disease or pest diagnosis" in signals[0]["not_supported"]
        assert signals[0]["severity"] == "info"  # no context -> cause unknown

    def vectorized_scalar_agreement():
        bundle = {"red": 0.15, "nir": 0.45, "blue": 0.08, "green": 0.18, "swir1": 0.22}
        for index in ("ndvi", "evi", "savi", "ndmi", "ndwi"):
            assert agree_with_scalar(sensor="sentinel2", reflectances=bundle, index=index), index

    return [
        {"case_id": "satellite_ndvi_formula", "domain": "satellite", "check": _check("ndvi_formula", ndvi_formula)},
        {"case_id": "satellite_evi_coefficients", "domain": "satellite", "check": _check("evi_coefficients", evi_coefficients)},
        {"case_id": "satellite_same_month_baseline", "domain": "satellite", "check": _check("baseline_prior_years_only", baseline_prior_years_only)},
        {"case_id": "satellite_dormancy_labeling", "domain": "satellite", "check": _check("dormancy_labeling", dormancy_labeling)},
        {"case_id": "satellite_stress_honesty", "domain": "satellite", "check": _check("stress_honesty", stress_signal_not_supported_honesty)},
        {"case_id": "satellite_vectorized_agreement", "domain": "satellite", "check": _check("vectorized_agreement", vectorized_scalar_agreement)},
    ]


# ----------------------------------------------------------------- climate
def _climate_cases() -> list[dict[str, Any]]:
    from app.climate.risk import HEAVY_PRECIP_MM, HOT_DAY_THRESHOLD_C, screen_forecast_risks
    from app.climate.contracts import PROVIDER_CAPABILITY_MATRIX

    def heat_threshold():
        rows = [
            {"variable_code": "air_temperature_max", "value": v, "valid_time": datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=i)}
            for i, v in enumerate([20.0, HOT_DAY_THRESHOLD_C, HOT_DAY_THRESHOLD_C + 2.0])
        ]
        risks = screen_forecast_risks(forecast_rows=rows)
        heat = [r for r in risks if r.risk_code == "extreme_heat_risk"]
        assert len(heat) == 1 and heat[0].affected_days == 2

    def heavy_precip():
        rows = [
            {"variable_code": "precipitation", "value": v, "valid_time": datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=i)}
            for i, v in enumerate([2.0, HEAVY_PRECIP_MM + 5.0])
        ]
        risks = screen_forecast_risks(forecast_rows=rows)
        assert any(r.risk_code == "heavy_precipitation_risk" for r in risks)

    def dry_spell_consecutive_only():
        def rows(values):
            return [
                {"variable_code": "precipitation", "value": v, "valid_time": datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=i)}
                for i, v in enumerate(values)
            ]

        assert any(r.risk_code == "dry_spell_risk" for r in screen_forecast_risks(forecast_rows=rows([0.0] * 6 + [15.0])))
        assert not [r for r in screen_forecast_risks(forecast_rows=rows([0.0] * 4 + [3.0] + [0.0] * 4)) if r.risk_code == "dry_spell_risk"]

    def blocked_adapter_declared():
        cmip = next(p for p in PROVIDER_CAPABILITY_MATRIX if p["provider_code"] == "cmip6_projection")
        assert cmip["status"] == "blocked_pending_credentials"

    return [
        {"case_id": "climate_heat_threshold", "domain": "climate", "check": _check("heat_threshold", heat_threshold)},
        {"case_id": "climate_heavy_precip", "domain": "climate", "check": _check("heavy_precip", heavy_precip)},
        {"case_id": "climate_dry_spell_consecutive", "domain": "climate", "check": _check("dry_spell", dry_spell_consecutive_only)},
        {"case_id": "climate_blocked_adapter_declared", "domain": "climate", "check": _check("blocked_adapter", blocked_adapter_declared)},
    ]


# -------------------------------------------------------------------- soil
def _soil_cases() -> list[dict[str, Any]]:
    from app.soil.memory import soc_fixed_depth_trajectory, soil_alerts

    def trajectory_math():
        result = soc_fixed_depth_trajectory(
            soc_stocks=[
                {"observed_at": "2020-01-01", "total_stock_mg_ha": 40.0, "comparable_key": "k"},
                {"observed_at": "2024-01-01", "total_stock_mg_ha": 42.0, "comparable_key": "k"},
            ]
        )
        assert result["value"] is not None and abs(result["value"] - 0.5) < 0.01
        assert result["estimated"] is True

    def trajectory_refusal():
        result = soc_fixed_depth_trajectory(
            soc_stocks=[{"observed_at": "2020-01-01", "total_stock_mg_ha": 40.0, "comparable_key": "k"}]
        )
        assert result["value"] is None and "not_evaluated" in result

    def alert_labeling():
        alerts = soil_alerts(
            nutrient_budget={"elements": {"n": {"net_kg_ha": -35.0}}, "source_ref": None},
            salinity=None, soc_trajectory=None, erosion=None,
        )
        assert alerts and "PARTIAL" in alerts[0]["detail"]

    return [
        {"case_id": "soil_soc_trajectory_math", "domain": "soil", "check": _check("soc_trajectory", trajectory_math)},
        {"case_id": "soil_soc_refusal_below_two", "domain": "soil", "check": _check("soc_refusal", trajectory_refusal)},
        {"case_id": "soil_alert_partial_labeling", "domain": "soil", "check": _check("alert_labeling", alert_labeling)},
    ]


# ------------------------------------------------------------- failure lab
def _failure_lab_cases() -> list[dict[str, Any]]:
    from app.failure_lab.contracts import PRESET_PACKS
    from app.failure_lab.metrics import downside_risk, regret_by_pack, worst_case_regret

    def packs_documented():
        for code, pack in PRESET_PACKS.items():
            assert pack.assumption_note, code
            assert pack.provenance, code

    def regret_math():
        regrets = regret_by_pack(
            scores_by_pack={"s1": 0.8, "s2": 0.4},
            best_by_pack={"s1": 0.9, "s2": 0.6},
        )
        worst = worst_case_regret(regrets)
        assert worst["value"] is not None and abs(worst["value"] - 0.2) < 1e-9

    def downside_math():
        result = downside_risk({"a": 0.9, "b": 0.3}, 0.5)
        assert result["value"] is not None and abs(result["value"] - 0.1) < 1e-9  # (0 + 0.2)/2

    return [
        {"case_id": "stress_packs_documented", "domain": "failure_lab", "check": _check("packs_documented", packs_documented)},
        {"case_id": "stress_regret_math", "domain": "failure_lab", "check": _check("regret_math", regret_math)},
        {"case_id": "stress_downside_math", "domain": "failure_lab", "check": _check("downside_math", downside_math)},
    ]


# ----------------------------------------------------------- evidence gaps
def _evidence_cases() -> list[dict[str, Any]]:
    from app.evidence_gaps.voi import acquisition_plan_for_gap

    def plan_completeness():
        gap = {
            "gap_code": "soil_sample_missing",
            "required_evidence": "lab analysis",
            "potential_impact": "impact text",
            "affected_decisions": ["fertilization_plan"],
            "how_to_obtain": "Collect a composite sample. Then ship.",
            "urgent": True,
            "collection_cost": {"category": "medium", "effort": "effort"},
            "voi": {"decision_sensitivity": {"detail": "detail"}},
        }
        plan = acquisition_plan_for_gap(gap)
        for key in ("what_is_missing", "why_it_matters", "affected_decisions", "how_to_obtain", "urgent", "uncertainty_reduced"):
            assert key in plan, key
        assert not any(isinstance(v, str) and "$" in v for v in plan.values()), "no monetary values"

    return [
        {"case_id": "evidence_plan_completeness", "domain": "evidence", "check": _check("plan_completeness", plan_completeness)},
    ]


# ---------------------------------------------------------------- portfolio
def _portfolio_cases() -> list[dict[str, Any]]:
    from app.portfolio import contracts

    def weight_validation():
        try:
            contracts.validate_objective_weights({"water_efficiency": 0.0})
            raise AssertionError("all-zero weights must be refused")
        except contracts.ValidationFailed:
            pass

    def checksum_order_insensitive():
        allocs = [
            {"field_id": "f1", "season_index": 0, "crop_code": "maize", "area_ha": 2.5},
            {"field_id": "f2", "season_index": 0, "crop_code": "faba_bean", "area_ha": 3.0},
        ]
        c1 = contracts.canonical_checksum(
            contracts.run_checksum_payload(engine_version="x", request_parameters={}, result={}, allocations=allocs)
        )
        c2 = contracts.canonical_checksum(
            contracts.run_checksum_payload(engine_version="x", request_parameters={}, result={}, allocations=list(reversed(allocs)))
        )
        assert c1 == c2

    def labor_not_enforced_honesty():
        canonical, notes = contracts.validate_constraints(
            {"labor_capacity_person_days_per_season": 10}, has_labor_resources=False, has_machinery_resources=False
        )
        assert canonical["labor_capacity_person_days_per_season"] == 10
        assert any("not enforced" in n["reason"] for n in notes)

    return [
        {"case_id": "portfolio_weight_validation", "domain": "portfolio", "check": _check("weights", weight_validation)},
        {"case_id": "portfolio_checksum_stability", "domain": "portfolio", "check": _check("checksum", checksum_order_insensitive)},
        {"case_id": "portfolio_labor_honesty", "domain": "portfolio", "check": _check("labor_honesty", labor_not_enforced_honesty)},
    ]


def run_p2_deterministic_eval() -> dict[str, Any]:
    cases = (
        _satellite_cases()
        + _climate_cases()
        + _soil_cases()
        + _failure_lab_cases()
        + _evidence_cases()
        + _portfolio_cases()
    )
    total = len(cases)
    passed = sum(1 for c in cases if c["check"]["passed"])
    coverage: dict[str, dict[str, int]] = {}
    for c in cases:
        entry = coverage.setdefault(c["domain"], {"cases": 0, "passed": 0})
        entry["cases"] += 1
        entry["passed"] += 1 if c["check"]["passed"] else 0
    return {
        "suite": "p2-deterministic",
        "version": P2_EVALUATION_VERSION,
        "total_checks": total,
        "passed_checks": passed,
        "failed_checks": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "coverage_by_domain": coverage,
        "cases": cases,
        "limitations": [
            "P2 golden cases verify the ALGORITHMIC contracts of the pure "
            "decision cores over synthetic fixtures (formulas, thresholds, "
            "honesty labeling, checksum stability).",
            "They are NOT scientific validation: no field data, no calibrated "
            "accuracy claims, no real-world agronomic validation is implied.",
            "DB-backed behavior is covered by the integration suites; live "
            "provider behavior is BLOCKED in this deployment and asserted to "
            "fail loudly rather than fabricate data.",
        ],
    }

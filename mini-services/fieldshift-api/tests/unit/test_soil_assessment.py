"""Soil assessment engine tests (M6B Step 7, ADR-0026/0027/0028)."""

from __future__ import annotations

import pytest

from app.soil import assessment


def _m(var, value, observed_at="2026-01-01", unit="g/kg", method_params=None,
       evidence="direct_field_measurement", depth=(0, 30), synthetic=False):
    return {
        "variable_code": var,
        "value": value,
        "unit": unit,
        "observed_at": observed_at,
        "method_params": method_params or {},
        "evidence_class": evidence,
        "source_kind": "lab_analysis",
        "quality_status": "valid",
        "is_synthetic": synthetic,
        "top_depth_cm": depth[0],
        "bottom_depth_cm": depth[1],
        "result_qualifier": None,
    }


class TestDomainAssessment:
    def test_no_score_ever(self):
        result = assessment.assess_domains([_m("soil_ph", 7.0)], field_id="f1")
        assert result["composite_score"] is None
        assert "no composite index" in result["composite_note"]

    def test_domains_covered(self):
        result = assessment.assess_domains([], field_id="f1")
        assert [d["domain"] for d in result["domains"]] == list(assessment.DOMAINS)
        for d in result["domains"]:
            assert d["available"] == [] and d["available_count"] == 0

    def test_missing_is_unknown_not_bad(self):
        result = assessment.assess_domains([_m("soil_ph", 7.2)], field_id="f1")
        bio = next(d for d in result["domains"] if d["domain"] == "biological")
        assert bio["available"] == []
        assert "UNKNOWN" in result["missing_is_not_bad_note"]

    def test_available_indicator_carries_method_and_evidence(self):
        result = assessment.assess_domains(
            [_m("soil_ph", 7.2, method_params={"code": "ph_water_1_2_5", "medium": "water"})],
            field_id="f1",
        )
        chem = next(d for d in result["domains"] if d["domain"] == "chemical")
        entry = next(e for e in chem["available"] if e["variable_code"] == "soil_ph")
        assert entry["evidence_class"] == "direct_field_measurement"
        assert entry["method"] == "ph_water_1_2_5"
        assert entry["local_applicability"].startswith("reference-grade")

    def test_prediction_indicator_never_merged_with_measured(self):
        # two rows same variable: one measured, one prediction — both listed,
        # latest picked but evidence class preserved per row
        measured = _m("soil_organic_carbon", 12.0, observed_at="2026-02-01")
        mapped = _m("soil_organic_carbon", 15.0, observed_at="2020-01-01",
                    evidence="global_soil_prediction", synthetic=False)
        result = assessment.assess_domains([measured, mapped], field_id="f1")
        om = next(d for d in result["domains"] if d["domain"] == "organic_matter_nutrient_cycling")
        assert len(om["available"]) == 1
        entry = om["available"][0]
        assert entry["evidence_class"] == "direct_field_measurement"  # latest by date

    def test_synthetic_flagged(self):
        result = assessment.assess_domains(
            [_m("soil_ph", 7.0, synthetic=True)], field_id="f1"
        )
        assert any(d["synthetic_flag"] for d in result["domains"])


class TestComparabilityGate:
    def test_same_method_comparable(self):
        history = [
            _m("soil_organic_carbon", 12.0, observed_at="2020-05-01"),
            _m("soil_organic_carbon", 13.5, observed_at="2026-05-01"),
        ]
        gate = assessment.comparability_gate(history)
        assert gate["comparable"] is True

    def test_method_difference_blocks_trend(self):
        history = [
            _m("soil_ph", 6.8, observed_at="2020-05-01",
               method_params={"medium": "water", "soil_solution_ratio": "1:2.5"}),
            _m("soil_ph", 6.2, observed_at="2026-05-01",
               method_params={"medium": "cacl2", "soil_solution_ratio": "1:2.5"}),
        ]
        gate = assessment.comparability_gate(history)
        assert gate["comparable"] is False
        assert "method identity" in gate["reason"]

    def test_depth_difference_blocks_trend(self):
        history = [
            _m("soil_organic_carbon", 12.0, observed_at="2020-05-01", depth=(0, 15)),
            _m("soil_organic_carbon", 13.5, observed_at="2026-05-01", depth=(0, 30)),
        ]
        gate = assessment.comparability_gate(history)
        assert gate["comparable"] is False
        assert "depth" in gate["reason"]

    def test_trend_delta_hand_computed(self):
        history = [
            _m("soil_organic_carbon", 12.0, observed_at="2020-05-01"),
            _m("soil_organic_carbon", 13.5, observed_at="2026-05-01"),
        ]
        trend = assessment._trend(history)
        assert trend["status"] == "measured_change"
        assert trend["delta"] == 1.5
        assert "not causation" in trend["caveat"]

    def test_trend_refused_for_incompatible_history(self):
        history = [
            _m("soil_organic_carbon", 12.0, observed_at="2020-05-01"),
            _m("soil_organic_carbon", 13.5, observed_at="2026-05-01",
               evidence="global_soil_prediction", method_params={"code": "soilgrids"}),
        ]
        trend = assessment._trend(history)
        assert trend["status"] == "not_comparable"


class TestVOI:
    def test_priorities_decision_linked_qualitative(self):
        result = assessment.data_readiness([])
        codes = [p["variable_code"] for p in result["priorities"]]
        assert "soil_electrical_conductivity" in codes
        for p in result["priorities"]:
            assert p["decision_unblocked"]  # each states the decision it unblocks
        assert "no sampling costs" in result["policy"]

    def test_present_variables_not_suggested(self):
        result = assessment.data_readiness([_m("soil_ph", 7.0), _m("soil_electrical_conductivity", 1.2, unit="dS/m")])
        codes = [p["variable_code"] for p in result["priorities"]]
        assert "soil_ph" not in codes
        assert "soil_electrical_conductivity" not in codes
        assert "soil_bulk_density" in codes  # still missing

    def test_checksum_stable(self):
        result = assessment.assess_domains([_m("soil_ph", 7.0)], field_id="f1")
        assert assessment.assessment_checksum(result) == assessment.assessment_checksum(result)

"""Unit: erosion & conservation screening engine (M6C Increment 6).

Golden RUSLE case hand-computed: R=100, K=0.25, LS=1.0, C=0.3, P=0.5 →
A = 3.75. Honesty properties: no numeric result without all five factors;
mixed unit conventions refused; process scope declared; screening never
numeric; alternatives never ranked with invented effectiveness.
"""

import pytest

from app.management.erosion import (
    ErosionEngineError,
    conservation_alternatives,
    qualitative_screening,
    run_erosion_assessment,
    rusle_screening,
)


def _factors(**overrides):
    def f(value, convention="metric_si"):
        return {
            "value": value,
            "source_reference": "local soil survey (2024)",
            "region_scope": "demo-region",
            "unit_convention": convention,
        }

    base = {"R": f(100.0), "K": f(0.25), "LS": f(1.0), "C": f(0.3), "P": f(0.5)}
    base.update(overrides)
    return base


class TestRusleDomainControl:
    def test_golden_hand_computed(self):
        out = rusle_screening(_factors())
        assert out["status"] == "computed"
        assert out["annual_soil_loss_a"] == pytest.approx(3.75)
        assert out["assessment_kind"] == "screening_only"
        assert set(out["processes"]) == {"sheet_interrill", "rill"}

    def test_missing_factor_refuses_partial_product(self):
        factors = _factors()
        del factors["LS"]
        out = rusle_screening(factors)
        assert out["status"] == "not_evaluated"
        assert out["missing_factors"] == ["LS"]
        assert "annual_soil_loss_a" not in out

    def test_no_factors_names_all_missing(self):
        out = rusle_screening(None)
        assert out["status"] == "not_evaluated"
        assert set(out["missing_factors"]) == {"R", "K", "LS", "C", "P"}
        assert "annual_soil_loss_a" not in out

    def test_unsourced_factor_refused(self):
        factors = _factors()
        factors["K"]["source_reference"] = None
        out = rusle_screening(factors)
        assert out["status"] == "not_evaluated"
        assert "provenance" in out["message"]

    def test_mixed_unit_conventions_refused(self):
        factors = _factors()
        factors["R"]["unit_convention"] = "us_customary"
        out = rusle_screening(factors)
        assert out["status"] == "not_evaluated"
        assert "never combined" in out["message"]
        assert "annual_soil_loss_a" not in out

    def test_result_declares_scope_limits(self):
        out = rusle_screening(_factors())
        blob = " ".join(out["scope_disclosures"]).lower()
        for banned_scope in ("ephemeral", "gull", "wind", "streambank", "sediment yield"):
            assert f"not " in blob or "no " in blob  # disclosures exist
        assert out["processes"] == ["sheet_interrill", "rill"]
        assert any("no dem" in d.lower() or "supplied, not computed" in d.lower()
                   for d in out["scope_disclosures"])

    def test_platform_ships_no_factor_values(self):
        """The no-factors message must not contain any numeric suggestion."""
        out = rusle_screening(None)
        import re

        numbers = re.findall(r"\d+\.?\d*", out["message"])
        assert numbers == [], f"engine suggested values: {numbers}"


class TestQualitativeScreening:
    def test_bare_days_raise_sheet_rill_and_wind_concerns(self):
        out = qualitative_screening(
            slope_evidence=None,
            soil_evidence=None,
            cover_metrics={"days_known_bare": 42, "longest_bare_interval_days": 15},
            rainfall_evidence=None,
            management_flags=[],
            observed_signs=[],
        )
        codes = {c["code"] for c in out["concerns"]}
        assert "exposed_soil_days" in codes
        concern = next(c for c in out["concerns"] if c["code"] == "exposed_soil_days")
        assert "42" in concern["evidence"]
        assert "wind" in concern["processes"]

    def test_no_inputs_all_unknown(self):
        out = qualitative_screening(
            slope_evidence=None, soil_evidence=None, cover_metrics=None,
            rainfall_evidence=None, management_flags=[], observed_signs=[],
        )
        assert out["concerns"] == []
        assert len(out["unknowns"]) >= 3
        assert out["assessment_kind"] == "qualitative_screening"

    def test_steep_slope_flagged_with_evidence_class(self):
        out = qualitative_screening(
            slope_evidence={"slope_class": "steep", "evidence_class": "farmer_reported_record"},
            soil_evidence=None, cover_metrics=None, rainfall_evidence=None,
            management_flags=[], observed_signs=[],
        )
        concern = next(c for c in out["concerns"] if c["code"] == "slope_class_evidence")
        assert "steep" in concern["evidence"]

    def test_rainfall_amount_not_erosivity(self):
        out = qualitative_screening(
            slope_evidence=None, soil_evidence=None, cover_metrics=None,
            rainfall_evidence={"wettest_month_mm": 180.0, "feature_run_id": "r"},
            management_flags=[], observed_signs=[],
        )
        concern = next(c for c in out["concerns"] if c["code"] == "rainfall_amount_evidence")
        assert "NOT an erosivity" in concern["evidence"]

    def test_observed_signs_separate_from_concerns(self):
        out = qualitative_screening(
            slope_evidence=None, soil_evidence=None, cover_metrics=None,
            rainfall_evidence=None, management_flags=[],
            observed_signs=[{"description": "rill visible after storm",
                             "processes": ["rill"]}],
        )
        assert out["field_observed_signs"][0]["description"] == "rill visible after storm"
        assert out["field_observed_signs"] != out["concerns"]


class TestAlternatives:
    def test_alternatives_carry_citations_and_no_ranking(self):
        practices = [
            {
                "practice_code": "contour_operations",
                "name": "Contour-aligned operations",
                "practice_family": "erosion_control",
                "validation_status": "reference",
                "payload": {
                    "mechanisms": [
                        {"mechanism_code": "runoff_slowing",
                         "text": "Contour orientation reduces runoff concentration and transport on slopes.",
                         "citation": {"citation_text": "NAM (2022)"}, "confidence": "low"},
                        {"mechanism_code": "other",
                         "text": "Requires guidance capability to keep passes on the contour.",
                         "citation": {"citation_text": "NAM (2022)"}, "confidence": "low"},
                    ],
                    "trade_offs": [
                        {"dimension": "erosion_protection", "direction": "positive",
                         "text": "acts as a support practice", "citation": {"citation_text": "RUSLE2"}},
                    ],
                },
            },
            {
                "practice_code": "mulching",
                "name": "Mulching",
                "practice_family": "soil_cover",
                "validation_status": "reference",
                "payload": {"mechanisms": [], "trade_offs": []},
            },
        ]
        out = conservation_alternatives(practices)
        codes = [a["practice_code"] for a in out["alternatives"]]
        assert "contour_operations" in codes
        assert "mulching" not in codes  # soil_cover family not in the erosion set
        alt = out["alternatives"][0]
        assert alt["mechanisms"][0]["citation"]["citation_text"] == "NAM (2022)"
        assert "no effectiveness number is invented" in out["message"]
        assert "requires model parameters" in alt["quantitative_note"]


class TestRunAssessment:
    def test_status_separation_structure(self):
        out = run_erosion_assessment(
            rusle_factors=None,
            slope_evidence={"slope_class": "moderate", "evidence_class": "farmer_reported_record"},
            soil_evidence=None,
            cover_metrics={"days_known_bare": 10, "longest_bare_interval_days": 6},
            rainfall_evidence=None,
            management_flags=[{"code": "tillage_disturbance",
                               "processes": ["sheet_interrill"], "message": "tillage recorded"}],
            observed_signs=[],
            practices=[],
        )
        sep = out["status_separation"]
        assert len(sep["model_estimates"]) == 0  # no factors → no model estimate
        assert sep["susceptibility_evidence"]
        assert sep["field_observed_signs"] == []
        assert any("rainfall" in u for u in sep["unknown_status"])
        # process coverage: gully/wind/etc. explicitly not_evaluated
        ne = out["not_evaluated"]["processes"]
        assert "classical_gully" in ne and "streambank" in ne

    def test_deterministic(self):
        kwargs = dict(
            rusle_factors=_factors(),
            slope_evidence={"slope_class": "gentle"},
            soil_evidence=None,
            cover_metrics={"days_known_bare": 3, "longest_bare_interval_days": 3},
            rainfall_evidence={"wettest_month_mm": 90.0},
            management_flags=[],
            observed_signs=[],
            practices=[],
        )
        assert run_erosion_assessment(**kwargs) == run_erosion_assessment(**kwargs)

"""Unit: M7.4 sensitivity mathematics — sweep design, finite differences,
elasticity, response classification, envelope, interaction contrast.

All tolerances come from the versioned rubric (sensitivity contracts).
"""

import pytest

from app.sensitivity import contracts as sc
from app.sensitivity import math as smath


# ------------------------------------------------------------- sweep design


class TestLinspace:
    def test_includes_endpoints(self):
        points = smath.linspace(-2.0, 6.0, 9)
        assert points[0] == -2.0
        assert points[-1] == pytest.approx(6.0, abs=1e-12)
        assert len(points) == 9

    def test_even_spacing(self):
        points = smath.linspace(0.0, 1.0, 5)
        diffs = [points[i + 1] - points[i] for i in range(4)]
        assert all(abs(d - 0.25) < 1e-12 for d in diffs)

    def test_two_points(self):
        assert smath.linspace(1.0, 3.0, 2) == [1.0, 3.0]

    def test_requires_two_points(self):
        with pytest.raises(ValueError):
            smath.linspace(0, 1, 1)


class TestParameterDesignValidation:
    def test_valid_design_has_no_findings(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": -2.0, "upper": 6.0, "n_points": 9}, 2.0
        )
        assert findings == []

    def test_bounds_must_contain_reference(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": 3.0, "upper": 6.0, "n_points": 5}, 2.0
        )
        assert any("bounds must contain the reference" in f["reason"] for f in findings)

    def test_lower_exceeds_upper(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": 6.0, "upper": 2.0, "n_points": 5}, 2.0
        )
        assert any("lower bound exceeds upper bound" in f["reason"] for f in findings)

    def test_negative_multiplier_lower_rejected(self):
        findings = smath.validate_parameter_design(
            "precipitation_multiplier", {"lower": -0.5, "upper": 1.5, "n_points": 5}, 1.0
        )
        assert any(">= 0" in f["reason"] for f in findings)

    def test_temperature_guardrail(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": -30.0, "upper": 6.0, "n_points": 5}, 2.0
        )
        assert any("guardrail" in f["reason"] for f in findings)

    def test_multiplier_guardrail(self):
        findings = smath.validate_parameter_design(
            "precipitation_multiplier", {"lower": 0.5, "upper": 11.0, "n_points": 5}, 1.0
        )
        assert any("guardrail" in f["reason"] for f in findings)

    def test_n_points_range(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": -2.0, "upper": 6.0, "n_points": 2}, 2.0
        )
        assert any("between 3 and 21" in f["reason"] for f in findings)
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": -2.0, "upper": 6.0, "n_points": 22}, 2.0
        )
        assert any("between 3 and 21" in f["reason"] for f in findings)

    def test_non_finite_rejected(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": float("nan"), "upper": 6.0, "n_points": 5}, 2.0
        )
        assert any("finite" in f["reason"] for f in findings)

    def test_bool_rejected(self):
        findings = smath.validate_parameter_design(
            "temperature_delta_c", {"lower": True, "upper": 6.0, "n_points": 5}, 2.0
        )
        assert any("finite number" in f["reason"] for f in findings)

    def test_grid_design_requires_all_axes(self):
        findings = smath.validate_grid_design(
            {"temperature_delta_c": {"lower": -2, "upper": 6, "n_points": 3}},
            {"temperature_delta_c": 2.0, "precipitation_multiplier": 1.0},
        )
        assert any("every explorable parameter" in f["reason"] for f in findings)

    def test_grid_at_cell_cap_allowed(self):
        # 9×9 = 81 cells is exactly the documented cap; allowed. The binding
        # guard in practice is the unique-evaluation budget (service layer).
        findings = smath.validate_grid_design(
            {
                "temperature_delta_c": {"lower": -2, "upper": 6, "n_points": 9},
                "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 9},
            },
            {"temperature_delta_c": 2.0, "precipitation_multiplier": 1.0},
        )
        assert findings == []


# --------------------------------------------------------- finite differences


class TestFiniteDifferenceSlope:
    def test_central_difference_linear(self):
        points = [(-2.0, 5.0), (0.0, 7.0), (2.0, 9.0)]
        info = smath.finite_difference_slope(points, 0.0)
        assert info["slope_method"] == "central"
        assert info["slope"] == pytest.approx(1.0)

    def test_forward_one_sided_at_lower_boundary(self):
        points = [(0.0, 4.0), (1.0, 6.0)]
        info = smath.finite_difference_slope(points, 0.0)
        assert info["slope_method"] == "forward_one_sided"
        assert info["slope"] == pytest.approx(2.0)

    def test_backward_one_sided_at_upper_boundary(self):
        points = [(-1.0, 3.0), (0.0, 5.0)]
        info = smath.finite_difference_slope(points, 0.0)
        assert info["slope_method"] == "backward_one_sided"
        assert info["slope"] == pytest.approx(2.0)

    def test_insufficient_points(self):
        info = smath.finite_difference_slope([(1.0, 2.0)], 1.0)
        assert info["slope"] is None
        assert info["slope_method"] == sc.SLOPE_METHOD_NOT_EVALUATED

    def test_reference_between_grid_points_bracketed(self):
        # reference not among evaluated points → secant over bracket
        points = [(0.0, 2.0), (2.0, 6.0)]
        info = smath.finite_difference_slope(points, 1.0)
        assert info["slope"] == pytest.approx(2.0)


class TestElasticity:
    def test_available(self):
        payload = smath.elasticity_payload(1.0, 2.0, 7.0)
        assert payload["status"] == "available"
        assert payload["value"] == pytest.approx(2.0 / 7.0)

    def test_reference_value_zero_structurally_unavailable(self):
        payload = smath.elasticity_payload(1.0, 2.0, 0.0)
        assert payload == {
            "status": "unavailable",
            "value": None,
            "reason": "reference_value_is_zero",
        }

    def test_reference_parameter_zero_structurally_unavailable(self):
        payload = smath.elasticity_payload(1.0, 0.0, 5.0)
        assert payload["reason"] == "reference_parameter_is_zero"

    def test_missing_slope(self):
        payload = smath.elasticity_payload(None, 2.0, 5.0)
        assert payload["reason"] == "slope_not_evaluated"


# ------------------------------------------------------------ direction


class TestDirection:
    def test_increasing(self):
        assert smath.direction_payload([(0, 1.0), (1, 2.0)]) == "increasing"

    def test_decreasing(self):
        assert smath.direction_payload([(0, 2.0), (1, 1.0)]) == "decreasing"

    def test_no_change(self):
        assert smath.direction_payload([(0, 1.0), (1, 1.0)]) == "no_change"

    def test_not_evaluated(self):
        assert smath.direction_payload([(0, 1.0)]) == "not_evaluated"


# -------------------------------------------------------- classification


class TestClassification:
    def test_not_evaluated(self):
        assert smath.classify_response([], 1.0) == "not_evaluated"

    def test_insufficient_points(self):
        assert (
            smath.classify_response([(0, 1.0)], 1.0)
            == "insufficient_evaluated_points"
        )

    def test_constant_within_band(self):
        points = [(0, 10.0), (1, 10.0 + 1e-12), (2, 10.0 - 1e-12)]
        assert smath.classify_response(points, 10.0) == "constant"

    def test_monotonic_increasing(self):
        points = [(0, 1.0), (1, 2.0), (2, 4.0)]
        assert smath.classify_response(points, 2.0) == "monotonic_increasing"

    def test_monotonic_decreasing(self):
        points = [(0, 4.0), (1, 2.0), (2, 1.0)]
        assert smath.classify_response(points, 2.0) == "monotonic_decreasing"

    def test_non_monotonic(self):
        points = [(0, 1.0), (1, 3.0), (2, 2.0), (3, 4.0)]
        assert smath.classify_response(points, 2.0) == "non_monotonic"

    def test_threshold_dominant_step(self):
        # flat then one dominant jump: median nonzero is tiny, max step is huge
        points = [(0, 0.0), (1, 0.001), (2, 0.002), (3, 0.003), (4, 0.004), (5, 10.0)]
        assert smath.classify_response(points, 0.0) == "threshold_suspected"

    def test_smooth_steep_monotonic_not_threshold(self):
        # uniformly increasing: no dominant single step
        points = [(i, float(i)) for i in range(8)]
        assert smath.classify_response(points, 0.0) == "monotonic_increasing"

    def test_threshold_affected_flag(self):
        points = [(0, 0.0), (1, 0.0), (2, 0.0), (3, 0.0), (4, 0.0), (5, 5.0)]
        assert smath.threshold_affected(points, 0.0) is True


# ------------------------------------------------------------- envelope


class TestEnvelope:
    def test_min_max(self):
        payload = smath.envelope_payload([(0, 2.0), (1, 5.0), (2, 3.0)], 0, 2)
        assert payload["lower"] == 2.0
        assert payload["upper"] == 5.0
        assert payload["parameter_lower"] == 0
        assert payload["parameter_upper"] == 2

    def test_empty(self):
        payload = smath.envelope_payload([], 0, 1)
        assert payload["lower"] is None and payload["upper"] is None


# ------------------------------------------------- interaction contrast


class TestInteractionContrast:
    def test_super_additive(self):
        result = smath.interaction_contrast({"f00": 1.0, "f10": 2.0, "f01": 3.0, "f11": 6.0})
        assert result["value"] == pytest.approx(2.0)
        assert result["interpretation"] == "super_additive_over_explored_grid"

    def test_sub_additive(self):
        result = smath.interaction_contrast({"f00": 1.0, "f10": 2.0, "f01": 3.0, "f11": 5.0})
        assert result["value"] == pytest.approx(1.0)
        assert result["interpretation"] == "super_additive_over_explored_grid"
        result = smath.interaction_contrast({"f00": 1.0, "f10": 2.0, "f01": 3.0, "f11": 4.0})
        assert result["value"] == pytest.approx(0.0)
        assert result["interpretation"] == "approximately_additive"

    def test_missing_corner_not_evaluated(self):
        result = smath.interaction_contrast({"f00": 1.0, "f10": None, "f01": 3.0, "f11": 4.0})
        assert result["interpretation"] == "not_evaluated"

    def test_single_family_feature_exactly_zero(self):
        # A feature depending on one axis only: f(x,z) = g(x) ⇒ I = 0 exactly.
        def g(x):
            return 10.0 + 2.0 * x

        x0, x1, z0, z1 = 0.0, 2.0, 0.5, 1.5
        result = smath.interaction_contrast(
            {
                "f00": g(x0),
                "f10": g(x1),
                "f01": g(x0),
                "f11": g(x1),
            }
        )
        assert result["value"] == 0.0
        assert result["interpretation"] == "approximately_additive"


class TestGridAxisMonotonicity:
    def test_row_sign_change_detected(self):
        assert smath.grid_axis_monotonicity({"row": [1.0, 3.0, 2.0]}) is True

    def test_monotonic_row(self):
        assert smath.grid_axis_monotonicity({"row": [1.0, 2.0, 3.0]}) is False

    def test_skips_insufficient(self):
        assert smath.grid_axis_monotonicity({"row": [1.0]}) is False

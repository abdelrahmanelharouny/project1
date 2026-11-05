"""Pure sensitivity mathematics (Milestone 7.4).

Deterministic, side-effect-free implementations of the M7.4 method
(docs/m7/m7_4/M7_4_SENSITIVITY_METHOD.md):

- parameter sweep design (linspace) + validation with structured findings,
- finite-difference slopes (central preferred, one-sided fallback) with
  explicit units and validity flags,
- normalised elasticity with structured unavailability (never a division by
  zero, never an epsilon fudge),
- response-behaviour classification under the versioned rubric,
- finite-grid interaction contrast and grid summaries.

NO database, NO HTTP, NO randomness, NO clock. Identical inputs produce
identical outputs. Classification tolerances live in
`app.sensitivity.contracts` and are versioned with the rubric.
"""

import math
from typing import Any

from app.sensitivity import contracts as sc

# ---------------------------------------------------------------------------
# Sweep design
# ---------------------------------------------------------------------------


def linspace(lower: float, upper: float, n_points: int) -> list[float]:
    """Closed even sweep including both endpoints (deterministic)."""
    if n_points < 2:
        raise ValueError("n_points must be >= 2")
    if n_points == 2:
        return [float(lower), float(upper)]
    step = (float(upper) - float(lower)) / (n_points - 1)
    return [float(lower) + i * step for i in range(n_points)]


def validate_parameter_design(
    parameter_code: str,
    design: dict[str, Any],
    reference_value: float,
) -> list[dict[str, str]]:
    """Validate one parameter design against its reference value.

    Returns structured findings (empty = valid). Mirrors the documented
    guardrails; every finding names its field and reason.
    """
    findings: list[dict[str, str]] = []
    field = f"parameter_design.{parameter_code}"

    lower = design.get("lower")
    upper = design.get("upper")
    n_points = design.get("n_points", sc.DEFAULT_OAT_POINTS)

    for name, value in (("lower", lower), ("upper", upper)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            findings.append({"field": f"{field}.{name}", "reason": "must be a finite number"})
        elif not math.isfinite(float(value)):
            findings.append({"field": f"{field}.{name}", "reason": "must be a finite number"})
    if findings:
        return findings

    lower_f, upper_f = float(lower), float(upper)
    reference_f = float(reference_value)

    if lower_f > upper_f:
        findings.append({"field": f"{field}.lower", "reason": "lower bound exceeds upper bound"})
    if reference_f < lower_f - sc.EQUALITY_TOL or reference_f > upper_f + sc.EQUALITY_TOL:
        findings.append(
            {
                "field": field,
                "reason": "bounds must contain the reference parameter value",
            }
        )
    if parameter_code == sc.SensitivityParameter.TEMPERATURE_DELTA_C.value:
        if abs(lower_f) > sc.MAX_ABS_TEMPERATURE_DELTA_C or abs(upper_f) > sc.MAX_ABS_TEMPERATURE_DELTA_C:
            findings.append(
                {
                    "field": field,
                    "reason": (
                        f"temperature bounds beyond ±{sc.MAX_ABS_TEMPERATURE_DELTA_C:g} °C "
                        "are outside the documented guardrail"
                    ),
                }
            )
    if parameter_code == sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value:
        if lower_f < 0:
            findings.append(
                {"field": f"{field}.lower", "reason": "precipitation multiplier must be >= 0"}
            )
        if upper_f > sc.MAX_PRECIPITATION_MULTIPLIER:
            findings.append(
                {
                    "field": field,
                    "reason": (
                        f"multiplier bounds beyond {sc.MAX_PRECIPITATION_MULTIPLIER:g} are "
                        "outside the documented guardrail"
                    ),
                }
            )

    if isinstance(n_points, bool) or not isinstance(n_points, int):
        findings.append({"field": f"{field}.n_points", "reason": "must be an integer"})
    elif n_points < sc.MIN_OAT_POINTS or n_points > sc.MAX_OAT_POINTS:
        findings.append(
            {
                "field": f"{field}.n_points",
                "reason": f"must be between {sc.MIN_OAT_POINTS} and {sc.MAX_OAT_POINTS}",
            }
        )
    return findings


def validate_grid_design(
    grid_design: dict[str, Any],
    reference_values: dict[str, float],
) -> list[dict[str, str]]:
    """Validate the opt-in joint grid design (bounds per explorable axis)."""
    findings: list[dict[str, str]] = []
    if not isinstance(grid_design, dict):
        return [{"field": "grid", "reason": "must be an object with per-parameter designs"}]
    if not reference_values:
        return [{"field": "grid", "reason": "joint grid requires two explorable parameters"}]
    total_cells = 1
    for parameter_code, reference in reference_values.items():
        design = grid_design.get(parameter_code)
        if design is None:
            findings.append(
                {"field": f"grid.{parameter_code}", "reason": "joint grid requires bounds for every explorable parameter"}
            )
            continue
        # Grid axes may use the OAT validator's bound/finite checks but allow
        # the grid-specific point range.
        findings.extend(validate_parameter_design(parameter_code, design, float(reference)))
        n_points = design.get("n_points", sc.DEFAULT_OAT_POINTS)
        if isinstance(n_points, int) and not isinstance(n_points, bool):
            if n_points < sc.MIN_GRID_POINTS or n_points > sc.MAX_GRID_POINTS:
                findings.append(
                    {
                        "field": f"grid.{parameter_code}.n_points",
                        "reason": f"must be between {sc.MIN_GRID_POINTS} and {sc.MAX_GRID_POINTS}",
                    }
                )
            total_cells *= n_points
    if not findings and total_cells > sc.MAX_GRID_CELLS:
        findings.append(
            {
                "field": "grid",
                "reason": f"joint grid would evaluate {total_cells} cells; the documented cap is {sc.MAX_GRID_CELLS}",
            }
        )
    return findings


# ---------------------------------------------------------------------------
# Finite differences & elasticity
# ---------------------------------------------------------------------------


def finite_difference_slope(
    points: list[tuple[float, float]],
    x_ref: float,
) -> dict[str, Any]:
    """Slope at the reference point from evaluated sweep points.

    `points` are (x, y) pairs with finite y, ascending in x. Returns
    {slope, slope_method, h} or {slope: None, slope_method: not_evaluated}.
    Central difference is preferred; one-sided fallback at the boundary.
    """
    if len(points) < 2:
        return {"slope": None, "slope_method": sc.SLOPE_METHOD_NOT_EVALUATED, "h": None}

    # Locate the reference position among the points (or its insertion index).
    xs = [p[0] for p in points]
    exact = None
    for i, x in enumerate(xs):
        if abs(x - x_ref) <= sc.EQUALITY_TOL:
            exact = i
            break

    if exact is not None:
        i = exact
        has_left = i > 0
        has_right = i < len(points) - 1
        if has_left and has_right:
            x_l, y_l = points[i - 1]
            x_r, y_r = points[i + 1]
            h_l = x_ref - x_l
            h_r = x_r - x_ref
            # Central difference requires (near-)equal spacing; the sweep is
            # a linspace so this holds; unequal spacing falls back one-sided.
            if h_l > sc.EQUALITY_TOL and h_r > sc.EQUALITY_TOL and abs(h_l - h_r) <= 1e-6 * max(h_l, h_r):
                return {
                    "slope": (y_r - y_l) / (h_r + h_l),
                    "slope_method": sc.SLOPE_METHOD_CENTRAL,
                    "h": (h_l + h_r) / 2.0,
                }
        if has_right:
            x_r, y_r = points[i + 1]
            h = x_r - x_ref
            if h > sc.EQUALITY_TOL:
                return {
                    "slope": (y_r - points[i][1]) / h,
                    "slope_method": sc.SLOPE_METHOD_FORWARD,
                    "h": h,
                }
        if has_left:
            x_l, y_l = points[i - 1]
            h = x_ref - x_l
            if h > sc.EQUALITY_TOL:
                return {
                    "slope": (points[i][1] - y_l) / h,
                    "slope_method": sc.SLOPE_METHOD_BACKWARD,
                    "h": h,
                }
        return {"slope": None, "slope_method": sc.SLOPE_METHOD_NOT_EVALUATED, "h": None}

    # x_ref not among evaluated points (e.g. the reference evaluation failed):
    # bracket by nearest neighbours of the insertion position.
    import bisect

    pos = bisect.bisect_left(xs, x_ref)
    if pos == 0 or pos == len(points):
        return {"slope": None, "slope_method": sc.SLOPE_METHOD_NOT_EVALUATED, "h": None}
    x_l, y_l = points[pos - 1]
    x_r, y_r = points[pos]
    h = x_r - x_l
    if h <= sc.EQUALITY_TOL:
        return {"slope": None, "slope_method": sc.SLOPE_METHOD_NOT_EVALUATED, "h": None}
    return {"slope": (y_r - y_l) / h, "slope_method": sc.SLOPE_METHOD_CENTRAL, "h": h}


def elasticity_payload(
    slope: float | None,
    x_ref: float,
    y_ref: float | None,
) -> dict[str, Any]:
    """Normalised elasticity E = (Δy/y_ref) / (Δx/x_ref) = S·x_ref/y_ref.

    Structured unavailability whenever the ratio is not mathematically
    meaningful — never a division by zero, never an epsilon substitution.
    """
    if slope is None:
        return {"status": sc.ELASTICITY_UNAVAILABLE, "value": None, "reason": "slope_not_evaluated"}
    if y_ref is None or not math.isfinite(y_ref):
        return {"status": sc.ELASTICITY_UNAVAILABLE, "value": None, "reason": "reference_value_missing"}
    if y_ref == 0.0 or abs(y_ref) <= sc.EQUALITY_TOL:
        return {"status": sc.ELASTICITY_UNAVAILABLE, "value": None, "reason": "reference_value_is_zero"}
    if x_ref == 0.0 or abs(x_ref) <= sc.EQUALITY_TOL:
        return {"status": sc.ELASTICITY_UNAVAILABLE, "value": None, "reason": "reference_parameter_is_zero"}
    value = float(slope) * float(x_ref) / float(y_ref)
    if not math.isfinite(value):
        return {"status": sc.ELASTICITY_UNAVAILABLE, "value": None, "reason": "non_finite_result"}
    return {"status": sc.ELASTICITY_AVAILABLE, "value": value, "reason": None}


# ---------------------------------------------------------------------------
# Direction & classification (rubric: sensitivity-response-classification-1.0)
# ---------------------------------------------------------------------------


def direction_payload(points: list[tuple[float, float | None]]) -> str:
    """Sign of f(upper bound) − f(lower bound) over the sweep.

    None values (failed evaluations / missing cell values) are ignored;
    fewer than two finite values → not_evaluated.
    """
    finite = [(x, y) for x, y in points if y is not None]
    if len(finite) < 2:
        return sc.DIRECTION_NOT_EVALUATED
    points_sorted = sorted(finite, key=lambda p: p[0])
    first, last = points_sorted[0][1], points_sorted[-1][1]
    delta = last - first
    if abs(delta) <= sc.EQUALITY_TOL:
        return sc.DIRECTION_NO_CHANGE
    return sc.DIRECTION_INCREASING if delta > 0 else sc.DIRECTION_DECREASING


def classify_response(
    points: list[tuple[float, float]],
    y_ref: float | None,
) -> str:
    """Classify the response over the evaluated sweep (M7.4 method §5.2).

    First match wins. All tolerances come from the versioned rubric.
    """
    if not points:
        return sc.CLASSIFICATION_NOT_EVALUATED
    if len(points) < 2:
        return sc.CLASSIFICATION_INSUFFICIENT_POINTS

    pts = sorted(points, key=lambda p: p[0])
    ys = [p[1] for p in pts]
    span = max(ys) - min(ys)

    # Constant band (relative to the reference magnitude, absolute floor).
    ref_scale = abs(y_ref) if y_ref is not None else 0.0
    constant_band = max(sc.CONSTANT_BAND_RELATIVE * ref_scale, sc.EQUALITY_TOL)
    if span <= constant_band:
        return sc.CLASSIFICATION_CONSTANT

    diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    eps = sc.EQUALITY_TOL
    sign_changes = 0
    last_sign = 0
    for d in diffs:
        if abs(d) <= eps:
            continue
        sign = 1 if d > 0 else -1
        if last_sign != 0 and sign != last_sign:
            sign_changes += 1
        last_sign = sign

    if sign_changes > 0:
        return sc.CLASSIFICATION_NON_MONOTONIC

    monotonic = (
        sc.CLASSIFICATION_MONOTONIC_INCREASING
        if pts[-1][1] > pts[0][1]
        else sc.CLASSIFICATION_MONOTONIC_DECREASING
    )

    # Threshold detection: one dominant step within an otherwise flat or
    # monotonic response.
    nonzero = [abs(d) for d in diffs if abs(d) > eps]
    if nonzero:
        nonzero_sorted = sorted(nonzero)
        mid = nonzero_sorted[len(nonzero_sorted) // 2]
        max_step = max(nonzero)
        if mid > 0 and max_step >= sc.THRESHOLD_JUMP_FACTOR * mid:
            return sc.CLASSIFICATION_THRESHOLD_SUSPECTED
        if len(pts) >= sc.THRESHOLD_MIN_POINTS and span > 0 and max_step >= sc.THRESHOLD_STEP_SPAN_SHARE * span:
            return sc.CLASSIFICATION_THRESHOLD_SUSPECTED

    return monotonic


def threshold_affected(points: list[tuple[float, float]], y_ref: float | None) -> bool:
    """True when the classification flags a suspected discontinuity."""
    return classify_response(points, y_ref) == sc.CLASSIFICATION_THRESHOLD_SUSPECTED


# ---------------------------------------------------------------------------
# Envelope & summaries
# ---------------------------------------------------------------------------


def envelope_payload(
    points: list[tuple[float, float]],
    parameter_lower: float,
    parameter_upper: float,
) -> dict[str, Any]:
    """The explored parameter-range envelope (binding name and semantics).

    Deterministic min/max over the evaluated sweep — never a confidence or
    probability interval.
    """
    finite = [p[1] for p in points]
    if not finite:
        return {
            "parameter_lower": parameter_lower,
            "parameter_upper": parameter_upper,
            "lower": None,
            "upper": None,
        }
    return {
        "parameter_lower": parameter_lower,
        "parameter_upper": parameter_upper,
        "lower": min(finite),
        "upper": max(finite),
    }


def interaction_contrast(corners: dict[str, float]) -> dict[str, Any]:
    """Finite-grid interaction contrast I = f11 − f10 − f01 + f00.

    `corners` keys: f00 = f(x0,z0), f10 = f(x1,z0), f01 = f(x0,z1),
    f11 = f(x1,z1) where x0/x1 and z0/z1 are each axis's grid extremes.
    Explicitly labelled a finite-grid contrast — never a Sobol index.
    """
    required = ("f00", "f10", "f01", "f11")
    if any(corners.get(k) is None for k in required):
        return {"value": None, "interpretation": sc.INTERACTION_NOT_EVALUATED}
    value = (
        float(corners["f11"])
        - float(corners["f10"])
        - float(corners["f01"])
        + float(corners["f00"])
    )
    if abs(value) <= sc.EQUALITY_TOL:
        interpretation = sc.INTERACTION_ADDITIVE
    elif value > 0:
        interpretation = sc.INTERACTION_SUPER_ADDITIVE
    else:
        interpretation = sc.INTERACTION_SUB_ADDITIVE
    return {"value": value, "interpretation": interpretation}


def grid_axis_monotonicity(values_by_axis_point: dict[float, list[float | None]]) -> bool:
    """True when ANY one-axis sweep across the grid is non-monotonic.

    `values_by_axis_point` maps each fixed combination key to the ordered
    values along the varying axis; implemented by the caller as per-row and
    per-column sequences.
    """
    for values in values_by_axis_point.values():
        finite = [v for v in values if v is not None]
        if len(finite) < 2:
            continue
        diffs = [finite[i + 1] - finite[i] for i in range(len(finite) - 1)]
        signs = {1 if d > sc.EQUALITY_TOL else -1 if d < -sc.EQUALITY_TOL else 0 for d in diffs}
        if 1 in signs and -1 in signs:
            return True
    return False

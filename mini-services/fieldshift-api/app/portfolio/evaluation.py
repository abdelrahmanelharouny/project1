"""Portfolio evaluation layer (P2.F) — post-hoc scoring + comparisons.

The optimizer's steering objective is a solver device (rotation-engine
rule). This module recomputes the REPORTED evidence from the concrete
allocation with plain arithmetic, then builds the two honest comparisons:

- `score_allocation(model, allocations)` — per-criterion values for any
  allocation list (portfolio or the independent per-field baseline mapped
  into the same shape), so both sides of every comparison are scored by the
  SAME code path.
- `independent_field_comparison(model)` — portfolio vs each field optimized
  alone (its own FarmContext allocation), trade-offs per criterion with
  explanation anchored in the binding-constraint report.
- `scenario_comparison(baseline_solution, scenario_solution)` — allocation
  deltas under a stressed scenario, feasibility verdict.

Honesty rules:
- Criteria not evaluable from evidence are reported `not_comparable`, never
  zero-filled into a ranking.
- The weighted objective is a steering device; comparisons are made
  criterion-by-criterion (same units on both sides, never across units).
"""

from __future__ import annotations

from typing import Any

from app.portfolio.optimizer import (
    AREA_SCALE,
    FALLOW_CROP_CODE,
    RESOURCE_UTILIZATION_TARGET,
    PreparedModel,
)

EVALUATION_VERSION = "portfolio-evaluation-1.0.0"


def _cultivated(allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in allocations if a.get("crop_code") != FALLOW_CROP_CODE]


def _fallow_area_ha(allocations: list[dict[str, Any]]) -> float:
    return sum(float(a.get("area_ha") or 0.0) for a in allocations if a.get("crop_code") == FALLOW_CROP_CODE)


def _area_weighted_score(
    model: PreparedModel,
    allocations: list[dict[str, Any]],
    score_of: dict[str, float],
) -> float | None:
    """Area-weighted mean of a per-crop score over cultivated area."""
    num = 0.0
    den = 0.0
    for a in _cultivated(allocations):
        code = a.get("crop_code")
        area = float(a.get("area_ha") or 0.0)
        score = score_of.get(code)
        if score is None or area <= 0:
            continue
        num += score * area
        den += area
    if den <= 0:
        return None
    return num / den


def _max_crop_share(allocations: list[dict[str, Any]], total_area_ha: float) -> float | None:
    cultivated = _cultivated(allocations)
    if total_area_ha <= 0 or not cultivated:
        return None
    by_crop: dict[str, float] = {}
    for a in cultivated:
        by_crop[a["crop_code"]] = by_crop.get(a["crop_code"], 0.0) + float(a.get("area_ha") or 0.0)
    return max(by_crop.values()) / total_area_ha


def _max_family_share(model: PreparedModel, allocations: list[dict[str, Any]], total_area_ha: float) -> float | None:
    cultivated = _cultivated(allocations)
    if total_area_ha <= 0 or not cultivated:
        return None
    by_family: dict[str, float] = {}
    for a in cultivated:
        family = model.family_of(a["crop_code"])
        by_family[family] = by_family.get(family, 0.0) + float(a.get("area_ha") or 0.0)
    return max(by_family.values()) / total_area_ha


def water_use_m3(model: PreparedModel, allocations: list[dict[str, Any]]) -> tuple[float | None, bool]:
    """(estimated water use, lower_bound_only). Demand per allocation row is
    carried from the prepared crops (NIR x 10 m3/ha/mm, or the ETc screening
    fallback — the same coefficients the hard constraint uses)."""
    prepared = {
        (c.field_idx, c.season_idx, c.crop_code): c for c in model.crops
    }
    field_idx = {fid: i for i, fid in enumerate(model.field_ids)}
    season_idx = {s.label: i for i, s in enumerate(model.seasons)}
    used = 0.0
    lower_bound_only = False
    for a in _cultivated(allocations):
        f_idx = field_idx.get(str(a.get("field_id")))
        s_idx = season_idx.get(str(a.get("season_label")))
        crop = prepared.get((f_idx, s_idx, str(a.get("crop_code"))))
        if crop is None:
            continue
        area = float(a.get("area_ha") or 0.0)
        if crop.demand_mm is None:
            lower_bound_only = True
            continue
        used += area * crop.demand_mm * 10.0
    if not _cultivated(allocations):
        return None, lower_bound_only
    return used, lower_bound_only


def score_allocation(
    model: PreparedModel, allocations: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Reported per-criterion evidence for a concrete allocation.

    Every criterion that cannot be evaluated from the evidence reports
    {"value": None, "not_evaluated": reason} — never a zero.
    """
    total_area = sum(float(a.get("area_ha") or 0.0) for a in allocations) or model.total_area_ha
    water_score_of = {
        c.crop_code: c.scores["water_efficiency"]
        for c in model.crops
        if "water_efficiency" in c.scores
    }
    soil_score_of = {
        c.crop_code: c.scores["soil_health"] for c in model.crops if "soil_health" in c.scores
    }
    feasibility_score_of = {
        c.crop_code: c.scores["operational_feasibility"]
        for c in model.crops
        if "operational_feasibility" in c.scores
    }

    out: dict[str, dict[str, Any]] = {}

    water_eff = _area_weighted_score(model, allocations, water_score_of)
    out["water_efficiency"] = (
        {"value": round(water_eff, 4), "unit": "score_0_1",
         "basis": "area-weighted inverse per-ha water demand (NIR, else ETc screening), normalized within each field's candidate pool"}
        if water_eff is not None
        else {"value": None, "not_evaluated": "no candidate carries an evaluable water score"}
    )

    soil_eff = _area_weighted_score(model, allocations, soil_score_of)
    out["soil_health"] = (
        {"value": round(soil_eff, 4), "unit": "score_0_1",
         "basis": "area-weighted rotation-engine soil-health score (legumes, rooting depth, N fixation)"}
        if soil_eff is not None
        else {"value": None, "not_evaluated": "no candidate carries an evaluable soil-health score"}
    )

    feas = _area_weighted_score(model, allocations, feasibility_score_of)
    out["operational_feasibility"] = (
        {"value": round(feas, 4), "unit": "score_0_1",
         "basis": "area-weighted planting-window fit and duration fit"}
        if feas is not None
        else {"value": None, "not_evaluated": "no cultivated area to score"}
    )

    max_crop = _max_crop_share(allocations, total_area)
    out["risk_diversification"] = (
        {"value": round(1.0 - max_crop, 4), "unit": "score_0_1",
         "basis": "1 - maximum single-crop area share across the farm"}
        if max_crop is not None
        else {"value": None, "not_evaluated": "nothing cultivated"}
    )

    max_family = _max_family_share(model, allocations, total_area)
    out["rotation_diversity"] = (
        {"value": round(1.0 - max_family, 4), "unit": "score_0_1",
         "basis": "1 - maximum single-crop-family area share across the farm "
         "(per-field consecutive-season alternation is steering-only; reported value is the concentration measure)"}
        if max_family is not None
        else {"value": None, "not_evaluated": "nothing cultivated"}
    )

    used_m3, lower_bound = water_use_m3(model, allocations)
    alloc_m3 = model.constraints.get("water_allocation_m3")
    if used_m3 is None or alloc_m3 is None:
        out["resource_utilization"] = {
            "value": None,
            "not_evaluated": (
                "no shared water allocation supplied" if alloc_m3 is None
                else "no cultivated area with a water-demand estimate"
            ),
        }
    else:
        target = RESOURCE_UTILIZATION_TARGET * float(alloc_m3)
        value = min(used_m3 / target, 1.0) if target > 0 else 0.0
        entry: dict[str, Any] = {
            "value": round(value, 4),
            "unit": "score_0_1",
            "basis": (
                f"water use {used_m3:.0f} m3 against the utilization ramp target "
                f"{RESOURCE_UTILIZATION_TARGET} x allocation ({target:.0f} m3); allocation is a hard constraint"
            ),
        }
        if lower_bound:
            entry["used_is_lower_bound"] = True
        out["resource_utilization"] = entry

    out["water_use"] = {
        "value": round(used_m3, 1) if used_m3 is not None else None,
        "unit": "m3",
        "basis": "sum(area_ha x demand_mm x 10 m3/ha/mm) over cultivated area"
        + (" (lower bound: some area has no demand estimate)" if lower_bound else ""),
    }
    out["fallow_share"] = {
        "value": round(_fallow_area_ha(allocations) / total_area, 4) if total_area > 0 else None,
        "unit": "fraction",
        "basis": "fallow area / total farm area",
    }
    out["_meta"] = {"version": EVALUATION_VERSION}
    return out


def independent_field_comparison(model: PreparedModel) -> dict[str, Any]:
    """Portfolio vs independent per-field optimization.

    The independent baseline optimizes each field ALONE with its own
    FarmContext allocation (the same RotationProblem objects the portfolio
    model reused), strategy 'balanced'. Its assignment is mapped into the
    portfolio allocation shape and scored by score_allocation — one scoring
    code path for both sides.
    """
    from app.rotation.optimizer import InfeasibleResult, PROFILE_WEIGHTS, optimize_strategy

    independent_allocations: list[dict[str, Any]] = []
    per_field: list[dict[str, Any]] = []
    for field_id, problem in sorted(model.problems.items()):
        result = optimize_strategy(problem, "balanced", dict(PROFILE_WEIGHTS["balanced"]))
        entry: dict[str, Any] = {"field_id": field_id}
        if isinstance(result, InfeasibleResult):
            entry["status"] = result.status
            entry["conflicts"] = result.conflicts
            per_field.append(entry)
            continue
        entry["status"] = "optimal"
        entry["assignment"] = [
            {"season_label": label, "crop_code": crop}
            for label, crop in result.assignment
        ]
        per_field.append(entry)
        season_idx = {s.label: i for i, s in enumerate(model.seasons)}
        for label, crop in result.assignment:
            if crop is None:
                continue
            independent_allocations.append(
                {
                    "field_id": field_id,
                    "season_index": season_idx.get(label, 0),
                    "season_label": label,
                    "crop_code": crop,
                    "area_ha": next(
                        f.area_ha for f in model.fields if str(f.field_id) == field_id
                    ),
                    "family_key": model.family_of(crop) if not model.family_of(crop).startswith("__u__:") else None,
                    "status": "assigned",
                }
            )

    independent_scores = score_allocation(model, independent_allocations)
    return {
        "independent_allocations": independent_allocations,
        "independent_scores": independent_scores,
        "per_field": per_field,
        "version": EVALUATION_VERSION,
    }


def compare_criteria(
    portfolio_scores: dict[str, dict[str, Any]],
    independent_scores: dict[str, dict[str, Any]],
    binding_constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Criterion-by-criterion trade-off report (same unit both sides)."""
    comparisons: list[dict[str, Any]] = []
    binding_names = {b.get("name") for b in binding_constraints}
    for criterion in (
        "water_efficiency",
        "soil_health",
        "rotation_diversity",
        "operational_feasibility",
        "risk_diversification",
        "resource_utilization",
        "water_use",
    ):
        p = portfolio_scores.get(criterion, {})
        i = independent_scores.get(criterion, {})
        pv, iv = p.get("value"), i.get("value")
        if pv is None or iv is None:
            verdict = "not_comparable"
            detail = "at least one side lacks evaluable evidence — no ranking is manufactured"
        else:
            if abs(pv - iv) <= 1e-6:
                verdict = "equal"
                detail = "identical values under the shared scoring path"
            else:
                better_is_higher = criterion != "water_use"
                if (pv > iv) == better_is_higher:
                    verdict = "portfolio"
                    detail = f"portfolio {pv} vs independent {iv}"
                else:
                    verdict = "independent"
                    detail = f"independent {iv} vs portfolio {pv}"
        comparisons.append(
            {
                "criterion": criterion,
                "portfolio_value": pv,
                "independent_value": iv,
                "unit": p.get("unit") or i.get("unit"),
                "verdict": verdict,
                "detail": detail,
                "basis": p.get("basis") or i.get("basis"),
            }
        )
    explanations: list[str] = []
    if "water_allocation" in binding_names:
        explanations.append(
            "The shared farm water allocation is binding: fields cannot all take "
            "their individually-optimal crops, so the portfolio trades water "
            "across fields (this is the mechanism behind water-criterion differences)."
        )
    if "family_share_cap" in binding_names:
        explanations.append(
            "The crop-family diversification cap is binding: concentration that "
            "would maximize a single field's score is limited for farm-level "
            "risk diversification."
        )
    if not explanations:
        explanations.append(
            "No shared constraint is binding — the portfolio outcome coincides "
            "with independent optimization on the binding-free criteria."
        )
    return {
        "comparisons": comparisons,
        "explanations": explanations,
        "note": (
            "Independent baseline: each field optimized alone with its own "
            "allocation (strategy 'balanced'), scored by the same code path "
            "as the portfolio. Comparisons never cross units."
        ),
        "version": EVALUATION_VERSION,
    }


def scenario_comparison(
    baseline: dict[str, Any],
    stressed: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Baseline portfolio vs stressed-scenario portfolio (allocation deltas)."""
    def _key(a: dict[str, Any]) -> tuple[str, int, str]:
        return (str(a.get("field_id")), int(a.get("season_index", 0)), str(a.get("crop_code")))

    baseline_map = {_key(a): float(a.get("area_ha") or 0.0) for a in baseline.get("allocations", [])}
    stressed_map = {_key(a): float(a.get("area_ha") or 0.0) for a in stressed.get("allocations", [])}
    deltas: list[dict[str, Any]] = []
    for key in sorted(set(baseline_map) | set(stressed_map)):
        b = baseline_map.get(key, 0.0)
        s = stressed_map.get(key, 0.0)
        if abs(b - s) > 0.005:
            deltas.append(
                {
                    "field_id": key[0],
                    "season_index": key[1],
                    "crop_code": key[2],
                    "baseline_area_ha": b,
                    "scenario_area_ha": s,
                    "delta_ha": round(s - b, 2),
                }
            )
    status = {
        "baseline": baseline.get("status"),
        "scenario": stressed.get("status"),
    }
    if stressed.get("status") == "infeasible":
        verdict = "infeasible_under_scenario"
        detail = "The stressed scenario admits no allocation; named conflicts are attached to the scenario run."
    elif stressed.get("status") in ("model_invalid", "unknown"):
        verdict = "solver_failure"
        detail = "The scenario solve failed at the solver level; nothing is concluded."
    else:
        verdict = "feasible_with_changes" if deltas else "feasible_unchanged"
        detail = (
            f"{len(deltas)} allocation(s) changed under the scenario."
            if deltas
            else "The baseline allocation remains optimal under the scenario."
        )
    return {
        "verdict": verdict,
        "detail": detail,
        "status": status,
        "allocation_deltas": deltas,
        "scenario": scenario,
        "version": EVALUATION_VERSION,
    }

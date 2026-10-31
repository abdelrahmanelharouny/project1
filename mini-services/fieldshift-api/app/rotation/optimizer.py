"""CP-SAT optimizer adapter (Milestone 5.4, ADR-0015/0016).

The ONLY module that knows OR-Tools. Deterministic: num_search_workers=1 and
a recorded seed — identical inputs yield identical assignments (tested).

Hard constraints are added 1:1 with `constraints.py`, each registered as a
solver ASSUMPTION (fixed true for the solve). If the model is infeasible,
`SufficientAssumptionsForInfeasibility` maps back to the named constraints —
no silent relaxation, explicit conflict identification.

Soft objectives enter the solver through per-criterion, per-crop score tables
(solution-independent) + a family-alternation term. The reported criteria are
ALWAYS recomputed post-hoc by `objectives.evaluate_criteria` — the solver's
internal objective is a steering device, never the reported evidence.

A rotation break (predecessor p at season j, successor s at season i,
min_break_seasons k) is forbidden when the gap i - j <= k; the history's last
crop occupies virtual season -1 (gap i + 1 <= k).
"""

from __future__ import annotations

from typing import Any

from ortools.sat.python import cp_model

from app.knowledge.service import rules_between
from app.rotation.constraints import WATER_ESTIMATE_NOTE
from app.rotation.problem import (
    RotationProblem,
    StrategySolution,
)

MAX_SOLVE_SECONDS = 10.0

PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "water_priority": {
        "water_requirement_mm": 0.45,
        "soil_health_index": 0.10,
        "economic_margin_index": 0.05,
        "crop_family_diversity": 0.10,
        "climate_resilience_index": 0.15,
        "erosion_reduction_index": 0.10,
        "cover_crop_opportunity": 0.05,
    },
    "soil_health_priority": {
        "water_requirement_mm": 0.05,
        "soil_health_index": 0.40,
        "economic_margin_index": 0.05,
        "crop_family_diversity": 0.20,
        "climate_resilience_index": 0.05,
        "erosion_reduction_index": 0.15,
        "cover_crop_opportunity": 0.10,
    },
    "balanced": {
        "water_requirement_mm": 0.20,
        "soil_health_index": 0.20,
        "economic_margin_index": 0.10,
        "crop_family_diversity": 0.20,
        "climate_resilience_index": 0.10,
        "erosion_reduction_index": 0.10,
        "cover_crop_opportunity": 0.10,
    },
    "economic_priority": {
        "water_requirement_mm": 0.05,
        "soil_health_index": 0.05,
        "economic_margin_index": 0.55,
        "crop_family_diversity": 0.15,
        "climate_resilience_index": 0.05,
        "erosion_reduction_index": 0.05,
        "cover_crop_opportunity": 0.10,
    },
}

DEFAULT_PROFILES = tuple(PROFILE_WEIGHTS.keys())

STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "water_priority": "Prioritizes the lowest screened crop water requirement "
    "(FAO-56 single-Kc screening estimate) while keeping agronomic diversity.",
    "soil_health_priority": "Prioritizes legumes, rooting depth, family "
    "alternation and soil cover.",
    "balanced": "Even weighting across all available criteria.",
    "economic_priority": "Prioritizes the farmer-supplied margin index. Without "
    "farmer economics, this profile degrades to the remaining criteria (the "
    "skipped weight is reported, economics is never invented).",
    "baseline": "The current rotation reconstructed from the field's crop "
    "history — evaluated, never modified to look feasible.",
}


class InfeasibleResult:
    """No usable assignment from one profile.

    `status` distinguishes the CP-SAT outcomes that produce no solution
    (deepening F-4, Master solver-status semantics): 'infeasible' means the
    CONSTRAINTS are contradictory (conflict identification applies);
    'model_invalid' means the model itself is malformed (a reporting bug, not
    an agronomic statement); 'unknown' means the solver gave up (e.g. time
    limit) without proving infeasibility. Only 'infeasible' may be reported
    as an infeasible profile — the others are solver failures."""

    def __init__(
        self,
        conflicts: list[dict[str, Any]],
        *,
        notes: list[str] | None = None,
        status: str = "infeasible",
    ) -> None:
        self.status = status
        self.conflicts = conflicts
        self.notes = notes or []


def _norm_min_max(values: dict[str, float], invert: bool) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    span = hi - lo
    out: dict[str, float] = {}
    for k, v in values.items():
        out[k] = 0.5 if span <= 1e-12 else (v - lo) / span
        if invert:
            out[k] = 1.0 - out[k]
    return out


def _per_crop_scores(
    problem: RotationProblem, candidates: list[str]
) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """Solution-independent per-crop scores per criterion (0..1), pooled across
    planning seasons (a crop's water estimate differs per season; the pooled
    min-max uses the per-season assessments of the first season — the same
    basis candidate generation reports). Criteria that cannot be scored from
    evidence are OMITTED (never zero-filled) and the omission reason is
    returned."""
    scores: dict[str, dict[str, float]] = {}
    skipped: dict[str, str] = {}
    first_season = problem.seasons[0].label if problem.seasons else ""

    def _assessment(code: str):
        return problem.candidates.get(first_season, {}).get(code)

    water_raw: dict[str, float] = {}
    for code in candidates:
        a = _assessment(code)
        if a is not None and a.water_requirement_mm is not None:
            water_raw[code] = a.water_requirement_mm

    if water_raw:
        scores["water_requirement_mm"] = _norm_min_max(water_raw, invert=True)
    else:
        skipped["water_requirement_mm"] = (
            "no candidate has an estimable water requirement (missing ET0/Kc evidence)"
        )

    def _sub(crop, code, lo, hi):
        v = crop.numeric_trait(code)
        if v is None:
            return None
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    soil: dict[str, float] = {}
    for code in candidates:
        crop = problem.knowledge.crops[code]
        parts = []
        if crop.is_legume:
            parts.append(1.0)
        if crop.is_cover_crop_capable:
            parts.append(1.0)
        rd = _sub(crop, "root_depth_effective_m", 0.3, 1.8)
        if rd is not None:
            parts.append(rd)
        nf = _sub(crop, "n_fixation_capacity_kg_ha", 0, 200)
        if nf is not None:
            parts.append(nf)
        if parts:
            soil[code] = sum(parts) / len(parts)
    if soil:
        scores["soil_health_index"] = soil
    else:
        skipped["soil_health_index"] = "no soil-health sub-indicators evaluable"

    if problem.farm.margin_index_by_crop:
        margin = {
            c: problem.farm.margin_index_by_crop[c] / 100.0
            for c in candidates
            if c in problem.farm.margin_index_by_crop
        }
        if margin:
            scores["economic_margin_index"] = margin
        else:
            skipped["economic_margin_index"] = (
                "farmer margin indices exist but cover none of the admissible candidates"
            )
    else:
        skipped["economic_margin_index"] = (
            "no farmer-supplied margin data — economics is never invented"
        )

    resilience: dict[str, float] = {}
    for code in candidates:
        a = _assessment(code)
        if a is None:
            continue
        codes = {r["code"] for r in a.reasons}
        if "temperature_within_optimum" in codes:
            resilience[code] = 1.0
        elif any(c.startswith("temperature_") for c in codes):
            resilience[code] = 0.0
    if resilience:
        scores["climate_resilience_index"] = resilience
    else:
        skipped["climate_resilience_index"] = (
            "temperature evidence not evaluable for any candidate"
        )

    erosion: dict[str, float] = {}
    season0 = problem.seasons[0]
    for code in candidates:
        crop = problem.knowledge.crops[code]
        d = crop.numeric_trait("duration_days_total")
        if d is not None:
            erosion[code] = min(1.0, d / season0.length_days)
    if erosion:
        scores["erosion_reduction_index"] = erosion
    else:
        skipped["erosion_reduction_index"] = "crop durations missing for all candidates"

    cover = {
        code: 1.0
        if (
            problem.knowledge.crops[code].is_legume
            or problem.knowledge.crops[code].is_cover_crop_capable
        )
        else 0.0
        for code in candidates
    }
    if any(v > 0 for v in cover.values()):
        scores["cover_crop_opportunity"] = cover
    else:
        skipped["cover_crop_opportunity"] = (
            "no admissible candidate is legume or cover-crop capable"
        )
    return scores, skipped


def optimize_strategy(
    problem: RotationProblem,
    strategy_key: str,
    profile_weights: dict[str, float],
) -> StrategySolution | InfeasibleResult:
    """Optimize one weighted profile. Returns a StrategySolution WITHOUT
    post-hoc criteria (the orchestrator fills those) or an InfeasibleResult."""
    model = cp_model.CpModel()
    seasons = problem.seasons
    knowledge = problem.knowledge

    # ---- variables: only admissible candidates for THAT season (ADR-0016)
    admissible: dict[int, list[str]] = {}
    for i, season in enumerate(seasons):
        season_candidates = problem.candidates.get(season.label, {})
        eligible_now = []
        for code, assessment in season_candidates.items():
            if not assessment.admissible:
                continue
            # with a hard allocation, crops without estimates are held out
            if (
                problem.water_allocation_m3 is not None
                and assessment.water_requirement_mm is None
            ):
                continue
            eligible_now.append(code)
        if not eligible_now:
            return InfeasibleResult(
                conflicts=[{
                    "constraint": "candidate_admissibility",
                    "detail": f"No admissible candidates for season '{season.label}'.",
                }],
                notes=[
                    "Candidate generation excluded every crop for this season "
                    "(unevaluated candidates never enter optimization)."
                ],
            )
        admissible[i] = sorted(eligible_now)

    x: dict[tuple[int, str], Any] = {}
    for i in admissible:
        for code in admissible[i]:
            x[(i, code)] = model.NewBoolVar(f"x_{i}_{code}")
        model.AddExactlyOne(x[(i, code)] for code in admissible[i])

    # ---- hard-constraint registry (assumption pattern, ADR-0015)
    assumption_vars: list[Any] = []
    assumption_labels: dict[int, dict[str, Any]] = {}

    def register(label: dict[str, Any], enforce: Any) -> None:
        a = model.NewBoolVar(f"assume_{len(assumption_vars)}")
        model.Add(enforce).OnlyEnforceIf(a)
        assumption_vars.append(a)
        # SufficientAssumptionsForInfeasibility returns MODEL VARIABLE indices,
        # not positions in our list — key by the variable's own index.
        assumption_labels[a.Index()] = label

    history_codes = [h.get("crop_code") for h in problem.farm.history if h.get("crop_code")]

    # Deepening F-06: the pairwise lookback is derived from the deepest
    # confirmed rule (a rule with min_break_seasons=k binds when i - j <= k,
    # so j must reach back k seasons). The old fixed window of 4 silently
    # under-enforced rules with k >= 5.
    max_break = max(
        (r.min_break_seasons for r in knowledge.rules if r.is_hard_enforceable),
        default=0,
    )

    # confirmed rotation-break rules: planned-planned pairs
    for i in range(len(seasons)):
        for code in admissible[i]:
            for j in range(max(0, i - max_break), i):
                for pred in admissible[j]:
                    rules = rules_between(
                        knowledge, pred, code, problem.farm.country_code,
                        only_enforceable=True,
                    )
                    for rule in rules:
                        if (i - j) <= rule.min_break_seasons:
                            register(
                                {
                                    "constraint": "rotation_break_confirmed_regional",
                                    "rule_code": rule.rule_code,
                                    "detail": f"Confirmed rule '{rule.rule_code}' forbids "
                                    f"'{pred}' (season {seasons[j].label}) followed by "
                                    f"'{code}' (season {seasons[i].label}): gap {i - j} <= "
                                    f"min_break_seasons {rule.min_break_seasons}. "
                                    f"{rule.mechanism}",
                                },
                                x[(j, pred)] + x[(i, code)] <= 1,
                            )
    # history boundary: last history crop occupies virtual season -1
    last_hist = history_codes[-1] if history_codes else None
    if last_hist is not None:
        # binds when (i + 1) <= k, i.e. i <= k - 1
        for i in range(min(len(seasons), max_break)):
            for code in admissible[i]:
                rules = rules_between(
                    knowledge, last_hist, code, problem.farm.country_code,
                    only_enforceable=True,
                )
                for rule in rules:
                    if (i + 1) <= rule.min_break_seasons:
                        register(
                            {
                                "constraint": "rotation_break_confirmed_regional",
                                "rule_code": rule.rule_code,
                                "detail": f"Confirmed rule '{rule.rule_code}' forbids "
                                f"'{code}' in season {seasons[i].label} immediately after "
                                f"history crop '{last_hist}' "
                                f"(min_break_seasons={rule.min_break_seasons}). "
                                f"{rule.mechanism}",
                            },
                            x[(i, code)] == 0,
                        )

    # water allocation (per season, only when the farmer supplied one).
    # CP-SAT needs integer arithmetic: coefficients are m3 x 1000 (L precision).
    # M6A: the demand coefficient uses the NET IRRIGATION REQUIREMENT when it
    # is evaluable for the season's crop, else the ETc screening value — a
    # CONSERVATIVE upper bound (NIR ≤ ETc when the rainfall credit ≥ 0),
    # recorded in the constraint detail. No estimate at all ⇒ the crop was
    # already held out above (never silently skipped).
    area_m2 = problem.farm.area_ha * 10_000.0
    if problem.water_allocation_m3 is not None:
        alloc_scaled = int(round(problem.water_allocation_m3 * 1000))
        for i, season in enumerate(seasons):
            season_terms = []
            demand_basis_notes: list[str] = []
            for code in admissible[i]:
                a = problem.candidates[season.label][code]
                demand_mm = (
                    a.net_irrigation_requirement_mm
                    if a.net_irrigation_requirement_mm is not None
                    else a.water_requirement_mm
                )
                if demand_mm is not None:
                    coeff = int(round(demand_mm / 1000.0 * area_m2 * 1000))
                    season_terms.append(x[(i, code)] * coeff)
                    if a.net_irrigation_requirement_mm is None:
                        demand_basis_notes.append(
                            f"{code}: ETc screening (NIR not evaluable)"
                        )
            if season_terms:
                basis_note = (
                    " demand basis: net irrigation requirement (ETc − Pe; soil-water "
                    "contribution not evaluated at solver level)."
                    if not demand_basis_notes
                    else " demand basis per crop: " + "; ".join(sorted(demand_basis_notes)) + "."
                )
                register(
                    {
                        "constraint": "water_allocation",
                        "detail": f"Season {season.label}: crop water demand within the "
                        f"farmer-supplied allocation "
                        f"({problem.water_allocation_m3:.0f} m3)." + basis_note + " "
                        + WATER_ESTIMATE_NOTE,
                    },
                    sum(season_terms) <= alloc_scaled,
                )

    # ---- soft objective from per-crop, per-season score tables
    candidates_flat = sorted({c for i in admissible for c in admissible[i]})
    score_tables, _skipped_scores = _per_crop_scores(problem, candidates_flat)

    effective_weights = {
        c: w for c, w in profile_weights.items() if c in score_tables and w > 0
    }
    diversity_w = profile_weights.get("crop_family_diversity", 0.0)
    if diversity_w > 0 and len(seasons) >= 2:
        effective_weights["crop_family_diversity"] = diversity_w
    w_total = sum(effective_weights.values())

    objective_terms = []
    if w_total > 0:
        for criterion, w in effective_weights.items():
            weight = w / w_total
            if criterion == "crop_family_diversity":
                # family alternation bonus between consecutive seasons
                for i in range(len(seasons) - 1):
                    for code_a in admissible[i]:
                        for code_b in admissible[i + 1]:
                            fa = knowledge.crops[code_a].family_key or f"__u__:{code_a}"
                            fb = knowledge.crops[code_b].family_key or f"__u__:{code_b}"
                            if fa == fb:
                                continue
                            both = model.NewBoolVar(f"alt_{i}_{code_a}_{code_b}")
                            model.AddBoolAnd([x[(i, code_a)], x[(i + 1, code_b)]]).OnlyEnforceIf(both)
                            model.AddBoolOr([x[(i, code_a)].Not(), x[(i + 1, code_b)].Not(), both])
                            objective_terms.append(
                                both * int(round(weight * 1_000_000))
                            )
                continue
            table = score_tables[criterion]
            for (i, code), var in x.items():
                if code in table:
                    objective_terms.append(var * int(round(table[code] * weight * 1_000_000)))
    else:
        # No criterion evaluable → nothing to optimize; take the first feasible
        # solution and label it explicitly as feasibility-only.
        objective_terms = [0]

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = problem.seed
    solver.parameters.max_time_in_seconds = MAX_SOLVE_SECONDS

    if assumption_vars:
        model.AddAssumptions(assumption_vars)

    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        conflicts: list[dict[str, Any]] = []
        try:
            for idx in solver.SufficientAssumptionsForInfeasibility():
                label = assumption_labels.get(idx)
                if label:
                    conflicts.append(label)
        except Exception:  # noqa: BLE001 — older ortools may lack the API
            pass
        if not conflicts:
            conflicts.append({
                "constraint": "combined_constraints",
                "detail": "No assignment satisfies the admissible-candidate pool together "
                "with the active hard constraints.",
            })
        return InfeasibleResult(conflicts)

    if status == cp_model.MODEL_INVALID:
        return InfeasibleResult(
            conflicts=[{
                "constraint": "solver_model_invalid",
                "detail": "CP-SAT reported MODEL_INVALID — the model is malformed and "
                "nothing can be concluded about the constraints; no solution is "
                "fabricated.",
            }],
            notes=[f"wall time {solver.WallTime():.3f}s"],
            status="model_invalid",
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # UNKNOWN (or any other non-solution status): the solver did not prove
        # infeasibility — reporting it as 'infeasible' would be a false claim.
        return InfeasibleResult(
            conflicts=[{
                "constraint": "solver_no_solution",
                "detail": f"Solver ended with status {solver.StatusName(status)} — no "
                "solution reported and infeasibility NOT proven; nothing is fabricated.",
            }],
            notes=[f"wall time {solver.WallTime():.3f}s"],
            status="unknown",
        )

    assignment: list[tuple[str, str | None]] = []
    for i, season in enumerate(seasons):
        chosen = None
        for code in admissible[i]:
            if solver.Value(x[(i, code)]):
                chosen = code
                break
        assignment.append((season.label, chosen))

    return StrategySolution(
        strategy_key=strategy_key,
        strategy_kind="optimized",
        is_baseline=False,
        profile_weights=dict(profile_weights),
        weights_effective={},
        skipped_weights={},
        assignment=tuple(assignment),
        objective_value=round(solver.ObjectiveValue() / 1_000_000, 6),
        criteria=(),
        constraints_checked=(),
        evidence_coverage=None,
        solver_status=solver.StatusName(status).lower(),
        solver_wall_time_ms=int(solver.WallTime() * 1000),
    )


def build_baseline_solution(
    problem: RotationProblem, strategy_key: str = "baseline"
) -> StrategySolution:
    return StrategySolution(
        strategy_key=strategy_key,
        strategy_kind="baseline",
        is_baseline=True,
        profile_weights={},
        weights_effective={},
        skipped_weights={},
        assignment=tuple(problem.baseline_assignment),
        objective_value=None,
        criteria=(),
        constraints_checked=(),
        evidence_coverage=None,
        solver_status="not_attempted",
    )

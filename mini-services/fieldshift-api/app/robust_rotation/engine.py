"""Robust shared-plan optimizer (Milestone 7.5, reuses ADR-0015/0016/0017).

ONE CP-SAT model decides ONE shared crop-rotation plan for MULTIPLE M7.3
scenario executions. This is NOT "optimize every scenario separately and
relabel": the assignment variables are shared, the hard constraints that are
genuinely evaluable in every scenario are enforced once on the shared
variables, and the steering objective is the WORST CASE (maximin) across
per-scenario weighted score sums:

    maximize W  subject to  W <= objective_s(x)  for every scenario s.

Determinism: num_search_workers=1, recorded seed, sorted iteration order —
identical inputs yield identical assignments (tested).

Honesty rules carried over from M5 (ADR-0015):

- Hard constraints are registered as solver ASSUMPTIONS so infeasibility maps
  back to named constraints — never a silent relaxation.
- The reported per-scenario criteria are recomputed POST-HOC by the existing
  M5 evaluation code (`objectives.evaluate_criteria`); the solver's internal
  maximin value is a steering device, never the reported evidence.
- A scenario whose steering criteria are entirely unevaluable contributes NO
  maximin constraint (it would silently zero the worst case); the omission is
  recorded per scenario.
- Farmer water allocations are rejected upstream (scenario ET0 is never
  recalculated by M7.3), so no water-allocation constraint exists here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from app.knowledge.service import rules_between
from app.rotation.optimizer import MAX_SOLVE_SECONDS, InfeasibleResult, _per_crop_scores
from app.rotation.problem import RotationProblem


@dataclass
class SharedPlanResult:
    """The optimized shared plan + per-scenario steering diagnostics."""

    assignment: tuple[tuple[str, str | None], ...]
    solver_status: str
    solver_wall_time_ms: int
    maximin_objective: float | None  # solver-internal steering value (scaled 1e-6)
    objective_bound: float | None  # proven bound on the steering objective
    per_scenario_steering: dict[str, dict[str, Any]] = field(default_factory=dict)


def intersection_candidates(
    problems: dict[str, RotationProblem],
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Crops admissible in EVERY scenario, per season.

    Returns (intersection per season label, exclusion records). A crop that
    is admissible in some scenario but not all is excluded from the shared
    pool and the exclusion is recorded WITH the failing scenario(s) and
    reason — cross-scenario restrictions are first-class results."""
    season_labels = [s.label for s in next(iter(problems.values())).seasons]
    intersection: dict[str, list[str]] = {}
    records: list[dict[str, Any]] = []
    for label in season_labels:
        pool: set[str] | None = None
        for sid in sorted(problems):
            assessments = problems[sid].candidates.get(label, {})
            admissible = {c for c, a in assessments.items() if a.admissible}
            pool = admissible if pool is None else (pool & admissible)
        all_codes = sorted(
            {c for sid in sorted(problems) for c in problems[sid].candidates.get(label, {})}
        )
        intersection[label] = sorted(pool or set())
        for code in all_codes:
            if code in (pool or set()):
                continue
            failing = []
            for sid in sorted(problems):
                a = problems[sid].candidates.get(label, {}).get(code)
                if a is not None and not a.admissible:
                    failing.append(
                        {
                            "scenario_id": sid,
                            "status": a.status,
                            "reason": next(
                                (
                                    r.get("message")
                                    for r in a.reasons
                                    if r.get("severity") == "hard"
                                ),
                                "not admissible in this scenario",
                            ),
                        }
                    )
            if failing:
                records.append(
                    {
                        "season_label": label,
                        "crop_code": code,
                        "excluded_by_scenarios": failing,
                    }
                )
    return intersection, records


def optimize_shared_plan(
    problems: dict[str, RotationProblem],
    intersection: dict[str, list[str]],
    strategy_key: str,
    profile_weights: dict[str, float],
) -> SharedPlanResult | InfeasibleResult:
    """Optimize ONE shared plan across all scenarios (maximin steering)."""
    model = cp_model.CpModel()
    first = next(iter(sorted(problems)))
    seasons = problems[first].seasons
    knowledge = problems[first].knowledge

    # ---- variables: only crops admissible in EVERY scenario (the pool)
    admissible: dict[int, list[str]] = {}
    for i, season in enumerate(seasons):
        eligible = intersection.get(season.label, [])
        if not eligible:
            return InfeasibleResult(
                conflicts=[
                    {
                        "constraint": "candidate_admissibility",
                        "detail": (
                            f"No crop is admissible in EVERY selected scenario for "
                            f"season '{season.label}' — the cross-scenario pool is "
                            "empty; nothing is fabricated."
                        ),
                    }
                ],
                notes=[
                    "The shared plan can only draw on candidates admissible in "
                    "all selected scenarios (cross-scenario restrictions reported)."
                ],
            )
        admissible[i] = list(eligible)

    x: dict[tuple[int, str], Any] = {}
    for i in admissible:
        for code in admissible[i]:
            x[(i, code)] = model.NewBoolVar(f"x_{i}_{code}")
        model.AddExactlyOne(x[(i, code)] for code in admissible[i])

    # ---- hard-constraint registry (assumption pattern, ADR-0015).
    # Rotation-break rules depend only on the knowledge pack and the field's
    # crop history — both identical across scenarios of the same field — so
    # they are registered ONCE on the shared variables.
    assumption_vars: list[Any] = []
    assumption_labels: dict[int, dict[str, Any]] = {}

    def register(label: dict[str, Any], enforce: Any) -> None:
        a = model.NewBoolVar(f"assume_{len(assumption_vars)}")
        model.Add(enforce).OnlyEnforceIf(a)
        assumption_vars.append(a)
        assumption_labels[a.Index()] = label

    history_codes = [
        h.get("crop_code") for h in problems[first].farm.history if h.get("crop_code")
    ]
    max_break = max(
        (r.min_break_seasons for r in knowledge.rules if r.is_hard_enforceable),
        default=0,
    )

    country = problems[first].farm.country_code
    for i in range(len(seasons)):
        for code in admissible[i]:
            for j in range(max(0, i - max_break), i):
                for pred in admissible[j]:
                    rules = rules_between(
                        knowledge, pred, code, country, only_enforceable=True
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

    last_hist = history_codes[-1] if history_codes else None
    if last_hist is not None:
        for i in range(min(len(seasons), max_break)):
            for code in admissible[i]:
                rules = rules_between(
                    knowledge, last_hist, code, country, only_enforceable=True
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

    # ---- per-scenario steering: W <= objective_s(x), maximize W
    worst = model.NewIntVar(0, 1_000_000_000, "worst_case")
    steering: dict[str, dict[str, Any]] = {}
    scenario_ids = sorted(problems)
    for sid in scenario_ids:
        problem = problems[sid]
        candidates_flat = sorted({c for i in admissible for c in admissible[i]})
        score_tables, skipped_scores = _per_crop_scores(problem, candidates_flat)

        effective_weights = {
            c: w for c, w in profile_weights.items() if c in score_tables and w > 0
        }
        diversity_w = profile_weights.get("crop_family_diversity", 0.0)
        if diversity_w > 0 and len(seasons) >= 2:
            effective_weights["crop_family_diversity"] = diversity_w
        w_total = sum(effective_weights.values())

        entry: dict[str, Any] = {
            "score_tables_used": sorted(score_tables.keys()),
            "skipped_scores": dict(skipped_scores),
            "steering_active": w_total > 0,
        }
        if w_total <= 0:
            entry["reason"] = (
                "no steering criterion is evaluable in this scenario's "
                "environment — the scenario contributes no maximin constraint "
                "(a zero floor would silently dominate the worst case)"
            )
            steering[sid] = entry
            continue

        terms: list[Any] = []
        for criterion, w in effective_weights.items():
            weight = w / w_total
            if criterion == "crop_family_diversity":
                for i in range(len(seasons) - 1):
                    for code_a in admissible[i]:
                        for code_b in admissible[i + 1]:
                            fa = knowledge.crops[code_a].family_key or f"__u__:{code_a}"
                            fb = knowledge.crops[code_b].family_key or f"__u__:{code_b}"
                            if fa == fb:
                                continue
                            both = model.NewBoolVar(f"alt_{i}_{code_a}_{code_b}")
                            model.AddBoolAnd([x[(i, code_a)], x[(i + 1, code_b)]]).OnlyEnforceIf(both)
                            model.AddBoolOr(
                                [x[(i, code_a)].Not(), x[(i + 1, code_b)].Not(), both]
                            )
                            terms.append(both * int(round(weight * 1_000_000)))
                continue
            table = score_tables[criterion]
            for (i, code), var in x.items():
                if code in table:
                    terms.append(var * int(round(table[code] * weight * 1_000_000)))
        model.Add(worst <= sum(terms))
        steering[sid] = entry

    if not any(e.get("steering_active") for e in steering.values()):
        # No scenario offers steering evidence: feasibility-only solve.
        model.Add(worst == 0)

    model.Maximize(worst)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = problems[first].seed
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
            conflicts.append(
                {
                    "constraint": "combined_constraints",
                    "detail": "No assignment satisfies the cross-scenario candidate "
                    "pool together with the active hard constraints.",
                }
            )
        return InfeasibleResult(conflicts)

    if status == cp_model.MODEL_INVALID:
        return InfeasibleResult(
            conflicts=[
                {
                    "constraint": "solver_model_invalid",
                    "detail": "CP-SAT reported MODEL_INVALID — nothing can be "
                    "concluded about the constraints; no solution is fabricated.",
                }
            ],
            notes=["shared-plan solve"],
            status="model_invalid",
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return InfeasibleResult(
            conflicts=[
                {
                    "constraint": "solver_no_solution",
                    "detail": f"Solver ended with status {solver.StatusName(status)} — "
                    "no solution reported and infeasibility NOT proven.",
                }
            ],
            notes=["shared-plan solve"],
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

    maximin = solver.Value(worst) / 1_000_000
    bound = solver.BestObjectiveBound() / 1_000_000

    return SharedPlanResult(
        assignment=tuple(assignment),
        solver_status=solver.StatusName(status).lower(),
        solver_wall_time_ms=int(solver.WallTime() * 1000),
        maximin_objective=round(maximin, 6),
        objective_bound=round(bound, 6),
        per_scenario_steering=steering,
    )

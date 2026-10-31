"""Hard constraints — declared once, checked WITHOUT the solver (M5.4).

The CP-SAT model mirrors these constraints 1:1; `check_assignment` is the
solver-independent validator used by tests, the baseline report, and the
explanation layer. A solution labelled feasible MUST satisfy every check here
(Master: no hard constraint is ever silently relaxed).
"""

from __future__ import annotations

from typing import Any

from app.rotation.problem import (
    ConstraintCheck,
    FarmContext,
    KnowledgeBaseData,
    RotationProblem,
    SeasonSpec,
)
from app.knowledge.service import rules_between

# Water estimate provenance marker (ADR-0017)
WATER_ESTIMATE_NOTE = (
    "Screening estimate: FAO-56 single Kc x monthly ET0, sowing at season start "
    "(assumptions recorded per candidate; superseded by the M7 daily water balance)."
)


def season_crop(problem: RotationProblem, season_label: str) -> str | None:
    for label, crop in problem.baseline_assignment:
        if label == season_label:
            return crop
    return None


def check_one_crop_per_season(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> ConstraintCheck:
    missing = [s.label for s in problem.seasons if s.label not in assignment]
    if missing:
        return ConstraintCheck(
            constraint_code="one_crop_per_season",
            description="Every planning season carries exactly one main crop.",
            status="violated",
            detail=f"Seasons without an assignment: {', '.join(missing)}",
        )
    return ConstraintCheck(
        constraint_code="one_crop_per_season",
        description="Every planning season carries exactly one main crop.",
        status="satisfied",
    )


def check_candidate_admissibility(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> list[ConstraintCheck]:
    """Crops assigned to a season must be admissible (eligible/conditionally
    eligible) for THAT season AND, when a hard water allocation is active, must
    have an estimable water requirement (ADR-0016)."""
    checks: list[ConstraintCheck] = []
    for season in problem.seasons:
        crop_code = assignment.get(season.label)
        if crop_code is None:
            continue
        assessment = problem.candidates.get(season.label, {}).get(crop_code)
        if assessment is None:
            checks.append(
                ConstraintCheck(
                    constraint_code="candidate_admissibility",
                    description="Assigned crops are evaluated candidates for their season.",
                    status="violated",
                    detail=f"{season.label}: '{crop_code}' is not an evaluated candidate "
                    "(unevaluated candidates never enter optimization).",
                )
            )
            continue
        if not assessment.admissible:
            checks.append(
                ConstraintCheck(
                    constraint_code="candidate_admissibility",
                    description="Assigned crops are evaluated candidates for their season.",
                    status="violated",
                    detail=f"{season.label}: '{crop_code}' status is {assessment.status}.",
                )
            )
        elif (
            problem.water_allocation_m3 is not None
            and assessment.water_requirement_mm is None
        ):
            checks.append(
                ConstraintCheck(
                    constraint_code="candidate_admissibility",
                    description="With a hard water allocation, assigned crops need an "
                    "estimable water requirement.",
                    status="violated",
                    detail=f"{season.label}: '{crop_code}' has no water estimate, so the "
                    "allocation cannot be verified — excluded from allocation-"
                    "constrained optimization (never silently skipped).",
                )
            )
    if checks:
        return checks
    return [
        ConstraintCheck(
            constraint_code="candidate_admissibility",
            description="Assigned crops are evaluated candidates for their season (and "
            "water-estimable when an allocation constraint is active).",
            status="satisfied",
        )
    ]


def check_rotation_breaks(
    problem: RotationProblem, assignment: dict[str, str | None], *, seasons_back: int | None = None
) -> list[ConstraintCheck]:
    """Confirmed-regional rotation-break rules over planned seasons and the
    history → first-season boundary. Reference rules are NEVER enforced here
    (they appear in explanations and candidate conditionality).

    Gap semantics: with the predecessor in season j and the successor in
    season i, `gap = i - j - 1` (seasons strictly between). The history's last
    crop occupies virtual season -1. A rule binds when gap < min_break_seasons."""
    checks: list[ConstraintCheck] = []
    knowledge = problem.knowledge
    country = problem.farm.country_code
    history_codes = [h.get("crop_code") for h in problem.farm.history if h.get("crop_code")]
    if seasons_back is None:
        # Deepening F-06: the lookback is DERIVED from the deepest confirmed
        # rule — the old fixed cap (3) silently under-enforced rules with
        # min_break_seasons >= 4. A rule with min_break_seasons=k binds when
        # gap < k and gap = back - 1, so exactly `max_break` seasons back are
        # needed (predecessor at idx - back, back in 1..max_break).
        seasons_back = max(
            (r.min_break_seasons for r in knowledge.rules if r.is_hard_enforceable),
            default=0,
        )

    for idx, season in enumerate(problem.seasons):
        crop_code = assignment.get(season.label)
        if crop_code is None:
            continue
        predecessors: list[tuple[str, int]] = []
        for back in range(1, min(seasons_back, idx) + 1):
            prev = assignment.get(problem.seasons[idx - back].label)
            if prev:
                predecessors.append((prev, back - 1))
        if seasons_back > idx and history_codes:
            # the last history crop occupies the virtual season immediately
            # before the first planned season (deeper history is not modelled)
            predecessors.append((history_codes[-1], idx))
        for pred, gap in predecessors:
            for rule in rules_between(knowledge, pred, crop_code, country, only_enforceable=True):
                if gap < rule.min_break_seasons:
                    checks.append(
                        ConstraintCheck(
                            constraint_code="rotation_break_confirmed_regional",
                            description="Confirmed regional rotation-break rules are honoured.",
                            status="violated",
                            detail=f"{season.label}: confirmed rule '{rule.rule_code}' "
                            f"requires >= {rule.min_break_seasons} season(s) between "
                            f"'{pred}' and '{crop_code}' (gap {gap}): {rule.mechanism}",
                            rule_codes=(rule.rule_code,),
                            source_refs=[{
                                "type": "rotation_rule",
                                "rule_code": rule.rule_code,
                                "citation_text": rule.citation_text,
                                "validation_status": rule.validation_status,
                            }],
                        )
                    )
    if not checks:
        confirmed = knowledge.confirmed_rule_count
        detail = (
            f"No confirmed-regional rotation-break rules are active for this region "
            f"({confirmed} confirmed rule(s) loaded overall)."
            if confirmed == 0
            else "All confirmed-regional rotation-break rules satisfied."
        )
        checks.append(
            ConstraintCheck(
                constraint_code="rotation_break_confirmed_regional",
                description="Confirmed regional rotation-break rules are honoured "
                "(reference rules are advisory and never enforced).",
                status="satisfied",
                detail=detail,
            )
        )
    return checks


def check_water_allocation(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> ConstraintCheck:
    """PER-SEASON allocation: each planning season's crop must fit within the
    farmer-supplied seasonal allocation (constraint_code
    water_allocation_m3_per_season)."""
    allocation = problem.water_allocation_m3
    if allocation is None:
        return ConstraintCheck(
            constraint_code="water_allocation",
            description="Seasonal water allocation constraint (per season).",
            status="not_applicable",
            detail="No water allocation supplied by the farmer — constraint not applied "
            "(and never invented).",
        )
    area_m2 = problem.farm.area_ha * 10_000.0
    worst_ratio: float | None = None
    worst_detail = ""
    unevaluable: list[str] = []
    for season in problem.seasons:
        crop_code = assignment.get(season.label)
        if crop_code is None:
            continue
        assessment = problem.candidates.get(season.label, {}).get(crop_code)
        if assessment is None or assessment.water_requirement_mm is None:
            unevaluable.append(f"{season.label}:{crop_code}")
            continue
        need_m3 = assessment.water_requirement_mm / 1000.0 * area_m2
        ratio = need_m3 / allocation
        if worst_ratio is None or ratio > worst_ratio:
            worst_ratio = ratio
            worst_detail = (
                f"{season.label}: '{crop_code}' needs {need_m3:.0f} m3 vs "
                f"allocation {allocation:.0f} m3 ({ratio * 100:.0f}%)."
            )
    if unevaluable:
        return ConstraintCheck(
            constraint_code="water_allocation",
            description="Seasonal water allocation constraint (per season).",
            status="violated",
            detail="Crops without an estimable water requirement under an active hard "
            f"allocation: {', '.join(sorted(set(unevaluable)))} (they must not enter "
            "allocation-constrained optimization).",
        )
    status = "satisfied" if (worst_ratio or 0) <= 1.0 + 1e-9 else "violated"
    return ConstraintCheck(
        constraint_code="water_allocation",
        description="Seasonal water allocation constraint (each season's estimated crop "
        "water requirement within the farmer-supplied allocation).",
        status=status,
        detail=(worst_detail or "no assigned crops") + " " + WATER_ESTIMATE_NOTE,
    )


def check_all(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> list[ConstraintCheck]:
    checks = [check_one_crop_per_season(problem, assignment)]
    checks.extend(check_candidate_admissibility(problem, assignment))
    checks.extend(check_rotation_breaks(problem, assignment))
    checks.append(check_water_allocation(problem, assignment))
    return checks


def all_satisfied(checks: list[ConstraintCheck]) -> bool:
    return all(
        c.status in ("satisfied", "not_applicable") for c in checks
    )

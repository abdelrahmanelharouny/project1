"""Rotation recommendations.

Reads the rotation section of the evidence pack (latest succeeded rotation run
+ its recommended strategy). Planting recommendations cite the run and
strategy ids; unevaluated candidate water requirements are surfaced honestly
(candidate exclusions are computed at run time by the engine, so the persisted
run exposes the unevaluated-dimension list, not fabricated exclusion counts).
"""

from __future__ import annotations

import logging
from typing import Any

from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("fieldshift.recommendations.rotation")

# At or above this many crop-season pairs with unevaluated water requirements,
# the water-evidence gap gets its own advisory.
WATER_UNEVALUATED_ADVISORY_COUNT = 3


@registry.generator("rotation")
def rotation_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    if ctx.section("rotation") is not None:
        return []
    return [
        Recommendation(
            domain="rotation",
            severity=Severity.INFO,
            title="No rotation run yet — run the rotation engine to unlock planting advice",
            summary=(
                "This field has no succeeded rotation run, so there is no "
                "optimizer-backed crop plan to recommend."
            ),
            rationale=(
                "The intelligence layer reads the latest succeeded rotation run "
                "(strategies, assignment, explanations). Without one, crop "
                "choice stays unevaluated by the platform."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: rotation",
            )],
            actions=[
                "Create a rotation run for this field "
                "(POST /api/v1/fields/{id}/rotation-runs).",
            ],
            confidence=0.95,
            confidence_basis="deterministic: absence of a succeeded rotation_run row for the field",
        )
    ]


@registry.generator("rotation")
def planting_recommendations(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """One RECOMMENDED planting rec per season of the recommended strategy."""
    section = ctx.section("rotation") or {}
    strategy = section.get("strategy") or {}
    if strategy.get("is_baseline"):
        return []  # baseline is shown for comparison, never recommended
    if strategy.get("kind") != "optimized":
        return []
    if section.get("solver_status") not in ("optimal", "feasible"):
        return []
    run_id = (section.get("source") or {}).get("id")
    strategy_id = strategy.get("id")
    out: list[Recommendation] = []
    for entry in section.get("assignment") or []:
        season, crop = entry.get("season"), entry.get("crop")
        if not season or not crop:
            continue
        out.append(
            Recommendation(
                domain="rotation",
                severity=Severity.RECOMMENDED,
                title=f"Plant {crop} in {season} (optimizer strategy '{strategy.get('key')}')",
                summary=(
                    f"The rotation engine's recommended strategy assigns {crop} to "
                    f"{season} — review the plan and lock the sowing window."
                ),
                rationale=(
                    f"Rotation run {run_id}, strategy {strategy_id} "
                    f"('{strategy.get('key')}') solved to {section.get('solver_status')} and is on the "
                    "Pareto front of the generated strategy set; its assignment "
                    f"puts {crop} in {season}. Hard constraints (admissible "
                    "candidates, confirmed rotation rules, water allocation when "
                    "supplied) were enforced by the engine."
                ),
                evidence=[
                    evidence_item(
                        type="rotation_run", id=run_id, label="rotation",
                        detail=f"assignment[{season}] = {crop}",
                    ),
                    evidence_item(
                        type="rotation_strategy", id=strategy_id, label="rotation",
                        detail=(
                            f"strategy '{strategy.get('key')}' kind={strategy.get('kind')} "
                            f"solver_status={section.get('solver_status')}"
                        ),
                    ),
                ],
                actions=[
                    f"Confirm the {crop} sowing window for {season}.",
                    "Check seed/planting-resource availability before committing.",
                ],
                confidence=0.85,
                confidence_basis=(
                    "deterministic: CP-SAT strategy on the Pareto front with "
                    "solver status optimal/feasible"
                ),
            )
        )
    return out


@registry.generator("rotation")
def water_evidence_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("rotation") or {}
    count = section.get("unevaluated_crop_seasons") or 0
    if count < WATER_UNEVALUATED_ADVISORY_COUNT:
        return []
    run_id = (section.get("source") or {}).get("id")
    examples = section.get("unevaluated_examples") or []
    example_labels = ", ".join(
        f"{e.get('crop')} ({e.get('season')})" for e in examples[:3] if e.get("crop")
    )
    has_water_dimension = any(
        "water_requirement" in (e.get("unevaluated_dimensions") or [])
        for e in examples
    )
    reason = (
        "the water requirement could not be evaluated for them (missing ET0 or "
        "Kc evidence)"
        if has_water_dimension
        else "some evaluation dimensions had no evidence"
    )
    return [
        Recommendation(
            domain="rotation",
            severity=Severity.ADVISORY,
            title=(
                f"{count} crop-season candidate(s) not fully evaluated — "
                "water evidence missing"
                if has_water_dimension
                else f"{count} crop-season candidate(s) not fully evaluated"
            ),
            summary=(
                "Several knowledge-base crops could not be fully screened for "
                "this field — the optimizer's candidate pool is narrower than "
                "the knowledge base."
            ),
            rationale=(
                f"Rotation run {run_id} reports {count} crop-season pair(s) with "
                f"unevaluated dimensions ({reason}); examples: {example_labels or 'n/a'}. "
                "Candidates with unevaluated dimensions are not excluded — but "
                "their criteria stay unevaluable, which can hide better options."
            ),
            evidence=[evidence_item(
                type="rotation_run", id=run_id, label="rotation",
                detail=(
                    f"unevaluated_crop_seasons = {count}; "
                    f"examples: {example_labels or 'n/a'}"
                ),
            )],
            actions=[
                "Run a feature run covering the planning seasons (adds climate evidence).",
                "Re-run the rotation to widen the evaluable candidate pool.",
            ],
            confidence=0.75,
            confidence_basis=(
                "deterministic: rotation-run not_evaluated ledger lists crop-season "
                "pairs with unevaluated dimensions"
            ),
        )
    ]

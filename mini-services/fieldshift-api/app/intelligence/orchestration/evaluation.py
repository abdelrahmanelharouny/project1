"""Offline, deterministic AI Core evaluation helpers; never calls a provider."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from app.intelligence.orchestration.contracts import IntentPlan
from app.intelligence.orchestration.planning import create_plan


@dataclass(frozen=True)
class PlanEvaluation:
    case_id: str
    passed: bool
    expected_intent: str
    actual_intent: str
    expected_tool: bool
    actual_tool: bool
    expected_availability: str
    actual_availability: str
    clarification_matches: bool


def evaluate_plan_case(
    *,
    case_id: str,
    question: str,
    has_field: bool,
    expected_intent: str,
    expected_tool: bool,
    expected_availability: str,
    expected_clarification: bool = False,
) -> PlanEvaluation:
    plan: IntentPlan = create_plan(question, has_field=has_field)
    actual_tool = bool(plan.required_tools)
    clarification_matches = plan.clarification_needed == expected_clarification
    passed = (
        plan.intent.value == expected_intent
        and actual_tool == expected_tool
        and plan.availability == expected_availability
        and clarification_matches
    )
    return PlanEvaluation(
        case_id=case_id,
        passed=passed,
        expected_intent=expected_intent,
        actual_intent=plan.intent.value,
        expected_tool=expected_tool,
        actual_tool=actual_tool,
        expected_availability=expected_availability,
        actual_availability=plan.availability,
        clarification_matches=clarification_matches,
    )


def summarize_latency_ms(samples: Iterable[int]) -> dict[str, int | float | None]:
    """Return nearest-rank p50/p95/p99 and mean from safe numeric samples."""
    values = sorted(max(0, int(sample)) for sample in samples)
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "p99": None}

    def percentile(q: float) -> int:
        return values[max(0, math.ceil(q * len(values)) - 1)]

    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 2),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def summarize_outcomes(statuses: Iterable[str]) -> dict[str, int | float]:
    """Report clearly defined full-answer, answer-returned and failure rates."""
    counts = {
        status: 0
        for status in ("answered", "partial", "clarification_required", "unavailable", "failed")
    }
    other = 0
    total = 0
    for status in statuses:
        total += 1
        if status in counts:
            counts[status] += 1
        else:
            other += 1
    denominator = total or 1
    return {
        "count": total,
        **counts,
        "other": other,
        "answer_returned_rate": round((counts["answered"] + counts["partial"]) / denominator, 4) if total else 0.0,
        "fully_answered_rate": round(counts["answered"] / denominator, 4) if total else 0.0,
        "failure_rate": round(counts["failed"] / denominator, 4) if total else 0.0,
    }


def estimate_provider_cost(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    input_usd_per_million: float | None,
    output_usd_per_million: float | None,
) -> float | None:
    """Estimate cost only when both token usage and caller-supplied pricing exist."""
    if None in (input_tokens, output_tokens, input_usd_per_million, output_usd_per_million):
        return None
    if input_tokens < 0 or output_tokens < 0 or input_usd_per_million < 0 or output_usd_per_million < 0:
        raise ValueError("token counts and pricing must be non-negative")
    return round(
        (input_tokens * input_usd_per_million + output_tokens * output_usd_per_million)
        / 1_000_000,
        8,
    )

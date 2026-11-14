"""Deterministic offline evaluation tests; no external model or DB required."""
from __future__ import annotations

import json
from pathlib import Path

from app.intelligence.orchestration.evaluation import (
    estimate_provider_cost,
    evaluate_plan_case,
    summarize_latency_ms,
    summarize_outcomes,
)


def test_checked_in_intent_benchmark_cases():
    cases_path = Path(__file__).parents[1] / "evaluation" / "ai_core_cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    results = [evaluate_plan_case(**case) for case in cases]
    assert len(results) >= 8
    assert all(result.passed for result in results), [r for r in results if not r.passed]


def test_latency_percentiles_are_bounded_and_empty_safe():
    summary = summarize_latency_ms([100, 30, 50, 80, 10])
    assert summary == {"count": 5, "mean": 54.0, "p50": 50, "p95": 100, "p99": 100}
    assert summarize_latency_ms([])["p95"] is None


def test_outcome_summary_separates_partial_answer_from_full_success():
    summary = summarize_outcomes([
        "answered", "partial", "unavailable", "failed", "clarification_required"
    ])
    assert summary["answer_returned_rate"] == 0.4
    assert summary["fully_answered_rate"] == 0.2
    assert summary["failure_rate"] == 0.2


def test_cost_is_not_invented_without_usage_or_price():
    assert estimate_provider_cost(
        input_tokens=None,
        output_tokens=None,
        input_usd_per_million=1.0,
        output_usd_per_million=2.0,
    ) is None
    assert estimate_provider_cost(
        input_tokens=1000,
        output_tokens=500,
        input_usd_per_million=1.0,
        output_usd_per_million=2.0,
    ) == 0.002

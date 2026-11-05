"""Contracts for decision comparisons (Milestone 7.6).

A decision comparison is ONE immutable, checksummed document that unifies
M7.3 scenario executions, M7.4 sensitivity analyses and M7.5 robust rotation
runs into a traceable decision view for one field.

Scientific discipline (docs/m7/m7_6/M7_6_DECISION_INTELLIGENCE.md):

- No composite scores, no unsupported rankings, no probabilities, no yield
  predictions, no universal recommendations — ever.
- Rankings of changes are only computed WITHIN the same unit (a mm can be
  ranked against a mm; a degC is never ranked against a mm).
- Every section item carries its source references (execution run id +
  output checksum, analysis id, robust run id) and method versions.
- Missing and unavailable evidence is a first-class section, never a footnote.
"""

from __future__ import annotations

from typing import Any

DECISION_ENGINE_VERSION = "decision-comparison-engine-1.0.0"
DECISION_METHOD_VERSION = "decision-comparison-1.0"

DOC_STATUS_QUEUED = "queued"
DOC_STATUS_RUNNING = "running"
DOC_STATUS_SUCCEEDED = "succeeded"
DOC_STATUS_COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
DOC_STATUS_FAILED = "failed"
RESULT_DOC_STATUSES = (DOC_STATUS_SUCCEEDED, DOC_STATUS_COMPLETED_WITH_LIMITATIONS)
DOC_STATUSES = (
    DOC_STATUS_QUEUED,
    DOC_STATUS_RUNNING,
    DOC_STATUS_SUCCEEDED,
    DOC_STATUS_COMPLETED_WITH_LIMITATIONS,
    DOC_STATUS_FAILED,
)
IMMUTABLE_DOC_STATUSES = RESULT_DOC_STATUSES

# Bounds (validated; generation reads aggregates only — no engine re-runs).
MAX_EXECUTION_RUNS = 8
MAX_ROBUST_RUNS = 3
MAX_SENSITIVITY_ANALYSES = 8
MAX_SCENARIO_PAIRS = 6
MAX_FINDINGS = 40

FINDING_KINDS = (
    "largest_scenario_change",
    "scenario_pair_delta",
    "sensitivity_response",
    "plan_feasibility",
    "cross_scenario_exclusion",
    "tradeoff_note",
    "missing_evidence",
)


def document_fingerprint_payload(
    *,
    field_id: str,
    title: str,
    execution_run_ids: list[str],
    robust_run_ids: list[str],
    sensitivity_analysis_ids: list[str],
    generator_version: str,
    method_version: str,
) -> dict[str, Any]:
    return {
        "kind": "decision_comparison",
        "field_id": field_id,
        "title": title,
        "execution_run_ids": sorted(execution_run_ids),
        "robust_run_ids": sorted(robust_run_ids),
        "sensitivity_analysis_ids": sorted(sensitivity_analysis_ids),
        "generator_version": generator_version,
        "method_version": method_version,
    }

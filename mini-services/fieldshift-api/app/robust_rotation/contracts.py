"""Contracts and constants for robust multi-scenario rotation (Milestone 7.5).

A robust evaluation evaluates ONE shared crop-rotation plan across MULTIPLE
compatible M7.3 scenario executions. It is a DERIVED ANALYTICAL ARTIFACT: it
never mutates observations, feature runs, Field States, scenario definitions
or M7.3 execution results.

Scientific scope (docs/m7/m7_5/M7_5_ROBUST_METHOD.md):

- The shared plan is optimized ONCE against the union of hard constraints that
  are genuinely evaluable in every selected scenario (the cross-scenario
  admissible candidate pool), with a worst-case (maximin) steering objective.
- Per-scenario results are recomputed POST-HOC by the existing M5 evaluation
  code — the solver's internal objective is a steering device, never the
  reported evidence.
- The reported worst-case objective is the minimum over scenarios of the
  per-scenario weighted normalized objective. It is NOT a confidence interval
  and NOT a probability statement.
- Scenario ET0 is never recalculated by M7.3, so scenario water estimates are
  structurally unavailable: robust runs reject farmer water allocations
  instead of silently dropping the constraint.
- Minimax regret (optional) compares the shared plan against per-scenario
  solo optima on the same normalization basis. It is a deterministic
  objective-gap measure, NOT a probability-weighted expected regret.
"""

from __future__ import annotations

from typing import Any

ROBUST_ENGINE_VERSION = "robust-rotation-engine-1.0.0"
ROBUST_METHOD_VERSION = "robust-worst-case-1.0"
ROBUST_CONFIG_SCHEMA_VERSION = "robust-rotation-1.0"

# Bound expensive operations (documented caps; validated before any solve).
MAX_SCENARIO_SET_SIZE = 5
MAX_ROBUST_PROFILES = 5  # including 'custom'
MAX_SOLO_SOLVES = 25  # regret anchors: scenarios x profiles

SET_STATUS_ACTIVE = "active"
SET_STATUSES = (SET_STATUS_ACTIVE,)

RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
RUN_STATUS_FAILED = "failed"
RESULT_RUN_STATUSES = (RUN_STATUS_SUCCEEDED, RUN_STATUS_COMPLETED_WITH_LIMITATIONS)
RUN_STATUSES = (
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_COMPLETED_WITH_LIMITATIONS,
    RUN_STATUS_FAILED,
)
IMMUTABLE_RUN_STATUSES = RESULT_RUN_STATUSES

SOLVER_STATUS_OPTIMAL = "optimal"
SOLVER_STATUS_FEASIBLE = "feasible"
SOLVER_STATUS_INFEASIBLE = "infeasible"
SOLVER_STATUS_UNKNOWN = "unknown"
SOLVER_STATUS_MODEL_INVALID = "model_invalid"
SOLVER_STATUS_NOT_ATTEMPTED = "not_attempted"
SOLVER_STATUSES = (
    SOLVER_STATUS_OPTIMAL,
    SOLVER_STATUS_FEASIBLE,
    SOLVER_STATUS_INFEASIBLE,
    SOLVER_STATUS_UNKNOWN,
    SOLVER_STATUS_MODEL_INVALID,
    SOLVER_STATUS_NOT_ATTEMPTED,
)

STRATEGY_KIND_OPTIMIZED = "optimized"
STRATEGY_KIND_BASELINE = "baseline"
STRATEGY_KINDS = (STRATEGY_KIND_OPTIMIZED, STRATEGY_KIND_BASELINE)

# Robust feasibility verdicts (per shared plan, across selected scenarios).
ROBUST_FEASIBLE = "robust_feasible"
ROBUST_INFEASIBLE = "robust_infeasible"
ROBUST_NOT_EVALUABLE = "not_evaluable"
ROBUST_FEASIBILITY_STATES = (ROBUST_FEASIBLE, ROBUST_INFEASIBLE, ROBUST_NOT_EVALUABLE)

# How a scenario's derived feature value is used for climate evidence.
VALUE_SOURCE_RECALCULATED = "scenario_recalculated"
VALUE_SOURCE_UNAFFECTED_BASELINE = "not_affected_baseline"

WATER_ALLOCATION_UNSUPPORTED_CODE = "WATER_ALLOCATION_UNSUPPORTED"
WATER_ALLOCATION_UNSUPPORTED_REASON = (
    "Scenario water feasibility is structurally unavailable: M7.3 never "
    "recalculates reference ET0, so crop water requirements cannot be "
    "estimated under scenario climate. A farmer water allocation would make "
    "the constraint unevaluated for every scenario — and unevaluated "
    "constraints are never treated as satisfied. Omit water_allocation_m3 for "
    "robust runs; per-scenario water criteria are reported as not evaluable."
)


def member_document(run: Any) -> dict[str, Any]:
    """BY-VALUE pin of one scenario-set member (an M7.3 execution run).

    The document copies every integrity-relevant field so later changes on
    the source rows are detectable by re-verification; nothing is re-resolved
    at evaluation time."""
    return {
        "execution_run_id": str(run.id),
        "scenario_id": str(run.scenario_id),
        "scenario_version": int(run.scenario_version),
        "run_status": run.run_status,
        "output_checksum": run.output_checksum,
        "parent_field_state_id": str(run.parent_field_state_id),
        "parent_snapshot_checksum": run.parent_snapshot_checksum,
        "scenario_configuration_checksum": run.scenario_configuration_checksum,
        "input_fingerprint": run.input_fingerprint,
        "transformation_engine_version": run.transformation_engine_version,
        "feature_engine_version": run.feature_engine_version,
        "feature_catalog_version": run.feature_catalog_version,
    }


def set_checksum_payload(*, field_id: str, label: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "scenario_set",
        "schema_version": ROBUST_CONFIG_SCHEMA_VERSION,
        "field_id": field_id,
        "label": label,
        "members": sorted(members, key=lambda m: m["execution_run_id"]),
    }


def run_fingerprint_payload(
    *,
    scenario_set_id: str,
    scenario_set_checksum: str,
    seasons: list[dict[str, Any]],
    strategy_profiles: list[str],
    custom_weights: dict[str, float] | None,
    regret_analysis: bool,
    member_pins: list[dict[str, Any]],
    engine_version: str,
    method_version: str,
) -> dict[str, Any]:
    return {
        "kind": "robust_rotation_run",
        "schema_version": ROBUST_CONFIG_SCHEMA_VERSION,
        "scenario_set_id": scenario_set_id,
        "scenario_set_checksum": scenario_set_checksum,
        "seasons": seasons,
        "strategy_profiles": list(strategy_profiles),
        "custom_weights": dict(custom_weights or {}),
        "regret_analysis": bool(regret_analysis),
        "member_pins": sorted(member_pins, key=lambda m: m["execution_run_id"]),
        "engine_version": engine_version,
        "method_version": method_version,
    }


def strategy_checksum_payload(
    *,
    run_fingerprint: str,
    strategy_key: str,
    strategy_kind: str,
    assignment: list[tuple[str, str | None]],
    worst_case_objective: float | None,
    worst_case_regret: float | None,
    robust_feasibility: str,
    per_scenario: list[dict[str, Any]],
    engine_version: str,
) -> dict[str, Any]:
    return {
        "kind": "robust_strategy",
        "run_fingerprint": run_fingerprint,
        "strategy_key": strategy_key,
        "strategy_kind": strategy_kind,
        "assignment": [[lbl, cc] for lbl, cc in assignment],
        "worst_case_objective": worst_case_objective,
        "worst_case_regret": worst_case_regret,
        "robust_feasibility": robust_feasibility,
        "per_scenario": per_scenario,
        "engine_version": engine_version,
    }

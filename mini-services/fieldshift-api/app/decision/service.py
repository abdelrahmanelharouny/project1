"""Decision comparison generation (Milestone 7.6).

Unifies immutable artifacts — M7.3 scenario executions, M7.4 sensitivity
analyses, M7.5 robust rotation runs — into ONE traceable, checksummed
decision document per field. Generation READS aggregates only: no engine is
re-run, no calculation is duplicated (executions were computed once by M7.3;
sensitivities by M7.4; robust evaluations by M7.5 — this module only
assembles, ranks-within-unit and explains).

Determinism: every ranking is a documented key sort (magnitude desc, then
identifiers) — identical inputs yield an identical document and checksum.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.field_state.manifest import sha256_of_document
from app.decision import contracts as dc

logger = logging.getLogger("fieldshift.decision")

RESULT_RUN_STATUSES = ("succeeded", "completed_with_limitations")
RESULT_ANALYSIS_STATUSES = ("succeeded", "completed_with_limitations")


# ---------------------------------------------------------------------------
# Resolution of the comparison scope
# ---------------------------------------------------------------------------


def _resolve_scope(
    db: Session,
    field: dbm.Field,
    payload: dict[str, Any],
) -> tuple[list[dbm.ScenarioExecutionRun], list[dbm.RobustRotationRun], list[dbm.SensitivityAnalysis], list[str]]:
    """Resolve + validate the pinned artifact scope (all tenant-scoped)."""
    findings: list[str] = []

    execution_ids = payload.get("execution_run_ids") or []
    robust_ids = payload.get("robust_run_ids") or []
    analysis_ids = payload.get("sensitivity_analysis_ids") or []
    if not isinstance(execution_ids, list) or not isinstance(robust_ids, list) or not isinstance(analysis_ids, list):
        raise ValidationFailed(
            "execution_run_ids, robust_run_ids and sensitivity_analysis_ids must be lists.",
            details=[{"field": "scope"}],
        )
    if len(execution_ids) > dc.MAX_EXECUTION_RUNS:
        findings.append(
            f"execution runs capped at {dc.MAX_EXECUTION_RUNS}; the newest {dc.MAX_EXECUTION_RUNS} are used"
        )
    if len(robust_ids) > dc.MAX_ROBUST_RUNS:
        findings.append(f"robust runs capped at {dc.MAX_ROBUST_RUNS}")
    if len(analysis_ids) > dc.MAX_SENSITIVITY_ANALYSES:
        findings.append(f"sensitivity analyses capped at {dc.MAX_SENSITIVITY_ANALYSES}")

    executions: list[dbm.ScenarioExecutionRun] = []
    for raw in execution_ids[: dc.MAX_EXECUTION_RUNS]:
        run = db.get(dbm.ScenarioExecutionRun, uuid_mod.UUID(str(raw)))
        if run is None or str(run.field_id) != str(field.id):
            raise ValidationFailed(
                f"Execution run '{raw}' not found for this field.",
                details=[{"field": "execution_run_ids", "reason": str(raw)}],
            )
        if run.run_status not in RESULT_RUN_STATUSES:
            findings.append(f"execution {str(run.id)[:8]} has status '{run.run_status}' and is skipped")
            continue
        executions.append(run)

    robust_runs: list[dbm.RobustRotationRun] = []
    for raw in robust_ids[: dc.MAX_ROBUST_RUNS]:
        row = db.get(dbm.RobustRotationRun, uuid_mod.UUID(str(raw)))
        if row is None or str(row.field_id) != str(field.id):
            raise ValidationFailed(
                f"Robust run '{raw}' not found for this field.",
                details=[{"field": "robust_run_ids", "reason": str(raw)}],
            )
        if row.run_status not in RESULT_RUN_STATUSES:
            findings.append(f"robust run {str(row.id)[:8]} has status '{row.run_status}' and is skipped")
            continue
        robust_runs.append(row)

    analyses: list[dbm.SensitivityAnalysis] = []
    for raw in analysis_ids[: dc.MAX_SENSITIVITY_ANALYSES]:
        row = db.get(dbm.SensitivityAnalysis, uuid_mod.UUID(str(raw)))
        if row is None or str(row.field_id) != str(field.id):
            raise ValidationFailed(
                f"Sensitivity analysis '{raw}' not found for this field.",
                details=[{"field": "sensitivity_analysis_ids", "reason": str(raw)}],
            )
        if row.analysis_status not in RESULT_ANALYSIS_STATUSES:
            findings.append(f"sensitivity analysis {str(row.id)[:8]} has status '{row.analysis_status}' and is skipped")
            continue
        analyses.append(row)

    return executions, robust_runs, analyses, findings


def _auto_scope(
    db: Session, field: dbm.Field
) -> tuple[list[dbm.ScenarioExecutionRun], list[dbm.RobustRotationRun], list[dbm.SensitivityAnalysis], list[str]]:
    """No explicit scope: newest result-bearing artifacts of this field."""
    findings: list[str] = ["scope not provided — the newest result-bearing artifacts of this field were selected"]
    executions = db.scalars(
        select(dbm.ScenarioExecutionRun)
        .where(
            dbm.ScenarioExecutionRun.field_id == field.id,
            dbm.ScenarioExecutionRun.run_status.in_(RESULT_RUN_STATUSES),
        )
        .order_by(dbm.ScenarioExecutionRun.completed_at.desc().nullslast())
        .limit(dc.MAX_EXECUTION_RUNS)
    ).all()
    robust_runs = db.scalars(
        select(dbm.RobustRotationRun)
        .where(
            dbm.RobustRotationRun.field_id == field.id,
            dbm.RobustRotationRun.run_status.in_(RESULT_RUN_STATUSES),
        )
        .order_by(dbm.RobustRotationRun.completed_at.desc().nullslast())
        .limit(dc.MAX_ROBUST_RUNS)
    ).all()
    analyses = db.scalars(
        select(dbm.SensitivityAnalysis)
        .where(
            dbm.SensitivityAnalysis.field_id == field.id,
            dbm.SensitivityAnalysis.analysis_status.in_(RESULT_ANALYSIS_STATUSES),
        )
        .order_by(dbm.SensitivityAnalysis.completed_at.desc().nullslast())
        .limit(dc.MAX_SENSITIVITY_ANALYSES)
    ).all()
    return list(executions), list(robust_runs), list(analyses), findings


# ---------------------------------------------------------------------------
# Section builders (pure assembly over stored rows)
# ---------------------------------------------------------------------------


def _scenario_label(db: Session, run: dbm.ScenarioExecutionRun) -> str:
    scenario = db.get(dbm.Scenario, run.scenario_id)
    return scenario.name if scenario else str(run.id)[:8]


def _pct(baseline: float | None, value: float | None) -> float | None:
    if baseline in (None, 0.0) or value is None:
        return None
    return round((value - baseline) / abs(baseline) * 100.0, 2)


def _baseline_vs_scenario_section(
    db: Session, executions: list[dbm.ScenarioExecutionRun]
) -> dict[str, Any]:
    per_run: list[dict[str, Any]] = []
    ranked_changes: list[dict[str, Any]] = []
    for run in executions:
        rows = db.scalars(
            select(dbm.ScenarioDerivedFeature).where(
                dbm.ScenarioDerivedFeature.execution_run_id == run.id
            )
        ).all()
        compact = []
        for r in rows:
            if r.aggregation_level not in ("monthly", "seasonal"):
                continue  # daily rows are excluded from the document (bounded)
            item = {
                "feature_code": r.feature_code,
                "unit": r.unit,
                "aggregation_level": r.aggregation_level,
                "period_label": r.period_label,
                "baseline_value": r.baseline_value,
                "scenario_value": r.scenario_value,
                "difference_value": r.difference_value,
                "difference_percent": r.difference_percent,
                "evidence_status": r.evidence_status,
            }
            compact.append(item)
            if (
                r.evidence_status == "scenario_recalculated"
                and r.difference_percent is not None
            ):
                ranked_changes.append(
                    {
                        "execution_run_id": str(run.id),
                        "scenario": _scenario_label(db, run),
                        **item,
                        "abs_percent": abs(r.difference_percent),
                    }
                )
        recalculated = [r for r in rows if r.evidence_status == "scenario_recalculated"]
        changed = [r for r in recalculated if r.difference_value not in (None, 0.0)]
        compact.sort(
            key=lambda x: (
                -(abs(x["difference_percent"]) if x["difference_percent"] is not None else 0.0),
                x["feature_code"],
                x["period_label"],
            )
        )
        rows_included = len(compact)
        compact = compact[:200]
        per_run.append(
            {
                "execution_run_id": str(run.id),
                "scenario": _scenario_label(db, run),
                "output_checksum": run.output_checksum,
                "scenario_version": run.scenario_version,
                "summary": {
                    "recalculated_comparisons": len(recalculated),
                    "changed_values": len(changed),
                    "not_affected_features": sum(
                        1 for r in rows if r.evidence_status == "not_affected"
                    ),
                    "not_evaluated_features": sum(
                        1 for r in rows if r.evidence_status == "not_evaluated"
                    ),
                },
                "rows": compact,
                "rows_included": rows_included,
                "rows_note": (
                    "Only monthly and seasonal rows are listed, capped at 200 "
                    "ordered by absolute percent difference; daily aggregates stay "
                    "in the execution run itself."
                )
                if rows_included > 200
                else "Only monthly and seasonal rows are listed; daily aggregates stay in the execution run itself.",
            }
        )
    ranked_changes.sort(key=lambda x: (-x["abs_percent"], x["feature_code"], x["period_label"], x["execution_run_id"]))
    return {
        "per_execution": per_run,
        "largest_changes": ranked_changes[:20],
        "ranking_note": (
            "Ranked by absolute percent difference WITHIN each feature row (the "
            "percentage is per-row); different units are never compared directly."
        ),
    }


def _scenario_pairs_section(
    db: Session, executions: list[dbm.ScenarioExecutionRun]
) -> dict[str, Any]:
    """Scenario-to-scenario feature deltas (both recalculated on the same
    feature code + period). Deterministic pairs: executions in scope order
    (newest first), bounded count."""
    if len(executions) < 2:
        return {"pairs": [], "note": "Fewer than two executions in scope — no scenario-to-scenario deltas."}
    by_run: dict[str, dict[tuple[str, str], dbm.ScenarioDerivedFeature]] = {}
    for run in executions:
        rows = db.scalars(
            select(dbm.ScenarioDerivedFeature).where(
                dbm.ScenarioDerivedFeature.execution_run_id == run.id,
                dbm.ScenarioDerivedFeature.evidence_status == "scenario_recalculated",
            )
        ).all()
        by_run[str(run.id)] = {
            (r.feature_code, r.period_label): r for r in rows
        }
    pairs: list[dict[str, Any]] = []
    for i in range(len(executions)):
        for j in range(i + 1, len(executions)):
            if len(pairs) >= dc.MAX_SCENARIO_PAIRS:
                break
            a, b = executions[i], executions[j]
            a_map, b_map = by_run[str(a.id)], by_run[str(b.id)]
            shared = sorted(set(a_map) & set(b_map))
            deltas: list[dict[str, Any]] = []
            for key in shared:
                ra, rb = a_map[key], b_map[key]
                if ra.unit != rb.unit:
                    continue  # units must match to subtract
                if ra.scenario_value is None or rb.scenario_value is None:
                    continue
                delta = round(rb.scenario_value - ra.scenario_value, 4)
                base = ra.scenario_value
                rel = None if base in (None, 0.0) else round(delta / abs(base) * 100.0, 2)
                deltas.append(
                    {
                        "feature_code": key[0],
                        "period_label": key[1],
                        "unit": ra.unit,
                        "scenario_a": _scenario_label(db, a),
                        "scenario_b": _scenario_label(db, b),
                        "value_a": ra.scenario_value,
                        "value_b": rb.scenario_value,
                        "delta_b_minus_a": delta,
                        "delta_percent": rel,
                        "abs_percent": abs(rel) if rel is not None else 0.0,
                    }
                )
            deltas.sort(key=lambda x: (-x["abs_percent"], x["feature_code"], x["period_label"]))
            pairs.append(
                {
                    "execution_run_a": str(a.id),
                    "execution_run_b": str(b.id),
                    "scenario_a": _scenario_label(db, a),
                    "scenario_b": _scenario_label(db, b),
                    "shared_recalculated_rows": len(shared),
                    "top_deltas": deltas[:15],
                }
            )
    return {
        "pairs": pairs,
        "note": (
            "Deltas compare each scenario's OWN recalculated values (both sides "
            "are transformed hypothetical outputs — neither is observed weather)."
        ),
    }


def _sensitivity_section(
    db: Session, analyses: list[dbm.SensitivityAnalysis]
) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for a in analyses:
        responses = db.scalars(
            select(dbm.SensitivityOatResponse).where(
                dbm.SensitivityOatResponse.analysis_id == a.id
            )
        ).all()
        # top response per (parameter, unit-group of feature): max |slope|
        best: dict[tuple[str, str], dict[str, Any]] = {}
        classification_counts: dict[str, int] = {}
        for r in responses:
            classification_counts[r.response_classification] = (
                classification_counts.get(r.response_classification, 0) + 1
            )
            if r.slope is None:
                continue
            key = (r.parameter_code, r.slope_units)
            cur = best.get(key)
            if cur is None or abs(r.slope) > abs(cur["slope"]):
                best[key] = {
                    "parameter_code": r.parameter_code,
                    "feature_code": r.feature_code,
                    "feature_unit": r.unit,
                    "aggregation_level": r.aggregation_level,
                    "period_label": r.period_label,
                    "slope": r.slope,
                    "slope_units": r.slope_units,
                    "direction": r.direction,
                    "response_classification": r.response_classification,
                    "n_evaluated_points": r.n_evaluated_points,
                }
        uncertainty = db.scalars(
            select(dbm.SensitivityUncertaintyItem).where(
                dbm.SensitivityUncertaintyItem.analysis_id == a.id
            )
        ).all()
        status_counts: dict[str, int] = {}
        for u in uncertainty:
            status_counts[u.quantification_status] = status_counts.get(u.quantification_status, 0) + 1
        out.append(
            {
                "analysis_id": str(a.id),
                "source_execution_run_id": str(a.source_execution_run_id),
                "analysis_status": a.analysis_status,
                "analysis_method_version": a.analysis_method_version,
                "reference_parameter_values": a.reference_parameter_values,
                "reference_reproduced": (a.reference_reproduction or {}).get("reproduced"),
                "top_responses_by_parameter_and_unit": sorted(
                    best.values(), key=lambda x: (x["parameter_code"], x["feature_code"])
                ),
                "classification_counts": dict(sorted(classification_counts.items())),
                "uncertainty_registry_status_counts": dict(sorted(status_counts.items())),
                "interpretation_note": (
                    "Slopes are deterministic OAT derivatives with explicit units — "
                    "values with different units are never ranked against each other. "
                    "The explored parameter-range envelope is NOT a confidence "
                    "interval."
                ),
            }
        )
    return {"analyses": out}


def _rotation_section(
    db: Session, robust_runs: list[dbm.RobustRotationRun]
) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for run in robust_runs:
        strategies = db.scalars(
            select(dbm.RobustRotationStrategy)
            .where(dbm.RobustRotationStrategy.run_id == run.id)
            .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
        ).all()
        evals = db.scalars(
            select(dbm.RobustScenarioEvaluation).where(
                dbm.RobustScenarioEvaluation.run_id == run.id
            )
        ).all()
        evals_by_strategy: dict[str, list[dbm.RobustScenarioEvaluation]] = {}
        for e in evals:
            evals_by_strategy.setdefault(str(e.strategy_id), []).append(e)

        plans = []
        for s in strategies:
            scenario_rows = []
            for e in evals_by_strategy.get(str(s.id), []):
                scenario_rows.append(
                    {
                        "scenario_id": str(e.scenario_id),
                        "execution_run_id": str(e.execution_run_id),
                        "weighted_objective": e.weighted_objective,
                        "objective_evaluable": e.objective_evaluable,
                        "on_scenario_pareto_front": e.on_scenario_pareto_front,
                        "regret_vs_solo": e.regret_vs_solo,
                        "inadmissible_crops": [
                            {
                                "season_label": a["season_label"],
                                "crop_code": a["crop_code"],
                                "reason": a.get("hard_reason") or a.get("status"),
                            }
                            for a in (e.crop_admissibility or [])
                            if not a.get("admissible", True)
                        ],
                        "violated_constraints": [
                            {
                                "constraint_code": c["constraint_code"],
                                "detail": c.get("detail"),
                            }
                            for c in (e.constraint_checks or [])
                            if c.get("status") == "violated"
                        ],
                    }
                )
            plans.append(
                {
                    "strategy_key": s.strategy_key,
                    "strategy_kind": s.strategy_kind,
                    "is_baseline": s.is_baseline,
                    "assignment": s.assignment,
                    "worst_case_objective": s.worst_case_objective,
                    "worst_case_regret": s.worst_case_regret,
                    "robust_feasibility": s.robust_feasibility,
                    "solver_status": s.solver_status,
                    "per_scenario": scenario_rows,
                }
            )
        out.append(
            {
                "robust_run_id": str(run.id),
                "run_status": run.run_status,
                "solver_status": run.solver_status,
                "robust_method_version": run.robust_method_version,
                "scenario_set_id": str(run.scenario_set_id),
                "seasons": run.seasons,
                "member_count": run.member_count,
                "plans": plans,
                "not_evaluated": run.not_evaluated,
            }
        )
    return {"runs": out}


def _tradeoff_section(
    db: Session, robust_runs: list[dbm.RobustRotationRun]
) -> dict[str, Any]:
    """Plan × scenario × criterion raw values (units + directions preserved).
    One robust run (the first with evaluations) keeps the document bounded."""
    for run in robust_runs:
        strategies = db.scalars(
            select(dbm.RobustRotationStrategy)
            .where(dbm.RobustRotationStrategy.run_id == run.id)
            .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
        ).all()
        evals = db.scalars(
            select(dbm.RobustScenarioEvaluation).where(
                dbm.RobustScenarioEvaluation.run_id == run.id
            )
        ).all()
        if not evals:
            continue
        name_by_id = {str(s.id): s.strategy_key for s in strategies}
        matrix: list[dict[str, Any]] = []
        for e in evals:
            for c in e.criteria or []:
                matrix.append(
                    {
                        "plan": name_by_id.get(str(e.strategy_id), str(e.strategy_id)[:8]),
                        "scenario_id": str(e.scenario_id),
                        "criterion_code": c["criterion_code"],
                        "raw_value": c.get("raw_value"),
                        "unit": c.get("unit"),
                        "direction": c.get("direction"),
                        "evaluable": c.get("evaluable", False),
                        "missing_evidence": c.get("missing_evidence", []),
                    }
                )
        return {
            "robust_run_id": str(run.id),
            "matrix": matrix,
            "note": (
                "Trade-offs are shown as RAW criterion values with units and "
                "directions — no composite score, no single ranking across "
                "criteria with different units."
            ),
        }
    return {"robust_run_id": None, "matrix": [], "note": "No robust run with evaluations in scope."}


def _missing_evidence_section(
    db: Session,
    field: dbm.Field,
    executions: list[dbm.ScenarioExecutionRun],
    robust_runs: list[dbm.RobustRotationRun],
    analyses: list[dbm.SensitivityAnalysis],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for run in executions:
        reasons = run.not_evaluated_reasons or {}
        for code, reason in sorted(reasons.items()) if isinstance(reasons, dict) else []:
            items.append(
                {
                    "kind": "execution_not_evaluated",
                    "source": f"scenario-execution:{run.id}",
                    "code": code,
                    "detail": reason,
                }
            )
    for a in analyses:
        not_analysed = a.not_analysed_features or {}
        for code, reason in sorted(not_analysed.items()) if isinstance(not_analysed, dict) else []:
            items.append(
                {
                    "kind": "sensitivity_not_analysed",
                    "source": f"sensitivity-analysis:{a.id}",
                    "code": code,
                    "detail": reason,
                }
            )
    for run in robust_runs:
        for group, entries in sorted((run.not_evaluated or {}).items()):
            for key, reason in sorted((entries or {}).items()):
                items.append(
                    {
                        "kind": "robust_not_evaluated",
                        "source": f"robust-run:{run.id}",
                        "code": f"{group}/{key}",
                        "detail": reason,
                    }
                )
    items.append(
        {
            "kind": "structural_unavailability",
            "source": "platform",
            "code": "scenario_et0_and_water",
            "detail": (
                "Reference ET0 is never recalculated under scenarios, so scenario "
                "water requirements and water-constrained robust feasibility are "
                "structurally unavailable — not merely missing data."
            ),
        }
    )
    forecast_scenarios = db.scalar(
        select(dbm.Scenario.id)
        .where(
            dbm.Scenario.field_id == field.id,
            dbm.Scenario.scenario_type.in_(("climate_projection", "weather_forecast")),
        )
        .limit(1)
    )
    if forecast_scenarios is None:
        items.append(
            {
                "kind": "no_forecast_sources",
                "source": "platform",
                "code": "climate_projections",
                "detail": (
                    "No climate projection or forecast scenario exists on this field. "
                    "M7.8 (projections/forecasts) remains blocked until a real, "
                    "validated provider is connected — none is fabricated."
                ),
            }
        )
    return {"items": items, "count": len(items)}


def _findings_section(
    db: Session,
    executions: list[dbm.ScenarioExecutionRun],
    robust_runs: list[dbm.RobustRotationRun],
    analyses: list[dbm.SensitivityAnalysis],
    baseline_section: dict[str, Any],
    missing: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for item in baseline_section.get("largest_changes", [])[:10]:
        findings.append(
            {
                "kind": "largest_scenario_change",
                "text": (
                    f"Scenario '{item['scenario']}' changes {item['feature_code']} by "
                    f"{item['difference_percent']}% ({item['baseline_value']} → "
                    f"{item['scenario_value']} {item['unit']}, {item['period_label']})."
                ),
                "evidence": [
                    {
                        "type": "scenario_execution",
                        "execution_run_id": item["execution_run_id"],
                        "output_checksum": None,
                    }
                ],
            }
        )

    for run in robust_runs:
        strategies = db.scalars(
            select(dbm.RobustRotationStrategy)
            .where(dbm.RobustRotationStrategy.run_id == run.id)
            .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
        ).all()
        evals = db.scalars(
            select(dbm.RobustScenarioEvaluation).where(
                dbm.RobustScenarioEvaluation.run_id == run.id
            )
        ).all()
        for s in strategies:
            reasons: list[str] = []
            if s.is_baseline and s.robust_feasibility == "robust_infeasible":
                for e in evals:
                    if str(e.strategy_id) != str(s.id):
                        continue
                    for a in e.crop_admissibility or []:
                        if not a.get("admissible", True):
                            reasons.append(
                                f"{a['crop_code']} in {a['season_label']}: "
                                f"{a.get('hard_reason') or a.get('status')}"
                                f" (execution {str(e.execution_run_id)[:8]})"
                            )
                    for c in e.constraint_checks or []:
                        if c.get("status") == "violated":
                            reasons.append(
                                f"constraint {c['constraint_code']} violated"
                                f" (execution {str(e.execution_run_id)[:8]})"
                            )
            if s.is_baseline and s.robust_feasibility == "robust_infeasible":
                findings.append(
                    {
                        "kind": "plan_feasibility",
                        "text": (
                            "The CURRENT rotation is not robust across the selected "
                            "scenarios: " + "; ".join(reasons[:5])
                        ),
                        "evidence": [
                            {
                                "type": "robust_run",
                                "robust_run_id": str(run.id),
                                "strategy_key": s.strategy_key,
                            }
                        ],
                    }
                )
            elif s.robust_feasibility == "robust_feasible" and not s.is_baseline:
                findings.append(
                    {
                        "kind": "plan_feasibility",
                        "text": (
                            f"Shared plan '{s.strategy_key}' is feasible in every "
                            "selected scenario for the evaluated constraints "
                            f"(worst-case objective {s.worst_case_objective})."
                        ),
                        "evidence": [
                            {
                                "type": "robust_run",
                                "robust_run_id": str(run.id),
                                "strategy_key": s.strategy_key,
                            }
                        ],
                    }
                )

    for a in analyses:
        responses = db.scalars(
            select(dbm.SensitivityOatResponse).where(
                dbm.SensitivityOatResponse.analysis_id == a.id
            )
        ).all()
        slopes = [r for r in responses if r.slope is not None]
        slopes.sort(key=lambda r: (-abs(r.slope), r.parameter_code, r.feature_code))
        for r in slopes[:5]:
            findings.append(
                {
                    "kind": "sensitivity_response",
                    "text": (
                        f"{r.feature_code} responds to {r.parameter_code} with slope "
                        f"{r.slope} {r.slope_units} ({r.response_classification}, "
                        f"{r.n_evaluated_points} evaluated points)."
                    ),
                    "evidence": [
                        {
                            "type": "sensitivity_analysis",
                            "analysis_id": str(a.id),
                            "source_execution_run_id": str(a.source_execution_run_id),
                        }
                    ],
                }
            )

    for item in missing.get("items", [])[:10]:
        findings.append(
            {
                "kind": "missing_evidence",
                "text": f"{item['code']}: {item['detail']}",
                "evidence": [{"type": "source", "source": item["source"]}],
            }
        )

    findings = findings[: dc.MAX_FINDINGS]
    return findings


# ---------------------------------------------------------------------------
# Document assembly + persistence
# ---------------------------------------------------------------------------


def generate_decision_comparison(
    db: Session,
    field: dbm.Field,
    *,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.DecisionComparison:
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.DecisionComparison).where(
                dbm.DecisionComparison.idempotency_key == idempotency_key,
                dbm.DecisionComparison.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    has_explicit_scope = bool(
        payload.get("execution_run_ids")
        or payload.get("robust_run_ids")
        or payload.get("sensitivity_analysis_ids")
    )
    if has_explicit_scope:
        executions, robust_runs, analyses, scope_findings = _resolve_scope(db, field, payload)
    else:
        executions, robust_runs, analyses, scope_findings = _auto_scope(db, field)

    if not executions and not robust_runs and not analyses:
        raise ValidationFailed(
            "Nothing to compare: no result-bearing executions, robust runs or "
            "sensitivity analyses exist for this field yet.",
            details=[{"field": "scope", "reason": "empty"}],
        )

    title = (payload.get("title") or "").strip() or "Decision comparison"

    fingerprint = sha256_of_document(
        dc.document_fingerprint_payload(
            field_id=str(field.id),
            title=title,
            execution_run_ids=[str(r.id) for r in executions],
            robust_run_ids=[str(r.id) for r in robust_runs],
            sensitivity_analysis_ids=[str(a.id) for a in analyses],
            generator_version=dc.DECISION_ENGINE_VERSION,
            method_version=dc.DECISION_METHOD_VERSION,
        )
    )
    existing = db.scalar(
        select(dbm.DecisionComparison).where(
            dbm.DecisionComparison.field_id == field.id,
            dbm.DecisionComparison.fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing

    warnings = list(scope_findings)
    not_available: dict[str, str] = {}

    baseline_section = _baseline_vs_scenario_section(db, executions)
    pairs_section = _scenario_pairs_section(db, executions)
    sensitivity_section = _sensitivity_section(db, analyses)
    rotation_section = _rotation_section(db, robust_runs)
    tradeoff_section = _tradeoff_section(db, robust_runs)
    missing = _missing_evidence_section(db, field, executions, robust_runs, analyses)
    findings = _findings_section(
        db, executions, robust_runs, analyses, baseline_section, missing
    )

    if not executions:
        not_available["baseline_vs_scenario"] = "no result-bearing executions in scope"
        not_available["scenario_pairs"] = "no result-bearing executions in scope"
    if not analyses:
        not_available["sensitivity_interpretation"] = (
            "no result-bearing sensitivity analyses in scope — run M7.4 analyses first"
        )
    if not robust_runs:
        not_available["rotation_decisions"] = (
            "no result-bearing robust runs in scope — build a scenario set and run M7.5 first"
        )
        not_available["tradeoffs"] = "no robust run in scope"

    document = {
        "generator_version": dc.DECISION_ENGINE_VERSION,
        "method_version": dc.DECISION_METHOD_VERSION,
        "field_id": str(field.id),
        "title": title,
        "scope": {
            "executions": [
                {
                    "execution_run_id": str(r.id),
                    "scenario_id": str(r.scenario_id),
                    "scenario": _scenario_label(db, r),
                    "scenario_version": r.scenario_version,
                    "output_checksum": r.output_checksum,
                    "run_status": r.run_status,
                }
                for r in executions
            ],
            "robust_runs": [
                {
                    "robust_run_id": str(r.id),
                    "solver_status": r.solver_status,
                    "output_checksum": r.output_checksum,
                    "member_count": r.member_count,
                }
                for r in robust_runs
            ],
            "sensitivity_analyses": [
                {
                    "analysis_id": str(a.id),
                    "source_execution_run_id": str(a.source_execution_run_id),
                    "output_checksum": a.output_checksum,
                }
                for a in analyses
            ],
        },
        "baseline_vs_scenario": baseline_section,
        "scenario_pairs": pairs_section,
        "sensitivity_interpretation": sensitivity_section,
        "rotation_decisions": rotation_section,
        "tradeoffs": tradeoff_section,
        "missing_evidence": missing,
        "findings": findings,
        "not_available": not_available,
        "honesty_note": (
            "This document assembles stored, immutable artifacts. It contains no "
            "composite scores, no probabilities, no yield predictions and no "
            "universal recommendations. Findings are evidence-linked and only "
            "ranked within the same unit."
        ),
    }

    doc_status = (
        dc.DOC_STATUS_COMPLETED_WITH_LIMITATIONS
        if warnings or not_available or not executions
        else dc.DOC_STATUS_SUCCEEDED
    )

    row = dbm.DecisionComparison(
        field_id=field.id,
        title=title,
        generator_version=dc.DECISION_ENGINE_VERSION,
        method_version=dc.DECISION_METHOD_VERSION,
        scope=document["scope"],
        document=document,
        document_checksum=sha256_of_document(document),
        fingerprint=fingerprint,
        doc_status=doc_status,
        warnings=warnings,
        not_available=not_available,
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.DecisionComparison).where(
                dbm.DecisionComparison.field_id == field.id,
                dbm.DecisionComparison.fingerprint == fingerprint,
            )
        )
        if winner is not None:
            return winner
        raise
    db.refresh(row)
    return row


def comparison_payload(row: dbm.DecisionComparison, *, include_document: bool = True) -> dict[str, Any]:
    out = {
        "id": str(row.id),
        "field_id": str(row.field_id),
        "title": row.title,
        "doc_status": row.doc_status,
        "fingerprint": row.fingerprint,
        "document_checksum": row.document_checksum,
        "scope": row.scope,
        "warnings": row.warnings,
        "not_available": row.not_available,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_document:
        out["document"] = row.document
    return out


def verify_comparison(db: Session, row: dbm.DecisionComparison) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    recomputed = sha256_of_document(row.document)
    if recomputed != row.document_checksum:
        findings.append({"issue": "document checksum mismatch", "stored": row.document_checksum})

    # source pins: executions / robust runs / analyses must still exist and be
    # result-bearing with the pinned checksums
    for e in (row.scope or {}).get("executions", []):
        run = db.get(dbm.ScenarioExecutionRun, uuid_mod.UUID(e["execution_run_id"]))
        if run is None:
            findings.append({"issue": "execution run deleted", "execution_run_id": e["execution_run_id"]})
        elif run.output_checksum != e.get("output_checksum"):
            findings.append(
                {"issue": "execution output checksum drift", "execution_run_id": e["execution_run_id"]}
            )
    for r in (row.scope or {}).get("robust_runs", []):
        rr = db.get(dbm.RobustRotationRun, uuid_mod.UUID(r["robust_run_id"]))
        if rr is None:
            findings.append({"issue": "robust run deleted", "robust_run_id": r["robust_run_id"]})
        elif rr.output_checksum != r.get("output_checksum"):
            findings.append(
                {"issue": "robust run output checksum drift", "robust_run_id": r["robust_run_id"]}
            )
    for a in (row.scope or {}).get("sensitivity_analyses", []):
        sa = db.get(dbm.SensitivityAnalysis, uuid_mod.UUID(a["analysis_id"]))
        if sa is None:
            findings.append({"issue": "sensitivity analysis deleted", "analysis_id": a["analysis_id"]})
        elif sa.output_checksum != a.get("output_checksum"):
            findings.append(
                {"issue": "sensitivity output checksum drift", "analysis_id": a["analysis_id"]}
            )
    return {
        "id": str(row.id),
        "verified": not findings,
        "findings": findings,
        "document_checksum": row.document_checksum,
        "note": (
            "Verification recomputes the document checksum and re-compares every "
            "scoped source's output checksum against the pinned value."
        ),
    }

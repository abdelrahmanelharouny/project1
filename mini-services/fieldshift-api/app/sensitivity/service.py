"""Sensitivity analysis orchestration (Milestone 7.4).

Builds, executes and persists sensitivity & uncertainty analyses of ONE
immutable M7.3 execution run. The analysis varies the run's configured
transformation parameters over user-supplied bounds and recomputes the
affected environmental features with the EXISTING M4 engine through the SAME
code paths M7.3 uses (`_manifest_observations`, `apply_transformations`,
`plan_scenario_features`, `recalculate_specs`, `compute_feature_drafts`) —
no transformation or feature-engineering logic is duplicated here.

Nothing in this module mutates parent artifacts: observations, feature runs,
Field States, finalized scenario definitions and M7.3 execution results are
read-only inputs; all outputs land in the sensitivity_* analytical layer.

Analysis flow (docs/m7/m7_4/M7_4_ARCHITECTURE_AND_LINEAGE.md):

    Result-bearing M7.3 Execution Run
        ↓  verify integrity gates (pins, checksums, run verification)
    Resolve Exploration Design           (bounds validated against references)
        ↓  canonical input document + fingerprint (idempotent replay)
    Reproduce Reference Evaluation       (exact gate against stored rows)
        ↓  mismatch ⇒ analysis FAILS, nothing substituted
    Evaluate OAT Sweeps + Joint Grid     (unique parameter tuples, deduped)
        ↓
    Compute Response Metrics             (envelope, slopes, classification)
        ↓
    Build Uncertainty Registry           (dynamic evidence binding)
        ↓
    Persist Immutable Results            (trigger-frozen analysis rows)
"""

import logging
import math
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.db import models as dbm
from app.features.catalog import FEATURE_CATALOG
from app.field_state.manifest import sha256_of_document
from app.scenario_execution import contracts as exc
from app.scenario_execution import service as execution_service
from app.scenario_execution.dependency_graph import (
    plan_scenario_features,
    recalculate_specs,
)
from app.scenarios import contracts as scenario_contracts
from app.sensitivity import contracts as sc
from app.sensitivity import math as smath
from app.sensitivity import registry as sregistry

logger = logging.getLogger("croptwist.sensitivity")

# ---------------------------------------------------------------------------
# Source-run eligibility (M7.4 architecture §2)
# ---------------------------------------------------------------------------


def _verify_scenario_pins(db: Session, scenario: dbm.Scenario) -> None:
    payload = scenario_contracts.scenario_checksum_payload(
        scenario_type=scenario.scenario_type,
        configuration_schema_version=scenario.configuration_schema_version,
        canonical_configuration=scenario.canonical_configuration or {},
        parent_field_state_id=str(scenario.parent_field_state_id),
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        timezone=scenario.timezone,
    )
    recomputed = scenario_contracts.compute_scenario_checksum(payload)
    if recomputed != scenario.configuration_checksum:
        raise Conflict(
            "Scenario configuration checksum does not match its stored content.",
            code="SCENARIO_CHECKSUM_MISMATCH",
            details=[{"stored": scenario.configuration_checksum, "recomputed": recomputed}],
        )


def validate_source_run(db: Session, run: dbm.ScenarioExecutionRun) -> dbm.Scenario:
    """All eligibility gates for attaching an analysis to a run (§2)."""
    if run.run_status not in exc.RESULT_STATUSES:
        raise Conflict(
            f"Sensitivity analysis requires a result-bearing execution run "
            f"(status is '{run.run_status}').",
            code="RUN_NOT_RESULT_BEARING",
        )
    scenario = db.get(dbm.Scenario, run.scenario_id)
    if scenario is None:
        raise Conflict("Source scenario no longer exists.", code="SCENARIO_NOT_FINALIZED")
    if scenario.scenario_status != "finalized":
        raise Conflict(
            f"Source scenario must be finalized (status is '{scenario.scenario_status}').",
            code="SCENARIO_NOT_FINALIZED",
        )
    _verify_scenario_pins(db, scenario)

    parent = db.get(dbm.FieldState, run.parent_field_state_id)
    if parent is None:
        raise Conflict("Parent Field State no longer exists.", code="PARENT_STATE_CHECKSUM_MISMATCH")
    if parent.checksum_sha256 != run.parent_snapshot_checksum:
        raise Conflict(
            "Parent Field State checksum no longer matches the run's pin.",
            code="PARENT_STATE_CHECKSUM_MISMATCH",
        )
    if (parent.observation_manifest_sha256 or "") != run.source_observation_manifest_sha256:
        raise Conflict(
            "Observation manifest checksum no longer matches the run's pin.",
            code="MANIFEST_CHECKSUM_MISMATCH",
        )

    verification = execution_service.verify_execution(db, run)
    failing = [
        flag
        for flag in (
            "output_checksum_valid",
            "scenario_definition_checksum_valid",
            "parent_snapshot_intact",
            "manifest_checksum_matches_run",
        )
        if not verification.get(flag)
    ]
    if failing:
        raise Conflict(
            "Source execution verification failed; the run cannot be analysed.",
            code="RUN_VERIFICATION_FAILED",
            details=[{"field": flag, "reason": "verification flag false"} for flag in failing],
        )
    return scenario


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------


def _reference_parameters(run: dbm.ScenarioExecutionRun) -> dict[str, float]:
    """Reference values strictly from the run's execution configuration."""
    refs: dict[str, float] = {}
    for doc in (run.execution_configuration or {}).get("transformations") or []:
        code = doc.get("code")
        if code == exc.TransformationCode.TEMPERATURE_DELTA_C.value and doc.get("delta_c") is not None:
            refs[sc.SensitivityParameter.TEMPERATURE_DELTA_C.value] = float(doc["delta_c"])
        elif code == exc.TransformationCode.PRECIPITATION_MULTIPLIER.value and doc.get("multiplier") is not None:
            refs[sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value] = float(doc["multiplier"])
    return refs


def _explorable_payload(reference_values: dict[str, float]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for code in sc.PARAMETER_CODES:
        if code in reference_values:
            out[code] = {"explorable": True, "reference_value": reference_values[code], "reason": None}
        else:
            out[code] = {
                "explorable": False,
                "reference_value": None,
                "reason": sc.NOT_CONFIGURED_REASON,
            }
    return out


def _parse_request(
    payload: dict[str, Any],
    reference_values: dict[str, float],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]] | None]:
    """Validate the request body into (parameter_design, grid_design)."""
    if not reference_values:
        raise ValidationFailed(
            "The source execution has no explorable parameters.",
            details=[{"field": "parameter_design", "reason": sc.NOT_CONFIGURED_REASON}],
            code="NO_EXPLORABLE_PARAMETERS",
        )

    designs_in = (payload or {}).get("parameter_design")
    if not isinstance(designs_in, dict) or not designs_in:
        raise ValidationFailed(
            "parameter_design must provide bounds for at least one explorable parameter.",
            details=[{"field": "parameter_design", "reason": "missing"}],
        )

    findings: list[dict[str, str]] = []
    design: dict[str, dict[str, Any]] = {}
    for code, raw in designs_in.items():
        if code not in sc.PARAMETER_CODES:
            findings.append({"field": f"parameter_design.{code}", "reason": "unknown parameter code"})
            continue
        if code not in reference_values:
            findings.append(
                {
                    "field": f"parameter_design.{code}",
                    "reason": sc.NOT_CONFIGURED_REASON,
                }
            )
            continue
        if not isinstance(raw, dict):
            findings.append({"field": f"parameter_design.{code}", "reason": "must be an object"})
            continue
        design[code] = {
            "lower": raw.get("lower"),
            "upper": raw.get("upper"),
            "n_points": raw.get("n_points", sc.DEFAULT_OAT_POINTS),
        }
        findings.extend(smath.validate_parameter_design(code, design[code], reference_values[code]))

    grid_design: dict[str, dict[str, Any]] | None = None
    grid_requested = (payload or {}).get("grid")
    if grid_requested:
        both_explorable = set(reference_values) == set(sc.PARAMETER_CODES)
        if not both_explorable:
            findings.append(
                {
                    "field": "grid",
                    "reason": (
                        "joint grid requires both supported parameters to be "
                        "configured in the source execution"
                    ),
                }
            )
        elif isinstance(grid_requested, dict):
            grid_design = {}
            for code in reference_values:
                raw = grid_requested.get(code)
                if not isinstance(raw, dict):
                    findings.append(
                        {"field": f"grid.{code}", "reason": "joint grid requires bounds for every explorable parameter"}
                    )
                    continue
                grid_design[code] = {
                    "lower": raw.get("lower"),
                    "upper": raw.get("upper"),
                    "n_points": raw.get("n_points", sc.MIN_GRID_POINTS + 1),
                }
            findings.extend(smath.validate_grid_design(grid_design, reference_values))
        elif grid_requested is True:
            # Reuse the OAT designs as grid axes; every explorable parameter
            # must have a design for the grid to be well-formed.
            missing = [c for c in reference_values if c not in design]
            if missing:
                findings.append(
                    {
                        "field": "grid",
                        "reason": (
                            "grid=true reuses parameter_design bounds; provide designs for "
                            f"all explorable parameters (missing: {', '.join(sorted(missing))})"
                        ),
                    }
                )
            else:
                grid_design = {code: dict(design[code]) for code in design}
        else:
            findings.append({"field": "grid", "reason": "must be true or an object of per-parameter designs"})

    # Unique-evaluation budget (upper bound before dedupe — conservative).
    unique_upper = 1 + sum(int(d.get("n_points") or 0) for d in design.values())
    if grid_design is not None:
        cells = 1
        for code, g in grid_design.items():
            cells *= int(g.get("n_points") or 0)
        unique_upper += cells
    if unique_upper > sc.MAX_UNIQUE_EVALUATIONS:
        findings.append(
            {
                "field": "evaluation_budget",
                "reason": (
                    f"design would evaluate up to {unique_upper} unique parameter tuples; "
                    f"the documented cap is {sc.MAX_UNIQUE_EVALUATIONS}"
                ),
            }
        )

    if findings:
        raise ValidationFailed(
            "Sensitivity analysis design is invalid.",
            details=findings,
        )
    return design, grid_design


# ---------------------------------------------------------------------------
# Evaluation plan
# ---------------------------------------------------------------------------


def _tuple_key(delta_c: float | None, multiplier: float | None) -> tuple[str, str]:
    """Canonical dedupe key (6-dp canonical precision, matching checksums)."""

    def _norm(value: float | None) -> str:
        if value is None:
            return "None"
        v = float(value)
        if v == 0.0:
            v = 0.0  # normalize -0.0 so mathematically equal tuples share a key
        return f"{round(v, 6):.6f}"

    return (_norm(delta_c), _norm(multiplier))


def build_evaluation_plan(
    *,
    reference_values: dict[str, float],
    parameter_design: dict[str, dict[str, Any]],
    grid_design: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Ordered unique evaluation tuples with their roles.

    Order: reference first, then OAT sweeps (parameter order, ascending x),
    then grid cells (ascending x, then z). Dedupe merges identical tuples.
    """
    ref_delta = reference_values.get(sc.SensitivityParameter.TEMPERATURE_DELTA_C.value)
    ref_mult = reference_values.get(sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value)

    plan: dict[tuple[str, str], dict[str, Any]] = {}

    def _add(delta_c: float | None, multiplier: float | None, role: str, meta: dict[str, Any] | None = None) -> None:
        key = _tuple_key(delta_c, multiplier)
        entry = plan.get(key)
        if entry is None:
            entry = {
                "delta_c": delta_c,
                "multiplier": multiplier,
                "roles": [],
                "meta": {},
            }
            plan[key] = entry
        if role not in entry["roles"]:
            entry["roles"].append(role)
        if meta:
            entry["meta"].update(meta)

    _add(ref_delta, ref_mult, "reference")

    for code in sc.PARAMETER_CODES:
        if code not in parameter_design:
            continue
        d = parameter_design[code]
        points = smath.linspace(float(d["lower"]), float(d["upper"]), int(d["n_points"]))
        for index, x in enumerate(points):
            if code == sc.SensitivityParameter.TEMPERATURE_DELTA_C.value:
                _add(x, ref_mult, "oat", {"parameter_code": code, "point_index": index, "points": points})
            else:
                _add(ref_delta, x, "oat", {"parameter_code": code, "point_index": index, "points": points})

    if grid_design is not None:
        x_design = grid_design.get(sc.SensitivityParameter.TEMPERATURE_DELTA_C.value)
        z_design = grid_design.get(sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value)
        if x_design and z_design:
            xs = smath.linspace(float(x_design["lower"]), float(x_design["upper"]), int(x_design["n_points"]))
            zs = smath.linspace(float(z_design["lower"]), float(z_design["upper"]), int(z_design["n_points"]))
            for x in xs:
                for z in zs:
                    _add(x, z, "grid")

    return list(plan.values())


# ---------------------------------------------------------------------------
# One evaluation = one M4 scenario pass (M7.3 code paths, no duplication)
# ---------------------------------------------------------------------------


def _run_single_evaluation(
    *,
    source_observations: list[dict[str, Any]],
    delta_c: float | None,
    multiplier: float | None,
    specs: list,
    tz: Any,
    hemisphere: str,
    window_start: Any,
    window_end: Any,
    aggregation_levels: list[str],
) -> tuple[dict[tuple[str, str, str], Any], int]:
    """Run one scenario pass; returns (keyed drafts, transformed count)."""
    derived_records, _exclusions = execution_service.apply_transformations(
        source_observations, delta_c=delta_c, multiplier=multiplier
    )
    scenario_obs = [execution_service._as_engine_observation(r) for r in derived_records]
    keyed, _not_evaluated, _warnings = execution_service._run_engine_pass(
        observations=scenario_obs,
        specs=specs,
        tz=tz,
        hemisphere=hemisphere,
        window_start=window_start,
        window_end=window_end,
        aggregation_levels=aggregation_levels,
    )
    return keyed, len(derived_records)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_sensitivity_analysis(
    db: Session,
    run: dbm.ScenarioExecutionRun,
    *,
    payload: dict[str, Any] | None = None,
    created_by: Any = None,
) -> dbm.SensitivityAnalysis:
    """Validate eligibility and design, create (or replay) the analysis,
    execute it inline."""
    scenario = validate_source_run(db, run)

    reference_values = _reference_parameters(run)
    parameter_design, grid_design = _parse_request(payload or {}, reference_values)

    if payload_idem := (payload or {}).get("idempotency_key"):
        existing = db.scalar(
            select(dbm.SensitivityAnalysis).where(
                dbm.SensitivityAnalysis.source_execution_run_id == run.id,
                dbm.SensitivityAnalysis.idempotency_key == payload_idem,
            )
        )
        if existing is not None:
            return existing

    analysis_configuration = sc.AnalysisConfiguration(
        source_execution_run_id=str(run.id),
        scenario_id=str(scenario.id),
        scenario_version=scenario.scenario_version,
        scenario_configuration_checksum=scenario.configuration_checksum,
        parent_field_state_id=str(run.parent_field_state_id),
        parent_snapshot_checksum=run.parent_snapshot_checksum,
        source_observation_manifest_sha256=run.source_observation_manifest_sha256,
        source_output_checksum=run.output_checksum or "",
        reference_parameter_values={code: reference_values[code] for code in sorted(reference_values)},
        explorable_parameters=sorted(reference_values),
        parameter_design={code: dict(design) for code, design in sorted(parameter_design.items())},
        grid_design=None if grid_design is None else {code: dict(g) for code, g in sorted(grid_design.items())},
        engine_versions={
            "analysis_method_version": sc.ANALYSIS_METHOD_VERSION,
            "response_classification_version": sc.RESPONSE_CLASSIFICATION_VERSION,
            "uncertainty_registry_version": sc.UNCERTAINTY_REGISTRY_VERSION,
            "transformation_engine_version": run.transformation_engine_version,
            "feature_engine_version": run.feature_engine_version,
            "feature_catalog_version": run.feature_catalog_version,
        },
    )
    fingerprint = sc.analysis_fingerprint(analysis_configuration)

    existing = db.scalar(
        select(dbm.SensitivityAnalysis).where(
            dbm.SensitivityAnalysis.source_execution_run_id == run.id,
            dbm.SensitivityAnalysis.analysis_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    analysis = dbm.SensitivityAnalysis(
        field_id=run.field_id,
        source_execution_run_id=run.id,
        scenario_id=scenario.id,
        scenario_version=scenario.scenario_version,
        parent_field_state_id=run.parent_field_state_id,
        parent_snapshot_checksum=run.parent_snapshot_checksum,
        scenario_configuration_checksum=scenario.configuration_checksum,
        source_observation_manifest_sha256=run.source_observation_manifest_sha256,
        source_output_checksum=run.output_checksum or "",
        reference_parameter_values=analysis_configuration.reference_parameter_values,
        explorable_parameters=sorted(reference_values),
        parameter_design=analysis_configuration.parameter_design,
        grid_design=analysis_configuration.grid_design,
        analysis_configuration=analysis_configuration.model_dump(mode="json"),
        analysis_fingerprint=fingerprint,
        analysis_method_version=sc.ANALYSIS_METHOD_VERSION,
        response_classification_version=sc.RESPONSE_CLASSIFICATION_VERSION,
        uncertainty_registry_version=sc.UNCERTAINTY_REGISTRY_VERSION,
        transformation_engine_version=run.transformation_engine_version,
        feature_engine_version=run.feature_engine_version,
        feature_catalog_version=run.feature_catalog_version,
        analysis_status=sc.ANALYSIS_STATUS_QUEUED,
        idempotency_key=payload_idem,
        created_by=getattr(created_by, "id", None),
        started_at=now,
    )
    db.add(analysis)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.SensitivityAnalysis).where(
                dbm.SensitivityAnalysis.source_execution_run_id == run.id,
                dbm.SensitivityAnalysis.analysis_fingerprint == fingerprint,
            )
        )
        if winner is not None:
            return winner
        raise

    _execute_analysis(db, analysis, run=run, scenario=scenario)
    return analysis


def _fail_analysis(db: Session, analysis: dbm.SensitivityAnalysis, message: str) -> None:
    db.rollback()
    analysis.analysis_status = sc.ANALYSIS_STATUS_FAILED
    analysis.error_summary = message
    analysis.completed_at = datetime.now(UTC)
    db.commit()


def _execute_analysis(
    db: Session,
    analysis: dbm.SensitivityAnalysis,
    *,
    run: dbm.ScenarioExecutionRun,
    scenario: dbm.Scenario,
) -> None:
    analysis.analysis_status = sc.ANALYSIS_STATUS_RUNNING
    db.commit()
    try:
        from app.features.calendar import resolve_timezone

        reference_values = {
            code: float(value) for code, value in (analysis.reference_parameter_values or {}).items()
        }
        ref_delta = reference_values.get(sc.SensitivityParameter.TEMPERATURE_DELTA_C.value)
        ref_mult = reference_values.get(sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value)

        window_start = scenario.period_start
        window_end = scenario.period_end
        aggregation_levels = list(run.aggregation_levels or [])
        tz = resolve_timezone(run.calendar_timezone)
        hemisphere = run.hemisphere or "north"

        manifest = run.source_observation_manifest or {}
        source_observations = execution_service._manifest_observations(
            manifest, window_start=window_start, window_end=window_end
        )

        # Dependency plan: identical across evaluations (role depends on which
        # parameters are configured, never on their values).
        plan = plan_scenario_features(delta_c=ref_delta, multiplier=ref_mult)
        specs = recalculate_specs(delta_c=ref_delta, multiplier=ref_mult)
        not_analysed = {
            code: entry["reason"]
            for code, entry in sorted(plan.items())
            if entry["role"] != "recalculate" and entry["reason"]
        }

        # ---- reference evaluation + reproduction gate ---------------------
        ref_keyed, ref_count = _run_single_evaluation(
            source_observations=source_observations,
            delta_c=ref_delta,
            multiplier=ref_mult,
            specs=specs,
            tz=tz,
            hemisphere=hemisphere,
            window_start=window_start,
            window_end=window_end,
            aggregation_levels=aggregation_levels,
        )
        stored_rows = db.execute(
            select(dbm.ScenarioDerivedFeature).where(
                dbm.ScenarioDerivedFeature.execution_run_id == run.id,
                dbm.ScenarioDerivedFeature.evidence_status == exc.FEATURE_EVIDENCE_RECALCULATED,
            )
        ).scalars().all()
        stored = {
            (r.feature_code, r.aggregation_level, r.period_label): r.scenario_value for r in stored_rows
        }
        compared_keys = sorted(set(stored) | set(ref_keyed))
        mismatched: list[dict[str, Any]] = []
        matched = 0
        for key in compared_keys:
            stored_value = stored.get(key)
            reproduced = ref_keyed[key].value if key in ref_keyed else None
            if stored_value is None and reproduced is None:
                matched += 1
                continue
            if stored_value is None or reproduced is None:
                mismatched.append(
                    {"key": list(key), "stored": stored_value, "reproduced": reproduced}
                )
            elif abs(float(stored_value) - float(reproduced)) <= 1e-9:
                matched += 1
            else:
                mismatched.append(
                    {"key": list(key), "stored": float(stored_value), "reproduced": float(reproduced)}
                )
        observation_count_match = ref_count == run.transformed_observation_count
        reproduction = {
            "reproduced": not mismatched and observation_count_match,
            "compared_rows": len(compared_keys),
            "matched_rows": matched,
            "mismatched_rows": mismatched[:20],
            "mismatched_row_count": len(mismatched),
            "observation_count_match": observation_count_match,
            "reproduced_observation_count": ref_count,
            "stored_observation_count": run.transformed_observation_count,
        }
        analysis.reference_reproduction = reproduction
        if mismatched or not observation_count_match:
            analysis.evaluation_count = 0
            analysis.evaluated_feature_count = 0
            analysis.analysis_status = sc.ANALYSIS_STATUS_FAILED
            analysis.error_summary = (
                "Reference reproduction failed: the source execution's stored "
                f"results could not be reproduced exactly ({len(mismatched)} "
                f"mismatched feature rows, observation_count_match="
                f"{observation_count_match}). No analysis was substituted."
            )
            analysis.completed_at = datetime.now(UTC)
            db.commit()
            return

        # ---- evaluation plan ----------------------------------------------
        parameter_design = analysis.parameter_design or {}
        grid_design = analysis.grid_design
        plan_entries = build_evaluation_plan(
            reference_values=reference_values,
            parameter_design=parameter_design,
            grid_design=grid_design,
        )

        evaluations: dict[tuple[str, str], dbm.SensitivityEvaluation] = {}
        evaluation_values: dict[tuple[str, str], dict[tuple[str, str, str], float | None]] = {}

        for entry in plan_entries:
            delta_c = entry["delta_c"]
            multiplier = entry["multiplier"]
            is_reference = "reference" in entry["roles"]
            row = dbm.SensitivityEvaluation(
                analysis_id=analysis.id,
                evaluation_kind="reference" if is_reference else (entry["roles"][0]),
                roles=entry["roles"],
                is_reference=is_reference,
                temperature_delta_c=delta_c,
                precipitation_multiplier=multiplier,
            )
            try:
                keyed, count = _run_single_evaluation(
                    source_observations=source_observations,
                    delta_c=delta_c,
                    multiplier=multiplier,
                    specs=specs,
                    tz=tz,
                    hemisphere=hemisphere,
                    window_start=window_start,
                    window_end=window_end,
                    aggregation_levels=aggregation_levels,
                )
                row.evaluation_status = sc.EVALUATION_STATUS_SUCCEEDED
                row.transformed_observation_count = count
                row.derived_feature_count = len(keyed)
                evaluation_values[_tuple_key(delta_c, multiplier)] = {
                    key: draft.value for key, draft in keyed.items()
                }
            except Exception as eval_exc:  # noqa: BLE001 — per-evaluation capture
                row.evaluation_status = sc.EVALUATION_STATUS_FAILED
                row.error_summary = f"{type(eval_exc).__name__}: {eval_exc}"
                evaluation_values[_tuple_key(delta_c, multiplier)] = {}
            db.add(row)
            evaluations[_tuple_key(delta_c, multiplier)] = row
        db.flush()

        # Feature-value rows (reference key universe; deterministic order).
        # Each entry carries its evaluation row beside it (no ORM relationship
        # is defined — evaluation parameter values are needed for checksums).
        ref_tuple_key = _tuple_key(ref_delta, ref_mult)
        reference_universe = sorted(evaluation_values.get(ref_tuple_key, {}).keys())
        feature_value_pairs: list[tuple[dbm.SensitivityEvaluation, dbm.SensitivityFeatureValue]] = []
        for key in reference_universe:
            feature_code, agg_level, period_label = key
            reference_value = evaluation_values.get(ref_tuple_key, {}).get(key)
            unit = FEATURE_CATALOG[feature_code].unit
            for tuple_key, row in evaluations.items():
                if row.evaluation_status != sc.EVALUATION_STATUS_SUCCEEDED:
                    continue
                value = evaluation_values.get(tuple_key, {}).get(key)
                feature_value_pairs.append(
                    (
                        row,
                        dbm.SensitivityFeatureValue(
                            analysis_id=analysis.id,
                            evaluation_id=row.id,
                            feature_code=feature_code,
                            unit=unit,
                            aggregation_level=agg_level,
                            period_label=period_label,
                            reference_value=reference_value,
                            evaluated_value=value,
                            difference_from_reference=(
                                None if value is None or reference_value is None else value - reference_value
                            ),
                        ),
                    )
                )
        feature_value_rows = [fv for _eval, fv in feature_value_pairs]
        for row in feature_value_rows:
            db.add(row)

        # ---- OAT responses -------------------------------------------------
        oat_rows: list[dbm.SensitivityOatResponse] = []
        for code in sc.PARAMETER_CODES:
            if code not in parameter_design:
                continue
            design = parameter_design[code]
            param_lower = float(design["lower"])
            param_upper = float(design["upper"])
            slope_unit = f"{{unit}} / {sc.PARAMETER_UNITS[code]}"

            # Sweep points in design order with their evaluations.
            sweep: list[tuple[float, dbm.SensitivityEvaluation]] = []
            for entry in plan_entries:
                if "oat" not in entry["roles"] or entry["meta"].get("parameter_code") != code:
                    continue
                x = (
                    entry["delta_c"]
                    if code == sc.SensitivityParameter.TEMPERATURE_DELTA_C.value
                    else entry["multiplier"]
                )
                sweep.append((float(x), evaluations[_tuple_key(entry["delta_c"], entry["multiplier"])]))
            sweep.sort(key=lambda p: p[0])
            n_design_points = int(design["n_points"])
            failed_evaluations = sum(1 for _, row in sweep if row.evaluation_status != sc.EVALUATION_STATUS_SUCCEEDED)

            for key in reference_universe:
                feature_code, agg_level, period_label = key
                reference_value = evaluation_values.get(ref_tuple_key, {}).get(key)
                unit = FEATURE_CATALOG[feature_code].unit
                points: list[tuple[float, float]] = []
                for x, row in sweep:
                    if row.evaluation_status != sc.EVALUATION_STATUS_SUCCEEDED:
                        continue
                    value = evaluation_values.get(_tuple_key(row.temperature_delta_c, row.precipitation_multiplier), {}).get(key)
                    if value is not None and math.isfinite(float(value)):
                        points.append((x, float(value)))

                envelope = smath.envelope_payload(points, param_lower, param_upper)
                finite_values = [v for _, v in points]
                diffs = (
                    [abs(v - float(reference_value)) for v in finite_values]
                    if reference_value is not None and math.isfinite(float(reference_value))
                    else []
                )
                at_lower = next((v for x, v in points if abs(x - param_lower) <= 1e-9), None)
                at_upper = next((v for x, v in points if abs(x - param_upper) <= 1e-9), None)

                slope_info = smath.finite_difference_slope(points, float(reference_values[code]))
                classification = smath.classify_response(points, reference_value)
                threshold = classification == sc.CLASSIFICATION_THRESHOLD_SUSPECTED
                elasticity = smath.elasticity_payload(
                    slope_info["slope"], float(reference_values[code]), reference_value
                )
                if len(points) == n_design_points and failed_evaluations == 0:
                    response_status = sc.RESPONSE_STATUS_EVALUATED
                elif points:
                    response_status = sc.RESPONSE_STATUS_PARTIALLY_EVALUATED
                else:
                    response_status = sc.RESPONSE_STATUS_NOT_EVALUATED

                oat_rows.append(
                    dbm.SensitivityOatResponse(
                        analysis_id=analysis.id,
                        parameter_code=code,
                        feature_code=feature_code,
                        unit=unit,
                        aggregation_level=agg_level,
                        period_label=period_label,
                        reference_value=reference_value,
                        min_evaluated=envelope["lower"],
                        max_evaluated=envelope["upper"],
                        output_range=(
                            None
                            if envelope["lower"] is None or envelope["upper"] is None
                            else envelope["upper"] - envelope["lower"]
                        ),
                        max_abs_difference=max(diffs) if diffs else None,
                        difference_at_lower=None if at_lower is None else at_lower - float(reference_value),
                        difference_at_upper=None if at_upper is None else at_upper - float(reference_value),
                        slope=slope_info["slope"],
                        slope_method=slope_info["slope_method"],
                        slope_units=slope_unit.format(unit=unit),
                        slope_validity=(
                            sc.SLOPE_VALIDITY_INVALID_ACROSS_JUMP
                            if threshold and slope_info["slope"] is not None
                            else sc.SLOPE_VALIDITY_VALID
                        ),
                        elasticity=elasticity["value"],
                        elasticity_status=elasticity["status"],
                        elasticity_unavailable_reason=elasticity["reason"],
                        direction=smath.direction_payload(points),
                        response_classification=classification,
                        classification_version=sc.RESPONSE_CLASSIFICATION_VERSION,
                        n_evaluated_points=len(points),
                        response_status=response_status,
                    )
                )
        for row in oat_rows:
            db.add(row)

        # ---- joint grid -----------------------------------------------------
        grid_cell_rows: list[dbm.SensitivityGridCell] = []
        grid_summary_rows: list[dbm.SensitivityGridSummary] = []
        if grid_design is not None:
            x_design = grid_design[sc.SensitivityParameter.TEMPERATURE_DELTA_C.value]
            z_design = grid_design[sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value]
            xs = smath.linspace(float(x_design["lower"]), float(x_design["upper"]), int(x_design["n_points"]))
            zs = smath.linspace(float(z_design["lower"]), float(z_design["upper"]), int(z_design["n_points"]))
            x0, x1 = min(xs), max(xs)
            z0, z1 = min(zs), max(zs)

            for key in reference_universe:
                feature_code, agg_level, period_label = key
                unit = FEATURE_CATALOG[feature_code].unit
                reference_value = evaluation_values.get(ref_tuple_key, {}).get(key)
                dep = None
                from app.scenario_execution.dependency_graph import FEATURE_DEPENDENCIES

                dep = FEATURE_DEPENDENCIES.get(feature_code)
                families: list[str] = []
                if dep is not None:
                    if dep.temperature_sensitive:
                        families.append(sc.VARIABLE_FAMILY_TEMPERATURE)
                    if dep.precipitation_sensitive:
                        families.append(sc.VARIABLE_FAMILY_PRECIPITATION)

                cell_values: dict[tuple[float, float], float] = {}
                for x in xs:
                    for z in zs:
                        row = evaluations.get(_tuple_key(x, z))
                        value = None
                        if row is not None and row.evaluation_status == sc.EVALUATION_STATUS_SUCCEEDED:
                            value = evaluation_values.get(_tuple_key(x, z), {}).get(key)
                        if value is not None and math.isfinite(float(value)):
                            cell_values[(x, z)] = float(value)
                        grid_cell_rows.append(
                            dbm.SensitivityGridCell(
                                analysis_id=analysis.id,
                                feature_code=feature_code,
                                unit=unit,
                                aggregation_level=agg_level,
                                period_label=period_label,
                                temperature_delta_c=x,
                                precipitation_multiplier=z,
                                cell_value=value,
                            )
                        )

                corners = {
                    "f00": cell_values.get((x0, z0)),
                    "f10": cell_values.get((x1, z0)),
                    "f01": cell_values.get((x0, z1)),
                    "f11": cell_values.get((x1, z1)),
                }
                interaction = smath.interaction_contrast(corners)

                # Per-row (fixed z, vary x) and per-column (fixed x, vary z)
                # monotonicity / threshold classification.
                non_monotonic = False
                threshold_count = 0
                for z in zs:
                    seq = [cell_values.get((x, z)) for x in xs]
                    finite_seq = [(x, v) for x, v in zip(xs, seq) if v is not None]
                    if len(finite_seq) >= 2:
                        if smath.grid_axis_monotonicity({"row": [v for _, v in finite_seq]}):
                            non_monotonic = True
                        if smath.classify_response(finite_seq, reference_value) == sc.CLASSIFICATION_THRESHOLD_SUSPECTED:
                            threshold_count += 1
                for x in xs:
                    seq = [cell_values.get((x, z)) for z in zs]
                    finite_seq = [(z, v) for z, v in zip(zs, seq) if v is not None]
                    if len(finite_seq) >= 2:
                        if smath.grid_axis_monotonicity({"col": [v for _, v in finite_seq]}):
                            non_monotonic = True
                        if smath.classify_response(finite_seq, reference_value) == sc.CLASSIFICATION_THRESHOLD_SUSPECTED:
                            threshold_count += 1

                corner_points = [(0.0, corners["f00"]), (1.0, corners["f11"])]
                grid_summary_rows.append(
                    dbm.SensitivityGridSummary(
                        analysis_id=analysis.id,
                        feature_code=feature_code,
                        unit=unit,
                        aggregation_level=agg_level,
                        period_label=period_label,
                        grid_min=min(cell_values.values()) if cell_values else None,
                        grid_max=max(cell_values.values()) if cell_values else None,
                        grid_output_range=(
                            max(cell_values.values()) - min(cell_values.values()) if cell_values else None
                        ),
                        direction=smath.direction_payload(corner_points),
                        non_monotonic=non_monotonic,
                        threshold_transition_count=threshold_count,
                        interaction_contrast=interaction["value"],
                        interaction_interpretation=interaction["interpretation"],
                        variable_families=families,
                    )
                )
        for row in grid_cell_rows:
            db.add(row)
        for row in grid_summary_rows:
            db.add(row)

        # ---- uncertainty registry -------------------------------------------
        recalculated_codes = sorted({key[0] for key in reference_universe})
        temperature_features = []
        precipitation_features = []
        et0_features = []
        from app.scenario_execution.dependency_graph import FEATURE_DEPENDENCIES

        for code in recalculated_codes:
            dep = FEATURE_DEPENDENCIES.get(code)
            if dep is None:
                continue
            if dep.temperature_sensitive:
                temperature_features.append(code)
            if dep.precipitation_sensitive:
                precipitation_features.append(code)
        for code, dep in sorted(FEATURE_DEPENDENCIES.items()):
            if dep.et0_dependent:
                et0_features.append(code)

        coverage_values = [float(r.coverage_ratio) for r in stored_rows if r.coverage_ratio is not None]
        gaps = sum(1 for r in stored_rows if (r.n_missing or 0) > 0)
        coverage_stats = (
            {
                "min_coverage_ratio": min(coverage_values),
                "mean_coverage_ratio": sum(coverage_values) / len(coverage_values),
                "features_with_missing_inputs": gaps,
                "compared_rows": len(stored_rows),
            }
            if coverage_values
            else None
        )
        has_synthetic = db.scalar(
            select(dbm.ScenarioDerivedObservation.id).where(
                dbm.ScenarioDerivedObservation.execution_run_id == run.id,
                dbm.ScenarioDerivedObservation.is_synthetic.is_(True),
            )
        ) is not None

        registry_items = sregistry.build_registry(
            explorable_parameters=sorted(reference_values),
            reference_values=reference_values,
            parameter_design=parameter_design,
            grid_requested=grid_design is not None,
            temperature_features=temperature_features,
            precipitation_features=precipitation_features,
            et0_features=et0_features,
            coverage_stats=coverage_stats,
            has_synthetic=has_synthetic,
        )
        registry_rows = [
            dbm.SensitivityUncertaintyItem(
                analysis_id=analysis.id,
                category=item["category"],
                code=item["code"],
                description=item["description"],
                evidence_source=item["evidence_source"],
                quantification_status=item["quantification_status"],
                quantification_method=item["quantification_method"],
                quantified_value=item["quantified_value"],
                affects_current_analysis=item["affects_current_analysis"],
                affected_inputs=item["affected_inputs"],
                affected_features=item["affected_features"],
                applicability=item["applicability"],
                user_facing_explanation=item["user_facing_explanation"],
                registry_version=item["registry_version"],
            )
            for item in registry_items
        ]
        for row in registry_rows:
            db.add(row)

        # ---- warnings + status ----------------------------------------------
        warnings: list[str] = list(sc.STANDARD_DISCLOSURES)
        if has_synthetic:
            warnings.append(
                "SYNTHETIC SOURCE: part of the source execution derives from "
                "synthetic fixture data; every sensitivity result inherits that label."
            )
        failed_evaluations = [row for row in evaluations.values() if row.evaluation_status != sc.EVALUATION_STATUS_SUCCEEDED]
        if failed_evaluations:
            warnings.append(
                f"{len(failed_evaluations)} evaluation(s) failed and are excluded "
                "from responses; affected responses are reported as "
                "partially_evaluated or not_evaluated."
            )
        if not_analysed:
            warnings.append(
                f"{len(not_analysed)} source feature(s) are outside the analysis "
                "scope (not affected or not evaluated by the source execution); "
                "reasons are listed verbatim in not_analysed_features."
            )
        for code in sc.PARAMETER_CODES:
            if code in reference_values and code not in parameter_design:
                warnings.append(
                    f"Explorable parameter {code} was not explored: no parameter "
                    "design was supplied for it, so it was held at its reference "
                    "value and no OAT response was computed for it."
                )

        status = sc.ANALYSIS_STATUS_SUCCEEDED
        if any(w not in sc.STANDARD_DISCLOSURES for w in warnings):
            status = sc.ANALYSIS_STATUS_COMPLETED_WITH_LIMITATIONS

        # ---- output checksum --------------------------------------------------
        evaluation_rows = [evaluations[key] for key in sorted(evaluations, key=lambda k: (k[0] == "None", k))]
        evaluation_docs = sorted(
            (
                {
                    "temperature_delta_c": row.temperature_delta_c,
                    "precipitation_multiplier": row.precipitation_multiplier,
                    "roles": sorted(row.roles or []),
                    "evaluation_status": row.evaluation_status,
                    "transformed_observation_count": row.transformed_observation_count,
                }
                for row in evaluation_rows
            ),
            key=lambda d: (_tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),),
        )
        feature_value_docs = sorted(
            (
                {
                    "temperature_delta_c": eval_row.temperature_delta_c,
                    "precipitation_multiplier": eval_row.precipitation_multiplier,
                    "feature_code": fv_row.feature_code,
                    "aggregation_level": fv_row.aggregation_level,
                    "period_label": fv_row.period_label,
                    "reference_value": fv_row.reference_value,
                    "evaluated_value": fv_row.evaluated_value,
                    "difference_from_reference": fv_row.difference_from_reference,
                }
                for eval_row, fv_row in feature_value_pairs
            ),
            key=lambda d: (
                _tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),
                d["feature_code"],
                d["aggregation_level"],
                d["period_label"],
            ),
        )
        oat_docs = sorted(
            (
                {
                    "parameter_code": row.parameter_code,
                    "feature_code": row.feature_code,
                    "aggregation_level": row.aggregation_level,
                    "period_label": row.period_label,
                    "reference_value": row.reference_value,
                    "min_evaluated": row.min_evaluated,
                    "max_evaluated": row.max_evaluated,
                    "output_range": row.output_range,
                    "max_abs_difference": row.max_abs_difference,
                    "difference_at_lower": row.difference_at_lower,
                    "difference_at_upper": row.difference_at_upper,
                    "slope": row.slope,
                    "slope_method": row.slope_method,
                    "slope_units": row.slope_units,
                    "slope_validity": row.slope_validity,
                    "elasticity": row.elasticity,
                    "elasticity_status": row.elasticity_status,
                    "elasticity_unavailable_reason": row.elasticity_unavailable_reason,
                    "direction": row.direction,
                    "response_classification": row.response_classification,
                    "n_evaluated_points": row.n_evaluated_points,
                    "response_status": row.response_status,
                }
                for row in oat_rows
            ),
            key=lambda d: (d["parameter_code"], d["feature_code"], d["aggregation_level"], d["period_label"]),
        )
        grid_cell_docs = sorted(
            (
                {
                    "feature_code": row.feature_code,
                    "aggregation_level": row.aggregation_level,
                    "period_label": row.period_label,
                    "temperature_delta_c": row.temperature_delta_c,
                    "precipitation_multiplier": row.precipitation_multiplier,
                    "cell_value": row.cell_value,
                }
                for row in grid_cell_rows
            ),
            key=lambda d: (
                d["feature_code"],
                d["aggregation_level"],
                d["period_label"],
                _tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),
            ),
        )
        grid_summary_docs = sorted(
            (
                {
                    "feature_code": row.feature_code,
                    "aggregation_level": row.aggregation_level,
                    "period_label": row.period_label,
                    "grid_min": row.grid_min,
                    "grid_max": row.grid_max,
                    "grid_output_range": row.grid_output_range,
                    "direction": row.direction,
                    "non_monotonic": row.non_monotonic,
                    "threshold_transition_count": row.threshold_transition_count,
                    "interaction_contrast": row.interaction_contrast,
                    "interaction_interpretation": row.interaction_interpretation,
                    "variable_families": row.variable_families,
                }
                for row in grid_summary_rows
            ),
            key=lambda d: (d["feature_code"], d["aggregation_level"], d["period_label"]),
        )
        registry_docs = sorted(
            (
                {
                    "category": row.category,
                    "code": row.code,
                    "quantification_status": row.quantification_status,
                    "quantification_method": row.quantification_method,
                    "quantified_value": row.quantified_value,
                    "affects_current_analysis": row.affects_current_analysis,
                    "affected_inputs": row.affected_inputs,
                    "affected_features": row.affected_features,
                    "applicability": row.applicability,
                }
                for row in registry_rows
            ),
            key=lambda d: (d["category"], d["code"]),
        )

        payload_doc = sc.analysis_checksum_payload(
            analysis_configuration=analysis.analysis_configuration,
            reference_reproduction=reproduction,
            evaluations=evaluation_docs,
            feature_values=feature_value_docs,
            oat_responses=oat_docs,
            grid_cells=grid_cell_docs,
            grid_summaries=grid_summary_docs,
            uncertainty_items=registry_docs,
            not_analysed_features=not_analysed,
            warnings=warnings,
        )
        output_checksum = sha256_of_document(sc.canonical_value(payload_doc))

        analysis.evaluation_count = len(evaluation_rows)
        analysis.evaluated_feature_count = len(reference_universe)
        analysis.warnings = warnings
        analysis.not_analysed_features = not_analysed
        analysis.output_checksum = output_checksum
        analysis.analysis_status = status
        analysis.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc_:  # noqa: BLE001 — analysis lifecycle must capture failures
        db.rollback()
        analysis.analysis_status = sc.ANALYSIS_STATUS_FAILED
        analysis.error_summary = f"{type(exc_).__name__}: {exc_}"
        analysis.completed_at = datetime.now(UTC)
        db.commit()
        logger.exception("sensitivity analysis failed", extra={"analysis_id": str(analysis.id)})


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_analysis(db: Session, analysis: dbm.SensitivityAnalysis) -> dict[str, Any]:
    """Recompute the output checksum from persisted rows and re-check pins."""
    evaluations = db.execute(
        select(dbm.SensitivityEvaluation)
        .where(dbm.SensitivityEvaluation.analysis_id == analysis.id)
    ).scalars().all()
    eval_by_id = {row.id: row for row in evaluations}
    feature_values = db.execute(
        select(dbm.SensitivityFeatureValue).where(
            dbm.SensitivityFeatureValue.analysis_id == analysis.id
        )
    ).scalars().all()
    oat_rows = db.execute(
        select(dbm.SensitivityOatResponse).where(dbm.SensitivityOatResponse.analysis_id == analysis.id)
    ).scalars().all()
    grid_cells = db.execute(
        select(dbm.SensitivityGridCell).where(dbm.SensitivityGridCell.analysis_id == analysis.id)
    ).scalars().all()
    grid_summaries = db.execute(
        select(dbm.SensitivityGridSummary).where(dbm.SensitivityGridSummary.analysis_id == analysis.id)
    ).scalars().all()
    registry_rows = db.execute(
        select(dbm.SensitivityUncertaintyItem).where(
            dbm.SensitivityUncertaintyItem.analysis_id == analysis.id
        )
    ).scalars().all()

    evaluation_docs = sorted(
        (
            {
                "temperature_delta_c": row.temperature_delta_c,
                "precipitation_multiplier": row.precipitation_multiplier,
                "roles": sorted(row.roles or []),
                "evaluation_status": row.evaluation_status,
                "transformed_observation_count": row.transformed_observation_count,
            }
            for row in evaluations
        ),
        key=lambda d: (_tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),),
    )
    feature_value_docs = sorted(
        (
            {
                "temperature_delta_c": eval_by_id[row.evaluation_id].temperature_delta_c,
                "precipitation_multiplier": eval_by_id[row.evaluation_id].precipitation_multiplier,
                "feature_code": row.feature_code,
                "aggregation_level": row.aggregation_level,
                "period_label": row.period_label,
                "reference_value": row.reference_value,
                "evaluated_value": row.evaluated_value,
                "difference_from_reference": row.difference_from_reference,
            }
            for row in feature_values
        ),
        key=lambda d: (
            _tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),
            d["feature_code"],
            d["aggregation_level"],
            d["period_label"],
        ),
    )
    oat_docs = sorted(
        (
            {
                "parameter_code": row.parameter_code,
                "feature_code": row.feature_code,
                "aggregation_level": row.aggregation_level,
                "period_label": row.period_label,
                "reference_value": row.reference_value,
                "min_evaluated": row.min_evaluated,
                "max_evaluated": row.max_evaluated,
                "output_range": row.output_range,
                "max_abs_difference": row.max_abs_difference,
                "difference_at_lower": row.difference_at_lower,
                "difference_at_upper": row.difference_at_upper,
                "slope": row.slope,
                "slope_method": row.slope_method,
                "slope_units": row.slope_units,
                "slope_validity": row.slope_validity,
                "elasticity": row.elasticity,
                "elasticity_status": row.elasticity_status,
                "elasticity_unavailable_reason": row.elasticity_unavailable_reason,
                "direction": row.direction,
                "response_classification": row.response_classification,
                "n_evaluated_points": row.n_evaluated_points,
                "response_status": row.response_status,
            }
            for row in oat_rows
        ),
        key=lambda d: (d["parameter_code"], d["feature_code"], d["aggregation_level"], d["period_label"]),
    )
    grid_cell_docs = sorted(
        (
            {
                "feature_code": row.feature_code,
                "aggregation_level": row.aggregation_level,
                "period_label": row.period_label,
                "temperature_delta_c": row.temperature_delta_c,
                "precipitation_multiplier": row.precipitation_multiplier,
                "cell_value": row.cell_value,
            }
            for row in grid_cells
        ),
        key=lambda d: (
            d["feature_code"],
            d["aggregation_level"],
            d["period_label"],
            _tuple_key(d["temperature_delta_c"], d["precipitation_multiplier"]),
        ),
    )
    grid_summary_docs = sorted(
        (
            {
                "feature_code": row.feature_code,
                "aggregation_level": row.aggregation_level,
                "period_label": row.period_label,
                "grid_min": row.grid_min,
                "grid_max": row.grid_max,
                "grid_output_range": row.grid_output_range,
                "direction": row.direction,
                "non_monotonic": row.non_monotonic,
                "threshold_transition_count": row.threshold_transition_count,
                "interaction_contrast": row.interaction_contrast,
                "interaction_interpretation": row.interaction_interpretation,
                "variable_families": row.variable_families,
            }
            for row in grid_summaries
        ),
        key=lambda d: (d["feature_code"], d["aggregation_level"], d["period_label"]),
    )
    registry_docs = sorted(
        (
            {
                "category": row.category,
                "code": row.code,
                "quantification_status": row.quantification_status,
                "quantification_method": row.quantification_method,
                "quantified_value": row.quantified_value,
                "affects_current_analysis": row.affects_current_analysis,
                "affected_inputs": row.affected_inputs,
                "affected_features": row.affected_features,
                "applicability": row.applicability,
            }
            for row in registry_rows
        ),
        key=lambda d: (d["category"], d["code"]),
    )

    payload_doc = sc.analysis_checksum_payload(
        analysis_configuration=analysis.analysis_configuration,
        reference_reproduction=analysis.reference_reproduction or {},
        evaluations=evaluation_docs,
        feature_values=feature_value_docs,
        oat_responses=oat_docs,
        grid_cells=grid_cell_docs,
        grid_summaries=grid_summary_docs,
        uncertainty_items=registry_docs,
        not_analysed_features=analysis.not_analysed_features or {},
        warnings=analysis.warnings or [],
    )
    recomputed = sha256_of_document(sc.canonical_value(payload_doc))

    run = db.get(dbm.ScenarioExecutionRun, analysis.source_execution_run_id)
    parent = db.get(dbm.FieldState, analysis.parent_field_state_id)
    run_intact = (
        run is not None
        and run.output_checksum == analysis.source_output_checksum
        and run.run_status in exc.RESULT_STATUSES
    )
    parent_intact = parent is not None and parent.checksum_sha256 == analysis.parent_snapshot_checksum
    manifest_ok = (
        parent is not None
        and (parent.observation_manifest_sha256 or "") == analysis.source_observation_manifest_sha256
    )

    return {
        "analysis_id": str(analysis.id),
        "analysis_status": analysis.analysis_status,
        "output_checksum_valid": analysis.output_checksum == recomputed,
        "expected_output_checksum": recomputed,
        "stored_output_checksum": analysis.output_checksum,
        "source_run_intact": run_intact,
        "parent_snapshot_intact": parent_intact,
        "manifest_checksum_matches": manifest_ok,
        "reference_reproduction_consistent": bool(
            (analysis.reference_reproduction or {}).get("reproduced")
        ),
        "verified_at": datetime.now(UTC).isoformat(),
        "note": (
            "Verification recomputes the analysis checksum from persisted "
            "artifacts and re-checks the source-run pins. It confirms the "
            "integrity and reproducibility of a HYPOTHETICAL analysis — never "
            "that the underlying transformed values are observations."
        ),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def analysis_payload(analysis: dbm.SensitivityAnalysis) -> dict[str, Any]:
    return {
        "analysis_id": str(analysis.id),
        "source_execution_run_id": str(analysis.source_execution_run_id),
        "scenario_id": str(analysis.scenario_id),
        "scenario_version": analysis.scenario_version,
        "field_id": str(analysis.field_id),
        "parent_field_state_id": str(analysis.parent_field_state_id),
        "analysis_status": analysis.analysis_status,
        "analysis_method_version": analysis.analysis_method_version,
        "response_classification_version": analysis.response_classification_version,
        "uncertainty_registry_version": analysis.uncertainty_registry_version,
        "transformation_engine_version": analysis.transformation_engine_version,
        "feature_engine_version": analysis.feature_engine_version,
        "feature_catalog_version": analysis.feature_catalog_version,
        "reference_parameter_values": analysis.reference_parameter_values or {},
        "explorable_parameters": analysis.explorable_parameters or [],
        "parameter_design": analysis.parameter_design or {},
        "grid_design": analysis.grid_design,
        "analysis_fingerprint": analysis.analysis_fingerprint,
        "reference_reproduction": analysis.reference_reproduction or {},
        "evaluation_count": analysis.evaluation_count,
        "evaluated_feature_count": analysis.evaluated_feature_count,
        "warnings": analysis.warnings or [],
        "not_analysed_features": analysis.not_analysed_features or {},
        "output_checksum": analysis.output_checksum,
        "error_summary": analysis.error_summary,
        "idempotency_key": analysis.idempotency_key,
        "started_at": analysis.started_at.isoformat() if analysis.started_at else None,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "evidence_note": (
            "Sensitivity results analyse hypothetical scenario-derived "
            "features. The explored parameter-range envelope is a "
            "deterministic sensitivity result — not a confidence or "
            "probability interval."
        ),
    }


def _explorable_detail(analysis: dbm.SensitivityAnalysis) -> dict[str, dict[str, Any]]:
    """Full explorable map (including not-configured parameters)."""
    configured = set(analysis.explorable_parameters or [])
    reference = analysis.reference_parameter_values or {}
    return _explorable_payload_from(configured, reference)


def _explorable_payload_from(
    configured: set[str], reference: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for code in sc.PARAMETER_CODES:
        if code in configured:
            out[code] = {"explorable": True, "reference_value": reference.get(code), "reason": None}
        else:
            out[code] = {
                "explorable": False,
                "reference_value": None,
                "reason": sc.NOT_CONFIGURED_REASON,
            }
    return out


def analysis_detail_payload(
    analysis: dbm.SensitivityAnalysis,
    evaluations: list[dbm.SensitivityEvaluation],
) -> dict[str, Any]:
    payload = analysis_payload(analysis)
    payload["explorable_parameters_detail"] = _explorable_detail(analysis)
    payload["evaluations"] = [evaluation_payload(e) for e in evaluations]
    return payload


def evaluation_payload(row: dbm.SensitivityEvaluation) -> dict[str, Any]:
    return {
        "evaluation_id": str(row.id),
        "evaluation_kind": row.evaluation_kind,
        "roles": row.roles or [],
        "is_reference": row.is_reference,
        "parameter_values": {
            "temperature_delta_c": row.temperature_delta_c,
            "precipitation_multiplier": row.precipitation_multiplier,
        },
        "evaluation_status": row.evaluation_status,
        "transformed_observation_count": row.transformed_observation_count,
        "derived_feature_count": row.derived_feature_count,
        "error_summary": row.error_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def oat_response_payload(row: dbm.SensitivityOatResponse) -> dict[str, Any]:
    return {
        "parameter_code": row.parameter_code,
        "feature_code": row.feature_code,
        "unit": row.unit,
        "aggregation_level": row.aggregation_level,
        "period_label": row.period_label,
        "reference_value": row.reference_value,
        "explored_parameter_range_envelope": {
            "parameter_lower": None,  # filled by the endpoint from the design
            "parameter_upper": None,
            "lower": row.min_evaluated,
            "upper": row.max_evaluated,
        },
        "output_range": row.output_range,
        "max_abs_difference": row.max_abs_difference,
        "difference_at_lower": row.difference_at_lower,
        "difference_at_upper": row.difference_at_upper,
        "slope": row.slope,
        "slope_method": row.slope_method,
        "slope_units": row.slope_units,
        "slope_validity": row.slope_validity,
        "elasticity": {
            "status": row.elasticity_status,
            "value": row.elasticity,
            "reason": row.elasticity_unavailable_reason,
        },
        "direction": row.direction,
        "response_classification": row.response_classification,
        "classification_version": row.classification_version,
        "n_evaluated_points": row.n_evaluated_points,
        "response_status": row.response_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def responses_payload(
    analysis: dbm.SensitivityAnalysis, rows: list[dbm.SensitivityOatResponse]
) -> dict[str, Any]:
    items = []
    parameter_design = analysis.parameter_design or {}
    for row in rows:
        item = oat_response_payload(row)
        design = parameter_design.get(row.parameter_code) or {}
        item["explored_parameter_range_envelope"]["parameter_lower"] = design.get("lower")
        item["explored_parameter_range_envelope"]["parameter_upper"] = design.get("upper")
        items.append(item)
    return {
        "analysis_id": str(analysis.id),
        "items": items,
        "count": len(items),
        "note": (
            "One-factor-at-a-time responses: each parameter varies over the "
            "explored bounds while every other configured parameter is held at "
            "its reference value. Slopes keep their units and are never "
            "compared across different units."
        ),
    }


def grid_cells_payload(rows: list[dbm.SensitivityGridCell]) -> list[dict[str, Any]]:
    return [
        {
            "feature_code": row.feature_code,
            "unit": row.unit,
            "aggregation_level": row.aggregation_level,
            "period_label": row.period_label,
            "temperature_delta_c": row.temperature_delta_c,
            "precipitation_multiplier": row.precipitation_multiplier,
            "cell_value": row.cell_value,
        }
        for row in rows
    ]


def grid_summaries_payload(rows: list[dbm.SensitivityGridSummary]) -> list[dict[str, Any]]:
    return [
        {
            "feature_code": row.feature_code,
            "unit": row.unit,
            "aggregation_level": row.aggregation_level,
            "period_label": row.period_label,
            "grid_min": row.grid_min,
            "grid_max": row.grid_max,
            "grid_output_range": row.grid_output_range,
            "direction": row.direction,
            "non_monotonic": row.non_monotonic,
            "threshold_transition_count": row.threshold_transition_count,
            "interaction_contrast": row.interaction_contrast,
            "interaction_interpretation": row.interaction_interpretation,
            "variable_families": row.variable_families or [],
        }
        for row in rows
    ]


def uncertainty_payload(rows: list[dbm.SensitivityUncertaintyItem]) -> dict[str, Any]:
    return {
        "registry_version": (
            rows[0].registry_version if rows else sc.UNCERTAINTY_REGISTRY_VERSION
        ),
        "items": [
            {
                "category": row.category,
                "code": row.code,
                "description": row.description,
                "evidence_source": row.evidence_source,
                "quantification_status": row.quantification_status,
                "quantification_method": row.quantification_method,
                "quantified_value": row.quantified_value,
                "affects_current_analysis": row.affects_current_analysis,
                "affected_inputs": row.affected_inputs or [],
                "affected_features": row.affected_features or [],
                "applicability": row.applicability,
                "user_facing_explanation": row.user_facing_explanation,
            }
            for row in rows
        ],
        "count": len(rows),
        "note": (
            "The registry distinguishes fundamentally different uncertainty "
            "types; no composite uncertainty score exists and no numeric "
            "confidence values are invented."
        ),
    }

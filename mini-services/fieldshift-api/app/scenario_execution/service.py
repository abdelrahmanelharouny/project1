"""Scenario execution orchestration (Milestone 7.3).

Applies the supported environmental transformations of a FINALIZED scenario
definition to the observation set pinned by its parent Field State manifest
and recomputes the affected environmental features with the existing M4
feature engine (compute_feature_drafts). Nothing here mutates parent
artifacts: observations, feature runs, Field States and finalized scenario
definitions are read-only inputs; all outputs land in the scenario_execution_*
derived layer.

Execution flow (docs/m7/m7_3/M7_3_EXECUTION_ARCHITECTURE.md):

    Finalized Scenario Definition
        ↓  verify lifecycle + configuration checksum + parent pins
    Resolve Observation Manifest          (BY VALUE — never a live query)
        ↓  variable / temporal compatibility (blocking findings)
    Apply Environmental Transformations   (pure functions)
        ↓
    Recalculate Supported Features        (M4 engine, two passes)
        ↓  baseline pass  = original values, scenario pass = transformed
    Propagate Quality and Uncertainty
        ↓
    Generate Execution Checksum           (canonical JSON, SHA-256)
        ↓
    Persist Immutable Results             (trigger-frozen result rows)

Eligibility (M7.3 spec §8): only `finalized` scenarios execute; scenarios
whose configuration carries unsupported adjustment dimensions are refused
with structured findings (water_allocation_multiplier is allowed as context);
a scenario without any supported transformation is refused (no-op runs are
meaningless and would masquerade as the baseline).
"""

import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.db import models as dbm
from app.features import engine as fengine
from app.features.calendar import resolve_timezone
from app.features.catalog import FEATURE_CATALOG, FEATURE_ENGINE_VERSION
from app.field_state.manifest import sha256_of_document
from app.scenario_execution import contracts as exc
from app.scenario_execution.dependency_graph import (
    ET0_NOT_EVALUATED_REASON,
    plan_scenario_features,
    recalculate_specs,
)
from app.scenario_execution.transformations import apply_transformations
from app.scenarios import contracts as sc
from app.scenarios import service as scenario_service

logger = logging.getLogger("croptwist.scenario_execution")

MAX_EXECUTION_WINDOW_DAYS = 366 * 3

HYPOTHETICAL_DISCLOSURE = (
    "Scenario execution is a derived hypothetical calculation: transformed "
    "values are NOT observations of the real world and never enter the "
    "observation record."
)


# ---------------------------------------------------------------------------
# Eligibility & verification
# ---------------------------------------------------------------------------


def _require_executable(scenario: dbm.Scenario) -> None:
    if scenario.scenario_status == "draft":
        raise Conflict(
            "Scenario is still a draft; validate and finalize it before execution.",
            code="SCENARIO_NOT_FINALIZED",
        )
    if scenario.scenario_status != "finalized":
        raise Conflict(
            f"Only finalized scenarios can execute (status is "
            f"'{scenario.scenario_status}').",
            code="SCENARIO_NOT_FINALIZED",
        )
    if scenario.scenario_type not in (
        sc.ScenarioType.HISTORICAL_PERTURBATION.value,
        sc.ScenarioType.USER_DEFINED_STRESS.value,
    ):
        raise Conflict(
            f"Scenario type '{scenario.scenario_type}' has no executable "
            "transformation (reference-only or not-implemented type).",
            code="SCENARIO_TYPE_NOT_EXECUTABLE",
        )


def _verify_definition_pins(db: Session, scenario: dbm.Scenario) -> None:
    """Re-verify the definition checksum and parent pins at execution time."""
    payload = sc.scenario_checksum_payload(
        scenario_type=scenario.scenario_type,
        configuration_schema_version=scenario.configuration_schema_version,
        canonical_configuration=scenario.canonical_configuration or {},
        parent_field_state_id=str(scenario.parent_field_state_id),
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        timezone=scenario.timezone,
    )
    recomputed = sc.compute_scenario_checksum(payload)
    if recomputed != scenario.configuration_checksum:
        raise Conflict(
            "Scenario configuration checksum does not match its stored content; "
            "the definition cannot be executed.",
            code="SCENARIO_CHECKSUM_MISMATCH",
            details=[{"stored": scenario.configuration_checksum, "recomputed": recomputed}],
        )
    parent = db.get(dbm.FieldState, scenario.parent_field_state_id)
    if parent is None:
        raise Conflict(
            "Parent Field State no longer exists; execution refused.",
            code="PARENT_STATE_MISSING",
        )
    if parent.status != "succeeded" or parent.checksum_sha256 != scenario.parent_snapshot_checksum:
        raise Conflict(
            "Parent Field State checksum no longer matches the scenario's pin; "
            "execution refused.",
            code="PARENT_STATE_CHECKSUM_MISMATCH",
        )


def _extract_transformations(canonical_configuration: dict[str, Any]) -> dict[str, Any]:
    """Map the M7.2 AdjustmentSet onto M7.3 execution parameters.

    Raises ExecutionBlockedError with structured findings when an unsupported
    dimension is configured or no supported transformation is present.
    """
    adjustments = canonical_configuration.get("adjustments") or {}
    findings: list[dict[str, Any]] = []
    for dimension, reason in exc.UNSUPPORTED_DIMENSION_REASONS.items():
        if adjustments.get(dimension) is not None:
            findings.append({"field": f"adjustments.{dimension}", "reason": reason, "code": "unsupported_transformation"})

    delta_c = adjustments.get("temperature_delta_c")
    multiplier = adjustments.get("precipitation_multiplier")
    if delta_c is None and multiplier is None:
        findings.append(
            {
                "field": "adjustments",
                "reason": (
                    "No supported transformation is configured: M7.3 executes "
                    "temperature_delta_c and precipitation_multiplier only."
                ),
                "code": "no_supported_transformation",
            }
        )
    if findings:
        raise exc.ExecutionBlockedError(
            "Scenario configuration cannot execute under the M7.3 "
            "transformation engine.",
            findings=findings,
        )

    water = adjustments.get("water_allocation_multiplier")
    return {
        "delta_c": None if delta_c is None else float(delta_c),
        "multiplier": None if multiplier is None else float(multiplier),
        "resource_constraints": (
            {} if water is None else {"water_allocation_multiplier": float(water)}
        ),
    }


# ---------------------------------------------------------------------------
# Manifest-driven input set
# ---------------------------------------------------------------------------


def _parse_instant(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _manifest_observations(
    manifest: dict[str, Any],
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    """Engine observation dicts built PURELY from the parent manifest.

    The manifest is the BY-VALUE pin of the parent input set (M7.1 H-02) — a
    later ingestion can never silently change an execution's input. Entries
    outside the scenario window are excluded (hard boundary, no margin).
    """
    out: list[dict[str, Any]] = []
    for entry in manifest.get("observations") or []:
        observed_at = _parse_instant(entry.get("observed_at"))
        period_start = _parse_instant(entry.get("period_start"))
        period_end = _parse_instant(entry.get("period_end"))
        if period_start is None or period_end is None:
            continue
        if period_start < window_start or period_end > window_end:
            continue  # hard window boundary — never extended
        out.append(
            {
                "id": entry.get("id"),
                "variable_code": entry.get("variable_code"),
                "value": entry.get("value"),
                "unit": entry.get("unit"),
                "quality_status": entry.get("quality_status") or "valid",
                "observed_at": observed_at,
                "period_start": period_start,
                "period_end": period_end,
                "time_support": entry.get("time_support") or "daily",
                "is_synthetic": bool(entry.get("is_synthetic")),
                "processing_version": entry.get("processing_version"),
                "evidence_class": entry.get("evidence_class"),
                "dataset_product_id": entry.get("dataset_product_id"),
                "spatial_support_type": entry.get("spatial_support_type"),
                "spatial_resolution_m": None,
                "uncertainty_value": (entry.get("uncertainty") or {}).get("value"),
                "uncertainty_type": (entry.get("uncertainty") or {}).get("type"),
                "metadata": {"asset_refs": entry.get("asset_refs") or {}},
            }
        )
    return out


def _as_engine_observation(record: Any) -> dict[str, Any]:
    """Scenario-pass observation dict: same shape, DERIVED id and values."""
    return {
        "id": str(record.source_observation_id) + ":derived",  # engine-unique provenance key
        "variable_code": record.variable_code,
        "value": record.value,
        "unit": record.unit,
        "quality_status": record.quality_status,
        "observed_at": record.observed_at,
        "period_start": record.period_start,
        "period_end": record.period_end,
        "time_support": record.time_support,
        "is_synthetic": record.is_synthetic,
        "processing_version": record.processing_version,
        "evidence_class": record.evidence_class,
        "dataset_product_id": record.dataset_product_id,
        "spatial_support_type": record.spatial_support_type,
        "spatial_resolution_m": record.spatial_resolution_m,
        "uncertainty_value": None,
        "uncertainty_type": None,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Execution configuration + fingerprints
# ---------------------------------------------------------------------------


def _execution_configuration(
    scenario: dbm.Scenario,
    *,
    parent_state: dbm.FieldState,
    transformations: list[dict[str, Any]],
    resource_constraints: dict[str, Any],
    aggregation_levels: list[str],
) -> exc.ExecutionConfiguration:
    calendar_context = parent_state.calendar_context or {}
    hemisphere = calendar_context.get("hemisphere") or "north"
    if hemisphere not in ("north", "south"):
        hemisphere = "north"
    return exc.ExecutionConfiguration(
        scenario_type=scenario.scenario_type,
        scenario_configuration_checksum=scenario.configuration_checksum,
        parent_field_state_id=str(scenario.parent_field_state_id),
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        period_start=scenario.period_start.astimezone(UTC).isoformat(),
        period_end=scenario.period_end.astimezone(UTC).isoformat(),
        timezone=parent_state.timezone or "UTC",
        hemisphere=hemisphere,
        transformations=transformations,
        resource_constraints=resource_constraints,
        aggregation_levels=aggregation_levels,
        engine_versions={
            "transformation_engine_version": exc.TRANSFORMATION_ENGINE_VERSION,
            "feature_engine_version": FEATURE_ENGINE_VERSION,
        },
    )


def _input_fingerprint(
    execution_configuration: exc.ExecutionConfiguration,
    source_manifest_sha256: str,
) -> str:
    return sha256_of_document(
        {
            "fingerprint_format": "scenario-execution-input-1",
            "execution_configuration": execution_configuration.model_dump(mode="json"),
            "source_observation_manifest_sha256": source_manifest_sha256,
        }
    )


def _transformation_documents(
    *, delta_c: float | None, multiplier: float | None
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if delta_c is not None:
        docs.append({"code": exc.TransformationCode.TEMPERATURE_DELTA_C.value, "delta_c": delta_c})
    if multiplier is not None:
        docs.append(
            {"code": exc.TransformationCode.PRECIPITATION_MULTIPLIER.value, "multiplier": multiplier}
        )
    return docs


def _aggregation_levels(window_days: int) -> list[str]:
    levels = ["monthly", "seasonal"]
    if window_days <= 366:
        levels.insert(0, "daily")
    return levels


# ---------------------------------------------------------------------------
# Feature passes
# ---------------------------------------------------------------------------


def _run_engine_pass(
    *,
    observations: list[dict[str, Any]],
    specs: list,
    tz,
    hemisphere: str,
    window_start: datetime,
    window_end: datetime,
    aggregation_levels: list[str],
) -> tuple[dict[tuple[str, str, str], Any], dict[str, str], list[str]]:
    drafts, not_evaluated, warnings = fengine.compute_feature_drafts(
        observations=observations,
        specs=specs,
        tz=tz,
        hemisphere=hemisphere,
        window_start=window_start,
        window_end=window_end,
        aggregation_levels=list(aggregation_levels),
        crop_seasons=[],
        engine_version=FEATURE_ENGINE_VERSION,
        definition_version=FEATURE_CATALOG_CACHED(),
    )
    keyed = {(d.feature_code, d.aggregation_level, d.period_label): d for d in drafts}
    return keyed, not_evaluated, warnings


def FEATURE_CATALOG_CACHED() -> str:
    from app.features.catalog import FEATURE_CATALOG_VERSION

    return FEATURE_CATALOG_VERSION


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_scenario_execution(
    db: Session,
    scenario: dbm.Scenario,
    *,
    idempotency_key: str | None = None,
    created_by: Any = None,
) -> dbm.ScenarioExecutionRun:
    """Validate eligibility, create (or replay) the run, execute it inline."""
    _require_executable(scenario)
    _verify_definition_pins(db, scenario)

    if idempotency_key:
        existing = db.scalar(
            select(dbm.ScenarioExecutionRun).where(
                dbm.ScenarioExecutionRun.scenario_id == scenario.id,
                dbm.ScenarioExecutionRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

    parent_state = db.get(dbm.FieldState, scenario.parent_field_state_id)
    assert parent_state is not None  # _verify_definition_pins guarantees this

    params = _extract_transformations(scenario.canonical_configuration or {})
    delta_c = params["delta_c"]
    multiplier = params["multiplier"]

    window_days = (scenario.period_end - scenario.period_start).days + 1
    if window_days > MAX_EXECUTION_WINDOW_DAYS:
        raise ValidationFailed(
            f"Scenario period exceeds {MAX_EXECUTION_WINDOW_DAYS} days.",
            details=[{"field": "period_end", "reason": "window too long"}],
        )

    manifest = parent_state.observation_manifest or {}
    manifest_sha = parent_state.observation_manifest_sha256 or sha256_of_document(manifest)
    source_observations = _manifest_observations(
        manifest,
        window_start=scenario.period_start,
        window_end=scenario.period_end,
    )

    execution_configuration = _execution_configuration(
        scenario,
        parent_state=parent_state,
        transformations=_transformation_documents(delta_c=delta_c, multiplier=multiplier),
        resource_constraints=params["resource_constraints"],
        aggregation_levels=_aggregation_levels(window_days),
    )
    fingerprint = _input_fingerprint(execution_configuration, manifest_sha)

    existing = db.scalar(
        select(dbm.ScenarioExecutionRun).where(
            dbm.ScenarioExecutionRun.scenario_id == scenario.id,
            dbm.ScenarioExecutionRun.input_fingerprint == fingerprint,
        )
    )
    if existing is not None and existing.run_status != exc.RUN_STATUS_FAILED:
        return existing  # idempotent replay of a live/finished run

    # Resolve the active member's organization and lock its row. A missing
    # organization context retains legacy personal/system behavior; members
    # without a live subscription use the Free entitlement floor. Repeat the
    # replay checks under the lock so concurrent duplicate requests return
    # their winner before consuming quota.
    quota_org_id = scenario_service.lock_scenario_run_quota(db, scenario, created_by)
    if quota_org_id is not None:
        if idempotency_key:
            winner = db.scalar(
                select(dbm.ScenarioExecutionRun).where(
                    dbm.ScenarioExecutionRun.scenario_id == scenario.id,
                    dbm.ScenarioExecutionRun.idempotency_key == idempotency_key,
                )
            )
            if winner is not None:
                return winner
        locked_existing = db.scalar(
            select(dbm.ScenarioExecutionRun).where(
                dbm.ScenarioExecutionRun.scenario_id == scenario.id,
                dbm.ScenarioExecutionRun.input_fingerprint == fingerprint,
            )
        )
        if locked_existing is not None:
            if locked_existing.run_status == exc.RUN_STATUS_FAILED:
                # Keep its prior charge; this new admitted retry receives its
                # own reservation in the upcoming execution-row transaction.
                db.delete(locked_existing)
                db.flush()
            else:
                return locked_existing
        # This upsert remains uncommitted until the new run row is committed
        # below. Failed calculations stay charged because that admission
        # transaction has already committed before execution starts.
        scenario_service.reserve_scenario_run_quota(db, quota_org_id)
    elif existing is not None:
        # Preserve the legacy retry behavior for runs that have no org quota.
        db.delete(existing)
        db.commit()

    now = datetime.now(UTC)
    run = dbm.ScenarioExecutionRun(
        field_id=scenario.field_id,
        scenario_id=scenario.id,
        scenario_version=scenario.scenario_version,
        parent_field_state_id=scenario.parent_field_state_id,
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        scenario_configuration_checksum=scenario.configuration_checksum,
        transformation_engine_version=exc.TRANSFORMATION_ENGINE_VERSION,
        feature_engine_version=FEATURE_ENGINE_VERSION,
        feature_catalog_version=FEATURE_CATALOG_CACHED(),
        source_observation_manifest=manifest,
        source_observation_manifest_sha256=manifest_sha,
        execution_configuration=execution_configuration.model_dump(mode="json"),
        input_fingerprint=fingerprint,
        run_status=exc.RUN_STATUS_QUEUED,
        aggregation_levels=execution_configuration.aggregation_levels,
        hemisphere=execution_configuration.hemisphere,
        calendar_timezone=execution_configuration.timezone,
        resource_constraints=params["resource_constraints"],
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=now,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.ScenarioExecutionRun).where(
                dbm.ScenarioExecutionRun.scenario_id == scenario.id,
                dbm.ScenarioExecutionRun.input_fingerprint == fingerprint,
            )
        )
        if winner is not None:
            return winner
        raise

    _execute_run(
        db,
        run,
        scenario=scenario,
        delta_c=delta_c,
        multiplier=multiplier,
        source_observations=source_observations,
        execution_configuration=execution_configuration,
    )
    return run


def _execute_run(
    db: Session,
    run: dbm.ScenarioExecutionRun,
    *,
    scenario: dbm.Scenario,
    delta_c: float | None,
    multiplier: float | None,
    source_observations: list[dict[str, Any]],
    execution_configuration: exc.ExecutionConfiguration,
) -> None:
    run.run_status = exc.RUN_STATUS_RUNNING
    db.commit()
    try:
        from app.features.catalog import FEATURE_CATALOG_VERSION

        tz = resolve_timezone(run.calendar_timezone)
        window_start = scenario.period_start
        window_end = scenario.period_end

        # ---- transformations (pure) --------------------------------------
        derived_records, unit_exclusions = apply_transformations(
            source_observations, delta_c=delta_c, multiplier=multiplier
        )

        # ---- dependency plan ---------------------------------------------
        plan = plan_scenario_features(delta_c=delta_c, multiplier=multiplier)
        specs = recalculate_specs(delta_c=delta_c, multiplier=multiplier)
        recalc_codes = {s.feature_code for s in specs}

        not_evaluated: dict[str, str] = {}
        warnings: list[str] = [HYPOTHETICAL_DISCLOSURE]
        for code in sorted(plan):
            entry = plan[code]
            if entry["role"] == "exclude_et0":
                not_evaluated[code] = ET0_NOT_EVALUATED_REASON
            elif entry["role"] == "not_affected":
                not_evaluated[code] = entry["reason"]
            elif entry["role"] == "exclude_mixed_inputs":
                not_evaluated[code] = entry["reason"]

        if params_resource := run.resource_constraints:
            warnings.append(
                "Water allocation multiplier "
                f"{list(params_resource.values())[0]} is retained as a "
                "resource-constraint assumption in the execution context; it is "
                "NOT a transformed weather observation."
            )
        if unit_exclusions:
            warnings.append(
                f"{len(unit_exclusions)} source observation(s) were excluded from "
                "transformation because their variable/unit is not eligible; see "
                "run metadata."
            )
        non_daily_supports = sorted(
            {r.time_support for r in derived_records if r.time_support != "daily"}
        )
        if non_daily_supports:
            warnings.append(
                "Transformed observations include non-daily temporal support "
                f"({', '.join(non_daily_supports)}); scenario feature "
                "recalculation supports daily-source features — aggregated-"
                "source features are reported as not_evaluated (engine "
                "limitation, disclosed)."
            )

        synthetic_count = sum(1 for r in derived_records if r.is_synthetic)
        if synthetic_count:
            warnings.append(
                f"SYNTHETIC SOURCE: {synthetic_count} of {len(derived_records)} "
                "transformed observations derive from synthetic fixture data — "
                "values are for demonstration/testing only."
            )

        # ---- baseline pass (original values, full compatible spec set) ----
        baseline_specs = list(FEATURE_CATALOG.values())
        baseline_keyed, baseline_not_evaluated, baseline_warnings = _run_engine_pass(
            observations=source_observations,
            specs=baseline_specs,
            tz=tz,
            hemisphere=run.hemisphere,
            window_start=window_start,
            window_end=window_end,
            aggregation_levels=run.aggregation_levels,
        )

        # ---- scenario pass (transformed values, recalculate set only) -----
        scenario_obs = [_as_engine_observation(r) for r in derived_records]
        if specs:
            scenario_keyed, scenario_not_evaluated, scenario_warnings = _run_engine_pass(
                observations=scenario_obs,
                specs=specs,
                tz=tz,
                hemisphere=run.hemisphere,
                window_start=window_start,
                window_end=window_end,
                aggregation_levels=run.aggregation_levels,
            )
        else:
            scenario_keyed, scenario_not_evaluated, scenario_warnings = {}, {}, []

        for code, reason in scenario_not_evaluated.items():
            not_evaluated.setdefault(code, reason)
        warnings.extend(baseline_warnings)
        warnings.extend(scenario_warnings)

        # ---- persist derived observations ---------------------------------
        derived_row_ids: dict[str, str] = {}
        obs_rows: list[dbm.ScenarioDerivedObservation] = []
        for rec in derived_records:
            row_id = uuid_mod.uuid4()
            derived_row_ids[rec.source_observation_id] = str(row_id)
            obs_rows.append(
                dbm.ScenarioDerivedObservation(
                    id=row_id,
                    execution_run_id=run.id,
                    source_observation_id=uuid_mod.UUID(rec.source_observation_id),
                    dataset_product_id=(
                        uuid_mod.UUID(rec.dataset_product_id)
                        if rec.dataset_product_id
                        else None
                    ),
                    variable_code=rec.variable_code,
                    baseline_value=rec.baseline_value,
                    transformed_value=rec.value,
                    unit=rec.unit or "",
                    observed_at=rec.observed_at,
                    period_start=rec.period_start,
                    period_end=rec.period_end,
                    time_support=rec.time_support,
                    spatial_support_type=rec.spatial_support_type,
                    spatial_resolution_m=rec.spatial_resolution_m,
                    transformation_code=rec.transformation_code,
                    transformation_parameter=rec.transformation_parameter,
                    evidence_class=rec.evidence_class,
                    source_evidence_class=rec.source_evidence_class,
                    is_synthetic=rec.is_synthetic,
                    quality_status=rec.quality_status,
                    source_metadata=rec.source_metadata,
                )
            )
        for row in obs_rows:
            db.add(row)

        # ---- persist derived features -------------------------------------
        feature_rows: list[dbm.ScenarioDerivedFeature] = []
        feature_checksum_rows: list[dict[str, Any]] = []

        for key in sorted(scenario_keyed):
            draft = scenario_keyed[key]
            baseline = baseline_keyed.get(key)
            difference = None
            percent = None
            if draft.value is not None and baseline is not None and baseline.value is not None:
                difference = draft.value - baseline.value
                if baseline.value != 0:
                    percent = (difference / abs(baseline.value)) * 100.0
            uncertainty_meta = {
                "source_uncertainty": (
                    {"value": draft.uncertainty_value, "type": draft.uncertainty_type}
                    if draft.uncertainty_value is not None
                    else None
                ),
                "transformation_assumption": {
                    "class": "user_defined_hypothetical",
                    "note": (
                        "Deterministic transformation of the configured "
                        "adjustment; adds no numerical uncertainty to the "
                        "source data."
                    ),
                },
                "missing_evidence_note": (
                    "No defensible quantitative uncertainty calculation exists "
                    "for scenario transformations; the source dataset's own "
                    "uncertainty flags travel unchanged."
                ),
                "provenance": draft.provenance,
                "baseline_reference": draft.baseline_reference,
            }
            row = dbm.ScenarioDerivedFeature(
                execution_run_id=run.id,
                feature_code=draft.feature_code,
                feature_name=FEATURE_CATALOG[draft.feature_code].name,
                unit=draft.unit,
                aggregation_level=draft.aggregation_level,
                period_label=draft.period_label,
                period_start=draft.period_start,
                period_end=draft.period_end,
                baseline_value=baseline.value if baseline is not None else None,
                scenario_value=draft.value,
                difference_value=difference,
                difference_percent=percent,
                feature_specification_version=FEATURE_CATALOG_VERSION,
                evidence_status=exc.FEATURE_EVIDENCE_RECALCULATED,
                quality_status=draft.quality_status,
                coverage_ratio=draft.coverage_ratio,
                n_input=draft.n_input,
                n_missing=draft.n_missing,
                uncertainty_metadata=uncertainty_meta,
            )
            feature_rows.append(row)
            feature_checksum_rows.append(
                {
                    "feature_code": draft.feature_code,
                    "aggregation_level": draft.aggregation_level,
                    "period_label": draft.period_label,
                    "baseline_value": baseline.value if baseline is not None else None,
                    "scenario_value": draft.value,
                    "difference_value": difference,
                    "difference_percent": percent,
                    "unit": draft.unit,
                    "quality_status": draft.quality_status,
                    "evidence_status": exc.FEATURE_EVIDENCE_RECALCULATED,
                }
            )

        # Explicit status rows for excluded features (never fabricated values).
        excluded_codes = sorted(
            code for code, entry in plan.items() if entry["role"] != "recalculate"
        )
        for code in excluded_codes:
            entry = plan[code]
            row = dbm.ScenarioDerivedFeature(
                execution_run_id=run.id,
                feature_code=code,
                feature_name=FEATURE_CATALOG[code].name,
                unit=FEATURE_CATALOG[code].unit,
                aggregation_level=entry["aggregation_levels"][0]
                if entry["aggregation_levels"]
                else "summary",
                period_label="run_window",
                period_start=window_start,
                period_end=window_end,
                baseline_value=None,
                scenario_value=None,
                difference_value=None,
                difference_percent=None,
                feature_specification_version=entry["specification_version"],
                evidence_status=(
                    exc.FEATURE_EVIDENCE_NOT_AFFECTED
                    if entry["role"] == "not_affected"
                    else exc.FEATURE_EVIDENCE_NOT_EVALUATED
                ),
                uncertainty_metadata={
                    "reason": entry["reason"],
                    "role": entry["role"],
                    "required_variables": entry["required_variables"],
                },
            )
            feature_rows.append(row)
            feature_checksum_rows.append(
                {
                    "feature_code": code,
                    "aggregation_level": row.aggregation_level,
                    "period_label": "run_window",
                    "baseline_value": None,
                    "scenario_value": None,
                    "difference_value": None,
                    "difference_percent": None,
                    "unit": row.unit,
                    "quality_status": None,
                    "evidence_status": row.evidence_status,
                }
            )

        for row in feature_rows:
            db.add(row)

        # ---- output checksum (canonical, stable) --------------------------
        obs_checksum_rows = sorted(
            (r.to_checksum_row() for r in derived_records),
            key=lambda d: (
                d["variable_code"],
                str(d["period_start"]),
                d["source_observation_id"],
            ),
        )
        feature_checksum_rows.sort(
            key=lambda d: (d["feature_code"], d["aggregation_level"], d["period_label"])
        )
        payload = exc.execution_checksum_payload(
            execution_configuration=execution_configuration.model_dump(mode="json"),
            parent_snapshot_checksum=run.parent_snapshot_checksum,
            source_observation_manifest_sha256=run.source_observation_manifest_sha256,
            scenario_configuration_checksum=run.scenario_configuration_checksum,
            scenario_version=run.scenario_version,
            transformation_engine_version=run.transformation_engine_version,
            feature_engine_version=run.feature_engine_version,
            feature_catalog_version=run.feature_catalog_version,
            derived_observations=obs_checksum_rows,
            derived_features=feature_checksum_rows,
            not_evaluated_reasons=not_evaluated,
            warnings=warnings,
        )
        output_checksum = sha256_of_document(exc.canonical_value(payload))

        run.records_written = len(obs_rows) + len(feature_rows)
        run.transformed_observation_count = len(obs_rows)
        run.derived_feature_count = len(feature_rows)
        run.warnings = warnings[:100]
        run.not_evaluated_reasons = not_evaluated
        run.output_checksum = output_checksum
        run.run_status = (
            exc.RUN_STATUS_COMPLETED_WITH_LIMITATIONS
            if (not_evaluated or warnings_excluding_disclosure(warnings))
            else exc.RUN_STATUS_SUCCEEDED
        )
        run.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc_:  # noqa: BLE001 — run lifecycle must capture failures
        db.rollback()
        run.run_status = exc.RUN_STATUS_FAILED
        run.error_summary = f"{type(exc_).__name__}: {exc_}"
        run.completed_at = datetime.now(UTC)
        db.commit()
        logger.exception("scenario execution failed", extra={"run_id": str(run.id)})


def warnings_excluding_disclosure(warnings: list[str]) -> bool:
    """True when any warning beyond the standard hypothetical disclosure exists."""
    return any(w != HYPOTHETICAL_DISCLOSURE for w in warnings)


# ---------------------------------------------------------------------------
# Verification (independent re-check of a stored run)
# ---------------------------------------------------------------------------


def verify_execution(db: Session, run: dbm.ScenarioExecutionRun) -> dict[str, Any]:
    """Recompute the output checksum from persisted artifacts and compare."""
    obs_rows = db.execute(
        select(dbm.ScenarioDerivedObservation)
        .where(dbm.ScenarioDerivedObservation.execution_run_id == run.id)
        .order_by(
            dbm.ScenarioDerivedObservation.variable_code,
            dbm.ScenarioDerivedObservation.period_start,
            dbm.ScenarioDerivedObservation.source_observation_id,
        )
    ).scalars().all()
    feature_rows = db.execute(
        select(dbm.ScenarioDerivedFeature)
        .where(dbm.ScenarioDerivedFeature.execution_run_id == run.id)
        .order_by(
            dbm.ScenarioDerivedFeature.feature_code,
            dbm.ScenarioDerivedFeature.aggregation_level,
            dbm.ScenarioDerivedFeature.period_label,
        )
    ).scalars().all()

    obs_checksum_rows = sorted(
        (
            {
                "source_observation_id": str(r.source_observation_id),
                "variable_code": r.variable_code,
                "baseline_value": r.baseline_value,
                "value": r.transformed_value,
                "unit": r.unit,
                "observed_at": str(r.observed_at),
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "time_support": r.time_support,
                "transformation_code": r.transformation_code,
                "transformation_parameter": r.transformation_parameter,
                "quality_status": r.quality_status,
                "is_synthetic": r.is_synthetic,
            }
            for r in obs_rows
        ),
        key=lambda d: (d["variable_code"], d["period_start"], d["source_observation_id"]),
    )
    feature_checksum_rows = sorted(
        (
            {
                "feature_code": r.feature_code,
                "aggregation_level": r.aggregation_level,
                "period_label": r.period_label,
                "baseline_value": r.baseline_value,
                "scenario_value": r.scenario_value,
                "difference_value": r.difference_value,
                "difference_percent": r.difference_percent,
                "unit": r.unit,
                "quality_status": r.quality_status,
                "evidence_status": r.evidence_status,
            }
            for r in feature_rows
        ),
        key=lambda d: (d["feature_code"], d["aggregation_level"], d["period_label"]),
    )
    payload = exc.execution_checksum_payload(
        execution_configuration=run.execution_configuration,
        parent_snapshot_checksum=run.parent_snapshot_checksum,
        source_observation_manifest_sha256=run.source_observation_manifest_sha256,
        scenario_configuration_checksum=run.scenario_configuration_checksum,
        scenario_version=run.scenario_version,
        transformation_engine_version=run.transformation_engine_version,
        feature_engine_version=run.feature_engine_version,
        feature_catalog_version=run.feature_catalog_version,
        derived_observations=obs_checksum_rows,
        derived_features=feature_checksum_rows,
        not_evaluated_reasons=run.not_evaluated_reasons or {},
        warnings=run.warnings or [],
    )
    recomputed = sha256_of_document(exc.canonical_value(payload))

    scenario = db.get(dbm.Scenario, run.scenario_id)
    parent_state = db.get(dbm.FieldState, run.parent_field_state_id)
    return {
        "run_id": str(run.id),
        "run_status": run.run_status,
        "output_checksum_valid": run.output_checksum == recomputed,
        "expected_output_checksum": recomputed,
        "stored_output_checksum": run.output_checksum,
        "scenario_definition_checksum_valid": (
            scenario is not None
            and scenario.configuration_checksum == run.scenario_configuration_checksum
        ),
        "parent_snapshot_intact": (
            parent_state is not None
            and parent_state.checksum_sha256 == run.parent_snapshot_checksum
        ),
        "manifest_checksum_matches_run": (
            parent_state is not None
            and parent_state.observation_manifest_sha256 == run.source_observation_manifest_sha256
        ),
        "verified_at": datetime.now(UTC).isoformat(),
        "note": (
            "Verification recomputes the execution checksum from persisted "
            "derived artifacts and re-checks the parent pins. It confirms "
            "integrity and reproducibility of the HYPOTHETICAL calculation — "
            "never that the transformed values are observations."
        ),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def run_payload(run: dbm.ScenarioExecutionRun, *, scenario: dbm.Scenario | None = None) -> dict[str, Any]:
    plan_note = (
        "An execution is a derived hypothetical calculation. Transformed values "
        "never enter the observation record; parent artifacts are untouched."
    )
    return {
        "run_id": str(run.id),
        "scenario_id": str(run.scenario_id),
        "scenario_version": run.scenario_version,
        "field_id": str(run.field_id),
        "parent_field_state_id": str(run.parent_field_state_id),
        "parent_snapshot_checksum": run.parent_snapshot_checksum,
        "scenario_configuration_checksum": run.scenario_configuration_checksum,
        "transformation_engine_version": run.transformation_engine_version,
        "feature_engine_version": run.feature_engine_version,
        "feature_catalog_version": run.feature_catalog_version,
        "input_fingerprint": run.input_fingerprint,
        "run_status": run.run_status,
        "aggregation_levels": run.aggregation_levels,
        "hemisphere": run.hemisphere,
        "calendar_timezone": run.calendar_timezone,
        "output_checksum": run.output_checksum,
        "records_written": run.records_written,
        "transformed_observation_count": run.transformed_observation_count,
        "derived_feature_count": run.derived_feature_count,
        "warnings": run.warnings or [],
        "not_evaluated_reasons": run.not_evaluated_reasons or {},
        "resource_constraints": run.resource_constraints or {},
        "execution_configuration": run.execution_configuration or {},
        "error_summary": run.error_summary,
        "idempotency_key": run.idempotency_key,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "evidence_note": plan_note,
    }


def derived_observation_payload(row: dbm.ScenarioDerivedObservation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "execution_run_id": str(row.execution_run_id),
        "source_observation_id": str(row.source_observation_id),
        "dataset_product_id": str(row.dataset_product_id) if row.dataset_product_id else None,
        "variable_code": row.variable_code,
        "baseline_value": row.baseline_value,
        "transformed_value": row.transformed_value,
        "unit": row.unit,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "time_support": row.time_support,
        "spatial_support_type": row.spatial_support_type,
        "spatial_resolution_m": row.spatial_resolution_m,
        "transformation_code": row.transformation_code,
        "transformation_parameter": row.transformation_parameter,
        "evidence_class": row.evidence_class,
        "source_evidence_class": row.source_evidence_class,
        "is_synthetic": row.is_synthetic,
        "quality_status": row.quality_status,
        "source_metadata": row.source_metadata or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def derived_feature_payload(row: dbm.ScenarioDerivedFeature) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "execution_run_id": str(row.execution_run_id),
        "feature_code": row.feature_code,
        "feature_name": row.feature_name,
        "unit": row.unit,
        "aggregation_level": row.aggregation_level,
        "period_label": row.period_label,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "baseline_value": row.baseline_value,
        "scenario_value": row.scenario_value,
        "difference_value": row.difference_value,
        "difference_percent": row.difference_percent,
        "feature_specification_version": row.feature_specification_version,
        "evidence_status": row.evidence_status,
        "quality_status": row.quality_status,
        "coverage_ratio": row.coverage_ratio,
        "n_input": row.n_input,
        "n_missing": row.n_missing,
        "uncertainty_metadata": row.uncertainty_metadata or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def comparison_payload(rows: list[dbm.ScenarioDerivedFeature], run: dbm.ScenarioExecutionRun) -> dict[str, Any]:
    """Definition-safe baseline-vs-scenario comparison document."""
    recalculated = [r for r in rows if r.evidence_status == exc.FEATURE_EVIDENCE_RECALCULATED]
    changed = [r for r in recalculated if r.difference_value not in (None, 0.0)]
    return {
        "run_id": str(run.id),
        "run_status": run.run_status,
        "output_checksum": run.output_checksum,
        "summary": {
            "recalculated_comparisons": len(recalculated),
            "changed_values": len(changed),
            "unchanged_values": len(recalculated) - len(changed),
            "not_affected_features": sum(
                1 for r in rows if r.evidence_status == exc.FEATURE_EVIDENCE_NOT_AFFECTED
            ),
            "not_evaluated_features": sum(
                1 for r in rows if r.evidence_status == exc.FEATURE_EVIDENCE_NOT_EVALUATED
            ),
        },
        "rows": [derived_feature_payload(r) for r in rows],
        "note": (
            "Comparison is between two in-process engine passes over the SAME "
            "window: original observations vs scenario-transformed "
            "observations. Percentage difference is omitted when the baseline "
            "is zero or the comparison is invalid. No forecast or projection "
            "is implied."
        ),
    }

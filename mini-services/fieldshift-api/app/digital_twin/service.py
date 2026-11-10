"""Digital twin assembly & validation (Milestone 7.7).

The twin is a TRACEABLE field-level representation that connects:

    field identity / boundary versions
        → immutable Field State snapshots (checksummed)
        → observations & provenance → derived features
        → finalized scenarios → M7.3 scenario executions
        → M7.4 sensitivity analyses
        → M7.5 robust rotation runs → M7.6 decision documents

Honesty rules (docs/m7/m7_7/M7_7_ARCHITECTURE.md):

- The twin is NOT a decorative dashboard: every section links to the
  underlying artifact ids and checksums, and validation re-verification
  results are persisted as immutable records.
- Observed / transformed / calculated information classes are distinguished
  everywhere; scenario derivatives are always labelled hypothetical.
- Maturity is classified from IMPLEMENTED capabilities only — no predictive,
  autonomous or forecasting claims (no such infrastructure exists).
- Validation walks reuse the EXISTING per-artifact verifiers (field states,
  executions, analyses, robust runs, decision documents) — no verification
  logic is duplicated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.field_state.manifest import sha256_of_document
from app.digital_twin import contracts as tc

logger = logging.getLogger("croptwist.digital_twin")

TWIN_SNAPSHOT_VERSION = "digital-twin-view-1.0"


def _verdict(checks: list[tuple[str, bool]]) -> tuple[bool, list[str]]:
    """Uniform verdict from a verifier report's boolean flags: verified only
    when EVERY integrity flag holds; findings name each failing flag."""
    findings = [name for name, ok in checks if not ok]
    return (not findings), findings


def _verdict_field_state(report: dict[str, Any]) -> tuple[bool, list[str]]:
    return _verdict(
        [
            ("checksum_valid", bool(report.get("checksum_valid"))),
            ("manifest_checksum_valid", bool(report.get("manifest_checksum_valid"))),
            ("boundary_version_record_exists", bool(report.get("boundary_version_record_exists"))),
            (
                "referenced_artifacts_intact",
                all(
                    (a.get("intact", True) if isinstance(a, dict) else True)
                    for a in (report.get("referenced_artifacts", {}) or {}).values()
                ),
            ),
        ]
    )


def _verdict_scenario(report: dict[str, Any]) -> tuple[bool, list[str]]:
    latest = report.get("latest_validation")
    checks = [
        ("configuration_checksum_valid", bool(report.get("configuration_checksum_valid"))),
        ("parent_state_exists", bool(report.get("parent_state_exists"))),
        ("parent_snapshot_checksum_matches", bool(report.get("parent_snapshot_checksum_matches"))),
        ("boundary_version_record_exists", bool(report.get("boundary_version_record_exists"))),
    ]
    if latest is not None:
        checks.append(
            (
                "latest_validation_matches_configuration",
                bool(latest.get("matches_current_configuration", True)),
            )
        )
    return _verdict(checks)


def _verdict_execution(report: dict[str, Any]) -> tuple[bool, list[str]]:
    return _verdict(
        [
            ("output_checksum_valid", bool(report.get("output_checksum_valid"))),
            ("scenario_definition_checksum_valid", bool(report.get("scenario_definition_checksum_valid"))),
            ("parent_snapshot_intact", bool(report.get("parent_snapshot_intact"))),
            ("manifest_checksum_matches_run", bool(report.get("manifest_checksum_matches_run"))),
        ]
    )


def _verdict_analysis(report: dict[str, Any]) -> tuple[bool, list[str]]:
    return _verdict(
        [
            ("output_checksum_valid", bool(report.get("output_checksum_valid"))),
            ("source_run_intact", bool(report.get("source_run_intact"))),
            ("parent_snapshot_intact", bool(report.get("parent_snapshot_intact"))),
            ("manifest_checksum_matches", bool(report.get("manifest_checksum_matches"))),
            (
                "reference_reproduction_consistent",
                bool(report.get("reference_reproduction_consistent")),
            ),
        ]
    )


RESULT_RUN_STATUSES = ("succeeded", "completed_with_limitations")
RESULT_ANALYSIS_STATUSES = ("succeeded", "completed_with_limitations")
RESULT_DOC_STATUSES = ("succeeded", "completed_with_limitations")


# ---------------------------------------------------------------------------
# Field-level view (read-only assembly)
# ---------------------------------------------------------------------------


def build_field_twin(db: Session, field: dbm.Field) -> dict[str, Any]:
    farm = db.get(dbm.Farm, field.farm_id)
    latest_boundary = db.scalar(
        select(dbm.FieldBoundaryVersion)
        .where(dbm.FieldBoundaryVersion.field_id == field.id)
        .order_by(dbm.FieldBoundaryVersion.version_number.desc())
        .limit(1)
    )

    states = db.scalars(
        select(dbm.FieldState)
        .where(dbm.FieldState.field_id == field.id)
        .order_by(dbm.FieldState.created_at.desc())
        .limit(tc.MAX_STATES)
    ).all()
    state_count = db.scalar(
        select(func.count()).select_from(dbm.FieldState).where(dbm.FieldState.field_id == field.id)
    )

    # observation coverage per variable
    coverage_rows = db.execute(
        select(
            dbm.Observation.variable_code,
            func.count().label("n"),
            func.min(dbm.Observation.observed_at).label("first_at"),
            func.max(dbm.Observation.observed_at).label("last_at"),
        )
        .where(dbm.Observation.field_id == field.id)
        .group_by(dbm.Observation.variable_code)
        .order_by(dbm.Observation.variable_code.asc())
    ).all()
    coverage = []
    now = datetime.now(UTC)
    for row in coverage_rows:
        last = row.last_at
        freshness_days = (
            round((now - (last if last.tzinfo else last.replace(tzinfo=UTC))).total_seconds() / 86400, 1)
            if last
            else None
        )
        coverage.append(
            {
                "variable_code": row.variable_code,
                "observation_count": row.n,
                "first_observed_at": row.first_at.isoformat() if row.first_at else None,
                "last_observed_at": last.isoformat() if last else None,
                "freshness_days": freshness_days,
            }
        )

    feature_runs = db.scalars(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field.id)
        .order_by(dbm.FeatureRun.created_at.desc())
        .limit(tc.MAX_FEATURE_RUNS)
    ).all()

    scenarios = db.scalars(
        select(dbm.Scenario)
        .where(dbm.Scenario.field_id == field.id)
        .order_by(dbm.Scenario.created_at.desc())
        .limit(tc.MAX_SCENARIOS)
    ).all()
    scenario_tree = []
    for s in scenarios:
        executions = db.scalars(
            select(dbm.ScenarioExecutionRun)
            .where(dbm.ScenarioExecutionRun.scenario_id == s.id)
            .order_by(dbm.ScenarioExecutionRun.created_at.desc())
            .limit(tc.MAX_EXECUTIONS_PER_SCENARIO)
        ).all()
        scenario_tree.append(
            {
                "scenario_id": str(s.id),
                "name": s.name,
                "scenario_type": s.scenario_type,
                "evidence_classification": s.evidence_classification,
                "scenario_status": s.scenario_status,
                "scenario_version": s.scenario_version,
                "lineage_kind": s.lineage_kind,
                "parent_scenario_id": str(s.parent_scenario_id) if s.parent_scenario_id else None,
                "configuration_checksum": s.configuration_checksum,
                "period": {"start": s.period_start.isoformat(), "end": s.period_end.isoformat()},
                "executions": [
                    {
                        "execution_run_id": str(r.id),
                        "run_status": r.run_status,
                        "output_checksum": r.output_checksum,
                        "input_fingerprint": r.input_fingerprint,
                    }
                    for r in executions
                ],
            }
        )

    # information-class census (observed vs transformed vs calculated)
    observed_count = db.scalar(
        select(func.count()).select_from(dbm.Observation).where(dbm.Observation.field_id == field.id)
    )
    transformed_count = 0
    if scenarios:
        run_ids = db.scalars(
            select(dbm.ScenarioExecutionRun.id).where(dbm.ScenarioExecutionRun.field_id == field.id)
        ).all()
        if run_ids:
            transformed_count = db.scalar(
                select(func.count())
                .select_from(dbm.ScenarioDerivedObservation)
                .where(dbm.ScenarioDerivedObservation.execution_run_id.in_(run_ids))
            )
    calculated_count = db.scalar(
        select(func.count()).select_from(dbm.FeatureValue).where(dbm.FeatureValue.field_id == field.id)
    )

    sensitivity_by_run = (
        db.execute(
            select(
                dbm.SensitivityAnalysis.source_execution_run_id,
                func.count().label("n"),
            )
            .where(dbm.SensitivityAnalysis.field_id == field.id)
            .group_by(dbm.SensitivityAnalysis.source_execution_run_id)
        ).all()
    )

    robust_summary = _robust_summary(db, field)
    decisions = db.scalars(
        select(dbm.DecisionComparison)
        .where(dbm.DecisionComparison.field_id == field.id)
        .order_by(dbm.DecisionComparison.created_at.desc())
        .limit(tc.MAX_DECISION_DOCS)
    ).all()

    soil_mgmt = _soil_management_summary(db, field)
    capabilities = _capability_matrix(db, field)
    twin = {
        "view_version": TWIN_SNAPSHOT_VERSION,
        "generated_at": now.isoformat(),
        "field_identity": {
            "field_id": str(field.id),
            "field_name": field.name,
            "area_ha": float(field.area_ha) if field.area_ha is not None else None,
            "farm_id": str(field.farm_id),
            "farm_name": farm.name if farm else None,
            "country_code": farm.country_code if farm else None,
            "latest_boundary_version": latest_boundary.version_number if latest_boundary else None,
            "note": "Field identity and boundary versions are append-only (immutable history).",
        },
        "field_states": {
            "total": state_count,
            "items": [
                {
                    "field_state_id": str(s.id),
                    "status": s.status,
                    "period": {
                        "start": s.period_start.isoformat() if s.period_start else None,
                        "end": s.period_end.isoformat() if s.period_end else None,
                    },
                    "snapshot_checksum": s.checksum_sha256,
                    "boundary_version": s.boundary_version,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in states
            ],
            "note": (
                "Snapshots are immutable; the manifest is stored next to its hash "
                "so checksums stay verifiable without the original query."
            ),
        },
        "observation_coverage": {
            "variables": coverage,
            "note": "Freshness is days since the last observation — a data-age indicator, not a forecast.",
        },
        "feature_runs": [
            {
                "run_id": str(r.id),
                "status": r.status,
                "feature_engine_version": r.feature_engine_version,
                "is_synthetic": r.is_synthetic,
                "period": {
                    "start": r.period_start.isoformat() if r.period_start else None,
                    "end": r.period_end.isoformat() if r.period_end else None,
                },
            }
            for r in feature_runs
        ],
        "scenarios": scenario_tree,
        "sensitivity_analyses": [
            {"source_execution_run_id": str(row.source_execution_run_id), "analysis_count": row.n}
            for row in sensitivity_by_run
        ],
        "robust_rotation": robust_summary,
        "decision_documents": [
            {
                "decision_comparison_id": str(d.id),
                "title": d.title,
                "doc_status": d.doc_status,
                "document_checksum": d.document_checksum,
            }
            for d in decisions
        ],
        "soil_management": soil_mgmt,
        "information_classes": {
            "observed_observations": observed_count,
            "scenario_derived_transformed_observations": transformed_count,
            "calculated_feature_values": calculated_count,
            "note": (
                "Observed = real-world measurements; transformed = scenario "
                "derivatives (hypothetical, never merged into the observation "
                "record); calculated = feature-engine outputs."
            ),
        },
        "capabilities": capabilities,
        "maturity": _maturity_classification(capabilities),
        "prohibitions_note": (
            "This digital twin claims NO predictive, autonomous or forecasting "
            "capability. Climate projections and weather forecasts are not "
            "implemented; none are implied by any section."
        ),
    }
    return twin


def _soil_management_summary(db: Session, field: dbm.Field) -> dict[str, Any]:
    """M6B/M6C artifact inventory: record counts + run/plan artifacts with lineage.

    Record counts are observed-input presence; run artifacts carry status and the
    stored checksum where the producing module computes one (M6B). M6C artifacts
    store no checksum today — reported as None, never fabricated.
    """
    records = {}
    for model, key in (
        (dbm.SoilSamplingEvent, "soil_sampling_events"),
        (dbm.SoilSample, "soil_samples"),
        (dbm.SoilMeasurement, "soil_measurements"),
        (dbm.SoilManagementEvent, "soil_management_events"),
        (dbm.NutrientApplication, "nutrient_applications"),
        (dbm.NutrientRemoval, "nutrient_removals"),
        (dbm.SoilCoverObservation, "soil_cover_observations"),
        (dbm.ResidueRecord, "residue_records"),
        (dbm.FieldOperation, "field_operations"),
    ):
        records[key] = db.scalar(
            select(func.count()).select_from(model).where(model.field_id == field.id)
        )

    run_artifacts = []
    for model, kind in (
        (dbm.SoilAssessmentRun, "soil_assessment"),
        (dbm.SocStockRun, "soc_stock"),
        (dbm.NutrientBudgetRun, "nutrient_budget"),
        (dbm.CoverCropPlan, "cover_crop_plan"),
        (dbm.ErosionAssessmentRun, "erosion_assessment"),
        (dbm.OperationScheduleRun, "operation_schedule"),
        (dbm.ManagementPlan, "management_plan"),
    ):
        rows = db.scalars(
            select(model)
            .where(model.field_id == field.id)
            .order_by(model.created_at.desc())
            .limit(tc.MAX_SOIL_MGMT_RUNS)
        ).all()
        for r in rows:
            run_artifacts.append(
                {
                    "artifact_kind": kind,
                    "artifact_id": str(r.id),
                    "label": r.label,
                    "status": r.status,
                    "checksum_sha256": getattr(r, "checksum_sha256", None),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )

    return {
        "records": records,
        "run_artifacts": run_artifacts,
        "note": (
            "M6B/M6C artifacts are observed-input records and deterministic "
            "assessments/plans. Checksums are shown only where the producing "
            "module stores one; absence is reported, never synthesized."
        ),
    }


def _robust_summary(db: Session, field: dbm.Field) -> dict[str, Any]:
    sets = db.scalars(
        select(dbm.ScenarioSet)
        .where(dbm.ScenarioSet.field_id == field.id)
        .order_by(dbm.ScenarioSet.created_at.desc())
        .limit(tc.MAX_SCENARIO_SETS)
    ).all()
    out = []
    for s in sets:
        runs = db.scalars(
            select(dbm.RobustRotationRun)
            .where(dbm.RobustRotationRun.scenario_set_id == s.id)
            .order_by(dbm.RobustRotationRun.created_at.desc())
            .limit(tc.MAX_ROBUST_RUNS_PER_SET)
        ).all()
        out.append(
            {
                "scenario_set_id": str(s.id),
                "label": s.label,
                "set_checksum": s.set_checksum,
                "member_count": s.member_count,
                "robust_runs": [
                    {
                        "robust_run_id": str(r.id),
                        "run_status": r.run_status,
                        "solver_status": r.solver_status,
                        "output_checksum": r.output_checksum,
                    }
                    for r in runs
                ],
            }
        )
    return {"scenario_sets": out}


def _capability_matrix(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    """Implemented capabilities with DATA READINESS from actual row presence."""
    has_feature_run = db.scalar(
        select(dbm.FeatureRun.id)
        .where(dbm.FeatureRun.field_id == field.id, dbm.FeatureRun.status == "succeeded")
        .limit(1)
    )
    has_state = db.scalar(
        select(dbm.FieldState.id).where(dbm.FieldState.field_id == field.id).limit(1)
    )
    has_finalized = db.scalar(
        select(dbm.Scenario.id).where(
            dbm.Scenario.field_id == field.id, dbm.Scenario.scenario_status == "finalized"
        ).limit(1)
    )
    has_execution = db.scalar(
        select(dbm.ScenarioExecutionRun.id).where(
            dbm.ScenarioExecutionRun.field_id == field.id,
            dbm.ScenarioExecutionRun.run_status.in_(RESULT_RUN_STATUSES),
        ).limit(1)
    )
    has_analysis = db.scalar(
        select(dbm.SensitivityAnalysis.id).where(
            dbm.SensitivityAnalysis.field_id == field.id,
            dbm.SensitivityAnalysis.analysis_status.in_(RESULT_ANALYSIS_STATUSES),
        ).limit(1)
    )
    has_robust = db.scalar(
        select(dbm.RobustRotationRun.id).where(
            dbm.RobustRotationRun.field_id == field.id,
            dbm.RobustRotationRun.run_status.in_(RESULT_RUN_STATUSES),
        ).limit(1)
    )
    has_decision = db.scalar(
        select(dbm.DecisionComparison.id).where(
            dbm.DecisionComparison.field_id == field.id,
            dbm.DecisionComparison.doc_status.in_(RESULT_DOC_STATUSES),
        ).limit(1)
    )
    has_rotation = db.scalar(
        select(dbm.RotationRun.id).where(
            dbm.RotationRun.field_id == field.id, dbm.RotationRun.status == "succeeded"
        ).limit(1)
    )
    has_water = db.scalar(
        select(dbm.WaterPlan.id).where(
            dbm.WaterPlan.field_id == field.id, dbm.WaterPlan.status == "succeeded"
        ).limit(1)
    )
    has_soil_data = db.scalar(
        select(dbm.SoilMeasurement.id).where(dbm.SoilMeasurement.field_id == field.id).limit(1)
    )
    has_soil_run = db.scalar(
        select(dbm.SoilAssessmentRun.id).where(
            dbm.SoilAssessmentRun.field_id == field.id,
            dbm.SoilAssessmentRun.status == "succeeded",
        ).limit(1)
    )
    has_mgmt_artifact = db.scalar(
        select(dbm.ManagementPlan.id).where(
            dbm.ManagementPlan.field_id == field.id,
            dbm.ManagementPlan.status == "succeeded",
        ).limit(1)
    ) or db.scalar(
        select(dbm.CoverCropPlan.id).where(
            dbm.CoverCropPlan.field_id == field.id,
            dbm.CoverCropPlan.status == "succeeded",
        ).limit(1)
    ) or db.scalar(
        select(dbm.ErosionAssessmentRun.id).where(
            dbm.ErosionAssessmentRun.field_id == field.id,
            dbm.ErosionAssessmentRun.status == "succeeded",
        ).limit(1)
    ) or db.scalar(
        select(dbm.OperationScheduleRun.id).where(
            dbm.OperationScheduleRun.field_id == field.id,
            dbm.OperationScheduleRun.status.in_(("succeeded", "infeasible")),
        ).limit(1)
    )
    entries = [
        ("field_state_snapshots", "M7.1", True, bool(has_state), "needs a computed field state snapshot"),
        ("feature_engineering", "M4", True, bool(has_feature_run), "needs a succeeded feature run"),
        ("rotation_optimization", "M5", True, bool(has_rotation), "needs a succeeded rotation run"),
        ("water_planning", "M6A", True, bool(has_water), "needs a succeeded water plan"),
        ("soil_health_intelligence", "M6B", True, bool(has_soil_data or has_soil_run), "needs soil measurements or a succeeded soil assessment"),
        ("field_management_intelligence", "M6C", True, bool(has_mgmt_artifact), "needs a succeeded cover-crop/erosion/schedule/management artifact"),
        ("scenario_domain", "M7.2", True, bool(has_finalized), "needs a field state and a finalized scenario"),
        ("scenario_execution", "M7.3", True, bool(has_execution), "needs an executed scenario"),
        ("sensitivity_uncertainty", "M7.4", True, bool(has_analysis), "needs a sensitivity analysis"),
        ("robust_rotation", "M7.5", True, bool(has_robust), "needs a scenario set + robust run"),
        ("decision_intelligence", "M7.6", True, bool(has_decision), "needs a decision document"),
        ("digital_twin_view", "M7.7", True, True, None),
    ]
    matrix = []
    for code, milestone, implemented, ready, prerequisite in entries:
        matrix.append(
            {
                "capability": code,
                "milestone": milestone,
                "implemented": implemented,
                "data_ready": ready if implemented else False,
                "readiness": "ready" if (implemented and ready) else ("prerequisite_missing" if implemented else "not_implemented"),
                "prerequisite": prerequisite,
            }
        )
    return matrix


def _maturity_classification(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    implemented = [c["capability"] for c in capabilities if c["implemented"]]
    not_implemented = [c["capability"] for c in capabilities if not c["implemented"]]
    ready = [c["capability"] for c in capabilities if c["implemented"] and c["data_ready"]]
    return {
        "classification": "observational-analytical field twin (no forecasting)",
        "implemented_capabilities": implemented,
        "capabilities_with_data": ready,
        "not_implemented": not_implemented
        + [
            "climate_projection_scenarios (M7.8 blocked — no validated provider)",
            "weather_forecasts (no provider)",
            "crop_yield_prediction (no evidence basis; prohibited)",
            "autonomous_decisions (decision support only)",
        ],
        "note": (
            "Maturity is derived from implemented, verified capabilities and the "
            "presence of data — never from aspiration."
        ),
    }


# ---------------------------------------------------------------------------
# Validation walk (reuses the existing per-artifact verifiers)
# ---------------------------------------------------------------------------


def run_twin_validation(
    db: Session,
    field: dbm.Field,
    *,
    created_by: Any = None,
    idempotency_key: str | None = None,
) -> dbm.DigitalTwinValidation:
    if idempotency_key:
        existing = db.scalar(
            select(dbm.DigitalTwinValidation).where(
                dbm.DigitalTwinValidation.idempotency_key == idempotency_key,
                dbm.DigitalTwinValidation.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    started = datetime.now(UTC)
    checks: list[dict[str, Any]] = []

    # 1. Field States (latest N)
    states = db.scalars(
        select(dbm.FieldState)
        .where(dbm.FieldState.field_id == field.id)
        .order_by(dbm.FieldState.created_at.desc())
        .limit(tc.MAX_STATES_VALIDATED)
    ).all()
    from app.field_state.service import verify_field_state

    for s in states:
        report = verify_field_state(db, s)
        verified, findings = _verdict_field_state(report)
        checks.append(
            {"artifact": "field_state", "artifact_id": str(s.id), "verified": verified, "findings": findings}
        )

    # 2. Scenario definitions
    scenarios = db.scalars(
        select(dbm.Scenario)
        .where(dbm.Scenario.field_id == field.id)
        .order_by(dbm.Scenario.created_at.desc())
        .limit(tc.MAX_SCENARIOS_VALIDATED)
    ).all()
    from app.scenarios.service import verify_scenario

    for s in scenarios:
        report = verify_scenario(db, s)
        verified, findings = _verdict_scenario(report)
        checks.append(
            {"artifact": "scenario", "artifact_id": str(s.id), "verified": verified, "findings": findings}
        )

    # 3. Scenario executions
    executions = db.scalars(
        select(dbm.ScenarioExecutionRun)
        .where(
            dbm.ScenarioExecutionRun.field_id == field.id,
            dbm.ScenarioExecutionRun.run_status.in_(RESULT_RUN_STATUSES),
        )
        .order_by(dbm.ScenarioExecutionRun.completed_at.desc().nullslast())
        .limit(tc.MAX_EXECUTIONS_VALIDATED)
    ).all()
    from app.scenario_execution.service import verify_execution

    for r in executions:
        report = verify_execution(db, r)
        verified, findings = _verdict_execution(report)
        checks.append(
            {"artifact": "scenario_execution", "artifact_id": str(r.id), "verified": verified, "findings": findings}
        )

    # 4. Sensitivity analyses
    analyses = db.scalars(
        select(dbm.SensitivityAnalysis)
        .where(
            dbm.SensitivityAnalysis.field_id == field.id,
            dbm.SensitivityAnalysis.analysis_status.in_(RESULT_ANALYSIS_STATUSES),
        )
        .order_by(dbm.SensitivityAnalysis.completed_at.desc().nullslast())
        .limit(tc.MAX_ANALYSES_VALIDATED)
    ).all()
    from app.sensitivity.service import verify_analysis

    for a in analyses:
        report = verify_analysis(db, a)
        verified, findings = _verdict_analysis(report)
        checks.append(
            {"artifact": "sensitivity_analysis", "artifact_id": str(a.id), "verified": verified, "findings": findings}
        )

    # 5. Robust runs
    robust_runs = db.scalars(
        select(dbm.RobustRotationRun)
        .where(
            dbm.RobustRotationRun.field_id == field.id,
            dbm.RobustRotationRun.run_status.in_(RESULT_RUN_STATUSES),
        )
        .order_by(dbm.RobustRotationRun.completed_at.desc().nullslast())
        .limit(tc.MAX_ROBUST_RUNS_VALIDATED)
    ).all()
    from app.robust_rotation.service import verify_run

    for r in robust_runs:
        report = verify_run(db, r)
        verified, findings = bool(report.get("verified")), list(report.get("findings", []))
        checks.append(
            {"artifact": "robust_rotation_run", "artifact_id": str(r.id), "verified": verified, "findings": findings}
        )

    # 6. Decision documents
    docs = db.scalars(
        select(dbm.DecisionComparison)
        .where(
            dbm.DecisionComparison.field_id == field.id,
            dbm.DecisionComparison.doc_status.in_(RESULT_DOC_STATUSES),
        )
        .order_by(dbm.DecisionComparison.created_at.desc().nullslast())
        .limit(tc.MAX_DECISION_DOCS_VALIDATED)
    ).all()
    from app.decision.service import verify_comparison

    for d in docs:
        report = verify_comparison(db, d)
        verified, findings = bool(report.get("verified")), list(report.get("findings", []))
        checks.append(
            {"artifact": "decision_comparison", "artifact_id": str(d.id), "verified": verified, "findings": findings}
        )

    # 7. M6B soil run artifacts — integrity via checksum recomputation where the
    #    producing module defines one. A failed re-verification counts as an
    #    integrity failure (their ABSENCE never does — see analytical gate below).
    from app.soil.assessment import assessment_checksum
    from app.soil.soc import soc_run_checksum
    from app.soil.nutrients import budget_checksum

    for model, kind, checker in (
        (dbm.SoilAssessmentRun, "soil_assessment_run", assessment_checksum),
        (dbm.SocStockRun, "soc_stock_run", soc_run_checksum),
        (dbm.NutrientBudgetRun, "nutrient_budget_run", budget_checksum),
    ):
        rows = db.scalars(
            select(model)
            .where(
                model.field_id == field.id,
                model.status == "succeeded",
            )
            .order_by(model.created_at.desc())
            .limit(tc.MAX_SOIL_MGMT_RUNS_VALIDATED)
        ).all()
        for r in rows:
            recomputed = checker(r.result or {})
            if not r.checksum_sha256:
                verified, findings = False, ["artifact stores no checksum — cannot re-verify"]
            elif recomputed != r.checksum_sha256:
                verified = False
                findings = [
                    "stored checksum does not match recomputed result checksum "
                    f"({r.checksum_sha256[:12]}… != {recomputed[:12]}…)"
                ]
            else:
                verified, findings = True, []
            checks.append(
                {"artifact": kind, "artifact_id": str(r.id), "verified": verified, "findings": findings}
            )

    # 8. M6C management artifacts — presence/shape verification only: these
    #    modules store no checksum today, so integrity claims stay at that
    #    boundary (never fabricated beyond it).
    for model, kind in (
        (dbm.CoverCropPlan, "cover_crop_plan"),
        (dbm.ErosionAssessmentRun, "erosion_assessment_run"),
        (dbm.OperationScheduleRun, "operation_schedule_run"),
        (dbm.ManagementPlan, "management_plan"),
    ):
        rows = db.scalars(
            select(model)
            .where(model.field_id == field.id, model.status == "succeeded")
            .order_by(model.created_at.desc())
            .limit(tc.MAX_SOIL_MGMT_RUNS_VALIDATED)
        ).all()
        for r in rows:
            ok = bool(r.result)
            checks.append(
                {
                    "artifact": kind,
                    "artifact_id": str(r.id),
                    "verified": ok,
                    "findings": [] if ok else ["succeeded artifact carries no result payload"],
                }
            )

    total = len(checks)
    failed = [c for c in checks if not c["verified"]]
    analytical = [
        c for c in checks if c["artifact"] in ("scenario_execution", "sensitivity_analysis", "robust_rotation_run", "decision_comparison")
    ]
    if not analytical:
        overall = "no_artifacts"
    elif failed:
        overall = "inconsistent"
    else:
        overall = "consistent"
    completed = datetime.now(UTC)

    report = {
        "validation_version": tc.VALIDATION_VERSION,
        "field_id": str(field.id),
        "overall_status": overall,
        "artifact_checks": checks,
        "summary": {
            "total_checked": total,
            "verified": total - len(failed),
            "failed": len(failed),
        },
        "bounds_note": (
            f"Validation re-verifies the {tc.MAX_EXECUTIONS_VALIDATED} newest "
            "result-bearing executions, "
            f"{tc.MAX_ANALYSES_VALIDATED} newest analyses, "
            f"{tc.MAX_ROBUST_RUNS_VALIDATED} newest robust runs, "
            f"{tc.MAX_DECISION_DOCS_VALIDATED} newest decision documents, "
            f"{tc.MAX_SOIL_MGMT_RUNS_VALIDATED} newest M6B/M6C run artifacts "
            "(checksum recomputation where stored, presence checks otherwise), "
            f"{tc.MAX_SCENARIOS_VALIDATED} newest scenarios and "
            f"{tc.MAX_STATES_VALIDATED} newest field states (bounded walk)."
        ),
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
    }

    row = dbm.DigitalTwinValidation(
        field_id=field.id,
        overall_status=overall,
        report=report,
        report_checksum=sha256_of_document(report),
        artifacts_checked=total,
        artifacts_failed=len(failed),
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=started,
        completed_at=completed,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.DigitalTwinValidation)
            .where(dbm.DigitalTwinValidation.idempotency_key == idempotency_key)
            .limit(1)
        ) if idempotency_key else None
        if winner is not None:
            return winner
        raise
    db.refresh(row)
    return row


def validation_payload(row: dbm.DigitalTwinValidation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "field_id": str(row.field_id),
        "overall_status": row.overall_status,
        "artifacts_checked": row.artifacts_checked,
        "artifacts_failed": row.artifacts_failed,
        "report_checksum": row.report_checksum,
        "report": row.report,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

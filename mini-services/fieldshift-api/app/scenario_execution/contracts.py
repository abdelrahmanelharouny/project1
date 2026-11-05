"""Scenario execution contracts (Milestone 7.3).

Pure-data contracts for the environmental stress transformation & scenario
execution layer. Deliberately free of database / HTTP / engine code.

Versioning:

- TRANSFORMATION_ENGINE_VERSION — bumped when transformation semantics change.
- EXECUTION_CONFIG_SCHEMA_VERSION — canonical execution document format.

Evidence vocabulary (M7.3 spec §10). This layer introduces its own classes; it
deliberately does NOT extend the M7.2 `EvidenceClassification` enum, whose
values and database CHECK constraints stay frozen:

- ``observed_source``            — the value came from an observed/reanalysis
                                   source observation (source class passthrough)
- ``scenario_derived_transformed`` — a deterministic transformation of an
                                   observed source value (hypothetical)
- ``synthetic_test``             — the source observation was synthetic
                                   (flag passthrough; synthetic stays visible)

Run statuses mirror the workspace contract: queued / running / succeeded /
completed_with_limitations / failed.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TRANSFORMATION_ENGINE_VERSION = "scenario-transform-1.0.0"
EXECUTION_CONFIG_SCHEMA_VERSION = "scenario-execution-1.0"

# ---------------------------------------------------------------------------
# Supported transformations (M7.3 spec §2 — nothing else executes)
# ---------------------------------------------------------------------------


class TransformationCode(str, Enum):
    TEMPERATURE_DELTA_C = "temperature_delta_c"
    PRECIPITATION_MULTIPLIER = "precipitation_multiplier"


# Adjustment dimensions from the M7.2 AdjustmentSet that have NO M7.3
# transformation. Their presence in a configuration blocks execution with an
# explicit, honest reason (never silently ignored).
UNSUPPORTED_DIMENSION_REASONS: dict[str, str] = {
    "precipitation_delta_mm": (
        "Additive precipitation shifts are not a supported M7.3 transformation; "
        "only multiplicative precipitation scaling executes."
    ),
    "seasonal_timing_shift_days": (
        "Seasonal timing shifts are not implemented: re-dating observations "
        "would falsify the historical record and M7.3 never alters observation "
        "dates."
    ),
    "rainfall_period_shift_days": (
        "Rainfall-period shifts are not implemented: re-dating rainfall "
        "observations would falsify the historical record."
    ),
}

# Dimension allowed to ride along as a resource-constraint context assumption
# (M7.3 spec §2) — never a transformed weather observation.
RESOURCE_CONSTRAINT_DIMENSION = "water_allocation_multiplier"


class ExecutionBlockedError(ValueError):
    """Raised when a scenario configuration cannot execute.

    Carries structured findings so the API can return a precise 422 body
    instead of a generic message.
    """

    def __init__(self, message: str, findings: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


# ---------------------------------------------------------------------------
# Evidence classes and run statuses
# ---------------------------------------------------------------------------

EVIDENCE_OBSERVED_SOURCE = "observed_source"
EVIDENCE_SCENARIO_DERIVED = "scenario_derived_transformed"
EVIDENCE_SYNTHETIC_TEST = "synthetic_test"

DERIVED_EVIDENCE_CLASSES = (
    EVIDENCE_OBSERVED_SOURCE,
    EVIDENCE_SCENARIO_DERIVED,
    EVIDENCE_SYNTHETIC_TEST,
)

RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
RUN_STATUS_FAILED = "failed"

RESULT_STATUSES = (RUN_STATUS_SUCCEEDED, RUN_STATUS_COMPLETED_WITH_LIMITATIONS)
# Statuses frozen by the database trigger (result-bearing runs are immutable).
IMMUTABLE_RUN_STATUSES = RESULT_STATUSES

RUN_STATUSES = (
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_COMPLETED_WITH_LIMITATIONS,
    RUN_STATUS_FAILED,
)

FEATURE_EVIDENCE_RECALCULATED = "scenario_recalculated"
FEATURE_EVIDENCE_NOT_AFFECTED = "not_affected"
FEATURE_EVIDENCE_NOT_EVALUATED = "not_evaluated"

FEATURE_EVIDENCE_STATUSES = (
    FEATURE_EVIDENCE_RECALCULATED,
    FEATURE_EVIDENCE_NOT_AFFECTED,
    FEATURE_EVIDENCE_NOT_EVALUATED,
)


# ---------------------------------------------------------------------------
# Canonical execution configuration (checksummed input document)
# ---------------------------------------------------------------------------


class ExecutionConfiguration(BaseModel):
    """The canonical, versioned execution input document.

    This is the record of WHAT the engine was asked to do — derived from the
    finalized scenario's configuration at execution time, re-validated here so
    the run row is self-describing without re-parsing the scenario.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scenario-execution-1.0"] = "scenario-execution-1.0"
    scenario_type: str
    scenario_configuration_checksum: str
    parent_field_state_id: str
    parent_snapshot_checksum: str
    boundary_version: int
    period_start: str = Field(..., description="ISO-8601 UTC instant (inclusive)")
    period_end: str = Field(..., description="ISO-8601 UTC instant (inclusive)")
    timezone: str
    hemisphere: str = Field(..., description="Season hemisphere reused from the parent run")
    transformations: list[dict[str, Any]] = Field(
        ..., description='e.g. [{"code": "temperature_delta_c", "delta_c": 2.0}]'
    )
    resource_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="e.g. water_allocation_multiplier retained as context (never weather)",
    )
    aggregation_levels: list[str] = Field(
        ..., description="Aggregation levels requested for the scenario feature pass"
    )
    engine_versions: dict[str, str] = Field(
        ..., description="transformation engine + feature engine + feature catalog versions"
    )

    def checksum(self) -> str:
        from app.field_state.manifest import sha256_of_document

        return sha256_of_document(self.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Checksum document (M7.3 spec §11)
# ---------------------------------------------------------------------------


def execution_checksum_payload(
    *,
    execution_configuration: dict[str, Any],
    parent_snapshot_checksum: str,
    source_observation_manifest_sha256: str,
    scenario_configuration_checksum: str,
    scenario_version: int,
    transformation_engine_version: str,
    feature_engine_version: str,
    feature_catalog_version: str,
    derived_observations: list[dict[str, Any]],
    derived_features: list[dict[str, Any]],
    not_evaluated_reasons: dict[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    """Everything materially relevant to a run's output, in one document.

    Excluded on purpose: run id, timestamps, created_by, idempotency key —
    identical scientific inputs must produce identical checksums regardless of
    who ran them or when (M7.3 spec §11).
    """
    return {
        "checksum_format": "scenario-execution-output-1",
        "execution_configuration": execution_configuration,
        "parent_snapshot_checksum": parent_snapshot_checksum,
        "source_observation_manifest_sha256": source_observation_manifest_sha256,
        "scenario_configuration_checksum": scenario_configuration_checksum,
        "scenario_version": scenario_version,
        "transformation_engine_version": transformation_engine_version,
        "feature_engine_version": feature_engine_version,
        "feature_catalog_version": feature_catalog_version,
        "derived_observations": derived_observations,
        "derived_features": derived_features,
        "not_evaluated_reasons": not_evaluated_reasons,
        "warnings": warnings,
    }


# Floats serialized with fixed precision inside canonical checksum documents —
# stable across runs/platforms for the magnitudes involved (mm, degC, days).
CHECKSUM_FLOAT_PRECISION = 6


def canonical_value(value: Any) -> Any:
    """Round floats for checksum stability; recurse containers; keep nulls."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return round(value, CHECKSUM_FLOAT_PRECISION)
    if isinstance(value, dict):
        return {k: canonical_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(v) for v in value]
    return str(value)

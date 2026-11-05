"""Sensitivity & uncertainty analysis contracts (Milestone 7.4).

Pure-data contracts for the sensitivity analysis layer. Deliberately free of
database / HTTP / engine code (M7.3 module idiom).

M7.4 analyses ONE immutable M7.3 execution run: it varies the run's configured
transformation parameters over user-supplied bounds, recomputes the affected
environmental features with the EXISTING M4 engine through the SAME code paths
M7.3 uses, and materialises auditable response metrics + an uncertainty and
limitation registry. Analyses are derived analytical artifacts — they never
mutate observations, feature runs, Field States, scenario definitions or M7.3
execution results.

Versioning:
- ANALYSIS_METHOD_VERSION — bumped when analysis semantics change.
- RESPONSE_CLASSIFICATION_VERSION — bumped when classification tolerances /
  rubric change (all thresholds are part of the rubric and documented).
- UNCERTAINTY_REGISTRY_VERSION — bumped when the registry schema/items change.
- ANALYSIS_CONFIG_SCHEMA_VERSION — canonical analysis input document format.

Parameter vocabulary mirrors M7.3's TransformationCode exactly. Parameters not
configured in the source execution are NOT explorable (no reference value
exists) — reported as not_applicable, never invented.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ANALYSIS_METHOD_VERSION = "sensitivity-analysis-1.0.0"
RESPONSE_CLASSIFICATION_VERSION = "sensitivity-response-classification-1.0"
UNCERTAINTY_REGISTRY_VERSION = "sensitivity-uncertainty-registry-1.0"
ANALYSIS_CONFIG_SCHEMA_VERSION = "sensitivity-analysis-1.0"

# ---------------------------------------------------------------------------
# Parameters (exactly the M7.3 supported transformations)
# ---------------------------------------------------------------------------


class SensitivityParameter(str, Enum):
    TEMPERATURE_DELTA_C = "temperature_delta_c"
    PRECIPITATION_MULTIPLIER = "precipitation_multiplier"


PARAMETER_CODES = (
    SensitivityParameter.TEMPERATURE_DELTA_C.value,
    SensitivityParameter.PRECIPITATION_MULTIPLIER.value,
)

# Display units used in slope_units strings (M7.4 method §4.1).
PARAMETER_UNITS = {
    SensitivityParameter.TEMPERATURE_DELTA_C.value: "degC",
    SensitivityParameter.PRECIPITATION_MULTIPLIER.value: "multiplier",
}

# Physical guardrails for explored ranges (documented, part of the method
# version). They bound absurd explorations; they are NOT probability claims.
MAX_ABS_TEMPERATURE_DELTA_C = 25.0
MAX_PRECIPITATION_MULTIPLIER = 10.0

MIN_OAT_POINTS = 3
MAX_OAT_POINTS = 21
DEFAULT_OAT_POINTS = 11

MIN_GRID_POINTS = 2
MAX_GRID_POINTS = 9
MAX_GRID_CELLS = 81
MAX_UNIQUE_EVALUATIONS = 100

# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

ANALYSIS_STATUS_QUEUED = "queued"
ANALYSIS_STATUS_RUNNING = "running"
ANALYSIS_STATUS_SUCCEEDED = "succeeded"
ANALYSIS_STATUS_COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
ANALYSIS_STATUS_FAILED = "failed"

RESULT_ANALYSIS_STATUSES = (ANALYSIS_STATUS_SUCCEEDED, ANALYSIS_STATUS_COMPLETED_WITH_LIMITATIONS)
IMMUTABLE_ANALYSIS_STATUSES = RESULT_ANALYSIS_STATUSES
ANALYSIS_STATUSES = (
    ANALYSIS_STATUS_QUEUED,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_SUCCEEDED,
    ANALYSIS_STATUS_COMPLETED_WITH_LIMITATIONS,
    ANALYSIS_STATUS_FAILED,
)

EVALUATION_KIND_REFERENCE = "reference"
EVALUATION_KIND_OAT = "oat"
EVALUATION_KIND_GRID = "grid"
EVALUATION_KINDS = (EVALUATION_KIND_REFERENCE, EVALUATION_KIND_OAT, EVALUATION_KIND_GRID)

EVALUATION_STATUS_SUCCEEDED = "succeeded"
EVALUATION_STATUS_FAILED = "failed"
EVALUATION_STATUSES = (EVALUATION_STATUS_SUCCEEDED, EVALUATION_STATUS_FAILED)

RESPONSE_STATUS_EVALUATED = "evaluated"
RESPONSE_STATUS_PARTIALLY_EVALUATED = "partially_evaluated"
RESPONSE_STATUS_NOT_EVALUATED = "not_evaluated"
RESPONSE_STATUSES = (
    RESPONSE_STATUS_EVALUATED,
    RESPONSE_STATUS_PARTIALLY_EVALUATED,
    RESPONSE_STATUS_NOT_EVALUATED,
)

SLOPE_METHOD_CENTRAL = "central"
SLOPE_METHOD_FORWARD = "forward_one_sided"
SLOPE_METHOD_BACKWARD = "backward_one_sided"
SLOPE_METHOD_NOT_EVALUATED = "not_evaluated"
SLOPE_METHODS = (
    SLOPE_METHOD_CENTRAL,
    SLOPE_METHOD_FORWARD,
    SLOPE_METHOD_BACKWARD,
    SLOPE_METHOD_NOT_EVALUATED,
)

SLOPE_VALIDITY_VALID = "valid"
SLOPE_VALIDITY_INVALID_ACROSS_JUMP = "invalid_across_suspected_discontinuity"
SLOPE_VALIDITIES = (SLOPE_VALIDITY_VALID, SLOPE_VALIDITY_INVALID_ACROSS_JUMP)

DIRECTION_INCREASING = "increasing"
DIRECTION_DECREASING = "decreasing"
DIRECTION_NO_CHANGE = "no_change"
DIRECTION_NOT_EVALUATED = "not_evaluated"
DIRECTIONS = (
    DIRECTION_INCREASING,
    DIRECTION_DECREASING,
    DIRECTION_NO_CHANGE,
    DIRECTION_NOT_EVALUATED,
)

CLASSIFICATION_NOT_EVALUATED = "not_evaluated"
CLASSIFICATION_INSUFFICIENT_POINTS = "insufficient_evaluated_points"
CLASSIFICATION_CONSTANT = "constant"
CLASSIFICATION_MONOTONIC_INCREASING = "monotonic_increasing"
CLASSIFICATION_MONOTONIC_DECREASING = "monotonic_decreasing"
CLASSIFICATION_THRESHOLD_SUSPECTED = "threshold_suspected"
CLASSIFICATION_NON_MONOTONIC = "non_monotonic"
RESPONSE_CLASSIFICATIONS = (
    CLASSIFICATION_NOT_EVALUATED,
    CLASSIFICATION_INSUFFICIENT_POINTS,
    CLASSIFICATION_CONSTANT,
    CLASSIFICATION_MONOTONIC_INCREASING,
    CLASSIFICATION_MONOTONIC_DECREASING,
    CLASSIFICATION_THRESHOLD_SUSPECTED,
    CLASSIFICATION_NON_MONOTONIC,
)

INTERACTION_ADDITIVE = "approximately_additive"
INTERACTION_SUPER_ADDITIVE = "super_additive_over_explored_grid"
INTERACTION_SUB_ADDITIVE = "sub_additive_over_explored_grid"
INTERACTION_NOT_EVALUATED = "not_evaluated"
INTERACTION_INTERPRETATIONS = (
    INTERACTION_ADDITIVE,
    INTERACTION_SUPER_ADDITIVE,
    INTERACTION_SUB_ADDITIVE,
    INTERACTION_NOT_EVALUATED,
)

VARIABLE_FAMILY_TEMPERATURE = "temperature"
VARIABLE_FAMILY_PRECIPITATION = "precipitation"

ELASTICITY_AVAILABLE = "available"
ELASTICITY_UNAVAILABLE = "unavailable"

# ---------------------------------------------------------------------------
# Classification rubric tolerances (M7.4 method §5 — versioned together with
# RESPONSE_CLASSIFICATION_VERSION; changing any of these is a version bump).
# ---------------------------------------------------------------------------

EQUALITY_TOL = 1e-9
CONSTANT_BAND_RELATIVE = 1e-3
THRESHOLD_JUMP_FACTOR = 10.0
THRESHOLD_STEP_SPAN_SHARE = 0.8
THRESHOLD_MIN_POINTS = 6

# ---------------------------------------------------------------------------
# Disclosures (always carried in analysis warnings)
# ---------------------------------------------------------------------------

HYPOTHETICAL_DISCLOSURE = (
    "Sensitivity analysis examines hypothetical scenario-derived features: the "
    "source execution's transformed values are NOT observations of the real "
    "world, and this analysis adds no new observations."
)

ENVELOPE_DISCLOSURE = (
    "The explored parameter-range envelope is the minimum and maximum output "
    "observed across the parameter values you asked the engine to evaluate. It "
    "is a deterministic sensitivity result, not a confidence or probability "
    "interval, and it does not establish how the real climate varies."
)

NOT_PREDICTIVE_DISCLOSURE = (
    "M7.4 does not predict crop yields, future climate, rainfall probabilities, "
    "irrigation outcomes or farm productivity."
)

STANDARD_DISCLOSURES = (HYPOTHETICAL_DISCLOSURE, ENVELOPE_DISCLOSURE, NOT_PREDICTIVE_DISCLOSURE)

NOT_CONFIGURED_REASON = (
    "parameter not configured in the source execution; no reference value exists"
)

# ---------------------------------------------------------------------------
# Canonical analysis configuration (checksummed input document)
# ---------------------------------------------------------------------------


class ParameterDesign(BaseModel):
    """User-supplied bounds + resolution for ONE parameter."""

    model_config = ConfigDict(extra="forbid")

    lower: float
    upper: float
    n_points: int = DEFAULT_OAT_POINTS


class AnalysisConfiguration(BaseModel):
    """The canonical, versioned analysis input document.

    Records WHAT the analysis was asked to do. `parameter_design` and
    `grid_design` keys are restricted to the source run's explorable
    parameters by the service layer before this document is built.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["sensitivity-analysis-1.0"] = "sensitivity-analysis-1.0"
    source_execution_run_id: str
    scenario_id: str
    scenario_version: int
    scenario_configuration_checksum: str
    parent_field_state_id: str
    parent_snapshot_checksum: str
    source_observation_manifest_sha256: str
    source_output_checksum: str
    reference_parameter_values: dict[str, Any]
    explorable_parameters: list[str]
    parameter_design: dict[str, Any]
    grid_design: dict[str, Any] | None = None
    engine_versions: dict[str, str] = Field(
        ..., description="analysis + transformation + feature engine + catalog versions"
    )

    def checksum(self) -> str:
        from app.field_state.manifest import sha256_of_document

        return sha256_of_document(self.model_dump(mode="json"))


def analysis_fingerprint(configuration: AnalysisConfiguration) -> str:
    """Deterministic fingerprint over the analysis input document."""
    return configuration.checksum()


# ---------------------------------------------------------------------------
# Output checksum document (M7.4 method §7)
# ---------------------------------------------------------------------------


def analysis_checksum_payload(
    *,
    analysis_configuration: dict[str, Any],
    reference_reproduction: dict[str, Any],
    evaluations: list[dict[str, Any]],
    feature_values: list[dict[str, Any]],
    oat_responses: list[dict[str, Any]],
    grid_cells: list[dict[str, Any]],
    grid_summaries: list[dict[str, Any]],
    uncertainty_items: list[dict[str, Any]],
    not_analysed_features: dict[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    """Everything materially relevant to an analysis's output, in one document.

    Excluded on purpose: analysis id, evaluation ids, timestamps, created_by,
    idempotency key — identical scientific inputs must produce identical
    checksums regardless of who ran them or when (M7.3 §11 discipline).
    """
    return {
        "checksum_format": "sensitivity-analysis-output-1",
        "analysis_configuration": analysis_configuration,
        "reference_reproduction": reference_reproduction,
        "evaluations": evaluations,
        "feature_values": feature_values,
        "oat_responses": oat_responses,
        "grid_cells": grid_cells,
        "grid_summaries": grid_summaries,
        "uncertainty_items": uncertainty_items,
        "not_analysed_features": not_analysed_features,
        "warnings": warnings,
    }


def canonical_value(value: Any) -> Any:
    """Round floats for checksum stability; recurse containers; keep nulls."""
    from app.scenario_execution.contracts import canonical_value as m73_canonical

    return m73_canonical(value)


def float_eq(a: float | None, b: float | None) -> bool:
    """Equality under the documented classification tolerance."""
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= EQUALITY_TOL

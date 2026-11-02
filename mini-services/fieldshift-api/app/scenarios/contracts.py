"""Scenario domain contracts (Milestone 7.2).

This module is the single source of truth for the scenario taxonomy and the
strictly-typed, versioned scenario configuration contracts. It deliberately
contains NO database, HTTP or engine code — a scenario definition is pure
data, and its integrity rules must be testable without any I/O.

Architecture rules enforced here (M7.2 spec §2):

- A scenario is a DEFINITION, never a simulation result. Nothing in this
  module computes environmental transformations (that is M7.3 scope and it
  does not exist yet).
- Scenario types are NOT equivalent evidence: every type is bound to exactly
  one evidence classification (``observed`` / ``hypothetical`` /
  ``not_available``), enforced here AND by a database CHECK constraint.
- Climate Projection and Weather Forecast are contract placeholders only:
  they exist in the taxonomy with capability ``not_implemented``, they have
  NO configuration model, and creation requests carrying them are rejected.
- Soil and Management scenario dimensions do not exist in this repository
  (M6B/M6C absent — M7.0 finding H-03) and are reported ``not_implemented``.

Versioning contract:

- SCENARIO_TAXONOMY_VERSION — bumped when the set of types / capability
  semantics change.
- SCENARIO_CONFIG_SCHEMA_VERSION — the canonical configuration document
  format. Bumped when serialization semantics change in a way that could
  change a checksum. Every stored scenario pins the version it was created
  with; older checksums remain verifiable against their pinned version.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.field_state.manifest import sha256_of_document

# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SCENARIO_TAXONOMY_VERSION = "scenario-taxonomy-1.0"
SCENARIO_CONFIG_SCHEMA_VERSION = "scenario-config-1.0"
SCENARIO_VALIDATION_RULES_VERSION = "scenario-validation-rules-1.0"

SCENARIO_NAME_MAX = 120

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class ScenarioType(str, Enum):
    """Scenario taxonomy (M7.2 spec §4). Versioned via SCENARIO_TAXONOMY_VERSION."""

    HISTORICAL_OBSERVED = "historical_observed"
    HISTORICAL_PERTURBATION = "historical_perturbation"
    USER_DEFINED_STRESS = "user_defined_stress"
    CLIMATE_PROJECTION = "climate_projection"
    WEATHER_FORECAST = "weather_forecast"


class ScenarioStatus(str, Enum):
    """Lifecycle states (M7.2 spec §9)."""

    DRAFT = "draft"
    VALIDATION_PENDING = "validation_pending"
    VALID = "valid"
    CONDITIONALLY_VALID = "conditionally_valid"
    INVALID = "invalid"
    FINALIZED = "finalized"
    ARCHIVED = "archived"
    UNSUPPORTED = "unsupported"


class EvidenceClassification(str, Enum):
    """Evidence classes (M7.0 condition C2 — types are never equivalent evidence)."""

    OBSERVED = "observed"
    HYPOTHETICAL = "hypothetical"
    NOT_AVAILABLE = "not_available"


class LineageKind(str, Enum):
    """How a scenario row relates to its (optional) parent scenario."""

    ROOT = "root"
    REVISION = "revision"  # a new version of the same logical scenario
    BRANCH = "branch"  # a derived, differently-configured scenario


class CapabilityStatus(str, Enum):
    IMPLEMENTED = "implemented"
    NOT_IMPLEMENTED = "not_implemented"


# Fixed, honest reasons for unavailable capabilities (M7.0 H-03 / C3 / C5).
CLIMATE_PROJECTION_UNAVAILABLE_REASON = (
    "Climate projection scenarios are contract-only in M7.2: no sourced, "
    "licensed projection dataset or methodology exists in this repository "
    "(M7.0 finding; condition C5). Creation is rejected; no projection "
    "records are invented or synthesized."
)
WEATHER_FORECAST_UNAVAILABLE_REASON = (
    "Weather forecast scenarios are contract-only in M7.2: no real forecast "
    "provider with issue-time/validity-time/horizon semantics is integrated. "
    "Creation is rejected; hypothetical weather is never displayed as "
    "forecast evidence."
)
SOIL_DIMENSION_UNAVAILABLE_REASON = (
    "Soil scenario dimensions are unavailable: soil health & nutrient "
    "cycling (M6B) is not implemented in this repository (M7.0 finding H-03)."
)
MANAGEMENT_DIMENSION_UNAVAILABLE_REASON = (
    "Management scenario dimensions are unavailable: field management "
    "intelligence (M6C) is not implemented in this repository (M7.0 finding "
    "H-03)."
)


class ScenarioTypeCapability(BaseModel):
    """Static capability record for one taxonomy member."""

    model_config = ConfigDict(frozen=True)

    scenario_type: ScenarioType
    display_name: str
    capability: CapabilityStatus
    evidence_classification: EvidenceClassification
    description: str
    unavailable_reason: str | None = None


SCENARIO_TYPE_CAPABILITIES: dict[ScenarioType, ScenarioTypeCapability] = {
    st: ScenarioTypeCapability(
        scenario_type=st,
        display_name=display_name,
        capability=capability,
        evidence_classification=evidence,
        description=description,
        unavailable_reason=reason,
    )
    for st, (display_name, capability, evidence, description, reason) in {
        ScenarioType.HISTORICAL_OBSERVED: (
            "Historical observed",
            CapabilityStatus.IMPLEMENTED,
            EvidenceClassification.OBSERVED,
            "References an immutable Field State and represents its recorded "
            "historical/reference condition. Never a future prediction.",
            None,
        ),
        ScenarioType.HISTORICAL_PERTURBATION: (
            "Historical perturbation",
            CapabilityStatus.IMPLEMENTED,
            EvidenceClassification.HYPOTHETICAL,
            "Hypothetical adjustments (temperature, precipitation, seasonal "
            "timing, water availability) applied to a historical environmental "
            "reference. Configuration-only in M7.2; no transformation executes.",
            None,
        ),
        ScenarioType.USER_DEFINED_STRESS: (
            "User-defined stress",
            CapabilityStatus.IMPLEMENTED,
            EvidenceClassification.HYPOTHETICAL,
            "A manually configured hypothetical stress experiment (e.g. reduced "
            "irrigation allocation, user-specified temperature increase). Every "
            "input is labelled a user assumption — never measured or forecast data.",
            None,
        ),
        ScenarioType.CLIMATE_PROJECTION: (
            "Climate projection",
            CapabilityStatus.NOT_IMPLEMENTED,
            EvidenceClassification.NOT_AVAILABLE,
            "Reserved contract for future climate projection datasets.",
            CLIMATE_PROJECTION_UNAVAILABLE_REASON,
        ),
        ScenarioType.WEATHER_FORECAST: (
            "Weather forecast",
            CapabilityStatus.NOT_IMPLEMENTED,
            EvidenceClassification.NOT_AVAILABLE,
            "Reserved contract for future forecast data (issue time, validity "
            "time and horizon will be distinguished when a real provider exists).",
            WEATHER_FORECAST_UNAVAILABLE_REASON,
        ),
    }.items()
}

IMPLEMENTED_SCENARIO_TYPES = frozenset(
    st for st, cap in SCENARIO_TYPE_CAPABILITIES.items() if cap.capability == CapabilityStatus.IMPLEMENTED
)

# Domain dimensions a scenario can report as unsupported. soil/management are
# structurally absent from this repository (M6B/M6C) — never fabricated.
SCENARIO_DIMENSION_AVAILABILITY: dict[str, dict[str, Any]] = {
    "soil": {"status": "not_implemented", "reason": SOIL_DIMENSION_UNAVAILABLE_REASON},
    "management": {"status": "not_implemented", "reason": MANAGEMENT_DIMENSION_UNAVAILABLE_REASON},
    "climate_projection": {"status": "not_implemented", "reason": CLIMATE_PROJECTION_UNAVAILABLE_REASON},
    "weather_forecast": {"status": "not_implemented", "reason": WEATHER_FORECAST_UNAVAILABLE_REASON},
}

# Lifecycle transition table (M7.2 spec §9). Documented and enforced by the
# service; the database trigger additionally freezes finalized/archived rows.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    ScenarioStatus.DRAFT.value: frozenset(
        {
            ScenarioStatus.VALIDATION_PENDING.value,
            ScenarioStatus.ARCHIVED.value,
        }
    ),
    ScenarioStatus.VALIDATION_PENDING.value: frozenset(
        {
            ScenarioStatus.VALID.value,
            ScenarioStatus.CONDITIONALLY_VALID.value,
            ScenarioStatus.INVALID.value,
            ScenarioStatus.UNSUPPORTED.value,
        }
    ),
    ScenarioStatus.VALID.value: frozenset(
        {
            ScenarioStatus.FINALIZED.value,
            ScenarioStatus.ARCHIVED.value,
            ScenarioStatus.DRAFT.value,  # edit reset (PATCH)
            ScenarioStatus.VALIDATION_PENDING.value,  # re-validation
        }
    ),
    ScenarioStatus.CONDITIONALLY_VALID.value: frozenset(
        {
            ScenarioStatus.FINALIZED.value,
            ScenarioStatus.ARCHIVED.value,
            ScenarioStatus.DRAFT.value,  # edit reset (PATCH)
            ScenarioStatus.VALIDATION_PENDING.value,  # re-validation
        }
    ),
    ScenarioStatus.INVALID.value: frozenset({ScenarioStatus.DRAFT.value, ScenarioStatus.ARCHIVED.value}),
    ScenarioStatus.FINALIZED.value: frozenset({ScenarioStatus.ARCHIVED.value}),
    ScenarioStatus.ARCHIVED.value: frozenset(),
    ScenarioStatus.UNSUPPORTED.value: frozenset(),
}

# Validation-result vocabulary (M7.2 spec §8) mapped to lifecycle states.
VALIDATION_RESULT_STATUSES = (
    "valid",
    "invalid",
    "conditionally_valid",
    "unsupported",
    "not_implemented",
    "missing_reference",
    "incompatible_period",
    "insufficient_parent_evidence",
)

VALIDATION_RESULT_TO_LIFECYCLE: dict[str, str] = {
    "valid": ScenarioStatus.VALID.value,
    "conditionally_valid": ScenarioStatus.CONDITIONALLY_VALID.value,
    "insufficient_parent_evidence": ScenarioStatus.CONDITIONALLY_VALID.value,
    "invalid": ScenarioStatus.INVALID.value,
    "missing_reference": ScenarioStatus.INVALID.value,
    "incompatible_period": ScenarioStatus.INVALID.value,
    "unsupported": ScenarioStatus.UNSUPPORTED.value,
    "not_implemented": ScenarioStatus.UNSUPPORTED.value,
}

# ---------------------------------------------------------------------------
# Configuration contracts (strictly typed — no unrestricted JSON documents)
# ---------------------------------------------------------------------------

# Adjustment bounds with explicit units embedded in the field names.
TEMPERATURE_DELTA_C_MIN = -20.0
TEMPERATURE_DELTA_C_MAX = 20.0
PRECIPITATION_MULTIPLIER_MIN = 0.0
PRECIPITATION_MULTIPLIER_MAX = 3.0
PRECIPITATION_DELTA_MM_MIN = -500.0
PRECIPITATION_DELTA_MM_MAX = 500.0
WATER_ALLOCATION_MULTIPLIER_MIN = 0.0
WATER_ALLOCATION_MULTIPLIER_MAX = 2.0
SEASONAL_TIMING_SHIFT_DAYS_MIN = -180
SEASONAL_TIMING_SHIFT_DAYS_MAX = 180
RAINFALL_PERIOD_SHIFT_DAYS_MIN = -180
RAINFALL_PERIOD_SHIFT_DAYS_MAX = 180


class ConfigBase(BaseModel):
    """All configuration models forbid unknown keys — an unmodelled
    adjustment dimension is a contract violation, never silently ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PeriodRange(ConfigBase):
    """Half-open analysis window [start, end]. Dates serialize as ISO-8601."""

    start: str = Field(..., description="ISO-8601 date or datetime (UTC midnight for dates)")
    end: str = Field(..., description="ISO-8601 date or datetime (UTC midnight for dates); >= start")


class AssumptionMetadata(ConfigBase):
    """Provenance of hypothetical inputs. ``status`` is pinned to
    ``hypothetical`` — user assumptions can never masquerade as observed or
    forecast evidence (M7.2 spec §2 rules 5/6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin: Literal["user_defined", "derived_from_scenario"] = "user_defined"
    status: Literal["hypothetical"] = "hypothetical"
    description: str | None = Field(default=None, max_length=500)


class AdjustmentSet(ConfigBase):
    """Hypothetical adjustment dimensions (M7.2 spec §4.2/4.3).

    Every field is optional but must be explicitly ``null`` when unset
    (explicit-null canonical serialization). Units are part of the names.
    At least one adjustment is required; conflicting representations of the
    same physical dimension are rejected.
    """

    temperature_delta_c: float | None = Field(
        default=None,
        ge=TEMPERATURE_DELTA_C_MIN,
        le=TEMPERATURE_DELTA_C_MAX,
        description="Hypothetical air-temperature shift, degrees Celsius.",
    )
    precipitation_multiplier: float | None = Field(
        default=None,
        ge=PRECIPITATION_MULTIPLIER_MIN,
        le=PRECIPITATION_MULTIPLIER_MAX,
        description="Hypothetical precipitation ratio (1.0 = unchanged).",
    )
    precipitation_delta_mm: float | None = Field(
        default=None,
        ge=PRECIPITATION_DELTA_MM_MIN,
        le=PRECIPITATION_DELTA_MM_MAX,
        description="Hypothetical precipitation shift, millimetres.",
    )
    water_allocation_multiplier: float | None = Field(
        default=None,
        ge=WATER_ALLOCATION_MULTIPLIER_MIN,
        le=WATER_ALLOCATION_MULTIPLIER_MAX,
        description="Hypothetical irrigation allocation ratio (1.0 = unchanged).",
    )
    seasonal_timing_shift_days: int | None = Field(
        default=None,
        ge=SEASONAL_TIMING_SHIFT_DAYS_MIN,
        le=SEASONAL_TIMING_SHIFT_DAYS_MAX,
        description="Hypothetical shift of seasonal timing, days.",
    )
    rainfall_period_shift_days: int | None = Field(
        default=None,
        ge=RAINFALL_PERIOD_SHIFT_DAYS_MIN,
        le=RAINFALL_PERIOD_SHIFT_DAYS_MAX,
        description="Hypothetical shift of the assumed rainfall period, days.",
    )

    @model_validator(mode="after")
    def _check_conflicts(self) -> "AdjustmentSet":
        if self.precipitation_multiplier is not None and self.precipitation_delta_mm is not None:
            raise ValueError(
                "Conflicting precipitation adjustments: specify either "
                "precipitation_multiplier or precipitation_delta_mm, not both."
            )
        if self.seasonal_timing_shift_days is not None and self.rainfall_period_shift_days is not None:
            raise ValueError(
                "Conflicting timing adjustments: specify either "
                "seasonal_timing_shift_days or rainfall_period_shift_days, not both."
            )
        if (
            self.temperature_delta_c is None
            and self.precipitation_multiplier is None
            and self.precipitation_delta_mm is None
            and self.water_allocation_multiplier is None
            and self.seasonal_timing_shift_days is None
            and self.rainfall_period_shift_days is None
        ):
            raise ValueError(
                "At least one hypothetical adjustment is required; an empty "
                "adjustment set defines no scenario."
            )
        return self


class HistoricalObservedConfig(ConfigBase):
    """M7.2 spec §4.1 — reference condition of an immutable Field State.

    Carries no assumptions: it is a labelled reference to recorded evidence.
    Any attempt to attach hypothetical inputs is a contract violation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["historical_observed"]
    schema_version: Literal["scenario-config-1.0"]
    parent_field_state_id: str = Field(..., description="UUID of the parent field state")


class _HypotheticalConfigBase(ConfigBase):
    """Shared shape of the two implemented hypothetical types (§4.2/§4.3)."""

    parent_field_state_id: str = Field(..., description="UUID of the parent field state")
    period: PeriodRange
    adjustments: AdjustmentSet
    assumption_metadata: AssumptionMetadata = Field(default_factory=AssumptionMetadata)


class HistoricalPerturbationConfig(_HypotheticalConfigBase):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["historical_perturbation"]
    schema_version: Literal["scenario-config-1.0"]


class UserDefinedStressConfig(_HypotheticalConfigBase):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["user_defined_stress"]
    schema_version: Literal["scenario-config-1.0"]


# The discriminated union of IMPLEMENTED configuration contracts. Climate
# projection and weather forecast intentionally have NO model: there is
# nothing honest to validate yet (spec §4.4/§4.5).
ScenarioConfiguration = (
    HistoricalObservedConfig | HistoricalPerturbationConfig | UserDefinedStressConfig
)

CONFIG_MODEL_BY_TYPE: dict[str, type[BaseModel]] = {
    ScenarioType.HISTORICAL_OBSERVED.value: HistoricalObservedConfig,
    ScenarioType.HISTORICAL_PERTURBATION.value: HistoricalPerturbationConfig,
    ScenarioType.USER_DEFINED_STRESS.value: UserDefinedStressConfig,
}


def parse_configuration(scenario_type: str, payload: dict[str, Any]) -> BaseModel:
    """Validate a raw configuration payload against the type's contract.

    Raises pydantic ValidationError on any contract violation; the API layer
    converts it to a structured 422. Unknown/unsupported scenario types are
    rejected here as well.
    """
    model_cls = CONFIG_MODEL_BY_TYPE.get(scenario_type)
    if model_cls is None:
        from app.core.errors import ValidationFailed

        capability = SCENARIO_TYPE_CAPABILITIES.get(scenario_type)
        reason = (
            capability.unavailable_reason
            if capability is not None
            else "Unknown scenario type."
        )
        raise ValidationFailed(
            f"Scenario type '{scenario_type}' is not implemented; configuration rejected.",
            details=[{"field": "scenario_type", "reason": reason}],
            code="SCENARIO_TYPE_NOT_IMPLEMENTED",
        )
    return model_cls.model_validate(payload)


# ---------------------------------------------------------------------------
# Canonical serialization + deterministic checksum (M7.2 spec §7)
# ---------------------------------------------------------------------------


def canonicalize_configuration(model: BaseModel) -> dict[str, Any]:
    """Canonical configuration document.

    - Key order: sorted at serialization time (sha256_of_document canonical JSON).
    - Nulls: optional adjustment dimensions are ALWAYS present — unset means
      explicit ``null``, never an omitted key and never a silent zero.
    - Units: embedded in field names (e.g. ``temperature_delta_c``).
    - ``schema_version`` and ``type`` are part of the document, so a stored
      checksum is self-describing and re-verifiable years later.
    """
    doc = model.model_dump(mode="json")  # UUID/datetime-free by contract design
    adjustments = doc.get("adjustments")
    if isinstance(adjustments, dict):
        doc["adjustments"] = {
            key: adjustments.get(key) for key in sorted(AdjustmentSet.model_fields.keys())
        }
    return doc


def scenario_checksum_payload(
    *,
    scenario_type: str,
    configuration_schema_version: str,
    canonical_configuration: dict[str, Any],
    parent_field_state_id: str,
    parent_snapshot_checksum: str,
    boundary_version: int,
    timezone: str,
) -> dict[str, Any]:
    """The exact checksum input for a scenario definition.

    Covers everything scientifically material: the typed configuration, its
    schema version, the type itself, and the BY-VALUE pins of the parent
    Field State (id, snapshot checksum, boundary version) plus the calendar
    timezone. UI/provenance metadata (name, description, idempotency key,
    created_by, timestamps) is deliberately excluded.
    """
    return {
        "configuration_schema_version": configuration_schema_version,
        "scenario_type": scenario_type,
        "canonical_configuration": canonical_configuration,
        "parent_field_state_id": str(parent_field_state_id),
        "parent_snapshot_checksum": parent_snapshot_checksum,
        "boundary_version": boundary_version,
        "timezone": timezone,
    }


def compute_scenario_checksum(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 over the canonical checksum payload."""
    return sha256_of_document(payload)


def evidence_label(evidence_classification: str) -> str:
    """Human-readable evidence label (C2: per-type labels everywhere)."""
    return {
        EvidenceClassification.OBSERVED.value: "Observed historical condition",
        EvidenceClassification.HYPOTHETICAL.value: "Hypothetical assumption — not observed data",
        EvidenceClassification.NOT_AVAILABLE.value: "Not available — no real data source",
    }.get(evidence_classification, evidence_classification)

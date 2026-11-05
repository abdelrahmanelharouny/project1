"""Pydantic contracts + vocabulary for M6C field management intelligence.

Increment 2 (practice knowledge): practice definitions are knowledge-pack
data — validated strictly, source-cited per claim, and never treated as
validated without review. The engine vocabulary lives here so every module
and test shares one honest status language:

- candidate eligibility: eligible | conditional | excluded | not_evaluated
- evidence-backed dimensions: evaluated | conditional | not_evaluated
- erosion outputs: qualitative_screening | model_estimate | not_evaluated
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------- vocabulary
PRACTICE_FAMILIES: tuple[str, ...] = (
    "cover_crop", "residue", "tillage", "soil_cover",
    "erosion_control", "traffic", "termination",
)

TRADE_OFF_DIMENSIONS: tuple[str, ...] = (
    "soil_cover", "erosion_protection", "water_demand", "nutrient_cycling",
    "soil_organic_matter", "crop_establishment", "pests_diseases", "labor",
    "machinery", "cost", "revenue", "forage_value",
)

ELIGIBILITY_STATUSES: tuple[str, ...] = (
    "eligible", "conditional", "excluded", "not_evaluated",
)

# M6C engine identity (mirrors water-engine / feature-engine versioning).
MANAGEMENT_ENGINE_VERSION = "management-engine-1.0.0"
MANAGEMENT_METHODS_VERSION = "management-methods-1.0.0"

# Cover-crop candidate trait codes (documented vocabulary; values only ever
# come from sourced pack rows — the vocabulary itself carries no numbers).
COVER_CROP_TRAIT_CODES: tuple[str, ...] = (
    "cover_establishment_speed",        # text class: rapid|moderate|slow (sourced)
    "cover_growth_duration_days",       # days (sourced) — expected vegetative duration
    "cover_sowing_window_note",         # text — regional window context
    "cover_frost_tolerance",            # text class + conditions
    "cover_water_use_note",             # text — qualitative water behaviour (sourced)
    "cover_termination_methods",        # text list — methods with cited evidence
    "cover_seeding_rate",               # value + unit (sourced, region-scoped)
    "cover_seed_availability_note",     # text
    "cover_invasiveness_risk",          # text — legal/invasiveness where known
    "cover_forage_value_note",          # text — livestock/forage value where known
    "cover_biomass_potential_note",     # text — biomass class where sourced
    "cover_n_scavenging_note",          # text — nutrient capture where sourced
)


class _Sourced(BaseModel):
    """Base for every knowledge claim: a claim without a source is an error,
    not a default (red line: missing evidence must not become eligibility)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=4)
    source_key: str = Field(min_length=2, max_length=80)
    evidence_class: str = Field(min_length=2, max_length=60)
    confidence: Literal["high", "moderate", "low", "unknown"] = "unknown"
    conditions: dict[str, Any] = Field(default_factory=dict)


class PracticeMechanismIn(_Sourced):
    """A claimed mechanism ('how it works') — always qualitative + cited."""

    mechanism_code: str = Field(min_length=2, max_length=80)


class PracticeRequirementIn(_Sourced):
    """An operating requirement (seed, equipment, labor, window, knowledge)."""

    requirement_code: str = Field(min_length=2, max_length=80)
    kind: Literal["seed", "equipment", "labor", "knowledge", "window", "other"]


class PracticeTradeOffIn(_Sourced):
    """A trade-off with explicit direction — a practice is never a
    universal switch (red line 5)."""

    dimension: str
    direction: Literal["positive", "negative", "context_dependent"]


class PracticeRiskIn(_Sourced):
    risk_code: str = Field(min_length=2, max_length=80)


class PracticeRegionalApplicabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: str | None = Field(default=None, max_length=80)
    agroecological_zone: str | None = Field(default=None, max_length=120)
    basis: str = Field(min_length=4)  # WHY this scope is claimed
    source_key: str = Field(min_length=2, max_length=80)
    validation_status: Literal[
        "reference", "locally_validated", "confirmed_regional", "retired"
    ] = "reference"

    @model_validator(mode="after")
    def _check_scope(self) -> "PracticeRegionalApplicabilityIn":
        if not self.region_code and not self.agroecological_zone:
            raise ValueError(
                "regional applicability needs region_code or agroecological_zone "
                "(latitude/hemisphere alone is not a regional basis)"
            )
        return self


class PracticeDefinitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    practice_code: str = Field(min_length=2, max_length=80)
    practice_family: str
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    validation_status: Literal[
        "reference", "locally_validated", "confirmed_regional", "retired"
    ] = "reference"
    mechanisms: list[PracticeMechanismIn] = Field(default_factory=list)
    requirements: list[PracticeRequirementIn] = Field(default_factory=list)
    trade_offs: list[PracticeTradeOffIn] = Field(default_factory=list)
    risks: list[PracticeRiskIn] = Field(default_factory=list)
    regional_applicability: list[PracticeRegionalApplicabilityIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_family(self) -> "PracticeDefinitionIn":
        if self.practice_family not in PRACTICE_FAMILIES:
            raise ValueError(
                f"practice '{self.practice_code}': unknown family "
                f"'{self.practice_family}'"
            )
        if not self.mechanisms and not self.trade_offs:
            raise ValueError(
                f"practice '{self.practice_code}': needs at least one cited "
                "mechanism or trade-off — an uncited practice cannot be shipped"
            )
        return self


class OperationTemplatePredecessorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_code: str = Field(min_length=2, max_length=80)
    rationale: str = Field(min_length=4)
    source_key: str = Field(min_length=2, max_length=80)


class OperationTemplateIn(BaseModel):
    """An operation template: WHICH operation, for what, ordered by cited
    rationale. Deliberately carries NO durations/capacities/speeds."""

    model_config = ConfigDict(extra="forbid")
    template_code: str = Field(min_length=2, max_length=80)
    operation_type: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    validation_status: Literal[
        "reference", "locally_validated", "confirmed_regional", "retired"
    ] = "reference"
    # Crop scoping: category list (e.g. ["cereal","legume"]) or explicit codes;
    # empty means "applies generically" and the generator still requires a
    # concrete crop/plan context before emitting an operation.
    applies_to_crop_categories: list[str] = Field(default_factory=list)
    applies_to_crop_codes: list[str] = Field(default_factory=list)
    typical_predecessors: list[OperationTemplatePredecessorIn] = Field(default_factory=list)
    # Restriction KINDS (soil_moisture | weather | access) — never thresholds.
    restriction_kinds: list[Literal["soil_moisture", "weather", "access"]] = Field(
        default_factory=list
    )
    notes: str | None = None


def validate_practice_sources(
    practices: list[PracticeDefinitionIn], source_keys: set[str], report: Any
) -> None:
    """Cross-validation hook used by the pack importer: every claim inside a
    practice must cite a pack source."""
    for practice in practices:
        where = f"practice '{practice.practice_code}'"
        claims: list[tuple[str, str]] = []
        for m in practice.mechanisms:
            claims.append((f"mechanism '{m.mechanism_code}'", m.source_key))
        for r in practice.requirements:
            claims.append((f"requirement '{r.requirement_code}'", r.source_key))
        for t in practice.trade_offs:
            claims.append((f"trade-off '{t.dimension}'", t.source_key))
        for r in practice.risks:
            claims.append((f"risk '{r.risk_code}'", r.source_key))
        for ra in practice.regional_applicability:
            claims.append(("regional applicability", ra.source_key))
        for claim, key in claims:
            if key not in source_keys:
                report.errors.append(f"{where} {claim}: unknown source_key '{key}'")

    # Unknown trade-off dimensions are a typo risk that would silently hide a
    # dimension from the comparison UI.
    known = set(TRADE_OFF_DIMENSIONS)
    for practice in practices:
        for t in practice.trade_offs:
            if t.dimension not in known:
                report.errors.append(
                    f"practice '{practice.practice_code}': unknown trade-off "
                    f"dimension '{t.dimension}'"
                )

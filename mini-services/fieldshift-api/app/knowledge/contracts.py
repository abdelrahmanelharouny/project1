"""Pydantic contracts for knowledge pack import & validation (Milestone 5).

The import workflow is deliberately strict: a pack that lacks license /
attribution, cites an unknown source, references an unknown crop or family, or
contains conflicting trait values is rejected as a whole with structured
errors. Knowledge never enters the decision pipeline half-validated
(ADR-0014).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TraitOwner = Literal["crop", "variety"]
ValidationStatus = Literal["reference", "locally_validated", "confirmed_regional", "retired"]
Confidence = Literal["high", "moderate", "low", "unknown"]

VALIDATION_STATUSES: tuple[str, ...] = (
    "reference", "locally_validated", "confirmed_regional", "retired",
)
CONFIDENCES: tuple[str, ...] = ("high", "moderate", "low", "unknown")
RULE_TYPES: tuple[str, ...] = (
    "rotation_break", "succession_compatibility", "cover_crop_suitability",
    "residue_management", "soil_cover", "host_pathogen", "host_pest",
)
SEVERITIES: tuple[str, ...] = ("advisory", "recommended", "required")


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str = Field(min_length=2, max_length=80)
    publisher: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=4)
    url: str | None = None
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    license: str | None = None
    citation_text: str = Field(min_length=8)


class FamilyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family_key: str = Field(min_length=2, max_length=80)
    scientific_name: str = Field(min_length=2, max_length=120)
    common_names: list[str] = Field(default_factory=list)


class TraitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trait_code: str = Field(min_length=2, max_length=80)
    value_numeric: float | None = None
    value_text: str | None = None
    value_low: float | None = None
    value_high: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    region_code: str | None = Field(default=None, max_length=80)
    management_context: str | None = Field(default=None, max_length=120)
    growth_stage: str | None = Field(default=None, max_length=60)
    conditions: dict[str, Any] = Field(default_factory=dict)
    source_key: str = Field(min_length=2, max_length=80)
    evidence_class: str = Field(min_length=2, max_length=60)
    confidence: Confidence = "unknown"
    validation_status: ValidationStatus = "reference"
    notes: str | None = None

    @model_validator(mode="after")
    def _check_value(self) -> "TraitIn":
        has_point = self.value_numeric is not None or self.value_text is not None
        has_range = self.value_low is not None or self.value_high is not None
        if not has_point and not has_range:
            raise ValueError("trait needs value_numeric, value_text, or a value_low/high range")
        if self.value_numeric is not None and self.value_text is not None:
            raise ValueError("trait needs exactly one of value_numeric/value_text")
        return self


class CalendarWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: str | None = None
    hemisphere: Literal["north", "south"] = "north"
    season_code: str | None = None
    planting_start: str = Field(pattern=r"^\d{2}-\d{2}$")
    planting_end: str = Field(pattern=r"^\d{2}-\d{2}$")
    harvest_start: str | None = Field(default=None, pattern=r"^\d{2}-\d{2}$")
    harvest_end: str | None = Field(default=None, pattern=r"^\d{2}-\d{2}$")
    source_key: str = Field(min_length=2, max_length=80)
    evidence_class: str = Field(min_length=2, max_length=60)
    validation_status: ValidationStatus = "reference"
    notes: str | None = None


class WaterParameterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Deepening F-05: only the three FAO-56 single-Kc ANCHOR stages are valid
    # here (initial/mid/late — development is a linear ramp with no anchor and
    # its length is a trait, not a water parameter). Restricting the stage
    # vocabulary prevents malformed rows that would silently become zeros.
    growth_stage: Literal["initial", "mid", "late"]
    kc_value: float = Field(ge=0, le=3)
    kc_method: Literal["single", "dual"] = "single"
    stage_length_days: int | None = Field(default=None, ge=0)
    valid_region: str | None = None
    climate_context: str | None = None
    source_key: str = Field(min_length=2, max_length=80)
    evidence_class: str = Field(min_length=2, max_length=60)
    confidence: Confidence = "moderate"
    validation_status: ValidationStatus = "reference"
    notes: str | None = None


class CropIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop_code: str = Field(min_length=2, max_length=80)
    family_key: str | None = None
    scientific_name: str | None = None
    common_names: list[str] = Field(default_factory=list)
    crop_category: str | None = None
    life_cycle_type: str | None = None
    is_legume: bool = False
    is_cover_crop_capable: bool = False
    status: Literal["active", "draft", "retired"] = "active"
    traits: list[TraitIn] = Field(default_factory=list)
    calendar_windows: list[CalendarWindowIn] = Field(default_factory=list)
    water_parameters: list[WaterParameterIn] = Field(default_factory=list)


class RuleTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["crop", "family"]
    key: str = Field(min_length=2, max_length=80)


class RotationRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_code: str = Field(min_length=2, max_length=120)
    rule_type: str
    rule_definition: dict[str, Any]
    applies_to_regions: list[str] = Field(default_factory=list)
    source_key: str = Field(min_length=2, max_length=80)
    validation_status: ValidationStatus = "reference"
    severity: str = "advisory"


class KnowledgePackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_code: str = Field(min_length=2, max_length=80)
    pack_version: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    region_scope: str = "global"
    license_name: str = Field(min_length=2, max_length=200)
    attribution_text: str = Field(min_length=8)
    license_notes: str | None = None
    digitization_note: str | None = None
    sources: list[SourceIn] = Field(min_length=1)
    families: list[FamilyIn] = Field(default_factory=list)
    crops: list[CropIn] = Field(min_length=1)
    rotation_rules: list[RotationRuleIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_rule_type(self) -> "KnowledgePackIn":
        for rule in self.rotation_rules:
            if rule.rule_type not in RULE_TYPES:
                raise ValueError(f"rule '{rule.rule_code}': unknown rule_type '{rule.rule_type}'")
            if rule.severity not in SEVERITIES:
                raise ValueError(f"rule '{rule.rule_code}': unknown severity '{rule.severity}'")
            definition = rule.rule_definition
            for side in ("predecessor", "successor", "target"):
                if side in definition:
                    RuleTargetIn.model_validate(definition[side])
            if rule.rule_type in ("rotation_break", "host_pathogen", "host_pest"):
                if "predecessor" not in definition or "successor" not in definition:
                    raise ValueError(
                        f"rule '{rule.rule_code}': break-type rules need predecessor+successor"
                    )
                if int(definition.get("min_break_seasons", 0)) < 1:
                    raise ValueError(
                        f"rule '{rule.rule_code}': min_break_seasons must be >= 1"
                    )
            if "mechanism" not in definition:
                raise ValueError(f"rule '{rule.rule_code}': mechanism text is required")
        return self


class PackValidationReport(BaseModel):
    """Structured outcome of cross-referential validation."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_pack_cross_references(pack: KnowledgePackIn) -> PackValidationReport:
    """Checks that go beyond the per-model schema:

    - every source_key referenced anywhere resolves to a pack source;
    - every family_key referenced by a crop resolves;
    - every crop/family referenced by a rotation rule resolves;
    - trait values for the same (crop, trait_code, region, management,
      growth_stage) context agree — conflicting values are an error, not a
      silent overwrite;
    - pack-level license/attribution present (schema-enforced) plus
      per-source citation text present (schema-enforced) — repeated here for
      the report.
    """
    report = PackValidationReport()
    source_keys = {s.source_key for s in pack.sources}
    family_keys = {f.family_key for f in pack.families}
    crop_keys = {c.crop_code for c in pack.crops}

    def _use_source(where: str, key: str) -> None:
        if key not in source_keys:
            report.errors.append(f"{where}: unknown source_key '{key}'")

    for family in pack.families:
        if not family.scientific_name:
            report.errors.append(f"family '{family.family_key}': scientific_name required")

    context_values: dict[tuple[str, str, str, str, str], set[float | str]] = {}
    for crop in pack.crops:
        if crop.family_key and crop.family_key not in family_keys:
            report.errors.append(
                f"crop '{crop.crop_code}': unknown family_key '{crop.family_key}'"
            )
        for i, trait in enumerate(crop.traits):
            where = f"crop '{crop.crop_code}' trait[{i}] '{trait.trait_code}'"
            _use_source(where, trait.source_key)
            if trait.value_low is not None and trait.value_high is not None:
                if trait.value_low > trait.value_high:
                    report.errors.append(f"{where}: value_low > value_high")
            ctx = (
                crop.crop_code, trait.trait_code, trait.region_code or "",
                trait.management_context or "", trait.growth_stage or "",
            )
            if trait.value_numeric is not None:
                val: float | str = trait.value_numeric
            elif trait.value_text is not None:
                val = str(trait.value_text)
            else:
                val = (trait.value_low, trait.value_high)
            context_values.setdefault(ctx, set()).add(val)
        for i, window in enumerate(crop.calendar_windows):
            _use_source(f"crop '{crop.crop_code}' calendar[{i}]", window.source_key)
        for i, wp in enumerate(crop.water_parameters):
            _use_source(f"crop '{crop.crop_code}' water[{i}]", wp.source_key)
        stage_anchors = [wp.growth_stage for wp in crop.water_parameters]
        if len(stage_anchors) != len(set(stage_anchors)):
            report.errors.append(
                f"crop '{crop.crop_code}': duplicate water-parameter growth_stage"
            )
        # F-05 (continued): a partial anchor set can never drive the FAO-56
        # curve — the water estimator requires all three anchors, so a pack
        # that ships fewer is rejected instead of being zero-filled later.
        if crop.water_parameters:
            groups: dict[tuple[str, str | None], set[str]] = {}
            for wp in crop.water_parameters:
                groups.setdefault((wp.kc_method, wp.valid_region), set()).add(wp.growth_stage)
            for (method, region), stages in sorted(groups.items()):
                absent = {"initial", "mid", "late"} - stages
                if absent:
                    report.errors.append(
                        f"crop '{crop.crop_code}': incomplete Kc anchor set for "
                        f"method '{method}' region '{region or 'global'}' — missing "
                        f"{', '.join(sorted(absent))} (partial anchors are never "
                        "zero-filled at load time, so the pack must ship all three)"
                    )

    for ctx, values in context_values.items():
        if len(values) > 1:
            report.errors.append(
                f"conflicting trait values for crop '{ctx[0]}' trait '{ctx[1]}' "
                f"(region='{ctx[2]}' management='{ctx[3]}' stage='{ctx[4]}'): {sorted(map(str, values))}"
            )

    for rule in pack.rotation_rules:
        where = f"rule '{rule.rule_code}'"
        _use_source(where, rule.source_key)
        definition = rule.rule_definition
        for side in ("predecessor", "successor", "target"):
            ref = definition.get(side)
            if not ref:
                continue
            if ref.get("kind") == "crop" and ref.get("key") not in crop_keys:
                report.errors.append(f"{where}: unknown crop '{ref.get('key')}'")
            if ref.get("kind") == "family" and ref.get("key") not in family_keys:
                report.errors.append(f"{where}: unknown family '{ref.get('key')}'")

    if not pack.digitization_note:
        report.warnings.append(
            "pack has no digitization_note — provenance of transcription is unclear"
        )
    referenced_sources = set()
    for crop in pack.crops:
        referenced_sources |= {t.source_key for t in crop.traits}
        referenced_sources |= {w.source_key for w in crop.calendar_windows}
        referenced_sources |= {w.source_key for w in crop.water_parameters}
    for rule in pack.rotation_rules:
        referenced_sources.add(rule.source_key)
    for s in pack.sources:
        if s.source_key not in referenced_sources:
            report.warnings.append(f"source '{s.source_key}' is declared but never cited")

    report.counts = {
        "sources": len(pack.sources),
        "families": len(pack.families),
        "crops": len(pack.crops),
        "traits": sum(len(c.traits) for c in pack.crops),
        "calendar_windows": sum(len(c.calendar_windows) for c in pack.crops),
        "water_parameters": sum(len(c.water_parameters) for c in pack.crops),
        "rotation_rules": len(pack.rotation_rules),
    }
    return report


def pack_checksum(pack: KnowledgePackIn) -> str:
    """Stable sha256 over the canonical JSON of the pack content."""
    import hashlib
    import json

    canonical = json.dumps(pack.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

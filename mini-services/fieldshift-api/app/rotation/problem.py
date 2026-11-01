"""Pure data model for the rotation decision core (Milestone 5, ADR-0015).

These dataclasses are the ONLY interchange between the ORM/HTTP world and the
decision core (candidates / constraints / optimizer / objectives / explain).
They carry no ORM objects, no FastAPI types and no I/O.

Knowledge data is versioned at the container level: every `KnowledgeCrop`
carries the pack_code/pack_version it came from, and every attribute carries
its source citation + evidence class + confidence so the explanation layer can
render provenance end-to-end.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

ROTATION_ENGINE_VERSION = "rotation-engine-1.0.0"
SOLVER_NAME = "cp-sat"
RANDOM_SEED = 0


def solver_version() -> str:
    """Resolved OR-Tools version — written per rotation run (M7.1 F-20:
    the column existed but was never populated; reproducibility diagnostics
    need the actual solver build)."""
    try:
        import ortools

        return str(getattr(ortools, "__version__", "unknown"))
    except Exception:  # noqa: BLE001 — provenance must never break a solve
        return "unknown"

# --------------------------------------------------------------- knowledge


@dataclass(frozen=True)
class TraitValue:
    trait_code: str
    value_numeric: float | None
    value_text: str | None
    value_low: float | None
    value_high: float | None
    unit: str | None
    region_code: str | None
    evidence_class: str
    confidence: str
    validation_status: str
    source_key: str
    citation_text: str
    pack_code: str
    pack_version: str
    notes: str | None = None

    def numeric(self) -> float | None:
        return self.value_numeric


@dataclass(frozen=True)
class CalendarWindow:
    region_code: str | None
    hemisphere: str
    season_code: str | None
    planting_start: str  # MM-DD
    planting_end: str    # MM-DD
    evidence_class: str
    validation_status: str
    source_key: str
    citation_text: str
    pack_code: str
    pack_version: str
    notes: str | None = None


@dataclass(frozen=True)
class WaterParams:
    """FAO-56 single-Kc anchors; the curve is reconstructed by the estimator."""

    kc_initial: float
    kc_mid: float
    kc_late: float
    evidence_class: str
    source_key: str
    citation_text: str
    pack_code: str
    pack_version: str


@dataclass
class KnowledgeCrop:
    """Read-model container assembled by the knowledge service. Mutable on
    purpose during assembly (traits/windows accumulate); treat as read-only
    afterwards."""

    crop_code: str
    pack_code: str
    pack_version: str
    family_key: str | None
    scientific_name: str | None
    common_name: str | None
    crop_category: str | None
    life_cycle_type: str | None
    is_legume: bool
    is_cover_crop_capable: bool
    traits: dict[str, TraitValue] = field(default_factory=dict)
    calendar_windows: tuple[CalendarWindow, ...] = ()
    water_params: WaterParams | None = None

    def trait(self, code: str) -> TraitValue | None:
        return self.traits.get(code)

    def resolve_trait(self, code: str, country_code: str | None = None) -> TraitValue | None:
        """Region-aware trait resolution: an exact region-scoped value wins
        over the global value; coexisting values remain inspectable."""
        if country_code:
            regional = self.traits.get(f"{code}@{country_code}")
            if regional is not None:
                return regional
        return self.traits.get(code)

    def numeric_trait(self, code: str) -> float | None:
        t = self.traits.get(code)
        return t.value_numeric if t else None


@dataclass(frozen=True)
class RotationRuleData:
    rule_code: str
    rule_type: str
    predecessor_kind: str | None  # crop | family | None
    predecessor_key: str | None
    successor_kind: str | None
    successor_key: str | None
    min_break_seasons: int
    mechanism: str
    scope_note: str | None
    applies_to_regions: tuple[str, ...]
    validation_status: str
    severity: str
    source_key: str
    citation_text: str
    pack_code: str
    pack_version: str

    @property
    def is_hard_enforceable(self) -> bool:
        """Only regionally-confirmed rules bind the solver (ADR-0014/0016)."""
        return self.validation_status == "confirmed_regional"


@dataclass(frozen=True)
class KnowledgeBaseData:
    pack_refs: tuple[dict[str, Any], ...]
    crops: dict[str, KnowledgeCrop]
    rules: tuple[RotationRuleData, ...]
    confirmed_rule_count: int = 0
    reference_rule_count: int = 0

    def crops_from_family(self, family_key: str) -> list[str]:
        return [c for c, k in self.crops.items() if k.family_key == family_key]


# ----------------------------------------------------------------- evidence


@dataclass(frozen=True)
class ClimateEvidence:
    """Season climate aggregates derived from ONE feature run (M4).

    Planning seasons are typically in the future, so aggregates are built as a
    MONTH-OF-YEAR climatology from the run's covered years — a historical
    proxy, never a forecast. `basis` states this explicitly; `is_synthetic`
    propagates the run's honesty flag."""

    feature_run_id: str
    is_synthetic: bool
    season_precipitation_mm: float | None
    season_mean_temp_degC: float | None
    season_mean_tmax_degC: float | None
    season_hot_days_35c: float | None  # expected days (mean across years)
    season_et0_mm: float | None
    monthly_et0: tuple[tuple[int, int, float], ...]  # (year, month, mm) on the SEASON calendar
    coverage_ratio: float
    years_used: tuple[int, ...] = ()
    basis: str = "monthly climatology from the evidence feature run (historical proxy, not a forecast)"
    warnings: tuple[str, ...] = ()
    # M6A (additive): month-of-year precipitation climatology on the season
    # calendar — feeds the net irrigation requirement. Months absent from the
    # tuple are unknown (never zero-filled); the water engine treats them
    # conservatively with disclosure. Kept last to preserve field order.
    monthly_precip: tuple[tuple[int, int, float], ...] = ()


@dataclass(frozen=True)
class SoilEvidence:
    """Latest non-null soil observations for the field (point measurements or
    SoilGrids predictions — the evidence class is carried per value)."""

    ph: tuple[float, str] | None = None          # (value, evidence_class)
    organic_carbon_g_kg: tuple[float, str] | None = None
    clay_g_kg: tuple[float, str] | None = None
    sand_g_kg: tuple[float, str] | None = None
    bulk_density: tuple[float, str] | None = None


@dataclass(frozen=True)
class SeasonSpec:
    label: str
    start_date: date
    end_date: date

    @property
    def length_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


@dataclass(frozen=True)
class FarmContext:
    """Everything the engine knows about the farm/field situation."""

    field_id: str
    farm_id: str
    area_ha: float
    country_code: str
    hemisphere: str
    seasons: tuple[SeasonSpec, ...]
    soil: SoilEvidence | None
    climate_by_season: dict[str, ClimateEvidence]
    climate_run_refs: dict[str, str]  # season label -> feature run id used as evidence
    history: tuple[dict[str, Any], ...]  # [{season_label, crop_code|None, crop_label, date}]
    market_exclusions: tuple[str, ...]
    equipment_limits: tuple[str, ...]
    water_allocation_m3: float | None
    margin_index_by_crop: dict[str, float]  # farmer-supplied economics only
    synthetic_evidence_in_use: bool
    soil_evidence_class: str | None


# ------------------------------------------------------------------ problem


@dataclass(frozen=True)
class CandidateAssessment:
    """Outcome of candidate generation for one crop (M5.3)."""

    crop_code: str
    status: str  # eligible | conditionally_eligible | excluded | unevaluated
    reasons: tuple[dict[str, Any], ...] = ()
    unevaluated_dimensions: tuple[dict[str, Any], ...] = ()
    water_requirement_mm: float | None = None
    water_estimate_assumptions: tuple[str, ...] = ()
    # M6A (additive): net irrigation requirement (ETc − Pe, FAO-33 fallback) —
    # None when precipitation evidence is absent, with the reason recorded in
    # water_demand_basis. When None the allocation constraint falls back to
    # the ETc screening value (a conservative upper bound, disclosed).
    net_irrigation_requirement_mm: float | None = None
    water_demand_basis: str | None = None
    calendar_windows_matched: tuple[str, ...] = ()

    @property
    def admissible(self) -> bool:
        """Only evaluated candidates enter optimization (ADR-0016)."""
        return self.status in ("eligible", "conditionally_eligible")


@dataclass(frozen=True)
class RotationProblem:
    field_id: str
    seasons: tuple[SeasonSpec, ...]
    # candidate assessment is PER SEASON: {season_label: {crop_code: assessment}}
    candidates: dict[str, dict[str, CandidateAssessment]]
    knowledge: KnowledgeBaseData
    farm: FarmContext
    water_allocation_m3: float | None
    baseline_assignment: tuple[tuple[str, str | None], ...]  # (season_label, crop_code|None)
    synthetic_evidence: bool
    engine_version: str = ROTATION_ENGINE_VERSION
    seed: int = RANDOM_SEED

    def checksum(self) -> str:
        payload = {
            "field": self.field_id,
            "seasons": [
                {"label": s.label, "start": s.start_date.isoformat(), "end": s.end_date.isoformat()}
                for s in self.seasons
            ],
            "candidates": {
                season: sorted(crops) for season, crops in self.candidates.items()
            },
            "allocation": self.water_allocation_m3,
            "baseline": [[lbl, cc] for lbl, cc in self.baseline_assignment],
            "seed": self.seed,
            "packs": [dict(r) for r in self.knowledge.pack_refs],
            "engine": self.engine_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConstraintCheck:
    constraint_code: str
    description: str
    status: str  # satisfied | violated | not_applicable | partially_checked
    detail: str | None = None
    rule_codes: tuple[str, ...] = ()
    source_refs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CriterionResult:
    criterion_code: str
    raw_value: float | None
    unit: str
    direction: str  # maximize | minimize
    normalized: float | None
    evaluable: bool
    missing_evidence: tuple[str, ...] = ()
    derivation: str = ""
    source_refs: tuple[dict[str, Any], ...] = ()


@dataclass
class StrategySolution:
    """One strategy of a run — assignment + full evaluation evidence. Mutable
    during the evaluation pipeline (normalization/pareto annotate it); the
    persisted row is the immutable snapshot."""

    strategy_key: str
    strategy_kind: str  # optimized | baseline
    is_baseline: bool
    profile_weights: dict[str, float]
    weights_effective: dict[str, float]
    skipped_weights: dict[str, str]  # criterion -> why skipped
    assignment: tuple[tuple[str, str | None], ...]  # (season_label, crop_code|None)
    objective_value: float | None
    criteria: tuple[CriterionResult, ...]
    constraints_checked: tuple[ConstraintCheck, ...]
    evidence_coverage: float | None
    solver_status: str | None = None
    solver_wall_time_ms: int | None = None
    dominated_by: tuple[str, ...] = ()
    dominates: tuple[str, ...] = ()
    on_pareto_front: bool = False
    checksum_sha256: str | None = None

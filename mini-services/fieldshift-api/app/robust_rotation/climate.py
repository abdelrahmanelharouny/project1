"""Scenario climate evidence for robust rotation (Milestone 7.5).

Builds the M5 `ClimateEvidence` structure from an IMMUTABLE M7.3 execution
run's derived features by REUSING `app.rotation.service._season_climate`
verbatim through a read-only view adapter — the month-of-year aggregation
arithmetic exists exactly once (no duplicated math, ADR-0015 idiom).

Value-source honesty rules:

- `scenario_recalculated` rows contribute their `scenario_value` (the real
  scenario output of the M4 engine over transformed observations);
- `not_affected` rows contribute their stored `baseline_value` — the
  transformation provably does not touch that variable, so the scenario
  environment for it IS the observed environment; the identity is recorded,
  never silently assumed;
- `not_evaluated` rows are excluded (missing stays missing — most notably
  reference ET0, which M7.3 refuses to approximate; scenario water estimates
  are therefore structurally unavailable, by design).
"""

from __future__ import annotations

import calendar as cal
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from typing import Iterable

from app.db import models as dbm
from app.rotation.problem import ClimateEvidence, SeasonSpec
from app.rotation.service import MIN_CLIMATE_COVERAGE, _season_climate


@dataclass(frozen=True)
class _ShimValue:
    """Read-only stand-in for a FeatureValue row (duck-typed for
    `_season_climate`)."""

    feature_code: str
    aggregation_level: str
    period_start: datetime
    value: float | None


@dataclass(frozen=True)
class ScenarioRunView:
    """Read-only view of one ScenarioExecutionRun shaped like a FeatureRun
    for `_season_climate`, plus the value-source audit trail."""

    id: str  # the execution run id (used only for provenance text)
    values: tuple[_ShimValue, ...]
    is_synthetic: bool
    value_sources: dict[str, str] = dc_field(default_factory=dict)
    not_evaluated_codes: tuple[str, ...] = ()


def build_scenario_run_view(
    db_features: Iterable[dbm.ScenarioDerivedFeature],
    *,
    is_synthetic: bool,
) -> ScenarioRunView:
    """Monthly scenario feature rows -> the `_season_climate` view.

    Only monthly rows enter the climatology; the value-source rules above are
    applied row by row and the choice is recorded for the audit trail."""
    values: list[_ShimValue] = []
    sources: dict[str, str] = {}
    not_evaluated: set[str] = set()
    for row in db_features:
        if row.aggregation_level != "monthly":
            continue
        code = row.feature_code
        if row.evidence_status == "scenario_recalculated":
            value = row.scenario_value
            if value is not None:
                sources.setdefault(code, "scenario_recalculated")
        elif row.evidence_status == "not_affected":
            # Identity: the scenario provably leaves this variable unchanged;
            # the row's own baseline_value IS the scenario value.
            value = row.baseline_value
            if value is not None:
                sources[code] = "not_affected_baseline"
        else:
            not_evaluated.add(code)
            value = None
        values.append(_ShimValue(code, "monthly", row.period_start, value))
    return ScenarioRunView(
        id="scenario-derived-features",
        values=tuple(values),
        is_synthetic=is_synthetic,
        value_sources=sources,
        not_evaluated_codes=tuple(sorted(not_evaluated)),
    )


def scenario_season_climate(
    view: ScenarioRunView,
    season: SeasonSpec,
    *,
    execution_run_id: str,
    is_synthetic: bool,
    scenario_label: str,
) -> ClimateEvidence | None:
    """Season climate evidence from ONE scenario execution's derived features.

    Delegates the aggregation to the EXISTING M5 `_season_climate` and then
    rebuilds the provenance basis to state the scenario derivation honestly.
    ET0 fields are cleared explicitly (structurally unavailable under
    scenarios)."""
    evidence = _season_climate(view, season)  # type: ignore[arg-type]
    if evidence is None:
        return None
    basis = (
        f"month-of-year climatology from scenario execution run "
        f"{execution_run_id[:8]} derived features (transformed hypothetical "
        f"environment of scenario '{scenario_label}' — NOT observed weather "
        "and NOT a forecast)"
    )
    return ClimateEvidence(
        feature_run_id=evidence.feature_run_id,
        is_synthetic=is_synthetic,
        season_precipitation_mm=evidence.season_precipitation_mm,
        season_mean_temp_degC=evidence.season_mean_temp_degC,
        season_mean_tmax_degC=evidence.season_mean_tmax_degC,
        season_hot_days_35c=evidence.season_hot_days_35c,
        season_et0_mm=None,  # structurally unavailable under scenarios (M7.3)
        monthly_et0=(),
        coverage_ratio=evidence.coverage_ratio,
        years_used=evidence.years_used,
        basis=basis,
        warnings=evidence.warnings
        + (
            "ET0 is not recalculated under scenarios — water-requirement "
            "criteria are not evaluable in this scenario environment.",
        ),
        monthly_precip=evidence.monthly_precip,
    )


def required_months(season: SeasonSpec) -> list[tuple[int, int]]:
    """(year, month) pairs a scenario window must cover for this season."""
    out: list[tuple[int, int]] = []
    y, m = season.start_date.year, season.start_date.month
    while (y, m) <= (season.end_date.year, season.end_date.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_coverage_gaps(
    view: ScenarioRunView,
    seasons: list[SeasonSpec],
) -> dict[str, list[str]]:
    """Months (per season) missing ANY monthly row at all in the view.

    A month with rows that are all not_evaluated is NOT a structural gap —
    the engine reports it through the per-season evidence, not here."""
    present: set[tuple[int, int]] = set()
    for v in view.values:
        present.add((v.period_start.year, v.period_start.month))
    gaps: dict[str, list[str]] = {}
    for season in seasons:
        missing = [f"{y:04d}-{m:02d}" for y, m in required_months(season) if (y, m) not in present]
        if missing:
            gaps[season.label] = missing
    return gaps


def season_months_inside_window(
    season: SeasonSpec, window_start: datetime, window_end: datetime
) -> bool:
    """True when EVERY month of the season intersects the execution window.

    Used by compatibility validation BEFORE looking at rows: a scenario whose
    window does not reach a planning season cannot provide month-of-year
    evidence for it."""
    w_start = window_start.date() if isinstance(window_start, datetime) else window_start
    w_end = window_end.date() if isinstance(window_end, datetime) else window_end
    for y, m in required_months(season):
        month_start = date(y, m, 1)
        if y == season.start_date.year and m == season.start_date.month:
            month_start = season.start_date
        month_end = date(y, m, cal.monthrange(y, m)[1])
        if y == season.end_date.year and m == season.end_date.month:
            month_end = season.end_date
        if month_end < w_start or month_start > w_end:
            return False
    return True

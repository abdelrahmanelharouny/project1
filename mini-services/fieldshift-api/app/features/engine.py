"""Deterministic feature computation engine (Milestone 4).

Pure functions over normalized observations. The engine:

- assigns daily observations to LOCAL calendar days via the explicit midpoint
  rule (app.features.calendar);
- NEVER mixes temporal resolutions: monthly/pentadal observations do not
  participate in daily-bucket aggregation (they are counted and reported);
- NEVER treats missing observations as zero: accumulations sum valid days
  only and stay NULL below the definition's minimum coverage; a data gap
  interrupts dry spells instead of assuming dryness;
- propagates quality (valid/partial/insufficient_coverage/missing) and, for
  means, the standard error of the mean as uncertainty;
- computes baselines and anomalies only when the baseline window holds enough
  distinct years (>= 5), otherwise the feature is explicitly `not_evaluated`
  with the reason embedded in provenance;
- stamps every draft with full provenance (contributing observation ids,
  dataset products, processing versions, evidence classes, calendar basis)
  and a reproducibility checksum.
"""

import hashlib
import json
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from zoneinfo import ZoneInfo

from app.features import calendar as fscal
from app.features.catalog import BASELINE_MIN_YEARS, FeatureSpec

PROVENANCE_OBS_CAP = 400

VALID_STATUSES = {"valid"}


# ----------------------------------------------------------------- inputs
@dataclass
class DailyCell:
    value: float | None
    obs_id: str
    dataset_product_id: str
    processing_version: str
    evidence_class: str
    is_synthetic: bool
    quality_status: str


@dataclass
class DailySeries:
    variable: str
    cells: dict[date, DailyCell] = field(default_factory=dict)
    duplicate_assignments: int = 0
    excluded_time_supports: dict[str, int] = field(default_factory=dict)


def build_daily_series(observations: list[dict[str, Any]], variable: str, tz: ZoneInfo) -> DailySeries:
    """Bucket one variable's DAILY observations into local calendar days.

    Observations whose time_support is not 'daily' are excluded (counted) —
    mixing e.g. monthly product totals into daily buckets would double-count
    or misrepresent periods. Only observations with a usable value are
    quality-valid; missing observations create explicit empty slots? No —
    missing observations are simply absent from `cells`, and coverage math
    treats absent days as missing (never as zero).
    """
    series = DailySeries(variable=variable)
    obs_list = [o for o in observations if o["variable_code"] == variable]
    ordered = sorted(obs_list, key=lambda o: (o["period_start"], o["observed_at"]))
    for obs in ordered:
        ts = obs.get("time_support") or "daily"
        if ts != "daily":
            series.excluded_time_supports[ts] = series.excluded_time_supports.get(ts, 0) + 1
            continue
        local_day = fscal.assign_local_date(obs["period_start"], obs["period_end"], tz)
        if local_day in series.cells:
            series.duplicate_assignments += 1
            continue  # first (earliest) wins; deterministic
        value = obs.get("value")
        if obs.get("quality_status") == "missing" or value is None:
            continue  # missing stays missing; the day counts as uncovered
        series.cells[local_day] = DailyCell(
            value=float(value),
            obs_id=str(obs["id"]),
            dataset_product_id=str(obs["dataset_product_id"]),
            processing_version=obs.get("processing_version") or "unknown",
            evidence_class=obs.get("evidence_class") or "unknown",
            is_synthetic=bool(obs.get("is_synthetic")),
            quality_status=obs.get("quality_status") or "valid",
        )
    return series


# ----------------------------------------------------------------- drafts
@dataclass
class FeatureDraft:
    feature_code: str
    aggregation_level: str
    period_label: str
    period_start: datetime
    period_end: datetime
    value: float | None
    unit: str
    coverage_ratio: float | None
    n_input: int
    n_missing: int
    quality_status: str
    uncertainty_value: float | None = None
    uncertainty_type: str | None = None
    baseline_reference: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "feature_code": self.feature_code,
            "aggregation_level": self.aggregation_level,
            "period_label": self.period_label,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "value": self.value,
            "unit": self.unit,
            "coverage_ratio": self.coverage_ratio,
            "n_input": self.n_input,
            "n_missing": self.n_missing,
            "quality_status": self.quality_status,
            "uncertainty_value": self.uncertainty_value,
            "uncertainty_type": self.uncertainty_type,
            "baseline_reference": self.baseline_reference,
            "provenance": self.provenance,
        }


def _periods_overlap_days(p_start: datetime, p_end: datetime, w_start: datetime, w_end: datetime) -> tuple[datetime, datetime]:
    s = max(p_start, w_start)
    e = min(p_end, w_end)
    return s, e


def _expected_days(p_start_utc: datetime, p_end_utc: datetime, tz: ZoneInfo) -> int:
    """Number of local days whose [start, next-start) lies within the period."""
    local_start = p_start_utc.astimezone(tz).date()
    local_end = p_end_utc.astimezone(tz).date()
    days = 0
    d = local_start
    while d <= local_end:
        days += 1
        d += timedelta(days=1)
    return max(1, days)


def _checksum(draft: FeatureDraft, obs_ids: list[str]) -> str:
    payload = json.dumps(
        {
            "feature_code": draft.feature_code,
            "aggregation_level": draft.aggregation_level,
            "period_label": draft.period_label,
            "value": None if draft.value is None else round(draft.value, 6),
            "n_input": draft.n_input,
            "n_missing": draft.n_missing,
            "coverage_ratio": draft.coverage_ratio,
            "quality_status": draft.quality_status,
            "observation_ids": obs_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provenance(
    *,
    spec: FeatureSpec,
    draft: FeatureDraft,
    cells_used: list[DailyCell],
    calendar_meta: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obs_ids = [c.obs_id for c in cells_used]
    variables: dict[str, Any] = {}
    for c in cells_used:
        entry = variables.setdefault(
            "inputs",
            {
                "observation_count": 0,
                "dataset_products": [],
                "processing_versions": [],
                "evidence_classes": [],
                "is_synthetic": False,
            },
        )
        entry["observation_count"] += 1
        if c.dataset_product_id not in entry["dataset_products"]:
            entry["dataset_products"].append(c.dataset_product_id)
        if c.processing_version not in entry["processing_versions"]:
            entry["processing_versions"].append(c.processing_version)
        if c.evidence_class not in entry["evidence_classes"]:
            entry["evidence_classes"].append(c.evidence_class)
        entry["is_synthetic"] = entry["is_synthetic"] or c.is_synthetic
    prov = {
        "engine_version": calendar_meta["engine_version"],
        "definition_version": calendar_meta["definition_version"],
        "calendar": {
            "timezone": calendar_meta["timezone"],
            "hemisphere": calendar_meta["hemisphere"],
            "assignment_rule": fscal.CALENDAR_ASSIGNMENT_RULE,
        },
        "required_variables": list(spec.required_variables),
        "inputs": variables.get("inputs", {
            "observation_count": 0,
            "dataset_products": [],
            "processing_versions": [],
            "evidence_classes": [],
            "is_synthetic": False,
        }),
        "observation_ids": obs_ids[:PROVENANCE_OBS_CAP],
        "observation_count": len(obs_ids),
        "observation_ids_capped": len(obs_ids) > PROVENANCE_OBS_CAP,
        "checksum": _checksum(draft, obs_ids),
    }
    if extra:
        prov.update(extra)
    return prov


# ------------------------------------------------------------ core engine
def _iter_period_days(
    p_start_utc: datetime, p_end_utc: datetime, tz: ZoneInfo
) -> list[date]:
    d = p_start_utc.astimezone(tz).date()
    end = p_end_utc.astimezone(tz).date()
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def _series_for(spec: FeatureSpec, series_by_var: dict[str, DailySeries]) -> DailySeries:
    variable = spec.strategy_params["variable"]
    return series_by_var.get(variable) or DailySeries(variable=variable)


def _aggregate_period(
    spec: FeatureSpec,
    strategy: str,
    series: DailySeries,
    p_start: datetime,
    p_end: datetime,
    tz: ZoneInfo,
    calendar_meta: dict[str, Any],
    level: str,
    label: str,
    *,
    window_start: datetime,
    window_end: datetime,
) -> FeatureDraft:
    """One period aggregation for accumulation/mean/count/dry_spell strategies."""
    s, e = _periods_overlap_days(p_start, p_end, window_start, window_end)
    days = _iter_period_days(s, e, tz)
    expected = len(days)
    if expected == 0:
        return FeatureDraft(
            feature_code=spec.feature_code, aggregation_level=level, period_label=label,
            period_start=s, period_end=e, value=None, unit=spec.unit,
            coverage_ratio=0.0, n_input=0, n_missing=0,
            quality_status="not_evaluated",
            provenance={"reason": "Period does not overlap the run window."},
        )

    cells = [series.cells.get(d) for d in days]
    valid_cells = [c for c in cells if c is not None and c.value is not None]
    valid_days = len(valid_cells)
    missing_days = expected - valid_days
    coverage = valid_days / expected

    base_kwargs = dict(
        feature_code=spec.feature_code, aggregation_level=level, period_label=label,
        period_start=s, period_end=e, unit=spec.unit,
        coverage_ratio=round(coverage, 4), n_input=valid_days, n_missing=missing_days,
    )

    if valid_days == 0:
        return FeatureDraft(
            value=None, quality_status="missing", **base_kwargs,
            provenance=_provenance(
                spec=spec,
                draft=FeatureDraft(
                    feature_code=spec.feature_code, aggregation_level=level, period_label=label,
                    period_start=s, period_end=e, value=None, unit=spec.unit,
                    coverage_ratio=0.0, n_input=0, n_missing=missing_days, quality_status="missing",
                ),
                cells_used=[],
                calendar_meta=calendar_meta,
                extra={"reason": "No valid observations for this period."},
            ),
        )

    if coverage < spec.min_coverage_ratio:
        return FeatureDraft(
            value=None, quality_status="insufficient_coverage", **base_kwargs,
            provenance=_provenance(
                spec=spec,
                draft=FeatureDraft(
                    feature_code=spec.feature_code, aggregation_level=level, period_label=label,
                    period_start=s, period_end=e, value=None, unit=spec.unit,
                    coverage_ratio=coverage, n_input=valid_days, n_missing=missing_days,
                    quality_status="insufficient_coverage",
                ),
                cells_used=valid_cells,
                calendar_meta=calendar_meta,
                extra={
                    "reason": (
                        f"Coverage {coverage:.2f} is below the definition minimum "
                        f"{spec.min_coverage_ratio:.2f}; value not computed (missing data is "
                        "never treated as zero and totals are never scaled up)."
                    )
                },
            ),
        )

    value: float | None = None
    uncertainty: float | None = None
    uncertainty_type: str | None = None
    if strategy == "accumulation":
        value = sum(c.value for c in valid_cells)  # type: ignore[arg-type]
    elif strategy == "mean":
        values = [c.value for c in valid_cells]  # type: ignore[arg-type]
        value = sum(values) / len(values)  # type: ignore[arg-type]
        if len(values) >= 2:
            uncertainty = statistics.stdev(values) / (len(values) ** 0.5)
            uncertainty_type = "standard_error_of_mean"
    elif strategy == "count_days":
        op = spec.strategy_params["op"]
        thr = float(spec.strategy_params["threshold"])
        preds = {
            ">=": lambda v: v >= thr,
            ">": lambda v: v > thr,
            "<": lambda v: v < thr,
            "<=": lambda v: v <= thr,
        }
        pred = preds[op]
        value = float(sum(1 for c in valid_cells if pred(float(c.value))))  # type: ignore[arg-type]
    elif strategy == "dry_spell_max":
        dry_below = float(spec.strategy_params["dry_below_mm"])
        current = best = 0
        for d in days:  # ordered; missing cells interrupt the spell
            cell = series.cells.get(d)
            if cell is None or cell.value is None:
                current = 0
                continue
            if float(cell.value) < dry_below:
                current += 1
                best = max(best, current)
            else:
                current = 0
        value = float(best)
    else:  # pragma: no cover — catalog guards strategies
        raise ValueError(f"Unknown aggregation strategy '{strategy}'.")

    quality = "valid" if missing_days == 0 else "partial"
    draft = FeatureDraft(
        value=round(float(value), 4), quality_status=quality,
        uncertainty_value=uncertainty, uncertainty_type=uncertainty_type, **base_kwargs,
    )
    draft.provenance = _provenance(spec=spec, draft=draft, cells_used=valid_cells, calendar_meta=calendar_meta)
    return draft


def _daily_passthrough(
    spec: FeatureSpec, series: DailySeries, window_days: list[date],
    window_start: datetime, window_end: datetime, tz: ZoneInfo,
    calendar_meta: dict[str, Any],
) -> list[FeatureDraft]:
    drafts = []
    for d in window_days:
        cell = series.cells.get(d)
        p_start, _ = fscal.day_bounds_utc(d, tz)
        label = d.isoformat()
        if cell is None or cell.value is None:
            drafts.append(FeatureDraft(
                feature_code=spec.feature_code, aggregation_level="daily", period_label=label,
                period_start=p_start, period_end=p_start + timedelta(days=1) - timedelta(seconds=1),
                value=None, unit=spec.unit, coverage_ratio=0.0, n_input=0, n_missing=1,
                quality_status="missing",
                provenance={
                    "reason": "No valid observation for this local day (missing is never zero).",
                    "engine_version": calendar_meta["engine_version"],
                    "definition_version": calendar_meta["definition_version"],
                    "calendar": {
                        "timezone": calendar_meta["timezone"],
                        "hemisphere": calendar_meta["hemisphere"],
                        "assignment_rule": fscal.CALENDAR_ASSIGNMENT_RULE,
                    },
                    "required_variables": list(spec.required_variables),
                    "inputs": {"observation_count": 0, "dataset_products": [], "processing_versions": [], "evidence_classes": [], "is_synthetic": False},
                    "observation_ids": [], "observation_count": 0, "observation_ids_capped": False,
                },
            ))
            continue
        draft = FeatureDraft(
            feature_code=spec.feature_code, aggregation_level="daily", period_label=label,
            period_start=p_start, period_end=p_start + timedelta(days=1) - timedelta(seconds=1),
            value=round(cell.value, 4), unit=spec.unit, coverage_ratio=1.0,
            n_input=1, n_missing=0, quality_status="valid",
        )
        draft.provenance = _provenance(spec=spec, draft=draft, cells_used=[cell], calendar_meta=calendar_meta)
        drafts.append(draft)
    return drafts


def _baseline_by_calendar_month(
    monthly_drafts: list[FeatureDraft], label: str
) -> dict[str, Any] | None:
    """Climatology of the same calendar month across the run window."""
    month = int(label.split("-")[1])
    values = []
    years = set()
    for d in monthly_drafts:
        if d.value is None or d.quality_status in ("missing", "not_evaluated"):
            continue
        d_year, d_month = d.period_label.split("-")[:2]
        if int(d_month) != month:
            continue
        values.append(float(d.value))
        years.add(int(d_year))
    if len(years) < BASELINE_MIN_YEARS or len(values) < BASELINE_MIN_YEARS:
        return None
    mean = sum(values) / len(values)
    sd = statistics.stdev(values) if len(values) >= 2 else 0.0
    return {
        "calendar_month": month,
        "window_years": sorted(years),
        "n_years": len(years),
        "mean": round(mean, 4),
        "sd": round(sd, 4),
        "min_years_required": BASELINE_MIN_YEARS,
    }


def _derived_draft(
    spec: FeatureSpec,
    level: str,
    label: str,
    period_start: datetime,
    period_end: datetime,
    base_value: float | None,
    baseline: dict[str, Any] | None,
    calendar_meta: dict[str, Any],
    mode: str,
    reason: str | None = None,
) -> FeatureDraft:
    draft = FeatureDraft(
        feature_code=spec.feature_code, aggregation_level=level, period_label=label,
        period_start=period_start, period_end=period_end, value=None, unit=spec.unit,
        coverage_ratio=None, n_input=0, n_missing=0, quality_status="not_evaluated",
        baseline_reference=baseline,
    )
    if reason:
        draft.provenance = {"reason": reason, "engine_version": calendar_meta["engine_version"]}
        return draft
    if base_value is None:
        draft.provenance = {
            "reason": "Base monthly feature for this period is not available (missing or below coverage).",
            "engine_version": calendar_meta["engine_version"],
        }
        return draft
    if baseline is None:
        draft.provenance = {
            "reason": (
                f"Baseline climatology requires >= {BASELINE_MIN_YEARS} distinct years of this "
                "calendar month within the run window."
            ),
            "engine_version": calendar_meta["engine_version"],
        }
        return draft
    mean = baseline["mean"]
    sd = baseline["sd"]
    if mode == "anomaly":
        draft.value = round(base_value - mean, 4)
        draft.quality_status = "valid"
        draft.coverage_ratio = None
        draft.n_input = baseline["n_years"]
    elif mode == "anomaly_z":
        if sd <= 0:
            draft.provenance = {
                "reason": "Baseline standard deviation is zero; standardized anomaly undefined.",
                "engine_version": calendar_meta["engine_version"],
            }
            draft.baseline_reference = baseline
            return draft
        draft.value = round((base_value - mean) / sd, 4)
        draft.quality_status = "valid"
        draft.n_input = baseline["n_years"]
    draft.provenance = {
        "engine_version": calendar_meta["engine_version"],
        "definition_version": calendar_meta["definition_version"],
        "calendar": {
            "timezone": calendar_meta["timezone"],
            "hemisphere": calendar_meta["hemisphere"],
            "assignment_rule": fscal.CALENDAR_ASSIGNMENT_RULE,
        },
        "required_variables": list(spec.required_variables),
        "inputs": {"observation_count": baseline["n_years"]},
        "baseline": baseline,
        "formula": spec.formula_reference,
    }
    return draft


def compute_feature_drafts(
    *,
    observations: list[dict[str, Any]],
    specs: list[FeatureSpec],
    tz: ZoneInfo,
    hemisphere: str,
    window_start: datetime,
    window_end: datetime,
    aggregation_levels: list[str],
    crop_seasons: list[dict[str, Any]],
    engine_version: str,
    definition_version: str,
) -> tuple[list[FeatureDraft], dict[str, str], list[str]]:
    """Compute all requested feature drafts.

    Returns (drafts ordered by (level, label, code), not_evaluated_reasons by
    feature_code (representative reason), warnings).
    """
    calendar_meta = {
        "timezone": str(tz),
        "hemisphere": hemisphere,
        "engine_version": engine_version,
        "definition_version": definition_version,
    }
    warnings: list[str] = []
    not_evaluated: dict[str, str] = {}

    series_by_var: dict[str, DailySeries] = {}
    for spec in specs:
        variable = spec.strategy_params.get("variable")
        if variable and variable not in series_by_var:
            series_by_var[variable] = build_daily_series(observations, variable, tz)
    for variable, series in series_by_var.items():
        if series.duplicate_assignments:
            warnings.append(
                f"{variable}: {series.duplicate_assignments} duplicate local-day assignments "
                "were collapsed (first observation wins)."
            )
        for ts, count in series.excluded_time_supports.items():
            warnings.append(
                f"{variable}: {count} observations with time_support '{ts}' were excluded from "
                "daily-bucket aggregation (temporal resolutions are never mixed)."
            )

    drafts: list[FeatureDraft] = []

    # ---- daily passthrough ----
    if "daily" in aggregation_levels:
        w_days = _iter_period_days(window_start, window_end, tz)
        for spec in specs:
            if "daily" not in spec.aggregation_levels:
                continue
            series = _series_for(spec, series_by_var)
            drafts.extend(
                _daily_passthrough(spec, series, w_days, window_start, window_end, tz, calendar_meta)
            )

    # ---- monthly ----
    monthly_drafts_by_code: dict[str, list[FeatureDraft]] = {}
    if "monthly" in aggregation_levels:
        months = fscal.iter_months(window_start.astimezone(tz).date(), window_end.astimezone(tz).date())
        for year, month in months:
            m_start, m_end_excl = fscal.month_bounds_utc(year, month, tz)
            m_end = m_end_excl - timedelta(seconds=1)
            label = f"{year:04d}-{month:02d}"
            for spec in specs:
                if "monthly" not in spec.aggregation_levels:
                    continue
                if spec.strategy in ("accumulation", "mean", "count_days", "dry_spell_max"):
                    series = _series_for(spec, series_by_var)
                    draft = _aggregate_period(
                        spec, spec.strategy, series, m_start, m_end, tz, calendar_meta,
                        "monthly", label, window_start=window_start, window_end=window_end,
                    )
                    drafts.append(draft)
                    monthly_drafts_by_code.setdefault(spec.feature_code, []).append(draft)

    # ---- derived monthly (anomaly, z, difference) ----
    if "monthly" in aggregation_levels:
        for spec in specs:
            if "monthly" not in spec.aggregation_levels:
                continue
            if spec.strategy in ("anomaly", "anomaly_z"):
                base_code = spec.strategy_params["base_feature"]
                base_drafts = monthly_drafts_by_code.get(base_code, [])
                for base in sorted(base_drafts, key=lambda d: d.period_label):
                    baseline = _baseline_by_calendar_month(base_drafts, base.period_label)
                    draft = _derived_draft(
                        spec, "monthly", base.period_label, base.period_start, base.period_end,
                        base.value, baseline, calendar_meta, spec.strategy,
                    )
                    if draft.quality_status == "not_evaluated":
                        not_evaluated.setdefault(spec.feature_code, draft.provenance.get("reason", ""))
                    drafts.append(draft)
            elif spec.strategy == "difference":
                left_code = spec.strategy_params["left"]
                right_code = spec.strategy_params["right"]
                left_by_label = {d.period_label: d for d in monthly_drafts_by_code.get(left_code, [])}
                right_by_label = {d.period_label: d for d in monthly_drafts_by_code.get(right_code, [])}
                for label in sorted(set(left_by_label) | set(right_by_label)):
                    left = left_by_label.get(label)
                    right = right_by_label.get(label)
                    if left is None or right is None or right.value is None or left.value is None:
                        draft = _derived_draft(
                            spec, "monthly", label,
                            (left or right).period_start, (left or right).period_end,
                            None, None, calendar_meta, "difference",
                            reason="Requires both monthly totals (precipitation and ET0) for this month.",
                        )
                        not_evaluated.setdefault(spec.feature_code, draft.provenance.get("reason", ""))
                        drafts.append(draft)
                        continue
                    draft = FeatureDraft(
                        feature_code=spec.feature_code, aggregation_level="monthly",
                        period_label=label, period_start=left.period_start,
                        period_end=left.period_end,
                        value=round(left.value - right.value, 4), unit=spec.unit,
                        coverage_ratio=round(min(left.coverage_ratio or 0, right.coverage_ratio or 0), 4),
                        n_input=left.n_input + right.n_input,
                        n_missing=left.n_missing + right.n_missing,
                        quality_status="valid" if left.quality_status == "valid" and right.quality_status == "valid" else "partial",
                    )
                    draft.provenance = {
                        "engine_version": calendar_meta["engine_version"],
                        "definition_version": calendar_meta["definition_version"],
                        "calendar": {
                            "timezone": calendar_meta["timezone"],
                            "hemisphere": calendar_meta["hemisphere"],
                            "assignment_rule": fscal.CALENDAR_ASSIGNMENT_RULE,
                        },
                        "required_variables": list(spec.required_variables),
                        "derived_from": {
                            "left": {"feature_code": left_code, "value": left.value},
                            "right": {"feature_code": right_code, "value": right.value},
                        },
                    }
                    drafts.append(draft)

    # ---- seasonal ----
    if "seasonal" in aggregation_levels:
        season_labels = _season_labels_overlapping(window_start, window_end, tz, hemisphere)
        seasonal_drafts_by_code: dict[str, list[FeatureDraft]] = {}
        for label in season_labels:
            s_start, s_end_excl = fscal.season_bounds_utc(label, tz)
            s_end = s_end_excl - timedelta(seconds=1)
            for spec in specs:
                if "seasonal" not in spec.aggregation_levels:
                    continue
                if spec.strategy in ("accumulation", "mean", "count_days", "dry_spell_max"):
                    series = _series_for(spec, series_by_var)
                    draft = _aggregate_period(
                        spec, spec.strategy, series, s_start, s_end, tz, calendar_meta,
                        "seasonal", label, window_start=window_start, window_end=window_end,
                    )
                    drafts.append(draft)
                    seasonal_drafts_by_code.setdefault(spec.feature_code, []).append(draft)
        # CV across years per season
        for spec in specs:
            if "seasonal" not in spec.aggregation_levels or spec.strategy != "cv_across_years":
                continue
            base_code = spec.strategy_params["base_feature"]
            base_drafts = seasonal_drafts_by_code.get(base_code, [])
            by_season: dict[str, list[FeatureDraft]] = {}
            for d in base_drafts:
                if d.value is not None and d.quality_status not in ("missing", "not_evaluated"):
                    by_season.setdefault(d.period_label.split("-")[1], []).append(d)
            for season, items in sorted(by_season.items()):
                years = {int(d.period_label.split("-")[0]) for d in items}
                if len(years) < BASELINE_MIN_YEARS:
                    reason = (
                        f"Variability requires >= {BASELINE_MIN_YEARS} distinct years of the "
                        f"{season} season within the run window; found {len(years)}."
                    )
                    not_evaluated.setdefault(spec.feature_code, reason)
                    for d in items:
                        draft = _derived_draft(
                            spec, "seasonal", d.period_label, d.period_start, d.period_end,
                            d.value, None, calendar_meta, "cv", reason=reason,
                        )
                        drafts.append(draft)
                    continue
                values = [float(d.value) for d in items]
                mean = sum(values) / len(values)
                sd = statistics.stdev(values) if len(values) >= 2 else 0.0
                for d in sorted(items, key=lambda x: x.period_label):
                    draft = FeatureDraft(
                        feature_code=spec.feature_code, aggregation_level="seasonal",
                        period_label=d.period_label, period_start=d.period_start,
                        period_end=d.period_end, value=None, unit=spec.unit,
                        coverage_ratio=None, n_input=len(years), n_missing=0,
                        quality_status="not_evaluated",
                    )
                    if mean == 0:
                        reason = "Mean seasonal total is zero; CV undefined."
                        not_evaluated.setdefault(spec.feature_code, reason)
                        draft.provenance = {"reason": reason, "engine_version": calendar_meta["engine_version"]}
                        drafts.append(draft)
                        continue
                    draft.value = round(sd / mean, 4)
                    draft.quality_status = "valid"
                    draft.provenance = {
                        "engine_version": calendar_meta["engine_version"],
                        "definition_version": calendar_meta["definition_version"],
                        "calendar": {
                            "timezone": calendar_meta["timezone"],
                            "hemisphere": calendar_meta["hemisphere"],
                            "assignment_rule": fscal.CALENDAR_ASSIGNMENT_RULE,
                        },
                        "required_variables": list(spec.required_variables),
                        "inputs": {"observation_count": len(items)},
                        "baseline": {
                            "season": season,
                            "window_years": sorted(years),
                            "n_years": len(years),
                            "mean": round(mean, 4),
                            "sd": round(sd, 4),
                        },
                        "formula": spec.formula_reference,
                    }
                    drafts.append(draft)

    # ---- crop seasons (explicit user windows) ----
    if "crop_season" in aggregation_levels and crop_seasons:
        for season in crop_seasons:
            label = str(season["label"])[:40]
            cs_start = season["start"]
            cs_end = season["end"]
            for spec in specs:
                if "crop_season" not in spec.aggregation_levels:
                    continue
                series = _series_for(spec, series_by_var)
                draft = _aggregate_period(
                    spec, spec.strategy, series, cs_start, cs_end, tz, calendar_meta,
                    "crop_season", label, window_start=window_start, window_end=window_end,
                )
                draft.provenance = dict(draft.provenance)
                draft.provenance["crop_season_window"] = {
                    "label": label,
                    "start": cs_start.date().isoformat(),
                    "end": cs_end.date().isoformat(),
                    "source": "user_supplied_window (crop knowledge base arrives in a later milestone)",
                }
                drafts.append(draft)

    drafts.sort(key=lambda d: (
        {"daily": 0, "monthly": 1, "seasonal": 2, "crop_season": 3}[d.aggregation_level],
        d.period_label, d.feature_code,
    ))
    return drafts, not_evaluated, warnings


def _season_labels_overlapping(
    window_start: datetime, window_end: datetime, tz: ZoneInfo, hemisphere: str
) -> list[str]:
    labels: list[str] = []
    start_d = window_start.astimezone(tz).date()
    end_d = window_end.astimezone(tz).date()
    for year in range(start_d.year - 1, end_d.year + 2):
        for season in ("DJF", "MAM", "JJA", "SON"):
            label = f"{year:04d}-{season}"
            s_start, s_end_excl = fscal.season_bounds_utc(label, tz)
            if s_start <= window_end and s_end_excl - timedelta(seconds=1) >= window_start:
                # keep only seasons with at least one local day inside the window
                d = s_start.astimezone(tz).date()
                last = (s_end_excl - timedelta(seconds=1)).astimezone(tz).date()
                while d <= last:
                    if start_d <= d <= end_d:
                        labels.append(label)
                        break
                    d += timedelta(days=1)
    return labels

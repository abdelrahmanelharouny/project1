"""Seasonal-aware statistical anomaly detection (A1, Intelligence layer).

Screening over the field's LATEST succeeded feature run. P1 semantics:

Same-calendar-month baselines for MONTHLY series (January against historical
Januaries, February against Februaries, …) — the core fix. Previously every
monthly value was z-scored against the whole-series mean, so ordinary
seasonal variation (e.g. a dry June in a monsoon climate) was flagged as an
anomaly. The baseline semantics deliberately mirror the feature engine's own
same-month climatology (`app/features/engine.py::_baseline_by_calendar_month`):
same calendar month, distinct-year minimum, classified (never silently called
a WMO normal), and `includes_evaluated_period=True`. Seasonal / crop_season
series (few rows per year by design) keep whole-series baselines.

Finding kinds (mutually exclusive, per observation):
- "anomaly"     — |z_same_month| >= Z_THRESHOLD: statistically unusual FOR
                  THIS CALENDAR MONTH (the real screening signal).
- "trend"       — the TREND_LENGTH most recent same-month (or most recent
                  seasonal) values all shift the same direction with
                  |z| >= TREND_Z_THRESHOLD: a persistent shift, not a one-off.
- "seasonal_variation" — deviates from the WHOLE-series mean but NOT from its
                  own calendar-month baseline: ordinary seasonality, reported
                  for transparency, explicitly NOT an anomaly.
- "insufficient_baseline" — the month has fewer than BASELINE_MIN_YEARS
                  distinct years in the run window: no same-month baseline is
                  claimed; reported once per (code, month) so consumers know
                  the screening is blind there (missing months, short runs,
                  incomplete observations). Never an anomaly.

Honesty contract:
- Baselines are per-(code, aggregation_level, calendar_month) — no cross-code
  or cross-run mixing; provenance (baseline window years, n_years, class)
  travels in every finding.
- Series with zero variance are skipped (z undefined), never reported.
- Zero-variance within a calendar month falls back to whole-series stats only
  for the seasonal_variation check, never for "anomaly".
- The output is a SCREENING product: statistical unusualness against this
  field's own history, not an agronomic diagnosis.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm

logger = logging.getLogger("croptwist.intelligence.anomaly")

MIN_VALUES = 5                 # whole-series minimum for ANY screening
BASELINE_MIN_YEARS = 2         # same as the feature engine's climatology
Z_THRESHOLD = 1.5
TREND_LENGTH = 3
TREND_Z_THRESHOLD = 1.0
MAX_FINDINGS = 12
_INCLUDED_LEVELS = ("monthly", "seasonal", "crop_season")


def _month_of(row: dbm.FeatureValue) -> int | None:
    """Calendar month of a monthly row's period_start (None when unknown)."""
    start = row.period_start
    if start is None:
        return None
    return int(start.month)


def _same_month_stats(
    rows: list[dbm.FeatureValue], month: int
) -> dict[str, Any] | None:
    """Mean/σ of one calendar month across distinct years (engine parity).

    Mirrors _baseline_by_calendar_month: values from the same calendar month,
    requiring BASELINE_MIN_YEARS distinct years; population σ for z-scores
    (documented difference from the engine's sample stdev — the screener has
    always used population σ and states it in every finding's detail text).
    """
    values: list[float] = []
    years: set[int] = set()
    for row in rows:
        if row.value is None or row.quality_status in ("missing", "not_evaluated"):
            continue
        row_month = _month_of(row)
        if row_month != month:
            continue
        start = row.period_start
        if start is not None:
            years.add(int(start.year))
        values.append(float(row.value))
    if len(years) < BASELINE_MIN_YEARS or len(values) < BASELINE_MIN_YEARS:
        return None
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    return {
        "calendar_month": month,
        "window_years": sorted(years),
        "n_years": len(years),
        "n_values": len(values),
        "mean": round(mean, 4),
        "sd": round(stdev, 4),
        "min_years_required": BASELINE_MIN_YEARS,
        "baseline_class": (
            "long_record_reference" if len(years) >= 30 else "short_record_exploratory"
        ),
        "includes_evaluated_period": True,
    }


def _whole_series(rows: list[dbm.FeatureValue]) -> tuple[list[float], float, float] | None:
    values = [float(r.value) for r in rows if r.value is not None]
    if len(values) < MIN_VALUES:
        return None
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if stdev <= 1e-12:
        return None
    return values, mean, stdev


def _finding(
    row: dbm.FeatureValue,
    kind: str,
    code: str,
    level: str,
    value: float,
    baseline_mean: float,
    z: float,
    unit: str,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    detail_basis = (
        f"same-month baseline for calendar month {baseline['calendar_month']} "
        f"({baseline.get('n_years', 0)} distinct years, "
        f"{baseline.get('baseline_class', 'insufficient_record')}, "
        f"mean {baseline.get('mean', 'n/a')}, "
        f"population σ {baseline.get('sd', 'n/a')})"
        if baseline is not None
        else f"whole-series mean {round(baseline_mean, 4)} (population σ)"
    )
    if kind == "seasonal_variation":
        verdict = (
            f"ordinary seasonal variation: {code} ({level}) was {value:g} {unit} "
            f"in {row.period_label} — {abs(round(z, 2))}σ from the field's whole-series "
            f"mean {round(baseline_mean, 4)} {unit} but within its "
            f"{detail_basis}. Not an anomaly."
        )
    elif kind == "insufficient_baseline":
        verdict = (
            f"insufficient historical evidence: calendar month {baseline['calendar_month']} "
            f"has {baseline['n_years']} distinct year(s) in the run window, below the "
            f"{BASELINE_MIN_YEARS}-year minimum — {code} ({level}) is not screened "
            f"this month (missing/incomplete history is reported, never estimated)."
        )
    elif kind == "trend":
        verdict = (
            f"persistent shift: {code} ({level}) ran {z:+.2f}σ or beyond in the same "
            f"direction for the last {TREND_LENGTH} periods "
            f"({detail_basis}); value {value:g} {unit} in {row.period_label}."
        )
    else:
        verdict = (
            f"{code} ({level}) was {value:g} {unit} in {row.period_label} — "
            f"{abs(round(z, 2))}σ from its {detail_basis}."
        )
    finding: dict[str, Any] = {
        "kind": kind,
        "metric": code,
        "aggregation_level": level,
        "value": row.value,
        "baseline_mean": round(baseline_mean, 4),
        "z": round(z, 3),
        "direction": "above" if z >= 0 else "below",
        "period": row.period_label,
        "detail": verdict,
    }
    if baseline is not None and "window_years" in baseline:
        finding["baseline"] = {
            "calendar_month": baseline["calendar_month"],
            "window_years": baseline["window_years"],
            "n_years": baseline["n_years"],
            "mean": baseline["mean"],
            "sd": baseline["sd"],
            "class": baseline["baseline_class"],
            "includes_evaluated_period": baseline["includes_evaluated_period"],
        }
    return finding


def detect_feature_anomalies(db: Session, field_id: Any) -> list[dict[str, Any]]:
    """Seasonal-aware screening over the latest feature run's values.

    Returns findings ordered by screening relevance (anomalies/trends by |z|
    first, then seasonal_variation / insufficient_baseline), capped at
    MAX_FINDINGS. Empty when the field has no succeeded feature run (a data
    gap, not an error).
    """
    run = db.scalar(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field_id, dbm.FeatureRun.status == "succeeded")
        .order_by(dbm.FeatureRun.completed_at.desc().nullslast(), dbm.FeatureRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return []

    series: dict[tuple[str, str], list[dbm.FeatureValue]] = {}
    for row in run.values:
        if row.value is None or row.aggregation_level not in _INCLUDED_LEVELS:
            continue
        if row.quality_status not in ("valid", "partial"):
            continue
        series.setdefault((row.feature_code, row.aggregation_level), []).append(row)

    findings: list[dict[str, Any]] = []
    for (code, level), rows in sorted(series.items()):
        whole = _whole_series(rows)
        if whole is None:
            continue  # too short or zero-variance: screening honestly silent
        _values, whole_mean, whole_stdev = whole

        if level == "monthly":
            findings.extend(_screen_monthly(code, level, rows, whole_mean, whole_stdev))
        else:
            findings.extend(_screen_seasonal(code, level, rows, whole_mean, whole_stdev))

    # Anomalies and trends dominate; informational kinds follow, each capped.
    priority = {"anomaly": 0, "trend": 1, "seasonal_variation": 2, "insufficient_baseline": 3}
    findings.sort(key=lambda f: (priority.get(f["kind"], 9), -abs(float(f["z"] or 0))))
    hard_signals = [f for f in findings if f["kind"] in ("anomaly", "trend")]
    soft_signals = [f for f in findings if f["kind"] not in ("anomaly", "trend")]
    if len(hard_signals) > MAX_FINDINGS:
        logger.info(
            "anomaly screening capped for field %s: %s hard findings -> %s",
            field_id, len(hard_signals), MAX_FINDINGS,
        )
        hard_signals = hard_signals[:MAX_FINDINGS]
    # Soft kinds are transparency products: never crowd out real anomalies.
    findings = hard_signals + soft_signals[:8]
    return findings


def _screen_monthly(
    code: str,
    level: str,
    rows: list[dbm.FeatureValue],
    whole_mean: float,
    whole_stdev: float,
) -> list[dict[str, Any]]:
    """Same-month screening for one monthly series."""
    out: list[dict[str, Any]] = []
    recent_by_month: dict[int, list[dbm.FeatureValue]] = {}
    insufficient_seen: set[int] = set()

    for row in sorted(rows, key=lambda r: (r.period_start or r.created_at)):
        month = _month_of(row)
        if month is None:
            continue
        value = float(row.value)
        baseline = _same_month_stats(rows, month)

        if baseline is None:
            if month not in insufficient_seen:
                insufficient_seen.add(month)
                out.append(_finding(
                    row, "insufficient_baseline", code, level, value,
                    whole_mean, 0.0, row.unit or "",
                    {"calendar_month": month, "n_years": len({
                        r.period_start.year for r in rows
                        if r.period_start is not None and _month_of(r) == month
                    })},
                ))
            continue

        month_sd = baseline["sd"]
        if month_sd > 1e-12:
            z_month = (value - baseline["mean"]) / month_sd
            if abs(z_month) >= Z_THRESHOLD:
                out.append(_finding(
                    row, "anomaly", code, level, value,
                    baseline["mean"], z_month, row.unit or "", baseline,
                ))
            elif abs(value - whole_mean) / whole_stdev >= Z_THRESHOLD:
                # Deviates from the whole series but not from its own month:
                # exactly the seasonal-variation case A1 exists for.
                z_whole = (value - whole_mean) / whole_stdev
                out.append(_finding(
                    row, "seasonal_variation", code, level, value,
                    whole_mean, z_whole, row.unit or "", baseline,
                ))
        recent_by_month.setdefault(month, []).append(row)

    # Trends: per calendar month, last TREND_LENGTH same-month values.
    for month, month_rows in recent_by_month.items():
        if len(month_rows) < TREND_LENGTH:
            continue
        baseline = _same_month_stats(rows, month)
        if baseline is None or baseline["sd"] <= 1e-12:
            continue
        recent = month_rows[-TREND_LENGTH:]
        zs = [
            (float(r.value) - baseline["mean"]) / baseline["sd"]
            for r in recent
        ]
        if all(z >= TREND_Z_THRESHOLD for z in zs) or all(z <= -TREND_Z_THRESHOLD for z in zs):
            last = recent[-1]
            out.append(_finding(
                last, "trend", code, level, float(last.value),
                baseline["mean"], zs[-1], last.unit or "", baseline,
            ))
    return out


def _screen_seasonal(
    code: str,
    level: str,
    rows: list[dbm.FeatureValue],
    whole_mean: float,
    whole_stdev: float,
) -> list[dict[str, Any]]:
    """Seasonal / crop-season series keep whole-series baselines (few rows
    per year by design; a calendar-month split would leave <2 years)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        z = (float(row.value) - whole_mean) / whole_stdev
        if abs(z) >= Z_THRESHOLD:
            out.append(_finding(
                row, "anomaly", code, level, float(row.value),
                whole_mean, z, row.unit or "", None,
            ))
    recent = sorted(rows, key=lambda r: (r.period_start or r.created_at))[-TREND_LENGTH:]
    if len(recent) == TREND_LENGTH:
        zs = [(float(r.value) - whole_mean) / whole_stdev for r in recent]
        if all(z >= TREND_Z_THRESHOLD for z in zs) or all(z <= -TREND_Z_THRESHOLD for z in zs):
            out.append(_finding(
                recent[-1], "trend", code, level, float(recent[-1].value),
                whole_mean, zs[-1], recent[-1].unit or "", None,
            ))
    return out

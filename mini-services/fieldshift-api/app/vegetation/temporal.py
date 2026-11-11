"""Temporal vegetation intelligence (P2.A) — seasonal baselines and change.

Core honesty rules (mirroring the P1 seasonal anomaly screener):
- Monthly index statistics are compared ONLY against the SAME calendar month
  in previous years (same-month climatology baseline). Low NDVI in a dormant
  month is normal — never flagged as decline by cross-month comparison.
- A baseline requires >= BASELINE_MIN_YEARS distinct prior years; fewer
  yields `insufficient_baseline`, never a fabricated z-score.
- Population standard deviation (consistent with
  app/intelligence/anomaly.py `_same_month_stats` and the feature engine).
- Trend detection is a least-squares slope over same-month values with the
  slope unit stated (index units / year) and an explicit "exploratory,
  not causal" label. It does NOT diagnose disease, drought or nutrient
  deficiency — observed change and inferred causes are kept separate
  (stress.py handles evidence-based cause context).
- Dormancy/harvest awareness: when crop calendar windows exist for the
  field's crops, observations inside documented off-season windows are
  labelled `seasonal_dormancy_or_harvest` context rather than anomalies.
- Cloud-awareness: observations carry quality flags; rows flagged with
  CLOUD_* or quality_status != 'valid' are EXCLUDED from statistics and
  reported as missing-observation gaps, never averaged in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TEMPORAL_VERSION = "veg-temporal-1.0.0"

BASELINE_MIN_YEARS = 2  # consistent with intelligence/anomaly.py
MIN_VALUES_PER_MONTH = 3
Z_THRESHOLD = 1.5
TREND_MIN_MONTHS = 4
TREND_Z_THRESHOLD = 1.0
MAX_FINDINGS = 12

# Observation quality flags that disqualify an index value from statistics
# (cloud/shadow contamination family; providers use these prefixes).
DISQUALIFYING_FLAG_PREFIXES = ("CLOUD", "SHADOW", "SATURATED", "NODATA")


@dataclass
class MonthlyStat:
    year: int
    month: int
    mean: float
    n_valid: int
    n_excluded: int
    flags: list[str] = field(default_factory=list)


@dataclass
class Baseline:
    month: int
    mean: float
    sd: float
    n_years: int
    window_years: list[int]
    classification: str  # long_record_reference | short_record_exploratory | insufficient


def _is_disqualified(metadata: dict[str, Any] | None, quality_status: str | None) -> bool:
    if quality_status is not None and quality_status != "valid":
        return True
    if not metadata:
        return False
    flags = metadata.get("quality_flags") or []
    for flag in flags:
        code = flag.get("flag_code") if isinstance(flag, dict) else str(flag)
        if any(code.startswith(prefix) for prefix in DISQUALIFYING_FLAG_PREFIXES):
            return True
    return False


def monthly_statistics(
    observations: list[dict[str, Any]],
) -> tuple[list[MonthlyStat], int]:
    """Aggregate valid index observations into calendar-month statistics.

    `observations` rows: {value, observed_at, quality_status, metadata}.
    Cloud/shadow-flagged and non-valid rows are EXCLUDED (counted, not
    averaged). Returns (stats sorted by period, excluded_count).
    """
    buckets: dict[tuple[int, int], list[float]] = {}
    excluded_counts: dict[tuple[int, int], int] = {}
    excluded_total = 0
    for obs in observations:
        value = obs.get("value")
        observed_at = obs.get("observed_at")
        if value is None or observed_at is None:
            continue
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        key = (observed_at.year, observed_at.month)
        if _is_disqualified(obs.get("metadata"), obs.get("quality_status")):
            excluded_counts[key] = excluded_counts.get(key, 0) + 1
            excluded_total += 1
            continue
        buckets.setdefault(key, []).append(float(value))
    stats: list[MonthlyStat] = []
    for (year, month), values in sorted(buckets.items()):
        if not values:
            continue
        stats.append(
            MonthlyStat(
                year=year,
                month=month,
                mean=sum(values) / len(values),
                n_valid=len(values),
                n_excluded=excluded_counts.get((year, month), 0),
                flags=[],
            )
        )
    return stats, excluded_total


def same_month_baseline(
    stats: list[MonthlyStat],
    month: int,
    *,
    exclude_year: int | None = None,
) -> Baseline:
    """Same-calendar-month climatology baseline over PRIOR years only.

    `exclude_year` removes the evaluated year from the baseline (temporal
    honesty: the evaluated period never contributes to its own baseline).
    """
    prior = [s for s in stats if s.month == month and (exclude_year is None or s.year != exclude_year)]
    if not prior:
        return Baseline(
            month=month, mean=math.nan, sd=math.nan, n_years=0, window_years=[], classification="insufficient"
        )
    window_years = sorted({s.year for s in prior})
    means = [s.mean for s in prior]
    mean = sum(means) / len(means)
    sd = math.sqrt(sum((m - mean) ** 2 for m in means) / len(means))  # population
    if len(window_years) >= 10:
        classification = "long_record_reference"
    else:
        classification = "short_record_exploratory"
    if len(window_years) < BASELINE_MIN_YEARS:
        classification = "insufficient"
    return Baseline(
        month=month,
        mean=mean,
        sd=sd,
        n_years=len(window_years),
        window_years=window_years,
        classification=classification,
    )


def detect_temporal_findings(
    *,
    stats: list[MonthlyStat],
    index: str,
    dormancy_months: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Detect vegetation anomalies/trends against same-month baselines.

    Findings carry `kind` ∈ {anomaly, trend, seasonal_variation,
    insufficient_baseline}; every anomaly/trend cites its baseline (years,
    mean, sd, class). Dormancy months (from crop calendars, when known) are
    screened but any finding there is labelled with
    `context: seasonal_dormancy_or_harvest` instead of implying decline.
    Low NDVI alone NEVER maps to a disease/nutrient claim here — the finding
    reports the observed statistical change only.
    """
    findings: list[dict[str, Any]] = []
    dormancy = dormancy_months or set()
    for stat in stats:
        baseline = same_month_baseline(stats, stat.month, exclude_year=stat.year)
        if baseline.classification == "insufficient" or baseline.n_years < BASELINE_MIN_YEARS:
            if stat.n_valid >= MIN_VALUES_PER_MONTH:
                findings.append(
                    {
                        "kind": "insufficient_baseline",
                        "index": index,
                        "period": {"year": stat.year, "month": stat.month},
                        "value": stat.mean,
                        "n_valid": stat.n_valid,
                        "detail": (
                            f"{index.upper()} {stat.year}-{stat.month:02d} has no usable "
                            f"same-month baseline ({baseline.n_years} prior year(s); "
                            f"need >= {BASELINE_MIN_YEARS})."
                        ),
                    }
                )
            continue
        if baseline.sd <= 1e-9 or stat.n_valid < MIN_VALUES_PER_MONTH:
            continue
        z = (stat.mean - baseline.mean) / baseline.sd
        in_dormancy = stat.month in dormancy
        if abs(z) >= Z_THRESHOLD:
            direction = "below_baseline" if z < 0 else "above_baseline"
            finding: dict[str, Any] = {
                "kind": "anomaly",
                "index": index,
                "period": {"year": stat.year, "month": stat.month},
                "value": stat.mean,
                "baseline_mean": baseline.mean,
                "baseline_sd": baseline.sd,
                "z": round(z, 3),
                "direction": direction,
                "n_valid": stat.n_valid,
                "n_excluded_cloud": stat.n_excluded,
                "baseline": {
                    "window_years": baseline.window_years,
                    "n_years": baseline.n_years,
                    "class": baseline.classification,
                },
                "detail": (
                    f"{index.upper()} {stat.year}-{stat.month:02d} is {abs(z):.1f} "
                    f"standard deviations {direction.replace('_', ' ')} of the same-month "
                    f"baseline ({baseline.n_years} years, {baseline.classification})."
                ),
            }
            if in_dormancy:
                finding["context"] = "seasonal_dormancy_or_harvest"
            findings.append(finding)
    # Trend: least-squares slope over same-month means across years.
    for month in sorted({s.month for s in stats}):
        series = sorted((s for s in stats if s.month == month), key=lambda s: s.year)
        if len(series) < TREND_MIN_MONTHS:
            continue
        years = [float(s.year) for s in series]
        values = [s.mean for s in series]
        n = len(values)
        mean_x = sum(years) / n
        mean_y = sum(values) / n
        denom = sum((x - mean_x) ** 2 for x in years)
        if denom <= 1e-12:
            continue
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(years, values)) / denom
        residuals = [y - (slope * x + mean_y - slope * mean_x) for x, y in zip(years, values)]
        sd_res = math.sqrt(sum(r * r for r in residuals) / n) if n > 0 else 0.0
        if sd_res <= 1e-9:
            continue
        # Normalized slope signal in sd-of-residuals per year (exploratory).
        slope_signal = slope / sd_res
        if abs(slope_signal) >= TREND_Z_THRESHOLD:
            findings.append(
                {
                    "kind": "trend",
                    "index": index,
                    "period": {"month": month},
                    "slope_per_year": round(slope, 5),
                    "slope_signal": round(slope_signal, 3),
                    "direction": "declining" if slope < 0 else "increasing",
                    "n_years": len({s.year for s in series}),
                    "detail": (
                        f"Exploratory {index.upper()} {direction if slope < 0 else 'increase'} "
                        f"trend of {slope:+.4f}/yr for calendar month {month} across "
                        f"{len({s.year for s in series})} years. Descriptive only — "
                        "not a causal diagnosis."
                    ),
                    "context": "seasonal_dormancy_or_harvest" if month in dormancy else None,
                }
            )
    # Deterministic ordering: anomalies by |z| desc, then trends, then gaps.
    findings.sort(
        key=lambda f: (
            {"anomaly": 0, "trend": 1, "insufficient_baseline": 2}.get(f["kind"], 3),
            -abs(f.get("z", f.get("slope_signal", 0)) or 0),
        )
    )
    return findings[:MAX_FINDINGS]


def classify_series_state(
    *,
    stats: list[MonthlyStat],
    index: str,
) -> dict[str, Any]:
    """Honest summary of what the temporal record can and cannot say."""
    if not stats:
        return {
            "state": "no_data",
            "detail": f"No valid {index} observations exist for this field.",
            "can_assess": False,
        }
    years = sorted({s.year for s in stats})
    if len(years) < BASELINE_MIN_YEARS:
        return {
            "state": "insufficient_history",
            "detail": (
                f"{index.upper()} observations cover {len(years)} year(s); "
                f"seasonal comparison needs >= {BASELINE_MIN_YEARS}."
            ),
            "can_assess": False,
            "years": years,
        }
    return {
        "state": "assessable",
        "detail": (
            f"{index.upper()} record spans {years[0]}-{years[-1]} "
            f"({len(stats)} monthly aggregates)."
        ),
        "can_assess": True,
        "years": years,
    }

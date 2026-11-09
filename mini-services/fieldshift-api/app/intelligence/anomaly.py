"""Statistical anomaly detection over feature-run values (Intelligence layer).

Pure statistics — no ML dependencies (numpy is available, but the stdlib is
sufficient and keeps the layer dependency-free). For each numeric feature code
of the field's LATEST succeeded feature run with at least MIN_VALUES
monthly/seasonal values, values are z-scored against that series' own mean and
POPULATION standard deviation; |z| >= Z_THRESHOLD flags an anomaly. A sustained
same-direction shift over the three most recent periods is additionally
reported as a trend.

Honesty contract:
- Baselines are per-series (same code, same aggregation level) — no cross-code
  or cross-run mixing.
- Series with zero variance are skipped (z is undefined), never reported as
  anomalies.
- The anomaly list is a SCREENING output: it names what is statistically
  unusual for this field's own history; it is not a agronomic diagnosis.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm

logger = logging.getLogger("fieldshift.intelligence.anomaly")

MIN_VALUES = 5
Z_THRESHOLD = 1.5
TREND_LENGTH = 3
TREND_Z_THRESHOLD = 1.0
MAX_FINDINGS = 12
_INCLUDED_LEVELS = ("monthly", "seasonal", "crop_season")


def detect_feature_anomalies(db: Session, field_id: Any) -> list[dict[str, Any]]:
    """Z-score screening over the latest feature run's values for the field.

    Returns a list of findings:
        {"kind": "anomaly" | "trend", "metric": <feature_code>,
         "aggregation_level": ..., "value": ..., "baseline_mean": ...,
         "z": ..., "direction": "above" | "below", "detail": str}
    Ordered by |z| descending, capped at MAX_FINDINGS. Empty when the field
    has no succeeded feature run (a data gap, not an error).
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
        if len(rows) < MIN_VALUES:
            continue
        values = [float(r.value) for r in rows]
        mean = statistics.fmean(values)
        stdev = statistics.pstdev(values)
        if stdev <= 1e-12:
            continue  # zero-variance series: z is undefined, skip honestly

        def _finding(row: dbm.FeatureValue, kind: str) -> dict[str, Any]:
            z = (float(row.value) - mean) / stdev
            return {
                "kind": kind,
                "metric": code,
                "aggregation_level": level,
                "value": row.value,
                "baseline_mean": round(mean, 4),
                "z": round(z, 3),
                "direction": "above" if z >= 0 else "below",
                "period": row.period_label,
                "detail": (
                    f"{code} ({level}) was {row.value} {row.unit} in {row.period_label} — "
                    f"{abs(round(z, 2))}σ {'above' if z >= 0 else 'below'} this field's "
                    f"own {len(values)}-period mean {round(mean, 4)} {row.unit} "
                    f"(population σ {round(stdev, 4)})."
                ),
            }

        for row in rows:
            z = (float(row.value) - mean) / stdev
            if abs(z) >= Z_THRESHOLD:
                findings.append(_finding(row, "anomaly"))

        # Sustained shift: the TREND_LENGTH most recent periods all deviate in
        # the same direction with |z| >= TREND_Z_THRESHOLD.
        recent = sorted(rows, key=lambda r: r.period_start)[-TREND_LENGTH:]
        if len(recent) == TREND_LENGTH:
            zs = [(float(r.value) - mean) / stdev for r in recent]
            if all(z >= TREND_Z_THRESHOLD for z in zs) or all(z <= -TREND_Z_THRESHOLD for z in zs):
                findings.append(_finding(recent[-1], "trend"))

    findings.sort(key=lambda f: abs(f["z"]), reverse=True)
    if len(findings) > MAX_FINDINGS:
        logger.info(
            "anomaly screening capped for field %s: %s findings -> %s",
            field_id, len(findings), MAX_FINDINGS,
        )
        findings = findings[:MAX_FINDINGS]
    return findings

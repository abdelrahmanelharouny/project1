"""Vegetation intelligence service (P2.A) — assembly + persistence bridge.

Reads index observations for a field (from the single `observations` store),
runs the temporal analysis (same-month baselines, anomalies, trends,
dormancy context), cross-references climate/water/rotation evidence for
stress signals, and assembles the UI payload. Pure computation lives in
`temporal.py` / `stress.py`; this module is the DB bridge (project
convention: decision cores stay free of ORM).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Field, Observation
from app.intelligence.evidence import build_field_evidence
from app.intelligence.anomaly import detect_feature_anomalies
from app.vegetation.indices import INDEX_FORMULAS, supported_indices
from app.vegetation.temporal import (
    TEMPORAL_VERSION,
    classify_series_state,
    detect_temporal_findings,
    monthly_statistics,
)
from app.vegetation.stress import VEGETATION_STRESS_VERSION, build_stress_signals

logger = logging.getLogger("croptwist.vegetation.service")

VEGETATION_SERVICE_VERSION = "vegetation-service-1.0.0"

# Crop calendar dormancy context: months inside documented harvest windows
# of the crops that actually grew on the field are labelled (not excluded)
# so post-harvest declines aren't misread as stress.
def _dormancy_months(db: Session, field_id: uuid.UUID) -> set[int]:
    from app.db.models import CropCalendarWindow, CropHistory

    history = list(
        db.scalars(select(CropHistory).where(CropHistory.field_id == field_id))
    )
    crop_ids = [h.crop_id for h in history if h.crop_id is not None]
    # Farmer harvest dates are the most direct dormancy context.
    months: set[int] = set()
    for h in history:
        if h.harvest_date is not None:
            months.add(h.harvest_date.month)
    if crop_ids:
        windows = list(
            db.scalars(
                select(CropCalendarWindow).where(CropCalendarWindow.crop_id.in_(crop_ids))
            )
        )
        for window in windows:
            raw_start, raw_end = window.harvest_start, window.harvest_end
            if not raw_start or not raw_end:
                continue
            try:
                sm, sd = int(raw_start.split("-")[0]), int(raw_start.split("-")[1])
                em, ed = int(raw_end.split("-")[0]), int(raw_end.split("-")[1])
            except (ValueError, AttributeError):
                continue
            if (sm, sd) <= (em, ed):
                months.update(range(sm, em + 1))
            else:  # wraps year end
                months.update(list(range(sm, 13)) + list(range(1, em + 1)))
    return months


def index_observations(
    db: Session, field_id: uuid.UUID, index: str
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(Observation)
            .where(
                Observation.field_id == field_id,
                Observation.variable_code == index,
            )
            .order_by(Observation.observed_at.asc())
        )
    )
    return [
        {
            "value": r.value,
            "observed_at": r.observed_at,
            "quality_status": r.quality_status,
            "metadata": r.metadata or {},
        }
        for r in rows
    ]


def vegetation_summary(
    db: Session,
    field: Field,
    *,
    index: str = "ndvi",
) -> dict[str, Any]:
    """Full vegetation intelligence payload for one field + index."""
    if index not in supported_indices():
        from app.core.errors import InvalidDateRange

        raise InvalidDateRange(
            f"Unknown vegetation index '{index}'.",
            details=[{"field": "index", "reason": f"supported: {', '.join(supported_indices())}"}],
        )
    observations = index_observations(db, field.id, index)
    stats, excluded_total = monthly_statistics(observations)
    dormancy = _dormancy_months(db, field.id)
    findings = detect_temporal_findings(stats=stats, index=index, dormancy_months=dormancy)

    evidence = build_field_evidence(db, field)
    anomalies = detect_feature_anomalies(db, field.id)
    stress_signals = build_stress_signals(
        index=index, findings=findings, evidence=evidence, anomalies=anomalies
    )

    valid_scenes = sum(1 for o in observations if o["value"] is not None)
    missing_or_cloudy = sum(1 for o in observations if o["value"] is None)
    series_state = classify_series_state(stats=stats, index=index)

    monthly_payload = [
        {
            "year": s.year,
            "month": s.month,
            "mean": round(s.mean, 4),
            "n_valid": s.n_valid,
            "n_excluded_cloud": s.n_excluded,
        }
        for s in stats
    ]
    scene_payload = [
        {
            "observed_at": o["observed_at"].isoformat() if o.get("observed_at") else None,
            "value": o["value"],
            "quality_status": o.get("quality_status"),
            "cloud_cover_pct": (o.get("metadata") or {}).get("cloud_cover_pct"),
            "scene_id": (o.get("metadata") or {}).get("scene_id"),
            "spatial_resolution_m": (o.get("metadata") or {}).get("spatial_resolution_m"),
            "platform": (o.get("metadata") or {}).get("platform"),
        }
        for o in observations[-200:]
    ]
    return {
        "field_id": str(field.id),
        "index": index,
        "formula": INDEX_FORMULAS.get(index),
        "series_state": series_state,
        "monthly_stats": monthly_payload,
        "findings": findings,
        "stress_signals": stress_signals,
        "data_gaps": _data_gaps(index, valid_scenes, missing_or_cloudy, series_state),
        "observation_counts": {
            "total": len(observations),
            "valid": valid_scenes,
            "missing_or_cloudy": missing_or_cloudy,
            "cloud_excluded_from_stats": excluded_total,
        },
        "scenes": scene_payload,
        "dormancy_months_hint": sorted(dormancy) if dormancy else None,
        "engine_versions": {
            "service": VEGETATION_SERVICE_VERSION,
            "temporal": TEMPORAL_VERSION,
            "stress": VEGETATION_STRESS_VERSION,
        },
        "limitations": [
            "Vegetation indices are satellite-derived surface reflectance "
            "estimates; they are not ground measurements.",
            "Statistical anomalies compare SAME calendar months only; low "
            "NDVI in a documented dormant month is not a decline signal.",
            "No disease, pest, or nutrient-deficiency diagnosis is made from "
            "NDVI alone — stress signals only list corroborating environmental "
            "evidence and explicitly state what is not supported.",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _data_gaps(
    index: str, valid_scenes: int, missing_or_cloudy: int, series_state: dict[str, Any]
) -> list[str]:
    gaps: list[str] = []
    if valid_scenes == 0:
        gaps.append(
            f"No valid {index} observations exist for this field. Ingest a "
            "satellite product (live Sentinel-2 requires network access; a "
            "synthetic fixture is available for demos)."
        )
    else:
        if missing_or_cloudy > 0:
            gaps.append(
                f"{missing_or_cloudy} scene(s) are missing or cloud-contaminated "
                "and are excluded from statistics (flagged, never averaged in)."
            )
    if series_state.get("state") == "insufficient_history":
        gaps.append(
            f"{index.upper()} history spans fewer than 2 years; same-month "
            "baselines cannot be formed yet."
        )
    return gaps

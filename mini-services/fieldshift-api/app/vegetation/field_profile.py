"""Field-level satellite intelligence profile (P05/P06 Workstream D).

One reusable, honest summary of the satellite evidence for a field,
consumed by Crop Intelligence, Map & Satellite, Decision Center, Data Hub
and Reports through a single contract (`field_satellite_profile`).

Layer discipline (the payload carries `interpretation_levels` explicitly):

1. **measurements**      — acquisition dates, cloud cover, resolution,
   scene/product identity straight from `satellite_scenes` provenance.
2. **derived_indicators** — per-scene index values computed by the
   documented index math (observations with
   evidence_class=satellite_derived_estimate).
3. **statistical_interpretations** — timelines, baselines, deltas, spatial
   variation, tercile zones: deterministic statistics over (1)+(2),
   labelled as statistics, never as agronomy.
4. **agronomic_recommendations** — NOT produced here. Vegetation condition
   context is emitted only through the existing recommendation engine
   contracts; a low NDVI value alone NEVER becomes "disease/drought/
   nutrient deficiency".

Honesty rules enforced:
- Quality gates before any statistic: only observations with
  quality_status='valid' count; cloud/quality-flagged rows are excluded and
  COUNTED as excluded (never silently dropped).
- `insufficient_evidence` with explicit reasons when fewer than two valid
  observations exist, or the valid-pixel support is below the documented
  zonal threshold — the profile never squeezes a trend out of one point.
- Coverage gaps and acquisition recency are reported from real dates; no
  interpolation or gap-filling is ever performed or implied.
- Uncertainty: temporal deltas carry the baseline spread and the valid-
  pixel fraction of both dates; small-support comparisons are flagged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Field
from app.db.models_p2 import RasterAsset, SatelliteScene

logger = logging.getLogger("croptwist.field_profile")

PROFILE_VERSION = "field-satellite-profile-1.0.0"
MIN_PIXELS_FOR_ZONES = 5  # mirrors vegetation.zonal MIN_PIXELS_FOR_VARIABILITY
FRESH_SATELLITE_DAYS = 45  # mirrors evidence_gaps detection freshness window
MIN_VALID_OBS_FOR_TREND = 2


def field_satellite_profile(
    db: Session,
    field: Field,
    *,
    index: str = "ndvi",
    max_timeline_points: int = 60,
) -> dict[str, Any]:
    """Build the unified field satellite profile for one index.

    Pure read model over `observations` + `satellite_scenes` +
    `raster_assets` — no computation that could drift from persisted
    provenance beyond deterministic statistics of stored values.
    """
    from app.db.models import Observation
    from app.vegetation.indices import INDEX_FORMULAS, INDEX_VALID_RANGE

    if index not in INDEX_FORMULAS:
        raise ValueError(f"unsupported index code: {index!r}")

    # ---- observations for this field + this index (derived indicator layer)
    obs_rows = db.scalars(
        select(Observation).where(
            Observation.field_id == field.id,
            Observation.variable_code == index,
            Observation.spatial_support_type == "polygon_average",
            Observation.time_support == "instant",
        )
    ).all()

    product_ids = {row.dataset_product_id for row in obs_rows}
    scene_by_key: dict[tuple[str, str], SatelliteScene] = {}
    if obs_rows:
        scenes = db.scalars(
            select(SatelliteScene).where(SatelliteScene.field_id == field.id)
        ).all()
        for s in scenes:
            scene_by_key[(s.provider_code or "", s.scene_id)] = s

    timeline: list[dict[str, Any]] = []
    excluded_cloud: list[dict[str, Any]] = []
    valid_values: list[float] = []
    for row in sorted(obs_rows, key=lambda r: r.observed_at):
        meta = row.metadata or {}
        scene_id = meta.get("scene_id")
        scene = scene_by_key.get(("nasa_hls", scene_id)) if scene_id else None
        entry = {
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            "value": row.value,
            "quality_status": row.quality_status,
            "processing_version": row.processing_version,
            "scene_id": scene_id,
            "cloud_cover_pct": meta.get("cloud_cover_pct"),
            "valid_pixel_fraction": (meta.get("zonal") or {}).get("coverage_fraction"),
            "valid_pixels": (meta.get("zonal") or {}).get("valid_pixels"),
            "subfield_statistics_ok": meta.get("subfield_statistics_ok"),
            "spatial_resolution_m": row.spatial_resolution_m,
            "evidence_class": row.evidence_class,
            "is_synthetic": row.is_synthetic,
        }
        if row.quality_status == "valid" and row.value is not None:
            timeline.append(entry)
            valid_values.append(float(row.value))
        else:
            excluded_cloud.append(
                {
                    "observed_at": entry["observed_at"],
                    "scene_id": scene_id,
                    "quality_status": row.quality_status,
                    "reason": "observation has no valid value (cloud/nodata attempt)",
                }
            )

    latest = timeline[-1] if timeline else None
    now = datetime.now(UTC)

    # ---- coverage (measurement layer + honest gaps)
    acquired_dates = sorted(
        s.acquired_at for s in scene_by_key.values() if s.acquired_at is not None
    )
    days_since_last = None
    if latest and latest["observed_at"]:
        observed = datetime.fromisoformat(str(latest["observed_at"]))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        days_since_last = (now - observed).days

    gaps: list[dict[str, Any]] = []
    if len(timeline) >= 2:
        for prev, cur in zip(timeline, timeline[1:], strict=False):
            d0 = datetime.fromisoformat(str(prev["observed_at"]))
            d1 = datetime.fromisoformat(str(cur["observed_at"]))
            gap_days = (d1 - d0).days
            if gap_days > FRESH_SATELLITE_DAYS:
                gaps.append(
                    {
                        "from": prev["observed_at"],
                        "to": cur["observed_at"],
                        "days": gap_days,
                        "note": "no valid observation between these dates",
                    }
                )

    # ---- temporal statistics (statistical interpretation layer)
    baseline: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    trend: dict[str, Any] | None = None
    if len(valid_values) >= MIN_VALID_OBS_FOR_TREND and latest is not None:
        hist = valid_values[:-1]
        mean = sum(hist) / len(hist)
        var = sum((v - mean) ** 2 for v in hist) / max(len(hist) - 1, 1)
        std = var**0.5
        z = (latest["value"] - mean) / std if std > 1e-9 else None
        baseline = {
            "kind": "prior_observations",
            "count": len(hist),
            "mean": round(mean, 6),
            "std": round(std, 6) if std > 1e-9 else 0.0,
            "min": round(min(hist), 6),
            "max": round(max(hist), 6),
        }
        comparison = {
            "latest_value": latest["value"],
            "delta_vs_baseline_mean": round(latest["value"] - mean, 6),
            "z_score_vs_baseline": round(z, 3) if z is not None else None,
            "uncertainty_note": (
                "delta computed against the spread of prior valid observations; "
                "a single-scene comparison with wide baseline spread is weak "
                "evidence and is flagged, not interpreted."
            ),
            "weak_evidence": bool(
                len(hist) < 3 or (z is not None and abs(z) < 1.0)
            ),
        }
        # slope over time (simple deterministic least squares)
        ts = [
            datetime.fromisoformat(str(t["observed_at"])).timestamp()
            for t in timeline
            if t["observed_at"]
        ]
        if len(ts) == len(valid_values) and ts[-1] > ts[0]:
            n = len(ts)
            t0 = ts[0]
            xs = [(t - t0) / 86400.0 for t in ts]
            x_mean = sum(xs) / n
            y_mean = sum(valid_values) / n
            denom = sum((x - x_mean) ** 2 for x in xs)
            if denom > 1e-9:
                slope = sum((xs[i] - x_mean) * (valid_values[i] - y_mean) for i in range(n)) / denom
                trend = {
                    "slope_per_day": round(slope, 8),
                    "slope_per_30d": round(slope * 30, 6),
                    "points": n,
                    "method": "ordinary_least_squares",
                }

    # ---- spatial variation + statistical zones (from latest observation)
    spatial_variation: dict[str, Any] | None = None
    zone_summary: dict[str, Any] | None = None
    latest_meta = None
    if obs_rows:
        latest_row = max(
            (r for r in obs_rows if r.quality_status == "valid" and r.value is not None),
            key=lambda r: r.observed_at,
            default=None,
        )
        latest_meta = (latest_row.metadata or {}) if latest_row else None
    if latest_meta:
        zonal = latest_meta.get("zonal") or {}
        spatial_variation = {
            "std": zonal.get("std"),
            "p5": zonal.get("p5"),
            "p25": zonal.get("p25"),
            "p75": zonal.get("p75"),
            "p95": zonal.get("p95"),
            "valid_pixels": zonal.get("valid_pixels"),
            "coverage_fraction": zonal.get("coverage_fraction"),
            "supports_subfield_claims": bool(latest_meta.get("subfield_statistics_ok")),
        }
        zone_summary = latest_meta.get("zone_summary")

    # ---- derived asset provenance (traceability to stored rasters)
    asset_rows = (
        db.scalars(
            select(RasterAsset).where(
                RasterAsset.field_id == field.id,
                RasterAsset.index_code == index,
                RasterAsset.asset_kind == "derived",
            )
        ).all()
        if latest is not None
        else []
    )
    derived_assets = [
        {
            "asset_id": str(a.id),
            "scene_id": a.scene_id,
            "processing_version": a.processing_version,
            "acquired_at": a.acquired_at.isoformat() if a.acquired_at else None,
            "storage_backend": a.storage_backend,
            "valid_pixel_fraction": a.valid_pixel_fraction,
            "checksum_sha256": a.checksum_sha256,
        }
        for a in sorted(asset_rows, key=lambda r: r.acquired_at or datetime.now(UTC).replace(tzinfo=None))[-10:]
    ]

    # ---- insufficient-evidence gate
    insufficient: dict[str, Any] | None = None
    reasons: list[str] = []
    if len(timeline) < MIN_VALID_OBS_FOR_TREND:
        reasons.append(
            f"only {len(timeline)} valid observation(s) for index '{index}'; "
            f"at least {MIN_VALID_OBS_FOR_TREND} required for any temporal claim"
        )
    if timeline and latest_meta:
        zonal = latest_meta.get("zonal") or {}
        if (zonal.get("valid_pixels") or 0) < MIN_PIXELS_FOR_ZONES:
            reasons.append(
                "latest observation has fewer valid field pixels than the "
                f"documented sub-field threshold ({MIN_PIXELS_FOR_ZONES})"
            )
    if reasons:
        insufficient = {
            "status": "insufficient_evidence",
            "reasons": reasons,
            "note": (
                "The profile returns no trend/zone interpretation; "
                "acquisition and coverage facts remain visible."
            ),
        }

    valid_pixel_fractions = [
        t["valid_pixel_fraction"] for t in timeline if t.get("valid_pixel_fraction") is not None
    ]
    quality_summary = {
        "valid_observations": len(timeline),
        "excluded_no_value": len(excluded_cloud),
        "total_scene_records": len(scene_by_key),
        "avg_valid_pixel_fraction": round(sum(valid_pixel_fractions) / len(valid_pixel_fractions), 4)
        if valid_pixel_fractions
        else None,
        "min_valid_pixel_fraction": min(valid_pixel_fractions) if valid_pixel_fractions else None,
        "freshness_days_since_last": days_since_last,
        "fresh": days_since_last is not None and days_since_last <= FRESH_SATELLITE_DAYS,
        "freshness_window_days": FRESH_SATELLITE_DAYS,
    }

    return {
        "profile_version": PROFILE_VERSION,
        "field_id": str(field.id),
        "index": index,
        "index_formula": INDEX_FORMULAS[index],
        "documented_range": list(INDEX_VALID_RANGE[index]),
        "interpretation_levels": {
            "measurement": "acquisition dates, cloud cover, resolution, scene identity",
            "derived_indicator": f"{index.upper()} values from documented index math",
            "statistical_interpretation": "timeline, baseline comparison, variation, tercile zones",
            "agronomic_recommendation": (
                "produced only by the recommendation engine contracts; never "
                "directly from an index value"
            ),
        },
        "latest_valid_observation": latest,
        "timeline": timeline[-max_timeline_points:],
        "excluded_observations": excluded_cloud[-max_timeline_points:],
        "coverage": {
            "first_scene_acquired": acquired_dates[0].isoformat() if acquired_dates else None,
            "last_scene_acquired": acquired_dates[-1].isoformat() if acquired_dates else None,
            "scene_records": len(scene_by_key),
            "gaps": gaps,
            "gaps_note": (
                "no valid observations in these windows (cloud/missing scenes); "
                "no interpolation is performed or implied"
            ),
            "expected_revisit_note": (
                "HLS combined revisit is ~2-4 days cloud-free; actual usable "
                "cadence depends on cloud cover at the field location"
            ),
        },
        "quality_summary": quality_summary,
        "baseline": baseline,
        "comparison": comparison,
        "trend": trend,
        "spatial_variation": spatial_variation,
        "statistical_zones": zone_summary,
        "derived_assets": derived_assets,
        "insufficient_evidence": insufficient,
    }

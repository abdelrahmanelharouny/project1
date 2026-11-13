"""Quality-aware spatial analytics + anomaly detection (P07 B1-B4).

Deterministic, threshold-gated read models over data that actually exists
(observations + raster_assets). Nothing here diagnoses: anomalies are
*signals* with explicit minimum-sample requirements, coverage and baseline
gates, confidence computed from evidence-quality components, and machine-
readable reasons. Every payload carries ``not_a_diagnosis`` and the list of
claims that would require independent evidence (disease, pests, nutrient
deficiency, irrigation failure).

Contracts:
- ``field_spatial_analytics``  — variation, distribution, zones, zone history,
  coverage for one index (map + analytics UI).
- ``detect_spatial_anomalies`` — gated anomaly signals with confidence.
- ``spatial_comparison``       — two products (fields/periods) with explicit
  temporal/resolution compatibility checks; incompatible comparisons are
  labeled, never silently equated.
- ``farm_satellite_overview``  — per-field latest NDVI state for farm-level
  analytics and cross-filtering.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("croptwist.geospatial.spatial_analytics")

SPATIAL_ANALYTICS_VERSION = "spatial-analytics-1.0.0"

# Explicit minimum requirements (false-positive safeguards). An anomaly is
# emitted ONLY when every gate passes; failed gates are reported instead.
MIN_BASELINE_OBS = 3
MIN_VALID_PIXELS = 5
MIN_COVERAGE = 0.4
MIN_ZONE_PIXELS = 30
FRESH_DAYS = 45
DECLINE_Z_THRESHOLD = -1.5
# Uniform-baseline safeguard: with a zero-variance baseline the z-score is
# undefined (std -> 0). A LARGE absolute drop in documented units is still
# reportable through this stricter absolute gate instead of being silently
# unreportable forever.
UNIFORM_BASELINE_DELTA = -0.15
ZONE_GAP_STD_MULT = 1.0
HIGH_VARIATION_SPREAD = 0.2  # documented index units
MAX_TEMPORAL_DISTANCE_DAYS = 16  # HLS revisit cadence for compatible scenes
CONFIDENCE_FLOOR = 0.3
CONFIDENCE_CEIL = 0.95


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _latest_derived(db: Session, field_id: Any, index_code: str) -> Any:
    from app.db.models_p2 import RasterAsset

    return db.scalar(
        select(RasterAsset)
        .where(
            RasterAsset.field_id == field_id,
            RasterAsset.asset_kind == "derived",
            RasterAsset.index_code == index_code,
        )
        .order_by(RasterAsset.acquired_at.desc(), RasterAsset.created_at.desc())
        .limit(1)
    )


def _derived_history(db: Session, field_id: Any, index_code: str, cap: int = 24) -> list[Any]:
    from app.db.models_p2 import RasterAsset

    return list(
        db.scalars(
            select(RasterAsset)
            .where(
                RasterAsset.field_id == field_id,
                RasterAsset.asset_kind == "derived",
                RasterAsset.index_code == index_code,
            )
            .order_by(RasterAsset.acquired_at.desc())
            .limit(cap)
        ).all()
    )


def _product_meta(asset: Any) -> dict[str, Any]:
    stats = asset.stats_json or {}
    return {
        "asset_id": str(asset.id),
        "scene_id": asset.scene_id,
        "acquired_at": asset.acquired_at.isoformat() if asset.acquired_at else None,
        "processing_version": asset.processing_version,
        "spatial_resolution_m": asset.spatial_resolution_m,
        "crs": asset.crs,
        "valid_pixel_fraction": asset.valid_pixel_fraction,
        "zonal": stats.get("zonal"),
        "zone_summary": stats.get("zone_summary"),
    }


# --------------------------------------------------------------- analytics
def field_spatial_analytics(
    db: Session,
    field: Any,
    *,
    index_code: str = "ndvi",
    geometry_geojson: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Spatial variation / distribution / zones for one index.

    Combines the persisted processing-time zonal statistics (never
    recomputed silently — recomputation would break provenance) with
    on-demand zone polygons and a field-masked histogram rendered from the
    stored COG. Zone polygons require the stored raster to still be
    readable; a missing object is reported, not synthesized.
    """
    from app.geospatial.rendering import value_distribution, zone_polygons_fc
    from app.vegetation.indices import INDEX_FORMULAS

    latest = _latest_derived(db, field.id, index_code)
    result: dict[str, Any] = {
        "version": SPATIAL_ANALYTICS_VERSION,
        "field_id": str(field.id),
        "index": index_code,
        "index_formula": INDEX_FORMULAS.get(index_code),
        "available": latest is not None,
        "not_zones_note": (
            "Tercile zones are statistical strata of valid pixels — NOT "
            "validated agronomic management zones."
        ),
    }
    if latest is None:
        result["unavailable_reason"] = (
            f"no derived {index_code} product processed for this field"
        )
        return result

    meta = _product_meta(latest)
    result["latest_product"] = meta
    zonal = meta["zonal"] or {}
    result["variation"] = {
        "std": zonal.get("std"),
        "p5": zonal.get("p5"),
        "p25": zonal.get("p25"),
        "p75": zonal.get("p75"),
        "p95": zonal.get("p95"),
        "spread_p95_p5": (
            round(zonal["p95"] - zonal["p5"], 6)
            if zonal.get("p95") is not None and zonal.get("p5") is not None
            else None
        ),
        "valid_pixels": zonal.get("valid_pixels"),
        "coverage_fraction": zonal.get("coverage_fraction"),
        "supports_subfield_claims": (zonal.get("valid_pixels") or 0) >= MIN_ZONE_PIXELS,
        "flags": zonal.get("flags"),
    }

    # zone polygons (on demand, cached by the rendering layer)
    if geometry_geojson is not None:
        try:
            from app.geospatial.objectstore import get_raster_storage

            result["zone_polygons"] = zone_polygons_fc(
                asset=latest,
                storage=get_raster_storage(),
                geometry_geojson=geometry_geojson,
                index_code=index_code,
            )
        except Exception as exc:  # noqa: BLE001 — honesty over availability
            logger.warning("zone polygons unavailable for asset %s: %s", latest.id, exc)
            result["zone_polygons"] = {
                "available": False,
                "reason": f"stored raster could not be vectorized ({type(exc).__name__})",
            }

        # histogram (field-masked, documented range)
        try:
            result["distribution"] = value_distribution(
                asset=latest,
                storage=get_raster_storage(),
                geometry_geojson=geometry_geojson,
                index_code=index_code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("distribution unavailable for asset %s: %s", latest.id, exc)
            result["distribution"] = {
                "available": False,
                "reason": f"stored raster could not be read ({type(exc).__name__})",
            }

    # zone-level history from persisted processing outputs (never refetched)
    history: list[dict[str, Any]] = []
    for asset in _derived_history(db, field.id, index_code):
        zs = (asset.stats_json or {}).get("zone_summary") or {}
        zones = zs.get("zones") or []
        if not zones:
            continue
        history.append(
            {
                "acquired_at": asset.acquired_at.isoformat() if asset.acquired_at else None,
                "scene_id": asset.scene_id,
                "processing_version": asset.processing_version,
                "valid_pixel_fraction": asset.valid_pixel_fraction,
                "zones": [
                    {
                        "zone": z.get("zone"),
                        "mean": z.get("mean"),
                        "pixel_share": z.get("pixel_share"),
                        "value_range": z.get("value_range"),
                    }
                    for z in zones
                ],
            }
        )
    result["zone_history"] = history
    return result


# ---------------------------------------------------------------- anomalies
def _confidence(
    *,
    baseline_count: int | None,
    fresh: bool,
    coverage: float | None,
    resolution_m: float | None,
    cloud_ok: bool,
) -> float:
    """Deterministic confidence from evidence-quality components.

    Mirrors app/recommendations/evidence_quality.py component semantics:
    completeness, recency, coverage, spatial resolution. Never inflates:
    each missing component pulls the score down; any failed hard gate means
    the anomaly is not emitted at all.
    """
    components: list[float] = []
    if baseline_count is not None:
        components.append(min(1.0, baseline_count / 8.0))
    if fresh:
        components.append(1.0)
    if coverage is not None:
        components.append(min(1.0, max(0.0, (coverage - 0.4) / 0.6)))
    if resolution_m is not None:
        components.append(1.0 if resolution_m <= 30 else 0.5)
    if not cloud_ok:
        components.append(0.5)
    if not components:
        return CONFIDENCE_FLOOR
    score = sum(components) / len(components)
    return round(CONFIDENCE_FLOOR + (CONFIDENCE_CEIL - CONFIDENCE_FLOOR) * score, 3)


def _anomaly_id(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return digest[:12]


def detect_spatial_anomalies(db: Session, field: Any, *, index_code: str = "ndvi") -> dict[str, Any]:
    """Gated anomaly signals for one field/index (NOT diagnoses).

    Gates (all must pass for any anomaly):
      - baseline >= MIN_BASELINE_OBS valid observations
      - latest observation fresh (<= FRESH_DAYS days)
      - valid pixels >= MIN_VALID_PIXELS, coverage >= MIN_COVERAGE
    Signals:
      - vegetation_decline_vs_baseline: z-score <= DECLINE_Z_THRESHOLD
      - spatially_concentrated_low_vegetation: lowest tercile mean far
        below the field mean with enough pixels for sub-field claims
      - high_spatial_variation: p95-p5 spread above threshold
    Environmental context (precipitation/soil moisture) is attached as
    context only — it never upgrades a signal into a cause.
    """
    from app.vegetation.field_profile import field_satellite_profile

    profile = field_satellite_profile(db, field, index=index_code)
    latest = profile.get("latest_valid_observation")
    insufficient: list[str] = []
    anomalies: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "version": SPATIAL_ANALYTICS_VERSION,
        "field_id": str(field.id),
        "index": index_code,
        "anomalies": anomalies,
        "not_a_diagnosis": True,
        "requires_independent_evidence_for": [
            "disease",
            "pests",
            "nutrient_deficiency",
            "irrigation_failure",
        ],
        "generated_from": "observations + raster_assets (no external calls)",
    }

    baseline = profile.get("baseline") or {}
    quality = profile.get("quality_summary") or {}
    spatial = profile.get("spatial_variation") or {}
    coverage = latest.get("valid_pixel_fraction") if latest else None

    if latest is None:
        insufficient.append("no valid satellite observation for this field")
    if (baseline.get("count") or 0) < MIN_BASELINE_OBS:
        insufficient.append(
            f"baseline requires >= {MIN_BASELINE_OBS} valid observations (have "
            f"{baseline.get('count') or 0})"
        )
    if not quality.get("fresh", False):
        insufficient.append(
            f"latest observation older than the {FRESH_DAYS}-day freshness window"
        )
    if latest and (latest.get("valid_pixels") or 0) < MIN_VALID_PIXELS:
        insufficient.append(
            f"latest observation has < {MIN_VALID_PIXELS} valid field pixels"
        )
    if coverage is not None and coverage < MIN_COVERAGE:
        insufficient.append(
            f"latest valid-pixel coverage {coverage} below the {MIN_COVERAGE} gate"
        )
    result["insufficient_evidence"] = insufficient

    if insufficient:
        return result

    z_score = (profile.get("comparison") or {}).get("z_score_vs_baseline")
    zonal_mean = latest.get("value")
    resolution_m = latest.get("spatial_resolution_m")
    cloud_pct = latest.get("cloud_cover_pct")
    cloud_ok = cloud_pct is None or cloud_pct <= 40.0
    acquired_at = latest.get("observed_at")
    scene_id = latest.get("scene_id")
    proc_version = latest.get("processing_version")

    def _base(kind: str, severity: str, reasons: list[str]) -> dict[str, Any]:
        return {
            "id": _anomaly_id(field.id, index_code, kind, acquired_at, proc_version),
            "type": kind,
            "severity": severity,
            "index": index_code,
            "confidence": _confidence(
                baseline_count=baseline.get("count"),
                fresh=bool(quality.get("fresh")),
                coverage=coverage,
                resolution_m=resolution_m,
                cloud_ok=cloud_ok,
            ),
            "reasons": reasons,
            "observed_at": acquired_at,
            "scene_id": scene_id,
            "processing_version": proc_version,
            "spatial_resolution_m": resolution_m,
            "valid_pixel_fraction": coverage,
            "limitations": [],
            "not_a_diagnosis": True,
        }

    # 1) decline vs baseline
    delta = (profile.get("comparison") or {}).get("delta_vs_baseline_mean")
    baseline_std = baseline.get("std")
    decline_reasons: list[str] | None = None
    if z_score is not None and z_score <= DECLINE_Z_THRESHOLD:
        decline_reasons = [
            f"latest {index_code.upper()} {zonal_mean} is {delta} below the "
            f"baseline mean of the last {baseline.get('count')} valid observations",
            f"z-score {z_score} <= {DECLINE_Z_THRESHOLD} gate",
        ]
    elif (
        baseline_std is not None
        and baseline_std <= 1e-9
        and delta is not None
        and delta <= UNIFORM_BASELINE_DELTA
    ):
        # zero-variance baseline: z is undefined, so the stricter absolute
        # drop gate applies (documented index units)
        decline_reasons = [
            f"latest {index_code.upper()} {zonal_mean} is {delta} below the "
            f"baseline mean of the last {baseline.get('count')} valid observations",
            f"baseline has zero spread (uniform), so the absolute-drop gate "
            f"({UNIFORM_BASELINE_DELTA}) applies instead of a z-score",
        ]
    if decline_reasons is not None:
        anomaly = _base(
            "vegetation_decline_vs_baseline",
            "warning",
            decline_reasons,
        )
        anomaly["measurements"] = {
            "latest_value": zonal_mean,
            "baseline_mean": baseline.get("mean"),
            "baseline_std": baseline_std,
            "z_score_vs_baseline": z_score,
            "delta_vs_baseline_mean": delta,
        }
        anomaly["limitations"].append(
            "spectral decline is consistent with several possible causes; "
            "cloud contamination is only partially excluded"
            if not cloud_ok
            else "spectral decline alone cannot identify a cause"
        )
        anomalies.append(anomaly)

    # 2) spatially concentrated low vegetation (zone divergence)
    zones = (profile.get("statistical_zones") or {}).get("zones") or []
    zonal_std = spatial.get("std")
    if zones and zonal_std is not None and (latest.get("valid_pixels") or 0) >= MIN_ZONE_PIXELS:
        lowest = next((z for z in zones if z.get("zone") == "lowest_tercile"), None)
        highest = next((z for z in zones if z.get("zone") == "highest_tercile"), None)
        if lowest and highest and lowest.get("mean") is not None and highest.get("mean") is not None:
            gap = highest["mean"] - lowest["mean"]
            if gap >= max(ZONE_GAP_STD_MULT * zonal_std, 0.05):
                anomaly = _base(
                    "spatially_concentrated_low_vegetation",
                    "warning",
                    [
                        f"lowest tercile mean {lowest['mean']} vs highest tercile "
                        f"mean {highest['mean']} (gap {round(gap, 4)} >= "
                        f"{ZONE_GAP_STD_MULT}x field std {zonal_std})",
                        f"statistical zones from {latest.get('valid_pixels')} valid pixels",
                    ],
                )
                anomaly["measurements"] = {
                    "lowest_tercile_mean": lowest["mean"],
                    "highest_tercile_mean": highest["mean"],
                    "zone_gap": round(gap, 6),
                    "field_std": zonal_std,
                }
                anomaly["limitations"].append(
                    "statistical terciles are not agronomic zones; the low stratum "
                    "is a data-description aid, not a mapped problem area"
                )
                anomalies.append(anomaly)

    # 3) high spatial variation
    spread = spatial.get("p95") and spatial.get("p5")
    if spread and (latest.get("valid_pixels") or 0) >= MIN_ZONE_PIXELS:
        gap = round(spatial["p95"] - spatial["p5"], 6)
        if gap >= HIGH_VARIATION_SPREAD:
            anomaly = _base(
                "high_spatial_variation",
                "info",
                [
                    f"p95-p5 spread {gap} >= {HIGH_VARIATION_SPREAD} documented units",
                    f"computed over {latest.get('valid_pixels')} valid pixels",
                ],
            )
            anomaly["measurements"] = {
                "p5": spatial.get("p5"),
                "p95": spatial.get("p95"),
                "spread": gap,
                "std": zonal_std,
            }
            anomalies.append(anomaly)

    # environmental context (never a cause — labeled context)
    result["environmental_context"] = _environmental_context(db, field)

    return result


def _environmental_context(db: Session, field: Any) -> dict[str, Any]:
    """Real environmental observations as *context* for anomaly payloads."""
    from app.db.models import Observation

    now = _utcnow()
    context: dict[str, Any] = {"note": "context only — not interpreted as a cause"}
    precip_30d = db.scalars(
        select(Observation.value)
        .where(
            Observation.field_id == field.id,
            Observation.variable_code == "precipitation",
            Observation.observed_at >= now - timedelta(days=30),
            Observation.value.is_not(None),
        )
        .order_by(Observation.observed_at.desc())
        .limit(200)
    ).all()
    if precip_30d:
        context["precipitation_last_30d_sum_mm"] = round(sum(float(v) for v in precip_30d), 2)
        context["precipitation_last_30d_days_with_data"] = len(precip_30d)
    soil = db.scalar(
        select(Observation)
        .where(
            Observation.field_id == field.id,
            Observation.variable_code == "soil_moisture_surface",
            Observation.value.is_not(None),
        )
        .order_by(Observation.observed_at.desc())
        .limit(1)
    )
    if soil is not None and soil.value is not None:
        context["soil_moisture_surface_latest"] = {
            "value": float(soil.value),
            "unit": soil.unit,
            "observed_at": soil.observed_at.isoformat() if soil.observed_at else None,
        }
    return context


# ---------------------------------------------------------------- comparison
def spatial_comparison(
    db: Session,
    *,
    field_a: Any,
    index_code: str = "ndvi",
    field_b: Any | None = None,
    acquired_at_a: str | None = None,
    acquired_at_b: str | None = None,
) -> dict[str, Any]:
    """Compare two index products with explicit compatibility checks.

    Defaults: latest product of field_a vs latest product of the same field
    (period comparison) or of field_b (field/zone comparison). Observations
    whose acquisition times differ by more than MAX_TEMPORAL_DISTANCE_DAYS
    or whose spatial resolution differs are still returned — but flagged
    ``comparable: false`` with the concrete incompatibility, never silently
    equated.
    """
    from app.db.models_p2 import RasterAsset

    def _resolve(field: Any, when: str | None) -> Any:
        stmt = (
            select(RasterAsset)
            .where(
                RasterAsset.field_id == field.id,
                RasterAsset.asset_kind == "derived",
                RasterAsset.index_code == index_code,
            )
            .order_by(RasterAsset.acquired_at.desc())
            .limit(1)
        )
        if when:
            try:
                target = datetime.fromisoformat(when)
            except ValueError as exc:
                raise ValueError(f"invalid acquisition timestamp: {when}") from exc
            stmt = (
                select(RasterAsset)
                .where(
                    RasterAsset.field_id == field.id,
                    RasterAsset.asset_kind == "derived",
                    RasterAsset.index_code == index_code,
                    RasterAsset.acquired_at == target,
                )
                .limit(1)
            )
        return db.scalar(stmt)

    asset_a = _resolve(field_a, acquired_at_a)
    asset_b = _resolve(field_b or field_a, acquired_at_b)
    result: dict[str, Any] = {
        "version": SPATIAL_ANALYTICS_VERSION,
        "index": index_code,
        "comparable": False,
        "incompatibilities": [],
    }
    if asset_a is None or asset_b is None:
        result["unavailable_reason"] = (
            "one or both sides have no processed product for this index"
        )
        if asset_a is None:
            result["side_a"] = None
        if asset_b is None:
            result["side_b"] = None
        return result

    side_a, side_b = _product_meta(asset_a), _product_meta(asset_b)
    result.update({"side_a": side_a, "side_b": side_b})

    zonal_a = side_a["zonal"] or {}
    zonal_b = side_b["zonal"] or {}
    mean_a, mean_b = zonal_a.get("mean"), zonal_b.get("mean")

    incompat: list[str] = []
    res_a = side_a.get("spatial_resolution_m")
    res_b = side_b.get("spatial_resolution_m")
    if res_a and res_b and abs(res_a - res_b) > 1e-6:
        incompat.append(
            f"spatial resolution differs ({res_a} m vs {res_b} m)"
        )
    distance_days: int | None = None
    try:
        ta = datetime.fromisoformat(side_a["acquired_at"]) if side_a["acquired_at"] else None
        tb = datetime.fromisoformat(side_b["acquired_at"]) if side_b["acquired_at"] else None
        if ta and tb:
            distance_days = abs((ta - tb).days)
            if distance_days > MAX_TEMPORAL_DISTANCE_DAYS:
                incompat.append(
                    f"acquisition dates differ by {distance_days} days "
                    f"(> {MAX_TEMPORAL_DISTANCE_DAYS}-day compatibility window)"
                )
    except ValueError:  # pragma: no cover — stored ISO timestamps
        pass
    coverage = [s.get("valid_pixel_fraction") for s in (side_a, side_b) if s.get("valid_pixel_fraction") is not None]
    if coverage and min(coverage) < MIN_COVERAGE:
        incompat.append(
            f"one side has valid-pixel coverage below {MIN_COVERAGE} "
            f"(min {min(coverage)})"
        )

    result["comparable"] = not incompat
    result["incompatibilities"] = incompat
    result["compatibility"] = {
        "spatial_resolution_delta_m": (
            round(abs(res_a - res_b), 3) if res_a and res_b else None
        ),
        "temporal_distance_days": distance_days,
        "min_valid_pixel_fraction": min(coverage) if coverage else None,
        "same_field": field_b is None or field_b.id == field_a.id,
    }
    if mean_a is not None and mean_b is not None:
        result["mean_delta"] = round(mean_a - mean_b, 6)
        result["mean_delta_pct"] = (
            round((mean_a - mean_b) / abs(mean_b), 6) if mean_b else None
        )
    zone_a = (side_a.get("zone_summary") or {}).get("zones") or []
    zone_b = (side_b.get("zone_summary") or {}).get("zones") or []
    if zone_a and zone_b:
        by_name_b = {z.get("zone"): z for z in zone_b}
        result["zone_deltas"] = [
            {
                "zone": z.get("zone"),
                "mean_a": z.get("mean"),
                "mean_b": by_name_b.get(z.get("zone"), {}).get("mean"),
                "delta": (
                    round(z["mean"] - by_name_b[z["zone"]]["mean"], 6)
                    if z.get("mean") is not None
                    and by_name_b.get(z.get("zone"), {}).get("mean") is not None
                    else None
                ),
            }
            for z in zone_a
            if z.get("zone") in by_name_b
        ]
    result["measurement_notes"] = [
        "zonal means are pixel-based over equal-area projected pixels "
        "(each valid pixel contributes equally)",
        "sides come from independently processed scenes; processing versions "
        "are reported per side and are NOT reconciled",
    ]
    return result


# ------------------------------------------------------------- farm overview
def farm_satellite_overview(db: Session, farm: Any, *, index_code: str = "ndvi") -> dict[str, Any]:
    """Per-field latest index state for farm-level analytics (bounded)."""
    from app.db.models import Field
    from app.vegetation.field_profile import FRESH_SATELLITE_DAYS

    fields = list(
        db.scalars(
            select(Field).where(Field.farm_id == farm.id).order_by(Field.name).limit(200)
        ).all()
    )
    now = _utcnow()
    rows: list[dict[str, Any]] = []
    for f in fields:
        latest = _latest_derived(db, f.id, index_code)
        entry: dict[str, Any] = {
            "field_id": str(f.id),
            "field_name": f.name,
            "area_ha": f.area_ha,
            "available": latest is not None,
        }
        if latest is not None:
            zonal = (latest.stats_json or {}).get("zonal") or {}
            entry.update(
                {
                    "acquired_at": latest.acquired_at.isoformat() if latest.acquired_at else None,
                    "mean": zonal.get("mean"),
                    "valid_pixel_fraction": latest.valid_pixel_fraction,
                    "processing_version": latest.processing_version,
                    "freshness_days": (
                        (now - latest.acquired_at).days
                        if latest.acquired_at
                        else None
                    ),
                    "fresh": bool(
                        latest.acquired_at
                        and (now - latest.acquired_at).days <= FRESH_SATELLITE_DAYS
                    ),
                }
            )
        else:
            entry["unavailable_reason"] = f"no processed {index_code} product"
        rows.append(entry)
    return {
        "version": SPATIAL_ANALYTICS_VERSION,
        "farm_id": str(farm.id),
        "index": index_code,
        "fields": rows,
        "freshness_window_days": FRESH_SATELLITE_DAYS,
    }

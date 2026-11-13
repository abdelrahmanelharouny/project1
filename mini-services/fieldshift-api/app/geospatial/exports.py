"""Authorized geospatial exports (P07 D3): GeoJSON boundaries + CSV timeline.

Rules:
- Every export is tenant-gated by the API layer (membership required); these
  builders never bypass the principal checks.
- GeoJSON carries CRS metadata (EPSG:4326 WGS84 — the registered boundary
  CRS) and boundary version so consumers can trace the geometry.
- The CSV timeline exports persisted satellite-derived observations with
  their provenance columns (scene, processing version, cloud, valid-pixel
  fraction, quality status) — bounded queries only (hard row cap + optional
  date window), never an unbounded scan.
- Missing values stay missing (empty CSV cells) — never zero-filled.
"""

from __future__ import annotations

import csv
import io
import json as _json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

logger = logging.getLogger("croptwist.geospatial.exports")

EXPORTS_VERSION = "geo-exports-1.0.0"
TIMELINE_ROW_CAP = 2000
TIMELINE_MAX_SPAN_DAYS = 365 * 3

TIMELINE_COLUMNS = [
    "observed_at",
    "index",
    "value",
    "unit",
    "quality_status",
    "evidence_class",
    "is_synthetic",
    "cloud_cover_pct",
    "valid_pixel_fraction",
    "valid_pixels",
    "spatial_resolution_m",
    "processing_version",
    "scene_id",
    "crs_of_product_window",
]


# ------------------------------------------------------------- GeoJSON
def field_boundary_feature(db: Session, field: Any, farm: Any) -> dict[str, Any]:
    """GeoJSON Feature for one field boundary (EPSG:4326)."""
    geometry = _boundary_geojson(db, field.id)
    if geometry is None:
        raise ValueError("field boundary is not registered")
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "field_id": str(field.id),
            "name": field.name,
            "farm_id": str(field.farm_id),
            "farm_name": farm.name if farm else None,
            "area_ha": float(field.area_ha) if field.area_ha else None,
            "area_method": "registered_geometry",
            "boundary_version": field.boundary_version,
            "status": field.status,
            "crs": "EPSG:4326",
            "export_version": EXPORTS_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
        },
    }


def farm_fields_feature_collection(db: Session, farm: Any) -> dict[str, Any]:
    """GeoJSON FeatureCollection of all registered fields of one farm."""
    rows = db.execute(
        text(
            "SELECT ST_AsGeoJSON(boundary) AS g, id, name, area_ha, "
            "boundary_version, status FROM fields WHERE farm_id = :fid "
            "ORDER BY name"
        ).bindparams(fid=str(farm.id))
    ).all()
    features = []
    for geojson_text, field_id, name, area_ha, boundary_version, status in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": _json.loads(geojson_text) if geojson_text else None,
                "properties": {
                    "field_id": str(field_id),
                    "name": name,
                    "area_ha": float(area_ha) if area_ha else None,
                    "area_method": "registered_geometry",
                    "boundary_version": boundary_version,
                    "status": status,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "farm_id": str(farm.id),
        "farm_name": farm.name,
        "crs": "EPSG:4326",
        "export_version": EXPORTS_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "field_count": len(features),
    }


# ---------------------------------------------------------------- timeline
def satellite_timeline_rows(
    db: Session,
    field: Any,
    *,
    index_codes: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[list[str]]:
    """Bounded satellite observation rows with provenance (shared by CSV)."""
    from app.db.models import Observation

    now = datetime.now(UTC)
    end = date_to or now
    start = date_from or (end - timedelta(days=365))
    if (end - start) > timedelta(days=TIMELINE_MAX_SPAN_DAYS):
        start = end - timedelta(days=TIMELINE_MAX_SPAN_DAYS)

    stmt = (
        select(Observation)
        .where(Observation.field_id == field.id)
        .where(
            Observation.variable_code.in_(
                index_codes or ["ndvi", "evi", "ndmi", "ndwi", "bsi", "savi"]
            )
        )
        .where(Observation.observed_at >= start, Observation.observed_at <= end)
        .order_by(Observation.observed_at.desc())
        .limit(TIMELINE_ROW_CAP)
    )
    rows = db.scalars(stmt).all()
    out: list[list[str]] = []
    for obs in rows:
        meta = obs.metadata or {}
        zonal = meta.get("zonal") or {}
        fraction = meta.get("valid_pixel_fraction")
        if fraction is None:
            fraction = zonal.get("coverage_fraction")
        window_crs = ((meta.get("pipeline") or {}).get("crs")) or None
        out.append(
            [
                obs.observed_at.isoformat() if obs.observed_at else "",
                obs.variable_code,
                "" if obs.value is None else f"{float(obs.value):.6f}",
                obs.unit or "",
                obs.quality_status or "",
                obs.evidence_class or "",
                "1" if obs.is_synthetic else "0",
                "" if meta.get("cloud_cover_pct") is None else str(meta["cloud_cover_pct"]),
                "" if fraction is None else f"{float(fraction):.6f}",
                "" if zonal.get("valid_pixels") is None else str(zonal["valid_pixels"]),
                "" if obs.spatial_resolution_m is None else str(obs.spatial_resolution_m),
                obs.processing_version or "",
                str(meta.get("scene_id", "") or ""),
                window_crs or "",
            ]
        )
    return out


def satellite_timeline_csv(
    db: Session,
    field: Any,
    *,
    index_codes: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> bytes:
    """UTF-8 CSV (BOM for Excel/Arabic compatibility) of the timeline rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TIMELINE_COLUMNS)
    for row in satellite_timeline_rows(
        db, field, index_codes=index_codes, date_from=date_from, date_to=date_to
    ):
        writer.writerow(row)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------- helpers
def _boundary_geojson(db: Session, field_id: Any) -> dict[str, Any] | None:
    row = db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar()
    return _json.loads(row) if row else None

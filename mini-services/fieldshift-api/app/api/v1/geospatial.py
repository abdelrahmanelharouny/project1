"""Geospatial preprocessing + field-level satellite intelligence (P05/P06)
and the advanced map experience (P07).

Endpoints (all tenant-scoped through get_field_for_principal):

P05/P06:
- POST /fields/{field_id}/satellite/processing        — enqueue per-scene
  preprocessing jobs (operator role; 202; never processes in-request).
- GET  /fields/{field_id}/satellite/processing        — per-scene processing
  state + derived products + provenance (membership).
- POST /fields/{field_id}/satellite/processing/{job_id}/cancel — cancel a
  still-queued preprocessing job (operator role).
- GET  /fields/{field_id}/satellite/profile            — unified field
  satellite profile for one index (membership).
- GET  /fields/{field_id}/satellite/assets/{asset_id}/content — controlled
  read of a stored raster asset (local backend streams bytes; S3 backend
  302s to a short-lived presigned URL). Access is field-membership gated
  and never exposes object-store credentials.
- GET  /fields/{field_id}/satellite/processing-jobs    — recent job rows.

P07 (advanced map + spatial analytics + exports):
- GET  /fields/{field_id}/map/layers                  — unified honest layer
  catalog (vegetation products, environmental series, infrastructure).
- GET  /fields/{field_id}/satellite/products/{asset_id}/tiles/{z}/{x}/{y}.png
  — XYZ web-mercator tile rendered server-side from the stored COG
  (documented-range colormap, transparent nodata, bounded LRU cache,
  membership gated, no storage URLs leaked).
- GET  /fields/{field_id}/satellite/products/{asset_id}/zones — statistical
  tercile zone polygons (GeoJSON, explicitly non-agronomic).
- GET  /fields/{field_id}/satellite/products/{asset_id}/distribution —
  field-masked histogram over the documented range.
- GET  /fields/{field_id}/satellite/spatial-analytics — variation,
  distribution, zones, zone history for one index.
- GET  /fields/{field_id}/satellite/anomalies         — quality-gated anomaly
  signals (NOT diagnoses) with confidence + reasons.
- GET  /fields/{field_id}/satellite/comparison        — two-product
  comparison with explicit temporal/resolution compatibility.
- GET  /farms/{farm_id}/satellite/overview            — per-field latest
  index state (farm membership).
- GET  /fields/{field_id}/boundary.geojson            — authorized GeoJSON
  boundary export.
- GET  /farms/{farm_id}/fields.geojson                — authorized farm
  fields FeatureCollection export.
- GET  /fields/{field_id}/satellite/timeline.csv      — provenance-complete
  CSV export of persisted satellite observations (bounded).

No endpoint performs raster work in-request beyond small windowed tile
renders from already-processed products; no endpoint fabricates data.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.db.models_p2 import RasterAsset, RasterProcessingJob, SatelliteScene
from app.data_platform.processing import service as processing
from app.domains.identity.service import (
    get_field_for_principal,
    get_farm_for_principal,
    get_principal,
)

router = APIRouter(tags=["geospatial"])


def _require_field_role(
    db: Session, principal: Any, field_id: uuid.UUID, minimum: str
) -> dbm.Field:
    field = get_field_for_principal(db, principal, field_id)
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:
        raise NotFound("Field has no farm.")
    principal.require_org_role(farm.organization_id, minimum)
    return field


class ProcessingRequest(BaseModel):
    scene_ids: list[str] = Field(min_length=1, max_length=30)
    indices: list[str] = Field(min_length=1, max_length=10)
    processing_version: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------- enqueue
@router.post("/fields/{field_id}/satellite/processing", status_code=202)
def create_satellite_processing(
    field_id: uuid.UUID,
    payload: ProcessingRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Enqueue preprocessing jobs for cataloged, ready scenes (operator).

    Returns 202 with per-scene job descriptors; raster work happens only in
    workers (API or standalone `python -m app.worker`).
    """
    field = _require_field_role(db, principal, field_id, "operator")
    try:
        return processing.create_processing_jobs(
            db,
            field=field,
            scene_ids=payload.scene_ids,
            indices=payload.indices,
            processing_version=payload.processing_version or processing.PROCESSING_VERSION,
            created_by=principal.id,
        )
    except processing.ProcessingRequestError as exc:
        raise ValidationFailed(str(exc)) from exc


# ---------------------------------------------------------------- inspect
@router.get("/fields/{field_id}/satellite/processing")
def list_satellite_processing(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    return processing.list_field_products(db, field_id=field_id)


# ---------------------------------------------------------------- profile
@router.get("/fields/{field_id}/satellite/profile")
def get_satellite_profile(
    field_id: uuid.UUID,
    index: str = Query(default="ndvi", max_length=32),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.vegetation.field_profile import field_satellite_profile

    field = get_field_for_principal(db, principal, field_id)
    try:
        return field_satellite_profile(db, field, index=index.lower())
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


# ---------------------------------------------------------------- cancel
@router.post("/fields/{field_id}/satellite/processing/{job_id}/cancel")
def cancel_satellite_processing(
    field_id: uuid.UUID,
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel a still-queued preprocessing job (operator role)."""
    _require_field_role(db, principal, field_id, "operator")
    rp = db.get(RasterProcessingJob, job_id)
    if rp is None or rp.field_id != field_id:
        raise NotFound("Processing job not found for this field.")
    if rp.background_job_id is None:
        raise ValidationFailed("processing job has no background job reference")
    bg = db.get(dbm.BackgroundJob, rp.background_job_id)
    if bg is None:
        raise NotFound("Background job row missing.")
    try:
        return processing.cancel_processing_job(db, job=bg)
    except processing.ProcessingRequestError as exc:
        raise ValidationFailed(str(exc)) from exc


# ------------------------------------------------------------------ assets
@router.get("/fields/{field_id}/satellite/assets/{asset_id}/content")
def get_satellite_asset_content(
    field_id: uuid.UUID,
    asset_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Any:
    """Controlled read of a stored raster asset (field-membership gated)."""
    get_field_for_principal(db, principal, field_id)
    asset = db.get(RasterAsset, asset_id)
    if asset is None or asset.field_id != field_id:
        # foreign asset is indistinguishable from an unknown one
        raise NotFound("Asset not found.")

    from app.geospatial.objectstore import get_raster_storage

    storage = get_raster_storage()
    if storage.backend == "s3":
        return RedirectResponse(
            url=storage.signed_url(asset.storage_key, ttl_seconds=300),
            status_code=status.HTTP_302_FOUND,
        )
    try:
        data = storage.read_bytes(asset.storage_key)
    except Exception as exc:  # storage backend missing object
        raise HTTPException(status_code=502, detail=f"raster asset unavailable: {exc}") from exc
    return Response(
        content=data,
        media_type=asset.content_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Asset-Checksum": asset.checksum_sha256,
        },
    )


# ---------------------------------------------------- processing job list
@router.get("/fields/{field_id}/satellite/processing-jobs")
def list_satellite_processing_jobs(
    field_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Recent preprocessing job rows for the field (status + failures)."""
    get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(RasterProcessingJob)
        .where(RasterProcessingJob.field_id == field_id)
        .order_by(RasterProcessingJob.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "field_id": str(field_id),
        "total": len(rows),
        "jobs": [
            {
                "job_id": str(r.id),
                "background_job_id": str(r.background_job_id) if r.background_job_id else None,
                "scene_id": r.scene_id,
                "indices": list(r.indices or []),
                "processing_version": r.processing_version,
                "status": r.status,
                "progress": r.progress,
                "stage": r.stage,
                "error": (r.error or "")[:500] or None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ],
    }


# =============================================================== P07 ========
# ------------------------------------------------------------ layer catalog
@router.get("/fields/{field_id}/map/layers")
def get_field_map_layers(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Unified honest layer catalog for the map (membership gated)."""
    from app.geospatial.layer_catalog import field_map_layers

    field = get_field_for_principal(db, principal, field_id)
    catalog = field_map_layers(db, field)
    # resolve synthetic identity of the latest products from the scene rows
    latest_assets = db.scalars(
        select(RasterAsset).where(
            RasterAsset.field_id == field_id, RasterAsset.asset_kind == "derived"
        )
    ).all()
    scene_ids = {a.scene_id for a in latest_assets}
    scene_flags: dict[str, bool] = {}
    if scene_ids:
        for scene in db.scalars(
            select(SatelliteScene).where(
                SatelliteScene.field_id == field_id,
                SatelliteScene.scene_id.in_(scene_ids),
            )
        ).all():
            scene_flags[scene.scene_id] = bool(scene.is_synthetic)
    for layer in catalog["layers"]["vegetation"]:
        latest = layer.get("latest")
        if latest and latest.get("scene_id") in scene_flags:
            latest["is_synthetic"] = scene_flags[latest["scene_id"]]
    return catalog


# --------------------------------------------------------- XYZ tile service
@router.get("/fields/{field_id}/satellite/products/{asset_id}/tiles/{z}/{x}/{y}.png")
def get_product_tile(
    field_id: uuid.UUID,
    asset_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Render one XYZ tile of a derived product (membership gated).

    Server-side windowed render from the stored COG with the documented
    colormap; nodata is transparent. The client never receives storage keys
    or object-store URLs — only tile pixels. Tiles are cached server-side
    keyed by asset checksum so reprocessed products never serve stale pixels.
    """
    from fastapi.responses import Response as _Response

    from app.geospatial.objectstore import get_raster_storage
    from app.geospatial.rendering import (
        TILE_SIZE,
        asset_fingerprint,
        render_product_tile,
        tile_bounds,
    )

    get_field_for_principal(db, principal, field_id)
    asset = db.get(RasterAsset, asset_id)
    if asset is None or asset.field_id != field_id or asset.asset_kind != "derived":
        # foreign/preview/unknown assets are indistinguishable
        raise NotFound("Derived product not found for this field.")
    if not (0 <= z <= 22):
        raise ValidationFailed("tile zoom z must be within 0..22")
    try:
        tile_bounds(z, x, y)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc

    storage = get_raster_storage()
    try:
        png = render_product_tile(
            asset=asset,
            storage=storage,
            z=z,
            x=x,
            y=y,
            index_code=asset.index_code or "ndvi",
            size=TILE_SIZE,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # storage backend missing object
        raise HTTPException(
            status_code=502, detail=f"raster asset unavailable: {exc}"
        ) from exc
    etag = f'"{asset_fingerprint(asset)}-{z}-{x}-{y}"'
    return _Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=300",
            "ETag": etag,
            "X-Product-Index": asset.index_code or "",
            "X-Processing-Version": asset.processing_version or "",
        },
    )


# ------------------------------------------------------------- zone polygons
@router.get("/fields/{field_id}/satellite/products/{asset_id}/zones")
def get_product_zone_polygons(
    field_id: uuid.UUID,
    asset_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Statistical tercile zone polygons for one derived product (GeoJSON)."""
    from app.geospatial.objectstore import get_raster_storage
    from app.geospatial.rendering import zone_polygons_fc

    field = get_field_for_principal(db, principal, field_id)
    asset = db.get(RasterAsset, asset_id)
    if asset is None or asset.field_id != field_id or asset.asset_kind != "derived":
        raise NotFound("Derived product not found for this field.")
    geometry = _field_boundary_geojson(db, field.id)
    if geometry is None:
        raise ValidationFailed("field boundary is not registered")
    try:
        return zone_polygons_fc(
            asset=asset,
            storage=get_raster_storage(),
            geometry_geojson=geometry,
            index_code=asset.index_code or "ndvi",
        )
    except Exception as exc:  # noqa: BLE001 — loud, honest unavailability
        raise HTTPException(
            status_code=502,
            detail=f"stored raster could not be vectorized: {exc}",
        ) from exc


# -------------------------------------------------------------- distribution
@router.get("/fields/{field_id}/satellite/products/{asset_id}/distribution")
def get_product_distribution(
    field_id: uuid.UUID,
    asset_id: uuid.UUID,
    bins: int = Query(default=10, ge=2, le=50),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Field-masked histogram of one derived product (documented range)."""
    from app.geospatial.objectstore import get_raster_storage
    from app.geospatial.rendering import value_distribution

    field = get_field_for_principal(db, principal, field_id)
    asset = db.get(RasterAsset, asset_id)
    if asset is None or asset.field_id != field_id or asset.asset_kind != "derived":
        raise NotFound("Derived product not found for this field.")
    geometry = _field_boundary_geojson(db, field.id)
    if geometry is None:
        raise ValidationFailed("field boundary is not registered")
    try:
        return value_distribution(
            asset=asset,
            storage=get_raster_storage(),
            geometry_geojson=geometry,
            index_code=asset.index_code or "ndvi",
            bins=bins,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"stored raster could not be read: {exc}",
        ) from exc


# ------------------------------------------------------------ spatial analytics
@router.get("/fields/{field_id}/satellite/spatial-analytics")
def get_field_spatial_analytics(
    field_id: uuid.UUID,
    index: str = Query(default="ndvi", max_length=32),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Spatial variation, distribution, zones and zone history (membership)."""
    from app.geospatial.spatial_analytics import field_spatial_analytics

    field = get_field_for_principal(db, principal, field_id)
    return field_spatial_analytics(
        db,
        field,
        index_code=index.lower(),
        geometry_geojson=_field_boundary_geojson(db, field.id),
    )


# ----------------------------------------------------------------- anomalies
@router.get("/fields/{field_id}/satellite/anomalies")
def get_field_spatial_anomalies(
    field_id: uuid.UUID,
    index: str = Query(default="ndvi", max_length=32),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Quality-gated anomaly signals (NOT diagnoses; membership gated)."""
    from app.geospatial.spatial_analytics import detect_spatial_anomalies

    field = get_field_for_principal(db, principal, field_id)
    return detect_spatial_anomalies(db, field, index_code=index.lower())


# ---------------------------------------------------------------- comparison
@router.get("/fields/{field_id}/satellite/comparison")
def get_field_spatial_comparison(
    field_id: uuid.UUID,
    index: str = Query(default="ndvi", max_length=32),
    target_field_id: uuid.UUID | None = Query(default=None),
    acquired_at_a: str | None = Query(default=None, max_length=40),
    acquired_at_b: str | None = Query(default=None, max_length=40),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Compare two processed products with explicit compatibility checks.

    Both sides are membership-gated independently (the target field must be
    accessible to the caller too, otherwise 404 — no existence leak).
    """
    from app.geospatial.spatial_analytics import spatial_comparison

    field_a = get_field_for_principal(db, principal, field_id)
    field_b = None
    if target_field_id is not None:
        field_b = get_field_for_principal(db, principal, target_field_id)
    try:
        return spatial_comparison(
            db,
            field_a=field_a,
            index_code=index.lower(),
            field_b=field_b,
            acquired_at_a=acquired_at_a,
            acquired_at_b=acquired_at_b,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


# -------------------------------------------------------------- farm overview
@router.get("/farms/{farm_id}/satellite/overview")
def get_farm_satellite_overview(
    farm_id: uuid.UUID,
    index: str = Query(default="ndvi", max_length=32),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-field latest index state for farm-level analytics (membership)."""
    from app.geospatial.spatial_analytics import farm_satellite_overview

    farm = get_farm_for_principal(db, principal, farm_id)
    return farm_satellite_overview(db, farm, index_code=index.lower())


# ------------------------------------------------------------------- exports
@router.get("/fields/{field_id}/boundary.geojson")
def export_field_boundary_geojson(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Authorized GeoJSON boundary export (EPSG:4326, boundary versioned)."""
    from app.geospatial.exports import field_boundary_feature

    field = get_field_for_principal(db, principal, field_id)
    farm = db.get(dbm.Farm, field.farm_id)
    try:
        feature = field_boundary_feature(db, field, farm)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    return feature


@router.get("/farms/{farm_id}/fields.geojson")
def export_farm_fields_geojson(
    farm_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Authorized GeoJSON FeatureCollection of the farm's fields."""
    from app.geospatial.exports import farm_fields_feature_collection

    farm = get_farm_for_principal(db, principal, farm_id)
    return farm_fields_feature_collection(db, farm)


@router.get("/fields/{field_id}/satellite/timeline.csv")
def export_satellite_timeline_csv(
    field_id: uuid.UUID,
    index: str | None = Query(default=None, max_length=200),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Provenance-complete CSV of persisted satellite observations (bounded).

    `index` accepts a comma-separated list of index codes (default: all
    satellite indices). The row cap and time-span cap are enforced in the
    service — the endpoint can never scan unbounded history.
    """
    from fastapi.responses import Response as _Response

    from app.geospatial.exports import satellite_timeline_csv

    field = get_field_for_principal(db, principal, field_id)
    index_codes = None
    if index:
        codes = [c.strip().lower() for c in index.split(",") if c.strip()]
        unknown = [c for c in codes if c not in ("ndvi", "evi", "savi", "ndmi", "ndwi", "bsi")]
        if unknown:
            raise ValidationFailed(f"unsupported index codes: {unknown}")
        index_codes = codes
    csv_bytes = satellite_timeline_csv(
        db, field, index_codes=index_codes, date_from=date_from, date_to=date_to
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return _Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="field-{field_id}-satellite-timeline-{stamp}.csv"'
            ),
            "Cache-Control": "private, max-age=60",
        },
    )


def _field_boundary_geojson(db: Session, field_id: uuid.UUID) -> dict[str, Any] | None:
    import json as _json

    from sqlalchemy import text

    row = db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar()
    return _json.loads(row) if row else None

"""Geospatial preprocessing + field-level satellite intelligence (P05/P06).

Endpoints (all tenant-scoped through get_field_for_principal):

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

No endpoint performs raster work in-request; no endpoint fabricates data.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.db.models_p2 import RasterAsset, RasterProcessingJob
from app.data_platform.processing import service as processing
from app.domains.identity.service import get_field_for_principal, get_principal

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

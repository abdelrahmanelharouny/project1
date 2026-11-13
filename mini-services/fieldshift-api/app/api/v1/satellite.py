"""Satellite scene discovery & acquisition endpoints (P04 Workstream C/D).

Catalog + acquisition workflow for NASA HLS scenes:

- POST /fields/{field_id}/satellite/discovery   — CMR STAC metadata search
  (unauthenticated upstream; operator role required because it persists
  scene rows) → scenes persisted with status 'discovered'.
- GET  /fields/{field_id}/satellite/scenes      — paginated catalog with
  lifecycle statuses (membership required).
- POST /fields/{field_id}/satellite/acquisitions — queue bounded ingestion
  jobs for selected scenes (operator role required; 202 + status URLs).
- POST /jobs/{job_id}/cancel                    — cancel a still-queued
  acquisition job and release its scenes (operator role required).

No endpoint ever fabricates scenes, observations or quality metadata; empty
results are honest empty states and provider failures surface as 502/503.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.data_platform.acquisition import service as acquisition
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["satellite-acquisition"])


def _require_field_role(db: Session, principal: Any, field_id: uuid.UUID, minimum: str) -> dbm.Field:
    """Field access + org role gate for acquisition actions."""
    field = get_field_for_principal(db, principal, field_id)
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:
        raise NotFound("Field has no farm.")
    principal.require_org_role(farm.organization_id, minimum)
    return field


def _field_boundary_geojson(db: Session, field_id: Any) -> dict[str, Any]:
    from sqlalchemy import text

    raw = db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar_one()
    return json.loads(raw)


# ------------------------------------------------------------------ discovery
class DiscoveryRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    max_cloud_cover: float | None = Field(default=None, ge=0, le=100)
    limit: int = Field(default=240, ge=1, le=500)


@router.post("/fields/{field_id}/satellite/discovery")
def discover_satellite_scenes(
    field_id: uuid.UUID,
    payload: DiscoveryRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Discover NASA HLS scenes for a field geometry and date range (STAC).

    Synchronous and bounded: page size/page caps keep worst-case request
    duration controlled. Metadata only — no scene assets are downloaded.
    """
    field = _require_field_role(db, principal, field_id, "operator")
    start = payload.start_date if payload.start_date.tzinfo else payload.start_date.replace(tzinfo=UTC)
    end = payload.end_date if payload.end_date.tzinfo else payload.end_date.replace(tzinfo=UTC)
    acquisition.validate_acquisition_request(
        start=start,
        end=end,
        max_cloud_cover=payload.max_cloud_cover,
    )
    geometry = _field_boundary_geojson(db, field.id)
    return acquisition.discover_scenes(
        db,
        field=field,
        geometry_geojson=geometry,
        start=start,
        end=end,
        max_cloud_cover=payload.max_cloud_cover,
        limit=payload.limit,
    )


# --------------------------------------------------------------------- scenes
@router.get("/fields/{field_id}/satellite/scenes")
def list_satellite_scenes(
    field_id: uuid.UUID,
    provider_code: str | None = None,
    scene_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=settings.max_page_size),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Scene catalog for a field: lifecycle statuses, pagination, filtering."""
    field = get_field_for_principal(db, principal, field_id)
    return acquisition.list_field_scenes(
        db,
        field_id=field.id,
        provider_code=provider_code,
        status=scene_status,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------- acquisitions
class AcquisitionRequest(BaseModel):
    scene_ids: list[str] = Field(min_length=1, max_length=settings.nasa_hls_max_scenes_per_job)
    variables: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Vegetation index variables to derive (ndvi, evi, savi, ndmi, ndwi).",
    )


@router.post(
    "/fields/{field_id}/satellite/acquisitions",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_satellite_acquisitions(
    field_id: uuid.UUID,
    payload: AcquisitionRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Queue acquisition (asset read + index derivation) for selected scenes.

    Creates one idempotent ingestion job per HLS collection on the existing
    background infrastructure and returns 202 with status URLs to poll.
    """
    field = _require_field_role(db, principal, field_id, "operator")
    return acquisition.create_acquisitions(
        db,
        field=field,
        scene_ids=payload.scene_ids,
        variables=payload.variables,
        created_by=principal.id,
    )


# --------------------------------------------------------------------- cancel
@router.post("/jobs/{job_id}/cancel")
def cancel_satellite_job(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel a still-queued ingestion job and release its scenes.

    Running jobs are rejected (409): the single-process executor cannot
    interrupt work safely — surfaced honestly instead of pretending.
    """
    job = db.get(dbm.IngestionJob, job_id)
    if job is None:
        raise NotFound("Job not found.")
    field = get_field_for_principal(db, principal, job.field_id)
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:
        raise NotFound("Field has no farm.")
    principal.require_org_role(farm.organization_id, "operator")
    return acquisition.cancel_ingestion_job(db, job=job)

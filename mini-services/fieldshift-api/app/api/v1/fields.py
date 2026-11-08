"""Fields endpoints: CRUD, boundary versions, map payload (Master §41)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.farms_fields import service as field_service
from app.domains.identity.service import (
    get_farm_for_principal,
    get_field_for_principal,
    get_principal,
    require_farm_role,
)
from app.db import models as dbm

router = APIRouter(tags=["fields"])


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geometry: dict[str, Any]
    change_reason: str | None = Field(default=None, max_length=500)


class FieldPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class BoundaryVersionCreate(BaseModel):
    geometry: dict[str, Any]
    change_reason: str | None = Field(default=None, max_length=500)


@router.post("/farms/{farm_id}/fields", status_code=201)
def create_field(
    farm_id: uuid.UUID,
    payload: FieldCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    # RBAC (P0-2): field creation is a manager+ mutation.
    require_farm_role(db, principal, farm, "manager")
    return field_service.create_field(
        db, principal, farm, name=payload.name, geometry=payload.geometry,
        change_reason=payload.change_reason,
    )


@router.get("/farms/{farm_id}/fields")
def list_fields(
    farm_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    fields = db.scalars(select(dbm.Field).where(dbm.Field.farm_id == farm.id).order_by(dbm.Field.created_at)).all()
    return {"items": [field_service.field_payload(db, f) for f in fields], "total": len(fields)}


@router.get("/fields/{field_id}")
def get_field(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return field_service.field_payload(db, field)


def _farm_of_field(db: Session, field: Any) -> Any:
    """Resolve the owning farm of a tenant-scoped field (for role gates)."""
    return db.get(dbm.Farm, field.farm_id)


@router.patch("/fields/{field_id}")
def patch_field(
    field_id: uuid.UUID,
    payload: FieldPatch,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    # RBAC (P0-2): field edits are manager+ mutations on the field's farm.
    require_farm_role(db, principal, _farm_of_field(db, field), "manager")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        field.name = data["name"].strip()
    db.commit()
    return field_service.field_payload(db, field)


@router.post("/fields/{field_id}/boundary-versions", status_code=201)
def add_boundary_version(
    field_id: uuid.UUID,
    payload: BoundaryVersionCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    # RBAC (P0-2): boundary changes are manager+ mutations on the field's farm.
    require_farm_role(db, principal, _farm_of_field(db, field), "manager")
    return field_service.update_field_boundary(
        db, principal, field, geometry=payload.geometry, change_reason=payload.change_reason
    )


@router.get("/fields/{field_id}/boundary-versions")
def list_boundary_versions(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    versions = db.scalars(
        select(dbm.FieldBoundaryVersion)
        .where(dbm.FieldBoundaryVersion.field_id == field.id)
        .order_by(dbm.FieldBoundaryVersion.version_number)
    ).all()
    import json as _json
    from sqlalchemy import func as _func

    items = []
    for v in versions:
        geojson_str = db.scalar(
            select(_func.ST_AsGeoJSON(v.boundary))
        )
        geojson = _json.loads(geojson_str) if geojson_str else None
        items.append(
            {
                "id": str(v.id),
                "version_number": v.version_number,
                "area_ha": v.area_ha,
                "change_reason": v.change_reason,
                "created_by": str(v.created_by) if v.created_by else None,
                "created_at": v.created_at.isoformat(),
                "boundary_geojson": geojson,
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/fields/{field_id}/map")
def field_map(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    payload = field_service.field_payload(db, field)
    geojson = payload["boundary_geojson"]
    from app.geospatial.validation import bbox_of

    return {
        "field": {"id": payload["id"], "name": payload["name"], "area_ha": payload["area_ha"],
                  "boundary_version": payload["boundary_version"]},
        "boundary_geojson": geojson,
        "bbox": bbox_of(geojson) if geojson else None,
        "crs": "EPSG:4326",
        "area_method": "geodesic (WGS84 ellipsoid via PyProj Geod)",
    }

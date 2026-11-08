"""Farms and fields domain: CRUD, boundary versioning, serialization.

Business logic stays here — HTTP routers only parse/serialize (Master rule 16).
"""

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden
from app.db.models import AuditEvent, Farm, Field, FieldBoundaryVersion, Observation
from app.geospatial.validation import (
    GeometryValidationResult,
    validate_boundary_geojson,
)


def _wkb_from_geojson(geojson: dict[str, Any]):
    from geoalchemy2.shape import from_shape
    from shapely.geometry import shape

    return from_shape(shape(geojson), srid=4326)


def _ha(m2: float) -> float:
    return round(m2 / 10_000.0, 4)


# ------------------------------------------------------------------ farms
def create_farm(db: Session, principal: Any, payload: dict[str, Any]) -> Farm:
    # RBAC (P0-2): farm creation is a manager+ mutation in the organization
    # the farm is created in (the principal's first active org — same org
    # selection the tenant model has always used here).
    org_ids = principal.org_ids()
    if not org_ids:
        raise Forbidden("You do not belong to an active organization.")
    principal.require_org_role(next(iter(org_ids)), "manager")
    farm = Farm(
        organization_id=next(iter(org_ids)),
        name=payload["name"].strip(),
        country_code=payload["country_code"].strip().upper(),
        admin_region=(payload.get("admin_region") or "").strip() or None,
        timezone=payload.get("timezone", "UTC"),
        currency_code=payload.get("currency_code", "USD").upper(),
        unit_system=payload.get("unit_system", "metric"),
        preferred_language=payload.get("preferred_language", "en"),
    )
    db.add(farm)
    db.flush()
    db.add(
        AuditEvent(
            actor_id=principal.id,
            organization_id=farm.organization_id,
            entity_type="farm",
            entity_id=str(farm.id),
            action="create",
            after_snapshot={"name": farm.name},
        )
    )
    db.commit()
    return farm


def _farm_summary(db: Session, farm: Farm) -> dict[str, Any]:
    field_count = db.scalar(select(func.count()).select_from(Field).where(Field.farm_id == farm.id)) or 0
    total_area = db.scalar(
        select(func.coalesce(func.sum(Field.area_ha), 0.0)).select_from(Field).where(Field.farm_id == farm.id)
    )
    return {
        "id": str(farm.id),
        "organization_id": str(farm.organization_id),
        "name": farm.name,
        "country_code": farm.country_code,
        "admin_region": farm.admin_region,
        "timezone": farm.timezone,
        "currency_code": farm.currency_code,
        "unit_system": farm.unit_system,
        "preferred_language": farm.preferred_language,
        "field_count": int(field_count),
        "total_area_ha": float(total_area or 0.0),
        "created_at": farm.created_at.isoformat(),
        "updated_at": farm.updated_at.isoformat(),
    }


def list_farms(db: Session, principal: Any) -> list[dict[str, Any]]:
    org_ids = list(principal.org_ids())
    if not org_ids:
        return []
    farms = db.scalars(
        select(Farm).where(Farm.organization_id.in_(org_ids)).order_by(Farm.created_at)
    ).all()
    return [_farm_summary(db, farm) for farm in farms]


def farm_payload(db: Session, farm: Farm) -> dict[str, Any]:
    return _farm_summary(db, farm)


# ----------------------------------------------------------------- fields
def create_field(
    db: Session,
    principal: Any,
    farm: Farm,
    *,
    name: str,
    geometry: Any,
    change_reason: str | None = None,
) -> dict[str, Any]:
    validation = validate_boundary_geojson(geometry)
    area_ha = _ha(validation.area_m2_geodesic)
    field = Field(
        farm_id=farm.id,
        name=name.strip(),
        area_ha=area_ha,
        boundary=_wkb_from_geojson(validation.geojson),
        boundary_version=1,
        status="active",
    )
    db.add(field)
    db.flush()
    db.add(
        FieldBoundaryVersion(
            field_id=field.id,
            version_number=1,
            boundary=_wkb_from_geojson(validation.geojson),
            area_ha=area_ha,
            change_reason=change_reason or "initial boundary",
            created_by=principal.id,
        )
    )
    db.add(
        AuditEvent(
            actor_id=principal.id,
            organization_id=farm.organization_id,
            entity_type="field",
            entity_id=str(field.id),
            action="create",
            after_snapshot={"name": field.name, "area_ha": area_ha},
        )
    )
    db.commit()
    return {
        "id": str(field.id),
        "farm_id": str(farm.id),
        "name": field.name,
        "area_ha": area_ha,
        "geometry_valid": True,
        "boundary_version": 1,
        "data_passport_status": "not_assessed",
        "geometry_warnings": validation.warnings,
        "geometry_repaired": validation.repaired,
    }


def update_field_boundary(
    db: Session,
    principal: Any,
    field: Field,
    *,
    geometry: Any,
    change_reason: str | None = None,
) -> dict[str, Any]:
    validation = validate_boundary_geojson(geometry)
    area_ha = _ha(validation.area_m2_geodesic)
    next_version = field.boundary_version + 1
    field.boundary = _wkb_from_geojson(validation.geojson)
    field.area_ha = area_ha
    field.boundary_version = next_version
    db.add(
        FieldBoundaryVersion(
            field_id=field.id,
            version_number=next_version,
            boundary=_wkb_from_geojson(validation.geojson),
            area_ha=area_ha,
            change_reason=change_reason or "boundary update",
            created_by=principal.id,
        )
    )
    db.add(
        AuditEvent(
            actor_id=principal.id,
            organization_id=field.farm.organization_id,
            entity_type="field_boundary",
            entity_id=str(field.id),
            action="new_version",
            after_snapshot={"version": next_version, "area_ha": area_ha},
        )
    )
    db.commit()
    return {
        "id": str(field.id),
        "boundary_version": next_version,
        "area_ha": area_ha,
        "geometry_valid": True,
        "geometry_warnings": validation.warnings,
        "geometry_repaired": validation.repaired,
    }


def field_payload(db: Session, field: Field) -> dict[str, Any]:
    row = db.execute(
        select(
            func.ST_AsGeoJSON(field.boundary),
            # geography ST_Area (spheroidal) — independent cross-check of the
            # stored PyProj geodesic area (Master §14.1 area-method discipline).
            func.ST_Area(func.ST_GeogFromText(func.ST_AsText(field.boundary))),
        )
    ).first()
    geojson_str, postgis_area_m2 = row
    geojson = json.loads(geojson_str) if geojson_str else None
    postgis_area_ha = round(float(postgis_area_m2) / 10_000.0, 4) if postgis_area_m2 is not None else None
    obs_count = db.scalar(
        select(func.count()).select_from(Observation).where(Observation.field_id == field.id)
    ) or 0
    return {
        "id": str(field.id),
        "farm_id": str(field.farm_id),
        "name": field.name,
        "area_ha": field.area_ha,
        "boundary_geojson": geojson,
        "boundary_version": field.boundary_version,
        "status": field.status,
        "postgis_geodesic_area_ha": postgis_area_ha,
        "observation_count": int(obs_count),
        "data_passport_status": "not_assessed" if obs_count == 0 else "available",
        "created_at": field.created_at.isoformat(),
        "updated_at": field.updated_at.isoformat(),
    }

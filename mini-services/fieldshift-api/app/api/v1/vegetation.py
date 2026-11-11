"""Vegetation Intelligence endpoints (P2.A satellite intelligence).

- GET /vegetation/indices               — supported index catalog with formulas
- GET /fields/{id}/vegetation/summary   — temporal analysis + stress signals
- GET /fields/{id}/vegetation/scenes    — scene-level provenance table

All field-scoped endpoints are tenant-scoped through the field's farm.
Reads are viewer-accessible; ingestion runs through the standard data-jobs
pipeline (provider_code=satellite_sim|sentinel2).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db import models as dbm
from app.db.models_p2 import SatelliteScene
from app.domains.identity.service import get_field_for_principal, get_principal
from app.vegetation.indices import INDEX_FORMULAS, INDEX_REQUIREMENTS, supported_indices
from app.vegetation.service import vegetation_summary

router = APIRouter(tags=["vegetation"])


@router.get("/vegetation/indices")
def vegetation_indices() -> dict:
    """Catalog of supported vegetation indices with documented formulas and
    band requirements. An index is listed only when its formula is
    implemented; sensors lacking a required band refuse to compute it."""
    return {
        "indices": [
            {
                "code": code,
                "formula": INDEX_FORMULAS[code],
                "required_surfaces": list(INDEX_REQUIREMENTS[code]),
            }
            for code in supported_indices()
        ],
        "note": (
            "Indices are computed per pixel over the field mask, then "
            "summarized (index first, statistics second)."
        ),
    }


@router.get("/fields/{field_id}/vegetation/summary")
def field_vegetation_summary(
    field_id: uuid.UUID,
    index: str = Query("ndvi", description="Vegetation index code (ndvi/evi/savi/ndmi/ndwi)"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Temporal vegetation intelligence for one field + index: monthly stats
    against same-month seasonal baselines, anomaly/trend findings with
    dormancy context, and evidence-based stress signals that separate
    observed change from possible causes."""
    field = get_field_for_principal(db, principal, field_id)
    return vegetation_summary(db, field, index=index)


@router.get("/fields/{field_id}/vegetation/scenes")
def field_vegetation_scenes(
    field_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Scene-level provenance for satellite ingestions of this field,
    newest first (pagination for historical data)."""
    field = get_field_for_principal(db, principal, field_id)
    total = db.scalar(
        select(dbm.func.count(SatelliteScene.id)).where(SatelliteScene.field_id == field.id)
    )
    rows = list(
        db.scalars(
            select(SatelliteScene)
            .where(SatelliteScene.field_id == field.id)
            .order_by(SatelliteScene.acquired_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "field_id": str(field.id),
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "scenes": [
            {
                "id": str(r.id),
                "provider_code": r.provider_code,
                "product_code": r.product_code,
                "scene_id": r.scene_id,
                "acquired_at": r.acquired_at.isoformat() if r.acquired_at else None,
                "cloud_cover_pct": r.cloud_cover_pct,
                "spatial_resolution_m": r.spatial_resolution_m,
                "coverage_fraction": r.coverage_fraction,
                "is_synthetic": r.is_synthetic,
                "asset_refs": r.asset_refs,
            }
            for r in rows
        ],
    }

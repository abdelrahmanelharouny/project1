"""Feature engineering endpoints (Milestone 4): catalog, feature-run creation,
status, retrieval, values and run-to-run comparison (Master §41)."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.features.catalog import FEATURE_CATALOG_VERSION, catalog_payload
from app.features.service import (
    compare_runs,
    get_run_for_principal,
    run_payload,
    start_feature_run,
    value_payload,
)
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["features"])


# ------------------------------------------------------------------ catalog
@router.get("/features/catalog")
def features_catalog(principal: Any = Depends(get_principal)) -> dict:
    return {
        "feature_catalog_version": FEATURE_CATALOG_VERSION,
        "features": catalog_payload(),
        "notes": [
            "Count-style indicators cite their meteorological convention (WMO / ETCCDI); "
            "they are generic climate indices, not crop-specific stress thresholds.",
            "Crop-specific thresholds remain unevaluated until the versioned, sourced crop "
            "knowledge base is available.",
        ],
    }


# --------------------------------------------------------------- run create
class CropSeasonWindow(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date


class FeatureRunRequest(BaseModel):
    start_date: date
    end_date: date
    aggregation_levels: list[str] = Field(default=["monthly"])
    feature_codes: list[str] | None = None
    variables: list[str] | None = None
    calendar_timezone: str | None = None
    hemisphere: str = "north"
    crop_seasons: list[CropSeasonWindow] = Field(default_factory=list)
    source_overrides: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str | None = None


@router.post("/fields/{field_id}/feature-runs", status_code=status.HTTP_202_ACCEPTED)
def create_feature_run(
    field_id: uuid.UUID,
    payload: FeatureRunRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    run = start_feature_run(
        db,
        field=field,
        payload=payload.model_dump(),
        created_by=principal.id,
    )
    return run_payload(run)


# ----------------------------------------------------------------- run read
@router.get("/fields/{field_id}/feature-runs")
def list_feature_runs(
    field_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    total = db.scalar(
        select(dbm.func.count()).select_from(dbm.FeatureRun).where(dbm.FeatureRun.field_id == field.id)
    ) or 0
    runs = db.scalars(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field.id)
        .order_by(dbm.FeatureRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [run_payload(r) for r in runs], "total": int(total), "limit": limit, "offset": offset}


@router.get("/feature-runs/{run_id}")
def get_feature_run(
    run_id: uuid.UUID,
    include_manifest: bool = False,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run_for_principal(db, run_id, principal)
    return run_payload(run, include_manifest=include_manifest)


@router.get("/feature-runs/{run_id}/values")
def get_feature_run_values(
    run_id: uuid.UUID,
    aggregation_level: str | None = None,
    feature_code: str | None = None,
    quality_status: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run_for_principal(db, run_id, principal)
    q = select(dbm.FeatureValue).where(dbm.FeatureValue.run_id == run.id)
    count_q = (
        select(dbm.func.count())
        .select_from(dbm.FeatureValue)
        .where(dbm.FeatureValue.run_id == run.id)
    )
    if aggregation_level:
        q = q.where(dbm.FeatureValue.aggregation_level == aggregation_level)
        count_q = count_q.where(dbm.FeatureValue.aggregation_level == aggregation_level)
    if feature_code:
        q = q.where(dbm.FeatureValue.feature_code == feature_code)
        count_q = count_q.where(dbm.FeatureValue.feature_code == feature_code)
    if quality_status:
        q = q.where(dbm.FeatureValue.quality_status == quality_status)
        count_q = count_q.where(dbm.FeatureValue.quality_status == quality_status)
    total = db.scalar(count_q) or 0
    rows = db.scalars(
        q.order_by(
            dbm.FeatureValue.aggregation_level,
            dbm.FeatureValue.period_start,
            dbm.FeatureValue.feature_code,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "run_id": str(run.id),
        "items": [value_payload(v) for v in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/feature-runs/{run_id}/comparison")
def compare_feature_runs(
    run_id: uuid.UUID,
    against_run_id: uuid.UUID = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run_for_principal(db, run_id, principal)
    against = get_run_for_principal(db, against_run_id, principal)
    return compare_runs(db, run, against)

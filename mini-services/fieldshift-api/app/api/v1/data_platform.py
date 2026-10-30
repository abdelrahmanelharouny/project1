"""Data platform endpoints: catalog, provider health, ingestion jobs,
observations and the Field Data Passport (Master §41)."""

import uuid
from datetime import UTC, datetime, date
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import InvalidDateRange, NotFound
from app.data_platform.contracts.observations import validate_provider_request
from app.data_platform.contracts.variables import catalog_payload, DATA_DICTIONARY_VERSION
from app.data_platform.ingestion.service import start_ingestion_job
from app.data_platform.registry.provider_registry import get_provider_registry
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal
from app.passport.service import build_data_passport

router = APIRouter(tags=["data-platform"])


# ------------------------------------------------------------------ catalog
@router.get("/data/catalog")
def data_catalog(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    sources = db.scalars(select(dbm.DataSource).order_by(dbm.DataSource.provider_code)).all()
    items = []
    for source in sources:
        products = db.scalars(
            select(dbm.DatasetProduct).where(dbm.DatasetProduct.source_id == source.id)
        ).all()
        items.append(
            {
                "provider_code": source.provider_code,
                "provider_name": source.provider_name,
                "license_name": source.license_name,
                "license_url": source.license_url,
                "attribution_text": source.attribution_text,
                "documentation_url": source.documentation_url,
                "status": source.status,
                "known_limitations": source.known_limitations,
                "products": [
                    {
                        "product_code": p.product_code,
                        "product_version": p.product_version,
                        "description": p.description,
                        "spatial_resolution_m": p.spatial_resolution_m,
                        "temporal_resolution": p.temporal_resolution,
                        "coverage": {
                            "start": p.coverage_start.date().isoformat() if p.coverage_start else None,
                            "end": p.coverage_end.date().isoformat() if p.coverage_end else None,
                        },
                        "metadata": p.metadata,
                    }
                    for p in products
                ],
            }
        )
    return {
        "data_dictionary_version": DATA_DICTIONARY_VERSION,
        "variables": catalog_payload(),
        "sources": items,
    }


@router.get("/data/providers/health")
def providers_health(principal: Any = Depends(get_principal)) -> dict:
    return {"providers": get_provider_registry().health()}


@router.get("/variables")
def variables(principal: Any = Depends(get_principal)) -> dict:
    return {"data_dictionary_version": DATA_DICTIONARY_VERSION, "items": catalog_payload()}


# ---------------------------------------------------------------- data jobs
class DataJobRequest(BaseModel):
    provider_code: str = "synthetic"
    variables: list[str] = Field(min_length=1)
    start_date: date
    end_date: date
    profile: str | None = "temperate_seasonal"
    seed: int = 42


@router.post("/fields/{field_id}/data-jobs", status_code=status.HTTP_202_ACCEPTED)
def create_data_job(
    field_id: uuid.UUID,
    payload: DataJobRequest,
    response: Response,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    start_dt = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(payload.end_date, datetime.min.time(), tzinfo=UTC)
    # Fail fast on obviously invalid requests (providers re-validate anyway).
    validate_provider_request(payload.variables, start_dt, end_dt)
    # Unknown provider -> 404 before a job row is created.
    get_provider_registry().get(payload.provider_code)
    job = start_ingestion_job(
        db,
        field=field,
        provider_code=payload.provider_code,
        variables=payload.variables,
        start=start_dt,
        end=end_dt + _one_day_minus(),
        options={"profile": payload.profile, "seed": payload.seed},
        idempotency_key=None,
        created_by=principal.id,
    )
    return _job_payload(job)


def _one_day_minus():
    from datetime import timedelta

    return timedelta(seconds=1)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(dbm.IngestionJob, job_id)
    if job is None:
        raise NotFound("Job not found.")
    get_field_for_principal(db, principal, job.field_id)
    return _job_payload(job)


def _job_payload(job: "dbm.IngestionJob") -> dict:
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "field_id": str(job.field_id),
        "provider_code": job.provider_code,
        "status": job.status,
        "records_received": job.records_received,
        "records_rejected": job.records_rejected,
        "warnings": job.warnings,
        "error_summary": job.error_summary,
        "request_parameters": job.request_parameters,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "status_url": f"/api/v1/jobs/{job.id}",
    }


# -------------------------------------------------------------- observations
@router.get("/fields/{field_id}/observations")
def list_observations(
    field_id: uuid.UUID,
    variable_code: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    q = select(dbm.Observation).where(dbm.Observation.field_id == field.id)
    count_q = select(func.count()).select_from(dbm.Observation).where(dbm.Observation.field_id == field.id)
    if variable_code:
        q = q.where(dbm.Observation.variable_code == variable_code)
        count_q = count_q.where(dbm.Observation.variable_code == variable_code)
    if start:
        q = q.where(dbm.Observation.observed_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC))
        count_q = count_q.where(dbm.Observation.observed_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC))
    if end:
        end_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC)
        q = q.where(dbm.Observation.observed_at < end_dt)
        count_q = count_q.where(dbm.Observation.observed_at < end_dt)
    total = db.scalar(count_q) or 0
    rows = db.scalars(q.order_by(dbm.Observation.observed_at, dbm.Observation.variable_code).offset(offset).limit(limit)).all()
    items = [
        {
            "id": str(o.id),
            "variable_code": o.variable_code,
            "value": o.value,
            "unit": o.unit,
            "observed_at": o.observed_at.date().isoformat(),
            "period_start": o.period_start.date().isoformat(),
            "period_end": o.period_end.date().isoformat(),
            "time_support": o.time_support,
            "spatial_support_type": o.spatial_support_type,
            "spatial_resolution_m": o.spatial_resolution_m,
            "quality_status": o.quality_status,
            "uncertainty_value": o.uncertainty_value,
            "uncertainty_type": o.uncertainty_type,
            "is_synthetic": o.is_synthetic,
            "processing_version": o.processing_version,
            "metadata": o.metadata,
        }
        for o in rows
    ]
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


# ------------------------------------------------------------- dev seeding
@router.post("/dev/seed-demo")
def seed_demo_endpoint(
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """DEV-ONLY convenience (disabled when FIELDSHIFT_DEV_MODE=false).

    Creates/reuses a clearly-labelled demo workspace with SYNTHETIC data so the
    preview UI can be explored without manual setup. It never contains real
    measurements and its observations are all is_synthetic=true.
    """
    from app.core.config import settings
    from app.core.errors import Forbidden

    if not settings.dev_mode:
        raise NotFound("Demo seeding is disabled in this environment.")
    from app.dev.seed import ensure_demo_workspace

    return ensure_demo_workspace(db)


# ------------------------------------------------------------- data passport
@router.get("/fields/{field_id}/data-passport")
def data_passport(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return build_data_passport(db, field.id)

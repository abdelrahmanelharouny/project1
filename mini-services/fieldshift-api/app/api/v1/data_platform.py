"""Data platform endpoints: catalog, provider health, ingestion jobs,
observations, imports and the Field Data Passport (Master §41)."""

import json
import uuid
from datetime import UTC, datetime, date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import InvalidDateRange, NotFound, UnsupportedVariable, ValidationFailed
from app.data_platform.contracts.observations import validate_provider_request
from app.data_platform.contracts.variables import catalog_payload, DATA_DICTIONARY_VERSION
from app.data_platform.ingestion.service import (
    create_import_job,
    start_ingestion_job,
    submit_ingestion_job,
)
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
def providers_health(
    principal: Any = Depends(get_principal),
    with_probes: bool = Query(default=True),
) -> dict:
    return {"providers": get_provider_registry().health(with_probes=with_probes)}


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
    model: str | None = None  # open_meteo product selection (era5_land | era5)
    # P04: nasa_hls acquisition targets (scene ids discovered via the
    # satellite discovery endpoint). Without them the provider runs its own
    # bounded auto-discovery; the acquisition API is the preferred path.
    scene_ids: list[str] | None = None
    # M7.1 F-30: optional field-scoped idempotency key (replay is scoped to
    # THIS field — a colliding key from another field/tenant can never leak a
    # foreign job). Matches the feature-run contract.
    idempotency_key: str | None = None


def _provider_options(provider_code: str, payload: DataJobRequest) -> dict[str, Any]:
    if provider_code == "synthetic":
        return {"profile": payload.profile, "seed": payload.seed}
    if provider_code == "open_meteo":
        return {"model": payload.model or "era5_land"}
    if provider_code == "nasa_hls":
        return {"scene_ids": [s for s in (payload.scene_ids or []) if s]}
    return {}


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
    registry = get_provider_registry()
    provider = registry.get(payload.provider_code)
    # Fail fast when no requested variable is available from this provider.
    supported = registry.supported_variables(payload.provider_code)
    if supported and not (set(payload.variables) & set(supported)):
        raise UnsupportedVariable(
            f"Provider '{payload.provider_code}' supplies none of the requested variables.",
            details=[{"field": "variables", "reason": f"supported: {', '.join(supported)}"}],
        )
    # Provider-specific fail-fast checks (e.g. open_meteo model/variable fit).
    options = _provider_options(payload.provider_code, payload)
    if hasattr(provider, "validate_request"):
        provider.validate_request(variables=payload.variables, options=options)
    # Async execution (P0-3): with workers enabled the provider fetch runs on
    # the background worker pool and the 202 response keeps its exact shape
    # (status 'queued'; clients poll the unchanged status URL). With
    # job_workers <= 0 the legacy inline execution is preserved.
    job = start_ingestion_job(
        db,
        field=field,
        provider_code=payload.provider_code,
        variables=payload.variables,
        start=start_dt,
        end=end_dt + _one_day_minus(),
        options=options,
        idempotency_key=payload.idempotency_key,
        created_by=principal.id,
        execute=settings.job_workers <= 0,
    )
    if job.status == "queued" and settings.job_workers > 0:
        submit_ingestion_job(job.id)
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
            "evidence_class": o.evidence_class,
            "ingestion_job_id": str(o.ingestion_job_id) if o.ingestion_job_id else None,
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
    """DEV-ONLY convenience (disabled when CROPTWIST_DEV_MODE=false).

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


# ------------------------------------------------------------- data coverage
@router.get("/fields/{field_id}/data-coverage")
def data_coverage(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-variable, per-provider coverage summary for the coverage view."""
    field = get_field_for_principal(db, principal, field_id)
    rows = db.execute(
        select(
            dbm.Observation.variable_code,
            dbm.Observation.unit,
            dbm.DataSource.provider_code,
            dbm.DataSource.provider_name,
            dbm.DatasetProduct.product_code,
            dbm.DatasetProduct.product_version,
            func.count().label("n"),
            func.min(dbm.Observation.observed_at).label("first"),
            func.max(dbm.Observation.observed_at).label("last"),
            func.max(dbm.Observation.retrieved_at).label("last_retrieval"),
            func.sum(
                func.coalesce(dbm.Observation.value.is_not(None).cast(Integer), 0)
            ).label("valid_n"),
        )
        .join(dbm.DatasetProduct, dbm.Observation.dataset_product_id == dbm.DatasetProduct.id)
        .join(dbm.DataSource, dbm.DatasetProduct.source_id == dbm.DataSource.id)
        .where(dbm.Observation.field_id == field.id)
        .group_by(
            dbm.Observation.variable_code,
            dbm.Observation.unit,
            dbm.DataSource.provider_code,
            dbm.DataSource.provider_name,
            dbm.DatasetProduct.product_code,
            dbm.DatasetProduct.product_version,
        )
        .order_by(dbm.Observation.variable_code, dbm.DataSource.provider_code)
    ).all()

    grouped: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = grouped.setdefault(
            r.variable_code,
            {"variable_code": r.variable_code, "unit": r.unit, "total": 0, "valid": 0, "providers": []},
        )
        entry["total"] += int(r.n)
        entry["valid"] += int(r.valid_n or 0)
        entry["providers"].append(
            {
                "provider_code": r.provider_code,
                "provider_name": r.provider_name,
                "product_code": r.product_code,
                "product_version": r.product_version,
                "count": int(r.n),
                "valid_count": int(r.valid_n or 0),
                "first": r.first.date().isoformat() if r.first else None,
                "last": r.last.date().isoformat() if r.last else None,
                "last_retrieval": r.last_retrieval.isoformat() if r.last_retrieval else None,
            }
        )
    return {"field_id": str(field.id), "variables": sorted(grouped.values(), key=lambda v: v["variable_code"])}


# --------------------------------------------------------------- CSV import
@router.get("/data/imports/observations-csv/template")
def observations_csv_template() -> Response:
    template = (
        "date,variable_code,value,unit,notes\n"
        "2024-03-01,precipitation,12.5,mm,heavy overnight rain\n"
        "2024-03-02,precipitation,0,mm,dry day\n"
        "2024-03-03,air_temperature_mean,,degC,sensor offline\n"
    )
    return Response(
        content=template,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="croptwist-observations-template.csv"'},
    )


@router.post(
    "/fields/{field_id}/imports/observations-csv",
    status_code=status.HTTP_202_ACCEPTED,
)
def import_observations_csv(
    field_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Controlled farmer CSV import -> farmer_reported observations (M3)."""
    from app.data_platform.imports.csv_service import (
        PROVIDER_CODE as CSV_PROVIDER_CODE,
        parse_csv_observations,
    )

    field = get_field_for_principal(db, principal, field_id)
    raw = file.file.read()
    if len(raw) > settings.max_import_file_bytes:
        raise ValidationFailed(
            "CSV file exceeds the import size limit.",
            details=[{"field": "file", "reason": f"limit {settings.max_import_file_bytes} bytes"}],
        )
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationFailed(
            "CSV file must be UTF-8 encoded.",
            details=[{"field": "file", "reason": "decoding failed"}],
        ) from None

    result = parse_csv_observations(content, file_name=file.filename or "upload.csv")
    job = create_import_job(
        db,
        field=field,
        provider_code=CSV_PROVIDER_CODE,
        job_type="csv_import",
        result=result,
        request_parameters={
            "import_kind": "observations_csv",
            "file_name": file.filename,
            "file_sha256": result.coverage.get("file_sha256"),
        },
        created_by=principal.id,
    )
    return _job_payload(job)


# ------------------------------------------------------------ CHIRPS import
@router.post(
    "/fields/{field_id}/chirps-extractions",
    status_code=status.HTTP_202_ACCEPTED,
)
def chirps_extraction(
    field_id: uuid.UUID,
    file: UploadFile = File(...),
    observed_at: date = Form(...),
    period_kind: str = Form("daily"),
    product_status: str = Form("final"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Bulk CHIRPS v3 GeoTIFF import + spatial subset extraction (M3)."""
    from app.data_platform.providers.chirps.extractor import extract_field_precipitation
    from app.data_platform.providers.chirps.registry_info import (
        PROVIDER_CODE as CHIRPS_PROVIDER_CODE,
    )

    field = get_field_for_principal(db, principal, field_id)
    raw = file.file.read()
    if len(raw) > settings.max_import_file_bytes:
        raise ValidationFailed(
            "GeoTIFF exceeds the import size limit.",
            details=[{"field": "file", "reason": f"limit {settings.max_import_file_bytes} bytes"}],
        )

    boundary_geojson = json.loads(_field_boundary_geojson(db, field.id))
    observed_dt = datetime.combine(observed_at, datetime.min.time(), tzinfo=UTC)
    result = extract_field_precipitation(
        raw,
        file_name=file.filename or "chirps.tif",
        field_geometry_geojson=boundary_geojson,
        observed_at=observed_dt,
        period_kind=period_kind,
        product_status=product_status,
    )
    job = create_import_job(
        db,
        field=field,
        provider_code=CHIRPS_PROVIDER_CODE,
        job_type="chirps_raster_import",
        result=result,
        request_parameters={
            "import_kind": "chirps_geotiff_extract",
            "file_name": file.filename,
            "file_sha256": result.coverage.get("file_sha256"),
            "period_kind": period_kind,
            "product_status": product_status,
            "observed_at": observed_at.isoformat(),
        },
        created_by=principal.id,
    )
    return _job_payload(job)


def _field_boundary_geojson(db: Session, field_id) -> str:
    from sqlalchemy import text

    return db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar_one()

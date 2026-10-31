"""Ingestion orchestration (Master §12, §49).

Runs a provider fetch inside an ingestion_job lifecycle, validates every
payload against the canonical contracts, persists observations with full
provenance, and counts rejected records. Dedupe is enforced by the
`uq_observation_natural_key` unique constraint so retries never duplicate rows.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    ProviderFetchResult,
)
from app.data_platform.observability import record_ingestion
from app.data_platform.registry.provider_registry import get_provider_registry
from app.data_platform.registry.seed_sources import seed_data_registry
from app.db.models import (
    DatasetProduct,
    DataSource,
    Field,
    IngestionJob,
    Observation,
    ObservationQualityFlag,
)

logger = logging.getLogger("fieldshift.ingestion")


def _product_for_provider(
    db: Session,
    provider_code: str,
    product_code: str | None = None,
    product_version: str | None = None,
) -> tuple[DataSource, DatasetProduct]:
    source = db.scalar(select(DataSource).where(DataSource.provider_code == provider_code))
    if source is None:
        seed_data_registry(db)
        source = db.scalar(select(DataSource).where(DataSource.provider_code == provider_code))
    if source is None:
        raise NotFound(f"No registered data source for provider '{provider_code}'.")
    query = select(DatasetProduct).where(DatasetProduct.source_id == source.id)
    if product_code:
        query = query.where(DatasetProduct.product_code == product_code)
    if product_version:
        query = query.where(DatasetProduct.product_version == product_version)
    product = db.scalars(query.order_by(DatasetProduct.product_code)).first()
    if product is None:
        seed_data_registry(db)
        product = db.scalars(query).first()
    if product is None:
        raise NotFound(f"No dataset product registered for provider '{provider_code}'.")
    return source, product


def start_ingestion_job(
    db: Session,
    *,
    field: Field,
    provider_code: str,
    variables: list[str],
    start: datetime,
    end: datetime,
    options: dict[str, Any],
    idempotency_key: str | None,
    created_by: Any,
) -> IngestionJob:
    """Create (or return an existing) ingestion job. Job executes inline in this
    slice; the job table preserves state so a future worker queue can take over
    without contract changes (Master §9 async work)."""
    if idempotency_key:
        existing = db.scalar(
            select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

    job = IngestionJob(
        field_id=field.id,
        provider_code=provider_code,
        request_parameters={
            "variables": variables,
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "options": options,
        },
        idempotency_key=idempotency_key,
        status="queued",
        created_by=created_by,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing

    _execute_job(db, job, field=field, variables=variables, start=start, end=end, options=options)
    return job


def create_import_job(
    db: Session,
    *,
    field: Field,
    provider_code: str,
    job_type: str,
    result: "ProviderFetchResult",
    request_parameters: dict[str, Any] | None = None,
    created_by: Any = None,
) -> IngestionJob:
    """Create a completed import job from an already-materialized provider
    result (CSV / CHIRPS GeoTIFF workflows). Shares the exact persistence and
    accounting path with provider ingestion."""
    job = IngestionJob(
        field_id=field.id,
        provider_code=provider_code,
        job_type=job_type,
        request_parameters=request_parameters or {},
        status="running",
        created_by=created_by,
    )
    db.add(job)
    db.commit()
    job.started_at = datetime.now(UTC)
    _persist_result(db, job, field=field, result=result)
    return job


def _execute_job(
    db: Session,
    job: IngestionJob,
    *,
    field: Field,
    variables: list[str],
    start: datetime,
    end: datetime,
    options: dict[str, Any],
) -> None:
    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()

    try:
        provider = get_provider_registry().get(job.provider_code)
        aoi = AreaOfInterest(
            field_id=str(field.id),
            geometry_geojson=_field_boundary_geojson(db, field.id),
            area_ha=field.area_ha,
        )
        result = provider.fetch_observations(
            area_of_interest=aoi,
            variables=variables,
            start=start,
            end=end,
            options=options,
        )
    except Exception as exc:
        job.status = "failed"
        job.error_summary = f"{type(exc).__name__}: {exc}"
        job.completed_at = datetime.now(UTC)
        db.commit()
        logger.warning("ingestion job failed", extra={"job_id": str(job.id), "error": str(exc)})
        return

    _persist_result(db, job, field=field, result=result)


def _persist_result(db: Session, job: IngestionJob, *, field: Field, result) -> None:
    source, product = _product_for_provider(
        db,
        job.provider_code,
        product_code=result.provenance.product_code,
        product_version=result.provenance.product_version,
    )

    received = result.input_record_count if result.input_record_count is not None else len(result.observations)
    rejected = int(result.coverage.get("rows_rejected", 0) or 0)
    inserted = 0
    warnings = list(result.warnings)

    try:
        for obs in result.observations:
            if obs.quality_status == "missing" and obs.value is not None:
                rejected += 1
                warnings.append(
                    f"{obs.variable_code}@{obs.observed_at.date()} rejected: missing rows must not carry a value."
                )
                continue
            row = Observation(
                field_id=field.id,
                dataset_product_id=product.id,
                variable_code=obs.variable_code,
                value=obs.value,
                unit=obs.unit,
                observed_at=obs.observed_at,
                period_start=obs.period_start,
                period_end=obs.period_end,
                time_support=obs.time_support.value,
                spatial_support_type=obs.spatial_support_type.value,
                spatial_resolution_m=obs.spatial_resolution_m,
                quality_status=obs.quality_status.value,
                uncertainty_value=obs.uncertainty_value,
                uncertainty_type=obs.uncertainty_type,
                is_synthetic=obs.is_synthetic,
                retrieved_at=datetime.now(UTC),
                processing_version=obs.processing_version,
                metadata=obs.metadata,
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError:
                # Natural-key duplicate (retry/same-day refetch) — idempotent skip.
                db.rollback()
                continue
            inserted += 1
            for flag in obs.quality_flags:
                db.add(
                    ObservationQualityFlag(
                        observation_id=row.id,
                        flag_code=flag.get("flag_code", "UNKNOWN"),
                        severity=flag.get("severity", "info"),
                        message=flag.get("message", ""),
                        details=flag.get("details", {}),
                    )
                )
        db.commit()
        job.status = "succeeded"
        job.records_received = received
        job.records_rejected = rejected
        job.warnings = warnings[:100]
        job.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_summary = f"{type(exc).__name__}: {exc}"
        job.completed_at = datetime.now(UTC)
        db.commit()
        logger.exception("ingestion persistence failed", extra={"job_id": str(job.id)})

    record_ingestion(
        provider_code=job.provider_code,
        received=received,
        rejected=rejected,
        inserted=inserted,
        status=job.status,
    )


def _field_boundary_geojson(db: Session, field_id) -> dict[str, Any]:
    from sqlalchemy import text

    row = db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar_one()
    import json

    return json.loads(row)

"""Ingestion orchestration (Master §12, §49).

Runs a provider fetch inside an ingestion_job lifecycle, validates every
payload against the canonical contracts, persists observations with full
provenance, and counts rejected records. Dedupe is enforced by the
`uq_observation_natural_key` unique constraint so retries never duplicate rows.
"""

import logging
from datetime import UTC, datetime, timedelta
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

logger = logging.getLogger("croptwist.ingestion")


def _record_satellite_scenes(db: Session, job: IngestionJob, field: Field, result) -> int:
    """Record scene-level provenance for satellite providers (P2.A).

    Index VALUES go through the normal observation path; this only captures
    the scene dimension (id, acquisition time, cloud cover, resolution, asset
    refs) that many observations share. Idempotent per
    (field, provider, scene_id); scenes referenced by failed/missing rows are
    still recorded — the scene existed even if the index retrieval failed.
    """
    from sqlalchemy import select as _select

    from app.db.models_p2 import SatelliteScene

    scenes: dict[tuple[str, str], dict] = {}
    for obs in result.observations:
        meta = obs.metadata or {}
        scene_id = meta.get("scene_id")
        if not scene_id:
            continue
        key = (job.provider_code, str(scene_id))
        if key in scenes:
            continue
        scenes[key] = {
            "scene_id": str(scene_id)[:255],
            "acquired_at": obs.observed_at,
            "cloud_cover_pct": meta.get("cloud_cover_pct"),
            "spatial_resolution_m": meta.get("spatial_resolution_m") or obs.spatial_resolution_m,
            "band_mapping": meta.get("band_mapping"),
            "asset_refs": meta.get("asset_refs"),
            "coverage_fraction": (meta.get("zonal") or {}).get("coverage_fraction"),
            "is_synthetic": bool(obs.is_synthetic),
            "processing_version": obs.processing_version,
            "metadata_json": {
                "product_code": result.provenance.product_code,
                "platform": meta.get("platform"),
                "processing_baseline": meta.get("processing_baseline"),
                "provider_code": job.provider_code,
            },
        }
    recorded = 0
    for key, payload in scenes.items():
        exists = db.scalar(
            _select(SatelliteScene.id).where(
                SatelliteScene.field_id == field.id,
                SatelliteScene.provider_code == job.provider_code,
                SatelliteScene.scene_id == payload["scene_id"],
            )
        )
        if exists is not None:
            continue
        db.add(
            SatelliteScene(
                field_id=field.id,
                provider_code=job.provider_code,
                product_code=payload["metadata_json"].get("product_code") or "",
                **payload,
            )
        )
        recorded += 1
    return recorded


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
    execute: bool = True,
) -> IngestionJob:
    """Create (or return an existing) ingestion job.

    With ``execute=True`` (legacy default) the provider fetch runs inline in
    the request. With ``execute=False`` the job row stays 'queued' and the
    caller submits it to the background worker pool (app/core/jobs.py,
    P0-3) via :func:`submit_ingestion_job` — the job table preserves state
    so the queue can take over without contract changes (Master §9 async
    work)."""
    if idempotency_key:
        # M7.1 F-30: the replay lookup is scoped to THIS field (composite
        # index uq_ingestion_idempotency_v2). A key-only lookup could return
        # another tenant's job if a key collided or was guessed — the last
        # remaining cross-tenant replay edge (same fix pattern as feature
        # runs in 0005/F-3).
        existing = db.scalar(
            select(IngestionJob).where(
                IngestionJob.idempotency_key == idempotency_key,
                IngestionJob.field_id == field.id,
            )
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
            select(IngestionJob).where(
                IngestionJob.idempotency_key == idempotency_key,
                IngestionJob.field_id == field.id,
            )
        )
        if existing is None:
            raise
        return existing

    if execute:
        _execute_job(db, job, field=field, variables=variables, start=start, end=end, options=options)
    return job


def _execute_ingestion_job_by_id(job_id: Any, progress) -> None:  # noqa: ANN001
    """Worker-side execution: resolve job + field fresh in a worker session.

    Runs the exact same persistence path as inline execution; safe to call
    for a job still in 'queued' (returns silently otherwise — a duplicate
    submission must never double-execute).
    """
    from app.core.database import SessionLocal

    with SessionLocal() as worker_db:
        job = worker_db.get(IngestionJob, job_id)
        if job is None:
            raise NotFound(f"Ingestion job {job_id} not found.")
        if job.status != "queued":
            return  # already executed / cancelled while queued
        field = worker_db.get(Field, job.field_id)
        if field is None:
            raise NotFound(f"Field {job.field_id} not found.")
        params = job.request_parameters or {}
        progress(5, "fetching")
        _execute_job(
            worker_db,
            job,
            field=field,
            variables=params.get("variables", []),
            start=datetime.fromisoformat(params["start"]).replace(tzinfo=UTC)
            if "start" in params
            else None,
            end=datetime.fromisoformat(params["end"]).replace(tzinfo=UTC) + timedelta(seconds=1)
            if "end" in params
            else None,
            options=params.get("options", {}),
        )
        progress(100, "done")


def _replay_ingestion(background_job_id: Any, progress) -> None:  # noqa: ANN001
    """Crash-recovery executor: rebuild the ingestion id from the row's ref."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    with SessionLocal() as worker_db:
        bg = worker_db.get(BackgroundJob, background_job_id)
        if bg is None or bg.ref_id is None:
            raise NotFound("Background job has no ingestion reference.")
        target_id = bg.ref_id
    _execute_ingestion_job_by_id(target_id, progress)


_replay_registered = False


def submit_ingestion_job(ingestion_job_id: Any, request_id: str | None = None) -> Any:
    """Enqueue a queued ingestion job on the background worker pool (P0-3).

    The work function re-opens its own session inside the worker thread and
    resolves the job + field rows fresh from the captured ingestion job id —
    nothing request-scoped is closed over. The 'ingestion' kind is registered
    as replayable so crash-recovered 'queued' rows execute after a restart.
    """
    global _replay_registered
    from app.core import jobs as background_jobs

    if not _replay_registered:
        background_jobs.register_kind("ingestion", _replay_ingestion)
        _replay_registered = True
    return background_jobs.submit(
        "ingestion",
        lambda _background_job_id, progress: _execute_ingestion_job_by_id(
            ingestion_job_id, progress
        ),
        ref_kind="ingestion",
        ref_id=ingestion_job_id,
        label="provider observation ingestion",
        request_id=request_id,
    )


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
                evidence_class=obs.evidence_class.value,
                uncertainty_value=obs.uncertainty_value,
                uncertainty_type=obs.uncertainty_type,
                is_synthetic=obs.is_synthetic,
                ingestion_job_id=job.id,
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
        # Commit the terminal job state FIRST, independently of scene
        # provenance: scene-recording problems must never roll the job back
        # to 'running' (the observations themselves are already durable).
        db.commit()
        try:
            scenes_recorded = _record_satellite_scenes(db, job, field, result)
            db.commit()
            if scenes_recorded:
                logger.info(
                    "satellite scenes recorded",
                    extra={"job_id": str(job.id), "scenes": scenes_recorded},
                )
        except Exception:  # noqa: BLE001 — scene provenance must never fail the job
            db.rollback()
            logger.exception("satellite scene recording failed", extra={"job_id": str(job.id)})
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

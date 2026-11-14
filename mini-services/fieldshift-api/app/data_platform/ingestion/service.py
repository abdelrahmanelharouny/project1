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

from app.core.config import settings
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
    BackgroundJob,
    IngestionJob,
    Observation,
    ObservationQualityFlag,
)

logger = logging.getLogger("croptwist.ingestion")

_OBSERVATION_BATCH_SIZE = 100


def set_scene_acquisition_status(
    db: Session,
    field_id: Any,
    provider_code: str,
    scene_ids: list[str],
    status: str,
    detail: dict[str, Any] | None = None,
) -> int:
    """Move satellite scenes along the acquisition lifecycle (P04).

    Rows that do not exist are silently skipped (direct /data-jobs calls may
    reference scenes never discovered); rows already 'ready' are never
    downgraded — re-ingestion of ingested scenes must not resurrect stale
    statuses. Returns the number of rows updated.
    """
    from app.db.models_p2 import SatelliteScene

    updated = 0
    now = datetime.now(UTC)
    for scene_id in scene_ids:
        row = db.scalar(
            select(SatelliteScene).where(
                SatelliteScene.field_id == field_id,
                SatelliteScene.provider_code == provider_code,
                SatelliteScene.scene_id == str(scene_id)[:255],
            )
        )
        if row is None or row.acquisition_status == "ready":
            continue
        row.acquisition_status = status
        row.acquisition_detail = detail or {}
        row.acquisition_updated_at = now
        updated += 1
    if updated:
        logger.info(
            "satellite scene status updated",
            extra={
                "field_id": str(field_id),
                "provider_code": provider_code,
                "status": status,
                "scenes": updated,
            },
        )
    return updated


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
    now = datetime.now(UTC)
    for key, payload in scenes.items():
        exists = db.scalar(
            _select(SatelliteScene.id).where(
                SatelliteScene.field_id == field.id,
                SatelliteScene.provider_code == job.provider_code,
                SatelliteScene.scene_id == payload["scene_id"],
            )
        )
        if exists is not None:
            # Idempotent replay: never duplicate, and mark the scene 'ready'
            # (it produced observations in THIS job). Legacy rows keep their
            # other metadata untouched.
            row = db.get(SatelliteScene, exists)
            if row is not None and row.acquisition_status != "ready":
                row.acquisition_status = "ready"
                row.acquisition_detail = {"job_id": str(job.id)}
                row.acquisition_updated_at = now
            if row is not None:
                zonal_coverage = (payload.get("coverage_fraction"))
                if zonal_coverage is not None and row.coverage_fraction is None:
                    row.coverage_fraction = zonal_coverage
            continue
        db.add(
            SatelliteScene(
                field_id=field.id,
                provider_code=job.provider_code,
                product_code=payload["metadata_json"].get("product_code") or "",
                acquisition_status="ready",
                acquisition_detail={"job_id": str(job.id)},
                discovered_at=now,
                acquisition_updated_at=now,
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


def _register_ingestion_executor() -> None:
    global _replay_registered
    if not _replay_registered:
        from app.core import jobs as background_jobs

        background_jobs.register_kind("ingestion", _replay_ingestion)
        _replay_registered = True


def _ensure_ingestion_background_job(
    db: Session, ingestion_job_id: Any, request_id: str | None = None
) -> Any:
    """Create or reuse the durable companion row in the caller transaction."""
    from app.core import jobs as background_jobs

    _register_ingestion_executor()
    existing = db.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "ingestion",
            BackgroundJob.ref_kind == "ingestion",
            BackgroundJob.ref_id == ingestion_job_id,
        )
        .order_by(BackgroundJob.created_at.desc())
    )
    if existing is not None:
        return existing
    return background_jobs.submit(
        "ingestion",
        lambda _background_job_id, progress: _execute_ingestion_job_by_id(
            ingestion_job_id, progress
        ),
        db=db,
        ref_kind="ingestion",
        ref_id=ingestion_job_id,
        label="provider observation ingestion",
        request_id=request_id,
    )


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
            if existing.status == "queued" and (not execute or settings.job_queue_only):
                _ensure_ingestion_background_job(db, existing.id)
                db.commit()
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
    db.flush()
    should_execute = bool(execute and not settings.job_queue_only)
    if not should_execute:
        # The ingestion row and its replayable queue row share one commit. The
        # jobs after_commit hook wakes local workers only after both are visible.
        _ensure_ingestion_background_job(db, job.id)
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

    if should_execute:
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
        worker_db.refresh(job)
        if job.status != "succeeded":
            raise RuntimeError(job.error_summary or f"ingestion domain job ended as {job.status}")
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
    from app.core import jobs as background_jobs

    _register_ingestion_executor()
    from app.core.database import SessionLocal

    callback = lambda _background_job_id, progress: _execute_ingestion_job_by_id(
        ingestion_job_id, progress
    )
    with SessionLocal() as db:
        existing = db.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.kind == "ingestion",
                BackgroundJob.ref_kind == "ingestion",
                BackgroundJob.ref_id == ingestion_job_id,
            )
            .order_by(BackgroundJob.created_at.desc())
        )
    if existing is not None:
        if existing.status == "queued":
            background_jobs.enqueue_existing(existing.id, callback)
        return existing
    return background_jobs.submit(
        "ingestion",
        callback,
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

    # P04: move explicitly-targeted satellite scenes along the acquisition
    # lifecycle so scene status always mirrors real ingestion state.
    scene_ids = [str(s) for s in (options or {}).get("scene_ids") or []]
    if scene_ids:
        set_scene_acquisition_status(
            db, field.id, job.provider_code, scene_ids, "running", {"job_id": str(job.id)}
        )
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
        if scene_ids:
            set_scene_acquisition_status(
                db,
                field.id,
                job.provider_code,
                scene_ids,
                "failed",
                {
                    "job_id": str(job.id),
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                },
            )
        db.commit()
        logger.warning("ingestion job failed", extra={"job_id": str(job.id), "error": str(exc)})
        return

    _persist_result(db, job, field=field, result=result)

    # P04: scenes that were requested but produced no observations (degraded,
    # unreadable, or filtered out by the provider) surface honestly as failed.
    if scene_ids:
        returned = {
            str((obs.metadata or {}).get("scene_id"))
            for obs in result.observations
            if (obs.metadata or {}).get("scene_id")
        }
        missing = [s for s in scene_ids if s not in returned]
        if missing:
            relevant_warnings = [
                w for w in result.warnings if any(s in w for s in missing)
            ][:10]
            set_scene_acquisition_status(
                db,
                field.id,
                job.provider_code,
                missing,
                "failed",
                {
                    "job_id": str(job.id),
                    "reason": "scene not returned by provider",
                    "warnings": relevant_warnings,
                },
            )
        db.commit()


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

    def _new_observation(obs) -> Observation:
        return Observation(
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

    def _quality_flags(row: Observation, obs) -> list[ObservationQualityFlag]:
        return [
            ObservationQualityFlag(
                observation_id=row.id,
                flag_code=flag.get("flag_code", "UNKNOWN"),
                severity=flag.get("severity", "info"),
                message=flag.get("message", ""),
                details=flag.get("details", {}),
            )
            for flag in obs.quality_flags
        ]

    def _persist_chunk(events: list[tuple[str, Any]], candidates: list[Any]) -> None:
        """Persist one bounded chunk, retrying rows individually only on failure.

        A failed chunk savepoint expires/rolls back every ORM object involved in
        that attempt. The fallback therefore constructs fresh rows rather than
        reusing those objects, which keeps the session usable after PostgreSQL
        rejects a duplicate or another row-level integrity violation.
        """
        nonlocal inserted, rejected

        successful = [False] * len(candidates)
        try:
            rows = [_new_observation(obs) for obs in candidates]
            with db.begin_nested():
                db.add_all(rows)
                db.flush()
                flags = [
                    flag
                    for row, obs in zip(rows, candidates)
                    for flag in _quality_flags(row, obs)
                ]
                if flags:
                    db.add_all(flags)
                    db.flush()
            successful = [True] * len(candidates)
        except IntegrityError:
            # The chunk savepoint is gone; use a fresh row and a row-local
            # savepoint so one duplicate/bad row cannot poison its neighbours.
            for index, obs in enumerate(candidates):
                row = _new_observation(obs)
                try:
                    with db.begin_nested():
                        db.add(row)
                        db.flush()
                        flags = _quality_flags(row, obs)
                        if flags:
                            db.add_all(flags)
                            db.flush()
                    successful[index] = True
                except IntegrityError:
                    continue

        candidate_index = 0
        for event_kind, event_value in events:
            if event_kind == "missing":
                rejected += 1
                warnings.append(event_value)
                continue
            if successful[candidate_index]:
                inserted += 1
            else:
                rejected += 1
                obs = event_value
                warnings.append(
                    f"{obs.variable_code}@{obs.observed_at.date()} skipped: "
                    "duplicate or database integrity constraint."
                )
            candidate_index += 1

    try:
        events: list[tuple[str, Any]] = []
        candidates: list[Any] = []
        for obs in result.observations:
            if obs.quality_status == "missing" and obs.value is not None:
                events.append(
                    (
                        "missing",
                        f"{obs.variable_code}@{obs.observed_at.date()} rejected: "
                        "missing rows must not carry a value.",
                    )
                )
                continue
            events.append(("candidate", obs))
            candidates.append(obs)
            if len(events) >= _OBSERVATION_BATCH_SIZE:
                _persist_chunk(events, candidates)
                events = []
                candidates = []
        if events:
            _persist_chunk(events, candidates)
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

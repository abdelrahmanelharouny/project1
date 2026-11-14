"""Database-backed background-job dispatcher.

The ``background_jobs`` table is the durable source of truth. Each process
maintains only a local wake-up queue; workers poll the table so submissions
from an API process are visible to standalone workers without a broker.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings

logger = logging.getLogger("croptwist.jobs")

ProgressFn = Callable[[int, str | None], None]
JobFn = Callable[[uuid.UUID, ProgressFn], None]

_queue: "queue.Queue[uuid.UUID | None]" = queue.Queue()
_threads: list[threading.Thread] = []
_shutdown = threading.Event()
_pending_fns: dict[uuid.UUID, JobFn] = {}
_kind_executors: dict[str, JobFn] = {}
_registry_lock = threading.Lock()
_queue_lock = threading.Lock()
_queued_ids: set[uuid.UUID] = set()
_poll_lock = threading.Lock()
_last_poll_at = 0.0
_MAX_RECOVERY_ATTEMPTS = 3


def _queue_job_id(job_id: uuid.UUID) -> None:
    """Queue an ID once in this process; persisted state remains authoritative."""
    with _queue_lock:
        if job_id in _queued_ids:
            return
        _queued_ids.add(job_id)
        _queue.put(job_id)


def enqueue_existing(job_id: uuid.UUID, fn: JobFn | None = None) -> None:
    """Wake a worker for a BackgroundJob row committed by the caller."""
    if fn is not None:
        with _registry_lock:
            _pending_fns[job_id] = fn
    _queue_job_id(job_id)


def register_kind(kind: str, fn: JobFn) -> None:
    """Register a replayable executor for a durable job kind."""
    with _registry_lock:
        _kind_executors[kind] = fn


def register_builtin_executors() -> None:
    """Register known executors before startup recovery and DB polling."""
    from app.data_platform.ingestion.service import _replay_ingestion
    from app.data_platform.processing.service import (
        PROCESSING_JOB_KIND,
        replay_processing_job,
    )
    from app.reports.worker import REPORT_JOB_KIND, replay_report_job

    register_kind("ingestion", _replay_ingestion)
    register_kind(PROCESSING_JOB_KIND, replay_processing_job)
    register_kind(REPORT_JOB_KIND, replay_report_job)


def submit(
    kind: str,
    fn: JobFn,
    *,
    ref_kind: str | None = None,
    ref_id: uuid.UUID | None = None,
    label: str | None = None,
    request_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> Any:
    """Persist a queued BackgroundJob row first, then wake a local worker."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    job = BackgroundJob(
        kind=kind,
        status="queued",
        ref_kind=ref_kind,
        ref_id=ref_id,
        label=label,
        request_id=request_id,
        created_by=created_by,
    )
    with SessionLocal() as db:
        db.add(job)
        db.commit()
        job_id = job.id
    enqueue_existing(job_id, fn)
    return job


def start_workers() -> int:
    """Register executors, recover durable work, and start configured threads."""
    register_builtin_executors()
    n = settings.job_workers
    if n <= 0:
        return 0
    _shutdown.clear()

    # Remove legacy sentinels and retain real IDs. Do not rotate a real ID in
    # place: doing so can prevent the drain loop from ever reaching Empty.
    retained: list[uuid.UUID] = []
    while True:
        try:
            item = _queue.get_nowait()
        except queue.Empty:
            break
        if item is not None:
            retained.append(item)
        else:
            _queue.task_done()
    with _queue_lock:
        _queued_ids.clear()
    for job_id in retained:
        _queue_job_id(job_id)

    _recover_orphans()
    alive = sum(thread.is_alive() for thread in _threads)
    to_start = max(0, n - alive)
    for i in range(to_start):
        thread = threading.Thread(
            target=_worker_loop,
            name=f"croptwist-job-{len(_threads) + i}",
            daemon=True,
        )
        thread.start()
        _threads.append(thread)
    logger.info("background job workers active: %d", alive + to_start)
    return alive + to_start


def shutdown_workers() -> None:
    """Signal workers to finish current tasks; remaining IDs stay durable."""
    _shutdown.set()
    _threads.clear()


def _domain_job(db: Any, job: Any) -> Any | None:
    """Load the domain row referenced by a generic background job."""
    if job.ref_id is None:
        return None
    if job.ref_kind == "ingestion":
        from app.db.models import IngestionJob

        return db.get(IngestionJob, job.ref_id)
    if job.ref_kind == "raster_processing":
        from app.db.models_p2 import RasterProcessingJob

        return db.get(RasterProcessingJob, job.ref_id)
    if job.ref_kind == "report":
        from app.db.models_p3 import ReportJob

        return db.get(ReportJob, job.ref_id)
    return None


def _reset_domain_for_replay(domain: Any) -> None:
    domain.status = "queued"
    for field in ("error", "error_summary", "finished_at", "completed_at", "started_at"):
        if hasattr(domain, field):
            setattr(domain, field, None)
    if hasattr(domain, "progress"):
        domain.progress = 0
    if hasattr(domain, "stage"):
        domain.stage = "recovered after stale worker"


def _recover_orphans() -> None:
    """Requeue queued jobs and boundedly recover genuinely stale running jobs."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=max(settings.job_stale_after_seconds, 60))
    retry_ids: list[uuid.UUID] = []
    discovered = requeued = recovered = failed = 0
    with SessionLocal() as db:
        queued = db.scalars(
            select(BackgroundJob).where(BackgroundJob.status == "queued")
        ).all()
        discovered += len(queued)
        for job in queued:
            if job.kind in _kind_executors:
                _queue_job_id(job.id)
                requeued += 1

        stale = db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.status == "running",
                BackgroundJob.updated_at < stale_before,
            )
        ).all()
        for job in stale:
            domain = _domain_job(db, job)
            attempts = int((job.result or {}).get("_recovery_attempts", 0))
            if domain is not None and attempts < _MAX_RECOVERY_ATTEMPTS and job.kind in _kind_executors:
                _reset_domain_for_replay(domain)
                job.status = "queued"
                job.started_at = None
                job.finished_at = None
                job.error = None
                job.progress = 0
                job.result = {**(job.result or {}), "_recovery_attempts": attempts + 1}
                retry_ids.append(job.id)
                recovered += 1
            else:
                job.status = "failed"
                job.error = (
                    "interrupted by worker restart; recovery attempts exhausted"
                    if domain is not None
                    else "interrupted by worker restart; domain job missing or unsupported"
                )
                job.finished_at = now
                if domain is not None:
                    domain.status = "failed"
                    if hasattr(domain, "error"):
                        domain.error = job.error
                    elif hasattr(domain, "error_summary"):
                        domain.error_summary = job.error
                    if hasattr(domain, "finished_at"):
                        domain.finished_at = now
                    elif hasattr(domain, "completed_at"):
                        domain.completed_at = now
                failed += 1
        if queued or stale:
            db.commit()

    for job_id in retry_ids:
        _queue_job_id(job_id)
    if discovered or stale:
        logger.warning(
            "background job recovery: discovered=%d queued=%d retried=%d failed=%d",
            discovered,
            requeued,
            recovered,
            failed,
        )


def _poll_queued_jobs() -> None:
    """Discover durable queued work submitted by another API/worker process."""
    global _last_poll_at
    if not _poll_lock.acquire(blocking=False):
        return
    try:
        now = time.monotonic()
        if now - _last_poll_at < 0.5:
            return
        _last_poll_at = now
        with _registry_lock:
            kinds = tuple(_kind_executors)
        if not kinds:
            return
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.db.models import BackgroundJob

        with SessionLocal() as db:
            ids = db.scalars(
                select(BackgroundJob.id)
                .where(BackgroundJob.status == "queued", BackgroundJob.kind.in_(kinds))
                .order_by(BackgroundJob.created_at)
                .limit(100)
            ).all()
        for job_id in ids:
            _queue_job_id(job_id)
    except Exception:  # noqa: BLE001 — a poll error must not kill a worker thread
        logger.exception("durable background-job poll failed")
    finally:
        _poll_lock.release()


def _worker_loop() -> None:
    while not _shutdown.is_set():
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
            _poll_queued_jobs()
            continue
        if job_id is None:
            _queue.task_done()
            continue
        try:
            _run_job(job_id)
        except Exception:  # pragma: no cover — _run_job records its own errors
            logger.exception("worker loop error for job %s", job_id)
        finally:
            _queue.task_done()
            with _queue_lock:
                _queued_ids.discard(job_id)


def _run_job(job_id: uuid.UUID) -> None:
    """Atomically claim and execute one durable job."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    with _registry_lock:
        fn = _pending_fns.pop(job_id, None)

    with SessionLocal() as db:
        job = db.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return
        if fn is None:
            fn = _kind_executors.get(job.kind)
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress = 0
        db.commit()

        def progress(pct: int, stage: str | None = None) -> None:
            job.progress = max(0, min(int(pct), 100))
            if stage:
                job.stage = stage[:200]
            db.commit()

        try:
            if fn is None:
                raise RuntimeError(f"no executor available for background job kind '{job.kind}'")
            fn(job.id, progress)
            db.refresh(job)
            if job.status == "running":
                job.status = "succeeded"
                job.progress = 100
        except Exception as exc:
            db.refresh(job)
            if job.status == "running":
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning(
                "background job failed", extra={"job_id": str(job.id), "error": str(exc)}
            )
        finally:
            db.refresh(job)
            if job.status in ("succeeded", "failed", "cancelled") and job.finished_at is None:
                job.finished_at = datetime.now(UTC)
            db.commit()


def wait_for_job(job_id: uuid.UUID, timeout: float = 30.0, interval: float = 0.05) -> Any:
    """Block until a job reaches a terminal state (test/ops helper)."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if job is not None and job.status in ("succeeded", "failed", "cancelled"):
                return job
        time.sleep(interval)
    raise TimeoutError(f"background job {job_id} did not finish within {timeout}s")

"""In-process background job executor (async jobs P0-3).

Runs queue-level work outside the HTTP request so long-running tasks
(provider ingestion with 25-45s network calls today; heavier domain runs as
they migrate) no longer block FastAPI's threadpool or time out at the
gateway.

Design (deliberately small, dependency-free, single-process):

- A ``queue.Queue`` holds BackgroundJob ids; N daemon worker threads
  (``settings.job_workers``) drain it. Work functions execute in the worker
  thread and open their own ``SessionLocal`` — never reuse a request session.
- ``submit()`` persists the BackgroundJob row first (status 'queued'), then
  enqueues. The row is the source of truth for clients; the callable lives in
  an in-process registry keyed by job id.
- Crash recovery: on startup, rows still 'queued' are re-enqueued when their
  kind has a registered executor (``register_kind``); rows found 'running'
  are marked failed("interrupted by restart") — re-running a half-applied
  task is NOT safe in general (e.g. observations already persisted), so
  interrupted work is surfaced as failed instead of silently replayed.
- Progress: the work function receives ``progress(percent, stage=None)``
  which updates the row (committed immediately) so clients polling
  ``GET /api/v1/jobs/background/{id}`` observe liveness.
- Failure: any exception marks the job failed with ``type: message`` and is
  logged; the exception never kills a worker.

Multi-replica deployments should replace the queue with a shared store
(Redis) behind the same submit/progress surface; the HTTP contract and the
BackgroundJob table stay unchanged (same trade-off as app/core/rate_limit.py).
"""

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

logger = logging.getLogger("fieldshift.jobs")

ProgressFn = Callable[[int, str | None], None]
# Work function: receives (job_id, progress). Opens its own DB session(s).
JobFn = Callable[[uuid.UUID, ProgressFn], None]

_queue: "queue.Queue[uuid.UUID | None]" = queue.Queue()
_threads: list[threading.Thread] = []
_shutdown = threading.Event()
_pending_fns: dict[uuid.UUID, JobFn] = {}
_kind_executors: dict[str, JobFn] = {}
_registry_lock = threading.Lock()


# ------------------------------------------------------------------ submit
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
    """Persist a queued BackgroundJob row and enqueue it for a worker.

    ``fn`` runs later in a worker thread with its own session(s) — it must
    not close over request-scoped objects other than plain ids/values.
    """
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
    with _registry_lock:
        _pending_fns[job_id] = fn
    _queue.put(job_id)
    return job


def register_kind(kind: str, fn: JobFn) -> None:
    """Register a replayable executor for ``kind``.

    Jobs of this kind that are re-discovered 'queued' after a process
    restart can be executed from the persisted row (the executor rebuilds
    its inputs from ref ids / request_parameters in the domain tables).
    """
    with _registry_lock:
        _kind_executors[kind] = fn


# ------------------------------------------------------------------ workers
def start_workers() -> int:
    """Start ``settings.job_workers`` daemon threads; recover crash orphans.

    Returns the number of workers started (0 when the executor is disabled —
    ``job_workers <= 0`` keeps the legacy inline-execution behaviour).
    """
    n = settings.job_workers
    if n <= 0:
        return 0
    _shutdown.clear()
    # Purge stale sentinels from a previous pool generation (shutdown used
    # to enqueue None markers; a fresh worker consuming one would exit
    # immediately and silently shrink the pool).
    while True:
        try:
            stale = _queue.get_nowait()
            if stale is not None:
                _queue.put(stale)  # a real job id — keep it queued
        except queue.Empty:
            break
    _recover_orphans()
    for i in range(n):
        t = threading.Thread(target=_worker_loop, name=f"fieldshift-job-{i}", daemon=True)
        t.start()
        _threads.append(t)
    logger.info("background job workers started: %d", n)
    return n


def shutdown_workers() -> None:
    """Signal workers to exit after their current task (best effort).

    Workers poll ``_shutdown`` between queue waits (0.5s timeout), so no
    sentinel is needed — enqueueing one risks a fresh worker in a later
    pool generation consuming it and exiting.
    """
    _shutdown.set()
    _threads.clear()


def _recover_orphans() -> None:
    """Re-enqueue 'queued' rows from a previous process; fail stale 'running'."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    with SessionLocal() as db:
        queued = db.scalars(select(BackgroundJob).where(BackgroundJob.status == "queued")).all()
        requeued = 0
        for job in queued:
            if job.kind in _kind_executors:
                _queue.put(job.id)
                requeued += 1
        stale = db.scalars(select(BackgroundJob).where(BackgroundJob.status == "running")).all()
        now = datetime.now(UTC)
        for job in stale:
            job.status = "failed"
            job.error = "interrupted by restart"
            job.finished_at = now
        if queued or stale:
            db.commit()
            logger.warning(
                "background job recovery: discovered=%d requeued=%d interrupted=%d",
                len(queued),
                requeued,
                len(stale),
            )


def _worker_loop() -> None:
    while not _shutdown.is_set():
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if job_id is None:  # legacy sentinel — ignore
            _queue.task_done()
            continue
        try:
            _run_job(job_id)
        except Exception:  # pragma: no cover — _run_job records its own errors
            logger.exception("worker loop error for job %s", job_id)
        finally:
            _queue.task_done()


def _run_job(job_id: uuid.UUID) -> None:
    """Execute one job: queued -> running -> succeeded | failed."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    with _registry_lock:
        fn = _pending_fns.pop(job_id, None)

    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.status != "queued":
            return  # cancelled or unknown — do not execute
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
            job.status = "succeeded"
            job.progress = 100
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning(
                "background job failed", extra={"job_id": str(job.id), "error": str(exc)}
            )
        finally:
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

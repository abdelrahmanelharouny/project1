"""Database-backed background-job dispatcher.

The ``background_jobs`` table is the durable source of truth. Each process
maintains only a local wake-up queue; workers poll the table so submissions
from an API process are visible to standalone workers without a broker.

A worker owns a job only while both its persisted (owner, fencing token, lease)
and a PostgreSQL session advisory lock are valid. The independent heartbeat
keeps long-running jobs live even when executors report no user-facing progress.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from sqlalchemy import event, func, or_, select, text, update
from sqlalchemy.orm import Session

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
_JOB_LEASE_SECONDS = 120
_JOB_HEARTBEAT_SECONDS = 20
_TERMINAL_DOMAIN_STATUSES = {"succeeded", "failed", "cancelled", "expired"}
_TERMINAL_BACKGROUND_STATUSES = ("succeeded", "failed", "cancelled")
_DEFERRED_ENQUEUES_KEY = "croptwist_deferred_background_enqueues"
_current_execution: ContextVar[tuple[uuid.UUID, uuid.UUID, int] | None] = ContextVar(
    "current_background_job_execution", default=None
)


def current_job_execution() -> tuple[uuid.UUID, uuid.UUID, int] | None:
    """Return (job ID, owner ID, fencing token) for this executor thread, if any.

    Executors use this identity to fence domain writes against the persisted
    BackgroundJob lease. The context is scoped to the executor call and is not
    propagated to independent heartbeat threads.
    """
    return _current_execution.get()


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


def _enqueue_after_commit(session: Session) -> None:
    """Publish local wake-ups only after the owning DB transaction commits."""
    pending = session.info.pop(_DEFERRED_ENQUEUES_KEY, ())
    for job_id, fn in pending:
        enqueue_existing(job_id, fn)


def _discard_deferred_enqueues(session: Session) -> None:
    """Never wake a worker for rows discarded by a transaction rollback."""
    session.info.pop(_DEFERRED_ENQUEUES_KEY, None)


# A caller-provided session lets a domain row and its companion queue row share
# one transaction.  These listeners keep the existing submit() API compatible
# while preventing a worker from seeing a queue row before the domain commit.
event.listen(Session, "after_commit", _enqueue_after_commit)
event.listen(Session, "after_rollback", _discard_deferred_enqueues)


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
    db: Session | None = None,
    ref_kind: str | None = None,
    ref_id: uuid.UUID | None = None,
    label: str | None = None,
    request_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> Any:
    """Persist a queued row and wake workers only after its transaction commits.

    Existing callers may omit ``db``; that preserves the original self-contained
    transaction behavior.  A caller that is creating a domain row in an open
    transaction should pass that same session.  The companion row is flushed
    into that transaction and its local wake-up is deferred until commit, so a
    worker can never claim a queue row whose domain row was rolled back or is
    not yet visible.
    """
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
    if db is None:
        from app.core.database import SessionLocal

        with SessionLocal() as own_db:
            own_db.add(job)
            own_db.commit()
            # Touch the identity while the session is still open; SessionLocal
            # expires ORM attributes on commit and callers historically receive
            # this detached job object from submit().
            job_id = job.id
        enqueue_existing(job_id, fn)
        return job

    db.add(job)
    db.flush()
    db.info.setdefault(_DEFERRED_ENQUEUES_KEY, []).append((job.id, fn))
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


def _domain_model(job: Any) -> Any | None:
    """Return the mapped class for the domain row referenced by a job."""
    if job.ref_id is None:
        return None
    if job.ref_kind == "ingestion":
        from app.db.models import IngestionJob

        return IngestionJob
    if job.ref_kind == "raster_processing":
        from app.db.models_p2 import RasterProcessingJob

        return RasterProcessingJob
    if job.ref_kind == "report":
        from app.db.models_p3 import ReportJob

        return ReportJob
    return None


def _domain_job(db: Any, job: Any) -> Any | None:
    """Load the domain row referenced by a generic background job."""
    model = _domain_model(job)
    return db.get(model, job.ref_id) if model is not None else None


def _reset_domain_for_replay(domain: Any) -> None:
    """Reset only explicitly replayable, nonterminal domain work."""
    domain.status = "queued"
    for field in ("error", "error_summary", "finished_at", "completed_at", "started_at"):
        if hasattr(domain, field):
            setattr(domain, field, None)
    if hasattr(domain, "progress"):
        domain.progress = 0
    if hasattr(domain, "stage"):
        domain.stage = "recovered after expired worker lease"


def _background_terminal_status(domain_status: str) -> str | None:
    """Map terminal domain states onto the unified background-job contract."""
    return {
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "expired": "cancelled",
    }.get(domain_status)


def _replay_is_safe(job: Any, domain: Any) -> bool:
    """Allow only registered, known-idempotent domain replay paths."""
    if domain is None or domain.status not in {"queued", "running"}:
        return False
    if job.kind == "ingestion" and job.ref_kind == "ingestion":
        # Provider reads are repeatable; observations use a natural-key unique
        # constraint and scene provenance is upsert/idempotent.
        return True
    if job.kind == "raster_processing" and job.ref_kind == "raster_processing":
        # Raster assets overwrite deterministic keys; registries/observations
        # use natural keys and the processing service's replay path is queued-only.
        return True
    if job.kind == "report_generation" and job.ref_kind == "report":
        # Report rendering is replayed only if it never entered execution.
        # A 'running' report may have emitted/metered side effects before a
        # crash, so it fails closed rather than risking a duplicate.
        return domain.status == "queued"
    return False


def _lock_key(job_id: uuid.UUID) -> int:
    """Derive a stable signed int64 advisory-lock key from a UUID."""
    digest = hashlib.blake2b(job_id.bytes, digest_size=8, person=b"job-lock").digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@contextmanager
def _job_advisory_lock(job_id: uuid.UUID) -> Iterator[bool]:
    """Hold a PostgreSQL session lock for an entire execution/recovery action.

    The lock is session-scoped (not transaction-scoped), so committing heartbeats
    and executor work cannot release it. A lock miss means another live actor
    owns the job and this caller must not claim or recover it.
    """
    from app.core.database import engine

    connection = None
    acquired = False
    lock_key = _lock_key(job_id)
    try:
        connection = engine.connect()
        if connection.dialect.name != "postgresql":
            logger.error("background job ownership requires PostgreSQL advisory locks")
            yield False
            return
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}
            ).scalar_one()
        )
        connection.commit()
        yield acquired
    finally:
        if connection is not None:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                    connection.commit()
                except Exception:  # noqa: BLE001 — never return a possibly locked connection to pool
                    connection.invalidate()
            connection.close()


def _stale_candidate_ids(stale_before: datetime) -> list[uuid.UUID]:
    """Read candidate IDs; every row is rechecked under its advisory lock."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    with SessionLocal() as db:
        return list(
            db.scalars(
                select(BackgroundJob.id).where(
                    BackgroundJob.status == "running",
                    or_(
                        BackgroundJob.lease_expires_at <= func.clock_timestamp(),
                        (
                            BackgroundJob.lease_expires_at.is_(None)
                            & (BackgroundJob.updated_at < stale_before)
                        ),
                    ),
                )
            ).all()
        )


def _update_recovered_row(
    db: Any,
    job: Any,
    *,
    stale_before: datetime,
    values: dict[str, Any],
) -> bool:
    """CAS a stale running row using its observed fencing generation."""
    from app.db.models import BackgroundJob

    predicates = [
        BackgroundJob.id == job.id,
        BackgroundJob.status == "running",
        BackgroundJob.fencing_token == job.fencing_token,
    ]
    if job.owner_id is None:
        predicates.extend(
            [
                BackgroundJob.owner_id.is_(None),
                BackgroundJob.lease_expires_at.is_(None),
                BackgroundJob.updated_at < stale_before,
            ]
        )
    elif job.lease_expires_at is None:
        predicates.extend(
            [
                BackgroundJob.owner_id == job.owner_id,
                BackgroundJob.lease_expires_at.is_(None),
                BackgroundJob.updated_at < stale_before,
            ]
        )
    else:
        predicates.extend(
            [
                BackgroundJob.owner_id == job.owner_id,
                BackgroundJob.lease_expires_at <= func.clock_timestamp(),
            ]
        )
    result = db.execute(update(BackgroundJob).where(*predicates).values(**values))
    return result.rowcount == 1


def _reconcile_terminal_result(job: Any, domain: Any) -> dict[str, Any] | None:
    """Preserve useful executor result details when completing a crashed job."""
    result = dict(job.result or {}) if isinstance(job.result, dict) else {}
    if job.ref_kind == "report":
        result.update(
            {
                "report_job_id": str(domain.id),
                "report_type": domain.report_type,
                "format": domain.output_format,
            }
        )
    elif job.ref_kind == "raster_processing":
        result.update(
            {
                "derived_indices": list(domain.indices or []),
                "scene_id": domain.scene_id,
                "processing_version": domain.processing_version,
            }
        )
    elif not result:
        result["domain_status"] = str(domain.status)
    return result or None


def _recover_one(job_id: uuid.UUID, now: datetime, stale_before: datetime) -> str:
    """Recover one candidate while holding its advisory lock and row locks."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    retry = False
    outcome = "unchanged"
    with SessionLocal() as db:
        job = db.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "running":
            return outcome
        database_now = db.scalar(select(func.clock_timestamp()))
        if job.owner_id is None or job.lease_expires_at is None:
            if job.updated_at >= stale_before:
                return outcome
        elif job.lease_expires_at > database_now:
            return outcome

        model = _domain_model(job)
        domain = None
        if model is not None:
            domain = db.scalar(
                select(model).where(model.id == job.ref_id).with_for_update()
            )

        # A domain commit can win just before the worker crashes while the
        # unified row remains running. Reconcile; never reset or execute it.
        terminal = _background_terminal_status(str(domain.status)) if domain is not None else None
        if terminal is not None:
            error = getattr(domain, "error", None) or getattr(domain, "error_summary", None)
            values: dict[str, Any] = {
                "status": terminal,
                "owner_id": None,
                "lease_expires_at": None,
                "finished_at": now,
                "error": error if terminal == "failed" else None,
                "result": _reconcile_terminal_result(job, domain),
            }
            if terminal == "succeeded":
                values.update(progress=100, stage="completed")
            if _update_recovered_row(db, job, stale_before=stale_before, values=values):
                db.commit()
                outcome = "reconciled"
            else:
                db.rollback()
            return outcome

        # Legacy running rows without a persisted owner have no fencing proof.
        # Likewise, report rows already marked running might have completed a
        # usage/event side effect before a process crash. Fail closed.
        executors = set(_kind_executors)
        safe = (
            domain is not None
            and job.kind in executors
            and _replay_is_safe(job, domain)
        )
        attempts = int((job.result or {}).get("_recovery_attempts", 0)) if isinstance(job.result, dict) else 0
        has_valid_expired_owner = job.owner_id is not None and job.lease_expires_at is not None
        if safe and has_valid_expired_owner and attempts < _MAX_RECOVERY_ATTEMPTS:
            _reset_domain_for_replay(domain)
            result = dict(job.result or {}) if isinstance(job.result, dict) else {}
            result["_recovery_attempts"] = attempts + 1
            values = {
                "status": "queued",
                "owner_id": None,
                "lease_expires_at": None,
                "fencing_token": job.fencing_token + 1,
                "started_at": None,
                "finished_at": None,
                "error": None,
                "progress": 0,
                "stage": "recovered after expired worker lease",
                "result": result,
            }
            if _update_recovered_row(db, job, stale_before=stale_before, values=values):
                db.commit()
                retry = True
                outcome = "requeued"
            else:
                db.rollback()
        else:
            if not has_valid_expired_owner:
                reason = "stale running job has no valid owner lease; replay refused"
            elif domain is None:
                reason = "interrupted by worker restart; domain job missing or unsupported"
            elif job.kind == "report_generation" and domain.status == "running":
                reason = "report was already running; recovery refused to repeat side effects"
            elif job.kind not in executors:
                reason = "interrupted by worker restart; no registered replay executor"
            elif attempts >= _MAX_RECOVERY_ATTEMPTS:
                reason = "interrupted by worker restart; recovery attempts exhausted"
            else:
                reason = f"interrupted by worker restart; replay unsafe for domain status '{domain.status}'"
            values = {
                "status": "failed",
                "owner_id": None,
                "lease_expires_at": None,
                "fencing_token": job.fencing_token + 1,
                "finished_at": now,
                "error": reason,
            }
            if _update_recovered_row(db, job, stale_before=stale_before, values=values):
                db.commit()
                outcome = "failed"
            else:
                db.rollback()

    if retry:
        _queue_job_id(job_id)
    return outcome


def _recover_orphans() -> None:
    """Requeue queued work and safely recover expired, fenced worker leases."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=max(settings.job_stale_after_seconds, 60))
    queued_ids: list[uuid.UUID] = []
    with SessionLocal() as db:
        queued_ids = list(
            db.scalars(
                select(BackgroundJob.id).where(BackgroundJob.status == "queued")
            ).all()
        )
    discovered = len(queued_ids)
    requeued = 0
    with _registry_lock:
        kinds = set(_kind_executors)
    for job_id in queued_ids:
        # _run_job performs the authoritative atomic claim. Queue only durable
        # kinds with a registered process-local executor for cross-process work.
        with SessionLocal() as db:
            job_kind = db.scalar(
                select(BackgroundJob.kind).where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.status == "queued",
                )
            )
        if job_kind in kinds:
            _queue_job_id(job_id)
            requeued += 1

    recovered = failed = reconciled = locked = 0
    for job_id in _stale_candidate_ids(stale_before):
        try:
            with _job_advisory_lock(job_id) as acquired:
                if not acquired:
                    locked += 1
                    continue
                outcome = _recover_one(job_id, now, stale_before)
        except Exception:  # noqa: BLE001 — one damaged row must not block startup
            logger.exception("background job recovery failed for %s", job_id)
            failed += 1
            continue
        recovered += outcome == "requeued"
        failed += outcome == "failed"
        reconciled += outcome == "reconciled"

    if discovered or recovered or failed or reconciled or locked:
        logger.warning(
            "background job recovery: discovered=%d queued=%d retried=%d "
            "reconciled=%d failed=%d live_locks=%d",
            discovered,
            requeued,
            recovered,
            reconciled,
            failed,
            locked,
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


def _claim_job(job_id: uuid.UUID, owner_id: uuid.UUID) -> int | None:
    """Atomically claim queued work and advance the fencing generation."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    with SessionLocal() as db:
        result = db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
            .values(
                status="running",
                owner_id=owner_id,
                fencing_token=BackgroundJob.fencing_token + 1,
                lease_expires_at=func.clock_timestamp() + timedelta(seconds=_JOB_LEASE_SECONDS),
                started_at=now,
                finished_at=None,
                error=None,
                progress=0,
            )
            .returning(BackgroundJob.fencing_token)
        )
        token = result.scalar_one_or_none()
        db.commit()
        return int(token) if token is not None else None


def _heartbeat_once(job_id: uuid.UUID, owner_id: uuid.UUID, fencing_token: int) -> bool:
    """Extend a lease only while this exact owner/generation remains current."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    with SessionLocal() as db:
        result = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.fencing_token == fencing_token,
                BackgroundJob.lease_expires_at > now,
            )
            .values(lease_expires_at=now + timedelta(seconds=_JOB_LEASE_SECONDS))
        )
        db.commit()
        return result.rowcount == 1


def _heartbeat_loop(
    job_id: uuid.UUID,
    owner_id: uuid.UUID,
    fencing_token: int,
    stop: threading.Event,
    ownership_lost: threading.Event,
) -> None:
    """Renew leases in independent sessions while executors block or compute."""
    while not stop.wait(_JOB_HEARTBEAT_SECONDS):
        try:
            if not _heartbeat_once(job_id, owner_id, fencing_token):
                ownership_lost.set()
                return
        except Exception:  # noqa: BLE001 — retry transient DB failures before lease expiry
            logger.exception("background job heartbeat failed for %s", job_id)


def _write_progress(
    job_id: uuid.UUID,
    owner_id: uuid.UUID,
    fencing_token: int,
    pct: int,
    stage: str | None,
) -> bool:
    """Persist progress/lease only if the exact live owner still holds the fence."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "progress": max(0, min(int(pct), 100)),
        "lease_expires_at": now + timedelta(seconds=_JOB_LEASE_SECONDS),
    }
    if stage:
        values["stage"] = stage[:200]
    with SessionLocal() as db:
        result = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.fencing_token == fencing_token,
                BackgroundJob.lease_expires_at > now,
            )
            .values(**values)
        )
        db.commit()
        return result.rowcount == 1


def _finalize_job(
    job_id: uuid.UUID,
    owner_id: uuid.UUID,
    fencing_token: int,
    *,
    error: str | None,
) -> bool:
    """Fenced finalization; also clear leases after owned executors finalize directly."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    now = datetime.now(UTC)
    status = "failed" if error is not None else "succeeded"
    values: dict[str, Any] = {
        "status": status,
        "owner_id": None,
        "lease_expires_at": None,
        "finished_at": now,
        "error": error[:2000] if error is not None else None,
    }
    if error is None:
        values.update(progress=100, stage="completed")
    with SessionLocal() as db:
        result = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.fencing_token == fencing_token,
                BackgroundJob.lease_expires_at > now,
            )
            .values(**values)
        )
        if result.rowcount == 1:
            db.commit()
            return True

        # Built-in report/raster executors historically write their terminal
        # background status inside their domain transaction. Do not overwrite
        # that result, but clear the still-matching owner's lease metadata.
        cleanup = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status.in_(_TERMINAL_BACKGROUND_STATUSES),
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.fencing_token == fencing_token,
            )
            .values(
                owner_id=None,
                lease_expires_at=None,
                finished_at=func.coalesce(BackgroundJob.finished_at, now),
            )
        )
        db.commit()
        return cleanup.rowcount == 1


def _worker_loop() -> None:
    while not _shutdown.is_set():
        # The local queue is only a wake-up optimization.  Poll on every loop
        # so a process can discover rows committed by another API/worker even
        # while local wake-ups continue to arrive.
        _poll_queued_jobs()
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
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
    """Acquire a cross-process lock, atomically claim, heartbeat, and execute."""
    with _job_advisory_lock(job_id) as acquired:
        if not acquired:
            return

        with _registry_lock:
            fn = _pending_fns.pop(job_id, None)
        if fn is None:
            # Resolve a registered executor only after loading the durable kind.
            from app.core.database import SessionLocal
            from app.db.models import BackgroundJob

            with SessionLocal() as db:
                kind = db.scalar(
                    select(BackgroundJob.kind).where(
                        BackgroundJob.id == job_id,
                        BackgroundJob.status == "queued",
                    )
                )
            with _registry_lock:
                fn = _kind_executors.get(kind) if kind is not None else None

        owner_id = uuid.uuid4()
        fencing_token = _claim_job(job_id, owner_id)
        if fencing_token is None:
            return

        heartbeat_stop = threading.Event()
        ownership_lost = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(job_id, owner_id, fencing_token, heartbeat_stop, ownership_lost),
            name=f"croptwist-job-heartbeat-{job_id}",
            daemon=True,
        )
        heartbeat.start()
        execution_error: str | None = None

        def progress(pct: int, stage: str | None = None) -> None:
            if ownership_lost.is_set():
                return
            if not _write_progress(job_id, owner_id, fencing_token, pct, stage):
                ownership_lost.set()

        context_token = _current_execution.set((job_id, owner_id, fencing_token))
        try:
            if fn is None:
                raise RuntimeError("no executor available for durable background job kind")
            fn(job_id, progress)
        except Exception as exc:
            execution_error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning(
                "background job failed", extra={"job_id": str(job_id), "error": str(exc)}
            )
        finally:
            _current_execution.reset(context_token)
            heartbeat_stop.set()
            heartbeat.join(timeout=max(_JOB_HEARTBEAT_SECONDS, 1) + 1)
            if ownership_lost.is_set():
                logger.warning(
                    "background job owner lost its fencing lease",
                    extra={"job_id": str(job_id), "owner_id": str(owner_id), "fencing_token": fencing_token},
                )
            _finalize_job(job_id, owner_id, fencing_token, error=execution_error)


def wait_for_job(job_id: uuid.UUID, timeout: float = 30.0, interval: float = 0.05) -> Any:
    """Block until a job reaches a terminal state (test/ops helper)."""
    from app.core.database import SessionLocal
    from app.db.models import BackgroundJob

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))
            if job is not None and job.status in _TERMINAL_BACKGROUND_STATUSES:
                return job
        time.sleep(interval)
    raise TimeoutError(f"background job {job_id} did not finish within {timeout}s")

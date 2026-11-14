"""Periodic maintenance scheduler (P3 W5/W6 — recurring work).

Small, dependency-free, single-process interval scheduler. It complements
``app.core.jobs`` (which runs *queued one-shot work*) by driving the P3
sweeps that must happen over time:

- report execution: queued report jobs (API-created and recurring copies)
- outgoing webhook delivery: due/pending deliveries with backoff
- subscription lifecycle: expire stale trials/past-due subscriptions
- notifications: purge expired notifications
- activity: prune old activity events (per organization)
- reports retention: purge expired report artifacts
- AI and public API retention: bounded trace, feedback, conversation, usage and rate-state sweeps

Design rules:
- Every task opens its own ``SessionLocal`` and is fully error-isolated:
  an exception in one task never kills the loop or the other tasks.
- Tasks are idempotent; a lost race between replicas costs at most a
  no-op pass (same trade-off as app/core/rate_limit.py).
- Execution history: each task's last run timestamp/outcome is kept in
  ``LAST_RUNS`` (visible to ops health) and logged.
- The thread is a daemon and only starts when ``settings.scheduler_enabled``
  and ``settings.job_workers > 0``; tests run tasks directly instead.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger("croptwist.scheduler")

# Task -> {"at": iso8601, "ok": bool, "detail": str} — best-effort history.
LAST_RUNS: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval_seconds: int
    fn: Callable[[], str]


def _task_lock_key(task_name: str) -> int:
    """Stable signed int64 key shared by every scheduler process."""
    digest = hashlib.blake2b(
        task_name.encode("utf-8"), digest_size=8, person=b"sched-lock"
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@contextmanager
def _task_advisory_lock(session: Any, task_name: str):
    """Hold one cross-process lock for the task's complete DB transaction."""
    from app.core.database import engine

    lock_connection = engine.connect()
    try:
        if lock_connection.dialect.name != "postgresql":
            # Production is PostgreSQL; retaining local execution keeps unit
            # tests and development adapters compatible without claiming exclusivity.
            yield True
            return
        lock_key = _task_lock_key(task_name)
        acquired = bool(
            lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}
            ).scalar_one()
        )
        lock_connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                    lock_connection.commit()
                except Exception:  # noqa: BLE001 — never return a locked connection to pool
                    lock_connection.invalidate()
    finally:
        lock_connection.close()


def _run_task(task: PeriodicTask) -> None:
    from app.core.database import SessionLocal

    started = time.monotonic()
    ok = True
    detail = ""
    session = SessionLocal()
    try:
        with _task_advisory_lock(session, task.name) as acquired:
            if not acquired:
                detail = "skipped: advisory lock held by another scheduler"
            else:
                detail = str(task.fn(session)) or "ok"
                session.commit()
    except Exception:  # noqa: BLE001 — never kill the scheduler loop
        ok = False
        detail = "error (see log)"
        logger.exception("scheduler task %s failed", task.name)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        session.close()
    took_ms = int((time.monotonic() - started) * 1000)
    with _lock:
        LAST_RUNS[task.name] = {
            "at": datetime.now(UTC).isoformat(),
            "ok": ok,
            "detail": detail,
            "took_ms": took_ms,
        }
    logger.info("scheduler.%s ok=%s detail=%s took_ms=%d", task.name, ok, detail, took_ms)


# ------------------------------------------------------------- task bodies
def _execute_queued_reports(session) -> str:  # type: ignore[no-untyped-def]
    """Enqueue queued reports (oldest first, bounded batch) for workers."""
    import uuid as _uuid

    from sqlalchemy import select

    from app.core import jobs as core_jobs
    from app.db.models import BackgroundJob
    from app.db.models_p3 import ReportJob
    from app.reports.worker import replay_report_job, submit_report_job

    jobs = list(
        session.scalars(
            select(ReportJob)
            .where(ReportJob.status == "queued")
            .order_by(ReportJob.created_at.asc())
            .limit(10)
        ).all()
    )
    enqueued = 0
    skipped = 0
    for job in jobs:
        job_id = _uuid.UUID(str(job.id))
        existing = session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.kind == "report_generation",
                BackgroundJob.ref_kind == "report",
                BackgroundJob.ref_id == job_id,
            )
            .order_by(BackgroundJob.created_at.desc())
        )
        if existing is not None and existing.status != "queued":
            skipped += 1
            continue
        if existing is None:
            submit_report_job(
                job_id,
                created_by=job.requested_by,
                db=session,
            )
        else:
            core_jobs.enqueue_existing(existing.id, replay_report_job)
        enqueued += 1
    return f"enqueued={enqueued} skipped={skipped}"


def _retry_webhooks(session) -> str:  # type: ignore[no-untyped-def]
    from app.publicapi.webhooks import retry_due_webhooks

    counts = retry_due_webhooks(session, datetime.now(UTC))
    return str(counts)


def _expire_subscriptions(session) -> str:  # type: ignore[no-untyped-def]
    from app.billing.service import expire_stale_subscriptions

    n = expire_stale_subscriptions(session)
    return f"expired={n}"


def _purge_notifications(session) -> str:  # type: ignore[no-untyped-def]
    from app.notifications.service import purge_expired

    n = purge_expired(session)
    return f"purged={n}"


def _prune_activity(session) -> str:  # type: ignore[no-untyped-def]
    """Per-organization prune (service is org-scoped by design)."""
    import uuid as _uuid

    from sqlalchemy import select

    from app.activity.service import prune_older_than
    from app.db.models_p3 import Organization as P3Organization  # noqa: F401
    from app.db.models import Organization

    cutoff = datetime.now(UTC) - timedelta(days=365)
    org_ids = list(session.scalars(select(Organization.id)).all())
    pruned = 0
    for raw in org_ids:
        pruned += prune_older_than(
            session, before=cutoff, organization_id=_uuid.UUID(str(raw))
        )
    return f"orgs={len(org_ids)} pruned={pruned}"


def _purge_reports(session) -> str:  # type: ignore[no-untyped-def]
    from app.reports.service import advance_recurring, purge_expired_reports

    copies = advance_recurring(session, datetime.now(UTC))
    purged = purge_expired_reports(session, datetime.now(UTC))
    return f"recurring_enqueued={len(copies)} purged={purged}"


def _purge_ai_data(session) -> str:  # type: ignore[no-untyped-def]
    from app.intelligence.orchestration.retention import purge_expired_ai_data

    return str(purge_expired_ai_data(session, batch_size=1000))


def _purge_public_api_state(session) -> str:  # type: ignore[no-untyped-def]
    from app.publicapi.api_keys import purge_api_key_usage

    return str(purge_api_key_usage(session, batch_size=1000))


TASKS: tuple[PeriodicTask, ...] = (
    PeriodicTask("reports.execute_queued", 15, _execute_queued_reports),
    PeriodicTask("webhooks.retry_due", 30, _retry_webhooks),
    PeriodicTask("billing.expire_stale", 300, _expire_subscriptions),
    PeriodicTask("notifications.purge_expired", 300, _purge_notifications),
    PeriodicTask("reports.recurring_and_retention", 300, _purge_reports),
    PeriodicTask("activity.prune", 900, _prune_activity),
    PeriodicTask("ai.retention", 900, _purge_ai_data),
    PeriodicTask("public_api.retention", 3600, _purge_public_api_state),
)

_thread: threading.Thread | None = None
_shutdown = threading.Event()


def _loop() -> None:  # pragma: no cover — thread body
    # Stagger first run slightly so the app finishes booting.
    if not _shutdown.wait(5.0):
        pass
    next_at = {t.name: time.monotonic() + t.interval_seconds for t in TASKS}
    while not _shutdown.is_set():
        now = time.monotonic()
        for task in TASKS:
            if _shutdown.is_set():
                break
            if now >= next_at[task.name]:
                _run_task(task)
                next_at[task.name] = time.monotonic() + task.interval_seconds
        _shutdown.wait(1.0)


def start_scheduler() -> bool:
    """Start the maintenance loop. Returns True when started."""
    global _thread
    if not settings.scheduler_enabled or settings.job_workers <= 0:
        logger.info(
            "scheduler disabled (scheduler_enabled=%s job_workers=%s)",
            settings.scheduler_enabled,
            settings.job_workers,
        )
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _shutdown.clear()
    _thread = threading.Thread(target=_loop, name="croptwist-scheduler", daemon=True)
    _thread.start()
    logger.info("scheduler started with %d periodic tasks", len(TASKS))
    return True


def stop_scheduler() -> None:
    global _thread
    _shutdown.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None


def scheduler_status() -> dict[str, Any]:
    """Ops surface: task intervals + last-run history (no secrets)."""
    return {
        "enabled": bool(settings.scheduler_enabled and settings.job_workers > 0),
        "running": _thread is not None and _thread.is_alive(),
        "tasks": [
            {"name": t.name, "interval_seconds": t.interval_seconds} for t in TASKS
        ],
        "last_runs": dict(LAST_RUNS),
    }

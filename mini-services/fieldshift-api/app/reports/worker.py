"""Report-generation background-job kind (P07 D4).

Reports were historically executed by the API scheduler sweep (every 15 s,
bounded batch). That remains the default path. This module adds the SAME
execution as a background-job kind so long report renders (large PDF/XLSX
payloads, field-intelligence reports over many observations) can be picked up
by the standalone worker process (`python -m app.worker`) instead of the API.
The shared report-service advisory fence serializes both entry points; only a
queued report is replayed, while succeeded rows reconcile without side effects
and an already-running row fails closed.

Idempotency contract:
- One `background_jobs` row per `report_jobs` row (`ref_kind=report`,
  `ref_id=report_job_id`); the executor checks terminal state before rendering,
  and the report service rechecks it after acquiring a per-report advisory lock.
- Failures surface on both rows with a storage-safe error message.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.database import SessionLocal

logger = logging.getLogger("croptwist.reports.worker")

REPORT_JOB_KIND = "report_generation"


def execute_report_background_job(background_job_id: uuid.UUID, progress: Any = None) -> None:
    """Background-job executor: render one report job end-to-end.

    Rebuilds all inputs from persisted rows (the report_jobs row carries the
    full request: type, format, locale, scope, window) — nothing comes from
    the enqueueing request, so crash recovery after restart replays cleanly.
    """
    from app.db.models import BackgroundJob
    from app.db.models_p3 import ReportJob
    from app.reports import service as reports

    with SessionLocal() as session:
        bg = session.get(BackgroundJob, background_job_id)
        if bg is None or bg.ref_id is None:
            logger.warning(
                "report background job %s has no report reference; skipping",
                background_job_id,
            )
            return
        report_id = uuid.UUID(str(bg.ref_id))
        report = session.get(ReportJob, report_id)
        if report is None:
            _fail(session, bg, "report job row disappeared")
            return
        if report.status == "succeeded":
            # Domain success commits together with usage metering. Reconcile a
            # crash-window background row without re-entering report service.
            bg.status = "succeeded"
            bg.progress = 100
            bg.result = {
                "report_job_id": str(report_id),
                "report_type": report.report_type,
                "format": report.output_format,
            }
            session.commit()
            return
        if report.status == "expired":
            bg.status = "cancelled"
            session.commit()
            return
        if report.status == "failed":
            bg.status = "failed"
            bg.error = report.error or "report job has failed; replay refused"
            session.commit()
            return
        if report.status == "running":
            # A legacy/inline/scheduler executor may have made progress before
            # the crash. Never reset it to queued or risk repeating metering or
            # report.ready emission; recovery marks this queue record failed.
            bg.status = "failed"
            bg.error = "report job was already running; replay refused"
            session.commit()
            return
        if callable(progress):
            progress(5, "gathering report data")
        ok, error = reports.execute_report_job(session, report_id)
        bg2 = session.get(BackgroundJob, background_job_id)
        if bg2 is None:  # pragma: no cover
            return
        if ok:
            bg2.status = "succeeded"
            bg2.progress = 100
            bg2.result = {
                "report_job_id": str(report_id),
                "report_type": report.report_type,
                "format": report.output_format,
            }
        else:
            bg2.status = "failed"
            bg2.error = error or "report rendering failed"
        session.commit()
        logger.info(
            "report background job %s finished ok=%s", background_job_id, ok
        )


def replay_report_job(background_job_id: uuid.UUID, progress: Any = None) -> None:
    """Replay entrypoint registered with core.jobs (same executor)."""
    execute_report_background_job(background_job_id, progress)


def submit_report_job(report_job_id: uuid.UUID, *, created_by: uuid.UUID | None = None) -> Any:
    """Enqueue report rendering as a background job (worker path).

    The API keeps its scheduler sweep; callers that know a report is heavy
    (field-intelligence PDFs) can route through this instead so the work
    lands on the worker pool.
    """
    from app.core import jobs as core_jobs
    from app.db.models import BackgroundJob

    return core_jobs.submit(
        REPORT_JOB_KIND,
        lambda job_id, progress=None: execute_report_background_job(job_id, progress),
        ref_kind="report",
        ref_id=str(report_job_id),
        label=f"report:{report_job_id}",
        created_by=created_by,
    )


def _fail(session: Any, bg: Any, message: str) -> None:
    bg.status = "failed"
    bg.error = message[:500]
    session.commit()

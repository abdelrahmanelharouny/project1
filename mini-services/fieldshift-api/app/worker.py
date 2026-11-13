"""Standalone geospatial worker process (P05 Workstream B).

Runs ONLY background-job workers (no HTTP server): ingestion, raster
preprocessing and any other registered job kinds. Independently deployable
from the FastAPI application so long-running raster work never shares a
process (or a timeout budget) with request handlers, and so production can
scale workers separately from the API.

Usage (local development):
    .venv/bin/python -m app.worker              # N workers (job_workers)
    .venv/bin/python -m app.worker --workers 1  # explicit concurrency

Graceful shutdown: SIGTERM/SIGINT stop the intake loop immediately; workers
finish their CURRENT job and exit. Queued-but-unstarted rows stay 'queued'
in the database and are recovered by the NEXT worker process (or the API)
via the registered replay executors — no work is lost, no half-applied
state is replayed.

Durability contract (unchanged from app/core/jobs.py):
- background_jobs rows are the source of truth; the in-process queue holds
  only ids;
- crash recovery re-enqueues 'queued' rows whose kind is registered and
  fails stale 'running' rows loudly (never silent half-replay);
- concurrency limits come from --workers / CROPTWIST_JOB_WORKERS (raster
  work is memory/CPU heavy; keep N modest on small hosts).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

logger = logging.getLogger("croptwist.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CropTwist background-job worker")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="worker thread count (default: CROPTWIST_JOB_WORKERS)",
    )
    parser.add_argument(
        "--idle-exit-seconds",
        type=int,
        default=0,
        help="exit after N seconds with an empty queue (0 = run forever)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("geospatial worker starting")

    # Import side effects: settings, DB engine, observability.
    from app.core.config import settings
    from app.core import jobs
    from app.core.database import SessionLocal  # noqa: F401 — engine warm-up
    from app.db.models import BackgroundJob
    from sqlalchemy import func as sqlfunc, select

    if args.workers is not None and args.workers != settings.job_workers:
        settings.job_workers = args.workers

    # Register replayable kinds BEFORE recovery so orphans can re-execute.
    # The 'ingestion' kind self-registers lazily on first submit; raster
    # processing and report generation register eagerly here so recovered
    # rows replay (P07: report generation is worker-deployable too — long
    # PDF/XLSX renders never share the API's request budget).
    from app.data_platform.processing.service import (
        PROCESSING_JOB_KIND,
        replay_processing_job,
    )
    from app.reports.worker import REPORT_JOB_KIND, replay_report_job

    jobs.register_kind(PROCESSING_JOB_KIND, replay_processing_job)
    jobs.register_kind(REPORT_JOB_KIND, replay_report_job)

    started = jobs.start_workers()
    if started == 0:
        logger.error(
            "no workers started: CROPTWIST_JOB_WORKERS<=0; set a positive count"
        )
        return 2
    logger.info("worker pool running: %d threads", started)

    stop = threading.Event()

    def _handle(sig: int, _frame: object) -> None:
        logger.info("signal %s received: draining current job", sig)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    # Idle-exit watchdog (used by smoke checks; 0 disables it).
    import time

    deadline = time.monotonic() + args.idle_exit_seconds if args.idle_exit_seconds else None
    while not stop.is_set():
        time.sleep(0.5)
        if deadline is not None:
            with SessionLocal() as db:
                pending = db.scalar(
                    select(sqlfunc.count())
                    .select_from(BackgroundJob)
                    .where(BackgroundJob.status == "queued")
                )
            if pending == 0 and time.monotonic() > deadline:
                logger.info("idle exit reached")
                break

    jobs.shutdown_workers()
    logger.info("worker pool drained; bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())

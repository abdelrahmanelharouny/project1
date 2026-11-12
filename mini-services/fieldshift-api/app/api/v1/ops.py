"""Operational health endpoint (P3 W8 §8.3 — observability).

One authenticated surface answering "is the stack healthy and is work
flowing?" WITHOUT exposing sensitive internals:

- database connectivity + latency + PostGIS
- maintenance scheduler: enabled/running + last-run outcome per task
- background job pool: queued/running depth + 24h failure count
- report queue depth, webhook delivery backlog (pending/retrying/dead)
- configured billing provider name + mode (sandbox vs live) — never keys

Access policy: any AUTHENTICATED user. Rationale: every registered user
owns at least a personal organization (so an org-role gate is vacuous
here), and the payload is aggregate-only infrastructure health with zero
tenant-scoped data — no emails, no org ids, no tokens, no secrets
(P3 §12 red line: never log or expose credentials).
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.db.models import BackgroundJob
from app.db.models_p3 import ReportJob, WebhookDelivery
from app.domains.identity.service import Principal, get_principal

router = APIRouter(prefix="/ops", tags=["ops"])


def _db_health(db: Session) -> dict[str, Any]:
    started = time.perf_counter()
    db.execute(text("SELECT 1"))
    latency_ms = int((time.perf_counter() - started) * 1000)
    postgis = db.scalar(text("SELECT PostGIS_Lib_Version()"))
    return {"connected": True, "latency_ms": latency_ms, "postgis_version": postgis}


def _job_depths(db: Session) -> dict[str, Any]:
    day_ago = datetime.now(UTC) - timedelta(hours=24)
    queued = int(
        db.scalar(
            select(func.count()).select_from(BackgroundJob).where(BackgroundJob.status == "queued")
        )
        or 0
    )
    running = int(
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.status == "running")
        )
        or 0
    )
    failed_24h = int(
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.status == "failed", BackgroundJob.created_at >= day_ago)
        )
        or 0
    )
    return {"queued": queued, "running": running, "failed_24h": failed_24h}


def _report_depth(db: Session) -> dict[str, Any]:
    queued = int(
        db.scalar(
            select(func.count()).select_from(ReportJob).where(ReportJob.status == "queued")
        )
        or 0
    )
    running = int(
        db.scalar(
            select(func.count()).select_from(ReportJob).where(ReportJob.status == "running")
        )
        or 0
    )
    return {"queued": queued, "running": running}


def _webhook_backlog(db: Session) -> dict[str, Any]:
    day_ago = datetime.now(UTC) - timedelta(hours=24)
    pending = int(
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.status.in_(("pending", "retrying")))
        )
        or 0
    )
    failed_24h = int(
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.status == "failed", WebhookDelivery.created_at >= day_ago)
        )
        or 0
    )
    dead = int(
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.status == "dead")
        )
        or 0
    )
    return {"pending_or_retrying": pending, "failed_24h": failed_24h, "dead_letter": dead}


def _billing_surface() -> dict[str, Any]:
    from app.billing.provider import get_provider

    provider = get_provider(settings.billing_provider)
    # Name + mode only. Never credentials, never webhook signing secrets.
    return {"provider": provider.name, "mode": provider.mode}


def ops_health(db: Session) -> dict[str, Any]:
    from app.core import scheduler as maintenance_scheduler

    database = _db_health(db)
    jobs = _job_depths(db)
    reports = _report_depth(db)
    webhooks = _webhook_backlog(db)
    degraded = (
        (not database.get("connected"))
        or jobs["failed_24h"] > 0
        or webhooks["dead_letter"] > 0
    )
    return {
        "status": "degraded" if degraded else "ok",
        "time": datetime.now(UTC).isoformat(),
        "environment": settings.environment,
        "database": database,
        "scheduler": maintenance_scheduler.scheduler_status(),
        "background_jobs": jobs,
        "report_queue": reports,
        "webhook_deliveries": webhooks,
        "billing": _billing_surface(),
    }


@router.get("/health")
def operational_health(
    _principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ops_health(db)

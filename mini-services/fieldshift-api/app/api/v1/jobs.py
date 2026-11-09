"""Unified background-job status API (async jobs P0-3).

``GET /jobs/background``        — list jobs visible to the principal
``GET /jobs/background/{id}``   — one job (progress, stage, error, result)

Visibility rules (tenant isolation, same policy as the rest of the API):
- the principal's own jobs (``created_by``), always;
- jobs that reference a domain row the principal can read — today only
  ``ref_kind == "ingestion"``, resolved through the referenced
  IngestionJob's field via ``get_field_for_principal``.

Domain rows keep their own state (e.g. ``ingestion_jobs`` with
records_received / error_summary); the BackgroundJob row adds the queue-level
lifecycle and progress. Clients polling the ingestion status URL
(``GET /jobs/{job_id}``, unchanged) get the domain view; these endpoints add
the unified queue view for all kinds.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound
from app.db.models import BackgroundJob, IngestionJob
from app.domains.identity.service import get_field_for_principal, get_principal

router = APIRouter(tags=["jobs"])

_TERMINAL = ("succeeded", "failed", "cancelled")


def _payload(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "ref_kind": job.ref_kind,
        "ref_id": str(job.ref_id) if job.ref_id else None,
        "label": job.label,
        "result": job.result,
        "error": job.error,
        "request_id": job.request_id,
        "created_by": str(job.created_by) if job.created_by else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat(),
        "terminal": job.status in _TERMINAL,
    }


def _visible(db: Session, principal: Any, job: BackgroundJob) -> bool:
    """True when the principal may see this job. Never raises: a foreign job
    is indistinguishable from an unknown one (404 — no existence leak)."""
    if job.created_by is not None and job.created_by == principal.id:
        return True
    if job.ref_kind == "ingestion" and job.ref_id is not None:
        ingestion = db.get(IngestionJob, job.ref_id)
        if ingestion is not None:
            try:
                get_field_for_principal(db, principal, ingestion.field_id)
                return True
            except Exception:
                return False
    return False


@router.get("/jobs/background")
def list_background_jobs(
    kind: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Most recent background jobs visible to the principal (newest first)."""
    query = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit * 3)
    if kind:
        query = query.where(BackgroundJob.kind == kind)
    if status:
        query = query.where(BackgroundJob.status == status)
    rows = db.scalars(query).all()
    visible = [job for job in rows if _visible(db, principal, job)][:limit]
    return {
        "jobs": [_payload(job) for job in visible],
        "count": len(visible),
    }


@router.get("/jobs/background/{job_id}")
def get_background_job(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """One background job by queue id — or by DOMAIN reference id.

    Domain-scoped flows keep returning the domain row's own id
    (e.g. ``POST /data-jobs`` → ``job_id`` = IngestionJob.id, unchanged
    contract), so the unified view resolves a job whose ``ref_id`` matches
    the caller's id when no queue row has that primary key. Tenant
    visibility applies to the resolved row either way.
    """
    job = db.get(BackgroundJob, job_id)
    if job is None:
        job = db.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.ref_id == job_id)
            .order_by(BackgroundJob.created_at.desc())
            .limit(1)
        )
    if job is None or not _visible(db, principal, job):
        raise NotFound("Background job not found.")
    return _payload(job)

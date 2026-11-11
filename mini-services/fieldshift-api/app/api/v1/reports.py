"""Reports & exports endpoints (P3 W5).

Auth follows the platform pattern: ``get_principal`` resolves the caller,
role gates live INSIDE the service layer (viewer+ to read/scope, manager+
to delete or reschedule). Router registration is handled by the integrator
in ``app/api/v1/router.py`` — this module declares the router only.

Inline execution: POST /reports accepts ``sync=true`` to render immediately
for the small formats (csv/xlsx) — pdf always enqueues (rendering cost is
unbounded with row count). POST /reports/{id}/regenerate re-renders inline
regardless of format (regeneration is an explicit, user-initiated action).
"""

import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ValidationFailed
from app.domains.identity.service import get_principal
from app.reports import contracts, service

router = APIRouter(prefix="/reports", tags=["reports"])

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}


class ReportCreate(BaseModel):
    report_type: str = Field(min_length=1, max_length=60)
    output_format: str = Field(min_length=3, max_length=10, alias="format")
    locale: str = Field(default="en", max_length=10)
    farm_id: uuid.UUID | None = None
    field_id: uuid.UUID | None = None
    date_from: Any = None  # ISO date string; validated in the service
    date_to: Any = None
    title: str | None = Field(default=None, max_length=300)
    sync: bool = Field(
        default=False,
        description="Execute inline immediately (csv/xlsx only; pdf always queues).",
    )

    model_config = {"populate_by_name": True}


class ReportSchedule(BaseModel):
    interval_days: int | None = Field(
        default=None,
        description="Recurrence interval in days; null clears the schedule.",
    )


def _parse_date(value: Any, field_name: str) -> Any:
    from datetime import date as date_cls

    if value is None or isinstance(value, date_cls):
        return value
    if isinstance(value, str):
        try:
            return date_cls.fromisoformat(value)
        except ValueError as exc:
            raise ValidationFailed(
                f"{field_name} must be an ISO date (YYYY-MM-DD).",
                details=[{"field": field_name, "reason": str(value)}],
            ) from exc
    raise ValidationFailed(
        f"{field_name} must be an ISO date (YYYY-MM-DD).",
        details=[{"field": field_name, "reason": str(value)}],
    )


@router.post("", status_code=201)
def create_report(
    payload: ReportCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import date as date_cls

    sync = bool(payload.sync)
    if sync and payload.output_format not in ("csv", "xlsx"):
        raise ValidationFailed(
            "sync=true is only supported for csv and xlsx; pdf is queued.",
            details=[{"field": "sync", "reason": payload.output_format}],
        )
    job = service.create_report_job(
        db,
        principal,
        report_type=payload.report_type,
        output_format=payload.output_format,
        locale=payload.locale,
        farm_id=payload.farm_id,
        field_id=payload.field_id,
        date_from=_parse_date(payload.date_from, "date_from"),
        date_to=_parse_date(payload.date_to, "date_to"),
        title=payload.title,
    )
    if sync:
        success, _error = service.execute_report_job(db, job.id)
        if not success:
            # The job row carries the failure; surface it honestly as 201
            # with status=failed so the client can inspect job.error.
            db.refresh(job)
    body = service.job_payload(job)
    body["_links"] = {
        "self": f"/api/v1/reports/{job.id}",
        "download": f"/api/v1/reports/{job.id}/download",
        "status": f"/api/v1/reports/{job.id}/status",
    }
    return body


@router.get("")
def list_reports(
    status: str | None = None,
    report_type: str | None = None,
    farm_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = service.list_report_jobs(
        db,
        principal,
        status=status,
        report_type=report_type,
        farm_id=farm_id,
        limit=limit,
        offset=offset,
    )
    return {"items": [service.job_payload(row) for row in rows], "total": total}


@router.get("/{job_id}")
def get_report(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    job = service.get_report_job(db, principal, job_id)
    return service.job_payload(job)


@router.get("/{job_id}/status")
def get_report_status(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    job = service.get_report_job(db, principal, job_id)
    return {
        "id": str(job.id),
        "status": job.status,
        "error": job.error,
        "file_size_bytes": job.file_size_bytes,
        "retention_until": job.retention_until.isoformat() if job.retention_until else None,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
    }


@router.get("/{job_id}/download")
def download_report(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    from pathlib import Path as fs_path

    job = service.get_report_job(db, principal, job_id)
    path = service.read_report_file(db, principal, job_id)
    ext = job.output_format
    media = _MEDIA_TYPES.get(ext, "application/octet-stream")
    filename = f"{job.report_type}_{job.date_to.isoformat()}.{ext}"
    disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        _file_iterator(path),
        media_type=media,
        headers={"Content-Disposition": disposition},
    )


def _file_iterator(path: Path, chunk_size: int = 64 * 1024):  # noqa: ANN202
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            yield chunk


@router.delete("/{job_id}")
def delete_report(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_report_job(db, principal, job_id)
    return {"deleted": True, "id": str(job_id)}


@router.post("/{job_id}/regenerate")
def regenerate_report(
    job_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Re-render an existing job inline (viewer+; execution errors land on
    the job row as status=failed + error, never raised raw)."""
    service.get_report_job(db, principal, job_id)  # tenant + role gate
    success, _error = service.execute_report_job(db, job_id)
    job = service.get_report_job(db, principal, job_id)
    body = service.job_payload(job)
    body["rendered"] = success
    return body


@router.post("/{job_id}/schedule")
def schedule_report(
    job_id: uuid.UUID,
    payload: ReportSchedule,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    job = service.set_report_schedule(
        db, principal, job_id, interval_days=payload.interval_days
    )
    return service.job_payload(job)


__all__ = ["router", "contracts"]

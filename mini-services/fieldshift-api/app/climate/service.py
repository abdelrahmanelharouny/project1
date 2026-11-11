"""Forecast ingestion, freshness and retrieval service (P2.B).

Writes ForecastEvidence into `weather_forecasts` (immutable, idempotent by
natural key) and reads it back for the UI with freshness verdicts. Forecast
rows are NEVER merged into `observations` — the historical record stays
pure (P2.B core honesty rule).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate.contracts import ForecastEvidence, ForecastFreshness
from app.core.config import settings
from app.db.models_p2 import WeatherForecast

logger = logging.getLogger("croptwist.climate.service")

FORECAST_INGEST_VERSION = "forecast-ingest-1.0.0"


def persist_forecast_evidence(
    db: Session,
    field_id: uuid.UUID,
    evidence: list[ForecastEvidence],
    *,
    ingestion_job_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Insert forecast rows idempotently (natural-key dedupe).

    Existing identical (field, provider, variable, issued, valid, horizon)
    rows are left untouched — a re-ingest of the same response is a no-op.
    """
    inserted = 0
    skipped = 0
    for item in evidence:
        exists = db.scalar(
            select(WeatherForecast.id).where(
                WeatherForecast.field_id == field_id,
                WeatherForecast.provider_code == item.provider_code,
                WeatherForecast.variable_code == item.variable_code,
                WeatherForecast.issued_at == item.issued_at,
                WeatherForecast.valid_time == item.valid_time,
                WeatherForecast.horizon_hours == item.horizon_hours,
            )
        )
        if exists is not None:
            skipped += 1
            continue
        row = WeatherForecast(
            field_id=field_id,
            ingestion_job_id=ingestion_job_id,
            retrieved_at=datetime.now(UTC),
            **item.to_row(),
        )
        db.add(row)
        inserted += 1
    db.flush()
    return {"inserted": inserted, "skipped_existing": skipped}


def latest_issue_time(
    db: Session, field_id: uuid.UUID, *, provider_code: str | None = None
) -> datetime | None:
    query = select(WeatherForecast.issued_at).where(WeatherForecast.field_id == field_id)
    if provider_code:
        query = query.where(WeatherForecast.provider_code == provider_code)
    return db.scalar(query.order_by(WeatherForecast.issued_at.desc()).limit(1))


def forecast_freshness(
    db: Session, field_id: uuid.UUID, variable_code: str
) -> ForecastFreshness:
    """Freshness verdict: age of the latest issue for a variable."""
    latest = db.scalar(
        select(WeatherForecast)
        .where(
            WeatherForecast.field_id == field_id,
            WeatherForecast.variable_code == variable_code,
        )
        .order_by(WeatherForecast.issued_at.desc())
        .limit(1)
    )
    max_age = settings.forecast_freshness_max_age_hours
    now = datetime.now(UTC)
    if latest is None:
        return ForecastFreshness(
            variable_code=variable_code,
            latest_issued_at=None,
            age_hours=None,
            max_age_hours=max_age,
            fresh=False,
            detail="No forecast ingested for this variable.",
        )
    age = (now - latest.issued_at).total_seconds() / 3600.0
    fresh = age <= max_age
    detail = (
        f"Latest issue {latest.issued_at.isoformat()} is {age:.1f} h old "
        f"(limit {max_age:.0f} h): {'fresh' if fresh else 'STALE'}."
    )
    return ForecastFreshness(
        variable_code=variable_code,
        latest_issued_at=latest.issued_at,
        age_hours=round(age, 2),
        max_age_hours=max_age,
        fresh=fresh,
        detail=detail,
    )


def forecasts_in_window(
    db: Session,
    field_id: uuid.UUID,
    *,
    variable_code: str,
    start: datetime,
    end: datetime,
    latest_issue_only: bool = True,
) -> list[WeatherForecast]:
    """Forecast rows valid within [start, end].

    `latest_issue_only=True` returns only rows from the newest issue (the
    current forecast), never a blend of issues; older issues remain queryable
    for verification.
    """
    query = (
        select(WeatherForecast)
        .where(
            WeatherForecast.field_id == field_id,
            WeatherForecast.variable_code == variable_code,
            WeatherForecast.valid_time >= start,
            WeatherForecast.valid_time <= end,
            WeatherForecast.value.isnot(None),
        )
        .order_by(WeatherForecast.valid_time.asc())
    )
    if latest_issue_only:
        latest = latest_issue_time(db, field_id)
        if latest is None:
            return []
        query = query.where(WeatherForecast.issued_at == latest)
    return list(db.scalars(query))


def horizon_bucket(horizon_hours: int) -> str:
    """Documented verification buckets (§4.E)."""
    if horizon_hours <= 24:
        return "0-24h"
    if horizon_hours <= 72:
        return "24-72h"
    if horizon_hours <= 168:
        return "72-168h"
    return "168h+"


def purge_expired_forecasts(db: Session, *, keep_days: int = 180) -> int:
    """Retention policy: forecast issues older than `keep_days` are deleted.

    Only FORECAST rows are subject to retention (they are reproducible from
    the provider archive and would otherwise grow unbounded); observations
    are never touched.
    """
    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    result = db.execute(
        delete(WeatherForecast).where(
            WeatherForecast.issued_at < cutoff,
            WeatherForecast.is_synthetic.is_(False),
        )
    )
    return int(result.rowcount or 0)

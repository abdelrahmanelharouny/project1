"""Analytics endpoints (P3 W6.1-6.3): executive dashboard, farm performance,
commercial metrics, benchmarks.

Wraps `app/analytics/service.py` — every metric is returned EXACTLY as the
service computes it, including `provenance` markers
(observed / model_derived / simulated / missing) and unit fields. No metric
is invented at the API layer: financial figures exist only from
user-supplied assumptions, and unavailable metrics report `missing` with an
explanation.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics import service as analytics_service
from app.core.database import get_db
from app.core.errors import Forbidden, ValidationFailed
from app.domains.identity.service import get_farm_for_principal, get_principal

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _resolve_org_id(principal: Any, organization_id: uuid.UUID | None) -> uuid.UUID:
    if organization_id is not None:
        return organization_id  # the service enforces membership
    active = [m for m in principal.memberships if m.status == "active"]
    if not active:
        raise Forbidden("You do not belong to an active organization.")
    active.sort(key=lambda m: (m.created_at or datetime.now(UTC), m.organization_id))
    return active[0].organization_id


def _reject_unsupported(
    field_id: uuid.UUID | None,
    crop: str | None,
    date_from: date | None,
    date_to: date | None,
) -> None:
    """The dashboard service currently supports farm_id/season filters only.
    Declared-but-unsupported filters are refused loudly instead of being
    silently ignored (no fabricated narrowing of the result set)."""
    provided = []
    if field_id is not None:
        provided.append("field_id")
    if crop is not None:
        provided.append("crop")
    if date_from is not None:
        provided.append("date_from")
    if date_to is not None:
        provided.append("date_to")
    if provided:
        raise ValidationFailed(
            "Filter(s) not supported by this endpoint yet: "
            + ", ".join(provided)
            + " (supported filters: organization_id, farm_id, season).",
            details=[{"field": name} for name in provided],
        )


@router.get("/executive-dashboard")
def executive_dashboard(
    organization_id: uuid.UUID | None = None,
    farm_id: uuid.UUID | None = None,
    season: str | None = None,
    field_id: uuid.UUID | None = None,
    crop: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Organization-level executive dashboard (farm/field counts, crop
    distribution, recommendations summary, adoption, data freshness)."""
    _reject_unsupported(field_id, crop, date_from, date_to)
    org_id = _resolve_org_id(principal, organization_id)
    return analytics_service.executive_dashboard(
        db,
        principal,
        organization_id=org_id,
        farm_id=farm_id,
        season=season,
    )


@router.get("/farm-performance/{farm_id}")
def farm_performance(
    farm_id: uuid.UUID,
    date_from: date = Query(...),
    date_to: date = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-farm analytics over a period with per-field comparison rows."""
    farm = get_farm_for_principal(db, principal, farm_id)  # tenant scoping
    return analytics_service.farm_performance(
        db,
        principal,
        organization_id=farm.organization_id,
        farm_id=farm.id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/commercial-metrics")
def commercial_metrics(
    farm_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    water_price_per_m3: float | None = None,
    currency: str = "USD",
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Financial metrics ONLY where defensible: water cost from a
    USER-SUPPLIED price (model_derived, assumptions echoed); cost per
    hectare / yield / profit are reported as `missing` — never fabricated."""
    farm = get_farm_for_principal(db, principal, farm_id)  # tenant scoping
    return analytics_service.commercial_metrics(
        db,
        principal,
        organization_id=farm.organization_id,
        farm_id=farm.id,
        date_from=date_from,
        date_to=date_to,
        water_price_per_m3=water_price_per_m3,
        currency=currency,
    )


@router.get("/benchmarks")
def benchmarks(
    scope: str = Query(..., pattern="^(farm|field)$"),
    date_from: date = Query(...),
    date_to: date = Query(...),
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Farm-vs-farm / field-vs-field comparison INSIDE the organization only.
    Cross-organization anonymized aggregates are not implemented — the
    service reports them with provenance `missing`."""
    org_id = _resolve_org_id(principal, organization_id)
    return analytics_service.benchmark(
        db,
        principal,
        organization_id=org_id,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )

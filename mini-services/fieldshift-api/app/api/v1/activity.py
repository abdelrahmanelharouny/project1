"""Organization activity timeline endpoint (P3 W3/W9): append-only audit
trail of tenant events.

Wraps `app/activity/service.py`. `list_events` performs no authorization of
its own — the route REQUIRES active membership in the organization before
reading. The event log is append-only (no update/delete routes by design).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.activity import service as activity_service
from app.core.database import get_db
from app.domains.identity.service import get_principal

router = APIRouter(tags=["activity"])


@router.get("/orgs/{org_id}/activity")
def list_org_activity(
    org_id: uuid.UUID,
    farm_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Tenant-scoped activity timeline, newest first (pagination via
    limit/offset; optional farm_id / event_type filters)."""
    # Membership gate: the service list is org-scoped but unauthenticated
    # callers and non-members must never see the timeline.
    principal.require_member_of(org_id)
    rows, total = activity_service.list_events(
        db,
        organization_id=org_id,
        farm_id=farm_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [activity_service.event_payload(e) for e in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

"""Activity timeline: append-only, tenant-scoped, auditable (P3 §5.4).

Every commercially meaningful mutation (farm created, member invited,
report generated, plan changed, API key rotated, ...) appends one row here.
Records are never updated or deleted by application code — the timeline is
the audit surface. Listing is always organization-scoped; a farm filter is
an additional scope narrowing, never a way to escape the org scope.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models_p3 import ActivityEvent

# Event types emitted by P3 services (open set — domain modules may extend).
EVENT_FARM_CREATED = "farm.created"
EVENT_FARM_UPDATED = "farm.updated"
EVENT_FIELD_ADDED = "field.added"
EVENT_MEMBER_INVITED = "member.invited"
EVENT_MEMBER_JOINED = "member.joined"
EVENT_MEMBER_REMOVED = "member.removed"
EVENT_MEMBER_ROLE_CHANGED = "member.role_changed"
EVENT_OWNERSHIP_TRANSFERRED = "member.ownership_transferred"
EVENT_RECOMMENDATION_GENERATED = "recommendation.generated"
EVENT_REPORT_CREATED = "report.created"
EVENT_SETTING_CHANGED = "setting.changed"
EVENT_PLAN_CHANGED = "billing.plan_changed"
EVENT_SUBSCRIPTION_CHANGED = "billing.subscription_changed"
EVENT_API_KEY_CREATED = "developer.api_key_created"
EVENT_API_KEY_REVOKED = "developer.api_key_revoked"
EVENT_WEBHOOK_CREATED = "developer.webhook_created"
EVENT_CROP_CYCLE_UPDATED = "crop_cycle.updated"


def record_event(
    db: Session,
    *,
    organization_id: uuid.UUID,
    event_type: str,
    summary: str,
    farm_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_kind: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Append one activity event. Caller owns the surrounding transaction."""
    event = ActivityEvent(
        organization_id=organization_id,
        farm_id=farm_id,
        actor_user_id=actor_user_id,
        event_type=event_type[:80],
        entity_kind=entity_kind[:60] if entity_kind else None,
        entity_id=entity_id[:64] if entity_id else None,
        summary=summary[:500],
        details=details or {},
    )
    db.add(event)
    return event


def list_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    farm_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ActivityEvent], int]:
    """Tenant-scoped timeline, newest first. Hard limits prevent unbounded
    queries (P3 §15)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conditions = [ActivityEvent.organization_id == organization_id]
    if farm_id is not None:
        conditions.append(ActivityEvent.farm_id == farm_id)
    if event_type:
        conditions.append(ActivityEvent.event_type == event_type)
    total = db.scalar(
        select(func.count()).select_from(ActivityEvent).where(*conditions)
    ) or 0
    rows = list(
        db.scalars(
            select(ActivityEvent)
            .where(*conditions)
            .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, int(total)


def prune_older_than(db: Session, *, before: datetime, organization_id: uuid.UUID) -> int:
    """Retention helper (enterprise configurable retention, P3 §9.4)."""
    result = db.execute(
        sa_delete(ActivityEvent).where(
            ActivityEvent.organization_id == organization_id,
            ActivityEvent.created_at < before,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def event_payload(event: ActivityEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "entity_kind": event.entity_kind,
        "entity_id": event.entity_id,
        "summary": event.summary,
        "details": event.details,
        "farm_id": str(event.farm_id) if event.farm_id else None,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "created_at": event.created_at.isoformat(),
    }

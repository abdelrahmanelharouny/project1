"""Unified in-app notification center (P3 §7.3).

Categories map 1:1 to the preference keys (agronomic_alert, data_freshness,
recommendation_update, report_ready, invitation, subscription, billing,
system). Dedupe is enforced at the DATABASE level via a partial unique index
on (organization_id, dedupe_key) — concurrent emitters cannot create
duplicates; the loser of the race is treated as "already notified".

Delivery honesty: in-app delivery is implemented. EMAIL is a provider
adapter seam only (see app/notifications/channels.py) — no code path claims
outbound email works without a configured provider.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models_p3 import Notification, NotificationPreference

CATEGORIES = (
    "agronomic_alert",
    "data_freshness",
    "recommendation_update",
    "report_ready",
    "invitation",
    "subscription",
    "billing",
    "system",
)

SEVERITIES = ("info", "advisory", "warning", "critical")

# Default expiry: read notifications vanish after 30d, unread after 90d.
READ_RETENTION = timedelta(days=30)
UNREAD_RETENTION = timedelta(days=90)

DEFAULT_EXPIRY_BY_CATEGORY: dict[str, timedelta] = {
    "data_freshness": timedelta(days=14),
    "agronomic_alert": timedelta(days=30),
    "report_ready": timedelta(days=30),
    "invitation": timedelta(days=14),
    "subscription": timedelta(days=90),
    "billing": timedelta(days=90),
    "recommendation_update": timedelta(days=30),
    "system": timedelta(days=90),
}


def _category_enabled(db: Session, user_id: uuid.UUID, category: str) -> bool:
    pref = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
    )
    if pref is None:
        return True  # default: in-app on (see migration default)
    return bool(pref.in_app_enabled)


def create_notification(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    category: str,
    title: str,
    body: str = "",
    severity: str = "info",
    user_id: uuid.UUID | None = None,
    link_kind: str | None = None,
    link_id: str | None = None,
    dedupe_key: str | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> Notification | None:
    """Create one in-app notification.

    - Category preference gates creation for user-scoped notifications.
    - dedupe_key + org scope is unique at the DB level; an existing row
      wins (idempotent emission) and None is returned.
    """
    if category not in CATEGORIES:
        raise ValueError(f"Unknown notification category '{category}'.")
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown notification severity '{severity}'.")
    if user_id is not None and not _category_enabled(db, user_id, category):
        return None
    if expires_at is None:
        expires_at = datetime.now(UTC) + DEFAULT_EXPIRY_BY_CATEGORY.get(
            category, UNREAD_RETENTION
        )
    notification = Notification(
        organization_id=organization_id,
        user_id=user_id,
        category=category,
        severity=severity,
        title=title[:300],
        body=body,
        link_kind=link_kind[:60] if link_kind else None,
        link_id=link_id[:64] if link_id else None,
        dedupe_key=dedupe_key[:200] if dedupe_key else None,
        expires_at=expires_at,
    )
    db.add(notification)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent duplicate emission — the existing row wins.
        db.rollback()
        if dedupe_key is None or organization_id is None:
            return None
        return db.scalar(
            select(Notification).where(
                Notification.organization_id == organization_id,
                Notification.dedupe_key == dedupe_key,
            )
        )
    if commit:
        db.commit()
        db.refresh(notification)
    return notification


def list_notifications(
    db: Session,
    principal,
    *,
    organization_id: uuid.UUID,
    unread_only: bool = False,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    """Notifications visible to the principal in the org: org-scoped rows
    plus rows addressed to this user. Unread count included."""
    from app.core.errors import Forbidden

    principal.require_member_of(organization_id)
    now = datetime.now(UTC)
    conditions = [
        Notification.organization_id == organization_id,
        (Notification.expires_at.is_(None)) | (Notification.expires_at > now),
    ]
    scope = Notification.user_id.is_(None) | (Notification.user_id == principal.id)
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    if category:
        if category not in CATEGORIES:
            from app.core.errors import ValidationFailed

            raise ValidationFailed(f"Unknown notification category '{category}'.")
        conditions.append(Notification.category == category)
    base = select(Notification).where(*conditions, scope)
    total = int(
        db.scalar(select(func.count()).select_from(Notification).where(*conditions, scope)) or 0
    )
    unread = int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(*conditions, scope, Notification.read_at.is_(None))
        )
        or 0
    )
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = list(
        db.scalars(
            base.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total, unread


def mark_read(
    db: Session, principal, *, organization_id: uuid.UUID, notification_id: uuid.UUID, read: bool = True
) -> Notification:
    from app.core.errors import Forbidden, NotFound

    principal.require_member_of(organization_id)
    notification = db.get(Notification, notification_id)
    if notification is None or (
        notification.organization_id != organization_id
        or (notification.user_id is not None and notification.user_id != principal.id)
    ):
        raise NotFound("Notification not found.")
    notification.read_at = datetime.now(UTC) if read else None
    db.commit()
    db.refresh(notification)
    return notification


def mark_all_read(db: Session, principal, *, organization_id: uuid.UUID) -> int:
    from sqlalchemy import update as sa_update

    principal.require_member_of(organization_id)
    now = datetime.now(UTC)
    result = db.execute(
        sa_update(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.read_at.is_(None),
            (Notification.user_id.is_(None)) | (Notification.user_id == principal.id),
        )
        .values(read_at=now)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def set_preference(
    db: Session,
    user_id: uuid.UUID,
    *,
    category: str,
    in_app_enabled: bool | None = None,
    email_enabled: bool | None = None,
) -> NotificationPreference:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown notification category '{category}'.")
    return _upsert_pref(db, user_id, category=category, in_app=in_app_enabled, email=email_enabled)


def _upsert_pref(
    db: Session,
    user_id: uuid.UUID,
    *,
    category: str,
    in_app: bool | None,
    email: bool | None,
) -> NotificationPreference:
    row = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
    )
    if row is None:
        row = NotificationPreference(user_id=user_id, category=category)
        db.add(row)
    if in_app is not None:
        row.in_app_enabled = in_app
    if email is not None:
        row.email_enabled = email
    db.commit()
    db.refresh(row)
    return row


def get_preferences(db: Session, user_id: uuid.UUID) -> list[NotificationPreference]:
    rows = list(
        db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).all()
    )
    existing = {r.category: r for r in rows}
    out = []
    for category in CATEGORIES:
        if category in existing:
            out.append(existing[category])
        else:
            out.append(
                NotificationPreference(user_id=user_id, category=category,
                                       in_app_enabled=True, email_enabled=False)
            )
    return out


def purge_expired(db: Session) -> int:
    """Retention sweep: delete notifications past expiry (scheduler job)."""
    from sqlalchemy import delete as sa_delete

    now = datetime.now(UTC)
    result = db.execute(sa_delete(Notification).where(Notification.expires_at.is_not(None), Notification.expires_at < now))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def notification_payload(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "category": n.category,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "link_kind": n.link_kind,
        "link_id": n.link_id,
        "read": n.read_at is not None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "expires_at": n.expires_at.isoformat() if n.expires_at else None,
        "created_at": n.created_at.isoformat(),
    }

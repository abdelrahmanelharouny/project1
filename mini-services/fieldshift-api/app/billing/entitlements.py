"""Central entitlement engine (P3 §4.2).

ONE system for every restricted capability: plans define entitlement rows
(configurable data), organizations resolve them through their live
subscription, and every enforcement point asks THIS module — never local
constants, never frontend-only hiding.

Value semantics:
- value_bool entitlements: flag on/off.
- value_int entitlements: a count limit; -1 means UNLIMITED.

Usage accounting: ``increment_usage``/``check_quota`` read/write
usage_counters rows keyed (organization, key, period_start) where the
period is the subscription's current billing period (monthly → calendar
month; yearly → calendar year).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, PaymentRequired
from app.db.models_p3 import Plan, PlanEntitlement, Subscription, UsageCounter

# Entitlement keys (stable contract — frontend + backend agree on names).
KEY_MAX_FARMS = "max_farms"
KEY_MAX_FIELDS = "max_fields"
KEY_MAX_ORG_MEMBERS = "max_org_members"
KEY_HISTORY_RETENTION_YEARS = "history_retention_years"
KEY_ADVANCED_ANALYSIS = "advanced_analysis"
KEY_SCENARIO_RUNS_PER_MONTH = "scenario_runs_per_month"
KEY_SATELLITE_ACCESS = "satellite_access"
KEY_REPORTS_PER_MONTH = "reports_per_month"
KEY_API_ENABLED = "api_enabled"
KEY_API_RATE_LIMIT_PER_MINUTE = "api_rate_limit_per_minute"
KEY_AI_MESSAGES_PER_DAY = "ai_messages_per_day"
KEY_EXPORTS_ENABLED = "exports_enabled"
KEY_ANALYTICS_ACCESS = "analytics_access"

ALL_INT_KEYS = (
    KEY_MAX_FARMS,
    KEY_MAX_FIELDS,
    KEY_MAX_ORG_MEMBERS,
    KEY_HISTORY_RETENTION_YEARS,
    KEY_SCENARIO_RUNS_PER_MONTH,
    KEY_REPORTS_PER_MONTH,
    KEY_API_RATE_LIMIT_PER_MINUTE,
    KEY_AI_MESSAGES_PER_DAY,
)
ALL_BOOL_KEYS = (
    KEY_ADVANCED_ANALYSIS,
    KEY_SATELLITE_ACCESS,
    KEY_API_ENABLED,
    KEY_EXPORTS_ENABLED,
    KEY_ANALYTICS_ACCESS,
)

UNLIMITED = -1

def get_live_subscription(db: Session, organization_id: uuid.UUID) -> Subscription | None:
    """The organization's live subscription, or None (never a fabricated one)."""
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(("trialing", "active", "past_due", "grace")),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )


def is_billing_active(subscription: Subscription | None) -> bool:
    """True when the organization may use paid capabilities right now."""
    if subscription is None:
        return False
    if subscription.status == "trialing":
        if subscription.trial_ends_at is None:
            return True
        return subscription.trial_ends_at > datetime.now(UTC)
    if subscription.status == "active":
        return True
    if subscription.status in ("past_due", "grace"):
        if subscription.grace_ends_at is None:
            return True
        return subscription.grace_ends_at > datetime.now(UTC)
    return False


def resolve_entitlements(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """Effective entitlements for the organization.

    Returns {key: {"value": int|bool, "kind": "int"|"bool", "unlimited": bool,
    "plan_code": str|None}}. Without a live subscription the Free-plan floor
    applies IF a free plan exists in the catalog; otherwise only explicitly
    seeded rows apply. The response always names the source plan.
    """
    subscription = get_live_subscription(db, organization_id)
    plan: Plan | None = subscription.plan if subscription else None
    if plan is None:
        plan = db.scalar(select(Plan).where(Plan.code == "free", Plan.is_active.is_(True)))
    resolved: dict[str, Any] = {}
    if plan is None:
        # No catalog at all: deny-by-default for gated features.
        for key in ALL_BOOL_KEYS:
            resolved[key] = {"value": False, "kind": "bool", "unlimited": False}
        for key in ALL_INT_KEYS:
            resolved[key] = {"value": 0, "kind": "int", "unlimited": False}
        return resolved
    rows = list(db.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan.id)).all())
    for row in rows:
        if row.value_int is not None:
            resolved[row.key] = {
                "value": row.value_int,
                "kind": "int",
                "unlimited": row.value_int == UNLIMITED,
            }
        else:
            resolved[row.key] = {"value": bool(row.value_bool), "kind": "bool", "unlimited": False}
    # Fill any missing int/bool keys with deny-by-default so enforcement
    # never depends on catalog completeness.
    for key in ALL_BOOL_KEYS:
        resolved.setdefault(key, {"value": False, "kind": "bool", "unlimited": False})
    for key in ALL_INT_KEYS:
        resolved.setdefault(key, {"value": 0, "kind": "int", "unlimited": False})
    for entry in resolved.values():
        entry["plan_code"] = plan.code
    return resolved


def require_flag(db: Session, organization_id: uuid.UUID, key: str, *, expected: bool = True) -> None:
    """Deny unless the boolean entitlement is active (and billing allows)."""
    resolved = resolve_entitlements(db, organization_id)
    entry = resolved.get(key)
    if entry is None or entry["kind"] != "bool":
        raise Forbidden(f"Unknown entitlement '{key}'.")
    if expected and not entry["value"]:
        raise Forbidden("This capability is not part of your current plan.")
    if not expected and entry["value"]:
        raise Forbidden("This capability is excluded by your current plan.")


def limit_for(db: Session, organization_id: uuid.UUID, key: str) -> int:
    """The numeric limit for `key` (-1 = unlimited)."""
    resolved = resolve_entitlements(db, organization_id)
    entry = resolved.get(key)
    if entry is None or entry["kind"] != "int":
        raise Forbidden(f"Unknown entitlement '{key}'.")
    return int(entry["value"])


def _period_start(subscription: Subscription | None, now: datetime) -> date:
    if subscription is not None and subscription.billing_period == "yearly":
        return date(now.year, 1, 1)
    return date(now.year, now.month, 1)


def current_usage(db: Session, organization_id: uuid.UUID, key: str) -> int:
    subscription = get_live_subscription(db, organization_id)
    period = _period_start(subscription, datetime.now(UTC))
    row = db.scalar(
        select(UsageCounter).where(
            UsageCounter.organization_id == organization_id,
            UsageCounter.key == key,
            UsageCounter.period_start == period,
        )
    )
    return int(row.used_value) if row else 0


def increment_usage(db: Session, organization_id: uuid.UUID, key: str, *, amount: int = 1) -> int:
    """Add `amount` to the period counter and return the new value."""
    subscription = get_live_subscription(db, organization_id)
    now = datetime.now(UTC)
    period = _period_start(subscription, now)
    row = db.scalar(
        select(UsageCounter).where(
            UsageCounter.organization_id == organization_id,
            UsageCounter.key == key,
            UsageCounter.period_start == period,
        )
    )
    if row is None:
        row = UsageCounter(organization_id=organization_id, key=key, period_start=period, used_value=amount)
        db.add(row)
        db.flush()
        return amount
    row.used_value += amount
    db.flush()
    return int(row.used_value)


def check_quota(db: Session, organization_id: uuid.UUID, key: str) -> int:
    """Raise when the period quota is exhausted; return the limit."""
    limit = limit_for(db, organization_id, key)
    if limit == UNLIMITED:
        return limit
    used = current_usage(db, organization_id, key)
    if used >= limit:
        raise PaymentRequired(
            f"Plan limit reached for '{key}' ({used}/{limit} this period). Upgrade to continue."
        )
    return limit


def assert_within_limit(db: Session, organization_id: uuid.UUID, key: str, current_count: int) -> None:
    """Resource-count entitlement (farms/fields/members) enforcement."""
    limit = limit_for(db, organization_id, key)
    if limit == UNLIMITED:
        return
    if current_count >= limit:
        raise PaymentRequired(
            f"Plan limit reached for '{key}' ({current_count}/{limit}). Upgrade to add more."
        )


def require_active_billing(db: Session, organization_id: uuid.UUID, *, capability: str) -> Subscription:
    """Gate paid capabilities: live subscription + active billing window."""
    subscription = get_live_subscription(db, organization_id)
    if subscription is None:
        raise PaymentRequired(
            f"'{capability}' requires a subscription. Choose a plan to continue."
        )
    if not is_billing_active(subscription):
        raise PaymentRequired(
            "Your subscription is not active (expired or past due). Update billing to continue."
        )
    return subscription


def usage_snapshot(db: Session, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    """Usage meter data: every int entitlement vs. its current consumption."""
    resolved = resolve_entitlements(db, organization_id)
    out: list[dict[str, Any]] = []
    for key in ALL_INT_KEYS:
        entry = resolved[key]
        out.append(
            {
                "key": key,
                "limit": entry["value"],
                "unlimited": entry["unlimited"],
                "used": current_usage(db, organization_id, key),
                "plan_code": entry.get("plan_code"),
            }
        )
    return out


def resource_counts(db: Session, organization_id: uuid.UUID) -> dict[str, int]:
    """Current farm/field/member counts for count-based entitlements."""
    from sqlalchemy import func as sa_func
    from app.db.models import Farm, Field, Membership

    farms = int(
        db.scalar(
            select(sa_func.count()).select_from(Farm).where(Farm.organization_id == organization_id)
        )
        or 0
    )
    fields = int(
        db.scalar(
            select(sa_func.count())
            .select_from(Field)
            .join(Farm, Field.farm_id == Farm.id)
            .where(Farm.organization_id == organization_id)
        )
        or 0
    )
    members = int(
        db.scalar(
            select(sa_func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id, Membership.status == "active"
            )
        )
        or 0
    )
    return {"farms": farms, "fields": fields, "members": members}

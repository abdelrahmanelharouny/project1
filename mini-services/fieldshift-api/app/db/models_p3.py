"""P3 commercial SaaS platform models.

Additive schema layer for: subscription/billing/entitlements (W2), org
invitations + activity timeline (W3), notifications + reports (W5), public
API keys + outgoing webhooks (W6), onboarding + user preferences (W1/W7).

Design rules honored here (P3 §12):
- Every tenant-scoped table carries organization_id with an FK + index so
  tenant isolation is enforceable at the query layer.
- Idempotency: billing_events has a unique (provider, provider_event_id);
  webhook_deliveries has a unique (endpoint_id, event_id, attempt).
- No raw card data is ever stored — the provider layer keeps only opaque
  provider references.
- Money is stored as integer minor units (cents) + ISO currency code; no
  floats for money.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as text_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models import Base, Organization, TimestampMixin, User, _uuid


# ------------------------------------------------------------- W2: plans
class Plan(Base, TimestampMixin):
    """Commercial plan definition. Pricing/limits are DATA, not code."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    prices: Mapped[list["PlanPrice"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    entitlements: Mapped[list["PlanEntitlement"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("code", name="uq_plans_code"),)


class PlanPrice(Base):
    """Configurable price row. amount_cents NULL means 'contact sales'."""

    __tablename__ = "plan_prices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    billing_period: Mapped[str] = mapped_column(String(20), nullable=False)  # monthly|yearly
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    plan: Mapped[Plan] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("plan_id", "billing_period", "currency_code", name="uq_plan_price"),
        CheckConstraint("billing_period IN ('monthly','yearly')", name="ck_plan_price_period"),
        CheckConstraint("amount_cents IS NULL OR amount_cents >= 0", name="ck_plan_price_amount"),
    )


class PlanEntitlement(Base):
    """One entitlement limit per plan. value_int for counts, value_bool for flags."""

    __tablename__ = "plan_entitlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value_int: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="entitlements")

    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_plan_entitlement"),
        CheckConstraint(
            "(value_int IS NOT NULL)::int + (value_bool IS NOT NULL)::int = 1",
            name="ck_plan_entitlement_one_value",
        ),
    )


# ------------------------------------------------------ W2: subscriptions
class Subscription(Base, TimestampMixin):
    """Organization subscription. Exactly one LIVE row per organization."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="trialing")
    billing_period: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="sandbox")
    provider_customer_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_subscription_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[Plan] = relationship()
    organization: Mapped[Organization] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing','active','past_due','grace','canceled','expired')",
            name="ck_subscription_status",
        ),
        CheckConstraint("billing_period IN ('monthly','yearly')", name="ck_subscription_period"),
        # One live subscription per organization (partial unique index; the
        # terminal statuses canceled/expired are excluded).
        Index(
            "uq_subscription_live_per_org",
            organization_id,
            unique=True,
            postgresql_where=text_("status IN ('trialing','active','past_due','grace')"),
        ),
        Index("ix_subscriptions_org", organization_id),
    )


class SubscriptionEvent(Base):
    """Audit trail of every subscription state transition (P3 §4.4)."""

    __tablename__ = "subscription_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_subscription_events_sub", subscription_id),)


class Invoice(Base, TimestampMixin):
    """Invoice record (billing history). Amounts in minor units."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("number", name="uq_invoice_number"),
        CheckConstraint(
            "status IN ('draft','open','paid','void','uncollectible')", name="ck_invoice_status"
        ),
        CheckConstraint("amount_cents >= 0", name="ck_invoice_amount"),
        Index("ix_invoices_org", organization_id),
    )


class BillingEvent(Base):
    """Provider webhook event record: idempotency + audit (P3 §4.4)."""

    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
        CheckConstraint(
            "status IN ('received','processed','failed','duplicate')",
            name="ck_billing_event_status",
        ),
        Index("ix_billing_events_created", "created_at"),
    )


class UsageCounter(Base):
    """Metered usage per organization per period (quota enforcement input)."""

    __tablename__ = "usage_counters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    used_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "key", "period_start", name="uq_usage_counter"),
        Index("ix_usage_counters_org", organization_id),
    )


# --------------------------------------------- W3: invitations + activity
class Invitation(Base, TimestampMixin):
    """Pending organization membership invitation (single-use token)."""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship()

    __table_args__ = (
        Index("uq_invitations_token_hash", token_hash, unique=True),
        Index("ix_invitations_org_email", organization_id, "email"),
        CheckConstraint(
            "status IN ('pending','accepted','revoked','expired')", name="ck_invitation_status"
        ),
    )


class ActivityEvent(Base):
    """Tenant-scoped operational activity timeline (auditable, append-only)."""

    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    farm_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_activity_org_created", organization_id, text_("created_at DESC")),
        Index("ix_activity_farm", farm_id),
    )


# ------------------------------------------------------- W5: notifications
class Notification(Base):
    """In-app notification. Dedupe via partial-unique (org, dedupe_key)."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link_kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','advisory','warning','critical')", name="ck_notification_severity"
        ),
        Index(
            "uq_notification_dedupe",
            organization_id,
            "dedupe_key",
            unique=True,
            postgresql_where=text_("dedupe_key IS NOT NULL"),
        ),
        Index("ix_notifications_org_created", organization_id, text_("created_at DESC")),
        Index("ix_notifications_user", user_id),
    )


class NotificationPreference(Base):
    """Per-user, per-category channel toggles."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_pref"),
        CheckConstraint(
            "category IN ('agronomic_alert','data_freshness','recommendation_update',"
            "'report_ready','invitation','subscription','billing','system')",
            name="ck_notification_pref_category",
        ),
    )


# ----------------------------------------------------------- W5: reports
class ReportJob(Base, TimestampMixin):
    """Report generation job + library entry (async via background jobs)."""

    __tablename__ = "report_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    farm_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    report_type: Mapped[str] = mapped_column(String(60), nullable=False)
    output_format: Mapped[str] = mapped_column(String(10), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Retention: downloadable until this timestamp, then purge-eligible.
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Recurring schedule (P3 §7.4): NULL = one-off report.
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("output_format IN ('pdf','xlsx','csv')", name="ck_report_format"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','expired')",
            name="ck_report_status",
        ),
        CheckConstraint("locale IN ('en','ar')", name="ck_report_locale"),
        CheckConstraint("date_to >= date_from", name="ck_report_period"),
        Index("ix_report_jobs_org_created", organization_id, text_("created_at DESC")),
        Index("ix_report_jobs_due", "next_run_at"),
    )


# -------------------------------------------------------- W6: public API
class ApiKey(Base, TimestampMixin):
    """Scoped public API key. Only the SHA-256 hash is stored."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_api_keys_prefix", prefix, unique=True),
        Index("uq_api_keys_hash", key_hash, unique=True),
        CheckConstraint("status IN ('active','revoked')", name="ck_api_key_status"),
        CheckConstraint("rate_limit_per_minute > 0", name="ck_api_key_rate"),
    )


class ApiKeyUsage(Base):
    """Daily request counter per key (usage dashboard input)."""

    __tablename__ = "api_key_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("api_key_id", "day", name="uq_api_key_usage"),
    )


# -------------------------------------------------- W6: outgoing webhooks
class WebhookEndpoint(Base, TimestampMixin):
    """Registered outgoing webhook receiver."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Signing secret — returned once at creation, never again (like provider
    # signing secrets); rotation creates a new secret.
    secret: Mapped[str] = mapped_column(String(120), nullable=False)
    event_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="ck_webhook_endpoint_status"),
        Index("ix_webhook_endpoints_org", organization_id),
    )


class WebhookDelivery(Base):
    """One delivery attempt chain per (endpoint, event); retries with backoff."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_delivery_event"),
        CheckConstraint(
            "status IN ('pending','delivered','failed','dead')", name="ck_webhook_delivery_status"
        ),
        Index("ix_webhook_deliveries_due", "status", "next_retry_at"),
        Index("ix_webhook_deliveries_org_created", organization_id, text_("created_at DESC")),
    )


# ----------------------------------------------- W1/W7: onboarding + prefs
class OnboardingProgress(Base):
    """Resumable onboarding state machine per user."""

    __tablename__ = "onboarding_progress"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    steps: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    current_step: Mapped[str] = mapped_column(String(60), nullable=False, default="account")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_onboarding_user"),
        CheckConstraint("account_type IS NULL OR account_type IN ('individual','business','farm_org')",
                        name="ck_onboarding_account_type"),
    )


class UserPreference(Base):
    """Global product configuration per user (locale, units, currency...)."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    unit_system: Mapped[str] = mapped_column(String(20), nullable=False, default="metric")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    week_start: Mapped[str] = mapped_column(String(10), nullable=False, default="monday")
    agricultural_calendar: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notify_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("unit_system IN ('metric','imperial')", name="ck_user_pref_units"),
        CheckConstraint("locale IN ('en','ar')", name="ck_user_pref_locale"),
        CheckConstraint("week_start IN ('monday','sunday','saturday')", name="ck_user_pref_week"),
    )

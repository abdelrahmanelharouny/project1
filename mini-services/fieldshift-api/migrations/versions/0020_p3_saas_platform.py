"""P3 commercial SaaS platform: billing, teams, reports, notifications,
public API, webhooks, onboarding, preferences.

Additive-only migration (P3 §12):
- All new tables; no existing table is altered destructively.
- Two exceptions, both additive: ``users.is_platform_admin`` (new nullable-
  default column) and ``ck_membership_role`` widened to a SUPERSET of the
  old role codes (old codes stay valid; no data migration needed).
- Downgrade drops exactly what this migration created, in reverse order.

Revision ID: 0020_p3_saas_platform
Revises: 0019_p2_intelligence
"""

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020_p3_saas_platform"
down_revision = "0019_p2_intelligence"
branch_labels = None
depends_on = None

_WIDENED_ROLES = (
    "role_code IN ('owner','manager','agronomist','viewer',"
    "'org_admin','operator','analyst')"
)
_ORIGINAL_ROLES = "role_code IN ('owner','manager','agronomist','viewer')"


def upgrade() -> None:
    # -- additive columns on existing tables --------------------------------
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint("ck_membership_role", "memberships", _WIDENED_ROLES)

    # -- W2: plans / prices / entitlements ----------------------------------
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trial_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_plans_code"),
    )
    op.create_table(
        "plan_prices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_period", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("plan_id", "billing_period", "currency_code", name="uq_plan_price"),
        sa.CheckConstraint("billing_period IN ('monthly','yearly')", name="ck_plan_price_period"),
        sa.CheckConstraint("amount_cents IS NULL OR amount_cents >= 0", name="ck_plan_price_amount"),
    )
    op.create_table(
        "plan_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("plan_id", "key", name="uq_plan_entitlement"),
        sa.CheckConstraint(
            "(value_int IS NOT NULL)::int + (value_bool IS NOT NULL)::int = 1",
            name="ck_plan_entitlement_one_value",
        ),
    )

    # -- W2: subscriptions / events / invoices / billing events / usage -----
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="trialing"),
        sa.Column("billing_period", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("provider", sa.String(30), nullable=False, server_default="sandbox"),
        sa.Column("provider_customer_ref", sa.String(200), nullable=True),
        sa.Column("provider_subscription_ref", sa.String(200), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('trialing','active','past_due','grace','canceled','expired')",
            name="ck_subscription_status",
        ),
        sa.CheckConstraint("billing_period IN ('monthly','yearly')", name="ck_subscription_period"),
    )
    # One LIVE subscription per organization (partial unique index).
    op.create_index(
        "uq_subscription_live_per_org",
        "subscriptions",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('trialing','active','past_due','grace')"),
    )
    op.create_index("ix_subscriptions_org", "subscriptions", ["organization_id"])
    op.create_table(
        "subscription_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscription_events_sub", "subscription_events", ["subscription_id"])
    op.create_table(
        "invoices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("number", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("number", name="uq_invoice_number"),
        sa.CheckConstraint(
            "status IN ('draft','open','paid','void','uncollectible')", name="ck_invoice_status"
        ),
        sa.CheckConstraint("amount_cents >= 0", name="ck_invoice_amount"),
    )
    op.create_index("ix_invoices_org", "invoices", ["organization_id"])
    op.create_table(
        "billing_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
        sa.CheckConstraint(
            "status IN ('received','processed','failed','duplicate')",
            name="ck_billing_event_status",
        ),
    )
    op.create_index("ix_billing_events_created", "billing_events", ["created_at"])
    op.create_table(
        "usage_counters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("used_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "key", "period_start", name="uq_usage_counter"),
    )
    op.create_index("ix_usage_counters_org", "usage_counters", ["organization_id"])

    # -- W3: invitations + activity timeline --------------------------------
    op.create_table(
        "invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role_code", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("invited_by", UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_invitations_token_hash", "invitations", ["token_hash"], unique=True)
    op.create_index("ix_invitations_org_email", "invitations", ["organization_id", "email"])
    op.create_check_constraint(
        "ck_invitation_status",
        "invitations",
        "status IN ('pending','accepted','revoked','expired')",
    )
    op.create_table(
        "activity_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("farm_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("entity_kind", sa.String(60), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_activity_org_created", "activity_events", ["organization_id", sa.text("created_at DESC")]
    )
    op.create_index("ix_activity_farm", "activity_events", ["farm_id"])

    # -- W5: notifications ---------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link_kind", sa.String(60), nullable=True),
        sa.Column("link_id", sa.String(64), nullable=True),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('info','advisory','warning','critical')", name="ck_notification_severity"
        ),
    )
    op.create_index(
        "uq_notification_dedupe",
        "notifications",
        ["organization_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_org_created", "notifications", ["organization_id", sa.text("created_at DESC")]
    )
    op.create_index("ix_notifications_user", "notifications", ["user_id"])
    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("user_id", "category", name="uq_notification_pref"),
        sa.CheckConstraint(
            "category IN ('agronomic_alert','data_freshness','recommendation_update',"
            "'report_ready','invitation','subscription','billing','system')",
            name="ck_notification_pref_category",
        ),
    )

    # -- W5: report jobs ------------------------------------------------------
    op.create_table(
        "report_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("farm_id", UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), nullable=True),
        sa.Column("report_type", sa.String(60), nullable=False),
        sa.Column("output_format", sa.String(10), nullable=False),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("background_job_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("output_format IN ('pdf','xlsx','csv')", name="ck_report_format"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','expired')",
            name="ck_report_status",
        ),
        sa.CheckConstraint("locale IN ('en','ar')", name="ck_report_locale"),
        sa.CheckConstraint("date_to >= date_from", name="ck_report_period"),
    )
    op.create_index(
        "ix_report_jobs_org_created", "report_jobs", ["organization_id", sa.text("created_at DESC")]
    )
    op.create_index("ix_report_jobs_due", "report_jobs", ["next_run_at"])

    # -- W6: api keys ---------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_api_keys_prefix", "api_keys", ["prefix"], unique=True)
    op.create_index("uq_api_keys_hash", "api_keys", ["key_hash"], unique=True)
    op.create_check_constraint("ck_api_key_status", "api_keys", "status IN ('active','revoked')")
    op.create_check_constraint("ck_api_key_rate", "api_keys", "rate_limit_per_minute > 0")
    op.create_table(
        "api_key_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("api_key_id", "day", name="uq_api_key_usage"),
    )

    # -- W6: outgoing webhooks ------------------------------------------------
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("secret", sa.String(120), nullable=False),
        sa.Column("event_types", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_endpoints_org", "webhook_endpoints", ["organization_id"])
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint_id", UUID(as_uuid=True), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_delivery_event"),
        sa.CheckConstraint(
            "status IN ('pending','delivered','failed','dead')", name="ck_webhook_delivery_status"
        ),
    )
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_retry_at"])
    op.create_index(
        "ix_webhook_deliveries_org_created",
        "webhook_deliveries",
        ["organization_id", sa.text("created_at DESC")],
    )

    # -- W1/W7: onboarding + preferences --------------------------------------
    op.create_table(
        "onboarding_progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_type", sa.String(40), nullable=True),
        sa.Column("steps", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("current_step", sa.String(60), nullable=False, server_default="account"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_onboarding_user"),
        sa.CheckConstraint(
            "account_type IS NULL OR account_type IN ('individual','business','farm_org')",
            name="ck_onboarding_account_type",
        ),
    )
    op.create_table(
        "user_preferences",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("unit_system", sa.String(20), nullable=False, server_default="metric"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("week_start", sa.String(10), nullable=False, server_default="monday"),
        sa.Column("agricultural_calendar", sa.String(60), nullable=True),
        sa.Column("notify_in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("unit_system IN ('metric','imperial')", name="ck_user_pref_units"),
        sa.CheckConstraint("locale IN ('en','ar')", name="ck_user_pref_locale"),
        sa.CheckConstraint("week_start IN ('monday','sunday','saturday')", name="ck_user_pref_week"),
    )

    # -- default plan catalog (CONFIGURABLE DATA — editable at runtime via
    #    the platform-admin API; the sandbox amounts below are placeholder
    #    catalog values, never final commercial pricing).
    _seed_default_plans()


def _seed_default_plans() -> None:
    """Seed the default plan catalog. Plans/limits/prices are DATA: platform
    administrators reconfigure them via the plans admin API at any time;
    entitlement enforcement reads the current rows, never code constants."""
    now = datetime.now(UTC)
    plans = [
        # code, name, sort, trial_days, price_monthly_cents (None = contact sales)
        ("free", "Free", 0, 0, 0),
        ("starter", "Starter", 10, 14, 1900),
        ("professional", "Professional", 20, 14, 4900),
        ("business", "Business", 30, 14, 14900),
        ("enterprise", "Enterprise", 40, 0, None),
    ]
    # key: (free, starter, professional, business, enterprise); -1 = unlimited
    ent_int = {
        "max_farms": (1, 2, 10, 50, -1),
        "max_fields": (3, 10, 50, 250, -1),
        "max_org_members": (1, 3, 15, 100, -1),
        "history_retention_years": (1, 3, 10, 15, -1),
        "scenario_runs_per_month": (5, 25, 200, 1000, -1),
        "reports_per_month": (3, 15, 100, 500, -1),
        "api_rate_limit_per_minute": (0, 0, 60, 300, 1000),
        "ai_messages_per_day": (10, 60, 300, 2000, -1),
    }
    ent_bool = {
        "advanced_analysis": (False, False, True, True, True),
        "satellite_access": (False, True, True, True, True),
        "api_enabled": (False, False, True, True, True),
        "exports_enabled": (False, True, True, True, True),
        "analytics_access": (False, False, True, True, True),
    }

    for code, name, sort, trial, monthly_cents in plans:
        plan_id = uuid.uuid4()
        op.bulk_insert(
            sa.table(
                "plans",
                sa.column("id", UUID(as_uuid=True)),
                sa.column("code", sa.String),
                sa.column("name", sa.String),
                sa.column("description", sa.String),
                sa.column("is_public", sa.Boolean),
                sa.column("is_active", sa.Boolean),
                sa.column("sort_order", sa.Integer),
                sa.column("trial_days", sa.Integer),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            ),
            [
                {
                    "id": plan_id,
                    "code": code,
                    "name": name,
                    "description": f"{name} plan (sandbox catalog default — reconfigure via plans admin).",
                    "is_public": True,
                    "is_active": True,
                    "sort_order": sort,
                    "trial_days": trial,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
        if monthly_cents is not None:
            op.bulk_insert(
                sa.table(
                    "plan_prices",
                    sa.column("id", UUID(as_uuid=True)),
                    sa.column("plan_id", UUID(as_uuid=True)),
                    sa.column("billing_period", sa.String),
                    sa.column("amount_cents", sa.Integer),
                    sa.column("currency_code", sa.String),
                    sa.column("is_active", sa.Boolean),
                ),
                [
                    {
                        "id": uuid.uuid4(),
                        "plan_id": plan_id,
                        "billing_period": "monthly",
                        "amount_cents": monthly_cents,
                        "currency_code": "USD",
                        "is_active": True,
                    },
                    {
                        "id": uuid.uuid4(),
                        "plan_id": plan_id,
                        "billing_period": "yearly",
                        "amount_cents": None if monthly_cents == 0 else monthly_cents * 10,
                        "currency_code": "USD",
                        "is_active": True,
                    },
                ],
            )
        idx = ["free", "starter", "professional", "business", "enterprise"].index(code)
        rows = []
        for key, values in ent_int.items():
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "plan_id": plan_id,
                    "key": key,
                    "value_int": values[idx],
                    "value_bool": None,
                }
            )
        for key, values in ent_bool.items():
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "plan_id": plan_id,
                    "key": key,
                    "value_int": None,
                    "value_bool": values[idx],
                }
            )
        op.bulk_insert(
            sa.table(
                "plan_entitlements",
                sa.column("id", UUID(as_uuid=True)),
                sa.column("plan_id", UUID(as_uuid=True)),
                sa.column("key", sa.String),
                sa.column("value_int", sa.Integer),
                sa.column("value_bool", sa.Boolean),
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("onboarding_progress")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_endpoints_org", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_table("api_key_usage")
    op.drop_table("api_keys")
    op.drop_index("ix_report_jobs_due", table_name="report_jobs")
    op.drop_index("ix_report_jobs_org_created", table_name="report_jobs")
    op.drop_table("report_jobs")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user", table_name="notifications")
    op.drop_index("ix_notifications_org_created", table_name="notifications")
    op.drop_index("uq_notification_dedupe", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_activity_farm", table_name="activity_events")
    op.drop_index("ix_activity_org_created", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_index("ix_invitations_org_email", table_name="invitations")
    op.drop_index("uq_invitations_token_hash", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_usage_counters_org", table_name="usage_counters")
    op.drop_table("usage_counters")
    op.drop_index("ix_billing_events_created", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_index("ix_invoices_org", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_subscription_events_sub", table_name="subscription_events")
    op.drop_table("subscription_events")
    op.drop_index("ix_subscriptions_org", table_name="subscriptions")
    op.drop_index("uq_subscription_live_per_org", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plan_entitlements")
    op.drop_table("plan_prices")
    op.drop_table("plans")
    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint("ck_membership_role", "memberships", _ORIGINAL_ROLES)
    op.drop_column("users", "is_platform_admin")

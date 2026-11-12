"""Plan catalog seeding (P3 §4.1 — plans are DATA, never hardcoded gates).

Single runtime source for the default commercial catalog. Values here MUST
match migrations/versions/0020_p3_saas_platform.py::_seed_default_plans
(that frozen copy runs for fresh alembic installs; THIS module covers
environments whose database was built via create_all + stamp, where
migration-time seeding never executes, e.g. the integration-test database).

``ensure_plan_catalog`` is idempotent and insert-missing-only:

- Missing plans are created.
- Missing price rows (plan, billing_period, currency) are created.
- Missing entitlement rows (plan, key) are created.
- Rows that already exist are NEVER overwritten — platform administrators
  may reconfigure prices/limits at runtime without the seeder silently
  reverting them on restart (plans admin API, P3 §4.1).

Removing a plan here does not deactivate its row (historical subscriptions
must keep resolving); retire plans by flipping is_active/is_public in the
database. The public catalog renders a plan with zero active prices as
"contact sales" (enterprise) — never a fabricated $0 price.

Entitlement value semantics (see app/billing/entitlements.py):
- int keys: a count limit, -1 = UNLIMITED.
- bool keys: capability flag.

All amounts are SANDBOX/DEMO catalog values (sandbox provider, test mode,
no money moves — P3 §4.3 honesty rule). Connecting a real payment provider
requires credentials + provider-side product/price mirrors synced with this
catalog (see app/billing/provider.py).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_p3 import Plan, PlanEntitlement, PlanPrice

CATALOG_VERSION = "0020-parity-v1"

# Stable entitlement key names (must match app/billing/entitlements.py).
MAX_FARMS = "max_farms"
MAX_FIELDS = "max_fields"
MAX_ORG_MEMBERS = "max_org_members"
HISTORY_RETENTION_YEARS = "history_retention_years"
ADVANCED_ANALYSIS = "advanced_analysis"
SCENARIO_RUNS_PER_MONTH = "scenario_runs_per_month"
SATELLITE_ACCESS = "satellite_access"
REPORTS_PER_MONTH = "reports_per_month"
API_ENABLED = "api_enabled"
API_RATE_LIMIT_PER_MINUTE = "api_rate_limit_per_minute"
AI_MESSAGES_PER_DAY = "ai_messages_per_day"
EXPORTS_ENABLED = "exports_enabled"
ANALYTICS_ACCESS = "analytics_access"

DEFAULT_CURRENCY = "USD"

# (code, name, sort_order, trial_days, price_monthly_cents | None = contact sales)
_PLAN_ROWS: tuple[tuple[str, str, int, int, int | None], ...] = (
    ("free", "Free", 0, 0, 0),
    ("starter", "Starter", 10, 14, 1900),
    ("professional", "Professional", 20, 14, 4900),
    ("business", "Business", 30, 14, 14900),
    ("enterprise", "Enterprise", 40, 0, None),
)

# key → (free, starter, professional, business, enterprise); -1 = unlimited
_ENTITLEMENT_INT: dict[str, tuple[int, int, int, int, int]] = {
    MAX_FARMS: (1, 2, 10, 50, -1),
    MAX_FIELDS: (3, 10, 50, 250, -1),
    MAX_ORG_MEMBERS: (1, 3, 15, 100, -1),
    HISTORY_RETENTION_YEARS: (1, 3, 10, 15, -1),
    SCENARIO_RUNS_PER_MONTH: (5, 25, 200, 1000, -1),
    REPORTS_PER_MONTH: (3, 15, 100, 500, -1),
    API_RATE_LIMIT_PER_MINUTE: (0, 0, 60, 300, 1000),
    AI_MESSAGES_PER_DAY: (10, 60, 300, 2000, -1),
}

_ENTITLEMENT_BOOL: dict[str, tuple[bool, bool, bool, bool, bool]] = {
    ADVANCED_ANALYSIS: (False, False, True, True, True),
    SATELLITE_ACCESS: (False, True, True, True, True),
    API_ENABLED: (False, False, True, True, True),
    EXPORTS_ENABLED: (False, True, True, True, True),
    ANALYTICS_ACCESS: (False, False, True, True, True),
}

_PLAN_INDEX = {code: i for i, (code, *_rest) in enumerate(_PLAN_ROWS)}


def _yearly_amount(monthly_cents: int | None) -> int | None:
    """Yearly list price. Free keeps a NULL yearly row (annual billing is
    not a commercial offer on a $0 plan); paid plans get 10x monthly."""
    if monthly_cents is None or monthly_cents == 0:
        return None
    return monthly_cents * 10


def ensure_plan_catalog(db: Session) -> dict[str, int]:
    """Idempotently seed the plan catalog. Insert-missing-only by design.

    Returns counts: {"plans_created", "prices_created", "entitlements_created"}.
    Safe to call on every startup; cheap no-op once seeded.
    """
    plans_created = 0
    prices_created = 0
    entitlements_created = 0

    for code, name, sort_order, trial_days, monthly_cents in _PLAN_ROWS:
        plan = db.scalar(select(Plan).where(Plan.code == code))
        if plan is None:
            plan = Plan(
                code=code,
                name=name,
                description=f"{name} plan (sandbox catalog default — reconfigure via plans admin).",
                is_public=True,
                is_active=True,
                sort_order=sort_order,
                trial_days=trial_days,
            )
            db.add(plan)
            db.flush()
            plans_created += 1

        existing_prices = {
            (p.billing_period, p.currency_code)
            for p in db.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id)).all()
        }
        if monthly_cents is not None:
            for period, amount in (("monthly", monthly_cents), ("yearly", _yearly_amount(monthly_cents))):
                if (period, DEFAULT_CURRENCY) in existing_prices:
                    continue
                db.add(
                    PlanPrice(
                        plan_id=plan.id,
                        billing_period=period,
                        amount_cents=amount,
                        currency_code=DEFAULT_CURRENCY,
                        is_active=True,
                    )
                )
                prices_created += 1

        existing_keys = {
            e.key
            for e in db.scalars(
                select(PlanEntitlement).where(PlanEntitlement.plan_id == plan.id)
            ).all()
        }
        idx = _PLAN_INDEX[code]
        for key, values in _ENTITLEMENT_INT.items():
            if key in existing_keys:
                continue
            db.add(
                PlanEntitlement(plan_id=plan.id, key=key, value_int=values[idx], value_bool=None)
            )
            entitlements_created += 1
        for key, values in _ENTITLEMENT_BOOL.items():
            if key in existing_keys:
                continue
            db.add(
                PlanEntitlement(plan_id=plan.id, key=key, value_int=None, value_bool=values[idx])
            )
            entitlements_created += 1

    db.flush()
    return {
        "plans_created": plans_created,
        "prices_created": prices_created,
        "entitlements_created": entitlements_created,
    }

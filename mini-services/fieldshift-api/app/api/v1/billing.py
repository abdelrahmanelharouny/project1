"""Billing endpoints (P3 W2): plans, subscriptions, invoices, usage,
entitlements, sandbox payment simulation and the provider webhook receiver.

Wraps `app/billing/service.py` + `app/billing/entitlements.py`. Every
org-scoped route requires the org_admin or owner role (Task 3 policy —
`principal.require_org_role(org_id, "org_admin")`; services re-check).

HONESTY CONTRACT: the only wired provider is `sandbox` (test mode, no real
money). `/billing/sandbox/pay` is refused unless the active provider is the
sandbox provider; the webhook receiver verifies provider signatures before
anything is processed.
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import entitlements
from app.billing import service as billing_service
from app.billing.provider import get_provider
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.db.models_p3 import Invoice
from app.domains.identity.service import get_principal

router = APIRouter(prefix="/billing", tags=["billing"])

# Signature header for provider callbacks (format: "<timestamp>.<hmac_hex>",
# see SandboxBillingProvider.compute_signature).
WEBHOOK_SIGNATURE_HEADER = "x-croptwist-signature"


# --------------------------------------------------------------- helpers
def _require_org_admin(principal: Any, organization_id: uuid.UUID) -> None:
    """Task 3 policy: every org-scoped billing route requires org_admin/owner.
    Services re-check with their own gates."""
    principal.require_org_role(organization_id, "org_admin")


def _subscription_payload(subscription: Any) -> dict[str, Any]:
    plan = subscription.plan
    return {
        "id": str(subscription.id),
        "organization_id": str(subscription.organization_id),
        "status": subscription.status,
        "billing_period": subscription.billing_period,
        "provider": subscription.provider,
        "provider_mode": get_provider(subscription.provider).mode,
        "current_period_start": subscription.current_period_start.isoformat(),
        "current_period_end": subscription.current_period_end.isoformat(),
        "trial_ends_at": (
            subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None
        ),
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "grace_ends_at": (
            subscription.grace_ends_at.isoformat() if subscription.grace_ends_at else None
        ),
        "plan": (
            {"id": str(plan.id), "code": plan.code, "name": plan.name} if plan else None
        ),
    }


def _checkout_payload(checkout: Any) -> dict[str, Any]:
    return {
        "session_id": checkout.session_id,
        "provider": checkout.provider,
        "url": checkout.url,
        "mode": checkout.mode,
    }


def _invoice_payload(invoice: Invoice) -> dict[str, Any]:
    return {
        "id": str(invoice.id),
        "number": invoice.number,
        "status": invoice.status,
        "amount_cents": invoice.amount_cents,
        "currency_code": invoice.currency_code,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "issued_at": invoice.issued_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
    }


def _plan_by_code_or_404(db: Session, code: str):
    plan = billing_service.get_plan_by_code(db, code)
    if plan is None:
        raise NotFound(f"Plan '{code}' not found in the catalog.")
    return plan


# ------------------------------------------------------------ request models
class SubscriptionStart(BaseModel):
    organization_id: uuid.UUID
    plan_code: str = Field(min_length=1, max_length=40)
    billing_period: str = Field(pattern="^(monthly|yearly)$")


class SubscriptionChange(BaseModel):
    organization_id: uuid.UUID
    new_plan_code: str = Field(min_length=1, max_length=40)
    billing_period: str | None = Field(default=None, pattern="^(monthly|yearly)$")


class SubscriptionCancel(BaseModel):
    organization_id: uuid.UUID
    at_period_end: bool = True


class SubscriptionResume(BaseModel):
    organization_id: uuid.UUID


class SandboxPay(BaseModel):
    organization_id: uuid.UUID
    outcome: str = Field(pattern="^(succeeded|declined)$")


# ------------------------------------------------------------------- routes
@router.get("/plans")
def list_plans(
    db: Session = Depends(get_db),
) -> dict:
    """Public pricing catalog: active public plans + prices + entitlements
    (amount_cents NULL = contact sales). No authentication required."""
    return {"items": billing_service.list_public_plans(db)}


@router.get("/subscription")
def get_subscription(
    organization_id: uuid.UUID = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Billing dashboard snapshot: subscription, plan, usage, resource
    counts, recent invoices and subscription events."""
    _require_org_admin(principal, organization_id)
    return billing_service.subscription_snapshot(
        db, principal, organization_id=organization_id
    )


@router.post("/subscription")
def start_subscription(
    payload: SubscriptionStart,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Start a subscription (trial or paid). Creates the provider checkout —
    the sandbox provider returns a test-mode checkout (no real payment)."""
    _require_org_admin(principal, payload.organization_id)
    plan = _plan_by_code_or_404(db, payload.plan_code)
    result = billing_service.start_subscription(
        db,
        principal,
        organization_id=payload.organization_id,
        plan_id=plan.id,
        billing_period=payload.billing_period,
    )
    return {
        "subscription": _subscription_payload(result["subscription"]),
        "checkout": _checkout_payload(result["checkout"]),
    }


@router.post("/subscription/change")
def change_subscription(
    payload: SubscriptionChange,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Upgrade/downgrade effective immediately (sandbox semantics: proration
    is not simulated; the next invoice reflects the new plan price)."""
    _require_org_admin(principal, payload.organization_id)
    plan = _plan_by_code_or_404(db, payload.new_plan_code)
    subscription = billing_service.change_plan(
        db,
        principal,
        organization_id=payload.organization_id,
        new_plan_id=plan.id,
        billing_period=payload.billing_period,
    )
    return _subscription_payload(subscription)


@router.post("/subscription/cancel")
def cancel_subscription(
    payload: SubscriptionCancel,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel at period end (default) or immediately."""
    _require_org_admin(principal, payload.organization_id)
    subscription = billing_service.cancel_subscription(
        db,
        principal,
        organization_id=payload.organization_id,
        at_period_end=payload.at_period_end,
    )
    return _subscription_payload(subscription)


@router.post("/subscription/resume")
def resume_subscription(
    payload: SubscriptionResume,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Undo a scheduled period-end cancellation."""
    _require_org_admin(principal, payload.organization_id)
    subscription = billing_service.resume_subscription(
        db, principal, organization_id=payload.organization_id
    )
    return _subscription_payload(subscription)


@router.get("/invoices")
def list_invoices(
    organization_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    _require_org_admin(principal, organization_id)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.organization_id == organization_id)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.organization_id == organization_id)
            .order_by(Invoice.issued_at.desc(), Invoice.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return {
        "items": [_invoice_payload(i) for i in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/usage")
def get_usage(
    organization_id: uuid.UUID = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Usage counters vs entitlements for the current billing period."""
    _require_org_admin(principal, organization_id)
    return {"items": entitlements.usage_snapshot(db, organization_id)}


@router.get("/entitlements")
def get_entitlements(
    organization_id: uuid.UUID = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Effective entitlements resolved from the live subscription (free-plan
    floor applies without one; deny-by-default without a catalog)."""
    _require_org_admin(principal, organization_id)
    resolved = entitlements.resolve_entitlements(db, organization_id)
    return {"organization_id": str(organization_id), "entitlements": resolved}


@router.post("/sandbox/pay")
def sandbox_pay(
    payload: SandboxPay,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """TEST-MODE ONLY: simulate a provider payment webhook (success/decline)
    for the org's live subscription, processed through the same idempotent
    pipeline as a real callback. Refused unless the ACTIVE provider is the
    sandbox provider."""
    _require_org_admin(principal, payload.organization_id)
    if settings.billing_provider != "sandbox":
        raise Forbidden(
            "Payment simulation is only available when the sandbox billing "
            "provider is active."
        )
    return billing_service.simulate_sandbox_payment(
        db, principal, organization_id=payload.organization_id, outcome=payload.outcome
    )


@router.post("/webhook")
async def billing_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Provider-agnostic billing webhook receiver.

    Reads the RAW body, verifies the provider signature over the exact bytes
    received (tamper-proof), then hands the event to the idempotent
    `process_billing_webhook` pipeline. Replayed (provider, provider_event_id)
    pairs return the original row with status "duplicate" and never
    double-process. Returns 2xx quickly for accepted events; signature
    failures are rejected with 403 (and recorded for audit).
    """
    raw = await request.body()
    if len(raw) > settings.billing_max_webhook_payload_bytes:
        raise ValidationFailed("Webhook payload exceeds the allowed size.")
    provider_adapter = get_provider(settings.billing_provider)

    signature = request.headers.get(WEBHOOK_SIGNATURE_HEADER, "")
    signature_valid = provider_adapter.verify_webhook(
        payload=raw,
        signature=signature,
        secret=settings.billing_webhook_secret,
    )

    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        # Record the rejected event for audit, then fail loudly.
        billing_service.process_billing_webhook(
            db,
            provider=provider_adapter.name,
            event_type="invalid.payload",
            provider_event_id=f"unparseable-{uuid.uuid4().hex}",
            payload={},
            signature_valid=False,
        )
        raise ValidationFailed("Webhook body must be a JSON object.")

    event_type = str(body.get("event_type") or body.get("type") or "")
    provider_event_id = str(
        body.get("event_id") or body.get("provider_event_id") or body.get("id") or ""
    )
    if not event_type or not provider_event_id:
        raise ValidationFailed(
            "Webhook payload must include 'event_type' and 'event_id'."
        )

    event = billing_service.process_billing_webhook(
        db,
        provider=provider_adapter.name,
        event_type=event_type,
        provider_event_id=provider_event_id,
        payload=body,
        signature_valid=signature_valid,
    )
    return {"received": True, "id": str(event.id), "status": event.status}

"""Subscription lifecycle + billing webhooks (P3 §4.3 / §4.4).

State machine (single live subscription per organization):

    (none) ──start──▶ trialing ──trial_end──▶ active ──period_end──▶ (renew)
                        │                        │
                        └─────────▶ active ──────┘
    active ──payment_failed──▶ past_due ──grace_deadline──▶ grace
    past_due/grace ──payment_ok──▶ active
    any live ──cancel──▶ canceled (at period end) ──expire──▶ canceled/expired

Every transition appends a SubscriptionEvent (audit) and an activity event;
payment events append billing events with provider-level idempotency
(unique provider_event_id). Invoice rows are created on activation/renewal.
NO real payment processing is claimed — provider="sandbox" only (P3 §4.3).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.billing import entitlements
from app.billing.provider import SandboxBillingProvider, get_provider, grace_deadline, period_bounds
from app.core.config import settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.models_p3 import (
    BillingEvent,
    Invoice,
    Plan,
    PlanEntitlement,
    PlanPrice,
    Subscription,
    SubscriptionEvent,
)
from app.domains.identity.service import Principal

LIVE_STATUSES = ("trialing", "active", "past_due", "grace")


def get_plan_by_code(db: Session, code: str) -> Plan | None:
    return db.scalar(select(Plan).where(Plan.code == code, Plan.is_active.is_(True)))


def get_plan_by_id(db: Session, plan_id: uuid.UUID) -> Plan | None:
    return db.get(Plan, plan_id)


def list_public_plans(db: Session) -> list[dict[str, Any]]:
    """Plan catalog for the pricing page (public plans with prices +
    entitlement summaries). Prices are catalog DATA; None = contact sales."""
    plans = list(
        db.scalars(
            select(Plan)
            .where(Plan.is_public.is_(True), Plan.is_active.is_(True))
            .order_by(Plan.sort_order)
        ).all()
    )
    out = []
    for plan in plans:
        prices = list(db.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id)).all())
        ents = list(
            db.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan.id)).all()
        )
        entitlement_map: dict[str, Any] = {}
        for e in ents:
            entitlement_map[e.key] = e.value_int if e.value_int is not None else bool(e.value_bool)
        out.append(
            {
                "id": str(plan.id),
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "trial_days": plan.trial_days,
                "prices": [
                    {
                        "billing_period": p.billing_period,
                        "amount_cents": p.amount_cents,
                        "currency_code": p.currency_code,
                    }
                    for p in prices
                    if p.is_active
                ],
                "entitlements": entitlement_map,
            }
        )
    return out


def _record_transition(
    db: Session,
    *,
    subscription: Subscription,
    event_type: str,
    to_status: str | None,
    actor_user_id: uuid.UUID | None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        SubscriptionEvent(
            subscription_id=subscription.id,
            event_type=event_type,
            from_status=subscription.status,
            to_status=to_status,
            details=details or {},
            actor_user_id=actor_user_id,
        )
    )
    if to_status is not None:
        subscription.status = to_status
    activity.record_event(
        db,
        organization_id=subscription.organization_id,
        event_type=activity.EVENT_SUBSCRIPTION_CHANGED,
        summary=f"Subscription {event_type}" + (f" → {to_status}" if to_status else ""),
        actor_user_id=actor_user_id,
        entity_kind="subscription",
        entity_id=str(subscription.id),
        details=details or {},
    )
    # P3 W6: direct lifecycle transitions (start/change/cancel/resume/renew)
    # also notify subscribed webhooks — same event the provider-webhook path
    # emits. Emission must never fail the billing transition.
    try:
        from app.publicapi.emitters import emit_event

        emit_event(
            db,
            subscription.organization_id,
            "subscription.updated",
            payload_id=str(subscription.id),
            data={
                "billing_event": event_type,
                "subscription_status": to_status or subscription.status,
                "plan_code": getattr(subscription, "plan_code", None),
            },
        )
    except Exception:  # noqa: BLE001
        pass


def _create_invoice(
    db: Session,
    *,
    subscription: Subscription,
    period_start: datetime,
    period_end: datetime,
    amount_cents: int,
    currency_code: str,
) -> Invoice:
    number = f"CT-{period_end.strftime('%Y%m')}-{uuid.uuid4().hex[:8].upper()}"
    invoice = Invoice(
        organization_id=subscription.organization_id,
        subscription_id=subscription.id,
        number=number,
        status="paid" if amount_cents == 0 else "open",
        amount_cents=amount_cents,
        currency_code=currency_code,
        period_start=period_start.date(),
        period_end=period_end.date(),
        issued_at=datetime.now(UTC),
        paid_at=datetime.now(UTC) if amount_cents == 0 else None,
        provider_ref=subscription.provider_subscription_ref,
        provider_invoice_ref=f"inv_{subscription.provider}_{uuid.uuid4().hex}",
    )
    db.add(invoice)
    return invoice


def _price_for(db: Session, plan: Plan, billing_period: str) -> tuple[int | None, str]:
    price = db.scalar(
        select(PlanPrice).where(
            PlanPrice.plan_id == plan.id,
            PlanPrice.billing_period == billing_period,
            PlanPrice.is_active.is_(True),
        )
    )
    if price is None:
        return None, "USD"
    return price.amount_cents, price.currency_code


# ---------------------------------------------------------------- lifecycle
def start_subscription(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    billing_period: str,
    actor: str = "self",
) -> dict[str, Any]:
    """Start a trial or paid subscription for the organization.

    Owner/org_admin only. Creates the checkout session via the provider
    (sandbox) and, for plans with a trial, activates a trialing subscription
    immediately; paid-without-trial starts 'active' with a $0-truth invoice
    in the sandbox (test mode — no money moves).
    """
    principal.require_org_role(organization_id, "org_admin")
    if billing_period not in ("monthly", "yearly"):
        raise ValidationFailed("billing_period must be 'monthly' or 'yearly'.")
    # Match scenario reservation's lock order before inspecting live subscription state.
    entitlements.lock_organization(db, organization_id)
    existing = entitlements.get_live_subscription(db, organization_id)
    if existing is not None:
        raise Conflict("This organization already has a live subscription.")
    plan = db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise NotFound("Plan not found.")

    provider = get_provider(settings.billing_provider)
    checkout = provider.create_checkout(
        organization_id=organization_id,
        plan_code=plan.code,
        billing_period=billing_period,
        success_url="/billing?checkout=success",
        cancel_url="/pricing?checkout=cancelled",
    )
    now = datetime.now(UTC)
    start, end = period_bounds(start=now, billing_period=billing_period)
    trial_ends = (
        now + timedelta(days=plan.trial_days) if plan.trial_days and plan.trial_days > 0 else None
    )
    status = "trialing" if trial_ends is not None else "active"
    amount, currency = _price_for(db, plan, billing_period)
    subscription = Subscription(
        organization_id=organization_id,
        plan_id=plan.id,
        status=status,
        billing_period=billing_period,
        provider=provider.name,
        provider_customer_ref=provider.create_customer(
            organization_id=organization_id,
            email=principal.user.email,
            name=principal.user.display_name,
        ),
        provider_subscription_ref=f"sub_sandbox_{subscription_ref_suffix(checkout.session_id)}",
        current_period_start=start,
        current_period_end=end if trial_ends is None else (now + timedelta(days=plan.trial_days)),
        trial_ends_at=trial_ends,
    )
    db.add(subscription)
    db.flush()
    _record_transition(
        db,
        subscription=subscription,
        event_type="subscription.started",
        to_status=status,
        actor_user_id=principal.id,
        details={
            "plan_code": plan.code,
            "billing_period": billing_period,
            "provider": provider.name,
            "mode": provider.mode,
            "checkout_session": checkout.session_id,
            "actor": actor,
        },
    )
    if status == "active":
        _create_invoice(
            db,
            subscription=subscription,
            period_start=start,
            period_end=end,
            amount_cents=amount or 0,
            currency_code=currency,
        )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_PLAN_CHANGED,
        summary=f"Subscribed to the {plan.name} plan ({billing_period}, sandbox test mode)",
        actor_user_id=principal.id,
        entity_kind="subscription",
        entity_id=str(subscription.id),
        details={"plan_code": plan.code, "mode": provider.mode},
    )
    db.commit()
    db.refresh(subscription)
    return {"subscription": subscription, "checkout": checkout}


def subscription_ref_suffix(session_id: str) -> str:
    return hashlib_short(session_id)


def hashlib_short(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:16]


def change_plan(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    new_plan_id: uuid.UUID,
    billing_period: str | None = None,
) -> Subscription:
    """Upgrade/downgrade effective immediately (sandbox semantics: proration
    is NOT simulated; the next invoice reflects the new plan price)."""
    principal.require_org_role(organization_id, "org_admin")
    entitlements.lock_organization(db, organization_id)
    subscription = entitlements.get_live_subscription(db, organization_id)
    if subscription is None:
        raise Conflict("No live subscription to change.")
    plan = db.get(Plan, new_plan_id)
    if plan is None or not plan.is_active:
        raise NotFound("Plan not found.")
    old_plan = db.get(Plan, subscription.plan_id)
    period = billing_period or subscription.billing_period
    if period not in ("monthly", "yearly"):
        raise ValidationFailed("billing_period must be 'monthly' or 'yearly'.")
    subscription.plan_id = plan.id
    if billing_period and billing_period != subscription.billing_period:
        subscription.billing_period = billing_period
        start, end = period_bounds(start=subscription.current_period_end, billing_period=period)
        subscription.current_period_start = subscription.current_period_end
        subscription.current_period_end = end
    _record_transition(
        db,
        subscription=subscription,
        event_type="subscription.plan_changed",
        to_status=None,
        actor_user_id=principal.id,
        details={
            "from_plan": old_plan.code if old_plan else None,
            "to_plan": plan.code,
            "billing_period": period,
        },
    )
    activity.record_event(
        db,
        organization_id=organization_id,
        event_type=activity.EVENT_PLAN_CHANGED,
        summary=f"Plan changed to {plan.name} (sandbox test mode)",
        actor_user_id=principal.id,
        entity_kind="subscription",
        entity_id=str(subscription.id),
        details={"to_plan": plan.code},
    )
    db.commit()
    db.refresh(subscription)
    return subscription


def cancel_subscription(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    at_period_end: bool = True,
) -> Subscription:
    principal.require_org_role(organization_id, "org_admin")
    entitlements.lock_organization(db, organization_id)
    subscription = entitlements.get_live_subscription(db, organization_id)
    if subscription is None:
        raise Conflict("No live subscription to cancel.")
    now = datetime.now(UTC)
    if at_period_end:
        subscription.cancel_at_period_end = True
        _record_transition(
            db,
            subscription=subscription,
            event_type="subscription.cancel_scheduled",
            to_status=None,
            actor_user_id=principal.id,
            details={"effective_at": subscription.current_period_end.isoformat()},
        )
    else:
        subscription.canceled_at = now
        _record_transition(
            db,
            subscription=subscription,
            event_type="subscription.canceled",
            to_status="canceled",
            actor_user_id=principal.id,
        )
        from app.notifications import service as notifications

        notifications.create_notification(
            db,
            organization_id=organization_id,
            category="subscription",
            severity="warning",
            title="Subscription canceled",
            body="Your subscription is now canceled. Plan limits apply.",
            dedupe_key=f"subscription:canceled:{subscription.id}",
        )
    db.commit()
    db.refresh(subscription)
    return subscription


def resume_subscription(
    db: Session, principal: Principal, *, organization_id: uuid.UUID
) -> Subscription:
    """Undo a scheduled period-end cancellation."""
    principal.require_org_role(organization_id, "org_admin")
    entitlements.lock_organization(db, organization_id)
    subscription = entitlements.get_live_subscription(db, organization_id)
    if subscription is None:
        raise Conflict("No live subscription.")
    if not subscription.cancel_at_period_end:
        raise Conflict("Cancellation is not scheduled.")
    subscription.cancel_at_period_end = False
    _record_transition(
        db,
        subscription=subscription,
        event_type="subscription.resume",
        to_status=None,
        actor_user_id=principal.id,
    )
    db.commit()
    db.refresh(subscription)
    return subscription


# -------------------------------------------------------- webhook pipeline
def _parse_callback_identity(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate identity fields before any callback can mutate billing state."""
    org_ref = payload.get("organization_id")
    if not isinstance(org_ref, str) or not org_ref:
        raise ValidationFailed("payload.organization_id is required.")
    try:
        organization_id = uuid.UUID(org_ref)
    except (ValueError, AttributeError) as exc:
        raise ValidationFailed("payload.organization_id must be a UUID.") from exc

    subscription_ref = payload.get("provider_subscription_ref")
    if not isinstance(subscription_ref, str) or not subscription_ref.strip():
        raise ValidationFailed("payload.provider_subscription_ref is required.")
    if len(subscription_ref) > 200:
        raise ValidationFailed("payload.provider_subscription_ref is too long.")

    identity: dict[str, Any] = {
        "organization_id": organization_id,
        "provider_subscription_ref": subscription_ref,
    }
    if event_type in ("payment.succeeded", "payment.declined"):
        invoice_ref = payload.get("invoice_id")
        try:
            invoice_id = uuid.UUID(invoice_ref) if isinstance(invoice_ref, str) else None
        except ValueError as exc:
            raise ValidationFailed("payload.invoice_id must be a UUID.") from exc
        if invoice_id is None:
            raise ValidationFailed("payload.invoice_id is required.")

        transaction_id = payload.get("provider_transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise ValidationFailed("payload.provider_transaction_id is required.")
        if len(transaction_id) > 200:
            raise ValidationFailed("payload.provider_transaction_id is too long.")

        amount_cents = payload.get("amount_cents")
        if type(amount_cents) is not int or amount_cents < 0:
            raise ValidationFailed("Payment requires a non-negative integer amount_cents.")
        currency_code = payload.get("currency")
        if not isinstance(currency_code, str) or len(currency_code.strip()) != 3:
            raise ValidationFailed("Payment requires a three-letter currency.")
        currency_code = currency_code.strip().upper()
        if not currency_code.isalpha():
            raise ValidationFailed("Payment currency must contain three letters.")

        provider_invoice_ref = payload.get("provider_invoice_ref")
        if provider_invoice_ref is not None and (
            not isinstance(provider_invoice_ref, str)
            or not provider_invoice_ref.strip()
            or len(provider_invoice_ref) > 200
        ):
            raise ValidationFailed("payload.provider_invoice_ref is invalid.")
        identity.update(
            invoice_id=invoice_id,
            provider_transaction_id=transaction_id,
            amount_cents=amount_cents,
            currency_code=currency_code,
            provider_invoice_ref=provider_invoice_ref,
        )
    elif event_type == "subscription.renewal_due":
        period_start = payload.get("period_start")
        if not isinstance(period_start, str) or not period_start:
            raise ValidationFailed("payload.period_start is required for a renewal.")
        try:
            parsed_start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationFailed("payload.period_start must be an ISO datetime.") from exc
        if parsed_start.tzinfo is None:
            raise ValidationFailed("payload.period_start must include a timezone.")
        identity["period_start"] = parsed_start.astimezone(UTC)
    return identity


def _resolve_callback_subscription(
    db: Session, *, provider: str, organization_id: uuid.UUID, subscription_ref: str
) -> Subscription:
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.provider == provider,
            Subscription.organization_id == organization_id,
            Subscription.provider_subscription_ref == subscription_ref,
        )
        .with_for_update()
        .limit(1)
    )
    if subscription is None:
        raise NotFound("No subscription matches this provider identity.")
    return subscription


def _resolve_callback_invoice(
    db: Session, *, identity: dict[str, Any], subscription: Subscription
) -> Invoice:
    invoice = db.scalar(
        select(Invoice)
        .where(
            Invoice.id == identity["invoice_id"],
            Invoice.organization_id == subscription.organization_id,
            Invoice.subscription_id == subscription.id,
        )
        .with_for_update()
    )
    if invoice is None:
        raise NotFound("No invoice matches this subscription payment.")
    if invoice.provider_ref and invoice.provider_ref != subscription.provider_subscription_ref:
        raise ValidationFailed("Invoice provider subscription does not match the callback.")
    supplied_invoice_ref = identity.get("provider_invoice_ref")
    if supplied_invoice_ref is not None and invoice.provider_invoice_ref != supplied_invoice_ref:
        raise ValidationFailed("Invoice provider reference does not match the callback.")
    if identity["amount_cents"] != invoice.amount_cents:
        raise ValidationFailed("Payment amount does not match the referenced invoice.")
    if identity["currency_code"] != invoice.currency_code.upper():
        raise ValidationFailed("Payment currency does not match the referenced invoice.")
    return invoice


def process_billing_webhook(
    db: Session,
    *,
    provider: str,
    event_type: str,
    provider_event_id: str,
    payload: dict[str, Any],
    signature_valid: bool,
) -> BillingEvent:
    """Idempotent billing webhook ingestion (P3 §4.4).

    - Signature-invalid events are REJECTED (status 'failed') and never
      processed.
    - (provider, provider_event_id) and successfully processed provider
      transaction identity are idempotent, even when event IDs differ.
    - Payment callbacks must bind an invoice UUID, transaction ID, and exact
      provider subscription reference; there is deliberately no open-invoice
      fallback.
    - Handled event types: payment.succeeded, payment.declined,
      subscription.renewal_due, subscription.expired.
    """
    from app.core.errors import Forbidden

    if not signature_valid:
        event = BillingEvent(
            provider=provider,
            event_type=event_type[:80],
            provider_event_id=provider_event_id[:200],
            signature_valid=False,
            status="failed",
            error="invalid webhook signature",
            payload={},
        )
        db.add(event)
        db.commit()
        raise Forbidden("Webhook signature verification failed.")

    existing = db.scalar(
        select(BillingEvent).where(
            BillingEvent.provider == provider, BillingEvent.provider_event_id == provider_event_id
        )
    )
    if existing is not None and existing.status in ("processed", "duplicate"):
        existing.status = "duplicate"
        db.commit()
        return existing

    if existing is None:
        event = BillingEvent(
            provider=provider,
            event_type=event_type[:80],
            provider_event_id=provider_event_id[:200],
            signature_valid=True,
            status="received",
            payload=payload,
        )
        db.add(event)
    else:
        # A previously failed delivery can retry with the same provider event ID.
        event = existing
        event.event_type = event_type[:80]
        event.signature_valid = True
        event.status = "received"
        event.error = None
        event.payload = payload
        event.processed_at = None
        event.provider_transaction_id = None
        event.provider_subscription_ref = None
        event.invoice_id = None
    db.flush()

    audit_transaction_id = payload.get("provider_transaction_id")
    if not isinstance(audit_transaction_id, str) or not audit_transaction_id.strip():
        audit_transaction_id = None
    elif len(audit_transaction_id) > 200:
        audit_transaction_id = None
    audit_subscription_ref = payload.get("provider_subscription_ref")
    if not isinstance(audit_subscription_ref, str) or len(audit_subscription_ref) > 200:
        audit_subscription_ref = None
    audit_invoice_id: uuid.UUID | None = None
    subscription: Subscription | None = None
    try:
        identity = _parse_callback_identity(event_type, payload)
        audit_subscription_ref = identity["provider_subscription_ref"]
        audit_invoice_id = identity.get("invoice_id")
        # Always lock organization before locking a subscription or invoice row.
        entitlements.lock_organization(db, identity["organization_id"])
        subscription = _resolve_callback_subscription(
            db,
            provider=provider,
            organization_id=identity["organization_id"],
            subscription_ref=identity["provider_subscription_ref"],
        )
        event.provider_subscription_ref = subscription.provider_subscription_ref

        if event_type == "payment.succeeded":
            invoice = _resolve_callback_invoice(db, identity=identity, subscription=subscription)
            event.invoice_id = invoice.id
            transaction_id = identity["provider_transaction_id"]
            existing_transaction = db.scalar(
                select(BillingEvent).where(
                    BillingEvent.provider == provider,
                    BillingEvent.provider_transaction_id == transaction_id,
                    BillingEvent.status.in_(("processed", "duplicate")),
                )
            )
            if existing_transaction is not None:
                if (
                    existing_transaction.invoice_id != invoice.id
                    or existing_transaction.provider_subscription_ref
                    != subscription.provider_subscription_ref
                ):
                    raise ValidationFailed(
                        "Provider transaction identity conflicts with a prior payment."
                    )
                event.status = "duplicate"
                event.processed_at = datetime.now(UTC)
                db.commit()
                return event
            _settle_payment(
                db,
                subscription=subscription,
                invoice=invoice,
                amount_cents=identity["amount_cents"],
                currency_code=identity["currency_code"],
                provider_transaction_id=transaction_id,
            )
            event.provider_transaction_id = transaction_id
        elif event_type == "payment.declined":
            invoice = _resolve_callback_invoice(db, identity=identity, subscription=subscription)
            event.invoice_id = invoice.id
            transaction_id = identity["provider_transaction_id"]
            existing_transaction = db.scalar(
                select(BillingEvent).where(
                    BillingEvent.provider == provider,
                    BillingEvent.provider_transaction_id == transaction_id,
                    BillingEvent.status.in_(("processed", "duplicate")),
                )
            )
            if existing_transaction is not None:
                if (
                    existing_transaction.invoice_id != invoice.id
                    or existing_transaction.provider_subscription_ref
                    != subscription.provider_subscription_ref
                ):
                    raise ValidationFailed(
                        "Provider transaction identity conflicts with a prior payment."
                    )
                event.status = "duplicate"
                event.processed_at = datetime.now(UTC)
                db.commit()
                return event
            _enter_past_due(db, subscription=subscription, invoice=invoice)
            event.provider_transaction_id = transaction_id
        elif event_type == "subscription.renewal_due":
            if subscription.status not in LIVE_STATUSES:
                pass  # stale lifecycle event for a terminal subscription
            elif identity["period_start"] < subscription.current_period_end:
                pass  # already-applied or delayed renewal; never roll forward twice
            elif identity["period_start"] > subscription.current_period_end:
                raise ValidationFailed("Renewal period_start does not match the current period end.")
            else:
                _renew(
                    db,
                    subscription=subscription,
                    paid=payload.get("simulate_outcome") != "declined",
                    expected_period_start=identity["period_start"],
                )
        elif event_type in ("subscription.ended", "subscription.expired"):
            if subscription.status in LIVE_STATUSES:
                terminal_status = "expired" if event_type == "subscription.expired" else "canceled"
                _record_transition(
                    db,
                    subscription=subscription,
                    event_type=event_type,
                    to_status=terminal_status,
                    actor_user_id=None,
                    details={"source": "provider_webhook"},
                )
        else:
            raise ValidationFailed(f"Unhandled billing event type '{event_type}'.")
        event.status = "processed"
        event.processed_at = datetime.now(UTC)
    except Exception as exc:
        # A webhook is one atomic domain transaction. Discard every invoice,
        # subscription, activity, and notification mutation before writing a
        # separate failed-event audit row; never commit a partial settlement.
        db.rollback()
        failed_event = db.scalar(
            select(BillingEvent).where(
                BillingEvent.provider == provider,
                BillingEvent.provider_event_id == provider_event_id,
            )
        )
        if failed_event is None:
            failed_event = BillingEvent(
                provider=provider,
                event_type=event_type[:80],
                provider_event_id=provider_event_id[:200],
                signature_valid=True,
                payload=payload,
            )
            db.add(failed_event)
        failed_event.status = "failed"
        failed_event.error = f"{type(exc).__name__}: {exc}"[:2000]
        failed_event.processed_at = None
        failed_event.provider_transaction_id = audit_transaction_id
        failed_event.provider_subscription_ref = audit_subscription_ref
        failed_event.invoice_id = audit_invoice_id
        db.commit()
        raise
    db.commit()
    # P3 W6: surface subscription lifecycle changes to subscribed webhooks.
    try:
        from app.publicapi.emitters import emit_event

        if subscription is not None:
            emit_event(
                db,
                subscription.organization_id,
                "subscription.updated",
                payload_id=str(event.id),
                data={
                    "billing_event": event_type,
                    "subscription_status": subscription.status
                    if subscription is not None
                    else None,
                },
            )
            db.commit()
    except Exception:  # noqa: BLE001 — emission must not fail billing intake
        db.rollback()
    db.refresh(event)
    return event


def _settle_payment(
    db: Session,
    *,
    subscription: Subscription,
    invoice: Invoice,
    amount_cents: int,
    currency_code: str,
    provider_transaction_id: str,
) -> None:
    """Settle only the referenced invoice; never infer from open invoice order."""
    now = datetime.now(UTC)
    if invoice.status == "paid":
        if invoice.provider_transaction_ref in (None, provider_transaction_id):
            return  # a delayed replay cannot emit a second notification
        raise ValidationFailed("The referenced invoice was paid by a different transaction.")
    if invoice.status != "open":
        raise ValidationFailed("The referenced invoice is not open for payment.")
    if amount_cents != invoice.amount_cents:
        raise ValidationFailed("Payment amount does not match the referenced invoice.")
    if currency_code != invoice.currency_code.upper():
        raise ValidationFailed("Payment currency does not match the referenced invoice.")
    invoice.status = "paid"
    invoice.paid_at = now
    invoice.provider_transaction_ref = provider_transaction_id
    is_current_period = invoice.period_start == subscription.current_period_start.date()
    if is_current_period and subscription.status in ("past_due", "grace"):
        _record_transition(
            db,
            subscription=subscription,
            event_type="payment.succeeded",
            to_status="active",
            actor_user_id=None,
            details={"amount_cents": amount_cents},
        )
        subscription.grace_ends_at = None
    from app.notifications import service as notifications

    notifications.create_notification(
        db,
        organization_id=subscription.organization_id,
        category="billing",
        severity="info",
        title="Payment received",
        body="Your invoice has been paid. Thank you.",
        dedupe_key=f"billing:paid:{invoice.id}",
        commit=False,
    )


def _enter_past_due(db: Session, *, subscription: Subscription, invoice: Invoice) -> None:
    now = datetime.now(UTC)
    if (
        invoice.status != "open"
        or invoice.period_start != subscription.current_period_start.date()
        or subscription.status not in LIVE_STATUSES
        or subscription.status == "past_due"
    ):
        return
    _record_transition(
        db,
        subscription=subscription,
        event_type="payment.declined",
        to_status="past_due",
        actor_user_id=None,
    )
    subscription.grace_ends_at = grace_deadline(now)
    from app.notifications import service as notifications

    notifications.create_notification(
        db,
        organization_id=subscription.organization_id,
        category="billing",
        severity="critical",
        title="Payment failed",
        body="A payment attempt for this invoice failed. Update your payment method to avoid service limits.",
        dedupe_key=f"billing:failed:{invoice.id}",
        commit=False,
    )


def _renew(
    db: Session,
    *,
    subscription: Subscription,
    paid: bool,
    expected_period_start: datetime,
) -> None:
    """Period rollover: honor cancel_at_period_end, expire trials, renew."""
    now = datetime.now(UTC)
    if expected_period_start != subscription.current_period_end.astimezone(UTC):
        raise ValidationFailed("Renewal period_start does not match the current period end.")
    if subscription.cancel_at_period_end:
        subscription.canceled_at = now
        _record_transition(
            db,
            subscription=subscription,
            event_type="subscription.canceled",
            to_status="canceled",
            actor_user_id=None,
            details={"reason": "cancel_at_period_end"},
        )
        return
    # Trial expiry without payment setup → active (sandbox) unless declined.
    plan = db.get(Plan, subscription.plan_id)
    amount, currency = _price_for(db, plan, subscription.billing_period) if plan else (0, "USD")
    start, end = period_bounds(start=subscription.current_period_end, billing_period=subscription.billing_period)
    subscription.current_period_start = start
    subscription.current_period_end = end
    if subscription.status == "trialing":
        _record_transition(
            db,
            subscription=subscription,
            event_type="trial.ended",
            to_status="active" if paid else "past_due",
            actor_user_id=None,
        )
        if not paid:
            subscription.grace_ends_at = grace_deadline(now)
            return
    _create_invoice(
        db,
        subscription=subscription,
        period_start=start,
        period_end=end,
        amount_cents=amount or 0,
        currency_code=currency,
    )
    if not paid:
        invoice = db.scalar(
            select(Invoice)
            .where(
                Invoice.subscription_id == subscription.id,
                Invoice.period_start == start.date(),
                Invoice.period_end == end.date(),
            )
            .order_by(Invoice.issued_at.desc())
            .limit(1)
        )
        if invoice is not None:
            _enter_past_due(db, subscription=subscription, invoice=invoice)


def expire_stale_subscriptions(db: Session) -> int:
    """Scheduler sweep: cancel_at_period_end subscriptions past period end
    and grace windows that lapsed → 'expired'/'canceled'."""
    now = datetime.now(UTC)
    changed = 0
    stale_condition = or_(
        and_(
            Subscription.cancel_at_period_end.is_(True),
            Subscription.current_period_end < now,
        ),
        and_(
            Subscription.status == "past_due",
            Subscription.grace_ends_at.is_not(None),
            Subscription.grace_ends_at < now,
        ),
    )
    # Discover candidates by organization id, then acquire organization locks
    # in a stable order and re-read subscription state under those locks.
    candidate_organization_ids = list(
        db.scalars(
            select(Subscription.organization_id)
            .where(Subscription.status.in_(LIVE_STATUSES), stale_condition)
            .distinct()
            .order_by(Subscription.organization_id)
        ).all()
    )
    for organization_id in candidate_organization_ids:
        if not entitlements.lock_organization(db, organization_id):
            continue
        rows = list(
            db.scalars(
                select(Subscription)
                .where(
                    Subscription.organization_id == organization_id,
                    Subscription.status.in_(LIVE_STATUSES),
                )
                .order_by(Subscription.created_at, Subscription.id)
                .with_for_update()
            ).all()
        )
        for sub in rows:
            if sub.cancel_at_period_end and sub.current_period_end < now:
                sub.canceled_at = now
                _record_transition(
                    db,
                    subscription=sub,
                    event_type="subscription.canceled",
                    to_status="canceled",
                    actor_user_id=None,
                    details={"reason": "period_ended_after_cancel_request"},
                )
                changed += 1
            elif (
                sub.status == "past_due"
                and sub.grace_ends_at is not None
                and sub.grace_ends_at < now
            ):
                _record_transition(
                    db,
                    subscription=sub,
                    event_type="subscription.grace_ended",
                    to_status="grace",
                    actor_user_id=None,
                    details={"note": "grace window lapsed — paid capabilities locked"},
                )
                changed += 1
    if changed:
        db.commit()
    return changed


# ------------------------------------------------------------ sandbox sims
def simulate_sandbox_payment(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    outcome: str,
) -> dict[str, Any]:
    """TEST-MODE ONLY: simulate the provider payment webhook for the org's
    live subscription (success or decline). Requires org_admin and the
    sandbox provider; the generated webhook is processed through the same
    idempotent pipeline as a real callback."""
    principal.require_org_role(organization_id, "org_admin")
    # Lock before querying subscription/invoice rows; the webhook path later
    # reacquires this transaction-held lock before its subscription row lock.
    entitlements.lock_organization(db, organization_id)
    subscription = entitlements.get_live_subscription(db, organization_id)
    if subscription is None:
        raise Conflict("No live subscription.")
    if subscription.provider != "sandbox":
        raise ValidationFailed("Payment simulation is only available for the sandbox provider.")
    open_invoices = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.organization_id == organization_id,
                Invoice.subscription_id == subscription.id,
                Invoice.status == "open",
            )
            .with_for_update()
        ).all()
    )
    if not open_invoices:
        raise Conflict("No open invoice is available for sandbox payment simulation.")
    if len(open_invoices) != 1:
        raise Conflict("Sandbox payment simulation requires an explicit invoice when multiple are open.")
    invoice = open_invoices[0]
    if invoice.provider_invoice_ref is None:
        invoice.provider_invoice_ref = f"inv_sandbox_{invoice.id}"
    provider = get_provider("sandbox")
    assert isinstance(provider, SandboxBillingProvider)
    result = provider.simulate_payment(
        outcome=outcome,
        subscription_ref=subscription.provider_subscription_ref or "",
        invoice_id=str(invoice.id),
        provider_invoice_ref=invoice.provider_invoice_ref,
        amount_cents=invoice.amount_cents,
        currency=invoice.currency_code,
    )
    payload = {
        "organization_id": str(organization_id),
        "event_id": result.provider_event_id,
        "outcome": result.outcome,
        **result.details,
    }
    event = process_billing_webhook(
        db,
        provider="sandbox",
        event_type="payment.succeeded" if outcome == "succeeded" else "payment.declined",
        provider_event_id=result.provider_event_id,
        payload=payload,
        signature_valid=True,  # simulated in-process; signing verified in unit tests
    )
    db.refresh(subscription)
    return {"billing_event_id": str(event.id), "status": event.status, "outcome": result.outcome}


def subscription_snapshot(db: Session, principal: Principal, *, organization_id: uuid.UUID) -> dict[str, Any]:
    """Billing dashboard payload: subscription, plan, usage, invoices."""
    principal.require_member_of(organization_id)
    subscription = entitlements.get_live_subscription(db, organization_id)
    plan = subscription.plan if subscription else None
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.organization_id == organization_id)
            .order_by(Invoice.issued_at.desc())
            .limit(24)
        ).all()
    )
    events = []
    if subscription is not None:
        rows = list(
            db.scalars(
                select(SubscriptionEvent)
                .where(SubscriptionEvent.subscription_id == subscription.id)
                .order_by(SubscriptionEvent.created_at.desc())
                .limit(20)
            ).all()
        )
        events = [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "details": e.details,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ]
    return {
        "subscription": (
            {
                "id": str(subscription.id),
                "status": subscription.status,
                "billing_period": subscription.billing_period,
                "provider": subscription.provider,
                "provider_mode": get_provider(subscription.provider).mode,
                "current_period_start": subscription.current_period_start.isoformat(),
                "current_period_end": subscription.current_period_end.isoformat(),
                "trial_ends_at": subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "grace_ends_at": subscription.grace_ends_at.isoformat() if subscription.grace_ends_at else None,
                "plan": (
                    {"id": str(plan.id), "code": plan.code, "name": plan.name} if plan else None
                ),
            }
            if subscription
            else None
        ),
        "usage": entitlements.usage_snapshot(db, organization_id),
        "resource_counts": entitlements.resource_counts(db, organization_id),
        "invoices": [
            {
                "id": str(i.id),
                "number": i.number,
                "status": i.status,
                "amount_cents": i.amount_cents,
                "currency_code": i.currency_code,
                "period_start": i.period_start.isoformat(),
                "period_end": i.period_end.isoformat(),
                "issued_at": i.issued_at.isoformat(),
                "paid_at": i.paid_at.isoformat() if i.paid_at else None,
            }
            for i in invoices
        ],
        "events": events,
    }

"""Database integration regressions for invoice-bound billing callbacks.

All provider payloads below are synthetic and HMAC-signed locally. No live
payment, email, or external provider is invoked.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.billing import service as billing_service
from app.core.config import settings
from app.db.models_p3 import BillingEvent, Invoice, Notification, Subscription

WEBHOOK_URL = "/api/v1/billing/webhook"


def _start_subscription(client, headers: dict, organization_id: str, plan_code: str) -> None:
    response = client.post(
        "/api/v1/billing/subscription",
        headers=headers,
        json={
            "organization_id": organization_id,
            "plan_code": plan_code,
            "billing_period": "monthly",
        },
    )
    assert response.status_code == 200, response.text


def _signed_webhook(payload: dict) -> tuple[bytes, dict]:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        settings.billing_webhook_secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "x-croptwist-signature": f"{timestamp}.{signature}",
    }


def _deliver(client, payload: dict):
    raw, headers = _signed_webhook(payload)
    return client.post(WEBHOOK_URL, content=raw, headers=headers)


def _open_invoice_context(client, auth_headers, db):
    headers, user = auth_headers
    organization_id = user["organization"]["id"]
    _start_subscription(client, headers, organization_id, "free")
    changed = client.post(
        "/api/v1/billing/subscription/change",
        headers=headers,
        json={"organization_id": organization_id, "new_plan_code": "starter"},
    )
    assert changed.status_code == 200, changed.text
    db.expire_all()
    subscription = db.scalar(
        select(Subscription).where(
            Subscription.organization_id == uuid.UUID(organization_id),
            Subscription.status.in_(("trialing", "active", "past_due", "grace")),
        )
    )
    assert subscription is not None
    renewal = _renewal_payload(subscription, event_id=f"evt_seed_renew_{uuid.uuid4().hex}")
    response = _deliver(client, renewal)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"
    db.expire_all()
    subscription = db.get(Subscription, subscription.id)
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.organization_id == uuid.UUID(organization_id),
            Invoice.subscription_id == subscription.id,
            Invoice.status == "open",
        )
    )
    assert invoice is not None
    return headers, organization_id, subscription, invoice


def _renewal_payload(subscription: Subscription, *, event_id: str) -> dict:
    return {
        "event_type": "subscription.renewal_due",
        "event_id": event_id,
        "organization_id": str(subscription.organization_id),
        "provider_subscription_ref": subscription.provider_subscription_ref,
        "period_start": subscription.current_period_end.isoformat(),
    }


def _payment_payload(
    subscription: Subscription,
    invoice: Invoice,
    *,
    event_id: str,
    transaction_id: str,
    event_type: str = "payment.succeeded",
    amount_cents: int | None = None,
    currency: str | None = None,
) -> dict:
    return {
        "event_type": event_type,
        "event_id": event_id,
        "organization_id": str(subscription.organization_id),
        "provider_subscription_ref": subscription.provider_subscription_ref,
        "invoice_id": str(invoice.id),
        "provider_invoice_ref": invoice.provider_invoice_ref,
        "provider_transaction_id": transaction_id,
        "amount_cents": invoice.amount_cents if amount_cents is None else amount_cents,
        "currency": invoice.currency_code if currency is None else currency,
    }


def _add_open_invoice(db, subscription: Subscription, *, amount_cents: int, issued_at: datetime) -> Invoice:
    invoice = Invoice(
        organization_id=subscription.organization_id,
        subscription_id=subscription.id,
        number=f"CT-CB-{uuid.uuid4().hex[:12].upper()}",
        status="open",
        amount_cents=amount_cents,
        currency_code="USD",
        period_start=subscription.current_period_start.date(),
        period_end=subscription.current_period_end.date(),
        issued_at=issued_at,
        provider_ref=subscription.provider_subscription_ref,
        provider_invoice_ref=f"inv_sandbox_{uuid.uuid4().hex}",
    )
    db.add(invoice)
    db.flush()
    return invoice


def test_success_settles_the_referenced_older_invoice_not_the_newest(client, auth_headers, db):
    headers, organization_id, subscription, older = _open_invoice_context(client, auth_headers, db)
    now = datetime.now(UTC)
    older.issued_at = now - timedelta(days=2)
    newer = _add_open_invoice(db, subscription, amount_cents=older.amount_cents, issued_at=now)
    db.commit()

    response = _deliver(
        client,
        _payment_payload(
            subscription,
            older,
            event_id=f"evt_older_invoice_{uuid.uuid4().hex}",
            transaction_id=f"txn_older_{uuid.uuid4().hex}",
        ),
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Invoice, older.id).status == "paid"
    assert db.get(Invoice, newer.id).status == "open"
    assert db.get(Invoice, older.id).provider_transaction_ref.startswith("txn_older_")


def test_delayed_older_invoice_payment_uses_its_amount_not_latest_invoice(client, auth_headers, db):
    _, _, subscription, older = _open_invoice_context(client, auth_headers, db)
    older.amount_cents = 700
    newer = _add_open_invoice(
        db,
        subscription,
        amount_cents=1_900,
        issued_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    db.commit()

    response = _deliver(
        client,
        _payment_payload(
            subscription,
            older,
            event_id=f"evt_delayed_{uuid.uuid4().hex}",
            transaction_id=f"txn_delayed_{uuid.uuid4().hex}",
            amount_cents=700,
        ),
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Invoice, older.id).status == "paid"
    assert db.get(Invoice, newer.id).status == "open"


def test_same_provider_transaction_under_new_event_id_is_idempotent(client, auth_headers, db):
    _, _, subscription, paid_invoice = _open_invoice_context(client, auth_headers, db)
    other_invoice = _add_open_invoice(
        db,
        subscription,
        amount_cents=paid_invoice.amount_cents,
        issued_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    db.commit()
    transaction_id = f"txn_replayed_{uuid.uuid4().hex}"

    first = _deliver(
        client,
        _payment_payload(
            subscription,
            paid_invoice,
            event_id=f"evt_tx_first_{uuid.uuid4().hex}",
            transaction_id=transaction_id,
        ),
    )
    assert first.status_code == 200, first.text
    replay = _deliver(
        client,
        _payment_payload(
            subscription,
            paid_invoice,
            event_id=f"evt_tx_second_{uuid.uuid4().hex}",
            transaction_id=transaction_id,
        ),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "duplicate"

    db.expire_all()
    assert db.get(Invoice, paid_invoice.id).status == "paid"
    assert db.get(Invoice, other_invoice.id).status == "open"
    canonical = list(
        db.scalars(
            select(BillingEvent).where(
                BillingEvent.provider == "sandbox",
                BillingEvent.provider_transaction_id == transaction_id,
                BillingEvent.status.in_(("processed", "duplicate")),
            )
        ).all()
    )
    assert len(canonical) == 1
    assert canonical[0].invoice_id == paid_invoice.id


def test_delayed_decline_cannot_regress_a_paid_invoice_or_active_subscription(client, auth_headers, db):
    _, _, subscription, invoice = _open_invoice_context(client, auth_headers, db)
    success = _deliver(
        client,
        _payment_payload(
            subscription,
            invoice,
            event_id=f"evt_success_first_{uuid.uuid4().hex}",
            transaction_id=f"txn_success_{uuid.uuid4().hex}",
        ),
    )
    assert success.status_code == 200, success.text
    decline = _deliver(
        client,
        _payment_payload(
            subscription,
            invoice,
            event_id=f"evt_decline_late_{uuid.uuid4().hex}",
            transaction_id=f"txn_decline_{uuid.uuid4().hex}",
            event_type="payment.declined",
        ),
    )
    assert decline.status_code == 200, decline.text
    db.expire_all()
    assert db.get(Invoice, invoice.id).status == "paid"
    assert db.get(Subscription, subscription.id).status == "active"


def test_stale_ended_event_for_old_subscription_cannot_touch_replacement(client, auth_headers, db):
    headers, user = auth_headers
    organization_id = user["organization"]["id"]
    _start_subscription(client, headers, organization_id, "free")
    db.expire_all()
    old = db.scalar(
        select(Subscription).where(Subscription.organization_id == uuid.UUID(organization_id))
    )
    old_ref = old.provider_subscription_ref
    ended = client.post(
        "/api/v1/billing/subscription/cancel",
        headers=headers,
        json={"organization_id": organization_id, "at_period_end": False},
    )
    assert ended.status_code == 200, ended.text
    _start_subscription(client, headers, organization_id, "starter")
    db.expire_all()
    replacement = db.scalar(
        select(Subscription).where(
            Subscription.organization_id == uuid.UUID(organization_id),
            Subscription.status.in_(("trialing", "active", "past_due", "grace")),
        )
    )
    replacement_status = replacement.status

    response = _deliver(
        client,
        {
            "event_type": "subscription.ended",
            "event_id": f"evt_old_ended_{uuid.uuid4().hex}",
            "organization_id": organization_id,
            "provider_subscription_ref": old_ref,
        },
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Subscription, replacement.id).status == replacement_status
    assert db.get(Subscription, old.id).status == "canceled"


def test_duplicate_renewal_period_does_not_advance_or_create_another_invoice(client, auth_headers, db):
    _, _, subscription, _ = _open_invoice_context(client, auth_headers, db)
    payload = _renewal_payload(subscription, event_id=f"evt_period_one_{uuid.uuid4().hex}")
    response = _deliver(client, payload)
    assert response.status_code == 200, response.text
    db.expire_all()
    after_first = db.get(Subscription, subscription.id)
    period_end_after_first = after_first.current_period_end
    invoice_count_after_first = int(
        db.scalar(
            select(func.count()).select_from(Invoice).where(
                Invoice.subscription_id == subscription.id
            )
        )
    )

    replay = dict(payload)
    replay["event_id"] = f"evt_period_two_{uuid.uuid4().hex}"
    duplicate = _deliver(client, replay)
    assert duplicate.status_code == 200, duplicate.text
    db.expire_all()
    after_second = db.get(Subscription, subscription.id)
    invoice_count_after_second = int(
        db.scalar(
            select(func.count()).select_from(Invoice).where(
                Invoice.subscription_id == subscription.id
            )
        )
    )
    assert after_second.current_period_end == period_end_after_first
    assert invoice_count_after_second == invoice_count_after_first


def test_failure_after_notification_flush_rolls_back_settlement_before_failed_audit(
    client, auth_headers, db, monkeypatch
):
    _, organization_id, subscription, invoice = _open_invoice_context(client, auth_headers, db)
    subscription.status = "past_due"
    subscription.grace_ends_at = datetime.now(UTC) + timedelta(days=3)
    status_before = subscription.status
    grace_before = subscription.grace_ends_at
    db.commit()
    notifications_before = int(
        db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.organization_id == uuid.UUID(organization_id),
                Notification.category == "billing",
            )
        )
    )
    event_id = f"evt_atomic_fail_{uuid.uuid4().hex}"
    payload = _payment_payload(
        subscription,
        invoice,
        event_id=event_id,
        transaction_id=f"txn_atomic_{uuid.uuid4().hex}",
    )
    from app.notifications import service as notification_service

    original_create = notification_service.create_notification

    def create_then_fail(*args, **kwargs):
        assert kwargs.get("commit") is False
        created = original_create(*args, **kwargs)
        assert created is not None
        raise RuntimeError("synthetic failure after notification flush")

    monkeypatch.setattr(notification_service, "create_notification", create_then_fail)
    with pytest.raises(RuntimeError, match="synthetic failure after notification flush"):
        billing_service.process_billing_webhook(
            db,
            provider="sandbox",
            event_type="payment.succeeded",
            provider_event_id=event_id,
            payload=payload,
            signature_valid=True,
        )

    db.expire_all()
    assert db.get(Invoice, invoice.id).status == "open"
    rolled_back_subscription = db.get(Subscription, subscription.id)
    assert rolled_back_subscription.status == status_before
    assert rolled_back_subscription.grace_ends_at == grace_before
    notifications_after = int(
        db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.organization_id == uuid.UUID(organization_id),
                Notification.category == "billing",
            )
        )
    )
    assert notifications_after == notifications_before
    failed = db.scalar(
        select(BillingEvent).where(
            BillingEvent.provider == "sandbox", BillingEvent.provider_event_id == event_id
        )
    )
    assert failed is not None
    assert failed.status == "failed"
    assert "synthetic failure" in failed.error
    assert failed.invoice_id == invoice.id
    assert failed.provider_transaction_id == payload["provider_transaction_id"]

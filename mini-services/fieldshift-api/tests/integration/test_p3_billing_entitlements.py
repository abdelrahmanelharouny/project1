"""Integration: P3 billing + entitlements over HTTP (billing router,
entitlement gates on the farms/fields domain, webhook receiver).

Mirrors tests/integration/test_farms_fields_crud.py conventions. NO real
payments and NO network: the sandbox provider signs webhooks locally and
`/billing/sandbox/pay` is the only payment simulation used. Coverage:

- public plan catalog (anonymous GET /billing/plans)
- subscription start (sandbox provider, trialing), double-start 409,
  change/cancel/resume, org_admin gate
- entitlement gates: max_farms / max_fields enforced ONLY when the org has a
  live subscription (402 PAYMENT_REQUIRED structured error); pass-through
  without one
- reports_per_month quota accounting via entitlements.increment_usage
- billing webhook receiver: valid HMAC signature processes
  payment.succeeded (open invoice -> paid); invalid signature rejected
  403 and never processed; duplicate provider_event_id is idempotent
- /billing/sandbox/pay refused when the active provider is not sandbox
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models_p3 import BillingEvent, Invoice, Notification, Subscription

WEBHOOK_URL = "/api/v1/billing/webhook"


# --------------------------------------------------------------- helpers
def _register(client, display_name: str) -> tuple[dict, dict]:
    email = f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def _org_id(user: dict) -> str:
    return user["organization"]["id"]


def _start_subscription(client, headers, org, plan_code: str, period: str = "monthly") -> dict:
    resp = client.post(
        "/api/v1/billing/subscription",
        headers=headers,
        json={"organization_id": org, "plan_code": plan_code, "billing_period": period},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_farm(client, headers, name: str) -> object:
    return client.post(
        "/api/v1/farms",
        headers=headers,
        json={
            "name": name,
            "country_code": "EG",
            "timezone": "Africa/Cairo",
            "currency_code": "EGP",
        },
    )


def _create_field(client, headers, farm_id: str, name: str) -> object:
    return client.post(
        f"/api/v1/farms/{farm_id}/fields",
        headers=headers,
        json={
            "name": name,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]
                ],
            },
        },
    )


def _signed_webhook(payload: dict, *, tamper: bool = False) -> tuple[bytes, dict]:
    """Sandbox-provider signed webhook body + headers (offline HMAC)."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if tamper:
        raw = raw[:-1] + b" "  # flip one byte AFTER signing
    ts = str(int(datetime.now(UTC).timestamp()))
    mac = hmac.new(
        settings.billing_webhook_secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "x-croptwist-signature": f"{ts}.{mac}",
    }


class TestPlanCatalog:
    def test_public_catalog_anonymous(self, client):
        resp = client.get("/api/v1/billing/plans")
        assert resp.status_code == 200  # no Authorization header at all
        codes = [p["code"] for p in resp.json()["items"]]
        assert codes == ["free", "starter", "professional", "business", "enterprise"]
        by_code = {p["code"]: p for p in resp.json()["items"]}
        starter = by_code["starter"]
        assert starter["trial_days"] == 14
        monthly = [p for p in starter["prices"] if p["billing_period"] == "monthly"][0]
        assert monthly["amount_cents"] == 1900
        assert monthly["currency_code"] == "USD"
        # entitlement map is catalog data, -1 = unlimited (enterprise)
        assert by_code["free"]["entitlements"]["max_farms"] == 1
        assert by_code["enterprise"]["entitlements"]["max_farms"] == -1
        assert by_code["free"]["entitlements"]["exports_enabled"] is False
        assert by_code["starter"]["entitlements"]["exports_enabled"] is True
        # enterprise has no monthly price row -> contact sales
        assert by_code["enterprise"]["prices"] == []

    def test_unknown_plan_on_start_404(self, client, auth_headers):
        headers, user = auth_headers
        resp = client.post(
            "/api/v1/billing/subscription",
            headers=headers,
            json={"organization_id": _org_id(user), "plan_code": "platinum", "billing_period": "monthly"},
        )
        assert resp.status_code == 404


class TestSubscriptionLifecycle:
    def test_start_subscription_sandbox_trialing(self, client, auth_headers):
        headers, user = auth_headers
        result = _start_subscription(client, headers, _org_id(user), "starter")
        sub = result["subscription"]
        assert sub["status"] == "trialing"  # starter carries a 14-day trial
        assert sub["provider"] == "sandbox"
        assert sub["provider_mode"] == "test"
        assert sub["plan"]["code"] == "starter"
        checkout = result["checkout"]
        assert checkout["provider"] == "sandbox"
        assert checkout["mode"] == "test"
        assert checkout["url"] is None  # sandbox has no hosted checkout

    def test_start_paid_plan_without_trial_is_active_with_invoice(self, client, auth_headers):
        headers, user = auth_headers
        result = _start_subscription(client, headers, _org_id(user), "free")
        assert result["subscription"]["status"] == "active"  # free: no trial
        invoices = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": _org_id(user)}
        ).json()
        assert invoices["total"] == 1
        invoice = invoices["items"][0]
        assert invoice["amount_cents"] == 0  # sandbox truth: $0, no money moved
        assert invoice["status"] == "paid"
        assert invoice["paid_at"] is not None

    def test_double_start_conflicts(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "starter")
        resp = client.post(
            "/api/v1/billing/subscription",
            headers=headers,
            json={"organization_id": _org_id(user), "plan_code": "free", "billing_period": "monthly"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    def test_subscription_routes_require_org_admin(self, client):
        a_headers, a_user = _register(client, "Alice")
        _start_subscription(client, a_headers, _org_id(a_user), "starter")
        b_headers, _b = _register(client, "Bob")
        resp = client.get(
            "/api/v1/billing/subscription", headers=b_headers, params={"organization_id": _org_id(a_user)}
        )
        assert resp.status_code == 403
        resp = client.post(
            "/api/v1/billing/subscription",
            headers=b_headers,
            json={"organization_id": _org_id(a_user), "plan_code": "free", "billing_period": "monthly"},
        )
        assert resp.status_code == 403

    def test_change_plan_immediate(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "free")
        changed = client.post(
            "/api/v1/billing/subscription/change",
            headers=headers,
            json={"organization_id": _org_id(user), "new_plan_code": "professional"},
        )
        assert changed.status_code == 200
        assert changed.json()["plan"]["code"] == "professional"
        assert changed.json()["status"] == "active"

    def test_cancel_at_period_end_and_resume(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "starter")
        canceled = client.post(
            "/api/v1/billing/subscription/cancel",
            headers=headers,
            json={"organization_id": _org_id(user), "at_period_end": True},
        )
        assert canceled.status_code == 200
        assert canceled.json()["cancel_at_period_end"] is True
        assert canceled.json()["status"] == "trialing"  # still live until period end
        resumed = client.post(
            "/api/v1/billing/subscription/resume",
            headers=headers,
            json={"organization_id": _org_id(user)},
        )
        assert resumed.status_code == 200
        assert resumed.json()["cancel_at_period_end"] is False

    def test_entitlements_free_floor_without_subscription(self, client, auth_headers):
        headers, user = auth_headers
        resp = client.get(
            "/api/v1/billing/entitlements",
            headers=headers,
            params={"organization_id": _org_id(user)},
        )
        assert resp.status_code == 200
        entitlements = resp.json()["entitlements"]
        # no live subscription -> the free-plan floor applies
        assert entitlements["max_farms"]["value"] == 1
        assert entitlements["max_farms"]["plan_code"] == "free"
        assert entitlements["exports_enabled"]["value"] is False

    def test_usage_snapshot_shape(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "starter")
        usage = client.get(
            "/api/v1/billing/usage", headers=headers, params={"organization_id": _org_id(user)}
        ).json()
        keys = {item["key"] for item in usage["items"]}
        assert {"max_farms", "max_fields", "reports_per_month"} <= keys
        for item in usage["items"]:
            assert item["used"] == 0  # nothing consumed yet


class TestEntitlementEnforcement:
    def test_farm_limit_enforced_with_live_subscription(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "free")  # max_farms = 1
        first = _create_farm(client, headers, "First Farm")
        assert first.status_code == 201, first.text
        second = _create_farm(client, headers, "Second Farm")
        assert second.status_code == 402  # PAYMENT_REQUIRED -> upgrade signal
        err = second.json()["error"]
        assert err["code"] == "PAYMENT_REQUIRED"
        assert "max_farms" in err["message"]

    def test_field_limit_enforced_with_live_subscription(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "free")  # max_fields = 3
        farm = _create_farm(client, headers, "Free Farm").json()
        for i in range(3):
            created = _create_field(client, headers, farm["id"], f"Field {i}")
            assert created.status_code == 201, created.text
        fourth = _create_field(client, headers, farm["id"], "Field 3")
        assert fourth.status_code == 402
        assert fourth.json()["error"]["code"] == "PAYMENT_REQUIRED"
        assert "max_fields" in fourth.json()["error"]["message"]

    def test_free_plan_limits_apply_without_live_subscription(self, client, auth_headers):
        # Missing subscription resolves to the explicit Free plan rather than
        # bypassing the product's farm/field quotas.
        headers, user = auth_headers
        first = _create_farm(client, headers, "Farm One")
        second = _create_farm(client, headers, "Farm Two")
        assert first.status_code == 201
        assert second.status_code == 402
        farm_id = first.json()["id"]
        for i in range(3):
            assert _create_field(client, headers, farm_id, f"Free Field {i}").status_code == 201
        fourth = _create_field(client, headers, farm_id, "Free Field 3")
        assert fourth.status_code == 402

    def test_higher_plan_raises_the_limit(self, client, auth_headers):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "starter")  # max_farms = 2
        assert _create_farm(client, headers, "Farm One").status_code == 201
        assert _create_farm(client, headers, "Farm Two").status_code == 201
        third = _create_farm(client, headers, "Farm Three")
        assert third.status_code == 402


class TestSandboxPaymentSimulation:
    def test_sandbox_pay_processes_through_webhook_pipeline(self, client, auth_headers, db):
        headers, user = auth_headers
        org = _org_id(user)
        _start_subscription(client, headers, org, "starter")
        subscription = db.scalar(
            select(Subscription).where(Subscription.organization_id == uuid.UUID(org))
        )
        invoice = Invoice(
            organization_id=uuid.UUID(org),
            subscription_id=subscription.id,
            number=f"CT-TEST-{uuid.uuid4().hex[:8]}",
            status="open",
            amount_cents=1900,
            currency_code="USD",
            period_start=subscription.current_period_start.date(),
            period_end=subscription.current_period_end.date(),
            issued_at=datetime.now(UTC),
            provider_ref=subscription.provider_subscription_ref,
            provider_invoice_ref=f"inv_test_{uuid.uuid4().hex}",
        )
        db.add(invoice)
        db.commit()
        resp = client.post(
            "/api/v1/billing/sandbox/pay",
            headers=headers,
            json={"organization_id": org, "outcome": "succeeded"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "processed"
        assert body["outcome"] == "succeeded"
        snapshot = client.get(
            "/api/v1/billing/subscription", headers=headers, params={"organization_id": org}
        ).json()
        assert snapshot["subscription"]["provider"] == "sandbox"
        assert snapshot["subscription"]["provider_mode"] == "test"
        event = db.get(BillingEvent, uuid.UUID(body["billing_event_id"]))
        assert event.provider == "sandbox"
        assert event.invoice_id == invoice.id
        assert event.provider_transaction_id.startswith("txn_sandbox_")
        assert event.provider_subscription_ref == subscription.provider_subscription_ref
        # the simulated provider payment also produced the billing notification
        notifs = client.get("/api/v1/notifications", headers=headers).json()
        assert any(
            n["category"] == "billing" and n["title"] == "Payment received"
            for n in notifs["items"]
        )

    def test_sandbox_pay_refused_for_non_sandbox_provider(self, client, auth_headers, monkeypatch):
        headers, user = auth_headers
        _start_subscription(client, headers, _org_id(user), "starter")
        monkeypatch.setattr(settings, "billing_provider", "stripe")  # not wired
        resp = client.post(
            "/api/v1/billing/sandbox/pay",
            headers=headers,
            json={"organization_id": _org_id(user), "outcome": "succeeded"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"


class TestBillingWebhookReceiver:
    def _org_with_open_invoice(self, client, auth_headers, db) -> tuple[dict, str]:
        """free (active, $0 invoice) -> change to starter -> renewal_due
        webhook creates an OPEN invoice for 1900 cents."""
        headers, user = auth_headers
        org = _org_id(user)
        _start_subscription(client, headers, org, "free")
        assert (
            client.post(
                "/api/v1/billing/subscription/change",
                headers=headers,
                json={"organization_id": org, "new_plan_code": "starter"},
            ).status_code
            == 200
        )
        subscription = db.scalar(
            select(Subscription).where(Subscription.organization_id == uuid.UUID(org))
        )
        renewal = {
            "event_type": "subscription.renewal_due",
            "event_id": f"evt_renew_{uuid.uuid4().hex}",
            "organization_id": org,
            "provider_subscription_ref": subscription.provider_subscription_ref,
            "period_start": subscription.current_period_end.isoformat(),
        }
        raw, sig_headers = _signed_webhook(renewal)
        resp = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processed"
        return headers, org

    def test_valid_signature_processes_payment_and_marks_invoice_paid(
        self, client, auth_headers, db
    ):
        headers, org = self._org_with_open_invoice(client, auth_headers, db)
        before = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()
        open_invoices = [i for i in before["items"] if i["status"] == "open"]
        assert len(open_invoices) == 1
        assert open_invoices[0]["amount_cents"] == 1900
        invoice = db.get(Invoice, uuid.UUID(open_invoices[0]["id"]))
        subscription = db.scalar(
            select(Subscription).where(Subscription.organization_id == uuid.UUID(org))
        )

        event_id = f"evt_pay_{uuid.uuid4().hex}"
        raw, sig_headers = _signed_webhook(
            {
                "event_type": "payment.succeeded",
                "event_id": event_id,
                "organization_id": org,
                "provider_subscription_ref": subscription.provider_subscription_ref,
                "invoice_id": str(invoice.id),
                "provider_invoice_ref": invoice.provider_invoice_ref,
                "provider_transaction_id": f"txn_pay_{uuid.uuid4().hex}",
                "amount_cents": 1900,
                "currency": "USD",
            }
        )
        resp = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processed"

        after = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()
        assert after["total"] == before["total"]  # no new invoice was created
        paid = [i for i in after["items"] if i["status"] == "paid" and i["amount_cents"] == 1900]
        assert len(paid) == 1
        assert paid[0]["paid_at"] is not None
        # exactly one billing event row for the provider event id
        rows = list(
            db.scalars(select(BillingEvent).where(BillingEvent.provider_event_id == event_id)).all()
        )
        assert len(rows) == 1
        assert rows[0].status == "processed"
        assert rows[0].signature_valid is True

    def test_invalid_signature_rejected_and_never_processed(self, client, auth_headers, db):
        headers, user = auth_headers
        org = _org_id(user)
        _start_subscription(client, headers, org, "free")
        snapshot = client.get(
            "/api/v1/billing/subscription", headers=headers, params={"organization_id": org}
        ).json()
        invoices_before = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()["total"]

        raw, sig_headers = _signed_webhook(
            {
                "event_type": "payment.succeeded",
                "event_id": f"evt_bad_{uuid.uuid4().hex}",
                "organization_id": org,
                "amount_cents": 990000,
            },
            tamper=True,  # body flipped after signing
        )
        resp = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

        # nothing changed: same invoice count, subscription untouched
        invoices_after = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()["total"]
        assert invoices_after == invoices_before
        snapshot_after = client.get(
            "/api/v1/billing/subscription", headers=headers, params={"organization_id": org}
        ).json()
        assert snapshot_after["subscription"]["status"] == snapshot["subscription"]["status"]

        # the rejection is recorded for audit, flagged invalid + failed
        rows = list(db.scalars(select(BillingEvent).where(BillingEvent.status == "failed")).all())
        assert len(rows) == 1
        assert rows[0].signature_valid is False
        assert rows[0].error == "invalid webhook signature"
        # the failed row carries no payload (never processed)
        assert rows[0].payload == {}

    def test_duplicate_provider_event_id_is_idempotent(self, client, auth_headers, db):
        headers, org = self._org_with_open_invoice(client, auth_headers, db)
        invoice = db.scalar(
            select(Invoice).where(
                Invoice.organization_id == uuid.UUID(org), Invoice.status == "open"
            )
        )
        subscription = db.scalar(
            select(Subscription).where(Subscription.organization_id == uuid.UUID(org))
        )
        event_id = f"evt_dup_{uuid.uuid4().hex}"
        payload = {
            "event_type": "payment.succeeded",
            "event_id": event_id,
            "organization_id": org,
            "provider_subscription_ref": subscription.provider_subscription_ref,
            "invoice_id": str(invoice.id),
            "provider_invoice_ref": invoice.provider_invoice_ref,
            "provider_transaction_id": f"txn_dup_{uuid.uuid4().hex}",
            "amount_cents": 1900,
            "currency": "USD",
        }
        raw, sig_headers = _signed_webhook(payload)
        first = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert first.status_code == 200
        assert first.json()["status"] == "processed"

        invoices_after_first = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()["total"]

        replay = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert replay.status_code == 200
        assert replay.json()["status"] == "duplicate"

        # idempotency: no second invoice, no second billing event row
        invoices_after_replay = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()["total"]
        assert invoices_after_replay == invoices_after_first
        rows = list(
            db.scalars(select(BillingEvent).where(BillingEvent.provider_event_id == event_id)).all()
        )
        assert len(rows) == 1
        assert rows[0].status == "duplicate"

    def test_payment_amount_or_currency_mismatch_cannot_settle_invoice(
        self, client, auth_headers, db
    ):
        headers, org = self._org_with_open_invoice(client, auth_headers, db)
        invoice = db.scalar(
            select(Invoice).where(
                Invoice.organization_id == uuid.UUID(org), Invoice.status == "open"
            )
        )
        subscription = db.scalar(
            select(Subscription).where(Subscription.organization_id == uuid.UUID(org))
        )
        status_before = subscription.status
        notifications_before = int(
            db.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.organization_id == uuid.UUID(org),
                    Notification.category == "billing",
                )
            )
        )
        for amount, currency in ((1899, "USD"), (1900, "EUR")):
            raw, sig_headers = _signed_webhook(
                {
                    "event_type": "payment.succeeded",
                    "event_id": f"evt_mismatch_{uuid.uuid4().hex}",
                    "organization_id": org,
                    "provider_subscription_ref": subscription.provider_subscription_ref,
                    "invoice_id": str(invoice.id),
                    "provider_invoice_ref": invoice.provider_invoice_ref,
                    "provider_transaction_id": f"txn_mismatch_{uuid.uuid4().hex}",
                    "amount_cents": amount,
                    "currency": currency,
                }
            )
            response = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
            assert response.status_code == 422
        invoices = client.get(
            "/api/v1/billing/invoices", headers=headers, params={"organization_id": org}
        ).json()
        assert any(invoice["status"] == "open" for invoice in invoices["items"])
        db.expire_all()
        assert db.get(Invoice, invoice.id).status == "open"
        assert db.get(Subscription, subscription.id).status == status_before
        notifications_after = int(
            db.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.organization_id == uuid.UUID(org),
                    Notification.category == "billing",
                )
            )
        )
        assert notifications_after == notifications_before

    def test_unparsable_body_rejected(self, client, db):
        """A non-JSON body is recorded as an invalid event and rejected. The
        receiver verifies signatures over raw bytes; an unparsable body can
        never match, so the pipeline treats it as signature-invalid (403)."""
        resp = client.post(
            WEBHOOK_URL,
            content=b"not-json",
            headers={"Content-Type": "application/json", "x-croptwist-signature": "1.aa"},
        )
        assert resp.status_code == 403
        rows = list(db.scalars(select(BillingEvent).where(BillingEvent.status == "failed")).all())
        assert len(rows) == 1
        assert rows[0].event_type == "invalid.payload"

    def test_missing_fields_rejected(self, client):
        raw, sig_headers = _signed_webhook({"event_type": "payment.succeeded"})  # no event_id
        resp = client.post(WEBHOOK_URL, content=raw, headers=sig_headers)
        assert resp.status_code == 422


class TestReportsQuotaAccounting:
    def test_quota_enforced_after_increment_usage(self, client, auth_headers, db):
        from app.billing import entitlements

        headers, user = auth_headers
        org = _org_id(user)
        _start_subscription(client, headers, org, "starter")  # reports_per_month = 15

        # first report renders inline and consumes one unit of the quota
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "succeeded"

        usage = client.get(
            "/api/v1/billing/usage", headers=headers, params={"organization_id": org}
        ).json()
        reports_usage = [u for u in usage["items"] if u["key"] == "reports_per_month"][0]
        assert reports_usage["used"] == 1
        assert reports_usage["limit"] == 15

        # simulate the rest of the period's consumption via the entitlement
        # engine (the same accounting path the report executor uses)
        used = entitlements.increment_usage(db, uuid.UUID(org), "reports_per_month", amount=14)
        assert used == 15
        db.commit()

        exhausted = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        assert exhausted.status_code == 402
        err = exhausted.json()["error"]
        assert err["code"] == "PAYMENT_REQUIRED"
        assert "reports_per_month" in err["message"]


class TestOrgMemberSeatCap:
    """max_org_members enforcement on invitation acceptance (P3 §4.2).

    Missing subscriptions resolve to the catalog's Free plan, so the cap is
    enforced consistently before and after billing activation.
    """

    def test_seat_cap_free_plan_blocks_third_member_and_upgrade_unlocks(self, client):
        a_headers, a = _register(client, "SeatOwner")
        org = _org_id(a)
        b_headers, b = _register(client, "SeatBob")
        c_headers, c = _register(client, "SeatCarol")
        d_headers, d = _register(client, "SeatDana")

        def invite(email, role):
            inv = client.post(
                f"/api/v1/orgs/{org}/invitations",
                headers=a_headers,
                json={"email": email, "role_code": role},
            )
            assert inv.status_code == 201, inv.text
            return inv.json()["token"]

        def accept(headers_invitee, token):
            return client.post(
                "/api/v1/invitations/accept", headers=headers_invitee, json={"token": token}
            )

        # No subscription resolves to Free: A already holds the only seat.
        bob_token = invite(b["user"]["email"], "viewer")
        blocked_bob = accept(b_headers, bob_token)
        assert blocked_bob.status_code == 402, blocked_bob.text

        # Upgrade unlocks three seats. The still-pending invitation can now be
        # accepted, and the fourth member remains blocked.
        _start_subscription(client, a_headers, org, "starter")
        assert accept(b_headers, bob_token).status_code == 200
        carol_token = invite(c["user"]["email"], "viewer")
        assert accept(c_headers, carol_token).status_code == 200
        fourth = accept(d_headers, invite(d["user"]["email"], "viewer"))
        assert fourth.status_code == 402, fourth.text
        assert "max_org_members" in fourth.json()["error"]["message"]

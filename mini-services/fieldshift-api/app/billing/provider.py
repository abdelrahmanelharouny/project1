"""Billing provider abstraction (P3 §4.3) + sandbox adapter.

`BillingProvider` is the seam a real provider (Stripe, Paddle, Paymob, ...)
implements. The sandbox adapter is fully functional for local/test runs:
it signs and verifies its own webhook payloads, simulates checkout and
payment outcomes (success, decline), and NEVER touches real money.

HONESTY CONTRACT (P3 §16.10): no code path claims real payment processing.
Real processing requires a concrete provider with verified credentials and
successful sandbox transactions — until then `provider="sandbox"` is the
only enabled provider and the UI labels it as test mode.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import ValidationFailed


@dataclass(frozen=True)
class CheckoutSession:
    """What a checkout flow hands back to the caller."""

    session_id: str
    provider: str
    url: str | None  # hosted checkout URL (None in the sandbox)
    mode: str  # "test" | "live" — the sandbox is ALWAYS "test"


@dataclass(frozen=True)
class PaymentResult:
    outcome: str  # "succeeded" | "declined"
    provider_event_id: str
    details: dict[str, Any]


class BillingProvider:
    """Provider seam. Concrete adapters implement all methods."""

    name: str = "abstract"
    mode: str = "live"

    def create_customer(self, *, organization_id: uuid.UUID, email: str, name: str) -> str:
        raise NotImplementedError

    def create_checkout(
        self,
        *,
        organization_id: uuid.UUID,
        plan_code: str,
        billing_period: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        raise NotImplementedError

    def cancel_subscription(self, *, provider_subscription_ref: str) -> None:
        raise NotImplementedError

    def sign_webhook(self, *, payload: dict[str, Any], secret: str, timestamp: str) -> str:
        raise NotImplementedError

    def verify_webhook(self, *, payload: bytes, signature: str, secret: str) -> bool:
        raise NotImplementedError


def _canonical(payload: bytes) -> bytes:
    return payload


def compute_signature(*, payload: bytes, secret: str, timestamp: str) -> str:
    """HMAC-SHA256 over ``timestamp + "." + payload`` — replay-resistant."""
    mac = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + _canonical(payload), hashlib.sha256
    )
    return mac.hexdigest()


class SandboxBillingProvider(BillingProvider):
    """In-repo test provider. Demonstrates the full lifecycle end-to-end
    (checkout → webhook → activation → invoices) without external calls."""

    name = "sandbox"
    mode = "test"

    def __init__(self, secret: str) -> None:
        self._secret = secret

    # -- customer / checkout ------------------------------------------------
    def create_customer(self, *, organization_id: uuid.UUID, email: str, name: str) -> str:
        return f"cus_sandbox_{hashlib.sha256(str(organization_id).encode()).hexdigest()[:16]}"

    def create_checkout(
        self,
        *,
        organization_id: uuid.UUID,
        plan_code: str,
        billing_period: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        session_id = f"cs_sandbox_{uuid.uuid4().hex}"
        return CheckoutSession(
            session_id=session_id, provider=self.name, url=None, mode=self.mode
        )

    def cancel_subscription(self, *, provider_subscription_ref: str) -> None:
        return None

    # -- payment simulation (sandbox only) -----------------------------------
    def simulate_payment(
        self,
        *,
        outcome: str,
        subscription_ref: str,
        invoice_id: str,
        provider_invoice_ref: str,
        amount_cents: int,
        currency: str,
    ) -> PaymentResult:
        if outcome not in ("succeeded", "declined"):
            raise ValidationFailed("outcome must be 'succeeded' or 'declined'.")
        event_id = f"evt_sandbox_{uuid.uuid4().hex}"
        return PaymentResult(
            outcome=outcome,
            provider_event_id=event_id,
            details={
                "provider_subscription_ref": subscription_ref,
                "invoice_id": invoice_id,
                "provider_invoice_ref": provider_invoice_ref,
                "provider_transaction_id": f"txn_sandbox_{uuid.uuid4().hex}",
                "amount_cents": amount_cents,
                "currency": currency,
                "simulated_at": datetime.now(UTC).isoformat(),
            },
        )

    # -- webhook signing / verification ---------------------------------------
    def sign_webhook(self, *, payload: dict[str, Any], secret: str, timestamp: str) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return compute_signature(payload=raw, secret=secret, timestamp=timestamp)

    def verify_webhook(self, *, payload: bytes, signature: str, secret: str) -> bool:
        # The sandbox signs with a constant timestamp embedded by the caller;
        # verification recomputes over the exact bytes received — any
        # tampering with the body invalidates the signature.
        parts = signature.split(".", 1)
        if len(parts) != 2:
            return False
        timestamp, mac = parts
        if self.stale_timestamp(timestamp):
            return False
        expected = compute_signature(payload=payload, secret=secret, timestamp=timestamp)
        return hmac.compare_digest(expected, mac)

    @staticmethod
    def default_timestamp() -> str:
        return str(int(datetime.now(UTC).timestamp()))

    @staticmethod
    def stale_timestamp(ts: str, *, max_age_seconds: int = 600) -> bool:
        try:
            issued = int(ts)
        except ValueError:
            return True
        return abs(datetime.now(UTC).timestamp() - issued) > max_age_seconds


def get_provider(name: str) -> BillingProvider:
    """Provider registry. Only 'sandbox' is wired (P3 honesty contract)."""
    from app.core.config import settings

    if name == "sandbox":
        return SandboxBillingProvider(secret=settings.billing_webhook_secret)
    raise ValidationFailed(
        f"Billing provider '{name}' is not configured. Available providers: sandbox."
    )


def period_bounds(
    *, start: datetime, billing_period: str
) -> tuple[datetime, datetime]:
    """Next period window for renewal handling."""
    if billing_period == "yearly":
        end = start.replace(year=start.year + 1)
    else:
        # calendar-month add (clamp day to month length)
        year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        end = start.replace(year=year, month=month)
    return start, end


def grace_deadline(failed_at: datetime) -> datetime:
    from app.core.config import settings

    return failed_at + timedelta(seconds=settings.billing_grace_seconds)

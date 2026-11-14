"""Pure regressions for invoice-bound provider callback identity."""

import uuid
from datetime import UTC, datetime

import pytest

from app.billing.provider import SandboxBillingProvider
from app.billing.service import _parse_callback_identity
from app.core.errors import ValidationFailed


def test_payment_callback_requires_exact_invoice_transaction_and_subscription():
    invoice_id = uuid.uuid4()
    parsed = _parse_callback_identity(
        "payment.succeeded",
        {
            "organization_id": str(uuid.uuid4()),
            "provider_subscription_ref": "sub_sandbox_exact",
            "invoice_id": str(invoice_id),
            "provider_invoice_ref": "inv_sandbox_exact",
            "provider_transaction_id": "txn_sandbox_exact",
            "amount_cents": 1_900,
            "currency": "usd",
        },
    )

    assert parsed["invoice_id"] == invoice_id
    assert parsed["provider_transaction_id"] == "txn_sandbox_exact"
    assert parsed["provider_subscription_ref"] == "sub_sandbox_exact"
    assert parsed["provider_invoice_ref"] == "inv_sandbox_exact"
    assert parsed["amount_cents"] == 1_900
    assert parsed["currency_code"] == "USD"


@pytest.mark.parametrize(
    "missing_field",
    ("invoice_id", "provider_transaction_id", "provider_subscription_ref"),
)
def test_payment_callback_missing_any_identity_is_rejected(missing_field):
    payload = {
        "organization_id": str(uuid.uuid4()),
        "provider_subscription_ref": "sub_sandbox_exact",
        "invoice_id": str(uuid.uuid4()),
        "provider_invoice_ref": "inv_sandbox_exact",
        "provider_transaction_id": "txn_sandbox_exact",
        "amount_cents": 1_900,
        "currency": "USD",
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationFailed):
        _parse_callback_identity("payment.succeeded", payload)


def test_payment_amount_must_be_integer_minor_units_and_currency_three_letters():
    base = {
        "organization_id": str(uuid.uuid4()),
        "provider_subscription_ref": "sub_sandbox_exact",
        "invoice_id": str(uuid.uuid4()),
        "provider_transaction_id": "txn_sandbox_exact",
        "amount_cents": True,
        "currency": "USD",
    }
    with pytest.raises(ValidationFailed, match="integer amount_cents"):
        _parse_callback_identity("payment.succeeded", base)

    base["amount_cents"] = 1_900
    base["currency"] = "US"
    with pytest.raises(ValidationFailed, match="three-letter"):
        _parse_callback_identity("payment.succeeded", base)


def test_renewal_callback_requires_timezone_and_period_identity():
    base = {
        "organization_id": str(uuid.uuid4()),
        "provider_subscription_ref": "sub_sandbox_exact",
        "period_start": "2026-11-14T00:00:00+00:00",
    }
    parsed = _parse_callback_identity("subscription.renewal_due", base)
    assert parsed["period_start"] == datetime(2026, 11, 14, tzinfo=UTC)

    base["period_start"] = "2026-11-14T00:00:00"
    with pytest.raises(ValidationFailed, match="timezone"):
        _parse_callback_identity("subscription.renewal_due", base)


def test_sandbox_simulation_emits_exact_synthetic_payment_identity():
    provider = SandboxBillingProvider(secret="synthetic-test-secret")
    result = provider.simulate_payment(
        outcome="succeeded",
        subscription_ref="sub_sandbox_synthetic",
        invoice_id="11111111-1111-4111-8111-111111111111",
        provider_invoice_ref="inv_sandbox_synthetic",
        amount_cents=1_900,
        currency="USD",
    )

    assert provider.name == "sandbox"
    assert provider.mode == "test"
    assert result.details["provider_subscription_ref"] == "sub_sandbox_synthetic"
    assert result.details["invoice_id"] == "11111111-1111-4111-8111-111111111111"
    assert result.details["provider_invoice_ref"] == "inv_sandbox_synthetic"
    assert result.details["provider_transaction_id"].startswith("txn_sandbox_")
    assert result.details["amount_cents"] == 1_900
    assert result.details["currency"] == "USD"

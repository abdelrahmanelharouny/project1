import pytest

from app.core.config import Settings


def test_production_refuses_sandbox_billing_provider():
    with pytest.raises(ValueError, match="sandbox billing provider"):
        Settings(environment="production", dev_mode=False)


def test_billing_webhook_secret_has_no_predictable_default():
    assert Settings().billing_webhook_secret == ""


def test_production_refuses_dev_mode_even_with_strong_secret():
    with pytest.raises(ValueError, match="DEV_MODE"):
        Settings(
            environment="production",
            dev_mode=True,
            billing_provider="stripe",
            billing_webhook_secret="x" * 40,
        )


def test_production_refuses_unknown_or_unimplemented_provider():
    with pytest.raises(ValueError, match="No production billing adapter"):
        Settings(
            environment="production",
            dev_mode=False,
            billing_provider="stripe",
            billing_webhook_secret="x" * 40,
        )

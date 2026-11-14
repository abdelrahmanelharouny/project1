"""Identity email delivery adapters and safe failure mapping.

A direct TLS-protected SMTP adapter is provided for configured deployments;
callers may inject a fake adapter in tests. Challenge plaintext is passed only
in the message body and is never logged or persisted by this module.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.errors import CropTwistError
from app.domains.identity.delivery_config import (
    SMTPConfigurationError,
    SMTPSettings,
    load_smtp_settings,
)

logger = logging.getLogger(__name__)


class EmailDeliveryUnavailable(CropTwistError):
    """No safe delivery configuration exists or an email could not be sent."""

    status_code = 503
    code = "EMAIL_DELIVERY_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(
            "Email delivery is unavailable. Configure a secure SMTP adapter and retry."
        )


class EmailDeliveryAdapter(Protocol):
    def send_email(self, recipient: str, subject: str, text_body: str) -> None:
        """Send a text-only message or raise if delivery fails."""


class SMTPEmailDeliveryAdapter:
    """Small synchronous SMTP adapter with mandatory TLS and bounded sockets."""

    def __init__(self, config: SMTPSettings):
        self.config = config

    def send_email(self, recipient: str, subject: str, text_body: str) -> None:
        message = EmailMessage()
        message["From"] = self.config.from_address
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text_body)
        context = ssl.create_default_context()
        try:
            if self.config.tls_mode == "ssl":
                with smtplib.SMTP_SSL(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                    context=context,
                ) as smtp:
                    self._authenticate(smtp)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                ) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                    self._authenticate(smtp)
                    smtp.send_message(message)
        except (OSError, TimeoutError, smtplib.SMTPException) as exc:
            # Provider error text can include recipient/server details. Keep it
            # in process logs only as a generic event; never expose credentials
            # or SMTP responses to the caller.
            logger.warning("SMTP challenge delivery failed (%s)", type(exc).__name__)
            raise EmailDeliveryUnavailable() from None

    def _authenticate(self, smtp: smtplib.SMTP | smtplib.SMTP_SSL) -> None:
        if self.config.username is not None and self.config.password is not None:
            smtp.login(self.config.username, self.config.password)


def get_email_delivery_adapter() -> EmailDeliveryAdapter | None:
    """Build an adapter from environment-only settings, if configured."""
    try:
        config = load_smtp_settings()
    except SMTPConfigurationError:
        raise EmailDeliveryUnavailable() from None
    return SMTPEmailDeliveryAdapter(config) if config is not None else None


def require_email_delivery_adapter(
    injected: EmailDeliveryAdapter | None = None,
) -> EmailDeliveryAdapter:
    """Return an injected/configured adapter or raise an explicit 503 error."""
    adapter = injected if injected is not None else get_email_delivery_adapter()
    if adapter is None:
        raise EmailDeliveryUnavailable()
    return adapter


def send_or_rollback(
    db: Session,
    adapter: EmailDeliveryAdapter,
    recipient: str,
    subject: str,
    text_body: str,
) -> None:
    """Send while the challenge transaction is open; rollback on send failure."""
    try:
        adapter.send_email(recipient, subject, text_body)
    except Exception as exc:
        db.rollback()
        if isinstance(exc, EmailDeliveryUnavailable):
            raise
        raise EmailDeliveryUnavailable() from None

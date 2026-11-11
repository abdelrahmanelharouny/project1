"""Notification delivery channels (P3 W5.3) — the email adapter seam.

The notification center writes in-app rows only; OUT-OF-BAND delivery goes
through a `NotificationChannel`. This module is the seam named in
`app/notifications/service.py` docstrings: an adapter protocol plus a
registry-style factory, mirroring the billing provider seam
(`app/billing/provider.py`).

HONESTY CONTRACT (P3 §16.10): the only wired channel is `LoggingEmailChannel`,
which LOGS the message and reports `sent=False`. No code path claims that
email was delivered. A real SMTP/provider adapter must be implemented,
registered in `_REGISTRY` and selected via configuration before any
"email sent" claim is made — until then `email_enabled` preferences are
recorded but produce no outbound mail.
"""

import logging
from typing import Any, Protocol

from app.core.errors import ValidationFailed

logger = logging.getLogger("croptwist.notifications.channels")


class NotificationChannel(Protocol):
    """Delivery adapter seam. Implementations MUST be honest: the returned
    mapping states whether the message actually left the system."""

    name: str
    mode: str  # "test" | "live" — logging channel is ALWAYS "test"

    def deliver_email(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver (or honestly not deliver) one email. Returns a result map
        with at least {"channel", "sent", "reason"}."""
        ...


class LoggingEmailChannel:
    """Default channel: writes the email to the application log INSTEAD of
    sending it. Honest no-op — used whenever no real mail transport is
    configured (the sandbox default, and every current deployment)."""

    name = "log"
    mode = "test"

    def deliver_email(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "email NOT sent (logging channel): to=%s subject=%r meta=%s body=%r",
            recipient,
            subject,
            meta or {},
            body[:500],
        )
        return {
            "channel": self.name,
            "sent": False,
            "reason": (
                "logging channel — no email transport is configured; the "
                "message was logged, not delivered"
            ),
        }


# Channel registry. Only the logging channel is wired (P3 honesty contract).
_REGISTRY: dict[str, type] = {
    LoggingEmailChannel.name: LoggingEmailChannel,
}


def get_channel(name: str | None = None) -> NotificationChannel:
    """Channel factory.

    Selects `name`, defaulting to `settings.email_channel` when present and
    "log" otherwise (the setting is optional — absent configuration MUST NOT
    break notification flows). Unknown channel names raise ValidationFailed
    instead of silently falling back, so a misconfiguration is loud.
    """
    from app.core.config import settings

    selected = name or str(getattr(settings, "email_channel", "") or "log")
    channel_cls = _REGISTRY.get(selected)
    if channel_cls is None:
        raise ValidationFailed(
            f"Notification channel '{selected}' is not configured. "
            f"Available channels: {', '.join(sorted(_REGISTRY))}."
        )
    return channel_cls()

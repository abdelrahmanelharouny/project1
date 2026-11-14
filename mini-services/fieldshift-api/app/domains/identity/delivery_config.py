"""Environment-only SMTP configuration for identity challenge delivery.

No dotenv/config-file lookup is performed here: production credentials must
arrive through the process environment or the deployment secret manager.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class SMTPConfigurationError(ValueError):
    """SMTP settings are partially configured or unsafe."""


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    from_address: str
    tls_mode: str
    timeout_seconds: float
    username: str | None = None
    password: str | None = None


def load_smtp_settings(environ: dict[str, str] | None = None) -> SMTPSettings | None:
    """Read SMTP settings from ``FIELDSHIFT_EMAIL_SMTP_*`` variables only.

    Returns ``None`` only when no SMTP setting is configured. A partial or
    invalid configuration raises rather than silently behaving as an absent
    adapter. TLS is mandatory; socket timeouts are bounded to 1–30 seconds.
    """
    source = os.environ if environ is None else environ
    prefix = "FIELDSHIFT_EMAIL_SMTP_"
    names = (
        "HOST",
        "PORT",
        "FROM_ADDRESS",
        "TLS_MODE",
        "TIMEOUT_SECONDS",
        "USERNAME",
        "PASSWORD",
    )
    values = {name: source.get(prefix + name, "").strip() for name in names}
    if not any(values.values()):
        return None
    if not values["HOST"] or not values["FROM_ADDRESS"]:
        raise SMTPConfigurationError("SMTP host and sender address are required.")

    try:
        port = int(values["PORT"] or "587")
        timeout = float(values["TIMEOUT_SECONDS"] or "10")
    except ValueError as exc:
        raise SMTPConfigurationError("SMTP port or timeout is invalid.") from exc
    if not 1 <= port <= 65535:
        raise SMTPConfigurationError("SMTP port must be between 1 and 65535.")
    if not 1 <= timeout <= 30:
        raise SMTPConfigurationError("SMTP timeout must be between 1 and 30 seconds.")

    tls_mode = (values["TLS_MODE"] or "starttls").lower()
    if tls_mode not in {"starttls", "ssl"}:
        raise SMTPConfigurationError("SMTP TLS mode must be 'starttls' or 'ssl'.")
    if bool(values["USERNAME"]) != bool(values["PASSWORD"]):
        raise SMTPConfigurationError("SMTP username and password must be configured together.")

    return SMTPSettings(
        host=values["HOST"],
        port=port,
        from_address=values["FROM_ADDRESS"],
        tls_mode=tls_mode,
        timeout_seconds=timeout,
        username=values["USERNAME"] or None,
        password=values["PASSWORD"] or None,
    )

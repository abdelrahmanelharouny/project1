"""Outgoing webhooks (P3 W6): endpoint CRUD, emission, signed delivery.

Semantics:
- Endpoints belong to exactly one organization; secrets (``whsec_``) are shown
  once at creation/rotation. The model stores the plaintext secret — REQUIRED
  for HMAC signing of outbound requests (see notes/limitations).
- ``emit_event`` creates one pending :class:`WebhookDelivery` per matching
  enabled endpoint (unique (endpoint_id, event_id) → idempotent emission).
  It performs NO HTTP.
- ``deliver_webhook`` POSTs the canonical JSON payload with
  ``X-FieldShift-Signature: t=<unix>,v1=HMAC_SHA256(secret, "<t>.<body>")``,
  plus event id/type headers. 2xx → delivered; anything else (or a transport
  error) → attempt incremented and ``next_retry_at`` scheduled with the
  configured backoff; exhausting ``webhook_max_attempts`` → status ``dead``;
  5 consecutive endpoint failures → endpoint auto-disabled (manual re-enable).
- ``retry_due_webhooks`` is the batched sweep for pending/failed deliveries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.core.config import settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.models_p3 import WebhookDelivery, WebhookEndpoint
from app.domains.identity.service import Principal, record_auth_audit
from app.publicapi.api_keys import resolve_org_id

# Event types a webhook endpoint may subscribe to (open set — extend with care;
# emitters in domain code must use one of these).
EVENT_TYPES: tuple[str, ...] = (
    "farm.updated",
    "field.created",
    "crop_cycle.updated",
    "recommendation.generated",
    "report.ready",
    "alert.raised",
    "subscription.updated",
)

DELIVERY_STATUSES: tuple[str, ...] = ("pending", "delivered", "failed", "dead")

WEBHOOK_SECRET_PREFIX = "whsec_"
SIGNATURE_HEADER = "X-FieldShift-Signature"
EVENT_ID_HEADER = "X-FieldShift-Event-Id"
EVENT_HEADER = "X-FieldShift-Event"
USER_AGENT = "FieldShift-Webhooks/1.0"

# Auto-disable an endpoint after this many CONSECUTIVE failed attempts
# (re-enable is manual, via update_webhook_endpoint(enabled=True)).
AUTO_DISABLE_FAILURES = 5

# Delivery HTTP timeout. Not a Settings field (config.py is outside this
# workstream's file ownership) — a module constant, overridable per call.
DEFAULT_DELIVERY_TIMEOUT_SECONDS = 10.0


# --------------------------------------------------------------------------
# validation helpers
# --------------------------------------------------------------------------
def _allow_insecure_local_urls() -> bool:
    """http://localhost is accepted outside production (sandbox convenience).

    settings.environment acts as the flag here (config.py has no dedicated
    field); production always requires https://.
    """
    return settings.environment != "production"


def validate_webhook_url(url: str) -> str:
    """Validate a receiver URL: https:// (or http://localhost in sandbox)."""
    candidate = (url or "").strip()
    if not candidate:
        raise ValidationFailed(
            "Webhook URL is required.", details=[{"field": "url", "reason": "empty"}]
        )
    if len(candidate) > 1000:
        raise ValidationFailed(
            "Webhook URL is too long (max 1000).", details=[{"field": "url", "reason": "too long"}]
        )
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("https", "http"):
        raise ValidationFailed(
            "Webhook URL must use https://.",
            details=[{"field": "url", "reason": f"unsupported scheme '{parsed.scheme}'"}],
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationFailed(
            "Webhook URL has no host.", details=[{"field": "url", "reason": "missing host"}]
        )
    if parsed.username or parsed.password:
        raise ValidationFailed(
            "Credentials in webhook URLs are not allowed.",
            details=[{"field": "url", "reason": "embedded credentials"}],
        )
    if parsed.scheme == "http":
        local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
        if not (local and _allow_insecure_local_urls()):
            raise ValidationFailed(
                "Webhook URL must use https:// (plain http is only allowed for "
                "localhost in non-production environments).",
                details=[{"field": "url", "reason": "insecure scheme"}],
            )
    return candidate


def validate_event_types(events: list[str] | None) -> list[str]:
    """Normalize + validate the subscription list (deduped, sorted)."""
    if not events:
        raise ValidationFailed(
            "At least one event type is required.",
            details=[{"field": "events", "reason": "must not be empty"}],
        )
    unknown = sorted(set(events) - set(EVENT_TYPES))
    if unknown:
        raise ValidationFailed(
            f"Unsupported event type(s): {', '.join(unknown)}.",
            details=[{"field": "events", "reason": unknown, "allowed": list(EVENT_TYPES)}],
        )
    return sorted(set(events))


def generate_webhook_secret() -> str:
    return f"{WEBHOOK_SECRET_PREFIX}{secrets.token_urlsafe(32)}"


# --------------------------------------------------------------------------
# endpoint CRUD (developer console)
# --------------------------------------------------------------------------
def create_webhook_endpoint(
    session: Session,
    principal: Principal,
    *,
    url: str,
    events: list[str],
    description: str = "",
    organization_id: uuid.UUID | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Register a receiver (org_admin+). Returns (endpoint, plaintext_secret) —
    the secret is shown ONCE."""
    organization_id = resolve_org_id(principal, organization_id)
    principal.require_org_role(organization_id, "org_admin")
    clean_url = validate_webhook_url(url)
    clean_events = validate_event_types(events)
    clean_description = (description or "").strip()[:300]

    count = int(
        session.scalar(
            select(func.count())
            .select_from(WebhookEndpoint)
            .where(WebhookEndpoint.organization_id == organization_id)
        )
        or 0
    )
    if count >= settings.webhook_max_endpoints_per_org:
        raise Conflict(
            f"Webhook endpoint limit reached ({settings.webhook_max_endpoints_per_org} "
            "per organization). Remove one before adding another."
        )

    secret = generate_webhook_secret()
    endpoint = WebhookEndpoint(
        organization_id=organization_id,
        url=clean_url,
        secret=secret,
        event_types=clean_events,
        status="active",
        description=clean_description,
    )
    session.add(endpoint)
    session.flush()
    record_auth_audit(
        session,
        actor_id=principal.id,
        organization_id=organization_id,
        action="webhook.create",
        entity_type="webhook_endpoint",
        entity_id=str(endpoint.id),
        meta={"url": clean_url, "events": clean_events},
    )
    activity.record_event(
        session,
        organization_id=organization_id,
        event_type=activity.EVENT_WEBHOOK_CREATED,
        summary=f"Webhook endpoint registered ({clean_url})",
        actor_user_id=principal.id,
        entity_kind="webhook_endpoint",
        entity_id=str(endpoint.id),
        details={"events": clean_events},
    )
    session.commit()
    return endpoint, secret


def get_webhook_endpoint(
    session: Session,
    principal: Principal,
    *,
    endpoint_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> WebhookEndpoint:
    """Load one of the org's endpoints (cross-org ids are 404s, not 403s)."""
    organization_id = resolve_org_id(principal, organization_id)
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.organization_id != organization_id:
        raise NotFound("Webhook endpoint not found.")
    return endpoint


def list_webhook_endpoints(
    session: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID | None = None,
) -> list[WebhookEndpoint]:
    organization_id = resolve_org_id(principal, organization_id)
    return list(
        session.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.organization_id == organization_id)
            .order_by(WebhookEndpoint.created_at.desc())
        ).all()
    )


def update_webhook_endpoint(
    session: Session,
    principal: Principal,
    *,
    endpoint_id: uuid.UUID,
    enabled: bool | None = None,
    events: list[str] | None = None,
    description: str | None = None,
    url: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> WebhookEndpoint:
    """Patch enabled/events/description/url (org_admin+).

    Re-enabling clears the auto-disable state (consecutive_failures reset,
    disabled_reason cleared). Disabling by hand sets a user-facing reason.
    """
    organization_id = resolve_org_id(principal, organization_id)
    endpoint = get_webhook_endpoint(
        session, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    principal.require_org_role(organization_id, "org_admin")

    if enabled is True:
        endpoint.status = "active"
        endpoint.disabled_reason = None
        endpoint.consecutive_failures = 0
    elif enabled is False:
        endpoint.status = "disabled"
        endpoint.disabled_reason = "disabled by organization administrator"
    if events is not None:
        endpoint.event_types = validate_event_types(events)
    if description is not None:
        endpoint.description = (description or "").strip()[:300]
    if url is not None:
        endpoint.url = validate_webhook_url(url)

    record_auth_audit(
        session,
        actor_id=principal.id,
        organization_id=organization_id,
        action="webhook.update",
        entity_type="webhook_endpoint",
        entity_id=str(endpoint.id),
        meta={"enabled": enabled, "events": endpoint.event_types},
    )
    session.commit()
    return endpoint


def delete_webhook_endpoint(
    session: Session,
    principal: Principal,
    *,
    endpoint_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> None:
    """Delete an endpoint and (via FK CASCADE) its delivery history."""
    organization_id = resolve_org_id(principal, organization_id)
    endpoint = get_webhook_endpoint(
        session, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    principal.require_org_role(organization_id, "org_admin")
    record_auth_audit(
        session,
        actor_id=principal.id,
        organization_id=organization_id,
        action="webhook.delete",
        entity_type="webhook_endpoint",
        entity_id=str(endpoint.id),
        meta={"url": endpoint.url},
    )
    session.delete(endpoint)
    session.commit()


def rotate_webhook_secret(
    session: Session,
    principal: Principal,
    *,
    endpoint_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Issue a new signing secret (old one stops verifying immediately)."""
    organization_id = resolve_org_id(principal, organization_id)
    endpoint = get_webhook_endpoint(
        session, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    principal.require_org_role(organization_id, "org_admin")
    secret = generate_webhook_secret()
    endpoint.secret = secret
    record_auth_audit(
        session,
        actor_id=principal.id,
        organization_id=organization_id,
        action="webhook.secret_rotate",
        entity_type="webhook_endpoint",
        entity_id=str(endpoint.id),
    )
    session.commit()
    return endpoint, secret


# --------------------------------------------------------------------------
# emission (no HTTP)
# --------------------------------------------------------------------------
def emit_event(
    session: Session,
    org_id: uuid.UUID,
    event_type: str,
    payload_id: str | None = None,
    data: dict[str, Any] | None = None,
    *,
    commit: bool = False,
) -> list[WebhookDelivery]:
    """Create one pending WebhookDelivery per matching enabled endpoint.

    ``payload_id`` (optional) becomes the dedupe id (``event_id``) so a domain
    event replayed for the same entity is delivered once per endpoint; without
    it a fresh uuid is used. The payload JSON shape is
    ``{id, event, created_at, org_id, data}`` where ``id`` is the delivery's
    own uuid. Performs NO HTTP — delivery happens via ``deliver_webhook`` /
    ``retry_due_webhooks``. Caller owns the transaction unless ``commit``.
    """
    if event_type not in EVENT_TYPES:
        raise ValidationFailed(
            f"Unsupported webhook event type '{event_type}'.",
            details=[{"field": "event_type", "reason": "unknown", "allowed": list(EVENT_TYPES)}],
        )
    # SQL prefilter + in-Python recheck (the recheck keeps emission correct
    # even for exotic session configurations and makes unit fakes honest).
    endpoints = [
        endpoint
        for endpoint in session.scalars(
            select(WebhookEndpoint).where(WebhookEndpoint.organization_id == org_id)
        ).all()
        if endpoint.status == "active" and event_type in (endpoint.event_types or [])
    ]
    if not endpoints:
        return []

    now = datetime.now(UTC)
    event_id = str(payload_id) if payload_id else str(uuid.uuid4())
    created: list[WebhookDelivery] = []
    for endpoint in endpoints:
        delivery_id = uuid.uuid4()
        payload = {
            "id": str(delivery_id),
            "event": event_type,
            "created_at": now.isoformat(),
            "org_id": str(org_id),
            "data": data or {},
        }
        delivery = WebhookDelivery(
            id=delivery_id,  # explicit: payload["id"] MUST equal the row id
            endpoint_id=endpoint.id,
            organization_id=org_id,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
            attempt=0,
            status="pending",
            next_retry_at=now,
        )
        try:
            with session.begin_nested():
                session.add(delivery)
                session.flush()
        except IntegrityError:
            continue  # duplicate (endpoint_id, event_id) — idempotent emission
        created.append(delivery)
    if commit:  # pragma: no cover — convenience for standalone callers
        session.commit()
    return created


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------
def canonical_body(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON body — sign EXACTLY the bytes we send."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_payload(secret: str, body: bytes | str, timestamp: int) -> str:
    """Build the signature header value: ``t=<unix>,v1=<hex hmac>``.

    The HMAC is SHA-256 over ``f"{timestamp}.{body}"`` with the endpoint secret.
    """
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(
    secret: str,
    body: bytes | str,
    header: str | None,
    tolerance_seconds: int = 300,
    *,
    now: datetime | None = None,
) -> bool:
    """Verify an ``X-FieldShift-Signature`` header against a body.

    Rejects malformed headers, stale timestamps (|now - t| > tolerance) and
    signature mismatches — all as ``False`` (never raises).
    """
    if not header or not isinstance(header, str):
        return False
    try:
        parts = dict(
            piece.strip().split("=", 1) for piece in header.split(",") if "=" in piece
        )
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (KeyError, ValueError, AttributeError, TypeError):
        return False
    if tolerance_seconds is not None:
        current = int(now.timestamp()) if now is not None else int(time.time())
        if abs(current - timestamp) > tolerance_seconds:
            return False
    expected = sign_payload(secret, body, timestamp)
    expected_mac = expected.split("v1=", 1)[1]
    return hmac.compare_digest(expected_mac, received)


# --------------------------------------------------------------------------
# delivery state machine (pure logic — unit-testable without HTTP)
# --------------------------------------------------------------------------
def _backoff_delay(attempt: int, backoff: Any = None) -> float:
    """Delay before the retry AFTER ``attempt`` failed.

    The configured schedule is a LIST (``webhook_backoff_seconds`` =
    [30, 120, 600, 3600, 21600]): index attempt-1, clamped to the last entry.
    A scalar is also supported (exponential form from the delivery spec:
    ``scalar * 2**(attempt-1)``).
    """
    schedule = settings.webhook_backoff_seconds if backoff is None else backoff
    if isinstance(schedule, (list, tuple)):
        if not schedule:
            return 0.0
        index = min(max(attempt - 1, 0), len(schedule) - 1)
        return float(schedule[index])
    return float(schedule) * (2 ** max(attempt - 1, 0))


def _record_success(
    delivery: WebhookDelivery,
    endpoint: WebhookEndpoint,
    *,
    status_code: int,
    now: datetime | None = None,
) -> None:
    moment = now or datetime.now(UTC)
    delivery.status = "delivered"
    delivery.attempt = int(delivery.attempt or 0) + 1
    delivery.delivered_at = moment
    delivery.last_status_code = int(status_code)
    delivery.last_error = None
    delivery.next_retry_at = None
    endpoint.consecutive_failures = 0


def _record_failure(
    delivery: WebhookDelivery,
    endpoint: WebhookEndpoint,
    *,
    error: str,
    status_code: int | None = None,
    now: datetime | None = None,
    max_attempts: int | None = None,
    backoff: Any = None,
) -> str:
    """Apply a failed attempt; returns the delivery's new status.

    - attempt counter +1, ``next_retry_at`` = now + backoff(attempt)
    - ``attempt >= webhook_max_attempts`` → status ``dead`` (dead-letter;
      the model has no separate dead-letter columns — encoded via status +
      last_error, see workstream notes)
    - endpoint.consecutive_failures +1; >= 5 → endpoint auto-disabled.
    """
    moment = now or datetime.now(UTC)
    cap = settings.webhook_max_attempts if max_attempts is None else max_attempts
    delivery.attempt = int(delivery.attempt or 0) + 1
    delivery.last_status_code = int(status_code) if status_code is not None else None
    delivery.last_error = error
    endpoint.consecutive_failures = int(endpoint.consecutive_failures or 0) + 1

    if delivery.attempt >= cap:
        delivery.status = "dead"
        delivery.next_retry_at = None
        delivery.last_error = f"dead-lettered after {delivery.attempt} attempt(s): {error}"
    else:
        delivery.status = "failed"
        delay = _backoff_delay(delivery.attempt, backoff)
        delivery.next_retry_at = moment + timedelta(seconds=delay)

    if endpoint.consecutive_failures >= AUTO_DISABLE_FAILURES and endpoint.status == "active":
        endpoint.status = "disabled"
        endpoint.disabled_reason = (
            f"auto-disabled after {endpoint.consecutive_failures} consecutive "
            "delivery failures — re-enable manually after fixing the receiver"
        )
    return str(delivery.status)


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------
def deliver_webhook(
    session: Session,
    delivery_id: uuid.UUID,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Perform (or schedule the failure of) ONE delivery attempt.

    Skips silently when the endpoint is disabled. Commits the outcome.
    ``transport`` is an httpx transport (tests inject MockTransport — the test
    suite never touches the network).
    """
    delivery = session.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise NotFound("Webhook delivery not found.")
    endpoint = session.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None or endpoint.status != "active":
        return {
            "delivery_id": str(delivery.id),
            "status": delivery.status,
            "skipped": "endpoint_disabled",
        }

    body = canonical_body(delivery.payload)
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        EVENT_HEADER: delivery.event_type,
        EVENT_ID_HEADER: str(delivery.id),
        SIGNATURE_HEADER: sign_payload(endpoint.secret, body, timestamp),
    }
    timeout = (
        DEFAULT_DELIVERY_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds)
    )

    status_code: int | None = None
    error: str | None = None
    ok = False
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.post(endpoint.url, content=body, headers=headers)
        status_code = response.status_code
        if 200 <= response.status_code < 300:
            ok = True
        else:
            error = f"receiver returned HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        error = f"transport error: {type(exc).__name__}"

    if ok:
        _record_success(delivery, endpoint, status_code=status_code, now=now)
    else:
        _record_failure(delivery, endpoint, error=error or "delivery failed", status_code=status_code, now=now)
    session.commit()
    return {
        "delivery_id": str(delivery.id),
        "status": delivery.status,
        "attempt": int(delivery.attempt),
        "status_code": delivery.last_status_code,
        "error": delivery.last_error,
    }


def retry_due_webhooks(
    session: Session,
    now: datetime | None = None,
    *,
    batch: int = 50,
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, int]:
    """Sweep pending/failed deliveries that are due (cap 50 per run)."""
    moment = now or datetime.now(UTC)
    cap = max(1, min(int(batch), 50))
    rows = (
        session.execute(
            select(WebhookDelivery)
            .join(WebhookEndpoint, WebhookDelivery.endpoint_id == WebhookEndpoint.id)
            .where(
                WebhookDelivery.status.in_(("pending", "failed")),
                WebhookDelivery.next_retry_at.isnot(None),
                WebhookDelivery.next_retry_at <= moment,
                WebhookEndpoint.status == "active",
            )
            .order_by(WebhookDelivery.next_retry_at)
            .limit(cap)
        )
        .scalars()
        .all()
    )
    counts = {"attempted": 0, "delivered": 0, "failed": 0, "dead": 0, "skipped": 0}
    for delivery in rows:
        result = deliver_webhook(
            session, delivery.id, transport=transport, timeout_seconds=timeout_seconds, now=now
        )
        counts["attempted"] += 1
        if result.get("skipped"):
            counts["skipped"] += 1
        elif result["status"] == "delivered":
            counts["delivered"] += 1
        elif result["status"] == "dead":
            counts["dead"] += 1
        else:
            counts["failed"] += 1
    return counts


# --------------------------------------------------------------------------
# observability (developer console)
# --------------------------------------------------------------------------
def list_deliveries(
    session: Session,
    principal: Principal,
    *,
    endpoint_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[WebhookDelivery], int]:
    """Org-scoped delivery history, newest first."""
    organization_id = resolve_org_id(principal, organization_id)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    conditions = [WebhookDelivery.organization_id == organization_id]
    if endpoint_id is not None:
        endpoint = get_webhook_endpoint(
            session, principal, endpoint_id=endpoint_id, organization_id=organization_id
        )
        conditions.append(WebhookDelivery.endpoint_id == endpoint.id)
    if status is not None:
        if status not in DELIVERY_STATUSES:
            raise ValidationFailed(
                f"Unknown delivery status '{status}'.",
                details=[{"field": "status", "reason": list(DELIVERY_STATUSES)}],
            )
        conditions.append(WebhookDelivery.status == status)
    total = int(
        session.scalar(
            select(func.count()).select_from(WebhookDelivery).where(*conditions)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(WebhookDelivery)
            .where(*conditions)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


def redeliver(
    session: Session,
    principal: Principal,
    *,
    delivery_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> WebhookDelivery:
    """Manual redelivery: reset to pending, due immediately, attempt counter
    reset (operator-initiated retry deserves a full budget)."""
    organization_id = resolve_org_id(principal, organization_id)
    delivery = session.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.organization_id != organization_id:
        raise NotFound("Webhook delivery not found.")
    if delivery.status == "delivered":
        raise Conflict("Delivery already succeeded — nothing to redeliver.")
    delivery.status = "pending"
    delivery.attempt = 0
    delivery.next_retry_at = now or datetime.now(UTC)
    delivery.last_error = None
    session.commit()
    return delivery


def webhook_endpoint_payload(endpoint: WebhookEndpoint) -> dict[str, Any]:
    """Client-safe projection — the signing secret is NEVER included."""
    return {
        "id": str(endpoint.id),
        "organization_id": str(endpoint.organization_id),
        "url": endpoint.url,
        "event_types": list(endpoint.event_types or []),
        "status": endpoint.status,
        "description": endpoint.description,
        "consecutive_failures": int(endpoint.consecutive_failures or 0),
        "disabled_reason": endpoint.disabled_reason,
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
        "updated_at": endpoint.updated_at.isoformat() if endpoint.updated_at else None,
    }


def webhook_delivery_payload(delivery: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": str(delivery.id),
        "endpoint_id": str(delivery.endpoint_id),
        "event_type": delivery.event_type,
        "event_id": delivery.event_id,
        "status": delivery.status,
        "attempt": int(delivery.attempt or 0),
        "next_retry_at": delivery.next_retry_at.isoformat() if delivery.next_retry_at else None,
        "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
        "last_status_code": delivery.last_status_code,
        "last_error": delivery.last_error,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
    }

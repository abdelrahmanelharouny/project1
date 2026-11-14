"""Public API keys: issue, scope, throttle and authenticate (P3 W6).

Design:
- Only the SHA-256 hash of the plaintext key is persisted; the plaintext
  (``ctk_``-prefixed, 256-bit) is returned exactly once at creation/rotation.
- Every key is scoped to its organization (tenant isolation boundary) and to
  an explicit scope list (subset of ``API_KEY_SCOPES``).
- Production per-key throttling uses PostgreSQL row-locked rolling-window
  state shared across workers; a bounded local limiter remains for pure unit
  tests. The per-key limit is clamped to the live plan entitlement.
- ``require_api_key(*scopes)`` is the FastAPI dependency used by the versioned
  public API; it returns an :class:`ApiKeyPrincipal` (org_id, key_id, scopes) —
  never a user principal.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.billing import entitlements
from app.billing.entitlements import (
    KEY_API_ENABLED,
    KEY_API_RATE_LIMIT_PER_MINUTE,
    resolve_entitlements,
    get_live_subscription,
    assert_within_limit,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import (
    Conflict,
    Forbidden,
    NotFound,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
)
from app.db.models import Organization
from app.db.models_api_rate import ApiKeyRateWindow
from app.db.models_p3 import ApiKey, ApiKeyUsage, PlanEntitlement
from app.domains.identity.service import Principal, bearer_scheme, record_auth_audit

# Scopes a public API key may carry (open set — extend deliberately).
API_KEY_SCOPES: tuple[str, ...] = (
    "org:read",
    "farms:read",
    "fields:read",
    "crops:read",
    "analytics:read",
    "recommendations:read",
    "reports:read",
    "environment:read",
)

# Optional plan entitlement that caps the number of ACTIVE keys per org. NOT
# part of the seeded catalog (migration 0020) — the gate passes through unless
# a plan actually defines it, so today's plans never hit a false 402.
KEY_MAX_API_KEYS = "max_api_keys"

# Fallback per-key throttle when the org has no live subscription (the seeded
# free/starter plans set api_rate_limit_per_minute to 0 = no public API).
DEFAULT_RATE_LIMIT_PER_MINUTE = 60

RATE_WINDOW_SECONDS = 60.0
MAX_LOCAL_RATE_BUCKETS = 10_000
MAX_RATE_WINDOW_EVENTS = 10_000
USAGE_RETENTION_DAYS = 90
RATE_STATE_RETENTION_SECONDS = 2 * RATE_WINDOW_SECONDS


# --------------------------------------------------------------------------
# per-key rate limiting (same primitive as app/core/rate_limit.py)
# --------------------------------------------------------------------------
class SlidingWindowLimiter:
    """Per-(bucket) sliding window with a PER-CALL limit.

    Mirrors the deque-of-monotonic-timestamps primitive from
    ``app/core/rate_limit.py``; the difference is that the limit is supplied by
    the caller (each API key carries its own ``rate_limit_per_minute``) rather
    than read from a global setting.
    """

    def __init__(
        self,
        window_seconds: float = RATE_WINDOW_SECONDS,
        *,
        max_buckets: int = MAX_LOCAL_RATE_BUCKETS,
    ) -> None:
        self._window = float(window_seconds)
        self._max_buckets = max(1, int(max_buckets))
        self._store: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, *, now: float | None = None) -> None:
        """Count one request; raise TooManyRequests (429) when exhausted."""
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            cutoff = moment - self._window
            for bucket, values in tuple(self._store.items()):
                while values and values[0] <= cutoff:
                    values.popleft()
                if not values:
                    self._store.pop(bucket, None)
            if limit is None or limit <= 0:
                self._store.pop(key, None)
                return  # 0 disables limiting and never retains timestamps
            timestamps = self._store.get(key)
            if timestamps is None:
                if len(self._store) >= self._max_buckets:
                    self._store.pop(next(iter(self._store)))
                timestamps = self._store.setdefault(key, deque())
            if len(timestamps) >= limit or len(timestamps) >= MAX_RATE_WINDOW_EVENTS:
                retry_after = max(int(self._window - (moment - timestamps[0])) + 1, 1)
                raise TooManyRequests(
                    "API rate limit exceeded for this key — slow down.",
                    retry_after_seconds=retry_after,
                )
            timestamps.append(moment)

    def forget(self, key: str) -> None:
        """Evict one key's local fallback state after revocation/rotation."""
        with self._lock:
            self._store.pop(key, None)

    @property
    def bucket_count(self) -> int:
        """Current cache size, exposed for deterministic lifecycle tests."""
        with self._lock:
            return len(self._store)

    def reset(self) -> None:
        """Clear all counters (test isolation helper)."""
        with self._lock:
            self._store.clear()


# Local bounded fallback is used only by pure/mock-session tests. Production
# authentication consumes ApiKeyRateWindow rows through PostgreSQL below.
key_rate_limiter = SlidingWindowLimiter()


# --------------------------------------------------------------------------
# principal + key material
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ApiKeyPrincipal:
    """Auth context for a request made with a public API key (NOT a user)."""

    organization_id: uuid.UUID
    key_id: uuid.UUID
    scopes: frozenset[str]

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization_id

    def has_scopes(self, required: Iterable[str]) -> bool:
        return set(required).issubset(set(self.scopes))

    def require_member_of(self, organization_id: uuid.UUID) -> None:
        """Compatibility shim for org-scoped services (e.g. analytics):
        a key may only ever act on its own organization."""
        if organization_id != self.organization_id:
            raise Forbidden("This API key cannot access another organization's resources.")


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hex digest of the plaintext key (64 chars — fits key_hash)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(plaintext, prefix, key_hash)``.

    The plaintext is ``settings.api_key_prefix`` (default ``ctk_``) + 256 bits
    of urlsafe randomness; ``prefix`` is its first 12 characters (display +
    lookup convenience); the hash is the ONLY persisted secret material.
    """
    plaintext = f"{settings.api_key_prefix}{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:12], hash_api_key(plaintext)


def validate_scopes(scopes: list[str] | None) -> list[str]:
    """Normalize + validate a scope list (deduped, sorted)."""
    if not scopes:
        raise ValidationFailed(
            "At least one scope is required.",
            details=[{"field": "scopes", "reason": "must not be empty"}],
        )
    unknown = sorted(set(scopes) - set(API_KEY_SCOPES))
    if unknown:
        raise ValidationFailed(
            f"Unknown scope(s): {', '.join(unknown)}.",
            details=[{"field": "scopes", "reason": unknown, "allowed": list(API_KEY_SCOPES)}],
        )
    return sorted(set(scopes))


def resolve_org_id(principal: Principal, organization_id: uuid.UUID | None = None) -> uuid.UUID:
    """Resolve the organization a developer-console call applies to.

    Explicit ``organization_id`` must be one of the caller's orgs; otherwise
    the caller must belong to exactly one organization (multi-member callers
    must name the org — never guess the tenant).
    """
    if organization_id is not None:
        principal.require_member_of(organization_id)
        return organization_id
    org_ids = principal.org_ids()
    if len(org_ids) == 1:
        return next(iter(org_ids))
    if not org_ids:
        raise Forbidden("You do not belong to any organization.")
    raise ValidationFailed(
        "organization_id is required — you are a member of multiple organizations.",
        details=[{"field": "organization_id", "reason": "ambiguous organization"}],
    )


# --------------------------------------------------------------------------
# entitlement plumbing
# --------------------------------------------------------------------------
def _assert_api_keys_within_limit(
    session: Session, organization_id: uuid.UUID, current_count: int
) -> None:
    """Gate the number of ACTIVE keys against the plan's ``max_api_keys``.

    Passes through when the org has no live subscription OR the plan does not
    define the entitlement (not in the seeded catalog — platform admins may
    add it per plan later). This mirrors the other resource gates, which only
    bite when the plan actually carries a limit.
    """
    subscription = get_live_subscription(session, organization_id)
    if subscription is None:
        return
    row = session.scalar(
        select(PlanEntitlement).where(
            PlanEntitlement.plan_id == subscription.plan_id,
            PlanEntitlement.key == KEY_MAX_API_KEYS,
        )
    )
    if row is None or row.value_int is None:
        return
    assert_within_limit(session, organization_id, KEY_MAX_API_KEYS, current_count)


def _resolve_rate_limit(session: Session, organization_id: uuid.UUID) -> int:
    """Resolve a positive per-key limit or fail closed for disabled plans."""
    entitlements = resolve_entitlements(session, organization_id)
    entry = entitlements.get(KEY_API_RATE_LIMIT_PER_MINUTE) or {}
    try:
        value = int(entry.get("value") or 0)
    except (TypeError, ValueError):
        value = 0
    if value == -1:
        return 2_147_483_647
    if value <= 0:
        raise Forbidden("The current plan does not enable the public API.")
    return value


def _active_api_key_count(session: Session, organization_id: uuid.UUID) -> int:
    """Count currently active keys while the caller holds the org lock."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.organization_id == organization_id, ApiKey.status == "active")
        )
        or 0
    )


def _require_postgresql_session(session: Session) -> None:
    """Prevent production paths from silently falling back to local state."""
    if not hasattr(session, "get_bind"):
        return  # Minimal mock sessions are used by pure unit tests only.
    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("API-key counters and shared rate windows require PostgreSQL.")


def _lock_organization(session: Session, organization_id: uuid.UUID) -> None:
    """Serialize all key mutations for an organization using one lock order."""
    session.scalar(
        select(Organization.id)
        .where(Organization.id == organization_id)
        .with_for_update()
    )


def _locked_api_key(
    session: Session, organization_id: uuid.UUID, key_id: uuid.UUID
) -> ApiKey:
    """Lock the target key only after its organization lock has been acquired."""
    key = session.scalar(
        select(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
        .with_for_update()
    )
    if key is None:
        raise NotFound("API key not found.")
    return key


def _check_shared_rate_window(
    session: Session, key_id: uuid.UUID, limit: int
) -> None:
    """Consume one request in a shared, row-locked PostgreSQL sliding window.

    The event array is bounded even for an unlimited plan. At the hard safety
    cap, requests fail closed with 429 until its oldest event ages out.
    """
    _require_postgresql_session(session)
    session.execute(
        pg_insert(ApiKeyRateWindow)
        .values(api_key_id=key_id, timestamps=[])
        .on_conflict_do_nothing(index_elements=[ApiKeyRateWindow.api_key_id])
    )
    row = session.scalar(
        select(ApiKeyRateWindow)
        .where(ApiKeyRateWindow.api_key_id == key_id)
        .with_for_update()
    )
    if row is None:  # pragma: no cover - PK insert/select must yield a row
        raise RuntimeError("Unable to initialize API-key rate-window state.")
    moment = float(session.scalar(select(func.extract("epoch", func.clock_timestamp()))))
    cutoff = moment - RATE_WINDOW_SECONDS
    active = [float(value) for value in (row.timestamps or []) if float(value) > cutoff]
    retry_after = max(int(RATE_WINDOW_SECONDS - (moment - active[0])) + 1, 1) if active else 1
    if len(active) >= int(limit) or len(active) >= MAX_RATE_WINDOW_EVENTS:
        raise TooManyRequests(
            "API rate limit exceeded for this key — slow down.",
            retry_after_seconds=retry_after,
        )
    active.append(moment)
    row.timestamps = active
    row.updated_at = datetime.fromtimestamp(moment, UTC)
    session.flush()


def prune_api_key_state(
    session: Session,
    *,
    usage_retention_days: int = USAGE_RETENTION_DAYS,
    before: date | None = None,
    rate_idle_seconds: float = RATE_STATE_RETENTION_SECONDS,
    batch_size: int = 1_000,
    now: datetime | None = None,
    commit: bool = False,
) -> dict[str, int]:
    """Delete at most ``batch_size`` expired usage and idle-rate rows.

    This bounded sweep can be run repeatedly by maintenance without holding a
    long transaction. Rate rows can be recreated on the next authenticated
    request; daily dashboard usage is retained for the declared 90-day window.
    """
    _require_postgresql_session(session)
    if batch_size < 1 or usage_retention_days < 1 or rate_idle_seconds <= 0:
        raise ValueError("Retention values and batch size must be positive.")
    moment = now or datetime.now(UTC)
    usage_cutoff = before or moment.date() - timedelta(days=usage_retention_days)
    rate_cutoff = moment - timedelta(seconds=rate_idle_seconds)
    # Materialize the locked, bounded identifiers before DELETE. This makes
    # the per-table ceiling explicit even on dialects that rewrite a limited
    # SELECT nested inside DELETE differently.
    old_usage_ids = list(
        session.scalars(
            select(ApiKeyUsage.id)
            .where(ApiKeyUsage.day < usage_cutoff)
            .order_by(ApiKeyUsage.day.asc(), ApiKeyUsage.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
    )
    stale_rate_ids = list(
        session.scalars(
            select(ApiKeyRateWindow.api_key_id)
            .where(ApiKeyRateWindow.updated_at < rate_cutoff)
            .order_by(ApiKeyRateWindow.updated_at.asc(), ApiKeyRateWindow.api_key_id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
    )
    usage_rows = 0
    if old_usage_ids:
        usage_rows = int(
            session.execute(
                delete(ApiKeyUsage).where(ApiKeyUsage.id.in_(old_usage_ids))
            ).rowcount
            or 0
        )
    rate_rows = (
        int(
            session.execute(
                delete(ApiKeyRateWindow).where(ApiKeyRateWindow.api_key_id.in_(stale_rate_ids))
            ).rowcount
            or 0
        )
        if stale_rate_ids
        else 0
    )
    result = {
        "usage_rows": usage_rows,
        "rate_rows": rate_rows,
    }
    if commit:
        session.commit()
    return result


def purge_api_key_usage(
    db: Session,
    *,
    before: date | datetime | None = None,
    batch_size: int = 1_000,
) -> dict[str, int]:
    """Scheduler entry point: bounded usage and stale rate-state retention.

    Rows with ``day < before`` are eligible; by default usage older than 90
    days is removed. Rate rows idle for two rolling-window lengths are also
    eligible. The caller owns commit/rollback; at most ``batch_size`` rows per
    table are deleted on each invocation.
    """
    cutoff = before.date() if isinstance(before, datetime) else before
    return prune_api_key_state(db, before=cutoff, batch_size=batch_size)


# --------------------------------------------------------------------------
# key lifecycle service
# --------------------------------------------------------------------------
def create_api_key(
    session: Session,
    principal: Principal,
    *,
    name: str,
    scopes: list[str],
    organization_id: uuid.UUID | None = None,
) -> tuple[ApiKey, str]:
    """Create a scoped key for the caller's organization (org_admin+).

    Returns ``(key_row, plaintext)`` — the plaintext is shown ONCE and only
    its SHA-256 hash is stored.
    """
    organization_id = resolve_org_id(principal, organization_id)
    principal.require_org_role(organization_id, "org_admin")
    _require_postgresql_session(session)
    _lock_organization(session, organization_id)
    entitlements.require_flag(session, organization_id, KEY_API_ENABLED)
    clean_name = (name or "").strip()
    if not 1 <= len(clean_name) <= 120:
        raise ValidationFailed(
            "API key name must be 1-120 characters.",
            details=[{"field": "name", "reason": "length out of range"}],
        )
    clean_scopes = validate_scopes(scopes)

    active_count = _active_api_key_count(session, organization_id)
    _assert_api_keys_within_limit(session, organization_id, active_count)
    rate_limit = _resolve_rate_limit(session, organization_id)

    plaintext, prefix, key_hash = generate_api_key()
    key = ApiKey(
        organization_id=organization_id,
        name=clean_name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=clean_scopes,
        status="active",
        rate_limit_per_minute=rate_limit,
        created_by=principal.id,
    )
    session.add(key)
    session.flush()
    record_auth_audit(
        session,
        actor_id=principal.id,
        organization_id=organization_id,
        action="api_key.create",
        entity_type="api_key",
        entity_id=str(key.id),
        meta={"name": clean_name, "prefix": prefix, "scopes": clean_scopes},
    )
    activity.record_event(
        session,
        organization_id=organization_id,
        event_type=activity.EVENT_API_KEY_CREATED,
        summary=f"API key '{clean_name}' created",
        actor_user_id=principal.id,
        entity_kind="api_key",
        entity_id=str(key.id),
        details={"prefix": prefix, "scopes": clean_scopes},
    )
    session.commit()
    return key, plaintext


def get_api_key(
    session: Session,
    principal: Principal,
    *,
    key_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> ApiKey:
    """Load one of the org's keys (tenant guard: cross-org ids are 404s)."""
    organization_id = resolve_org_id(principal, organization_id)
    key = session.get(ApiKey, key_id)
    if key is None or key.organization_id != organization_id:
        raise NotFound("API key not found.")
    return key


def list_api_keys(
    session: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID | None = None,
) -> list[ApiKey]:
    """All of the org's keys, newest first (any active member may list)."""
    organization_id = resolve_org_id(principal, organization_id)
    return list(
        session.scalars(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


def revoke_api_key(
    session: Session,
    principal: Principal,
    *,
    key_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> ApiKey:
    """Revoke a key (org_admin+). Idempotent; takes effect immediately."""
    organization_id = resolve_org_id(principal, organization_id)
    principal.require_org_role(organization_id, "org_admin")
    _require_postgresql_session(session)
    _lock_organization(session, organization_id)
    key = _locked_api_key(session, organization_id, key_id)
    if key.status != "revoked":
        key.status = "revoked"
        key.revoked_at = datetime.now(UTC)
        record_auth_audit(
            session,
            actor_id=principal.id,
            organization_id=organization_id,
            action="api_key.revoke",
            entity_type="api_key",
            entity_id=str(key.id),
            meta={"name": key.name, "prefix": key.prefix},
        )
        activity.record_event(
            session,
            organization_id=organization_id,
            event_type=activity.EVENT_API_KEY_REVOKED,
            summary=f"API key '{key.name}' revoked",
            actor_user_id=principal.id,
            entity_kind="api_key",
            entity_id=str(key.id),
        )
    if hasattr(session, "get_bind"):
        session.execute(
            delete(ApiKeyRateWindow).where(ApiKeyRateWindow.api_key_id == key.id)
        )
    key_rate_limiter.forget(str(key.id))
    session.commit()
    return key


def rotate_api_key(
    session: Session,
    principal: Principal,
    *,
    key_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> tuple[ApiKey, str]:
    """Rotate: old key is revoked immediately (NO grace window) and a fresh
    secret is issued with the same name/scopes and the current plan rate
    limit. Returns the new plaintext ONCE."""
    organization_id = resolve_org_id(principal, organization_id)
    principal.require_org_role(organization_id, "org_admin")
    _require_postgresql_session(session)
    _lock_organization(session, organization_id)
    try:
        entitlements.require_flag(session, organization_id, KEY_API_ENABLED)
        old_key = _locked_api_key(session, organization_id, key_id)
        if old_key.status != "active" or old_key.revoked_at is not None:
            raise Conflict("Cannot rotate a revoked API key — create a new one instead.")

        # Rotation is a replacement, not an additional key: check the same
        # live issuance cap while excluding the active key this transaction
        # replaces. All checks precede mutation so a downgraded plan cannot
        # strand an otherwise valid credential.
        active_count = _active_api_key_count(session, organization_id)
        replacement_count = max(0, active_count - 1)
        _assert_api_keys_within_limit(session, organization_id, replacement_count)
        rate_limit = _resolve_rate_limit(session, organization_id)
    except Exception:
        # Release the organization/key locks and leave the caller with no
        # partially authorized transaction to accidentally commit.
        if hasattr(session, "rollback"):
            session.rollback()
        raise

    plaintext, prefix, key_hash = generate_api_key()
    new_key = ApiKey(
        organization_id=old_key.organization_id,
        name=old_key.name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=list(old_key.scopes or []),
        status="active",
        rate_limit_per_minute=rate_limit,
        created_by=principal.id,
    )
    try:
        now = datetime.now(UTC)
        old_key.status = "revoked"
        old_key.revoked_at = now
        if hasattr(session, "get_bind"):
            session.execute(
                delete(ApiKeyRateWindow).where(ApiKeyRateWindow.api_key_id == old_key.id)
            )
        session.add(new_key)
        session.flush()
        record_auth_audit(
            session,
            actor_id=principal.id,
            organization_id=organization_id,
            action="api_key.rotate",
            entity_type="api_key",
            entity_id=str(new_key.id),
            meta={"rotated_from": str(old_key.id), "prefix": prefix},
        )
        activity.record_event(
            session,
            organization_id=organization_id,
            event_type=activity.EVENT_API_KEY_CREATED,
            summary=f"API key '{old_key.name}' rotated",
            actor_user_id=principal.id,
            entity_kind="api_key",
            entity_id=str(new_key.id),
            details={"rotated_from": str(old_key.id), "prefix": prefix},
        )
        session.commit()
    except Exception:
        # Keep the old credential and replacement in one all-or-nothing
        # transaction even if persistence/audit work fails mid-rotation.
        if hasattr(session, "rollback"):
            session.rollback()
        raise
    key_rate_limiter.forget(str(old_key.id))
    return new_key, plaintext


def record_usage(
    session: Session,
    key_id: uuid.UUID,
    path: str,
    status_code: int,
    *,
    day: date | None = None,
    commit: bool = False,
) -> ApiKeyUsage:
    """Upsert the per-day/per-key request counter (background-safe).

    PostgreSQL uses one ``INSERT .. ON CONFLICT DO UPDATE`` statement, so both
    first inserts and increments of an existing row are atomic. The
    read/modify/write branch is only for mock sessions in pure unit tests.
    ``path``/``status_code`` are accepted for future per-route metrics; the
    current model persists a daily counter only.
    """
    usage_day = day or datetime.now(UTC).date()
    if hasattr(session, "get_bind"):
        _require_postgresql_session(session)
        statement = (
            pg_insert(ApiKeyUsage)
            .values(api_key_id=key_id, day=usage_day, request_count=1)
            .on_conflict_do_update(
                index_elements=[ApiKeyUsage.api_key_id, ApiKeyUsage.day],
                set_={"request_count": ApiKeyUsage.request_count + 1},
            )
            .returning(ApiKeyUsage)
        )
        row = session.scalars(statement.execution_options(populate_existing=True)).one()
        if commit:  # pragma: no cover — convenience for standalone sweeps
            session.commit()
        return row

    row = session.scalar(
        select(ApiKeyUsage).where(ApiKeyUsage.api_key_id == key_id, ApiKeyUsage.day == usage_day)
    )
    if row is None:
        try:
            with session.begin_nested():
                row = ApiKeyUsage(api_key_id=key_id, day=usage_day, request_count=1)
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.scalar(
                select(ApiKeyUsage).where(
                    ApiKeyUsage.api_key_id == key_id, ApiKeyUsage.day == usage_day
                )
            )
            if row is None:  # pragma: no cover — concurrent delete; retry caller
                raise
            row.request_count = int(row.request_count or 0) + 1
            session.flush()
    else:
        row.request_count = int(row.request_count or 0) + 1
        session.flush()
    if commit:  # pragma: no cover — convenience for standalone sweeps
        session.commit()
    return row


# --------------------------------------------------------------------------
# key authentication (service core + FastAPI dependency)
# --------------------------------------------------------------------------
def authenticate_api_key(
    session: Session,
    raw_key: str | None,
    required_scopes: Iterable[str] = (),
    *,
    now: datetime | None = None,
    limiter: SlidingWindowLimiter | None = None,
) -> ApiKeyPrincipal:
    """Validate a raw key and return the :class:`ApiKeyPrincipal`.

    Order of checks: format → hash lookup → revoked/expired (401) → scopes
    (403) → per-key rate limit (429, Retry-After). On success stamps
    ``last_used_at`` and records the daily usage counter inline (committed
    immediately so it survives later request failures).
    """
    moment = now or datetime.now(UTC)
    if not raw_key or not raw_key.startswith(settings.api_key_prefix):
        raise Unauthorized(
            "Missing or malformed API key. Send 'Authorization: Bearer <key>' "
            "or the X-API-Key header."
        )
    key = session.scalar(
        select(ApiKey)
        .where(ApiKey.key_hash == hash_api_key(raw_key))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if key is None:
        raise Unauthorized("Invalid API key.")
    if key.status != "active" or key.revoked_at is not None:
        raise Unauthorized("API key has been revoked.")
    if key.expires_at is not None and key.expires_at < moment:
        raise Unauthorized("API key has expired.")

    entitlements.require_flag(session, key.organization_id, KEY_API_ENABLED)
    current_limit = entitlements.limit_for(
        session, key.organization_id, KEY_API_RATE_LIMIT_PER_MINUTE
    )
    if current_limit == 0:
        raise Forbidden("The current plan does not enable the public API.")

    scopes = set(key.scopes or [])
    missing = [scope for scope in required_scopes if scope not in scopes]
    if missing:
        raise Forbidden(
            f"API key is missing required scope(s): {', '.join(missing)}.",
            details=[{"field": "scopes", "reason": missing}],
        )

    effective_limit = (
        int(key.rate_limit_per_minute)
        if current_limit < 0
        else min(int(key.rate_limit_per_minute), current_limit)
    )
    if limiter is not None or not hasattr(session, "get_bind"):
        # Explicit/local limiter use exists only for deterministic pure tests.
        (limiter or key_rate_limiter).check(str(key.id), effective_limit)
    else:
        _check_shared_rate_window(session, key.id, effective_limit)

    key.last_used_at = moment
    record_usage(session, key.id, "", 200)
    session.commit()
    return ApiKeyPrincipal(
        organization_id=key.organization_id,
        key_id=key.id,
        scopes=frozenset(scopes),
    )


def require_api_key(*required_scopes: str):
    """FastAPI dependency factory for public API routes.

    Accepts ``Authorization: Bearer ctk_...`` OR the ``X-API-Key`` header.
    Raises the structured errors (401/403/429) handled by the global error
    handlers (``X-Request-Id`` is added by the app-wide request-id middleware).
    """

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> ApiKeyPrincipal:
        raw: str | None = None
        if credentials is not None and credentials.scheme.lower() == "bearer":
            raw = credentials.credentials
        if not raw and x_api_key:
            raw = x_api_key.strip()
        principal = authenticate_api_key(db, raw, required_scopes)
        request.state.api_key_id = str(principal.key_id)
        return principal

    return dependency


def api_key_payload(key: ApiKey) -> dict[str, Any]:
    """Client-safe projection — NEVER exposes key_hash (that IS the secret)."""
    return {
        "id": str(key.id),
        "organization_id": str(key.organization_id),
        "name": key.name,
        "prefix": key.prefix,
        "scopes": list(key.scopes or []),
        "status": key.status,
        "rate_limit_per_minute": int(key.rate_limit_per_minute),
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
    }

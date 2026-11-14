"""P3 W6 outgoing webhooks — unit tests (pure logic + fake Session, no DB).

Coverage: HMAC signature header build/verify (happy path, tamper, wrong
secret, timestamp tolerance, malformed headers), backoff computation (list
schedule + scalar exponential form), emit_event endpoint matching +
idempotent dedupe, delivery state machine (success, failure backoff,
dead-letter after max attempts, auto-disable after 5 consecutive failures)
and end-to-end deliver_webhook over an httpx.MockTransport (the suite never
touches the network). Follows the pure-logic conventions of
tests/unit/test_recommendation_fingerprint.py.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac as hmac_mod
import json
import operator
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import operators as sa_ops
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from app.core import config
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.models_p3 import ActivityEvent, WebhookDelivery, WebhookEndpoint
from app.publicapi import webhooks

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
USER_ID = uuid.uuid4()
SECRET = "whsec_unit_test_secret"
NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# fakes (same approach as tests/unit/test_publicapi_keys.py)
# ---------------------------------------------------------------------------
class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _stmt_entity(stmt):
    try:
        return stmt.column_descriptions[0]["entity"]
    except Exception:  # pragma: no cover
        return None


_BIN_OPS = {
    sa_ops.eq: operator.eq,
    sa_ops.ne: operator.ne,
    sa_ops.lt: operator.lt,
    sa_ops.le: operator.le,
    sa_ops.gt: operator.gt,
    sa_ops.ge: operator.ge,
}


def _clause_matches(obj, clause, table_name=None) -> bool:
    """Tiny WHERE evaluator: simple comparisons/IN/IS on the primary table.
    Conditions referencing a JOINed table (e.g. endpoint status in the retry
    sweep) are skipped — they cannot be evaluated against the row."""
    if clause is None:
        return True
    if isinstance(clause, BooleanClauseList):
        return all(_clause_matches(obj, c, table_name) for c in clause.clauses)
    if isinstance(clause, BinaryExpression):
        name = getattr(clause.left, "key", None)
        if name is None:
            return True
        if table_name is not None:
            left_table = getattr(getattr(clause.left, "table", None), "name", None)
            if left_table is not None and left_table != table_name:
                return True
        actual = getattr(obj, name, None)
        value = getattr(clause.right, "value", None)
        op = clause.operator
        if op is sa_ops.in_op:
            values = value if isinstance(value, (list, tuple, set)) else []
            return actual in values
        if op is sa_ops.is_:
            return actual is value
        if op is sa_ops.isnot:
            return actual is not value
        fn = _BIN_OPS.get(op)
        if fn is None:
            return True
        try:
            return bool(fn(actual, value))
        except TypeError:
            return True
    return True


class _FakeNested:
    def __init__(self, session):
        self._session = session
        self._mark = len(session.objects)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            del self._session.objects[self._mark:]
        return False


class FakeSession:
    def __init__(self):
        self.objects: list = []
        self.commits = 0

    def add(self, obj):
        if getattr(obj, "id", None) is None and hasattr(type(obj), "id"):
            obj.id = uuid.uuid4()
        self.objects.append(obj)

    def flush(self):
        seen = set()
        for obj in self.objects:
            if isinstance(obj, WebhookDelivery):
                k = (obj.endpoint_id, obj.event_id)
                if k in seen:
                    raise IntegrityError("uq_webhook_delivery_event", {}, Exception("dup"))
                seen.add(k)

    def begin_nested(self):
        return _FakeNested(self)

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)

    def get(self, entity, pk):
        for obj in self.objects:
            if isinstance(obj, entity) and getattr(obj, "id", None) == pk:
                return obj
        return None

    def _matching(self, stmt):
        entity = _stmt_entity(stmt)
        if entity is None:
            return []
        table_name = getattr(getattr(entity, "__table__", None), "name", None)
        return [
            o for o in self.objects
            if isinstance(o, entity) and _clause_matches(o, stmt.whereclause, table_name)
        ]

    def scalar(self, stmt):
        if _stmt_entity(stmt) is None:  # e.g. select(func.count()) → zero
            return 0
        rows = self._matching(stmt)
        return rows[0] if rows else None

    def scalars(self, stmt):
        return FakeResult(self._matching(stmt))

    def execute(self, stmt):
        return FakeExecResult(self._matching(stmt))


class FakeExecResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeResult(self._rows)


class FakePrincipal:
    def __init__(self, org_ids=(ORG_A,), role="owner"):
        self._org_ids = set(org_ids)
        self._role = role
        self.id = USER_ID

    def org_ids(self):
        return set(self._org_ids)

    def require_member_of(self, organization_id):
        if organization_id not in self._org_ids:
            raise NotFound("no access")

    def require_org_role(self, organization_id, minimum):
        self.require_member_of(organization_id)
        assert self._role in ("org_admin", "owner")
        return None


def make_endpoint(session, *, org=ORG_A, status="active", events=("farm.updated",),
                  secret=SECRET, failures=0) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        organization_id=org,
        url="https://receiver.example.com/hook",
        secret=secret,
        event_types=list(events),
        status=status,
        description="",
        consecutive_failures=failures,
    )
    session.add(endpoint)
    return endpoint


def make_delivery(session, endpoint, *, event="farm.updated", event_id="evt-1",
                  status="pending", attempt=0) -> WebhookDelivery:
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id,
        organization_id=endpoint.organization_id,
        event_type=event,
        event_id=event_id,
        payload={
            "id": str(uuid.uuid4()),
            "event": event,
            "created_at": NOW.isoformat(),
            "org_id": str(endpoint.organization_id),
            "data": {"entity_id": event_id},
        },
        attempt=attempt,
        status=status,
        next_retry_at=NOW,
    )
    session.add(delivery)
    return delivery


@pytest.fixture(autouse=True)
def restore_settings(monkeypatch):
    """Snapshot webhook-related settings; each test gets pristine values."""
    monkeypatch.setattr(config.settings, "webhook_max_attempts", 5)
    monkeypatch.setattr(config.settings, "webhook_backoff_seconds", [30, 120, 600, 3600, 21600])


# ---------------------------------------------------------------------------
# signing
# ---------------------------------------------------------------------------
def test_sign_and_verify_roundtrip():
    body = b'{"event":"farm.updated"}'
    header = webhooks.sign_payload(SECRET, body, 1_700_000_000)
    assert header.startswith("t=1700000000,v1=")
    mac = header.split("v1=", 1)[1]
    expected = hmac_mod.new(
        SECRET.encode(), b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    assert mac == expected
    assert webhooks.verify_signature(
        SECRET, body, header, tolerance_seconds=300,
        now=datetime.fromtimestamp(1_700_000_000, tz=UTC),
    )


def test_verify_rejects_tampered_body():
    body = b'{"amount":1}'
    header = webhooks.sign_payload(SECRET, body, int(NOW.timestamp()))
    assert not webhooks.verify_signature(SECRET, b'{"amount":2}', header, now=NOW)
    # extra trailing byte also breaks it — signature covers exact bytes
    assert not webhooks.verify_signature(SECRET, body + b" ", header, now=NOW)


def test_verify_rejects_wrong_secret():
    body = b"payload"
    header = webhooks.sign_payload(SECRET, body, int(NOW.timestamp()))
    assert not webhooks.verify_signature("whsec_other", body, header, now=NOW)


def test_verify_timestamp_tolerance():
    body = b"payload"
    ts = int(NOW.timestamp())
    header = webhooks.sign_payload(SECRET, body, ts)
    assert webhooks.verify_signature(SECRET, body, header, tolerance_seconds=300, now=NOW)
    assert webhooks.verify_signature(
        SECRET, body, header, tolerance_seconds=300,
        now=NOW + timedelta(seconds=300),
    )
    assert not webhooks.verify_signature(
        SECRET, body, header, tolerance_seconds=300,
        now=NOW + timedelta(seconds=301),
    )
    assert not webhooks.verify_signature(
        SECRET, body, header, tolerance_seconds=300,
        now=NOW - timedelta(seconds=301),
    )
    # tolerance disabled (None) → any timestamp verifies on MAC match
    assert webhooks.verify_signature(
        SECRET, body, header, tolerance_seconds=None,
        now=NOW + timedelta(days=30),
    )


def test_verify_rejects_malformed_headers():
    body = b"payload"
    good = webhooks.sign_payload(SECRET, body, int(NOW.timestamp()))
    assert not webhooks.verify_signature(SECRET, body, None, now=NOW)
    assert not webhooks.verify_signature(SECRET, body, "", now=NOW)
    assert not webhooks.verify_signature(SECRET, body, "garbage", now=NOW)
    assert not webhooks.verify_signature(SECRET, body, "t=notanumber,v1=ff", now=NOW)
    assert not webhooks.verify_signature(SECRET, body, "t=123", now=NOW)  # missing v1
    assert not webhooks.verify_signature(SECRET, body, good.replace("v1=", "v2="), now=NOW)
    assert not webhooks.verify_signature(SECRET, body, good[:-4], now=NOW)


def test_canonical_body_is_deterministic_json():
    payload = {"b": 1, "a": {"d": [2, 1], "c": "x"}}
    body = webhooks.canonical_body(payload)
    assert body == b'{"a":{"c":"x","d":[2,1]},"b":1}'
    assert webhooks.canonical_body(payload) == body  # stable across calls
    # the deterministic body is what gets signed
    header = webhooks.sign_payload(SECRET, body, int(NOW.timestamp()))
    assert webhooks.verify_signature(SECRET, body, header, now=NOW)


# ---------------------------------------------------------------------------
# backoff
# ---------------------------------------------------------------------------
def test_backoff_follows_configured_schedule():
    assert webhooks._backoff_delay(1) == 30.0
    assert webhooks._backoff_delay(2) == 120.0
    assert webhooks._backoff_delay(3) == 600.0
    assert webhooks._backoff_delay(4) == 3600.0
    assert webhooks._backoff_delay(5) == 21600.0
    # beyond the schedule → clamped to the last entry (no unbounded growth)
    assert webhooks._backoff_delay(99) == 21600.0


def test_backoff_scalar_exponential_form():
    assert webhooks._backoff_delay(1, backoff=30) == 30.0
    assert webhooks._backoff_delay(2, backoff=30) == 60.0
    assert webhooks._backoff_delay(3, backoff=30) == 120.0  # 30 * 2**(3-1)


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------
def test_emit_event_creates_pending_deliveries_for_matching_endpoints():
    session = FakeSession()
    subscribed = make_endpoint(session)  # active + subscribed
    make_endpoint(session, events=("report.ready",))  # active, NOT subscribed
    make_endpoint(session, status="disabled")  # subscribed but disabled

    deliveries = webhooks.emit_event(
        session, ORG_A, "farm.updated", payload_id="farm-1",
        data={"farm_id": "farm-1", "name": "Riverbend"},
    )
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.endpoint_id == subscribed.id
    assert delivery.organization_id == ORG_A
    assert delivery.status == "pending" and delivery.attempt == 0
    assert delivery.event_id == "farm-1"
    assert delivery.next_retry_at is not None
    payload = delivery.payload
    assert payload["id"] == str(delivery.id)
    assert payload["event"] == "farm.updated"
    assert payload["org_id"] == str(ORG_A)
    assert payload["data"] == {"farm_id": "farm-1", "name": "Riverbend"}
    assert "created_at" in payload


def test_emit_event_is_idempotent_per_payload_id():
    session = FakeSession()
    make_endpoint(session)
    first = webhooks.emit_event(session, ORG_A, "farm.updated", payload_id="farm-1")
    second = webhooks.emit_event(session, ORG_A, "farm.updated", payload_id="farm-1")
    assert len(first) == 1 and second == []
    # distinct payload ids create distinct deliveries
    third = webhooks.emit_event(session, ORG_A, "farm.updated", payload_id="farm-2")
    assert len(third) == 1


def test_emit_event_without_payload_id_uses_fresh_event_id():
    session = FakeSession()
    make_endpoint(session)
    a = webhooks.emit_event(session, ORG_A, "farm.updated")
    b = webhooks.emit_event(session, ORG_A, "farm.updated")
    assert len(a) == 1 and len(b) == 1
    assert a[0].event_id != b[0].event_id  # unique uuid → no dedupe collision


def test_emit_event_unknown_type_and_other_org():
    session = FakeSession()
    make_endpoint(session, org=ORG_B)
    with pytest.raises(ValidationFailed):
        webhooks.emit_event(session, ORG_A, "farm.exploded")
    # endpoints of another org are never touched
    assert webhooks.emit_event(session, ORG_A, "farm.updated") == []


def test_emitters_module_reexports():
    from app.publicapi.emitters import EVENT_TYPES, emit_event

    assert emit_event is webhooks.emit_event
    assert set(EVENT_TYPES) == {
        "farm.updated", "field.created", "crop_cycle.updated",
        "recommendation.generated", "report.ready", "alert.raised",
        "subscription.updated",
    }


# ---------------------------------------------------------------------------
# delivery state machine
# ---------------------------------------------------------------------------
def test_record_success_delivers_and_resets_failures():
    session = FakeSession()
    endpoint = make_endpoint(session, failures=3)
    delivery = make_delivery(session, endpoint, status="failed", attempt=2)
    webhooks._record_success(delivery, endpoint, status_code=200, now=NOW)
    assert delivery.status == "delivered"
    assert delivery.attempt == 3
    assert delivery.delivered_at == NOW
    assert delivery.last_status_code == 200
    assert delivery.last_error is None
    assert delivery.next_retry_at is None
    assert endpoint.consecutive_failures == 0


def test_record_failure_schedules_backoff():
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)
    assert webhooks._record_failure(
        delivery, endpoint, error="receiver returned HTTP 500",
        status_code=500, now=NOW,
    ) == "failed"
    assert delivery.status == "failed" and delivery.attempt == 1
    assert delivery.next_retry_at == NOW + timedelta(seconds=30)
    assert endpoint.consecutive_failures == 1
    # second failure → second schedule step
    webhooks._record_failure(delivery, endpoint, error="boom", now=NOW)
    assert delivery.attempt == 2
    assert delivery.next_retry_at == NOW + timedelta(seconds=120)


def test_record_failure_dead_letters_after_max_attempts(monkeypatch):
    monkeypatch.setattr(config.settings, "webhook_max_attempts", 3)
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)
    for i in range(1, 3):
        assert webhooks._record_failure(
            delivery, endpoint, error=f"fail {i}", now=NOW
        ) == "failed"
    final = webhooks._record_failure(delivery, endpoint, error="fail 3", now=NOW)
    assert final == "dead"
    assert delivery.status == "dead"
    assert delivery.attempt == 3
    assert delivery.next_retry_at is None  # never retried again
    assert "dead-lettered after 3 attempt(s)" in delivery.last_error


def test_endpoint_auto_disables_after_five_consecutive_failures(monkeypatch):
    monkeypatch.setattr(config.settings, "webhook_max_attempts", 50)
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)
    for i in range(4):
        webhooks._record_failure(delivery, endpoint, error=f"fail {i}", now=NOW)
        assert endpoint.status == "active"
    webhooks._record_failure(delivery, endpoint, error="fail 4", now=NOW)
    assert endpoint.status == "disabled"
    assert endpoint.disabled_reason and "auto-disabled" in endpoint.disabled_reason
    # further failures do not rewrite the reason
    webhooks._record_failure(delivery, endpoint, error="fail 5", now=NOW)
    assert "auto-disabled" in endpoint.disabled_reason


def test_disabled_endpoint_skips_delivery():
    session = FakeSession()
    endpoint = make_endpoint(session, status="disabled")
    delivery = make_delivery(session, endpoint)
    result = webhooks.deliver_webhook(session, delivery.id, now=NOW)
    assert result["skipped"] == "endpoint_disabled"
    assert delivery.attempt == 0 and delivery.status == "pending"


def test_deliver_webhook_success_signs_exact_bytes():
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    result = webhooks.deliver_webhook(
        session, delivery.id, transport=httpx.MockTransport(handler), now=NOW
    )
    assert result["status"] == "delivered"
    assert captured["url"] == endpoint.url
    # deterministic canonical body was sent and signed
    assert captured["body"] == webhooks.canonical_body(delivery.payload)
    assert captured["headers"][webhooks.EVENT_HEADER.lower()] == "farm.updated"
    assert captured["headers"][webhooks.EVENT_ID_HEADER.lower()] == str(delivery.id)
    sig = captured["headers"][webhooks.SIGNATURE_HEADER.lower()]
    # verify against the timestamp the SENDER used (parsed from the header) —
    # proves the receiver-side verification path end to end
    sent_t = int(sig.split(",")[0].split("=", 1)[1])
    assert webhooks.verify_signature(
        SECRET, captured["body"], sig, tolerance_seconds=300,
        now=datetime.fromtimestamp(sent_t, tz=UTC),
    )
    assert delivery.status == "delivered" and delivery.last_status_code == 200
    assert delivery.delivered_at == NOW
    assert endpoint.consecutive_failures == 0
    assert session.commits == 1


def test_deliver_webhook_http_error_schedules_retry():
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    result = webhooks.deliver_webhook(
        session, delivery.id, transport=httpx.MockTransport(handler), now=NOW
    )
    assert result["status"] == "failed"
    assert delivery.last_status_code == 503
    assert "HTTP 503" in (delivery.last_error or "")
    assert delivery.next_retry_at == NOW + timedelta(seconds=30)
    assert endpoint.consecutive_failures == 1


def test_deliver_webhook_transport_error_counts_as_failure():
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = webhooks.deliver_webhook(
        session, delivery.id, transport=httpx.MockTransport(handler), now=NOW
    )
    assert result["status"] == "failed"
    assert delivery.last_status_code is None
    assert "transport error" in (delivery.last_error or "")
    assert delivery.next_retry_at == NOW + timedelta(seconds=30)


def test_deliver_webhook_missing_delivery_is_404():
    session = FakeSession()
    with pytest.raises(NotFound):
        webhooks.deliver_webhook(session, uuid.uuid4())


def test_retry_due_webhooks_sweeps_due_deliveries(monkeypatch):
    session = FakeSession()
    endpoint = make_endpoint(session)
    due = make_delivery(session, endpoint, event_id="due-1")  # pending, next_retry NOW
    future = make_delivery(session, endpoint, event_id="future-1")
    future.next_retry_at = NOW + timedelta(hours=1)
    delivered = make_delivery(session, endpoint, event_id="done-1", status="delivered")

    calls: list[uuid.UUID] = []

    def fake_deliver(session_, delivery_id, **kwargs):
        """Network-free stand-in for one delivery attempt."""
        calls.append(delivery_id)
        d = session_.get(WebhookDelivery, delivery_id)
        endpoint_ = session_.get(WebhookEndpoint, d.endpoint_id)
        d.status = "delivered"
        d.attempt = int(d.attempt or 0) + 1
        d.delivered_at = NOW
        d.next_retry_at = None
        endpoint_.consecutive_failures = 0
        return {"delivery_id": str(delivery_id), "status": "delivered", "attempt": d.attempt}

    monkeypatch.setattr(webhooks, "deliver_webhook", fake_deliver)
    counts = webhooks.retry_due_webhooks(session, now=NOW, batch=50)
    assert calls == [due.id]  # only the DUE pending delivery
    assert counts == {"attempted": 1, "delivered": 1, "failed": 0, "dead": 0, "skipped": 0}
    assert due.status == "delivered"


# ---------------------------------------------------------------------------
# endpoint service guards (tenant scoping / role gates) — fake-session level
# ---------------------------------------------------------------------------
def test_redeliver_resets_pending_and_rejects_delivered():
    session = FakeSession()
    endpoint = make_endpoint(session)
    delivery = make_delivery(session, endpoint, status="dead", attempt=5)
    delivery.last_error = "dead-lettered"
    principal = FakePrincipal(role="org_admin")
    out = webhooks.redeliver(session, principal, delivery_id=delivery.id, now=NOW)
    assert out.status == "pending" and out.attempt == 0
    assert out.next_retry_at == NOW and out.last_error is None
    with pytest.raises(Conflict):
        ok = make_delivery(session, endpoint, event_id="ok", status="delivered")
        webhooks.redeliver(session, principal, delivery_id=ok.id)
    # cross-org delivery is a 404
    foreign = FakeSession()
    foreign_endpoint = make_endpoint(foreign, org=ORG_B)
    foreign_delivery = make_delivery(foreign, foreign_endpoint, event_id="x")
    with pytest.raises(NotFound):
        webhooks.redeliver(session, principal, delivery_id=foreign_delivery.id)


def test_webhook_endpoint_payload_never_leaks_secret():
    session = FakeSession()
    endpoint = make_endpoint(session)
    payload = webhooks.webhook_endpoint_payload(endpoint)
    assert "secret" not in payload
    assert SECRET not in json.dumps(payload)
    assert payload["url"] == endpoint.url
    assert payload["status"] == "active"


def test_validate_webhook_url_rules(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "development")
    assert webhooks.validate_webhook_url("https://hooks.example.com/x") == (
        "https://hooks.example.com/x"
    )
    assert webhooks.validate_webhook_url("http://localhost:9000/hook") == (
        "http://localhost:9000/hook"
    )
    assert webhooks.validate_webhook_url("http://127.0.0.1/hook")
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("http://hooks.example.com/x")  # plain http, non-local
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("ftp://hooks.example.com")
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("https://user:pass@hooks.example.com")
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("")
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("https://" + "x" * 1100 + ".com")

    # production: even localhost must use https
    monkeypatch.setattr(config.settings, "environment", "production")
    with pytest.raises(ValidationFailed):
        webhooks.validate_webhook_url("http://localhost:9000/hook")


def test_webhook_rejects_private_ip_literals_and_dns_rebinding(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "production")
    for url in (
        "https://127.0.0.1/hook",
        "https://10.0.0.8/hook",
        "https://192.168.1.5/hook",
        "https://[::1]/hook",
        "https://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(ValidationFailed):
            webhooks.validate_webhook_url(url)

    monkeypatch.setattr(
        webhooks.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValidationFailed, match="private or non-global"):
        webhooks._resolve_pinned_address("rebound.example", 443, "https")


def test_webhook_dns_resolution_pins_public_address(monkeypatch):
    monkeypatch.setattr(
        webhooks.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    assert webhooks._resolve_pinned_address("hooks.example", 443, "https") == "8.8.8.8"


def test_validate_event_types_rules():
    assert webhooks.validate_event_types(["report.ready", "farm.updated"]) == [
        "farm.updated", "report.ready",
    ]
    with pytest.raises(ValidationFailed):
        webhooks.validate_event_types([])
    with pytest.raises(ValidationFailed):
        webhooks.validate_event_types(["farm.updated", "not.an.event"])


def test_billing_webhook_signatures_reject_stale_and_future_timestamps():
    from app.billing.provider import SandboxBillingProvider

    provider = SandboxBillingProvider(secret="unit-test-secret")
    payload = {"event_type": "payment.succeeded", "event_id": "event-1"}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    now = int(time.time())
    valid = f"{now}." + provider.sign_webhook(
        payload=payload, secret="unit-test-secret", timestamp=str(now)
    )
    stale_ts = now - 601
    stale = f"{stale_ts}." + provider.sign_webhook(
        payload=payload, secret="unit-test-secret", timestamp=str(stale_ts)
    )
    future_ts = now + 601
    future = f"{future_ts}." + provider.sign_webhook(
        payload=payload, secret="unit-test-secret", timestamp=str(future_ts)
    )
    assert provider.verify_webhook(payload=raw, signature=valid, secret="unit-test-secret")
    assert not provider.verify_webhook(payload=raw, signature=stale, secret="unit-test-secret")
    assert not provider.verify_webhook(payload=raw, signature=future, secret="unit-test-secret")
    assert not provider.verify_webhook(
        payload=raw, signature="not-a-timestamp.mac", secret="unit-test-secret"
    )


def test_developer_event_activity_written():
    """create_webhook_endpoint writes the developer.webhook_created activity
    event + audit trail (caller-visible history)."""
    session = FakeSession()
    principal = FakePrincipal(role="org_admin")
    endpoint, secret = webhooks.create_webhook_endpoint(
        session, principal, url="https://hooks.example.com/x",
        events=["farm.updated"], description="ops receiver",
    )
    assert secret.startswith(webhooks.WEBHOOK_SECRET_PREFIX)
    assert endpoint.secret == secret  # model stores the signing secret (see notes)
    activities = [o for o in session.objects if isinstance(o, ActivityEvent)]
    assert any(a.event_type == "developer.webhook_created" for a in activities)
    assert session.commits == 1

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from app.api.v1 import auth as auth_routes
from app.core.config import settings
from app.db.models import Organization, User
from app.domains.identity import delivery
from app.domains.identity.delivery import EmailDeliveryUnavailable, SMTPEmailDeliveryAdapter
from app.domains.identity.delivery_config import (
    SMTPConfigurationError,
    SMTPSettings,
    load_smtp_settings,
)
from app.domains.identity import service as identity_service


class FakeDelivery:
    def __init__(self):
        self.messages: list[tuple[str, str, str]] = []
        self.fail: Exception | None = None

    def send_email(self, recipient: str, subject: str, text_body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.messages.append((recipient, subject, text_body))


def _user(email: str = "synthetic@example.test") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="synthetic-hash",
        display_name="Synthetic User",
        email_verified=False,
    )


def test_smtp_config_is_environment_only_tls_mandatory_and_timeout_bounded():
    prefix = "FIELDSHIFT_EMAIL_SMTP_"
    config = load_smtp_settings(
        {
            prefix + "HOST": "smtp.example.test",
            prefix + "FROM_ADDRESS": "no-reply@example.test",
            prefix + "USERNAME": "synthetic-user",
            prefix + "PASSWORD": "synthetic-password",
        }
    )
    assert config is not None
    assert config.tls_mode == "starttls"
    assert config.timeout_seconds == 10
    assert config.username == "synthetic-user"
    assert load_smtp_settings({}) is None

    with pytest.raises(SMTPConfigurationError):
        load_smtp_settings({prefix + "HOST": "smtp.example.test"})
    with pytest.raises(SMTPConfigurationError):
        load_smtp_settings(
            {
                prefix + "HOST": "smtp.example.test",
                prefix + "FROM_ADDRESS": "no-reply@example.test",
                prefix + "TLS_MODE": "plain",
            }
        )
    with pytest.raises(SMTPConfigurationError):
        load_smtp_settings(
            {
                prefix + "HOST": "smtp.example.test",
                prefix + "FROM_ADDRESS": "no-reply@example.test",
                prefix + "TIMEOUT_SECONDS": "31",
            }
        )


def test_smtp_adapter_uses_starttls_and_a_bounded_socket(monkeypatch):
    calls: list[object] = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("close",))

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self, *, context):
            calls.append(("starttls", context))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"], message.get_content()))

    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    adapter = SMTPEmailDeliveryAdapter(
        SMTPSettings(
            host="smtp.example.test",
            port=587,
            from_address="no-reply@example.test",
            tls_mode="starttls",
            timeout_seconds=4,
            username="test-user",
            password="test-password",
        )
    )
    adapter.send_email("recipient@example.test", "Synthetic subject", "Synthetic body")

    assert calls[0] == ("connect", "smtp.example.test", 587, 4)
    assert any(call[0] == "starttls" for call in calls)
    assert ("login", "test-user", "test-password") in calls
    sent = next(call for call in calls if call[0] == "send")
    assert sent[1:] == ("recipient@example.test", "Synthetic subject", "Synthetic body\n")


def test_production_registration_requires_delivery_before_any_database_write(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(delivery, "get_email_delivery_adapter", lambda: None)
    db = Mock()

    with pytest.raises(EmailDeliveryUnavailable) as exc_info:
        identity_service.register_user(
            db,
            email="person@example.test",
            password="synthetic-password",
            display_name="Synthetic",
        )

    assert exc_info.value.status_code == 503
    assert db.scalar.call_count == 0
    assert db.add.call_count == 0
    assert db.flush.call_count == 0
    assert db.commit.call_count == 0


@pytest.mark.parametrize(
    "request_function",
    [identity_service.request_password_reset, identity_service.request_email_verification],
)
def test_production_reset_and_resend_require_delivery_before_lookup(monkeypatch, request_function):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(delivery, "get_email_delivery_adapter", lambda: None)
    db = Mock()

    with pytest.raises(EmailDeliveryUnavailable) as exc_info:
        request_function(db, "person@example.test")

    assert exc_info.value.status_code == 503
    db.scalar.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_fake_smtp_registration_delivers_challenge_without_returning_it(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    fake = FakeDelivery()
    db = Mock()
    db.scalar.return_value = None

    user, org, access, access_exp, refresh, refresh_exp = identity_service.register_user(
        db,
        email=" PERSON@example.test ",
        password="synthetic-password",
        display_name="Synthetic",
        delivery_adapter=fake,
    )

    assert user.email == "person@example.test"
    assert org is not None
    assert (access, access_exp, refresh, refresh_exp) == (None, None, None, None)
    assert len(fake.messages) == 1
    recipient, subject, body = fake.messages[0]
    assert recipient == "person@example.test"
    assert "verify" in subject.lower()
    delivered_token = body.splitlines()[2]
    assert delivered_token
    assert delivered_token not in (access, refresh)
    assert db.commit.call_count == 1
    credential_rows = [
        call.args[0] for call in db.add.call_args_list
        if getattr(call.args[0], "kind", None) == "email_verification"
    ]
    assert len(credential_rows) == 1
    assert credential_rows[0].token_hash != delivered_token


def test_registration_delivery_failure_rolls_back_unverified_account(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    fake = FakeDelivery()
    fake.fail = OSError("synthetic SMTP outage")
    db = Mock()
    db.scalar.return_value = None

    with pytest.raises(EmailDeliveryUnavailable) as exc_info:
        identity_service.register_user(
            db,
            email="rollback@example.test",
            password="synthetic-password",
            display_name="Rollback User",
            delivery_adapter=fake,
        )

    assert exc_info.value.status_code == 503
    db.rollback.assert_called_once_with()
    db.commit.assert_not_called()


def test_fake_delivery_serves_verification_and_password_reset_and_rolls_back_failures(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    user = _user()
    db = Mock()
    db.scalar.return_value = user
    fake = FakeDelivery()

    verification_token = identity_service.request_email_verification(
        db, user.email, delivery_adapter=fake
    )
    reset_token = identity_service.request_password_reset(
        db, user.email, delivery_adapter=fake
    )
    assert verification_token and reset_token
    assert [message[0] for message in fake.messages] == [user.email, user.email]
    assert verification_token in fake.messages[0][2]
    assert reset_token in fake.messages[1][2]
    assert "verify" in fake.messages[0][1].lower()
    assert "reset" in fake.messages[1][1].lower()
    assert db.commit.call_count == 2

    failing = FakeDelivery()
    failing.fail = OSError("synthetic SMTP failure")
    failed_db = Mock()
    failed_db.scalar.return_value = user
    with pytest.raises(EmailDeliveryUnavailable) as exc_info:
        identity_service.request_password_reset(
            failed_db, user.email, delivery_adapter=failing
        )
    assert exc_info.value.status_code == 503
    failed_db.rollback.assert_called_once_with()
    failed_db.commit.assert_not_called()


def test_production_auth_responses_do_not_claim_queue_or_expose_challenges(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 0)
    monkeypatch.setattr(
        auth_routes,
        "request_email_verification",
        lambda db, email: "synthetic-verification-token",
    )
    monkeypatch.setattr(
        auth_routes,
        "request_password_reset",
        lambda db, email: "synthetic-reset-token",
    )
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )
    db = Mock()

    verify_response = auth_routes.verify_email_request(
        auth_routes.EmailVerificationRequest(email="person@example.test"), request, db
    )
    reset_response = auth_routes.password_reset(
        auth_routes.PasswordResetRequest(email="person@example.test"), request, db
    )
    verify_body = verify_response
    reset_body = reset_response
    assert verify_body["status"] == reset_body["status"] == "accepted"
    assert "queued" not in verify_body["status"]
    assert "verification_token" not in verify_body
    assert "reset_token" not in reset_body
    assert "synthetic-verification-token" not in json.dumps(verify_body)
    assert "synthetic-reset-token" not in json.dumps(reset_body)


def test_production_registration_route_never_exposes_the_challenge(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 0)
    user = _user("signup@example.test")
    organization = Organization(id=uuid.uuid4(), name="Synthetic Organization")
    monkeypatch.setattr(
        auth_routes,
        "register_user",
        lambda db, **kwargs: (user, organization, None, None, None, None),
    )
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )

    response = auth_routes.register(
        auth_routes.RegisterRequest(
            email=user.email, password="synthetic-password", display_name="Synthetic"
        ),
        request,
        Mock(),
    )

    body = json.loads(response.body)
    assert response.status_code == 202
    assert body["status"] == "verification_required"
    assert "token" not in body
    assert "verification_token" not in body


def test_development_registration_keeps_existing_session_fixture_behavior(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", True)
    fake = FakeDelivery()
    db = Mock()
    db.scalar.return_value = None

    user, _org, access, access_exp, refresh, refresh_exp = identity_service.register_user(
        db,
        email="dev@example.test",
        password="synthetic-password",
        display_name="Dev",
        delivery_adapter=fake,
    )

    assert user.email_verified is True
    assert access and access_exp and refresh and refresh_exp
    assert fake.messages == []
    db.commit.assert_called_once_with()

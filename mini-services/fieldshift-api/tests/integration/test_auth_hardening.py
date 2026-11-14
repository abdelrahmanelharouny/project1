"""Integration: auth hardening (P0-2) — refresh rotation with family reuse
detection, kind-scoped bearer auth, account lockout, per-IP rate limiting,
password reset, email verification gate, membership RBAC matrix, audit trail.

Mirrors tests/integration/test_auth_tenant_isolation.py fixture usage. The
suite-wide env disables the rate limiter (conftest); these tests patch
settings attributes directly and reset the limiter store per test.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.rate_limit import _reset_store
from app.db.models import AuditEvent, AuthToken, Membership, User
from app.domains.identity.service import (
    _issue_token_pair,
    confirm_email_verification,
    request_email_verification,
)

PASSWORD = "test-password-1"

GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
}


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    _reset_store()
    yield
    _reset_store()


def _register(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:10]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Farmer"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _create_farm(client, headers, name):
    return client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": name, "country_code": "EG", "timezone": "Africa/Cairo", "currency_code": "EGP"},
    )


class TestRefreshRotation:
    def test_refresh_issues_new_pair_and_reuse_revokes_family(self, client):
        data = _register(client)
        old_access = data["token"]
        refresh = data["refresh_token"]
        assert old_access and refresh
        assert data["refresh_expires_at"]

        rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert rotated.status_code == 200, rotated.text
        body = rotated.json()
        assert body["token"] and body["token"] != old_access
        assert body["refresh_token"] != refresh
        assert body["token_type"] == "bearer"
        assert body["user"]["id"] == data["user"]["id"]
        assert body["organization"]["id"] == data["organization"]["id"]

        # Reuse of the OLD (already rotated) refresh token → 401 ...
        reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert reuse.status_code == 401
        assert reuse.json()["error"]["code"] == "UNAUTHORIZED"

        # ... AND family-wide revocation: the old access token, the rotated
        # access token and the rotated refresh token are all dead.
        assert (
            client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_access}"}).status_code
            == 401
        )
        assert (
            client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"}).status_code
            == 401
        )
        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code
            == 401
        )

    def test_refresh_token_never_authenticates_api(self, client):
        # Bearer lookup MUST filter AuthToken.kind == "access".
        data = _register(client)
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {data['refresh_token']}"})
        assert me.status_code == 401


class TestLockout:
    def test_lockout_after_threshold_and_success_resets_counter(self, client, monkeypatch):
        monkeypatch.setattr(settings, "auth_max_failed_logins", 3)
        data = _register(client)
        email = data["user"]["email"]

        # Two failures stay below the threshold; a correct login resets it.
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email).status_code == 200
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email).status_code == 200

        # Third CONSECUTIVE failure locks the account: the correct password
        # is now rejected with 423 before the password is even checked.
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email, "wrong-password").status_code == 401
        assert _login(client, email, "wrong-password").status_code == 401
        locked = _login(client, email)
        assert locked.status_code == 423
        body = locked.json()
        assert body["error"]["code"] == "ACCOUNT_LOCKED"
        assert body["error"]["details"][0]["retry_after_seconds"] >= 1


class TestRateLimit:
    def test_login_rate_limited_per_ip(self, client, monkeypatch):
        data = _register(client)  # registration runs with the limiter disabled
        monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 2)
        email = data["user"]["email"]

        assert _login(client, email).status_code == 200
        assert _login(client, email).status_code == 200
        third = _login(client, email)
        assert third.status_code == 429
        assert third.json()["error"]["code"] == "RATE_LIMITED"
        assert int(third.headers["Retry-After"]) >= 1


class TestPasswordReset:
    def test_reset_flow_revokes_sessions_and_rotates_password(self, client):
        data = _register(client)
        email = data["user"]["email"]
        old_access = data["token"]

        resp = client.post("/api/v1/auth/password-reset", json={"email": email})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["message"] == "If the account exists, a password reset has been initiated."
        reset_token = body["reset_token"]  # dev_mode sandbox/testing convenience
        assert reset_token

        # Unknown email: identical generic shape, no token, no enumeration.
        ghost = client.post(
            "/api/v1/auth/password-reset", json={"email": f"ghost-{uuid.uuid4().hex[:6]}@test.local"}
        )
        assert ghost.status_code == 202
        assert ghost.json()["status"] == "queued"
        assert "reset_token" not in ghost.json()

        confirm = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": "brand-new-password-9"},
        )
        assert confirm.status_code == 200
        assert confirm.json() == {"status": "ok"}

        # Challenges are single-use.
        replay = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": "another-password-9"},
        )
        assert replay.status_code == 422

        # All pre-reset session tokens (access AND refresh) are revoked.
        assert (
            client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_access}"}).status_code
            == 401
        )
        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code
            == 401
        )
        # Old password rejected; new password works.
        assert _login(client, email, PASSWORD).status_code == 401
        assert _login(client, email, "brand-new-password-9").status_code == 200


class TestEmailVerification:
    def test_unverified_login_gated_until_verified(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "dev_mode", False)
        from app.domains.identity import delivery

        class RecordingEmailAdapter:
            def __init__(self):
                self.sent = []

            def send_email(self, recipient, subject, text_body):
                self.sent.append((recipient, subject))

        adapter = RecordingEmailAdapter()
        monkeypatch.setattr(delivery, "get_email_delivery_adapter", lambda: adapter)
        email = f"unverified-{uuid.uuid4().hex[:8]}@test.local"
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "display_name": "Farmer"},
        )
        assert registered.status_code == 202
        registration_body = registered.json()
        assert registration_body["status"] == "verification_required"
        assert "token" not in registration_body
        assert "refresh_token" not in registration_body
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None and user.email_verified is False
        assert db.scalars(select(AuthToken).where(AuthToken.user_id == user.id)).all() == []

        gated = _login(client, email)
        assert gated.status_code == 403
        assert gated.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

        # Even an access/refresh token issued by an older or alternate path
        # cannot authenticate an unverified account.
        access, _, refresh, _ = _issue_token_pair(db, user.id, uuid.uuid4())
        db.commit()
        assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"}).status_code == 403
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 403

        # API request keeps the generic shape (no token leaked outside dev_mode).
        resp = client.post("/api/v1/auth/verify-email/request", json={"email": email})
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"
        assert "verification_token" not in resp.json()

        # The plaintext challenge is internal — fetch it from the service.
        token = request_email_verification(db, email)
        assert token
        user = confirm_email_verification(db, token)
        assert user.email_verified is True

        ok = _login(client, email)
        assert ok.status_code == 200
        assert len(adapter.sent) == 3

    def test_missing_delivery_fails_closed_without_account_creation(
        self, client, db, monkeypatch
    ):
        monkeypatch.setattr(settings, "dev_mode", False)
        from app.domains.identity import delivery

        monkeypatch.setattr(delivery, "get_email_delivery_adapter", lambda: None)
        email = f"no-mail-{uuid.uuid4().hex[:8]}@test.local"
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "display_name": "Farmer"},
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "EMAIL_DELIVERY_UNAVAILABLE"
        assert db.scalar(select(User).where(User.email == email)) is None
        assert db.scalars(select(AuthToken).where(AuthToken.user_id.is_(None))).all() == []


class TestRbacMatrix:
    def test_role_matrix_and_last_owner_guard(self, client, db):
        owner = _register(client)  # org A
        owner_headers = {"Authorization": f"Bearer {owner['token']}"}
        subscription = client.post(
            "/api/v1/billing/subscription",
            headers=owner_headers,
            json={
                "organization_id": owner["organization"]["id"],
                "plan_code": "starter",
                "billing_period": "monthly",
            },
        )
        assert subscription.status_code == 200, subscription.text
        farm_resp = _create_farm(client, owner_headers, "Home Farm")
        assert farm_resp.status_code == 201, farm_resp.text
        farm = farm_resp.json()
        field_resp = client.post(
            f"/api/v1/farms/{farm['id']}/fields",
            headers=owner_headers,
            json={"name": "North Field", "geometry": GEOMETRY},
        )
        assert field_resp.status_code == 201, field_resp.text
        field = field_resp.json()

        viewer = _register(client)  # org B (their own registration org)
        viewer_headers = {"Authorization": f"Bearer {viewer['token']}"}

        # Owner adds the org-B user to org A as 'viewer'.
        resp = client.post(
            f"/api/v1/farms/{farm['id']}/members",
            headers=owner_headers,
            json={"email": viewer["user"]["email"], "role_code": "viewer"},
        )
        assert resp.status_code == 201, resp.text
        member_payload = resp.json()
        viewer_membership_id = member_payload["id"]
        assert {"id", "user_id", "email", "display_name", "role_code", "status", "created_at"} <= set(member_payload)

        # Farm creation must target the selected organization explicitly for
        # multi-organization principals; it must not guess the oldest member.
        own_farm = client.post(
            "/api/v1/farms",
            headers=viewer_headers,
            json={
                "organization_id": viewer["organization"]["id"],
                "name": "Viewer Own Farm",
                "country_code": "EG",
            },
        )
        assert own_farm.status_code == 201, own_farm.text

        # viewer: read org-A farm OK; mutating org A 403; rotation run
        # creation 403 (agronomist+ required, BEFORE any engine work).
        assert client.get(f"/api/v1/farms/{farm['id']}", headers=viewer_headers).status_code == 200
        assert client.patch(
            f"/api/v1/farms/{farm['id']}",
            headers=viewer_headers,
            json={"name": "Hijack"},
        ).status_code == 403
        rotation = client.post(
            f"/api/v1/fields/{field['id']}/rotation-runs",
            headers=viewer_headers,
            json={"seasons": [{"label": "2025", "start_date": "2025-01-01", "end_date": "2025-06-30"}]},
        )
        assert rotation.status_code == 403
        assert rotation.json()["error"]["code"] == "FORBIDDEN"

        # Owner promotes viewer → manager.
        resp = client.patch(
            f"/api/v1/farms/{farm['id']}/members/{viewer_membership_id}",
            headers=owner_headers,
            json={"role_code": "manager"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_code"] == "manager"

        # Manager can create fields but member management stays owner-only.
        assert client.post(
            f"/api/v1/farms/{farm['id']}/fields",
            headers=viewer_headers,
            json={"name": "South Field", "geometry": GEOMETRY},
        ).status_code == 201
        assert (
            client.patch(
                f"/api/v1/farms/{farm['id']}/members/{viewer_membership_id}",
                headers=viewer_headers,
                json={"role_code": "manager"},
            ).status_code
            == 403
        )

        # Promote the viewer to org_admin, then prove equal role rank cannot
        # grant owner through the legacy farm-member mutation route.
        promoted = client.patch(
            f"/api/v1/farms/{farm['id']}/members/{viewer_membership_id}",
            headers=owner_headers,
            json={"role_code": "org_admin"},
        )
        assert promoted.status_code == 200, promoted.text
        elevation = client.patch(
            f"/api/v1/farms/{farm['id']}/members/{viewer_membership_id}",
            headers=viewer_headers,
            json={"role_code": "owner"},
        )
        assert elevation.status_code == 403

        members = client.get(
            f"/api/v1/farms/{farm['id']}/members", headers=owner_headers
        ).json()
        assert members["total"] == 2
        owner_membership_id = next(
            m["id"] for m in members["items"] if m["role_code"] == "owner"
        )

        # Last-owner guard: demoting / removing the sole owner is a 409.
        assert (
            client.patch(
                f"/api/v1/farms/{farm['id']}/members/{owner_membership_id}",
                headers=owner_headers,
                json={"role_code": "viewer"},
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/farms/{farm['id']}/members/{owner_membership_id}",
                headers=owner_headers,
            ).status_code
            == 409
        )


class TestAuthAudit:
    def test_login_outcomes_are_audited(self, client, db):
        data = _register(client)
        email = data["user"]["email"]
        assert _login(client, email).status_code == 200
        assert _login(client, email, "wrong-password").status_code == 401

        actions = {
            row.action
            for row in db.scalars(
                select(AuditEvent).where(AuditEvent.action.like("auth.login%"))
            ).all()
        }
        assert "auth.login.success" in actions
        assert "auth.login.failure" in actions

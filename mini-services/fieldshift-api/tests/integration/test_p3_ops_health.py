"""Integration: operational health endpoint (P3 W8 §8.3).

Coverage:
- anonymous access rejected (401)
- any authenticated user (even a plain viewer) gets the aggregate surface:
  db + scheduler + job/report/webhook depths + billing provider mode —
  the payload is aggregate-only (every user owns a personal org, so an
  org-role gate would be vacuous; there is zero tenant data here)
- NO secrets or emails anywhere in the payload; status is ok/degraded
- payload stays truthful: scheduler tasks enumerate the 6 maintenance jobs
"""

import uuid

import pytest


def _register(client, display_name: str) -> tuple[dict, dict]:
    email = f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def _invite(client, headers, org_id: str, role: str) -> dict:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/invitations",
        headers=headers,
        json={"email": f"invitee-{uuid.uuid4().hex[:8]}@test.local", "role_code": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_with_token(client, token: str, display_name: str) -> tuple[dict, dict]:
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@test.local",
            "password": "test-password-1",
            "display_name": display_name,
            "invite_token": token,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


class TestOpsHealthAccess:
    def test_anonymous_rejected(self, client):
        resp = client.get("/api/v1/ops/health")
        assert resp.status_code == 401

    def test_plain_member_gets_aggregate_surface_without_secrets(self, client):
        a_headers, a = _register(client, "OpsOwner")
        org = a["organization"]["id"]
        invite = _invite(client, a_headers, org, "viewer")
        v_headers, _v = _register_with_token(client, invite["token"], "OpsViewer")
        resp = client.get("/api/v1/ops/health", headers=v_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "token" not in str(body).lower()

    def test_org_admin_gets_aggregate_surface_without_secrets(self, client):
        a_headers, a = _register(client, "OpsAdmin")
        resp = client.get("/api/v1/ops/health", headers=a_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        # database section is aggregate + version only
        assert body["database"]["connected"] is True
        assert "latency_ms" in body["database"]
        # scheduler enumerates the maintenance tasks with last-run outcomes
        task_names = {t["name"] for t in body["scheduler"]["tasks"]}
        assert {
            "reports.execute_queued",
            "webhooks.retry_due",
            "billing.expire_stale",
            "notifications.purge_expired",
            "reports.recurring_and_retention",
            "activity.prune",
            "ai.retention",
            "public_api.retention",
        } <= task_names
        for run in body["scheduler"]["last_runs"].values():
            assert isinstance(run, dict)
        # aggregate counters only
        assert set(body["background_jobs"]) == {"queued", "running", "failed_24h"}
        assert set(body["report_queue"]) == {"queued", "running"}
        assert set(body["webhook_deliveries"]) == {
            "pending_or_retrying",
            "failed_24h",
            "dead_letter",
        }
        # billing surface names provider + mode, never credentials
        assert body["billing"]["mode"] in ("sandbox", "live", "test")
        # honesty: no emails/tokens/keys anywhere in the payload
        raw = str(body).lower()
        for banned in ("password", "token", "secret", "api_key", "@test.local"):
            assert banned not in raw, f"ops health leaked '{banned}'"

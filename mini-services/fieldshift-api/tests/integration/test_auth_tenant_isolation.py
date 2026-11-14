"""Integration: auth + tenant isolation (Master rule 17, §47, §54)."""

import uuid


class TestRegistrationAndLogin:
    def test_register_creates_user_org_and_token(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "fresh@test.local", "password": "test-password-1", "display_name": "Fresh"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["token"]
        assert body["organization"]["id"]
        assert body["user"]["email"] == "fresh@test.local"

    def test_duplicate_email_conflicts(self, client, auth_headers):
        email = auth_headers[1]["user"]["email"]
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "test-password-1", "display_name": "Dup"},
        )
        assert resp.status_code == 409

    def test_login_success_and_failure(self, client, auth_headers):
        headers, user = auth_headers
        ok = client.post(
            "/api/v1/auth/login", json={"email": user["user"]["email"], "password": "test-password-1"}
        )
        assert ok.status_code == 200
        bad = client.post(
            "/api/v1/auth/login", json={"email": user["user"]["email"], "password": "wrong-password"}
        )
        assert bad.status_code == 401

    def test_me_requires_token(self, client):
        assert client.get("/api/v1/me").status_code == 401

    def test_me_returns_memberships(self, client, auth_headers):
        headers, user = auth_headers
        me = client.get("/api/v1/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["user"]["id"] == user["user"]["id"]
        assert len(me.json()["organizations"]) == 1

    def test_logout_revokes_token_family(self, client, auth_headers):
        headers, user = auth_headers
        assert client.get("/api/v1/me", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/v1/me", headers=headers).status_code == 401
        assert client.post(
            "/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}
        ).status_code == 401

    def test_cookie_logout_revokes_token_family(self, client, auth_headers):
        _, user = auth_headers
        cookie = {"fs_token": user["token"]}
        assert client.get("/api/v1/me", cookies=cookie).status_code == 200
        assert client.post("/api/v1/auth/logout", cookies=cookie).status_code == 204
        assert client.get("/api/v1/me", cookies=cookie).status_code == 401
        assert client.post(
            "/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}
        ).status_code == 401


class TestTenantIsolation:
    def test_other_user_cannot_read_farm(self, client, farm_with_field):
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        farm_id = farm_with_field["farm"]["id"]
        resp = client.get(f"/api/v1/farms/{farm_id}", headers=other_headers)
        assert resp.status_code == 403

    def test_other_user_cannot_read_field(self, client, farm_with_field):
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        field_id = farm_with_field["field"]["id"]
        assert client.get(f"/api/v1/fields/{field_id}", headers=other_headers).status_code == 403
        assert client.get(f"/api/v1/fields/{field_id}/data-passport", headers=other_headers).status_code == 403
        assert client.get(f"/api/v1/fields/{field_id}/observations", headers=other_headers).status_code == 403
        assert client.get(f"/api/v1/fields/{field_id}/map", headers=other_headers).status_code == 403

    def test_other_user_cannot_ingest_into_field(self, client, farm_with_field):
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=other_headers,
            json={"provider_code": "synthetic", "variables": ["precipitation"],
                  "start_date": "2023-01-01", "end_date": "2023-01-31"},
        )
        assert resp.status_code == 403

    def test_farm_list_scoped_to_own_orgs(self, client, farm_with_field):
        headers, _ = farm_with_field["headers"], farm_with_field["user"]
        farms = client.get("/api/v1/farms", headers=headers).json()
        assert farms["total"] == 1
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_farms = client.get("/api/v1/farms", headers={"Authorization": f"Bearer {other['token']}"}).json()
        assert other_farms["total"] == 0

    def test_unknown_resource_ids_404_not_403(self, client, auth_headers):
        random_id = str(uuid.uuid4())
        assert client.get(f"/api/v1/farms/{random_id}", headers=auth_headers[0]).status_code == 404

"""Integration: P3 organization lifecycle over HTTP (orgs/invitations/
members/ownership/activity routers).

Mirrors the conventions of tests/integration/test_auth_tenant_isolation.py:
plain pytest classes, the shared `client` fixture, inline second-user
registration. Coverage:

- org create/list/get/patch (+ payload validation)
- tenant isolation: a non-member cannot GET/PATCH another user's org
- invitation create (token shown once) -> accept -> join flow
- role rules: non-admin rejected 403; only the owner grants owner/org_admin;
  a non-owner admin cannot change an owner's role; last-owner guard
- ownership transfer (previous owner demoted to org_admin)
- member removal (incl. self-removal refusal)
- activity timeline records the member.* / setting.changed events
"""

import uuid

import pytest


def _register(client, display_name: str) -> tuple[dict, dict]:
    """Register a fresh user; return (auth headers, registration body)."""
    email = f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def _create_org(client, headers, name: str = "Riverbend Farms") -> dict:
    resp = client.post(
        "/api/v1/orgs",
        headers=headers,
        json={"name": name, "organization_type": "farm_org", "country_code": "EG"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _org_story(client):
    """Owner A + org + manager B + viewer C (all joined through invitations).

    Returns (a_headers, b_headers, c_headers, org, a_user, b_user, c_user).
    """
    a_headers, a_user = _register(client, "Alice")
    org = _create_org(client, a_headers)

    b_headers, b_user = _register(client, "Bob")
    c_headers, c_user = _register(client, "Carol")

    for headers, user, role in ((b_headers, b_user, "manager"), (c_headers, c_user, "viewer")):
        invite = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": user["user"]["email"], "role_code": role},
        )
        assert invite.status_code == 201, invite.text
        accept = client.post(
            "/api/v1/invitations/accept", headers=headers, json={"token": invite.json()["token"]}
        )
        assert accept.status_code == 200, accept.text
    return a_headers, b_headers, c_headers, org, a_user, b_user, c_user


class TestOrganizationCrud:
    def test_create_org_returns_owner_payload(self, client, auth_headers):
        headers, _ = auth_headers
        org = _create_org(client, headers, name="Nile Delta Co")
        assert org["name"] == "Nile Delta Co"
        assert org["organization_type"] == "farm_org"
        assert org["country_code"] == "EG"  # normalized uppercase
        assert org["my_role"] == "owner"

    def test_list_my_organizations_sorted_oldest_first(self, client, auth_headers):
        headers, _ = auth_headers
        # registration already created the personal org (oldest)
        first = _create_org(client, headers, name="Second Org")
        listed = client.get("/api/v1/orgs", headers=headers).json()
        assert listed["total"] == 2
        assert listed["items"][0]["id"] != first["id"]  # personal org first
        assert listed["items"][1]["id"] == first["id"]
        assert all(item["my_role"] == "owner" for item in listed["items"])

    def test_get_org_by_id(self, client, auth_headers):
        headers, _ = auth_headers
        org = _create_org(client, headers)
        got = client.get(f"/api/v1/orgs/{org['id']}", headers=headers)
        assert got.status_code == 200
        assert got.json()["id"] == org["id"]
        assert got.json()["my_role"] == "owner"

    def test_patch_org_name_and_validation(self, client, auth_headers):
        headers, _ = auth_headers
        org = _create_org(client, headers)
        patched = client.patch(
            f"/api/v1/orgs/{org['id']}", headers=headers, json={"name": "Renamed Org"}
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed Org"
        bad_type = client.patch(
            f"/api/v1/orgs/{org['id']}",
            headers=headers,
            json={"organization_type": "cooperative"},
        )
        assert bad_type.status_code == 422

    def test_unknown_org_type_rejected_on_create(self, client, auth_headers):
        headers, _ = auth_headers
        resp = client.post(
            "/api/v1/orgs", headers=headers, json={"name": "X", "organization_type": "tribe"}
        )
        assert resp.status_code == 422


class TestOrgTenantIsolation:
    def test_non_member_cannot_read_or_modify_org(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, _ = _register(client, "Bob")

        assert client.get(f"/api/v1/orgs/{org['id']}", headers=b_headers).status_code == 403
        patch = client.patch(
            f"/api/v1/orgs/{org['id']}", headers=b_headers, json={"name": "Hijacked"}
        )
        assert patch.status_code == 403
        assert client.get(f"/api/v1/orgs/{org['id']}/members", headers=b_headers).status_code == 403
        assert (
            client.get(f"/api/v1/orgs/{org['id']}/activity", headers=b_headers).status_code == 403
        )
        # the hijack did not happen
        assert client.get(f"/api/v1/orgs/{org['id']}", headers=a_headers).json()["name"] == org[
            "name"
        ]

    def test_non_member_cannot_invite_or_transfer(self, client):
        a_headers, a_user = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, b_user = _register(client, "Bob")

        invite = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=b_headers,
            json={"email": "someone@test.local", "role_code": "viewer"},
        )
        assert invite.status_code == 403
        transfer = client.post(
            f"/api/v1/orgs/{org['id']}/ownership-transfer",
            headers=b_headers,
            json={"target_user_id": b_user["user"]["id"]},
        )
        assert transfer.status_code == 403

    def test_org_list_never_contains_foreign_orgs(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, _ = _register(client, "Bob")
        orgs = client.get("/api/v1/orgs", headers=b_headers).json()
        assert org["id"] not in [o["id"] for o in orgs["items"]]


class TestInvitationFlow:
    def test_invite_shows_token_once_and_list_omits_it(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, b_user = _register(client, "Bob")

        invite = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": b_user["user"]["email"], "role_code": "manager"},
        )
        assert invite.status_code == 201
        body = invite.json()
        assert body["token"]  # plaintext shown once
        assert body["email"] == b_user["user"]["email"]
        assert body["status"] == "pending"

        listed = client.get(f"/api/v1/orgs/{org['id']}/invitations", headers=a_headers).json()
        assert listed["total"] == 1
        assert "token" not in listed["items"][0]  # never leaks on list

    def test_duplicate_pending_invitation_conflicts(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        email = f"dup-{uuid.uuid4().hex[:8]}@test.local"
        first = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": email, "role_code": "viewer"},
        )
        assert first.status_code == 201
        second = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": email.upper(), "role_code": "viewer"},  # case-insensitive
        )
        assert second.status_code == 409

    def test_invite_existing_member_conflicts(self, client):
        a_headers, b_headers, _c, org, _a, b_user, _c2 = _org_story(client)
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": b_user["user"]["email"], "role_code": "manager"},
        )
        assert resp.status_code == 409

    def test_accept_joins_second_user_to_org(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, b_user = _register(client, "Bob")

        token = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": b_user["user"]["email"], "role_code": "manager"},
        ).json()["token"]

        accepted = client.post(
            "/api/v1/invitations/accept", headers=b_headers, json={"token": token}
        )
        assert accepted.status_code == 200
        membership = accepted.json()
        assert membership["organization_id"] == org["id"]
        assert membership["role_code"] == "manager"

        # B now sees the org with their role; members directory has both
        got = client.get(f"/api/v1/orgs/{org['id']}", headers=b_headers)
        assert got.status_code == 200
        assert got.json()["my_role"] == "manager"
        members = client.get(f"/api/v1/orgs/{org['id']}/members", headers=b_headers).json()
        assert members["total"] == 2
        assert {m["role_code"] for m in members["items"]} == {"owner", "manager"}

    def test_accept_rejects_wrong_email(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, _b = _register(client, "Bob")
        c_headers, _c = _register(client, "Carol")

        token = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": _b["user"]["email"], "role_code": "viewer"},
        ).json()["token"]

        # C (different address) cannot consume B's token
        resp = client.post(
            "/api/v1/invitations/accept", headers=c_headers, json={"token": token}
        )
        assert resp.status_code == 403
        # B still can — single-use token survived the failed attempt
        ok = client.post("/api/v1/invitations/accept", headers=b_headers, json={"token": token})
        assert ok.status_code == 200

    def test_revoked_invitation_cannot_be_accepted(self, client):
        a_headers, _ = _register(client, "Alice")
        org = _create_org(client, a_headers)
        b_headers, b_user = _register(client, "Bob")

        invite = client.post(
            f"/api/v1/orgs/{org['id']}/invitations",
            headers=a_headers,
            json={"email": b_user["user"]["email"], "role_code": "viewer"},
        ).json()
        revoked = client.delete(
            f"/api/v1/orgs/{org['id']}/invitations/{invite['id']}", headers=a_headers
        )
        assert revoked.status_code == 204
        resp = client.post(
            "/api/v1/invitations/accept", headers=b_headers, json={"token": invite["token"]}
        )
        assert resp.status_code == 409  # invitation is revoked, not pending

    def test_unknown_token_404(self, client, auth_headers):
        resp = client.post(
            "/api/v1/invitations/accept", headers=auth_headers[0], json={"token": "x" * 32}
        )
        assert resp.status_code == 404

    def test_non_admin_cannot_list_or_revoke_invitations(self, client):
        a_headers, b_headers, _c, org, _a, _b, _c2 = _org_story(client)
        # B is only a manager
        listed = client.get(f"/api/v1/orgs/{org['id']}/invitations", headers=b_headers)
        assert listed.status_code == 403
        invitations = client.get(
            f"/api/v1/orgs/{org['id']}/invitations", headers=a_headers
        ).json()
        if invitations["total"]:
            revoke = client.delete(
                f"/api/v1/orgs/{org['id']}/invitations/{invitations['items'][0]['id']}",
                headers=b_headers,
            )
            assert revoke.status_code == 403


class TestMemberRoleRules:
    def test_non_admin_role_change_rejected_403(self, client):
        a_headers, b_headers, _c, org, a_user, _b, _c2 = _org_story(client)
        # B holds only "manager" — far below org_admin
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{a_user['user']['id']}",
            headers=b_headers,
            json={"role_code": "viewer"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_owner_promotes_manager_to_org_admin(self, client):
        a_headers, b_headers, _c, org, _a, b_user, _c2 = _org_story(client)
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{b_user['user']['id']}",
            headers=a_headers,
            json={"role_code": "org_admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role_code"] == "org_admin"
        assert resp.json()["user_id"] == b_user["user"]["id"]

    def test_org_admin_changes_plain_member_role(self, client):
        a_headers, b_headers, c_headers, org, _a, b_user, c_user = _org_story(client)
        # promote B first, then B (org_admin) manages a non-owner member
        assert (
            client.patch(
                f"/api/v1/orgs/{org['id']}/members/{b_user['user']['id']}",
                headers=a_headers,
                json={"role_code": "org_admin"},
            ).status_code
            == 200
        )
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{c_user['user']['id']}",
            headers=b_headers,
            json={"role_code": "manager"},
        )
        assert resp.status_code == 200
        assert resp.json()["role_code"] == "manager"

    def test_org_admin_cannot_change_an_owners_role(self, client):
        a_headers, b_headers, _c, org, a_user, b_user, _c2 = _org_story(client)
        assert (
            client.patch(
                f"/api/v1/orgs/{org['id']}/members/{b_user['user']['id']}",
                headers=a_headers,
                json={"role_code": "org_admin"},
            ).status_code
            == 200
        )
        # B is org_admin now, but ownership changes flow through the
        # ownership-transfer route only
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{a_user['user']['id']}",
            headers=b_headers,
            json={"role_code": "manager"},
        )
        assert resp.status_code == 403

    def test_last_owner_cannot_be_demoted(self, client):
        a_headers, _b, _c, org, a_user, _b2, _c2 = _org_story(client)
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{a_user['user']['id']}",
            headers=a_headers,
            json={"role_code": "manager"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    def test_unknown_role_rejected(self, client, auth_headers):
        headers, user = auth_headers
        org = _create_org(client, headers)
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{user['user']['id']}",
            headers=headers,
            json={"role_code": "emperor"},
        )
        assert resp.status_code == 422

    def test_role_change_on_non_member_404(self, client, auth_headers):
        headers, _ = auth_headers
        org = _create_org(client, headers)
        stranger_id = str(uuid.uuid4())
        resp = client.patch(
            f"/api/v1/orgs/{org['id']}/members/{stranger_id}",
            headers=headers,
            json={"role_code": "viewer"},
        )
        assert resp.status_code == 404


class TestOwnershipTransferAndRemoval:
    def test_ownership_transfer_flips_roles(self, client):
        a_headers, b_headers, _c, org, _a, b_user, _c2 = _org_story(client)
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/ownership-transfer",
            headers=a_headers,
            json={"target_user_id": b_user["user"]["id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_owner_user_id"] == b_user["user"]["id"]
        assert body["previous_owner_role"] == "owner"

        members = client.get(f"/api/v1/orgs/{org['id']}/members", headers=a_headers).json()
        roles = {m["user_id"]: m["role_code"] for m in members["items"]}
        assert roles[b_user["user"]["id"]] == "owner"

        # new owner sees the org; previous owner is org_admin
        assert (
            client.get(f"/api/v1/orgs/{org['id']}", headers=b_headers).json()["my_role"]
            == "owner"
        )
        assert (
            client.get(f"/api/v1/orgs/{org['id']}", headers=a_headers).json()["my_role"]
            == "org_admin"
        )

    def test_only_owner_can_transfer(self, client):
        a_headers, b_headers, _c, org, _a, b_user, _c2 = _org_story(client)
        assert (
            client.patch(
                f"/api/v1/orgs/{org['id']}/members/{b_user['user']['id']}",
                headers=a_headers,
                json={"role_code": "org_admin"},
            ).status_code
            == 200
        )
        # B is org_admin (not owner) — transfer attempt is rejected
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/ownership-transfer",
            headers=b_headers,
            json={"target_user_id": b_user["user"]["id"]},
        )
        assert resp.status_code == 403
        # ...and the owner is still the owner
        assert (
            client.get(f"/api/v1/orgs/{org['id']}", headers=a_headers).json()["my_role"]
            == "owner"
        )

    def test_transfer_requires_active_member_target(self, client):
        a_headers, _b, c_headers, org, _a2, _b2, c_user = _org_story(client)
        # C is a member; a stranger is not
        _stranger_headers, stranger_user = _register(client, "Stranger")
        resp = client.post(
            f"/api/v1/orgs/{org['id']}/ownership-transfer",
            headers=a_headers,
            json={"target_user_id": stranger_user["user"]["id"]},
        )
        assert resp.status_code == 404

    def test_remove_member_and_access_revocation(self, client):
        a_headers, _b, c_headers, org, _a2, _b2, c_user = _org_story(client)
        assert (
            client.get(f"/api/v1/orgs/{org['id']}", headers=c_headers).status_code == 200
        )
        removed = client.delete(
            f"/api/v1/orgs/{org['id']}/members/{c_user['user']['id']}", headers=a_headers
        )
        assert removed.status_code == 204
        # C lost access immediately
        assert (
            client.get(f"/api/v1/orgs/{org['id']}", headers=c_headers).status_code == 403
        )
        members = client.get(f"/api/v1/orgs/{org['id']}/members", headers=a_headers).json()
        assert c_user["user"]["id"] not in [m["user_id"] for m in members["items"]]

    def test_cannot_remove_self(self, client):
        a_headers, _b, _c, org, a_user, _b2, _c2 = _org_story(client)
        resp = client.delete(
            f"/api/v1/orgs/{org['id']}/members/{a_user['user']['id']}", headers=a_headers
        )
        assert resp.status_code == 409

    def test_non_admin_cannot_remove_member(self, client):
        a_headers, b_headers, _c, org, _a, _b2, c_user = _org_story(client)
        # B is only a manager
        resp = client.delete(
            f"/api/v1/orgs/{org['id']}/members/{c_user['user']['id']}", headers=b_headers
        )
        assert resp.status_code == 403


class TestActivityTimeline:
    def test_timeline_records_lifecycle_events(self, client):
        a_headers, b_headers, c_headers, org, a_user, b_user, c_user = _org_story(client)
        # generate the remaining event types
        assert (
            client.patch(
                f"/api/v1/orgs/{org['id']}/members/{b_user['user']['id']}",
                headers=a_headers,
                json={"role_code": "org_admin"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/orgs/{org['id']}/ownership-transfer",
                headers=a_headers,
                json={"target_user_id": b_user["user"]["id"]},
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/orgs/{org['id']}/members/{c_user['user']['id']}", headers=b_headers
            ).status_code
            == 204
        )

        timeline = client.get(f"/api/v1/orgs/{org['id']}/activity", headers=a_headers).json()
        event_types = [e["event_type"] for e in timeline["items"]]
        assert timeline["total"] >= 6
        for expected in (
            "setting.changed",  # organization created
            "member.invited",
            "member.joined",
            "member.role_changed",
            "member.ownership_transferred",
            "member.removed",
        ):
            assert expected in event_types, f"missing activity event {expected}"

    def test_timeline_filter_and_pagination(self, client):
        a_headers, _b, _c, org, _a2, _b2, _c2 = _org_story(client)
        joined = client.get(
            f"/api/v1/orgs/{org['id']}/activity",
            headers=a_headers,
            params={"event_type": "member.joined"},
        ).json()
        assert joined["total"] == 2
        assert all(e["event_type"] == "member.joined" for e in joined["items"])

        page = client.get(
            f"/api/v1/orgs/{org['id']}/activity", headers=a_headers, params={"limit": 2}
        ).json()
        assert len(page["items"]) == 2
        everything = client.get(f"/api/v1/orgs/{org['id']}/activity", headers=a_headers).json()
        assert page["total"] == everything["total"]
        created = [e["created_at"] for e in page["items"]]
        assert created == sorted(created, reverse=True)  # newest first

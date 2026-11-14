"""PostgreSQL integration regressions for organization signup seats and races.

Run only against an explicitly isolated PostgreSQL test DSN. Requests use the
ordinary test API and synthetic users; no external providers or mail are used.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from app.core.security import hash_token
from app.db.models import Membership
from app.db.models_p3 import Invitation

PASSWORD = "synthetic-password-1"


def _register(client, label: str) -> tuple[dict[str, str], dict]:
    email = f"{label.lower()}-{uuid.uuid4().hex[:10]}@test.local"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": label},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def _start_starter(client, headers: dict[str, str], organization_id: str) -> None:
    response = client.post(
        "/api/v1/billing/subscription",
        headers=headers,
        json={
            "organization_id": organization_id,
            "plan_code": "starter",
            "billing_period": "monthly",
        },
    )
    assert response.status_code == 200, response.text


def _create_farm(client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/farms",
        headers=headers,
        json={
            "name": "Synthetic Race Farm",
            "country_code": "US",
            "timezone": "UTC",
            "currency_code": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _race_two(call_one, call_two):
    barrier = Barrier(2)

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, call_one), pool.submit(run, call_two)]
        return [future.result(timeout=30) for future in futures]


def _active_member_count(db, organization_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == uuid.UUID(organization_id),
                Membership.status == "active",
            )
        )
        or 0
    )


def test_signup_without_subscription_keeps_free_one_owner_seat(client, db):
    owner_headers, owner = _register(client, "FreeSeatOwner")
    candidate_headers, candidate = _register(client, "FreeSeatCandidate")
    organization_id = owner["organization"]["id"]

    entitlements = client.get(
        "/api/v1/billing/entitlements",
        headers=owner_headers,
        params={"organization_id": organization_id},
    )
    assert entitlements.status_code == 200, entitlements.text
    member_limit = entitlements.json()["entitlements"]["max_org_members"]
    assert member_limit["value"] == 1
    assert member_limit["plan_code"] == "free"

    farm_id = _create_farm(client, owner_headers)
    blocked = client.post(
        f"/api/v1/farms/{farm_id}/members",
        headers=owner_headers,
        json={"email": candidate["user"]["email"], "role_code": "viewer"},
    )
    assert blocked.status_code == 402, blocked.text
    assert blocked.json()["error"]["code"] == "PAYMENT_REQUIRED"
    assert _active_member_count(db, organization_id) == 1


def test_racing_invitation_acceptances_cannot_use_the_last_seat(client, db):
    owner_headers, owner = _register(client, "InviteRaceOwner")
    first_headers, first = _register(client, "InviteRaceFirst")
    second_headers, second = _register(client, "InviteRaceSecond")
    organization_id = owner["organization"]["id"]
    _start_starter(client, owner_headers, organization_id)

    # Two of the Starter plan's three seats are already occupied, leaving one.
    initial = client.post(
        f"/api/v1/orgs/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": first["user"]["email"], "role_code": "viewer"},
    )
    assert initial.status_code == 201, initial.text
    accepted = client.post(
        "/api/v1/invitations/accept",
        headers=first_headers,
        json={"token": initial.json()["token"]},
    )
    assert accepted.status_code == 200, accepted.text

    first_invite = client.post(
        f"/api/v1/orgs/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": first["user"]["email"], "role_code": "viewer"},
    )
    # Already a member, so use two new invitees to race for the remaining seat.
    # Registering an additional synthetic invitee keeps their own org separate.
    third_headers, third = _register(client, "InviteRaceThird")
    invite_a = client.post(
        f"/api/v1/orgs/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": second["user"]["email"], "role_code": "viewer"},
    )
    invite_b = client.post(
        f"/api/v1/orgs/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": third["user"]["email"], "role_code": "viewer"},
    )
    assert invite_a.status_code == invite_b.status_code == 201
    assert first_invite.status_code == 409

    responses = _race_two(
        lambda: client.post(
            "/api/v1/invitations/accept",
            headers=second_headers,
            json={"token": invite_a.json()["token"]},
        ),
        lambda: client.post(
            "/api/v1/invitations/accept",
            headers=third_headers,
            json={"token": invite_b.json()["token"]},
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 402]
    loser = next(response for response in responses if response.status_code == 402)
    assert loser.json()["error"]["code"] == "PAYMENT_REQUIRED"
    assert _active_member_count(db, organization_id) == 3


def test_racing_direct_add_member_requests_cannot_exceed_seat_cap(client, db):
    owner_headers, owner = _register(client, "DirectRaceOwner")
    _first_headers, first = _register(client, "DirectRaceFirst")
    second_headers, second = _register(client, "DirectRaceSecond")
    _third_headers, third = _register(client, "DirectRaceThird")
    organization_id = owner["organization"]["id"]
    _start_starter(client, owner_headers, organization_id)
    farm_id = _create_farm(client, owner_headers)

    initial = client.post(
        f"/api/v1/farms/{farm_id}/members",
        headers=owner_headers,
        json={"email": first["user"]["email"], "role_code": "viewer"},
    )
    assert initial.status_code == 201, initial.text

    responses = _race_two(
        lambda: client.post(
            f"/api/v1/farms/{farm_id}/members",
            headers=owner_headers,
            json={"email": second["user"]["email"], "role_code": "viewer"},
        ),
        lambda: client.post(
            f"/api/v1/farms/{farm_id}/members",
            headers=owner_headers,
            json={"email": third["user"]["email"], "role_code": "viewer"},
        ),
    )
    assert sorted(response.status_code for response in responses) == [201, 402]
    loser = next(response for response in responses if response.status_code == 402)
    assert loser.json()["error"]["code"] == "PAYMENT_REQUIRED"
    assert _active_member_count(db, organization_id) == 3


def test_racing_same_email_invites_create_only_one_live_pending_invitation(client, db):
    owner_headers, owner = _register(client, "DuplicateInviteOwner")
    organization_id = owner["organization"]["id"]
    email = f"unregistered-{uuid.uuid4().hex[:12]}@test.local"

    responses = _race_two(
        lambda: client.post(
            f"/api/v1/orgs/{organization_id}/invitations",
            headers=owner_headers,
            json={"email": email, "role_code": "viewer"},
        ),
        lambda: client.post(
            f"/api/v1/orgs/{organization_id}/invitations",
            headers=owner_headers,
            json={"email": email.upper(), "role_code": "viewer"},
        ),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "CONFLICT"
    invitations = db.scalars(
        select(Invitation).where(
            Invitation.organization_id == uuid.UUID(organization_id),
            func.lower(Invitation.email) == email.lower(),
            Invitation.status == "pending",
            Invitation.expires_at > func.now(),
        )
    ).all()
    assert len(invitations) == 1


def test_racing_acceptance_of_one_token_is_single_use_conflict_not_integrity_error(client, db):
    owner_headers, owner = _register(client, "SingleUseOwner")
    invitee_headers, invitee = _register(client, "SingleUseInvitee")
    organization_id = owner["organization"]["id"]
    _start_starter(client, owner_headers, organization_id)
    invitation = client.post(
        f"/api/v1/orgs/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": invitee["user"]["email"], "role_code": "viewer"},
    )
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]

    responses = _race_two(
        lambda: client.post(
            "/api/v1/invitations/accept",
            headers=invitee_headers,
            json={"token": token},
        ),
        lambda: client.post(
            "/api/v1/invitations/accept",
            headers=invitee_headers,
            json={"token": token},
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "CONFLICT"
    assert _active_member_count(db, organization_id) == 2
    invitation_row = db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(token))
    )
    assert invitation_row is not None
    assert invitation_row.status == "accepted"

"""A12 feedback lifecycle: append-only transitions, authorization, tenant
isolation, superseded-rec history, payload feedback_state."""

from __future__ import annotations

from tests.conftest import auth_headers, client, farm_with_field  # noqa: F401


def _refresh(client, headers, field_id):
    resp = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_feedback_lifecycle_append_only(client, farm_with_field):
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    payload = _refresh(client, headers, field_id)
    rec_id = payload["recommendations"][0]["id"]

    states = ["accepted", "implemented", "dismissed"]
    for state in states:
        resp = client.post(
            f"/api/v1/recommendations/{rec_id}/feedback",
            headers=headers,
            json={"state": state, "reason": f"transition to {state}"},
        )
        assert resp.status_code == 201, resp.text

    # Current state = latest transition.
    detail = client.get(f"/api/v1/recommendations/{rec_id}/feedback", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "dismissed"
    # Audit history preserved: all three transitions present, in order.
    assert [h["state"] for h in body["history"]] == states
    assert all(h["reason"] for h in body["history"])

    # The recommendations payload carries the latest state.
    recs = client.get(f"/api/v1/fields/{field_id}/recommendations", headers=headers).json()
    target = next(r for r in recs["recommendations"] if r["id"] == rec_id)
    assert target["feedback_state"] == "dismissed"


def test_feedback_state_validation(client, farm_with_field):
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    rec_id = _refresh(client, headers, field_id)["recommendations"][0]["id"]
    resp = client.post(
        f"/api/v1/recommendations/{rec_id}/feedback",
        headers=headers, json={"state": "excellent"},
    )
    assert resp.status_code == 422


def test_feedback_unknown_rec_404(client, farm_with_field):
    headers = farm_with_field["headers"]
    resp = client.post(
        "/api/v1/recommendations/00000000-0000-0000-0000-000000000000/feedback",
        headers=headers, json={"state": "accepted"},
    )
    assert resp.status_code == 404


def _register_second_user(client) -> dict:
    """A genuinely separate user (the auth_headers fixture is cached and
    shared with farm_with_field — same owner!)."""
    import uuid as _uuid

    email = f"other-{_uuid.uuid4().hex[:10]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": "Other Farmer"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_feedback_tenant_isolation(client, farm_with_field):
    """Another user's token cannot feedback this user's recommendation."""
    field_id = farm_with_field["field"]["id"]
    owner_headers = farm_with_field["headers"]
    rec_id = _refresh(client, owner_headers, field_id)["recommendations"][0]["id"]

    other_headers = _register_second_user(client)
    resp = client.post(
        f"/api/v1/recommendations/{rec_id}/feedback",
        headers=other_headers, json={"state": "accepted"},
    )
    assert resp.status_code in (403, 404)

    # And the history endpoint is equally protected.
    resp = client.get(
        f"/api/v1/recommendations/{rec_id}/feedback", headers=other_headers
    )
    assert resp.status_code in (403, 404)


def test_feedback_survives_supersession(client, farm_with_field):
    """Feedback on a superseded rec keeps its history; the new generation
    starts fresh (pending = no feedback)."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    first = _refresh(client, headers, field_id)
    rec_id = first["recommendations"][0]["id"]
    resp = client.post(
        f"/api/v1/recommendations/{rec_id}/feedback",
        headers=headers, json={"state": "accepted", "reason": "will do"},
    )
    assert resp.status_code == 201

    # Supersede everything by clearing the generators momentarily.
    from app.recommendations import registry as registry_module

    reg = registry_module.registry
    saved = {d: list(f) for d, f in reg._generators.items()}  # noqa: SLF001
    try:
        for fns in reg._generators.values():  # noqa: SLF001
            fns.clear()
        empty = client.post(
            f"/api/v1/fields/{field_id}/recommendations/refresh", headers=headers
        )
        assert empty.status_code == 200
    finally:
        for d, fns in saved.items():
            reg._generators[d] = fns  # noqa: SLF001

    # History of the superseded rec is intact.
    detail = client.get(f"/api/v1/recommendations/{rec_id}/feedback", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["state"] == "accepted"

    # Restore + refresh → new generation, no feedback yet.
    restored = _refresh(client, headers, field_id)
    new_ids = {r["id"] for r in restored["recommendations"]}
    assert rec_id not in new_ids
    assert all(r["feedback_state"] is None for r in restored["recommendations"])

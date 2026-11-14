"""AI Core API integration tests (requires the disposable PostGIS test DB)."""
from __future__ import annotations

import json
import uuid

from tests.conftest import client, farm_with_field  # noqa: F401


def _mock_structured_bridge(monkeypatch):
    from app.intelligence.orchestration import service
    from app.intelligence.orchestration.provider import ProviderGeneration, ProviderCapabilities

    class ScriptedProvider:
        name = "test-provider"
        capabilities = ProviderCapabilities()

        async def generate(self, messages, **kwargs):
            return ProviderGeneration(content=json.dumps({
                "answer": "The field profile is available in the recorded evidence [evidence: field].",
                "citations": ["field"],
                "limitations": [],
                "uncertainty_notes": [],
                "follow_up_suggestions": [],
            }), provider=self.name, model="test-model")

    monkeypatch.setattr(service, "get_provider_chain", lambda **kwargs: ScriptedProvider())


def test_ai_request_returns_grounded_typed_response_and_session_owner(
    client, farm_with_field, monkeypatch
):
    _mock_structured_bridge(monkeypatch)
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    response = client.post(
        "/api/v1/ai/requests",
        headers=headers,
        json={"question": "What does the field profile say?", "field_id": field_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partial"
    assert body["conversation_id"]
    assert body["execution"]["provider"] == "test-provider"
    assert body["execution"]["degraded"] is False
    assert body["execution"]["planned_steps"] == 2
    assert body["predictions"] == []
    assert body["recommendations"] == []
    assert body["verified_facts"]
    assert body["evidence"]


def test_ai_conversation_is_private_between_members_of_the_same_organization(
    client, farm_with_field, monkeypatch
):
    _mock_structured_bridge(monkeypatch)
    owner_headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    farm_id = farm_with_field["farm"]["id"]
    subscription = client.post(
        "/api/v1/billing/subscription",
        headers=owner_headers,
        json={
            "organization_id": farm_with_field["user"]["organization"]["id"],
            "plan_code": "starter",
            "billing_period": "monthly",
        },
    )
    assert subscription.status_code == 200, subscription.text

    first = client.post(
        "/api/v1/ai/requests",
        headers=owner_headers,
        json={"question": "What does the field profile say?", "field_id": field_id},
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    email = f"member-{uuid.uuid4().hex[:10]}@test.local"
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": "Field Member"},
    )
    assert registered.status_code == 201, registered.text
    member_headers = {"Authorization": f"Bearer {registered.json()['token']}"}
    added = client.post(
        f"/api/v1/farms/{farm_id}/members",
        headers=owner_headers,
        json={"email": email, "role_code": "viewer"},
    )
    assert added.status_code == 201, added.text

    denied = client.post(
        "/api/v1/ai/requests",
        headers=member_headers,
        json={
            "question": "Continue this field conversation.",
            "field_id": field_id,
            "conversation_id": conversation_id,
        },
    )
    assert denied.status_code == 404

"""Integration coverage for feedback and trace-history flows (disposable DB required)."""
from __future__ import annotations

import json
import uuid

from tests.conftest import client, farm_with_field  # noqa: F401


def _mock_structured_bridge(monkeypatch):
    from app.intelligence import bridge

    async def scripted(messages, temperature=None, max_tokens=None):
        return {
            "content": json.dumps({
                "answer": "The field profile is available in recorded evidence [evidence: field].",
                "citations": ["field"],
                "limitations": [],
                "uncertainty_notes": [],
                "follow_up_suggestions": [],
            }),
            "model": "integration-test-model",
        }

    monkeypatch.setattr(bridge, "achat_detail", scripted)


def test_feedback_is_consent_gated_owned_lifecycle_tracked_and_deletable(
    client, farm_with_field, monkeypatch,
):
    _mock_structured_bridge(monkeypatch)
    owner_headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    answer = client.post(
        "/api/v1/ai/requests",
        headers=owner_headers,
        json={"question": "What does the field profile say?", "field_id": field_id},
    )
    assert answer.status_code == 200, answer.text
    answer_body = answer.json()
    trace_id = answer_body["execution"]["trace_id"]
    conversation_id = answer_body["conversation_id"]

    history = client.get(
        f"/api/v1/ai/conversations/{conversation_id}/messages", headers=owner_headers,
    )
    assert history.status_code == 200, history.text
    assistant = next(item for item in history.json() if item["role"] == "assistant")
    assert assistant["trace_id"] == trace_id
    assert assistant["engine"]["trace_id"] == trace_id
    assert all(item["trace_id"] == trace_id for item in assistant["evidence"])

    submitted = client.post(
        "/api/v1/ai/feedback",
        headers=owner_headers,
        json={
            "trace_id": trace_id,
            "rating": "helpful",
            "outcome": "improved",
            "comment": "User-reported improvement; not independently verified.",
            "quality_review_consent": True,
        },
    )
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    assert body["quality_review_consent"] is True
    assert body["lifecycle_state"] == "accepted"
    assert body["outcome_verification_label"] == "unverified_user_reported"
    feedback_id = body["feedback_id"]

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"feedback-reader-{uuid.uuid4().hex[:12]}@test.local",
            "password": "test-password-1",
            "display_name": "Other User",
        },
    )
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
    assert client.get("/api/v1/ai/feedback", headers=other_headers).json() == []
    denied_delete = client.delete(f"/api/v1/ai/feedback/{feedback_id}", headers=other_headers)
    assert denied_delete.status_code == 404

    listed = client.get("/api/v1/ai/feedback", headers=owner_headers)
    assert listed.status_code == 200, listed.text
    assert any(row["feedback_id"] == feedback_id for row in listed.json())
    changed = client.patch(
        f"/api/v1/ai/feedback/{feedback_id}/lifecycle",
        headers=owner_headers,
        json={"lifecycle_state": "outcome_reported", "reason": "Outcome report reviewed"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["lifecycle_state"] == "outcome_reported"
    assert changed.json()["outcome_verification_label"] == "unverified_user_reported"

    deleted = client.delete(f"/api/v1/ai/feedback/{feedback_id}", headers=owner_headers)
    assert deleted.status_code == 204
    remaining = client.get("/api/v1/ai/feedback", headers=owner_headers)
    assert all(row["feedback_id"] != feedback_id for row in remaining.json())


def test_stream_rejects_unauthorized_field_before_sse_headers(client, farm_with_field):
    response = client.post(
        "/api/v1/ai/requests/stream",
        headers=farm_with_field["headers"],
        json={"question": "What does the stored soil evidence say?", "field_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert not response.headers.get("content-type", "").startswith("text/event-stream")

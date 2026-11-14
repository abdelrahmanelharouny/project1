"""Mock-only lifecycle regressions; no live provider or database."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.intelligence.orchestration import service
from app.intelligence.orchestration.contracts import AIRequest
from app.intelligence.orchestration.tools import AdvisorToolOutput, EvidenceCollectionOutput


@pytest.mark.parametrize("mode", ["rules", "llm"])
def test_fallback_preserves_real_evidence_and_rejected_usage(monkeypatch, mode):
    field_id, user_id, session_id = uuid4(), uuid4(), uuid4()
    db = SimpleNamespace(commit=lambda: None)
    context = SimpleNamespace(
        field=SimpleNamespace(id=field_id), field_id=field_id,
        principal=SimpleNamespace(id=user_id), user_id=user_id,
        organization_id=uuid4(), session=SimpleNamespace(id=session_id),
        selected_domains=("field", "soil", "data_gaps"), provider=None,
    )
    monkeypatch.setattr(service, "resolve_authorized_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(service, "get_provider_chain", lambda **kwargs: object())
    monkeypatch.setattr(service, "_append_messages", lambda *args: None)
    captured = []
    monkeypatch.setattr(service, "_persist_trace", lambda *args, **kwargs: captured.append(kwargs))
    pack = {
        "field": {"id": str(field_id), "area_ha": 2.5},
        "soil": {"assessment": {"source": {"kind": "soil_assessment", "id": "synthetic-run"}, "status": "partial"}},
        "data_gaps": ["water"],
    }
    engine = {"mode": mode}
    if mode == "llm":
        engine.update({
            "provider": "mock-only", "model": "fixture-only",
            "token_usage": {"input_tokens": 12, "output_tokens": 6},
            "provider_attempts": [{"provider": "mock-only", "model": "fixture-only", "status": "succeeded", "latency_ms": 1}],
        })

    async def execute(*args, **kwargs):
        return [
            EvidenceCollectionOutput(evidence_pack=pack, selected_domains=["soil", "data_gaps"]),
            AdvisorToolOutput(answer="Unsupported model diagnosis without citations.", evidence_used=[], engine=engine, evidence_pack=pack),
        ], []

    monkeypatch.setattr(service.tool_registry, "execute_workflow", execute)
    result = asyncio.run(service.execute_ai_request(
        db, SimpleNamespace(id=user_id), AIRequest(question="Explain the soil evidence", field_id=field_id), request_id="fallback-test",
    ))
    assert result.status == "partial"
    assert result.execution.degraded
    assert result.execution.provider is None
    assert result.answer != "Unsupported model diagnosis without citations."
    assert any(item.capability == "soil_intelligence" for item in result.evidence)
    assert result.recommendations == [] and result.predictions == []
    assert "water" in result.missing_information
    assert len(captured) == 1
    if mode == "llm":
        assert result.execution.token_usage.total_tokens == 18
        assert result.execution.provider_attempts[0].provider == "mock-only"
        assert captured[0]["validation_errors"]

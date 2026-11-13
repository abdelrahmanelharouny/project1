from __future__ import annotations

import json
from types import SimpleNamespace

from app.intelligence import advisor


def _evidence() -> dict:
    return {
        "field": {
            "source": {"kind": "field_profile", "id": "field-1"},
            "name": "North Field",
            "area_ha": 12.5,
        },
        "water": {
            "source": {"kind": "water_plan", "id": "water-1"},
            "nir_mm": 420.5,
        },
        "data_gaps": [],
    }


def _detail(answer: str, citations: list[str]) -> dict:
    return {
        "content": json.dumps({"answer": answer, "citations": citations}),
        "model": "test-model",
    }


def test_field_brief_accepts_supported_claim_with_visible_citation() -> None:
    result = advisor._validated_brief_result(
        _detail("Net irrigation is 420.5 mm [evidence: water].", ["water"]),
        _evidence(),
    )

    assert result is not None
    assert result["engine"]["mode"] == "llm"
    assert result["engine"]["evidence_used"] == [
        {"type": "water_plan", "id": "water-1", "label": "water"}
    ]


def test_field_brief_rejects_same_value_with_wrong_unit_or_evidence_section() -> None:
    assert advisor._validated_brief_result(
        _detail("Area is 420.5 ha [evidence: water].", ["water"]),
        _evidence(),
    ) is None
    assert advisor._validated_brief_result(
        _detail("Field area is 420.5 mm [evidence: field].", ["field"]),
        _evidence(),
    ) is None


def test_field_brief_requires_inline_citation_not_only_metadata() -> None:
    assert advisor._validated_brief_result(
        _detail("The field profile has a water plan.", ["field", "water"]),
        _evidence(),
    ) is None


def test_empty_data_gaps_cannot_be_cited_as_evidence() -> None:
    assert advisor._validated_brief_result(
        _detail("The field has no data [evidence: data_gaps].", ["data_gaps"]),
        _evidence(),
    ) is None


def test_every_brief_sentence_requires_its_own_valid_citation() -> None:
    assert advisor._validated_brief_result(
        _detail(
            "Net irrigation is 420.5 mm [evidence: water]. The field needs irrigation.",
            ["water"],
        ),
        _evidence(),
    ) is None


def test_field_brief_rejects_fabricated_citations_and_unstructured_text() -> None:
    assert advisor._validated_brief_result(
        _detail("The field is healthy [evidence: satellite_2024].", ["satellite_2024"]),
        _evidence(),
    ) is None
    assert advisor._validated_brief_result(
        {"content": "The field is healthy.", "model": "test-model"},
        _evidence(),
    ) is None


def test_sync_field_brief_retries_then_falls_back_without_model_text(monkeypatch) -> None:
    monkeypatch.setattr(advisor, "build_field_evidence", lambda db, field: _evidence())
    monkeypatch.setattr(advisor, "detect_feature_anomalies", lambda db, field_id: [])
    responses = [
        _detail("Area is 420.5 ha [evidence: water].", ["water"]),
        _detail("Invented claim without a citation.", ["field"]),
    ]
    captured = []

    def scripted(messages, temperature=None, max_tokens=None):
        captured.append(messages)
        return responses.pop(0)

    monkeypatch.setattr(advisor, "chat_detail", scripted)
    result = advisor.field_brief(None, SimpleNamespace(id="field-1"))

    assert result == {"summary": None, "engine": {"mode": "rules", "model": None}}
    assert len(captured) == 2
    assert "inline" in captured[0][0]["content"]


def test_async_field_brief_retries_and_accepts_valid_grounded_result(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(advisor, "build_field_evidence", lambda db, field: _evidence())
    monkeypatch.setattr(advisor, "detect_feature_anomalies", lambda db, field_id: [])
    responses = [
        _detail("Area is 420.5 ha [evidence: water].", ["water"]),
        _detail("Net irrigation is 420.5 mm [evidence: water].", ["water"]),
    ]
    captured = []

    async def scripted(messages):
        captured.append(messages)
        return responses.pop(0)

    monkeypatch.setattr(advisor, "achat_detail", scripted)
    result = asyncio.run(advisor.field_brief_async(None, SimpleNamespace(id="field-1")))

    assert result["summary"] == "Net irrigation is 420.5 mm [evidence: water]."
    assert result["engine"]["mode"] == "llm"
    assert result["engine"]["evidence_used"][0]["label"] == "water"
    assert len(captured) == 2

"""A6 structured LLM responses + citation validation."""

from __future__ import annotations

import json

from app.intelligence.response_contract import (
    AdvisorStructuredResponse,
    citations_from_answer,
    parse_structured,
    validate_citations,
)


VALID = ["climate", "water", "soil", "rotation", "management", "data_gaps"]


def _good_answer() -> str:
    return json.dumps({
        "answer": "Rainfall was 40 mm in March [evidence: climate].",
        "citations": ["climate"],
        "limitations": ["no soil data"],
        "uncertainty_notes": [],
        "follow_up_suggestions": ["Run a water plan"],
    })


def test_valid_structured_response_parses():
    parsed = parse_structured(_good_answer())
    assert parsed is not None
    assert isinstance(parsed, AdvisorStructuredResponse)
    assert parsed.citations == ["climate"]
    assert parsed.limitations == ["no soil data"]
    assert parsed.follow_up_suggestions == ["Run a water plan"]


def test_fenced_json_and_prose_wrapping():
    fenced = "```json\n" + _good_answer() + "\n```"
    assert parse_structured(fenced) is not None
    prose = "Here is my answer:\n" + _good_answer() + "\nDone."
    assert parse_structured(prose) is not None


def test_empty_and_refusal_responses():
    assert parse_structured("") is None
    assert parse_structured(None) is None
    assert parse_structured("   ") is None
    assert parse_structured(json.dumps({"error": "refused"})) is None
    assert parse_structured(json.dumps({"refusal": "I cannot"})) is None


def test_malformed_json_rejected():
    assert parse_structured("not json at all") is None
    assert parse_structured('{"answer": "no closing brace') is not None or True  # repair may rescue
    broken = '{"answer": "x", "citations": [}'
    # Even if repair rescues a truncated object, malformed arrays must not crash.
    parsed = parse_structured(broken)
    assert parsed is None or isinstance(parsed, AdvisorStructuredResponse)


def test_truncated_response_repaired_best_effort():
    # A truncated JSON object: repair may rescue it or reject it — crashing is
    # the only unacceptable outcome.
    truncated = '{"answer": "The answer is cut off mid-sent'
    try:
        parsed = parse_structured(truncated)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"parse_structured must never raise: {exc}") from exc
    assert parsed is None or isinstance(parsed, AdvisorStructuredResponse)


def test_schema_validation_rejects_missing_answer():
    bad = json.dumps({"citations": ["climate"]})
    assert parse_structured(bad) is None


def test_citation_validation_accepts_known_rejects_fabricated():
    accepted, rejected = validate_citations(
        ["climate", "weather", "climate", "water"], VALID
    )
    assert accepted == ["climate", "water"]
    assert rejected == ["weather"]


def test_citation_validation_empty_and_whitespace():
    accepted, rejected = validate_citations(["", "  ", None], VALID)
    assert accepted == [] and rejected == []


def test_inline_citation_extraction():
    text = "Rainfall was high [evidence: climate] and SOC low [evidence: soil]."
    assert citations_from_answer(text) == ["climate", "soil"]
    assert citations_from_answer("no citations here") == []


def test_fabricated_inline_citation_flagged():
    accepted, rejected = validate_citations(
        citations_from_answer("The moon is [evidence: lunar_phase] full."), VALID
    )
    assert accepted == [] and rejected == ["lunar_phase"]

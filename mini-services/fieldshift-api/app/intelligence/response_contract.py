"""Structured LLM response contract + citation validation (A6).

The bridge model is asked to answer with STRICT JSON:

    {
      "answer": "…",
      "citations": ["climate", "water"],
      "sections": [{"title": "…", "content": "…"}]?,      // optional
      "limitations": ["…"]?,                               // optional
      "uncertainty_notes": ["…"]?,                         // optional
      "follow_up_suggestions": ["…"]?                      // optional
    }

Parsing is defensive at every step: code fences, leading prose, truncated
JSON, empty content and non-object bodies all return None (caller falls back
to the text-based EVIDENCE: contract, then to deterministic rules). The
backend then validates EVERY returned citation against the evidence pack of
that same request: unknown/fabricated labels are rejected (never shown to the
user), recorded as a validation failure, and if nothing valid remains the
citations list is empty — the answer renders without evidence chips and the
answer text is still constrained by the prompt to be evidence-grounded.

Malformed model output can never break deterministic recommendation
generation: nothing in this module raises toward its callers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.intelligence import metrics

logger = logging.getLogger("croptwist.intelligence.response_contract")

MAX_ANSWER_CHARS = 6000
MAX_LIST_ITEMS = 8

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class AdvisorStructuredResponse(BaseModel):
    """Validated schema of the model's structured reply."""

    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)
    citations: list[str] = Field(default_factory=list, max_length=16)
    sections: list[dict[str, str]] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    uncertainty_notes: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


def parse_structured(content: str | None) -> AdvisorStructuredResponse | None:
    """Parse + schema-validate a structured reply (None when unusable).

    Handles: raw JSON, fenced ```json blocks, prose around a JSON object,
    truncated tails (best-effort brace repair), empty/refusal text.
    """
    if not content or not content.strip():
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    candidate = text.strip()
    if not candidate.startswith("{"):
        found = _JSON_BLOCK_RE.search(candidate)
        if not found:
            return None
        candidate = found.group(0)

    parsed: Any = None
    for attempt in (candidate, _repair_truncated(candidate)):
        if attempt is None:
            continue
        try:
            parsed = json.loads(attempt)
            break
        except (json.JSONDecodeError, ValueError):
            continue
    if not isinstance(parsed, dict):
        return None
    # A refusal often arrives as {"error": ...} or {"refusal": ...} — not an
    # answer; treat as unusable so the caller can fall back honestly.
    if "answer" not in parsed:
        return None
    try:
        return AdvisorStructuredResponse.model_validate(parsed)
    except ValidationError as exc:
        metrics.incr_validation_failure("structured_response")
        logger.warning("structured response failed schema validation: %s", exc.error_count())
        return None


def _repair_truncated(text: str) -> str | None:
    """Best-effort repair of a JSON object truncated mid-string (no promises).

    Closes open strings/brackets so a partial answer's leading fields survive;
    a truncated `answer` still beats no answer when combined with downstream
    numeric validation. Returns None when the text cannot plausibly be a
    truncated object.
    """
    if not text.startswith("{"):
        return None
    repaired = text.rstrip()
    # Drop a trailing incomplete "key": or partial value to make the object closeable.
    repaired = re.sub(r',\s*"(?:[^"\\]|\\.)*"\s*:?\s*$', "", repaired)
    repaired = re.sub(r":\s*$", "", repaired)
    repaired = re.sub(r",\s*$", "", repaired)
    if repaired.endswith('"'):
        repaired += '"'
    open_brackets = repaired.count("{") - repaired.count("}")
    open_arrays = repaired.count("[") - repaired.count("]")
    if open_brackets < 0 or open_arrays < 0:
        return None
    repaired += "]" * open_arrays + "}" * open_brackets
    return repaired if repaired != text else repaired


def validate_citations(
    citations: list[str], valid_labels: list[str]
) -> tuple[list[str], list[str]]:
    """Split model citations into (accepted, rejected).

    Order preserved, duplicates removed. Rejected labels are those NOT in the
    evidence pack of this request — fabricated references never render.
    """
    valid = set(valid_labels)
    accepted: list[str] = []
    rejected: list[str] = []
    for label in citations:
        if not isinstance(label, str):
            continue
        label = label.strip()
        if not label:
            continue
        if label in valid and label not in accepted:
            accepted.append(label)
        elif label not in valid and label not in rejected:
            rejected.append(label)
    if rejected:
        metrics.incr_validation_failure("citation_validation")
        logger.warning("rejected %d fabricated citation(s): %s", len(rejected), rejected)
    return accepted, rejected


def citations_from_answer(answer: str) -> list[str]:
    """Extract inline [evidence: LABEL] citations from free text (fallback)."""
    labels = re.findall(r"\[evidence:\s*([A-Za-z0-9_]+)\s*\]", answer)
    out: list[str] = []
    for label in labels:
        if label not in out:
            out.append(label)
    return out

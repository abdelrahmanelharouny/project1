"""Strict validation used only by the new AI Core response contract."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.intelligence.numeric_guard import validate_numbers_for_citations
from app.intelligence.response_contract import citations_from_answer


@dataclass(frozen=True)
class GroundingValidation:
    valid: bool
    error_codes: tuple[str, ...]
    citations: tuple[str, ...]


def validate_core_answer(answer: str, evidence: dict[str, Any]) -> GroundingValidation:
    """Fail closed unless every prose sentence has a real evidence label.

    Numeric statements are additionally checked against the cited section with
    same-dimension units. This does not prove that prose logically follows a
    citation; it is a stricter label/value boundary than the legacy advisor.
    """
    citations = tuple(citations_from_answer(answer))
    allowed_labels = {"field", "climate", "water", "soil", "rotation", "management", "vegetation", "data_gaps"}
    errors: list[str] = []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+|\n+", answer) if s.strip()]
    inline = re.compile(r"\[evidence:\s*([A-Za-z0-9_.:-]+)\]", re.IGNORECASE)
    for sentence in sentences:
        found = inline.findall(sentence)
        if not found:
            errors.append("sentence_without_inline_evidence")
            break
        if any(label not in allowed_labels or label not in evidence for label in found):
            errors.append("unknown_evidence_label")
            break
    if citations and any(label not in allowed_labels or label not in evidence for label in citations):
        errors.append("unknown_evidence_label")
    numeric = validate_numbers_for_citations(answer, evidence)
    if numeric.material_mismatch:
        errors.append("cited_numeric_consistency")
    return GroundingValidation(valid=not errors, error_codes=tuple(dict.fromkeys(errors)), citations=citations)

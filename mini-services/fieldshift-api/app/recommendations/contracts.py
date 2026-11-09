"""Contracts for the central recommendation system.

Severity ladder — aligned with app/knowledge/contracts.py
(`SEVERITIES = ("advisory", "recommended", "required")`), extended with an
`info` rung BELOW advisory for contextual/empty-state notices:

    info < advisory < recommended < required

- info         — context or data-gap notice; no action demanded.
- advisory     — worth doing; engine evidence suggests a benefit.
- recommended  — engine evidence indicates a concrete agronomic need.
- required     — an engine output shows a binding shortfall/violation that
                 must be addressed (e.g. NIR exceeds the water allocation).

Every Recommendation carries its evidence (engine output ids + values), an
explicit confidence with a `confidence_basis` string describing the
DETERMINISTIC basis (rule thresholds + engine versions), and provenance
(`generated_by`, `model`). The LLM never fills numeric fields — it may only
add `narrative` text grounded in the given facts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    INFO = "info"
    ADVISORY = "advisory"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


# Domain order is also the presentation order of the payload.
DOMAINS: list[str] = ["climate", "water", "soil", "rotation", "management"]

SEVERITY_ORDER: dict[str, int] = {
    Severity.INFO.value: 0,
    Severity.ADVISORY.value: 1,
    Severity.RECOMMENDED.value: 2,
    Severity.REQUIRED.value: 3,
}


class Recommendation(BaseModel):
    """Internal + persistence shape of one recommendation."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    domain: str
    severity: Severity
    title: str = Field(min_length=1, max_length=255)
    summary: str
    rationale: str
    # Evidence items: {"type", "id", "label", "detail"} — engine output kind,
    # run/row id, short citation label, human-readable detail with the numbers.
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_basis: str | None = None
    status: str = "active"
    generated_by: str = "rules"
    model: str | None = None
    narrative: str | None = None
    created_at: datetime | None = None


def evidence_item(
    *, type: str, id: str | None, label: str, detail: str
) -> dict[str, Any]:
    """Uniform evidence-dict constructor (shape the frontend depends on)."""
    return {"type": type, "id": id, "label": label, "detail": detail}

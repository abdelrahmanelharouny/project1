"""Recommendation fingerprinting + refresh diffing (A4).

A stable fingerprint identifies the MATERIAL content of one recommendation:
field, domain, generator identity+version, evidence references, severity,
and the recommendation text/actions. Unstable values (row uuids, created_at
timestamps, narrative text, the LLM model name) are deliberately excluded.

Refresh then diffs candidates against the field's active rows:

    unchanged   — fingerprint already active → row untouched (history,
                  feedback links and narrative survive; no write).
    changed     — candidate fingerprint not active while a same-generator
                  twin is → old row superseded, new row inserted.
    removed     — active row whose generator twin vanished → superseded.
    new         — candidate with no active twin → inserted.

Concurrency: SELECT ... FOR UPDATE on the active rows serializes refreshes
for the same field; a partial UNIQUE index on (field_id, fingerprint) WHERE
status='active' is the final guard (migration 0018). An IntegrityError rolls
the session back and the refresh is retried once — the losing writer then
sees the winner's rows and converges to the same end state (idempotent).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.recommendations.contracts import Recommendation

logger = logging.getLogger("croptwist.recommendations.fingerprint")

# Bump when fingerprint MATERIAL semantics change (invalidates all existing
# fingerprints once — the first refresh after an upgrade rewrites rows).
FINGERPRINT_VERSION = "p1-1"

# Schema/generator version reported by the registry (A4: generator identity
# and version are part of the fingerprint material).
RECOMMENDATION_SCHEMA_VERSION = "p1-1"


def fingerprint_material(rec: Recommendation | dict[str, Any], field_id: Any) -> dict[str, Any]:
    """The stable, material content of one recommendation (canonical JSON)."""
    def get(name: str) -> Any:
        if isinstance(rec, dict):
            return rec.get(name)
        return getattr(rec, name, None)

    severity = get("severity")
    if not isinstance(severity, str):
        severity = getattr(severity, "value", None)
    evidence = get("evidence") or []
    # Evidence ids/kinds/labels are stable references; free-text `detail`
    # strings can carry formatting-only churn, so only the stable parts count.
    evidence_refs = sorted(
        f"{e.get('type')}:{e.get('id')}:{e.get('label')}"
        for e in evidence
        if isinstance(e, dict)
    )
    material = {
        "v": FINGERPRINT_VERSION,
        "field_id": str(field_id),
        "domain": get("domain"),
        "generator": get("generator"),
        "generator_version": RECOMMENDATION_SCHEMA_VERSION,
        "severity": severity,
        "title": get("title"),
        "summary": get("summary"),
        "rationale": get("rationale"),
        "actions": get("actions") or [],
        "evidence_refs": evidence_refs,
    }
    return material


def compute_fingerprint(rec: Recommendation | dict[str, Any], field_id: Any) -> str:
    """SHA-256 over the canonical material (hex, stable across runs)."""
    material = fingerprint_material(rec, field_id)
    canonical = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def refresh_plan(
    candidates: list[Any],
    active_rows: list[Any],
    field_id: Any,
) -> dict[str, list[Any]]:
    """Pure diff of candidate recommendations vs active rows (unit-testable).

    Candidates may be Recommendation contracts or ORM-shaped rows; active rows
    must expose `.fingerprint` (None on legacy rows → treated as changed).
    Returns {"keep": [active_rows], "supersede": [active_rows],
             "insert": [candidates]}.
    """
    candidate_fp_to_rec: dict[str, Any] = {}
    for rec in candidates:
        fp = compute_fingerprint(rec, field_id)
        # First occurrence wins (registry order is deterministic).
        candidate_fp_to_rec.setdefault(fp, rec)

    keep: list[Any] = []
    supersede: list[Any] = []
    for row in active_rows:
        fp = getattr(row, "fingerprint", None)
        if fp and fp in candidate_fp_to_rec:
            keep.append(row)
        else:
            supersede.append(row)

    active_fps = {getattr(row, "fingerprint", None) for row in keep}
    insert = [rec for fp, rec in candidate_fp_to_rec.items() if fp not in active_fps]
    return {"keep": keep, "supersede": supersede, "insert": insert}

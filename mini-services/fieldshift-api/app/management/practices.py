"""Management practice read services (M6C Increment 2).

Loads ACTIVE-pack practice definitions and operation templates with their
per-claim source citations. Practices from draft packs are inert (never
returned to decision surfaces); retired packs are history. Everything here is
read-only mapping — no augmentation, no defaults, no numeric inference.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.knowledge.service import active_packs, pack_ref

PRACTICE_STATUS_ACTIVE = "active"


def _citation_map(
    db: Session, pack_ids: list[Any]
) -> dict[tuple[Any, str], dbm.KnowledgeSource]:
    """Map (pack_id, source_key) → source row. Claims inside pack payloads
    cite source_key strings; the resolver turns them into full citations."""
    if not pack_ids:
        return {}
    rows = db.scalars(
        select(dbm.KnowledgeSource).where(dbm.KnowledgeSource.pack_id.in_(pack_ids))
    ).all()
    return {(s.pack_id, s.source_key): s for s in rows}


def _resolve_claims(
    pack_id: Any,
    claims: list[dict[str, Any]],
    citations: dict[tuple[Any, str], dbm.KnowledgeSource],
) -> list[dict[str, Any]]:
    out = []
    for claim in claims:
        c = dict(claim)
        src = citations.get((pack_id, claim.get("source_key", "")))
        c["citation"] = (
            {
                "source_key": src.source_key,
                "publisher": src.publisher,
                "title": src.title,
                "citation_text": src.citation_text,
                "url": src.url,
            }
            if src is not None
            else None
        )
        out.append(c)
    return out


def _claim_payload(
    row: dbm.PracticeDefinition,
    citations: dict[tuple[Any, str], dbm.KnowledgeSource],
) -> dict[str, Any]:
    """Attach resolved citations to every claim in the payload."""
    payload = dict(row.payload or {})
    payload["mechanisms"] = _resolve_claims(
        row.pack_id, payload.get("mechanisms", []), citations
    )
    payload["requirements"] = _resolve_claims(
        row.pack_id, payload.get("requirements", []), citations
    )
    payload["trade_offs"] = _resolve_claims(
        row.pack_id, payload.get("trade_offs", []), citations
    )
    payload["risks"] = _resolve_claims(row.pack_id, payload.get("risks", []), citations)
    payload["regional_applicability"] = _resolve_claims(
        row.pack_id, payload.get("regional_applicability", []), citations
    )
    return payload


def practice_payload(
    row: dbm.PracticeDefinition,
    citations: dict[tuple[Any, str], dbm.KnowledgeSource],
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "practice_code": row.practice_code,
        "practice_family": row.practice_family,
        "name": row.name,
        "description": row.description,
        "validation_status": row.validation_status,
        "status": row.status,
        "payload": _claim_payload(row, citations),
    }


def operation_template_payload(
    row: dbm.OperationTemplate,
    citations: dict[tuple[Any, str], dbm.KnowledgeSource],
) -> dict[str, Any]:
    payload = dict(row.payload or {})
    payload["typical_predecessors"] = _resolve_claims(
        row.pack_id, payload.get("typical_predecessors", []), citations
    )
    return {
        "id": str(row.id),
        "template_code": row.template_code,
        "operation_type": row.operation_type,
        "name": row.name,
        "description": row.description,
        "validation_status": row.validation_status,
        "status": row.status,
        "payload": payload,
    }


def active_practices(db: Session) -> list[dict[str, Any]]:
    """Practice definitions from ACTIVE packs only (draft is inert; retired is
    history). Deterministically ordered by (pack_version, practice_code)."""
    packs = active_packs(db)
    if not packs:
        return []
    pack_ids = [p.id for p in packs]
    citations = _citation_map(db, pack_ids)
    rows = db.scalars(
        select(dbm.PracticeDefinition)
        .join(dbm.KnowledgePack, dbm.PracticeDefinition.pack_id == dbm.KnowledgePack.id)
        .where(
            dbm.PracticeDefinition.pack_id.in_(pack_ids),
            dbm.PracticeDefinition.status == PRACTICE_STATUS_ACTIVE,
        )
        .order_by(
            dbm.KnowledgePack.pack_version.asc(),
            dbm.KnowledgePack.pack_code.asc(),
            dbm.PracticeDefinition.practice_code.asc(),
        )
    ).all()
    return [practice_payload(r, citations) for r in rows]


def active_operation_templates(db: Session) -> list[dict[str, Any]]:
    """Operation templates from ACTIVE packs only, deterministically ordered."""
    packs = active_packs(db)
    if not packs:
        return []
    pack_ids = [p.id for p in packs]
    citations = _citation_map(db, pack_ids)
    rows = db.scalars(
        select(dbm.OperationTemplate)
        .join(dbm.KnowledgePack, dbm.OperationTemplate.pack_id == dbm.KnowledgePack.id)
        .where(
            dbm.OperationTemplate.pack_id.in_(pack_ids),
            dbm.OperationTemplate.status == PRACTICE_STATUS_ACTIVE,
        )
        .order_by(
            dbm.KnowledgePack.pack_version.asc(),
            dbm.KnowledgePack.pack_code.asc(),
            dbm.OperationTemplate.template_code.asc(),
        )
    ).all()
    return [operation_template_payload(r, citations) for r in rows]


def active_pack_refs(db: Session) -> list[dict[str, Any]]:
    return [pack_ref(p) for p in active_packs(db)]


def practice_evidence_coverage(practice: dict[str, Any]) -> dict[str, Any]:
    """A transparency metric (never a confidence score, per the M5 convention):
    how many claims carry a resolved citation, and which dimensions are
    missing entirely — so the UI can show coverage, not endorsement."""
    payload = practice.get("payload", {})
    counts: dict[str, int] = {}
    cited: dict[str, int] = {}
    for section in ("mechanisms", "requirements", "trade_offs", "risks"):
        claims = payload.get(section, [])
        counts[section] = len(claims)
        cited[section] = sum(1 for c in claims if c.get("citation"))
    trade_dims = {t.get("dimension") for t in payload.get("trade_offs", [])}
    return {
        "claim_counts": counts,
        "claims_cited": cited,
        "trade_off_dimensions_covered": sorted(d for d in trade_dims if d),
        "regional_applicability_count": len(payload.get("regional_applicability", [])),
    }

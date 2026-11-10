"""Central recommendation service: refresh, persist, payload.

Flow (refresh_field_recommendations):
1. registry.run_all(db, field) — context built ONCE, every domain generator
   runs in isolation.
2. Persistence: the field's ACTIVE rows are marked 'superseded' and the new
   generation is inserted (append-only history; nothing is rewritten).
3. Optional LLM narrative enrichment (only when the bridge is reachable AND
   there are recommendations): the rules content never changes — the LLM may
   only add the `narrative` field. Rows that received a narrative are stamped
   generated_by='rules+llm' with the bridge-reported model.
4. Payload in the exact shape the frontend depends on.

Determinism: the rules layer is fully deterministic (same engine outputs ->
same recommendations); the LLM narrative is the only non-deterministic field.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models_ai
from app.recommendations import contracts as rc
from app.recommendations.registry import registry
from app.intelligence import narrative

logger = logging.getLogger("croptwist.recommendations.service")


def _row_to_contract(row: models_ai.AIRecommendation) -> rc.Recommendation:
    return rc.Recommendation(
        id=str(row.id),
        domain=row.domain,
        severity=rc.Severity(row.severity),
        title=row.title,
        summary=row.summary,
        rationale=row.rationale,
        evidence=list(row.evidence or []),
        actions=list(row.actions or []),
        confidence=row.confidence,
        confidence_basis=row.confidence_basis,
        status=row.status,
        generated_by=row.generated_by,
        model=row.model,
        narrative=row.narrative,
        created_at=row.created_at,
    )


def refresh_field_recommendations(db: Session, field: Any) -> dict[str, Any]:
    """Run the registry, persist a new generation and return the payload."""
    recommendations = registry.run_all(db, field)

    # 2) persistence: supersede active rows, insert the new generation.
    active_rows = db.scalars(
        select(models_ai.AIRecommendation)
        .where(
            models_ai.AIRecommendation.field_id == field.id,
            models_ai.AIRecommendation.status == "active",
        )
    ).all()
    for row in active_rows:
        row.status = "superseded"

    new_rows: list[models_ai.AIRecommendation] = []
    for rec in recommendations:
        row = models_ai.AIRecommendation(
            field_id=field.id,
            domain=rec.domain,
            severity=rec.severity.value,
            title=rec.title[:255],
            summary=rec.summary,
            rationale=rec.rationale,
            evidence=rec.evidence,
            actions=rec.actions,
            confidence=rec.confidence,
            confidence_basis=rec.confidence_basis,
            status="active",
            generated_by=rec.generated_by,
            model=rec.model,
        )
        db.add(row)
        new_rows.append(row)
    db.flush()

    # 3) optional LLM narrative (best-effort; rules content never changes).
    engine_mode = "rules"
    engine_model: str | None = None
    meta = narrative.enrich_recommendations(db, field, new_rows)
    if meta is not None and meta.get("enriched_count"):
        engine_mode = "rules+llm"
        engine_model = meta.get("model")
        for row in new_rows:
            if row.narrative:
                row.generated_by = "rules+llm"
                row.model = engine_model

    payload = _payload(db, field, new_rows, engine_mode, engine_model)
    logger.info(
        "recommendations refreshed for field %s: %s active (mode=%s)",
        field.id, len(new_rows), engine_mode,
    )
    return payload


def get_active_recommendations(db: Session, field: Any) -> list[dict[str, Any]]:
    """Read-only view of the field's active recommendations (no refresh, no
    writes) — used by the advisor's rules fallback."""
    rows = db.scalars(
        select(models_ai.AIRecommendation)
        .where(
            models_ai.AIRecommendation.field_id == field.id,
            models_ai.AIRecommendation.status == "active",
        )
        .order_by(models_ai.AIRecommendation.created_at.desc())
    ).all()
    return [_row_to_contract(r).model_dump(mode="json") for r in rows]


def get_field_recommendations(
    db: Session, field: Any, refresh: bool = False
) -> dict[str, Any]:
    """Payload for the field's active recommendations (refreshing when asked
    or when no active generation exists yet)."""
    if not refresh:
        rows = db.scalars(
            select(models_ai.AIRecommendation)
            .where(
                models_ai.AIRecommendation.field_id == field.id,
                models_ai.AIRecommendation.status == "active",
            )
            .order_by(
                models_ai.AIRecommendation.created_at.desc(),
                models_ai.AIRecommendation.severity.desc(),
            )
        ).all()
        if rows:
            # Rows persisted by a previous refresh keep their provenance.
            by_domain_set = {r.domain for r in rows}
            mode = "rules+llm" if any(r.generated_by == "rules+llm" for r in rows) else "rules"
            model = next((r.model for r in rows if r.model), None)
            return _payload(db, field, rows, mode, model, domains_present=by_domain_set)
    return refresh_field_recommendations(db, field)


def _payload(
    db: Session,
    field: Any,
    rows: list[models_ai.AIRecommendation],
    engine_mode: str,
    engine_model: str | None,
    domains_present: set[str] | None = None,
) -> dict[str, Any]:
    recs = [_row_to_contract(r) for r in rows]
    recs.sort(
        key=lambda rec: (
            -rc.SEVERITY_ORDER[rec.severity.value],
            rc.DOMAINS.index(rec.domain) if rec.domain in rc.DOMAINS else 99,
        )
    )
    by_severity: dict[str, int] = {s.value: 0 for s in rc.Severity}
    for rec in recs:
        by_severity[rec.severity.value] = by_severity.get(rec.severity.value, 0) + 1
    domains = (
        sorted(domains_present, key=rc.DOMAINS.index)
        if domains_present
        else list(rc.DOMAINS)
    )
    timestamps = [r.created_at for r in rows if r.created_at]
    generated_at = (
        max(timestamps).isoformat() if timestamps else datetime.now(UTC).isoformat()
    )
    return {
        "field_id": str(field.id),
        "generated_at": generated_at,
        "engine": {"mode": engine_mode, "model": engine_model},
        "domains": domains,
        "counts": {
            "total": len(recs),
            "by_severity": by_severity,
        },
        "recommendations": [rec.model_dump(mode="json") for rec in recs],
    }

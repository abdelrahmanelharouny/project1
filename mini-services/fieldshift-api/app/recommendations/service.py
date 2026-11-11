"""Central recommendation service: refresh, persist, payload (P1 edition).

Flow (refresh_field_recommendations / _async):
1. registry.run_all(db, field) — context built ONCE, every domain generator
   runs in isolation against the shared evidence pack + seasonal anomalies.
2. A4 fingerprint diff: candidate fingerprints are computed and compared with
   the field's ACTIVE rows (SELECT ... FOR UPDATE serializes concurrent
   refreshes). Unchanged recommendations are KEPT (no write, history and
   feedback links intact); materially changed/removed rows are superseded;
   genuinely new ones inserted. A partial UNIQUE index on
   (field_id, fingerprint) WHERE status='active' is the concurrency backstop;
   an IntegrityError rolls back and retries once (idempotent convergence).
3. Optional LLM narrative enrichment (A2 async / A3 cache-aware / A10
   locale-aware): only the `narrative` column is added; rules content never
   changes. Rows that received a narrative are stamped generated_by='rules+llm'
   with the bridge-reported model. Cached narratives reuse existing rows.
4. Payload in the exact shape the frontend depends on (extended additively
   with confidence_kind / evidence_quality / feedback_state / fingerprint).

Determinism: the rules layer is fully deterministic (same engine outputs ->
same recommendations); the LLM narrative is the only non-deterministic field.

Feedback (A12): latest feedback state per recommendation is joined into the
payload read-only; writing feedback lives in the feedback service.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models_ai
from app.intelligence import metrics
from app.recommendations import contracts as rc
from app.recommendations.fingerprint import compute_fingerprint, refresh_plan
from app.recommendations.registry import registry
from app.intelligence import narrative

logger = logging.getLogger("croptwist.recommendations.service")

_MAX_REFRESH_ATTEMPTS = 2


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
        confidence_kind=row.confidence_kind,
        confidence_basis=row.confidence_basis,
        evidence_quality=row.evidence_quality,
        generator=row.generator if hasattr(row, "generator") else None,
        status=row.status,
        generated_by=row.generated_by,
        model=row.model,
        narrative=row.narrative,
        created_at=row.created_at,
    )


def _lock_active_rows(db: Session, field_id: Any) -> list[models_ai.AIRecommendation]:
    """Active rows with a row lock — serializes concurrent refreshes (A4)."""
    return list(
        db.scalars(
            select(models_ai.AIRecommendation)
            .where(
                models_ai.AIRecommendation.field_id == field_id,
                models_ai.AIRecommendation.status == "active",
            )
            .with_for_update()
        ).all()
    )


def _apply_plan(
    db: Session,
    field: Any,
    plan: dict[str, list[Any]],
) -> list[models_ai.AIRecommendation]:
    """Execute a refresh plan: supersede, insert. Returns ALL active rows."""
    for row in plan["supersede"]:
        row.status = "superseded"

    inserted: list[models_ai.AIRecommendation] = []
    for rec in plan["insert"]:
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
            confidence_kind=rec.confidence_kind,
            confidence_basis=rec.confidence_basis,
            evidence_quality=rec.evidence_quality,
            fingerprint=compute_fingerprint(rec, field.id),
            status="active",
            generated_by=rec.generated_by,
            model=rec.model,
        )
        db.add(row)
        inserted.append(row)
    db.flush()
    return plan["keep"] + inserted


def _enrich(
    db: Session,
    field: Any,
    rows: list[models_ai.AIRecommendation],
    *,
    locale: str,
    force: bool,
) -> tuple[str, str | None, str | None]:
    """Attach narratives (cache-aware); returns (mode, model, cache_state)."""
    meta = narrative.enrich_recommendations(db, field, rows, locale=locale, force=force)
    if meta is None:
        return "rules", None, None
    if meta.get("cache") == "hit":
        return "rules+llm", None, "hit"
    engine_model = meta.get("model")
    if meta.get("enriched_count"):
        for row in rows:
            if row.narrative:
                row.generated_by = "rules+llm"
                row.model = engine_model
        return "rules+llm", engine_model, "miss"
    return "rules", None, None


def refresh_field_recommendations(
    db: Session,
    field: Any,
    *,
    locale: str = "en",
    force: bool = False,
) -> dict[str, Any]:
    """Run the registry, diff-persist a new generation, return the payload."""
    with metrics.observe_refresh():
        candidates = registry.run_all(db, field)

        for attempt in range(_MAX_REFRESH_ATTEMPTS):
            try:
                active_rows = _lock_active_rows(db, field.id)
                plan = refresh_plan(candidates, active_rows, field.id)
                for row in plan["keep"]:
                    # Kept rows may still need legacy fingerprint backfill.
                    if not row.fingerprint:
                        row.fingerprint = compute_fingerprint(
                            _row_to_contract(row), field.id
                        )
                new_rows = _apply_plan(db, field, plan)
                break
            except IntegrityError:
                # Concurrent refresh raced us past the partial unique index:
                # roll back and retry — the winner's rows now exist, so the
                # retry converges (dedupe by fingerprint) or is a no-op.
                db.rollback()
                logger.warning(
                    "concurrent recommendation refresh for field %s (attempt %s) — retrying",
                    field.id, attempt + 1,
                )
                if attempt == _MAX_REFRESH_ATTEMPTS - 1:
                    raise
                candidates = registry.run_all(db, field)
        else:  # pragma: no cover — loop always breaks or raises
            new_rows = []

        metrics.incr("recommendation_fingerprint_reused", len(plan["keep"]))
        metrics.incr("recommendation_fingerprint_superseded", len(plan["supersede"]))
        metrics.incr("recommendation_fingerprint_created", len(plan["insert"]))

        active_new = [r for r in new_rows if r.status == "active"]
        engine_mode, engine_model, cache_state = _enrich(
            db, field, active_new, locale=locale, force=force,
        )

    payload = _payload(db, field, active_new, engine_mode, engine_model)
    payload["narrative_cache"] = cache_state
    logger.info(
        "recommendations refreshed for field %s: kept=%s superseded=%s inserted=%s (mode=%s cache=%s)",
        field.id, len(plan["keep"]), len(plan["supersede"]), len(plan["insert"]),
        engine_mode, cache_state,
    )
    return payload


async def refresh_field_recommendations_async(
    db: Session,
    field: Any,
    *,
    locale: str = "en",
    force: bool = False,
) -> dict[str, Any]:
    """Async refresh for async endpoints (A2).

    Sync DB work runs in a worker thread (`asyncio.to_thread`) so the event
    loop is never blocked by database calls; the LLM narrative call awaits
    the async bridge client directly.
    """
    with metrics.observe_refresh():
        candidates = await asyncio.to_thread(registry.run_all, db, field)

        for attempt in range(_MAX_REFRESH_ATTEMPTS):
            try:
                active_rows = await asyncio.to_thread(_lock_active_rows, db, field.id)
                plan = refresh_plan(candidates, active_rows, field.id)
                for row in plan["keep"]:
                    if not row.fingerprint:
                        row.fingerprint = compute_fingerprint(
                            _row_to_contract(row), field.id
                        )
                new_rows = await asyncio.to_thread(_apply_plan, db, field, plan)
                break
            except IntegrityError:
                await asyncio.to_thread(db.rollback)
                logger.warning(
                    "concurrent recommendation refresh for field %s (attempt %s) — retrying",
                    field.id, attempt + 1,
                )
                if attempt == _MAX_REFRESH_ATTEMPTS - 1:
                    raise
                candidates = await asyncio.to_thread(registry.run_all, db, field)
        else:  # pragma: no cover
            new_rows = []

        metrics.incr("recommendation_fingerprint_reused", len(plan["keep"]))
        metrics.incr("recommendation_fingerprint_superseded", len(plan["supersede"]))
        metrics.incr("recommendation_fingerprint_created", len(plan["insert"]))

        active_new = [r for r in new_rows if r.status == "active"]
        # A3+A10+A2: cache-aware, locale-aware narrative enrichment awaiting
        # the async bridge. enrich_recommendations_async attaches narratives
        # in place and reports {"model", "enriched_count", "cache"}.
        meta = await narrative.enrich_recommendations_async(
            db, field, active_new, locale=locale, force=force
        )
        if meta is None or not meta.get("enriched_count"):
            engine_mode, engine_model, cache_state = "rules", None, None
        elif meta.get("cache") == "hit":
            engine_mode, engine_model, cache_state = "rules+llm", None, "hit"
        else:
            engine_model = meta.get("model")
            engine_mode, cache_state = "rules+llm", "miss"
            for row in active_new:
                if row.narrative:
                    row.generated_by = "rules+llm"
                    row.model = engine_model

    payload = _payload(db, field, active_new, engine_mode, engine_model)
    payload["narrative_cache"] = cache_state
    logger.info(
        "recommendations refreshed (async) for field %s: kept=%s superseded=%s inserted=%s (mode=%s cache=%s)",
        field.id, len(plan["keep"]), len(plan["supersede"]), len(plan["insert"]),
        engine_mode, cache_state,
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
    db: Session,
    field: Any,
    refresh: bool = False,
    locale: str = "en",
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
            by_domain_set = {r.domain for r in rows}
            mode = "rules+llm" if any(r.generated_by == "rules+llm" for r in rows) else "rules"
            model = next((r.model for r in rows if r.model), None)
            return _payload(db, field, rows, mode, model, domains_present=by_domain_set)
    return refresh_field_recommendations(db, field, locale=locale)


def _latest_feedback_states(
    db: Session, rec_ids: list[Any]
) -> dict[str, str]:
    """Latest feedback state per recommendation id (read-only join, A12)."""
    if not rec_ids:
        return {}
    rows = db.scalars(
        select(models_ai.AIRecommendationFeedback)
        .where(models_ai.AIRecommendationFeedback.recommendation_id.in_(rec_ids))
        .order_by(models_ai.AIRecommendationFeedback.created_at.asc())
    ).all()
    out: dict[str, str] = {}
    for row in rows:
        out[str(row.recommendation_id)] = row.state  # ascending: last write wins
    return out


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
    feedback_states = _latest_feedback_states(db, [r.id for r in rows])
    return {
        "field_id": str(field.id),
        "generated_at": generated_at,
        "engine": {"mode": engine_mode, "model": engine_model},
        "domains": domains,
        "counts": {
            "total": len(recs),
            "by_severity": by_severity,
        },
        "recommendations": [
            {**rec.model_dump(mode="json"), "feedback_state": feedback_states.get(rec.id)}
            for rec in recs
        ],
    }

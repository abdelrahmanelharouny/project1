"""Recommendation feedback lifecycle (A12).

Farmers communicate whether recommendations are useful and what happened
after they were presented. Design invariants:

- APPEND-ONLY: every transition INSERTs a row; the current state of a
  recommendation is its latest row (audit history is never overwritten).
- AUTHORIZED: writes require field access (tenant rule) AND the field/farm/
  organization ids are denormalized from the recommendation's field at write
  time — a client cannot feedback a rec into another tenant.
- NOT AGRONOMIC TRUTH: feedback is a farmer-communication signal for future
  analytics (acceptance/dismissal/implementation rates); it never modifies
  recommendations or engine outputs.
- Superseded recommendations keep their feedback history (fingerprint copied
  at feedback time survives supersession).

States: pending → accepted | dismissed | implemented | not_applicable |
deferred (any transition to any other state is a legal new entry; history
preserves the path).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.db import models_ai
from app.intelligence import metrics
from app.intelligence.guard import sanitize_text

logger = logging.getLogger("croptwist.recommendations.feedback")

MAX_REASON_CHARS = 1000
VALID_STATES = set(models_ai.FEEDBACK_STATES)


def record_feedback(
    db: Session,
    principal: Any,
    recommendation_id: Any,
    *,
    state: str,
    reason: str | None = None,
    outcome: str | None = None,
) -> models_ai.AIRecommendationFeedback:
    """Append one feedback transition (raises HTTP 4xx on any violation)."""
    if state not in VALID_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"state must be one of {sorted(VALID_STATES)}",
        )
    rec = db.get(models_ai.AIRecommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")

    field = db.get(dbm.Field, rec.field_id)
    if field is None:  # pragma: no cover — FK guarantees field
        raise HTTPException(status_code=404, detail="Field not found.")
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:  # pragma: no cover — FK guarantees farm
        raise HTTPException(status_code=404, detail="Farm not found.")

    # Tenant rule: same authorization surface as every other field route.
    from app.domains.identity.service import get_field_for_principal

    get_field_for_principal(db, principal, rec.field_id)

    clean_reason = sanitize_text(reason, max_chars=MAX_REASON_CHARS) if reason else None
    clean_outcome = sanitize_text(outcome, max_chars=MAX_REASON_CHARS) if outcome else None

    row = models_ai.AIRecommendationFeedback(
        recommendation_id=rec.id,
        field_id=rec.field_id,
        farm_id=farm.id,
        organization_id=farm.organization_id,
        user_id=principal.id,
        fingerprint=rec.fingerprint,
        state=state,
        reason=clean_reason,
        outcome=clean_outcome,
    )
    db.add(row)
    db.flush()
    metrics.record_feedback_event(state)
    logger.info(
        "feedback recorded: rec=%s state=%s user=%s field=%s",
        rec.id, state, principal.id, rec.field_id,
    )
    return row


def latest_states(
    db: Session, recommendation_ids: list[Any]
) -> dict[str, dict[str, Any]]:
    """Latest feedback per recommendation: {rec_id: {state, reason, at}}."""
    if not recommendation_ids:
        return {}
    rows = db.scalars(
        select(models_ai.AIRecommendationFeedback)
        .where(models_ai.AIRecommendationFeedback.recommendation_id.in_(recommendation_ids))
        .order_by(models_ai.AIRecommendationFeedback.created_at.asc())
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[str(row.recommendation_id)] = {
            "state": row.state,
            "reason": row.reason,
            "outcome": row.outcome,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    return out


def history_for_recommendation(
    db: Session, recommendation_id: Any
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(models_ai.AIRecommendationFeedback)
        .where(models_ai.AIRecommendationFeedback.recommendation_id == recommendation_id)
        .order_by(models_ai.AIRecommendationFeedback.created_at.asc())
    ).all()
    return [
        {
            "id": str(row.id),
            "state": row.state,
            "reason": row.reason,
            "outcome": row.outcome,
            "user_id": str(row.user_id),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

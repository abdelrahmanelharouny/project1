"""Bounded privacy-retention cleanup primitives for an approved worker."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models_ai import AIAdvisorSession
from app.db.models_orchestration import AIAnswerFeedback, AIExecutionTrace
from app.intelligence.config import ai_settings

MAX_PURGE_BATCH = 5000


def _ids_before(db: Session, model: Any, column: Any, cutoff: datetime, limit: int) -> list[Any]:
    return list(db.scalars(
        select(model.id).where(column < cutoff).order_by(column).limit(limit)
    ).all())


def purge_expired_ai_data(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = 1000,
) -> dict[str, int]:
    """Delete at most `batch_size` expired rows per table; caller commits."""
    if not 1 <= batch_size <= MAX_PURGE_BATCH:
        raise ValueError(f"batch_size must be between 1 and {MAX_PURGE_BATCH}")
    current = now or datetime.now(UTC)
    feedback_ids = list(db.scalars(
        select(AIAnswerFeedback.id)
        .where(AIAnswerFeedback.expires_at <= current)
        .order_by(AIAnswerFeedback.expires_at)
        .limit(batch_size)
    ).all())
    feedback_deleted = 0
    if feedback_ids:
        feedback_deleted = int(db.execute(
            delete(AIAnswerFeedback).where(AIAnswerFeedback.id.in_(feedback_ids))
        ).rowcount or 0)

    trace_cutoff = current - timedelta(days=ai_settings.ai_trace_retention_days)
    trace_ids = _ids_before(db, AIExecutionTrace, AIExecutionTrace.created_at, trace_cutoff, batch_size)
    traces_deleted = 0
    if trace_ids:
        traces_deleted = int(db.execute(
            delete(AIExecutionTrace).where(AIExecutionTrace.id.in_(trace_ids))
        ).rowcount or 0)

    conversations_deleted = 0
    if ai_settings.ai_conversation_retention_days > 0:
        conversation_cutoff = current - timedelta(days=ai_settings.ai_conversation_retention_days)
        conversation_ids = _ids_before(
            db, AIAdvisorSession, AIAdvisorSession.updated_at, conversation_cutoff, batch_size
        )
        if conversation_ids:
            conversations_deleted = int(db.execute(
                delete(AIAdvisorSession).where(AIAdvisorSession.id.in_(conversation_ids))
            ).rowcount or 0)

    return {
        "feedback_deleted": feedback_deleted,
        "traces_deleted": traces_deleted,
        "conversations_deleted": conversations_deleted,
    }

"""Advisor session management (A8).

Sessions group multi-turn advisor conversations. Access control rides on the
field (get_field_for_principal authorizes the field; the session's field_id
is re-checked on EVERY lookup so a valid session id for ANOTHER field/tenant
is indistinguishable from a missing one — no existence leak).

`recent_history` returns the last N turns (user/assistant) oldest-first, in
the exact {role, content} shape the advisor prompt consumes.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models_ai

logger = logging.getLogger("croptwist.intelligence.sessions")


def get_or_404_for_field(
    db: Session, session_id: Any, field_id: Any
) -> models_ai.AIAdvisorSession | None:
    """Return the session when it belongs to THIS field, else None.

    Caller raises NotFound when None — avoids leaking session existence
    across fields/tenants.
    """
    session = db.get(models_ai.AIAdvisorSession, session_id)
    if session is None or session.field_id != field_id:
        return None
    return session


def create_session(db: Session, field_id: Any, title: str | None = None) -> models_ai.AIAdvisorSession:
    session = models_ai.AIAdvisorSession(field_id=field_id, title=title)
    db.add(session)
    db.flush()
    return session


def touch_session(db: Session, session: models_ai.AIAdvisorSession) -> None:
    """Bump the session's updated_at on activity."""
    from datetime import UTC, datetime

    session.updated_at = datetime.now(UTC)


def recent_history(
    db: Session, session_id: Any, max_turns: int
) -> list[dict[str, str]]:
    """Last `max_turns` user/assistant turns of a session, oldest-first.

    The router writes user+assistant PAIRS; the transcript is read in full
    ascending order and the last complete pairs are replayed. Messages without
    the expected payload (question/answer) are skipped defensively.
    """
    rows = db.scalars(
        select(models_ai.AIAdvisorMessage)
        .where(models_ai.AIAdvisorMessage.session_id == session_id)
        .order_by(models_ai.AIAdvisorMessage.created_at.asc())
    ).all()
    pairs: list[dict[str, str]] = []
    pending_question: str | None = None
    for row in rows:
        if row.role == "user":
            if row.question:
                pending_question = str(row.question)
        elif row.role == "assistant" and row.answer:
            if pending_question is not None:
                pairs.append({"role": "user", "content": pending_question})
                pending_question = None
            pairs.append({"role": "assistant", "content": str(row.answer)})
    return pairs[-max_turns:]

"""AI layer endpoints: central recommendations, insights, AI advisor.

- GET  /fields/{field_id}/recommendations          — active recommendations
- POST /fields/{field_id}/recommendations/refresh  — re-run the registry
- GET  /fields/{field_id}/insights                 — seasonal anomalies +
                                                      LLM field brief
- POST /fields/{field_id}/advisor/query            — grounded multi-turn Q&A
- GET  /fields/{field_id}/advisor/history          — transcript (ascending)
- POST /recommendations/{id}/feedback              — feedback transition (A12)
- GET  /recommendations/{id}/feedback              — feedback audit history
- GET  /fields/{field_id}/ai/metrics               — AI-layer metrics snapshot

Every endpoint is tenant-scoped through get_field_for_principal. The LLM is
best-effort: recommendations, insights and the advisor all degrade to
rules-only output when the bridge is unavailable (never an error).

P1: endpoints that touch the LLM are `async def` and await the async bridge
client (A2); DB work runs in worker threads. `locale` (en|ar) propagates into
narratives/advisor (A10); `force` bypasses the narrative cache (A3); advisor
queries accept a stable `session_id` for multi-turn context (A8).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound
from app.core.rate_limit import check as check_ai_rate_limit
from app.db import models_ai
from app.domains.identity.service import get_field_for_principal, get_principal
from app.intelligence import advisor as advisor_service
from app.intelligence import sessions as session_service
from app.intelligence.anomaly import detect_feature_anomalies
from app.intelligence.config import ai_settings
from app.intelligence.metrics import snapshot_ai
from app.recommendations import feedback as feedback_service
from app.recommendations import service as recommendation_service

router = APIRouter(tags=["recommendations"])

ADVISOR_DISCLAIMER = (
    "AI-generated guidance grounded in CropTwist engine outputs. "
    "Verify before acting."
)


def _clean_locale(locale: str) -> str:
    return locale if locale in ai_settings.supported_locales else "en"


@router.get("/fields/{field_id}/recommendations")
async def get_recommendations(
    field_id: uuid.UUID,
    refresh: bool = False,
    force: bool = False,
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    if refresh or force:
        check_ai_rate_limit("ai_core", str(principal.id))
        payload = await recommendation_service.refresh_field_recommendations_async(
            db, field, locale=_clean_locale(locale), force=force
        )
    else:
        payload = await asyncio.to_thread(
            recommendation_service.get_field_recommendations,
            db, field, False, _clean_locale(locale),
        )
    db.commit()
    return payload


@router.post("/fields/{field_id}/recommendations/refresh")
async def refresh_recommendations(
    field_id: uuid.UUID,
    force: bool = False,
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    check_ai_rate_limit("ai_core", str(principal.id))
    field = get_field_for_principal(db, principal, field_id)
    payload = await recommendation_service.refresh_field_recommendations_async(
        db, field, locale=_clean_locale(locale), force=force
    )
    db.commit()
    return payload


@router.get("/fields/{field_id}/insights")
async def get_insights(
    field_id: uuid.UUID,
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    check_ai_rate_limit("ai_core", str(principal.id))
    field = get_field_for_principal(db, principal, field_id)
    insights = await asyncio.to_thread(detect_feature_anomalies, db, field.id)
    brief = await advisor_service.field_brief_async(db, field, locale=_clean_locale(locale))
    return {
        "field_id": str(field.id),
        "insights": insights,
        "summary": brief.get("summary"),
        "engine": brief.get("engine") or {"mode": "rules", "model": None},
    }


class AdvisorQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Stable advisor session id (A8). Omit to start a new conversation; "
            "the response returns the session id to reuse. Sessions are "
            "field-scoped: a session from another field/tenant is 404."
        ),
    )


@router.post("/fields/{field_id}/advisor/query")
async def advisor_query(
    field_id: uuid.UUID,
    payload: AdvisorQueryRequest,
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    check_ai_rate_limit("ai_core", str(principal.id))
    field = get_field_for_principal(db, principal, field_id)

    session: models_ai.AIAdvisorSession | None = None
    if payload.session_id is not None:
        session = session_service.get_or_404_for_field(
            db, payload.session_id, field.id, owner_user_id=principal.id
        )
        if session is None:
            raise NotFound("Advisor session not found for this field.")
    else:
        session = session_service.create_session(db, field.id, owner_user_id=principal.id)

    history = session_service.recent_history(db, session.id, ai_settings.advisor_history_turns)
    result = await advisor_service.answer_field_question_async(
        db, field, payload.question, history=history, locale=_clean_locale(locale)
    )
    now = datetime.now(UTC)
    db.add(
        models_ai.AIAdvisorMessage(
            field_id=field.id,
            session_id=session.id,
            role="user",
            question=payload.question,
        )
    )
    db.add(
        models_ai.AIAdvisorMessage(
            field_id=field.id,
            session_id=session.id,
            role="assistant",
            answer=result.get("answer"),
            evidence=result.get("evidence_used"),
            engine=result.get("engine"),
        )
    )
    session_service.touch_session(db, session)
    db.commit()
    return {
        "field_id": str(field.id),
        "session_id": str(session.id),
        "question": payload.question,
        "answer": result.get("answer"),
        "evidence_used": result.get("evidence_used") or [],
        "engine": result.get("engine") or {"mode": "rules", "model": None},
        "disclaimer": ADVISOR_DISCLAIMER,
        "created_at": now.isoformat(),
    }


@router.get("/fields/{field_id}/advisor/history")
def advisor_history(
    field_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    session_id: uuid.UUID | None = Query(default=None),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    stmt = (
        select(models_ai.AIAdvisorMessage)
        .outerjoin(
            models_ai.AIAdvisorSession,
            models_ai.AIAdvisorMessage.session_id == models_ai.AIAdvisorSession.id,
        )
        .where(
            models_ai.AIAdvisorMessage.field_id == field_id,
            or_(
                models_ai.AIAdvisorSession.owner_user_id == principal.id,
                models_ai.AIAdvisorSession.owner_user_id.is_(None),
            ),
        )
        .order_by(models_ai.AIAdvisorMessage.created_at.asc())
        .limit(limit)
    )
    if session_id is not None:
        session = session_service.get_or_404_for_field(
            db, session_id, field_id, owner_user_id=principal.id
        )
        if session is None:
            raise NotFound("Advisor session not found for this field.")
        stmt = stmt.where(models_ai.AIAdvisorMessage.session_id == session_id)
    rows = db.scalars(stmt).all()
    return {
        "session_id": str(session_id) if session_id is not None else None,
        "messages": [
            {
                "role": row.role,
                "question": row.question,
                "answer": row.answer,
                "session_id": str(row.session_id) if row.session_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# A12: recommendation feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    state: str = Field(
        description="pending | accepted | dismissed | implemented | not_applicable | deferred"
    )
    reason: str | None = Field(default=None, max_length=1000)
    outcome: str | None = Field(default=None, max_length=1000)


@router.post("/recommendations/{recommendation_id}/feedback", status_code=201)
def record_recommendation_feedback(
    recommendation_id: uuid.UUID,
    payload: FeedbackRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = feedback_service.record_feedback(
        db,
        principal,
        recommendation_id,
        state=payload.state,
        reason=payload.reason,
        outcome=payload.outcome,
    )
    db.commit()
    return {
        "id": str(row.id),
        "recommendation_id": str(row.recommendation_id),
        "state": row.state,
        "reason": row.reason,
        "outcome": row.outcome,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/recommendations/{recommendation_id}/feedback")
def get_recommendation_feedback_history(
    recommendation_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    from app.db import models as dbm

    rec = db.get(models_ai.AIRecommendation, recommendation_id)
    if rec is None:
        raise NotFound("Recommendation not found.")
    get_field_for_principal(db, principal, rec.field_id)  # tenant scoping
    history = feedback_service.history_for_recommendation(db, rec.id)
    latest = history[-1] if history else None
    return {
        "recommendation_id": str(rec.id),
        "state": latest["state"] if latest else "pending",
        "history": history,
    }


@router.get("/fields/{field_id}/ai/metrics")
def ai_layer_metrics(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    return snapshot_ai()

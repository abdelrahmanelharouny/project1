"""AI layer endpoints: central recommendations, insights, AI advisor.

- GET  /fields/{field_id}/recommendations          — active recommendations
- POST /fields/{field_id}/recommendations/refresh  — re-run the registry
- GET  /fields/{field_id}/insights                 — statistical anomalies +
                                                      LLM field brief
- POST /fields/{field_id}/advisor/query            — grounded Q&A (persisted)
- GET  /fields/{field_id}/advisor/history          — transcript (ascending)

Every endpoint is tenant-scoped through get_field_for_principal. The LLM is
best-effort: recommendations, insights and the advisor all degrade to
rules-only output when the bridge is unavailable (never an error).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db import models_ai
from app.domains.identity.service import get_field_for_principal, get_principal
from app.intelligence import advisor as advisor_service
from app.intelligence.anomaly import detect_feature_anomalies
from app.recommendations import service as recommendation_service

router = APIRouter(tags=["recommendations"])

ADVISOR_DISCLAIMER = (
    "AI-generated guidance grounded in FieldShift engine outputs. "
    "Verify before acting."
)


@router.get("/fields/{field_id}/recommendations")
def get_recommendations(
    field_id: uuid.UUID,
    refresh: bool = False,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    payload = recommendation_service.get_field_recommendations(db, field, refresh=refresh)
    db.commit()
    return payload


@router.post("/fields/{field_id}/recommendations/refresh")
def refresh_recommendations(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    payload = recommendation_service.refresh_field_recommendations(db, field)
    db.commit()
    return payload


@router.get("/fields/{field_id}/insights")
def get_insights(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    insights = detect_feature_anomalies(db, field.id)
    brief = advisor_service.field_brief(db, field)
    return {
        "field_id": str(field.id),
        "insights": insights,
        "summary": brief.get("summary"),
        "engine": brief.get("engine") or {"mode": "rules", "model": None},
    }


class AdvisorQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/fields/{field_id}/advisor/query")
def advisor_query(
    field_id: uuid.UUID,
    payload: AdvisorQueryRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    result = advisor_service.answer_field_question(db, field, payload.question)
    now = datetime.now(UTC)
    db.add(
        models_ai.AIAdvisorMessage(
            field_id=field.id,
            role="user",
            question=payload.question,
        )
    )
    db.add(
        models_ai.AIAdvisorMessage(
            field_id=field.id,
            role="assistant",
            answer=result.get("answer"),
            evidence=result.get("evidence_used"),
            engine=result.get("engine"),
        )
    )
    db.commit()
    return {
        "field_id": str(field.id),
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
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(models_ai.AIAdvisorMessage)
        .where(models_ai.AIAdvisorMessage.field_id == field_id)
        .order_by(models_ai.AIAdvisorMessage.created_at.asc())
        .limit(limit)
    ).all()
    return {
        "messages": [
            {
                "role": row.role,
                "question": row.question,
                "answer": row.answer,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }

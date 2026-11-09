"""ORM models for the AI layers (Intelligence + Recommendation).

AI-driven pivot (Milestone AI-2a): two additive tables backing the central
recommendation system and the AI advisor. Conventions intentionally mirror
app/db/models.py and app/db/models_m6bc_m7.py: UUID(as_uuid=True) PKs with
python-side uuid4 defaults, TimestampMixin for mutable tables, inline
created_at for append-only child tables, JSONB with python-side defaults.

This module is imported for its side effect of registering the tables on the
single declarative Base — import it wherever the AI rows are queried
(`from app.db.models_ai import AIRecommendation`). It is deliberately NOT
imported by app/db/models.py (that file is frozen for the AI pivot).

- `ai_recommendations` — one row per recommendation emitted by the central
  generator registry (app/recommendations/). A refresh supersedes the field's
  active rows and inserts the new set; history is never hard-deleted.
- `ai_advisor_messages` — append-only advisor transcript (user question +
  assistant answer pairs) with the evidence used and the engine mode that
  produced the answer (provenance discipline).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, TimestampMixin, _uuid

__all__ = [
    "AIRecommendation",
    "AIAdvisorMessage",
]


class AIRecommendation(Base, TimestampMixin):
    """One recommendation of the central recommendation system.

    Rows are written by app/recommendations/service.refresh_field_recommendations:
    every refresh marks the field's active rows `superseded` and inserts the new
    generation. Nothing is rewritten in place — superseded rows are the audit
    trail of what the system recommended before.
    """

    __tablename__ = "ai_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    generated_by: Mapped[str] = mapped_column(String(16), nullable=False, default="rules")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # LLM narrative (optional): 1-2 farmer-friendly sentences attached by the
    # intelligence layer AFTER the rules content was persisted. Nullable —
    # rules-only rows never carry one; the rules columns are never rewritten.
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','advisory','recommended','required')",
            name="ck_ai_recommendation_severity",
        ),
        CheckConstraint(
            "status IN ('active','superseded')",
            name="ck_ai_recommendation_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_recommendation_confidence_range",
        ),
        Index("ix_ai_recommendations_field_status", "field_id", "status"),
        Index("ix_ai_recommendations_field", "field_id"),
    )


class AIAdvisorMessage(Base):
    """One advisor transcript message (append-only).

    A POST to /advisor/query writes TWO rows: the user's question and the
    assistant's answer (with the evidence labels used + engine mode, so every
    answer is auditable back to the engine outputs that grounded it).
    """

    __tablename__ = "ai_advisor_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    engine: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_ai_advisor_message_role"),
        Index("ix_ai_advisor_messages_field", "field_id"),
    )

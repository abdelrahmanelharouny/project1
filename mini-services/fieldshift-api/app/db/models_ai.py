"""ORM models for the AI layers (Intelligence + Recommendation + Feedback).

AI-driven pivot (Milestone AI-2a) + P1 trust layer (fingerprinting A4,
evidence quality A5, advisor sessions A8, feedback ledger A12). Conventions
intentionally mirror app/db/models.py and app/db/models_m6bc_m7.py:
UUID(as_uuid=True) PKs with python-side uuid4 defaults, TimestampMixin for
mutable tables, inline created_at for append-only child tables, JSONB with
python-side defaults.

This module is imported for its side effect of registering the tables on the
single declarative Base — import it wherever the AI rows are queried
(`from app.db.models_ai import AIRecommendation`). It is deliberately NOT
imported by app/db/models.py (that file is frozen for the AI pivot).

- `ai_recommendations` — one row per recommendation emitted by the central
  generator registry (app/recommendations/). A refresh supersedes rows that
  materially changed/vanished and inserts genuinely new ones (A4 diff);
  unchanged fingerprints stay active. History is never hard-deleted.
- `ai_advisor_sessions` / `ai_advisor_messages` — append-only advisor
  transcript grouped into sessions (A8); legacy messages keep session_id NULL.
- `ai_recommendation_feedback` — append-only feedback ledger (A12): every
  state transition is a new row; the current state is the latest row per
  recommendation. Never overwritten, tenant-scoped via farm → organization.
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, TimestampMixin, _uuid

__all__ = [
    "AIRecommendation",
    "AIAdvisorSession",
    "AIAdvisorMessage",
    "AIRecommendationFeedback",
]

FEEDBACK_STATES = (
    "pending",
    "accepted",
    "dismissed",
    "implemented",
    "not_applicable",
    "deferred",
)


class AIRecommendation(Base, TimestampMixin):
    """One recommendation of the central recommendation system.

    Rows are written by app/recommendations/service.refresh_field_recommendations:
    every refresh diffs candidate fingerprints against the field's active rows —
    unchanged recommendations stay active, changed/new ones are inserted,
    vanished ones are marked `superseded`. Nothing is rewritten in place —
    superseded rows are the audit trail of what the system recommended before.
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
    confidence_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # A4: stable material fingerprint (SHA-256 hex); NULL for legacy rows.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        CheckConstraint(
            "confidence_kind IS NULL OR confidence_kind IN "
            "('deterministic_rule','evidence_quality')",
            name="ck_ai_recommendation_confidence_kind",
        ),
        Index("ix_ai_recommendations_field_status", "field_id", "status"),
        Index("ix_ai_recommendations_field", "field_id"),
        Index("ix_ai_recommendations_fingerprint", "fingerprint"),
        Index(
            "uq_ai_recommendations_active_fingerprint", "field_id", "fingerprint",
            unique=True, postgresql_where=text("status = 'active' AND fingerprint IS NOT NULL"),
        ),
    )


class AIAdvisorSession(Base):
    """One advisor conversation for a field (A8).

    Sessions scope multi-turn context: all messages of a conversation share a
    session row. New core sessions have an authenticated owner; legacy NULL
    owners retain field-scoped access until separately migrated/retired.
    """

    __tablename__ = "ai_advisor_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    # NULL is retained for pre-ownership legacy sessions; new core sessions
    # are always stamped from the authenticated principal on the server.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_advisor_sessions_field", "field_id"),
        Index("ix_ai_advisor_sessions_owner", "owner_user_id"),
    )


class AIAdvisorMessage(Base):
    """One advisor transcript message (append-only).

    A POST to /advisor/query writes TWO rows: the user's question and the
    assistant's answer (with the evidence labels used + engine mode, so every
    answer is auditable back to the engine outputs that grounded it).
    session_id groups the pair into its conversation (NULL on legacy rows).
    """

    __tablename__ = "ai_advisor_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_advisor_sessions.id", ondelete="CASCADE"),
        nullable=True,
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
        Index("ix_ai_advisor_messages_session", "session_id"),
    )


class AIRecommendationFeedback(Base):
    """One feedback state transition (append-only ledger, A12).

    Farmers communicate what happened after a recommendation was presented.
    Every transition INSERTs a row; the current state of a recommendation is
    its latest row by created_at. Previous decisions are preserved for audit —
    nothing is overwritten. Tenant isolation: field/farm/organization ids are
    denormalized at write time and every API path authorizes against the
    requesting principal's membership.

    Analytics-ready (acceptance/dismissal/implementation rates by domain,
    severity, region, crop) WITHOUT treating feedback as agronomic truth.
    """

    __tablename__ = "ai_recommendation_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Copied from the recommendation at feedback time so analytics survive
    # supersession (A12: handle recommendations that become superseded).
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','accepted','dismissed','implemented','not_applicable','deferred')",
            name="ck_ai_feedback_state",
        ),
        Index("ix_ai_feedback_rec", "recommendation_id"),
        Index("ix_ai_feedback_field_state", "field_id", "state"),
    )

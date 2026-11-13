"""Privacy-conscious append-only AI Core invocation metadata."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, _uuid


class AIExecutionTrace(Base):
    """One lifecycle record; raw request/answer and provider secrets are omitted."""

    __tablename__ = "ai_execution_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_advisor_sessions.id", ondelete="SET NULL"), nullable=True
    )
    intent: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_context_domains: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    planned_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('answered','partial','clarification_required','unavailable','failed')",
            name="ck_ai_execution_trace_status",
        ),
        CheckConstraint("planned_steps >= 0", name="ck_ai_execution_trace_steps_nonneg"),
        CheckConstraint("latency_ms >= 0", name="ck_ai_execution_trace_latency_nonneg"),
        Index("ix_ai_execution_traces_user_created", "user_id", "created_at"),
        Index("ix_ai_execution_traces_org_created", "organization_id", "created_at"),
        Index("ix_ai_execution_traces_request", "request_id"),
        Index("ix_ai_execution_traces_conversation", "conversation_id"),
    )

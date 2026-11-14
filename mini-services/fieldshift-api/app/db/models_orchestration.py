"""AI Core traces, feedback and tenant-scoped knowledge-index models."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
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


class AIAnswerFeedback(Base):
    """Append-only, explicitly consented feedback; never an automatic training row."""

    __tablename__ = "ai_answer_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_execution_traces.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_advisor_sessions.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quality_review_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("rating IN ('helpful','needs_improvement')", name="ck_ai_answer_feedback_rating"),
        CheckConstraint(
            "category IS NULL OR category IN ('factual_error','insufficient_evidence','unclear','unsafe','other')",
            name="ck_ai_answer_feedback_category",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('not_observed','no_change','improved','worsened')",
            name="ck_ai_answer_feedback_outcome",
        ),
        CheckConstraint("quality_review_consent IS TRUE", name="ck_ai_answer_feedback_consent"),
        Index("ix_ai_answer_feedback_org_created", "organization_id", "created_at"),
        Index("ix_ai_answer_feedback_user_created", "user_id", "created_at"),
        Index("ix_ai_answer_feedback_trace", "trace_id"),
        Index("ix_ai_answer_feedback_expires", "expires_at"),
    )


class AIKnowledgeDocument(Base):
    """One rights-attested document record scoped to its owning organization."""

    __tablename__ = "ai_knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_updated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False)
    crop_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    document_version: Mapped[str] = mapped_column(String(100), nullable=False)
    license_name: Mapped[str] = mapped_column(String(200), nullable=False)
    usage_restrictions: Mapped[str] = mapped_column(Text, nullable=False)
    rights_confirmed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    rights_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('pending_embedding','ready','failed')",
            name="ck_ai_knowledge_document_status",
        ),
        CheckConstraint("character_count > 0", name="ck_ai_knowledge_document_chars"),
        UniqueConstraint(
            "organization_id", "content_hash", "document_version",
            name="uq_ai_knowledge_document_org_hash_version",
        ),
        Index("ix_ai_knowledge_documents_org_status", "organization_id", "processing_status"),
        Index("ix_ai_knowledge_documents_org_language", "organization_id", "language"),
    )


class AIKnowledgeChunk(Base):
    """Text chunk and optional vector; organization is denormalized for safe scans."""

    __tablename__ = "ai_knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_ai_knowledge_chunk_index"),
        CheckConstraint("embedding_dimension IS NULL OR embedding_dimension > 0", name="ck_ai_knowledge_embedding_dim"),
        UniqueConstraint("document_id", "chunk_index", name="uq_ai_knowledge_chunk_document_index"),
        Index("ix_ai_knowledge_chunks_org", "organization_id"),
        Index("ix_ai_knowledge_chunks_document", "document_id"),
    )

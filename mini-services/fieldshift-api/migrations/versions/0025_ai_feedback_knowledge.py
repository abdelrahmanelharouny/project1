"""AI Core provider telemetry, explicit feedback and knowledge ingestion.

Revision ID: 0025_ai_feedback_knowledge
Revises: 0024_ai_core_orchestration

No pgvector extension, shared/global corpus, raw answer copy or provider secret
is introduced. Knowledge vectors are optional JSONB data until a reviewed
embedding provider is configured.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025_ai_feedback_knowledge"
down_revision = "0024_ai_core_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_execution_traces",
        sa.Column(
            "provider_attempts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "ai_answer_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_execution_traces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_advisor_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rating", sa.String(length=24), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("quality_review_consent", sa.Boolean(), nullable=False),
        sa.Column("consent_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating IN ('helpful','needs_improvement')", name="ck_ai_answer_feedback_rating"),
        sa.CheckConstraint("category IS NULL OR category IN ('factual_error','insufficient_evidence','unclear','unsafe','other')", name="ck_ai_answer_feedback_category"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('not_observed','no_change','improved','worsened')", name="ck_ai_answer_feedback_outcome"),
        sa.CheckConstraint("quality_review_consent IS TRUE", name="ck_ai_answer_feedback_consent"),
    )
    op.create_index("ix_ai_answer_feedback_org_created", "ai_answer_feedback", ["organization_id", "created_at"])
    op.create_index("ix_ai_answer_feedback_user_created", "ai_answer_feedback", ["user_id", "created_at"])
    op.create_index("ix_ai_answer_feedback_trace", "ai_answer_feedback", ["trace_id"])
    op.create_index("ix_ai_answer_feedback_expires", "ai_answer_feedback", ["expires_at"])

    op.create_table(
        "ai_knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_title", sa.String(length=300), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=False),
        sa.Column("source_reference", sa.String(length=1000), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("source_updated_at", sa.Date(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=100), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("crop_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("document_version", sa.String(length=100), nullable=False),
        sa.Column("license_name", sa.String(length=200), nullable=False),
        sa.Column("usage_restrictions", sa.Text(), nullable=False),
        sa.Column("rights_confirmed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rights_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("failure_category", sa.String(length=80), nullable=True),
        sa.Column("embedding_provider", sa.String(length=100), nullable=True),
        sa.Column("embedding_model", sa.String(length=160), nullable=True),
        sa.CheckConstraint("processing_status IN ('pending_embedding','ready','failed')", name="ck_ai_knowledge_document_status"),
        sa.CheckConstraint("character_count > 0", name="ck_ai_knowledge_document_chars"),
        sa.UniqueConstraint("organization_id", "content_hash", "document_version", name="uq_ai_knowledge_document_org_hash_version"),
    )
    op.create_index("ix_ai_knowledge_documents_org_status", "ai_knowledge_documents", ["organization_id", "processing_status"])
    op.create_index("ix_ai_knowledge_documents_org_language", "ai_knowledge_documents", ["organization_id", "language"])

    op.create_table(
        "ai_knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("chunk_index >= 0", name="ck_ai_knowledge_chunk_index"),
        sa.CheckConstraint("embedding_dimension IS NULL OR embedding_dimension > 0", name="ck_ai_knowledge_embedding_dim"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_ai_knowledge_chunk_document_index"),
    )
    op.create_index("ix_ai_knowledge_chunks_org", "ai_knowledge_chunks", ["organization_id"])
    op.create_index("ix_ai_knowledge_chunks_document", "ai_knowledge_chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_knowledge_chunks_document", table_name="ai_knowledge_chunks")
    op.drop_index("ix_ai_knowledge_chunks_org", table_name="ai_knowledge_chunks")
    op.drop_table("ai_knowledge_chunks")
    op.drop_index("ix_ai_knowledge_documents_org_language", table_name="ai_knowledge_documents")
    op.drop_index("ix_ai_knowledge_documents_org_status", table_name="ai_knowledge_documents")
    op.drop_table("ai_knowledge_documents")
    op.drop_index("ix_ai_answer_feedback_expires", table_name="ai_answer_feedback")
    op.drop_index("ix_ai_answer_feedback_trace", table_name="ai_answer_feedback")
    op.drop_index("ix_ai_answer_feedback_user_created", table_name="ai_answer_feedback")
    op.drop_index("ix_ai_answer_feedback_org_created", table_name="ai_answer_feedback")
    op.drop_table("ai_answer_feedback")
    op.drop_column("ai_execution_traces", "provider_attempts")

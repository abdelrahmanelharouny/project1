"""AI Core: private conversation ownership and privacy-conscious traces.

Revision ID: 0024_ai_core_orchestration
Revises: 0023_p07_field_reports

Existing session rows remain owner_user_id NULL and are not rewritten. New
requests persist no raw prompt, answer, evidence values or secrets in traces.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024_ai_core_orchestration"
down_revision = "0023_p07_field_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_advisor_sessions",
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ai_advisor_sessions_owner", "ai_advisor_sessions", ["owner_user_id"]
    )
    op.create_table(
        "ai_execution_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_advisor_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("intent", sa.String(length=48), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("selected_context_domains", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("planned_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('answered','partial','clarification_required','unavailable','failed')",
            name="ck_ai_execution_trace_status",
        ),
        sa.CheckConstraint("planned_steps >= 0", name="ck_ai_execution_trace_steps_nonneg"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_ai_execution_trace_latency_nonneg"),
    )
    op.create_index("ix_ai_execution_traces_user_created", "ai_execution_traces", ["user_id", "created_at"])
    op.create_index("ix_ai_execution_traces_org_created", "ai_execution_traces", ["organization_id", "created_at"])
    op.create_index("ix_ai_execution_traces_request", "ai_execution_traces", ["request_id"])
    op.create_index("ix_ai_execution_traces_conversation", "ai_execution_traces", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_execution_traces_conversation", table_name="ai_execution_traces")
    op.drop_index("ix_ai_execution_traces_request", table_name="ai_execution_traces")
    op.drop_index("ix_ai_execution_traces_org_created", table_name="ai_execution_traces")
    op.drop_index("ix_ai_execution_traces_user_created", table_name="ai_execution_traces")
    op.drop_table("ai_execution_traces")
    op.drop_index("ix_ai_advisor_sessions_owner", table_name="ai_advisor_sessions")
    op.drop_column("ai_advisor_sessions", "owner_user_id")

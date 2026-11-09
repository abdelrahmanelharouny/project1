"""AI layers: central recommendations + advisor transcript

Revision ID: 0017_ai_recommendations
Revises: 0016_background_jobs
Create Date: 2026-11-09

Additive migration — two new tables, no existing data is rewritten.

`ai_recommendations` — one row per recommendation emitted by the central
generator registry (app/recommendations/). A refresh supersedes the field's
active rows ('status' → 'superseded') and inserts the new generation; history
is never hard-deleted.

- `domain` VARCHAR(32) NOT NULL — climate | water | soil | rotation | management.
- `severity` VARCHAR(16) NOT NULL + CHECK `ck_ai_recommendation_severity`
  IN ('info','advisory','recommended','required') — the knowledge severity
  ladder extended with an `info` rung below advisory.
- `title`, `summary`, `rationale` — the rules content (LLM narratives go to
  `narrative`-shaped fields only at the API layer; the LLM never rewrites
  these columns).
- `evidence` JSONB NOT NULL — provenance items {type, id, label, detail}
  pointing at the engine outputs that produced the recommendation.
- `actions` JSONB NOT NULL — concrete next steps.
- `confidence` FLOAT NULL + CHECK `ck_ai_recommendation_confidence_range`
  0..1, `confidence_basis` TEXT — the deterministic basis is stated, never
  implied.
- `status` VARCHAR(16) NOT NULL server_default 'active' + CHECK
  `ck_ai_recommendation_status` IN ('active','superseded'), indexed with
  field_id for the active-generation lookup.
- `generated_by` VARCHAR(16) NOT NULL server_default 'rules' ('rules+llm'
  when an LLM narrative was attached), `model` VARCHAR(64) NULL — the
  bridge-reported model name (provenance).
- `narrative` TEXT NULL — the optional LLM narrative attached AFTER the rules
  content was written; rules columns are never rewritten by the LLM.

`ai_advisor_messages` — append-only advisor transcript: every
/advisor/query writes one 'user' row (question) and one 'assistant' row
(answer + evidence used + engine mode), so answers audit back to the engine
outputs that grounded them.

Downgrade drops both tables.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_ai_recommendations"
down_revision = "0016_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confidence_basis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("generated_by", sa.String(length=16), nullable=False, server_default="rules"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "severity IN ('info','advisory','recommended','required')",
            name="ck_ai_recommendation_severity",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded')",
            name="ck_ai_recommendation_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_recommendation_confidence_range",
        ),
    )
    op.create_index(
        "ix_ai_recommendations_field_status",
        "ai_recommendations",
        ["field_id", "status"],
    )
    op.create_index("ix_ai_recommendations_field", "ai_recommendations", ["field_id"])

    op.create_table(
        "ai_advisor_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("engine", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role IN ('user','assistant')", name="ck_ai_advisor_message_role"
        ),
    )
    op.create_index("ix_ai_advisor_messages_field", "ai_advisor_messages", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_advisor_messages_field", table_name="ai_advisor_messages")
    op.drop_table("ai_advisor_messages")
    op.drop_index("ix_ai_recommendations_field", table_name="ai_recommendations")
    op.drop_index(
        "ix_ai_recommendations_field_status", table_name="ai_recommendations"
    )
    op.drop_table("ai_recommendations")

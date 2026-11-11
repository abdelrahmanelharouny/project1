"""P1 trust layer: fingerprints, evidence quality, advisor sessions, feedback

Revision ID: 0018_p1_trust_layer
Revises: 0017_ai_recommendations
Create Date: 2026-11-11

Fully ADDITIVE migration (P1 rule: never rewrite existing data):

1. `ai_recommendations.fingerprint` VARCHAR(64) NULL — stable SHA-256 of the
   recommendation's material content (field, domain, generator identity+version,
   evidence refs, severity, text). NULL for legacy rows; the first P1 refresh
   backfills fingerprints through the normal diff path. A partial UNIQUE index
   on (field_id, fingerprint) WHERE status='active' guarantees no duplicate
   active recommendations share a fingerprint (concurrent-refresh guard).

1b. `ai_recommendations.confidence_kind` VARCHAR(32) NULL — the honest basis
   kind of the confidence value (A5): 'deterministic_rule' | 'evidence_quality'.
   CHECK-constrained; NULL for legacy rows (their basis strings stay valid).

2. `ai_recommendations.evidence_quality` JSONB NULL — component-wise evidence
   quality report attached by A5 ({score, components, summary}). NULL when the
   domain has no computable components.

3. `ai_advisor_sessions` — one row per advisor conversation (A8). Messages
   reference it through the new nullable `ai_advisor_messages.session_id`
   (legacy messages keep NULL: they stay field-level history).

4. `ai_recommendation_feedback` — append-only feedback ledger (A12). Every
   state transition INSERTs a row; the current state is the latest row per
   recommendation (audit history is never overwritten). `fingerprint` copies
   the recommendation's fingerprint at feedback time so analytics survive
   recommendation supersession.

Downgrade drops the feedback table + sessions table + added columns/index
(reversible; no data from other milestones is touched).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018_p1_trust_layer"
down_revision = "0017_ai_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) fingerprints + evidence quality on ai_recommendations ---------------
    op.add_column(
        "ai_recommendations",
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_recommendations",
        sa.Column("evidence_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ai_recommendations",
        sa.Column("confidence_kind", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_ai_recommendation_confidence_kind",
        "ai_recommendations",
        "confidence_kind IS NULL OR confidence_kind IN "
        "('deterministic_rule','evidence_quality')",
    )
    op.create_index(
        "ix_ai_recommendations_fingerprint",
        "ai_recommendations",
        ["fingerprint"],
    )
    op.create_index(
        "uq_ai_recommendations_active_fingerprint",
        "ai_recommendations",
        ["field_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND fingerprint IS NOT NULL"),
    )

    # 2) advisor sessions ----------------------------------------------------
    op.create_table(
        "ai_advisor_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_ai_advisor_sessions_field", "ai_advisor_sessions", ["field_id"])
    op.add_column(
        "ai_advisor_messages",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_advisor_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_ai_advisor_messages_session", "ai_advisor_messages", ["session_id"])

    # 3) recommendation feedback (append-only ledger) -------------------------
    op.create_table(
        "ai_recommendation_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('pending','accepted','dismissed','implemented','not_applicable','deferred')",
            name="ck_ai_feedback_state",
        ),
    )
    op.create_index("ix_ai_feedback_rec", "ai_recommendation_feedback", ["recommendation_id"])
    op.create_index(
        "ix_ai_feedback_field_state", "ai_recommendation_feedback", ["field_id", "state"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_feedback_field_state", table_name="ai_recommendation_feedback")
    op.drop_index("ix_ai_feedback_rec", table_name="ai_recommendation_feedback")
    op.drop_table("ai_recommendation_feedback")
    op.drop_index("ix_ai_advisor_messages_session", table_name="ai_advisor_messages")
    op.drop_column("ai_advisor_messages", "session_id")
    op.drop_index("ix_ai_advisor_sessions_field", table_name="ai_advisor_sessions")
    op.drop_table("ai_advisor_sessions")
    op.drop_index("uq_ai_recommendations_active_fingerprint", table_name="ai_recommendations")
    op.drop_index("ix_ai_recommendations_fingerprint", table_name="ai_recommendations")
    op.drop_constraint("ck_ai_recommendation_confidence_kind", "ai_recommendations", type_="check")
    op.drop_column("ai_recommendations", "confidence_kind")
    op.drop_column("ai_recommendations", "evidence_quality")
    op.drop_column("ai_recommendations", "fingerprint")

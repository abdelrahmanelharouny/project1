"""digital twin validations (Milestone 7.7)

Revision ID: 0013_digital_twin
Revises: 0012_decision_comparisons
Create Date: 2026-11-02

Additive migration:

`digital_twin_validations` — one immutable, checksummed integrity walk per
field over its twin artifacts. Re-verification reuses the existing
per-artifact verifiers; results are persisted so twin consistency is
auditable over time.

- CHECK `ck_digital_twin_validation_status` — the three honest outcomes.
- Partial UNIQUE `(field_id, idempotency_key)` — client-keyed replay.
- Append-only by design: every walk is a NEW row; no UPDATE trigger is
  needed because no column is ever rewritten after insert.

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_digital_twin"
down_revision = "0012_decision_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "digital_twin_validations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("overall_status", sa.String(length=20), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("report_checksum", sa.String(length=64), nullable=False),
        sa.Column("artifacts_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "overall_status IN ('consistent','inconsistent','no_artifacts')",
            name="ck_digital_twin_validation_status",
        ),
    )
    op.create_index(
        "uq_digital_twin_validation_idempotency",
        "digital_twin_validations",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_digital_twin_validations_field", "digital_twin_validations", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_digital_twin_validations_field", table_name="digital_twin_validations")
    op.drop_index("uq_digital_twin_validation_idempotency", table_name="digital_twin_validations")
    op.drop_table("digital_twin_validations")

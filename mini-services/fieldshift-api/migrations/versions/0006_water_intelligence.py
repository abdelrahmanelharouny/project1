"""water intelligence (Milestone 6A)

Revision ID: 0006_water_intelligence
Revises: 0005_deepening_hardening
Create Date: 2026-10-31

Additive migration: introduces `water_plans` — immutable seasonal water-plan
snapshots (M6A Phase 5/7). No existing table is altered; nothing is rewritten.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_water_intelligence"
down_revision = "0005_deepening_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "water_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="succeeded",
        ),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="water plan"),
        sa.Column("seasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("crop_assignments", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("methods", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("soil_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("water_engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("feature_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("water_allocation_m3", sa.Float(), nullable=True),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_water_plan_status",
        ),
    )
    op.create_index(
        "uq_water_plan_idempotency",
        "water_plans",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_water_plans_field", "water_plans", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_water_plans_field", table_name="water_plans")
    op.drop_index("uq_water_plan_idempotency", table_name="water_plans")
    op.drop_table("water_plans")

"""field state foundation (Milestone 7.1)

Revision ID: 0007_field_state_foundation
Revises: 0006_water_intelligence
Create Date: 2026-11-01

Additive migration (M7.0 adjustment A1):
1. New `field_states` table — immutable, checksummed by-reference snapshots
   of a field's state at a point/period in time. FKs to feature_runs,
   water_plans and rotation_runs are RESTRICT: a referenced artifact cannot
   be deleted out from under a state (F-13 enforcement).
2. `feature_runs` += boundary_version (H-01), observation_manifest +
   observation_manifest_sha256 (H-02/F-31). NULL for pre-M7.1 rows means
   "not recorded" — historical values are never guessed retroactively.
3. `water_plans` += boundary_version (H-01) + started_at/completed_at
   (run-envelope alignment, F-32 partial).
4. Ingestion idempotency fix (F-30): the legacy key-only unique index
   `uq_ingestion_idempotency` is replaced by a field-scoped composite
   `uq_ingestion_idempotency_v2 (field_id, idempotency_key)`, closing the
   cross-tenant replay edge case (same fix pattern as feature runs, 0005).

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_field_state_foundation"
down_revision = "0006_water_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------- field_states
    op.create_table(
        "field_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="field state"),
        sa.Column("boundary_version", sa.Integer(), nullable=False),
        sa.Column("state_reference_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=60), nullable=False, server_default="UTC"),
        sa.Column("calendar_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "environmental_feature_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feature_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "water_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("water_plans.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "rotation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rotation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("rotation_strategy_key", sa.String(length=60), nullable=True),
        sa.Column("crop_history_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("observation_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("observation_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest_format_version", sa.String(length=40), nullable=False),
        sa.Column("domain_availability", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("evidence_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("quality_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("period_compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("source_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_field_state_status"
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_field_state_period_order"),
    )
    op.create_index(
        "uq_field_state_idempotency",
        "field_states",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_field_states_field", "field_states", ["field_id"])

    # ------------------------------------------- feature_runs additive columns
    op.add_column("feature_runs", sa.Column("boundary_version", sa.Integer(), nullable=True))
    op.add_column(
        "feature_runs",
        sa.Column("observation_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "feature_runs",
        sa.Column("observation_manifest_sha256", sa.String(length=64), nullable=True),
    )

    # -------------------------------------------- water_plans additive columns
    op.add_column("water_plans", sa.Column("boundary_version", sa.Integer(), nullable=True))
    op.add_column("water_plans", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("water_plans", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    # ------------------------------------- F-30: field-scoped ingestion idempotency
    # Drop the legacy KEY-ONLY unique index, create the composite (field_id,
    # idempotency_key) one. Same fix pattern applied to feature/rotation runs
    # in 0005 (F-03); ingestion was the last holdout.
    op.drop_index("uq_ingestion_idempotency", table_name="ingestion_jobs")
    op.create_index(
        "uq_ingestion_idempotency_v2",
        "ingestion_jobs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    # F-30 revert: restore the legacy key-only index, drop the composite.
    op.drop_index("uq_ingestion_idempotency_v2", table_name="ingestion_jobs")
    op.create_index(
        "uq_ingestion_idempotency",
        "ingestion_jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.drop_column("water_plans", "completed_at")
    op.drop_column("water_plans", "started_at")
    op.drop_column("water_plans", "boundary_version")

    op.drop_column("feature_runs", "observation_manifest_sha256")
    op.drop_column("feature_runs", "observation_manifest")
    op.drop_column("feature_runs", "boundary_version")

    op.drop_index("ix_field_states_field", table_name="field_states")
    op.drop_index("uq_field_state_idempotency", table_name="field_states")
    op.drop_table("field_states")

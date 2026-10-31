"""Milestone 4: feature engineering tables — versioned definitions, runs, values.

Revision ID: 0003_feature_engine
Revises: 0002_observation_provenance
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003_feature_engine"
down_revision: Union[str, None] = "0002_observation_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("feature_code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, server_default="climate"),
        sa.Column("aggregation_levels", JSONB, nullable=False, server_default="[]"),
        sa.Column("required_variables", JSONB, nullable=False, server_default="[]"),
        sa.Column("min_coverage_ratio", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("definition_version", sa.String(40), nullable=False),
        sa.Column("formula_reference", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("feature_code", "definition_version", name="uq_feature_definition"),
    )
    op.create_index("ix_feature_definitions_code", "feature_definitions", ["feature_code"])

    op.create_table(
        "feature_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("calendar_timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("hemisphere", sa.String(10), nullable=False, server_default="north"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aggregation_levels", JSONB, nullable=False, server_default="[]"),
        sa.Column("requested_variables", JSONB, nullable=False, server_default="[]"),
        sa.Column("source_selection", JSONB, nullable=False, server_default="{}"),
        sa.Column("crop_seasons", JSONB, nullable=False, server_default="[]"),
        sa.Column("feature_engine_version", sa.String(40), nullable=False),
        sa.Column("feature_catalog_version", sa.String(40), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_parameters", JSONB, nullable=False, server_default="{}"),
        sa.Column("warnings", JSONB, nullable=False, server_default="[]"),
        sa.Column("not_evaluated_reasons", JSONB, nullable=False, server_default="{}"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_feature_run_status",
        ),
        sa.CheckConstraint("hemisphere IN ('north','south')", name="ck_feature_run_hemisphere"),
    )
    op.create_index(
        "uq_feature_run_idempotency",
        "feature_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_feature_runs_field", "feature_runs", ["field_id"])

    op.create_table(
        "feature_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("feature_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_code", sa.String(80), nullable=False),
        sa.Column("aggregation_level", sa.String(20), nullable=False),
        sa.Column("period_label", sa.String(40), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("coverage_ratio", sa.Float(), nullable=True),
        sa.Column("n_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_missing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_status", sa.String(24), nullable=False, server_default="valid"),
        sa.Column("uncertainty_value", sa.Float(), nullable=True),
        sa.Column("uncertainty_type", sa.String(40), nullable=True),
        sa.Column("baseline_reference", JSONB, nullable=True),
        sa.Column("provenance", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "quality_status IN ('valid','partial','insufficient_coverage','missing','not_evaluated')",
            name="ck_feature_value_quality",
        ),
        sa.CheckConstraint(
            "aggregation_level IN ('daily','monthly','seasonal','crop_season')",
            name="ck_feature_value_aggregation",
        ),
        sa.UniqueConstraint(
            "run_id", "feature_code", "aggregation_level", "period_label",
            name="uq_feature_value_period",
        ),
    )
    op.create_index(
        "ix_feature_values_field_feature_period",
        "feature_values",
        ["field_id", "feature_code", "aggregation_level", "period_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_feature_values_field_feature_period", table_name="feature_values")
    op.drop_table("feature_values")
    op.drop_index("ix_feature_runs_field", table_name="feature_runs")
    op.drop_index("uq_feature_run_idempotency", table_name="feature_runs")
    op.drop_table("feature_runs")
    op.drop_index("ix_feature_definitions_code", table_name="feature_definitions")
    op.drop_table("feature_definitions")

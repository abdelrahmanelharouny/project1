"""P2 advanced agricultural intelligence: shared data contracts

Revision ID: 0019_p2_intelligence
Revises: 0018_p1_trust_layer
Create Date: 2026-11-11

Fully ADDITIVE migration (P2 rule: never rewrite/drop existing tables, never
touch observations/recommendations/scenario data). Creates 12 tables for the
six P2 workstreams:

P2.A Satellite Intelligence
  - satellite_scenes: scene-level provenance (index VALUES live in the
    existing `observations` table — one observation store, unchanged).
P2.B Climate Forecasting & Projections
  - weather_forecasts: forecast evidence (issue/valid time, horizon, model,
    uncertainty). Deliberately separate from `observations` so forecasts can
    never overwrite or blend into the historical record.
  - forecast_verifications: aggregate forecast-vs-observation verification.
  - climate_projection_records: projections with scenario/model/ensemble
    identity, bias-correction label and uncertainty bands.
P2.C Soil Memory
  - soil_state_snapshots: immutable checksummed longitudinal soil state.
  - soil_change_estimates: conservative modeled change between snapshots.
P2.D Rotation Failure Lab
  - rotation_stress_runs: deterministic stress-testing runs (pinned inputs,
    robustness metrics, checksum reproducibility).
P2.E Adaptive Evidence Acquisition
  - evidence_gap_reports: append-only gap snapshots.
  - evidence_acquisition_actions + evidence_acquisition_events: acquisition
    lifecycle with append-only event history.
P2.F Farm Portfolio Intelligence
  - portfolio_runs + portfolio_allocations: farm-level CP-SAT area
    allocation under shared resource constraints.

All tables are tenant-scoped through fields/farms (resolved field → farm →
organization at the API layer, matching every existing domain table).
Downgrade drops exactly these tables in FK-safe order; no other objects are
modified.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_p2_intelligence"
down_revision = "0018_p1_trust_layer"
branch_labels = None
depends_on = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def _uuid_col():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # ------------------------------------------------------------------ P2.A
    op.create_table(
        "satellite_scenes",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("scene_id", sa.String(255), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_cover_pct", sa.Float(), nullable=True),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("band_mapping", _jsonb(), nullable=True),
        sa.Column("asset_refs", _jsonb(), nullable=True),
        sa.Column("coverage_fraction", sa.Float(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("processing_version", sa.String(64), nullable=True),
        sa.Column("metadata", _jsonb(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "cloud_cover_pct IS NULL OR (cloud_cover_pct >= 0 AND cloud_cover_pct <= 100)",
            name="ck_satellite_scene_cloud_range",
        ),
    )
    op.create_index(
        "uq_satellite_scene_natural_key",
        "satellite_scenes",
        ["field_id", "provider_code", "scene_id"],
        unique=True,
    )
    op.create_index(
        "ix_satellite_scenes_field_acquired",
        "satellite_scenes",
        ["field_id", "acquired_at"],
    )

    # ------------------------------------------------------------------ P2.B
    op.create_table(
        "weather_forecasts",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("ensemble_member", sa.String(48), nullable=True),
        sa.Column("variable_code", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_hours", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("value_min", sa.Float(), nullable=True),
        sa.Column("value_max", sa.Float(), nullable=True),
        sa.Column("uncertainty_type", sa.String(48), nullable=True),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("quality_status", sa.String(24), nullable=False, server_default="valid"),
        sa.Column("quality_flags", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("processing_version", sa.String(64), nullable=True),
        sa.Column("metadata", _jsonb(), nullable=True),
        sa.Column(
            "ingestion_job_id",
            _uuid_col(),
            sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("horizon_hours >= 0", name="ck_weather_forecast_horizon_nonneg"),
    )
    op.create_index(
        "uq_weather_forecast_natural_key",
        "weather_forecasts",
        ["field_id", "provider_code", "variable_code", "issued_at", "valid_time", "horizon_hours"],
        unique=True,
    )
    op.create_index(
        "ix_weather_forecasts_field_valid",
        "weather_forecasts",
        ["field_id", "variable_code", "valid_time"],
    )

    op.create_table(
        "forecast_verifications",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("variable_code", sa.String(64), nullable=False),
        sa.Column("horizon_bucket_hours", sa.String(24), nullable=False),
        sa.Column("pair_count", sa.Integer(), nullable=False),
        sa.Column("bias", sa.Float(), nullable=True),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_version", sa.String(48), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("warnings", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("pair_count > 0", name="ck_forecast_verification_pair_count"),
    )
    op.create_index(
        "uq_forecast_verification_key",
        "forecast_verifications",
        ["field_id", "provider_code", "variable_code", "horizon_bucket_hours", "window_start", "window_end"],
        unique=True,
    )

    op.create_table(
        "climate_projection_records",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("source_product", sa.String(96), nullable=True),
        sa.Column("model_id", sa.String(96), nullable=True),
        sa.Column("scenario_id", sa.String(48), nullable=True),
        sa.Column("ensemble_size", sa.Integer(), nullable=True),
        sa.Column("bias_correction", sa.String(32), nullable=True),
        sa.Column("variable_code", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_period", sa.String(48), nullable=True),
        sa.Column("statistic", sa.String(48), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("value_min", sa.Float(), nullable=True),
        sa.Column("value_max", sa.Float(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("processing_version", sa.String(64), nullable=True),
        sa.Column("metadata", _jsonb(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_climate_projection_natural_key",
        "climate_projection_records",
        ["field_id", "provider_code", "variable_code", "scenario_id", "model_id", "statistic", "period_start", "period_end"],
        unique=True,
    )
    op.create_index("ix_climate_projections_field", "climate_projection_records", ["field_id"])

    # ------------------------------------------------------------------ P2.C
    op.create_table(
        "soil_state_snapshots",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", _jsonb(), nullable=False),
        sa.Column("source_refs", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("missing_evidence", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", _uuid_col(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_soil_snapshot_checksum",
        "soil_state_snapshots",
        ["field_id", "checksum_sha256"],
        unique=True,
    )
    op.create_index("ix_soil_snapshots_field_asof", "soil_state_snapshots", ["field_id", "as_of"])

    op.create_table(
        "soil_change_estimates",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "start_snapshot_id",
            _uuid_col(),
            sa.ForeignKey("soil_state_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "end_snapshot_id",
            _uuid_col(),
            sa.ForeignKey("soil_state_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("result", _jsonb(), nullable=False),
        sa.Column("assumptions", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("uncertainty", _jsonb(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_soil_change_estimate_key",
        "soil_change_estimates",
        ["field_id", "start_snapshot_id", "end_snapshot_id", "method", "checksum_sha256"],
        unique=True,
    )

    # ------------------------------------------------------------------ P2.D
    op.create_table(
        "rotation_stress_runs",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("request_parameters", _jsonb(), nullable=False),
        sa.Column("result", _jsonb(), nullable=True),
        sa.Column("candidates", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("packs", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("warnings", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("not_evaluated", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("created_by", _uuid_col(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_stress_run_status"),
    )
    op.create_index(
        "uq_rotation_stress_run_idempotency",
        "rotation_stress_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ------------------------------------------------------------------ P2.E
    op.create_table(
        "evidence_gap_reports",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gaps", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("completeness", _jsonb(), nullable=True),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_evidence_gap_reports_field", "evidence_gap_reports", ["field_id", "created_at"])

    op.create_table(
        "evidence_acquisition_actions",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gap_code", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("plan", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="suggested"),
        sa.Column("submitted_ref_kind", sa.String(48), nullable=True),
        sa.Column("submitted_ref_id", _uuid_col(), nullable=True),
        sa.Column("created_by", _uuid_col(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('suggested','in_progress','submitted','resolved','dismissed')",
            name="ck_evidence_action_status",
        ),
    )
    op.create_index(
        "ix_evidence_actions_field_status",
        "evidence_acquisition_actions",
        ["field_id", "status"],
    )

    op.create_table(
        "evidence_acquisition_events",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "action_id",
            _uuid_col(),
            sa.ForeignKey("evidence_acquisition_actions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", _uuid_col(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_evidence_action_events_action",
        "evidence_acquisition_events",
        ["action_id", "created_at"],
    )

    # ------------------------------------------------------------------ P2.F
    op.create_table(
        "portfolio_runs",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "farm_id",
            _uuid_col(),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("request_parameters", _jsonb(), nullable=False),
        sa.Column("result", _jsonb(), nullable=True),
        sa.Column("field_ids", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("objective_weights", _jsonb(), nullable=True),
        sa.Column("scenario", _jsonb(), nullable=True),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("solver_diagnostics", _jsonb(), nullable=True),
        sa.Column("warnings", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("not_evaluated", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("created_by", _uuid_col(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_portfolio_run_status"),
    )
    op.create_index(
        "uq_portfolio_run_idempotency",
        "portfolio_runs",
        ["farm_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "portfolio_allocations",
        sa.Column("id", _uuid_col(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid_col(),
            sa.ForeignKey("portfolio_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            _uuid_col(),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_label", sa.String(48), nullable=False),
        sa.Column("season_index", sa.Integer(), nullable=False),
        sa.Column("crop_code", sa.String(64), nullable=False),
        sa.Column("area_ha", sa.Numeric(10, 2), nullable=False),
        sa.Column("family_key", sa.String(48), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="assigned"),
        sa.Column("metadata", _jsonb(), nullable=True),
        sa.CheckConstraint("area_ha >= 0", name="ck_portfolio_allocation_area_nonneg"),
    )
    op.create_index(
        "uq_portfolio_allocation_key",
        "portfolio_allocations",
        ["run_id", "field_id", "season_index", "crop_code"],
        unique=True,
    )


def downgrade() -> None:
    # Drop in FK-safe order: children first. Only P2 objects are touched.
    op.drop_table("portfolio_allocations")
    op.drop_table("portfolio_runs")
    op.drop_table("evidence_acquisition_events")
    op.drop_table("evidence_acquisition_actions")
    op.drop_table("evidence_gap_reports")
    op.drop_table("rotation_stress_runs")
    op.drop_table("soil_change_estimates")
    op.drop_table("soil_state_snapshots")
    op.drop_table("climate_projection_records")
    op.drop_table("forecast_verifications")
    op.drop_table("weather_forecasts")
    op.drop_table("satellite_scenes")

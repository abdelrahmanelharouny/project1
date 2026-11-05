"""field management intelligence (M6C)

Revision ID: 0008_field_management
Revises: 0007_soil_intelligence
Create Date: 2026-10-31

Additive migration for M6C — Field Management Intelligence
(docs/m6c/M6C_GAP_ANALYSIS.md, ADR-M6C-1..4). No existing table is altered;
the M6B `soil_management_events` event_type CHECK is intentionally NOT
extended — M6C planning artefacts reference events instead of redefining
them.

Tables:
  practice_definitions, operation_templates          (pack materializations)
  soil_cover_observations                             (cover timeline inputs)
  cover_crop_plans, cover_crop_plan_items             (cover-crop planning)
  residue_records, residue_flow_events,
  residue_quality_measurements                        (residue ledger)
  erosion_assessment_runs                             (erosion screening)
  farm_resources, field_operations,
  operation_dependencies, operation_schedule_runs     (operations planning)
  management_plans, management_plan_feedback          (aggregated plan)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_field_management"
down_revision = "0007_soil_intelligence"
branch_labels = None
depends_on = None

_TSTAMPS = (
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

_UUID_PK = sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)


def upgrade() -> None:
    # --- knowledge materializations ---------------------------------------
    op.create_table(
        "practice_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("practice_code", sa.String(length=80), nullable=False),
        sa.Column("practice_family", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="reference"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "practice_family IN ('cover_crop','residue','tillage','soil_cover',"
            "'erosion_control','traffic','termination')",
            name="ck_practice_family",
        ),
        sa.CheckConstraint("status IN ('active','draft','retired')", name="ck_practice_status"),
        sa.CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_practice_validation",
        ),
        sa.UniqueConstraint("pack_id", "practice_code", name="uq_practice_code_per_pack"),
    )
    op.create_index("ix_practice_defs_code", "practice_definitions", ["practice_code"])

    op.create_table(
        "operation_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_code", sa.String(length=80), nullable=False),
        sa.Column("operation_type", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="reference"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_TSTAMPS,
        sa.UniqueConstraint("pack_id", "template_code", name="uq_operation_template_code"),
    )
    op.create_index("ix_operation_templates_type", "operation_templates", ["operation_type"])

    # --- soil cover ---------------------------------------------------------
    op.create_table(
        "soil_cover_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("cover_state", sa.String(length=40), nullable=False),
        sa.Column("cover_fraction", sa.Float(), nullable=True),
        sa.Column("measurement_basis", sa.String(length=40), nullable=False, server_default="visual_estimate"),
        sa.Column("index_type", sa.String(length=40), nullable=True),
        sa.Column("index_value", sa.Float(), nullable=True),
        sa.Column("evidence_class", sa.String(length=60), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "cover_state IN ('living_main_crop','living_cover_crop','surface_residue',"
            "'mulch','bare','unknown','mixed')",
            name="ck_cover_obs_state",
        ),
        sa.CheckConstraint(
            "measurement_basis IN ('visual_estimate','line_point_transect','canopy_scope',"
            "'quadrat','remote_sensing_index','unknown')",
            name="ck_cover_obs_basis",
        ),
        sa.CheckConstraint(
            "cover_fraction IS NULL OR (cover_fraction >= 0 AND cover_fraction <= 1)",
            name="ck_cover_obs_fraction_range",
        ),
    )
    op.create_index("ix_cover_obs_field_date", "soil_cover_observations", ["field_id", "observed_date"])

    # --- cover-crop planning -------------------------------------------------
    op.create_table(
        "cover_crop_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Cover-crop plan"),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("next_crop_label", sa.String(length=160), nullable=True),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("feature_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("water_plan_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_cover_plan_status"),
    )
    op.create_index(
        "uq_cover_plan_idempotency",
        "cover_crop_plans",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_cover_crop_plans_field", "cover_crop_plans", ["field_id"])

    op.create_table(
        "cover_crop_plan_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cover_crop_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crops.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("crop_label", sa.String(length=160), nullable=False),
        sa.Column("is_mixture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mixture_composition", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("season_label", sa.String(length=60), nullable=True),
        sa.Column("intended_sowing_start", sa.Date(), nullable=True),
        sa.Column("intended_sowing_end", sa.Date(), nullable=True),
        sa.Column("intended_termination_window_start", sa.Date(), nullable=True),
        sa.Column("intended_termination_window_end", sa.Date(), nullable=True),
        sa.Column("intended_termination_method", sa.String(length=60), nullable=True),
        sa.Column("intended_functions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("seeding_rate", sa.Float(), nullable=True),
        sa.Column("seeding_rate_unit", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("evidence_class", sa.String(length=60), nullable=False, server_default="farmer_reported_record"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "status IN ('planned','established','terminated','abandoned','cancelled')",
            name="ck_cover_item_status",
        ),
        sa.CheckConstraint("seeding_rate IS NULL OR seeding_rate >= 0", name="ck_cover_item_rate"),
    )
    op.create_index("ix_cover_items_field", "cover_crop_plan_items", ["field_id", "season_label"])

    # --- residue ledger -------------------------------------------------------
    op.create_table(
        "residue_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crops.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("crop_label", sa.String(length=160), nullable=False),
        sa.Column("season_label", sa.String(length=60), nullable=True),
        sa.Column("basis", sa.String(length=20), nullable=False, server_default="dry_matter"),
        sa.Column("produced_dm_kg", sa.Float(), nullable=True),
        sa.Column("production_status", sa.String(length=30), nullable=False),
        sa.Column("coefficient_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("harvested_product_dm_kg", sa.Float(), nullable=True),
        sa.Column("harvested_product_status", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("basis IN ('dry_matter','fresh_weight')", name="ck_residue_basis"),
        sa.CheckConstraint(
            "production_status IN ('measured','farmer_reported','coefficient_estimate','missing')",
            name="ck_residue_production_status",
        ),
        sa.CheckConstraint("produced_dm_kg IS NULL OR produced_dm_kg >= 0", name="ck_residue_produced_nonneg"),
    )
    op.create_index("ix_residue_records_field", "residue_records", ["field_id", "season_label"])

    op.create_table(
        "residue_flow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "residue_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residue_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flow_type", sa.String(length=30), nullable=False),
        sa.Column("flow_date", sa.Date(), nullable=True),
        sa.Column("dm_kg", sa.Float(), nullable=True),
        sa.Column("dm_kg_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("soil_management_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_class", sa.String(length=60), nullable=False, server_default="farmer_reported_record"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "flow_type IN ('retained_surface','incorporated','removed_baled','grazed',"
            "'burned','other_loss','unknown')",
            name="ck_residue_flow_type",
        ),
        sa.CheckConstraint("dm_kg IS NULL OR dm_kg >= 0", name="ck_residue_flow_nonneg"),
        sa.CheckConstraint(
            "dm_kg_status IN ('measured','farmer_reported','estimated','unknown')",
            name="ck_residue_flow_dm_status",
        ),
    )
    op.create_index("ix_residue_flows_record", "residue_flow_events", ["residue_record_id"])

    op.create_table(
        "residue_quality_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "residue_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residue_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("measured_date", sa.Date(), nullable=True),
        sa.Column("carbon_fraction", sa.Float(), nullable=True),
        sa.Column("nitrogen_pct", sa.Float(), nullable=True),
        sa.Column("cn_ratio", sa.Float(), nullable=True),
        sa.Column("lignin_pct", sa.Float(), nullable=True),
        sa.Column("evidence_class", sa.String(length=60), nullable=False, server_default="laboratory_measured"),
        sa.Column("method_notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
    )
    op.create_index("ix_residue_quality_record", "residue_quality_measurements", ["residue_record_id"])

    # --- erosion ---------------------------------------------------------------
    op.create_table(
        "erosion_assessment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Erosion assessment"),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_erosion_run_status"),
    )
    op.create_index(
        "uq_erosion_run_idempotency",
        "erosion_assessment_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_erosion_runs_field", "erosion_assessment_runs", ["field_id"])

    # --- operations & resources -------------------------------------------------
    op.create_table(
        "farm_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("capacity_value", sa.Float(), nullable=True),
        sa.Column("capacity_unit", sa.String(length=30), nullable=True),
        sa.Column("working_width_m", sa.Float(), nullable=True),
        sa.Column("field_efficiency", sa.Float(), nullable=True),
        sa.Column("availability_calendar", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "resource_type IN ('tractor','implement','seeder','sprayer','harvester',"
            "'baler','irrigation_equipment','contractor','labor_crew','storage','transport','other')",
            name="ck_farm_resource_type",
        ),
        sa.CheckConstraint(
            "field_efficiency IS NULL OR (field_efficiency > 0 AND field_efficiency <= 1)",
            name="ck_farm_resource_efficiency",
        ),
    )
    op.create_index("ix_farm_resources_farm", "farm_resources", ["farm_id"])

    op.create_table(
        "field_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_code", sa.String(length=80), nullable=True),
        sa.Column("operation_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("crop_label", sa.String(length=160), nullable=True),
        sa.Column("season_label", sa.String(length=60), nullable=True),
        sa.Column("cover_crop_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("earliest_start", sa.Date(), nullable=True),
        sa.Column("latest_finish", sa.Date(), nullable=True),
        sa.Column("preferred_start", sa.Date(), nullable=True),
        sa.Column("preferred_end", sa.Date(), nullable=True),
        sa.Column("duration_estimate_hours", sa.Float(), nullable=True),
        sa.Column("duration_basis", sa.String(length=40), nullable=True),
        sa.Column("area_ha", sa.Float(), nullable=True),
        sa.Column("resource_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("restrictions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("scheduled_start", sa.Date(), nullable=True),
        sa.Column("scheduled_end", sa.Date(), nullable=True),
        sa.Column("assigned_resource_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("schedule_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("completion_date", sa.Date(), nullable=True),
        sa.Column("completed_soil_management_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column("template_source", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "status IN ('planned','scheduled','started','completed','delayed','cancelled','blocked')",
            name="ck_field_operation_status",
        ),
        sa.CheckConstraint("priority >= 1 AND priority <= 5", name="ck_field_operation_priority"),
        sa.CheckConstraint(
            "duration_estimate_hours IS NULL OR duration_estimate_hours >= 0",
            name="ck_field_operation_duration",
        ),
    )
    op.create_index("ix_field_operations_field", "field_operations", ["field_id", "earliest_start"])
    op.create_index("ix_field_operations_status", "field_operations", ["field_id", "status"])

    op.create_table(
        "operation_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "depends_on_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dependency_type", sa.String(length=30), nullable=False, server_default="finish_to_start"),
        sa.Column("lag_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_TSTAMPS,
        sa.CheckConstraint(
            "dependency_type IN ('finish_to_start','start_to_start','finish_to_finish')",
            name="ck_operation_dependency_type",
        ),
        sa.CheckConstraint("operation_id != depends_on_operation_id", name="ck_operation_dependency_self"),
        sa.UniqueConstraint("operation_id", "depends_on_operation_id", name="uq_operation_dependency_edge"),
    )
    op.create_index("ix_operation_deps_operation", "operation_dependencies", ["operation_id"])

    op.create_table(
        "operation_schedule_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Operations schedule"),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_end", sa.Date(), nullable=True),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','infeasible')", name="ck_schedule_run_status"
        ),
    )
    op.create_index(
        "uq_schedule_run_idempotency",
        "operation_schedule_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_schedule_runs_field", "operation_schedule_runs", ["field_id"])

    # --- management plans ---------------------------------------------------------
    op.create_table(
        "management_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Management plan"),
        sa.Column("season_label", sa.String(length=60), nullable=True),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("cover_crop_plan_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("erosion_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("schedule_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("water_plan_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("feature_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_mgmt_plan_status"),
    )
    op.create_index(
        "uq_mgmt_plan_idempotency",
        "management_plans",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_management_plans_field", "management_plans", ["field_id"])

    op.create_table(
        "management_plan_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "management_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("management_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_role", sa.String(length=20), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("author_role IN ('farmer','agronomist','other')", name="ck_plan_feedback_role"),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_plan_feedback_rating"),
    )
    op.create_index("ix_plan_feedback_plan", "management_plan_feedback", ["management_plan_id"])


def downgrade() -> None:
    # Drop in reverse dependency order (children first).
    op.drop_index("ix_plan_feedback_plan", table_name="management_plan_feedback")
    op.drop_table("management_plan_feedback")
    op.drop_index("ix_management_plans_field", table_name="management_plans")
    op.drop_table("management_plans")
    op.drop_index("ix_schedule_runs_field", table_name="operation_schedule_runs")
    op.drop_table("operation_schedule_runs")
    op.drop_index("ix_operation_deps_operation", table_name="operation_dependencies")
    op.drop_table("operation_dependencies")
    op.drop_index("ix_field_operations_status", table_name="field_operations")
    op.drop_index("ix_field_operations_field", table_name="field_operations")
    op.drop_table("field_operations")
    op.drop_index("ix_farm_resources_farm", table_name="farm_resources")
    op.drop_table("farm_resources")
    op.drop_index("ix_erosion_runs_field", table_name="erosion_assessment_runs")
    op.drop_table("erosion_assessment_runs")
    op.drop_index("ix_residue_quality_record", table_name="residue_quality_measurements")
    op.drop_table("residue_quality_measurements")
    op.drop_index("ix_residue_flows_record", table_name="residue_flow_events")
    op.drop_table("residue_flow_events")
    op.drop_index("ix_residue_records_field", table_name="residue_records")
    op.drop_table("residue_records")
    op.drop_index("ix_cover_items_field", table_name="cover_crop_plan_items")
    op.drop_table("cover_crop_plan_items")
    op.drop_index("ix_cover_crop_plans_field", table_name="cover_crop_plans")
    op.drop_table("cover_crop_plans")
    op.drop_index("ix_cover_obs_field_date", table_name="soil_cover_observations")
    op.drop_table("soil_cover_observations")
    op.drop_index("ix_operation_templates_type", table_name="operation_templates")
    op.drop_table("operation_templates")
    op.drop_index("ix_practice_defs_code", table_name="practice_definitions")
    op.drop_table("practice_definitions")

"""Milestone 5: agricultural knowledge base + rotation intelligence.

Knowledge packs, sources, crop taxonomy, traits, calendar windows, water
parameters, rotation rules, agronomist reviews; tenant-scoped crop history,
farmer preferences, rotation runs and strategies.

Revision ID: 0004_knowledge_rotation
Revises: 0003_feature_engine
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004_knowledge_rotation"
down_revision: Union[str, None] = "0003_feature_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
]


def upgrade() -> None:
    op.create_table(
        "knowledge_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_code", sa.String(80), nullable=False),
        sa.Column("pack_version", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("region_scope", sa.String(80), nullable=False, server_default="global"),
        sa.Column("license_name", sa.String(200), nullable=False),
        sa.Column("attribution_text", sa.Text(), nullable=False),
        sa.Column("license_notes", sa.Text(), nullable=True),
        sa.Column("digitization_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("content", JSONB, nullable=False, server_default="{}"),
        sa.Column("imported_by", UUID(as_uuid=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_TS,
        sa.CheckConstraint(
            "status IN ('draft','active','retired')", name="ck_knowledge_pack_status"
        ),
        sa.UniqueConstraint("pack_code", "pack_version", name="uq_knowledge_pack_version"),
    )
    op.create_index("ix_knowledge_packs_code", "knowledge_packs", ["pack_code"])

    op.create_table(
        "knowledge_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("license", sa.String(200), nullable=True),
        sa.Column("citation_text", sa.Text(), nullable=False),
        *_TS,
        sa.UniqueConstraint("pack_id", "source_key", name="uq_knowledge_source_key"),
    )

    op.create_table(
        "crop_families",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_key", sa.String(80), nullable=False),
        sa.Column("scientific_name", sa.String(120), nullable=False),
        sa.Column("common_names", JSONB, nullable=False, server_default="[]"),
        *_TS,
        sa.UniqueConstraint("pack_id", "family_key", name="uq_crop_family_key"),
    )
    op.create_index("ix_crop_families_pack", "crop_families", ["pack_id"])

    op.create_table(
        "crops",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_code", sa.String(80), nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("crop_families.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scientific_name", sa.String(160), nullable=True),
        sa.Column("common_names", JSONB, nullable=False, server_default="[]"),
        sa.Column("crop_category", sa.String(60), nullable=True),
        sa.Column("life_cycle_type", sa.String(40), nullable=True),
        sa.Column("is_legume", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_cover_crop_capable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        *_TS,
        sa.CheckConstraint("status IN ('active','draft','retired')", name="ck_crop_status"),
        sa.UniqueConstraint("pack_id", "crop_code", name="uq_crop_code_per_pack"),
    )
    op.create_index("ix_crops_code", "crops", ["crop_code"])

    op.create_table(
        "crop_varieties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("crop_id", UUID(as_uuid=True), sa.ForeignKey("crops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variety_name", sa.String(160), nullable=False),
        sa.Column("region_code", sa.String(80), nullable=True),
        sa.Column("maturity_group", sa.String(40), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        *_TS,
    )

    op.create_table(
        "crop_traits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_id", UUID(as_uuid=True), sa.ForeignKey("crops.id", ondelete="CASCADE"), nullable=True),
        sa.Column("crop_variety_id", UUID(as_uuid=True), sa.ForeignKey("crop_varieties.id", ondelete="CASCADE"), nullable=True),
        sa.Column("trait_code", sa.String(80), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_low", sa.Float(), nullable=True),
        sa.Column("value_high", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(40), nullable=True),
        sa.Column("region_code", sa.String(80), nullable=True),
        sa.Column("management_context", sa.String(120), nullable=True),
        sa.Column("growth_stage", sa.String(60), nullable=True),
        sa.Column("conditions", JSONB, nullable=False, server_default="{}"),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_class", sa.String(60), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="reference"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TS,
        sa.CheckConstraint(
            "(crop_id IS NOT NULL)::int + (crop_variety_id IS NOT NULL)::int = 1",
            name="ck_crop_trait_owner",
        ),
        sa.CheckConstraint(
            "(value_numeric IS NOT NULL)::int + (value_text IS NOT NULL)::int + "
            "(value_low IS NOT NULL)::int >= 1",
            name="ck_crop_trait_value",
        ),
        sa.CheckConstraint(
            "confidence IN ('high','moderate','low','unknown')", name="ck_crop_trait_confidence"
        ),
        sa.CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_crop_trait_validation",
        ),
    )
    op.create_index("ix_crop_traits_crop_code", "crop_traits", ["crop_id", "trait_code"])

    op.create_table(
        "crop_calendar_windows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_id", UUID(as_uuid=True), sa.ForeignKey("crops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("region_code", sa.String(80), nullable=True),
        sa.Column("hemisphere", sa.String(10), nullable=False, server_default="north"),
        sa.Column("season_code", sa.String(60), nullable=True),
        sa.Column("planting_start", sa.String(5), nullable=False),
        sa.Column("planting_end", sa.String(5), nullable=False),
        sa.Column("harvest_start", sa.String(5), nullable=True),
        sa.Column("harvest_end", sa.String(5), nullable=True),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_class", sa.String(60), nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="reference"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TS,
        sa.CheckConstraint("hemisphere IN ('north','south')", name="ck_calendar_hemisphere"),
    )
    op.create_index("ix_crop_calendar_crop", "crop_calendar_windows", ["crop_id"])

    op.create_table(
        "crop_water_parameters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_id", UUID(as_uuid=True), sa.ForeignKey("crops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_variety_id", UUID(as_uuid=True), sa.ForeignKey("crop_varieties.id", ondelete="CASCADE"), nullable=True),
        sa.Column("growth_stage", sa.String(40), nullable=False),
        sa.Column("kc_value", sa.Float(), nullable=False),
        sa.Column("kc_method", sa.String(20), nullable=False, server_default="single"),
        sa.Column("stage_length_days", sa.Integer(), nullable=True),
        sa.Column("valid_region", sa.String(80), nullable=True),
        sa.Column("climate_context", sa.String(120), nullable=True),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_class", sa.String(60), nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="reference"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TS,
        sa.CheckConstraint("kc_method IN ('single','dual')", name="ck_kc_method"),
        sa.UniqueConstraint(
            "crop_id", "crop_variety_id", "growth_stage", "kc_method", "valid_region",
            name="uq_crop_water_param",
        ),
    )
    op.create_index("ix_crop_water_crop", "crop_water_parameters", ["crop_id"])

    op.create_table(
        "rotation_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_code", sa.String(120), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("rule_definition", JSONB, nullable=False),
        sa.Column("applies_to_regions", JSONB, nullable=False, server_default="[]"),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="reference"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="advisory"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        *_TS,
        sa.CheckConstraint(
            "rule_type IN ('rotation_break','succession_compatibility','cover_crop_suitability',"
            "'residue_management','soil_cover','host_pathogen','host_pest')",
            name="ck_rotation_rule_type",
        ),
        sa.CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_rotation_rule_validation",
        ),
        sa.CheckConstraint(
            "severity IN ('advisory','recommended','required')", name="ck_rule_severity"
        ),
        sa.UniqueConstraint("pack_id", "rule_code", name="uq_rotation_rule_code"),
    )
    op.create_index("ix_rotation_rules_type", "rotation_rules", ["rule_type"])

    op.create_table(
        "agronomist_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("target_type", sa.String(60), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_TS,
    )
    op.create_index(
        "ix_agronomist_reviews_target", "agronomist_reviews", ["target_type", "target_id"]
    )

    # ------------------------------------------- tenant-scoped decision tables
    op.create_table(
        "crop_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop_id", UUID(as_uuid=True), sa.ForeignKey("crops.id", ondelete="SET NULL"), nullable=True),
        sa.Column("crop_label", sa.String(160), nullable=False),
        sa.Column("variety_id", UUID(as_uuid=True), sa.ForeignKey("crop_varieties.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sowing_date", sa.Date(), nullable=True),
        sa.Column("harvest_date", sa.Date(), nullable=True),
        sa.Column("season_label", sa.String(60), nullable=True),
        sa.Column("area_ha", sa.Float(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="farmer"),
        sa.Column("evidence_class", sa.String(60), nullable=False, server_default="farmer_reported_record"),
        *_TS,
    )
    op.create_index("ix_crop_history_field", "crop_history", ["field_id", "sowing_date"])

    op.create_table(
        "farmer_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("farm_id", UUID(as_uuid=True), sa.ForeignKey("farms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_weights", JSONB, nullable=False, server_default="{}"),
        sa.Column("risk_tolerance", sa.String(30), nullable=True),
        sa.Column("preferred_strategy_style", sa.String(40), nullable=True),
        *_TS,
    )
    op.create_index("ix_farmer_preferences_farm", "farmer_preferences", ["farm_id"])

    op.create_table(
        "rotation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("solver_status", sa.String(20), nullable=True),
        sa.Column("seasons", JSONB, nullable=False, server_default="[]"),
        sa.Column("strategy_profiles", JSONB, nullable=False, server_default="[]"),
        sa.Column("water_allocation_m3", sa.Float(), nullable=True),
        sa.Column("knowledge_pack_refs", JSONB, nullable=False, server_default="[]"),
        sa.Column("feature_run_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("crop_history_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("rotation_engine_version", sa.String(40), nullable=False),
        sa.Column("solver_name", sa.String(60), nullable=False, server_default="cp-sat"),
        sa.Column("solver_version", sa.String(40), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("infeasibility_details", JSONB, nullable=False, server_default="{}"),
        sa.Column("warnings", JSONB, nullable=False, server_default="[]"),
        sa.Column("not_evaluated", JSONB, nullable=False, server_default="{}"),
        sa.Column("request_parameters", JSONB, nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TS,
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_rotation_run_status",
        ),
        sa.CheckConstraint(
            "solver_status IN ('optimal','feasible','infeasible','unknown',"
            "'model_invalid','not_attempted') OR solver_status IS NULL",
            name="ck_rotation_solver_status",
        ),
    )
    op.create_index(
        "uq_rotation_run_idempotency",
        "rotation_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_rotation_runs_field", "rotation_runs", ["field_id"])

    op.create_table(
        "rotation_strategies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("rotation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_key", sa.String(60), nullable=False),
        sa.Column("strategy_kind", sa.String(30), nullable=False, server_default="optimized"),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("profile_weights", JSONB, nullable=False, server_default="{}"),
        sa.Column("assignment", JSONB, nullable=False, server_default="[]"),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column("criteria", JSONB, nullable=False, server_default="[]"),
        sa.Column("constraints_checked", JSONB, nullable=False, server_default="[]"),
        sa.Column("pareto", JSONB, nullable=False, server_default="{}"),
        sa.Column("explanations", JSONB, nullable=False, server_default="{}"),
        sa.Column("evidence_coverage", sa.Float(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        *_TS,
        sa.CheckConstraint(
            "strategy_kind IN ('optimized','baseline')", name="ck_rotation_strategy_kind"
        ),
        sa.UniqueConstraint("run_id", "strategy_key", name="uq_rotation_strategy_key"),
    )


def downgrade() -> None:
    op.drop_table("rotation_strategies")
    op.drop_index("ix_rotation_runs_field", table_name="rotation_runs")
    op.drop_index("uq_rotation_run_idempotency", table_name="rotation_runs")
    op.drop_table("rotation_runs")
    op.drop_index("ix_farmer_preferences_farm", table_name="farmer_preferences")
    op.drop_table("farmer_preferences")
    op.drop_index("ix_crop_history_field", table_name="crop_history")
    op.drop_table("crop_history")
    op.drop_index("ix_agronomist_reviews_target", table_name="agronomist_reviews")
    op.drop_table("agronomist_reviews")
    op.drop_index("ix_rotation_rules_type", table_name="rotation_rules")
    op.drop_table("rotation_rules")
    op.drop_index("ix_crop_water_crop", table_name="crop_water_parameters")
    op.drop_table("crop_water_parameters")
    op.drop_index("ix_crop_calendar_crop", table_name="crop_calendar_windows")
    op.drop_table("crop_calendar_windows")
    op.drop_index("ix_crop_traits_crop_code", table_name="crop_traits")
    op.drop_table("crop_traits")
    op.drop_table("crop_varieties")
    op.drop_index("ix_crops_code", table_name="crops")
    op.drop_table("crops")
    op.drop_index("ix_crop_families_pack", table_name="crop_families")
    op.drop_table("crop_families")
    op.drop_table("knowledge_sources")
    op.drop_index("ix_knowledge_packs_code", table_name="knowledge_packs")
    op.drop_table("knowledge_packs")

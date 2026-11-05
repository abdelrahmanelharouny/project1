"""soil intelligence (Milestone 6B, Step 3)

Revision ID: 0007_soil_intelligence
Revises: 0006_water_intelligence
Create Date: 2026-10-31

Additive migration: introduces the depth-explicit soil measurement domain
(docs/m6b/M6B_AS_BUILT_DESIGN.md, ADR-0022). No existing table is altered;
nothing is rewritten. The 0-5 cm SoilGrids rows in `observations` remain the
backward-compatible surface for rotation/water consumers.

Tables:
  soil_laboratories, soil_analytical_methods, soil_sampling_events,
  soil_samples, soil_sample_layers, soil_measurements,
  soil_management_events, nutrient_products, nutrient_applications,
  nutrient_removals, soc_stock_runs, nutrient_budget_runs,
  soil_assessment_runs.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_soil_intelligence"
down_revision = "0006_water_intelligence"
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


def upgrade() -> None:
    # --- registries -------------------------------------------------------
    op.create_table(
        "soil_laboratories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("accreditation", sa.String(length=160), nullable=True),
        sa.Column("contact", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.UniqueConstraint("organization_id", "name", name="uq_soil_lab_name"),
    )
    op.create_index("ix_soil_labs_org", "soil_laboratories", ["organization_id"])

    op.create_table(
        "soil_analytical_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("property_family", sa.String(length=40), nullable=False),
        sa.Column("analytical_method", sa.String(length=160), nullable=True),
        sa.Column("extraction_method", sa.String(length=160), nullable=True),
        sa.Column("extractant", sa.String(length=160), nullable=True),
        sa.Column("soil_solution_ratio", sa.String(length=40), nullable=True),
        sa.Column("temperature_note", sa.String(length=120), nullable=True),
        sa.Column("reporting_basis", sa.String(length=80), nullable=True),
        sa.Column("reference_text", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "property_family IN ('texture','bulk_density','water_retention','ph','salinity',"
            "'carbon','nitrogen','phosphorus','potassium','cec','biology','other')",
            name="ck_soil_method_family",
        ),
        sa.UniqueConstraint("organization_id", "code", name="uq_soil_method_code"),
    )
    op.create_index("ix_soil_methods_org", "soil_analytical_methods", ["organization_id"])

    # --- sampling domain ---------------------------------------------------
    op.create_table(
        "soil_sampling_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sampling_date", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=True),
        sa.Column("sampling_method", sa.String(length=120), nullable=True),
        sa.Column("sampling_depth_note", sa.String(length=120), nullable=True),
        sa.Column("management_zone", sa.String(length=120), nullable=True),
        sa.Column("gps_lat", sa.Float(), nullable=True),
        sa.Column("gps_lon", sa.Float(), nullable=True),
        sa.Column("composite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subsample_count", sa.Integer(), nullable=True),
        sa.Column("equipment", sa.String(length=160), nullable=True),
        sa.Column("sample_handling", sa.Text(), nullable=True),
        sa.Column("sample_preparation", sa.Text(), nullable=True),
        sa.Column("collected_by", sa.String(length=160), nullable=True),
        sa.Column("quality_status", sa.String(length=20), nullable=False, server_default="valid"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','not_assessed')",
            name="ck_soil_event_quality",
        ),
        sa.CheckConstraint("gps_lat IS NULL OR (gps_lat >= -90 AND gps_lat <= 90)", name="ck_soil_event_lat"),
        sa.CheckConstraint("gps_lon IS NULL OR (gps_lon >= -180 AND gps_lon <= 180)", name="ck_soil_event_lon"),
    )
    op.create_index("ix_soil_events_field_date", "soil_sampling_events", ["field_id", "sampling_date"])

    op.create_table(
        "soil_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_sampling_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_code", sa.String(length=120), nullable=False),
        sa.Column(
            "composite_parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_samples.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "laboratory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_laboratories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("report_reference", sa.String(length=160), nullable=True),
        sa.Column("received_date", sa.Date(), nullable=True),
        sa.Column("reported_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
    )
    op.create_index("uq_soil_sample_code", "soil_samples", ["field_id", "sample_code"], unique=True)
    op.create_index("ix_soil_samples_event", "soil_samples", ["event_id"])
    op.create_index("ix_soil_samples_field", "soil_samples", ["field_id"])

    op.create_table(
        "soil_sample_layers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "sample_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_samples.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("top_depth_cm", sa.Float(), nullable=False),
        sa.Column("bottom_depth_cm", sa.Float(), nullable=False),
        sa.Column("original_depth_unit", sa.String(length=12), nullable=False, server_default="cm"),
        sa.Column("original_top", sa.Float(), nullable=True),
        sa.Column("original_bottom", sa.Float(), nullable=True),
        sa.Column("layer_label", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("top_depth_cm >= 0 AND bottom_depth_cm > top_depth_cm", name="ck_soil_layer_depths"),
    )
    op.create_index(
        "uq_soil_layer_interval",
        "soil_sample_layers",
        ["sample_id", "top_depth_cm", "bottom_depth_cm"],
        unique=True,
    )
    op.create_index("ix_soil_layers_sample", "soil_sample_layers", ["sample_id"])

    op.create_table(
        "soil_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "layer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_sample_layers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("variable_code", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("top_depth_cm", sa.Float(), nullable=True),
        sa.Column("bottom_depth_cm", sa.Float(), nullable=True),
        sa.Column("evidence_class", sa.String(length=40), nullable=False),
        sa.Column("spatial_support_type", sa.String(length=30), nullable=False, server_default="lab_sample"),
        sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="lab_analysis"),
        sa.Column(
            "method_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soil_analytical_methods.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("method_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("detection_limit", sa.Float(), nullable=True),
        sa.Column("quantification_limit", sa.Float(), nullable=True),
        sa.Column("result_qualifier", sa.String(length=12), nullable=True),
        sa.Column("uncertainty_value", sa.Float(), nullable=True),
        sa.Column("uncertainty_type", sa.String(length=60), nullable=True),
        sa.Column("quality_status", sa.String(length=20), nullable=False, server_default="valid"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.Column("processing_version", sa.String(length=40), nullable=False, server_default="v1"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "evidence_class IN ('direct_field_measurement','farmer_reported_record',"
            "'station_observation','satellite_derived_estimate','reanalysis_model_estimate',"
            "'global_soil_prediction','curated_agronomic_reference','synthetic_test_data')",
            name="ck_soil_measurement_evidence",
        ),
        sa.CheckConstraint(
            "source_kind IN ('lab_analysis','farmer_report','soilgrids_profile','synthetic_fixture')",
            name="ck_soil_measurement_source",
        ),
        sa.CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','missing','estimated','not_assessed')",
            name="ck_soil_measurement_quality",
        ),
    )
    op.create_index(
        "uq_soil_measurement_natural_key",
        "soil_measurements",
        ["field_id", "variable_code", "observed_at", "top_depth_cm", "bottom_depth_cm", "source_kind", "method_id"],
        unique=True,
        postgresql_where=sa.text("layer_id IS NULL"),
    )
    op.create_index(
        "ix_soil_measurements_field_var_time", "soil_measurements", ["field_id", "variable_code", "observed_at"]
    )
    op.create_index("ix_soil_measurements_layer", "soil_measurements", ["layer_id"])

    # --- management ledger & nutrient domain -------------------------------
    op.create_table(
        "soil_management_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("nutrient_application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint(
            "event_type IN ('planting','harvest','fertilizer_application','manure_application',"
            "'compost_application','residue_retention','residue_removal','tillage',"
            "'cover_crop_termination','irrigation','soil_amendment','other')",
            name="ck_soil_mgmt_event_type",
        ),
    )
    op.create_index("ix_soil_mgmt_field_date", "soil_management_events", ["field_id", "event_date"])

    op.create_table(
        "nutrient_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("product_type", sa.String(length=40), nullable=False, server_default="fertilizer"),
        sa.Column("n_pct", sa.Float(), nullable=True),
        sa.Column("p_pct", sa.Float(), nullable=True),
        sa.Column("k_pct", sa.Float(), nullable=True),
        sa.Column("reporting_basis", sa.String(length=20), nullable=False, server_default="elemental"),
        sa.Column("dry_matter_fraction", sa.Float(), nullable=True),
        sa.Column("moisture_basis", sa.String(length=30), nullable=True),
        sa.Column("availability_notes", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "product_type IN ('fertilizer','manure','compost','organic_amendment','other')",
            name="ck_nutrient_product_type",
        ),
        sa.CheckConstraint("reporting_basis IN ('elemental','oxide')", name="ck_nutrient_product_basis"),
        sa.UniqueConstraint("organization_id", "name", name="uq_nutrient_product_name"),
    )
    op.create_index("ix_nutrient_products_org", "nutrient_products", ["organization_id"])

    op.create_table(
        "nutrient_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_label", sa.String(length=80), nullable=False),
        sa.Column("application_date", sa.Date(), nullable=False),
        sa.Column("input_kind", sa.String(length=40), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nutrient_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product_name_free", sa.String(length=160), nullable=True),
        sa.Column("applied_mass_kg", sa.Float(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("n_kg", sa.Float(), nullable=True),
        sa.Column("p_kg", sa.Float(), nullable=True),
        sa.Column("k_kg", sa.Float(), nullable=True),
        sa.Column("reporting_basis", sa.String(length=20), nullable=True),
        sa.Column("availability_fraction", sa.Float(), nullable=True),
        sa.Column("availability_basis", sa.Text(), nullable=True),
        sa.Column("application_method", sa.String(length=120), nullable=True),
        sa.Column("moisture_basis", sa.String(length=30), nullable=True),
        sa.Column("evidence_class", sa.String(length=40), nullable=False, server_default="farmer_reported_record"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "input_kind IN ('fertilizer','manure','compost','organic_amendment',"
            "'biological_nitrogen_fixation','atmospheric_deposition','irrigation_water','other')",
            name="ck_nutrient_input_kind",
        ),
        sa.CheckConstraint("applied_mass_kg >= 0 AND area_ha > 0", name="ck_nutrient_application_mass"),
    )
    op.create_index(
        "ix_nutrient_applications_field_season", "nutrient_applications", ["field_id", "season_label"]
    )

    op.create_table(
        "nutrient_removals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_label", sa.String(length=80), nullable=False),
        sa.Column("removal_date", sa.Date(), nullable=True),
        sa.Column("crop_code", sa.String(length=80), nullable=True),
        sa.Column("output_kind", sa.String(length=40), nullable=False, server_default="harvested_product"),
        sa.Column("biomass_kg", sa.Float(), nullable=False),
        sa.Column("dry_matter_fraction", sa.Float(), nullable=True),
        sa.Column("moisture_basis", sa.String(length=30), nullable=False, server_default="as_harvested"),
        sa.Column("n_concentration_g_kg", sa.Float(), nullable=True),
        sa.Column("p_concentration_g_kg", sa.Float(), nullable=True),
        sa.Column("k_concentration_g_kg", sa.Float(), nullable=True),
        sa.Column("concentration_basis", sa.String(length=30), nullable=True),
        sa.Column("concentration_source", sa.Text(), nullable=True),
        sa.Column("evidence_class", sa.String(length=40), nullable=False, server_default="farmer_reported_record"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        *_TSTAMPS,
        sa.CheckConstraint(
            "output_kind IN ('harvested_product','crop_residue','other_biomass')",
            name="ck_nutrient_removal_kind",
        ),
        sa.CheckConstraint("biomass_kg >= 0", name="ck_nutrient_removal_mass"),
        sa.CheckConstraint("moisture_basis IN ('as_harvested','dry_matter')", name="ck_nutrient_removal_moisture"),
    )
    op.create_index("ix_nutrient_removals_field_season", "nutrient_removals", ["field_id", "season_label"])

    # --- immutable run snapshots ------------------------------------------
    op.create_table(
        "soc_stock_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="SOC stock run"),
        sa.Column("input_sample_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("comparison_mode", sa.String(length=30), nullable=False, server_default="single_profile"),
        sa.Column(
            "baseline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soc_stock_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_soc_run_status"),
        sa.CheckConstraint(
            "comparison_mode IN ('single_profile','fixed_depth','equivalent_soil_mass')",
            name="ck_soc_run_mode",
        ),
    )
    op.create_index(
        "uq_soc_run_idempotency",
        "soc_stock_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_soc_runs_field", "soc_stock_runs", ["field_id"])

    op.create_table(
        "nutrient_budget_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Nutrient budget run"),
        sa.Column("seasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_nutrient_run_status"),
    )
    op.create_index(
        "uq_nutrient_run_idempotency",
        "nutrient_budget_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_nutrient_runs_field", "nutrient_budget_runs", ["field_id"])

    op.create_table(
        "soil_assessment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Soil assessment"),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("methods_version", sa.String(length=40), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("request_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        *_TSTAMPS,
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_soil_assessment_status"),
    )
    op.create_index(
        "uq_soil_assessment_idempotency",
        "soil_assessment_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_soil_assessments_field", "soil_assessment_runs", ["field_id"])


def downgrade() -> None:
    op.drop_index("ix_soil_assessments_field", table_name="soil_assessment_runs")
    op.drop_index("uq_soil_assessment_idempotency", table_name="soil_assessment_runs")
    op.drop_table("soil_assessment_runs")

    op.drop_index("ix_nutrient_runs_field", table_name="nutrient_budget_runs")
    op.drop_index("uq_nutrient_run_idempotency", table_name="nutrient_budget_runs")
    op.drop_table("nutrient_budget_runs")

    op.drop_index("ix_soc_runs_field", table_name="soc_stock_runs")
    op.drop_index("uq_soc_run_idempotency", table_name="soc_stock_runs")
    op.drop_table("soc_stock_runs")

    op.drop_index("ix_nutrient_removals_field_season", table_name="nutrient_removals")
    op.drop_table("nutrient_removals")

    op.drop_index("ix_nutrient_applications_field_season", table_name="nutrient_applications")
    op.drop_table("nutrient_applications")

    op.drop_index("ix_nutrient_products_org", table_name="nutrient_products")
    op.drop_table("nutrient_products")

    op.drop_index("ix_soil_mgmt_field_date", table_name="soil_management_events")
    op.drop_table("soil_management_events")

    op.drop_index("ix_soil_measurements_layer", table_name="soil_measurements")
    op.drop_index("ix_soil_measurements_field_var_time", table_name="soil_measurements")
    op.drop_index("uq_soil_measurement_natural_key", table_name="soil_measurements")
    op.drop_table("soil_measurements")

    op.drop_index("ix_soil_layers_sample", table_name="soil_sample_layers")
    op.drop_index("uq_soil_layer_interval", table_name="soil_sample_layers")
    op.drop_table("soil_sample_layers")

    op.drop_index("ix_soil_samples_field", table_name="soil_samples")
    op.drop_index("ix_soil_samples_event", table_name="soil_samples")
    op.drop_index("uq_soil_sample_code", table_name="soil_samples")
    op.drop_table("soil_samples")

    op.drop_index("ix_soil_events_field_date", table_name="soil_sampling_events")
    op.drop_table("soil_sampling_events")

    op.drop_index("ix_soil_methods_org", table_name="soil_analytical_methods")
    op.drop_table("soil_analytical_methods")

    op.drop_index("ix_soil_labs_org", table_name="soil_laboratories")
    op.drop_table("soil_laboratories")

"""sensitivity & uncertainty analysis (Milestone 7.4)

Revision ID: 0010_sensitivity_analysis
Revises: 0009_scenario_execution
Create Date: 2026-11-02

Additive migration:

1. `sensitivity_analyses` — one immutable sensitivity & uncertainty analysis
   of a RESULT-BEARING M7.3 execution run. The analysis varies the run's
   configured transformation parameters over user-supplied bounds and
   recomputes the affected environmental features with the existing M4
   engine through the same code paths M7.3 uses. An analysis is a derived
   analytical artifact — never a mutation of any parent artifact.

   Database-level protection:

   - `source_execution_run_id` / `scenario_id` / `parent_field_state_id`
     FK RESTRICT — protected artifacts cannot be deleted out from under an
     analysis (F-13 idiom).
   - CHECK `ck_sensitivity_analysis_status` — the five honest statuses.
   - CHECK `ck_sensitivity_analysis_checksum_on_success` — result-bearing
     analyses must carry their output checksum.
   - UNIQUE `(source_execution_run_id, analysis_fingerprint)` — deterministic
     replay: the same analysis definition resolves to the SAME analysis; any
     changed design or engine version yields a new fingerprint and a NEW
     analysis.
   - Partial UNIQUE `(source_execution_run_id, idempotency_key)` —
     client-keyed replay.
   - BEFORE UPDATE trigger `enforce_sensitivity_analysis_immutability` —
     result-bearing analyses (`succeeded`, `completed_with_limitations`)
     are frozen: every content column compared, any difference aborts.
   - BEFORE DELETE trigger — result-bearing analyses cannot be deleted.

2. `sensitivity_evaluations` — one row per unique parameter tuple (dedupe
   invariant enforced by UNIQUE `(analysis_id, temperature_delta_c,
   precipitation_multiplier)`); exactly one `is_reference` evaluation per
   analysis reproduces the source run.

3. `sensitivity_feature_values` — raw evaluated feature values per
   evaluation (the response data the metrics derive from).

4. `sensitivity_oat_responses` — per (parameter × feature) one-factor-at-a-
   time metrics with explicit slope units, versioned classification, and
   structured elasticity unavailability.

5. `sensitivity_grid_cells` / `sensitivity_grid_summaries` — the optional
   joint deterministic grid, including the finite-grid interaction contrast
   (explicitly NOT a Sobol index; CHECK-constrained interpretation labels).

6. `sensitivity_uncertainty_items` — the per-analysis uncertainty and
   limitation registry (7 categories, 6 statuses, applicability rubric;
   no composite score columns exist).

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_sensitivity_analysis"
down_revision = "0009_scenario_execution"
branch_labels = None
depends_on = None

IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_sensitivity_analysis_immutability() RETURNS trigger AS $$
BEGIN
    IF OLD.analysis_status IN ('succeeded', 'completed_with_limitations') THEN
        IF NEW.field_id IS DISTINCT FROM OLD.field_id
            OR NEW.source_execution_run_id IS DISTINCT FROM OLD.source_execution_run_id
            OR NEW.scenario_id IS DISTINCT FROM OLD.scenario_id
            OR NEW.scenario_version IS DISTINCT FROM OLD.scenario_version
            OR NEW.parent_field_state_id IS DISTINCT FROM OLD.parent_field_state_id
            OR NEW.parent_snapshot_checksum IS DISTINCT FROM OLD.parent_snapshot_checksum
            OR NEW.scenario_configuration_checksum IS DISTINCT FROM OLD.scenario_configuration_checksum
            OR NEW.source_observation_manifest_sha256 IS DISTINCT FROM OLD.source_observation_manifest_sha256
            OR NEW.source_output_checksum IS DISTINCT FROM OLD.source_output_checksum
            OR NEW.reference_parameter_values IS DISTINCT FROM OLD.reference_parameter_values
            OR NEW.explorable_parameters IS DISTINCT FROM OLD.explorable_parameters
            OR NEW.parameter_design IS DISTINCT FROM OLD.parameter_design
            OR NEW.grid_design IS DISTINCT FROM OLD.grid_design
            OR NEW.analysis_configuration IS DISTINCT FROM OLD.analysis_configuration
            OR NEW.analysis_fingerprint IS DISTINCT FROM OLD.analysis_fingerprint
            OR NEW.analysis_method_version IS DISTINCT FROM OLD.analysis_method_version
            OR NEW.response_classification_version IS DISTINCT FROM OLD.response_classification_version
            OR NEW.uncertainty_registry_version IS DISTINCT FROM OLD.uncertainty_registry_version
            OR NEW.transformation_engine_version IS DISTINCT FROM OLD.transformation_engine_version
            OR NEW.feature_engine_version IS DISTINCT FROM OLD.feature_engine_version
            OR NEW.feature_catalog_version IS DISTINCT FROM OLD.feature_catalog_version
            OR NEW.analysis_status IS DISTINCT FROM OLD.analysis_status
            OR NEW.reference_reproduction IS DISTINCT FROM OLD.reference_reproduction
            OR NEW.evaluation_count IS DISTINCT FROM OLD.evaluation_count
            OR NEW.evaluated_feature_count IS DISTINCT FROM OLD.evaluated_feature_count
            OR NEW.warnings IS DISTINCT FROM OLD.warnings
            OR NEW.not_analysed_features IS DISTINCT FROM OLD.not_analysed_features
            OR NEW.output_checksum IS DISTINCT FROM OLD.output_checksum
            OR NEW.error_summary IS DISTINCT FROM OLD.error_summary
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
        THEN
            RAISE EXCEPTION 'sensitivity analysis % is % and immutable: results cannot change', OLD.id, OLD.analysis_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DELETE_PROTECTION_SQL = """
CREATE OR REPLACE FUNCTION prevent_sensitivity_analysis_result_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.analysis_status IN ('succeeded', 'completed_with_limitations') THEN
        RAISE EXCEPTION 'sensitivity analysis % is % and immutable: result-bearing analyses cannot be deleted', OLD.id, OLD.analysis_status;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "sensitivity_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_execution_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_execution_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column(
            "parent_field_state_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_states.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("parent_snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("scenario_configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_observation_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_output_checksum", sa.String(length=64), nullable=False),
        sa.Column("reference_parameter_values", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("explorable_parameters", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("parameter_design", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("grid_design", postgresql.JSONB(), nullable=True),
        sa.Column("analysis_configuration", postgresql.JSONB(), nullable=False),
        sa.Column("analysis_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("analysis_method_version", sa.String(length=40), nullable=False),
        sa.Column("response_classification_version", sa.String(length=40), nullable=False),
        sa.Column("uncertainty_registry_version", sa.String(length=40), nullable=False),
        sa.Column("transformation_engine_version", sa.String(length=40), nullable=False),
        sa.Column("feature_engine_version", sa.String(length=40), nullable=False),
        sa.Column("feature_catalog_version", sa.String(length=40), nullable=False),
        sa.Column("analysis_status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("reference_reproduction", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evaluation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluated_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("not_analysed_features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_checksum", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "analysis_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_sensitivity_analysis_status",
        ),
        sa.CheckConstraint(
            "analysis_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_sensitivity_analysis_checksum_on_success",
        ),
    )
    op.create_index(
        "uq_sensitivity_analysis_fingerprint",
        "sensitivity_analyses",
        ["source_execution_run_id", "analysis_fingerprint"],
        unique=True,
    )
    op.create_index(
        "uq_sensitivity_analysis_idempotency",
        "sensitivity_analyses",
        ["source_execution_run_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_sensitivity_analyses_run", "sensitivity_analyses", ["source_execution_run_id"])
    op.create_index("ix_sensitivity_analyses_field", "sensitivity_analyses", ["field_id"])
    op.create_index("ix_sensitivity_analyses_scenario", "sensitivity_analyses", ["scenario_id"])

    op.create_table(
        "sensitivity_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluation_kind", sa.String(length=20), nullable=False, server_default="oat"),
        sa.Column("roles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_reference", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("temperature_delta_c", sa.Float(), nullable=True),
        sa.Column("precipitation_multiplier", sa.Float(), nullable=True),
        sa.Column("evaluation_status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("transformed_observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("derived_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "evaluation_kind IN ('reference','oat','grid')",
            name="ck_sensitivity_evaluation_kind",
        ),
        sa.CheckConstraint(
            "evaluation_status IN ('succeeded','failed')",
            name="ck_sensitivity_evaluation_status",
        ),
        sa.UniqueConstraint(
            "analysis_id",
            "temperature_delta_c",
            "precipitation_multiplier",
            name="uq_sensitivity_evaluation_tuple",
        ),
    )
    op.create_index(
        "ix_sensitivity_evaluations_analysis", "sensitivity_evaluations", ["analysis_id"]
    )

    op.create_table(
        "sensitivity_feature_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("aggregation_level", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("reference_value", sa.Float(), nullable=True),
        sa.Column("evaluated_value", sa.Float(), nullable=True),
        sa.Column("difference_from_reference", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_sensitivity_feature_values_analysis", "sensitivity_feature_values", ["analysis_id"]
    )
    op.create_index(
        "ix_sensitivity_feature_values_eval",
        "sensitivity_feature_values",
        ["evaluation_id", "feature_code"],
    )

    op.create_table(
        "sensitivity_oat_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parameter_code", sa.String(length=40), nullable=False),
        sa.Column("feature_code", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("aggregation_level", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("reference_value", sa.Float(), nullable=True),
        sa.Column("min_evaluated", sa.Float(), nullable=True),
        sa.Column("max_evaluated", sa.Float(), nullable=True),
        sa.Column("output_range", sa.Float(), nullable=True),
        sa.Column("max_abs_difference", sa.Float(), nullable=True),
        sa.Column("difference_at_lower", sa.Float(), nullable=True),
        sa.Column("difference_at_upper", sa.Float(), nullable=True),
        sa.Column("slope", sa.Float(), nullable=True),
        sa.Column("slope_method", sa.String(length=30), nullable=False, server_default="not_evaluated"),
        sa.Column("slope_units", sa.String(length=60), nullable=False),
        sa.Column("slope_validity", sa.String(length=60), nullable=False, server_default="valid"),
        sa.Column("elasticity", sa.Float(), nullable=True),
        sa.Column("elasticity_status", sa.String(length=40), nullable=False),
        sa.Column("elasticity_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("direction", sa.String(length=30), nullable=False),
        sa.Column("response_classification", sa.String(length=40), nullable=False),
        sa.Column("classification_version", sa.String(length=40), nullable=False),
        sa.Column("n_evaluated_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "parameter_code IN ('temperature_delta_c','precipitation_multiplier')",
            name="ck_sensitivity_oat_parameter",
        ),
        sa.CheckConstraint(
            "direction IN ('increasing','decreasing','no_change','not_evaluated')",
            name="ck_sensitivity_oat_direction",
        ),
        sa.CheckConstraint(
            "response_status IN ('evaluated','partially_evaluated','not_evaluated')",
            name="ck_sensitivity_oat_response_status",
        ),
        sa.CheckConstraint(
            "slope_method IN ('central','forward_one_sided','backward_one_sided','not_evaluated')",
            name="ck_sensitivity_oat_slope_method",
        ),
    )
    op.create_index(
        "ix_sensitivity_oat_analysis",
        "sensitivity_oat_responses",
        ["analysis_id", "parameter_code", "feature_code", "aggregation_level", "period_label"],
    )

    op.create_table(
        "sensitivity_grid_cells",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("aggregation_level", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("temperature_delta_c", sa.Float(), nullable=True),
        sa.Column("precipitation_multiplier", sa.Float(), nullable=True),
        sa.Column("cell_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "analysis_id",
            "feature_code",
            "aggregation_level",
            "period_label",
            "temperature_delta_c",
            "precipitation_multiplier",
            name="uq_sensitivity_grid_cell",
        ),
    )
    op.create_index("ix_sensitivity_grid_cells_analysis", "sensitivity_grid_cells", ["analysis_id"])

    op.create_table(
        "sensitivity_grid_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("aggregation_level", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("grid_min", sa.Float(), nullable=True),
        sa.Column("grid_max", sa.Float(), nullable=True),
        sa.Column("grid_output_range", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(length=30), nullable=False),
        sa.Column("non_monotonic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("threshold_transition_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interaction_contrast", sa.Float(), nullable=True),
        sa.Column("interaction_interpretation", sa.String(length=40), nullable=False),
        sa.Column("variable_families", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "interaction_interpretation IN ('approximately_additive',"
            "'super_additive_over_explored_grid','sub_additive_over_explored_grid','not_evaluated')",
            name="ck_sensitivity_grid_interaction",
        ),
        sa.CheckConstraint(
            "direction IN ('increasing','decreasing','no_change','not_evaluated')",
            name="ck_sensitivity_grid_direction",
        ),
    )
    op.create_index(
        "ix_sensitivity_grid_summaries_analysis", "sensitivity_grid_summaries", ["analysis_id"]
    )

    op.create_table(
        "sensitivity_uncertainty_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_source", sa.String(length=200), nullable=False),
        sa.Column("quantification_status", sa.String(length=30), nullable=False),
        sa.Column("quantification_method", sa.Text(), nullable=True),
        sa.Column("quantified_value", postgresql.JSONB(), nullable=True),
        sa.Column("affects_current_analysis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("affected_inputs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("affected_features", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("applicability", sa.String(length=20), nullable=False),
        sa.Column("user_facing_explanation", sa.Text(), nullable=False),
        sa.Column("registry_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('parameter_range_uncertainty','observation_data_quality',"
            "'spatial_coverage_limitation','temporal_resolution_limitation',"
            "'model_structural_limitation','feature_method_limitation',"
            "'regional_agronomic_uncertainty')",
            name="ck_sensitivity_uncertainty_category",
        ),
        sa.CheckConstraint(
            "quantification_status IN ('quantified','bounded_exploratory','qualitative_only',"
            "'not_quantified','not_applicable','not_evaluated')",
            name="ck_sensitivity_uncertainty_status",
        ),
        sa.CheckConstraint(
            "applicability IN ('direct','contextual','peripheral')",
            name="ck_sensitivity_uncertainty_applicability",
        ),
    )
    op.create_index(
        "ix_sensitivity_uncertainty_analysis",
        "sensitivity_uncertainty_items",
        ["analysis_id", "category"],
    )

    # ------------------------------------------------- immutability triggers
    op.execute(IMMUTABILITY_TRIGGER_SQL)
    op.execute(DELETE_PROTECTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_sensitivity_analysis_immutability BEFORE UPDATE ON sensitivity_analyses "
        "FOR EACH ROW EXECUTE FUNCTION enforce_sensitivity_analysis_immutability()"
    )
    op.execute(
        "CREATE TRIGGER trg_sensitivity_analysis_no_delete BEFORE DELETE ON sensitivity_analyses "
        "FOR EACH ROW EXECUTE FUNCTION prevent_sensitivity_analysis_result_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sensitivity_analysis_no_delete ON sensitivity_analyses")
    op.execute("DROP TRIGGER IF EXISTS trg_sensitivity_analysis_immutability ON sensitivity_analyses")
    op.execute("DROP FUNCTION IF EXISTS prevent_sensitivity_analysis_result_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_sensitivity_analysis_immutability()")

    op.drop_index("ix_sensitivity_uncertainty_analysis", table_name="sensitivity_uncertainty_items")
    op.drop_table("sensitivity_uncertainty_items")

    op.drop_index("ix_sensitivity_grid_summaries_analysis", table_name="sensitivity_grid_summaries")
    op.drop_table("sensitivity_grid_summaries")

    op.drop_index("ix_sensitivity_grid_cells_analysis", table_name="sensitivity_grid_cells")
    op.drop_table("sensitivity_grid_cells")

    op.drop_index("ix_sensitivity_oat_analysis", table_name="sensitivity_oat_responses")
    op.drop_table("sensitivity_oat_responses")

    op.drop_index("ix_sensitivity_feature_values_eval", table_name="sensitivity_feature_values")
    op.drop_index("ix_sensitivity_feature_values_analysis", table_name="sensitivity_feature_values")
    op.drop_table("sensitivity_feature_values")

    op.drop_index("ix_sensitivity_evaluations_analysis", table_name="sensitivity_evaluations")
    op.drop_table("sensitivity_evaluations")

    op.drop_index("ix_sensitivity_analyses_scenario", table_name="sensitivity_analyses")
    op.drop_index("ix_sensitivity_analyses_field", table_name="sensitivity_analyses")
    op.drop_index("ix_sensitivity_analyses_run", table_name="sensitivity_analyses")
    op.drop_index("uq_sensitivity_analysis_idempotency", table_name="sensitivity_analyses")
    op.drop_index("uq_sensitivity_analysis_fingerprint", table_name="sensitivity_analyses")
    op.drop_table("sensitivity_analyses")

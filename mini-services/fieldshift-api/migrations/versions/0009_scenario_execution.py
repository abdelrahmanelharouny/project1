"""scenario execution engine (Milestone 7.3)

Revision ID: 0009_scenario_execution
Revises: 0008_scenario_domain
Create Date: 2026-11-02

Additive migration:

1. `scenario_execution_runs` — one immutable execution of a FINALIZED scenario
   definition: applies the supported environmental transformations to the
   observations pinned by the parent Field State and recomputes the affected
   environmental features with the existing M4 engine. A run is a derived
   hypothetical calculation, never a new observation of the real world.

   Database-level protection:

   - `scenario_id` FK RESTRICT — the scenario cannot be deleted out from
     under a result-bearing run (F-13 idiom).
   - `parent_field_state_id` FK RESTRICT — the parent snapshot cannot be
     deleted while an execution references it.
   - CHECK `ck_scenario_execution_status` — the five honest run statuses.
   - CHECK `ck_scenario_execution_checksum_on_success` — a result-bearing run
     must carry its output checksum.
   - UNIQUE `(scenario_id, input_fingerprint)` — deterministic replay: the
     same inputs + engine versions resolve to the SAME run (idempotent
     execution); any changed assumption, parent pin or engine version yields
     a different fingerprint and therefore a NEW run.
   - Partial UNIQUE `(scenario_id, idempotency_key)` — client-keyed replay.
   - BEFORE UPDATE trigger `enforce_scenario_execution_immutability` —
     result-bearing runs (`succeeded`, `completed_with_limitations`) are
     frozen: every content column compared, any difference aborts. Failed
     runs may still be deleted (they carry no results); result-bearing runs
     can only be deleted together with their scenario (FK CASCADE from the
     scenario side is intentionally NOT used — scenario deletion is blocked
     by the RESTRICT FK while runs exist).

2. `scenario_derived_observations` — the transformed observation layer.
   Scenario-derived values are NEVER inserted into `observations`. Each row
   keeps its source observation id, the exact transformation code +
   parameter, the derived evidence class and the source's own evidence class.

3. `scenario_derived_features` — baseline-vs-scenario feature comparison
   rows, with `difference_percent` stored only when mathematically
   meaningful (baseline non-null and non-zero).

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_scenario_execution"
down_revision = "0008_scenario_domain"
branch_labels = None
depends_on = None

IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_scenario_execution_immutability() RETURNS trigger AS $$
BEGIN
    IF OLD.run_status IN ('succeeded', 'completed_with_limitations') THEN
        IF NEW.field_id IS DISTINCT FROM OLD.field_id
            OR NEW.scenario_id IS DISTINCT FROM OLD.scenario_id
            OR NEW.scenario_version IS DISTINCT FROM OLD.scenario_version
            OR NEW.parent_field_state_id IS DISTINCT FROM OLD.parent_field_state_id
            OR NEW.parent_snapshot_checksum IS DISTINCT FROM OLD.parent_snapshot_checksum
            OR NEW.scenario_configuration_checksum IS DISTINCT FROM OLD.scenario_configuration_checksum
            OR NEW.transformation_engine_version IS DISTINCT FROM OLD.transformation_engine_version
            OR NEW.feature_engine_version IS DISTINCT FROM OLD.feature_engine_version
            OR NEW.feature_catalog_version IS DISTINCT FROM OLD.feature_catalog_version
            OR NEW.source_observation_manifest IS DISTINCT FROM OLD.source_observation_manifest
            OR NEW.source_observation_manifest_sha256 IS DISTINCT FROM OLD.source_observation_manifest_sha256
            OR NEW.execution_configuration IS DISTINCT FROM OLD.execution_configuration
            OR NEW.input_fingerprint IS DISTINCT FROM OLD.input_fingerprint
            OR NEW.run_status IS DISTINCT FROM OLD.run_status
            OR NEW.aggregation_levels IS DISTINCT FROM OLD.aggregation_levels
            OR NEW.hemisphere IS DISTINCT FROM OLD.hemisphere
            OR NEW.calendar_timezone IS DISTINCT FROM OLD.calendar_timezone
            OR NEW.output_checksum IS DISTINCT FROM OLD.output_checksum
            OR NEW.records_written IS DISTINCT FROM OLD.records_written
            OR NEW.transformed_observation_count IS DISTINCT FROM OLD.transformed_observation_count
            OR NEW.derived_feature_count IS DISTINCT FROM OLD.derived_feature_count
            OR NEW.warnings IS DISTINCT FROM OLD.warnings
            OR NEW.not_evaluated_reasons IS DISTINCT FROM OLD.not_evaluated_reasons
            OR NEW.resource_constraints IS DISTINCT FROM OLD.resource_constraints
            OR NEW.error_summary IS DISTINCT FROM OLD.error_summary
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
        THEN
            RAISE EXCEPTION 'scenario execution % is % and immutable: results cannot change', OLD.id, OLD.run_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DELETE_PROTECTION_SQL = """
CREATE OR REPLACE FUNCTION prevent_scenario_execution_result_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.run_status IN ('succeeded', 'completed_with_limitations') THEN
        RAISE EXCEPTION 'scenario execution % is % and immutable: result-bearing runs cannot be deleted', OLD.id, OLD.run_status;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "scenario_execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
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
        sa.Column("transformation_engine_version", sa.String(length=40), nullable=False),
        sa.Column("feature_engine_version", sa.String(length=40), nullable=False),
        sa.Column("feature_catalog_version", sa.String(length=40), nullable=False),
        sa.Column("source_observation_manifest", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_observation_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("execution_configuration", postgresql.JSONB(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("run_status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("aggregation_levels", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("hemisphere", sa.String(length=10), nullable=False, server_default="north"),
        sa.Column("calendar_timezone", sa.String(length=60), nullable=False, server_default="UTC"),
        sa.Column("output_checksum", sa.String(length=64), nullable=True),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transformed_observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("derived_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("not_evaluated_reasons", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("resource_constraints", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "run_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_scenario_execution_status",
        ),
        sa.CheckConstraint(
            "run_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_scenario_execution_checksum_on_success",
        ),
    )
    op.create_index(
        "uq_scenario_execution_fingerprint",
        "scenario_execution_runs",
        ["scenario_id", "input_fingerprint"],
        unique=True,
    )
    op.create_index(
        "uq_scenario_execution_idempotency",
        "scenario_execution_runs",
        ["scenario_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_scenario_executions_scenario", "scenario_execution_runs", ["scenario_id"])
    op.create_index("ix_scenario_executions_field", "scenario_execution_runs", ["field_id"])

    op.create_table(
        "scenario_derived_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("variable_code", sa.String(length=80), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("transformed_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_support", sa.String(length=20), nullable=False),
        sa.Column("spatial_support_type", sa.String(length=30), nullable=False),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("transformation_code", sa.String(length=40), nullable=False),
        sa.Column("transformation_parameter", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evidence_class", sa.String(length=40), nullable=False),
        sa.Column("source_evidence_class", sa.String(length=40), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_status", sa.String(length=20), nullable=False, server_default="valid"),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "evidence_class IN ('scenario_derived_transformed','synthetic_test')",
            name="ck_scenario_derived_obs_evidence",
        ),
    )
    op.create_index(
        "ix_scenario_derived_obs_run", "scenario_derived_observations", ["execution_run_id"]
    )
    op.create_index(
        "ix_scenario_derived_obs_source", "scenario_derived_observations", ["source_observation_id"]
    )

    op.create_table(
        "scenario_derived_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=80), nullable=False),
        sa.Column("feature_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("aggregation_level", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("scenario_value", sa.Float(), nullable=True),
        sa.Column("difference_value", sa.Float(), nullable=True),
        sa.Column("difference_percent", sa.Float(), nullable=True),
        sa.Column("feature_specification_version", sa.String(length=40), nullable=False),
        sa.Column("evidence_status", sa.String(length=30), nullable=False),
        sa.Column("quality_status", sa.String(length=20), nullable=True),
        sa.Column("coverage_ratio", sa.Float(), nullable=True),
        sa.Column("n_input", sa.Integer(), nullable=True),
        sa.Column("n_missing", sa.Integer(), nullable=True),
        sa.Column("uncertainty_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "evidence_status IN ('scenario_recalculated','not_affected','not_evaluated')",
            name="ck_scenario_derived_feature_evidence",
        ),
    )
    op.create_index(
        "ix_scenario_derived_features_run", "scenario_derived_features", ["execution_run_id"]
    )
    op.create_index(
        "ix_scenario_derived_features_code",
        "scenario_derived_features",
        ["execution_run_id", "feature_code"],
    )

    # ------------------------------------------------- immutability triggers
    op.execute(IMMUTABILITY_TRIGGER_SQL)
    op.execute(DELETE_PROTECTION_SQL)
    op.execute(
        "CREATE TRIGGER trg_scenario_execution_immutability BEFORE UPDATE ON scenario_execution_runs "
        "FOR EACH ROW EXECUTE FUNCTION enforce_scenario_execution_immutability()"
    )
    op.execute(
        "CREATE TRIGGER trg_scenario_execution_no_delete BEFORE DELETE ON scenario_execution_runs "
        "FOR EACH ROW EXECUTE FUNCTION prevent_scenario_execution_result_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_scenario_execution_no_delete ON scenario_execution_runs")
    op.execute("DROP TRIGGER IF EXISTS trg_scenario_execution_immutability ON scenario_execution_runs")
    op.execute("DROP FUNCTION IF EXISTS prevent_scenario_execution_result_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_scenario_execution_immutability()")

    op.drop_index("ix_scenario_derived_features_code", table_name="scenario_derived_features")
    op.drop_index("ix_scenario_derived_features_run", table_name="scenario_derived_features")
    op.drop_table("scenario_derived_features")

    op.drop_index("ix_scenario_derived_obs_source", table_name="scenario_derived_observations")
    op.drop_index("ix_scenario_derived_obs_run", table_name="scenario_derived_observations")
    op.drop_table("scenario_derived_observations")

    op.drop_index("ix_scenario_executions_field", table_name="scenario_execution_runs")
    op.drop_index("ix_scenario_executions_scenario", table_name="scenario_execution_runs")
    op.drop_index("uq_scenario_execution_idempotency", table_name="scenario_execution_runs")
    op.drop_index("uq_scenario_execution_fingerprint", table_name="scenario_execution_runs")
    op.drop_table("scenario_execution_runs")

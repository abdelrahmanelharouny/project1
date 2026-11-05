"""robust multi-scenario rotation (Milestone 7.5)

Revision ID: 0011_robust_rotation
Revises: 0010_sensitivity_analysis
Create Date: 2026-11-02

Additive migration:

1. `scenario_sets` — a named, compatible set of RESULT-BEARING M7.3 execution
   runs for one field (the evaluation environments of a robust rotation).
   Members are copied BY VALUE (checksums, parent pins, engine versions) and
   the set content is checksummed (`set_checksum`, UNIQUE per field).

2. `robust_rotation_runs` — one immutable robust evaluation of ONE shared
   crop-rotation plan across ALL members of a scenario set:

   - the plan is optimized ONCE against the cross-scenario admissible
     candidate pool with a worst-case (maximin) steering objective, then
     evaluated per scenario by the existing M5 post-hoc code;
   - `source_execution_run_id`-style pins: `scenario_set_id` FK RESTRICT +
     BY-VALUE `member_pins` (per-member output checksums, parent pins);
   - CHECK `ck_robust_rotation_run_status` — the five honest statuses;
   - CHECK `ck_robust_rotation_checksum_on_success` — result-bearing runs
     must carry their output checksum;
   - UNIQUE `(scenario_set_id, run_fingerprint)` — deterministic replay: the
     same design over the same set resolves to the SAME run; any changed
     design or engine version yields a new fingerprint and a NEW run;
   - partial UNIQUE `(scenario_set_id, idempotency_key)` — client-keyed
     replay;
   - BEFORE UPDATE trigger `enforce_robust_rotation_run_immutability` —
     result-bearing runs (`succeeded`, `completed_with_limitations`) are
     frozen: every content column compared, any difference aborts;
   - BEFORE DELETE trigger — result-bearing runs cannot be deleted.

3. `robust_rotation_strategies` — one shared plan per strategy profile
   (plus the field's current rotation as the labelled baseline): the
   assignment (identical across scenarios), the cross-scenario aggregates
   (worst-case weighted objective, worst-case regret, robust-feasibility
   verdict) and the strategy checksum.

4. `robust_scenario_evaluations` — one shared plan evaluated on ONE scenario
   environment: criteria (units, directions, missing-evidence lists),
   constraint checks, per-season crop admissibility under that scenario,
   scenario-normalized weighted objective, Pareto flag within the scenario's
   evaluated plan set, and regret versus the scenario's solo optimum. Each
   row pins the source execution run (FK RESTRICT) and its output checksum.

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_robust_rotation"
down_revision = "0010_sensitivity_analysis"
branch_labels = None
depends_on = None

IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_robust_rotation_run_immutability() RETURNS trigger AS $$
BEGIN
    IF OLD.run_status IN ('succeeded', 'completed_with_limitations') THEN
        IF NEW.field_id IS DISTINCT FROM OLD.field_id
            OR NEW.scenario_set_id IS DISTINCT FROM OLD.scenario_set_id
            OR NEW.scenario_set_checksum IS DISTINCT FROM OLD.scenario_set_checksum
            OR NEW.member_pins IS DISTINCT FROM OLD.member_pins
            OR NEW.member_count IS DISTINCT FROM OLD.member_count
            OR NEW.seasons IS DISTINCT FROM OLD.seasons
            OR NEW.strategy_profiles IS DISTINCT FROM OLD.strategy_profiles
            OR NEW.custom_weights IS DISTINCT FROM OLD.custom_weights
            OR NEW.regret_analysis IS DISTINCT FROM OLD.regret_analysis
            OR NEW.run_fingerprint IS DISTINCT FROM OLD.run_fingerprint
            OR NEW.rotation_engine_version IS DISTINCT FROM OLD.rotation_engine_version
            OR NEW.robust_engine_version IS DISTINCT FROM OLD.robust_engine_version
            OR NEW.robust_method_version IS DISTINCT FROM OLD.robust_method_version
            OR NEW.solver_name IS DISTINCT FROM OLD.solver_name
            OR NEW.solver_version IS DISTINCT FROM OLD.solver_version
            OR NEW.random_seed IS DISTINCT FROM OLD.random_seed
            OR NEW.run_status IS DISTINCT FROM OLD.run_status
            OR NEW.solver_status IS DISTINCT FROM OLD.solver_status
            OR NEW.knowledge_pack_refs IS DISTINCT FROM OLD.knowledge_pack_refs
            OR NEW.feature_run_ids IS DISTINCT FROM OLD.feature_run_ids
            OR NEW.warnings IS DISTINCT FROM OLD.warnings
            OR NEW.not_evaluated IS DISTINCT FROM OLD.not_evaluated
            OR NEW.infeasibility_details IS DISTINCT FROM OLD.infeasibility_details
            OR NEW.solver_diagnostics IS DISTINCT FROM OLD.solver_diagnostics
            OR NEW.output_checksum IS DISTINCT FROM OLD.output_checksum
            OR NEW.error_summary IS DISTINCT FROM OLD.error_summary
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
        THEN
            RAISE EXCEPTION 'robust rotation run % is % and immutable: results cannot change', OLD.id, OLD.run_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DELETE_PROTECTION_SQL = """
CREATE OR REPLACE FUNCTION prevent_robust_rotation_run_result_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.run_status IN ('succeeded', 'completed_with_limitations') THEN
        RAISE EXCEPTION 'robust rotation run % is % and immutable: result-bearing runs cannot be deleted', OLD.id, OLD.run_status;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_DDL = [
    "CREATE TRIGGER robust_rotation_run_immutability BEFORE UPDATE ON robust_rotation_runs "
    "FOR EACH ROW EXECUTE FUNCTION enforce_robust_rotation_run_immutability()",
    "CREATE TRIGGER robust_rotation_run_delete_protection BEFORE DELETE ON robust_rotation_runs "
    "FOR EACH ROW EXECUTE FUNCTION prevent_robust_rotation_run_result_delete()",
]


def upgrade() -> None:
    op.create_table(
        "scenario_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "parent_field_state_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_states.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("parent_snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("members", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("compatibility_report", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("set_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active')", name="ck_scenario_set_status"),
        sa.CheckConstraint("member_count >= 1", name="ck_scenario_set_member_count"),
        sa.UniqueConstraint("field_id", "set_checksum", name="uq_scenario_set_content"),
    )
    op.create_index(
        "uq_scenario_set_idempotency",
        "scenario_sets",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_scenario_sets_field", "scenario_sets", ["field_id"])

    op.create_table(
        "robust_rotation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scenario_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scenario_set_checksum", sa.String(length=64), nullable=False),
        sa.Column("member_pins", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("seasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("strategy_profiles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("custom_weights", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("regret_analysis", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("run_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("rotation_engine_version", sa.String(length=40), nullable=False),
        sa.Column("robust_engine_version", sa.String(length=40), nullable=False),
        sa.Column("robust_method_version", sa.String(length=40), nullable=False),
        sa.Column("solver_name", sa.String(length=60), nullable=False, server_default="cp-sat"),
        sa.Column("solver_version", sa.String(length=40), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("solver_status", sa.String(length=20), nullable=True),
        sa.Column("knowledge_pack_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("feature_run_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("not_evaluated", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("infeasibility_details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("solver_diagnostics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_checksum", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "run_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_robust_rotation_run_status",
        ),
        sa.CheckConstraint(
            "solver_status IN ('optimal','feasible','infeasible','unknown',"
            "'model_invalid','not_attempted') OR solver_status IS NULL",
            name="ck_robust_rotation_solver_status",
        ),
        sa.CheckConstraint(
            "run_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_robust_rotation_checksum_on_success",
        ),
        sa.UniqueConstraint("scenario_set_id", "run_fingerprint", name="uq_robust_run_fingerprint"),
    )
    op.create_index(
        "uq_robust_run_idempotency",
        "robust_rotation_runs",
        ["scenario_set_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_robust_runs_set", "robust_rotation_runs", ["scenario_set_id"])
    op.create_index("ix_robust_runs_field", "robust_rotation_runs", ["field_id"])

    op.create_table(
        "robust_rotation_strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("robust_rotation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_key", sa.String(length=60), nullable=False),
        sa.Column("strategy_kind", sa.String(length=30), nullable=False, server_default="optimized"),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("profile_weights", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("assignment", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("worst_case_objective", sa.Float(), nullable=True),
        sa.Column("worst_case_regret", sa.Float(), nullable=True),
        sa.Column("robust_feasibility", sa.String(length=30), nullable=False),
        sa.Column(
            "objective_evaluable_in_all_scenarios", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("solver_status", sa.String(length=20), nullable=True),
        sa.Column("solver_wall_time_ms", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "strategy_kind IN ('optimized','baseline')", name="ck_robust_strategy_kind"
        ),
        sa.CheckConstraint(
            "robust_feasibility IN ('robust_feasible','robust_infeasible','not_evaluable')",
            name="ck_robust_strategy_feasibility",
        ),
        sa.UniqueConstraint("run_id", "strategy_key", name="uq_robust_strategy_key"),
    )
    op.create_index("ix_robust_strategies_run", "robust_rotation_strategies", ["run_id"])

    op.create_table(
        "robust_scenario_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("robust_rotation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("robust_rotation_strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "execution_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_execution_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("output_checksum_pin", sa.String(length=64), nullable=False),
        sa.Column("weighted_objective", sa.Float(), nullable=True),
        sa.Column("objective_evaluable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("on_scenario_pareto_front", sa.Boolean(), nullable=True),
        sa.Column("regret_vs_solo", sa.Float(), nullable=True),
        sa.Column("criteria", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("constraint_checks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("crop_admissibility", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("climate_evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("strategy_id", "scenario_id", name="uq_robust_eval_strategy_scenario"),
    )
    op.create_index("ix_robust_evals_run", "robust_scenario_evaluations", ["run_id"])
    op.create_index(
        "ix_robust_evals_scenario", "robust_scenario_evaluations", ["run_id", "scenario_id"]
    )

    op.execute(IMMUTABILITY_TRIGGER_SQL)
    op.execute(DELETE_PROTECTION_SQL)
    for ddl in TRIGGER_DDL:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS robust_rotation_run_delete_protection ON robust_rotation_runs")
    op.execute("DROP TRIGGER IF EXISTS robust_rotation_run_immutability ON robust_rotation_runs")
    op.execute("DROP FUNCTION IF EXISTS prevent_robust_rotation_run_result_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_robust_rotation_run_immutability()")

    op.drop_index("ix_robust_evals_scenario", table_name="robust_scenario_evaluations")
    op.drop_index("ix_robust_evals_run", table_name="robust_scenario_evaluations")
    op.drop_table("robust_scenario_evaluations")

    op.drop_index("ix_robust_strategies_run", table_name="robust_rotation_strategies")
    op.drop_table("robust_rotation_strategies")

    op.drop_index("ix_robust_runs_field", table_name="robust_rotation_runs")
    op.drop_index("ix_robust_runs_set", table_name="robust_rotation_runs")
    op.drop_index("uq_robust_run_idempotency", table_name="robust_rotation_runs")
    op.drop_table("robust_rotation_runs")

    op.drop_index("ix_scenario_sets_field", table_name="scenario_sets")
    op.drop_index("uq_scenario_set_idempotency", table_name="scenario_sets")
    op.drop_table("scenario_sets")

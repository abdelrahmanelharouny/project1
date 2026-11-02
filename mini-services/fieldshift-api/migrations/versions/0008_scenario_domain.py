"""scenario domain (Milestone 7.2)

Revision ID: 0008_scenario_domain
Revises: 0007_field_state_foundation
Create Date: 2026-11-01

Additive migration:

1. New `scenarios` table — hypothetical field-scenario DEFINITIONS that
   reference an immutable Field State as authoritative baseline. A scenario
   is never a simulation result (nothing executes in M7.2).

   Database-level protection (M7.2 spec §7 "use database-level protection
   where justified"):

   - `parent_field_state_id` FK RESTRICT — a referenced Field State cannot
     be deleted out from under a scenario (F-13 idiom).
   - `parent_scenario_id` FK RESTRICT — lineage members cannot be deleted
     out of a chain.
   - CHECK `ck_scenario_type_evidence_binding` — scenario type and evidence
     classification can never drift apart (M7.0 condition C2): historical
     observed = `observed`, hypothetical types = `hypothetical`,
     contract-only climate/forecast = `not_available`.
   - CHECK `ck_scenario_unavailable_types_never_finalized` — climate
     projection / weather forecast rows could never reach a status that
     implies executable capability.
   - BEFORE UPDATE trigger `enforce_scenario_immutability` — a finalized or
     archived scenario row is frozen: every content column is compared to
     its old value and any difference aborts the statement. Only the
     `finalized → archived` status move (and the bookkeeping `updated_at`)
     is allowed; archived is terminal.

2. New `scenario_validation_records` table — immutable, append-only
   validation results (rule version, status, full result document, checksum
   of the configuration that was validated).

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_scenario_domain"
down_revision = "0007_field_state_foundation"
branch_labels = None
depends_on = None

IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_scenario_immutability() RETURNS trigger AS $$
BEGIN
    IF OLD.scenario_status IN ('finalized', 'archived') THEN
        IF NEW.field_id IS DISTINCT FROM OLD.field_id
            OR NEW.name IS DISTINCT FROM OLD.name
            OR NEW.description IS DISTINCT FROM OLD.description
            OR NEW.scenario_type IS DISTINCT FROM OLD.scenario_type
            OR NEW.lineage_kind IS DISTINCT FROM OLD.lineage_kind
            OR NEW.scenario_version IS DISTINCT FROM OLD.scenario_version
            OR NEW.parent_field_state_id IS DISTINCT FROM OLD.parent_field_state_id
            OR NEW.parent_snapshot_checksum IS DISTINCT FROM OLD.parent_snapshot_checksum
            OR NEW.boundary_version IS DISTINCT FROM OLD.boundary_version
            OR NEW.parent_scenario_id IS DISTINCT FROM OLD.parent_scenario_id
            OR NEW.configuration_schema_version IS DISTINCT FROM OLD.configuration_schema_version
            OR NEW.canonical_configuration IS DISTINCT FROM OLD.canonical_configuration
            OR NEW.configuration_checksum IS DISTINCT FROM OLD.configuration_checksum
            OR NEW.period_start IS DISTINCT FROM OLD.period_start
            OR NEW.period_end IS DISTINCT FROM OLD.period_end
            OR NEW.timezone IS DISTINCT FROM OLD.timezone
            OR NEW.evidence_classification IS DISTINCT FROM OLD.evidence_classification
            OR NEW.assumption_metadata IS DISTINCT FROM OLD.assumption_metadata
            OR NEW.validation_summary IS DISTINCT FROM OLD.validation_summary
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.finalized_at IS DISTINCT FROM OLD.finalized_at
            OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
        THEN
            RAISE EXCEPTION 'scenario % is % and immutable: definition content cannot change', OLD.id, OLD.scenario_status;
        END IF;
        IF OLD.scenario_status = 'finalized' AND NEW.scenario_status NOT IN ('finalized', 'archived') THEN
            RAISE EXCEPTION 'finalized scenario % can only move to archived, not %', OLD.id, NEW.scenario_status;
        END IF;
        IF OLD.scenario_status = 'archived' AND NEW.scenario_status IS DISTINCT FROM 'archived' THEN
            RAISE EXCEPTION 'archived scenario % is terminal', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # ------------------------------------------------------------- scenarios
    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scenario_type", sa.String(length=40), nullable=False),
        sa.Column("scenario_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("lineage_kind", sa.String(length=20), nullable=False, server_default="root"),
        sa.Column("scenario_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_field_state_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("field_states.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("parent_snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("boundary_version", sa.Integer(), nullable=False),
        sa.Column(
            "parent_scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("configuration_schema_version", sa.String(length=20), nullable=False),
        sa.Column(
            "canonical_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=60), nullable=False, server_default="UTC"),
        sa.Column("evidence_classification", sa.String(length=30), nullable=False),
        sa.Column(
            "assumption_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "validation_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
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
            "scenario_type IN ('historical_observed','historical_perturbation',"
            "'user_defined_stress','climate_projection','weather_forecast')",
            name="ck_scenario_type",
        ),
        sa.CheckConstraint(
            "scenario_status IN ('draft','validation_pending','valid','conditionally_valid',"
            "'invalid','finalized','archived','unsupported')",
            name="ck_scenario_status",
        ),
        sa.CheckConstraint(
            "lineage_kind IN ('root','revision','branch')", name="ck_scenario_lineage_kind"
        ),
        sa.CheckConstraint(
            "evidence_classification IN ('observed','hypothetical','not_available')",
            name="ck_scenario_evidence_class",
        ),
        sa.CheckConstraint(
            "(scenario_type = 'historical_observed' AND evidence_classification = 'observed') "
            "OR (scenario_type IN ('historical_perturbation','user_defined_stress') "
            "AND evidence_classification = 'hypothetical') "
            "OR (scenario_type IN ('climate_projection','weather_forecast') "
            "AND evidence_classification = 'not_available')",
            name="ck_scenario_type_evidence_binding",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_scenario_period_order"),
        sa.CheckConstraint(
            "scenario_status != 'finalized' OR finalized_at IS NOT NULL",
            name="ck_scenario_finalized_at_present",
        ),
        sa.CheckConstraint(
            "scenario_type NOT IN ('climate_projection','weather_forecast') "
            "OR scenario_status NOT IN ('valid','conditionally_valid','finalized')",
            name="ck_scenario_unavailable_types_never_finalized",
        ),
    )
    op.create_index(
        "uq_scenario_idempotency",
        "scenarios",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_scenarios_field", "scenarios", ["field_id"])
    op.create_index("ix_scenarios_parent_scenario", "scenarios", ["parent_scenario_id"])
    op.create_index("ix_scenarios_parent_state", "scenarios", ["parent_field_state_id"])

    # --------------------------------------------- scenario_validation_records
    op.create_table(
        "scenario_validation_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("validation_rule_version", sa.String(length=40), nullable=False),
        sa.Column("validation_status", sa.String(length=40), nullable=False),
        sa.Column(
            "validation_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('valid','invalid','conditionally_valid','unsupported',"
            "'not_implemented','missing_reference','incompatible_period',"
            "'insufficient_parent_evidence')",
            name="ck_scenario_validation_status",
        ),
    )
    op.create_index(
        "ix_scenario_validation_scenario", "scenario_validation_records", ["scenario_id"]
    )

    # ------------------------------------------------- immutability trigger
    op.execute(IMMUTABILITY_TRIGGER_SQL)
    op.execute(
        "CREATE TRIGGER trg_scenario_immutability BEFORE UPDATE ON scenarios "
        "FOR EACH ROW EXECUTE FUNCTION enforce_scenario_immutability()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_scenario_immutability ON scenarios")
    op.execute("DROP FUNCTION IF EXISTS enforce_scenario_immutability()")

    op.drop_index("ix_scenario_validation_scenario", table_name="scenario_validation_records")
    op.drop_table("scenario_validation_records")

    op.drop_index("ix_scenarios_parent_state", table_name="scenarios")
    op.drop_index("ix_scenarios_parent_scenario", table_name="scenarios")
    op.drop_index("ix_scenarios_field", table_name="scenarios")
    op.drop_index("uq_scenario_idempotency", table_name="scenarios")
    op.drop_table("scenarios")

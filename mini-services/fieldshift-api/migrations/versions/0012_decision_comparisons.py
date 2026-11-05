"""decision comparisons (Milestone 7.6)

Revision ID: 0012_decision_comparisons
Revises: 0011_robust_rotation
Create Date: 2026-11-02

Additive migration:

`decision_comparisons` — one immutable, checksummed decision document per
field that assembles stored M7.3 executions, M7.4 sensitivity analyses and
M7.5 robust rotation runs into a traceable decision view. Generation reads
aggregates only; nothing is re-executed and no parent artifact is mutated.

Database-level protection:

- `field_id` FK CASCADE (field-scoped, tenant-isolated through ownership).
- CHECK `ck_decision_comparison_status` — the five honest statuses.
- CHECK `ck_decision_comparison_checksum_on_success` — result-bearing
  documents must carry their document checksum.
- UNIQUE `(field_id, fingerprint)` — deterministic regeneration: the same
  scope + generator version resolves to the SAME document.
- Partial UNIQUE `(field_id, idempotency_key)` — client-keyed replay.
- BEFORE UPDATE trigger `enforce_decision_comparison_immutability` —
  result-bearing documents are frozen (every content column compared).
- BEFORE DELETE trigger — result-bearing documents cannot be deleted.

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_decision_comparisons"
down_revision = "0011_robust_rotation"
branch_labels = None
depends_on = None

IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_decision_comparison_immutability() RETURNS trigger AS $$
BEGIN
    IF OLD.doc_status IN ('succeeded', 'completed_with_limitations') THEN
        IF NEW.field_id IS DISTINCT FROM OLD.field_id
            OR NEW.title IS DISTINCT FROM OLD.title
            OR NEW.scope IS DISTINCT FROM OLD.scope
            OR NEW.document IS DISTINCT FROM OLD.document
            OR NEW.document_checksum IS DISTINCT FROM OLD.document_checksum
            OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint
            OR NEW.doc_status IS DISTINCT FROM OLD.doc_status
            OR NEW.warnings IS DISTINCT FROM OLD.warnings
            OR NEW.not_available IS DISTINCT FROM OLD.not_available
            OR NEW.generator_version IS DISTINCT FROM OLD.generator_version
            OR NEW.method_version IS DISTINCT FROM OLD.method_version
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
        THEN
            RAISE EXCEPTION 'decision comparison % is % and immutable: documents cannot change', OLD.id, OLD.doc_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DELETE_PROTECTION_SQL = """
CREATE OR REPLACE FUNCTION prevent_decision_comparison_result_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.doc_status IN ('succeeded', 'completed_with_limitations') THEN
        RAISE EXCEPTION 'decision comparison % is % and immutable: result-bearing documents cannot be deleted', OLD.id, OLD.doc_status;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "decision_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("document", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("document_checksum", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("doc_status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("not_available", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("generator_version", sa.String(length=40), nullable=False),
        sa.Column("method_version", sa.String(length=40), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "doc_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_decision_comparison_status",
        ),
        sa.CheckConstraint(
            "doc_status NOT IN ('succeeded','completed_with_limitations') OR document_checksum IS NOT NULL",
            name="ck_decision_comparison_checksum_on_success",
        ),
        sa.UniqueConstraint("field_id", "fingerprint", name="uq_decision_comparison_fingerprint"),
    )
    op.create_index(
        "uq_decision_comparison_idempotency",
        "decision_comparisons",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_decision_comparisons_field", "decision_comparisons", ["field_id"])

    op.execute(IMMUTABILITY_TRIGGER_SQL)
    op.execute(DELETE_PROTECTION_SQL)
    op.execute(
        "CREATE TRIGGER decision_comparison_immutability BEFORE UPDATE ON decision_comparisons "
        "FOR EACH ROW EXECUTE FUNCTION enforce_decision_comparison_immutability()"
    )
    op.execute(
        "CREATE TRIGGER decision_comparison_delete_protection BEFORE DELETE ON decision_comparisons "
        "FOR EACH ROW EXECUTE FUNCTION prevent_decision_comparison_result_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS decision_comparison_delete_protection ON decision_comparisons")
    op.execute("DROP TRIGGER IF EXISTS decision_comparison_immutability ON decision_comparisons")
    op.execute("DROP FUNCTION IF EXISTS prevent_decision_comparison_result_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_decision_comparison_immutability()")
    op.drop_index("ix_decision_comparisons_field", table_name="decision_comparisons")
    op.drop_index("uq_decision_comparison_idempotency", table_name="decision_comparisons")
    op.drop_table("decision_comparisons")

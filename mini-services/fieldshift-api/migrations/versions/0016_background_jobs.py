"""background jobs: queue-level job records (P0-3 async jobs)

Revision ID: 0016_background_jobs
Revises: 0015_auth_hardening
Create Date: 2026-11-09

Additive migration — one new table, no existing data is rewritten.

`background_jobs` — one row per task executed outside the HTTP request by
the in-process worker pool (app/core/jobs.py):

- `kind` VARCHAR(60) NOT NULL — executor kind (e.g. 'ingestion').
- `status` VARCHAR(20) NOT NULL server_default 'queued' + CHECK
  `ck_background_job_status` IN ('queued','running','succeeded','failed',
  'cancelled'). Rows are never hard-deleted (audit/provenance).
- `progress` INT NOT NULL server_default 0 + CHECK 0..100, `stage`
  VARCHAR(200) NULL — liveness for polling clients.
- `ref_kind`/`ref_id` — the domain row carrying domain-specific state
  (e.g. ingestion_jobs.id); the unified jobs API joins on these.
- `label`, `result` JSONB, `error` TEXT, `request_id`, `created_by`,
  `started_at`, `finished_at` — provenance and diagnostics.

Downgrade drops the table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_background_jobs"
down_revision = "0015_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=200), nullable=True),
        sa.Column("ref_kind", sa.String(length=60), nullable=True),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_background_job_status",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_background_job_progress"),
    )
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_ref", "background_jobs", ["ref_kind", "ref_id"])
    op.create_index("ix_background_jobs_created_by", "background_jobs", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_created_by", table_name="background_jobs")
    op.drop_index("ix_background_jobs_ref", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_table("background_jobs")

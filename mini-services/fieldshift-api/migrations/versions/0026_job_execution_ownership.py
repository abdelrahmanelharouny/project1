"""Add durable execution ownership to background_jobs.

Revision ID: 0026_job_execution_ownership
Revises: 0025_ai_feedback_knowledge
"""

from alembic import op
import sqlalchemy as sa

revision = "0026_job_execution_ownership"
down_revision = "0025_ai_feedback_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "background_jobs",
        sa.Column("owner_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "background_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "background_jobs",
        sa.Column(
            "fencing_token",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_background_job_fencing_token_nonnegative",
        "background_jobs",
        "fencing_token >= 0",
    )
    op.create_index(
        "ix_background_jobs_status_lease",
        "background_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_background_jobs_status_lease", table_name="background_jobs")
    op.drop_constraint(
        "ck_background_job_fencing_token_nonnegative",
        "background_jobs",
        type_="check",
    )
    op.drop_column("background_jobs", "fencing_token")
    op.drop_column("background_jobs", "lease_expires_at")
    op.drop_column("background_jobs", "owner_id")

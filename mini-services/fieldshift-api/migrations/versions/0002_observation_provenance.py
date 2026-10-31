"""M3 audit: persist evidence_class and ingestion_job_id on observations.

Completes the provenance chain: the canonical contract's evidence class is
stored per observation row (not inferred from product metadata), and every
observation links back to the ingestion job that produced it.

Revision ID: 0002_observation_provenance
Revises: 0001_initial
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_observation_provenance"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("evidence_class", sa.String(40), nullable=True),
    )
    op.add_column(
        "observations",
        sa.Column(
            "ingestion_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_observations_ingestion_job", "observations", ["ingestion_job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_observations_ingestion_job", table_name="observations")
    op.drop_column("observations", "ingestion_job_id")
    op.drop_column("observations", "evidence_class")

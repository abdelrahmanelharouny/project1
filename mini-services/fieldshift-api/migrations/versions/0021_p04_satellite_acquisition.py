"""P04 satellite acquisition: lifecycle columns on satellite_scenes.

Revision ID: 0021_p04_satellite_acquisition
Revises: 0020_p3_saas_platform
Create Date: 2026-11-14

Fully ADDITIVE migration (existing rows and indexes untouched):

1. `satellite_scenes.acquisition_status` VARCHAR(24) NULL — the acquisition
   lifecycle: discovered | queued | running | ready | failed. NULL for legacy
   P2 rows (they were ingested on arrival, i.e. effectively 'ready'; the API
   layer COALESCEs NULL -> 'ready' for display). CHECK-constrained.
2. `satellite_scenes.acquisition_detail` JSONB NULL — job reference and
   failure/cancel details ({job_id, error, reason, cancelled, ...}).
3. `satellite_scenes.discovered_at` / `acquisition_updated_at` TIMESTAMPTZ
   NULL — lifecycle timestamps.
4. Partial index `ix_satellite_scenes_field_status` on (field_id,
   acquisition_status) WHERE acquisition_status IS NOT NULL — catalog/status
   listings.

Downgrade drops the added columns and the index (reversible; no other
milestone data is touched).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_p04_satellite_acquisition"
down_revision = "0020_p3_saas_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "satellite_scenes",
        sa.Column("acquisition_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "satellite_scenes",
        sa.Column("acquisition_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "satellite_scenes",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "satellite_scenes",
        sa.Column("acquisition_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_satellite_scene_acquisition_status",
        "satellite_scenes",
        "acquisition_status IS NULL OR acquisition_status IN "
        "('discovered','queued','running','ready','failed')",
    )
    op.create_index(
        "ix_satellite_scenes_field_status",
        "satellite_scenes",
        ["field_id", "acquisition_status"],
        postgresql_where=sa.text("acquisition_status IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_satellite_scenes_field_status", table_name="satellite_scenes")
    op.drop_constraint(
        "ck_satellite_scene_acquisition_status", "satellite_scenes", type_="check"
    )
    op.drop_column("satellite_scenes", "acquisition_updated_at")
    op.drop_column("satellite_scenes", "discovered_at")
    op.drop_column("satellite_scenes", "acquisition_detail")
    op.drop_column("satellite_scenes", "acquisition_status")

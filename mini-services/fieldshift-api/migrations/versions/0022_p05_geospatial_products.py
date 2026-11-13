"""P05 geospatial products: raster asset registry + processing jobs.

Revision ID: 0022_p05_geospatial_products
Revises: 0021_p04_satellite_acquisition
Create Date: 2026-11-14

Fully ADDITIVE migration (existing rows and indexes untouched):

1. `raster_assets` — metadata registry for raster assets stored OUTSIDE
   PostgreSQL (object storage). Binary content never enters relational
   storage; this table holds storage references, checksums, georeferencing,
   quality summaries and provenance. Natural key (field_id, asset_kind,
   scene_id, index_code, processing_version, asset_name) makes reprocessing
   idempotent. `asset_kind` separates ORIGINAL source scenes from
   CropTwist-derived products and preview renderings.

2. `raster_processing_jobs` — domain row for one satellite preprocessing
   job, companion to a `background_jobs` row (kind='raster_processing').
   Carries the processing request (scene, indices, processing version) so
   workers can rebuild inputs after restart. A partial unique index
   (scene_id, processing_version, indices_digest) WHERE status IN
   (queued, running) enforces single-active-job idempotency.

Downgrade drops both tables (reversible; no other milestone data touched).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022_p05_geospatial_products"
down_revision = "0021_p04_satellite_acquisition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raster_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scene_id", sa.String(length=255), nullable=True),
        sa.Column("provider_code", sa.String(length=48), nullable=True),
        sa.Column("product_code", sa.String(length=64), nullable=True),
        sa.Column("index_code", sa.String(length=32), nullable=True),
        sa.Column("asset_kind", sa.String(length=16), nullable=False),
        sa.Column("asset_name", sa.String(length=120), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column("storage_backend", sa.String(length=16), nullable=False, server_default="local"),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("crs", sa.String(length=80), nullable=True),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("transform", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("valid_pixel_fraction", sa.Float(), nullable=True),
        sa.Column("boundary_version", sa.Integer(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "asset_kind IN ('source','derived','preview')",
            name="ck_raster_asset_kind",
        ),
        sa.CheckConstraint(
            "storage_backend IN ('local','s3')",
            name="ck_raster_asset_backend",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_raster_asset_size_nonneg"),
        sa.CheckConstraint(
            "valid_pixel_fraction IS NULL OR (valid_pixel_fraction >= 0 AND "
            "valid_pixel_fraction <= 1)",
            name="ck_raster_asset_valid_fraction_range",
        ),
    )
    op.create_index(
        "uq_raster_asset_natural_key",
        "raster_assets",
        ["field_id", "asset_kind", "scene_id", "index_code", "processing_version", "asset_name"],
        unique=True,
    )
    op.create_index(
        "ix_raster_assets_field_index",
        "raster_assets",
        ["field_id", "index_code", "acquired_at"],
    )
    op.create_index("ix_raster_assets_field_scene", "raster_assets", ["field_id", "scene_id"])

    op.create_table(
        "raster_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("background_job_id", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scene_id", sa.String(length=255), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("indices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("indices_digest", sa.String(length=32), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_raster_processing_job_status",
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_raster_processing_job_progress_range",
        ),
    )
    op.create_index(
        "uq_raster_processing_active",
        "raster_processing_jobs",
        ["scene_id", "processing_version", "indices_digest"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_raster_processing_field_scene",
        "raster_processing_jobs",
        ["field_id", "scene_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_raster_processing_field_scene", table_name="raster_processing_jobs")
    op.drop_index("uq_raster_processing_active", table_name="raster_processing_jobs")
    op.drop_table("raster_processing_jobs")
    op.drop_index("ix_raster_assets_field_scene", table_name="raster_assets")
    op.drop_index("ix_raster_assets_field_index", table_name="raster_assets")
    op.drop_index("uq_raster_asset_natural_key", table_name="raster_assets")
    op.drop_table("raster_assets")

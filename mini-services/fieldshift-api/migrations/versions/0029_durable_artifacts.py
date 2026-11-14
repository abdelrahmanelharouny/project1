"""Create durable tenant-scoped artifact bytes shared by raster and reports.

Revision ID: 0029_durable_artifacts
Revises: 0028_api_key_rate_windows
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0029_durable_artifacts"
down_revision = "0028_api_key_rate_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_objects",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "byte_size > 0", name="ck_artifact_objects_byte_size_positive"
        ),
        sa.CheckConstraint(
            "length(checksum_sha256) = 64", name="ck_artifact_objects_checksum_length"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_artifact_objects_org_key",
        "artifact_objects",
        ["organization_id", "object_key"],
        unique=True,
    )
    op.create_index(
        "ix_artifact_objects_org_created",
        "artifact_objects",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_objects_org_created", table_name="artifact_objects")
    op.drop_index("uq_artifact_objects_org_key", table_name="artifact_objects")
    op.drop_table("artifact_objects")

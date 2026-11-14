"""Shared PostgreSQL rolling-window state for public API-key throttling.

Revision ID: 0028_api_key_rate_windows
Revises: 0027_invoice_payment_identity
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0028_api_key_rate_windows"
down_revision = "0027_invoice_payment_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key_rate_windows",
        sa.Column(
            "api_key_id",
            UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("timestamps", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(timestamps) = 'array' AND jsonb_array_length(timestamps) <= 10000",
            name="ck_api_key_rate_window_bound",
        ),
    )
    op.create_index(
        "ix_api_key_rate_windows_updated",
        "api_key_rate_windows",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_key_rate_windows_updated", table_name="api_key_rate_windows")
    op.drop_table("api_key_rate_windows")

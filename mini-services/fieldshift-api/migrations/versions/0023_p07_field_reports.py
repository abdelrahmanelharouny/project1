"""P07 field-scoped reports: add report_jobs.field_id.

Revision ID: 0023_p07_field_reports
Revises: 0022_p05_geospatial_products
Create Date: 2026-12-02

Additive migration enabling individual-field report scoping (P07 D1):

- `report_jobs.field_id` — optional single-field scope. When set, the
  report gathers data for this field only. NULL keeps the previous
  farm/organization scope semantics. No existing rows are touched.

Downgrade removes the column (reversible; no other milestone data touched).
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_p07_field_reports"
down_revision = "0022_p05_geospatial_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_jobs", sa.Column("field_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_report_jobs_field", "report_jobs", ["field_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_report_jobs_field", table_name="report_jobs")
    op.drop_column("report_jobs", "field_id")

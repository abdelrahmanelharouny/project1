"""merge m6b/m6c soil-management line with M7 main line

Revision ID: 0014_merge_m6bc_m7
Revises: 0013_digital_twin, 0008_field_management
Create Date: 2026-10-31

Housekeeping merge revision: the M6B soil-intelligence and M6C field-management
migrations (0007_soil_intelligence -> 0008_field_management) were developed on a
parallel branch and both share 0006_water_intelligence as their base with the
M7 line (0007_field_state_foundation -> ... -> 0013_digital_twin). This empty
merge revision unifies the two heads so `alembic upgrade head` resolves to a
single tip. No schema changes.
"""

from alembic import op  # noqa: F401

revision = "0014_merge_m6bc_m7"
down_revision = ("0013_digital_twin", "0008_field_management")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Merge point only — no schema operations.
    pass


def downgrade() -> None:
    # Merge point only — no schema operations.
    pass

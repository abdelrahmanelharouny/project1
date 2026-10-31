"""Deepening program hardening (additive only).

Deepening findings addressed (docs/deepening/SCIENTIFIC_AUDIT.md):

- F-03: feature-run / rotation-run idempotency keys become (field_id, key)
  unique — a key replay can no longer cross fields, so it can never leak
  another tenant's run. The old key-only partial unique indexes are replaced.
- F-15: missing indexes on tenant-chain hot paths (farm_constraints.farm_id
  was scanned on every rotation run) and on audit-trail lookups.
- F-18: crop_water_parameters uniqueness becomes NULLS NOT DISTINCT so
  species-level rows (NULL variety) are truly unique in the database and not
  only inside one pack import (PostgreSQL 15+ feature; PG 16.10 in this stack).
- Drift reconciliation: memberships/ingestion_jobs/observations indexes that
  migrations 0001/0002 created but models.py never declared are (re)created
  here idempotently so ORM metadata and the database agree again.

No column is dropped or rewritten; downgrade restores the prior shapes.

Revision ID: 0005_deepening_hardening
Revises: 0004_knowledge_rotation
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_deepening_hardening"
down_revision: Union[str, None] = "0004_knowledge_rotation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- F-03: composite idempotency uniqueness -------------------------
    op.drop_index("uq_feature_run_idempotency", table_name="feature_runs")
    op.create_index(
        "uq_feature_run_idempotency",
        "feature_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("uq_rotation_run_idempotency", table_name="rotation_runs")
    op.create_index(
        "uq_rotation_run_idempotency",
        "rotation_runs",
        ["field_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ---- F-15: tenant-chain and audit indexes ---------------------------
    op.create_index("ix_farm_constraints_farm", "farm_constraints", ["farm_id"])
    op.create_index("ix_crop_varieties_crop", "crop_varieties", ["crop_id"])
    op.create_index(
        "ix_observations_dataset_product", "observations", ["dataset_product_id"]
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index("ix_audit_events_organization", "audit_events", ["organization_id"])

    # ---- F-18: NULLS NOT DISTINCT on the water-parameter uniqueness -----
    op.drop_constraint("uq_crop_water_param", "crop_water_parameters", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_crop_water_param ON crop_water_parameters "
        "(crop_id, crop_variety_id, growth_stage, kc_method, valid_region) "
        "NULLS NOT DISTINCT"
    )

    # ---- drift reconciliation (indexes exist since 0001/0002) -----------
    # These were created by migrations 0001/0002 but never declared in
    # models.py. They already exist on every database that followed the normal
    # migration path, so the reconciliation is idempotent (IF NOT EXISTS).
    op.execute("CREATE INDEX IF NOT EXISTS ix_memberships_user ON memberships (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_field ON ingestion_jobs (field_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_observations_ingestion_job "
        "ON observations (ingestion_job_id)"
    )


def downgrade() -> None:
    # drift indexes predate this revision on the normal path; only drop them
    # when this revision's idempotent creation actually made them — on the
    # normal path they were created by 0001/0002 and must survive downgrade.
    # (0001/0002's downgrades own their lifecycle; nothing to do here.)

    op.drop_index("uq_crop_water_param", table_name="crop_water_parameters")
    op.create_unique_constraint(
        "uq_crop_water_param",
        "crop_water_parameters",
        ["crop_id", "crop_variety_id", "growth_stage", "kc_method", "valid_region"],
    )

    op.drop_index("ix_audit_events_organization", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_observations_dataset_product", table_name="observations")
    op.drop_index("ix_crop_varieties_crop", table_name="crop_varieties")
    op.drop_index("ix_farm_constraints_farm", table_name="farm_constraints")

    op.drop_index("uq_rotation_run_idempotency", table_name="rotation_runs")
    op.create_index(
        "uq_rotation_run_idempotency",
        "rotation_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("uq_feature_run_idempotency", table_name="feature_runs")
    op.create_index(
        "uq_feature_run_idempotency",
        "feature_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

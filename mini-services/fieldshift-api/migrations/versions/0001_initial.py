"""initial schema: identity, tenancy, farms/fields + boundary versions,
data registry, ingestion jobs, canonical observations + quality flags, audit.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostGIS is required before any geometry column exists.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_users_email_lower", "users", [sa.func.lower(sa.text("email"))], unique=True)

    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("organization_type", sa.String(50), nullable=False, server_default="farm"),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_code", sa.String(40), nullable=False, server_default="owner"),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        sa.CheckConstraint("role_code IN ('owner','manager','agronomist','viewer')", name="ck_membership_role"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_auth_tokens_hash", "auth_tokens", ["token_hash"], unique=True)

    op.create_table(
        "farms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("admin_region", sa.String(200), nullable=True),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("unit_system", sa.String(20), nullable=False, server_default="metric"),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("unit_system IN ('metric','imperial')", name="ck_farm_unit_system"),
    )
    op.create_index("ix_farms_organization", "farms", ["organization_id"])

    op.create_table(
        "fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("farm_id", UUID(as_uuid=True), sa.ForeignKey("farms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("boundary", Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False),
        sa.Column("boundary_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("area_ha > 0", name="ck_field_area_positive"),
    )
    op.create_index("ix_fields_farm", "fields", ["farm_id"])

    op.create_table(
        "field_boundary_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("boundary", Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("change_reason", sa.String(500), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("field_id", "version_number", name="uq_boundary_version"),
    )

    op.create_table(
        "data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(60), nullable=False),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("license_name", sa.String(200), nullable=True),
        sa.Column("license_url", sa.Text(), nullable=True),
        sa.Column("attribution_text", sa.Text(), nullable=True),
        sa.Column("documentation_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("known_limitations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_data_sources_provider", "data_sources", ["provider_code"], unique=True)

    op.create_table(
        "dataset_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_code", sa.String(80), nullable=False),
        sa.Column("product_version", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("temporal_resolution", sa.String(40), nullable=True),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "product_code", "product_version", name="uq_dataset_product"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_code", sa.String(60), nullable=False),
        sa.Column("job_type", sa.String(60), nullable=False, server_default="environmental_ingestion"),
        sa.Column("request_parameters", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("records_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled','retrying')",
            name="ck_ingestion_job_status",
        ),
    )
    op.create_index(
        "uq_ingestion_idempotency", "ingestion_jobs", ["idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_ingestion_jobs_field", "ingestion_jobs", ["field_id"])

    op.create_table(
        "observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_product_id", UUID(as_uuid=True),
                  sa.ForeignKey("dataset_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("variable_code", sa.String(80), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_support", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("spatial_support_type", sa.String(30), nullable=False, server_default="field_intersection"),
        sa.Column("spatial_resolution_m", sa.Float(), nullable=True),
        sa.Column("quality_status", sa.String(20), nullable=False, server_default="valid"),
        sa.Column("uncertainty_value", sa.Float(), nullable=True),
        sa.Column("uncertainty_type", sa.String(40), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','missing','estimated','not_assessed')",
            name="ck_observation_quality",
        ),
        sa.CheckConstraint(
            "time_support IN ('instant','hourly','daily','pentadal','dekadal','monthly','seasonal','annual')",
            name="ck_observation_time_support",
        ),
        sa.CheckConstraint(
            "spatial_support_type IN ('point','grid_cell','polygon_average','field_intersection','station','lab_sample')",
            name="ck_observation_spatial_support",
        ),
        sa.UniqueConstraint(
            "field_id", "dataset_product_id", "variable_code", "observed_at",
            "time_support", "spatial_support_type", name="uq_observation_natural_key",
        ),
    )
    op.create_index(
        "ix_observations_field_variable_time", "observations",
        ["field_id", "variable_code", "observed_at"],
    )

    op.create_table(
        "observation_quality_flags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_id", UUID(as_uuid=True),
                  sa.ForeignKey("observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_code", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('info','warning','error')", name="ck_quality_flag_severity"),
    )
    op.create_index("ix_oqf_observation", "observation_quality_flags", ["observation_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("before_snapshot", JSONB(), nullable=True),
        sa.Column("after_snapshot", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "farm_constraints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("farm_id", UUID(as_uuid=True), sa.ForeignKey("farms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("constraint_code", sa.String(80), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("is_hard_constraint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(30), nullable=False, server_default="farmer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("farm_constraints")
    op.drop_table("audit_events")
    op.drop_table("observation_quality_flags")
    op.drop_table("observations")
    op.drop_table("ingestion_jobs")
    op.drop_table("dataset_products")
    op.drop_table("data_sources")
    op.drop_table("field_boundary_versions")
    op.drop_table("fields")
    op.drop_table("farms")
    op.drop_table("auth_tokens")
    op.drop_table("memberships")
    op.drop_table("organizations")
    op.drop_table("users")

"""SQLAlchemy ORM models — first vertical slice schema.

Covers (Master Engineering Prompt §17): identity/tenancy, farms/fields +
boundary versions, data registry (sources/products), ingestion jobs, canonical
observations + quality flags, and audit events.

Later milestones extend this file with soil, crop knowledge, water, rotation,
scenario, journal and review tables (Part V).
"""

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as text_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------- identity
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    tokens: Mapped[list["AuthToken"]] = relationship(back_populates="user")

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(50), nullable=False, default="farm")
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization")
    farms: Mapped[list["Farm"]] = relationship(back_populates="organization")


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_code: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        Index("ix_memberships_user", user_id),
        CheckConstraint(
            "role_code IN ('owner','manager','agronomist','viewer')", name="ck_membership_role"
        ),
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="tokens")

    __table_args__ = (Index("uq_auth_tokens_hash", token_hash, unique=True),)


# ---------------------------------------------------------- farms / fields
class Farm(Base, TimestampMixin):
    __tablename__ = "farms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    admin_region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    unit_system: Mapped[str] = mapped_column(String(20), nullable=False, default="metric")
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    organization: Mapped[Organization] = relationship(back_populates="farms")
    fields: Mapped[list["Field"]] = relationship(back_populates="farm", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("unit_system IN ('metric','imperial')", name="ck_farm_unit_system"),
        Index("ix_farms_organization", organization_id),
    )


class Field(Base, TimestampMixin):
    __tablename__ = "fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    # User boundary stored as validated MULTIPOLYGON in EPSG:4326 (Master §17.2).
    boundary: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )
    boundary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    farm: Mapped[Farm] = relationship(back_populates="fields")
    boundary_versions: Mapped[list["FieldBoundaryVersion"]] = relationship(
        back_populates="field", cascade="all, delete-orphan", order_by="FieldBoundaryVersion.version_number"
    )
    observations: Mapped[list["Observation"]] = relationship(back_populates="field")

    __table_args__ = (
        CheckConstraint("area_ha > 0", name="ck_field_area_positive"),
        Index("ix_fields_farm", farm_id),
    )


class FieldBoundaryVersion(Base):
    __tablename__ = "field_boundary_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    boundary: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    field: Mapped[Field] = relationship(back_populates="boundary_versions")

    __table_args__ = (UniqueConstraint("field_id", "version_number", name="uq_boundary_version"),)


# ------------------------------------------------------ data registry
class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_code: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    known_limitations: Mapped[str | None] = mapped_column(Text, nullable=True)

    products: Mapped[list["DatasetProduct"]] = relationship(back_populates="source")

    __table_args__ = (Index("uq_data_sources_provider", provider_code, unique=True),)


class DatasetProduct(Base, TimestampMixin):
    __tablename__ = "dataset_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    product_code: Mapped[str] = mapped_column(String(80), nullable=False)
    product_version: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    temporal_resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    source: Mapped[DataSource] = relationship(back_populates="products")
    observations: Mapped[list["Observation"]] = relationship(back_populates="dataset_product")

    __table_args__ = (
        UniqueConstraint("source_id", "product_code", "product_version", name="uq_dataset_product"),
    )


# ------------------------------------------------------------- ingestion
class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(60), nullable=False)
    job_type: Mapped[str] = mapped_column(String(60), nullable=False, default="environmental_ingestion")
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled','retrying')",
            name="ck_ingestion_job_status",
        ),
        Index("uq_ingestion_idempotency", idempotency_key, unique=True,
               postgresql_where=text_("idempotency_key IS NOT NULL")),
        Index("ix_ingestion_jobs_field", field_id),
    )


# ---------------------------------------------------------- observations
class Observation(Base):
    """Canonical observation row (Master Engineering Prompt §13.1 / §17.3)."""

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    dataset_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_products.id", ondelete="RESTRICT"), nullable=False
    )
    variable_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # null = missing/nodata
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_support: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    spatial_support_type: Mapped[str] = mapped_column(String(30), nullable=False, default="field_intersection")
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid")
    # Evidence class from the canonical contract, persisted per row (M3 audit):
    # providers that emit mixed evidence classes stay representable, and the
    # passport never depends on inference alone. Nullable for legacy rows.
    evidence_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    uncertainty_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Job that produced this row (M3 audit): completes the job→observation→
    # feature provenance chain. Nullable for legacy rows; jobs are never
    # hard-deleted.
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    field: Mapped[Field] = relationship(back_populates="observations")
    dataset_product: Mapped[DatasetProduct] = relationship(back_populates="observations")
    quality_flags: Mapped[list["ObservationQualityFlag"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','missing','estimated','not_assessed')",
            name="ck_observation_quality",
        ),
        CheckConstraint(
            "time_support IN ('instant','hourly','daily','pentadal','dekadal','monthly','seasonal','annual')",
            name="ck_observation_time_support",
        ),
        CheckConstraint(
            "spatial_support_type IN ('point','grid_cell','polygon_average','field_intersection','station','lab_sample')",
            name="ck_observation_spatial_support",
        ),
        # Natural-key dedupe: makes provider ingestion idempotent on retry.
        UniqueConstraint(
            "field_id",
            "dataset_product_id",
            "variable_code",
            "observed_at",
            "time_support",
            "spatial_support_type",
            name="uq_observation_natural_key",
        ),
        Index("ix_observations_field_variable_time", field_id, variable_code, observed_at),
        Index("ix_observations_ingestion_job", ingestion_job_id),
        Index("ix_observations_dataset_product", dataset_product_id),
    )


class ObservationQualityFlag(Base):
    __tablename__ = "observation_quality_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=False
    )
    flag_code: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    observation: Mapped[Observation] = relationship(back_populates="quality_flags")

    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','error')", name="ck_quality_flag_severity"),
        Index("ix_oqf_observation", observation_id),
    )


# ------------------------------------------------------------------ audit
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_events_entity", entity_type, entity_id, created_at),
        Index("ix_audit_events_organization", organization_id),
    )


class FarmConstraint(Base, TimestampMixin):
    """Farmer-defined constraints table (Master §17.7) — minimal slice subset."""

    __tablename__ = "farm_constraints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    constraint_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_hard_constraint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="farmer")

    __table_args__ = (
        # Deepening F-15: queried on every rotation run (farm constraint load).
        Index("ix_farm_constraints_farm", farm_id),
    )


# ------------------------------------------------------- feature engineering
class FeatureDefinition(Base, TimestampMixin):
    """Versioned feature definition (Milestone 4).

    Feature codes, units, coverage policy and formula references are data, not
    code smell: every computed value links to the definition version it was
    produced with, so historical feature values remain interpretable when the
    catalog evolves. Thresholds used by count-style indicators cite their
    source convention (WMO / ETCCDI) and are explicitly NOT crop-specific.
    """

    __tablename__ = "feature_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="climate")
    aggregation_levels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    required_variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    min_coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    definition_version: Mapped[str] = mapped_column(String(40), nullable=False)
    formula_reference: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("feature_code", "definition_version", name="uq_feature_definition"),
        Index("ix_feature_definitions_code", feature_code),
    )


class FeatureRun(Base, TimestampMixin):
    """A reproducible feature computation over one field (Milestone 4).

    The run records EVERYTHING needed to reproduce it: the resolved source
    selection (one dataset product per variable — synthetic and real data are
    never blended), the calendar timezone and hemisphere, the period window,
    the engine version and the feature-definition version. Values are written
    once by a run; comparing runs is the supported way to see change.
    """

    __tablename__ = "feature_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    calendar_timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    hemisphere: Mapped[str] = mapped_column(String(10), nullable=False, default="north")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    aggregation_levels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    requested_variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    crop_seasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    feature_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_catalog_version: Mapped[str] = mapped_column(String(40), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated_reasons: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    values: Mapped[list["FeatureValue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_feature_run_status",
        ),
        CheckConstraint("hemisphere IN ('north','south')", name="ck_feature_run_hemisphere"),
        Index(
            "uq_feature_run_idempotency",
            field_id,
            idempotency_key,
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_feature_runs_field", field_id),
    )


class FeatureValue(Base):
    """One derived feature value for one calendar period (Milestone 4).

    `value` is NULL exactly when the value could not be honestly computed
    (coverage below the definition's minimum, or a required baseline/input
    missing) — missing observations are never treated as zero (Master rule 11).
    Provenance links the value back to the contributing observations, their
    dataset products, processing versions and evidence classes.
    """

    __tablename__ = "feature_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feature_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="valid")
    uncertainty_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    baseline_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[FeatureRun] = relationship(back_populates="values")

    __table_args__ = (
        CheckConstraint(
            "quality_status IN ('valid','partial','insufficient_coverage','missing','not_evaluated')",
            name="ck_feature_value_quality",
        ),
        CheckConstraint(
            "aggregation_level IN ('daily','monthly','seasonal','crop_season')",
            name="ck_feature_value_aggregation",
        ),
        UniqueConstraint(
            "run_id", "feature_code", "aggregation_level", "period_label",
            name="uq_feature_value_period",
        ),
        Index(
            "ix_feature_values_field_feature_period",
            field_id, feature_code, aggregation_level, period_start,
        ),
    )


# ==========================================================================
# Milestone 5 — agricultural knowledge base & decision intelligence
# (docs/architecture/knowledge-model.md; ADR-0014..0018)
# ==========================================================================

class KnowledgePack(Base, TimestampMixin):
    """A versioned, source-cited container of agricultural knowledge.

    Packs are platform-level (not tenant-scoped) and independent of
    environmental providers. A pack import is validated as a whole and stores
    its checksum so identical inputs are idempotent. `status` governs use:
    only `active` packs feed candidate generation and optimization; `draft`
    packs are inspectable but inert; `retired` packs are history.
    """

    __tablename__ = "knowledge_packs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_code: Mapped[str] = mapped_column(String(80), nullable=False)
    pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region_scope: Mapped[str] = mapped_column(String(80), nullable=False, default="global")
    license_name: Mapped[str] = mapped_column(String(200), nullable=False)
    attribution_text: Mapped[str] = mapped_column(Text, nullable=False)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    digitization_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft','active','retired')", name="ck_knowledge_pack_status"),
        UniqueConstraint("pack_code", "pack_version", name="uq_knowledge_pack_version"),
        Index("ix_knowledge_packs_code", pack_code),
    )


class KnowledgeSource(Base, TimestampMixin):
    """A citable reference backing knowledge attributes (Master §17.13)."""

    __tablename__ = "knowledge_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    citation_text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("pack_id", "source_key", name="uq_knowledge_source_key"),
    )


class CropFamily(Base, TimestampMixin):
    """Botanical family (taxonomy backbone for rotation relationships)."""

    __tablename__ = "crop_families"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    family_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scientific_name: Mapped[str] = mapped_column(String(120), nullable=False)
    common_names: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("pack_id", "family_key", name="uq_crop_family_key"),
        Index("ix_crop_families_pack", pack_id),
    )


class Crop(Base, TimestampMixin):
    """A crop species. Broad flags are descriptors, never agronomic conclusions."""

    __tablename__ = "crops"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    crop_code: Mapped[str] = mapped_column(String(80), nullable=False)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_families.id", ondelete="SET NULL"), nullable=True
    )
    scientific_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    common_names: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    crop_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    life_cycle_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_legume: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cover_crop_capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    family: Mapped[CropFamily | None] = relationship()

    __table_args__ = (
        CheckConstraint("status IN ('active','draft','retired')", name="ck_crop_status"),
        UniqueConstraint("pack_id", "crop_code", name="uq_crop_code_per_pack"),
        Index("ix_crops_code", crop_code),
    )


class CropVariety(Base, TimestampMixin):
    """Cultivar-level record; traits MAY be attached at variety level when the
    source is variety-specific (species-level traits stay on `crops`)."""

    __tablename__ = "crop_varieties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    crop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="CASCADE"), nullable=False
    )
    variety_name: Mapped[str] = mapped_column(String(160), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    maturity_group: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_crop_varieties_crop", crop_id),
    )


class CropTrait(Base, TimestampMixin):
    """One sourced attribute value for one crop (or variety) under one region /
    management / growth-stage context. Multiple rows per trait_code are
    EXPECTED (different contexts) — conflicts must be detectable, not merged."""

    __tablename__ = "crop_traits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="CASCADE"), nullable=True
    )
    crop_variety_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_varieties.id", ondelete="CASCADE"), nullable=True
    )
    trait_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    management_context: Mapped[str | None] = mapped_column(String(120), nullable=True)
    growth_stage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[KnowledgeSource] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(crop_id IS NOT NULL)::int + (crop_variety_id IS NOT NULL)::int = 1",
            name="ck_crop_trait_owner",
        ),
        CheckConstraint(
            "(value_numeric IS NOT NULL)::int + (value_text IS NOT NULL)::int + "
            "(value_low IS NOT NULL)::int >= 1",
            name="ck_crop_trait_value",
        ),
        CheckConstraint(
            "confidence IN ('high','moderate','low','unknown')", name="ck_crop_trait_confidence"
        ),
        CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_crop_trait_validation",
        ),
        Index("ix_crop_traits_crop_code", crop_id, trait_code),
    )


class CropCalendarWindow(Base, TimestampMixin):
    """Sowing/harvest window for a crop in a region & hemisphere.

    Dates are month-day strings (MM-DD) so windows recur annually; a window
    whose start exceeds its end wraps across the year boundary."""

    __tablename__ = "crop_calendar_windows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    crop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="CASCADE"), nullable=False
    )
    region_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hemisphere: Mapped[str] = mapped_column(String(10), nullable=False, default="north")
    season_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    planting_start: Mapped[str] = mapped_column(String(5), nullable=False)
    planting_end: Mapped[str] = mapped_column(String(5), nullable=False)
    harvest_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    harvest_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("hemisphere IN ('north','south')", name="ck_calendar_hemisphere"),
        Index("ix_crop_calendar_crop", crop_id),
    )


class CropWaterParameter(Base, TimestampMixin):
    """Growth-stage Kc (or other water parameter) — NEVER guessed. A crop with
    no verified parameter row stays unsupported for water calculations."""

    __tablename__ = "crop_water_parameters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    crop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="CASCADE"), nullable=False
    )
    crop_variety_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_varieties.id", ondelete="CASCADE"), nullable=True
    )
    growth_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    kc_value: Mapped[float] = mapped_column(Float, nullable=False)
    kc_method: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    stage_length_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    climate_context: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("kc_method IN ('single','dual')", name="ck_kc_method"),
        # Deepening F-18: NULLS NOT DISTINCT — species-level rows (NULL
        # variety) were previously treated as distinct by PostgreSQL, allowing
        # duplicate Kc anchor rows that only the import validator caught.
        UniqueConstraint(
            "crop_id", "crop_variety_id", "growth_stage", "kc_method", "valid_region",
            name="uq_crop_water_param",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_crop_water_crop", crop_id),
    )


class RotationRule(Base, TimestampMixin):
    """A structured agronomic relationship rule (Master §17.13 knowledge_rules
    specialised for rotation reasoning). Hard enforcement requires
    validation_status='confirmed_regional'; reference rules inform explanations
    and conditional eligibility only."""

    __tablename__ = "rotation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # {predecessor:{crop|family:key}, successor:{crop|family:key},
    #  min_break_seasons:int, mechanism:str, severity:str}
    rule_definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    applies_to_regions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="advisory")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    source: Mapped[KnowledgeSource] = relationship()

    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('rotation_break','succession_compatibility','cover_crop_suitability',"
            "'residue_management','soil_cover','host_pathogen','host_pest')",
            name="ck_rotation_rule_type",
        ),
        CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_rotation_rule_validation",
        ),
        CheckConstraint("severity IN ('advisory','recommended','required')", name="ck_rule_severity"),
        UniqueConstraint("pack_id", "rule_code", name="uq_rotation_rule_code"),
        Index("ix_rotation_rules_type", rule_type),
    )


class AgronomistReview(Base, TimestampMixin):
    """Review workflow records that upgrade reference knowledge to locally
    validated / regionally confirmed states (Master §17.13)."""

    __tablename__ = "agronomist_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_agronomist_reviews_target", target_type, target_id),
    )


# ------------------------------------------------- crop history / preferences
class CropHistory(Base, TimestampMixin):
    """What actually grew on a field (Master §17.8) — the rotation baseline."""

    __tablename__ = "crop_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="SET NULL"), nullable=True
    )
    crop_label: Mapped[str] = mapped_column(String(160), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crop_varieties.id", ondelete="SET NULL"), nullable=True
    )
    sowing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    harvest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    season_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="farmer")
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False, default="farmer_reported_record")

    __table_args__ = (
        Index("ix_crop_history_field", field_id, sowing_date),
    )


class FarmerPreference(Base, TimestampMixin):
    """Farm-level objectives & strategy style (Master §17.7)."""

    __tablename__ = "farmer_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    objective_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    risk_tolerance: Mapped[str | None] = mapped_column(String(30), nullable=True)
    preferred_strategy_style: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_farmer_preferences_farm", farm_id),
    )


# ------------------------------------------------------- rotation runs (M5)
class RotationRun(Base, TimestampMixin):
    """A reproducible rotation optimization over one field.

    Snapshots EVERYTHING needed to reproduce: planning seasons, strategy
    profiles/weights, active knowledge-pack versions + checksums, feature-run
    ids consumed, crop-history ids, engine + solver versions, seed. Values are
    written once; the baseline is preserved as a labelled strategy."""

    __tablename__ = "rotation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    solver_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    strategy_profiles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    water_allocation_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    knowledge_pack_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    feature_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    crop_history_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    rotation_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    solver_name: Mapped[str] = mapped_column(String(60), nullable=False, default="cp-sat")
    solver_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    infeasibility_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    strategies: Mapped[list["RotationStrategy"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_rotation_run_status",
        ),
        CheckConstraint(
            "solver_status IN ('optimal','feasible','infeasible','unknown',"
            "'model_invalid','not_attempted') OR solver_status IS NULL",
            name="ck_rotation_solver_status",
        ),
        Index(
            "uq_rotation_run_idempotency",
            field_id,
            idempotency_key,
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_rotation_runs_field", field_id),
    )


class RotationStrategy(Base, TimestampMixin):
    """One candidate strategy of a run: assignment + full evaluation evidence."""

    __tablename__ = "rotation_strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rotation_runs.id", ondelete="CASCADE"), nullable=False
    )
    strategy_key: Mapped[str] = mapped_column(String(60), nullable=False)
    strategy_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="optimized")
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profile_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assignment: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    constraints_checked: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    pareto: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    explanations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    run: Mapped[RotationRun] = relationship(back_populates="strategies")

    __table_args__ = (
        CheckConstraint(
            "strategy_kind IN ('optimized','baseline')", name="ck_rotation_strategy_kind"
        ),
        UniqueConstraint("run_id", "strategy_key", name="uq_rotation_strategy_key"),
    )

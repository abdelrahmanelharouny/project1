"""ORM models for M6B (soil), M6C (field management) and M7.3–M7.7.

Reconstructed 1:1 from Alembic migrations 0007_soil_intelligence …
0013_digital_twin (merge revision 0014_merge_m6bc_m7 adds no schema).
Conventions intentionally mirror app/db/models.py: UUID(as_uuid=True) PKs with
python-side uuid4 defaults, TimestampMixin for created/updated pairs, inline
created_at for append-only child tables, JSONB with python-side defaults,
constraint/index names copied verbatim from the migrations.

Relationships are deliberately not declared (new-domain modules query via
select(); nothing navigates ORM relationships).
"""

import uuid
from datetime import date, datetime
from typing import Any

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, TimestampMixin, _uuid

__all__ = [
    "SoilLaboratory",
    "SoilAnalyticalMethod",
    "SoilSamplingEvent",
    "SoilSample",
    "SoilSampleLayer",
    "SoilMeasurement",
    "SoilManagementEvent",
    "NutrientProduct",
    "NutrientApplication",
    "NutrientRemoval",
    "SocStockRun",
    "NutrientBudgetRun",
    "SoilAssessmentRun",
    "PracticeDefinition",
    "OperationTemplate",
    "SoilCoverObservation",
    "CoverCropPlan",
    "CoverCropPlanItem",
    "ResidueRecord",
    "ResidueFlowEvent",
    "ResidueQualityMeasurement",
    "ErosionAssessmentRun",
    "FarmResource",
    "FieldOperation",
    "OperationDependency",
    "OperationScheduleRun",
    "ManagementPlan",
    "ManagementPlanFeedback",
    "ScenarioExecutionRun",
    "ScenarioDerivedObservation",
    "ScenarioDerivedFeature",
    "SensitivityAnalysis",
    "SensitivityEvaluation",
    "SensitivityFeatureValue",
    "SensitivityOatResponse",
    "SensitivityGridCell",
    "SensitivityGridSummary",
    "SensitivityUncertaintyItem",
    "ScenarioSet",
    "RobustRotationRun",
    "RobustRotationStrategy",
    "RobustScenarioEvaluation",
    "DecisionComparison",
    "DigitalTwinValidation",
]


# ---------------------------------------------------------------------------
# M6B — soil intelligence (migration 0007_soil_intelligence)
# ---------------------------------------------------------------------------


class SoilLaboratory(Base, TimestampMixin):
    __tablename__ = "soil_laboratories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    accreditation: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_soil_lab_name"),
        Index("ix_soil_labs_org", "organization_id"),
    )


class SoilAnalyticalMethod(Base, TimestampMixin):
    __tablename__ = "soil_analytical_methods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    property_family: Mapped[str] = mapped_column(String(40), nullable=False)
    analytical_method: Mapped[str | None] = mapped_column(String(160), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(160), nullable=True)
    extractant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    soil_solution_ratio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    temperature_note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reporting_basis: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "property_family IN ('texture','bulk_density','water_retention','ph','salinity',"
            "'carbon','nitrogen','phosphorus','potassium','cec','biology','other')",
            name="ck_soil_method_family",
        ),
        UniqueConstraint("organization_id", "code", name="uq_soil_method_code"),
        Index("ix_soil_methods_org", "organization_id"),
    )


class SoilSamplingEvent(Base, TimestampMixin):
    __tablename__ = "soil_sampling_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    sampling_date: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sampling_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sampling_depth_note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    management_zone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subsample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equipment: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sample_handling: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_preparation: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("gps_lat IS NULL OR (gps_lat >= -90 AND gps_lat <= 90)", name="ck_soil_event_lat"),
        CheckConstraint("gps_lon IS NULL OR (gps_lon >= -180 AND gps_lon <= 180)", name="ck_soil_event_lon"),
        CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','not_assessed')",
            name="ck_soil_event_quality",
        ),
        Index("ix_soil_events_field_date", "field_id", "sampling_date"),
    )


class SoilSample(Base, TimestampMixin):
    __tablename__ = "soil_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_sampling_events.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    sample_code: Mapped[str] = mapped_column(String(120), nullable=False)
    composite_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_samples.id", ondelete="SET NULL"), nullable=True
    )
    laboratory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_laboratories.id", ondelete="SET NULL"), nullable=True
    )
    report_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reported_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("uq_soil_sample_code", "field_id", "sample_code", unique=True),
        Index("ix_soil_samples_event", "event_id"),
        Index("ix_soil_samples_field", "field_id"),
    )


class SoilSampleLayer(Base, TimestampMixin):
    __tablename__ = "soil_sample_layers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    sample_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_samples.id", ondelete="CASCADE"), nullable=False
    )
    top_depth_cm: Mapped[float] = mapped_column(Float, nullable=False)
    bottom_depth_cm: Mapped[float] = mapped_column(Float, nullable=False)
    original_depth_unit: Mapped[str] = mapped_column(String(12), nullable=False, default="cm")
    original_top: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_bottom: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "top_depth_cm >= 0 AND bottom_depth_cm > top_depth_cm", name="ck_soil_layer_depths"
        ),
        Index("uq_soil_layer_interval", "sample_id", "top_depth_cm", "bottom_depth_cm", unique=True),
        Index("ix_soil_layers_sample", "sample_id"),
    )


class SoilMeasurement(Base, TimestampMixin):
    __tablename__ = "soil_measurements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    layer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_sample_layers.id", ondelete="CASCADE"), nullable=True
    )
    variable_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    top_depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bottom_depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_class: Mapped[str] = mapped_column(String(40), nullable=False)
    spatial_support_type: Mapped[str] = mapped_column(String(30), nullable=False, default="lab_sample")
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="lab_analysis")
    method_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_analytical_methods.id", ondelete="SET NULL"), nullable=True
    )
    method_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    detection_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantification_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_qualifier: Mapped[str | None] = mapped_column(String(12), nullable=True)
    uncertainty_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    processing_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "evidence_class IN ('direct_field_measurement','farmer_reported_record',"
            "'station_observation','satellite_derived_estimate','reanalysis_model_estimate',"
            "'global_soil_prediction','curated_agronomic_reference','synthetic_test_data')",
            name="ck_soil_measurement_evidence",
        ),
        CheckConstraint(
            "source_kind IN ('lab_analysis','farmer_report','soilgrids_profile','synthetic_fixture')",
            name="ck_soil_measurement_source",
        ),
        CheckConstraint(
            "quality_status IN ('valid','suspect','invalid','missing','estimated','not_assessed')",
            name="ck_soil_measurement_quality",
        ),
        Index(
            "uq_soil_measurement_natural_key",
            "field_id",
            "variable_code",
            "observed_at",
            "top_depth_cm",
            "bottom_depth_cm",
            "source_kind",
            "method_id",
            unique=True,
            postgresql_where=text_("layer_id IS NULL"),
        ),
        Index("ix_soil_measurements_field_var_time", "field_id", "variable_code", "observed_at"),
        Index("ix_soil_measurements_layer", "layer_id"),
    )


class SoilManagementEvent(Base, TimestampMixin):
    __tablename__ = "soil_management_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Logical reference to nutrient_applications.id — intentionally no FK constraint.
    nutrient_application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('planting','harvest','fertilizer_application','manure_application',"
            "'compost_application','residue_retention','residue_removal','tillage',"
            "'cover_crop_termination','irrigation','soil_amendment','other')",
            name="ck_soil_mgmt_event_type",
        ),
        Index("ix_soil_mgmt_field_date", "field_id", "event_date"),
    )


class NutrientProduct(Base, TimestampMixin):
    __tablename__ = "nutrient_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_type: Mapped[str] = mapped_column(String(40), nullable=False, default="fertilizer")
    n_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reporting_basis: Mapped[str] = mapped_column(String(20), nullable=False, default="elemental")
    dry_matter_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    moisture_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    availability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "product_type IN ('fertilizer','manure','compost','organic_amendment','other')",
            name="ck_nutrient_product_type",
        ),
        CheckConstraint(
            "reporting_basis IN ('elemental','oxide')", name="ck_nutrient_product_basis"
        ),
        UniqueConstraint("organization_id", "name", name="uq_nutrient_product_name"),
        Index("ix_nutrient_products_org", "organization_id"),
    )


class NutrientApplication(Base, TimestampMixin):
    __tablename__ = "nutrient_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    season_label: Mapped[str] = mapped_column(String(80), nullable=False)
    application_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nutrient_products.id", ondelete="SET NULL"), nullable=True
    )
    product_name_free: Mapped[str | None] = mapped_column(String(160), nullable=True)
    applied_mass_kg: Mapped[float] = mapped_column(Float, nullable=False)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    n_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    reporting_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    availability_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    moisture_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_class: Mapped[str] = mapped_column(
        String(40), nullable=False, default="farmer_reported_record"
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "input_kind IN ('fertilizer','manure','compost','organic_amendment',"
            "'biological_nitrogen_fixation','atmospheric_deposition','irrigation_water','other')",
            name="ck_nutrient_input_kind",
        ),
        CheckConstraint("applied_mass_kg >= 0 AND area_ha > 0", name="ck_nutrient_application_mass"),
        Index("ix_nutrient_applications_field_season", "field_id", "season_label"),
    )


class NutrientRemoval(Base, TimestampMixin):
    __tablename__ = "nutrient_removals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    season_label: Mapped[str] = mapped_column(String(80), nullable=False)
    removal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    crop_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    output_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="harvested_product")
    biomass_kg: Mapped[float] = mapped_column(Float, nullable=False)
    dry_matter_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    moisture_basis: Mapped[str] = mapped_column(String(30), nullable=False, default="as_harvested")
    n_concentration_g_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_concentration_g_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    k_concentration_g_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    concentration_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_class: Mapped[str] = mapped_column(
        String(40), nullable=False, default="farmer_reported_record"
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "output_kind IN ('harvested_product','crop_residue','other_biomass')",
            name="ck_nutrient_removal_kind",
        ),
        CheckConstraint("biomass_kg >= 0", name="ck_nutrient_removal_mass"),
        CheckConstraint(
            "moisture_basis IN ('as_harvested','dry_matter')", name="ck_nutrient_removal_moisture"
        ),
        Index("ix_nutrient_removals_field_season", "field_id", "season_label"),
    )


class SocStockRun(Base, TimestampMixin):
    __tablename__ = "soc_stock_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="SOC stock run")
    input_sample_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    comparison_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="single_profile")
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soc_stock_runs.id", ondelete="SET NULL"), nullable=True
    )
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_soc_run_status"
        ),
        CheckConstraint(
            "comparison_mode IN ('single_profile','fixed_depth','equivalent_soil_mass')",
            name="ck_soc_run_mode",
        ),
        Index(
            "uq_soc_run_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_soc_runs_field", "field_id"),
    )


class NutrientBudgetRun(Base, TimestampMixin):
    __tablename__ = "nutrient_budget_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Nutrient budget run")
    seasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_nutrient_run_status"
        ),
        Index(
            "uq_nutrient_run_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_nutrient_runs_field", "field_id"),
    )


class SoilAssessmentRun(Base, TimestampMixin):
    __tablename__ = "soil_assessment_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Soil assessment")
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_soil_assessment_status"
        ),
        Index(
            "uq_soil_assessment_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_soil_assessments_field", "field_id"),
    )


# ---------------------------------------------------------------------------
# M6C — field management (migration 0008_field_management)
# ---------------------------------------------------------------------------


class PracticeDefinition(Base, TimestampMixin):
    __tablename__ = "practice_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    practice_code: Mapped[str] = mapped_column(String(80), nullable=False)
    practice_family: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "practice_family IN ('cover_crop','residue','tillage','soil_cover',"
            "'erosion_control','traffic','termination')",
            name="ck_practice_family",
        ),
        CheckConstraint(
            "validation_status IN ('reference','locally_validated','confirmed_regional','retired')",
            name="ck_practice_validation",
        ),
        CheckConstraint("status IN ('active','draft','retired')", name="ck_practice_status"),
        UniqueConstraint("pack_id", "practice_code", name="uq_practice_code_per_pack"),
        Index("ix_practice_defs_code", "practice_code"),
    )


class OperationTemplate(Base, TimestampMixin):
    __tablename__ = "operation_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False
    )
    template_code: Mapped[str] = mapped_column(String(80), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("pack_id", "template_code", name="uq_operation_template_code"),
        Index("ix_operation_templates_type", "operation_type"),
    )


class SoilCoverObservation(Base, TimestampMixin):
    __tablename__ = "soil_cover_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    cover_state: Mapped[str] = mapped_column(String(40), nullable=False)
    cover_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_basis: Mapped[str] = mapped_column(String(40), nullable=False, default="visual_estimate")
    index_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    index_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "cover_state IN ('living_main_crop','living_cover_crop','surface_residue','mulch',"
            "'bare','unknown','mixed')",
            name="ck_cover_obs_state",
        ),
        CheckConstraint(
            "cover_fraction IS NULL OR (cover_fraction >= 0 AND cover_fraction <= 1)",
            name="ck_cover_obs_fraction_range",
        ),
        CheckConstraint(
            "measurement_basis IN ('visual_estimate','line_point_transect','canopy_scope',"
            "'quadrat','remote_sensing_index','unknown')",
            name="ck_cover_obs_basis",
        ),
        Index("ix_cover_obs_field_date", "field_id", "observed_date"),
    )


class CoverCropPlan(Base, TimestampMixin):
    __tablename__ = "cover_crop_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Cover-crop plan")
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_crop_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    knowledge_pack_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    feature_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    water_plan_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_cover_plan_status"
        ),
        Index(
            "uq_cover_plan_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_cover_crop_plans_field", "field_id"),
    )


class CoverCropPlanItem(Base, TimestampMixin):
    __tablename__ = "cover_crop_plan_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    plan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cover_crop_plans.id", ondelete="SET NULL"), nullable=True
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="SET NULL"), nullable=True
    )
    crop_label: Mapped[str] = mapped_column(String(160), nullable=False)
    is_mixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mixture_composition: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    season_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    intended_sowing_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    intended_sowing_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    intended_termination_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    intended_termination_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    intended_termination_method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    intended_functions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    seeding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    seeding_rate_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    evidence_class: Mapped[str] = mapped_column(
        String(60), nullable=False, default="farmer_reported_record"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("seeding_rate IS NULL OR seeding_rate >= 0", name="ck_cover_item_rate"),
        CheckConstraint(
            "status IN ('planned','established','terminated','abandoned','cancelled')",
            name="ck_cover_item_status",
        ),
        Index("ix_cover_items_field", "field_id", "season_label"),
    )


class ResidueRecord(Base, TimestampMixin):
    __tablename__ = "residue_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crops.id", ondelete="SET NULL"), nullable=True
    )
    crop_label: Mapped[str] = mapped_column(String(160), nullable=False)
    season_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    basis: Mapped[str] = mapped_column(String(20), nullable=False, default="dry_matter")
    produced_dm_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    production_status: Mapped[str] = mapped_column(String(30), nullable=False)
    coefficient_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    harvested_product_dm_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    harvested_product_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "basis IN ('dry_matter','fresh_weight')", name="ck_residue_basis"
        ),
        CheckConstraint(
            "produced_dm_kg IS NULL OR produced_dm_kg >= 0", name="ck_residue_produced_nonneg"
        ),
        CheckConstraint(
            "production_status IN ('measured','farmer_reported','coefficient_estimate','missing')",
            name="ck_residue_production_status",
        ),
        Index("ix_residue_records_field", "field_id", "season_label"),
    )


class ResidueFlowEvent(Base, TimestampMixin):
    __tablename__ = "residue_flow_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    residue_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("residue_records.id", ondelete="CASCADE"), nullable=False
    )
    flow_type: Mapped[str] = mapped_column(String(30), nullable=False)
    flow_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dm_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    dm_kg_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    # Logical reference to soil_management_events.id — intentionally no FK constraint.
    soil_management_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    evidence_class: Mapped[str] = mapped_column(
        String(60), nullable=False, default="farmer_reported_record"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "flow_type IN ('retained_surface','incorporated','removed_baled','grazed',"
            "'burned','other_loss','unknown')",
            name="ck_residue_flow_type",
        ),
        CheckConstraint("dm_kg IS NULL OR dm_kg >= 0", name="ck_residue_flow_nonneg"),
        CheckConstraint(
            "dm_kg_status IN ('measured','farmer_reported','estimated','unknown')",
            name="ck_residue_flow_dm_status",
        ),
        Index("ix_residue_flows_record", "residue_record_id"),
    )


class ResidueQualityMeasurement(Base, TimestampMixin):
    __tablename__ = "residue_quality_measurements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    residue_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("residue_records.id", ondelete="CASCADE"), nullable=False
    )
    measured_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    carbon_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    nitrogen_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cn_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    lignin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_class: Mapped[str] = mapped_column(String(60), nullable=False, default="laboratory_measured")
    method_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_residue_quality_record", "residue_record_id"),)


class ErosionAssessmentRun(Base, TimestampMixin):
    __tablename__ = "erosion_assessment_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Erosion assessment")
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    knowledge_pack_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_erosion_run_status"
        ),
        Index(
            "uq_erosion_run_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_erosion_runs_field", "field_id"),
    )


class FarmResource(Base, TimestampMixin):
    __tablename__ = "farm_resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    capacity_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    working_width_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability_calendar: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('tractor','implement','seeder','sprayer','harvester','baler',"
            "'irrigation_equipment','contractor','labor_crew','storage','transport','other')",
            name="ck_farm_resource_type",
        ),
        CheckConstraint(
            "field_efficiency IS NULL OR (field_efficiency > 0 AND field_efficiency <= 1)",
            name="ck_farm_resource_efficiency",
        ),
        Index("ix_farm_resources_farm", "farm_id"),
    )


class FieldOperation(Base, TimestampMixin):
    __tablename__ = "field_operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    template_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    operation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    crop_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    season_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Logical references — intentionally no FK constraints.
    cover_crop_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    earliest_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_basis: Mapped[str | None] = mapped_column(String(40), nullable=True)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    resource_requirements: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    restrictions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    scheduled_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    scheduled_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_resource_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    schedule_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_soil_management_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "duration_estimate_hours IS NULL OR duration_estimate_hours >= 0",
            name="ck_field_operation_duration",
        ),
        CheckConstraint("priority >= 1 AND priority <= 5", name="ck_field_operation_priority"),
        CheckConstraint(
            "status IN ('planned','scheduled','started','completed','delayed','cancelled','blocked')",
            name="ck_field_operation_status",
        ),
        Index("ix_field_operations_field", "field_id", "earliest_start"),
        Index("ix_field_operations_status", "field_id", "status"),
    )


class OperationDependency(Base, TimestampMixin):
    __tablename__ = "operation_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_operations.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_operations.id", ondelete="CASCADE"), nullable=False
    )
    dependency_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="finish_to_start"
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "dependency_type IN ('finish_to_start','start_to_start','finish_to_finish')",
            name="ck_operation_dependency_type",
        ),
        CheckConstraint("operation_id != depends_on_operation_id", name="ck_operation_dependency_self"),
        UniqueConstraint("operation_id", "depends_on_operation_id", name="uq_operation_dependency_edge"),
        Index("ix_operation_deps_operation", "operation_id"),
    )


class OperationScheduleRun(Base, TimestampMixin):
    __tablename__ = "operation_schedule_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Operations schedule")
    horizon_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed','infeasible')",
            name="ck_schedule_run_status",
        ),
        Index(
            "uq_schedule_run_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_schedule_runs_field", "field_id"),
    )


class ManagementPlan(Base, TimestampMixin):
    __tablename__ = "management_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="Management plan")
    season_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    methods_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    knowledge_pack_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    cover_crop_plan_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    erosion_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    schedule_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    water_plan_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    feature_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_mgmt_plan_status"
        ),
        Index(
            "uq_mgmt_plan_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_management_plans_field", "field_id"),
    )


class ManagementPlanFeedback(Base, TimestampMixin):
    __tablename__ = "management_plan_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    management_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("management_plans.id", ondelete="CASCADE"), nullable=False
    )
    author_role: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "author_role IN ('farmer','agronomist','other')", name="ck_plan_feedback_role"
        ),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_plan_feedback_rating"
        ),
        Index("ix_plan_feedback_plan", "management_plan_id"),
    )


# ---------------------------------------------------------------------------
# M7.3 — scenario execution (migration 0009_scenario_execution)
# ---------------------------------------------------------------------------


class ScenarioExecutionRun(Base, TimestampMixin):
    __tablename__ = "scenario_execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_field_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_states.id", ondelete="RESTRICT"), nullable=False
    )
    parent_snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_configuration_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    transformation_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_catalog_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_observation_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    source_observation_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    aggregation_levels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    hemisphere: Mapped[str] = mapped_column(String(10), nullable=False, default="north")
    calendar_timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="UTC")
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transformed_observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    derived_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated_reasons: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resource_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "run_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_scenario_execution_status",
        ),
        CheckConstraint(
            "run_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_scenario_execution_checksum_on_success",
        ),
        Index("uq_scenario_execution_fingerprint", "scenario_id", "input_fingerprint", unique=True),
        Index(
            "uq_scenario_execution_idempotency",
            "scenario_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_scenario_executions_scenario", "scenario_id"),
        Index("ix_scenario_executions_field", "field_id"),
    )


class ScenarioDerivedObservation(Base):
    __tablename__ = "scenario_derived_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    execution_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_execution_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Logical references — intentionally no FK constraints.
    source_observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dataset_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    variable_code: Mapped[str] = mapped_column(String(80), nullable=False)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    transformed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_support: Mapped[str] = mapped_column(String(20), nullable=False)
    spatial_support_type: Mapped[str] = mapped_column(String(30), nullable=False)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    transformation_code: Mapped[str] = mapped_column(String(40), nullable=False)
    transformation_parameter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    evidence_class: Mapped[str] = mapped_column(String(40), nullable=False)
    source_evidence_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid")
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "evidence_class IN ('scenario_derived_transformed','synthetic_test')",
            name="ck_scenario_derived_obs_evidence",
        ),
        Index("ix_scenario_derived_obs_run", "execution_run_id"),
        Index("ix_scenario_derived_obs_source", "source_observation_id"),
    )


class ScenarioDerivedFeature(Base):
    __tablename__ = "scenario_derived_features"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    execution_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_execution_runs.id", ondelete="CASCADE"), nullable=False
    )
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_specification_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(30), nullable=False)
    quality_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_missing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uncertainty_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "evidence_status IN ('scenario_recalculated','not_affected','not_evaluated')",
            name="ck_scenario_derived_feature_evidence",
        ),
        Index("ix_scenario_derived_features_run", "execution_run_id"),
        Index("ix_scenario_derived_features_code", "execution_run_id", "feature_code"),
    )


# ---------------------------------------------------------------------------
# M7.4 — sensitivity analysis (migration 0010_sensitivity_analysis)
# ---------------------------------------------------------------------------


class SensitivityAnalysis(Base, TimestampMixin):
    __tablename__ = "sensitivity_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    source_execution_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_execution_runs.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_field_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_states.id", ondelete="RESTRICT"), nullable=False
    )
    parent_snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_configuration_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_observation_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_output_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_parameter_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    explorable_parameters: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    parameter_design: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    grid_design: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    analysis_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    analysis_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_method_version: Mapped[str] = mapped_column(String(40), nullable=False)
    response_classification_version: Mapped[str] = mapped_column(String(40), nullable=False)
    uncertainty_registry_version: Mapped[str] = mapped_column(String(40), nullable=False)
    transformation_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_catalog_version: Mapped[str] = mapped_column(String(40), nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    reference_reproduction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_analysed_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "analysis_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_sensitivity_analysis_status",
        ),
        CheckConstraint(
            "analysis_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_sensitivity_analysis_checksum_on_success",
        ),
        Index(
            "uq_sensitivity_analysis_fingerprint",
            "source_execution_run_id",
            "analysis_fingerprint",
            unique=True,
        ),
        Index(
            "uq_sensitivity_analysis_idempotency",
            "source_execution_run_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_sensitivity_analyses_run", "source_execution_run_id"),
        Index("ix_sensitivity_analyses_field", "field_id"),
        Index("ix_sensitivity_analyses_scenario", "scenario_id"),
    )


class SensitivityEvaluation(Base):
    __tablename__ = "sensitivity_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="oat")
    roles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temperature_delta_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    transformed_observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    derived_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "evaluation_kind IN ('reference','oat','grid')", name="ck_sensitivity_evaluation_kind"
        ),
        CheckConstraint(
            "evaluation_status IN ('succeeded','failed')",
            name="ck_sensitivity_evaluation_status",
        ),
        UniqueConstraint(
            "analysis_id",
            "temperature_delta_c",
            "precipitation_multiplier",
            name="uq_sensitivity_evaluation_tuple",
        ),
        Index("ix_sensitivity_evaluations_analysis", "analysis_id"),
    )


class SensitivityFeatureValue(Base):
    __tablename__ = "sensitivity_feature_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_from_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_sensitivity_feature_values_analysis", "analysis_id"),
        Index("ix_sensitivity_feature_values_eval", "evaluation_id", "feature_code"),
    )


class SensitivityOatResponse(Base):
    __tablename__ = "sensitivity_oat_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    parameter_code: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_evaluated: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_evaluated: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_range: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_difference: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_at_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference_at_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    slope_method: Mapped[str] = mapped_column(String(30), nullable=False, default="not_evaluated")
    slope_units: Mapped[str] = mapped_column(String(60), nullable=False)
    slope_validity: Mapped[str] = mapped_column(String(60), nullable=False, default="valid")
    elasticity: Mapped[float | None] = mapped_column(Float, nullable=True)
    elasticity_status: Mapped[str] = mapped_column(String(40), nullable=False)
    elasticity_unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction: Mapped[str] = mapped_column(String(30), nullable=False)
    response_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    classification_version: Mapped[str] = mapped_column(String(40), nullable=False)
    n_evaluated_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "parameter_code IN ('temperature_delta_c','precipitation_multiplier')",
            name="ck_sensitivity_oat_parameter",
        ),
        CheckConstraint(
            "slope_method IN ('central','forward_one_sided','backward_one_sided','not_evaluated')",
            name="ck_sensitivity_oat_slope_method",
        ),
        CheckConstraint(
            "direction IN ('increasing','decreasing','no_change','not_evaluated')",
            name="ck_sensitivity_oat_direction",
        ),
        CheckConstraint(
            "response_status IN ('evaluated','partially_evaluated','not_evaluated')",
            name="ck_sensitivity_oat_response_status",
        ),
        Index(
            "ix_sensitivity_oat_analysis",
            "analysis_id",
            "parameter_code",
            "feature_code",
            "aggregation_level",
            "period_label",
        ),
    )


class SensitivityGridCell(Base):
    __tablename__ = "sensitivity_grid_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    temperature_delta_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    cell_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "feature_code",
            "aggregation_level",
            "period_label",
            "temperature_delta_c",
            "precipitation_multiplier",
            name="uq_sensitivity_grid_cell",
        ),
        Index("ix_sensitivity_grid_cells_analysis", "analysis_id"),
    )


class SensitivityGridSummary(Base):
    __tablename__ = "sensitivity_grid_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    feature_code: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    aggregation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    grid_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_output_range: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(30), nullable=False)
    non_monotonic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    threshold_transition_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interaction_contrast: Mapped[float | None] = mapped_column(Float, nullable=True)
    interaction_interpretation: Mapped[str] = mapped_column(String(40), nullable=False)
    variable_families: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "direction IN ('increasing','decreasing','no_change','not_evaluated')",
            name="ck_sensitivity_grid_direction",
        ),
        CheckConstraint(
            "interaction_interpretation IN ('approximately_additive',"
            "'super_additive_over_explored_grid','sub_additive_over_explored_grid','not_evaluated')",
            name="ck_sensitivity_grid_interaction",
        ),
        Index("ix_sensitivity_grid_summaries_analysis", "analysis_id"),
    )


class SensitivityUncertaintyItem(Base):
    __tablename__ = "sensitivity_uncertainty_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(200), nullable=False)
    quantification_status: Mapped[str] = mapped_column(String(30), nullable=False)
    quantification_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantified_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    affects_current_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    affected_inputs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    affected_features: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    applicability: Mapped[str] = mapped_column(String(20), nullable=False)
    user_facing_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    registry_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('parameter_range_uncertainty','observation_data_quality',"
            "'spatial_coverage_limitation','temporal_resolution_limitation',"
            "'model_structural_limitation','feature_method_limitation',"
            "'regional_agronomic_uncertainty')",
            name="ck_sensitivity_uncertainty_category",
        ),
        CheckConstraint(
            "quantification_status IN ('quantified','bounded_exploratory','qualitative_only',"
            "'not_quantified','not_applicable','not_evaluated')",
            name="ck_sensitivity_uncertainty_status",
        ),
        CheckConstraint(
            "applicability IN ('direct','contextual','peripheral')",
            name="ck_sensitivity_uncertainty_applicability",
        ),
        Index("ix_sensitivity_uncertainty_analysis", "analysis_id", "category"),
    )


# ---------------------------------------------------------------------------
# M7.5 — robust rotation (migration 0011_robust_rotation)
# ---------------------------------------------------------------------------


class ScenarioSet(Base, TimestampMixin):
    __tablename__ = "scenario_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_field_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_states.id", ondelete="RESTRICT"), nullable=False
    )
    parent_snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    members: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    compatibility_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    set_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("member_count >= 1", name="ck_scenario_set_member_count"),
        CheckConstraint("status IN ('active')", name="ck_scenario_set_status"),
        UniqueConstraint("field_id", "set_checksum", name="uq_scenario_set_content"),
        Index(
            "uq_scenario_set_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_scenario_sets_field", "field_id"),
    )


class RobustRotationRun(Base, TimestampMixin):
    __tablename__ = "robust_rotation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    scenario_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_sets.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_set_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    member_pins: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    seasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    strategy_profiles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    custom_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    regret_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    run_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rotation_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    robust_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    robust_method_version: Mapped[str] = mapped_column(String(40), nullable=False)
    solver_name: Mapped[str] = mapped_column(String(60), nullable=False, default="cp-sat")
    solver_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    solver_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    knowledge_pack_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    feature_run_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    infeasibility_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    solver_diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "run_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_robust_rotation_run_status",
        ),
        CheckConstraint(
            "solver_status IS NULL OR solver_status IN ('optimal','feasible','infeasible',"
            "'unknown','model_invalid','not_attempted')",
            name="ck_robust_rotation_solver_status",
        ),
        CheckConstraint(
            "run_status NOT IN ('succeeded','completed_with_limitations') OR output_checksum IS NOT NULL",
            name="ck_robust_rotation_checksum_on_success",
        ),
        UniqueConstraint("scenario_set_id", "run_fingerprint", name="uq_robust_run_fingerprint"),
        Index(
            "uq_robust_run_idempotency",
            "scenario_set_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_robust_runs_set", "scenario_set_id"),
        Index("ix_robust_runs_field", "field_id"),
    )


class RobustRotationStrategy(Base, TimestampMixin):
    __tablename__ = "robust_rotation_strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("robust_rotation_runs.id", ondelete="CASCADE"), nullable=False
    )
    strategy_key: Mapped[str] = mapped_column(String(60), nullable=False)
    strategy_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="optimized")
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profile_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assignment: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    worst_case_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    worst_case_regret: Mapped[float | None] = mapped_column(Float, nullable=True)
    robust_feasibility: Mapped[str] = mapped_column(String(30), nullable=False)
    objective_evaluable_in_all_scenarios: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    solver_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    solver_wall_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "strategy_kind IN ('optimized','baseline')", name="ck_robust_strategy_kind"
        ),
        CheckConstraint(
            "robust_feasibility IN ('robust_feasible','robust_infeasible','not_evaluable')",
            name="ck_robust_strategy_feasibility",
        ),
        UniqueConstraint("run_id", "strategy_key", name="uq_robust_strategy_key"),
        Index("ix_robust_strategies_run", "run_id"),
    )


class RobustScenarioEvaluation(Base):
    __tablename__ = "robust_scenario_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("robust_rotation_runs.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("robust_rotation_strategies.id", ondelete="CASCADE"), nullable=False
    )
    # Logical reference to scenarios.id — intentionally no FK constraint.
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_execution_runs.id", ondelete="RESTRICT"), nullable=False
    )
    output_checksum_pin: Mapped[str] = mapped_column(String(64), nullable=False)
    weighted_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    objective_evaluable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    on_scenario_pareto_front: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    regret_vs_solo: Mapped[float | None] = mapped_column(Float, nullable=True)
    criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    constraint_checks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    crop_admissibility: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    climate_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("strategy_id", "scenario_id", name="uq_robust_eval_strategy_scenario"),
        Index("ix_robust_evals_run", "run_id"),
        Index("ix_robust_evals_scenario", "run_id", "scenario_id"),
    )


# ---------------------------------------------------------------------------
# M7.6 — decision comparisons (migration 0012_decision_comparisons)
# ---------------------------------------------------------------------------


class DecisionComparison(Base, TimestampMixin):
    __tablename__ = "decision_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_available: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    generator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    method_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "doc_status IN ('queued','running','succeeded','completed_with_limitations','failed')",
            name="ck_decision_comparison_status",
        ),
        CheckConstraint(
            "doc_status NOT IN ('succeeded','completed_with_limitations') OR document_checksum IS NOT NULL",
            name="ck_decision_comparison_checksum_on_success",
        ),
        UniqueConstraint("field_id", "fingerprint", name="uq_decision_comparison_fingerprint"),
        Index(
            "uq_decision_comparison_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_decision_comparisons_field", "field_id"),
    )


# ---------------------------------------------------------------------------
# M7.7 — digital twin (migration 0013_digital_twin)
# ---------------------------------------------------------------------------


class DigitalTwinValidation(Base, TimestampMixin):
    __tablename__ = "digital_twin_validations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    overall_status: Mapped[str] = mapped_column(String(20), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    artifacts_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifacts_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "overall_status IN ('consistent','inconsistent','no_artifacts')",
            name="ck_digital_twin_validation_status",
        ),
        Index(
            "uq_digital_twin_validation_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
        Index("ix_digital_twin_validations_field", "field_id"),
    )

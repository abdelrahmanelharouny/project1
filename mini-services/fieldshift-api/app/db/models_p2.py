"""ORM models for the P2 advanced agricultural intelligence expansion.

P2 workstreams (conventions mirror app/db/models.py, models_m6bc_m7.py and
models_ai.py: UUID PKs, TimestampMixin for mutable tables, JSONB with python
defaults, additive-only migrations):

- `satellite_scenes` (A) — scene-level provenance for satellite imagery used
  by vegetation intelligence. One row per (field, provider, scene); index
  values themselves live in `observations` (variable codes ndvi/evi/...,
  evidence_class=satellite_derived_estimate) so the platform has exactly one
  observation store.
- `weather_forecasts` (B) — forecast evidence. Deliberately NOT in
  `observations`: forecasts are issued estimates with issue time + valid time
  + horizon, and mixing them with historical observations would overwrite the
  observed record. One row per (field, provider, model, variable, issue,
  valid, horizon); immutable once written.
- `forecast_verifications` (B) — aggregate forecast-vs-observation verification
  (bias/MAE/RMSE) per horizon bucket; only written when paired data exists.
- `climate_projection_records` (B) — long-term projections preserving model id,
  scenario id, ensemble size, bias-correction status and uncertainty bands.
  Never treated as deterministic future weather.
- `soil_state_snapshots` (C) — immutable, checksummed longitudinal soil state
  (measured + estimated variables at depths, with per-value evidence class).
- `soil_change_estimates` (C) — conservative modeled change between two
  snapshots (mass-balance / trajectory), carrying assumptions + model version;
  estimated, never presented as measured improvement.
- `rotation_stress_runs` (D) — Rotation Failure Lab executions: candidate
  rotations × stress packs, robustness metrics, constraint violations,
  reproducible via pinned inputs + checksum.
- `evidence_gap_reports` (E) — append-only snapshots of detected evidence gaps
  with importance and decision impact.
- `evidence_acquisition_actions` / `evidence_acquisition_events` (E) —
  lifecycle of evidence acquisition suggestions (append-only event history).
- `portfolio_runs` / `portfolio_allocations` (F) — farm-level CP-SAT portfolio
  optimization: per-field × season × crop area allocation under shared
  resource constraints, with explicit trade-offs vs independent field plans.

Tenant isolation follows the existing pattern: rows are scoped through
field_id / farm_id and the API layer resolves field → farm → organization via
`get_field_for_principal` / `get_farm_for_principal`. No org_id column on
domain tables (consistent with soil/water/scenario tables).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text as text_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, TimestampMixin, _uuid

__all__ = [
    "SatelliteScene",
    "WeatherForecast",
    "ForecastVerification",
    "ClimateProjectionRecord",
    "SoilStateSnapshot",
    "SoilChangeEstimate",
    "RotationStressRun",
    "EvidenceGapReport",
    "EvidenceAcquisitionAction",
    "EvidenceAcquisitionEvent",
    "PortfolioRun",
    "PortfolioAllocation",
]

RUN_STATUSES = ("running", "succeeded", "failed")


class SatelliteScene(Base):
    """One satellite scene intersecting a field (P2.A provenance layer).

    Written by the ingestion service when a satellite provider returns
    observations; index values live in `observations`. Idempotent per
    (field_id, provider_code, scene_id) so re-ingestion updates nothing and
    duplicates nothing.

    P04 acquisition lifecycle (nullable for legacy P2 rows, which were always
    ingested-on-arrival and are displayed as 'ready' via COALESCE):
    - acquisition_status: discovered | queued | running | ready | failed
      (NULL = already ingested by the pre-P04 path).
    - acquisition_detail: JSONB {job_id, error/reason, cancelled, ...}.
    - discovered_at / acquisition_updated_at: lifecycle timestamps.
    """

    __tablename__ = "satellite_scenes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    band_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    asset_refs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    coverage_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    processing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    # P04 acquisition lifecycle (see class docstring).
    acquisition_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    acquisition_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquisition_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "cloud_cover_pct IS NULL OR (cloud_cover_pct >= 0 AND cloud_cover_pct <= 100)",
            name="ck_satellite_scene_cloud_range",
        ),
        CheckConstraint(
            "acquisition_status IS NULL OR acquisition_status IN "
            "('discovered','queued','running','ready','failed')",
            name="ck_satellite_scene_acquisition_status",
        ),
        Index(
            "uq_satellite_scene_natural_key",
            "field_id",
            "provider_code",
            "scene_id",
            unique=True,
        ),
        Index("ix_satellite_scenes_field_acquired", "field_id", "acquired_at"),
        Index(
            "ix_satellite_scenes_field_status",
            "field_id",
            "acquisition_status",
            postgresql_where=text_("acquisition_status IS NOT NULL"),
        ),
    )


class WeatherForecast(Base, TimestampMixin):
    """One forecast value (P2.B). Immutable evidence; new issues append rows.

    Issue/valid time separation is the core honesty rule: a forecast is an
    ESTIMATE issued at `issued_at` for `valid_time` with `horizon_hours`.
    Historical observations are never overwritten or blended with these rows.
    """

    __tablename__ = "weather_forecasts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ensemble_member: Mapped[str | None] = mapped_column(String(48), nullable=True)
    variable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="valid")
    quality_flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    processing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "horizon_hours >= 0",
            name="ck_weather_forecast_horizon_nonneg",
        ),
        Index(
            "uq_weather_forecast_natural_key",
            "field_id",
            "provider_code",
            "variable_code",
            "issued_at",
            "valid_time",
            "horizon_hours",
            unique=True,
        ),
        Index("ix_weather_forecasts_field_valid", "field_id", "variable_code", "valid_time"),
    )


class ForecastVerification(Base, TimestampMixin):
    """Aggregate forecast verification (P2.B): archived forecasts vs later
    observations. Written ONLY when paired forecast-observation data exists —
    never fabricated. Aggregate-level (per horizon bucket), checksummed."""

    __tablename__ = "forecast_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    variable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_bucket_hours: Mapped[str] = mapped_column(String(24), nullable=False)
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(48), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint("pair_count > 0", name="ck_forecast_verification_pair_count"),
        Index(
            "uq_forecast_verification_key",
            "field_id",
            "provider_code",
            "variable_code",
            "horizon_bucket_hours",
            "window_start",
            "window_end",
            unique=True,
        ),
    )


class ClimateProjectionRecord(Base, TimestampMixin):
    """One long-term climate projection value (P2.B).

    Scenario identity (SSP), model id, ensemble size, bias-correction status
    and uncertainty bands are mandatory provenance. Projections are never
    presented as deterministic future weather and are stored separately from
    both observations and forecasts.
    """

    __tablename__ = "climate_projection_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    source_product: Mapped[str | None] = mapped_column(String(96), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    ensemble_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bias_correction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    variable_code: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_period: Mapped[str | None] = mapped_column(String(48), nullable=True)
    statistic: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    processing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_climate_projection_natural_key",
            "field_id",
            "provider_code",
            "variable_code",
            "scenario_id",
            "model_id",
            "statistic",
            "period_start",
            "period_end",
            unique=True,
        ),
        Index("ix_climate_projections_field", "field_id"),
    )


class SoilStateSnapshot(Base):
    """Immutable longitudinal soil state (P2.C).

    `snapshot` holds per-variable entries: {code, depth_top_cm, depth_bottom_cm,
    value, unit, evidence_class, source_kind, source_ref, observed_at} —
    measured and estimated values keep their evidence classes side by side,
    never merged. Checksum makes ingestion idempotent; rows are never updated.
    """

    __tablename__ = "soil_state_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    missing_evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_soil_snapshot_checksum",
            "field_id",
            "checksum_sha256",
            unique=True,
        ),
        Index("ix_soil_snapshots_field_asof", "field_id", "as_of"),
    )


class SoilChangeEstimate(Base):
    """Conservative modeled soil change between two snapshots (P2.C).

    Every row records the method, model version, explicit assumptions and
    uncertainty. Results are ESTIMATES (labelled as such end to end) — the
    platform never implies measured field improvement from modeled deltas.
    """

    __tablename__ = "soil_change_estimates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    start_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_state_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    end_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soil_state_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    uncertainty: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_soil_change_estimate_key",
            "field_id",
            "start_snapshot_id",
            "end_snapshot_id",
            "method",
            "checksum_sha256",
            unique=True,
        ),
    )


class RotationStressRun(Base, TimestampMixin):
    """Rotation Failure Lab run (P2.D).

    Deterministic stress-testing of candidate rotations under named stress
    packs. Inputs are pinned in `request_parameters` (packs, candidates,
    strategy profiles, water allocation, seeds, engine versions); `result`
    holds per-candidate per-pack evaluations, robustness metrics, constraint
    violations and failure explanations. Reproducible: identical inputs and
    engine versions reproduce `checksum_sha256` byte-for-byte.
    """

    __tablename__ = "rotation_stress_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    candidates: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    packs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running','succeeded','failed')", name="ck_stress_run_status"),
        Index(
            "uq_rotation_stress_run_idempotency",
            "field_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
    )


class EvidenceGapReport(Base):
    """Append-only snapshot of detected evidence gaps (P2.E). Regeneration
    inserts a new row; history is preserved for acquisition analytics."""

    __tablename__ = "evidence_gap_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    gaps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    completeness: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_evidence_gap_reports_field", "field_id", "created_at"),
    )


class EvidenceAcquisitionAction(Base, TimestampMixin):
    """One evidence acquisition suggestion and its lifecycle state (P2.E)."""

    __tablename__ = "evidence_acquisition_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    gap_code: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="suggested")
    submitted_ref_kind: Mapped[str | None] = mapped_column(String(48), nullable=True)
    submitted_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested','in_progress','submitted','resolved','dismissed')",
            name="ck_evidence_action_status",
        ),
        Index("ix_evidence_actions_field_status", "field_id", "status"),
    )


class EvidenceAcquisitionEvent(Base):
    """Append-only lifecycle event for an acquisition action (P2.E)."""

    __tablename__ = "evidence_acquisition_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_acquisition_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_evidence_action_events_action", "action_id", "created_at"),
    )


class PortfolioRun(Base, TimestampMixin):
    """Farm-level portfolio optimization run (P2.F).

    CP-SAT area allocation across the farm's fields under SHARED resource
    constraints (water, labor, machinery) with explicit objective weights.
    `result` carries per-criterion scores, binding constraints, the
    comparison against independent per-field plans and the trade-off report.
    Deterministic: solver workers=1, fixed seed, checksum over pinned inputs.
    """

    __tablename__ = "portfolio_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    field_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    objective_weights: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    scenario: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    solver_diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    not_evaluated: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running','succeeded','failed')", name="ck_portfolio_run_status"),
        Index(
            "uq_portfolio_run_idempotency",
            "farm_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text_("idempotency_key IS NOT NULL"),
        ),
    )


class PortfolioAllocation(Base):
    """Per field × season × crop allocated area of a portfolio run (P2.F).

    area_ha is NUMERIC(10,2) — hectares at 0.01 ha granularity, matching the
    integer-scaled CP-SAT variables. Rows are written once per run (immutable
    result); run rows are never rewritten.
    """

    __tablename__ = "portfolio_allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    season_label: Mapped[str] = mapped_column(String(48), nullable=False)
    season_index: Mapped[int] = mapped_column(Integer, nullable=False)
    crop_code: Mapped[str] = mapped_column(String(64), nullable=False)
    area_ha: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    family_key: Mapped[str | None] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="assigned")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("area_ha >= 0", name="ck_portfolio_allocation_area_nonneg"),
        Index(
            "uq_portfolio_allocation_key",
            "run_id",
            "field_id",
            "season_index",
            "crop_code",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# P05 — geospatial derived products (storage + processing)
# ---------------------------------------------------------------------------
RASTER_ASSET_KINDS = ("source", "derived", "preview")
RASTER_ASSET_BACKENDS = ("local", "s3")
PROCESSING_JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class RasterAsset(Base, TimestampMixin):
    """Metadata for a raster asset stored OUTSIDE PostgreSQL (P05).

    Binary raster content (COGs, preview PNGs) lives in the object store
    (local disk in development, S3-compatible storage in production). This
    table stores only references, checksums, searchable metadata and
    provenance — never raster bytes.

    Honesty rules:
    - `asset_kind="source"` rows point at ORIGINAL NASA scenes (or references
      to them); `asset_kind="derived"` rows point at CropTwist-computed
      index products. The two are never mixed under one identity.
    - No metadata value is invented: fields a source does not provide stay
      NULL.
    - Natural key (field_id, scene_id, index_code, processing_version,
      asset_name, asset_kind) makes reprocessing idempotent — a repeated
      processing run for the same scene/product/version updates nothing.
    """

    __tablename__ = "raster_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    crs: Mapped[str | None] = mapped_column(String(80), nullable=True)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        "bbox", JSONB, nullable=True
    )  # [minx, miny, maxx, maxy] in the asset CRS
    transform_json: Mapped[dict[str, Any] | None] = mapped_column(
        "transform", JSONB, nullable=True
    )  # GDAL-style 6-tuple affine
    valid_pixel_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column("stats", JSONB, nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(
        "provenance", JSONB, nullable=True
    )
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "asset_kind IN ('source','derived','preview')",
            name="ck_raster_asset_kind",
        ),
        CheckConstraint(
            "storage_backend IN ('local','s3')",
            name="ck_raster_asset_backend",
        ),
        CheckConstraint("byte_size >= 0", name="ck_raster_asset_size_nonneg"),
        CheckConstraint(
            "valid_pixel_fraction IS NULL OR (valid_pixel_fraction >= 0 AND "
            "valid_pixel_fraction <= 1)",
            name="ck_raster_asset_valid_fraction_range",
        ),
        Index(
            "uq_raster_asset_natural_key",
            "field_id",
            "asset_kind",
            "scene_id",
            "index_code",
            "processing_version",
            "asset_name",
            unique=True,
        ),
        Index("ix_raster_assets_field_index", "field_id", "index_code", "acquired_at"),
        Index("ix_raster_assets_field_scene", "field_id", "scene_id"),
    )


class RasterProcessingJob(Base, TimestampMixin):
    """Domain row for one satellite preprocessing job (P05).

    Companion to a `background_jobs` row (kind='raster_processing'). The
    BackgroundJob carries queue state; this row carries the processing
    request (scene, indices, processing version), per-scene progress and
    failure details so workers and the API can rebuild inputs without
    keeping callables in memory.

    Idempotency: at most one active (queued|running) job per
    (scene_id, processing_version, indices_digest) — enforced with a partial
    unique index. Re-submission while an equivalent job is active replays the
    SAME job instead of duplicating work.
    """

    __tablename__ = "raster_processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    indices: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    indices_digest: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_raster_processing_job_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_raster_processing_job_progress_range",
        ),
        Index(
            "uq_raster_processing_active",
            "scene_id",
            "processing_version",
            "indices_digest",
            unique=True,
            postgresql_where=text_("status IN ('queued','running')"),
        ),
        Index(
            "ix_raster_processing_field_scene",
            "field_id",
            "scene_id",
            "status",
        ),
    )


__all__ = [
    "SatelliteScene",
    "WeatherForecast",
    "ForecastVerification",
    "ClimateProjectionRecord",
    "SoilStateSnapshot",
    "SoilChangeEstimate",
    "RotationStressRun",
    "EvidenceGapReport",
    "EvidenceAcquisitionAction",
    "EvidenceAcquisitionEvent",
    "PortfolioRun",
    "PortfolioAllocation",
    "RasterAsset",
    "RasterProcessingJob",
]

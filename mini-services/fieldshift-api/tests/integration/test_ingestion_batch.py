"""Regression coverage for bounded observation persistence batches."""

from datetime import UTC, datetime, timedelta
import uuid

from sqlalchemy import func, select

from app.data_platform.contracts.observations import (
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    SpatialSupportType,
    TimeSupport,
)
from app.data_platform.ingestion.service import _persist_result
from app.data_platform.providers.synthetic.provider import PRODUCT_CODE, PRODUCT_VERSION
from app.db.models import Field, IngestionJob, Observation, ObservationQualityFlag


def _observation(index: int, *, quality_flags: list[dict] | None = None) -> CanonicalObservation:
    observed_at = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return CanonicalObservation(
        variable_code="air_temperature_mean",
        value=20.0 + index,
        unit="degC",
        observed_at=observed_at,
        period_start=observed_at,
        period_end=observed_at + timedelta(days=1),
        time_support=TimeSupport.daily,
        spatial_support_type=SpatialSupportType.field_intersection,
        quality_status=QualityStatus.valid,
        evidence_class=EvidenceClass.synthetic_test_data,
        is_synthetic=True,
        quality_flags=quality_flags or [],
    )


def _result(observations: list[CanonicalObservation], count: int | None = None) -> ProviderFetchResult:
    return ProviderFetchResult.model_construct(
        provider_code="synthetic",
        provenance=SourceProvenance(
            provider_code="synthetic",
            provider_name="Synthetic Fixture",
            product_code=PRODUCT_CODE,
            product_version=PRODUCT_VERSION,
        ),
        observations=observations,
        warnings=[],
        coverage={},
        provider_request_id=None,
        raw_reference=None,
        input_record_count=count,
    )


def _job(db, farm_with_field) -> tuple[IngestionJob, Field]:
    field = db.get(Field, uuid.UUID(farm_with_field["field"]["id"]))
    job = IngestionJob(
        field_id=field.id,
        provider_code="synthetic",
        status="running",
        request_parameters={},
    )
    db.add(job)
    db.flush()
    return job, field


def test_large_valid_input_persists_in_bounded_batches_with_quality_flags(db, farm_with_field):
    job, field = _job(db, farm_with_field)
    observations = [
        _observation(
            index,
            quality_flags=[
                {
                    "flag_code": "BATCH_CHECK",
                    "severity": "info",
                    "message": "retained",
                    "details": {"index": index},
                }
            ],
        )
        for index in range(205)
    ]

    _persist_result(db, job, field=field, result=_result(observations))

    assert job.status == "succeeded"
    assert job.records_received == 205
    assert job.records_rejected == 0
    assert db.scalar(select(func.count()).where(Observation.ingestion_job_id == job.id)) == 205
    assert db.scalar(select(func.count()).select_from(ObservationQualityFlag)) == 205
    rows = db.scalars(
        select(Observation).where(Observation.ingestion_job_id == job.id).order_by(Observation.observed_at)
    ).all()
    assert all(row.evidence_class == "synthetic_test_data" for row in rows)
    assert all(row.quality_flags[0].flag_code == "BATCH_CHECK" for row in rows)


def test_mixed_invalid_and_duplicate_rows_do_not_poison_valid_rows(db, farm_with_field):
    job, field = _job(db, farm_with_field)
    first = _observation(0)
    invalid_missing = first.model_copy(update={"quality_status": QualityStatus.missing, "value": 1.0})
    duplicate = _observation(0)
    bad_flag = _observation(
        1,
        quality_flags=[
            {"flag_code": "BAD_FLAG", "severity": "fatal", "message": "must reject"}
        ],
    )
    last = _observation(2)

    _persist_result(db, job, field=field, result=_result([first, invalid_missing, duplicate, bad_flag, last], 5))

    assert job.status == "succeeded"
    assert job.records_received == 5
    assert job.records_rejected == 3
    assert db.scalar(select(func.count()).where(Observation.ingestion_job_id == job.id)) == 2
    assert db.scalar(select(func.count()).select_from(ObservationQualityFlag)) == 0
    assert len(job.warnings) == 3
    assert "missing rows must not carry a value" in job.warnings[0]
    assert "duplicate or database integrity constraint" in job.warnings[1]
    assert "duplicate or database integrity constraint" in job.warnings[2]

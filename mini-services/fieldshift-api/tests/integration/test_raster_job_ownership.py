"""PostgreSQL checks that raster completion is fenced by persisted ownership."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core import jobs
from app.core.database import SessionLocal
from app.db.models import BackgroundJob
from app.db.models_p2 import RasterProcessingJob
from app.data_platform.processing.service import execute_processing_job


def _field_id(farm_with_field: dict) -> uuid.UUID:
    return uuid.UUID(farm_with_field["field"]["id"])


@pytest.mark.parametrize("lease_expired", [False, True])
def test_stale_raster_executor_cannot_complete_domain_or_background_rows(
    farm_with_field, db, lease_expired: bool
) -> None:
    field_id = _field_id(farm_with_field)
    bg_id = uuid.uuid4()
    current_owner = uuid.uuid4()
    old_owner = uuid.uuid4()
    current_fence = 9
    lease = datetime.now(UTC) - timedelta(seconds=2) if lease_expired else datetime.now(UTC) + timedelta(minutes=2)
    raster_job = RasterProcessingJob(
        field_id=field_id,
        background_job_id=bg_id,
        scene_id=f"ownership-{uuid.uuid4()}",
        product_code="fixture_demo",
        indices=["ndvi"],
        indices_digest="b" * 32,
        processing_version="ownership-test-v1",
        status="queued",
    )
    background_job = BackgroundJob(
        id=bg_id,
        kind="raster_processing",
        status="running",
        ref_kind="raster_processing",
        ref_id=raster_job.id,
        owner_id=current_owner,
        fencing_token=current_fence,
        lease_expires_at=lease,
        progress=45,
    )
    db.add_all([raster_job, background_job])
    db.commit()

    # Simulate a still-computing former executor after ownership changed (or
    # its persisted lease expired). Its callback context cannot impersonate the
    # fresh owner now stored on the background row.
    token = jobs._current_execution.set((bg_id, old_owner, current_fence - 1))
    try:
        execute_processing_job(raster_job.id, progress=None)
    finally:
        jobs._current_execution.reset(token)

    db.refresh(raster_job)
    db.refresh(background_job)
    assert raster_job.status == "queued"
    assert raster_job.finished_at is None
    assert background_job.status == "running"
    assert background_job.owner_id == current_owner
    assert background_job.fencing_token == current_fence


def test_fresh_raster_owner_can_pass_the_database_guard(farm_with_field, db) -> None:
    field_id = _field_id(farm_with_field)
    bg_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    raster_job = RasterProcessingJob(
        field_id=field_id,
        background_job_id=bg_id,
        scene_id=f"ownership-{uuid.uuid4()}",
        product_code="fixture_demo",
        indices=["ndvi"],
        indices_digest="c" * 32,
        processing_version="ownership-test-v1",
        status="queued",
    )
    background_job = BackgroundJob(
        id=bg_id,
        kind="raster_processing",
        status="running",
        ref_kind="raster_processing",
        ref_id=raster_job.id,
        owner_id=owner_id,
        fencing_token=3,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    db.add_all([raster_job, background_job])
    db.commit()

    from app.data_platform.processing.service import _assert_processing_job_owner

    token = jobs._current_execution.set((bg_id, owner_id, 3))
    try:
        with SessionLocal() as owner_db:
            persisted_raster = owner_db.get(RasterProcessingJob, raster_job.id)
            _assert_processing_job_owner(owner_db, persisted_raster)
            owner_db.rollback()
    finally:
        jobs._current_execution.reset(token)

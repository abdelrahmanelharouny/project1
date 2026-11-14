"""Targeted release checks for durable worker dispatch and raster safety."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import jobs
from app.core.config import settings
from app.core.database import SessionLocal
from app.data_platform.processing.service import _safe_processing_error
from app.db.models import BackgroundJob


def _drain_local_wakeups() -> None:
    """Keep direct dispatcher tests from leaking IDs into later tests."""
    while True:
        try:
            item = jobs._queue.get_nowait()
        except jobs.queue.Empty:
            break
        jobs._queue.task_done()
        if item is not None:
            with jobs._queue_lock:
                jobs._queued_ids.discard(item)
    with jobs._queue_lock:
        jobs._queued_ids.clear()
    with jobs._registry_lock:
        jobs._pending_fns.clear()


def test_session_submit_is_atomic_and_wakes_only_after_commit(db):
    """A domain caller cannot publish a queue row before its transaction."""
    executed: list[uuid.UUID] = []
    job = jobs.submit(
        "transactional_test",
        lambda job_id, _progress: executed.append(job_id),
        db=db,
        label="transactional",
    )

    with SessionLocal() as observer:
        assert observer.get(BackgroundJob, job.id) is None
    assert job.id not in jobs._queued_ids

    db.commit()
    with SessionLocal() as observer:
        committed = observer.get(BackgroundJob, job.id)
        assert committed is not None
        assert committed.status == "queued"
    assert job.id in jobs._queued_ids
    assert executed == []
    _drain_local_wakeups()


def test_session_submit_rollback_discards_row_and_wakeup(db):
    """A rolled-back domain transaction leaves no durable or local work."""
    job = jobs.submit(
        "transactional_rollback_test",
        lambda _job_id, _progress: None,
        db=db,
    )
    db.rollback()

    with SessionLocal() as observer:
        assert observer.get(BackgroundJob, job.id) is None
    assert job.id not in jobs._queued_ids
    _drain_local_wakeups()


def test_poll_discovers_committed_row_without_in_process_callback(db):
    """A restart-like process discovers a row created by another process."""
    calls: list[uuid.UUID] = []
    kind = f"poll_restart_{uuid.uuid4().hex}"
    jobs.register_kind(kind, lambda job_id, _progress: calls.append(job_id))

    with SessionLocal() as producer:
        row = BackgroundJob(kind=kind, status="queued")
        producer.add(row)
        producer.commit()
        job_id = row.id

    _drain_local_wakeups()
    jobs._last_poll_at = 0.0
    jobs._poll_queued_jobs()
    assert job_id in jobs._queued_ids

    jobs._run_job(job_id)
    with SessionLocal() as observer:
        final = observer.get(BackgroundJob, job_id)
        assert final is not None
        assert final.status == "succeeded"
        assert final.fencing_token == 1
    assert calls == [job_id]
    _drain_local_wakeups()


def test_concurrent_dispatch_claims_one_fenced_owner(db):
    """Two dispatchers racing on one ID execute once under the advisory fence."""
    started = threading.Event()
    release = threading.Event()
    calls: list[uuid.UUID] = []
    call_lock = threading.Lock()

    def work(job_id, _progress):
        with call_lock:
            calls.append(job_id)
        started.set()
        assert release.wait(timeout=5)

    kind = f"race_{uuid.uuid4().hex}"
    jobs.register_kind(kind, work)
    job = jobs.submit(kind, work)
    _drain_local_wakeups()
    threads = [threading.Thread(target=jobs._run_job, args=(job.id,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=5)
    time.sleep(0.1)
    release.set()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    with SessionLocal() as observer:
        final = observer.get(BackgroundJob, job.id)
        assert final is not None
        assert final.status == "succeeded"
        assert final.fencing_token == 1
    assert calls == [job.id]
    _drain_local_wakeups()


def test_expired_owned_row_fails_closed_and_advances_fence(monkeypatch):
    """Restart recovery never reuses an expired generation without a domain proof."""
    kind = f"stale_{uuid.uuid4().hex}"
    jobs.register_kind(kind, lambda _job_id, _progress: None)
    with SessionLocal() as producer:
        row = BackgroundJob(
            kind=kind,
            status="running",
            owner_id=uuid.uuid4(),
            fencing_token=7,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        producer.add(row)
        producer.commit()
        job_id = row.id

    monkeypatch.setattr(settings, "job_workers", 0)
    jobs._recover_orphans()
    with SessionLocal() as observer:
        recovered = observer.get(BackgroundJob, job_id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.fencing_token == 8
        assert recovered.owner_id is None
        assert recovered.lease_expires_at is None
        assert "domain job missing or unsupported" in (recovered.error or "")


def test_processing_error_redacts_gis_storage_details():
    error = _safe_processing_error(
        RuntimeError(
            "GET https://storage.example/bucket/tile.tif?token=secret-value "
            "failed at /tmp/croptwist/private.tif password=also-secret"
        )
    )
    assert "storage.example" not in error
    assert "secret-value" not in error
    assert "also-secret" not in error
    assert "/tmp/croptwist" not in error
    assert "RuntimeError" in error


def test_raster_submission_publishes_only_after_domain_commit(db, farm_with_field, monkeypatch):
    """The raster enqueue callback sees the domain and companion rows together."""
    from app.data_platform.processing import service as processing
    from app.db.models import Field
    from app.db.models_p2 import RasterProcessingJob, SatelliteScene

    field_id = uuid.UUID(farm_with_field["field"]["id"])
    db.add(
        SatelliteScene(
            field_id=field_id,
            provider_code="nasa_hls",
            product_code="HLSL30",
            scene_id="ATOMIC.DISPATCH",
            acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
            cloud_cover_pct=1.0,
            spatial_resolution_m=30.0,
            band_mapping={"red": "B04", "nir": "B05"},
            asset_refs={"red": "red.tif", "nir": "nir.tif"},
            is_synthetic=False,
            processing_version="2.0",
            metadata_json={},
            acquisition_status="ready",
            discovered_at=datetime.now(UTC),
            acquisition_updated_at=datetime.now(UTC),
        )
    )
    db.commit()
    field = db.get(Field, field_id)

    observed: list[tuple[bool, bool]] = []
    original_enqueue = jobs.enqueue_existing

    def observe_enqueue(job_id, fn=None):
        with SessionLocal() as observer:
            background = observer.get(BackgroundJob, job_id)
            domain = observer.scalar(
                select(RasterProcessingJob).where(
                    RasterProcessingJob.background_job_id == job_id
                )
            )
            observed.append((background is not None, domain is not None))
        original_enqueue(job_id, fn)

    monkeypatch.setattr(jobs, "enqueue_existing", observe_enqueue)
    result = processing.create_processing_jobs(
        db,
        field=field,
        scene_ids=["ATOMIC.DISPATCH"],
        indices=["ndvi"],
    )

    assert result["queued_scenes"] == 1
    assert observed == [(True, True)]
    _drain_local_wakeups()

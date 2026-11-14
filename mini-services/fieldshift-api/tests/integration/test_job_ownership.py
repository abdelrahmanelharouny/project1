"""PostgreSQL regressions for durable job ownership and replay fencing.

These tests use only synthetic rows/executors and do not call providers, mail,
payment, or external services. Run only with an isolated integration-test DSN.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import update

from app.core import jobs
from app.core.database import SessionLocal
from app.db.models import BackgroundJob, Farm, Field, IngestionJob
from app.db.models_p2 import RasterProcessingJob
from app.db.models_p3 import ReportJob


def _field_id(farm_with_field: dict) -> uuid.UUID:
    return uuid.UUID(farm_with_field["field"]["id"])


def _make_expired_background(
    *, kind: str, ref_kind: str, ref_id: uuid.UUID, fencing_token: int = 4
) -> BackgroundJob:
    return BackgroundJob(
        kind=kind,
        status="running",
        ref_kind=ref_kind,
        ref_id=ref_id,
        owner_id=uuid.uuid4(),
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        fencing_token=fencing_token,
        started_at=datetime.now(UTC) - timedelta(minutes=20),
        progress=35,
    )


def _clear_local_queue(job_id: uuid.UUID) -> None:
    """Remove one synthetic recovery wake-up without disturbing other IDs."""
    retained: list[uuid.UUID | None] = []
    while True:
        try:
            item = jobs._queue.get_nowait()
        except jobs.queue.Empty:
            break
        jobs._queue.task_done()
        if item != job_id:
            retained.append(item)
    with jobs._queue_lock:
        jobs._queued_ids.discard(job_id)
        jobs._queued_ids.clear()
    for item in retained:
        if item is None:
            jobs._queue.put(None)
        else:
            jobs._queue_job_id(item)


def test_live_lease_is_not_recovered_even_when_updated_at_is_old(
    monkeypatch, db
) -> None:
    monkeypatch.setattr(jobs, "_JOB_LEASE_SECONDS", 3)
    monkeypatch.setattr(jobs, "_JOB_HEARTBEAT_SECONDS", 30)
    started = threading.Event()
    finish = threading.Event()
    calls: list[uuid.UUID] = []

    def work(job_id, _progress) -> None:
        calls.append(job_id)
        started.set()
        assert finish.wait(5)

    row = BackgroundJob(kind="live-lease-test", status="queued")
    db.add(row)
    db.commit()
    with jobs._registry_lock:
        jobs._pending_fns[row.id] = work

    worker = threading.Thread(target=jobs._run_job, args=(row.id,))
    worker.start()
    assert started.wait(5)
    old = datetime.now(UTC) - timedelta(days=1)
    db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == row.id)
        .values(updated_at=old)
    )
    db.commit()

    jobs._recover_orphans()
    db.refresh(row)
    assert row.status == "running"
    assert row.owner_id is not None
    assert row.lease_expires_at > datetime.now(UTC)
    assert calls == [row.id]

    # Even if the persisted lease is forced past expiry, recovery cannot take
    # the live session lock still held by the executing thread.
    owner_id, fence = row.owner_id, row.fencing_token
    db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == row.id)
        .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    jobs._recover_orphans()
    db.refresh(row)
    assert row.status == "running"
    assert row.owner_id == owner_id
    assert row.fencing_token == fence
    assert row.lease_expires_at < datetime.now(UTC)

    # Restore the current owner's lease so its normal fenced finalization wins.
    db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == row.id)
        .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=3))
    )
    db.commit()

    finish.set()
    worker.join(5)
    assert not worker.is_alive()
    db.refresh(row)
    assert row.status == "succeeded"
    assert calls == [row.id]


def test_concurrent_expired_lease_recovery_increments_once_and_claim_executes_once(
    farm_with_field, db, monkeypatch
) -> None:
    domain = IngestionJob(
        field_id=_field_id(farm_with_field),
        provider_code="synthetic",
        status="running",
        request_parameters={"variables": [], "options": {}},
        started_at=datetime.now(UTC) - timedelta(minutes=20),
    )
    db.add(domain)
    db.flush()
    row = _make_expired_background(
        kind="ingestion", ref_kind="ingestion", ref_id=domain.id, fencing_token=7
    )
    db.add(row)
    db.commit()

    executor_started = threading.Event()
    executor_finish = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    active = 0
    max_active = 0

    def replay(_job_id, _progress) -> None:
        nonlocal calls, active, max_active
        with call_lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        executor_started.set()
        assert executor_finish.wait(5)
        with call_lock:
            active -= 1

    monkeypatch.setitem(jobs._kind_executors, "ingestion", replay)
    gate = threading.Barrier(3)
    failures: list[BaseException] = []

    def recover() -> None:
        try:
            gate.wait(5)
            jobs._recover_orphans()
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    recoverers = [threading.Thread(target=recover) for _ in range(2)]
    for thread in recoverers:
        thread.start()
    gate.wait(5)
    for thread in recoverers:
        thread.join(5)
        assert not thread.is_alive()
    assert failures == []

    db.refresh(row)
    db.refresh(domain)
    assert row.status == "queued"
    assert row.fencing_token == 8
    assert row.result["_recovery_attempts"] == 1
    assert row.owner_id is None and row.lease_expires_at is None
    assert domain.status == "queued"

    # Repeated recovery cannot reset the job again or consume another attempt.
    jobs._recover_orphans()
    db.refresh(row)
    assert row.fencing_token == 8
    assert row.result["_recovery_attempts"] == 1

    _clear_local_queue(row.id)
    first = threading.Thread(target=jobs._run_job, args=(row.id,))
    first.start()
    assert executor_started.wait(5)
    second = threading.Thread(target=jobs._run_job, args=(row.id,))
    second.start()
    second.join(5)
    assert not second.is_alive()
    with call_lock:
        assert calls == 1
        assert max_active == 1
    executor_finish.set()
    first.join(5)
    assert not first.is_alive()
    db.refresh(row)
    assert row.status == "succeeded"
    assert calls == 1
    assert max_active == 1


def test_old_owner_cannot_write_progress_or_finalize_after_fencing(
    db,
) -> None:
    current_owner = uuid.uuid4()
    row = BackgroundJob(
        kind="fence-test",
        status="running",
        owner_id=current_owner,
        fencing_token=12,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        progress=25,
        stage="current owner",
    )
    db.add(row)
    db.commit()

    assert not jobs._write_progress(
        row.id, current_owner, 11, 95, "late old owner"
    )
    assert not jobs._finalize_job(
        row.id, current_owner, 11, error="late old failure"
    )
    db.refresh(row)
    assert row.status == "running"
    assert row.fencing_token == 12
    assert row.progress == 25
    assert row.stage == "current owner"
    assert row.owner_id == current_owner


def test_completed_ingestion_raster_and_report_rows_reconcile_without_replay(
    farm_with_field, db, monkeypatch
) -> None:
    field = db.get(Field, _field_id(farm_with_field))
    farm = db.get(Farm, field.farm_id)
    ingestion = IngestionJob(
        field_id=field.id,
        provider_code="synthetic",
        status="succeeded",
        request_parameters={"variables": [], "options": {}},
        completed_at=datetime.now(UTC),
    )
    raster = RasterProcessingJob(
        field_id=field.id,
        scene_id="synthetic-scene-ownership",
        product_code="fixture_demo",
        indices=["NDVI"],
        indices_digest="a" * 32,
        processing_version="test-v1",
        status="succeeded",
        progress=100,
        finished_at=datetime.now(UTC),
    )
    report = ReportJob(
        organization_id=farm.organization_id,
        report_type="synthetic_ownership_test",
        output_format="csv",
        locale="en",
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
        status="succeeded",
        file_path="/synthetic/report.csv",
        file_size_bytes=8,
    )
    db.add_all([ingestion, raster, report])
    db.flush()
    backgrounds = [
        _make_expired_background(
            kind="ingestion", ref_kind="ingestion", ref_id=ingestion.id
        ),
        _make_expired_background(
            kind="raster_processing",
            ref_kind="raster_processing",
            ref_id=raster.id,
        ),
        _make_expired_background(
            kind="report_generation", ref_kind="report", ref_id=report.id
        ),
    ]
    db.add_all(backgrounds)
    db.commit()

    executor_calls: list[uuid.UUID] = []
    for kind in ("ingestion", "raster_processing", "report_generation"):
        monkeypatch.setitem(
            jobs._kind_executors,
            kind,
            lambda job_id, _progress: executor_calls.append(job_id),
        )
    jobs._recover_orphans()

    for background in backgrounds:
        db.refresh(background)
        assert background.status == "succeeded"
        assert background.progress == 100
        assert background.owner_id is None
        assert background.lease_expires_at is None
        assert background.finished_at is not None
    for domain in (ingestion, raster, report):
        db.refresh(domain)
        assert domain.status == "succeeded"
    assert executor_calls == []

    # The report worker's independent replay entry point also reconciles an
    # already-succeeded domain row without re-running metering/event emission.
    from app.reports import service as report_service
    from app.reports.worker import execute_report_background_job

    report_calls: list[uuid.UUID] = []
    monkeypatch.setattr(
        report_service,
        "execute_report_job",
        lambda _session, report_id: report_calls.append(report_id),
    )
    queued_bg = BackgroundJob(
        kind="report_generation",
        status="queued",
        ref_kind="report",
        ref_id=report.id,
    )
    db.add(queued_bg)
    db.commit()
    execute_report_background_job(queued_bg.id)
    db.refresh(queued_bg)
    assert queued_bg.status == "succeeded"
    assert report_calls == []


def test_report_execution_serializes_scheduler_and_background_callers_idempotently(
    farm_with_field, db, monkeypatch
) -> None:
    field = db.get(Field, _field_id(farm_with_field))
    farm = db.get(Farm, field.farm_id)
    report = ReportJob(
        organization_id=farm.organization_id,
        report_type="synthetic_ownership_test",
        output_format="csv",
        locale="en",
        date_from=date(2025, 2, 1),
        date_to=date(2025, 2, 28),
        status="queued",
    )
    db.add(report)
    db.commit()
    report_id = report.id

    from app.publicapi import emitters
    from app.reports import service as report_service

    counters = {"render": 0, "usage": 0, "event": 0}
    counter_lock = threading.Lock()

    def bump(key: str) -> None:
        with counter_lock:
            counters[key] += 1

    monkeypatch.setattr(report_service.contracts, "get_report_type", lambda _kind: object())
    monkeypatch.setattr(
        report_service,
        "_build_payload",
        lambda _session, _job, _spec, _now: {},
    )
    monkeypatch.setattr(
        report_service,
        "_write_artifact",
        lambda _job, _blob: Path("/synthetic/report.csv"),
    )
    monkeypatch.setattr(
        report_service.renderers,
        "render",
        lambda *_args: (b"synthetic report", bump("render"))[0],
    )
    monkeypatch.setattr(
        report_service.entitlements,
        "increment_usage",
        lambda *_args: bump("usage"),
    )
    monkeypatch.setattr(emitters, "emit_event", lambda *_args, **_kwargs: bump("event"))
    monkeypatch.setattr(
        report_service.contracts,
        "retention_until_for",
        lambda now, *_args: now + timedelta(days=30),
    )

    start = threading.Barrier(3)
    results: list[tuple[bool, str | None]] = []
    failures: list[BaseException] = []

    def execute() -> None:
        try:
            with SessionLocal() as session:
                start.wait(5)
                results.append(report_service.execute_report_job(session, report_id))
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    callers = [threading.Thread(target=execute) for _ in range(2)]
    for thread in callers:
        thread.start()
    start.wait(5)
    for thread in callers:
        thread.join(15)
        assert not thread.is_alive()

    assert failures == []
    assert results == [(True, None), (True, None)]
    assert counters == {"render": 1, "usage": 1, "event": 1}
    db.refresh(report)
    assert report.status == "succeeded"

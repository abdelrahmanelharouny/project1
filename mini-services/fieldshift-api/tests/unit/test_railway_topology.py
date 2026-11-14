"""Targeted checks for the bounded Railway API/worker topology adaptation."""
from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core import jobs
from app.core import scheduler
from app.core.config import settings
from app.db.models import BackgroundJob, Field
from app.data_platform.ingestion import service as ingestion


def _drain_local_wakeups() -> None:
    """Prevent durable-submit wakeups from leaking into neighboring tests."""
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


def test_queue_only_ingestion_persists_without_inline_processing(
    db, farm_with_field, monkeypatch
):
    """API topology mode creates both rows but never invokes the provider path."""
    field = db.get(Field, uuid.UUID(farm_with_field["field"]["id"]))
    assert field is not None
    called = []

    def fail_inline(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("queue-only ingestion executed inline")

    monkeypatch.setattr(settings, "job_workers", 0)
    monkeypatch.setattr(settings, "job_queue_only", True)
    monkeypatch.setattr(ingestion, "_execute_job", fail_inline)

    job = ingestion.start_ingestion_job(
        db,
        field=field,
        provider_code="synthetic",
        variables=["air_temperature_mean"],
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 2, tzinfo=UTC),
        options={},
        idempotency_key=f"queue-only-{uuid.uuid4().hex}",
        created_by=None,
        execute=True,
    )

    assert job.status == "queued"
    queued = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.kind == "ingestion",
            BackgroundJob.ref_kind == "ingestion",
            BackgroundJob.ref_id == job.id,
        )
    )
    assert queued is not None
    assert queued.status == "queued"
    assert called == []
    _drain_local_wakeups()


def test_scheduler_task_advisory_lock_allows_one_process(monkeypatch):
    """Two scheduler instances cannot execute the same periodic task together."""
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    task_name = f"topology.lock.{uuid.uuid4().hex}"

    def task_body(_session):
        calls.append("executed")
        entered.set()
        assert release.wait(timeout=5)
        return "done"

    task = scheduler.PeriodicTask(task_name, 60, task_body)
    first = threading.Thread(target=scheduler._run_task, args=(task,))
    second = threading.Thread(target=scheduler._run_task, args=(task,))
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    second.join(timeout=5)
    assert not second.is_alive()
    release.set()
    first.join(timeout=5)
    assert not first.is_alive()
    assert calls == ["executed"]
    assert scheduler.LAST_RUNS[task_name]["ok"] is True
    assert "advisory lock" in scheduler.LAST_RUNS[task_name]["detail"] or scheduler.LAST_RUNS[
        task_name
    ]["detail"] == "done"


def test_queue_only_report_api_persists_replayable_job_without_inline_render(
    client, auth_headers, db, monkeypatch
):
    """Report creation links a durable queue row before returning to Railway."""
    from app.reports import service as report_service

    headers, user = auth_headers
    subscription = client.post(
        "/api/v1/billing/subscription",
        headers=headers,
        json={
            "organization_id": user["organization"]["id"],
            "plan_code": "starter",
            "billing_period": "monthly",
        },
    )
    assert subscription.status_code == 200, subscription.text
    called = []

    def fail_inline(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("queue-only report rendered inline")

    monkeypatch.setattr(settings, "job_workers", 0)
    monkeypatch.setattr(settings, "job_queue_only", True)
    monkeypatch.setattr(report_service, "execute_report_job", fail_inline)

    response = client.post(
        "/api/v1/reports",
        headers=headers,
        json={"report_type": "org_executive", "format": "csv", "sync": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["background_job_id"] is not None
    queue_row = db.get(BackgroundJob, uuid.UUID(body["background_job_id"]))
    assert queue_row is not None
    assert queue_row.status == "queued"
    assert queue_row.ref_kind == "report"
    assert queue_row.ref_id == uuid.UUID(body["id"])
    assert called == []
    _drain_local_wakeups()


def test_standalone_worker_starts_and_stops_scheduler(monkeypatch):
    """The worker owns scheduler lifecycle when configured as a worker process."""
    from app import worker as worker_entry
    from app.core import scheduler as maintenance_scheduler

    events: list[str] = []
    monkeypatch.setattr(settings, "job_workers", 1)
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(jobs, "start_workers", lambda: 1)
    monkeypatch.setattr(jobs, "shutdown_workers", lambda: events.append("workers.stop"))
    monkeypatch.setattr(
        maintenance_scheduler,
        "start_scheduler",
        lambda: events.append("scheduler.start") or True,
    )
    monkeypatch.setattr(
        maintenance_scheduler,
        "stop_scheduler",
        lambda: events.append("scheduler.stop"),
    )

    assert worker_entry.main(["--idle-exit-seconds", "1"]) == 0
    assert events == ["scheduler.start", "scheduler.stop", "workers.stop"]

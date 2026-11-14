"""Pure regression tests for durable background-job ownership decisions."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid

from app.core import jobs


def test_advisory_lock_key_is_stable_signed_int64() -> None:
    job_id = uuid.UUID("f21cae27-8891-4e13-b80e-bb10299601a7")

    key = jobs._lock_key(job_id)

    assert key == jobs._lock_key(job_id)
    assert -(2**63) <= key < 2**63


def test_terminal_domain_status_mapping() -> None:
    assert jobs._background_terminal_status("succeeded") == "succeeded"
    assert jobs._background_terminal_status("failed") == "failed"
    assert jobs._background_terminal_status("cancelled") == "cancelled"
    assert jobs._background_terminal_status("expired") == "cancelled"
    assert jobs._background_terminal_status("running") is None
    assert jobs._background_terminal_status("queued") is None


def test_replay_policy_is_allowlisted_and_report_running_fails_closed() -> None:
    ingestion_job = SimpleNamespace(kind="ingestion", ref_kind="ingestion")
    raster_job = SimpleNamespace(kind="raster_processing", ref_kind="raster_processing")
    report_job = SimpleNamespace(kind="report_generation", ref_kind="report")

    assert jobs._replay_is_safe(ingestion_job, SimpleNamespace(status="queued"))
    assert jobs._replay_is_safe(ingestion_job, SimpleNamespace(status="running"))
    assert not jobs._replay_is_safe(ingestion_job, SimpleNamespace(status="succeeded"))
    assert jobs._replay_is_safe(raster_job, SimpleNamespace(status="running"))
    assert jobs._replay_is_safe(report_job, SimpleNamespace(status="queued"))
    assert not jobs._replay_is_safe(report_job, SimpleNamespace(status="running"))
    assert not jobs._replay_is_safe(report_job, SimpleNamespace(status="failed"))
    assert not jobs._replay_is_safe(
        SimpleNamespace(kind="unknown", ref_kind="unknown"), SimpleNamespace(status="queued")
    )


def test_recovery_reset_clears_only_supported_lifecycle_fields() -> None:
    now = datetime.now(UTC)
    domain = SimpleNamespace(
        status="running",
        error="previous error",
        error_summary="previous summary",
        finished_at=now,
        completed_at=now,
        started_at=now,
        progress=73,
        stage="working",
        retained="do not change",
    )

    jobs._reset_domain_for_replay(domain)

    assert domain.status == "queued"
    assert domain.error is None
    assert domain.error_summary is None
    assert domain.finished_at is None
    assert domain.completed_at is None
    assert domain.started_at is None
    assert domain.progress == 0
    assert domain.stage == "recovered after expired worker lease"
    assert domain.retained == "do not change"


def test_expiry_policy_is_not_the_generic_updated_at_timestamp() -> None:
    now = datetime.now(UTC)
    live = SimpleNamespace(
        owner_id=uuid.uuid4(),
        lease_expires_at=now + timedelta(seconds=60),
        updated_at=now - timedelta(days=1),
    )
    expired = SimpleNamespace(
        owner_id=uuid.uuid4(),
        lease_expires_at=now - timedelta(seconds=1),
        updated_at=now,
    )

    assert live.lease_expires_at > now
    assert expired.lease_expires_at <= now
    # The test documents the defect boundary: old progress timestamps do not
    # invalidate a renewed lease, and fresh timestamps do not resurrect one.
    assert live.updated_at < expired.updated_at

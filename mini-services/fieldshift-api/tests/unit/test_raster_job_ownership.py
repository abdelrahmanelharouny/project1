"""Pure regressions for raster persistence fencing."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core import jobs
from app.data_platform.processing import service as processing


class _ScalarSession:
    def __init__(self, result):
        self.result = result
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)
        return self.result


def _rp(background_job_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), background_job_id=background_job_id)


def test_current_raster_owner_query_checks_job_owner_fence_and_live_lease(monkeypatch) -> None:
    job_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    fencing_token = 17
    monkeypatch.setattr(
        jobs, "current_job_execution", lambda: (job_id, owner_id, fencing_token)
    )
    db = _ScalarSession(result=job_id)

    processing._assert_processing_job_owner(db, _rp(job_id))

    assert len(db.statements) == 1
    statement = db.statements[0]
    compiled = statement.compile()
    sql = str(compiled)
    assert "background_jobs.status" in sql
    assert "background_jobs.owner_id" in sql
    assert "background_jobs.fencing_token" in sql
    assert "background_jobs.lease_expires_at" in sql
    assert "clock_timestamp()" in sql
    assert owner_id in compiled.params.values()
    assert fencing_token in compiled.params.values()


def test_old_context_is_rejected_when_persisted_generation_is_not_current(monkeypatch) -> None:
    job_id = uuid.uuid4()
    old_owner = uuid.uuid4()
    monkeypatch.setattr(
        jobs, "current_job_execution", lambda: (job_id, old_owner, 6)
    )
    db = _ScalarSession(result=None)

    with pytest.raises(processing.ProcessingOwnershipLostError, match="no longer current"):
        processing._assert_processing_job_owner(db, _rp(job_id))

    assert len(db.statements) == 1


def test_owner_context_for_a_different_background_job_fails_before_query(monkeypatch) -> None:
    requested_job = uuid.uuid4()
    monkeypatch.setattr(
        jobs,
        "current_job_execution",
        lambda: (uuid.uuid4(), uuid.uuid4(), 2),
    )
    db = _ScalarSession(result=requested_job)

    with pytest.raises(processing.ProcessingOwnershipLostError, match="different job"):
        processing._assert_processing_job_owner(db, _rp(requested_job))

    assert db.statements == []


def test_synchronous_unclaimed_row_is_allowed_but_ownerless_running_row_fails_closed(
    monkeypatch,
) -> None:
    job_id = uuid.uuid4()
    monkeypatch.setattr(processing.settings, "job_workers", 0)
    monkeypatch.setattr(jobs, "current_job_execution", lambda: None)

    processing._assert_processing_job_owner(_ScalarSession(result=job_id), _rp(job_id))
    with pytest.raises(processing.ProcessingOwnershipLostError, match="no active worker context"):
        processing._assert_processing_job_owner(_ScalarSession(result=None), _rp(job_id))


def test_artifact_write_is_not_attempted_when_ownership_precheck_fails(monkeypatch) -> None:
    attempted = []

    def reject_owner(_db, _rp):
        raise processing.ProcessingOwnershipLostError("stale raster owner")

    monkeypatch.setattr(processing, "_assert_processing_job_owner", reject_owner)
    storage = SimpleNamespace(
        put_bytes=lambda *args, **kwargs: attempted.append((args, kwargs))
    )

    with pytest.raises(processing.ProcessingOwnershipLostError, match="stale raster owner"):
        processing._put_asset_owned(
            object(),
            _rp(uuid.uuid4()),
            storage,
            "derived/example.tif",
            b"raster",
            "image/tiff",
            allow_overwrite=True,
        )

    assert attempted == []

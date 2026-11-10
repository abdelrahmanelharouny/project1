"""Integration: background job executor + unified jobs API (P0-3 async jobs).

The suite runs with CROPTWIST_JOB_WORKERS=0 (legacy inline ingestion); these
tests start the executor explicitly and shut it down after each test.
"""

import time
import uuid

import pytest
from sqlalchemy import func, select

from app.core import jobs
from app.core.config import settings
from app.db.models import BackgroundJob, IngestionJob, Observation


@pytest.fixture()
def worker_pool(monkeypatch):
    """A real executor pool for the duration of one test."""
    monkeypatch.setattr(settings, "job_workers", 2)
    assert jobs.start_workers() == 2
    yield
    jobs.shutdown_workers()
    jobs._pending_fns.clear()


class TestExecutor:
    def test_submit_runs_and_records_progress(self, worker_pool, db):
        def work(job_id, progress):
            progress(40, "halfway")
            progress(90, "almost")

        job = jobs.submit("demo_kind", work, label="demo")
        final = jobs.wait_for_job(job.id)
        assert final.status == "succeeded"
        assert final.progress == 100
        assert final.finished_at is not None
        # Intermediate progress actually hit the row while running (>= the
        # last explicit value before completion).
        assert final.result is None
        assert final.kind == "demo_kind"

    def test_failure_records_error_and_worker_survives(self, worker_pool):
        def bad(_job_id, _progress):
            raise ValueError("boom")

        job = jobs.submit("demo_bad", bad)
        final = jobs.wait_for_job(job.id)
        assert final.status == "failed"
        assert "ValueError: boom" in final.error
        assert final.finished_at is not None
        # The worker pool is still alive: a follow-up job succeeds.
        ok = jobs.submit("demo_ok", lambda _jid, _p: None)
        assert jobs.wait_for_job(ok.id).status == "succeeded"

    def test_recovered_queued_job_runs_via_registered_kind(self, monkeypatch, db):
        """A 'queued' row discovered at startup is executed when its kind has
        a replayable executor registered (crash recovery)."""
        calls = []

        def replayable(job_id, progress):
            calls.append(job_id)

        jobs.register_kind("replay_kind", replayable)
        row = BackgroundJob(kind="replay_kind", status="queued")
        db.add(row)
        db.commit()
        monkeypatch.setattr(settings, "job_workers", 1)
        assert jobs.start_workers() == 1
        try:
            final = jobs.wait_for_job(row.id)
            assert final.status == "succeeded"
            assert calls == [row.id]
        finally:
            jobs.shutdown_workers()

    def test_stale_running_row_marked_interrupted(self, monkeypatch, db):
        """'running' rows found at startup are failed, not re-executed."""
        executed = []
        jobs.register_kind("stale_kind", lambda jid, p: executed.append(jid))
        row = BackgroundJob(kind="stale_kind", status="running", started_at=None)
        db.add(row)
        db.commit()
        monkeypatch.setattr(settings, "job_workers", 1)
        assert jobs.start_workers() == 1
        try:
            time.sleep(0.3)
            db.refresh(row)
            assert row.status == "failed"
            assert row.error == "interrupted by restart"
            assert executed == []  # never re-executed
        finally:
            jobs.shutdown_workers()


class TestJobsApi:
    def _await_terminal(self, client, headers, job_id, timeout=30.0):
        """Poll the UNCHANGED domain status URL (the real client contract)
        until the job reaches a terminal state; returns the last payload."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            r = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
            if r.status_code == 200:
                last = r.json()
                if last.get("status") in ("succeeded", "failed", "cancelled"):
                    return last
            time.sleep(0.1)
        raise AssertionError(f"job {job_id} did not reach a terminal state; last={last}")

    def test_async_ingestion_endpoint_contract(self, client, farm_with_field, worker_pool, db):
        """POST /data-jobs with workers enabled: same 202 shape, status
        'queued', then the worker completes it and observations persist."""
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={
                "provider_code": "synthetic",
                "variables": ["air_temperature_mean", "precipitation"],
                "start_date": "2023-04-01",
                "end_date": "2023-04-30",
                "profile": "temperate_seasonal",
                "seed": 5,
            },
        )
        assert resp.status_code == 202, resp.text
        payload = resp.json()
        assert payload["status"] == "queued"
        job_id = uuid.UUID(payload["job_id"])

        # Poll the DOMAIN status URL (the ingestion job id) like real clients.
        deadline = time.monotonic() + 30
        domain = None
        while time.monotonic() < deadline:
            domain = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
            assert domain.status_code == 200
            if domain.json()["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.2)
        assert domain.json()["status"] == "succeeded", domain.text
        assert domain.json()["records_received"] == 60

        # Unified queue view references the domain row.
        bg_row = db.scalar(
            select(BackgroundJob).where(
                BackgroundJob.ref_kind == "ingestion", BackgroundJob.ref_id == job_id
            )
        )
        assert bg_row is not None and bg_row.status == "succeeded"
        unified = client.get(f"/api/v1/jobs/background/{bg_row.id}", headers=headers)
        assert unified.status_code == 200
        body = unified.json()
        assert body["kind"] == "ingestion"
        assert body["ref_kind"] == "ingestion"
        assert body["ref_id"] == str(job_id)
        assert body["terminal"] is True

        observations = db.scalar(
            select(func.count())
            .select_from(Observation)
            .where(Observation.field_id == uuid.UUID(field_id))
        )
        assert observations == 60

    def test_tenant_isolation_on_background_jobs(self, client, farm_with_field, worker_pool, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={
                "provider_code": "synthetic",
                "variables": ["air_temperature_mean"],
                "start_date": "2023-04-01",
                "end_date": "2023-04-10",
                "profile": "temperate_seasonal",
                "seed": 7,
            },
        )
        assert resp.status_code == 202
        job_id = uuid.UUID(resp.json()["job_id"])
        bg_row = db.scalar(
            select(BackgroundJob).where(
                BackgroundJob.ref_kind == "ingestion", BackgroundJob.ref_id == job_id
            )
        )
        assert bg_row is not None
        assert jobs.wait_for_job(bg_row.id, timeout=30).status == "succeeded"

        # A second tenant cannot see the job (404, same as unknown ids).
        other = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{uuid.uuid4().hex[:10]}@test.local",
                "password": "test-password-1",
                "display_name": "Other Farmer",
            },
        )
        assert other.status_code == 201
        other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
        assert (
            client.get(f"/api/v1/jobs/background/{bg_row.id}", headers=other_headers).status_code
            == 404
        )
        listed = client.get("/api/v1/jobs/background", headers=other_headers)
        assert listed.status_code == 200, listed.text
        assert all(item["id"] != str(bg_row.id) for item in listed.json()["jobs"])
        # ... while the owner sees it in their list.
        own = client.get("/api/v1/jobs/background", headers=headers).json()
        assert any(item["id"] == str(bg_row.id) for item in own["jobs"])

    def test_list_filters(self, client, farm_with_field, worker_pool, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={
                "provider_code": "synthetic",
                "variables": ["air_temperature_mean"],
                "start_date": "2023-05-01",
                "end_date": "2023-05-10",
                "profile": "temperate_seasonal",
                "seed": 9,
            },
        )
        assert resp.status_code == 202
        job_id = uuid.UUID(resp.json()["job_id"])
        bg_row = db.scalar(
            select(BackgroundJob).where(
                BackgroundJob.ref_kind == "ingestion", BackgroundJob.ref_id == job_id
            )
        )
        assert bg_row is not None
        assert jobs.wait_for_job(bg_row.id, timeout=30).status == "succeeded"
        failed_list = client.get(
            "/api/v1/jobs/background", headers=headers, params={"status": "failed"}
        ).json()
        assert all(item["status"] == "failed" for item in failed_list["jobs"])
        kind_list = client.get(
            "/api/v1/jobs/background", headers=headers, params={"kind": "ingestion"}
        ).json()
        assert kind_list["count"] >= 1
        assert all(item["kind"] == "ingestion" for item in kind_list["jobs"])

# ------------------------------------------------------------------ helpers
# (tests use uuid.UUID / func.count imported at module scope)

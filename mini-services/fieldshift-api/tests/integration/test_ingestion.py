"""Integration: synthetic ingestion jobs, idempotency, canonical persistence."""

import uuid

from sqlalchemy import func, select

from app.db.models import Observation

JOB_BODY = {
    "provider_code": "synthetic",
    "variables": ["air_temperature_mean", "precipitation"],
    "start_date": "2023-04-01",
    "end_date": "2023-04-30",
    "profile": "temperate_seasonal",
    "seed": 5,
}


def _start_job(client, headers, field_id, body=None):
    return client.post(f"/api/v1/fields/{field_id}/data-jobs", headers=headers, json=body or JOB_BODY)


class TestIngestion:
    def test_job_succeeds_and_persists_observations(self, client, farm_with_field, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = _start_job(client, headers, field_id)
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["status"] == "succeeded"
        assert job["records_received"] == 60  # 30 days x 2 variables
        assert job["records_rejected"] == 0

        total = db.scalar(select(func.count()).where(Observation.field_id == field_id))
        assert total == 60

    def test_observations_api_with_filters(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _start_job(client, headers, field_id)

        all_obs = client.get(f"/api/v1/fields/{field_id}/observations", headers=headers).json()
        assert all_obs["total"] == 60

        temp = client.get(
            f"/api/v1/fields/{field_id}/observations?variable_code=air_temperature_mean", headers=headers
        ).json()
        assert temp["total"] == 30

        window = client.get(
            f"/api/v1/fields/{field_id}/observations?start=2023-04-10&end=2023-04-15", headers=headers
        ).json()
        assert window["total"] == 10  # 5 days x 2 variables

        assert all(o["is_synthetic"] is True for o in all_obs["items"])
        assert all(o["unit"] for o in all_obs["items"])
        assert all(o["time_support"] == "daily" for o in all_obs["items"])

    def test_rerun_does_not_duplicate(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _start_job(client, headers, field_id)
        second = _start_job(client, headers, field_id)
        assert second.status_code == 202
        assert second.json()["status"] == "succeeded"
        total = client.get(f"/api/v1/fields/{field_id}/observations", headers=headers).json()["total"]
        assert total == 60  # unchanged — natural-key dedupe

    def test_unsupported_variable_fails_fast_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        resp = _start_job(
            client, headers, farm_with_field["field"]["id"],
            body={**JOB_BODY, "variables": ["nvdi_index"]},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "UNSUPPORTED_VARIABLE"

    def test_unknown_provider_404(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        resp = _start_job(
            client, headers, farm_with_field["field"]["id"],
            body={**JOB_BODY, "provider_code": "nasa_earthdata"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_provider_coverage_outside_range_surfaces_structured_job_failure(self, client, farm_with_field):
        """Per Master §12: provider errors surface as structured job failures,
        not as endpoint crashes."""
        headers = farm_with_field["headers"]
        resp = _start_job(
            client, headers, farm_with_field["field"]["id"],
            body={**JOB_BODY, "start_date": "2010-01-01", "end_date": "2010-02-01"},
        )
        assert resp.status_code == 202
        job = resp.json()
        assert job["status"] == "failed"
        assert job["error_summary"]
        assert "coverage" in job["error_summary"].lower()

    def test_job_state_persisted_and_queryable(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        job = _start_job(client, headers, farm_with_field["field"]["id"]).json()
        fetched = client.get(f"/api/v1/jobs/{job['job_id']}", headers=headers)
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "succeeded"
        assert body["started_at"] and body["completed_at"]
        assert any("SYNTHETIC" in w for w in body["warnings"])

    def test_missing_values_stored_as_null(self, client, farm_with_field, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _start_job(
            client, headers, field_id,
            body={**JOB_BODY, "start_date": "2022-01-01", "end_date": "2022-12-31"},
        )
        missing_rows = db.scalars(
            select(Observation).where(Observation.field_id == field_id, Observation.value.is_(None))
        ).all()
        assert missing_rows, "expected synthetic gaps to persist as NULL values"
        assert all(o.quality_status == "missing" for o in missing_rows)
        flags = [f for o in missing_rows for f in o.quality_flags]
        assert any(f.flag_code == "SYNTHETIC_GAP" for f in flags)

    def test_job_for_other_tenant_hidden(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        job = _start_job(client, headers, farm_with_field["field"]["id"]).json()
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        resp = client.get(f"/api/v1/jobs/{job['job_id']}",
                          headers={"Authorization": f"Bearer {other['token']}"})
        assert resp.status_code == 403

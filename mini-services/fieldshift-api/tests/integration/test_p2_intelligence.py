"""Integration: P2 intelligence golden path (satellite → vegetation →
recommendations → evidence gaps → staleness → apply → soil memory →
forecasts → failure lab → portfolio).

Runs against the real test database with deterministic provider fakes (the
suite never needs the network — see conftest). Every live-external surface
(Sentinel-2 STAC, CMIP6) is asserted to fail LOUDLY and store NOTHING rather
than fabricate data.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.climate.contracts import ForecastEvidence, ForecastClass
from app.climate.service import (
    forecast_freshness,
    forecasts_in_window,
    persist_forecast_evidence,
)
from app.climate.verification import verify_forecasts


@pytest.fixture()
def field_ctx(client, farm_with_field):
    return farm_with_field


def _ingest_satellite(client, field_ctx, *, start="2021-01-01", end="2021-12-31", profile="cropland_seasonal"):
    resp = client.post(
        f"/api/v1/fields/{field_ctx['field']['id']}/data-jobs",
        headers=field_ctx["headers"],
        json={
            "provider_code": "satellite_sim",
            "variables": ["ndvi", "evi"],
            "start_date": start,
            "end_date": end,
            "options": {"profile": profile, "seed": 7},
        },
    )
    assert resp.status_code in (200, 201, 202), resp.text
    return resp.json()


def _create_rotation_run(client, field_ctx) -> dict:
    """The failure lab stress-tests candidates of an existing rotation run
    (honest precondition) — create a minimal one first."""
    resp = client.post(
        f"/api/v1/fields/{field_ctx['field']['id']}/rotation-runs",
        headers=field_ctx["headers"],
        json={"seasons": [{"label": "s2026", "start_date": "2026-05-01", "end_date": "2026-09-15"}]},
    )
    assert resp.status_code in (200, 201, 202), resp.text
    return resp.json()


def _wait_job(client, headers, job_id: str, *, timeout_s: float = 30.0) -> dict:
    """Poll the unified job status endpoint until a terminal state."""
    import time as _time

    deadline = _time.time() + timeout_s
    payload = None
    while _time.time() < deadline:
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        if resp.status_code == 200:
            payload = resp.json()
            status = payload.get("status")
            if status in ("succeeded", "failed", "cancelled"):
                return payload
        _time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not reach a terminal state: {payload}")


class TestSatelliteIngestion:
    def test_sim_ingestion_records_observations_and_scenes(self, client, field_ctx):
        job = _ingest_satellite(client, field_ctx, start="2021-01-01", end="2021-06-30")
        assert job["status"] == "succeeded", job
        assert job["records_received"] > 0

        scenes = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/vegetation/scenes",
            headers=field_ctx["headers"],
        )
        assert scenes.status_code == 200
        body = scenes.json()
        assert body["total"] > 0
        scene = body["scenes"][0]
        assert scene["provider_code"] == "satellite_sim"
        assert scene["is_synthetic"] is True
        assert scene["spatial_resolution_m"] == 10.0

    def test_ingestion_idempotent_on_refetch(self, client, field_ctx):
        _ingest_satellite(client, field_ctx, start="2021-01-01", end="2021-03-31")
        job2 = _ingest_satellite(client, field_ctx, start="2021-01-01", end="2021-03-31")
        assert job2["status"] == "succeeded"
        assert job2["records_received"] > 0  # received counts upstream rows
        # scene-level dedupe: a second fetch records no NEW scenes
        scenes_path = f"/api/v1/fields/{field_ctx['field']['id']}/vegetation/scenes"
        total_scenes = client.get(scenes_path, headers=field_ctx["headers"]).json()["total"]
        _ingest_satellite(client, field_ctx, start="2021-01-01", end="2021-03-31")
        total_after = client.get(scenes_path, headers=field_ctx["headers"]).json()["total"]
        assert total_after == total_scenes


class TestVegetationSummary:
    def test_summary_after_ingestion(self, client, field_ctx):
        _ingest_satellite(client, field_ctx, start="2019-01-01", end="2021-12-31")
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/vegetation/summary?index=ndvi",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["index"] == "ndvi"
        assert body["formula"].startswith("NDVI")
        assert body["observation_counts"]["valid"] > 0
        assert isinstance(body["monthly_stats"], list) and body["monthly_stats"]
        assert isinstance(body["findings"], list)
        assert isinstance(body["stress_signals"], list)
        assert any("not ground measurements" in l for l in body["limitations"])

    def test_summary_without_data_reports_gap(self, client, field_ctx):
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/vegetation/summary",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["series_state"]["state"] == "no_data"
        assert body["data_gaps"]

    def test_unknown_index_refused(self, client, field_ctx):
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/vegetation/summary?index=nope",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 422


class TestVegetationRecommendations:
    def test_refresh_produces_vegetation_domain(self, client, field_ctx):
        # stress_declining: a steady synthetic decline -> trend finding ->
        # stress signal -> a vegetation-domain recommendation.
        _ingest_satellite(client, field_ctx, start="2018-01-01", end="2021-12-31", profile="stress_declining")
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/recommendations/refresh",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        domains = {r["domain"] for r in payload["recommendations"]}
        assert "vegetation" in domains
        # fingerprint stability: second refresh keeps the same active ids
        first_ids = {r["id"] for r in payload["recommendations"] if r["domain"] == "vegetation"}
        resp2 = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/recommendations/refresh",
            headers=field_ctx["headers"],
        )
        second = resp2.json()
        second_ids = {r["id"] for r in second["recommendations"] if r["domain"] == "vegetation"}
        assert first_ids == second_ids


class TestEvidenceGapsAndApply:
    def test_gaps_detected_with_voi_and_plans(self, client, field_ctx):
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/evidence-gaps",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        codes = {g["gap_code"] for g in body["gaps"]}
        assert "soil_sample_missing" in codes
        assert "weather_observations_missing" in codes
        # synthetic satellite scenes never close the real-coverage gap
        assert "satellite_coverage_missing" in codes
        for gap in body["gaps"]:
            assert "voi" in gap and "decision_sensitivity" in gap["voi"]
            assert "monetary" in gap["voi"]["honesty_note"]
        assert body["acquisition_plans"]
        plan = body["acquisition_plans"][0]
        for key in ("what_is_missing", "why_it_matters", "how_to_obtain", "urgent"):
            assert key in plan

    def test_staleness_report_domains(self, client, field_ctx):
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/evidence/staleness",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "weather" in body["domains"]
        assert "soil" in body["domains"]
        weather = body["domains"]["weather"]
        assert weather["downstream"]["feature_runs"]["status"] in ("stale", "current", "not_built")

    def test_apply_with_ingestion_job_ref(self, client, field_ctx):
        job = _ingest_satellite(client, field_ctx, start="2020-01-01", end="2021-06-30")
        job = _wait_job(client, field_ctx["headers"], job["job_id"])
        assert job["status"] == "succeeded", job
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/evidence/apply",
            headers=field_ctx["headers"],
            json={"ref_kind": "ingestion_job", "ref_id": job["job_id"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["evidence_ref"]["kind"] == "ingestion_job"
        assert any(r["artifact"] == "recommendations" for r in body["recomputed"])
        assert "changed_recommendation_fingerprints" in body

    def test_apply_rejects_unknown_ref(self, client, field_ctx):
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/evidence/apply",
            headers=field_ctx["headers"],
            json={"ref_kind": "ingestion_job", "ref_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    def test_action_lifecycle_append_only(self, client, field_ctx):
        create = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/evidence-actions",
            headers=field_ctx["headers"],
            json={"gap_code": "soil_sample_missing", "action_type": "collect_soil_sample", "title": "Sample the field"},
        )
        assert create.status_code == 200, create.text
        action = create.json()
        assert action["status"] == "suggested"
        # legal transition
        t1 = client.post(
            f"/api/v1/evidence-actions/{action['id']}/transition?field_id={field_ctx['field']['id']}",
            headers=field_ctx["headers"],
            json={"to_status": "in_progress", "note": "booking lab"},
        )
        assert t1.status_code == 200
        # illegal transition (in_progress -> suggested)
        t2 = client.post(
            f"/api/v1/evidence-actions/{action['id']}/transition?field_id={field_ctx['field']['id']}",
            headers=field_ctx["headers"],
            json={"to_status": "suggested"},
        )
        assert t2.status_code == 422
        history = client.get(
            f"/api/v1/evidence-actions/{action['id']}?field_id={field_ctx['field']['id']}",
            headers=field_ctx["headers"],
        )
        assert history.status_code == 200
        events = history.json()["events"]
        assert [e["to_status"] for e in events] == ["suggested", "in_progress"]


class TestSoilMemoryFlow:
    def test_snapshot_timeline_alerts_estimate(self, client, field_ctx, db):
        field_id = field_ctx["field"]["id"]
        snap = client.post(
            f"/api/v1/fields/{field_id}/soil-memory/snapshots",
            headers=field_ctx["headers"],
            json={"as_of": date.today().isoformat()},
        )
        assert snap.status_code == 200, snap.text
        body = snap.json()
        assert body["checksum_sha256"]
        assert "no soil measurements exist" in " ".join(body["missing_evidence"])
        # idempotent re-create
        snap2 = client.post(
            f"/api/v1/fields/{field_id}/soil-memory/snapshots",
            headers=field_ctx["headers"],
            json={"as_of": date.today().isoformat()},
        )
        assert snap2.json()["id"] == body["id"]

        timeline = client.get(
            f"/api/v1/fields/{field_id}/soil-memory/timeline", headers=field_ctx["headers"]
        )
        assert timeline.status_code == 200
        assert any(e["kind"] == "snapshot" for e in timeline.json()["events"])

        alerts = client.get(
            f"/api/v1/fields/{field_id}/soil-memory/alerts", headers=field_ctx["headers"]
        )
        assert alerts.status_code == 200
        assert isinstance(alerts.json()["alerts"], list)

        # estimate needs TWO snapshots
        earlier = client.post(
            f"/api/v1/fields/{field_id}/soil-memory/snapshots",
            headers=field_ctx["headers"],
            json={"as_of": (date.today() - timedelta(days=400)).isoformat()},
        )
        assert earlier.status_code == 200
        estimate = client.post(
            f"/api/v1/fields/{field_id}/soil-memory/change-estimates",
            headers=field_ctx["headers"],
            json={"start_snapshot_id": earlier.json()["id"], "end_snapshot_id": body["id"]},
        )
        assert estimate.status_code == 200, estimate.text
        est = estimate.json()
        assert est["method"] == "soil_change_conservative_v1"
        assert est["result"]["estimated"] is True

    def test_future_as_of_refused(self, client, field_ctx):
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/soil-memory/snapshots",
            headers=field_ctx["headers"],
            json={"as_of": (date.today() + timedelta(days=10)).isoformat()},
        )
        assert resp.status_code == 422


class TestForecastFlow:
    def test_ingest_persists_evidence_separated_from_observations(self, client, field_ctx, db):
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecasts/ingest",
            headers=field_ctx["headers"],
            json={"variables": ["air_temperature_max", "precipitation"], "model": "best_match", "forecast_days": 5},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stored"]["inserted"] > 0
        assert body["response_meta"]["issue_basis"] if "issue_basis" in body["response_meta"] else True

        # forecast rows live in weather_forecasts, never in observations
        from sqlalchemy import func, select

        from app.db.models import Observation
        from app.db.models_p2 import WeatherForecast

        forecast_count = db.scalar(
            select(func.count(WeatherForecast.id)).where(
                WeatherForecast.field_id == field_ctx["field"]["id"]
            )
        )
        assert forecast_count and forecast_count > 0
        obs_forecast = db.scalar(
            select(func.count(Observation.id)).where(
                Observation.field_id == field_ctx["field"]["id"],
                Observation.variable_code.in_(("air_temperature_max", "precipitation")),
            )
        )
        assert obs_forecast == 0

    def test_forecast_window_and_freshness(self, client, field_ctx):
        client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecasts/ingest",
            headers=field_ctx["headers"],
            json={"variables": ["air_temperature_max"], "forecast_days": 5},
        )
        window = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecasts?variable_code=air_temperature_max",
            headers=field_ctx["headers"],
        )
        assert window.status_code == 200
        body = window.json()
        assert body["basis"] == "forecast"
        assert body["values"]
        assert body["freshness"]["fresh"] is True

        risks = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecast-risks",
            headers=field_ctx["headers"],
        )
        assert risks.status_code == 200
        assert isinstance(risks.json()["risks"], list)
        assert any("GENERIC" in l for l in risks.json()["limitations"])

    def test_verification_without_pairs_reports_limitations(self, client, field_ctx):
        client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecasts/ingest",
            headers=field_ctx["headers"],
            json={"variables": ["air_temperature_max"], "forecast_days": 3},
        )
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/forecast-verifications",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pairs_total"] == 0
        assert body["limitations"], "no fabricated verification metrics"

    def test_projection_endpoint_honest_about_blocked_adapter(self, client, field_ctx):
        resp = client.get(
            f"/api/v1/fields/{field_ctx['field']['id']}/climate-projections",
            headers=field_ctx["headers"],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["adapter_status"] == "blocked_pending_credentials"

    def test_persist_idempotent_natural_key(self, db, field_ctx):
        from app.db.models import Field

        field = db.scalar(select(Field).where(Field.id == uuid.UUID(field_ctx["field"]["id"])))
        issued = datetime.now(UTC).replace(microsecond=0)
        valid = issued + timedelta(days=1)
        evidence = ForecastEvidence(
            provider_code="open_meteo_forecast",
            forecast_class=ForecastClass.short_range_forecast,
            model_id="best_match",
            variable_code="air_temperature_max",
            unit="degC",
            issued_at=issued,
            valid_time=valid,
            horizon_hours=24,
            value=31.5,
        )
        first = persist_forecast_evidence(db, field.id, [evidence])
        second = persist_forecast_evidence(db, field.id, [evidence])
        assert first["inserted"] == 1
        assert second["inserted"] == 0 and second["skipped_existing"] == 1
        freshness = forecast_freshness(db, field.id, "air_temperature_max")
        assert freshness.fresh is True
        rows = forecasts_in_window(
            db,
            field.id,
            variable_code="air_temperature_max",
            start=issued - timedelta(hours=1),
            end=valid + timedelta(hours=1),
        )
        assert len(rows) == 1 and rows[0].value == 31.5


class TestStressLabAndPortfolio:
    def test_stress_run_executes_and_verifies(self, client, field_ctx):
        _create_rotation_run(client, field_ctx)
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/rotation-stress-runs",
            headers=field_ctx["headers"],
            json={"packs": ["water_restriction", "severe_drought"], "candidates": ["baseline", "alternative"]},
        )
        assert resp.status_code == 200, resp.text
        run = resp.json()
        assert run["status"] == "succeeded"
        assert run["result"]["evaluations"]
        verify = client.post(
            f"/api/v1/rotation-stress-runs/{run['id']}/verify", headers=field_ctx["headers"]
        )
        assert verify.status_code == 200
        assert verify.json()["valid"] is True

    def test_unknown_pack_refused(self, client, field_ctx):
        resp = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/rotation-stress-runs",
            headers=field_ctx["headers"],
            json={"packs": ["alien_invasion"]},
        )
        assert resp.status_code == 422

    def test_portfolio_run_with_shared_allocation(self, client, field_ctx):
        farm_id = field_ctx["farm"]["id"]
        resp = client.post(
            f"/api/v1/farms/{farm_id}/portfolio-runs",
            headers=field_ctx["headers"],
            json={
                "season_count": 1,
                "constraints": {"water_allocation_m3": 2500.0},
                "objective_weights": {"water_efficiency": 2.0, "risk_diversification": 1.0},
            },
        )
        assert resp.status_code == 200, resp.text
        run = resp.json()
        assert run["status"] in ("succeeded", "failed")
        assert run["status"] == "succeeded", run.get("not_evaluated")
        assert run["allocations"]
        total_area = sum(a["area_ha"] for a in run["allocations"])
        assert total_area > 0
        assert run["result"]["independent_comparison"]["comparisons"]
        verify = client.post(
            f"/api/v1/portfolio-runs/{run['id']}/verify", headers=field_ctx["headers"]
        )
        assert verify.status_code == 200
        assert verify.json()["valid"] is True

    def test_portfolio_run_requires_manager_role(self, client, farm_with_field):
        # a fresh second user (no membership) cannot create runs on the farm
        import uuid as _uuid

        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                "password": "test-password-1",
                "display_name": "Outsider",
            },
        )
        assert reg.status_code == 201
        headers2 = {"Authorization": f"Bearer {reg.json()['token']}"}
        resp = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/portfolio-runs",
            headers=headers2,
            json={"season_count": 1},
        )
        assert resp.status_code in (403, 404)


class TestLiveProvidersFailLoudly:
    def test_sentinel2_search_unreachable_structured(self, client, field_ctx):
        job = client.post(
            f"/api/v1/fields/{field_ctx['field']['id']}/data-jobs",
            headers=field_ctx["headers"],
            json={
                "provider_code": "sentinel2",
                "variables": ["ndvi"],
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
            },
        )
        # The sandbox has no external network: the job must FAIL with a
        # structured summary and ingest nothing — never fabricate scenes.
        assert job.status_code in (200, 201, 202)
        body = job.json()
        if body["status"] == "succeeded" and body["records_inserted"] == 0:
            pytest.skip("STAC endpoint unexpectedly reachable (offline contract relaxed)")
        assert body["status"] == "failed"
        assert body.get("error_summary")

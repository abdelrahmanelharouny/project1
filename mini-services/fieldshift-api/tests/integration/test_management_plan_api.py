"""Integration: management plan aggregation API (M6C Increment 8)."""

import uuid


def _register(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": f"user-{uuid.uuid4().hex[:10]}@test.local",
              "password": "test-password-1", "display_name": "Farmer"},
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}, resp.json()


def _farm_and_field(client, headers):
    farm = client.post(
        "/api/v1/farms", headers=headers,
        json={"name": "Plan Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    ).json()
    field = client.post(
        f"/api/v1/farms/{farm['id']}/fields", headers=headers,
        json={
            "name": "Plan Field",
            "geometry": {"type": "Polygon", "coordinates": [
                [[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]]},
        },
    ).json()
    return farm, field


class TestManagementPlan:
    def test_aggregated_plan_empty_field_honest(self, client):
        headers, _ = _register(client)
        _, field = _farm_and_field(client, headers)
        resp = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers, json={}
        )
        assert resp.status_code == 201, resp.text
        plan = resp.json()
        result = plan["result"]
        # every section present, honest about missing data
        for section in ("season_context", "soil_cover", "cover_crop", "residue",
                        "erosion", "operations", "practice_guidance", "water", "checks"):
            assert section in result, section
        assert result["season_context"]["status"] == "not_evaluated"
        assert result["residue"]["status"] == "not_evaluated"
        assert result["cover_crop"]["status"] == "not_evaluated"
        # practice guidance from the bundled active pack
        practices = result["practice_guidance"]["practices"]
        assert len(practices) >= 10
        assert all(p["validation_status"] == "reference" for p in practices)
        # unresolved checks reference the missing data
        codes = {c["code"] for c in result["checks"]}
        assert "no_crop_history" in codes
        assert "cover_entirely_unknown" in codes
        # window metrics partition the (default, trailing-year) window
        m = result["soil_cover"]["metrics"]
        assert m["days_protective_cover"] + m["days_known_bare"] + m["days_unknown"] == m["window_days"]
        assert plan["checksum_sha256"]

    def test_aggregated_plan_with_data(self, client):
        headers, _ = _register(client)
        _, field = _farm_and_field(client, headers)
        fid = field["id"]
        client.post(
            f"/api/v1/fields/{fid}/crop-history", headers=headers,
            json={"crop_label": "maize", "sowing_date": "2026-05-01",
                  "harvest_date": "2026-08-15", "season_label": "summer_2026"},
        )
        client.post(
            f"/api/v1/fields/{fid}/operations", headers=headers,
            json={"operation_type": "tillage", "title": "Seedbed",
                  "duration_estimate_hours": 8.0,
                  "resource_requirements": [{"resource_type": "tractor"}]},
        )
        resp = client.post(
            f"/api/v1/fields/{fid}/management-plans", headers=headers,
            json={"window_start": "2026-01-01", "window_end": "2026-12-31",
                  "season_label": "summer_2026"},
        )
        assert resp.status_code == 201
        plan = resp.json()
        result = plan["result"]
        assert result["season_context"]["status"] == "evaluated"
        assert result["season_context"]["recent_crop_history"][0]["crop_label"] == "maize"
        assert result["soil_cover"]["metrics"]["days_protective_cover"] == 107
        assert result["operations"]["counts"]["total"] == 1
        assert result["operations"]["counts"]["planned"] == 1
        codes = {c["code"] for c in result["checks"]}
        assert "operations_unscheduled" in codes

    def test_plan_reproducible_and_idempotent(self, client):
        headers, _ = _register(client)
        _, field = _farm_and_field(client, headers)
        key = f"plan-{uuid.uuid4().hex[:8]}"
        r1 = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers,
            json={"idempotency_key": key},
        ).json()
        r2 = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers,
            json={"idempotency_key": key},
        ).json()
        assert r1["id"] == r2["id"]
        # without the key: identical inputs → identical checksum (new snapshot)
        r3 = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers, json={}
        ).json()
        assert r3["checksum_sha256"] == r1["checksum_sha256"]

    def test_plan_detail_tenant_isolated(self, client):
        headers, _ = _register(client)
        _, field = _farm_and_field(client, headers)
        plan = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers, json={}
        ).json()
        r = client.post("/api/v1/auth/register", json={
            "email": f"user-{uuid.uuid4().hex[:10]}@test.local",
            "password": "test-password-1", "display_name": "Other"})
        assert r.status_code == 201, r.text
        other = r.json()
        resp = client.get(
            f"/api/v1/management-plans/{plan['id']}",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 403

    def test_feedback_roundtrip(self, client):
        headers, _ = _register(client)
        _, field = _farm_and_field(client, headers)
        plan = client.post(
            f"/api/v1/fields/{field['id']}/management-plans", headers=headers, json={}
        ).json()
        resp = client.post(
            f"/api/v1/management-plans/{plan['id']}/feedback", headers=headers,
            json={"author_role": "farmer", "rating": 4, "accepted": True,
                  "comment": "Will try the cover crop after termination advice."},
        )
        assert resp.status_code == 201
        assert resp.json()["rating"] == 4
        bad = client.post(
            f"/api/v1/management-plans/{plan['id']}/feedback", headers=headers,
            json={"author_role": "farmer", "rating": 9},
        )
        assert bad.status_code == 422


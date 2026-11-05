"""Integration: soil-cover observation CRUD + timeline/metrics APIs
(M6C Increment 3). Tenant isolation mirrors the platform-wide 403 contract.
"""

import uuid


class TestCoverObservations:
    def test_create_and_list_observation(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/soil-cover/observations",
            headers=headers,
            json={
                "observed_date": "2026-03-15",
                "cover_state": "bare",
                "measurement_basis": "visual_estimate",
                "notes": "after harvest, before planting",
            },
        )
        assert resp.status_code == 201, resp.text
        obs = resp.json()
        assert obs["cover_state"] == "bare"
        assert obs["evidence_class"] == "farmer_reported_record"

        listed = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/observations", headers=headers
        )
        assert listed.status_code == 200
        assert any(o["id"] == obs["id"] for o in listed.json()["items"])

    def test_unknown_state_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/soil-cover/observations",
            headers=headers,
            json={"observed_date": "2026-03-15", "cover_state": "jungle"},
        )
        assert resp.status_code == 422

    def test_fraction_out_of_range_rejected_never_clamped(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        for bad in (-0.1, 1.5, 42):
            resp = client.post(
                f"/api/v1/fields/{field_id}/soil-cover/observations",
                headers=headers,
                json={"observed_date": "2026-03-15", "cover_state": "unknown", "cover_fraction": bad},
            )
            assert resp.status_code == 422, f"fraction {bad} must be rejected"

    def test_index_needs_type_and_value_together(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/soil-cover/observations",
            headers=headers,
            json={"observed_date": "2026-03-15", "cover_state": "unknown", "index_value": 0.62},
        )
        assert resp.status_code == 422
        resp = client.post(
            f"/api/v1/fields/{field_id}/soil-cover/observations",
            headers=headers,
            json={
                "observed_date": "2026-03-15",
                "cover_state": "unknown",
                "index_type": "ndvi",
                "index_value": 0.62,
                "measurement_basis": "remote_sensing_index",
                "metadata": {"provider": "test", "product": "test-product"},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["evidence_class"] == "remote_sensing_estimate"

    def test_tenant_isolation_403(self, client, farm_with_field):
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        field_id = farm_with_field["field"]["id"]
        resp = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/observations",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 403


class TestTimelineAndMetrics:
    def _seed_history(self, client, farm_with_field):
        """Create crop history via the rotation API (real flow)."""
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/crop-history",
            headers=headers,
            json={
                "crop_label": "maize",
                "sowing_date": "2026-05-01",
                "harvest_date": "2026-08-15",
                "season_label": "summer_2026",
            },
        )
        assert resp.status_code == 201, resp.text
        return field_id

    def test_timeline_from_crop_history(self, client, farm_with_field):
        field_id = self._seed_history(client, farm_with_field)
        headers = farm_with_field["headers"]
        resp = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/timeline",
            headers=headers,
            params={"window_start": "2026-01-01", "window_end": "2026-12-31"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["inputs_summary"]["crop_history_rows"] == 1
        m = data["metrics"]
        assert m["days_protective_cover"] == 107  # hand-computed golden
        assert m["days_known_bare"] == 0
        assert m["days_unknown"] == 365 - 107
        assert data["thresholds"]["applicable"] == []
        day = next(d for d in data["timeline"] if d["date"] == "2026-06-01")
        assert day["classification"] == "protective"
        assert day["states"] == ["living_main_crop"]

    def test_metrics_endpoint_matches_timeline(self, client, farm_with_field):
        field_id = self._seed_history(client, farm_with_field)
        headers = farm_with_field["headers"]
        params = {"window_start": "2026-01-01", "window_end": "2026-12-31"}
        tl = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/timeline", headers=headers, params=params
        ).json()
        mx = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/metrics", headers=headers, params=params
        ).json()
        assert mx["metrics"] == tl["metrics"]

    def test_timeline_requires_window(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/soil-cover/timeline", headers=headers)
        assert resp.status_code == 422

    def test_timeline_rejects_inverted_window(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/timeline",
            headers=headers,
            params={"window_start": "2026-12-31", "window_end": "2026-01-01"},
        )
        assert resp.status_code == 422

    def test_timeline_tenant_isolated(self, client, farm_with_field):
        field_id = self._seed_history(client, farm_with_field)
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        resp = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/timeline",
            headers={"Authorization": f"Bearer {other['token']}"},
            params={"window_start": "2026-01-01", "window_end": "2026-12-31"},
        )
        assert resp.status_code == 403

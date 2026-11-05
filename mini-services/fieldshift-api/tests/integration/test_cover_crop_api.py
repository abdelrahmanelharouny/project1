"""Integration: cover-crop plan API (M6C Increment 4) + cross-module link
into the soil-cover timeline. Uses the REAL bundled knowledge base (faba_bean
is the only cover-crop-capable species, with its deliberate Kc gap)."""

import uuid


class TestCoverCropPlans:
    def _create_plan(self, client, farm_with_field, **overrides):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        body = {
            "window_start": "2026-09-01",
            "window_end": "2026-12-20",
            "next_crop_label": "maize",
        }
        body.update(overrides)
        return client.post(
            f"/api/v1/fields/{field_id}/cover-crop-plans", headers=headers, json=body
        )

    def test_plan_with_real_knowledge_base(self, client, farm_with_field):
        resp = self._create_plan(client, farm_with_field)
        assert resp.status_code == 201, resp.text
        plan = resp.json()
        assert plan["status"] == "succeeded"
        assert plan["engine_version"] == "management-engine-1.0.0"
        assert plan["checksum_sha256"]
        candidates = plan["result"]["candidates"]
        # faba_bean is the seed pack's only cover-crop-capable species
        codes = {c["crop_code"] for c in candidates}
        assert "faba_bean" in codes
        faba = next(c for c in candidates if c["crop_code"] == "faba_bean")
        # honesty: without a feature run there is no climate evidence, and
        # faba_bean has no Kc — either way the water dimension is unevaluated
        assert faba["status"] == "conditional"
        dims = faba["dimensions"]
        assert dims["water_trade_off"]["status"] == "not_evaluated"
        assert (
            "no climate evidence" in dims["water_trade_off"]["message"]
            or "no sourced Kc" in dims["water_trade_off"]["message"]
        )
        assert dims["termination"]["status"] == "not_evaluated"
        cond_codes = {c["code"] for c in faba["conditions"]}
        assert "water_trade_off_not_evaluated" in cond_codes
        assert "termination_not_evaluated" in cond_codes
        # functions come only from sourced traits (Herridge n-fixation exists)
        fn = {f["function_code"] for f in faba["functions"]}
        assert "nitrogen_fixation" in fn
        # the trade-off note is always present (cover ≠ universal win)
        assert "trade-off" in faba["trade_off_note"].lower()

    def test_plan_without_feature_run_warns(self, client, farm_with_field):
        resp = self._create_plan(client, farm_with_field)
        plan = resp.json()
        assert any("feature run" in w for w in plan["warnings"])

    def test_plan_reproducible_checksum(self, client, farm_with_field):
        first = self._create_plan(client, farm_with_field).json()
        second = self._create_plan(client, farm_with_field).json()
        assert first["checksum_sha256"] == second["checksum_sha256"]
        assert first["id"] != second["id"]  # new immutable snapshot each run

    def test_plan_idempotency_key(self, client, farm_with_field):
        key = f"cov-{uuid.uuid4().hex[:8]}"
        first = self._create_plan(client, farm_with_field, idempotency_key=key).json()
        second = self._create_plan(client, farm_with_field, idempotency_key=key).json()
        assert first["id"] == second["id"]

    def test_plan_list_and_detail(self, client, farm_with_field):
        created = self._create_plan(client, farm_with_field).json()
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        listing = client.get(
            f"/api/v1/fields/{field_id}/cover-crop-plans", headers=headers
        ).json()
        assert listing["total"] >= 1
        detail = client.get(
            f"/api/v1/cover-crop-plans/{created['id']}", headers=headers
        ).json()
        assert detail["id"] == created["id"]
        assert detail["result"]["candidates"]

    def test_plan_detail_tenant_isolated(self, client, farm_with_field):
        created = self._create_plan(client, farm_with_field).json()
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        resp = client.get(
            f"/api/v1/cover-crop-plans/{created['id']}",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 403

    def test_plan_window_validation(self, client, farm_with_field):
        resp = self._create_plan(
            client, farm_with_field, window_start="2026-12-20", window_end="2026-09-01"
        )
        assert resp.status_code == 422


class TestCoverCropPlanItems:
    def test_create_and_list_item(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/cover-crop-plan-items",
            headers=headers,
            json={
                "crop_label": "faba_bean",
                "season_label": "winter_2026",
                "intended_sowing_start": "2026-10-01",
                "intended_sowing_end": "2026-10-20",
                "intended_termination_window_start": "2027-01-15",
                "intended_termination_window_end": "2027-02-10",
                "intended_functions": ["soil_protection"],
            },
        )
        assert resp.status_code == 201, resp.text
        item = resp.json()
        assert item["status"] == "planned"
        assert item["evidence_class"] == "farmer_reported_record"
        listed = client.get(
            f"/api/v1/fields/{field_id}/cover-crop-plan-items", headers=headers
        ).json()
        assert any(i["id"] == item["id"] for i in listed["items"])

    def test_mixture_fraction_sum_beyond_one_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/cover-crop-plan-items",
            headers=headers,
            json={
                "crop_label": "mix A+B",
                "is_mixture": True,
                "mixture_composition": [
                    {"crop_label": "faba_bean", "fraction": 0.6},
                    {"crop_label": "barley", "fraction": 0.7},
                ],
            },
        )
        assert resp.status_code == 422
        assert "never silently renormalized" in resp.json()["error"]["message"]

    def test_item_plan_run_must_belong_to_field(self, client, farm_with_field):
        """A plan item may only reference a plan run of its own field."""
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        # a plan belonging to THIS field
        plan = client.post(
            f"/api/v1/fields/{field_id}/cover-crop-plans",
            headers=headers,
            json={"window_start": "2026-09-01", "window_end": "2026-12-20"},
        ).json()
        # another user's field
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        other_farm = client.post(
            "/api/v1/farms", headers=other_headers,
            json={"name": "Farm B", "country_code": "EG", "timezone": "Africa/Cairo"},
        ).json()
        other_field = client.post(
            f"/api/v1/farms/{other_farm['id']}/fields", headers=other_headers,
            json={
                "name": "Field B",
                "geometry": {"type": "Polygon", "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]]},
            },
        ).json()
        resp = client.post(
            f"/api/v1/fields/{other_field['id']}/cover-crop-plan-items",
            headers=other_headers,
            json={"crop_label": "faba_bean", "plan_run_id": plan["id"]},
        )
        assert resp.status_code == 422
        assert "does not reference a plan of this field" in resp.json()["error"]["message"]

    def test_item_feeds_soil_cover_timeline(self, client, farm_with_field):
        """Cross-module: an adopted cover item appears in the cover timeline
        as living_cover_crop over its intended window."""
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/cover-crop-plan-items",
            headers=headers,
            json={
                "crop_label": "faba_bean",
                "intended_sowing_start": "2026-10-01",
                "intended_termination_window_start": "2027-01-15",
            },
        )
        assert resp.status_code == 201
        timeline = client.get(
            f"/api/v1/fields/{field_id}/soil-cover/timeline",
            headers=headers,
            params={"window_start": "2026-09-01", "window_end": "2027-03-31"},
        ).json()
        m = timeline["metrics"]
        # Oct 1 .. Jan 15 = 31+30+31+15 = 107 days of living_cover_crop
        assert m["state_day_counts"].get("living_cover_crop") == 107

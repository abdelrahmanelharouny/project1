"""Integration: rotation candidate generation + optimization runs through the
API — reproducibility, honest statuses, tenant isolation (Milestone 5)."""

import uuid
from datetime import date

import pytest


def _setup_field(client, headers):
    farm_resp = client.post(
        "/api/v1/farms", headers=headers,
        json={"name": "Rotation Farm", "country_code": "EG", "timezone": "Africa/Cairo",
              "currency_code": "EGP"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields", headers=headers,
        json={
            "name": "Rot Field",
            "geometry": {"type": "Polygon", "coordinates": [
                [[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]]},
        },
    )
    assert field_resp.status_code == 201, field_resp.text
    return farm, field_resp.json()


def _ingest_synthetic(client, headers, field_id):
    resp = client.post(
        f"/api/v1/fields/{field_id}/data-jobs", headers=headers,
        json={"provider_code": "synthetic", "variables":
              ["precipitation", "air_temperature_mean", "air_temperature_max", "reference_et0"],
              "start_date": "2023-01-01", "end_date": "2023-12-31",
              "profile": "semi_arid", "seed": 42},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


def _feature_run(client, headers, field_id):
    resp = client.post(
        f"/api/v1/fields/{field_id}/feature-runs", headers=headers,
        json={"start_date": "2023-01-01", "end_date": "2023-12-31",
              "aggregation_levels": ["monthly"]},
    )
    assert resp.status_code == 202, resp.text
    runs = client.get(f"/api/v1/fields/{field_id}/feature-runs", headers=headers).json()
    return runs["items"][0]["run_id"]


WINTER = {"label": "winter_2025", "start_date": "2024-12-01", "end_date": "2025-03-31"}
SUMMER = {"label": "summer_2025", "start_date": "2025-05-01", "end_date": "2025-09-15"}
BARLEY_SPRING = {
    "label": "barley_spring_2025",
    "start_date": "2025-03-01",
    "end_date": "2025-06-28",
}


@pytest.fixture()
def prepared_field(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest_synthetic(client, headers, field_id)
    run_id = _feature_run(client, headers, field_id)
    # crop history: maize last summer
    resp = client.post(f"/api/v1/fields/{field_id}/crop-history", headers=headers,
                       json={"crop_code": "maize", "crop_label": "Maize (2023)",
                             "sowing_date": "2023-05-01", "harvest_date": "2023-09-15",
                             "season_label": "summer_2023"})
    assert resp.status_code == 201, resp.text
    return {**farm_with_field, "feature_run_id": run_id}


class TestCropHistory:
    def test_add_and_list(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/crop-history", headers=headers,
                           json={"crop_label": "Unknown legacy crop", "season_label": "2022"})
        assert resp.status_code == 201
        listing = client.get(f"/api/v1/fields/{field_id}/crop-history", headers=headers).json()
        labels = [i["crop_label"] for i in listing["items"]]
        assert "Unknown legacy crop" in labels

    def test_unknown_crop_code_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/crop-history", headers=headers,
                           json={"crop_code": "not_a_crop", "crop_label": "X"})
        assert resp.status_code == 422

    def test_tenant_isolation(self, client, farm_with_field):
        import uuid as _uuid

        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        field_id = farm_with_field["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/crop-history", headers=other)
        assert resp.status_code == 403


class TestCandidateGenerationApi:
    def test_candidates_with_statuses_and_explanations(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/crop-candidates", headers=headers,
            json={"seasons": [WINTER, SUMMER], "hemisphere": "north"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["evidence_run_id"]
        assert data["knowledge_pack_refs"]
        assert data["seasons"]
        for season in data["seasons"]:
            assert season["candidates"]
            for c in season["candidates"]:
                assert c["status"] in ("eligible", "conditionally_eligible", "excluded", "unevaluated")
                assert isinstance(c["reasons"], list)
        counts = data["counts_by_season"]
        winter = next(s for s in data["seasons"] if s["season_label"] == "winter_2025")
        codes = {c["crop_code"]: c["status"] for c in winter["candidates"]}
        assert codes["cotton"] == "excluded"  # calendar: cotton is a summer crop
        summer = next(s for s in data["seasons"] if s["season_label"] == "summer_2025")
        summer_codes = {c["crop_code"]: c["status"] for c in summer["candidates"]}
        assert summer_codes["wheat_spring"] == "excluded"

    def test_synthetic_warning_surfaced(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/crop-candidates", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north"},
        )
        data = resp.json()
        assert any("SYNTHETIC" in w for w in data["warnings"])


class TestRotationRunsApi:
    def test_full_run_with_strategies_and_explanations(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [WINTER, SUMMER], "hemisphere": "north",
                  "strategy_profiles": ["water_priority", "balanced", "soil_health_priority"]},
        )
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["status"] == "succeeded"
        assert run["solver_status"] in ("optimal", "feasible")
        assert run["rotation_engine_version"]
        assert run["knowledge_pack_refs"]

        detail = client.get(f"/api/v1/rotation-runs/{run['id']}", headers=headers).json()
        strategies = detail["strategies"]
        assert len(strategies) >= 3
        baseline = next(s for s in strategies if s["is_baseline"])
        assert baseline["strategy_kind"] == "baseline"
        for s in strategies:
            assert s["checksum_sha256"]
            exp = s["explanations"]
            for block in ("why_generated", "recommendation", "constraints_checked",
                          "criteria_evaluation", "evidence_references", "data_limitations",
                          "expected_benefits", "risks_trade_offs",
                          "local_expert_validation_required"):
                assert block in exp
            assert any("screening estimate" in l for l in exp["data_limitations"])
            # constraint checks present with statuses
            assert s["constraints_checked"]
        baseline_assign = {a["season_label"]: a["crop_code"] for a in baseline["assignment"]}
        # history maize is matched only to overlapping seasons; planning seasons
        # don't overlap summer_2023 → baseline is honestly empty
        assert baseline_assign == {"winter_2025": None, "summer_2025": None}

    def test_no_silent_hard_constraint_relaxation(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north",
                  "strategy_profiles": ["water_priority"]},
        )
        run = resp.json()
        detail = client.get(f"/api/v1/rotation-runs/{run['id']}", headers=headers).json()
        for s in detail["strategies"]:
            if s["is_baseline"]:
                continue
            for check in s["constraints_checked"]:
                assert check["status"] != "violated", check

    def test_infeasible_reported_with_conflict(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north",
                  "strategy_profiles": ["water_priority"], "water_allocation_m3": 100.0},
        )
        run = resp.json()
        assert run["status"] == "succeeded"  # the JOB succeeded
        assert run["solver_status"] == "infeasible"
        profiles = run["infeasibility_details"]["profiles"]
        assert profiles
        conflicts = profiles[0]["conflicts"]
        assert any(c["constraint"] == "water_allocation" for c in conflicts)

    def test_water_respected_when_feasible(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        # Spring barley's 120-day crop cycle fits Mar 1–Jun 28. The former
        # Dec–Mar window correctly excluded barley before water feasibility.
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [BARLEY_SPRING], "hemisphere": "north",
                  "strategy_profiles": ["water_priority"], "water_allocation_m3": 3000000.0},
        )
        run = resp.json()
        assert run["solver_status"] in ("optimal", "feasible")
        detail = client.get(f"/api/v1/rotation-runs/{run['id']}", headers=headers).json()
        optimized = [s for s in detail["strategies"] if not s["is_baseline"]][0]
        assignment = {a["season_label"]: a["crop_code"] for a in optimized["assignment"]}
        water_check = next(c for c in optimized["constraints_checked"] if c["constraint_code"] == "water_allocation")
        assert water_check["status"] == "satisfied"

    def test_comparison_endpoint(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        run = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [WINTER, SUMMER], "hemisphere": "north"},
        ).json()
        resp = client.get(f"/api/v1/rotation-runs/{run['id']}/comparison", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["criterion_codes"]
        for s in data["strategies"]:
            assert set(s["criteria"].keys()) == set(data["criterion_codes"])

    def test_reproducible_runs_same_checksums(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        payload = {"seasons": [WINTER, SUMMER], "hemisphere": "north",
                   "strategy_profiles": ["balanced"]}
        run1 = client.post(f"/api/v1/fields/{field_id}/rotation-runs", headers=headers, json=payload).json()
        run2 = client.post(f"/api/v1/fields/{field_id}/rotation-runs", headers=headers, json=payload).json()
        d1 = client.get(f"/api/v1/rotation-runs/{run1['id']}", headers=headers).json()
        d2 = client.get(f"/api/v1/rotation-runs/{run2['id']}", headers=headers).json()
        c1 = {s["strategy_key"]: s["checksum_sha256"] for s in d1["strategies"]}
        c2 = {s["strategy_key"]: s["checksum_sha256"] for s in d2["strategies"]}
        assert c1 == c2

    def test_idempotency_key(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        payload = {"seasons": [SUMMER], "hemisphere": "north",
                   "idempotency_key": "rot-key-1"}
        r1 = client.post(f"/api/v1/fields/{field_id}/rotation-runs", headers=headers, json=payload).json()
        r2 = client.post(f"/api/v1/fields/{field_id}/rotation-runs", headers=headers, json=payload).json()
        assert r1["id"] == r2["id"]

    def test_tenant_isolation_on_runs(self, client, prepared_field):
        import uuid as _uuid

        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        field_id = prepared_field["field"]["id"]
        run = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=prepared_field["headers"],
            json={"seasons": [SUMMER], "hemisphere": "north"},
        ).json()
        resp = client.get(f"/api/v1/rotation-runs/{run['id']}", headers=other)
        assert resp.status_code == 403
        resp = client.get(f"/api/v1/fields/{field_id}/rotation-runs", headers=other)
        assert resp.status_code == 403

    def test_custom_weights(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north",
                  "strategy_profiles": ["custom"],
                  "custom_weights": {"cover_crop_opportunity": 0.7, "soil_health_index": 0.3}},
        )
        assert resp.status_code == 202, resp.text
        run = resp.json()
        detail = client.get(f"/api/v1/rotation-runs/{run['id']}", headers=headers).json()
        custom = next(s for s in detail["strategies"] if s["strategy_key"] == "custom")
        assert custom["profile_weights"]["cover_crop_opportunity"] == 0.7

    def test_unknown_profile_rejected(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north",
                  "strategy_profiles": ["max_profit"]},
        )
        assert resp.status_code == 422

    def test_passport_rotation_readiness_becomes_available(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        client.post(
            f"/api/v1/fields/{field_id}/rotation-runs", headers=headers,
            json={"seasons": [SUMMER], "hemisphere": "north"},
        )
        passport = client.get(f"/api/v1/fields/{field_id}/data-passport", headers=headers).json()
        rot = next(a for a in passport["analyses"] if a["analysis_code"] == "rotation_optimization")
        assert rot["status"] == "available"
        assert not rot["missing_inputs"]

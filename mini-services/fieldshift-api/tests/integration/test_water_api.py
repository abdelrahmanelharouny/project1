"""Integration: water intelligence API (Milestone 6A) — methodology catalog,
readiness matrix, plan create/list/get, honest missing evidence, tenant
isolation, reproducibility."""

import uuid
from datetime import date

import pytest


def _setup_field(client, headers, name="Water Field"):
    farm_resp = client.post(
        "/api/v1/farms", headers=headers,
        json={"name": f"Farm {name}", "country_code": "EG", "timezone": "Africa/Cairo",
              "currency_code": "EGP"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields", headers=headers,
        json={
            "name": name,
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


SUMMER = {"label": "summer_2025", "start_date": "2025-05-01", "end_date": "2025-09-15"}


@pytest.fixture()
def prepared_field(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest_synthetic(client, headers, field_id)
    run_id = _feature_run(client, headers, field_id)
    return {**farm_with_field, "feature_run_id": run_id}


class TestWaterMethodsCatalog:
    def test_methods_endpoint_public_and_versioned(self, client):
        resp = client.get("/api/v1/water/methods")
        assert resp.status_code == 200
        data = resp.json()
        assert data["water_engine_version"] == "water-engine-1.0.0"
        assert data["methods_version"] == "water-methods-1.0.0"
        codes = {m["code"] for m in data["effective_rainfall_methods"]}
        assert {"fao_aglw_1986", "constant_fraction", "none"} <= codes
        assert any("Paper 33" in m["citation_text"]
                   for m in data["effective_rainfall_methods"]
                   if m["code"] == "fao_aglw_1986")
        classes = {c["method_class"]: c["efficiency"] for c in data["irrigation_efficiency_classes"]}
        assert classes == {"surface": 0.60, "sprinkler": 0.75, "drip": 0.90}
        # unverified methods are explicitly listed as not implemented
        not_impl = {item["item"] for item in data["not_implemented"]}
        assert any("USDA-SCS" in item for item in not_impl)
        assert any("ET0" in item for item in not_impl)

    def test_unit_identities_exposed(self, client):
        data = client.get("/api/v1/water/methods").json()
        assert data["unit_identities"]["mm_over_ha_to_m3"] == 10.0


class TestReadinessMatrixEndpoint:
    def test_matrix_lists_all_crops_with_statuses(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/water/knowledge-readiness", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        crops = {c["crop_code"]: c for c in data["crops"]}
        assert "maize" in crops and "faba_bean" in crops
        assert crops["maize"]["etc_computable"] is True
        assert crops["faba_bean"]["etc_computable"] is False
        assert crops["faba_bean"]["overall"] == "missing"
        assert crops["maize"]["dimensions"]["kc_anchors"]["status"] == "complete"
        assert "citation" in crops["maize"]["dimensions"]["kc_anchors"]["source"]["citation_text"].lower() or \
               "Allen" in crops["maize"]["dimensions"]["kc_anchors"]["source"]["citation_text"]
        # stress sensitivity now documented (M6A pack v2026.11.1)
        assert crops["maize"]["dimensions"]["stress_sensitivity"]["status"] in ("partial", "complete")
        assert data["summary"]["total_crops"] >= 11

    def test_tenant_isolation(self, client, prepared_field):
        import uuid as _uuid

        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        field_id = prepared_field["field"]["id"]
        assert client.get(
            f"/api/v1/fields/{field_id}/water/knowledge-readiness", headers=other
        ).status_code == 403
        assert client.get(
            f"/api/v1/fields/{field_id}/water-plans", headers=other
        ).status_code == 403


class TestWaterPlanLifecycle:
    def _plan_request(self, prepared_field, **overrides):
        body = {
            "label": "Summer plan",
            "seasons": [SUMMER],
            "crop_assignments": [{"crop_code": "maize"}],
            "effective_rainfall_method": "fao_aglw_1986",
            "evidence_run_id": prepared_field["feature_run_id"],
            "water_allocation_m3": 45000.0,
        }
        body.update(overrides)
        return body

    def test_create_plan_with_synthetic_evidence(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans",
                           headers=headers, json=self._plan_request(prepared_field))
        assert resp.status_code == 201, resp.text
        plan = resp.json()
        assert plan["status"] == "succeeded"
        assert plan["water_engine_version"] == "water-engine-1.0.0"
        assert plan["checksum_sha256"]
        # synthetic banner must be present end-to-end
        assert any("SYNTHETIC" in w for w in plan["warnings"])
        result = plan["result"]
        season = result["seasons"][0]
        assert season["crop_code"] == "maize"
        totals = season["totals"]
        assert totals["etc_mm"] is not None
        assert totals["net_irrigation_requirement_mm"] is not None
        assert totals["volumes_m3"]["net_irrigation_requirement_m3"] > 0
        # stage + monthly structure
        assert [s["stage"] for s in season["stages"]] == ["initial", "development", "mid", "late"]
        assert len(season["months"]) == 5
        # ladder honesty
        ladder = {s["quantity"]: s for s in season["ladder"]}
        assert ladder["actual_irrigation_applied"]["status"] == "not_supplied"
        assert ladder["gross_irrigation_requirement"]["status"] == "not_evaluated"

    def test_plan_reproducibility_same_inputs_same_checksum(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        r1 = client.post(f"/api/v1/fields/{field_id}/water-plans",
                         headers=headers, json=self._plan_request(prepared_field)).json()
        r2 = client.post(f"/api/v1/fields/{field_id}/water-plans",
                         headers=headers, json=self._plan_request(prepared_field)).json()
        assert r1["checksum_sha256"] == r2["checksum_sha256"]
        # distinct plans persisted (immutable snapshots)
        listing = client.get(f"/api/v1/fields/{field_id}/water-plans", headers=headers).json()
        assert len(listing["items"]) == 2

    def test_idempotency_key_replays(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(prepared_field, idempotency_key="plan-key-1")
        r1 = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body)
        r2 = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body)
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

    def test_get_plan_detail(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans",
                           headers=headers, json=self._plan_request(prepared_field)).json()
        got = client.get(f"/api/v1/water-plans/{plan['id']}", headers=headers)
        assert got.status_code == 200
        assert got.json()["result"]["seasons"][0]["crop_code"] == "maize"

    def test_farmer_soil_layer_runs_root_zone_balance(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(
            prepared_field,
            soil_source="farmer_measured",
            farmer_soil={"theta_fc": 0.32, "theta_wp": 0.15, "zr_m": 1.35, "p_table": 0.55},
        )
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body).json()
        season = plan["result"]["seasons"][0]
        rz = season["root_zone"]
        assert rz["source_label"] == "farmer_measured"
        assert rz["taw_mm"] == pytest.approx(1000 * 0.17 * 1.35, abs=0.5)
        assert rz["raw_mm"] is not None
        assert season["totals"]["soil_water_contribution_mm"] is not None
        assert len(season["deficit_windows"]) >= 1

    def test_ptf_source_without_soil_observations_honestly_falls_back(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(prepared_field, soil_source="ptf_texture")
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body).json()
        # no soil observations ingested for this field → PTF refused, fallback used
        assert plan["methods"]["ptf"] == "refused_missing_texture"
        season = plan["result"]["seasons"][0]
        assert season["root_zone"]["source_label"] == "none"
        assert season["totals"]["soil_water_contribution_mm"] is None

    def test_faba_bean_plan_is_honestly_unevaluated(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(prepared_field, crop_assignments=[{"crop_code": "faba_bean"}])
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body).json()
        season = plan["result"]["seasons"][0]
        assert season["totals"]["etc_mm"] is None
        assert season["totals"]["net_irrigation_requirement_mm"] is None
        assert season["missing_evidence"]
        assert plan["not_evaluated"]["summer_2025"]
        assert any("Kc" in m for m in season["missing_evidence"])

    def test_unknown_allocation_is_unknown(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(prepared_field, water_allocation_m3=None)
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body).json()
        alloc = plan["result"]["seasons"][0]["allocation"]
        assert alloc["status"] == "unknown"
        assert "UNKNOWN" in alloc["detail"] or "unknown" in alloc["detail"]

    def test_method_class_efficiency_produces_gir(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        body = self._plan_request(prepared_field, irrigation_efficiency={"method_class": "drip"})
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body).json()
        season = plan["result"]["seasons"][0]
        gir = season["totals"]["gross_irrigation_requirement_mm"]
        assert gir is not None
        assert gir == pytest.approx(season["totals"]["net_irrigation_requirement_mm"] / 0.9, rel=1e-3)
        ladder = {s["quantity"]: s for s in season["ladder"]}
        assert "TM1" in (ladder["gross_irrigation_requirement"]["detail"] or "") or \
               "Annex I" in (ladder["gross_irrigation_requirement"]["detail"] or "")

    def test_validation_errors(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        # unknown crop
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field,
                                                   crop_assignments=[{"crop_code": "not_a_crop"}]))
        assert resp.status_code == 422
        # missing assignments
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json={"seasons": [SUMMER]})
        assert resp.status_code == 422
        # bad pe method
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field,
                                                   effective_rainfall_method="usda_scs"))
        assert resp.status_code == 422
        # constant_fraction without fraction
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field,
                                                   effective_rainfall_method="constant_fraction"))
        assert resp.status_code == 422
        # unknown efficiency class
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field,
                                                   irrigation_efficiency={"method_class": "flood"}))
        assert resp.status_code == 422
        # bad soil source
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field, soil_source="magic"))
        assert resp.status_code == 422
        # negative allocation
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers,
                           json=self._plan_request(prepared_field, water_allocation_m3=-1))
        assert resp.status_code == 422

    def test_plan_without_feature_run_is_unevaluated_not_zero(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        body = {
            "label": "No evidence plan",
            "seasons": [SUMMER],
            "crop_assignments": [{"crop_code": "maize"}],
        }
        resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body)
        assert resp.status_code == 201
        plan = resp.json()
        assert plan["status"] == "succeeded"
        season = plan["result"]["seasons"][0]
        assert season["totals"]["etc_mm"] is None
        assert season["totals"]["net_irrigation_requirement_mm"] is None
        assert season["missing_evidence"]

    def test_delete_plan(self, client, prepared_field):
        headers = prepared_field["headers"]
        field_id = prepared_field["field"]["id"]
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans",
                           headers=headers, json=self._plan_request(prepared_field)).json()
        resp = client.delete(f"/api/v1/water-plans/{plan['id']}", headers=headers)
        assert resp.status_code == 204
        assert client.get(f"/api/v1/water-plans/{plan['id']}", headers=headers).status_code == 404

    def test_cross_tenant_plan_access_denied(self, client, prepared_field):
        import uuid as _uuid

        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        field_id = prepared_field["field"]["id"]
        plan = client.post(f"/api/v1/fields/{field_id}/water-plans",
                           headers=prepared_field["headers"],
                           json=self._plan_request(prepared_field)).json()
        assert client.get(f"/api/v1/water-plans/{plan['id']}", headers=other).status_code == 403
        assert client.delete(f"/api/v1/water-plans/{plan['id']}", headers=other).status_code == 403

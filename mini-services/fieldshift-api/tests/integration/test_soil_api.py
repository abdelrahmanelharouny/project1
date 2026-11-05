"""Soil Intelligence API — integration tests (M6B Step 9/10).

Covers: sampling domain flow, method-metadata enforcement (ADR-0023),
profile read model integrity, SOC stock runs (golden value over HTTP),
nutrient budget runs (honest partial classification), CSV import endpoint,
assessment + readiness, management ledger, tenant isolation.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def soil_field(client, farm_with_field):
    return farm_with_field


def _create_event(client, headers, field_id, **over):
    payload = {"sampling_date": "2026-03-15", "purpose": "baseline characterization", **over}
    resp = client.post(f"/api/v1/fields/{field_id}/soil-sampling-events", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_sample(client, headers, field_id, event_id, code="S-001"):
    resp = client.post(
        f"/api/v1/fields/{field_id}/soil-samples",
        headers=headers,
        json={"event_id": event_id, "sample_code": code},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestSamplingDomain:
    def test_event_sample_flow(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        event = _create_event(client, headers, field["id"], composite=True, subsample_count=8,
                              gps_lat=31.11, gps_lon=31.41, management_zone="north")
        sample = _create_sample(client, headers, field["id"], event["id"], code="COMP-1")
        # individual core linked to the composite parent
        child = _create_sample(client, headers, field["id"], event["id"], code="CORE-1")
        link = client.post(
            f"/api/v1/fields/{field['id']}/soil-samples",
            headers=headers,
            json={"event_id": event["id"], "sample_code": "CORE-2", "composite_parent_id": sample["id"]},
        )
        assert link.status_code == 201
        listing = client.get(f"/api/v1/fields/{field['id']}/soil-samples", headers=headers).json()
        assert listing["items"][0]["composite_parent_id"] == sample["id"] or any(
            i["composite_parent_id"] == sample["id"] for i in listing["items"]
        )

    def test_gps_validation(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-sampling-events",
            headers=headers,
            json={"sampling_date": "2026-03-15", "gps_lat": 123.0},
        )
        assert resp.status_code == 422  # CHECK constraint gps range

    def test_tenant_isolation(self, client, soil_field):
        import uuid as _uuid

        headers, field = soil_field["headers"], soil_field["field"]
        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        resp = client.get(f"/api/v1/fields/{field['id']}/soil-profile", headers=other_headers)
        assert resp.status_code == 403


class TestMeasurementMethodEnforcement:
    def test_ph_requires_method_metadata(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={"variable_code": "soil_ph", "value": 7.2, "unit": "pH",
                  "top_depth_cm": 0, "bottom_depth_cm": 30, "observed_at": "2026-03-15"},
        )
        assert resp.status_code == 422
        assert "method metadata" in resp.json()["error"]["message"]

    def test_ph_with_method_accepted(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={
                "variable_code": "soil_ph", "value": 7.2, "unit": "pH",
                "top_depth_cm": 0, "bottom_depth_cm": 30, "observed_at": "2026-03-15",
                "method": {"code": "ph_h2o_1_2_5", "property_family": "ph",
                           "extractant": "water", "soil_solution_ratio": "1:2.5"},
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["method_params"]["code"] == "ph_h2o_1_2_5"

    def test_bulk_density_needs_no_method(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={"variable_code": "soil_bulk_density", "value": 1.33, "unit": "g/cm3",
                  "top_depth_cm": 0, "bottom_depth_cm": 30, "observed_at": "2026-03-15",
                  "method_params": {"bd_basis": "fine_earth", "core_volume_cm3": 100}},
        )
        assert resp.status_code == 201

    def test_unknown_variable_refused(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={"variable_code": "soil_magic", "value": 1.0, "unit": "x",
                  "top_depth_cm": 0, "bottom_depth_cm": 10, "observed_at": "2026-03-15"},
        )
        assert resp.status_code == 422

    def test_soilgrids_source_requires_prediction_evidence(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={"variable_code": "soil_organic_carbon", "value": 15.0, "unit": "g/kg",
                  "top_depth_cm": 0, "bottom_depth_cm": 5, "observed_at": "2020-01-01",
                  "source_kind": "soilgrids_profile", "evidence_class": "direct_field_measurement"},
        )
        assert resp.status_code == 422
        assert "global_soil_prediction" in resp.json()["error"]["message"]


class TestProfile:
    def test_profile_reports_gaps(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        event = _create_event(client, headers, field["id"])
        sample = _create_sample(client, headers, field["id"], event["id"])
        for top, bottom in ((0, 5), (15, 30)):
            resp = client.post(
                f"/api/v1/fields/{field['id']}/soil-measurements",
                headers=headers,
                json={"variable_code": "soil_organic_carbon", "value": 12.0, "unit": "g/kg",
                      "top_depth_cm": top, "bottom_depth_cm": bottom, "observed_at": "2026-03-15",
                      "layer_sample": None, "method_params": {}},
            )
            assert resp.status_code == 201, resp.text
        profile = client.get(f"/api/v1/fields/{field['id']}/soil-profile", headers=headers).json()
        assert profile["integrity"]["gaps"], "the 5–15 cm gap must be reported"
        assert profile["integrity"]["gaps"][0]["gap_cm"] == 10.0

    def test_indicators_derive_texture(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        for var, value, unit in (
            ("soil_sand_content", 700, "g/kg"),
            ("soil_clay_content", 100, "g/kg"),
        ):
            resp = client.post(
                f"/api/v1/fields/{field['id']}/soil-measurements",
                headers=headers,
                json={"variable_code": var, "value": value, "unit": unit,
                      "top_depth_cm": 0, "bottom_depth_cm": 30, "observed_at": "2026-03-15"},
            )
            assert resp.status_code == 201, resp.text
        indicators = client.get(f"/api/v1/fields/{field['id']}/soil-indicators", headers=headers).json()
        texture = indicators["layers"][0]["texture"]
        assert texture["class"] == "sandy loam"
        assert texture["silt_basis"] == "derived_silt_100_minus_sand_clay"


class TestSocRuns:
    def test_golden_value_over_http(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soc-stock-runs",
            headers=headers,
            json={
                "label": "baseline",
                "layers": [
                    {"top_depth": 0, "bottom_depth": 20, "oc_g_kg": 20.0,
                     "bulk_density_g_cm3": 1.3, "bd_basis": "whole_soil",
                     "coarse_fragment_vol_fraction": 0.1},
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        assert run["status"] == "succeeded"
        # hand-computed: 20 × 1.3 × 0.9 × 20 × 0.1 = 46.8 Mg C/ha
        assert run["result"]["profile_total"]["soc_stock_mg_ha"] == 46.8
        assert run["checksum_sha256"]

    def test_missing_bd_listed_not_zero(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soc-stock-runs",
            headers=headers,
            json={
                "layers": [
                    {"top_depth": 0, "bottom_depth": 20, "oc_g_kg": 20.0},
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        assert run["result"]["profile_total"]["soc_stock_mg_ha"] is None
        assert run["not_evaluated"], "the refusal reason must be listed"

    def test_fixed_depth_comparison_flow(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        base = client.post(
            f"/api/v1/fields/{field['id']}/soc-stock-runs",
            headers=headers,
            json={"label": "2020", "layers": [
                {"top_depth": 0, "bottom_depth": 10, "oc_g_kg": 20.0,
                 "bulk_density_g_cm3": 1.4, "bd_basis": "fine_earth"}]},
        ).json()
        follow = client.post(
            f"/api/v1/fields/{field['id']}/soc-stock-runs",
            headers=headers,
            json={"label": "2026", "comparison_mode": "fixed_depth",
                  "baseline_run_id": base["id"],
                  "layers": [
                {"top_depth": 0, "bottom_depth": 10, "oc_g_kg": 20.0,
                 "bulk_density_g_cm3": 1.2, "bd_basis": "fine_earth"}]},
        ).json()
        assert follow["status"] == "succeeded"
        comp = follow["result"]["comparison"]
        assert comp["delta_mg_ha"] == -4.0
        assert any("mass redistribution" in c for c in comp["caveats"])

    def test_idempotency(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        body = {
            "idempotency_key": f"soc-{uuid.uuid4().hex[:8]}",
            "layers": [{"top_depth": 0, "bottom_depth": 10, "oc_g_kg": 10.0,
                        "bulk_density_g_cm3": 1.3, "bd_basis": "fine_earth"}],
        }
        r1 = client.post(f"/api/v1/fields/{field['id']}/soc-stock-runs", headers=headers, json=body).json()
        r2 = client.post(f"/api/v1/fields/{field['id']}/soc-stock-runs", headers=headers, json=body).json()
        assert r1["id"] == r2["id"]

    def test_tenant_isolation_on_run_detail(self, client, soil_field):
        import uuid as _uuid

        headers, field = soil_field["headers"], soil_field["field"]
        other_resp = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        run = client.post(
            f"/api/v1/fields/{field['id']}/soc-stock-runs",
            headers=headers,
            json={"layers": [{"top_depth": 0, "bottom_depth": 10, "oc_g_kg": 10.0,
                              "bulk_density_g_cm3": 1.3, "bd_basis": "fine_earth"}]},
        ).json()
        resp = client.get(f"/api/v1/soc-stock-runs/{run['id']}", headers=other_headers)
        assert resp.status_code == 403


class TestNutrientBudget:
    def test_full_budget_flow(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        # product: urea 46 % N (elemental)
        product = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-products",
            headers=headers,
            json={"name": "Urea 46", "product_type": "fertilizer", "n_pct": 46.0,
                  "reporting_basis": "elemental"},
        ).json()
        app1 = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-applications",
            headers=headers,
            json={"season_label": "summer_2026", "application_date": "2026-05-20",
                  "input_kind": "fertilizer", "product_id": product["id"],
                  "applied_mass_kg": 100.0, "area_ha": 1.0},
        ).json()
        assert app1["n_kg"] == pytest.approx(46.0)
        # oxide grade: DAP 18-46-0 applied 50 kg → P2O5 23 kg → P 10.0378 kg
        dap = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-products",
            headers=headers,
            json={"name": "DAP 18-46-0", "product_type": "fertilizer", "n_pct": 18.0,
                  "p_pct": 46.0, "reporting_basis": "oxide"},
        ).json()
        app2 = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-applications",
            headers=headers,
            json={"season_label": "summer_2026", "application_date": "2026-05-20",
                  "input_kind": "fertilizer", "product_id": dap["id"],
                  "applied_mass_kg": 50.0, "area_ha": 1.0},
        ).json()
        # p_kg stays in the DECLARED form (P2O5, basis 'oxide') — the budget
        # engine converts through the versioned stoichiometric function.
        assert app2["p_kg"] == 23.0
        assert app2["reporting_basis"] == "oxide"
        # removal with farmer-supplied concentration
        removal = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-removals",
            headers=headers,
            json={"season_label": "summer_2026", "crop_code": "maize",
                  "output_kind": "harvested_product", "biomass_kg": 1000.0,
                  "moisture_basis": "dry_matter", "n_concentration_g_kg": 14.0,
                  "concentration_source": "farmer lab record"},
        )
        assert removal.status_code == 201, removal.text
        # budget run
        run = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-budget-runs",
            headers=headers,
            json={"seasons": ["summer_2026"], "area_ha": 1.0},
        ).json()
        assert run["status"] == "succeeded"
        n_balance = run["result"]["seasons"][0]["balance"]["N"]
        assert n_balance["inputs_kg_ha"] == 55.0  # urea 46 + DAP 18% × 50 kg = 9
        assert n_balance["outputs_kg_ha"] == 14.0
        assert n_balance["balance_kg_ha"] == 41.0
        assert run["result"]["seasons"][0]["overall"] == "partial"  # loss flows unknown
        p_balance = run["result"]["seasons"][0]["balance"]["P"]
        assert p_balance["inputs_kg_ha"] == pytest.approx(23.0 * 0.436421, rel=1e-4)

    def test_manure_requires_availability(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-applications",
            headers=headers,
            json={"season_label": "s1", "application_date": "2026-05-20",
                  "input_kind": "manure", "applied_mass_kg": 5000.0, "area_ha": 1.0,
                  "n_kg": 25.0},
        )
        assert resp.status_code == 422
        assert "availability_fraction" in resp.json()["error"]["message"]

    def test_removal_without_concentration_refused(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/nutrient-removals",
            headers=headers,
            json={"season_label": "s1", "biomass_kg": 1000.0, "moisture_basis": "dry_matter"},
        )
        assert resp.status_code == 422
        assert "never a removal estimate" in resp.json()["error"]["message"]


class TestLabImport:
    def test_import_endpoint_round_trip(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        csv_content = (
            "sample_code,top_depth,bottom_depth,depth_unit,observed_at,variable_code,value,unit,method_code\n"
            f"IMP-1,0,30,cm,2026-03-15,soil_ph,7.4,pH,ph_h2o_1_2_5\n"
            f"IMP-1,0,30,cm,2026-03-15,soil_organic_carbon,11.0,g/kg,walkley_black\n"
        ).encode()
        resp = client.post(
            "/api/v1/soil-samples/import",
            headers=headers,
            files={"file": ("lab_report.csv", csv_content, "text/csv")},
            data={"mapping": '{"columns": {"sample_code": "sample_code", "top_depth": "top_depth", "bottom_depth": "bottom_depth", "variable_code": "variable_code", "value": "value", "unit": "unit", "observed_at": "observed_at", "method_code": "method_code"}, "default_field_id": "%s"}' % field["id"]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["created_measurements"] == 2
        assert data["report"]["imported"] == 2
        profile = client.get(f"/api/v1/fields/{field['id']}/soil-profile", headers=headers).json()
        assert any(m["variable_code"] == "soil_ph" for layer in profile["layers"] for m in layer["measurements"])


class TestAssessmentAndReadiness:
    def test_assessment_snapshot_and_checksum(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        client.post(
            f"/api/v1/fields/{field['id']}/soil-measurements",
            headers=headers,
            json={"variable_code": "soil_ph", "value": 7.2, "unit": "pH",
                  "top_depth_cm": 0, "bottom_depth_cm": 30, "observed_at": "2026-03-15",
                  "method_params": {"medium": "water", "soil_solution_ratio": "1:2.5"}},
        )
        created = client.post(f"/api/v1/fields/{field['id']}/soil-assessments", headers=headers, json={}).json()
        assert created["status"] == "succeeded"
        assert created["result"]["composite_score"] is None
        detail = client.get(f"/api/v1/soil-assessments/{created['id']}", headers=headers).json()
        assert detail["checksum_sha256"] == created["checksum_sha256"]
        health = client.get(f"/api/v1/fields/{field['id']}/soil-health", headers=headers).json()
        assert health["source"] == "snapshot"

    def test_readiness_ranking(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        readiness = client.get(f"/api/v1/fields/{field['id']}/soil-data-readiness", headers=headers).json()
        codes = [p["variable_code"] for p in readiness["priorities"]]
        assert "soil_electrical_conductivity" in codes
        for p in readiness["priorities"]:
            assert p["decision_unblocked"]


class TestManagementLedger:
    def test_event_flow(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-management-events",
            headers=headers,
            json={"event_date": "2026-05-01", "event_type": "tillage",
                  "title": "Primary tillage", "details": {"depth_cm": 25}},
        )
        assert resp.status_code == 201
        listing = client.get(f"/api/v1/fields/{field['id']}/soil-management-events", headers=headers).json()
        assert listing["items"][0]["event_type"] == "tillage"

    def test_invalid_event_type_refused(self, client, soil_field):
        headers, field = soil_field["headers"], soil_field["field"]
        resp = client.post(
            f"/api/v1/fields/{field['id']}/soil-management-events",
            headers=headers,
            json={"event_date": "2026-05-01", "event_type": "party"},
        )
        assert resp.status_code == 422

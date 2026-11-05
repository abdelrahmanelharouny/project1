"""Integration: M7.7 digital twin — unified field view, information-class
census, capability/data readiness, bounded integrity validation walk,
maturity honesty, tenant isolation."""

import uuid

import pytest
from sqlalchemy import text

from tests.integration.test_robust_rotation import (  # reuse builders
    SEASON_2016,
    _executed_run,
    _feature_run,
    _field_state,
    _finalized_scenario,
    _ingest,
    _second_user,
)


@pytest.fixture()
def prepared(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest(client, headers, field_id)
    run = _feature_run(client, headers, field_id)
    state = _field_state(client, headers, field_id, run["run_id"])
    resp = client.post(
        f"/api/v1/fields/{field_id}/crop-history",
        headers=headers,
        json={
            "crop_code": "maize",
            "crop_label": "Maize (2015)",
            "sowing_date": "2015-05-01",
            "harvest_date": "2015-09-15",
            "season_label": "summer_2015",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"headers": headers, "field": farm_with_field["field"], "state": state, "feature_run": run}


@pytest.fixture()
def full_stack(client, prepared):
    """Executed scenario + sensitivity + robust run + decision doc."""
    h = prepared["headers"]
    field_id = prepared["field"]["id"]
    s_hot = _finalized_scenario(
        client, h, field_id, prepared["state"]["id"],
        adjustments={"temperature_delta_c": 2.0, "precipitation_multiplier": 0.8},
        name="Hot",
    )
    r_hot = _executed_run(client, h, s_hot["id"])
    resp = client.post(
        f"/api/v1/scenario-executions/{r_hot['run_id']}/sensitivity-analyses",
        headers=h,
        json={"parameter_design": {"temperature_delta_c": {"lower": 0.0, "upper": 4.0, "n_points": 5}}},
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/api/v1/fields/{field_id}/scenario-sets",
        headers=h,
        json={"label": "set", "execution_run_ids": [r_hot["run_id"]]},
    )
    set_id = resp.json()["id"]
    resp = client.post(
        f"/api/v1/scenario-sets/{set_id}/robust-runs",
        headers=h,
        json={"seasons": [SEASON_2016], "hemisphere": "north"},
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
    )
    assert resp.status_code == 200, resp.text
    return {**prepared, "scenario": s_hot, "execution": r_hot}


class TestTwinView:
    def test_unified_view_sections(self, client, full_stack):
        h = full_stack["headers"]
        field_id = full_stack["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/digital-twin", headers=h)
        assert resp.status_code == 200, resp.text
        twin = resp.json()
        assert twin["field_identity"]["field_id"] == field_id
        assert twin["field_identity"]["latest_boundary_version"] is not None
        assert twin["field_states"]["total"] >= 1
        assert len(twin["field_states"]["items"]) >= 1
        assert twin["field_states"]["items"][0]["snapshot_checksum"]
        assert twin["observation_coverage"]["variables"], "ingested variables present"
        assert any(v["observation_count"] > 0 for v in twin["observation_coverage"]["variables"])
        assert len(twin["scenarios"]) == 1
        node = twin["scenarios"][0]
        assert node["evidence_classification"] == "hypothetical"
        assert len(node["executions"]) == 1
        assert node["executions"][0]["output_checksum"]
        assert any(s["analysis_count"] >= 1 for s in twin["sensitivity_analyses"])
        assert twin["robust_rotation"]["scenario_sets"][0]["robust_runs"][0]["output_checksum"]
        assert len(twin["decision_documents"]) == 1

    def test_information_classes_distinguished(self, client, full_stack):
        h = full_stack["headers"]
        field_id = full_stack["field"]["id"]
        twin = client.get(f"/api/v1/fields/{field_id}/digital-twin", headers=h).json()
        ic = twin["information_classes"]
        assert ic["observed_observations"] > 0
        assert ic["scenario_derived_transformed_observations"] > 0
        assert ic["calculated_feature_values"] > 0
        assert "never merged into the observation record" in ic["note"]

    def test_capability_matrix_and_maturity_honesty(self, client, full_stack):
        h = full_stack["headers"]
        field_id = full_stack["field"]["id"]
        twin = client.get(f"/api/v1/fields/{field_id}/digital-twin", headers=h).json()
        caps = {c["capability"]: c for c in twin["capabilities"]}
        assert caps["digital_twin_view"]["data_ready"] is True
        assert caps["scenario_execution"]["data_ready"] is True
        assert caps["sensitivity_uncertainty"]["data_ready"] is True
        assert caps["robust_rotation"]["data_ready"] is True
        assert caps["decision_intelligence"]["data_ready"] is True
        maturity = twin["maturity"]
        assert maturity["classification"] == "observational-analytical field twin (no forecasting)"
        banned = [c for c in maturity["not_implemented"]]
        assert any("climate_projection" in c for c in banned)
        assert any("yield_prediction" in c for c in banned)
        assert twin["prohibitions_note"]

    def test_empty_field_twin_still_honest(self, client, farm_with_field):
        h = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        twin = client.get(f"/api/v1/fields/{field_id}/digital-twin", headers=h).json()
        assert twin["field_states"]["total"] == 0
        caps = {c["capability"]: c for c in twin["capabilities"]}
        assert caps["scenario_execution"]["readiness"] == "prerequisite_missing"
        assert twin["maturity"]["classification"]


class TestValidationWalk:
    def test_validate_consistent_stack(self, client, full_stack):
        h = full_stack["headers"]
        field_id = full_stack["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/digital-twin/validate", headers=h, json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["overall_status"] == "consistent"
        assert body["artifacts_checked"] >= 4
        assert body["artifacts_failed"] == 0
        assert body["report_checksum"]
        kinds = {c["artifact"] for c in body["report"]["artifact_checks"]}
        assert {"field_state", "scenario", "scenario_execution", "sensitivity_analysis",
                "robust_rotation_run", "decision_comparison"} <= kinds

    def test_no_artifacts_status(self, client, prepared):
        h = prepared["headers"]
        resp = client.post(
            f"/api/v1/fields/{prepared['field']['id']}/digital-twin/validate", headers=h, json={}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["overall_status"] == "no_artifacts"

    def test_validation_history(self, client, full_stack):
        h = full_stack["headers"]
        field_id = full_stack["field"]["id"]
        client.post(f"/api/v1/fields/{field_id}/digital-twin/validate", headers=h, json={})
        listing = client.get(f"/api/v1/fields/{field_id}/digital-twin/validations", headers=h).json()
        assert listing["count"] >= 1
        assert listing["items"][0]["overall_status"] in ("consistent", "inconsistent", "no_artifacts")

    def test_tenant_isolation(self, client, full_stack):
        other = _second_user(client)
        field_id = full_stack["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/digital-twin", headers=other)
        assert resp.status_code == 403
        resp = client.post(f"/api/v1/fields/{field_id}/digital-twin/validate", headers=other, json={})
        assert resp.status_code == 403
        resp = client.get(f"/api/v1/fields/{field_id}/digital-twin/validations", headers=other)
        assert resp.status_code == 403


class TestMigrationHead:
    def test_head_is_0013(self, db):
        row = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert row == "0014_merge_m6bc_m7"  # merge revision unifies the M6B/M6C and M7 migration lines

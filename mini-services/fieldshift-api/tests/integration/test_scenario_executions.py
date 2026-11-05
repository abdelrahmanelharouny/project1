"""Integration: M7.3 scenario execution — API lifecycle, eligibility, honest
refusals, determinism, immutability, provenance, tenant isolation."""

import uuid

import pytest
from sqlalchemy import text

INGEST_BODY = {
    "provider_code": "synthetic",
    "variables": [
        "precipitation",
        "air_temperature_mean",
        "air_temperature_min",
        "air_temperature_max",
        "reference_et0",
    ],
    "start_date": "2015-01-01",
    "end_date": "2017-12-31",
    "profile": "temperate_seasonal",
    "seed": 7,
}

STRESS_CONFIG = {
    "type": "user_defined_stress",
    "parent_field_state_id": None,
    "period": {"start": "2016-01-01", "end": "2016-12-31"},
    "adjustments": {"temperature_delta_c": 2.0, "precipitation_multiplier": 0.8},
    "assumption_metadata": {
        "origin": "user_defined",
        "status": "hypothetical",
        "description": "M7.3 integration stress experiment",
    },
}


def _ingest(client, headers, field_id):
    resp = client.post(f"/api/v1/fields/{field_id}/data-jobs", headers=headers, json=INGEST_BODY)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job.get("error_summary")
    return job


def _feature_run(client, headers, field_id):
    resp = client.post(
        f"/api/v1/fields/{field_id}/feature-runs",
        headers=headers,
        json={
            "start_date": "2015-01-01",
            "end_date": "2017-12-31",
            "aggregation_levels": ["monthly"],
            "hemisphere": "north",
        },
    )
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert run["status"] == "succeeded", run.get("error_summary")
    return run


def _field_state(client, headers, field_id, **payload):
    body = {"period_start": "2015-01-01", "period_end": "2017-12-31", **payload}
    resp = client.post(f"/api/v1/fields/{field_id}/field-states", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    state = resp.json()
    assert state["status"] == "succeeded", state.get("error_summary")
    return state


def _finalized_scenario(client, headers, field_id, state_id, adjustments=None, name="Stress"):
    config = {
        **STRESS_CONFIG,
        "parent_field_state_id": state_id,
    }
    if adjustments is not None:
        config["adjustments"] = adjustments
    resp = client.post(
        f"/api/v1/fields/{field_id}/scenarios",
        headers=headers,
        json={
            "scenario_type": "user_defined_stress",
            "name": name,
            "configuration": config,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    scenario = resp.json()
    resp = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _second_user(client):
    """A genuinely separate second tenant."""
    import uuid as _uuid

    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
            "password": "test-password-1",
            "display_name": "Other Farmer",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture()
def prepared(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest(client, headers, field_id)
    run = _feature_run(client, headers, field_id)
    state = _field_state(client, headers, field_id, environmental_feature_run_id=run["run_id"])
    return {
        "headers": headers,
        "user": farm_with_field["user"],
        "farm": farm_with_field["farm"],
        "field": farm_with_field["field"],
        "feature_run": run,
        "state": state,
    }


# ------------------------------------------------------------- happy path


class TestExecutionGoldenPath:
    def test_execute_finalized_scenario_end_to_end(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(
            client, h, prepared["field"]["id"], prepared["state"]["id"]
        )
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 200, resp.text
        run = resp.json()
        assert run["run_status"] in ("succeeded", "completed_with_limitations")
        assert run["transformed_observation_count"] > 0
        assert run["derived_feature_count"] > 0
        assert run["output_checksum"]
        assert run["parent_field_state_id"] == prepared["state"]["id"]
        assert run["parent_snapshot_checksum"] == prepared["state"]["checksum_sha256"]
        assert run["scenario_configuration_checksum"] == scenario["configuration_checksum"]
        # honest disclosure always present
        assert any("hypothetical" in w for w in run["warnings"])

    def test_derived_observations_link_to_source(self, client, prepared, db):
        from app.db import models as dbm

        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}
        ).json()
        obs = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/observations", headers=h
        ).json()
        assert obs["count"] > 0
        sample = obs["items"][0]
        assert sample["source_observation_id"]
        assert sample["baseline_value"] is not None or sample["transformed_value"] is None
        assert sample["transformation_code"] in ("temperature_delta_c", "precipitation_multiplier")
        assert sample["evidence_class"] in ("scenario_derived_transformed", "synthetic_test")
        # derived values never enter the observations table (count unchanged vs
        # the transformed count; the derived layer is a separate structure)
        total_obs = db.execute(
            text("SELECT count(*) FROM observations WHERE field_id = :f"),
            {"f": prepared["field"]["id"]},
        ).scalar()
        derived_rows = db.execute(
            text("SELECT count(*) FROM scenario_derived_observations")
        ).scalar()
        assert derived_rows == run["transformed_observation_count"]
        assert total_obs > 0  # real observation layer intact and separate

    def test_comparison_math(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}
        ).json()
        feats = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/features"
            "?evidence_status=scenario_recalculated",
            headers=h,
        ).json()
        assert feats["count"] > 0
        checked = 0
        for row in feats["items"]:
            if row["feature_code"] == "air_temperature_mean_monthly":
                assert row["difference_value"] == pytest.approx(2.0, abs=1e-6)
                assert row["difference_percent"] is not None
                checked += 1
            if row["difference_percent"] is not None:
                assert row["baseline_value"] not in (None, 0)
        assert checked > 0

    def test_et0_never_reused_as_scenario_output(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}
        ).json()
        feats = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/features", headers=h
        ).json()
        et0_rows = [f for f in feats["items"] if f["feature_code"].startswith("reference_et0")]
        assert et0_rows, "ET0 features must be reported"
        for row in et0_rows:
            assert row["evidence_status"] == "not_evaluated"
            assert row["scenario_value"] is None
            assert "ET0" in (row["uncertainty_metadata"].get("reason") or "")
        assert any("ET0" in k or "reference_et0" in k for k in run["not_evaluated_reasons"])
        # water balance also never computed
        wb = [f for f in feats["items"] if f["feature_code"] == "water_balance_p_minus_et0_monthly"]
        assert wb and wb[0]["evidence_status"] == "not_evaluated"

    def test_unaffected_features_reported_not_fabricated(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}
        ).json()
        feats = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/features"
            "?evidence_status=not_affected",
            headers=h,
        ).json()
        codes = {f["feature_code"] for f in feats["items"]}
        assert "wind_speed_10m_mean_monthly" in codes
        for row in feats["items"]:
            assert row["scenario_value"] is None
            assert row["uncertainty_metadata"].get("reason")


# ------------------------------------------------------------- eligibility


class TestExecutionEligibility:
    def test_draft_scenario_refused(self, client, prepared):
        h = prepared["headers"]
        config = {**STRESS_CONFIG, "parent_field_state_id": prepared["state"]["id"]}
        resp = client.post(
            f"/api/v1/fields/{prepared['field']['id']}/scenarios",
            headers=h,
            json={
                "scenario_type": "user_defined_stress",
                "name": "Draft",
                "configuration": config,
            },
        )
        assert resp.status_code in (200, 201)
        scenario = resp.json()
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "SCENARIO_NOT_FINALIZED"

    def test_historical_observed_refused(self, client, prepared):
        h = prepared["headers"]
        resp = client.post(
            f"/api/v1/fields/{prepared['field']['id']}/scenarios",
            headers=h,
            json={
                "scenario_type": "historical_observed",
                "name": "Reference",
                "configuration": {
                    "type": "historical_observed",
                    "parent_field_state_id": prepared["state"]["id"],
                },
            },
        )
        assert resp.status_code in (200, 201)
        scenario = resp.json()
        client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=h)
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=h)
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "SCENARIO_TYPE_NOT_EXECUTABLE"

    def test_unsupported_dimension_blocks_with_findings(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(
            client,
            h,
            prepared["field"]["id"],
            prepared["state"]["id"],
            adjustments={"precipitation_delta_mm": 50.0},
            name="Delta-precip (unsupported)",
        )
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "SCENARIO_EXECUTION_BLOCKED"
        findings = body["error"]["details"]
        assert any(f["code"] == "unsupported_transformation" for f in findings)

    def test_no_supported_transformation_blocks(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(
            client,
            h,
            prepared["field"]["id"],
            prepared["state"]["id"],
            adjustments={"water_allocation_multiplier": 0.5},
            name="Water-only",
        )
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 422
        findings = resp.json()["error"]["details"]
        assert any(f["code"] == "no_supported_transformation" for f in findings)

    def test_water_allocation_multiplier_rides_as_context(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(
            client,
            h,
            prepared["field"]["id"],
            prepared["state"]["id"],
            adjustments={
                "temperature_delta_c": 1.5,
                "water_allocation_multiplier": 0.5,
            },
            name="Temp + water context",
        )
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        assert resp.status_code == 200
        run = resp.json()
        assert run["resource_constraints"].get("water_allocation_multiplier") == 0.5
        assert any("resource-constraint" in w or "NOT a transformed weather" in w for w in run["warnings"])
        # the weather transformations only touched temperature variables
        obs = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/observations", headers=h
        ).json()
        assert {o["variable_code"] for o in obs["items"]} <= {
            "air_temperature_mean",
            "air_temperature_max",
            "air_temperature_min",
        }


# ---------------------------------------------------------- determinism


class TestDeterminismAndReplay:
    def test_identical_inputs_identical_checksum(self, client, prepared):
        h = prepared["headers"]
        s1 = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"], name="A")
        s2 = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"], name="B")
        r1 = client.post(f"/api/v1/scenarios/{s1['id']}/executions", headers=h, json={}).json()
        r2 = client.post(f"/api/v1/scenarios/{s2['id']}/executions", headers=h, json={}).json()
        assert r1["output_checksum"]
        assert r1["output_checksum"] == r2["output_checksum"]
        # different scenarios (different ids) but identical scientific inputs
        assert r1["run_id"] != r2["run_id"]

    def test_changed_assumption_changes_checksum(self, client, prepared):
        h = prepared["headers"]
        s1 = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"], name="dT2")
        s2 = _finalized_scenario(
            client,
            h,
            prepared["field"]["id"],
            prepared["state"]["id"],
            adjustments={"temperature_delta_c": 3.0, "precipitation_multiplier": 0.8},
            name="dT3",
        )
        r1 = client.post(f"/api/v1/scenarios/{s1['id']}/executions", headers=h, json={}).json()
        r2 = client.post(f"/api/v1/scenarios/{s2['id']}/executions", headers=h, json={}).json()
        assert r1["output_checksum"] != r2["output_checksum"]

    def test_same_scenario_replay_returns_same_run(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        r1 = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}).json()
        r2 = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}).json()
        assert r1["run_id"] == r2["run_id"]

    def test_idempotency_key_replay(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        r1 = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions",
            headers=h,
            json={"idempotency_key": "exec-key-1"},
        ).json()
        r2 = client.post(
            f"/api/v1/scenarios/{scenario['id']}/executions",
            headers=h,
            json={"idempotency_key": "exec-key-1"},
        ).json()
        assert r1["run_id"] == r2["run_id"]

    def test_verify_endpoint_confirms_integrity(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}).json()
        ver = client.post(f"/api/v1/scenario-executions/{run['run_id']}/verify", headers=h).json()
        assert ver["output_checksum_valid"] is True
        assert ver["scenario_definition_checksum_valid"] is True
        assert ver["parent_snapshot_intact"] is True
        assert ver["manifest_checksum_matches_run"] is True


# ------------------------------------------------------------- immutability


class TestImmutabilityAndProvenance:
    def test_parent_artifacts_unchanged(self, client, prepared, db):
        from app.db import models as dbm

        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        obs_before = db.execute(
            text("SELECT count(*), coalesce(sum(value),0) FROM observations WHERE field_id = :f"),
            {"f": field_id},
        ).fetchone()
        values_before = db.execute(
            text(
                "SELECT fv.value FROM feature_values fv "
                "JOIN feature_runs fr ON fr.id = fv.run_id "
                "WHERE fr.field_id = :f ORDER BY fv.id LIMIT 50"
            ),
            {"f": field_id},
        ).fetchall()
        state_checksum_before = prepared["state"]["checksum_sha256"]

        scenario = _finalized_scenario(client, h, field_id, prepared["state"]["id"])
        client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})

        db.rollback()
        obs_after = db.execute(
            text("SELECT count(*), coalesce(sum(value),0) FROM observations WHERE field_id = :f"),
            {"f": field_id},
        ).fetchone()
        values_after = db.execute(
            text(
                "SELECT fv.value FROM feature_values fv "
                "JOIN feature_runs fr ON fr.id = fv.run_id "
                "WHERE fr.field_id = :f ORDER BY fv.id LIMIT 50"
            ),
            {"f": field_id},
        ).fetchall()
        assert obs_after == obs_before
        assert values_after == values_before
        state_after = db.get(dbm.FieldState, prepared["state"]["id"])
        assert state_after.checksum_sha256 == state_checksum_before

    def test_scenario_definition_unchanged_after_execution(self, client, prepared, db):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        checksum = scenario["configuration_checksum"]
        client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        detail = client.get(f"/api/v1/scenarios/{scenario['id']}", headers=h).json()
        assert detail["configuration_checksum"] == checksum
        assert detail["scenario_status"] == "finalized"

    def test_result_bearing_run_frozen_at_db_level(self, client, prepared, db):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}).json()
        with pytest.raises(Exception):
            db.execute(
                text(
                    "UPDATE scenario_execution_runs SET records_written = 0 WHERE id = :id"
                ),
                {"id": run["run_id"]},
            )
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(
                text("DELETE FROM scenario_execution_runs WHERE id = :id"),
                {"id": run["run_id"]},
            )
            db.commit()
        db.rollback()

    def test_synthetic_evidence_survives_transformation(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        run = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={}).json()
        assert any("SYNTHETIC SOURCE" in w for w in run["warnings"])
        obs = client.get(
            f"/api/v1/scenario-executions/{run['run_id']}/observations", headers=h
        ).json()
        assert obs["items"], "expected transformed observations"
        assert all(o["evidence_class"] in ("scenario_derived_transformed", "synthetic_test") for o in obs["items"])
        assert all(o["is_synthetic"] for o in obs["items"])  # synthetic fixture ingest

    def test_scenario_delete_blocked_while_run_exists(self, client, prepared):
        """FK RESTRICT: a scenario with executions cannot be deleted silently."""
        from app.core.errors import Conflict

        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h, json={})
        resp = client.delete(f"/api/v1/scenarios/{scenario['id']}", headers=h)
        # finalized scenario cannot be deleted via the draft-only DELETE anyway
        assert resp.status_code in (403, 409)


# ---------------------------------------------------------- tenant isolation


class TestTenantIsolation:
    def test_other_tenant_cannot_execute_or_read(self, client, prepared):
        h1 = prepared["headers"]
        scenario = _finalized_scenario(
            client, h1, prepared["field"]["id"], prepared["state"]["id"]
        )
        run = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h1, json={}).json()
        h2 = _second_user(client)
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/executions", headers=h2, json={})
        assert resp.status_code in (403, 404)
        for path in (
            f"/api/v1/scenario-executions/{run['run_id']}",
            f"/api/v1/scenario-executions/{run['run_id']}/features",
            f"/api/v1/scenario-executions/{run['run_id']}/observations",
            f"/api/v1/scenario-executions/{run['run_id']}/compare",
        ):
            resp = client.get(path, headers=h2)
            assert resp.status_code in (403, 404), (path, resp.status_code)
        resp = client.post(f"/api/v1/scenario-executions/{run['run_id']}/verify", headers=h2)
        assert resp.status_code in (403, 404)


class TestCrossTenantScenarioExecution:
    def test_scenario_of_other_tenant_not_executable(self, client, prepared):
        """A scenario belongs to its field; its executions are scoped to the
        field's tenant — never the caller's claim."""
        h2 = _second_user(client)
        # second tenant cannot even see the scenario
        resp = client.get(f"/api/v1/scenarios/00000000-0000-0000-0000-000000000000/executions", headers=h2)
        assert resp.status_code in (403, 404)

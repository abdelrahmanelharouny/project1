"""Integration: M7.4 sensitivity & uncertainty analyses — eligibility gates,
reference reproduction, OAT golden mathematics, envelopes, joint grid,
uncertainty registry, idempotent replay, immutability, tenant isolation."""

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
        "description": "M7.4 integration stress experiment",
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
    config = {**STRESS_CONFIG, "parent_field_state_id": state_id}
    if adjustments is not None:
        config["adjustments"] = adjustments
    resp = client.post(
        f"/api/v1/fields/{field_id}/scenarios",
        headers=headers,
        json={"scenario_type": "user_defined_stress", "name": name, "configuration": config},
    )
    assert resp.status_code in (200, 201), resp.text
    scenario = resp.json()
    resp = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _executed_run(client, headers, scenario_id):
    resp = client.post(f"/api/v1/scenarios/{scenario_id}/executions", headers=headers, json={})
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["run_status"] in ("succeeded", "completed_with_limitations"), run.get("error_summary")
    return run


def _second_user(client):
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


@pytest.fixture()
def both_param_run(client, prepared):
    scenario = _finalized_scenario(client, prepared["headers"], prepared["field"]["id"], prepared["state"]["id"])
    run = _executed_run(client, prepared["headers"], scenario["id"])
    return {**prepared, "scenario": scenario, "run": run}


# --------------------------------------------------------------- golden path


class TestAnalysisGoldenPath:
    def test_analysis_end_to_end_with_reproduction(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 9},
                    "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 9},
                }
            },
        )
        assert resp.status_code == 200, resp.text
        analysis = resp.json()
        assert analysis["analysis_status"] in ("succeeded", "completed_with_limitations")
        assert analysis["reference_reproduction"]["reproduced"] is True
        assert analysis["reference_reproduction"]["mismatched_rows"] == []
        assert analysis["reference_reproduction"]["observation_count_match"] is True
        assert analysis["output_checksum"]
        # both parameters configured → both explorable
        detail = analysis["explorable_parameters_detail"]
        assert detail["temperature_delta_c"]["explorable"] is True
        assert detail["precipitation_multiplier"]["explorable"] is True
        # disclosures always present
        assert any("not a confidence or probability interval" in w for w in analysis["warnings"])

    def test_oat_slope_linearity_golden(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 9}
                }
            },
        )
        assert resp.status_code == 200, resp.text
        analysis = resp.json()
        analysis_id = analysis["analysis_id"]

        resp = client.get(
            f"/api/v1/sensitivity-analyses/{analysis_id}/responses",
            headers=h,
            params={"parameter_code": "temperature_delta_c", "feature_code": "air_temperature_mean_monthly"},
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["items"]
        assert rows, "expected monthly mean temperature responses"
        for row in rows:
            # Golden: monthly mean temperature shifts by exactly ΔT.
            assert row["slope"] == pytest.approx(1.0, abs=1e-9)
            assert row["slope_units"] == "degC / degC"
            assert row["direction"] == "increasing"
            assert row["response_classification"] in ("monotonic_increasing", "monotonic_decreasing")
            assert row["n_evaluated_points"] == 9
            # envelope = reference shifted by (bound − reference ΔT)
            envelope = row["explored_parameter_range_envelope"]
            assert envelope["parameter_lower"] == -2.0
            assert envelope["parameter_upper"] == 6.0
            assert envelope["lower"] == pytest.approx(row["reference_value"] - 4.0, abs=1e-9)
            assert envelope["upper"] == pytest.approx(row["reference_value"] + 4.0, abs=1e-9)
            assert row["output_range"] == pytest.approx(8.0, abs=1e-9)
            # elasticity available (reference value ≠ 0 for monthly means)
            assert row["elasticity"]["status"] == "available"
            assert row["elasticity"]["value"] == pytest.approx(2.0 / row["reference_value"], rel=1e-6)

    def test_precipitation_elasticity_golden(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 5}
                }
            },
        )
        assert resp.status_code == 200, resp.text
        analysis_id = resp.json()["analysis_id"]
        resp = client.get(
            f"/api/v1/sensitivity-analyses/{analysis_id}/responses",
            headers=h,
            params={"parameter_code": "precipitation_multiplier", "feature_code": "precipitation_total_monthly"},
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["items"]
        assert rows, "expected monthly precipitation responses"
        for row in rows:
            if row["response_status"] == "not_evaluated":
                continue
            # Golden: totals scale linearly with the multiplier.
            assert row["slope"] == pytest.approx(row["reference_value"] / 0.8, rel=1e-6)
            assert row["slope_units"] == "mm / multiplier"
            assert row["direction"] == "increasing"
            if row["reference_value"] not in (None, 0):
                assert row["elasticity"]["status"] == "available"
                assert row["elasticity"]["value"] == pytest.approx(1.0, abs=1e-9)
            else:
                assert row["elasticity"]["status"] == "unavailable"
                assert row["elasticity"]["reason"] in ("reference_value_is_zero", "reference_value_missing")

    def test_evaluations_endpoint_shows_reference(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": 0.0, "upper": 4.0, "n_points": 5}
                }
            },
        )
        assert resp.status_code == 200, resp.text
        analysis_id = resp.json()["analysis_id"]
        resp = client.get(f"/api/v1/sensitivity-analyses/{analysis_id}/evaluations", headers=h)
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        references = [e for e in items if e["is_reference"]]
        assert len(references) == 1
        assert references[0]["parameter_values"]["temperature_delta_c"] == 2.0
        assert references[0]["parameter_values"]["precipitation_multiplier"] == 0.8
        # 5 design points, one coincides with the reference → 5 unique tuples
        assert len(items) == 5

    def test_single_parameter_source_marks_other_not_applicable(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(
            client,
            h,
            prepared["field"]["id"],
            prepared["state"]["id"],
            adjustments={"temperature_delta_c": 2.0},
            name="TempOnly",
        )
        run = _executed_run(client, h, scenario["id"])
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                }
            },
        )
        assert resp.status_code == 200, resp.text
        analysis = resp.json()
        detail = analysis["explorable_parameters_detail"]
        assert detail["temperature_delta_c"]["explorable"] is True
        assert detail["precipitation_multiplier"]["explorable"] is False
        assert "not configured in the source execution" in detail["precipitation_multiplier"]["reason"]

    def test_joint_grid_interaction_contrast(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5},
                    "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 5},
                },
                "grid": True,
            },
        )
        assert resp.status_code == 200, resp.text
        analysis = resp.json()
        assert analysis["grid_design"] is not None
        analysis_id = analysis["analysis_id"]

        resp = client.get(
            f"/api/v1/sensitivity-analyses/{analysis_id}/grid",
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        grid = resp.json()
        assert set(grid["axes"]) == {"temperature_delta_c", "precipitation_multiplier"}
        assert grid["cells"], "expected grid cells"
        assert grid["summaries"], "expected grid summaries"
        for summary in grid["summaries"]:
            if summary["interaction_contrast"] is None:
                continue
            families = summary["variable_families"]
            if len(families) <= 1:
                # Golden: single-family features are exactly additive in the grid.
                assert summary["interaction_contrast"] == pytest.approx(0.0, abs=1e-9)
                assert summary["interaction_interpretation"] == "approximately_additive"

    def test_uncertainty_registry_content(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                }
            },
        )
        analysis_id = resp.json()["analysis_id"]
        resp = client.get(f"/api/v1/sensitivity-analyses/{analysis_id}/uncertainty", headers=h)
        assert resp.status_code == 200, resp.text
        registry = resp.json()
        assert registry["registry_version"] == "sensitivity-uncertainty-registry-1.0"
        categories = {i["category"] for i in registry["items"]}
        assert categories == {
            "parameter_range_uncertainty",
            "observation_data_quality",
            "spatial_coverage_limitation",
            "temporal_resolution_limitation",
            "model_structural_limitation",
            "feature_method_limitation",
            "regional_agronomic_uncertainty",
        }
        by_code = {i["code"]: i for i in registry["items"]}
        assert by_code["parameter_range_bounds"]["quantification_status"] == "bounded_exploratory"
        assert by_code["source_measurement_error"]["quantification_status"] == "not_quantified"
        # no numeric confidence invented anywhere
        for item in registry["items"]:
            assert item["quantification_status"] in (
                "quantified", "bounded_exploratory", "qualitative_only",
                "not_quantified", "not_applicable", "not_evaluated",
            )

    def test_verify_endpoint_all_flags(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                }
            },
        )
        analysis_id = resp.json()["analysis_id"]
        resp = client.post(f"/api/v1/sensitivity-analyses/{analysis_id}/verify", headers=h)
        assert resp.status_code == 200, resp.text
        verify = resp.json()
        assert verify["output_checksum_valid"] is True
        assert verify["source_run_intact"] is True
        assert verify["parent_snapshot_intact"] is True
        assert verify["manifest_checksum_matches"] is True
        assert verify["reference_reproduction_consistent"] is True


# ---------------------------------------------------------------- negative gates


class TestNegativeGates:
    def test_bounds_must_contain_reference(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": 3.0, "upper": 6.0, "n_points": 5}
                }
            },
        )
        assert resp.status_code == 422, resp.text
        assert "bounds must contain the reference" in resp.text

    def test_n_points_out_of_range(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 2}
                }
            },
        )
        assert resp.status_code == 422, resp.text

    def test_design_for_unconfigured_parameter_rejected(self, client, both_param_run):
        # Use a temperature-only source instead.
        h = both_param_run["headers"]
        scenario = _finalized_scenario(
            client, h, both_param_run["field"]["id"], both_param_run["state"]["id"],
            adjustments={"temperature_delta_c": 1.5}, name="TempOnly2",
        )
        run = _executed_run(client, h, scenario["id"])
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 5}
                }
            },
        )
        assert resp.status_code == 422, resp.text
        assert "not configured in the source execution" in resp.text

    def test_grid_refused_on_single_parameter_source(self, client, both_param_run):
        h = both_param_run["headers"]
        scenario = _finalized_scenario(
            client, h, both_param_run["field"]["id"], both_param_run["state"]["id"],
            adjustments={"temperature_delta_c": 1.5}, name="TempOnly3",
        )
        run = _executed_run(client, h, scenario["id"])
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                },
                "grid": True,
            },
        )
        assert resp.status_code == 422, resp.text
        assert "both supported parameters" in resp.text

    def test_non_result_bearing_run_refused(self, client, prepared):
        h = prepared["headers"]
        scenario = _finalized_scenario(client, h, prepared["field"]["id"], prepared["state"]["id"])
        # queued/running runs do not exist here (synchronous execution); use a
        # fabricated run id instead → 404, and a draft scenario's nonexistent
        # run cannot be reached. A finalized-but-unexecuted scenario has no
        # runs; the 404 path covers the routing gate.
        resp = client.post(
            f"/api/v1/scenario-executions/{uuid.uuid4()}/sensitivity-analyses",
            headers=h,
            json={},
        )
        assert resp.status_code == 404, resp.text

    def test_budget_exceeded(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        resp = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 21},
                    "precipitation_multiplier": {"lower": 0.5, "upper": 1.5, "n_points": 21},
                },
                "grid": True,
            },
        )
        assert resp.status_code == 422, resp.text
        assert "cap" in resp.text

    def test_tampered_parent_checksum_blocks_analysis(self, client, both_param_run, db):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        state_id = both_param_run["state"]["id"]
        original = both_param_run["state"]["checksum_sha256"]
        with db.begin():
            db.execute(
                text("UPDATE field_states SET checksum_sha256 = 'f' || substr(checksum_sha256, 2) WHERE id = :id"),
                {"id": state_id},
            )
        try:
            resp = client.post(
                f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
                headers=h,
                json={
                    "parameter_design": {
                        "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                    }
                },
            )
            assert resp.status_code == 409, resp.text
            assert "PARENT_STATE_CHECKSUM_MISMATCH" in resp.text or "RUN_VERIFICATION_FAILED" in resp.text
        finally:
            with db.begin():
                db.execute(
                    text("UPDATE field_states SET checksum_sha256 = :c WHERE id = :id"),
                    {"id": state_id, "c": original},
                )


# ------------------------------------------------------------- replay/immutability


class TestReplayAndImmutability:
    def test_fingerprint_replay_returns_same_analysis(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        body = {
            "parameter_design": {
                "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
            }
        }
        first = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses", headers=h, json=body
        ).json()
        second = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses", headers=h, json=body
        ).json()
        assert first["analysis_id"] == second["analysis_id"]
        assert first["output_checksum"] == second["output_checksum"]

    def test_idempotency_key_replay(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        body = {
            "parameter_design": {
                "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
            },
            "idempotency_key": "m74-replay-key",
        }
        first = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses", headers=h, json=body
        ).json()
        body2 = {
            "parameter_design": {
                "temperature_delta_c": {"lower": -1.0, "upper": 6.0, "n_points": 5}
            },
            "idempotency_key": "m74-replay-key",
        }
        second = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses", headers=h, json=body2
        ).json()
        assert first["analysis_id"] == second["analysis_id"]

    def test_result_bearing_analysis_frozen_by_trigger(self, client, both_param_run):
        h = both_param_run["headers"]
        run = both_param_run["run"]
        analysis = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=h,
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                }
            },
        ).json()
        from sqlalchemy.exc import DBAPIError

        from app.core.database import SessionLocal as SL

        with SL() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                session.execute(
                    text(
                        "UPDATE sensitivity_analyses SET evaluated_feature_count = "
                        "evaluated_feature_count + 1 WHERE id = :id"
                    ),
                    {"id": analysis["analysis_id"]},
                )
            session.rollback()
        # Content unchanged.
        resp = client.get(f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}", headers=h)
        assert resp.json()["evaluated_feature_count"] == analysis["evaluated_feature_count"]


# --------------------------------------------------------------- tenancy


class TestTenantIsolation:
    def test_other_tenant_gets_404(self, client, both_param_run):
        other = _second_user(client)
        run = both_param_run["run"]
        analysis = client.post(
            f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses",
            headers=both_param_run["headers"],
            json={
                "parameter_design": {
                    "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}
                }
            },
        ).json()
        for method, path in (
            ("get", f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}"),
            ("get", f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}/responses"),
            ("get", f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}/grid"),
            ("get", f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}/uncertainty"),
            ("post", f"/api/v1/sensitivity-analyses/{analysis['analysis_id']}/verify"),
            ("get", f"/api/v1/scenario-executions/{run['run_id']}/sensitivity-analyses"),
        ):
            resp = getattr(client, method)(path, headers=other)
            # An existing row from another tenant is Forbidden; a missing one
            # would be Not Found — both deny access.
            assert resp.status_code in (403, 404), (path, resp.status_code)

"""Integration: M7.2 scenario domain — lifecycle, immutability, lineage,
tenant isolation, comparison, reproducibility and honest unavailability."""

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
    "parent_field_state_id": None,  # filled at runtime
    "period": {"start": "2016-01-01", "end": "2017-12-31"},
    "adjustments": {"temperature_delta_c": 2.0, "water_allocation_multiplier": 0.7},
    "assumption_metadata": {
        "origin": "user_defined",
        "status": "hypothetical",
        "description": "User-defined stress experiment",
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
    body = {
        "period_start": "2015-01-01",
        "period_end": "2017-12-31",
        **payload,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/field-states", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    state = resp.json()
    assert state["status"] == "succeeded", state.get("error_summary")
    return state


def _prepared(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest(client, headers, field_id)
    run = _feature_run(client, headers, field_id)
    state = _field_state(client, headers, field_id, environmental_feature_run_id=run["run_id"])
    return headers, field_id, run, state


def _create_scenario(client, headers, field_id, **overrides):
    config = {**STRESS_CONFIG, **overrides.pop("configuration", {})}
    if config.get("parent_field_state_id") is None:
        config["parent_field_state_id"] = overrides.pop("_state_id")
    else:
        overrides.pop("_state_id", None)
    body = {
        "scenario_type": "user_defined_stress",
        "name": "Stress experiment",
        "configuration": config,
        **overrides,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/scenarios", headers=headers, json=body)
    return resp


def _observed_scenario(client, headers, field_id, state_id, **overrides):
    body = {
        "scenario_type": "historical_observed",
        "name": "Historical reference",
        "configuration": {
            "type": "historical_observed",
            "parent_field_state_id": state_id,
        },
        **overrides,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/scenarios", headers=headers, json=body)
    return resp


def _validated(client, headers, scenario_id):
    resp = client.post(f"/api/v1/scenarios/{scenario_id}/validate", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _finalized(client, headers, scenario_id):
    _validated(client, headers, scenario_id)
    resp = client.post(f"/api/v1/scenarios/{scenario_id}/finalize", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _second_user(client):
    """A genuinely separate second tenant (the cached auth_headers fixture
    would be the SAME user as farm_with_field's headers user)."""
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


# ---------------------------------------------------------------------------
# Creation & configuration contracts
# ---------------------------------------------------------------------------
class TestScenarioCreation:
    def test_create_stress_scenario(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        resp = _create_scenario(client, headers, field_id, _state_id=state["id"])
        assert resp.status_code == 200, resp.text
        scenario = resp.json()
        assert scenario["scenario_status"] == "draft"
        assert scenario["scenario_type"] == "user_defined_stress"
        assert scenario["evidence_classification"] == "hypothetical"
        assert scenario["evidence_label"] == "Hypothetical assumption — not observed data"
        assert scenario["parent_field_state_id"] == state["id"]
        assert scenario["parent_snapshot_checksum"] == state["checksum_sha256"]
        assert scenario["boundary_version"] == state["boundary_version"]
        assert scenario["configuration_checksum"]
        # explicit null semantics survive serialization
        adjustments = scenario["canonical_configuration"]["adjustments"]
        assert adjustments["precipitation_multiplier"] is None
        assert set(adjustments) == {
            "temperature_delta_c",
            "precipitation_multiplier",
            "precipitation_delta_mm",
            "water_allocation_multiplier",
            "seasonal_timing_shift_days",
            "rainfall_period_shift_days",
        }

    def test_create_observed_scenario(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        resp = _observed_scenario(client, headers, field_id, state["id"])
        assert resp.status_code == 200, resp.text
        scenario = resp.json()
        assert scenario["evidence_classification"] == "observed"
        assert scenario["evidence_label"] == "Observed historical condition"
        # inherits the parent period verbatim
        assert scenario["period"]["start"] == state["period"]["start"]
        assert scenario["period"]["end"] == state["period"]["end"]

    def test_create_rejects_unimplemented_types(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        for st in ("climate_projection", "weather_forecast"):
            body = {
                "scenario_type": st,
                "configuration": {"type": st, "parent_field_state_id": state["id"]},
            }
            resp = client.post(
                f"/api/v1/fields/{field_id}/scenarios", headers=headers, json=body
            )
            assert resp.status_code == 422, resp.text
            error = resp.json()["error"]
            assert error["code"] == "SCENARIO_TYPE_NOT_IMPLEMENTED"
            # the honest reason is carried in the structured details
            reasons = " ".join(str(d.get("reason", "")) for d in error["details"])
            assert ("no sourced, licensed projection dataset" in reasons) or (
                "forecast" in reasons and "provider" in reasons
            )

    def test_create_rejects_invalid_configuration(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        bad = {**STRESS_CONFIG, "parent_field_state_id": state["id"], "adjustments": {}}
        resp = _create_scenario(client, headers, field_id, configuration=bad, _state_id=state["id"])
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "SCENARIO_CONFIGURATION_INVALID"

    def test_create_rejects_unknown_adjustment_dimension(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        bad = {
            **STRESS_CONFIG,
            "parent_field_state_id": state["id"],
            "adjustments": {"soil_carbon_delta": 1.0},
        }
        resp = _create_scenario(client, headers, field_id, configuration=bad, _state_id=state["id"])
        assert resp.status_code == 422

    def test_create_rejects_conflicting_adjustments(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        bad = {
            **STRESS_CONFIG,
            "parent_field_state_id": state["id"],
            "adjustments": {"precipitation_multiplier": 0.8, "precipitation_delta_mm": -40.0},
        }
        resp = _create_scenario(client, headers, field_id, configuration=bad, _state_id=state["id"])
        assert resp.status_code == 422

    def test_create_rejects_parent_state_from_other_field(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        # second field, same farm
        resp = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/fields",
            headers=headers,
            json={
                "name": "Other Field",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.0, 30.0], [31.01, 30.0], [31.01, 30.01], [31.0, 30.01], [31.0, 30.0]]],
                },
                "crop_code": "maize",
            },
        )
        assert resp.status_code == 201, resp.text
        other_field_id = resp.json()["id"]
        resp = _create_scenario(client, headers, other_field_id, _state_id=state["id"])
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PARENT_STATE_MISMATCH"

    def test_create_rejects_unsucceeded_parent_state(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        resp = client.post(
            f"/api/v1/fields/{field_id}/field-states",
            headers=headers,
            json={
                "period_start": "2015-01-01",
                "period_end": "2017-12-31",
                "environmental_feature_run_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code in (404, 422)

    def test_idempotent_creation_replays_same_row(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        first = _create_scenario(
            client, headers, field_id, idempotency_key="key-1", _state_id=state["id"]
        ).json()
        second = _create_scenario(
            client, headers, field_id, idempotency_key="key-1", _state_id=state["id"]
        ).json()
        assert first["id"] == second["id"]

    def test_taxonomy_and_capabilities_endpoints(self, client):
        taxonomy = client.get("/api/v1/scenarios/types").json()
        types = {t["scenario_type"]: t for t in taxonomy["types"]}
        assert set(types) == {
            "historical_observed",
            "historical_perturbation",
            "user_defined_stress",
            "climate_projection",
            "weather_forecast",
        }
        assert types["climate_projection"]["capability"] == "not_implemented"
        assert types["weather_forecast"]["capability"] == "not_implemented"
        assert taxonomy["dimensions"]["soil"]["status"] == "not_implemented"
        assert taxonomy["dimensions"]["management"]["status"] == "not_implemented"

        capabilities = client.get("/api/v1/scenarios/capabilities").json()
        caps = {c["scenario_type"]: c["capability"] for c in capabilities["capabilities"]}
        assert caps["climate_projection"] == "not_implemented"
        assert capabilities["execution"]["scenario_execution"] == "not_implemented"
        assert "not predictive" in capabilities["digital_twin_level"]


# ---------------------------------------------------------------------------
# Validation & lifecycle
# ---------------------------------------------------------------------------
class TestValidationAndLifecycle:
    def test_validate_stress_scenario(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        result = _validated(client, headers, scenario["id"])
        assert result["validation_status"] == "conditionally_valid"  # soil/management etc.
        assert result["scenario_status"] == "conditionally_valid"
        assert "No simulation has been executed" in result["note"]
        dims = {d["dimension"]: d["status"] for d in result["validation_result"]["unsupported_dimensions"]}
        assert dims["soil"] == "not_implemented"
        assert dims["management"] == "not_implemented"

    def test_validate_observed_scenario(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _observed_scenario(client, headers, field_id, state["id"]).json()
        result = _validated(client, headers, scenario["id"])
        assert result["validation_status"] == "conditionally_valid"  # synthetic profile evidence

    def test_validation_record_is_immutable_and_appended(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        first = _validated(client, headers, scenario["id"])
        # re-validate (allowed from conditionally_valid via edit-reset path not needed: engine allows)
        second = _validated(client, headers, scenario["id"])
        assert first["record_id"] != second["record_id"]

    def test_finalize_requires_validation(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "SCENARIO_INVALID_STATE_TRANSITION"

    def test_finalize_freezes_definition(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        finalized = _finalized(client, headers, scenario["id"])
        assert finalized["scenario_status"] == "finalized"
        assert finalized["finalized_at"]

        checksum = finalized["configuration_checksum"]
        # PATCH rejected
        resp = client.patch(
            f"/api/v1/scenarios/{scenario['id']}",
            headers=headers,
            json={"name": "Renamed"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "SCENARIO_IMMUTABLE"
        # DELETE rejected
        resp = client.delete(f"/api/v1/scenarios/{scenario['id']}", headers=headers)
        assert resp.status_code == 409
        # re-validate rejected (validation_summary frozen with the row)
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=headers)
        assert resp.status_code == 409
        # DB trigger: even raw SQL cannot rewrite a finalized definition
        from app.core.database import SessionLocal

        session = SessionLocal()
        try:
            with pytest.raises(Exception):
                session.execute(
                    text(
                        "UPDATE scenarios SET canonical_configuration = "
                        "canonical_configuration || '{\"tampered\": true}'::jsonb "
                        "WHERE id = :sid"
                    ),
                    {"sid": uuid.UUID(scenario["id"])},
                )
                session.commit()
            session.rollback()
        finally:
            session.close()
        # checksum still verifiable
        verify = client.get(f"/api/v1/scenarios/{scenario['id']}/verify", headers=headers).json()
        assert verify["configuration_checksum_valid"] is True
        assert verify["stored_checksum"] == checksum

    def test_patch_resets_validation(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        _validated(client, headers, scenario["id"])
        resp = client.patch(
            f"/api/v1/scenarios/{scenario['id']}",
            headers=headers,
            json={
                "configuration": {
                    **STRESS_CONFIG,
                    "parent_field_state_id": state["id"],
                    "adjustments": {"temperature_delta_c": 3.5},
                }
            },
        )
        assert resp.status_code == 200, resp.text
        edited = resp.json()
        assert edited["scenario_status"] == "draft"
        assert edited["validation_summary"] == {}
        assert edited["canonical_configuration"]["adjustments"]["temperature_delta_c"] == 3.5
        # checksum changed with the assumption
        assert edited["configuration_checksum"] != scenario["configuration_checksum"]

    def test_draft_delete_and_archive(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.delete(f"/api/v1/scenarios/{scenario['id']}", headers=headers)
        assert resp.status_code == 200

        scenario2 = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.post(f"/api/v1/scenarios/{scenario2['id']}/archive", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["scenario_status"] == "archived"
        # archived stays retrievable and checksum-verifiable
        got = client.get(f"/api/v1/scenarios/{scenario2['id']}", headers=headers).json()
        assert got["scenario_status"] == "archived"
        verify = client.get(f"/api/v1/scenarios/{scenario2['id']}/verify", headers=headers).json()
        assert verify["configuration_checksum_valid"] is True

    def test_illegal_transition_archived_terminal(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        client.post(f"/api/v1/scenarios/{scenario['id']}/archive", headers=headers)
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=headers)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Versions & lineage
# ---------------------------------------------------------------------------
class TestVersionsAndLineage:
    def test_new_version_of_finalized_scenario(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        finalized = _finalized(client, headers, scenario["id"])

        new_config = {
            **STRESS_CONFIG,
            "parent_field_state_id": state["id"],
            "adjustments": {"temperature_delta_c": 4.0},
        }
        resp = client.post(
            f"/api/v1/scenarios/{scenario['id']}/versions",
            headers=headers,
            json={"configuration": new_config},
        )
        assert resp.status_code == 200, resp.text
        v2 = resp.json()
        assert v2["scenario_version"] == 2
        assert v2["lineage_kind"] == "revision"
        assert v2["parent_scenario_id"] == scenario["id"]
        assert v2["scenario_status"] == "draft"
        assert v2["parent_field_state_id"] == scenario["parent_field_state_id"]
        assert v2["configuration_checksum"] != finalized["configuration_checksum"]

        versions = client.get(f"/api/v1/scenarios/{scenario['id']}/versions", headers=headers).json()
        assert versions["chain_length"] == 2
        assert [v["scenario_version"] for v in versions["items"]] == [1, 2]

        lineage = client.get(f"/api/v1/scenarios/{scenario['id']}/lineage", headers=headers).json()
        assert len(lineage["children"]) == 1
        assert lineage["children"][0]["lineage_kind"] == "revision"

    def test_version_rejects_type_change(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        _finalized(client, headers, scenario["id"])
        resp = client.post(
            f"/api/v1/scenarios/{scenario['id']}/versions",
            headers=headers,
            json={"scenario_type": "historical_observed"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "SCENARIO_TYPE_MISMATCH"

    def test_version_requires_finalized_parent(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.post(
            f"/api/v1/scenarios/{scenario['id']}/versions",
            headers=headers,
            json={"configuration": {**STRESS_CONFIG, "parent_field_state_id": state["id"]}},
        )
        assert resp.status_code == 409

    def test_original_unchanged_after_versioning(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        before = client.get(f"/api/v1/scenarios/{scenario['id']}", headers=headers).json()
        _finalized(client, headers, scenario["id"])
        client.post(
            f"/api/v1/scenarios/{scenario['id']}/versions",
            headers=headers,
            json={
                "configuration": {
                    **STRESS_CONFIG,
                    "parent_field_state_id": state["id"],
                    "adjustments": {"temperature_delta_c": 5.0},
                }
            },
        )
        after = client.get(f"/api/v1/scenarios/{scenario['id']}", headers=headers).json()
        assert after["canonical_configuration"] == before["canonical_configuration"]
        assert after["configuration_checksum"] == before["configuration_checksum"]

    def test_branch_lineage(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        root = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = _create_scenario(
            client, headers, field_id, name="Branch", parent_scenario_id=root["id"], _state_id=state["id"]
        )
        assert resp.status_code == 200, resp.text
        branch = resp.json()
        assert branch["lineage_kind"] == "branch"
        assert branch["scenario_version"] == 1
        assert branch["parent_scenario_id"] == root["id"]
        lineage = client.get(f"/api/v1/scenarios/{branch['id']}/lineage", headers=headers).json()
        assert lineage["ancestors"][0]["id"] == root["id"]


# ---------------------------------------------------------------------------
# Parent protection & reproducibility
# ---------------------------------------------------------------------------
class TestParentProtectionAndReproducibility:
    def test_referenced_parent_state_delete_restricted(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        _create_scenario(client, headers, field_id, _state_id=state["id"])
        from app.core.database import SessionLocal

        session = SessionLocal()
        try:
            with pytest.raises(Exception):
                session.execute(
                    text("DELETE FROM field_states WHERE id = :sid"),
                    {"sid": uuid.UUID(state["id"])},
                )
                session.commit()
            session.rollback()
        finally:
            session.close()

    def test_scenario_creation_does_not_mutate_parent_state(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        before = client.get(
            f"/api/v1/field-states/{state['id']}?include_manifest=true", headers=headers
        ).json()
        _create_scenario(client, headers, field_id, _state_id=state["id"])
        after = client.get(
            f"/api/v1/field-states/{state['id']}?include_manifest=true", headers=headers
        ).json()
        assert before == after
        # historical observations untouched: manifest hash identical
        assert (
            before["observation_manifest_sha256"] == after["observation_manifest_sha256"]
        )

    def test_identical_definitions_identical_checksums(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        a = _create_scenario(
            client, headers, field_id, name="A", _state_id=state["id"]
        ).json()
        b = _create_scenario(
            client, headers, field_id, name="B", _state_id=state["id"]
        ).json()
        assert a["id"] != b["id"]
        # name is UI metadata — same configuration → same checksum
        assert a["configuration_checksum"] == b["configuration_checksum"]

    def test_parent_checksum_pinned_by_value(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        assert scenario["parent_snapshot_checksum"] == state["checksum_sha256"]
        verify = client.get(f"/api/v1/scenarios/{scenario['id']}/verify", headers=headers).json()
        assert verify["parent_state_exists"] is True
        assert verify["parent_snapshot_checksum_matches"] is True
        assert verify["boundary_version_record_exists"] is True


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class TestComparison:
    def test_identical_definitions_no_diffs(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        a = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        b = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.get(
            f"/api/v1/scenarios/{a['id']}/compare",
            params={"against": b["id"]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["identical_configuration"] is True
        assert body["configuration_diff"] == []
        assert body["parents"]["same_parent_state"] is True
        assert body["warnings"] == []
        assert "No simulated environmental outputs" in body["note"]

    def test_different_assumptions_diff_reported(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        a = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        b = _create_scenario(
            client,
            headers,
            field_id,
            configuration={
                **STRESS_CONFIG,
                "parent_field_state_id": state["id"],
                "adjustments": {"temperature_delta_c": 3.0, "water_allocation_multiplier": 0.7},
            },
            _state_id=state["id"],
        ).json()
        body = client.get(
            f"/api/v1/scenarios/{a['id']}/compare",
            params={"against": b["id"]},
            headers=headers,
        ).json()
        assert body["identical_configuration"] is False
        paths = [d["path"] for d in body["configuration_diff"]]
        assert "adjustments.temperature_delta_c" in paths
        assert "adjustments.temperature_delta_c" in body["changed_assumptions"]

    def test_different_boundary_versions_warned(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        a = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        # new boundary version on the same field (GeoJSON polygon payload)
        resp = client.post(
            f"/api/v1/fields/{field_id}/boundary-versions",
            headers=headers,
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[31.2, 30.2], [31.21, 30.2], [31.21, 30.21], [31.2, 30.21], [31.2, 30.2]]
                    ],
                },
                "change_reason": "re-survey",
            },
        )
        assert resp.status_code in (200, 201), resp.text
        _ingest(client, headers, field_id)
        run2 = _feature_run(client, headers, field_id)
        state2 = _field_state(client, headers, field_id, environmental_feature_run_id=run2["run_id"])
        b = _create_scenario(client, headers, field_id, _state_id=state2["id"]).json()
        body = client.get(
            f"/api/v1/scenarios/{a['id']}/compare",
            params={"against": b["id"]},
            headers=headers,
        ).json()
        assert body["parents"]["boundary_versions_equal"] is False
        assert body["parents"]["same_parent_state"] is False
        assert any("DIFFERENT parent Field States" in w for w in body["warnings"])

    def test_observed_vs_hypothetical_comparison_flagged(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        observed = _observed_scenario(client, headers, field_id, state["id"]).json()
        hypothetical = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        body = client.get(
            f"/api/v1/scenarios/{observed['id']}/compare",
            params={"against": hypothetical["id"]},
            headers=headers,
        ).json()
        assert body["evidence_classes_differ"] is True
        assert any("NOT equivalent evidence" in w for w in body["warnings"])

    def test_cross_tenant_comparison_forbidden(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        a = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        other = _second_user(client)
        resp = client.get(
            f"/api/v1/scenarios/{a['id']}/compare",
            params={"against": a["id"]},
            headers=other,
        )
        assert resp.status_code in (403, 404)  # platform convention: foreign objects 403/404


# ---------------------------------------------------------------------------
# Security & tenancy
# ---------------------------------------------------------------------------
class TestSecurityAndTenancy:
    def test_cross_tenant_scenario_access_404(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        other = _second_user(client)
        resp = client.get(f"/api/v1/scenarios/{scenario['id']}", headers=other)
        assert resp.status_code in (403, 404)  # foreign resource: 403 per identity convention
        resp = client.get(f"/api/v1/fields/{field_id}/scenarios", headers=other)
        assert resp.status_code in (403, 404)

    def test_cross_tenant_idempotency_is_field_scoped(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        mine = _create_scenario(
            client, headers, field_id, idempotency_key="shared-key", _state_id=state["id"]
        ).json()
        # another tenant cannot replay the key against their own field
        other = _second_user(client)
        resp = client.post(
            "/api/v1/farms",
            headers=other,
            json={"name": "Other Farm", "country_code": "EG", "timezone": "Africa/Cairo", "currency_code": "EGP"},
        )
        farm_id = resp.json()["id"]
        resp = client.post(
            f"/api/v1/farms/{farm_id}/fields",
            headers=other,
            json={
                "name": "Their Field",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[32.0, 31.0], [32.01, 31.0], [32.01, 31.01], [32.0, 31.01], [32.0, 31.0]]],
                },
                "crop_code": "maize",
            },
        )
        their_field = resp.json()["id"]
        resp = client.post(
            f"/api/v1/fields/{their_field}/scenarios",
            headers=other,
            json={
                "scenario_type": "user_defined_stress",
                "idempotency_key": "shared-key",
                "configuration": {
                    "type": "user_defined_stress",
                    "parent_field_state_id": str(uuid.uuid4()),
                    "period": {"start": "2016-01-01", "end": "2017-12-31"},
                    "adjustments": {"temperature_delta_c": 1.0},
                },
            },
        )
        # their field has no such state → 422 (never silently replays mine)
        assert resp.status_code == 422

    def test_unauthenticated_access_unauthorized(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize")
        assert resp.status_code == 401
        resp = client.get(f"/api/v1/scenarios/{scenario['id']}")
        assert resp.status_code == 401

    def test_scenario_id_enumeration_404(self, client, auth_headers):
        headers = auth_headers[0]
        random_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/scenarios/{random_id}", headers=headers)
        assert resp.status_code == 404

    def test_double_finalize_conflict(self, client, farm_with_field):
        headers, field_id, run, state = _prepared(client, farm_with_field)
        scenario = _create_scenario(client, headers, field_id, _state_id=state["id"]).json()
        _finalized(client, headers, scenario["id"])
        resp = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "SCENARIO_IMMUTABLE"

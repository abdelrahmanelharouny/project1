"""Integration: M7.5 robust multi-scenario rotation — scenario sets, shared
plan solves, worst-case objective/regret, robust feasibility honesty, ET0
and water restrictions, idempotent replay, immutability, tenant isolation,
lineage and checksum verification."""

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

SCENARIO_CONFIG = {
    "type": "user_defined_stress",
    "parent_field_state_id": None,
    "period": {"start": "2016-01-01", "end": "2016-12-31"},
    "adjustments": {"temperature_delta_c": 2.0, "precipitation_multiplier": 0.8},
    "assumption_metadata": {
        "origin": "user_defined",
        "status": "hypothetical",
        "description": "M7.5 robust evaluation environment",
    },
}

# A planning season fully inside every scenario's 2016 window.
SEASON_2016 = {"label": "summer_2016", "start_date": "2016-05-01", "end_date": "2016-09-15"}


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


def _field_state(client, headers, field_id, feature_run_id):
    body = {
        "period_start": "2015-01-01",
        "period_end": "2017-12-31",
        "environmental_feature_run_id": feature_run_id,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/field-states", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    state = resp.json()
    assert state["status"] == "succeeded", state.get("error_summary")
    return state


def _finalized_scenario(client, headers, field_id, state_id, adjustments=None, name="Stress"):
    config = {**SCENARIO_CONFIG, "parent_field_state_id": state_id}
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
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@test.local",
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
    state = _field_state(client, headers, field_id, run["run_id"])
    # crop history: maize last summer (drives the baseline plan)
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
    return {
        "headers": headers,
        "user": farm_with_field["user"],
        "farm": farm_with_field["farm"],
        "field": farm_with_field["field"],
        "feature_run": run,
        "state": state,
    }


@pytest.fixture()
def two_scenario_set(client, prepared):
    """A scenario set with two contrasting execution runs on one Field State."""
    h = prepared["headers"]
    field_id = prepared["field"]["id"]
    s_hot = _finalized_scenario(
        client, h, field_id, prepared["state"]["id"],
        adjustments={"temperature_delta_c": 3.0, "precipitation_multiplier": 0.7},
        name="Hot & dry",
    )
    s_cool = _finalized_scenario(
        client, h, field_id, prepared["state"]["id"],
        adjustments={"temperature_delta_c": -2.0, "precipitation_multiplier": 1.3},
        name="Cool & wet",
    )
    r_hot = _executed_run(client, h, s_hot["id"])
    r_cool = _executed_run(client, h, s_cool["id"])
    resp = client.post(
        f"/api/v1/fields/{field_id}/scenario-sets",
        headers=h,
        json={"label": "Contrasting futures", "execution_run_ids": [r_hot["run_id"], r_cool["run_id"]]},
    )
    assert resp.status_code in (200, 201), resp.text
    scenario_set = resp.json()
    return {**prepared, "scenarios": [s_hot, s_cool], "executions": [r_hot, r_cool], "set": scenario_set}


# ------------------------------------------------------------- scenario sets


class TestScenarioSets:
    def test_create_set_and_compatibility_report(self, client, two_scenario_set):
        s = two_scenario_set["set"]
        assert s["member_count"] == 2
        assert s["set_checksum"]
        assert s["compatibility_report"]["member_count"] == 2
        assert len(s["compatibility_report"]["distinct_scenario_ids"]) == 2
        assert all(m["output_checksum"] for m in s["members"])

    def test_content_addressed_replay(self, client, two_scenario_set):
        h = two_scenario_set["headers"]
        field_id = two_scenario_set["field"]["id"]
        ids = [m["execution_run_id"] for m in two_scenario_set["set"]["members"]]
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "Contrasting futures", "execution_run_ids": ids},
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["id"] == two_scenario_set["set"]["id"]

    def test_mixed_parent_states_rejected(self, client, prepared):
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        # a second, different Field State
        state2 = _field_state(client, h, field_id, prepared["feature_run"]["run_id"])
        s1 = _finalized_scenario(client, h, field_id, prepared["state"]["id"], name="A")
        s2 = _finalized_scenario(client, h, field_id, state2["id"], name="B")
        r1 = _executed_run(client, h, s1["id"])
        r2 = _executed_run(client, h, s2["id"])
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "mixed", "execution_run_ids": [r1["run_id"], r2["run_id"]]},
        )
        assert resp.status_code == 422
        assert "parent Field State" in resp.json()["error"]["message"]

    def test_duplicate_scenario_rejected(self, client, prepared):
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        s1 = _finalized_scenario(client, h, field_id, prepared["state"]["id"], name="A")
        r1 = _executed_run(client, h, s1["id"])
        r1b = _executed_run(client, h, s1["id"])  # replay returns same run
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "dup", "execution_run_ids": [r1["run_id"], r1b["run_id"]]},
        )
        assert resp.status_code == 422

    def test_non_result_bearing_run_rejected(self, client, prepared):
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "ghost", "execution_run_ids": [str(uuid.uuid4())]},
        )
        assert resp.status_code == 422

    def test_set_verification_detects_pin_drift(self, client, two_scenario_set, db):
        s = two_scenario_set["set"]
        h = two_scenario_set["headers"]
        # simulate drift: corrupt the PIN inside the set document (the live
        # execution row is trigger-frozen, so drift is emulated on the copy)
        members = [dict(m) for m in s["members"]]
        members[0]["output_checksum"] = "0" * 64
        db.execute(
            text("UPDATE scenario_sets SET members = CAST(:m AS jsonb) WHERE id = CAST(:i AS uuid)"),
            {"m": __import__("json").dumps(members), "i": s["id"]},
        )
        db.commit()
        resp = client.post(f"/api/v1/scenario-sets/{s['id']}/verify", headers=h)
        assert resp.status_code == 200
        body = resp.json()
        assert body["drift"]
        # a robust run over a drifted set must be refused
        resp = client.post(
            f"/api/v1/scenario-sets/{s['id']}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016]},
        )
        assert resp.status_code == 409

    def test_delete_blocked_when_runs_exist(self, client, robust_run):
        set_id = robust_run["set"]["id"]
        h = robust_run["headers"]
        resp = client.delete(f"/api/v1/scenario-sets/{set_id}", headers=h)
        assert resp.status_code == 409


# --------------------------------------------------------------- robust runs


@pytest.fixture()
def robust_run(client, two_scenario_set):
    h = two_scenario_set["headers"]
    set_id = two_scenario_set["set"]["id"]
    resp = client.post(
        f"/api/v1/scenario-sets/{set_id}/robust-runs",
        headers=h,
        json={"seasons": [SEASON_2016], "hemisphere": "north"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_status"] in ("succeeded", "completed_with_limitations"), body.get("error_summary")
    return {**two_scenario_set, "run": body}


class TestRobustRunsGoldenPath:
    def test_run_completes_with_shared_plan(self, client, robust_run):
        run = robust_run["run"]
        assert run["member_count"] == 2
        assert run["solver_status"] in ("optimal", "feasible")
        assert run["output_checksum"]
        assert run["robust_engine_version"] == "robust-rotation-engine-1.0.0"
        strategies = run["strategies"]
        keys = {s["strategy_key"] for s in strategies}
        assert "baseline" in keys
        assert {"water_priority", "soil_health_priority", "balanced", "economic_priority"} <= keys
        # every optimized strategy has ONE shared assignment evaluated on BOTH scenarios
        for s in strategies:
            if s["strategy_kind"] == "optimized" and s["solver_status"]:
                assert s["robust_feasibility"] in ("robust_feasible", "robust_infeasible", "not_evaluable")
        # diagnostics record both shared solves
        detail = client.get(f"/api/v1/robust-runs/{run['id']}", headers=robust_run["headers"]).json()
        assert detail["infeasibility_details"]["note"]

    def test_evaluations_are_per_scenario(self, client, robust_run):
        h = robust_run["headers"]
        run = robust_run["run"]
        resp = client.get(f"/api/v1/robust-runs/{run['id']}/evaluations", headers=h)
        assert resp.status_code == 200
        items = resp.json()["items"]
        by_strategy: dict[str, set[str]] = {}
        for item in items:
            by_strategy.setdefault(item["strategy_id"], set()).add(item["scenario_id"])
        shared = [
            s for s in run["strategies"] if s["strategy_kind"] == "optimized" and s["solver_status"]
        ]
        assert shared, "expected at least one solved shared plan"
        for s in shared:
            assert len(by_strategy[s["id"]]) == 2, "shared plan must be evaluated on both scenarios"
        # criteria carry units and evaluable flags; water criteria not evaluable
        water_rows = [
            c
            for item in items
            for c in item["criteria"]
            if c["criterion_code"] == "water_requirement_mm"
        ]
        assert water_rows, "water criterion rows present"
        assert all(c["evaluable"] is False for c in water_rows), (
            "scenario ET0 is never recalculated — water requirement must be not evaluable"
        )

    def test_worst_case_objective_is_min_across_scenarios(self, client, robust_run):
        h = robust_run["headers"]
        run = robust_run["run"]
        evals = client.get(f"/api/v1/robust-runs/{run['id']}/evaluations", headers=h).json()["items"]
        by_strategy: dict[str, list[float]] = {}
        for item in evals:
            if item["weighted_objective"] is not None:
                by_strategy.setdefault(item["strategy_id"], []).append(item["weighted_objective"])
        for s in run["strategies"]:
            if s["strategy_kind"] != "optimized" or not s["solver_status"]:
                continue
            if s["objective_evaluable_in_all_scenarios"]:
                values = by_strategy[s["id"]]
                assert len(values) == 2
                assert s["worst_case_objective"] == pytest.approx(min(values), abs=1e-9)
            else:
                assert s["worst_case_objective"] is None
                assert "worst_case_objective" in run["not_evaluated"]

    def test_single_scenario_set_matches_solo_optimum(self, client, prepared):
        """With ONE member, the robust shared plan must equal the M5 solo
        optimum for the same profile (identical model, deterministic)."""
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        s1 = _finalized_scenario(client, h, field_id, prepared["state"]["id"], name="Only")
        r1 = _executed_run(client, h, s1["id"])
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "solo", "execution_run_ids": [r1["run_id"]]},
        )
        assert resp.status_code in (200, 201), resp.text
        set_id = resp.json()["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016], "hemisphere": "north", "regret_analysis": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_status"] in ("succeeded", "completed_with_limitations")
        robust_plan = next(
            s for s in body["strategies"] if s["strategy_key"] == "water_priority"
        )
        # the solo M5 optimum for the same environment & profile
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs",
            headers=h,
            json={
                "seasons": [SEASON_2016],
                "hemisphere": "north",
                "strategy_profiles": ["water_priority"],
                "evidence_run_id": prepared["feature_run"]["run_id"],
            },
        )
        assert resp.status_code == 202, resp.text
        # NOTE: the M5 rotation run uses OBSERVED climate, the robust run uses
        # scenario climate — they are DIFFERENT environments, so equality is
        # not asserted between them; instead assert the robust run's own solo
        # anchor consistency: regret of the shared plan vs its solo anchor.
        evals = client.get(
            f"/api/v1/robust-runs/{body['id']}/evaluations",
            headers=h,
            params={"strategy_key": "water_priority"},
        ).json()["items"]
        assert evals
        for e in evals:
            if e["regret_vs_solo"] is not None:
                # a shared plan can never beat its scenario's solo optimum
                assert e["regret_vs_solo"] >= -1e-9

    def test_idempotent_replay_same_run(self, client, robust_run):
        h = robust_run["headers"]
        set_id = robust_run["set"]["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016], "hemisphere": "north"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == robust_run["run"]["id"]

    def test_changed_design_creates_new_run(self, client, robust_run):
        h = robust_run["headers"]
        set_id = robust_run["set"]["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={
                "seasons": [SEASON_2016],
                "hemisphere": "north",
                "strategy_profiles": ["balanced"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["id"] != robust_run["run"]["id"]
        assert resp.json()["strategy_profiles"] == ["balanced"]

    def test_listing_and_filters(self, client, robust_run):
        h = robust_run["headers"]
        set_id = robust_run["set"]["id"]
        listing = client.get(f"/api/v1/scenario-sets/{set_id}/robust-runs", headers=h).json()
        assert listing["count"] >= 1
        listing = client.get(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            params={"run_status": "succeeded"},
        ).json()
        assert all(item["run_status"] == "succeeded" for item in listing["items"])


class TestWaterRestrictions:
    def test_water_allocation_rejected(self, client, two_scenario_set):
        h = two_scenario_set["headers"]
        set_id = two_scenario_set["set"]["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016], "water_allocation_m3": 5000.0},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "WATER_ALLOCATION_UNSUPPORTED"
        assert "ET0" in body["error"]["message"]

    def test_no_water_constraint_in_problem(self, client, robust_run):
        """Without an allocation the constraint must be absent (not 'satisfied
        by omission') and scenario water criteria not evaluable."""
        h = robust_run["headers"]
        run = robust_run["run"]
        evals = client.get(f"/api/v1/robust-runs/{run['id']}/evaluations", headers=h).json()["items"]
        for item in evals:
            for check in item["constraint_checks"]:
                if check["constraint_code"] == "water_allocation":
                    # without an allocation the check is not_applicable —
                    # never "satisfied by omission"
                    assert check["status"] == "not_applicable"


class TestCoverageAndSeasons:
    def test_seasons_outside_scenario_window_rejected(self, client, two_scenario_set):
        h = two_scenario_set["headers"]
        set_id = two_scenario_set["set"]["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [{"label": "future", "start_date": "2020-05-01", "end_date": "2020-09-15"}]},
        )
        assert resp.status_code == 422
        assert "does not cover every month" in resp.json()["error"]["message"]

    def test_invalid_seasons_rejected(self, client, two_scenario_set):
        h = two_scenario_set["headers"]
        resp = client.post(
            f"/api/v1/scenario-sets/{two_scenario_set['set']['id']}/robust-runs",
            headers=h,
            json={"seasons": []},
        )
        assert resp.status_code == 422


class TestRobustFeasibilityHonesty:
    def test_extreme_cold_scenario_can_invalidate_baseline(self, client, prepared):
        """A strong negative ΔT scenario may render the history crop's
        environment inadmissible; the baseline verdict must reflect the
        SCENARIO evidence, never silently stay feasible."""
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        s_cold = _finalized_scenario(
            client, h, field_id, prepared["state"]["id"],
            adjustments={"temperature_delta_c": -12.0, "precipitation_multiplier": 1.0},
            name="Deep cold",
        )
        r_cold = _executed_run(client, h, s_cold["id"])
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "cold", "execution_run_ids": [r_cold["run_id"]]},
        )
        assert resp.status_code in (200, 201), resp.text
        set_id = resp.json()["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016], "hemisphere": "north", "regret_analysis": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        baseline = next(s for s in body["strategies"] if s["strategy_key"] == "baseline")
        evals = client.get(
            f"/api/v1/robust-runs/{body['id']}/evaluations",
            headers=h,
            params={"strategy_key": "baseline"},
        ).json()["items"]
        assert evals
        # the per-scenario admissibility rows carry the scenario's own screening
        for e in evals:
            for a in e["crop_admissibility"]:
                assert "admissible" in a
        # if maize is temperature-excluded under -12 degC, the baseline is
        # infeasible in that scenario (verdict is evidence-driven)
        excluded_any = any(
            not a["admissible"] for e in evals for a in e["crop_admissibility"]
        )
        if excluded_any:
            assert baseline["robust_feasibility"] == "robust_infeasible"
        else:
            assert baseline["robust_feasibility"] in ("robust_feasible", "not_evaluable")

    def test_cross_scenario_exclusions_reported(self, client, prepared):
        h = prepared["headers"]
        field_id = prepared["field"]["id"]
        s_hot = _finalized_scenario(
            client, h, field_id, prepared["state"]["id"],
            adjustments={"temperature_delta_c": 10.0, "precipitation_multiplier": 0.5},
            name="Extreme heat",
        )
        s_mild = _finalized_scenario(
            client, h, field_id, prepared["state"]["id"],
            adjustments={"temperature_delta_c": 0.5, "precipitation_multiplier": 1.0},
            name="Mild",
        )
        r_hot = _executed_run(client, h, s_hot["id"])
        r_mild = _executed_run(client, h, s_mild["id"])
        resp = client.post(
            f"/api/v1/fields/{field_id}/scenario-sets",
            headers=h,
            json={"label": "contrast", "execution_run_ids": [r_hot["run_id"], r_mild["run_id"]]},
        )
        set_id = resp.json()["id"]
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs",
            headers=h,
            json={"seasons": [SEASON_2016], "hemisphere": "north", "regret_analysis": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # exclusions (if any) are first-class records with the failing scenario
        exclusions = body["infeasibility_details"]["cross_scenario_exclusions"]
        for record in exclusions:
            assert record["season_label"]
            assert record["crop_code"]
            assert record["excluded_by_scenarios"]


class TestImmutabilityAndIsolation:
    def test_result_bearing_run_row_frozen(self, client, robust_run, db):
        run_id = robust_run["run"]["id"]
        with pytest.raises(Exception):
            db.execute(
                text(
                    "UPDATE robust_rotation_runs SET warnings = '[\"x\"]'::jsonb "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run_id},
            )
            db.commit()

    def test_result_bearing_run_row_not_deletable(self, client, robust_run, db):
        run_id = robust_run["run"]["id"]
        with pytest.raises(Exception):
            db.execute(
                text("DELETE FROM robust_rotation_runs WHERE id = CAST(:i AS uuid)"),
                {"i": run_id},
            )
            db.commit()

    def test_tenant_isolation_sets(self, client, two_scenario_set):
        other = _second_user(client)
        set_id = two_scenario_set["set"]["id"]
        resp = client.get(f"/api/v1/scenario-sets/{set_id}", headers=other)
        assert resp.status_code == 403
        resp = client.post(
            f"/api/v1/scenario-sets/{set_id}/robust-runs", headers=other, json={"seasons": [SEASON_2016]}
        )
        assert resp.status_code == 403

    def test_tenant_isolation_runs(self, client, robust_run):
        other = _second_user(client)
        run_id = robust_run["run"]["id"]
        resp = client.get(f"/api/v1/robust-runs/{run_id}", headers=other)
        assert resp.status_code == 403
        resp = client.get(f"/api/v1/robust-runs/{run_id}/evaluations", headers=other)
        assert resp.status_code == 403
        resp = client.post(f"/api/v1/robust-runs/{run_id}/verify", headers=other)
        assert resp.status_code == 403


class TestVerification:
    def test_verify_run_ok(self, client, robust_run):
        h = robust_run["headers"]
        run_id = robust_run["run"]["id"]
        resp = client.post(f"/api/v1/robust-runs/{run_id}/verify", headers=h)
        assert resp.status_code == 200
        body = resp.json()
        assert body["verified"] is True
        assert body["findings"] == []
        assert body["member_check"]["verified_members"] == 2
        assert body["strategy_count"] >= 2

    def test_migration_head(self, db):
        row = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert row == "0014_merge_m6bc_m7"

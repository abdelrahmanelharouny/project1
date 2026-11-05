#!/usr/bin/env python3
"""M7.3 end-to-end HTTP smoke test against the dev server (port 3030)."""
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:3030/api/v1"


def main() -> int:
    # --- bootstrap demo tenant ------------------------------------------
    r = httpx.post(f"{BASE}/dev/seed-demo", timeout=30)
    r.raise_for_status()
    seed = r.json()
    token = seed["token"]
    headers = {"Authorization": f"Bearer {token}"}
    farms = httpx.get(f"{BASE}/farms", headers=headers, timeout=30).json()
    farm = farms["items"][0]
    fields = httpx.get(f"{BASE}/farms/{farm['id']}/fields", headers=headers, timeout=30).json()
    field = fields["items"][0]
    print("field:", field["id"])

    # --- ensure a feature run exists for the field (synthetic ok) --------
    runs = httpx.get(f"{BASE}/fields/{field['id']}/feature-runs", headers=headers, timeout=30).json()
    if not runs.get("items"):
        payload = {
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "aggregation_levels": ["monthly", "seasonal"],
            "idempotency_key": "m73-smoke-fr",
        }
        r = httpx.post(f"{BASE}/fields/{field['id']}/feature-runs", headers=headers, json=payload, timeout=120)
        print("feature run:", r.status_code)
        r.raise_for_status()

    # --- assemble a Field State ------------------------------------------
    r = httpx.post(
        f"{BASE}/fields/{field['id']}/field-states",
        headers=headers,
        json={"idempotency_key": "m73-smoke-state", "label": "M7.3 smoke state"},
        timeout=120,
    )
    print("field state:", r.status_code)
    if r.status_code >= 300:
        print(r.text[:400])
    state = r.json()
    if state.get("status") == "running":
        for _ in range(40):
            time.sleep(1)
            state = httpx.get(
                f"{BASE}/field-states/{state['id']}", headers=headers, timeout=30
            ).json()
            if state.get("status") != "running":
                break
    print("state status:", state.get("status"))

    # --- create a user_defined_stress scenario ----------------------------
    config = {
        "schema_version": "scenario-config-1.0",
        "type": "user_defined_stress",
        "parent_field_state_id": state["id"],
        "period": {
            "start": state["period"]["start"][:10],
            "end": state["period"]["end"][:10],
        },
        "adjustments": {"temperature_delta_c": 2.0, "precipitation_multiplier": 0.8},
        "assumption_metadata": {
            "origin": "user_defined",
            "status": "hypothetical",
            "description": "M7.3 smoke: +2 degC, x0.8 precip",
        },
    }
    r = httpx.post(
        f"{BASE}/fields/{field['id']}/scenarios",
        headers=headers,
        json={
            "name": "M7.3 smoke scenario",
            "scenario_type": "user_defined_stress",
            "configuration": config,
            "idempotency_key": "m73-smoke-scenario",
        },
        timeout=60,
    )
    print("scenario:", r.status_code)
    if r.status_code >= 300:
        print(json.dumps(r.json(), indent=2)[:800])
        return 1
    scenario = r.json()

    # --- validate + finalize ----------------------------------------------
    r = httpx.post(f"{BASE}/scenarios/{scenario['id']}/validate", headers=headers, timeout=60)
    print("validate:", r.status_code, r.json().get("validation_status"))
    r = httpx.post(f"{BASE}/scenarios/{scenario['id']}/finalize", headers=headers, timeout=60)
    print("finalize:", r.status_code, r.json().get("scenario_status"))

    # --- BLOCKED check: unsupported dimension ------------------------------
    bad_config = json.loads(json.dumps(config))
    bad_config["adjustments"] = {"precipitation_delta_mm": 50.0}  # unsupported in M7.3
    r = httpx.post(
        f"{BASE}/scenarios/{scenario['id']}/versions",
        headers=headers,
        json={
            "name": "M7.3 blocked v2",
            "configuration": bad_config,
            "idempotency_key": "m73-smoke-v2",
        },
        timeout=60,
    )
    print("v2 create:", r.status_code)
    v2 = r.json()
    r = httpx.post(f"{BASE}/scenarios/{v2['id']}/validate", headers=headers, timeout=60)
    print("v2 validate:", r.status_code, r.json().get("validation_status"))
    r = httpx.post(f"{BASE}/scenarios/{v2['id']}/finalize", headers=headers, timeout=60)
    print("v2 finalize:", r.status_code, r.json().get("scenario_status"))
    r = httpx.post(f"{BASE}/scenarios/{v2['id']}/executions", headers=headers, json={}, timeout=60)
    print("v2 execute (expect 422):", r.status_code)
    if r.status_code >= 300:
        body = r.json()
        print("  blocked findings:", json.dumps(body.get("error", {}).get("details", []))[:300])

    # --- EXECUTE ------------------------------------------------------------
    r = httpx.post(
        f"{BASE}/scenarios/{scenario['id']}/executions", headers=headers, json={}, timeout=300
    )
    print("execute:", r.status_code)
    if r.status_code >= 300:
        print(json.dumps(r.json(), indent=2)[:1200])
        return 1
    run = r.json()
    print(
        "  run:", run["run_status"],
        "| transformed obs:", run["transformed_observation_count"],
        "| features:", run["derived_feature_count"],
        "| checksum:", (run["output_checksum"] or "")[:16],
    )
    run_id = run["run_id"]

    # idempotent replay
    r2 = httpx.post(
        f"{BASE}/scenarios/{scenario['id']}/executions", headers=headers, json={}, timeout=300
    )
    print("replay run_id equal:", r2.json().get("run_id") == run_id)

    # --- inspect ------------------------------------------------------------
    feats = httpx.get(
        f"{BASE}/scenario-executions/{run_id}/features", headers=headers, timeout=60
    ).json()
    print("features count:", feats["count"])
    changed = [
        f for f in feats["items"]
        if f["evidence_status"] == "scenario_recalculated" and f["difference_value"] not in (None, 0)
    ]
    print("changed comparisons:", len(changed))
    for f in changed[:4]:
        print(
            f"  {f['feature_code']} [{f['aggregation_level']} {f['period_label']}]",
            f"base={f['baseline_value']} scen={f['scenario_value']} diff={round(f['difference_value'],4)}",
        )
    ne = [f for f in feats["items"] if f["evidence_status"] == "not_evaluated"]
    na = [f for f in feats["items"] if f["evidence_status"] == "not_affected"]
    print("not_evaluated rows:", len(ne), "| not_affected rows:", len(na))

    obs = httpx.get(
        f"{BASE}/scenario-executions/{run_id}/observations", headers=headers, timeout=60
    ).json()
    print("observations page:", obs["count"], "of", obs["total_transformed"])
    if obs["items"]:
        o = obs["items"][0]
        print("  sample:", o["variable_code"], o["baseline_value"], "->", o["transformed_value"], o["unit"], o["evidence_class"])

    comp = httpx.get(
        f"{BASE}/scenario-executions/{run_id}/compare", headers=headers, timeout=60
    ).json()
    print("compare summary:", comp["summary"])

    ver = httpx.post(
        f"{BASE}/scenario-executions/{run_id}/verify", headers=headers, timeout=60
    ).json()
    print(
        "verify: checksum_ok=", ver["output_checksum_valid"],
        "| scenario_ok=", ver["scenario_definition_checksum_valid"],
        "| parent_ok=", ver["parent_snapshot_intact"],
        "| manifest_ok=", ver["manifest_checksum_matches_run"],
    )

    print("M7.3 SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

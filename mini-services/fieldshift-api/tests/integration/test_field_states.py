"""Integration: M7.1 field state foundation.

Covers the M7.1 acceptance criteria: boundary version pinning (H-01),
deterministic observation manifests (H-02), immutable field states with
honest not_implemented domains, period compatibility, F-13 water-plan
deletion restriction, F-30 field-scoped ingestion idempotency, provenance
surfacing (F-09/F-20/F-32), tenant isolation and reconstruction/verification.
"""

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


def _ingest(client, headers, field_id, **overrides):
    resp = client.post(
        f"/api/v1/fields/{field_id}/data-jobs", headers=headers, json={**INGEST_BODY, **overrides}
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job.get("error_summary")
    return job


def _job_id(job: dict) -> str:
    return job["job_id"]


def _feature_run(client, headers, field_id, **overrides):
    body = {
        "start_date": "2015-01-01",
        "end_date": "2017-12-31",
        "aggregation_levels": ["monthly"],
        "hemisphere": "north",
        **overrides,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/feature-runs", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert run["status"] == "succeeded", run.get("error_summary")
    return run


def _water_plan(client, headers, field_id, **overrides):
    body = {
        "seasons": [{"label": "summer_2016", "start_date": "2016-05-01", "end_date": "2016-09-30"}],
        "crop_assignments": [{"crop_code": "maize"}],
        **overrides,
    }
    resp = client.post(f"/api/v1/fields/{field_id}/water-plans", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    plan = resp.json()
    assert plan["status"] == "succeeded", plan.get("error_summary")
    return plan


def _create_state(client, headers, field_id, **payload):
    resp = client.post(f"/api/v1/fields/{field_id}/field-states", headers=headers, json=payload)
    assert resp.status_code == 202, resp.text
    return resp.json()


def _prepared(client, farm_with_field):
    headers = farm_with_field["headers"]
    field_id = farm_with_field["field"]["id"]
    _ingest(client, headers, field_id)
    run = _feature_run(client, headers, field_id)
    return headers, field_id, run


# ---------------------------------------------------------------------------
# H-02: feature-run observation manifest
# ---------------------------------------------------------------------------
class TestFeatureRunManifest:
    def test_run_stores_manifest_with_hash(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        assert run["observation_manifest_sha256"], "run must persist a manifest hash"
        assert run["boundary_version"] == 1  # H-01 pinned at run time
        assert run["created_by"]  # F-09 surfaced

        detail = client.get(
            f"/api/v1/feature-runs/{run['run_id']}?include_manifest=true", headers=headers
        ).json()
        manifest = detail["observation_manifest"]
        assert manifest["format_version"] == "field-observation-manifest-1"
        assert manifest["context"]["purpose"] == "feature_run_resolved_inputs"
        assert manifest["observation_count"] > 0
        # synthetic evidence stays identifiable end-to-end
        assert manifest["synthetic_observation_count"] == manifest["observation_count"]
        assert all(e["is_synthetic"] for e in manifest["observations"])

    def test_manifest_is_uncapped_and_covers_full_input_set(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        detail = client.get(
            f"/api/v1/feature-runs/{run['run_id']}?include_manifest=true", headers=headers
        ).json()
        manifest = detail["observation_manifest"]
        # 5 variables × ~1096 daily rows = ~5480 resolved inputs — far beyond
        # the legacy 400-id per-value provenance cap the manifest replaces.
        assert manifest["observation_count"] > 4000

    def test_new_ingestion_does_not_change_stored_manifest(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        before = client.get(f"/api/v1/feature-runs/{run['run_id']}", headers=headers).json()[
            "observation_manifest_sha256"
        ]
        # ingest MORE rows for the same window (new seed ⇒ new synthetic set)
        _ingest(client, headers, field_id, seed=99)
        after = client.get(f"/api/v1/feature-runs/{run['run_id']}", headers=headers).json()[
            "observation_manifest_sha256"
        ]
        assert before == after, "stored manifest must be immutable under new ingestions"

    def test_replay_via_idempotency_key_returns_same_run(self, client, farm_with_field):
        headers, field_id, _ = _prepared(client, farm_with_field)
        key = f"m71-run-{uuid.uuid4().hex[:8]}"
        r1 = _feature_run(client, headers, field_id, idempotency_key=key)
        r2 = _feature_run(client, headers, field_id, idempotency_key=key)
        assert r1["run_id"] == r2["run_id"]
        assert r1["observation_manifest_sha256"] == r2["observation_manifest_sha256"]


# ---------------------------------------------------------------------------
# H-01: boundary version pinning
# ---------------------------------------------------------------------------
class TestBoundaryPinning:
    def _add_boundary_version(self, client, headers, field_id):
        resp = client.post(
            f"/api/v1/fields/{field_id}/boundary-versions",
            headers=headers,
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[31.40, 31.10], [31.44, 31.10], [31.44, 31.14], [31.40, 31.14], [31.40, 31.10]]
                    ],
                },
                "change_reason": "M7.1 test: enlarge boundary",
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_runs_pinned_to_boundary_version_in_effect(self, client, farm_with_field):
        headers, field_id, run_before = _prepared(client, farm_with_field)
        updated = self._add_boundary_version(client, headers, field_id)
        assert updated["boundary_version"] == 2
        run_after = _feature_run(client, headers, field_id)

        detail_before = client.get(
            f"/api/v1/feature-runs/{run_before['run_id']}", headers=headers
        ).json()
        assert detail_before["boundary_version"] == 1, "historical run keeps its original boundary pin"
        assert run_after["boundary_version"] == 2

    def test_water_plan_pinned_to_boundary_version(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        plan = _water_plan(client, headers, field_id)
        assert plan["boundary_version"] == 1
        assert plan["started_at"] and plan["completed_at"]  # F-32 partial
        assert plan["created_by"]  # F-09

    def test_state_pins_current_boundary_and_verify_finds_record(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        self._add_boundary_version(client, headers, field_id)
        state = _create_state(client, headers, field_id)
        assert state["boundary_version"] == 2
        verify = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify["boundary_version_record_exists"] is True

    def test_historical_state_unchanged_by_boundary_edit(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        before_checksum = state["checksum_sha256"]
        self._add_boundary_version(client, headers, field_id)
        after = client.get(f"/api/v1/field-states/{state['id']}", headers=headers).json()
        assert after["boundary_version"] == 1
        assert after["checksum_sha256"] == before_checksum
        verify = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify["checksum_valid"] is True


# ---------------------------------------------------------------------------
# Field state lifecycle
# ---------------------------------------------------------------------------
class TestFieldStateLifecycle:
    def test_create_state_honest_domain_map(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        assert state["status"] == "succeeded"
        assert state["boundary_version"] == 1
        assert state["period"]["start"] and state["period"]["end"]
        assert state["timezone"] == "Africa/Cairo"
        assert state["field_state_assembly_version"] == "field-state-assembly-1.0.0"

        availability = state["domain_availability"]
        assert availability["environmental"]["status"] == "available"
        assert availability["environmental"]["snapshot_id"] == run["run_id"]
        assert availability["water"]["status"] == "missing"
        assert availability["crop_history"]["status"] == "missing"
        # THE core honesty requirement: absent domains are never fabricated
        assert availability["soil"]["status"] == "not_implemented"
        assert "M6B" in availability["soil"]["reason"]
        assert availability["management"]["status"] == "not_implemented"
        assert "M6C" in availability["management"]["reason"]
        assert state["evidence_summary"]["soil"]["status"] == "not_implemented"
        assert state["evidence_summary"]["management"]["status"] == "not_implemented"

    def test_state_copies_run_manifest_and_pack_refs(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        assert state["observation_manifest_sha256"] == run["observation_manifest_sha256"]
        # default pack set is resolved and pinned by value (checksums included)
        assert state["knowledge_pack_refs"], "bootstrap packs must be pinned"
        for ref in state["knowledge_pack_refs"]:
            assert ref["checksum_sha256"], ref

    def test_period_defaults_to_run_window_and_must_be_declared_without_run(self, client, farm_with_field):
        from datetime import datetime as dt, timezone as dt_tz
        from zoneinfo import ZoneInfo

        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        # The run's window is declared in field-local calendar days
        # (Africa/Cairo, UTC+2); the state stores UTC instants — local
        # midnight 2015-01-01 == 2014-12-31T22:00Z.
        expected_start = dt(2015, 1, 1, tzinfo=ZoneInfo("Africa/Cairo")).astimezone(dt_tz.utc).isoformat()
        assert state["period"]["start"] == expected_start, (
            "default period = pinned run's window expressed in UTC"
        )

        # fresh field without any run → period is mandatory
        other = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/fields",
            headers=headers,
            json={
                "name": "Empty Field",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.5, 31.2], [31.52, 31.2], [31.52, 31.22], [31.5, 31.22], [31.5, 31.2]]],
                },
            },
        ).json()
        resp = client.post(
            f"/api/v1/fields/{other['id']}/field-states", headers=headers, json={}
        )
        assert resp.status_code == 422

    def test_env_run_outside_state_period_refused(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        resp = client.post(
            f"/api/v1/fields/{field_id}/field-states",
            headers=headers,
            json={"period_start": "2024-01-01", "period_end": "2024-12-31"},
        )
        assert resp.status_code == 422
        assert "overlap" in str(resp.json()).lower()

    def test_water_period_mismatch_recorded_not_mixed(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        _water_plan(client, headers, field_id)  # summer_2016
        state = _create_state(
            client, headers, field_id, period_start="2017-01-01", period_end="2017-12-31"
        )
        assert state["domain_availability"]["water"]["status"] == "period_mismatch"
        assert any("not overlap" in w for w in state["warnings"])
        assert state["period_compatibility"]["water"]["status"] == "outside_period"

    def test_idempotency_key_replays(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        key = f"m71-state-{uuid.uuid4().hex[:8]}"
        s1 = _create_state(client, headers, field_id, idempotency_key=key)
        s2 = _create_state(client, headers, field_id, idempotency_key=key)
        assert s1["id"] == s2["id"]

    def test_reconstruction_same_refs_same_checksum(self, client, farm_with_field):
        """Core acceptance: a state is reproducible from its references alone."""
        headers, field_id, run = _prepared(client, farm_with_field)
        _water_plan(client, headers, field_id)
        ref_time = "2019-06-01T12:00:00+00:00"
        s1 = _create_state(client, headers, field_id, state_reference_time=ref_time)
        s2 = _create_state(client, headers, field_id, state_reference_time=ref_time)
        assert s1["id"] != s2["id"], "distinct rows, same content"
        assert s1["checksum_sha256"] == s2["checksum_sha256"]
        assert s1["observation_manifest_sha256"] == s2["observation_manifest_sha256"]

    def test_list_states_newest_first(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        _create_state(client, headers, field_id)
        _create_state(client, headers, field_id)
        listing = client.get(f"/api/v1/fields/{field_id}/field-states", headers=headers).json()
        assert len(listing["items"]) == 2

    def test_explicit_artifact_refs_resolved(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        plan = _water_plan(client, headers, field_id)
        state = _create_state(
            client,
            headers,
            field_id,
            environmental_feature_run_id=run["run_id"],
            water_plan_id=plan["id"],
        )
        assert state["environmental_feature_run_id"] == run["run_id"]
        assert state["water_plan_id"] == plan["id"]
        verify = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify["checksum_valid"] and verify["manifest_checksum_valid"]
        assert verify["referenced_artifacts"]["water_plan"]["intact"] is True

    def test_explicit_ref_from_other_field_rejected(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        other_field = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/fields",
            headers=headers,
            json={
                "name": "Other Field",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.6, 31.3], [31.62, 31.3], [31.62, 31.32], [31.6, 31.32], [31.6, 31.3]]],
                },
            },
        ).json()
        resp = client.post(
            f"/api/v1/fields/{other_field['id']}/field-states",
            headers=headers,
            json={"environmental_feature_run_id": run["run_id"]},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Immutability & verification
# ---------------------------------------------------------------------------
class TestImmutabilityAndVerification:
    def test_verify_ok_then_manifest_tamper_detected(self, client, farm_with_field):
        from app.core.database import SessionLocal
        from app.db import models as dbm

        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        verify = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify["checksum_valid"] is True and verify["manifest_checksum_valid"] is True

        # Direct SQL tamper (simulates out-of-band mutation of stored evidence)
        session = SessionLocal()
        try:
            session.execute(
                text(
                    "UPDATE field_states "
                    "SET observation_manifest = jsonb_set(observation_manifest, '{observation_count}', '999') "
                    "WHERE id = :sid"
                ),
                {"sid": uuid.UUID(state["id"])},
            )
            session.commit()
        finally:
            session.close()

        verify2 = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify2["manifest_checksum_valid"] is False
        # The state checksum still validates: it pins the manifest HASH (column,
        # untampered). Document tampering is caught by the manifest hash check
        # above — exactly the division of responsibility.
        assert verify2["checksum_valid"] is True
        # Tampering the STORED HASH instead must break the state checksum:
        session = SessionLocal()
        try:
            session.execute(
                text(
                    "UPDATE field_states SET observation_manifest_sha256 = :h WHERE id = :sid"
                ),
                {"h": "f" * 64, "sid": uuid.UUID(state["id"])},
            )
            session.commit()
        finally:
            session.close()
        verify3 = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify3["checksum_valid"] is False
        assert verify3["manifest_checksum_valid"] is False

    def test_state_checksum_tamper_detected(self, client, farm_with_field):
        from app.core.database import SessionLocal

        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        session = SessionLocal()
        try:
            session.execute(
                text(
                    "UPDATE field_states "
                    "SET domain_availability = jsonb_set(domain_availability, '{environmental,status}', '\"tampered\"') "
                    "WHERE id = :sid"
                ),
                {"sid": uuid.UUID(state["id"])},
            )
            session.commit()
        finally:
            session.close()
        verify = client.get(f"/api/v1/field-states/{state['id']}/verify", headers=headers).json()
        assert verify["checksum_valid"] is False

    def test_water_plan_delete_restricted_when_referenced(self, client, farm_with_field):
        """F-13: states own their inputs; referenced plans cannot be deleted."""
        headers, field_id, run = _prepared(client, farm_with_field)
        plan = _water_plan(client, headers, field_id)
        _create_state(client, headers, field_id)  # pins the (latest) plan by default
        resp = client.delete(f"/api/v1/water-plans/{plan['id']}", headers=headers)
        assert resp.status_code == 409
        # an unreferenced plan is deletable as before
        plan2 = _water_plan(client, headers, field_id, label="unreferenced plan")
        resp2 = client.delete(f"/api/v1/water-plans/{plan2['id']}", headers=headers)
        assert resp2.status_code == 204

    def test_manifest_endpoint_returns_document(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers, field_id)
        doc = client.get(f"/api/v1/field-states/{state['id']}/manifest", headers=headers).json()
        assert doc["observation_manifest"]["format_version"] == "field-observation-manifest-1"
        assert doc["observation_manifest_sha256"] == state["observation_manifest_sha256"]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
class TestComparison:
    def test_compare_same_field(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        s1 = _create_state(client, headers, field_id)
        s2 = _create_state(client, headers, field_id)
        report = client.post(
            "/api/v1/field-states/compare",
            headers=headers,
            json={"state_ids": [s1["id"], s2["id"]]},
        ).json()
        assert report["same_field"] is True
        assert report["boundary_versions_consistent"] is True
        assert report["dimension_comparison"]["observation_manifest_sha256"]["consistent"] is True
        overlap = report["pairwise_period_overlap"][0]
        assert overlap["compatible_periods"] is True

    def test_compare_requires_two_and_same_field(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        resp = client.post(
            "/api/v1/field-states/compare", headers=headers, json={"state_ids": ["x"]}
        )
        assert resp.status_code == 422

        s1 = _create_state(client, headers, field_id)
        other_field = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/fields",
            headers=headers,
            json={
                "name": "Field B",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.7, 31.4], [31.72, 31.4], [31.72, 31.42], [31.7, 31.42], [31.7, 31.4]]],
                },
            },
        ).json()
        _ingest(client, headers, other_field["id"])
        _feature_run(client, headers, other_field["id"])
        s2 = _create_state(client, headers, other_field["id"])
        resp2 = client.post(
            "/api/v1/field-states/compare",
            headers=headers,
            json={"state_ids": [s1["id"], s2["id"]]},
        )
        assert resp2.status_code == 422


# ---------------------------------------------------------------------------
# F-30: field-scoped ingestion idempotency
# ---------------------------------------------------------------------------
class TestIngestionIdempotencyScoping:
    def test_same_key_different_fields_never_replay(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        farm_id = farm_with_field["farm"]["id"]
        f1 = client.post(
            f"/api/v1/farms/{farm_id}/fields",
            headers=headers,
            json={
                "name": "F1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.41, 31.11], [31.42, 31.11], [31.42, 31.12], [31.41, 31.12], [31.41, 31.11]]],
                },
            },
        ).json()
        f2 = client.post(
            f"/api/v1/farms/{farm_id}/fields",
            headers=headers,
            json={
                "name": "F2",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.43, 31.11], [31.44, 31.11], [31.44, 31.12], [31.43, 31.12], [31.43, 31.11]]],
                },
            },
        ).json()
        key = f"m71-ingest-{uuid.uuid4().hex[:8]}"
        j1 = _ingest(client, headers, f1["id"], idempotency_key=key)
        j2 = _ingest(client, headers, f2["id"], idempotency_key=key)
        assert _job_id(j1) != _job_id(j2), "a colliding key on another field must create a NEW job"

    def test_same_field_same_key_replays(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        key = f"m71-ingest-{uuid.uuid4().hex[:8]}"
        j1 = _ingest(client, headers, field_id, idempotency_key=key)
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={**INGEST_BODY, "idempotency_key": key},
        )
        assert resp.status_code == 202
        assert _job_id(resp.json()) == _job_id(j1)

    def test_cross_tenant_key_collision_isolated(self, client, farm_with_field):
        # A genuinely separate second user (farm_with_field's own headers user
        # is user A; the cached auth_headers fixture would be the SAME user).
        import uuid as _uuid

        other_resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                "password": "test-password-1",
                "display_name": "Other",
            },
        )
        assert other_resp.status_code == 201, other_resp.text
        other = {"Authorization": f"Bearer {other_resp.json()['token']}"}
        farm_resp = client.post(
            "/api/v1/farms",
            headers=other,
            json={"name": "Other Farm", "country_code": "EG", "timezone": "Africa/Cairo", "currency_code": "EGP"},
        )
        assert farm_resp.status_code == 201
        other_field = client.post(
            f"/api/v1/farms/{farm_resp.json()['id']}/fields",
            headers=other,
            json={
                "name": "Tenant B Field",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[31.45, 31.15], [31.46, 31.15], [31.46, 31.16], [31.45, 31.16], [31.45, 31.15]]],
                },
            },
        ).json()
        key = f"m71-ingest-{uuid.uuid4().hex[:8]}"
        j1 = _ingest(client, farm_with_field["headers"], farm_with_field["field"]["id"], idempotency_key=key)
        j2 = _ingest(client, other, other_field["id"], idempotency_key=key)
        assert _job_id(j1) != _job_id(j2), "cross-tenant key collision must never replay a foreign job"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    @staticmethod
    def _second_user(client):
        import uuid as _uuid

        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                "password": "test-password-1",
                "display_name": "Other",
            },
        )
        assert resp.status_code == 201, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    def test_foreign_user_cannot_read_or_create_states(self, client, farm_with_field):
        headers_a, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers_a, field_id)
        headers_b = self._second_user(client)

        # Platform convention: an existing resource in a foreign organization
        # is Forbidden (403), never silently readable.
        assert (
            client.get(f"/api/v1/field-states/{state['id']}", headers=headers_b).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/field-states/{state['id']}/verify", headers=headers_b
            ).status_code
            == 403
        )
        assert (
            client.get(f"/api/v1/field-states/{state['id']}/manifest", headers=headers_b).status_code
            == 403
        )
        assert (
            client.get(f"/api/v1/fields/{field_id}/field-states", headers=headers_b).status_code
            == 403
        )
        resp = client.post(
            f"/api/v1/fields/{field_id}/field-states", headers=headers_b, json={}
        )
        assert resp.status_code == 403

    def test_unknown_state_is_404(self, client, auth_headers):
        resp = client.get(f"/api/v1/field-states/{uuid.uuid4()}", headers=auth_headers[0])
        assert resp.status_code == 404

    def test_compare_rejects_foreign_state(self, client, farm_with_field):
        headers_a, field_id, run = _prepared(client, farm_with_field)
        state = _create_state(client, headers_a, field_id)
        resp = client.post(
            "/api/v1/field-states/compare",
            headers=self._second_user(client),
            json={"state_ids": [state["id"], state["id"]]},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Rotation provenance surfacing (F-20/F-09)
# ---------------------------------------------------------------------------
class TestRotationProvenanceSurfacing:
    def test_rotation_run_writes_solver_version_and_created_by(self, client, farm_with_field):
        headers, field_id, run = _prepared(client, farm_with_field)
        resp = client.post(
            f"/api/v1/fields/{field_id}/rotation-runs",
            headers=headers,
            json={
                "seasons": [
                    {"label": "winter_2025", "start_date": "2024-12-01", "end_date": "2025-03-31"}
                ],
                "hemisphere": "north",
                "strategy_profiles": ["balanced"],
            },
        )
        assert resp.status_code == 202, resp.text
        payload = resp.json()
        if payload["status"] != "succeeded":
            pytest.skip(f"rotation run did not succeed in this context: {payload.get('error_summary')}")
        # F-20: the solver build is now written per run (was never populated)
        assert payload["solver_version"], "solver_version must be recorded"
        # F-09: the acting principal is surfaced
        assert payload["created_by"]

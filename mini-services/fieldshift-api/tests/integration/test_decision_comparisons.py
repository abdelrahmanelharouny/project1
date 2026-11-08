"""Integration: M7.6 decision comparisons — unified document assembly over
M7.3/M7.4/M7.5 artifacts, deterministic regeneration, evidence linking,
missing-evidence honesty, immutability, tenant isolation."""

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
    return {
        "headers": headers,
        "field": farm_with_field["field"],
        "state": state,
        "feature_run": run,
    }


@pytest.fixture()
def rich_scope(client, prepared):
    """Two executed scenarios + one sensitivity analysis + one robust run."""
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

    # sensitivity analysis on the hot scenario's execution
    resp = client.post(
        f"/api/v1/scenario-executions/{r_hot['run_id']}/sensitivity-analyses",
        headers=h,
        json={
            "parameter_design": {
                "temperature_delta_c": {"lower": 1.0, "upper": 5.0, "n_points": 5},
            }
        },
    )
    assert resp.status_code == 200, resp.text
    analysis = resp.json()

    # scenario set + robust run
    resp = client.post(
        f"/api/v1/fields/{field_id}/scenario-sets",
        headers=h,
        json={"label": "set", "execution_run_ids": [r_hot["run_id"], r_cool["run_id"]]},
    )
    assert resp.status_code in (200, 201), resp.text
    set_id = resp.json()["id"]
    resp = client.post(
        f"/api/v1/scenario-sets/{set_id}/robust-runs",
        headers=h,
        json={"seasons": [SEASON_2016], "hemisphere": "north"},
    )
    assert resp.status_code == 200, resp.text
    robust_run = resp.json()

    return {
        **prepared,
        "executions": [r_hot, r_cool],
        "analysis": analysis,
        "set_id": set_id,
        "robust_run": robust_run,
    }


class TestGeneration:
    def test_full_document_golden_path(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons",
            headers=h,
            json={"title": "Autumn review"},
        )
        assert resp.status_code == 200, resp.text
        doc = resp.json()
        assert doc["doc_status"] in ("succeeded", "completed_with_limitations")
        assert doc["document_checksum"]
        d = doc["document"]
        # scope pins every artifact with checksums
        assert len(d["scope"]["executions"]) == 2
        assert all(e["output_checksum"] for e in d["scope"]["executions"])
        assert len(d["scope"]["sensitivity_analyses"]) == 1
        assert len(d["scope"]["robust_runs"]) == 1
        # sections present
        assert len(d["baseline_vs_scenario"]["per_execution"]) == 2
        assert len(d["scenario_pairs"]["pairs"]) >= 1
        assert d["sensitivity_interpretation"]["analyses"][0]["reference_reproduced"] is True
        assert len(d["rotation_decisions"]["runs"]) == 1
        assert d["tradeoffs"]["robust_run_id"]
        assert d["missing_evidence"]["count"] >= 1
        # honesty: ET0 structural unavailability + no-forecast item present
        codes = {i["code"] for i in d["missing_evidence"]["items"]}
        assert "scenario_et0_and_water" in codes
        assert "climate_projections" in codes
        assert any(f["kind"] == "largest_scenario_change" for f in d["findings"])

    def test_auto_scope_when_empty(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={})
        assert resp.status_code == 200, resp.text
        doc = resp.json()
        assert len(doc["document"]["scope"]["executions"]) == 2

    def test_deterministic_regeneration_same_row(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        r1 = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={"title": "T"}
        ).json()
        r2 = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={"title": "T"}
        ).json()
        assert r1["id"] == r2["id"]
        assert r1["document_checksum"] == r2["document_checksum"]

    def test_different_scope_new_document(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        r1 = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={"title": "T"}
        ).json()
        r2 = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons",
            headers=h,
            json={"title": "T", "execution_run_ids": [rich_scope["executions"][0]["run_id"]]},
        ).json()
        assert r1["id"] != r2["id"]

    def test_empty_field_rejected(self, client, prepared):
        h = prepared["headers"]
        resp = client.post(
            f"/api/v1/fields/{prepared['field']['id']}/decision-comparisons", headers=h, json={}
        )
        assert resp.status_code == 422

    def test_no_composite_scores_or_probabilities(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        doc = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()["document"]
        # The invariant is structural: no pseudo-statistical KEYS exist anywhere
        # in the document. Denial language ("no composite scores") is honest and
        # allowed; fabricated fields would not be.
        banned_keys = (
            "composite_score", "probability", "confidence", "expected_yield",
            "p_value", "likelihood", "confidence_interval", "yield_prediction",
            "recommendation_score", "risk_score",
        )

        def keys_of(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield str(k).lower()
                    yield from keys_of(v)
            elif isinstance(node, list):
                for v in node:
                    yield from keys_of(v)

        found = set(keys_of(doc))
        for banned in banned_keys:
            assert banned not in found, f"pseudo-statistical key '{banned}' found"


class TestEvidence:
    def test_verify_document_and_sources(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        doc = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()
        resp = client.post(f"/api/v1/decision-comparisons/{doc['id']}/verify", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verified"] is True
        assert body["findings"] == []

    def test_findings_carry_evidence_refs(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        doc = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()["document"]
        for f in doc["findings"]:
            assert f["kind"]
            assert f["text"]
            assert isinstance(f["evidence"], list) and f["evidence"], "findings must be evidence-linked"

    def test_listing_and_detail(self, client, rich_scope):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        created = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()
        listing = client.get(f"/api/v1/fields/{field_id}/decision-comparisons", headers=h).json()
        assert listing["count"] >= 1
        assert all("document" not in item for item in listing["items"])  # list is lean
        detail = client.get(f"/api/v1/decision-comparisons/{created['id']}", headers=h).json()
        assert detail["document"]["scope"]["executions"]


class TestProtection:
    def test_document_row_frozen(self, client, rich_scope, db):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        doc = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()
        with pytest.raises(Exception):
            db.execute(
                text(
                    "UPDATE decision_comparisons SET title = 'x' WHERE id = CAST(:i AS uuid)"
                ),
                {"i": doc["id"]},
            )
            db.commit()

    def test_result_bearing_document_not_deletable(self, client, rich_scope, db):
        h = rich_scope["headers"]
        field_id = rich_scope["field"]["id"]
        doc = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons", headers=h, json={}
        ).json()
        with pytest.raises(Exception):
            db.execute(
                text("DELETE FROM decision_comparisons WHERE id = CAST(:i AS uuid)"),
                {"i": doc["id"]},
            )
            db.commit()

    def test_tenant_isolation(self, client, rich_scope):
        other = _second_user(client)
        field_id = rich_scope["field"]["id"]
        resp = client.post(f"/api/v1/fields/{field_id}/decision-comparisons", headers=other, json={})
        assert resp.status_code == 403
        created = client.post(
            f"/api/v1/fields/{field_id}/decision-comparisons",
            headers=rich_scope["headers"],
            json={},
        ).json()
        resp = client.get(f"/api/v1/decision-comparisons/{created['id']}", headers=other)
        assert resp.status_code == 403


class TestMigrationHead:
    def test_head_matches_script_directory(self, db):
        """Pin-free guard: the applied revision must equal the alembic head
        computed from the migrations script directory (stays valid across
        future migrations instead of pinning a hard-coded revision id)."""
        import os as _os

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "alembic.ini"))
        cfg.set_main_option("script_location", _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "migrations"))
        expected = ScriptDirectory.from_config(cfg).get_current_head()
        row = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert row == expected

"""Integration: M6C management knowledge lifecycle + APIs (Increment 2).

Covers: bootstrap of the bundled practice pack, active-pack read models,
draft/retired lifecycle gating (draft practices are inert), import API with a
practices section, idempotency, checksum-conflict rejection, and the
transparency coverage metric. Knowledge endpoints are platform-level
(authenticated, not tenant-scoped) — matching the M5 convention.
"""

import copy

import pytest


@pytest.fixture()
def practices_pack_payload():
    from app.knowledge.packs.m6c_practices_pack import get_m6c_practices_pack

    return get_m6c_practices_pack()


class TestBundledPracticePackBootstrap:
    def test_seed_practices_active_and_cited(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/practices", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 10
        codes = {p["practice_code"] for p in data["practices"]}
        assert {
            "cover_cropping",
            "residue_retention",
            "residue_removal_baling",
            "residue_incorporation",
            "mulching",
            "reduced_tillage",
            "contour_operations",
            "strip_cropping",
            "vegetated_buffer",
            "controlled_traffic",
            "cover_termination_planning",
            "field_access_management",
        } <= codes
        cover = next(p for p in data["practices"] if p["practice_code"] == "cover_cropping")
        assert cover["validation_status"] == "reference"
        assert cover["payload"]["mechanisms"], "mechanisms must be present"
        for mechanism in cover["payload"]["mechanisms"]:
            assert mechanism["citation"] is not None
            assert mechanism["citation"]["citation_text"]
        # every shipped claim is cited (transparency coverage = 100% cited)
        cov = cover["evidence_coverage"]
        assert cov["claims_cited"] == cov["claim_counts"]

    def test_practices_family_filter(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/practices?family=residue", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["practices"]
        assert items
        assert all(p["practice_family"] == "residue" for p in items)

    def test_operation_templates_listed_with_citation(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/operation-templates", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 10
        termination = next(
            t
            for t in data["operation_templates"]
            if t["template_code"] == "op_cover_termination"
        )
        preds = termination["payload"]["typical_predecessors"]
        assert preds, "termination template declares its predecessor"
        assert preds[0]["template_code"] == "op_cover_seeding"
        assert preds[0]["citation"] is not None
        # templates carry no durations/capacities
        assert "duration" not in termination["payload"]

    def test_pack_counts_include_m6c_sections(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/packs", headers=headers)
        assert resp.status_code == 200
        m6c = next(
            p for p in resp.json()["packs"] if p["pack_code"] == "kp-m6c-practices"
        )
        assert m6c["status"] == "active"
        assert m6c["counts"]["practices"] >= 10
        assert m6c["counts"]["operation_templates"] >= 10
        seed = next(p for p in resp.json()["packs"] if p["pack_code"] == "kp-seed-global")
        assert seed["counts"]["practices"] == 0


class TestPracticeLifecycleGating:
    def _import_pack(self, client, headers, payload, activate=False):
        body = {"pack": payload, "activate": activate}
        resp = client.post(
            "/api/v1/knowledge/packs/import", headers=headers, json=body
        )
        return resp

    def test_draft_practices_are_inert_until_activated(
        self, client, auth_headers, practices_pack_payload
    ):
        headers = auth_headers[0]
        payload = copy.deepcopy(practices_pack_payload)
        payload["pack_code"] = "kp-test-m6c-draft"
        payload["pack_version"] = "v1"

        # Import WITHOUT activation → draft → practices must not appear.
        resp = self._import_pack(client, headers, payload, activate=False)
        assert resp.status_code == 201, resp.text
        pack_id = resp.json()["pack"]["id"]
        assert resp.json()["pack"]["status"] == "draft"

        listed = client.get("/api/v1/knowledge/practices", headers=headers).json()
        codes = {p["practice_code"] for p in listed["practices"]}
        assert "cover_cropping" in codes  # from the bundled active pack
        draft_listed = client.get(
            "/api/v1/knowledge/practices?family=erosion_control", headers=headers
        ).json()
        # erosion-control practices exist in the ACTIVE pack; the draft copy of
        # the SAME codes must not double them
        assert draft_listed["total"] == len(
            [p for p in listed["practices"] if p["practice_family"] == "erosion_control"]
        )

        # Activate → now the draft pack's practices join the read model.
        resp = client.post(
            f"/api/v1/knowledge/packs/{pack_id}/activate",
            headers=headers,
            json={"activate": True},
        )
        assert resp.status_code == 200
        listed2 = client.get("/api/v1/knowledge/practices", headers=headers).json()
        erosion = [
            p for p in listed2["practices"] if p["practice_family"] == "erosion_control"
        ]
        assert len(erosion) >= 6  # duplicated by the activated second pack

        # Retire → the second pack's rows leave the read model again.
        resp = client.post(
            f"/api/v1/knowledge/packs/{pack_id}/activate",
            headers=headers,
            json={"activate": False},
        )
        assert resp.status_code == 200
        listed3 = client.get("/api/v1/knowledge/practices", headers=headers).json()
        erosion3 = [
            p for p in listed3["practices"] if p["practice_family"] == "erosion_control"
        ]
        assert len(erosion3) == 3

    def test_import_idempotent_and_checksum_conflict(
        self, client, auth_headers, practices_pack_payload
    ):
        headers = auth_headers[0]
        payload = copy.deepcopy(practices_pack_payload)
        payload["pack_code"] = "kp-test-m6c-idem"
        payload["pack_version"] = "v1"

        first = self._import_pack(client, headers, payload, activate=True)
        assert first.status_code == 201, first.text
        second = self._import_pack(client, headers, payload, activate=True)
        assert second.status_code == 200, second.text
        assert second.json()["pack"]["id"] == first.json()["pack"]["id"]

        conflicting = copy.deepcopy(payload)
        conflicting["practices"][0]["name"] = "Renamed practice"
        conflict = self._import_pack(client, headers, conflicting)
        assert conflict.status_code == 422
        assert "checksum" in conflict.json()["error"]["message"].lower()

    def test_import_rejects_practice_with_unknown_source(
        self, client, auth_headers, practices_pack_payload
    ):
        headers = auth_headers[0]
        payload = copy.deepcopy(practices_pack_payload)
        payload["pack_code"] = "kp-test-m6c-bad"
        payload["pack_version"] = "v1"
        payload["practices"][0]["mechanisms"][0]["source_key"] = "ghost_source"
        resp = self._import_pack(client, headers, payload)
        assert resp.status_code == 422
        error = resp.json()["error"]
        blob = error["message"] + " " + " ".join(
            d.get("reason", "") for d in error.get("details", [])
        )
        assert "ghost_source" in blob

    def test_pre_m6c_pack_reimport_is_idempotent(self, client, auth_headers):
        """Backward compatibility: the bundled crop pack must re-import cleanly
        under the M6C-extended schema (checksum unchanged)."""
        from app.knowledge.packs.seed_pack_v1 import get_seed_pack

        headers = auth_headers[0]
        resp = self._import_pack(client, headers, get_seed_pack(), activate=True)
        assert resp.status_code == 200, resp.text  # 201 would mean a NEW row
        assert resp.json()["pack"]["pack_code"] == "kp-seed-global"

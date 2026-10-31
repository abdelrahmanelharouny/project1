"""Integration: knowledge pack import workflow + APIs (Milestone 5, ADR-0014)."""

import copy

import pytest


@pytest.fixture()
def seed_pack_payload():
    from app.knowledge.packs.seed_pack_v1 import get_seed_pack

    return get_seed_pack()


class TestKnowledgeApi:
    def test_packs_listed_with_license_and_counts(self, client, auth_headers, seed_pack_payload):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/packs", headers=headers)
        assert resp.status_code == 200
        packs = resp.json()["packs"]
        assert packs, "bundled seed pack should be active"
        seed = next(p for p in packs if p["pack_code"] == "kp-seed-global")
        assert seed["status"] == "active"
        assert seed["license_name"]
        assert seed["attribution_text"]
        assert seed["checksum_sha256"]
        assert seed["counts"]["crops"] >= 5

    def test_crops_listed_with_trait_provenance(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/crops", headers=headers)
        assert resp.status_code == 200
        crops = resp.json()["crops"]
        maize = next(c for c in crops if c["crop_code"] == "maize")
        assert maize["family_key"] == "poaceae"
        assert maize["has_kc_parameters"] is True
        assert "kc_mid" in maize["trait_codes"] or "duration_days_total" in maize["trait_codes"]
        faba = next(c for c in crops if c["crop_code"] == "faba_bean")
        assert faba["has_kc_parameters"] is False  # deliberate gap
        assert faba["is_legume"] is True

    def test_crop_detail_carries_citations(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/crops/maize", headers=headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["pack"]["digitization_note"]
        trait = next(t for t in detail["traits"] if t["trait_code"] == "duration_days_total")
        assert trait["source"]["citation_text"]
        assert trait["source"]["source_key"] == "fao56_1998"
        assert trait["evidence_class"] == "published_reference"
        assert trait["confidence"] in ("high", "moderate", "low", "unknown")
        kc = detail["water_parameters"]
        assert {w["growth_stage"] for w in kc} == {"initial", "mid", "late"}
        assert all(w["source"]["citation_text"] for w in kc)
        window = detail["calendar_windows"][0]
        assert window["evidence_class"] == "reference_synthesized"

    def test_rotation_rules_report_enforceability(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/knowledge/rotation-rules", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmed_regional_count"] == 0
        assert data["total"] >= 3
        rule = data["rules"][0]
        assert rule["hard_enforceable"] is False
        assert rule["source"]["citation_text"]
        assert rule["mechanism"]

    def test_unknown_crop_404(self, client, auth_headers):
        resp = client.get("/api/v1/knowledge/crops/alien_crop", headers=auth_headers[0])
        assert resp.status_code == 404


class TestPackImportWorkflow:
    def test_import_and_idempotent_reimport(self, client, auth_headers, seed_pack_payload):
        headers = auth_headers[0]
        pack = copy.deepcopy(seed_pack_payload)
        pack["pack_code"] = "kp-test-import"
        pack["pack_version"] = "v-test-1"
        resp = client.post(
            "/api/v1/knowledge/packs/import", headers=headers,
            json={"pack": pack, "activate": False},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] is True
        assert body["pack"]["status"] == "draft"
        assert body["validation"]["ok"] is True

        # identical reimport → 200, not created, same checksum
        resp2 = client.post(
            "/api/v1/knowledge/packs/import", headers=headers,
            json={"pack": pack, "activate": False},
        )
        assert resp2.status_code == 200
        assert resp2.json()["created"] is False
        assert resp2.json()["pack"]["checksum_sha256"] == body["pack"]["checksum_sha256"]

    def test_conflicting_same_version_rejected(self, client, auth_headers, seed_pack_payload):
        headers = auth_headers[0]
        pack = copy.deepcopy(seed_pack_payload)
        pack["pack_code"] = "kp-test-conflict"
        pack["pack_version"] = "v-test-1"
        resp = client.post("/api/v1/knowledge/packs/import", headers=headers,
                           json={"pack": pack, "activate": False})
        assert resp.status_code == 201
        pack["crops"][0]["traits"][0]["value_numeric"] += 0.5
        resp2 = client.post("/api/v1/knowledge/packs/import", headers=headers,
                            json={"pack": pack, "activate": False})
        assert resp2.status_code == 422

    def test_invalid_pack_rejected_with_structured_errors(self, client, auth_headers, seed_pack_payload):
        headers = auth_headers[0]
        pack = copy.deepcopy(seed_pack_payload)
        pack["pack_code"] = "kp-test-invalid"
        pack["pack_version"] = "v-test-1"
        del pack["license_name"]
        resp = client.post("/api/v1/knowledge/packs/import", headers=headers,
                           json={"pack": pack, "activate": False})
        assert resp.status_code == 422
        assert resp.json()["error"]["details"]

    def test_draft_pack_is_inert_until_activated(self, client, auth_headers, seed_pack_payload):
        headers = auth_headers[0]
        pack = copy.deepcopy(seed_pack_payload)
        pack["pack_code"] = "kp-test-draft"
        pack["pack_version"] = "v-test-1"
        pack["crops"] = [copy.deepcopy(pack["crops"][0])]
        pack["crops"][0]["crop_code"] = "draft_only_crop"
        pack["crops"][0]["traits"] = []
        pack["crops"][0]["calendar_windows"] = []
        pack["crops"][0]["water_parameters"] = []
        pack["rotation_rules"] = []
        resp = client.post("/api/v1/knowledge/packs/import", headers=headers,
                           json={"pack": pack, "activate": False})
        assert resp.status_code == 201
        pack_id = resp.json()["pack"]["id"]

        crops = client.get("/api/v1/knowledge/crops", headers=headers).json()["crops"]
        assert "draft_only_crop" not in {c["crop_code"] for c in crops}

        resp = client.post(f"/api/v1/knowledge/packs/{pack_id}/activate", headers=headers,
                           json={"activate": True})
        assert resp.status_code == 200
        crops = client.get("/api/v1/knowledge/crops", headers=headers).json()["crops"]
        assert "draft_only_crop" in {c["crop_code"] for c in crops}

    def test_import_requires_auth(self, client, seed_pack_payload):
        resp = client.post("/api/v1/knowledge/packs/import", json={"pack": seed_pack_payload})
        assert resp.status_code in (401, 403)


class TestTraitVersioningSemantics:
    def test_variety_level_trait_model_exists(self, db):
        """Cultivar-level information is representable: a variety row can carry
        its own trait (species-level traits stay on crops)."""
        from app.db import models as dbm
        from app.knowledge.import_service import import_pack
        from app.knowledge.packs.seed_pack_v1 import get_seed_pack

        import_pack(db, get_seed_pack(), activate=True)
        crop = db.query(dbm.Crop).filter(dbm.Crop.crop_code == "soybean").one()
        variety = dbm.CropVariety(
            crop_id=crop.id, variety_name="Test-MG-IV", region_code="EG",
            maturity_group="IV", metadata_json={"note": "test fixture"},
        )
        db.add(variety)
        db.flush()
        source = db.query(dbm.KnowledgeSource).filter_by(pack_id=crop.pack_id).first()
        trait = dbm.CropTrait(
            pack_id=crop.pack_id, crop_variety_id=variety.id,
            trait_code="duration_days_total", value_numeric=112, unit="d",
            region_code="EG", source_id=source.id,
            evidence_class="published_reference", confidence="moderate",
            validation_status="reference",
        )
        db.add(trait)
        db.flush()
        stored = db.query(dbm.CropTrait).filter_by(crop_variety_id=variety.id).one()
        assert stored.value_numeric == 112
        assert stored.crop_id is None  # variety-owned, not species-owned

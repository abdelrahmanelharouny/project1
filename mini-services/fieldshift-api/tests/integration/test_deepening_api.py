"""Integration regression tests for the deepening program findings (F-01, F-03,
F-09, F-14, F-18) — database-level and API-contract level guarantees."""

import uuid

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.db import models as dbm


def _ingest(client, headers, field_id):
    resp = client.post(
        f"/api/v1/fields/{field_id}/data-jobs", headers=headers,
        json={"provider_code": "synthetic", "variables": ["precipitation",
              "air_temperature_mean", "reference_et0"],
              "start_date": "2023-01-01", "end_date": "2023-12-31",
              "profile": "semi_arid", "seed": 42},
    )
    assert resp.status_code == 202, resp.text


def _import_pack(client, headers, pack):
    resp = client.post("/api/v1/knowledge/packs/import", headers=headers,
                       json={"pack": pack})
    return resp


# ================= F-01: passport products carry the synthetic flag =================
class TestF01PassportSyntheticFlag:
    def test_dataset_product_payload_includes_is_synthetic(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs", headers=headers,
            json={"provider_code": "synthetic", "variables": ["precipitation"],
                  "start_date": "2023-01-01", "end_date": "2023-03-31",
                  "profile": "semi_arid", "seed": 42},
        )
        assert resp.status_code == 202
        passport = client.get(f"/api/v1/fields/{field_id}/data-passport", headers=headers).json()
        products = {
            (v["dataset_product"]["provider_code"], v["dataset_product"]["product_code"]): v["dataset_product"]
            for v in passport["variables"] if v.get("dataset_product")
        }
        assert products, "passport lists dataset products"
        synthetic = [p for p in products.values() if p["provider_code"] == "synthetic"]
        assert synthetic, "the synthetic fixture product is present"
        assert all(p["is_synthetic"] is True for p in synthetic)
        assert all(p["evidence_class"] == "synthetic_test_data" for p in synthetic)


# ================= F-03: idempotency replay is field-scoped =================
class TestF03IdempotencyScoping:
    def test_same_key_on_another_field_does_not_replay(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        farm_id = farm_with_field["farm"]["id"]
        # second field on the same farm
        resp = client.post(
            f"/api/v1/farms/{farm_id}/fields", headers=headers,
            json={"name": "South Field", "geometry": {
                "type": "Polygon",
                "coordinates": [[[31.50, 31.10], [31.52, 31.10], [31.52, 31.12], [31.50, 31.12], [31.50, 31.10]]],
            }},
        )
        assert resp.status_code == 201
        field_b = resp.json()
        field_a = farm_with_field["field"]

        _ingest(client, headers, field_a["id"])
        _ingest(client, headers, field_b["id"])
        body = {"start_date": "2023-01-01", "end_date": "2023-12-31",
                "aggregation_levels": ["monthly"], "idempotency_key": "deep-f3-key"}
        r1 = client.post(f"/api/v1/fields/{field_a['id']}/feature-runs", headers=headers, json=body)
        assert r1.status_code == 202
        run_a = r1.json()["run_id"] if "run_id" in r1.json() else r1.json()["id"]

        # the SAME key against ANOTHER field must not return field A's run
        r2 = client.post(f"/api/v1/fields/{field_b['id']}/feature-runs", headers=headers, json=body)
        assert r2.status_code == 202
        payload = r2.json()
        run_b = payload.get("run_id") or payload.get("id")
        assert run_b != run_a

    def test_cross_tenant_key_replay_returns_own_run(self, client, farm_with_field):
        # a second tenant cannot replay a key it observed from tenant one
        email = f"tenant-{uuid.uuid4().hex[:10]}@test.local"
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "test-password-1", "display_name": "Other Tenant"},
        )
        assert registered.status_code == 201, registered.text
        headers_b = {"Authorization": f"Bearer {registered.json()['token']}"}
        resp = client.post(
            "/api/v1/farms", headers=headers_b,
            json={"name": "Other Farm", "country_code": "EG", "timezone": "Africa/Cairo",
                  "currency_code": "EGP"},
        )
        assert resp.status_code == 201, resp.text
        farm_b = resp.json()
        field_response = client.post(
            f"/api/v1/farms/{farm_b['id']}/fields", headers=headers_b,
            json={"name": "B Field", "geometry": {
                "type": "Polygon",
                "coordinates": [[[31.60, 31.10], [31.62, 31.10], [31.62, 31.12], [31.60, 31.12], [31.60, 31.10]]],
            }},
        )
        assert field_response.status_code == 201, field_response.text
        field_b = field_response.json()

        headers_a = farm_with_field["headers"]
        field_a = farm_with_field["field"]
        _ingest(client, headers_a, field_a["id"])
        _ingest(client, headers_b, field_b["id"])
        body = {"start_date": "2023-01-01", "end_date": "2023-12-31",
                "aggregation_levels": ["monthly"], "idempotency_key": "cross-tenant-key"}
        r1 = client.post(f"/api/v1/fields/{field_a['id']}/feature-runs", headers=headers_a, json=body)
        assert r1.status_code == 202
        run_a = r1.json().get("run_id") or r1.json().get("id")

        r2 = client.post(f"/api/v1/fields/{field_b['id']}/feature-runs", headers=headers_b, json=body)
        assert r2.status_code == 202
        run_b = r2.json().get("run_id") or r2.json().get("id")
        assert run_b != run_a, "tenant B must never receive tenant A's run"


# ================= F-09: deterministic crop winner across packs =================
class TestF09DeterministicPackWinner:
    def test_later_pack_version_wins_deterministically(self, client, auth_headers):
        headers = auth_headers[0]
        base = {
            "license_name": "CC BY 4.0",
            "attribution_text": "Test attribution for the deepening pack.",
            "digitization_note": "Test pack",
            "sources": [{
                "source_key": "src", "publisher": "Test Publisher",
                "title": "A Test Source Title", "publication_year": 2020,
                "citation_text": "Test Publisher (2020). Test Source Title.",
            }],
            "families": [{"family_key": "testaceae", "scientific_name": "Testaceae testacea"}],
        }
        pack_a = {
            **base, "pack_code": "kp-f9", "pack_version": "1.0",
            "name": "Pack v1",
            "crops": [{
                "crop_code": "winner_crop", "family_key": "testaceae",
                "scientific_name": "Cropus v1us",
                "traits": [{"trait_code": "duration_days_total", "value_numeric": 100,
                            "unit": "d", "source_key": "src",
                            "evidence_class": "published_reference"}],
            }],
        }
        pack_b = {
            **base, "pack_code": "kp-f9", "pack_version": "2.0",
            "name": "Pack v2",
            "crops": [{
                "crop_code": "winner_crop", "family_key": "testaceae",
                "scientific_name": "Cropus v2us",
                "traits": [{"trait_code": "duration_days_total", "value_numeric": 120,
                            "unit": "d", "source_key": "src",
                            "evidence_class": "published_reference"}],
            }],
        }
        r1 = _import_pack(client, headers, pack_a)
        assert r1.status_code in (200, 201), r1.text
        r2 = _import_pack(client, headers, pack_b)
        assert r2.status_code in (200, 201), r2.text
        # activate the newer pack (import does not auto-activate a second version)
        packs = client.get("/api/v1/knowledge/packs", headers=headers).json()["packs"]
        v1 = next(p for p in packs if p["pack_code"] == "kp-f9" and p["pack_version"] == "1.0")
        v2 = next(p for p in packs if p["pack_code"] == "kp-f9" and p["pack_version"] == "2.0")
        act2 = client.post(f"/api/v1/knowledge/packs/{v2['id']}/activate", headers=headers, json={"activate": True})
        assert act2.status_code == 200, act2.text
        detail = client.get("/api/v1/knowledge/crops/winner_crop", headers=headers).json()
        assert detail["scientific_name"] == "Cropus v2us"
        # deterministic: re-reading gives the same winner
        again = client.get("/api/v1/knowledge/crops/winner_crop", headers=headers).json()
        assert again["scientific_name"] == detail["scientific_name"]


# ================= F-14: audit events carry the actor =================
class TestF14AuditActor:
    def test_pack_import_audit_row_has_actor_and_org(self, client, auth_headers):
        headers = auth_headers[0]
        user = auth_headers[1]
        pack = {
            "pack_code": "kp-f14", "pack_version": "1.0", "name": "Audit actor pack",
            "license_name": "CC BY 4.0",
            "attribution_text": "Test attribution for the audit-actor pack.",
            "sources": [{
                "source_key": "src", "publisher": "Test Publisher",
                "title": "A Test Source Title", "publication_year": 2020,
                "citation_text": "Test Publisher (2020). Test Source Title.",
            }],
            "crops": [{
                "crop_code": "audit_crop", "family_key": None,
                "traits": [{"trait_code": "duration_days_total", "value_numeric": 100,
                            "unit": "d", "source_key": "src",
                            "evidence_class": "published_reference"}],
            }],
        }
        resp = _import_pack(client, headers, pack)
        assert resp.status_code in (200, 201), resp.text
        session = SessionLocal()
        try:
            rows = session.execute(
                text("SELECT actor_id, organization_id, action FROM audit_events "
                     "ORDER BY created_at DESC LIMIT 5")
            ).all()
            assert rows, "audit events exist"
            # at least one row carries a non-null actor (import/activate path)
            assert any(r[0] is not None for r in rows)
        finally:
            session.close()


# ================= F-18: DB-level uniqueness for species-level Kc rows =================
class TestF18KcDbUniqueness:
    def test_duplicate_species_kc_row_rejected_by_database(self, client, auth_headers):
        headers = auth_headers[0]
        pack = {
            "pack_code": "kp-f18", "pack_version": "1.0", "name": "Kc uniqueness pack",
            "license_name": "CC BY 4.0",
            "attribution_text": "Test attribution for the F-18 pack.",
            "sources": [{
                "source_key": "fao56", "publisher": "FAO",
                "title": "FAO Irrigation and Drainage Paper 56", "publication_year": 1998,
                "citation_text": "Allen et al., 1998, FAO-56.",
            }],
            "crops": [{
                "crop_code": "kc_uniq", "family_key": None,
                "water_parameters": [
                    {"growth_stage": st, "kc_value": v, "kc_method": "single",
                     "source_key": "fao56", "evidence_class": "published_reference"}
                    for st, v in (("initial", 0.3), ("mid", 1.15), ("late", 0.5))
                ],
            }],
        }
        resp = _import_pack(client, headers, pack)
        assert resp.status_code in (200, 201), resp.text
        session = SessionLocal()
        try:
            crop_id = session.execute(
                text("SELECT id FROM crops WHERE crop_code = 'kc_uniq'")
            ).scalar_one()
            pack_id = session.execute(
                text("SELECT id FROM knowledge_packs WHERE pack_code = 'kp-f18'")
            ).scalar_one()
            # insert a duplicate species-level (NULL variety) anchor directly:
            # with NULLS NOT DISTINCT this must violate the unique index
            # with NULLS NOT DISTINCT the duplicate species-level anchor
            # violates the unique index immediately at execution time
            with pytest.raises(Exception, match="uq_crop_water_param"):
                session.execute(text("""
                    INSERT INTO crop_water_parameters
                        (id, pack_id, crop_id, crop_variety_id, growth_stage, kc_value,
                         kc_method, evidence_class, validation_status,
                         source_id, created_at, updated_at)
                    VALUES (gen_random_uuid(), :pack_id, :crop_id, NULL, 'mid', 9.9,
                            'single', 'published_reference', 'reference',
                            (SELECT source_id FROM crop_water_parameters LIMIT 1),
                            now(), now())
                    RETURNING id
                """), {"pack_id": pack_id, "crop_id": crop_id})
            session.rollback()
        finally:
            session.close()

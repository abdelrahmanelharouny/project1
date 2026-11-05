"""Integration: residue ledger API (M6C Increment 5) — CRUD, mass-balance
surfacing, provenance gates, tenant isolation, and the provenance link to
the M6B management-event ledger."""

import uuid


class TestResidueWorkflow:
    def _record(self, client, farm_with_field, **overrides):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        body = {
            "crop_label": "maize",
            "season_label": "summer_2026",
            "produced_dm_kg": 5000.0,
            "production_status": "farmer_reported",
        }
        body.update(overrides)
        resp = client.post(
            f"/api/v1/fields/{field_id}/residue-records", headers=headers, json=body
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _flow(self, client, farm_with_field, record_id, **overrides):
        headers = farm_with_field["headers"]
        body = {"flow_type": "retained_surface", "dm_kg": 3000.0, "dm_kg_status": "measured"}
        body.update(overrides)
        resp = client.post(
            f"/api/v1/residue-records/{record_id}/flows", headers=headers, json=body
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_full_ledger_roundtrip(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        self._flow(client, farm_with_field, record["id"],
                   flow_type="retained_surface", dm_kg=3000.0, dm_kg_status="measured")
        self._flow(client, farm_with_field, record["id"],
                   flow_type="removed_baled", dm_kg=1500.0, dm_kg_status="farmer_reported")
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        ledger = client.get(
            f"/api/v1/fields/{field_id}/residue-ledger", headers=headers
        ).json()
        assert ledger["totals"]["record_count"] == 1
        assert ledger["totals"]["produced_dm_kg_known_total"] == 5000.0
        rec = ledger["records"][0]
        assert rec["balance"]["status"] == "balanced"
        assert rec["balance"]["unaccounted_dm_kg"] == 500.0

    def test_over_allocation_surfaced(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        self._flow(client, farm_with_field, record["id"],
                   flow_type="removed_baled", dm_kg=6500.0, dm_kg_status="measured")
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        ledger = client.get(
            f"/api/v1/fields/{field_id}/residue-ledger", headers=headers
        ).json()
        assert ledger["records"][0]["balance"]["status"] == "over_allocated"
        assert ledger["records"][0]["balance"]["unaccounted_dm_kg"] == -1500.0
        assert any("never absorbed" in w for w in ledger["warnings"])

    def test_production_unknown_record(self, client, farm_with_field):
        record = self._record(client, farm_with_field, produced_dm_kg=None,
                              production_status="missing")
        assert record["produced_dm_kg"] is None
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        ledger = client.get(
            f"/api/v1/fields/{field_id}/residue-ledger", headers=headers
        ).json()
        assert ledger["totals"]["records_production_unknown"] == 1
        assert any("never assumed to be zero" in w for w in ledger["warnings"])

    def test_missing_status_with_mass_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/residue-records", headers=headers,
            json={"crop_label": "maize", "produced_dm_kg": 100.0,
                  "production_status": "missing"},
        )
        assert resp.status_code == 422
        assert "contradicts" in resp.json()["error"]["message"]

    def test_coefficient_estimate_requires_provenance(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/residue-records", headers=headers,
            json={"crop_label": "wheat", "produced_dm_kg": 4000.0,
                  "production_status": "coefficient_estimate"},
        )
        assert resp.status_code == 422
        assert "provenance" in resp.json()["error"]["message"]
        # with provenance it is accepted
        ok = client.post(
            f"/api/v1/fields/{field_id}/residue-records", headers=headers,
            json={"crop_label": "wheat", "produced_dm_kg": 4000.0,
                  "production_status": "coefficient_estimate",
                  "coefficient_provenance": {
                      "coefficient": 1.3,
                      "basis": "residue-to-product ratio",
                      "source_reference": "Farmer-supplied literature value (2024)",
                  }},
        )
        assert ok.status_code == 201
        assert ok.json()["coefficient_provenance"]["coefficient"] == 1.3

    def test_negative_flow_rejected(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        headers = farm_with_field["headers"]
        resp = client.post(
            f"/api/v1/residue-records/{record['id']}/flows", headers=headers,
            json={"flow_type": "grazed", "dm_kg": -10.0},
        )
        assert resp.status_code == 422

    def test_unknown_flow_type_rejected(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        headers = farm_with_field["headers"]
        resp = client.post(
            f"/api/v1/residue-records/{record['id']}/flows", headers=headers,
            json={"flow_type": "vaporized", "dm_kg": 10.0},
        )
        assert resp.status_code == 422

    def test_quality_and_derived_nutrient_content(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        self._flow(client, farm_with_field, record["id"], dm_kg=3000.0)
        headers = farm_with_field["headers"]
        q = client.post(
            f"/api/v1/residue-records/{record['id']}/quality", headers=headers,
            json={"carbon_fraction": 40.0, "nitrogen_pct": 1.2,
                  "evidence_class": "laboratory_measured"},
        )
        assert q.status_code == 201
        field_id = farm_with_field["field"]["id"]
        ledger = client.get(
            f"/api/v1/fields/{field_id}/residue-ledger", headers=headers
        ).json()
        derived = ledger["records"][0]["derived"]
        assert derived["total_nitrogen_kg"] == 36.0  # 1.2% × 3000 kg
        assert derived["cn_ratio_derived"] == 33.33
        assert "not counted" in derived["note"].lower()

    def test_flow_links_management_event_provenance(self, client, farm_with_field):
        """Provenance chain: flow → soil_management_event (M6B ledger)."""
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        event = client.post(
            f"/api/v1/fields/{field_id}/soil-management-events", headers=headers,
            json={"event_type": "residue_removal", "event_date": "2026-09-20",
                  "title": "baled straw"},
        ).json()
        record = self._record(client, farm_with_field)
        flow = self._flow(client, farm_with_field, record["id"],
                          flow_type="removed_baled", dm_kg=1500.0,
                          soil_management_event_id=event["id"])
        assert flow["soil_management_event_id"] == event["id"]
        ledger = client.get(
            f"/api/v1/fields/{field_id}/residue-ledger", headers=headers
        ).json()
        flows = ledger["records"][0]["flows"]
        assert flows[0]["soil_management_event_id"] == event["id"]

    def test_tenant_isolation_403(self, client, farm_with_field):
        record = self._record(client, farm_with_field)
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        resp = client.post(
            f"/api/v1/residue-records/{record['id']}/flows",
            headers={"Authorization": f"Bearer {other['token']}"},
            json={"flow_type": "grazed", "dm_kg": 5.0},
        )
        assert resp.status_code == 403

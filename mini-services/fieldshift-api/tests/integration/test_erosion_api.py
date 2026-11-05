"""Integration: erosion assessment API (M6C Increment 6) — snapshots,
checksum reproducibility, cover-metrics linkage, tenant isolation."""

import uuid


def _factors_payload():
    def f(value):
        return {
            "value": value,
            "source_reference": "local soil survey (2024)",
            "region_scope": "demo-region",
            "unit_convention": "metric_si",
        }

    return {"R": f(100.0), "K": f(0.25), "LS": f(1.0), "C": f(0.3), "P": f(0.5)}


class TestErosionAssessments:
    def test_screening_run_with_cover_linkage(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        # crop history → protective interval; then explicit bare observations
        # after harvest (crop history ALONE would leave those days unknown —
        # unknown is never bare, so the concern needs real bare evidence)
        client.post(
            f"/api/v1/fields/{field_id}/crop-history", headers=headers,
            json={"crop_label": "maize", "sowing_date": "2026-05-01",
                  "harvest_date": "2026-08-15", "season_label": "summer_2026"},
        )
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            client.post(
                f"/api/v1/fields/{field_id}/soil-cover/observations", headers=headers,
                json={"observed_date": day, "cover_state": "bare"},
            )
        resp = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers,
            json={
                "window_start": "2026-01-01",
                "window_end": "2026-12-31",
                "slope_evidence": {"slope_class": "moderate",
                                   "evidence_class": "farmer_reported_record"},
            },
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        screening = run["result"]["screening"]
        assert screening["assessment_kind"] == "qualitative_screening"
        codes = {c["code"] for c in screening["concerns"]}
        assert "slope_class_evidence" in codes
        assert "exposed_soil_days" in codes
        concern = next(c for c in screening["concerns"] if c["code"] == "exposed_soil_days")
        assert "3" in concern["evidence"]
        assert "wind" in concern["processes"]

    def test_rusle_computed_with_provenance(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers,
            json={"window_start": "2026-01-01", "window_end": "2026-12-31",
                  "rusle_factors": _factors_payload()},
        )
        assert resp.status_code == 201
        rusle = resp.json()["result"]["rusle"]
        assert rusle["status"] == "computed"
        assert rusle["annual_soil_loss_a"] == 3.75  # hand-computed golden
        assert rusle["unit_convention"] == "metric_si"
        assert rusle["assessment_kind"] == "screening_only"

    def test_rusle_missing_factor_not_evaluated(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        factors = _factors_payload()
        del factors["P"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers,
            json={"window_start": "2026-01-01", "window_end": "2026-12-31",
                  "rusle_factors": factors},
        )
        assert resp.status_code == 201
        rusle = resp.json()["result"]["rusle"]
        assert rusle["status"] == "not_evaluated"
        assert rusle["missing_factors"] == ["P"]
        assert "annual_soil_loss_a" not in rusle

    def test_snapshot_reproducible_and_idempotent(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        key = f"ero-{uuid.uuid4().hex[:8]}"
        body = {"window_start": "2026-01-01", "window_end": "2026-12-31",
                "idempotency_key": key}
        first = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers, json=body
        ).json()
        second = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers, json=body
        ).json()
        assert first["id"] == second["id"]
        assert first["checksum_sha256"] == second["checksum_sha256"]

    def test_readiness_endpoint(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/erosion-readiness", headers=headers)
        assert resp.status_code == 200
        readiness = resp.json()
        assert readiness["rusle_family"]["available"] is False
        assert any("DEM" in m for m in readiness["rusle_family"]["missing_inputs"])
        assert "classical_gully" in readiness["processes_out_of_scope"]

    def test_list_and_detail(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        created = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers,
            json={"window_start": "2026-01-01", "window_end": "2026-12-31"},
        ).json()
        listing = client.get(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers
        ).json()
        assert listing["total"] == 1
        detail = client.get(
            f"/api/v1/erosion-assessments/{created['id']}", headers=headers
        ).json()
        assert detail["id"] == created["id"]
        assert detail["result"]["screening"]

    def test_tenant_isolated(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        created = client.post(
            f"/api/v1/fields/{field_id}/erosion-assessments", headers=headers,
            json={"window_start": "2026-01-01", "window_end": "2026-12-31"},
        ).json()
        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "Other"},
        ).json()
        resp = client.get(
            f"/api/v1/erosion-assessments/{created['id']}",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 403

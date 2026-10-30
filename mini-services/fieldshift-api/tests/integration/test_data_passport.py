"""Integration: Field Data Passport (Master §16.5 / §27 / Milestone 2 acceptance)."""

PASSPORT_VARS = ["air_temperature_mean", "precipitation", "reference_et0"]


def _passport(client, headers, field_id):
    resp = client.get(f"/api/v1/fields/{field_id}/data-passport", headers=headers)
    assert resp.status_code == 200
    return resp.json()


class TestEmptyPassport:
    def test_empty_field_blocked_with_reasons(self, client, farm_with_field):
        passport = _passport(client, farm_with_field["headers"], farm_with_field["field"]["id"])
        assert passport["overall_status"] == "blocked"
        assert len(passport["variables"]) == 0
        missing_codes = {m["variable_code"] for m in passport["missing_variables"]}
        assert "precipitation" in missing_codes
        for analysis in passport["analyses"]:
            if analysis["analysis_code"] != "rotation_optimization":
                assert analysis["status"] == "blocked"
                assert analysis["missing_inputs"]


class TestFilledPassport:
    def test_variables_reported_with_provenance_and_synthetic_label(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={"provider_code": "synthetic", "variables": PASSPORT_VARS,
                  "start_date": "2023-01-01", "end_date": "2023-12-31",
                  "profile": "mediterranean_dry_summer", "seed": 42},
        )
        assert resp.status_code == 202

        passport = _passport(client, headers, field_id)
        assert passport["overall_status"] in ("partial", "ready")

        by_code = {v["variable_code"]: v for v in passport["variables"]}
        for code in PASSPORT_VARS:
            entry = by_code[code]
            assert entry["status"] == "available"
            assert entry["observation_count"] >= 365
            assert entry["is_synthetic"] is True
            assert entry["evidence_class"] == "synthetic_test_data"
            product = entry["dataset_product"]
            assert product["provider_code"] == "synthetic"
            assert product["product_code"] == "synthetic_environment"
            assert product["product_version"] == "v1"
            assert product["attribution_text"]
            assert "SYNTHETIC" in product["attribution_text"].upper()
            assert entry["period"]["start"].startswith("2023-01-01")
            assert entry["period"]["end"].startswith("2023-12-31")
            assert entry["last_retrieved_at"]
            assert entry["freshness_days"] == 0
            assert 0 < entry["valid_ratio"] <= 1

    def test_analyses_readiness_honest(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={"provider_code": "synthetic", "variables": PASSPORT_VARS,
                  "start_date": "2023-01-01", "end_date": "2023-12-31", "seed": 42},
        )
        passport = _passport(client, headers, field_id)
        by_code = {a["analysis_code"]: a for a in passport["analyses"]}
        assert by_code["climate_summary"]["status"] == "available"
        assert by_code["et0_only_summary"]["status"] == "available"
        # Water budget needs Kc + soil storage + allocation — blocked and says why.
        water = by_code["water_budget_screening"]
        assert water["status"] == "blocked"
        assert "crop_water_parameters" in water["missing_inputs"]
        assert any("not yet available" in r or "milestone" in r.lower() for r in water["reasons"])
        # Rotation optimization not implemented in slice — must be blocked, never faked.
        assert by_code["rotation_optimization"]["status"] == "blocked"
        assert "constraint_solver" in by_code["rotation_optimization"]["missing_inputs"]

    def test_quality_warnings_surface(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={"provider_code": "synthetic", "variables": ["precipitation"],
                  "start_date": "2022-01-01", "end_date": "2022-12-31", "seed": 3},
        )
        passport = _passport(client, headers, field_id)
        prec = next(v for v in passport["variables"] if v["variable_code"] == "precipitation")
        assert prec["missing_count"] > 0
        assert any(w["flag_code"] == "SYNTHETIC_GAP" for w in prec["warnings"])

    def test_passport_never_merges_quality_into_one_score(self, client, farm_with_field):
        passport = _passport(client, farm_with_field["headers"], farm_with_field["field"]["id"])
        assert "confidence_score" not in passport
        assert any("never merged" in n for n in passport["notes"])

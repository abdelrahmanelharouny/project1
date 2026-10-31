"""Integration: feature-run lifecycle, source selection, coverage policy,
provenance, comparison and tenant isolation (Milestone 4)."""

import uuid

import pytest
from sqlalchemy import select

from app.db.models import DatasetProduct, FeatureValue, Observation

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
    "end_date": "2019-12-31",
    "profile": "temperate_seasonal",
    "seed": 7,
}

# the synthetic provider caps a single job at 4 years; chunk the window
def _ingest(client, headers, field_id, body=None):
    if body is not None:
        return client.post(f"/api/v1/fields/{field_id}/data-jobs", headers=headers, json=body)
    statuses = []
    for start, end in (("2015-01-01", "2017-12-31"), ("2018-01-01", "2019-12-31")):
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={**INGEST_BODY, "start_date": start, "end_date": end},
        )
        assert resp.status_code == 202, resp.text
        statuses.append(resp.json())
    assert all(j["status"] == "succeeded" for j in statuses), [j.get("error_summary") for j in statuses]
    return resp


def _create_run(client, headers, field_id, **overrides):
    body = {
        "start_date": "2015-01-01",
        "end_date": "2019-12-31",
        "aggregation_levels": ["monthly"],
        "hemisphere": "north",
        **overrides,
    }
    return client.post(f"/api/v1/fields/{field_id}/feature-runs", headers=headers, json=body)


class TestFeatureCatalog:
    def test_catalog_is_versioned_with_formula_references(self, client, auth_headers):
        headers = auth_headers[0]
        resp = client.get("/api/v1/features/catalog", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["feature_catalog_version"]
        features = data["features"]
        assert features
        for f in features:
            assert f["formula_reference"]
            assert f["min_coverage_ratio"] <= 1.0
        codes = {f["feature_code"] for f in features}
        assert "precipitation_total_monthly" in codes
        # count indices cite their convention and disclaim crop-specificity
        hot = next(f for f in features if f["feature_code"] == "hot_days_35c_count_monthly")
        assert "NOT a crop-specific stress threshold" in hot["formula_reference"]


class TestFeatureRunLifecycle:
    def test_create_run_succeeds_and_persists_values(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        job = _ingest(client, headers, field_id).json()
        assert job["status"] == "succeeded"

        resp = _create_run(client, headers, field_id)
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["status"] == "succeeded", run.get("error_summary")
        assert run["records_written"] > 0
        assert run["feature_engine_version"]
        assert run["feature_catalog_version"]
        assert run["calendar_timezone"] == "Africa/Cairo"  # farm timezone default
        # one source per variable, resolved explicitly
        assert set(run["source_selection"]) >= {"precipitation", "air_temperature_mean"}

        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"aggregation_level": "monthly", "feature_code": "precipitation_total_monthly"},
        ).json()
        assert values["total"] == 60  # 2015-2019, 12 months x 5 years
        first = values["items"][0]
        assert first["unit"] == "mm"
        assert first["quality_status"] in ("valid", "partial")
        prov = first["provenance"]
        assert prov["observation_count"] >= 28
        assert prov["dataset_products"] if "dataset_products" in prov else prov["inputs"]["dataset_products"]
        assert prov["checksum"]
        assert prov["calendar"]["timezone"] == "Africa/Cairo"

    def test_daily_level_respects_window_cap(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id)
        resp = _create_run(
            client, headers, field_id,
            start_date="2015-01-01", end_date="2019-12-31",
            aggregation_levels=["daily"],
        )
        assert resp.status_code == 422

    def test_crop_season_windows(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2018-01-01", "end_date": "2018-12-31"})
        resp = _create_run(
            client, headers, field_id,
            start_date="2018-01-01", end_date="2018-12-31",
            aggregation_levels=["crop_season"],
            crop_seasons=[
                {"label": "summer_maize_2018", "start_date": "2018-06-01", "end_date": "2018-08-31"}
            ],
        )
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["status"] == "succeeded"
        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"aggregation_level": "crop_season", "feature_code": "precipitation_total_crop_season"},
        ).json()
        assert values["total"] == 1
        v = values["items"][0]
        assert v["period_label"] == "summer_maize_2018"
        assert v["provenance"]["crop_season_window"]["source"].startswith("user_supplied_window")

    def test_missing_variable_drops_dependent_features_with_reason(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        # ingest only precipitation (one year)
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-12-31",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        resp = _create_run(client, headers, field_id, start_date="2019-01-01", end_date="2019-12-31")
        assert resp.status_code == 202
        run = resp.json()
        assert run["status"] == "succeeded"
        # temperature features cannot be computed — explicitly
        assert any("air_temperature" in k for k in run["not_evaluated_reasons"])
        assert any("air_temperature" in w for w in run["warnings"])
        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"feature_code": "air_temperature_mean_monthly"},
        ).json()
        assert values["total"] == 0

    def test_insufficient_coverage_month_is_null_not_zero(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        # ingest one month only; run over three months
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-01-31",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        resp = _create_run(
            client, headers, field_id,
            start_date="2019-01-01", end_date="2019-03-31",
            aggregation_levels=["monthly"],
        )
        run = resp.json()
        assert run["status"] == "succeeded"
        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"aggregation_level": "monthly", "feature_code": "precipitation_total_monthly"},
        ).json()
        by_label = {v["period_label"]: v for v in values["items"]}
        assert by_label["2019-01"]["value"] is not None
        for label in ("2019-02", "2019-03"):
            assert by_label[label]["value"] is None  # never zero-filled
            assert by_label[label]["quality_status"] in ("insufficient_coverage", "missing")
            assert "reason" in by_label[label]["provenance"]

    def test_anomaly_features_with_baseline(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id)
        resp = _create_run(client, headers, field_id)
        run = resp.json()
        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"feature_code": "precipitation_anomaly_monthly", "quality_status": "valid"},
        ).json()
        assert values["total"] > 0
        v = values["items"][0]
        baseline = v["baseline_reference"]
        assert baseline and baseline["n_years"] >= 5
        assert "mean" in baseline and "sd" in baseline

    def test_synthetic_run_is_flagged(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id)
        run = _create_run(client, headers, field_id).json()
        assert run["is_synthetic"] is True
        assert any("SYNTHETIC" in w for w in run["warnings"])

    def test_idempotency_key_reuses_run(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id)
        key = f"run-{uuid.uuid4().hex[:10]}"
        r1 = _create_run(client, headers, field_id, idempotency_key=key).json()
        r2 = _create_run(client, headers, field_id, idempotency_key=key).json()
        assert r1["run_id"] == r2["run_id"]

    def test_reproducibility_same_data_same_checksums(self, client, farm_with_field, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id)
        r1 = _create_run(client, headers, field_id).json()
        r2 = _create_run(client, headers, field_id).json()
        v1 = db.scalars(
            select(FeatureValue).where(
                FeatureValue.run_id == uuid.UUID(r1["run_id"]),
                FeatureValue.feature_code == "air_temperature_mean_monthly",
                FeatureValue.quality_status == "valid",
            )
        ).all()
        v2 = db.scalars(
            select(FeatureValue).where(
                FeatureValue.run_id == uuid.UUID(r2["run_id"]),
                FeatureValue.feature_code == "air_temperature_mean_monthly",
                FeatureValue.quality_status == "valid",
            )
        ).all()
        assert len(v1) == len(v2) > 0
        by_label1 = {v.period_label: v for v in v1}
        by_label2 = {v.period_label: v for v in v2}
        for label, a in by_label1.items():
            b = by_label2[label]
            assert a.value == b.value
            assert a.provenance["checksum"] == b.provenance["checksum"]


class TestSourceSelection:
    def test_real_product_preferred_and_never_blended(self, client, farm_with_field, db, auth_headers):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-03-31",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        # simulate real (open-meteo era5_land) observations on the same field
        real_product = db.scalar(select(DatasetProduct).where(DatasetProduct.product_code == "era5_land"))
        assert real_product is not None
        field_uuid = uuid.UUID(field_id)
        db.add_all(
            [
                Observation(
                    field_id=field_uuid,
                    dataset_product_id=real_product.id,
                    variable_code="precipitation",
                    value=0.5,
                    unit="mm",
                    observed_at=datetime_utc(2019, 2, day),
                    period_start=datetime_utc(2019, 2, day),
                    period_end=datetime_utc(2019, 2, day, 23, 59, 59),
                    time_support="daily",
                    spatial_support_type="grid_cell",
                    quality_status="valid",
                    is_synthetic=False,
                    evidence_class="reanalysis_model_estimate",
                    retrieved_at=datetime_utc(2026, 10, 31),
                    processing_version="openmeteo-normalizer-v1",
                    metadata={"model": "era5_land"},
                )
                for day in range(1, 29)
            ]
        )
        db.commit()

        run = _create_run(
            client, headers, field_id,
            start_date="2019-02-01", end_date="2019-02-28",
            aggregation_levels=["monthly"],
        ).json()
        selection = run["source_selection"]["precipitation"]
        assert selection["product_code"] == "era5_land"
        assert selection["is_synthetic"] is False
        assert run["is_synthetic"] is False
        # the synthetic product was skipped with an explicit warning
        assert any("synthetic" in w and "not selected" in w for w in run["warnings"])
        # values come only from the selected product
        values = client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values",
            headers=headers,
            params={"feature_code": "precipitation_total_monthly"},
        ).json()
        v = values["items"][0]
        assert v["n_input"] == 28
        assert v["value"] == pytest.approx(0.5 * 28, abs=0.01)

    def test_source_override_pins_product(self, client, farm_with_field, db):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-01-31",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        synth_product = db.scalar(select(DatasetProduct).where(DatasetProduct.product_code == "synthetic_environment"))
        assert synth_product is not None
        run = _create_run(
            client, headers, field_id,
            start_date="2019-01-01", end_date="2019-01-31",
            source_overrides={"precipitation": str(synth_product.id)},
        ).json()
        assert run["source_selection"]["precipitation"]["dataset_product_id"] == str(synth_product.id)

    def test_override_to_unknown_product_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-01-31",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        resp = _create_run(
            client, headers, field_id,
            start_date="2019-01-01", end_date="2019-01-31",
            source_overrides={"precipitation": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    def test_no_observations_is_structured_error(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = _create_run(client, headers, field_id)
        assert resp.status_code == 422
        assert "No observations" in resp.json()["error"]["message"]


class TestValidation:
    def test_unknown_timezone_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        resp = _create_run(client, headers, field_id, calendar_timezone="Mars/Olympus", start_date="2019-01-01", end_date="2019-01-31")
        assert resp.status_code == 422

    def test_unknown_feature_code_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        resp = _create_run(client, headers, field_id, feature_codes=["crop_yield_forecast"], start_date="2019-01-01", end_date="2019-01-31")
        assert resp.status_code == 422

    def test_duplicate_crop_labels_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        resp = _create_run(
            client, headers, field_id,
            start_date="2019-01-01", end_date="2019-01-31",
            aggregation_levels=["crop_season"],
            crop_seasons=[
                {"label": "s1", "start_date": "2019-01-01", "end_date": "2019-01-15"},
                {"label": "s1", "start_date": "2019-01-16", "end_date": "2019-01-31"},
            ],
        )
        assert resp.status_code == 422

    def test_crop_seasons_require_level(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        resp = _create_run(
            client, headers, field_id,
            start_date="2019-01-01", end_date="2019-01-31",
            crop_seasons=[{"label": "s1", "start_date": "2019-01-01", "end_date": "2019-01-31"}],
        )
        assert resp.status_code == 422

    def test_unknown_aggregation_level_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = _create_run(client, headers, field_id, aggregation_levels=["weekly"])
        assert resp.status_code == 422


class TestIsolationAndComparison:
    def test_run_hidden_from_other_tenant(self, client, farm_with_field, auth_headers):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        run = _create_run(client, headers, field_id, start_date="2019-01-01", end_date="2019-01-31").json()

        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.local", "password": "test-password-1", "display_name": "Other"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        # cross-tenant access is rejected (403/404 — never leaked)
        assert client.get(f"/api/v1/feature-runs/{run['run_id']}", headers=other_headers).status_code in (403, 404)
        assert client.get(
            f"/api/v1/feature-runs/{run['run_id']}/values", headers=other_headers
        ).status_code in (403, 404)

    def test_list_runs_scoped_to_field(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={**INGEST_BODY, "start_date": "2019-01-01", "end_date": "2019-01-31"})
        _create_run(client, headers, field_id, start_date="2019-01-01", end_date="2019-01-31")
        listed = client.get(f"/api/v1/fields/{field_id}/feature-runs", headers=headers).json()
        assert listed["total"] == 1
        assert listed["items"][0]["field_id"] == field_id

    def test_comparison_endpoint(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        _ingest(client, headers, field_id, body={
            "provider_code": "synthetic",
            "variables": ["precipitation"],
            "start_date": "2019-01-01",
            "end_date": "2019-02-28",
            "profile": "temperate_seasonal",
            "seed": 7,
        })
        run_a = _create_run(client, headers, field_id, start_date="2019-01-01", end_date="2019-02-28").json()
        run_b = _create_run(client, headers, field_id, start_date="2019-01-01", end_date="2019-02-28").json()
        resp = client.get(
            f"/api/v1/feature-runs/{run_a['run_id']}/comparison",
            headers=headers,
            params={"against_run_id": run_b["run_id"]},
        )
        assert resp.status_code == 200
        cmp = resp.json()
        assert cmp["matched_periods"] > 0
        for d in cmp["deltas"]:
            assert d["delta"] == pytest.approx(d["run_value"] - d["against_value"], abs=0.01)
        assert "source selections" in cmp["note"]


def datetime_utc(y, m, d, hh=0, mm=0, ss=0):
    from datetime import UTC, datetime

    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)

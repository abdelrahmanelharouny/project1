"""Integration tests for P05 satellite preprocessing (DB-backed).

Deterministic raster fixtures (tests/fixtures — synthetic TEST imagery,
never production data) drive the full processing path: enqueue -> worker
execution -> object storage -> raster_assets registry -> honest observation
upsert. Covers idempotency, cancellation, restart replay, failure detail,
tenant isolation, access control, and provenance propagation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from tests.fixtures import raster_fixtures as fx


@pytest.fixture()
def raster_storage(tmp_path, monkeypatch):
    """Isolated local raster storage root per test."""
    from app.geospatial import objectstore as ost

    monkeypatch.setattr("app.core.config.settings.raster_storage_root", str(tmp_path / "rasters"))
    ost.reset_raster_storage()
    yield tmp_path / "rasters"
    ost.reset_raster_storage()


import pytest


@pytest.fixture()
def fixture_field(client, auth_headers):
    return _make_fixture_field(client, auth_headers)


def _make_fixture_field(client, auth_headers):
    """Farm + field whose geometry matches the raster fixture scene."""
    headers, _user = auth_headers
    farm_resp = client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": "Fixture Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields",
        headers=headers,
        json={"name": "Fixture Field", "geometry": fx.fixture_field_geojson()},
    )
    assert field_resp.status_code == 201, field_resp.text
    field = field_resp.json()
    return {"headers": headers, "farm": farm, "field": field}


def _make_scene_row(
    db,
    field_id,
    *,
    scene_id,
    assets,
    acquired_at,
    status="ready",
    is_synthetic=False,
    provider_code="nasa_hls",
    product_code="HLSL30",
    cloud=10.0,
    resolution=30.0,
):
    from app.db.models_p2 import SatelliteScene

    row = SatelliteScene(
        field_id=field_id,
        provider_code=provider_code,
        product_code=product_code,
        scene_id=scene_id,
        acquired_at=acquired_at,
        cloud_cover_pct=cloud,
        spatial_resolution_m=resolution,
        band_mapping={"red": "B04", "nir": "B05"},
        asset_refs=dict(assets),
        is_synthetic=is_synthetic,
        processing_version="2.0",
        metadata_json={"platform": "LANDSAT-8", "collection_id": "HLSL30_2.0"},
        acquisition_status=status,
        discovered_at=datetime.now(UTC),
        acquisition_updated_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    return row


def _process_inline(rp_job_id):
    from app.data_platform.processing.service import execute_processing_job

    execute_processing_job(rp_job_id, None)


def _get_rp(db, bg_job_id):
    from app.db.models_p2 import RasterProcessingJob

    return db.query_by_id if False else None


class TestProcessingEndToEnd:
    def test_scene_processed_to_products_and_observations(
        self, db, client, auth_headers, raster_storage, fixture_field, tmp_path
    ):
        from app.db.models import Observation
        from app.db.models_p2 import RasterAsset, RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.E2E1")
        _make_scene_row(db, field_id, scene_id="FIX.E2E1", assets=assets,
                        acquired_at=datetime(2026, 1, 10, 10, 0, tzinfo=UTC))
        from app.db.models import Field

        field = db.get(Field, field_id)

        result = proc.create_processing_jobs(
            db, field=field, scene_ids=["FIX.E2E1"], indices=["ndvi", "bsi"],
            created_by=uuid.uuid4(),
        )
        assert len(result["jobs"]) == 1
        rp_id = uuid.UUID(result["jobs"][0]["job_id"])
        _process_inline(rp_id)

        rp = db.get(RasterProcessingJob, rp_id)
        assert rp.status == "succeeded", rp.error

        # derived + preview raster assets registered with checksums
        derived = db.query(RasterAsset).filter_by(
            field_id=field_id, scene_id="FIX.E2E1", asset_kind="derived"
        ).all()
        previews = db.query(RasterAsset).filter_by(
            field_id=field_id, scene_id="FIX.E2E1", asset_kind="preview"
        ).all()
        assert {a.index_code for a in derived} == {"ndvi", "bsi"}
        assert len(previews) == 2
        for a in derived:
            assert a.storage_backend == "local"
            assert len(a.checksum_sha256) == 64
            assert a.crs == fx.FIXTURE_CRS
            assert a.byte_size > 0
            assert "/derived/" in a.storage_key
            assert a.boundary_version is not None
            prov = a.provenance_json
            assert prov["product_code"] == "HLSL30"
            assert prov["processing_version"] == proc.PROCESSING_VERSION
            expected_formula = "Rouse" if a.index_code == "ndvi" else "Rikimaru"
            assert expected_formula in prov["index_formula"]
            assert prov["pipeline"]["read_mode"] == "windowed_range_read"
            assert prov["pipeline"]["window"]["crs"] == fx.FIXTURE_CRS
            wgs84 = prov["pipeline"]["window_bounds_wgs84"]
            assert wgs84 and -180 <= wgs84[0] < wgs84[2] <= 180

        # honest observations with provenance + zonal metadata
        obs = db.query(Observation).filter_by(field_id=field_id, variable_code="ndvi").all()
        assert len(obs) == 1
        o = obs[0]
        assert o.quality_status == "valid"
        assert o.evidence_class == "satellite_derived_estimate"
        assert o.is_synthetic is False
        assert o.value == pytest.approx(fx.EXPECTED_VEGETATED["ndvi"] * 0.5 + fx.EXPECTED_STRESSED["ndvi"] * 0.5, rel=0.05)
        assert o.metadata["scene_id"] == "FIX.E2E1"
        assert o.metadata["zonal"]["valid_pixels"] > 0
        assert o.metadata["index_formula"]
        assert o.metadata["pipeline"]["processing_version"] == proc.PROCESSING_VERSION

    def test_no_valid_pixels_records_no_observation(
        self, db, auth_headers, raster_storage, fixture_field, tmp_path
    ):
        from app.db.models import Field, Observation
        from app.db.models_p2 import RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.CLOUDY")
        import rasterio

        with rasterio.open(assets["fmask"], "r+") as src:
            import numpy as np

            src.write(np.full((fx.FIXTURE_HEIGHT, fx.FIXTURE_WIDTH), 0b000010, dtype="uint8"), 1)
        _make_scene_row(db, field_id, scene_id="FIX.CLOUDY", assets=assets,
                        acquired_at=datetime(2026, 1, 11, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(
            db, field=field, scene_ids=["FIX.CLOUDY"], indices=["ndvi"],
        )
        _process_inline(uuid.UUID(result["jobs"][0]["job_id"]))
        rp = db.get(RasterProcessingJob, uuid.UUID(result["jobs"][0]["job_id"]))
        assert rp.status == "succeeded"
        assert any("no valid pixels" in w for w in rp.warnings)
        assert db.query(Observation).filter_by(field_id=field_id, variable_code="ndvi").count() == 0


class TestProcessingIdempotency:
    def test_double_submit_replays_same_job(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import Field
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.IDEM1")
        _make_scene_row(db, field_id, scene_id="FIX.IDEM1", assets=assets,
                        acquired_at=datetime(2026, 1, 12, tzinfo=UTC))
        field = db.get(Field, field_id)
        r1 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.IDEM1"], indices=["ndvi"])
        r2 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.IDEM1"], indices=["ndvi"])
        assert r2["jobs"][0]["job_id"] == r1["jobs"][0]["job_id"]
        assert r2["jobs"][0].get("replayed") is True

    def test_reprocessed_scene_skipped(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import Field
        from app.db.models_p2 import RasterAsset, RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.IDEM2")
        _make_scene_row(db, field_id, scene_id="FIX.IDEM2", assets=assets,
                        acquired_at=datetime(2026, 1, 13, tzinfo=UTC))
        field = db.get(Field, field_id)
        r1 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.IDEM2"], indices=["ndvi"])
        _process_inline(uuid.UUID(r1["jobs"][0]["job_id"]))
        r2 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.IDEM2"], indices=["ndvi"])
        assert r2["jobs"] == []
        assert any("already processed" in s["reason"] for s in r2["skipped"])
        # exactly one set of asset rows — no duplicates
        assert db.query(RasterAsset).filter_by(field_id=field_id, scene_id="FIX.IDEM2", asset_kind="derived").count() == 1

    def test_observation_upgrade_missing_then_supersede(self, db, raster_storage, fixture_field, tmp_path):
        """Missing ingestion attempts upgrade in place; valid values only
        supersede on a NEW processing version — chain kept in metadata."""
        from app.db.models import Field, Observation
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.UP1")
        scene = _make_scene_row(db, field_id, scene_id="FIX.UP1", assets=assets,
                                acquired_at=datetime(2026, 1, 14, tzinfo=UTC))
        field = db.get(Field, field_id)

        # seed a missing (failed attempt) observation on the natural key
        from app.data_platform.ingestion.service import _product_for_provider
        from app.data_platform.providers.nasa_hls.registry_info import PRODUCT_VERSION

        _s, product = _product_for_provider(db, "nasa_hls", product_code=scene.product_code, product_version=PRODUCT_VERSION)
        db.add(Observation(
            field_id=field_id, dataset_product_id=product.id, variable_code="ndvi",
            value=None, unit="index", observed_at=scene.acquired_at,
            period_start=scene.acquired_at, period_end=scene.acquired_at,
            time_support="instant", spatial_support_type="polygon_average",
            quality_status="missing", evidence_class="satellite_derived_estimate",
            is_synthetic=False, processing_version="2.0+veg-raster",
            retrieved_at=datetime.now(UTC),
            metadata={"scene_id": "FIX.UP1"},
        ))
        db.commit()

        r1 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.UP1"], indices=["ndvi"])
        _process_inline(uuid.UUID(r1["jobs"][0]["job_id"]))
        obs = db.query(Observation).filter_by(field_id=field_id, variable_code="ndvi").all()
        assert len(obs) == 1, "missing row upgraded, not duplicated"
        assert obs[0].value is not None
        chain = obs[0].metadata["provenance_chain"]
        assert chain and chain[0]["previous_status"] == "missing"

        # reprocessing at a NEW version supersedes with chain
        r2 = proc.create_processing_jobs(
            db, field=field, scene_ids=["FIX.UP1"], indices=["ndvi"],
            processing_version="hls-derivation-9.9.9",
        )
        _process_inline(uuid.UUID(r2["jobs"][0]["job_id"]))
        obs = db.query(Observation).filter_by(field_id=field_id, variable_code="ndvi").all()
        assert len(obs) == 1
        assert obs[0].processing_version == "hls-derivation-9.9.9"
        assert len(obs[0].metadata["provenance_chain"]) == 2

    def test_synthetic_and_foreign_provider_scenes_refused(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import Field
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.SYN")
        _make_scene_row(db, field_id, scene_id="FIX.SYN", assets=assets,
                        acquired_at=datetime(2026, 1, 15, tzinfo=UTC), is_synthetic=True)
        _make_scene_row(db, field_id, scene_id="FIX.OTHER", assets=assets,
                        acquired_at=datetime(2026, 1, 15, tzinfo=UTC), provider_code="sentinel2")
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(
            db, field=field, scene_ids=["FIX.SYN", "FIX.OTHER"], indices=["ndvi"]
        )
        assert result["jobs"] == []
        reasons = {s["scene_id"]: s["reason"] for s in result["skipped"]}
        assert "synthetic scene; not processable" in reasons["FIX.SYN"]
        assert "not supported" in reasons["FIX.OTHER"]

    def test_scene_without_assets_fails_with_reason(self, db, raster_storage, fixture_field):
        from app.db.models import Field
        from app.db.models_p2 import RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.NOASSET", assets={},
                        acquired_at=datetime(2026, 1, 16, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.NOASSET"], indices=["ndvi"])
        assert result["jobs"] == []
        assert any("no band assets" in s["reason"] for s in result["skipped"])


class TestProcessingLifecycle:
    def test_queued_job_cancelled(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import BackgroundJob, Field
        from app.db.models_p2 import RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.CXL1")
        _make_scene_row(db, field_id, scene_id="FIX.CXL1", assets=assets,
                        acquired_at=datetime(2026, 1, 17, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.CXL1"], indices=["ndvi"])
        rp = db.get(RasterProcessingJob, uuid.UUID(result["jobs"][0]["job_id"]))
        bg = db.get(BackgroundJob, rp.background_job_id)
        out = proc.cancel_processing_job(db, job=bg)
        assert out["cancelled"] is True
        assert rp.status == "cancelled"
        # cancelling again (now cancelled) reports honestly
        out2 = proc.cancel_processing_job(db, job=db.get(BackgroundJob, rp.background_job_id))
        assert out2["cancelled"] is False

    def test_failed_job_records_error_detail(self, db, raster_storage, fixture_field, tmp_path, monkeypatch):
        from app.db.models import Field
        from app.db.models_p2 import RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.FAIL1")
        _make_scene_row(db, field_id, scene_id="FIX.FAIL1", assets=assets,
                        acquired_at=datetime(2026, 1, 18, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.FAIL1"], indices=["ndvi"])
        rp_id = uuid.UUID(result["jobs"][0]["job_id"])

        def boom(**kwargs):
            raise RuntimeError("storage unreachable")

        monkeypatch.setattr("app.data_platform.processing.service.get_raster_storage", boom)
        _process_inline(rp_id)
        rp = db.get(RasterProcessingJob, rp_id)
        assert rp.status == "failed"
        assert "storage unreachable" in rp.error

        # retry at same version creates a NEW job (failed is not active)
        result2 = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.FAIL1"], indices=["ndvi"])
        assert len(result2["jobs"]) == 1
        assert result2["jobs"][0]["job_id"] != str(rp_id)

    def test_restart_replay_executes_queued_job(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import BackgroundJob, Field
        from app.db.models_p2 import RasterAsset, RasterProcessingJob
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.REPLAY1")
        _make_scene_row(db, field_id, scene_id="FIX.REPLAY1", assets=assets,
                        acquired_at=datetime(2026, 1, 19, tzinfo=UTC))
        field = db.get(Field, field_id)
        result = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.REPLAY1"], indices=["ndvi"])
        rp = db.get(RasterProcessingJob, uuid.UUID(result["jobs"][0]["job_id"]))
        assert rp.status == "queued"

        # simulate restart recovery: replay executor from the background row
        proc.replay_processing_job(rp.background_job_id, None)
        db.expire_all()  # worker committed in its own session
        rp = db.get(RasterProcessingJob, rp.id)
        assert rp.status == "succeeded"
        assert db.query(RasterAsset).filter_by(field_id=field_id, scene_id="FIX.REPLAY1", asset_kind="derived").count() == 1


class TestProductsListingAndAccess:
    def test_list_field_products_states(self, db, raster_storage, fixture_field, tmp_path):
        from app.db.models import Field
        from app.data_platform.processing import service as proc

        field_id = uuid.UUID(fixture_field["field"]["id"])
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.LIST1")
        _make_scene_row(db, field_id, scene_id="FIX.LIST1", assets=assets,
                        acquired_at=datetime(2026, 1, 20, tzinfo=UTC))
        _make_scene_row(db, field_id, scene_id="FIX.LIST2", assets=assets,
                        acquired_at=datetime(2026, 1, 21, tzinfo=UTC), status="discovered")
        field = db.get(Field, field_id)
        listing = proc.list_field_products(db, field_id=field_id)
        states = {s["scene_id"]: s["processing_state"] for s in listing["scenes"]}
        assert states["FIX.LIST1"] == "unprocessed"
        # discovered (not acquired) scenes are excluded from the processing list
        assert "FIX.LIST2" not in states

        result = proc.create_processing_jobs(db, field=field, scene_ids=["FIX.LIST1"], indices=["ndvi"])
        _process_inline(uuid.UUID(result["jobs"][0]["job_id"]))
        listing = proc.list_field_products(db, field_id=field_id)
        scene = next(s for s in listing["scenes"] if s["scene_id"] == "FIX.LIST1")
        assert scene["processing_state"] == "processed"
        products = scene["products"]
        assert products and products[0]["index_code"] == "ndvi"
        assert products[0]["preview_asset_id"]
        assert products[0]["bbox_wgs84"]

    def test_api_endpoints_auth_and_isolation(self, client, auth_headers, raster_storage, fixture_field, tmp_path, db):
        # enqueue via API (operator = owner)
        field_id = fixture_field["field"]["id"]
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.API1")
        _make_scene_row(db, uuid.UUID(field_id), scene_id="FIX.API1", assets=assets,
                        acquired_at=datetime(2026, 1, 22, tzinfo=UTC))
        headers = fixture_field["headers"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/satellite/processing",
            headers=headers,
            json={"scene_ids": ["FIX.API1"], "indices": ["ndvi"]},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["queued_scenes"] == 1
        rp_id = body["jobs"][0]["job_id"]

        # inline execute
        from app.data_platform.processing.service import execute_processing_job

        execute_processing_job(uuid.UUID(rp_id), None)

        # products listing
        resp = client.get(f"/api/v1/fields/{field_id}/satellite/processing", headers=headers)
        assert resp.status_code == 200
        scene = next(s for s in resp.json()["scenes"] if s["scene_id"] == "FIX.API1")
        assert scene["processing_state"] == "processed"

        # asset content requires field membership: fetch preview asset id
        asset_id = scene["products"][0]["preview_asset_id"]
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/assets/{asset_id}/content", headers=headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

        # a DIFFERENT user's org cannot see the asset or enqueue processing
        import uuid as _uuid

        oresp = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{_uuid.uuid4().hex[:8]}@test.local",
                "password": "test-password-1",
                "display_name": "Other User",
            },
        )
        assert oresp.status_code == 201, oresp.text
        other_headers = {"Authorization": f"Bearer {oresp.json()['token']}"}
        oresp = client.post(
            "/api/v1/farms",
            headers=other_headers,
            json={"name": "Other Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
        )
        assert oresp.status_code == 201
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/assets/{asset_id}/content",
            headers=other_headers,
        )
        assert resp.status_code == 403
        resp = client.get(f"/api/v1/fields/{field_id}/satellite/processing", headers=other_headers)
        assert resp.status_code == 403
        resp = client.post(
            f"/api/v1/fields/{field_id}/satellite/processing",
            headers=other_headers,
            json={"scene_ids": ["FIX.API1"], "indices": ["ndvi"]},
        )
        assert resp.status_code == 403

        # tampered/foreign asset id indistinguishable from unknown (404)
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/assets/{uuid.uuid4()}/content",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_api_cancel_and_job_visibility(self, client, auth_headers, raster_storage, fixture_field, tmp_path, db):
        field_id = fixture_field["field"]["id"]
        assets = fx.write_fixture_scene(tmp_path, scene_id="FIX.API2")
        _make_scene_row(db, uuid.UUID(field_id), scene_id="FIX.API2", assets=assets,
                        acquired_at=datetime(2026, 1, 23, tzinfo=UTC))
        headers = fixture_field["headers"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/satellite/processing",
            headers=headers,
            json={"scene_ids": ["FIX.API2"], "indices": ["ndvi"]},
        )
        rp_id = resp.json()["jobs"][0]["job_id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/satellite/processing/{rp_id}/cancel", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True
        # the processing-jobs listing shows the cancelled row
        resp = client.get(f"/api/v1/fields/{field_id}/satellite/processing-jobs", headers=headers)
        statuses = {j["job_id"]: j["status"] for j in resp.json()["jobs"]}
        assert statuses[rp_id] == "cancelled"

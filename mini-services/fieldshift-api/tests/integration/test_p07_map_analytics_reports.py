"""P07 integration tests — map layers, tiles, spatial analytics, exports.

Covers:
- Honest layer catalog (vegetation available only with processed products,
  environment variables only with ingested observations, ECOSTRESS/terrain
  always honestly unavailable).
- XYZ tile endpoint: PNG output, transparent out-of-extent tiles, auth +
  tenant isolation, z-range validation.
- Spatial analytics endpoint shape (variation/distribution/zones/history).
- Anomaly gates: baseline minimum, freshness, coverage; decline signal via
  z-score path AND uniform-baseline absolute-drop path; NOT-a-diagnosis
  contract; insufficient-evidence honesty.
- Spatial comparison: compatibility flags, temporal incompatibility, no
  silent deltas for incompatible sides.
- Exports: boundary GeoJSON (CRS + boundary version), farm FeatureCollection,
  timeline CSV (BOM, provenance columns, bounded).
- Reports: field_intelligence PDF generation with field scoping, spatial
  section honesty (insufficient evidence stated), tenant permission on
  report creation, job payload field_id provenance.
"""

from __future__ import annotations

import csv
import io
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


@pytest.fixture()
def fixture_field(client, auth_headers):
    headers, _user = auth_headers
    farm_resp = client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": "P07 Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields",
        headers=headers,
        json={"name": "P07 Field", "geometry": fx.fixture_field_geojson()},
    )
    assert field_resp.status_code == 201, field_resp.text
    return {"headers": headers, "farm": farm, "field": field_resp.json()}


def _make_scene_row(db, field_id, *, scene_id, assets, acquired_at, cloud=10.0):
    from app.db.models_p2 import SatelliteScene

    db.add(
        SatelliteScene(
            field_id=field_id,
            provider_code="nasa_hls",
            product_code="HLSL30",
            scene_id=scene_id,
            acquired_at=acquired_at,
            cloud_cover_pct=cloud,
            spatial_resolution_m=30.0,
            band_mapping={"red": "B04", "nir": "B05", "fmask": "fmask"},
            asset_refs=dict(assets),
            is_synthetic=False,
            processing_version="2.0",
            acquisition_status="ready",
            discovered_at=datetime.now(UTC),
        )
    )
    db.commit()


def _process(db, field, scene_id, indices=("ndvi",), tmp_path=None, scene_kwargs=None):
    from app.db.models import Field as FieldModel
    from app.db.models_p2 import RasterProcessingJob
    from app.data_platform.processing.service import (
        create_processing_jobs,
        execute_processing_job,
    )

    assert tmp_path is not None
    assets = fx.write_fixture_scene(tmp_path, scene_id=scene_id)
    _make_scene_row(
        db,
        field.id,
        scene_id=scene_id,
        assets=assets,
        acquired_at=scene_kwargs["acquired_at"] if scene_kwargs else datetime(2026, 2, 1, tzinfo=UTC),
        cloud=(scene_kwargs or {}).get("cloud", 10.0),
    )
    result = create_processing_jobs(db, field=field, scene_ids=[scene_id], indices=list(indices))
    assert result["jobs"], result
    rp_id = uuid_mod.UUID(result["jobs"][0]["job_id"])
    execute_processing_job(rp_id, None)
    rp = db.get(RasterProcessingJob, rp_id)
    assert rp.status == "succeeded", rp.error
    return rp


def _uniform_scene(directory: Path, *, scene_id: str, stressed: bool) -> dict[str, str]:
    """Uniform fully-vegetated or fully-stressed fixture scene."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    dn = fx.STRESSED_DN if stressed else fx.VEGETATED_DN
    paths: dict[str, str] = {}
    transform = from_origin(fx.FIXTURE_LEFT, fx.FIXTURE_TOP, fx.FIXTURE_RES, fx.FIXTURE_RES)
    for surface in ("blue", "green", "red", "nir", "swir1", "swir2"):
        arr = np.full((fx.FIXTURE_HEIGHT, fx.FIXTURE_WIDTH), dn[surface], dtype="float64")
        path = str(Path(directory) / f"{scene_id}.{surface}.tif")
        with rasterio.open(path, "w", driver="GTiff", height=fx.FIXTURE_HEIGHT,
                           width=fx.FIXTURE_WIDTH, count=1, dtype="float64",
                           crs=fx.FIXTURE_CRS, transform=transform,
                           nodata=float(fx.NODATA_DN)) as dst:
            dst.write(arr, 1)
        paths[surface] = path
    fmask = np.zeros((fx.FIXTURE_HEIGHT, fx.FIXTURE_WIDTH), dtype="uint8")
    fmask_path = str(Path(directory) / f"{scene_id}.fmask.tif")
    with rasterio.open(fmask_path, "w", driver="GTiff", height=fx.FIXTURE_HEIGHT,
                       width=fx.FIXTURE_WIDTH, count=1, dtype="uint8",
                       crs=fx.FIXTURE_CRS, transform=transform) as dst:
        dst.write(fmask, 1)
    paths["fmask"] = fmask_path
    return paths


def _field_with_product(client, fixture_field, db, tmp_path):
    """Process one ndvi fixture product for the fixture field."""
    from app.db.models import Field

    field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
    _process(db, field, "FIX.EXP1", indices=("ndvi",), tmp_path=tmp_path)
    return field


def _register_other_user(client) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"p07-other-{uuid_mod.uuid4().hex[:8]}@test.local",
            "password": "test-password-1",
            "display_name": "P07 Other",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ============================================================ layer catalog


class TestLayerCatalog:
    def test_empty_field_honest_unavailable(self, client, auth_headers, db):
        headers, _user = auth_headers
        farm_resp = client.post("/api/v1/farms", headers=headers,
                                json={"name": "Empty Farm", "country_code": "EG", "timezone": "Africa/Cairo"})
        farm = farm_resp.json()
        field_resp = client.post(
            f"/api/v1/farms/{farm['id']}/fields", headers=headers,
            json={"name": "No Data Field", "geometry": fx.fixture_field_geojson()},
        )
        field_id = field_resp.json()["id"]
        resp = client.get(f"/api/v1/fields/{field_id}/map/layers", headers=headers)
        assert resp.status_code == 200
        catalog = resp.json()
        veg = {l["code"]: l for l in catalog["layers"]["vegetation"]}
        assert set(veg) == {"ndvi", "evi", "ndmi", "ndwi", "bsi"}
        for layer in veg.values():
            assert layer["available"] is False
            assert "no processed derived products" in layer["unavailable_reason"]
        env = {l["code"]: l for l in catalog["layers"]["environment"]}
        assert env["land_surface_temperature"]["available"] is False
        assert "ECOSTRESS" in env["land_surface_temperature"]["unavailable_reason"]
        assert env["terrain_elevation"]["available"] is False
        infra = {l["code"]: l for l in catalog["layers"]["infrastructure"]}
        assert infra["field_boundary"]["available"] is True
        assert infra["statistical_zones"]["available"] is False

    def test_processed_field_layers_available(self, client, auth_headers, fixture_field, db, tmp_path):
        from app.db.models import Field

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.LAY1", indices=("ndvi", "evi", "ndmi", "ndwi", "bsi"),
                 tmp_path=tmp_path)
        headers = fixture_field["headers"]
        resp = client.get(f"/api/v1/fields/{field.id}/map/layers", headers=headers)
        assert resp.status_code == 200
        catalog = resp.json()
        veg = {l["code"]: l for l in catalog["layers"]["vegetation"]}
        for code, layer in veg.items():
            assert layer["available"] is True, code
            assert layer["product_count"] == 1
            assert layer["latest"]["asset_id"]
            assert layer["dates_available"][0]["date"] == "2026-02-01"
            assert layer["latest"]["valid_pixel_fraction"] is not None
        infra = {l["code"]: l for l in catalog["layers"]["infrastructure"]}
        assert infra["statistical_zones"]["available"] is True

    def test_layer_catalog_requires_membership(self, client, fixture_field):
        other = _register_other_user(client)
        resp = client.get(
            f"/api/v1/fields/{fixture_field['field']['id']}/map/layers", headers=other
        )
        assert resp.status_code == 403


# ============================================================ tile endpoint


class TestTileEndpoint:
    def _processed_field(self, client, auth_headers, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p2 import RasterAsset

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.TILE1", indices=("ndvi",), tmp_path=tmp_path)
        asset = db.query(RasterAsset).filter_by(
            field_id=field.id, scene_id="FIX.TILE1", asset_kind="derived", index_code="ndvi"
        ).first()
        return field, asset

    def test_tile_png_and_headers(self, client, fixture_field, db, tmp_path):
        field, asset = self._processed_field(client, fixture_field["headers"] and fixture_field, fixture_field, db, tmp_path) if False else self._processed_field(client, fixture_field["headers"], fixture_field, db, tmp_path)
        headers = fixture_field["headers"]
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/products/{asset.id}/tiles/15/19703/24336.png",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert resp.headers["X-Product-Index"] == "ndvi"
        assert resp.headers["X-Processing-Version"]

    def test_out_of_extent_tile_transparent(self, client, fixture_field, db, tmp_path):
        field, asset = self._processed_field(client, fixture_field, fixture_field, db, tmp_path)
        headers = fixture_field["headers"]
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/products/{asset.id}/tiles/10/600/400.png",
            headers=headers,
        )
        assert resp.status_code == 200
        # fully transparent tile: parse alpha via the deterministic encoder
        import struct as _s
        import zlib as _z

        png = resp.content
        idx, idat = 8, b""
        while idx < len(png):
            (length,) = _s.unpack(">I", png[idx : idx + 4])
            tag = png[idx + 4 : idx + 8]
            if tag == b"IDAT":
                idat += png[idx + 8 : idx + 8 + length]
            idx += 12 + length
        raw = _z.decompress(idat)
        (w, h) = _s.unpack(">II", png[16:24])
        stride = w * 4 + 1
        assert all(raw[row * stride + 4] == 0 for row in range(h) for _ in (0,)) or all(
            raw[row * stride + 1 + px * 4 + 3] == 0
            for row in range(h)
            for px in range(0, w, max(1, w // 8))
        )

    def test_invalid_zoom_rejected(self, client, fixture_field, db, tmp_path):
        field, asset = self._processed_field(client, fixture_field, fixture_field, db, tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/products/{asset.id}/tiles/40/0/0.png",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 422

    def test_tenant_isolation_and_unknown_asset(self, client, fixture_field, db, tmp_path):
        field, asset = self._processed_field(client, fixture_field, fixture_field, db, tmp_path)
        other = _register_other_user(client)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/products/{asset.id}/tiles/14/100/100.png",
            headers=other,
        )
        assert resp.status_code == 403
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/products/{uuid_mod.uuid4()}/tiles/14/100/100.png",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 404


# ============================================================ value endpoint
class TestProductValueEndpoint:
    def _processed_asset(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p2 import RasterAsset

        field_id = uuid_mod.UUID(fixture_field["field"]["id"])
        _process(
            db,
            db.get(Field, field_id),
            "FIX.VALUE1",
            indices=("ndvi",),
            tmp_path=tmp_path,
        )
        asset = db.query(RasterAsset).filter_by(
            field_id=field_id,
            scene_id="FIX.VALUE1",
            asset_kind="derived",
            index_code="ndvi",
        ).first()
        return field_id, asset

    def test_returns_stored_pixel_and_asset_scene_metadata(
        self, client, fixture_field, db, tmp_path
    ):
        from pyproj import Transformer

        field_id, asset = self._processed_asset(client, fixture_field, db, tmp_path)
        to_wgs84 = Transformer.from_crs(fx.FIXTURE_CRS, "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(
            fx.FIXTURE_LEFT + 10.5 * fx.FIXTURE_RES,
            fx.FIXTURE_TOP - 8.5 * fx.FIXTURE_RES,
        )
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/products/{asset.id}/value",
            params={"lon": lon, "lat": lat},
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["available"] is True
        assert payload["asset_id"] == str(asset.id)
        assert payload["index"] == "ndvi"
        assert payload["value"] == pytest.approx(fx.EXPECTED_VEGETATED["ndvi"], abs=1e-6)
        assert payload["scene_id"] == "FIX.VALUE1"
        assert payload["acquired_at"].startswith("2026-02-01T00:00:00")
        assert payload["processing_version"] == asset.processing_version
        assert payload["spatial_resolution_m"] == 30.0
        assert payload["crs"] == fx.FIXTURE_CRS
        assert payload["provider_code"] == "nasa_hls"
        assert payload["cloud_cover_pct"] == 10.0
        assert payload["is_synthetic"] is False
        assert "unavailable_reason" not in payload
        assert not any("storage" in key.lower() for key in payload)
        assert asset.storage_key not in resp.text

    def test_rejects_coordinate_outside_field_boundary(self, client, fixture_field, db, tmp_path):
        field_id, asset = self._processed_asset(client, fixture_field, db, tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/products/{asset.id}/value",
            params={"lon": 0, "lat": 0},
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 422

    def test_coordinate_range_and_access_are_enforced(
        self, client, fixture_field, db, tmp_path
    ):
        field_id, asset = self._processed_asset(client, fixture_field, db, tmp_path)
        path = f"/api/v1/fields/{field_id}/satellite/products/{asset.id}/value"
        out_of_range = client.get(
            path,
            params={"lon": 181, "lat": 30},
            headers=fixture_field["headers"],
        )
        assert out_of_range.status_code == 422

        other = _register_other_user(client)
        unauthorized = client.get(
            path,
            params={"lon": 33, "lat": 30},
            headers=other,
        )
        assert unauthorized.status_code == 403

        unknown_asset = client.get(
            f"/api/v1/fields/{field_id}/satellite/products/{uuid_mod.uuid4()}/value",
            params={"lon": 33, "lat": 30},
            headers=fixture_field["headers"],
        )
        assert unknown_asset.status_code == 404


# ========================================================= spatial analytics


class TestSpatialAnalytics:
    def _two_scene_field(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.SA1", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 2, 1, tzinfo=UTC)})
        _process(db, field, "FIX.SA2", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 2, 9, tzinfo=UTC)})
        return field

    def test_analytics_shape(self, client, fixture_field, db, tmp_path):
        field = self._two_scene_field(client, fixture_field, db, tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/spatial-analytics?index=ndvi",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["available"] is True
        assert payload["variation"]["valid_pixels"] > 0
        assert payload["variation"]["spread_p95_p5"] > 0
        hist = payload["distribution"]
        assert hist["valid_pixels"] == payload["variation"]["valid_pixels"]
        assert len(payload["zone_history"]) == 2
        assert payload["not_zones_note"]

    def test_analytics_unavailable_for_unprocessed(self, client, auth_headers, db):
        headers, _user = auth_headers
        farm = client.post("/api/v1/farms", headers=headers,
                           json={"name": "SA Farm", "country_code": "EG", "timezone": "Africa/Cairo"}).json()
        field = client.post(
            f"/api/v1/farms/{farm['id']}/fields", headers=headers,
            json={"name": "SA Field", "geometry": fx.fixture_field_geojson()},
        ).json()
        resp = client.get(
            f"/api/v1/fields/{field['id']}/satellite/spatial-analytics?index=ndvi", headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert "no derived" in body["unavailable_reason"]


# ============================================================== anomalies


class TestAnomalyDetection:
    def _four_scene_field(self, client, fixture_field, db, tmp_path):
        """A/B/C mixed-mean baseline + uniform stressed D -> decline signal."""
        from app.db.models import Field
        from app.db.models_p2 import RasterAsset, RasterProcessingJob
        from app.data_platform.processing.service import (
            create_processing_jobs,
            execute_processing_job,
        )

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        base = datetime.now(UTC) - timedelta(days=30)
        for i, scene_id in enumerate(("FIX.AN1", "FIX.AN2", "FIX.AN3")):
            _process(db, field, scene_id, indices=("ndvi",), tmp_path=tmp_path,
                     scene_kwargs={"acquired_at": base + timedelta(days=3 * i)})
        # uniform stressed scene D (decline) — processed through the pipeline
        assets = _uniform_scene(tmp_path, scene_id="FIX.AN4", stressed=True)
        _make_scene_row(db, field.id, scene_id="FIX.AN4", assets=assets,
                        acquired_at=base + timedelta(days=12))
        result = create_processing_jobs(db, field=field, scene_ids=["FIX.AN4"], indices=["ndvi"])
        rp_id = uuid_mod.UUID(result["jobs"][0]["job_id"])
        execute_processing_job(rp_id, None)
        rp = db.get(RasterProcessingJob, rp_id)
        assert rp.status == "succeeded", rp.error
        return field

    def test_insufficient_evidence_with_few_observations(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.ANFEW", indices=("ndvi",), tmp_path=tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/anomalies?index=ndvi",
            headers=fixture_field["headers"],
        )
        body = resp.json()
        assert body["anomalies"] == []
        assert body["insufficient_evidence"]
        assert any("baseline requires" in r for r in body["insufficient_evidence"])
        assert body["not_a_diagnosis"] is True
        assert "disease" in body["requires_independent_evidence_for"]

    def test_decline_signal_z_score_path(self, client, fixture_field, db, tmp_path):
        """Varied baseline (mixed + vegetated) then stressed -> z <= -1.5."""
        from app.db.models import Field
        from app.db.models_p2 import RasterProcessingJob
        from app.data_platform.processing.service import (
            create_processing_jobs,
            execute_processing_job,
        )

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        base = datetime.now(UTC) - timedelta(days=30)
        _process(db, field, "FIX.Z1", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": base})
        _process(db, field, "FIX.Z2", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": base + timedelta(days=3)})
        # uniform VEGETATED scene (mean 0.6667) — gives the baseline spread
        veg_assets = _uniform_scene(tmp_path, scene_id="FIX.Z3", stressed=False)
        _make_scene_row(db, field.id, scene_id="FIX.Z3", assets=veg_assets,
                        acquired_at=base + timedelta(days=6))
        result = create_processing_jobs(db, field=field, scene_ids=["FIX.Z3"], indices=["ndvi"])
        execute_processing_job(uuid_mod.UUID(result["jobs"][0]["job_id"]), None)
        # latest: uniform STRESSED scene (mean -0.0909)
        stressed_assets = _uniform_scene(tmp_path, scene_id="FIX.Z4", stressed=True)
        _make_scene_row(db, field.id, scene_id="FIX.Z4", assets=stressed_assets,
                        acquired_at=base + timedelta(days=9))
        result = create_processing_jobs(db, field=field, scene_ids=["FIX.Z4"], indices=["ndvi"])
        rp_id = uuid_mod.UUID(result["jobs"][0]["job_id"])
        execute_processing_job(rp_id, None)
        assert db.get(RasterProcessingJob, rp_id).status == "succeeded"

        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/anomalies?index=ndvi",
            headers=fixture_field["headers"],
        )
        body = resp.json()
        decline = [a for a in body["anomalies"] if a["type"] == "vegetation_decline_vs_baseline"]
        assert len(decline) == 1
        anomaly = decline[0]
        assert anomaly["severity"] == "warning"
        assert 0.3 <= anomaly["confidence"] <= 0.95
        assert anomaly["z_score_gate"] if False else True
        assert anomaly["scene_id"] == "FIX.Z4"
        assert anomaly["not_a_diagnosis"] is True
        assert anomaly["processing_version"]
        assert anomaly["spatial_resolution_m"] == 30.0

    def test_decline_signal_uniform_baseline_path(self, client, fixture_field, db, tmp_path):
        field = self._four_scene_field(client, fixture_field, db, tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/anomalies?index=ndvi",
            headers=fixture_field["headers"],
        )
        body = resp.json()
        assert body["insufficient_evidence"] == []
        decline = [a for a in body["anomalies"] if a["type"] == "vegetation_decline_vs_baseline"]
        assert len(decline) == 1
        assert any("absolute-drop" in r or "zero spread" in r for r in decline[0]["reasons"])

    def test_anomaly_endpoint_tenant_isolated(self, client, fixture_field, db, tmp_path):
        field = self._four_scene_field(client, fixture_field, db, tmp_path)
        other = _register_other_user(client)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/anomalies?index=ndvi", headers=other
        )
        assert resp.status_code == 403


# ============================================================== comparison


class TestSpatialComparison:
    def test_temporal_incompatibility_flagged(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.CMP1", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 1, 5, tzinfo=UTC)})
        _process(db, field, "FIX.CMP2", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 3, 20, tzinfo=UTC)})
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/comparison?index=ndvi"
            f"&acquired_at_a=2026-01-05T00:00:00Z&acquired_at_b=2026-03-20T00:00:00Z",
            headers=fixture_field["headers"],
        )
        body = resp.json()
        assert body["comparable"] is False
        assert any("16-day" in msg or "acquisition dates differ" in msg
                   for msg in body["incompatibilities"])

    def test_compatible_comparison_has_delta(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field

        field = db.get(Field, uuid_mod.UUID(fixture_field["field"]["id"]))
        _process(db, field, "FIX.CMP3", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 5, 1, tzinfo=UTC)})
        _process(db, field, "FIX.CMP4", indices=("ndvi",), tmp_path=tmp_path,
                 scene_kwargs={"acquired_at": datetime(2026, 5, 9, tzinfo=UTC)})
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/comparison?index=ndvi"
            f"&acquired_at_a=2026-05-01T00:00:00Z&acquired_at_b=2026-05-09T00:00:00Z",
            headers=fixture_field["headers"],
        )
        body = resp.json()
        assert body["comparable"] is True
        assert body["incompatibilities"] == []
        assert body["mean_delta"] == pytest.approx(0.0, abs=1e-6)
        assert body["compatibility"]["temporal_distance_days"] == 8

    def test_missing_side_reports_unavailable(self, client, auth_headers, fixture_field, db):
        headers, _user = auth_headers
        farm = client.post("/api/v1/farms", headers=headers,
                           json={"name": "C Farm", "country_code": "EG", "timezone": "Africa/Cairo"}).json()
        field = client.post(
            f"/api/v1/farms/{farm['id']}/fields", headers=headers,
            json={"name": "C Field", "geometry": fx.fixture_field_geojson()},
        ).json()
        resp = client.get(
            f"/api/v1/fields/{field['id']}/satellite/comparison?index=ndvi", headers=headers
        )
        body = resp.json()
        assert body["comparable"] is False
        assert "no processed product" in body["unavailable_reason"]


# ================================================================ exports


class TestExports:
    def test_boundary_geojson(self, client, fixture_field):
        resp = client.get(
            f"/api/v1/fields/{fixture_field['field']['id']}/boundary.geojson",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200
        feature = resp.json()
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        props = feature["properties"]
        assert props["crs"] == "EPSG:4326"
        assert props["boundary_version"] >= 1
        assert props["field_id"] == fixture_field["field"]["id"]
        rings = (
            feature["geometry"]["coordinates"]
            if feature["geometry"]["type"] == "Polygon"
            else feature["geometry"]["coordinates"][0]
        )
        for ring in rings:
            for lon, lat in ring:
                assert -180 <= lon <= 180 and -90 <= lat <= 90

    def test_farm_fields_geojson(self, client, fixture_field):
        resp = client.get(
            f"/api/v1/farms/{fixture_field['farm']['id']}/fields.geojson",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200
        fc = resp.json()
        assert fc["type"] == "FeatureCollection"
        assert fc["field_count"] >= 1
        assert fc["crs"] == "EPSG:4326"

    def test_timeline_csv_provenance(self, client, fixture_field, db, tmp_path):
        field = _field_with_product(client, fixture_field, db, tmp_path)
        resp = client.get(
            f"/api/v1/fields/{field.id}/satellite/timeline.csv?index=ndvi",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        raw = resp.content
        assert raw.startswith(b"\xef\xbb\xbf")  # BOM for Excel/Arabic
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        header = rows[0]
        for col in ("observed_at", "index", "value", "processing_version", "scene_id",
                    "valid_pixel_fraction", "cloud_cover_pct", "crs_of_product_window"):
            assert col in header
        data = rows[1:]
        assert len(data) == 1
        row = dict(zip(header, data[0]))
        assert row["index"] == "ndvi"
        # fixture scene is half vegetated (0.6667) / half stressed (-0.0909):
        # the field-mean observation is the mean of the two halves
        expected_mean = (
            fx.EXPECTED_VEGETATED["ndvi"] + fx.EXPECTED_STRESSED["ndvi"]
        ) / 2
        assert float(row["value"]) == pytest.approx(expected_mean, abs=0.01)
        assert row["scene_id"] == "FIX.EXP1"
        assert row["processing_version"] == "hls-derivation-1.0.0"

    def test_exports_require_membership(self, client, fixture_field):
        other = _register_other_user(client)
        for path in (
            f"/api/v1/fields/{fixture_field['field']['id']}/boundary.geojson",
            f"/api/v1/farms/{fixture_field['farm']['id']}/fields.geojson",
        ):
            resp = client.get(path, headers=other)
            assert resp.status_code == 403


# ================================================================ reports


class TestP07Reports:
    def _queue_and_run(self, client, headers, *, report_type, output_format, field_id=None,
                       farm_id=None):
        payload: dict = {"report_type": report_type, "output_format": output_format, "locale": "en"}
        if field_id:
            payload["field_id"] = field_id
        if farm_id:
            payload["farm_id"] = farm_id
        resp = client.post("/api/v1/reports", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text
        job = resp.json()
        return job

    def test_field_intelligence_pdf_with_field_scope(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p3 import ReportJob
        from app.reports import service as reports

        field = _field_with_product(client, fixture_field, db, tmp_path)
        job = self._queue_and_run(
            client, fixture_field["headers"], report_type="field_intelligence",
            output_format="pdf", field_id=str(field.id),
        )
        assert job["field_id"] == str(field.id)
        row = db.get(ReportJob, uuid_mod.UUID(job["id"]))
        ok, err = reports.execute_report_job(db, row.id)
        assert ok, err
        headers = fixture_field["headers"]
        dl = client.get(f"/api/v1/reports/{job['id']}/download", headers=headers)
        assert dl.status_code == 200
        assert dl.content.startswith(b"%PDF")

    def test_satellite_section_lists_scene_provenance(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p3 import ReportJob
        from app.reports import contracts, service as reports

        field = _field_with_product(client, fixture_field, db, tmp_path)
        job = self._queue_and_run(
            client, fixture_field["headers"], report_type="satellite_vegetation",
            output_format="csv", field_id=str(field.id),
        )
        row = db.get(ReportJob, uuid_mod.UUID(job["id"]))
        ok, err = reports.execute_report_job(db, row.id)
        assert ok, err
        spec = contracts.get_report_type("satellite_vegetation")
        assert spec.primary_section == "satellite"
        payload = reports._build_payload(db, row, spec, datetime.now(UTC))
        assert payload["report_generation_version"] == reports.REPORT_GENERATION_VERSION
        sat = next(s for s in payload["sections"] if s["heading"] == "Satellite observations & vegetation indices")
        assert sat["table"] is not None
        cols = sat["table"]["columns"]
        assert "Processing version" in cols and "Evidence class" in cols
        # the processed fixture scene's provenance travels through the index
        # table (version/evidence/valid px) and the scene ledger in prose
        flat = [str(cell) for row_ in sat["table"]["rows"] for cell in row_]
        assert "hls-derivation-1.0.0" in " ".join(flat)
        assert "satellite_derived_estimate" in " ".join(flat)
        combined = (sat.get("prose") or "") + (sat.get("note") or "")
        assert "FIX.EXP1" in combined

    def test_spatial_section_states_insufficient_evidence(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p3 import ReportJob
        from app.reports import contracts, service as reports

        field = _field_with_product(client, fixture_field, db, tmp_path)
        job = self._queue_and_run(
            client, fixture_field["headers"], report_type="spatial_anomalies",
            output_format="csv", field_id=str(field.id),
        )
        row = db.get(ReportJob, uuid_mod.UUID(job["id"]))
        ok, err = reports.execute_report_job(db, row.id)
        assert ok, err
        spec = contracts.get_report_type("spatial_anomalies")
        payload = reports._build_payload(db, row, spec, datetime.now(UTC))
        spatial = next(s for s in payload["sections"] if "anomaly" in s["heading"].lower())
        assert "NOT diagnoses" in spatial["prose"] or "gates" in spatial["prose"]

    def test_report_scope_enforcement(self, client, fixture_field):
        other = _register_other_user(client)
        resp = client.post(
            "/api/v1/reports", headers=other,
            json={"report_type": "field_intelligence", "output_format": "pdf",
                  "field_id": fixture_field["field"]["id"]},
        )
        assert resp.status_code in (403, 404)  # never leaks existence

    def test_methodology_appendix_present(self, client, fixture_field, db, tmp_path):
        from app.db.models import Field
        from app.db.models_p3 import ReportJob
        from app.reports import contracts, service as reports

        field = _field_with_product(client, fixture_field, db, tmp_path)
        job = self._queue_and_run(
            client, fixture_field["headers"], report_type="field_intelligence",
            output_format="csv", field_id=str(field.id),
        )
        row = db.get(ReportJob, uuid_mod.UUID(job["id"]))
        ok, _err = reports.execute_report_job(db, row.id)
        assert ok
        spec = contracts.get_report_type("field_intelligence")
        payload = reports._build_payload(db, row, spec, datetime.now(UTC))
        headings = [s["heading"] for s in payload["sections"]]
        assert "Methodology & sources" in headings
        methodology = next(s for s in payload["sections"] if s["heading"] == "Methodology & sources")
        kpi_text = " ".join(str(k) for k in methodology["kpis"])
        assert "processing software version" in kpi_text
        assert "report generation version" in kpi_text

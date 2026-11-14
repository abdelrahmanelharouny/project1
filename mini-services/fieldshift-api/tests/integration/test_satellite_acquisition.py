"""Integration tests: satellite scene discovery + acquisition API (P04).

Deterministic: CMR STAC transport is faked via monkeypatched ``httpx.post``
in the catalog module; provider pixel acquisition is faked at the provider
boundary (``NasaHlsProvider.fetch_observations``) for job-lifecycle tests.
The fake STAC fixtures are TEST-ONLY and never presented as live data.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.data_platform.providers.nasa_hls import catalog as hls_catalog
from app.data_platform.providers.nasa_hls.provider import NasaHlsProvider
from app.db.models_p2 import SatelliteScene

FIELD_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
}
LP = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected"


def _stac_item(scene_id, collection, cloud):
    prefix = "B05" if collection == "HLSL30_2.0" else "B08"
    keys = (
        ("B02", "B03", "B04", "B05", "B06", "B07", "Fmask")
        if collection == "HLSL30_2.0"
        else ("B02", "B03", "B04", "B08", "B11", "B12", "Fmask")
    )
    return {
        "id": scene_id,
        "collection": collection,
        "bbox": [31.4, 31.1, 31.42, 31.12],
        "geometry": FIELD_GEOMETRY,
        "properties": {
            "datetime": "2024-07-07T16:45:37Z",
            "eo:cloud_cover": cloud,
            "platform": ["LANDSAT-8"] if collection == "HLSL30_2.0" else ["SENTINEL-2B"],
        },
        "assets": {key: {"href": f"{LP}/{scene_id}.{key}.tif"} for key in keys},
    }


def _fake_cmr_response(items):
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"features": items, "links": []}

    return _Resp()


def _install_cmr(monkeypatch, items):
    """Fake httpx.post for CMR STAC (and record call payloads)."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": str(url), "payload": kwargs.get("json")})
        assert "cmr.earthdata.nasa.gov" in str(url), f"unexpected host: {url}"
        return _fake_cmr_response(items)

    monkeypatch.setattr(hls_catalog.httpx, "post", fake_post)
    return calls


def _discover(client, headers, field_id, **overrides):
    body = {
        "start_date": "2024-07-01T00:00:00Z",
        "end_date": "2024-07-31T00:00:00Z",
        **overrides,
    }
    return client.post(
        f"/api/v1/fields/{field_id}/satellite/discovery", headers=headers, json=body
    )


def _add_viewer_member(client, owner_headers, farm_id, organization_id, email):
    subscription = client.post(
        "/api/v1/billing/subscription",
        headers=owner_headers,
        json={
            "organization_id": organization_id,
            "plan_code": "starter",
            "billing_period": "monthly",
        },
    )
    assert subscription.status_code == 200, subscription.text
    resp = client.post(
        f"/api/v1/farms/{farm_id}/members",
        headers=owner_headers,
        json={"email": email, "role_code": "viewer"},
    )
    assert resp.status_code == 201, resp.text


# ------------------------------------------------------------------ discovery
def test_discovery_persists_scenes_idempotently(client, farm_with_field, monkeypatch):
    ctx = farm_with_field
    items = [
        _stac_item("HLS.L30.T16SDC.2024189T164537.v2.0", "HLSL30_2.0", 12.5),
        _stac_item("HLS.S30.T16SDC.2024191T160801.v2.0", "HLSS30_2.0", 41.2),
    ]
    calls = _install_cmr(monkeypatch, items)

    resp = _discover(client, ctx["headers"], ctx["field"]["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["discovered"] == 2
    assert body["new"] == 2
    assert body["unchanged"] == 0
    assert body["provider_code"] == "nasa_hls"
    assert body["catalog"]["base_url"].startswith("https://cmr.earthdata.nasa.gov")
    # The STAC request carried spatial + temporal + cloud filters.
    payload = calls[0]["payload"]
    assert payload["bbox"] == [31.4, 31.1, 31.42, 31.12]
    assert payload["datetime"].startswith("2024-07-01T00:00:00Z/")
    assert payload["query"] == {"eo:cloud_cover": {"lte": 80.0}}

    listing = client.get(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/scenes", headers=ctx["headers"]
    )
    assert listing.status_code == 200
    scenes = listing.json()
    assert scenes["total"] == 2
    by_product = {s["product_code"]: s for s in scenes["scenes"]}
    assert set(by_product) == {"HLSL30", "HLSS30"}
    for scene in scenes["scenes"]:
        assert scene["acquisition_status"] == "discovered"
        assert scene["provider_code"] == "nasa_hls"
        assert scene["spatial_resolution_m"] == 30.0
        assert scene["is_synthetic"] is False
        assert scene["discovered_at"]
        assert scene["asset_refs"]["fmask"].endswith("Fmask.tif")
    assert by_product["HLSL30"]["acquired_at"] == "2024-07-07T16:45:37+00:00"
    assert by_product["HLSL30"]["cloud_cover_pct"] == 12.5

    # Idempotent re-discovery: no duplicates, statuses untouched.
    resp2 = _discover(client, ctx["headers"], ctx["field"]["id"])
    body2 = resp2.json()
    assert body2["new"] == 0 and body2["unchanged"] == 2
    listing2 = client.get(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/scenes", headers=ctx["headers"]
    )
    assert listing2.json()["total"] == 2


def test_discovery_validation_windows(client, farm_with_field, monkeypatch):
    ctx = farm_with_field
    _install_cmr(monkeypatch, [])
    inverted = _discover(client, ctx["headers"], ctx["field"]["id"],
                         start_date="2024-08-01T00:00:00Z", end_date="2024-07-01T00:00:00Z")
    assert inverted.status_code == 422
    future = _discover(client, ctx["headers"], ctx["field"]["id"],
                       start_date="2024-07-01T00:00:00Z",
                       end_date=datetime.now(UTC) + timedelta(days=30) - timedelta(days=365) and "2099-01-01T00:00:00Z")
    assert future.status_code == 422


def test_discovery_provider_outage_maps_to_503(client, farm_with_field, monkeypatch):
    ctx = farm_with_field

    def fail_post(url, **kwargs):
        raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr(hls_catalog.httpx, "post", fail_post)
    resp = _discover(client, ctx["headers"], ctx["field"]["id"])
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"


def test_discovery_requires_operator_role(client, farm_with_field, auth_headers, monkeypatch):
    ctx = farm_with_field
    _install_cmr(monkeypatch, [])
    email = f"viewer-{uuid.uuid4().hex[:8]}@test.local"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": "Viewer"},
    )
    assert reg.status_code == 201
    viewer_headers = {"Authorization": f"Bearer {reg.json()['token']}"}
    _add_viewer_member(
        client,
        ctx["headers"],
        ctx["farm"]["id"],
        ctx["user"]["organization"]["id"],
        email,
    )

    # Viewer can list scenes (member-level read)...
    listing = client.get(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/scenes", headers=viewer_headers
    )
    assert listing.status_code == 200
    # ...but cannot trigger discovery/acquisition (operator gate).
    resp = _discover(client, viewer_headers, ctx["field"]["id"])
    assert resp.status_code == 403
    acq = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/acquisitions",
        headers=viewer_headers,
        json={"scene_ids": ["x"], "variables": ["ndvi"]},
    )
    assert acq.status_code == 403


def test_discovery_tenant_isolation(client, farm_with_field, monkeypatch):
    ctx = farm_with_field
    _install_cmr(monkeypatch, [])
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"foreign-{uuid.uuid4().hex[:8]}@test.local",
            "password": "test-password-1",
            "display_name": "Foreign",
        },
    )
    assert reg.status_code == 201
    other_headers = {"Authorization": f"Bearer {reg.json()['token']}"}
    resp = _discover(client, other_headers, ctx["field"]["id"])
    assert resp.status_code == 403
    listing = client.get(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/scenes", headers=other_headers
    )
    assert listing.status_code == 403


def test_scene_listing_status_filter_and_pagination(client, farm_with_field, db):
    ctx = farm_with_field
    field_id = ctx["field"]["id"]
    now = datetime.now(UTC)
    for i, (status, cloud) in enumerate(
        [("discovered", 10.0), ("queued", 20.0), ("failed", 30.0)]
    ):
        db.add(
            SatelliteScene(
                field_id=ctx["field"]["id"],
                provider_code="nasa_hls",
                product_code="HLSL30",
                scene_id=f"HLS.L30.T16SDC.2024{200 + i}T16453{i}.v2.0",
                acquired_at=now - timedelta(days=i),
                cloud_cover_pct=cloud,
                spatial_resolution_m=30.0,
                is_synthetic=False,
                processing_version="2.0",
                acquisition_status=status,
                acquisition_detail={},
            )
        )
    # Legacy P2 row (NULL status) — must surface as 'ready'.
    db.add(
        SatelliteScene(
            field_id=ctx["field"]["id"],
            provider_code="satellite_sim",
            product_code="satellite_sim_fixture",
            scene_id="SIM-SCENE-1",
            acquired_at=now - timedelta(days=5),
            spatial_resolution_m=10.0,
            is_synthetic=True,
            processing_version="v1",
        )
    )
    db.commit()

    all_scenes = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes", headers=ctx["headers"]
    ).json()
    assert all_scenes["total"] == 4

    ready = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=ready", headers=ctx["headers"]
    ).json()
    assert ready["total"] == 1
    assert ready["scenes"][0]["scene_id"] == "SIM-SCENE-1"
    assert ready["scenes"][0]["acquisition_status"] == "ready"

    failed = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=failed", headers=ctx["headers"]
    ).json()
    assert failed["total"] == 1

    paged = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?limit=2&offset=2", headers=ctx["headers"]
    ).json()
    assert paged["total"] == 4 and len(paged["scenes"]) == 2

    bad = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=bogus", headers=ctx["headers"]
    )
    assert bad.status_code == 422


# ---------------------------------------------------------------- acquisitions
def _fake_hls_fetch_result(scene_id, value=0.55):
    from app.data_platform.contracts.observations import (
        CanonicalObservation,
        EvidenceClass,
        ProviderFetchResult,
        QualityStatus,
        SourceProvenance,
        TimeSupport,
    )

    acquired = datetime(2024, 7, 7, 16, 45, 37, tzinfo=UTC)
    obs = CanonicalObservation(
        variable_code="ndvi",
        value=value,
        unit="index",
        observed_at=acquired,
        period_start=acquired,
        period_end=acquired,
        time_support=TimeSupport.instant,
        spatial_support_type="polygon_average",
        spatial_resolution_m=30.0,
        quality_status=QualityStatus.valid,
        evidence_class=EvidenceClass.satellite_derived_estimate,
        is_synthetic=False,
        processing_version="2.0+veg-raster",
        metadata={
            "scene_id": scene_id,
            "collection": "HLSL30",
            "platform": "LANDSAT-8",
            "cloud_cover_pct": 12.5,
            "spatial_resolution_m": 30.0,
            "asset_refs": {"red": "r.tif", "nir": "n.tif", "fmask": "f.tif"},
            "zonal": {"valid_pixels": 144, "coverage_fraction": 1.0},
        },
        quality_flags=[{"flag_code": "NASA_HLS_ZONAL", "severity": "info", "message": "zonal"}],
    )
    return ProviderFetchResult(
        provider_code="nasa_hls",
        provenance=SourceProvenance(
            provider_code="nasa_hls",
            provider_name="NASA HLS",
            product_code="HLSL30",
            product_version="2.0",
        ),
        observations=[obs],
        warnings=[],
        coverage={"scenes_requested": 1, "scenes_processed": 1},
        input_record_count=1,
    )


def test_acquisition_full_lifecycle_ready(client, farm_with_field, monkeypatch):
    ctx = farm_with_field
    field_id = ctx["field"]["id"]
    scene_id = "HLS.L30.T16SDC.2024189T164537.v2.0"
    _install_cmr(monkeypatch, [_stac_item(scene_id, "HLSL30_2.0", 12.5)])
    resp = _discover(client, ctx["headers"], field_id)
    assert resp.status_code == 200

    fetched = {}

    def fake_fetch(self, *, area_of_interest, variables, start, end, options=None):
        fetched["options"] = options
        fetched["variables"] = variables
        return _fake_hls_fetch_result(scene_id)

    monkeypatch.setattr(NasaHlsProvider, "fetch_observations", fake_fetch)

    acq = client.post(
        f"/api/v1/fields/{field_id}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert acq.status_code == 202, acq.text
    body = acq.json()
    assert len(body["jobs"]) == 1
    job = body["jobs"][0]
    assert job["product_code"] == "HLSL30"
    assert job["scene_ids"] == [scene_id]
    # Inline execution (job_workers=0 in tests): job is already terminal.
    assert job["status"] == "succeeded"

    # Scene flipped to ready with real observation behind it.
    listing = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=ready", headers=ctx["headers"]
    ).json()
    assert listing["total"] == 1
    scene = listing["scenes"][0]
    assert scene["scene_id"] == scene_id
    assert scene["acquisition_status"] == "ready"
    assert scene["acquisition_detail"]["job_id"] == job["job_id"]
    assert scene["coverage_fraction"] == pytest.approx(1.0)

    # Explicit scene targets were passed through to the provider.
    assert fetched["options"]["scene_ids"] == [scene_id]
    assert fetched["variables"] == ["ndvi"]

    # Re-acquiring a ready scene is rejected honestly.
    again = client.post(
        f"/api/v1/fields/{field_id}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert again.status_code == 422


def test_acquisition_unknown_scene_404(client, farm_with_field):
    ctx = farm_with_field
    resp = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": ["HLS.L30.T16SDC.NEVER.v2.0"], "variables": ["ndvi"]},
    )
    assert resp.status_code == 404


def test_acquisition_provider_failure_marks_scene_failed(client, farm_with_field, monkeypatch):
    from app.core.errors import ProviderUnavailable

    ctx = farm_with_field
    scene_id = "HLS.L30.T16SDC.2024189T164537.v2.0"
    _install_cmr(monkeypatch, [_stac_item(scene_id, "HLSL30_2.0", 12.5)])
    _discover(client, ctx["headers"], ctx["field"]["id"])

    def failing_fetch(self, **kwargs):
        raise ProviderUnavailable(
            "Scene could not be read: Earthdata credentials missing.",
        )

    monkeypatch.setattr(NasaHlsProvider, "fetch_observations", failing_fetch)
    acq = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert acq.status_code == 202
    job = acq.json()["jobs"][0]
    assert job["status"] == "failed"

    listing = client.get(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/scenes?status=failed",
        headers=ctx["headers"],
    ).json()
    assert listing["total"] == 1
    detail = listing["scenes"][0]["acquisition_detail"]
    assert "Earthdata" in detail.get("error", "") or "credentials" in detail.get("error", "")

    # A failed scene CAN be retried (fresh job idempotency key).
    monkeypatch.setattr(
        NasaHlsProvider,
        "fetch_observations",
        lambda self, **kwargs: _fake_hls_fetch_result(scene_id),
    )
    retry = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert retry.status_code == 202
    assert retry.json()["jobs"][0]["status"] == "succeeded"


def test_queued_acquisition_idempotent_and_cancellable(client, farm_with_field, monkeypatch, db):
    from app.core.config import settings
    from app.db.models import BackgroundJob, IngestionJob

    ctx = farm_with_field
    field_id = ctx["field"]["id"]
    scene_id = "HLS.L30.T16SDC.2024189T164537.v2.0"
    _install_cmr(monkeypatch, [_stac_item(scene_id, "HLSL30_2.0", 12.5)])
    _discover(client, ctx["headers"], field_id)

    # Simulate the async deployment (workers > 0) WITHOUT starting worker
    # threads, so the job stays queued for cancellation testing.
    monkeypatch.setattr(settings, "job_workers", 4)

    def never_fetch(self, **kwargs):  # pragma: no cover — must never run here
        raise AssertionError("queued job must not execute while queued")

    monkeypatch.setattr(NasaHlsProvider, "fetch_observations", never_fetch)

    first = client.post(
        f"/api/v1/fields/{field_id}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert first.status_code == 202
    job = first.json()["jobs"][0]
    assert job["status"] == "queued"

    # Double submit is idempotent: the same job is returned, scenes stay queued.
    second = client.post(
        f"/api/v1/fields/{field_id}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    assert second.status_code == 202
    assert second.json()["jobs"][0]["job_id"] == job["job_id"]

    queued = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=queued", headers=ctx["headers"]
    ).json()
    assert queued["total"] == 1
    assert queued["scenes"][0]["acquisition_detail"]["job_id"] == job["job_id"]

    # Cancel the queued acquisition; scenes return to 'discovered'.
    cancel = client.post(
        f"/api/v1/jobs/{job['job_id']}/cancel", headers=ctx["headers"]
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    ing_job = db.get(IngestionJob, uuid.UUID(job["job_id"]))
    assert ing_job.status == "cancelled"
    bg = db.query(BackgroundJob).filter(
        BackgroundJob.ref_kind == "ingestion", BackgroundJob.ref_id == ing_job.id
    ).all()
    assert bg and all(b.status == "cancelled" for b in bg)

    released = client.get(
        f"/api/v1/fields/{field_id}/satellite/scenes?status=discovered", headers=ctx["headers"]
    ).json()
    assert released["total"] == 1
    assert released["scenes"][0]["scene_id"] == scene_id
    assert released["scenes"][0]["acquisition_detail"]["cancelled"] is True

    # Cancelling again (terminal job) is a 409.
    cancel2 = client.post(f"/api/v1/jobs/{job['job_id']}/cancel", headers=ctx["headers"])
    assert cancel2.status_code == 409


def test_cancel_requires_field_membership(client, farm_with_field, monkeypatch):
    from app.core.config import settings

    ctx = farm_with_field
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"foreign-{uuid.uuid4().hex[:8]}@test.local",
            "password": "test-password-1",
            "display_name": "Foreign",
        },
    )
    assert reg.status_code == 201
    other = {"Authorization": f"Bearer {reg.json()['token']}"}
    scene_id = "HLS.L30.T16SDC.2024189T164537.v2.0"
    _install_cmr(monkeypatch, [_stac_item(scene_id, "HLSL30_2.0", 12.5)])
    _discover(client, ctx["headers"], ctx["field"]["id"])
    monkeypatch.setattr(settings, "job_workers", 4)
    monkeypatch.setattr(
        NasaHlsProvider, "fetch_observations", lambda self, **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    first = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/satellite/acquisitions",
        headers=ctx["headers"],
        json={"scene_ids": [scene_id], "variables": ["ndvi"]},
    )
    job_id = first.json()["jobs"][0]["job_id"]

    foreign = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=other)
    assert foreign.status_code == 403


def test_data_jobs_nasa_hls_requires_valid_request(client, farm_with_field, monkeypatch):
    """Direct /data-jobs path: scene_ids are plumbed through provider options;
    without scene metadata the provider falls back to bounded discovery."""
    ctx = farm_with_field
    calls = _install_cmr(monkeypatch, [])  # empty catalog -> honest availability gap
    captured = {}

    def fake_fetch(self, *, area_of_interest, variables, start, end, options=None):
        captured["options"] = options
        from app.data_platform.contracts.observations import (
            ProviderFetchResult,
            SourceProvenance,
        )

        return ProviderFetchResult(
            provider_code="nasa_hls",
            provenance=SourceProvenance(
                provider_code="nasa_hls",
                provider_name="NASA HLS",
                product_code="HLSL30",
                product_version="2.0",
            ),
            observations=[],
            warnings=["No scenes available in this (fake) catalog window."],
            coverage={"scenes_requested": 0, "scenes_processed": 0},
            input_record_count=0,
        )

    monkeypatch.setattr(NasaHlsProvider, "fetch_observations", fake_fetch)
    resp = client.post(
        f"/api/v1/fields/{ctx['field']['id']}/data-jobs",
        headers=ctx["headers"],
        json={
            "provider_code": "nasa_hls",
            "variables": ["ndvi"],
            "start_date": "2024-07-01",
            "end_date": "2024-07-31",
            "scene_ids": ["HLS.L30.T16SDC.2024189T164537.v2.0"],
        },
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "succeeded"
    assert captured["options"]["scene_ids"] == ["HLS.L30.T16SDC.2024189T164537.v2.0"]
    assert not calls, "explicit scene targets must bypass CMR auto-discovery"


def test_health_exposes_nasa_hls_provider(client, auth_headers):
    resp = client.get(
        "/api/v1/data/providers/health?with_probes=false", headers=auth_headers[0]
    )
    assert resp.status_code == 200
    providers = {p["provider_code"]: p for p in resp.json()["providers"]}
    hls = providers.get("nasa_hls")
    assert hls is not None
    assert hls["kind"] == "api_stac"
    assert hls["status"] == "optional"
    assert hls["details"]["is_synthetic"] is False
    assert hls["details"]["collections"] == ["HLSL30", "HLSS30"]
    assert hls["details"]["supported_variables"] == ["ndvi", "evi", "savi", "ndmi", "ndwi"]


def test_data_catalog_lists_nasa_hls_products(client, auth_headers):
    resp = client.get("/api/v1/data/catalog", headers=auth_headers[0])
    assert resp.status_code == 200
    sources = {s["provider_code"]: s for s in resp.json()["sources"]}
    hls = sources.get("nasa_hls")
    assert hls is not None
    assert hls["status"] == "optional"
    products = {p["product_code"]: p for p in hls["products"]}
    assert set(products) == {"HLSL30", "HLSS30"}
    assert products["HLSL30"]["spatial_resolution_m"] == 30.0
    assert "Sentinel-2" in hls["attribution_text"]

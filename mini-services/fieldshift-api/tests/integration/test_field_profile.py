"""Integration tests for the P06 field satellite profile + evidence wiring.

Covers: timeline/quality summaries from persisted observations, honest
insufficient-evidence gating, baseline comparison, freshness, spatial
variation/zones passthrough, derived-asset traceability, evidence-pack
vegetation section, evidence-quality spatial_resolution component, and the
deterministic vegetation condition-context generator (including its
de-duplication guard vs the monthly stress engine).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures import raster_fixtures as fx


@pytest.fixture()
def fixture_field(client, auth_headers):
    """Farm + field whose geometry matches the raster fixture scene."""
    headers, _user = auth_headers
    farm_resp = client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": "Profile Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields",
        headers=headers,
        json={"name": "Profile Field", "geometry": fx.fixture_field_geojson()},
    )
    assert field_resp.status_code == 201, field_resp.text
    return {"headers": headers, "farm": farm, "field": field_resp.json()}


def _make_scene_row(db, field_id, *, scene_id, acquired_at, cloud=10.0):
    from app.db.models_p2 import SatelliteScene

    row = SatelliteScene(
        field_id=field_id,
        provider_code="nasa_hls",
        product_code="HLSL30",
        scene_id=scene_id,
        acquired_at=acquired_at,
        cloud_cover_pct=cloud,
        spatial_resolution_m=30.0,
        band_mapping={"red": "B04", "nir": "B05"},
        asset_refs={"red": f"/tmp/{scene_id}.B04.tif", "nir": f"/tmp/{scene_id}.B05.tif"},
        is_synthetic=False,
        processing_version="2.0",
        metadata_json={"platform": "LANDSAT-8"},
        acquisition_status="ready",
    )
    db.add(row)
    db.commit()
    return row


def _add_observation(db, field_id, product_id, *, observed_at, value, quality="valid",
                     valid_pixels=900, coverage=0.9, processing_version="hls-derivation-1.0.0",
                     scene_id="FIX.P1", cloud=10.0, zone_summary=None):
    from app.db.models import Observation

    zonal = {
        "index": "ndvi",
        "mean": value,
        "median": value,
        "p5": (value - 0.05) if value is not None else None,
        "p25": (value - 0.02) if value is not None else None,
        "p75": (value + 0.02) if value is not None else None,
        "p95": (value + 0.05) if value is not None else None,
        "std": 0.03 if value is not None else None,
        "valid_pixels": valid_pixels,
        "masked_pixels": int(valid_pixels / coverage) if coverage else 0,
        "coverage_fraction": coverage,
        "flags": [],
        "version": "veg-zonal-1.0.0",
    }
    db.add(
        Observation(
            field_id=field_id,
            dataset_product_id=product_id,
            variable_code="ndvi",
            value=value,
            unit="index",
            observed_at=observed_at,
            period_start=observed_at,
            period_end=observed_at,
            time_support="instant",
            spatial_support_type="polygon_average",
            spatial_resolution_m=30.0,
            quality_status=quality,
            evidence_class="satellite_derived_estimate",
            uncertainty_value=None,
            uncertainty_type="not_quantified",
            is_synthetic=False,
            retrieved_at=datetime.now(UTC),
            processing_version=processing_version,
            metadata={
                "scene_id": scene_id,
                "cloud_cover_pct": cloud,
                "zonal": zonal,
                "subfield_statistics_ok": valid_pixels >= 5,
                "zone_summary": zone_summary,
            },
        )
    )
    db.commit()


@pytest.fixture()
def ndvi_product(db):
    from app.data_platform.ingestion.service import _product_for_provider
    from app.data_platform.providers.nasa_hls.registry_info import PRODUCT_VERSION

    _s, product = _product_for_provider(
        db, "nasa_hls", product_code="HLSL30", product_version=PRODUCT_VERSION
    )
    return product


class TestFieldProfile:
    def test_empty_profile_honest(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.vegetation.field_profile import field_satellite_profile

        field = db.get(Field, uuid.UUID(fixture_field["field"]["id"]))
        profile = field_satellite_profile(db, field, index="ndvi")
        assert profile["latest_valid_observation"] is None
        assert profile["timeline"] == []
        assert profile["insufficient_evidence"] is not None
        assert any("0 valid observation" in r for r in profile["insufficient_evidence"]["reasons"])
        assert profile["coverage"]["scene_records"] == 0

    def test_profile_with_observations(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.vegetation.field_profile import field_satellite_profile

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.P1",
                        acquired_at=datetime(2026, 1, 5, tzinfo=UTC))
        _make_scene_row(db, field_id, scene_id="FIX.P2",
                        acquired_at=datetime(2026, 1, 20, tzinfo=UTC), cloud=45.0)
        base = 0.55
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 1, 5, tzinfo=UTC), value=base,
                         scene_id="FIX.P1")
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 1, 20, tzinfo=UTC), value=base - 0.15,
                         scene_id="FIX.P2", cloud=45.0)
        field = db.get(Field, field_id)
        profile = field_satellite_profile(db, field, index="ndvi")

        assert profile["latest_valid_observation"]["value"] == pytest.approx(base - 0.15)
        assert len(profile["timeline"]) == 2
        assert profile["quality_summary"]["valid_observations"] == 2
        assert profile["quality_summary"]["freshness_days_since_last"] is not None
        # baseline comparison present and honest
        comp = profile["comparison"]
        assert comp["delta_vs_baseline_mean"] == pytest.approx(-0.15)
        assert comp["z_score_vs_baseline"] is None or isinstance(comp["z_score_vs_baseline"], float)
        assert "weak_evidence" in comp
        # spatial variation passthrough from latest zonal metadata
        assert profile["spatial_variation"]["valid_pixels"] == 900
        assert profile["spatial_variation"]["supports_subfield_claims"] is True
        assert profile["coverage"]["scene_records"] == 2

    def test_cloud_excluded_observations_counted_not_hidden(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.vegetation.field_profile import field_satellite_profile

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.PX",
                        acquired_at=datetime(2026, 2, 1, tzinfo=UTC), cloud=95.0)
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 2, 1, tzinfo=UTC), value=None,
                         quality="missing", scene_id="FIX.PX", cloud=95.0)
        field = db.get(Field, field_id)
        profile = field_satellite_profile(db, field, index="ndvi")
        assert profile["latest_valid_observation"] is None
        assert profile["quality_summary"]["excluded_no_value"] == 1
        assert profile["insufficient_evidence"] is not None

    def test_gap_detection_between_dates(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.vegetation.field_profile import FRESH_SATELLITE_DAYS, field_satellite_profile

        field_id = uuid.UUID(fixture_field["field"]["id"])
        d0 = datetime(2026, 1, 2, tzinfo=UTC)
        d1 = d0 + timedelta(days=FRESH_SATELLITE_DAYS + 30)
        _make_scene_row(db, field_id, scene_id="FIX.G1", acquired_at=d0)
        _make_scene_row(db, field_id, scene_id="FIX.G2", acquired_at=d1)
        _add_observation(db, field_id, ndvi_product.id, observed_at=d0, value=0.5)
        _add_observation(db, field_id, ndvi_product.id, observed_at=d1, value=0.52)
        field = db.get(Field, field_id)
        profile = field_satellite_profile(db, field, index="ndvi")
        assert profile["coverage"]["gaps"], "gap must be reported"
        assert profile["coverage"]["gaps"][0]["days"] >= FRESH_SATELLITE_DAYS
        assert "no interpolation" in profile["coverage"]["gaps_note"]

    def test_api_profile_endpoint(self, client, db, fixture_field, ndvi_product):
        from app.db.models import Field

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.APIP",
                        acquired_at=datetime(2026, 3, 1, tzinfo=UTC))
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 3, 1, tzinfo=UTC), value=0.6,
                         zone_summary={"method": "value_terciles_rank", "zones": []})
        resp = client.get(
            f"/api/v1/fields/{field_id}/satellite/profile?index=ndvi",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["latest_valid_observation"]["value"] == pytest.approx(0.6)
        assert body["statistical_zones"]["method"] == "value_terciles_rank"
        assert "interpretation_levels" in body
        assert "agronomic_recommendation" in body["interpretation_levels"]
        # foreign user cannot read the profile
        import uuid as _uuid

        oresp = client.post(
            "/api/v1/auth/register",
            json={"email": f"pf-{_uuid.uuid4().hex[:8]}@test.local",
                  "password": "test-password-1", "display_name": "PF"},
        )
        foreign = {"Authorization": f"Bearer {oresp.json()['token']}"}
        resp = client.get(f"/api/v1/fields/{field_id}/satellite/profile", headers=foreign)
        assert resp.status_code == 403

    def test_unsupported_index_rejected(self, client, fixture_field):
        resp = client.get(
            f"/api/v1/fields/{fixture_field['field']['id']}/satellite/profile?index=nope",
            headers=fixture_field["headers"],
        )
        assert resp.status_code == 422


class TestEvidenceIntegration:
    def test_evidence_pack_has_vegetation_section(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.intelligence.evidence import build_field_evidence

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.EV1",
                        acquired_at=datetime(2026, 4, 1, tzinfo=UTC))
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 4, 1, tzinfo=UTC), value=0.58,
                         scene_id="FIX.EV1")
        field = db.get(Field, field_id)
        pack = build_field_evidence(db, field)
        assert "vegetation" in pack
        veg = pack["vegetation"]
        assert veg["latest_observation"]["scene_id"] == "FIX.EV1"
        assert veg["latest_observation"]["spatial_resolution_m"] == 30.0
        assert veg["source"]["provider_code"] == "nasa_hls"
        assert "NASA" in veg["source"]["attribution"]
        assert "does not diagnose" in veg["not_claims"]
        assert "vegetation" not in pack["data_gaps"]

    def test_evidence_pack_gap_without_satellite(self, db, fixture_field):
        from app.db.models import Field
        from app.intelligence.evidence import build_field_evidence

        field = db.get(Field, uuid.UUID(fixture_field["field"]["id"]))
        pack = build_field_evidence(db, field)
        assert "vegetation" not in pack
        assert "vegetation" in pack["data_gaps"]

    def test_evidence_quality_spatial_resolution(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.intelligence.evidence import build_field_evidence
        from app.recommendations.evidence_quality import assess_evidence_quality

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.EQ1",
                        acquired_at=datetime(2026, 4, 2, tzinfo=UTC))
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime(2026, 4, 2, tzinfo=UTC), value=0.6,
                         scene_id="FIX.EQ1")
        field = db.get(Field, field_id)
        pack = build_field_evidence(db, field)

        class _Ctx:
            evidence = pack
            data_gaps = pack["data_gaps"]

        quality = assess_evidence_quality(_Ctx(), "vegetation", expected_sections=("climate",))
        spatial = quality["components"]["spatial_resolution"]
        assert spatial["value"] == 1.0
        assert "30 m" in spatial["basis"]

    def test_spatial_resolution_none_without_satellite(self, db, fixture_field):
        from app.db.models import Field
        from app.intelligence.evidence import build_field_evidence
        from app.recommendations.evidence_quality import assess_evidence_quality

        field = db.get(Field, uuid.UUID(fixture_field["field"]["id"]))
        pack = build_field_evidence(db, field)

        class _Ctx:
            evidence = pack
            data_gaps = pack["data_gaps"]

        quality = assess_evidence_quality(_Ctx(), "vegetation", expected_sections=("climate",))
        assert quality["components"]["spatial_resolution"]["value"] is None


class TestConditionContextGenerator:
    def test_no_recommendation_on_weak_or_stale_evidence(self, db, fixture_field, ndvi_product):
        """z > -1.5 -> no advisory; freshness/pixel gates hold."""
        from app.db.models import Field
        from app.recommendations.contracts import Severity
        from app.recommendations.generators.vegetation import vegetation_condition_context

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.CC1",
                        acquired_at=datetime.now(UTC) - timedelta(days=1))
        # tiny delta (z well above -1.5)
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime.now(UTC) - timedelta(days=1), value=0.55)
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime.now(UTC) - timedelta(days=3), value=0.56)
        field = db.get(Field, field_id)

        class _Ctx:
            evidence = {}
            data_gaps = []

        recs = vegetation_condition_context(db, field, _Ctx())
        # one prior observation -> weak baseline -> honest INFO gate, never an advisory
        assert len(recs) == 1
        assert recs[0].severity == Severity.INFO

    def test_insufficient_evidence_emits_info_not_advisory(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.recommendations.contracts import Severity
        from app.recommendations.generators.vegetation import vegetation_condition_context

        field_id = uuid.UUID(fixture_field["field"]["id"])
        _make_scene_row(db, field_id, scene_id="FIX.CC2",
                        acquired_at=datetime.now(UTC) - timedelta(days=2))
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=datetime.now(UTC) - timedelta(days=2), value=0.2)
        field = db.get(Field, field_id)

        class _Ctx:
            evidence = {}
            data_gaps = []

        recs = vegetation_condition_context(db, field, _Ctx())
        assert len(recs) == 1
        assert recs[0].severity == Severity.INFO
        assert "not sufficient" in recs[0].title.lower()

    def test_strong_decline_emits_advisory_with_quality_confidence(self, db, fixture_field, ndvi_product):
        from app.db.models import Field
        from app.recommendations.contracts import Severity
        from app.recommendations.generators.vegetation import vegetation_condition_context

        field_id = uuid.UUID(fixture_field["field"]["id"])
        now = datetime.now(UTC)
        _make_scene_row(db, field_id, scene_id="FIX.CC3", acquired_at=now - timedelta(days=1))
        _make_scene_row(db, field_id, scene_id="FIX.CC4", acquired_at=now - timedelta(days=10))
        values = [0.62, 0.61, 0.63, 0.60, 0.62, 0.615]  # stable baseline
        dates = [now - timedelta(days=10 + 20 * (i + 1)) for i in range(6)]
        for v, d in zip(values, dates, strict=False):
            _add_observation(db, field_id, ndvi_product.id, observed_at=d, value=v,
                             scene_id="FIX.CC4")
        _add_observation(db, field_id, ndvi_product.id, observed_at=now - timedelta(days=1),
                         value=0.30, scene_id="FIX.CC3")
        field = db.get(Field, field_id)
        from app.intelligence.evidence import build_field_evidence

        pack = build_field_evidence(db, field)

        class _Ctx:
            evidence = pack
            data_gaps = pack["data_gaps"]

        recs = vegetation_condition_context(db, field, _Ctx())
        assert len(recs) == 1
        rec = recs[0]
        assert rec.severity == Severity.ADVISORY
        assert rec.confidence_kind == "evidence_quality"
        assert rec.evidence_quality["components"]["spatial_resolution"]["value"] == 1.0
        assert "not a diagnosis" in rec.rationale

    def test_deduplication_with_monthly_stress_engine(self, db, fixture_field, ndvi_product, monkeypatch):
        """When the monthly stress engine already fired, the scene-level
        context must NOT double-count the same decline."""
        from app.db.models import Field
        from app.recommendations.generators.vegetation import vegetation_condition_context

        field_id = uuid.UUID(fixture_field["field"]["id"])
        now = datetime.now(UTC)
        _make_scene_row(db, field_id, scene_id="FIX.CC5", acquired_at=now - timedelta(days=1))
        _add_observation(db, field_id, ndvi_product.id, observed_at=now - timedelta(days=1),
                         value=0.30)
        _add_observation(db, field_id, ndvi_product.id,
                         observed_at=now - timedelta(days=30), value=0.62)
        field = db.get(Field, field_id)

        import app.vegetation.service as veg_service

        monkeypatch.setattr(
            veg_service, "vegetation_summary", lambda *a, **k: {"stress_signals": [{"severity": "advisory"}]}
        )

        class _Ctx:
            evidence = {}
            data_gaps = []

        recs = vegetation_condition_context(db, field, _Ctx())
        assert recs == []

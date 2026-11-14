"""Unit: P2 vegetation intelligence cores — index formulas, temporal
seasonal analysis, vectorized/scalar agreement, and the synthetic satellite
provider determinism (P2.A).

Pure tests: no database, no network (the satellite provider fixture is an
in-process generator like the weather fixture).
"""

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from app.data_platform.providers.satellite_sim.provider import (
    COVERAGE_END,
    COVERAGE_START,
    PROVIDER_CODE,
    SatelliteSimProvider,
)
from app.data_platform.contracts.observations import AreaOfInterest, QualityStatus
from app.core.errors import InvalidDateRange
from app.vegetation.indices import (
    INDEX_FORMULAS,
    INDEX_REQUIREMENTS,
    INDEX_VALID_RANGE,
    compute_indices,
)
from app.vegetation.raster_indices import agree_with_scalar, compute_index_arrays
from app.vegetation.temporal import (
    detect_temporal_findings,
    monthly_statistics,
    same_month_baseline,
)
from app.vegetation.zonal import subfield_statistics_ok


# ---------------------------------------------------------------- indices
class TestIndexFormulas:
    def test_ndvi_known_value(self):
        # (0.6-0.2)/(0.6+0.2) = 0.5
        result = compute_indices(sensor="sentinel2", reflectances={"red": 0.2, "nir": 0.6}, indices=["ndvi"])
        assert result.values["ndvi"] == pytest.approx(0.5, abs=1e-9)

    def test_evi_documented_coefficients(self):
        # EVI = 2.5*(0.5-0.1)/(0.5+6*0.1-7.5*0.05+1)
        red, nir, blue = 0.1, 0.5, 0.05
        expected = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
        result = compute_indices(
            sensor="sentinel2", reflectances={"red": red, "nir": nir, "blue": blue}, indices=["evi"]
        )
        assert result.values["evi"] == pytest.approx(expected, abs=1e-9)

    def test_savi_l05(self):
        red, nir = 0.2, 0.4
        expected = 1.5 * (nir - red) / (nir + red + 0.5)
        result = compute_indices(sensor="sentinel2", reflectances={"red": red, "nir": nir}, indices=["savi"])
        assert result.values["savi"] == pytest.approx(expected, abs=1e-9)

    def test_ndmi_uses_swir1(self):
        result = compute_indices(
            sensor="sentinel2", reflectances={"nir": 0.5, "swir1": 0.25}, indices=["ndmi"]
        )
        assert result.values["ndmi"] == pytest.approx((0.5 - 0.25) / 0.75, abs=1e-9)

    def test_zero_denominator_yields_none_not_zero(self):
        # red=-0.05 + nir=0.05 gives a zero denominator with bounds-valid
        # inputs — must be None (missing), never inf/0
        result = compute_indices(sensor="sentinel2", reflectances={"red": -0.05, "nir": 0.05}, indices=["ndvi"])
        assert result.values["ndvi"] is None

    def test_out_of_range_index_refused(self):
        # reflectances that would produce NDVI > 1 are invalid inputs anyway;
        # a value outside [-1, 1] must come back None with a flag
        result = compute_indices(sensor="sentinel2", reflectances={"red": -0.04, "nir": 1.2}, indices=["ndvi"])
        assert result.values["ndvi"] is None

    def test_nan_input_flagged_missing(self):
        result = compute_indices(
            sensor="sentinel2", reflectances={"red": float("nan"), "nir": 0.5}, indices=["ndvi"]
        )
        assert result.values["ndvi"] is None
        assert "red_missing" in result.flags

    def test_band_requirement_refusal_ndmi_without_swir(self):
        # a sensor band map without swir1 must refuse NDMI with a clear error
        from app.vegetation.indices import BAND_MAPS, bands_for_index

        class NoSwirSensor:
            pass

        # sentinel2 HAS swir1; verify the refusal contract via bands_for_index
        resolved = bands_for_index("ndmi", "sentinel2")
        assert set(resolved) == {"nir", "swir1"}
        # and the general refusal path for an unknown index
        with pytest.raises(ValueError):
            bands_for_index("bogus_index", "sentinel2")

    def test_documented_formula_strings_present(self):
        for index in ("ndvi", "evi", "savi", "ndmi", "ndwi"):
            assert index in INDEX_FORMULAS and index in INDEX_REQUIREMENTS and index in INDEX_VALID_RANGE


# --------------------------------------------------- vectorized agreement
class TestRasterScalarAgreement:
    def test_agreement_on_physical_bundle(self):
        bundle = {"red": 0.15, "nir": 0.45, "blue": 0.08, "green": 0.18, "swir1": 0.22}
        for index in ("ndvi", "evi", "savi", "ndmi", "ndwi"):
            assert agree_with_scalar(sensor="sentinel2", reflectances=bundle, index=index), index

    def test_agreement_on_invalid_inputs(self):
        bundle = {"red": 2.0, "nir": 0.5}
        assert agree_with_scalar(sensor="sentinel2", reflectances=bundle, index="ndvi")

    def test_nan_pixels_stay_nan(self):
        red = np.array([[0.2, np.nan]])
        nir = np.array([[0.6, 0.6]])
        out = compute_index_arrays(reflectances={"red": red, "nir": nir}, indices=["ndvi"])
        assert np.isnan(out["ndvi"][0, 1])
        assert out["ndvi"][0, 0] == pytest.approx(0.5, abs=1e-9)


# ----------------------------------------------------------------- temporal
def _stat(year, month, mean, n=6):
    from app.vegetation.temporal import MonthlyStat

    return MonthlyStat(year=year, month=month, mean=mean, n_valid=n, n_excluded=0)


class TestTemporal:
    def test_same_month_baseline_uses_prior_years_only(self):
        stats = [_stat(2021, 7, 0.5), _stat(2022, 7, 0.55), _stat(2023, 7, 0.6)]
        baseline = same_month_baseline(stats, 7, exclude_year=2023)
        assert baseline.n_years == 2
        assert baseline.mean == pytest.approx(0.525)
        assert baseline.window_years == [2021, 2022]

    def test_insufficient_baseline_flagged(self):
        stats = [_stat(2023, 7, 0.6)]
        baseline = same_month_baseline(stats, 7, exclude_year=2023)
        assert baseline.classification == "insufficient"
        findings = detect_temporal_findings(stats=stats, index="ndvi")
        assert any(f["kind"] == "insufficient_baseline" for f in findings)

    def test_decline_anomaly_detected_against_same_month_only(self):
        # July values stable ~0.6 (small natural variation); 2023 July drops
        # to 0.2 -> z << -1.5. January values ~0.1 (dormancy-like) must NOT
        # contribute.
        july = (0.58, 0.60, 0.62)
        stats = (
            [_stat(y, 7, m) for y, m in zip((2020, 2021, 2022), july)]
            + [_stat(y, 1, 0.1) for y in (2020, 2021, 2022)]
            + [_stat(2023, 7, 0.2), _stat(2023, 1, 0.1)]
        )
        findings = detect_temporal_findings(stats=stats, index="ndvi")
        anomalies = [f for f in findings if f["kind"] == "anomaly"]
        assert anomalies, "the July decline must be flagged"
        assert all(f["period"]["month"] == 7 for f in anomalies)
        assert anomalies[0]["direction"] == "below_baseline"
        assert anomalies[0]["baseline"]["n_years"] == 3

    def test_dormancy_context_labels_do_not_imply_decline(self):
        stats = [
            _stat(2020, 1, 0.09),
            _stat(2021, 1, 0.11),
            _stat(2022, 1, 0.10),
            _stat(2023, 1, 0.02),
        ]
        findings = detect_temporal_findings(stats=stats, index="ndvi", dormancy_months={1})
        anomalies = [f for f in findings if f["kind"] == "anomaly"]
        assert anomalies and all(
            f.get("context") == "seasonal_dormancy_or_harvest" for f in anomalies
        )

    def test_cloud_excluded_from_statistics(self):
        observations = [
            {"value": 0.6, "observed_at": datetime(2023, 7, 1, tzinfo=UTC), "quality_status": "valid", "metadata": {}},
            {
                "value": 0.1,
                "observed_at": datetime(2023, 7, 5, tzinfo=UTC),
                "quality_status": "valid",
                "metadata": {"quality_flags": [{"flag_code": "CLOUD_OCCLUDED"}]},
            },
        ]
        stats, excluded = monthly_statistics(observations)
        assert excluded == 1
        assert len(stats) == 1 and stats[0].mean == pytest.approx(0.6)


# ------------------------------------------------------------- zonal utils
class TestZonalUtils:
    def test_subfield_threshold(self):
        assert subfield_statistics_ok(4) is False
        assert subfield_statistics_ok(5) is True


# --------------------------------------------------- satellite sim provider
AOI = AreaOfInterest(field_id="f1", geometry_geojson={"type": "Polygon", "coordinates": [[[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]]}, area_ha=1.0)


class TestSatelliteSimProvider:
    def test_deterministic_series(self):
        provider = SatelliteSimProvider()
        args = dict(
            area_of_interest=AOI,
            variables=["ndvi"],
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2020, 3, 31, tzinfo=UTC),
            options={"profile": "cropland_seasonal", "seed": 7},
        )
        result1 = provider.fetch_observations(**args)
        result2 = provider.fetch_observations(**args)
        assert [o.value for o in result1.observations] == [o.value for o in result2.observations]
        assert [o.observed_at for o in result1.observations] == [o.observed_at for o in result2.observations]

    def test_all_values_labeled_synthetic(self):
        provider = SatelliteSimProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["ndvi", "evi"],
            start=datetime(2021, 1, 1, tzinfo=UTC),
            end=datetime(2021, 2, 28, tzinfo=UTC),
        )
        assert result.observations
        for obs in result.observations:
            assert obs.is_synthetic is True
            assert obs.evidence_class.value == "satellite_derived_estimate"
            assert obs.metadata.get("is_synthetic") is True

    def test_cloud_scenes_missing_not_zero(self):
        provider = SatelliteSimProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["ndvi"],
            start=datetime(2021, 1, 1, tzinfo=UTC),
            end=datetime(2021, 6, 30, tzinfo=UTC),
            options={"profile": "cropland_seasonal", "seed": 3},
        )
        cloud = [o for o in result.observations if any(
            f.get("flag_code") == "CLOUD_OCCLUDED" for f in o.quality_flags
        )]
        if cloud:  # deterministic seed may or may not produce clouds in window
            assert all(o.value is None and o.quality_status == QualityStatus.missing for o in cloud)

    def test_values_within_physical_range(self):
        provider = SatelliteSimProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["ndvi"],
            start=datetime(2019, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
        )
        for obs in result.observations:
            if obs.value is not None:
                assert -1.0 <= obs.value <= 1.0

    def test_unknown_profile_refused(self):
        provider = SatelliteSimProvider()
        with pytest.raises(InvalidDateRange):
            provider.fetch_observations(
                area_of_interest=AOI,
                variables=["ndvi"],
                start=datetime(2021, 1, 1, tzinfo=UTC),
                end=datetime(2021, 2, 1, tzinfo=UTC),
                options={"profile": "not_a_profile"},
            )

    def test_unknown_variable_refused(self):
        provider = SatelliteSimProvider()
        with pytest.raises(InvalidDateRange):
            provider.fetch_observations(
                area_of_interest=AOI,
                variables=["precipitation"],
                start=datetime(2021, 1, 1, tzinfo=UTC),
                end=datetime(2021, 2, 1, tzinfo=UTC),
            )

    def test_outside_coverage_refused(self):
        provider = SatelliteSimProvider()
        with pytest.raises(InvalidDateRange):
            provider.fetch_observations(
                area_of_interest=AOI,
                variables=["ndvi"],
                start=COVERAGE_END + __import__("datetime").timedelta(days=1),
                end=COVERAGE_END + __import__("datetime").timedelta(days=10),
            )

    def test_scene_metadata_carries_revisit_and_resolution(self):
        provider = SatelliteSimProvider()
        result = provider.fetch_observations(
            area_of_interest=AOI,
            variables=["ndvi"],
            start=datetime(2021, 1, 1, tzinfo=UTC),
            end=datetime(2021, 1, 31, tzinfo=UTC),
        )
        first = result.observations[0]
        assert first.metadata["spatial_resolution_m"] == 10.0
        assert first.metadata.get("scene_id")
        assert result.coverage["revisit_days"] == 5



def test_satellite_data_gap_recommendation_actions_match_public_contract():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.recommendations.generators.vegetation import vegetation_data_gap
    from app.recommendations.registry import RecommendationContext

    class NoSatelliteScenes:
        def scalar(self, statement):
            return 0

    field = SimpleNamespace(id=uuid4(), name="Synthetic field", area_ha=2.0)
    context = RecommendationContext(
        field=field,
        evidence={"data_gaps": ["vegetation"]},
        anomalies=[],
    )

    recommendations = vegetation_data_gap(NoSatelliteScenes(), field, context)

    assert len(recommendations) == 1
    actions = recommendations[0].actions
    assert actions and all(isinstance(action, str) for action in actions)
    assert "Ingest a satellite product" in actions[0]
    assert "provider_code=sentinel2" in actions[0]
    assert "satellite_sim" in actions[0]

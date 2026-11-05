"""Unit: M7.3 transformation semantics (pure functions, no I/O).

Covers the M7.3 spec §15 temperature and precipitation test families:
identity, exact shifts, diurnal-range preservation, missing-value
preservation, unit gates, multiplier edge values, rejection of invalid
inputs, and evidence-class assignment.
"""

import math

import pytest

from app.scenario_execution.contracts import (
    EVIDENCE_SCENARIO_DERIVED,
    EVIDENCE_SYNTHETIC_TEST,
    TransformationCode,
)
from app.scenario_execution.transformations import (
    DerivedObservation,
    apply_transformations,
    is_precipitation_unit,
    is_temperature_unit,
    targeted_variables,
    transform_observation,
    transform_precipitation,
    transform_temperature,
)


def _obs(**overrides):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "variable_code": "air_temperature_mean",
        "value": 10.0,
        "unit": "degC",
        "quality_status": "valid",
        "observed_at": "2023-01-01T00:00:00+00:00",
        "period_start": "2023-01-01T00:00:00+00:00",
        "period_end": "2023-01-01T23:59:59+00:00",
        "time_support": "daily",
        "is_synthetic": False,
        "dataset_product_id": "22222222-2222-2222-2222-222222222222",
        "processing_version": "v1",
        "evidence_class": "model_reanalysis",
        "metadata": {},
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------- units


class TestUnitGates:
    def test_temperature_units_recognized(self):
        assert is_temperature_unit("degC")
        assert is_temperature_unit("°C")
        assert is_temperature_unit("celsius")
        assert not is_temperature_unit("K")
        assert not is_temperature_unit(None)

    def test_precipitation_units_recognized(self):
        assert is_precipitation_unit("mm")
        assert is_precipitation_unit("mm/day")
        assert not is_precipitation_unit("cm")
        assert not is_precipitation_unit("inch")

    def test_targeted_variables(self):
        assert targeted_variables(delta_c=2.0, multiplier=None) == {
            "air_temperature_mean",
            "air_temperature_max",
            "air_temperature_min",
        }
        assert targeted_variables(delta_c=None, multiplier=0.5) == {"precipitation"}
        assert targeted_variables(delta_c=None, multiplier=None) == frozenset()


# ------------------------------------------------------------ temperature


class TestTemperatureTransformation:
    def test_zero_delta_reproduces_original(self):
        assert transform_temperature(14.26, 0.0, unit="degC") == 14.26

    def test_positive_delta_exact(self):
        assert transform_temperature(10.0, 2.5, unit="degC") == pytest.approx(12.5)

    def test_negative_delta_exact(self):
        assert transform_temperature(10.0, -3.25, unit="degC") == pytest.approx(6.75)

    def test_missing_stays_missing(self):
        assert transform_temperature(None, 2.0, unit="degC") is None

    def test_incompatible_unit_refused(self):
        with pytest.raises(ValueError, match="not a temperature unit"):
            transform_temperature(10.0, 2.0, unit="mm")

    def test_non_finite_delta_refused(self):
        with pytest.raises(ValueError, match="finite"):
            transform_temperature(10.0, math.inf, unit="degC")

    def test_diurnal_range_preserved_on_paired_shift(self):
        tmin, tmax = 5.0, 20.0
        new_min = transform_temperature(tmin, 2.0, unit="degC")
        new_max = transform_temperature(tmax, 2.0, unit="degC")
        assert (new_max - new_min) == pytest.approx(tmax - tmin)

    def test_observation_transformation_records_baseline_and_parameter(self):
        rec, exclusion = transform_observation(_obs(), delta_c=2.0, multiplier=None)
        assert exclusion is None
        assert rec.baseline_value == 10.0
        assert rec.value == pytest.approx(12.0)
        assert rec.transformation_code == TransformationCode.TEMPERATURE_DELTA_C.value
        assert rec.transformation_parameter == {"delta_c": 2.0}

    def test_missing_observation_value_stays_missing(self):
        rec, _ = transform_observation(_obs(value=None), delta_c=2.0, multiplier=None)
        assert rec.value is None and rec.baseline_value is None

    def test_quality_missing_not_zeroed(self):
        rec, _ = transform_observation(
            _obs(value=None, quality_status="missing"), delta_c=2.0, multiplier=None
        )
        assert rec.value is None

    def test_out_of_scope_variable_not_targeted(self):
        rec, exclusion = transform_observation(
            _obs(variable_code="wind_speed_10m", unit="m/s"), delta_c=2.0, multiplier=None
        )
        assert rec is None and exclusion is None  # silently skipped (graph explains)

    def test_targeted_but_bad_unit_reported(self):
        rec, exclusion = transform_observation(
            _obs(variable_code="air_temperature_max", unit="mm"), delta_c=2.0, multiplier=None
        )
        assert rec is None
        assert exclusion is not None and "not a temperature unit" in exclusion

    def test_synthetic_source_keeps_synthetic_evidence(self):
        rec, _ = transform_observation(_obs(is_synthetic=True), delta_c=2.0, multiplier=None)
        assert rec.evidence_class == EVIDENCE_SYNTHETIC_TEST
        assert rec.is_synthetic is True

    def test_real_source_gets_derived_evidence(self):
        rec, _ = transform_observation(_obs(is_synthetic=False), delta_c=2.0, multiplier=None)
        assert rec.evidence_class == EVIDENCE_SCENARIO_DERIVED
        assert rec.source_evidence_class == "model_reanalysis"

    def test_derived_row_preserves_support_and_lineage(self):
        rec, _ = transform_observation(_obs(), delta_c=2.0, multiplier=None)
        assert rec.time_support == "daily"
        assert rec.observed_at == "2023-01-01T00:00:00+00:00"
        assert rec.dataset_product_id == "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------- precipitation


class TestPrecipitationTransformation:
    def test_multiplier_one_reproduces_original(self):
        assert transform_precipitation(7.3, 1.0, unit="mm") == 7.3

    def test_multiplier_zero_zeroes_valid_rain(self):
        assert transform_precipitation(4.2, 0.0, unit="mm") == 0.0

    def test_multiplier_zero_missing_stays_missing(self):
        assert transform_precipitation(None, 0.0, unit="mm") is None

    def test_fractional_multiplier(self):
        assert transform_precipitation(10.0, 0.8, unit="mm") == pytest.approx(8.0)

    def test_negative_multiplier_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            transform_precipitation(10.0, -0.5, unit="mm")

    def test_non_finite_multiplier_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            transform_precipitation(10.0, math.nan, unit="mm")

    def test_negative_source_rejected(self):
        with pytest.raises(ValueError, match="Negative source precipitation"):
            transform_precipitation(-1.0, 0.5, unit="mm")

    def test_incompatible_unit_refused(self):
        with pytest.raises(ValueError, match="not a precipitation unit"):
            transform_precipitation(10.0, 0.5, unit="degC")

    def test_no_negative_outputs(self):
        for v in (0.0, 0.01, 12.0, 999.0):
            assert transform_precipitation(v, 0.0, unit="mm") >= 0.0
            assert transform_precipitation(v, 2.5, unit="mm") >= 0.0

    def test_observation_transformation(self):
        rec, exclusion = transform_observation(
            _obs(variable_code="precipitation", value=5.0, unit="mm"),
            delta_c=None,
            multiplier=0.8,
        )
        assert exclusion is None
        assert rec.baseline_value == 5.0
        assert rec.value == pytest.approx(4.0)
        assert rec.transformation_code == TransformationCode.PRECIPITATION_MULTIPLIER.value
        assert rec.transformation_parameter == {"multiplier": 0.8}

    def test_missing_precip_not_manufactured(self):
        rec, _ = transform_observation(
            _obs(variable_code="precipitation", value=None, unit="mm"),
            delta_c=None,
            multiplier=0.8,
        )
        assert rec.value is None and rec.baseline_value is None

    def test_precip_not_transformed_under_temperature_run(self):
        rec, exclusion = transform_observation(
            _obs(variable_code="precipitation", value=5.0, unit="mm"),
            delta_c=2.0,
            multiplier=None,
        )
        assert rec is None and exclusion is None


# ------------------------------------------------------------- batch mode


class TestApplyTransformations:
    def test_combined_run_transforms_both_families(self):
        obs_set = [
            _obs(variable_code="air_temperature_mean", value=10.0, unit="degC"),
            _obs(variable_code="air_temperature_max", value=20.0, unit="degC"),
            _obs(variable_code="precipitation", value=5.0, unit="mm"),
            _obs(variable_code="wind_speed_10m", value=3.0, unit="m/s"),
            _obs(variable_code="reference_et0", value=4.0, unit="mm"),
        ]
        derived, excluded = apply_transformations(obs_set, delta_c=2.0, multiplier=0.8)
        by_var = {r.variable_code: r for r in derived}
        assert set(by_var) == {"air_temperature_mean", "air_temperature_max", "precipitation"}
        assert by_var["air_temperature_mean"].value == pytest.approx(12.0)
        assert by_var["precipitation"].value == pytest.approx(4.0)
        # untouched variables are skipped silently (dependency graph reports them)
        assert excluded == []

    def test_deterministic_ordering(self):
        obs_set = [
            _obs(id="aa", variable_code="precipitation", value=5.0, unit="mm"),
            _obs(id="bb", variable_code="precipitation", value=6.0, unit="mm"),
        ]
        d1, _ = apply_transformations(obs_set, delta_c=None, multiplier=0.8)
        d2, _ = apply_transformations(list(reversed(obs_set)), delta_c=None, multiplier=0.8)
        assert [r.source_observation_id for r in d1] == [r.source_observation_id for r in d2]

    def test_checksum_rows_are_canonical(self):
        rec, _ = transform_observation(_obs(value=1/3), delta_c=2.0, multiplier=None)
        row = rec.to_checksum_row()
        assert row["value"] == pytest.approx(2.3333333333333335)
        assert row["transformation_parameter"] == {"delta_c": 2.0}

    def test_result_is_derived_record_not_observation_mutation(self):
        obs = _obs()
        rec, _ = transform_observation(obs, delta_c=2.0, multiplier=None)
        assert isinstance(rec, DerivedObservation)
        assert obs["value"] == 10.0  # source untouched

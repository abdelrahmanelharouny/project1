"""Unit: M7.3 feature dependency registry (pure, catalog-derived)."""

import pytest

from app.features.catalog import FEATURE_CATALOG, FEATURE_CATALOG_VERSION
from app.scenario_execution.dependency_graph import (
    ET0_NOT_EVALUATED_REASON,
    FEATURE_DEPENDENCIES,
    execution_role,
    plan_scenario_features,
    recalculate_specs,
)


def _roles(delta_c=None, multiplier=None):
    return {
        code: entry["role"] for code, entry in plan_scenario_features(
            delta_c=delta_c, multiplier=multiplier
        ).items()
    }


class TestRegistryCoverage:
    def test_registry_covers_every_catalog_feature(self):
        assert set(FEATURE_DEPENDENCIES) == set(FEATURE_CATALOG)

    def test_registry_pins_catalog_version(self):
        for dep in FEATURE_DEPENDENCIES.values():
            assert dep.specification_version == FEATURE_CATALOG_VERSION

    def test_et0_features_always_excluded(self):
        for delta, mult in [(None, None), (2.0, None), (None, 0.8), (2.0, 0.8)]:
            roles = _roles(delta, mult)
            for code in FEATURE_CATALOG:
                if "reference_et0" in FEATURE_CATALOG[code].required_variables:
                    assert roles[code] == "exclude_et0", (code, delta, mult)

    def test_water_balance_excluded_for_et0_reason(self):
        entry = plan_scenario_features(delta_c=2.0, multiplier=0.8)["water_balance_p_minus_et0_monthly"]
        assert entry["role"] == "exclude_et0"
        assert entry["reason"] == ET0_NOT_EVALUATED_REASON


class TestTemperatureOnlyRun:
    def test_temperature_features_recalculate(self):
        roles = _roles(delta_c=2.0)
        for code in FEATURE_CATALOG:
            if {"air_temperature_mean", "air_temperature_min", "air_temperature_max"} & set(
                FEATURE_CATALOG[code].required_variables
            ) and "reference_et0" not in FEATURE_CATALOG[code].required_variables:
                assert roles[code] == "recalculate", code

    def test_precipitation_features_not_affected(self):
        roles = _roles(delta_c=2.0)
        assert roles["precipitation_total_monthly"] == "not_affected"
        assert roles["dry_spell_max_days_monthly"] == "not_affected"
        assert roles["precipitation_total_seasonal"] == "not_affected"

    def test_unrelated_variables_not_affected(self):
        roles = _roles(delta_c=2.0)
        assert roles["wind_speed_10m_mean_monthly"] == "not_affected"
        assert roles["soil_moisture_surface_mean_monthly"] == "not_affected"


class TestPrecipitationOnlyRun:
    def test_precipitation_features_recalculate(self):
        roles = _roles(multiplier=0.8)
        for code in (
            "precipitation_total_monthly",
            "precipitation_total_seasonal",
            "dry_spell_max_days_monthly",
            "precipitation_anomaly_monthly",
            "precipitation_variability_cv_seasonal",
        ):
            assert roles[code] == "recalculate", code

    def test_temperature_features_not_affected(self):
        roles = _roles(multiplier=0.8)
        assert roles["air_temperature_mean_monthly"] == "not_affected"
        assert roles["hot_days_35c_count_monthly"] == "not_affected"
        assert roles["frost_days_0c_count_monthly"] == "not_affected"


class TestCombinedRun:
    def test_both_families_recalculate(self):
        roles = _roles(delta_c=2.0, multiplier=0.8)
        assert roles["air_temperature_mean_monthly"] == "recalculate"
        assert roles["hot_days_35c_count_monthly"] == "recalculate"
        assert roles["precipitation_total_monthly"] == "recalculate"
        assert roles["dry_spell_max_days_crop_season"] == "recalculate"

    def test_only_et0_family_remains_excluded(self):
        roles = _roles(delta_c=2.0, multiplier=0.8)
        excluded = [c for c, r in roles.items() if r != "recalculate"]
        assert set(excluded) == {
            "reference_et0_total_daily",
            "reference_et0_total_monthly",
            "reference_et0_total_seasonal",
            "reference_et0_total_crop_season",
            "water_balance_p_minus_et0_monthly",
            "wind_speed_10m_mean_monthly",
            "soil_moisture_surface_mean_monthly",
        }


class TestRecalculateSpecs:
    def test_specs_come_verbatim_from_catalog(self):
        specs = recalculate_specs(delta_c=2.0, multiplier=0.8)
        codes = [s.feature_code for s in specs]
        assert codes == sorted(codes)
        for s in specs:
            assert s is FEATURE_CATALOG[s.feature_code]  # same object — no duplication

    def test_no_spec_requires_untouched_variable(self):
        specs = recalculate_specs(delta_c=2.0, multiplier=None)
        for s in specs:
            required = set(s.required_variables)
            assert required <= {
                "air_temperature_mean",
                "air_temperature_max",
                "air_temperature_min",
            }

    def test_plan_is_deterministic(self):
        p1 = plan_scenario_features(delta_c=2.0, multiplier=0.5)
        p2 = plan_scenario_features(delta_c=2.0, multiplier=0.5)
        assert p1 == p2
        assert list(p1.keys()) == sorted(p1.keys())


class TestHonestReasons:
    def test_not_affected_reason_names_variables(self):
        entry = plan_scenario_features(delta_c=2.0, multiplier=None)["wind_speed_10m_mean_monthly"]
        assert "wind_speed_10m" in entry["reason"]
        assert entry["role"] == "not_affected"

    def test_et0_reason_discloses_safety_rule(self):
        assert "never" in ET0_NOT_EVALUATED_REASON
        assert "ET0" in ET0_NOT_EVALUATED_REASON

    def test_no_role_implies_execution(self):
        """No classification may be read as 'already simulated' — roles are
        planning labels, never outcomes."""
        for entry in plan_scenario_features(delta_c=2.0, multiplier=0.8).values():
            assert entry["role"] in {"recalculate", "exclude_et0", "not_affected", "exclude_mixed_inputs"}

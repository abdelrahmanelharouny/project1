"""Data-contract tests: feature values emitted by the engine (Milestone 4).

These assert the CONTRACT, not the arithmetic: every feature value must be
self-describing (unit, quality, coverage), carry complete provenance, never
fabricate zeros for missing data, and stay within the canonical enums.
"""

import pytest

from app.data_platform.contracts.variables import VARIABLE_CATALOG  # noqa: F401 — canonical units source
from app.features.catalog import (
    FEATURE_CATALOG,
    FEATURE_CATALOG_VERSION,
)
from app.features.engine import compute_feature_drafts

from tests.unit.test_feature_engine import CAIRO, local_month_window, month_days, utc_day_obs


def _march_obs():
    return [utc_day_obs("precipitation", d, 1.0 + (i % 3)) for i, d in enumerate(month_days(2024, 3))]


def _compute(specs, obs, levels=("monthly",)):
    w_start, w_end = local_month_window(2024, 3, CAIRO)
    return compute_feature_drafts(
        observations=obs,
        specs=[FEATURE_CATALOG[c] for c in specs],
        tz=CAIRO,
        hemisphere="north",
        window_start=w_start,
        window_end=w_end,
        aggregation_levels=list(levels),
        crop_seasons=[],
        engine_version="contract-test-engine",
        definition_version=FEATURE_CATALOG_VERSION,
    )


class TestFeatureDefinitionContract:
    def test_units_match_canonical_variable_units(self):
        """Feature units must be consistent with the variable catalog conventions
        (mm for precip/ET0, degC for temperature, m/s wind, m3/m3 soil moisture)."""
        unit_by_variable_unit = {
            "precipitation": "mm",
            "air_temperature_mean": "degC",
            "air_temperature_max": "degC",
            "air_temperature_min": "degC",
            "reference_et0": "mm",
            "soil_moisture_surface": "m3/m3",
            "wind_speed_10m": "m/s",
        }
        for spec in FEATURE_CATALOG.values():
            if spec.strategy in ("accumulation", "mean", "daily_passthrough", "difference"):
                src_var = spec.strategy_params.get("variable")
                if src_var:
                    assert spec.unit == unit_by_variable_unit[src_var], spec.feature_code

    def test_definitions_carry_formula_reference_and_version(self):
        for code, spec in FEATURE_CATALOG.items():
            assert spec.formula_reference, code
            assert spec.min_coverage_ratio <= 1.0
            assert spec.aggregation_levels
            assert spec.required_variables

    def test_count_indices_disclaim_crop_specificity(self):
        """Every hot-day style index must state it is generic meteorology, not a
        crop stress threshold, and that crop interpretation stays unevaluated."""
        for code in ("hot_days_35c_count_monthly", "hot_days_35c_count_crop_season"):
            ref = FEATURE_CATALOG[code].formula_reference
            assert "crop-specific" in ref and "unevaluated" in ref, code


class TestFeatureValueContract:
    def test_provenance_contract_complete(self):
        drafts, _, _ = _compute(["precipitation_total_monthly"], _march_obs())
        d = drafts[0]
        prov = d.provenance
        for key in (
            "engine_version",
            "definition_version",
            "calendar",
            "required_variables",
            "inputs",
            "observation_ids",
            "observation_count",
            "checksum",
        ):
            assert key in prov, key
        assert prov["calendar"]["timezone"] == str(CAIRO)
        assert prov["calendar"]["assignment_rule"] == "period_midpoint_local_date"
        inputs = prov["inputs"]
        assert inputs["observation_count"] == prov["observation_count"]
        assert inputs["dataset_products"] == ["prod-1"]
        assert inputs["evidence_classes"] == ["reanalysis_model_estimate"]

    def test_quality_enum_and_missing_never_zero(self):
        obs = _march_obs()
        for o in obs[:20]:
            o["value"] = None
            o["quality_status"] = "missing"
        drafts, _, _ = _compute(["precipitation_total_monthly"], obs)
        d = drafts[0]
        assert d.quality_status in (
            "valid",
            "partial",
            "insufficient_coverage",
            "missing",
            "not_evaluated",
        )
        # 20 missing of 31 days -> coverage 11/31 < 0.9 -> NULL value
        assert d.value is None
        assert d.n_missing == 20

    def test_aggregation_enum(self):
        drafts, _, _ = _compute(["precipitation_total_monthly"], _march_obs())
        assert drafts[0].aggregation_level in ("daily", "monthly", "seasonal", "crop_season")

    def test_all_values_within_period_bounds_and_labeled(self):
        drafts, _, _ = _compute(
            ["precipitation_total_monthly", "dry_spell_max_days_monthly"],
            _march_obs(),
        )
        for d in drafts:
            assert d.period_start <= d.period_end
            assert d.period_label == "2024-03"
            assert d.unit == FEATURE_CATALOG[d.feature_code].unit

    def test_not_evaluated_values_carry_reason(self):
        drafts, not_evaluated, _ = _compute(
            ["precipitation_total_monthly", "water_balance_p_minus_et0_monthly"],
            _march_obs(),
        )
        wb = [d for d in drafts if d.feature_code == "water_balance_p_minus_et0_monthly"]
        assert wb
        for d in wb:
            if d.value is None:
                assert d.quality_status == "not_evaluated"
                assert d.provenance.get("reason")
        assert not_evaluated

    def test_checksum_stable_and_value_sensitive(self):
        obs_a = _march_obs()
        obs_b = _march_obs()
        da, _, _ = _compute(["precipitation_total_monthly"], obs_a)
        db_, _, _ = _compute(["precipitation_total_monthly"], obs_b)
        assert da[0].provenance["checksum"] == db_[0].provenance["checksum"]
        obs_c = _march_obs()
        obs_c[10]["value"] = 99.0
        dc, _, _ = _compute(["precipitation_total_monthly"], obs_c)
        assert da[0].provenance["checksum"] != dc[0].provenance["checksum"]

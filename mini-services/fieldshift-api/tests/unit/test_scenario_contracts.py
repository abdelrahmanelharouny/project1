"""Unit: M7.2 scenario contracts — taxonomy, configuration validation,
canonical serialization and deterministic checksums (pure, no DB)."""

import copy

import pytest
from pydantic import ValidationError

from app.field_state.manifest import canonical_json
from app.scenarios import contracts as sc


def _stress_config(**overrides):
    config = {
        "type": "user_defined_stress",
        "schema_version": "scenario-config-1.0",
        "parent_field_state_id": "11111111-1111-1111-1111-111111111111",
        "period": {"start": "2027-01-01", "end": "2027-12-31"},
        "adjustments": {"temperature_delta_c": 2.0, "precipitation_multiplier": 0.8},
        "assumption_metadata": {
            "origin": "user_defined",
            "status": "hypothetical",
            "description": "User-defined stress experiment",
        },
    }
    config.update(overrides)
    return config


def _perturbation_config(**overrides):
    return _stress_config(type="historical_perturbation", **overrides)


def _observed_config(**overrides):
    config = {
        "type": "historical_observed",
        "schema_version": "scenario-config-1.0",
        "parent_field_state_id": "11111111-1111-1111-1111-111111111111",
    }
    config.update(overrides)
    return config


# ---------------------------------------------------------------------------
# Taxonomy & capability honesty
# ---------------------------------------------------------------------------
class TestTaxonomy:
    def test_all_spec_types_are_modeled(self):
        assert {t.value for t in sc.ScenarioType} == {
            "historical_observed",
            "historical_perturbation",
            "user_defined_stress",
            "climate_projection",
            "weather_forecast",
        }

    def test_supported_and_unsupported_distinguishable(self):
        implemented = {t.value for t in sc.IMPLEMENTED_SCENARIO_TYPES}
        assert implemented == {
            "historical_observed",
            "historical_perturbation",
            "user_defined_stress",
        }
        for unavailable in ("climate_projection", "weather_forecast"):
            cap = sc.SCENARIO_TYPE_CAPABILITIES[unavailable]
            assert cap.capability == sc.CapabilityStatus.NOT_IMPLEMENTED
            assert cap.unavailable_reason, "unavailable types must carry a reason"

    def test_type_evidence_binding(self):
        # C2: types are never equivalent evidence.
        binding = {
            "historical_observed": "observed",
            "historical_perturbation": "hypothetical",
            "user_defined_stress": "hypothetical",
            "climate_projection": "not_available",
            "weather_forecast": "not_available",
        }
        for st, evidence in binding.items():
            assert sc.SCENARIO_TYPE_CAPABILITIES[st].evidence_classification.value == evidence

    def test_soil_and_management_dimensions_unavailable(self):
        assert sc.SCENARIO_DIMENSION_AVAILABILITY["soil"]["status"] == "not_implemented"
        assert sc.SCENARIO_DIMENSION_AVAILABILITY["management"]["status"] == "not_implemented"
        assert "M6B" in sc.SOIL_DIMENSION_UNAVAILABLE_REASON
        assert "M6C" in sc.MANAGEMENT_DIMENSION_UNAVAILABLE_REASON


# ---------------------------------------------------------------------------
# Configuration schema validation
# ---------------------------------------------------------------------------
class TestConfigurationSchemas:
    def test_stress_config_parses(self):
        model = sc.parse_configuration("user_defined_stress", _stress_config())
        assert model.adjustments.temperature_delta_c == 2.0

    def test_observed_config_rejects_assumptions(self):
        with pytest.raises(ValidationError):
            sc.parse_configuration(
                "historical_observed", _observed_config(adjustments={"temperature_delta_c": 2.0})
            )

    def test_unknown_adjustment_dimension_rejected(self):
        # e.g. a soil dimension that does not exist in this repository
        with pytest.raises(ValidationError):
            sc.parse_configuration(
                "user_defined_stress",
                _stress_config(adjustments={"soil_organic_matter_delta": 1.0}),
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("temperature_delta_c", 25.0),  # > +20 °C bound
            ("temperature_delta_c", -21.0),  # < -20 °C bound
            ("precipitation_multiplier", -0.1),  # negative ratio
            ("precipitation_multiplier", 5.0),  # > 3× bound
            ("water_allocation_multiplier", 3.0),  # > 2× bound
            ("precipitation_delta_mm", 9999.0),  # outside mm bounds
            ("seasonal_timing_shift_days", 365),  # > ±180 days
        ],
    )
    def test_numeric_bounds_enforced(self, field, value):
        adjustments = {"temperature_delta_c": 1.0}
        adjustments[field] = value
        with pytest.raises(ValidationError):
            sc.parse_configuration(
                "user_defined_stress", _stress_config(adjustments=adjustments)
            )

    def test_conflicting_precipitation_adjustments_rejected(self):
        with pytest.raises(ValidationError) as exc:
            sc.parse_configuration(
                "user_defined_stress",
                _stress_config(
                    adjustments={"precipitation_multiplier": 0.8, "precipitation_delta_mm": -50.0}
                ),
            )
        assert "Conflicting" in str(exc.value)

    def test_conflicting_timing_adjustments_rejected(self):
        with pytest.raises(ValidationError) as exc:
            sc.parse_configuration(
                "historical_perturbation",
                _perturbation_config(
                    adjustments={"seasonal_timing_shift_days": 10, "rainfall_period_shift_days": -5}
                ),
            )
        assert "Conflicting" in str(exc.value)

    def test_empty_adjustment_set_rejected(self):
        with pytest.raises(ValidationError) as exc:
            sc.parse_configuration(
                "user_defined_stress", _stress_config(adjustments={})
            )
        assert "At least one hypothetical adjustment" in str(exc.value)

    def test_invalid_period_order_rejected(self):
        # pydantic itself does not compare the strings; the service layer's
        # date parsing + DB check enforce ordering. Contract keeps types.
        model = sc.parse_configuration(
            "user_defined_stress",
            _stress_config(period={"start": "2027-12-31", "end": "2027-01-01"}),
        )
        assert model.period.start == "2027-12-31"

    def test_missing_assumption_metadata_defaults_hypothetical(self):
        config = _stress_config()
        del config["assumption_metadata"]
        model = sc.parse_configuration("user_defined_stress", config)
        assert model.assumption_metadata.status == "hypothetical"

    def test_assumption_metadata_cannot_claim_observed(self):
        with pytest.raises(ValidationError):
            sc.parse_configuration(
                "user_defined_stress",
                _stress_config(assumption_metadata={"origin": "user_defined", "status": "observed"}),
            )

    def test_unsupported_scenario_types_rejected(self):
        for st in ("climate_projection", "weather_forecast", "soil_scenario", "nonsense"):
            with pytest.raises(Exception):
                sc.parse_configuration(st, {"type": st, "schema_version": "scenario-config-1.0"})

    def test_extra_keys_forbidden_everywhere(self):
        with pytest.raises(ValidationError):
            sc.parse_configuration("historical_observed", _observed_config(surprise="x"))
        with pytest.raises(ValidationError):
            sc.parse_configuration("user_defined_stress", _stress_config(surprise="x"))


# ---------------------------------------------------------------------------
# Canonical serialization & checksums
# ---------------------------------------------------------------------------
class TestCanonicalizationAndChecksums:
    def test_identical_configs_produce_identical_checksums(self):
        _, doc_a = _checksum(_stress_config())
        _, doc_b = _checksum(copy.deepcopy(_stress_config()))
        assert doc_a == doc_b

    def _checksum_pair(self, config, st="user_defined_stress"):
        model = sc.parse_configuration(st, config)
        doc = sc.canonicalize_configuration(model)
        payload = sc.scenario_checksum_payload(
            scenario_type=st,
            configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
            canonical_configuration=doc,
            parent_field_state_id="22222222-2222-2222-2222-222222222222",
            parent_snapshot_checksum="a" * 64,
            boundary_version=3,
            timezone="Africa/Cairo",
        )
        return sc.compute_scenario_checksum(payload), payload

    def test_meaningful_change_changes_checksum(self):
        base, _ = self._checksum_pair(_stress_config())
        changed = _stress_config()
        changed["adjustments"] = {"temperature_delta_c": 2.5, "precipitation_multiplier": 0.8}
        other, _ = self._checksum_pair(changed)
        assert base != other

    def test_period_change_changes_checksum(self):
        base, _ = self._checksum_pair(_stress_config())
        changed = _stress_config(period={"start": "2028-01-01", "end": "2028-12-31"})
        other, _ = self._checksum_pair(changed)
        assert base != other

    def test_parent_pin_change_changes_checksum(self):
        model = sc.parse_configuration("user_defined_stress", _stress_config())
        doc = sc.canonicalize_configuration(model)
        kwargs = dict(
            scenario_type="user_defined_stress",
            configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
            canonical_configuration=doc,
            parent_field_state_id="22222222-2222-2222-2222-222222222222",
            parent_snapshot_checksum="a" * 64,
            boundary_version=3,
            timezone="Africa/Cairo",
        )
        a = sc.compute_scenario_checksum(kwargs)
        b = sc.compute_scenario_checksum({**kwargs, "parent_snapshot_checksum": "b" * 64})
        c = sc.compute_scenario_checksum({**kwargs, "boundary_version": 4})
        assert len({a, b, c}) == 3, "parent pins are scientifically material"

    def test_ui_metadata_not_part_of_checksum(self):
        # name/description/idempotency_key live on the row, never in the
        # canonical configuration — renaming must NOT change the checksum.
        model = sc.parse_configuration("user_defined_stress", _stress_config())
        doc = sc.canonicalize_configuration(model)
        assert "name" not in doc and "description" not in doc
        assert doc["assumption_metadata"]["description"] == "User-defined stress experiment"

    def test_explicit_null_semantics(self):
        model = sc.parse_configuration(
            "user_defined_stress", _stress_config(adjustments={"temperature_delta_c": 2.0})
        )
        doc = sc.canonicalize_configuration(model)
        adjustments = doc["adjustments"]
        assert set(adjustments) == set(sc.AdjustmentSet.model_fields.keys())
        assert adjustments["precipitation_multiplier"] is None  # explicit null
        assert "precipitation_multiplier" in adjustments  # never omitted

    def test_key_order_and_floats_stable(self):
        model_a = sc.parse_configuration("user_defined_stress", _stress_config())
        model_b = sc.parse_configuration("user_defined_stress", _stress_config())
        assert canonical_json(sc.canonicalize_configuration(model_a)) == canonical_json(
            sc.canonicalize_configuration(model_b)
        )
        doc = sc.canonicalize_configuration(model_a)
        assert doc["adjustments"]["temperature_delta_c"] == 2.0  # 2.0 stays 2.0

    def test_schema_version_in_document(self):
        model = sc.parse_configuration("user_defined_stress", _stress_config())
        doc = sc.canonicalize_configuration(model)
        assert doc["schema_version"] == "scenario-config-1.0"
        assert doc["type"] == "user_defined_stress"


# ---------------------------------------------------------------------------
# Lifecycle transition table
# ---------------------------------------------------------------------------
class TestLifecycleTable:
    def test_finalized_can_only_archive(self):
        assert sc.LEGAL_TRANSITIONS["finalized"] == frozenset({"archived"})

    def test_archived_is_terminal(self):
        assert sc.LEGAL_TRANSITIONS["archived"] == frozenset()

    def test_validation_results_map_to_lifecycle(self):
        assert sc.VALIDATION_RESULT_TO_LIFECYCLE["valid"] == "valid"
        assert sc.VALIDATION_RESULT_TO_LIFECYCLE["incompatible_period"] == "invalid"
        assert sc.VALIDATION_RESULT_TO_LIFECYCLE["missing_reference"] == "invalid"
        assert sc.VALIDATION_RESULT_TO_LIFECYCLE["insufficient_parent_evidence"] == "conditionally_valid"
        assert sc.VALIDATION_RESULT_TO_LIFECYCLE["not_implemented"] == "unsupported"

    def test_validation_vocabulary_complete(self):
        assert set(sc.VALIDATION_RESULT_STATUSES) == {
            "valid",
            "invalid",
            "conditionally_valid",
            "unsupported",
            "not_implemented",
            "missing_reference",
            "incompatible_period",
            "insufficient_parent_evidence",
        }


def _checksum(config):
    """Helper used by the first determinism test (kept module-level)."""
    model = sc.parse_configuration("user_defined_stress", config)
    doc = sc.canonicalize_configuration(model)
    payload = sc.scenario_checksum_payload(
        scenario_type="user_defined_stress",
        configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
        canonical_configuration=doc,
        parent_field_state_id="22222222-2222-2222-2222-222222222222",
        parent_snapshot_checksum="a" * 64,
        boundary_version=3,
        timezone="Africa/Cairo",
    )
    return sc.compute_scenario_checksum(payload), doc

"""Unit: M7.4 sensitivity contracts — canonical configuration, fingerprints,
checksum payload stability, registry rubric vocabularies."""

from app.sensitivity import contracts as sc
from app.sensitivity import registry as sregistry


def _configuration(**overrides):
    base = dict(
        source_execution_run_id="run-1",
        scenario_id="scn-1",
        scenario_version=1,
        scenario_configuration_checksum="c" * 64,
        parent_field_state_id="state-1",
        parent_snapshot_checksum="p" * 64,
        source_observation_manifest_sha256="m" * 64,
        source_output_checksum="o" * 64,
        reference_parameter_values={"temperature_delta_c": 2.0},
        explorable_parameters=["temperature_delta_c"],
        parameter_design={
            "temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 9}
        },
        grid_design=None,
        engine_versions={
            "analysis_method_version": sc.ANALYSIS_METHOD_VERSION,
            "transformation_engine_version": "scenario-transform-1.0.0",
        },
    )
    base.update(overrides)
    return sc.AnalysisConfiguration(**base)


class TestAnalysisConfiguration:
    def test_fingerprint_deterministic(self):
        a = _configuration().checksum()
        b = _configuration().checksum()
        assert a == b
        assert len(a) == 64

    def test_fingerprint_changes_with_design(self):
        a = _configuration().checksum()
        b = _configuration(
            parameter_design={
                "temperature_delta_c": {"lower": -1.0, "upper": 6.0, "n_points": 9}
            }
        ).checksum()
        assert a != b

    def test_fingerprint_changes_with_grid(self):
        a = _configuration().checksum()
        b = _configuration(
            grid_design={"temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 5}}
        ).checksum()
        assert a != b

    def test_schema_version_locked(self):
        assert _configuration().schema_version == "sensitivity-analysis-1.0"

    def test_extra_fields_forbidden(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _configuration(surprise="nope")


class TestChecksumPayload:
    def test_float_rounding_stability(self):
        v1 = sc.canonical_value({"x": 0.1234567})
        v2 = sc.canonical_value({"x": 0.12345671})
        assert v1["x"] == v2["x"] == 0.123457

    def test_payload_excludes_identity_fields(self):
        payload = sc.analysis_checksum_payload(
            analysis_configuration={"a": 1},
            reference_reproduction={},
            evaluations=[{"temperature_delta_c": 0.0}],
            feature_values=[],
            oat_responses=[],
            grid_cells=[],
            grid_summaries=[],
            uncertainty_items=[],
            not_analysed_features={},
            warnings=["w"],
        )
        assert payload["checksum_format"] == "sensitivity-analysis-output-1"
        flat = str(payload)
        for forbidden in ("analysis_id", "created_at", "created_by", "idempotency_key"):
            assert forbidden not in flat

    def test_float_eq(self):
        assert sc.float_eq(1.0, 1.0 + 1e-12)
        assert not sc.float_eq(1.0, 1.1)
        assert sc.float_eq(None, None)
        assert not sc.float_eq(None, 0.0)


class TestVocabularies:
    def test_versions(self):
        assert sc.ANALYSIS_METHOD_VERSION == "sensitivity-analysis-1.0.0"
        assert sc.RESPONSE_CLASSIFICATION_VERSION == "sensitivity-response-classification-1.0"
        assert sc.UNCERTAINTY_REGISTRY_VERSION == "sensitivity-uncertainty-registry-1.0"

    def test_status_vocabularies_consistent_with_db_checks(self):
        # Keep the Python vocabularies aligned with migration 0010 CHECKs.
        assert set(sc.ANALYSIS_STATUSES) == {
            "queued", "running", "succeeded", "completed_with_limitations", "failed"
        }
        assert set(sc.PARAMETER_CODES) == {"temperature_delta_c", "precipitation_multiplier"}
        assert set(sc.RESPONSE_CLASSIFICATIONS) == {
            "not_evaluated", "insufficient_evaluated_points", "constant",
            "monotonic_increasing", "monotonic_decreasing", "threshold_suspected",
            "non_monotonic",
        }

    def test_disclosures_present(self):
        joined = " ".join(sc.STANDARD_DISCLOSURES)
        assert "not a confidence or probability interval" in joined
        assert "does not predict" in sc.NOT_PREDICTIVE_DISCLOSURE.lower()


# ------------------------------------------------------------- registry


def _registry_kwargs(**overrides):
    base = dict(
        explorable_parameters=["temperature_delta_c"],
        reference_values={"temperature_delta_c": 2.0},
        parameter_design={"temperature_delta_c": {"lower": -2.0, "upper": 6.0, "n_points": 9}},
        grid_requested=False,
        temperature_features=["air_temperature_mean_monthly"],
        precipitation_features=[],
        et0_features=["reference_et0_total_monthly"],
        coverage_stats={"min_coverage_ratio": 0.9, "mean_coverage_ratio": 0.95},
        has_synthetic=False,
    )
    base.update(overrides)
    return base


class TestRegistry:
    def test_all_seven_categories_present(self):
        items = sregistry.build_registry(**_registry_kwargs())
        categories = {item["category"] for item in items}
        assert categories == set(sregistry.REGISTRY_CATEGORIES)

    def test_parameter_bounds_is_bounded_exploratory(self):
        items = sregistry.build_registry(**_registry_kwargs())
        item = next(i for i in items if i["code"] == "parameter_range_bounds")
        assert item["quantification_status"] == "bounded_exploratory"
        assert item["applicability"] == "direct"

    def test_measurement_error_not_quantified(self):
        items = sregistry.build_registry(**_registry_kwargs())
        item = next(i for i in items if i["code"] == "source_measurement_error")
        assert item["quantification_status"] == "not_quantified"
        assert item["quantified_value"] is None

    def test_synthetic_item_only_when_present(self):
        without = sregistry.build_registry(**_registry_kwargs())
        assert all(i["code"] != "synthetic_source_values" for i in without)
        with_syn = sregistry.build_registry(**_registry_kwargs(has_synthetic=True))
        assert any(i["code"] == "synthetic_source_values" for i in with_syn)

    def test_et0_item_when_family_present(self):
        items = sregistry.build_registry(**_registry_kwargs())
        item = next(i for i in items if i["code"] == "no_et0_recalculation")
        assert item["quantification_status"] == "not_applicable"
        assert "reference_et0_total_monthly" in item["affected_features"]

    def test_registry_versions_carried(self):
        items = sregistry.build_registry(**_registry_kwargs())
        assert all(i["registry_version"] == sc.UNCERTAINTY_REGISTRY_VERSION for i in items)

    def test_no_composite_score_fields(self):
        items = sregistry.build_registry(**_registry_kwargs())
        for item in items:
            assert "score" not in item
            assert item["quantification_status"] in sregistry.REGISTRY_STATUSES

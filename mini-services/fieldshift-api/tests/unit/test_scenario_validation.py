"""Unit: M7.2 scenario validation engine (pure — no HTTP, no ORM)."""

from datetime import datetime, timezone

from app.scenarios import contracts as sc
from app.scenarios.validation import (
    ParentStateView,
    ScenarioView,
    validate_scenario,
)

ORG = "org-1"
TS = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _parent(**overrides):
    base = dict(
        field_id="field-1",
        organization_id=ORG,
        status="succeeded",
        checksum="c" * 64,
        boundary_version=2,
        boundary_record_exists=True,
        period_start=TS,
        period_end=datetime(2027, 12, 31, tzinfo=timezone.utc),
        timezone="Africa/Cairo",
        domain_availability={
            "environmental": {"status": "available", "reason": None, "snapshot_id": "run-1"},
            "water": {"status": "available", "reason": None, "snapshot_id": "plan-1"},
            "rotation": {"status": "missing", "reason": "not requested", "snapshot_id": None},
            "crop_history": {"status": "missing", "reason": "no rows", "snapshot_id": None},
            "soil": {"status": "not_implemented", "reason": sc.SOIL_DIMENSION_UNAVAILABLE_REASON, "snapshot_id": None},
            "management": {"status": "not_implemented", "reason": sc.MANAGEMENT_DIMENSION_UNAVAILABLE_REASON, "snapshot_id": None},
        },
        observation_count=100,
        synthetic_observation_count=0,
    )
    base.update(overrides)
    return ParentStateView(**base)


def _scenario(**overrides):
    base = dict(
        scenario_type="user_defined_stress",
        configuration={
            "type": "user_defined_stress",
            "schema_version": "scenario-config-1.0",
            "parent_field_state_id": "state-1",
            "period": {"start": "2027-01-01", "end": "2027-12-31"},
            "adjustments": {"temperature_delta_c": 2.0},
            "assumption_metadata": {"origin": "user_defined", "status": "hypothetical"},
        },
        parent_field_state_id="state-1",
        parent_snapshot_checksum="c" * 64,
        boundary_version=2,
        period_start=TS,
        period_end=datetime(2027, 12, 31, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return ScenarioView(**base)


def _codes(result):
    return [f["code"] for f in result.findings]


def _dimensions(result):
    return {d["dimension"]: d["status"] for d in result.unsupported_dimensions}


# ---------------------------------------------------------------------------
class TestParentCompatibility:
    def test_valid_scenario(self):
        result = validate_scenario(_scenario(), _parent(), requesting_organization_id=ORG)
        assert result.status == "conditionally_valid"  # rotation/crop_history missing → caveat
        assert "parent_state_cross_tenant" not in _codes(result)

    def test_missing_parent(self):
        result = validate_scenario(_scenario(), None, requesting_organization_id=ORG)
        assert result.status == "missing_reference"
        assert "parent_state_missing" in _codes(result)
        assert "parent_field_state_id" in result.missing_inputs

    def test_cross_tenant_parent_rejected(self):
        parent = _parent(organization_id="org-other")
        result = validate_scenario(_scenario(), parent, requesting_organization_id=ORG)
        assert result.status == "invalid"
        assert "parent_state_cross_tenant" in _codes(result)

    def test_checksum_mismatch_detected(self):
        scenario = _scenario(parent_snapshot_checksum="d" * 64)
        result = validate_scenario(scenario, _parent(), requesting_organization_id=ORG)
        assert result.status == "invalid"
        assert "parent_snapshot_checksum_mismatch" in _codes(result)

    def test_boundary_version_mismatch_detected(self):
        scenario = _scenario(boundary_version=7)
        result = validate_scenario(scenario, _parent(), requesting_organization_id=ORG)
        assert result.status == "invalid"
        assert "parent_boundary_version_mismatch" in _codes(result)

    def test_missing_boundary_record_insufficient_evidence(self):
        result = validate_scenario(
            _scenario(), _parent(boundary_record_exists=False), requesting_organization_id=ORG
        )
        assert result.status == "insufficient_parent_evidence"
        assert "parent_boundary_record_missing" in _codes(result)

    def test_unsucceeded_parent_rejected(self):
        result = validate_scenario(
            _scenario(), _parent(status="failed"), requesting_organization_id=ORG
        )
        assert result.status == "invalid"
        assert "parent_state_not_succeeded" in _codes(result)


# ---------------------------------------------------------------------------
class TestPeriodCompatibility:
    def test_zero_overlap_incompatible(self):
        result = validate_scenario(
            _scenario(
                period_start=datetime(2030, 1, 1, tzinfo=timezone.utc),
                period_end=datetime(2030, 12, 31, tzinfo=timezone.utc),
            ),
            _parent(),
            requesting_organization_id=ORG,
        )
        assert result.status == "incompatible_period"

    def test_partial_overlap_conditionally_valid(self):
        result = validate_scenario(
            _scenario(
                period_start=datetime(2027, 6, 1, tzinfo=timezone.utc),
                period_end=datetime(2028, 5, 31, tzinfo=timezone.utc),
            ),
            _parent(),
            requesting_organization_id=ORG,
        )
        assert result.status == "conditionally_valid"
        finding = next(f for f in result.findings if f["code"] == "scenario_period_partial_cover")
        assert 0.0 < finding["overlap_fraction"] < 1.0


# ---------------------------------------------------------------------------
class TestScenarioTypeSemantics:
    def test_observed_vs_hypothetical_distinction(self):
        observed = _scenario(
            scenario_type="historical_observed",
            configuration={
                "type": "historical_observed",
                "schema_version": "scenario-config-1.0",
                "parent_field_state_id": "state-1",
            },
        )
        result = validate_scenario(observed, _parent(), requesting_organization_id=ORG)
        assert result.status != "invalid"
        assert "observed_scenario_with_assumptions" not in _codes(result)

    def test_observed_with_hypothetical_inputs_rejected(self):
        observed = _scenario(
            scenario_type="historical_observed",
            configuration={
                "type": "historical_observed",
                "schema_version": "scenario-config-1.0",
                "parent_field_state_id": "state-1",
                "adjustments": {"temperature_delta_c": 3.0},
            },
        )
        result = validate_scenario(observed, _parent(), requesting_organization_id=ORG)
        assert result.status == "invalid"
        assert "observed_scenario_with_assumptions" in _codes(result)

    def test_unlabelled_hypothetical_rejected(self):
        scenario = _scenario(
            configuration={
                "type": "user_defined_stress",
                "schema_version": "scenario-config-1.0",
                "parent_field_state_id": "state-1",
                "period": {"start": "2027-01-01", "end": "2027-12-31"},
                "adjustments": {"temperature_delta_c": 2.0},
                "assumption_metadata": {"origin": "user_defined", "status": "forecast"},
            }
        )
        result = validate_scenario(scenario, _parent(), requesting_organization_id=ORG)
        assert result.status == "invalid"
        assert "assumption_not_labelled_hypothetical" in _codes(result)

    def test_unimplemented_types_reported(self):
        for st in ("climate_projection", "weather_forecast"):
            result = validate_scenario(
                _scenario(scenario_type=st), _parent(), requesting_organization_id=ORG
            )
            assert result.status == "not_implemented"
            assert _dimensions(result)[st] == "not_implemented"


# ---------------------------------------------------------------------------
class TestEvidenceIntegrity:
    def test_synthetic_evidence_degrades_to_conditionally_valid(self):
        result = validate_scenario(
            _scenario(), _parent(observation_count=100, synthetic_observation_count=40),
            requesting_organization_id=ORG,
        )
        assert result.status == "conditionally_valid"
        finding = next(f for f in result.findings if f["code"] == "parent_evidence_includes_synthetic")
        assert finding["synthetic_share"] == 0.4

    def test_all_synthetic_evidence_loudly_disclosed(self):
        result = validate_scenario(
            _scenario(), _parent(observation_count=100, synthetic_observation_count=100),
            requesting_organization_id=ORG,
        )
        # disclosure, not hard failure: the demo profile is synthetic by design
        assert result.status == "conditionally_valid"
        finding = next(f for f in result.findings if f["code"] == "parent_evidence_includes_synthetic")
        assert finding["all_synthetic"] is True
        assert "ALL evidence is synthetic" in finding["message"]

    def test_missing_parent_dimensions_listed(self):
        result = validate_scenario(_scenario(), _parent(), requesting_organization_id=ORG)
        dims = _dimensions(result)
        assert dims["rotation"] == "missing"
        assert dims["crop_history"] == "missing"
        # structurally absent domains always reported (C3)
        assert dims["soil"] == "not_implemented"
        assert dims["management"] == "not_implemented"
        assert dims["climate_projection"] == "not_implemented"
        assert dims["weather_forecast"] == "not_implemented"


# ---------------------------------------------------------------------------
class TestResultDocument:
    def test_document_carries_rule_version(self):
        result = validate_scenario(_scenario(), _parent(), requesting_organization_id=ORG)
        doc = result.to_document()
        assert doc["validation_rule_version"] == sc.SCENARIO_VALIDATION_RULES_VERSION
        assert doc["status"] == result.status
        assert isinstance(doc["findings"], list)
        assert isinstance(doc["missing_inputs"], list)
        assert isinstance(doc["unsupported_dimensions"], list)

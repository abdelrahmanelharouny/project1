"""Scenario validation engine (Milestone 7.2 — pure, I/O-free).

This module is deliberately independent of HTTP and ORM (M7.2 spec §8): it
consumes plain dataclass views and returns a plain result document. The API
service layer is responsible for building the views from tenant-scoped
database reads and for persisting the immutable result.

It answers ONE question — *is this scenario definition well-posed against
its parent Field State?* — and explicitly does NOT answer whether the
scenario has been executed (nothing executes in M7.2), whether any
simulation output exists, or whether the environment will behave as
configured.

Result vocabulary (spec §8): valid, invalid, conditionally_valid,
unsupported, not_implemented, missing_reference, incompatible_period,
insufficient_parent_evidence.

Severity ladder inside ``findings``:

- ``error``       — definition is not usable as posed (drives invalid/*)
- ``warning``     — usable, but a material caveat exists (drives
                    conditionally_valid)
- ``info``        — recorded limitation that does not change the verdict
                    (e.g. structurally unavailable soil/management domains)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.scenarios import contracts as sc


@dataclass
class ParentStateView:
    """The subset of a Field State a scenario validation may look at."""

    field_id: str
    organization_id: str
    status: str
    checksum: str | None
    boundary_version: int
    boundary_record_exists: bool
    period_start: datetime
    period_end: datetime
    timezone: str
    domain_availability: dict[str, Any]
    observation_count: int
    synthetic_observation_count: int


@dataclass
class ScenarioView:
    """The subset of a scenario definition the engine may look at."""

    scenario_type: str
    configuration: dict[str, Any]
    parent_field_state_id: str
    parent_snapshot_checksum: str
    boundary_version: int
    period_start: datetime
    period_end: datetime


@dataclass
class ValidationResult:
    status: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    unsupported_dimensions: list[dict[str, Any]] = field(default_factory=list)

    def to_document(self) -> dict[str, Any]:
        return {
            "validation_rule_version": sc.SCENARIO_VALIDATION_RULES_VERSION,
            "status": self.status,
            "findings": self.findings,
            "missing_inputs": self.missing_inputs,
            "unsupported_dimensions": self.unsupported_dimensions,
        }


def _finding(code: str, severity: str, message: str, **detail: Any) -> dict[str, Any]:
    entry = {"code": code, "severity": severity, "message": message}
    entry.update(detail)
    return entry


def _overlap_fraction(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    if overlap_end < overlap_start:
        return 0.0
    span = (a_end - a_start).total_seconds()
    if span <= 0:
        return 1.0
    return round(min(1.0, (overlap_end - overlap_start).total_seconds() / span), 6)


def validate_scenario(
    scenario: ScenarioView,
    parent: ParentStateView | None,
    *,
    requesting_organization_id: str,
) -> ValidationResult:
    """Validate a scenario definition against its (resolved) parent state.

    The verdict NEVER implies execution, simulated outputs, or predictive
    capability — it is a statement about the definition's integrity only.
    """
    result = ValidationResult(status="valid")

    # -- parent reference exists -------------------------------------------
    if parent is None:
        result.status = "missing_reference"
        result.findings.append(
            _finding(
                "parent_state_missing",
                "error",
                "The referenced parent Field State does not exist.",
            )
        )
        result.missing_inputs.append("parent_field_state_id")
        return result

    # -- tenant boundary (defense in depth; the API resolves this too) ------
    if parent.organization_id != str(requesting_organization_id):
        result.status = "invalid"
        result.findings.append(
            _finding(
                "parent_state_cross_tenant",
                "error",
                "The parent Field State belongs to another organization.",
            )
        )
        return result

    # -- scenario type capability -------------------------------------------
    capability = sc.SCENARIO_TYPE_CAPABILITIES.get(scenario.scenario_type)
    if capability is None or capability.capability != sc.CapabilityStatus.IMPLEMENTED:
        result.status = "not_implemented"
        result.unsupported_dimensions.append(
            {
                "dimension": scenario.scenario_type,
                "status": "not_implemented",
                "reason": (
                    capability.unavailable_reason
                    if capability is not None
                    else "Unknown scenario type."
                ),
            }
        )
        return result

    # -- parent state integrity (by-value pins must match the parent row) ---
    if parent.status != "succeeded":
        result.status = "invalid"
        result.findings.append(
            _finding(
                "parent_state_not_succeeded",
                "error",
                f"The parent Field State status is '{parent.status}', not 'succeeded'.",
            )
        )
    if parent.checksum is None:
        result.status = "invalid"
        result.findings.append(
            _finding(
                "parent_state_checksum_missing",
                "error",
                "The parent Field State has no checksum; it cannot be verified.",
            )
        )
        result.missing_inputs.append("parent_snapshot_checksum")
    elif scenario.parent_snapshot_checksum != parent.checksum:
        result.status = "invalid"
        result.findings.append(
            _finding(
                "parent_snapshot_checksum_mismatch",
                "error",
                "The scenario's pinned parent checksum does not match the parent Field State.",
                expected=parent.checksum,
                actual=scenario.parent_snapshot_checksum,
            )
        )
    if scenario.boundary_version != parent.boundary_version:
        result.status = "invalid"
        result.findings.append(
            _finding(
                "parent_boundary_version_mismatch",
                "error",
                "The scenario's pinned boundary version does not match the parent Field State.",
                expected=parent.boundary_version,
                actual=scenario.boundary_version,
            )
        )

    # -- boundary record exists (H-01 continuity) ----------------------------
    if not parent.boundary_record_exists:
        if result.status == "valid":
            result.status = "insufficient_parent_evidence"
        result.findings.append(
            _finding(
                "parent_boundary_record_missing",
                "error",
                "No boundary-history record exists for the parent state's "
                "boundary version; the spatial reference cannot be verified.",
            )
        )
        result.missing_inputs.append("parent_boundary_record")

    # -- temporal compatibility ----------------------------------------------
    overlap = _overlap_fraction(
        scenario.period_start, scenario.period_end, parent.period_start, parent.period_end
    )
    if overlap <= 0.0:
        result.status = "incompatible_period"
        result.findings.append(
            _finding(
                "scenario_period_outside_parent",
                "error",
                "The scenario period does not overlap the parent Field State "
                "period; incompatible time windows are never merged.",
                overlap_fraction=0.0,
            )
        )
    elif overlap < 1.0:
        if result.status == "valid":
            result.status = "conditionally_valid"
        result.findings.append(
            _finding(
                "scenario_period_partial_cover",
                "warning",
                "The scenario period only partially overlaps the parent Field "
                "State period; hypothetical adjustments outside the covered "
                "window cannot be grounded in the parent evidence.",
                overlap_fraction=overlap,
            )
        )

    # -- hypothetical inputs must be labelled hypothetical --------------------
    config = scenario.configuration or {}
    if scenario.scenario_type in (
        sc.ScenarioType.HISTORICAL_PERTURBATION.value,
        sc.ScenarioType.USER_DEFINED_STRESS.value,
    ):
        metadata = config.get("assumption_metadata") or {}
        if metadata.get("status") != "hypothetical":
            result.status = "invalid"
            result.findings.append(
                _finding(
                    "assumption_not_labelled_hypothetical",
                    "error",
                    "Hypothetical scenario inputs must carry "
                    "assumption_metadata.status = 'hypothetical'.",
                )
            )
    elif scenario.scenario_type == sc.ScenarioType.HISTORICAL_OBSERVED.value:
        if config.get("adjustments") is not None or config.get("assumption_metadata") is not None:
            result.status = "invalid"
            result.findings.append(
                _finding(
                    "observed_scenario_with_assumptions",
                    "error",
                    "A historical observed scenario is a labelled reference and "
                    "cannot carry hypothetical adjustments.",
                )
            )

    # -- parent evidence: real vs synthetic -----------------------------------
    # Synthetic evidence is DISCLOSED, never silently mixed: partial shares
    # degrade the verdict to conditionally_valid with a warning; an entirely
    # synthetic parent stays conditionally_valid but with a prominent,
    # explicit finding (synthetic data remains visibly synthetic — M7.0 rule;
    # the platform's demo profile is synthetic by design, so this must be a
    # disclosure, not a hard failure).
    if parent.observation_count > 0 and parent.synthetic_observation_count > 0:
        share = round(parent.synthetic_observation_count / parent.observation_count, 6)
        if result.status == "valid":
            result.status = "conditionally_valid"
        result.findings.append(
            _finding(
                "parent_evidence_includes_synthetic",
                "warning",
                (
                    "The parent Field State's environmental evidence includes "
                    f"synthetic observations ({parent.synthetic_observation_count} of "
                    f"{parent.observation_count}"
                    + (
                        " — ALL evidence is synthetic"
                        if share >= 1.0
                        else ""
                    )
                    + "); synthetic data remains visibly synthetic and never "
                    "counts as measured evidence."
                ),
                synthetic_share=share,
                all_synthetic=share >= 1.0,
            )
        )

    # -- structural evidence gaps in the parent state -------------------------
    implemented_dimensions = ("environmental", "water", "rotation", "crop_history")
    for dimension in implemented_dimensions:
        entry = (parent.domain_availability or {}).get(dimension) or {}
        status = entry.get("status")
        if status in (None, "available"):
            continue
        if result.status == "valid":
            result.status = "conditionally_valid"
        if status in ("not_implemented", "not_evaluated"):
            severity = "info"
        else:  # missing / period_mismatch
            severity = "warning"
        result.unsupported_dimensions.append(
            {
                "dimension": dimension,
                "status": status,
                "reason": entry.get("reason"),
            }
        )
        result.findings.append(
            _finding(
                f"parent_dimension_{status}",
                severity,
                f"Parent Field State dimension '{dimension}' is '{status}'; "
                "the scenario inherits this limitation.",
                dimension=dimension,
            )
        )

    # -- structurally unavailable domains (always reported — C3) --------------
    for dimension, entry in sc.SCENARIO_DIMENSION_AVAILABILITY.items():
        result.unsupported_dimensions.append(dict(entry, dimension=dimension))
    result.findings.append(
        _finding(
            "unavailable_domains_recorded",
            "info",
            "Soil, management, climate projection and weather forecast "
            "dimensions are unavailable in this repository and are reported "
            "as such — they are never fabricated.",
        )
    )

    return result

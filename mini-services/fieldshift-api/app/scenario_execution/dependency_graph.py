"""Feature dependency registry (Milestone 7.3).

Derives, from the versioned M4 feature catalog, how every feature relates to
the supported M7.3 transformations. NO formulas live here — the catalog
(`app/features/catalog.py`) remains the single source of scientific truth.

Roles:

- ``recalculate``  — every required variable is transformed by the configured
                     transformations; the feature is recomputed from the
                     transformed observation set by the existing M4 engine.
- ``exclude_et0``  — requires observed reference ET0; baseline ET0 is never
                     valid as a scenario-derived value and M7.3 does not
                     recalculate evaporative demand → not_evaluated.
- ``not_affected`` — required variables untouched by the configured
                     transformations → not computed, reported with a reason.
- ``exclude_mixed_inputs`` — requires both transformed and untouched,
                     non-ET0 variables (incoherent to recompute) →
                     not_evaluated. Fail-closed for future catalog entries.
"""

from dataclasses import dataclass
from typing import Any

from app.features.catalog import FEATURE_CATALOG, FEATURE_CATALOG_VERSION, FeatureSpec
from app.scenario_execution.transformations import (
    PRECIPITATION_VARIABLES,
    TEMPERATURE_VARIABLES,
)

TEMPERATURE_VARIABLE_SET = frozenset(TEMPERATURE_VARIABLES)
PRECIPITATION_VARIABLE_SET = frozenset(PRECIPITATION_VARIABLES)
ET0_VARIABLES = frozenset({"reference_et0"})

ET0_NOT_EVALUATED_REASON = (
    "Reference ET0 is an observed input (FAO-56 reference surface published by the "
    "source product). M7.3 does not recalculate evaporative demand under modified "
    "temperature — a defensible method would require humidity, radiation and wind "
    "scenario inputs that a temperature delta does not define. Baseline ET0 is never "
    "reused as scenario-derived ET0."
)

NOT_AFFECTED_REASON_TEMPLATE = (
    "Source variable(s) {variables} are not affected by the configured "
    "transformations; the feature is reported unchanged-basis, not recomputed "
    "and not fabricated."
)

MIXED_INPUTS_REASON = (
    "Feature requires both transformed and untouched non-ET0 variables; "
    "recomputation from half-transformed inputs is refused (fail-closed)."
)


@dataclass(frozen=True)
class FeatureDependency:
    feature_code: str
    required_variables: tuple[str, ...]
    aggregation_levels: tuple[str, ...]
    temperature_sensitive: bool
    precipitation_sensitive: bool
    et0_dependent: bool
    multi_variable: bool
    required_time_support: str  # every M4 strategy consumes daily series
    specification_version: str


def _dependency_for(spec: FeatureSpec) -> FeatureDependency:
    return FeatureDependency(
        feature_code=spec.feature_code,
        required_variables=tuple(spec.required_variables),
        aggregation_levels=tuple(spec.aggregation_levels),
        temperature_sensitive=any(v in TEMPERATURE_VARIABLE_SET for v in spec.required_variables),
        precipitation_sensitive=any(v in PRECIPITATION_VARIABLE_SET for v in spec.required_variables),
        et0_dependent=any(v in ET0_VARIABLES for v in spec.required_variables),
        multi_variable=len(spec.required_variables) > 1,
        required_time_support="daily",
        specification_version=FEATURE_CATALOG_VERSION,
    )


FEATURE_DEPENDENCIES: dict[str, FeatureDependency] = {
    code: _dependency_for(spec) for code, spec in FEATURE_CATALOG.items()
}


def execution_role(
    dep: FeatureDependency,
    *,
    delta_c: float | None,
    multiplier: float | None,
) -> tuple[str, str]:
    """Classify one feature for one execution's configured transformations.

    Returns (role, reason). Role ∈ {recalculate, exclude_et0, not_affected,
    exclude_mixed_inputs}.
    """
    transformed_vars: set[str] = set()
    if delta_c is not None:
        transformed_vars |= TEMPERATURE_VARIABLE_SET
    if multiplier is not None:
        transformed_vars |= PRECIPITATION_VARIABLE_SET

    if dep.et0_dependent:
        return "exclude_et0", ET0_NOT_EVALUATED_REASON

    required = set(dep.required_variables)
    touched = required & transformed_vars
    untouched = required - transformed_vars
    if not touched:
        return "not_affected", NOT_AFFECTED_REASON_TEMPLATE.format(
            variables=", ".join(sorted(required))
        )
    if untouched:
        return "exclude_mixed_inputs", MIXED_INPUTS_REASON
    return "recalculate", ""


def plan_scenario_features(
    *,
    delta_c: float | None,
    multiplier: float | None,
) -> dict[str, dict[str, Any]]:
    """Full classification plan for one execution.

    Returns {feature_code: {role, reason, specification_version, ...}} for
    every catalog feature. Deterministic ordering: sorted codes.
    """
    plan: dict[str, dict[str, Any]] = {}
    for code in sorted(FEATURE_DEPENDENCIES):
        dep = FEATURE_DEPENDENCIES[code]
        role, reason = execution_role(dep, delta_c=delta_c, multiplier=multiplier)
        plan[code] = {
            "feature_code": code,
            "role": role,
            "reason": reason or None,
            "required_variables": list(dep.required_variables),
            "aggregation_levels": list(dep.aggregation_levels),
            "required_time_support": dep.required_time_support,
            "specification_version": dep.specification_version,
        }
    return plan


def recalculate_specs(
    *,
    delta_c: float | None,
    multiplier: float | None,
) -> list[FeatureSpec]:
    """Catalog specs whose required variables are fully transformed — the set
    handed to the M4 engine for the scenario pass."""
    return [
        FEATURE_CATALOG[code]
        for code in sorted(FEATURE_DEPENDENCIES)
        if execution_role(FEATURE_DEPENDENCIES[code], delta_c=delta_c, multiplier=multiplier)[0]
        == "recalculate"
    ]

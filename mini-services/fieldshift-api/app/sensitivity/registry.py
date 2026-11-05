"""Uncertainty & limitation registry (Milestone 7.4).

Builds the per-analysis uncertainty registry defined by
docs/m7/m7_4/M7_4_UNCERTAINTY_REGISTRY.md (registry version
`sensitivity-uncertainty-registry-1.0`).

Rules:

- Categories and statuses are stable vocabularies; no composite uncertainty
  score exists and no numeric confidence is invented.
- Static items carry dynamic evidence bound to the actual analysis (affected
  features, coverage statistics, reference tuples).
- Items that have no meaning for a given analysis shape (grid items without a
  grid) are omitted rather than faked.
"""

from typing import Any

from app.sensitivity import contracts as sc
from app.sensitivity.math import classify_response  # noqa: F401  (re-exported for tests)

REGISTRY_VERSION = sc.UNCERTAINTY_REGISTRY_VERSION

CATEGORY_PARAMETER_RANGE = "parameter_range_uncertainty"
CATEGORY_OBSERVATION_QUALITY = "observation_data_quality"
CATEGORY_SPATIAL = "spatial_coverage_limitation"
CATEGORY_TEMPORAL = "temporal_resolution_limitation"
CATEGORY_MODEL_STRUCTURAL = "model_structural_limitation"
CATEGORY_FEATURE_METHOD = "feature_method_limitation"
CATEGORY_REGIONAL = "regional_agronomic_uncertainty"

REGISTRY_CATEGORIES = (
    CATEGORY_PARAMETER_RANGE,
    CATEGORY_OBSERVATION_QUALITY,
    CATEGORY_SPATIAL,
    CATEGORY_TEMPORAL,
    CATEGORY_MODEL_STRUCTURAL,
    CATEGORY_FEATURE_METHOD,
    CATEGORY_REGIONAL,
)

STATUS_QUANTIFIED = "quantified"
STATUS_BOUNDED_EXPLORATORY = "bounded_exploratory"
STATUS_QUALITATIVE_ONLY = "qualitative_only"
STATUS_NOT_QUANTIFIED = "not_quantified"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_NOT_EVALUATED = "not_evaluated"

REGISTRY_STATUSES = (
    STATUS_QUANTIFIED,
    STATUS_BOUNDED_EXPLORATORY,
    STATUS_QUALITATIVE_ONLY,
    STATUS_NOT_QUANTIFIED,
    STATUS_NOT_APPLICABLE,
    STATUS_NOT_EVALUATED,
)

APPLICABILITY_DIRECT = "direct"
APPLICABILITY_CONTEXTUAL = "contextual"
APPLICABILITY_PERIPHERAL = "peripheral"


def _item(
    *,
    category: str,
    code: str,
    description: str,
    evidence_source: str,
    quantification_status: str,
    quantification_method: str | None,
    quantified_value: dict[str, Any] | None,
    affects: bool,
    affected_inputs: list[str],
    affected_features: list[str],
    applicability: str,
    explanation: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "code": code,
        "description": description,
        "evidence_source": evidence_source,
        "quantification_status": quantification_status,
        "quantification_method": quantification_method,
        "quantified_value": quantified_value,
        "affects_current_analysis": affects,
        "affected_inputs": affected_inputs,
        "affected_features": affected_features,
        "applicability": applicability,
        "user_facing_explanation": explanation,
        "registry_version": REGISTRY_VERSION,
    }


def build_registry(
    *,
    explorable_parameters: list[str],
    reference_values: dict[str, float],
    parameter_design: dict[str, Any],
    grid_requested: bool,
    temperature_features: list[str],
    precipitation_features: list[str],
    et0_features: list[str],
    coverage_stats: dict[str, Any] | None,
    has_synthetic: bool,
) -> list[dict[str, Any]]:
    """Materialise the registry for ONE analysis with dynamic evidence."""
    items: list[dict[str, Any]] = []

    param_labels = {
        sc.SensitivityParameter.TEMPERATURE_DELTA_C.value: "temperature shift ΔT (°C)",
        sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value: "precipitation multiplier M_p",
    }
    explorable_labels = [param_labels[p] for p in explorable_parameters]

    # -- parameter range ---------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_PARAMETER_RANGE,
            code="parameter_range_bounds",
            description=(
                "User-supplied parameter bounds define the explored range; the "
                "evaluated min/max (the explored parameter-range envelope) has "
                "no probability meaning."
            ),
            evidence_source="user_analysis_definition",
            quantification_status=STATUS_BOUNDED_EXPLORATORY,
            quantification_method=(
                "deterministic evaluation of the scenario engine over the "
                "declared parameter grid"
            ),
            quantified_value={"explored": parameter_design},
            affects=True,
            affected_inputs=list(explorable_parameters),
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "The bounds you entered are assumptions for a deterministic "
                "experiment. The resulting envelope shows the minimum and "
                "maximum output across the evaluated parameter values — it is "
                "not a confidence or probability interval and does not imply "
                "that real temperature or precipitation uncertainty follows "
                "any distribution."
            ),
        )
    )
    items.append(
        _item(
            category=CATEGORY_PARAMETER_RANGE,
            code="parameter_reference_value",
            description=(
                "Reference parameter values come from the source scenario "
                "execution and were reproduced exactly before analysis."
            ),
            evidence_source="source_execution_run.execution_configuration",
            quantification_status=STATUS_QUANTIFIED,
            quantification_method="exact deterministic reproduction of the source pass",
            quantified_value={"reference_values": reference_values},
            affects=True,
            affected_inputs=list(explorable_parameters),
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "Every response in this analysis is measured relative to the "
                "source execution's own parameter values, which the analysis "
                "reproduced exactly before comparing anything."
            ),
        )
    )

    # -- observation data quality ------------------------------------------
    items.append(
        _item(
            category=CATEGORY_OBSERVATION_QUALITY,
            code="source_measurement_error",
            description=(
                "Source datasets carry no machine-readable measurement-error "
                "distributions in this repository; their uncertainty is "
                "unquantified here and is NOT invented."
            ),
            evidence_source="source_run.scenario_derived_features.uncertainty_metadata",
            quantification_status=STATUS_NOT_QUANTIFIED,
            quantification_method=None,
            quantified_value=None,
            affects=True,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "No defensible measurement-error numbers exist for the source "
                "observations, so no error bars can be attached to any "
                "response. Absent error bars mean 'not quantified', not 'zero "
                "uncertainty'."
            ),
        )
    )
    if coverage_stats is not None:
        items.append(
            _item(
                category=CATEGORY_OBSERVATION_QUALITY,
                code="missing_data_coverage",
                description=(
                    "Data completeness of the analysed window is inherited from "
                    "the source execution's recalculated feature rows."
                ),
                evidence_source="source_run.scenario_derived_features.coverage_ratio",
                quantification_status=STATUS_QUANTIFIED,
                quantification_method="descriptive coverage statistics (a data-quality descriptor, not an error distribution)",
                quantified_value=coverage_stats,
                affects=True,
                affected_inputs=[],
                affected_features=[],
                applicability=APPLICABILITY_DIRECT,
                explanation=(
                    "Coverage statistics describe how much of the analysed "
                    "window had usable source data. They are data-quality "
                    "descriptors — they are not measurement-error bars."
                ),
            )
        )
    else:
        items.append(
            _item(
                category=CATEGORY_OBSERVATION_QUALITY,
                code="missing_data_coverage",
                description=(
                    "No recalculated coverage statistics were available from "
                    "the source run for this analysis."
                ),
                evidence_source="source_run.scenario_derived_features",
                quantification_status=STATUS_NOT_EVALUATED,
                quantification_method=None,
                quantified_value=None,
                affects=False,
                affected_inputs=[],
                affected_features=[],
                applicability=APPLICABILITY_PERIPHERAL,
                explanation="Coverage could not be assessed because the source run exposed no statistics.",
            )
        )
    if has_synthetic:
        items.append(
            _item(
                category=CATEGORY_OBSERVATION_QUALITY,
                code="synthetic_source_values",
                description=(
                    "Part of the source execution derives from synthetic "
                    "fixture data; sensitivity results inherit that label."
                ),
                evidence_source="source_run.warnings / derived observations is_synthetic",
                quantification_status=STATUS_QUALITATIVE_ONLY,
                quantification_method=None,
                quantified_value=None,
                affects=True,
                affected_inputs=[],
                affected_features=[],
                applicability=APPLICABILITY_DIRECT,
                explanation=(
                    "Some source values are synthetic and always labelled as "
                    "such; every number derived from them is for demonstration "
                    "and testing only."
                ),
            )
        )

    # -- spatial ------------------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_SPATIAL,
            code="single_field_support",
            description=(
                "Observations are pinned to one field's boundary version by "
                "the parent Field State manifest; no spatial "
                "representativeness error is quantified."
            ),
            evidence_source="parent_field_state.observation_manifest",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=False,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_CONTEXTUAL,
            explanation=(
                "The analysis speaks for this field's pinned observation set "
                "only. How representative those observations are of the "
                "surrounding area is not quantified."
            ),
        )
    )

    # -- temporal -----------------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_TEMPORAL,
            code="daily_first_engine",
            description=(
                "The M4 feature engine is daily-first; features over non-daily "
                "source aggregation are outside this analysis (M7.3 engine "
                "limitation, disclosed)."
            ),
            evidence_source="engine_design (M7_3_LIMITATIONS_AND_BACKLOG §3)",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=False,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_CONTEXTUAL,
            explanation=(
                "Only features computed from daily observations are analysed; "
                "aggregated-source features were already excluded by the "
                "source execution and are not analysed here."
            ),
        )
    )
    items.append(
        _item(
            category=CATEGORY_TEMPORAL,
            code="transformation_preserves_timing",
            description=(
                "The precipitation multiplier preserves event occurrence and "
                "timing; the temperature shift preserves diurnal structure. "
                "Changed storm timing, dry-spell sequence changes and "
                "seasonality shifts are NOT representable and NOT analysed."
            ),
            evidence_source="M7_3_TRANSFORMATION_METHODOLOGY §4",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=True,
            affected_inputs=[sc.SensitivityParameter.PRECIPITATION_MULTIPLIER.value],
            affected_features=list(precipitation_features),
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "A fixed multiplier changes how much falls on days that "
                "already had rain; it cannot move rain to dry days or change "
                "when storms happen. Responses of precipitation features must "
                "be read with that limitation."
            ),
        )
    )

    # -- model structural ----------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_MODEL_STRUCTURAL,
            code="uniform_delta_t",
            description=(
                "A uniform additive ΔT preserves baseline variance and diurnal "
                "temperature range; asymmetric warming and changed extremes "
                "structure are not representable."
            ),
            evidence_source="M7_3_TRANSFORMATION_METHODOLOGY §4",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=True,
            affected_inputs=[sc.SensitivityParameter.TEMPERATURE_DELTA_C.value],
            affected_features=list(temperature_features),
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "The scenario warms every day by the same amount. It cannot "
                "warm nights more than days or change how variable the "
                "weather is — responses tied to variability are outside this "
                "analysis."
            ),
        )
    )
    if et0_features:
        items.append(
            _item(
                category=CATEGORY_MODEL_STRUCTURAL,
                code="no_et0_recalculation",
                description=(
                    "ET0-dependent features were not recalculated by the "
                    "source execution (M7.3 discipline) and have no "
                    "scenario-derived values to analyse."
                ),
                evidence_source="source_run.not_evaluated_reasons",
                quantification_status=STATUS_NOT_APPLICABLE,
                quantification_method=None,
                quantified_value=None,
                affects=False,
                affected_inputs=[],
                affected_features=list(et0_features),
                applicability=APPLICABILITY_CONTEXTUAL,
                explanation=(
                    "Reference evapotranspiration was deliberately excluded "
                    "from scenario recalculation, so it has no scenario "
                    "values whose sensitivity could be analysed."
                ),
            )
        )
    items.append(
        _item(
            category=CATEGORY_MODEL_STRUCTURAL,
            code="hypothetical_not_predictive",
            description=(
                "Every analysed value is a deterministic hypothetical "
                "transformation; nothing predicts yield, productivity, "
                "irrigation outcomes or rainfall probability."
            ),
            evidence_source="M7.4 method (binding scope)",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=True,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "Sensitivity results describe the arithmetic of the scenario "
                "engine, not the future. No crop, yield or water-supply "
                "prediction is made anywhere in this analysis."
            ),
        )
    )

    # -- feature method -------------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_FEATURE_METHOD,
            code="feature_engine_assumptions",
            description=(
                "Responses inherit the M4 feature-engine assumptions; catalog "
                "thresholds (e.g. 35 °C hot day, dry-spell definitions) are "
                "fixed constants that do not vary with the scenario."
            ),
            evidence_source="app.features.catalog (versioned)",
            quantification_status=STATUS_QUALITATIVE_ONLY,
            quantification_method=None,
            quantified_value=None,
            affects=True,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "Threshold-based features jump when a scenario value crosses "
                "their fixed definition (for example a 35 °C hot day). The "
                "analysis detects and labels such steps instead of hiding "
                "them behind an average slope."
            ),
        )
    )
    items.append(
        _item(
            category=CATEGORY_FEATURE_METHOD,
            code="classification_tolerance",
            description=(
                "Response classes use the documented, versioned rubric "
                f" {sc.RESPONSE_CLASSIFICATION_VERSION} (equality tolerance "
                f"{sc.EQUALITY_TOL:g}; constant band "
                f"{sc.CONSTANT_BAND_RELATIVE:.1%} of the reference; threshold "
                f"jump factor ×{sc.THRESHOLD_JUMP_FACTOR:g})."
            ),
            evidence_source="app.sensitivity.contracts (versioned rubric)",
            quantification_status=STATUS_QUANTIFIED,
            quantification_method="documented classification tolerances applied to evaluated values",
            quantified_value={
                "equality_tolerance": sc.EQUALITY_TOL,
                "constant_band_relative": sc.CONSTANT_BAND_RELATIVE,
                "threshold_jump_factor": sc.THRESHOLD_JUMP_FACTOR,
                "classification_version": sc.RESPONSE_CLASSIFICATION_VERSION,
            },
            affects=True,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_DIRECT,
            explanation=(
                "Words like 'monotonic' or 'threshold' on a response are "
                "produced by a published, versioned rubric over the actual "
                "numbers — they are never informal judgements."
            ),
        )
    )

    # -- regional agronomic ----------------------------------------------------
    items.append(
        _item(
            category=CATEGORY_REGIONAL,
            code="no_local_validation",
            description=(
                "No validation against local agronomic evidence exists for "
                "these scenario calculations in this repository; regional "
                "applicability is unquantified."
            ),
            evidence_source="repository_evidence_state",
            quantification_status=STATUS_NOT_QUANTIFIED,
            quantification_method=None,
            quantified_value=None,
            affects=False,
            affected_inputs=[],
            affected_features=[],
            applicability=APPLICABILITY_CONTEXTUAL,
            explanation=(
                "Nothing in this platform has been validated against local "
                "field trials; treat every result as an engine property, not "
                "an agronomic recommendation."
            ),
        )
    )

    return items

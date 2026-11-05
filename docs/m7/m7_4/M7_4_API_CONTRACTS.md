# M7.4 — API Contracts

Base path: `/api/v1` (FastAPI router `sensitivity.py`, tag `sensitivity`).
All endpoints are tenant-scoped through the analysis/run's field → farm;
ownership claims from the client are never trusted (M7.3 idiom). Every
response that shows numbers carries honesty notes; envelope fields use the
binding name `explored_parameter_range_envelope`.

---

## 1. Create an analysis

```
POST /scenario-executions/{run_id}/sensitivity-analyses
{
  "parameter_design": {
    "temperature_delta_c":      {"lower": -2.0, "upper": 6.0, "n_points": 9},
    "precipitation_multiplier": {"lower": 0.5,  "upper": 1.5, "n_points": 9}
  },
  "grid": true | false | {same per-parameter design},   # optional joint grid
  "idempotency_key": "optional-string"
}
```

- 200 → the analysis payload (§1.1) in its final status (synchronous execution,
  like M7.3).
- 404 unknown run / wrong tenant; 409 `RUN_NOT_RESULT_BEARING`,
  `SCENARIO_NOT_FINALIZED`, `*_CHECKSUM_MISMATCH`, `RUN_VERIFICATION_FAILED`;
  422 `NO_EXPLORABLE_PARAMETERS`, design validation failures (structured
  `details[]` with field + reason), `EVALUATION_BUDGET_EXCEEDED`.
- Replay: identical definition (same fingerprint) or same `idempotency_key`
  returns the existing analysis unchanged.

### 1.1 Analysis payload (abridged)

```jsonc
{
  "analysis_id": "…",
  "source_execution_run_id": "…",
  "scenario_id": "…", "scenario_version": 1,
  "analysis_status": "succeeded | completed_with_limitations | failed | queued | running",
  "analysis_method_version": "sensitivity-analysis-1.0.0",
  "response_classification_version": "sensitivity-response-classification-1.0",
  "uncertainty_registry_version": "sensitivity-uncertainty-registry-1.0",
  "reference_parameter_values": {"temperature_delta_c": 2.0},
  "explorable_parameters": {
     "temperature_delta_c": {"explorable": true},
     "precipitation_multiplier": {"explorable": false,
        "reason": "parameter not configured in the source execution; no reference value exists"}
  },
  "parameter_design": {…}, "grid_design": null | {…},
  "reference_reproduction": {"reproduced": true, "compared_rows": 40,
      "matched_rows": 40, "mismatched_rows": [], "observation_count_match": true},
  "evaluation_count": 9, "evaluated_feature_count": 120,
  "not_analysed_features": {"reference_et0_total_monthly": "…reason…"},
  "warnings": ["…disclosures…"],
  "output_checksum": "…", "input_fingerprint": "…",
  "started_at": "…", "completed_at": "…",
  "evidence_note": "Sensitivity results analyse hypothetical scenario-derived features …"
}
```

## 2. List analyses for a run

```
GET /scenario-executions/{run_id}/sensitivity-analyses
→ {"run_id": "…", "items": [analysis payload…], "count": n}
```

## 3. Analysis detail

```
GET /sensitivity-analyses/{analysis_id}          → payload §1.1
```

## 4. Evaluation points

```
GET /sensitivity-analyses/{analysis_id}/evaluations
→ {"analysis_id": "…", "items": [{
     "evaluation_id": "…", "evaluation_kind": "reference|oat|grid",
     "is_reference": true, "roles": ["reference","oat","grid"],
     "parameter_values": {"temperature_delta_c": 0.0, "precipitation_multiplier": 1.0},
     "evaluation_status": "succeeded",
     "transformed_observation_count": 1456, "derived_feature_count": 40}], "count": n}
```

## 5. OAT responses

```
GET /sensitivity-analyses/{analysis_id}/responses
    ?parameter_code=temperature_delta_c&feature_code=…&aggregation_level=monthly
→ {"analysis_id": "…", "items": [{
     "parameter_code": "temperature_delta_c",
     "feature_code": "air_temperature_mean_monthly",
     "unit": "degC", "aggregation_level": "monthly", "period_label": "2023-01",
     "reference_value": 9.8063,
     "explored_parameter_range_envelope": {
        "parameter_lower": -2.0, "parameter_upper": 6.0,
        "lower": 7.8063, "upper": 13.8063},
     "output_range": 6.0, "max_abs_difference": 4.0,
     "difference_at_lower": -2.0, "difference_at_upper": 4.0,
     "slope": 1.0, "slope_method": "central", "slope_units": "degC / degC",
     "slope_validity": "valid",
     "elasticity": {"value": 0.2039, "status": "available"} |
                   {"status": "unavailable", "reason": "reference_value_is_zero"},
     "direction": "increasing", "response_classification": "monotonic_increasing",
     "classification_version": "sensitivity-response-classification-1.0",
     "n_evaluated_points": 9, "response_status": "evaluated"}], "count": n}
```

## 6. Joint grid

```
GET /sensitivity-analyses/{analysis_id}/grid?feature_code=…
→ {"analysis_id": "…", "grid_design": {…} | null,
   "axes": {"temperature_delta_c": [x0, x1, …], "precipitation_multiplier": [z0, …]},
   "cells": [{"feature_code": "…", "aggregation_level": "…", "period_label": "…",
              "temperature_delta_c": x, "precipitation_multiplier": z,
              "cell_value": v}, …],
   "summaries": [{"feature_code": "…", "grid_min": v, "grid_max": v,
                  "grid_output_range": v, "direction": "…", "non_monotonic": false,
                  "threshold_transition_count": 0,
                  "interaction_contrast": 0.0,
                  "interaction_interpretation": "approximately_additive",
                  "variable_families": ["temperature"]}], "count": n}
```

When no grid was requested: `{"grid_design": null, "cells": [], "summaries": [],
"note": "No joint parameter grid was requested for this analysis."}`

## 7. Uncertainty registry

```
GET /sensitivity-analyses/{analysis_id}/uncertainty
→ {"analysis_id": "…", "registry_version": "sensitivity-uncertainty-registry-1.0",
   "items": [{"category": "parameter_range_uncertainty", "code": "parameter_range_bounds",
              "quantification_status": "bounded_exploratory", …,
              "user_facing_explanation": "…"}],
   "count": n,
   "note": "The registry distinguishes uncertainty types; no composite score exists."}
```

## 8. Verify

```
POST /sensitivity-analyses/{analysis_id}/verify
→ {"analysis_id": "…", "analysis_status": "…",
   "output_checksum_valid": true, "expected_output_checksum": "…",
   "stored_output_checksum": "…",
   "source_run_intact": true, "parent_snapshot_intact": true,
   "manifest_checksum_matches": true,
   "reference_reproduction_consistent": true,
   "verified_at": "…",
   "note": "…integrity verification of a hypothetical analysis…"}
```

---

## Error discipline

- 422 bodies always carry `details[]` entries `{field, reason}` exactly like
  M7.2/M7.3.
- No endpoint mutates a result-bearing analysis (trigger + application).
- No endpoint exposes forecast/projection language anywhere; capability
  honesty follows the M7.2 `capabilities` pattern — M7.4 capabilities are
  disclosed statically inside the analysis payload (`analysis_method_version`,
  disclosures) and in the UI.

# M7.4 — Uncertainty & Limitation Registry

**Registry version:** `sensitivity-uncertainty-registry-1.0` (constant
`UNCERTAINTY_REGISTRY_VERSION`)

Every M7.4 analysis materialises one registry: a structured list of
uncertainty sources and limitations attached to that analysis. The registry
**distinguishes fundamentally different uncertainty types and never merges
them into a composite score.** No numeric confidence values are invented.

---

## 1. Item schema

| Field | Meaning |
|---|---|
| `category` | One of the seven categories below (stable codes) |
| `code` | Stable item code within the category (e.g. `parameter_range_bounds`) |
| `description` | What the uncertainty/limitation is |
| `evidence_source` | Where the knowledge comes from (e.g. `source_run.coverage_ratio`, `M7_3_TRANSFORMATION_METHODOLOGY §4`, `engine_design`) |
| `quantification_status` | `quantified` \| `bounded_exploratory` \| `qualitative_only` \| `not_quantified` \| `not_applicable` \| `not_evaluated` |
| `quantification_method` | How it is quantified, when status is `quantified`/`bounded_exploratory`; else null |
| `quantified_value` | The actual number(s) when quantification exists; else null |
| `affects_current_analysis` | bool — does it bear on THIS analysis's outputs |
| `affected_inputs` | Transformation parameters / observation variables affected |
| `affected_features` | Feature codes affected (empty list = all/none as stated in description) |
| `applicability` | Documented rubric: `direct` (changes how this analysis must be read), `contextual` (background the reader needs), `peripheral` |
| `user_facing_explanation` | One-paragraph plain-language explanation rendered in the UI |

### Applicability rubric (versioned)

- `direct` — the item changes what conclusions the reader may draw from this
  analysis's numbers (e.g. the envelope's non-probabilistic nature).
- `contextual` — the item does not change this analysis's arithmetic but the
  reader needs it to interpret results honestly (e.g. uniform-ΔT structure).
- `peripheral` — noted for completeness; no bearing here.

---

## 2. Categories and static items

### 2.1 `parameter_range_uncertainty`

| Code | Status | Content |
|---|---|---|
| `parameter_range_bounds` | `bounded_exploratory` | "Parameter bounds are user-supplied assumptions defining the explored range. The evaluated min/max (the explored parameter-range envelope) carries no probability meaning: it does not establish that real temperature or precipitation uncertainty follows any distribution." Quantification method: deterministic evaluation over the declared grid. Affects analysis: true. Applicability: `direct`. Affected inputs: the explorable parameters. |
| `parameter_reference_value` | `quantified` | "The reference parameter values come from the source scenario execution and were reproduced exactly (see `reference_reproduction`)." Quantified value: the reference tuples. Applicability: `direct`. |

### 2.2 `observation_data_quality`

| Code | Status | Content |
|---|---|---|
| `source_measurement_error` | `not_quantified` | "The source datasets carry no machine-readable measurement-error distributions in this repository. Their uncertainty is therefore unquantified here — it is NOT invented." Evidence: source run `uncertainty_metadata` (source_uncertainty present on 0 features in the general case). Affects analysis: true (all feature levels inherit it). Applicability: `direct`. |
| `missing_data_coverage` | `quantified` **when the source run exposes coverage statistics** | "Data completeness of the analysed window is inherited from the source execution." Quantification method: descriptive coverage statistics from the run's recalculated feature rows (`coverage_ratio`, `n_input`, `n_missing`). Quantified value: `{min_coverage_ratio, mean_coverage_ratio, features_with_gaps}`. NOTE: coverage is a data-quality descriptor, not an error distribution. Applicability: `direct`. When the source run has no recalculated rows → status `not_evaluated`. |
| `synthetic_source_values` | `qualitative_only` **only when the source run flagged synthetic data** | Carried from the run's warnings; synthetic values are labelled and never treated as observations. Applicability: `direct` when present; item omitted otherwise. |

### 2.3 `spatial_coverage_limitation`

| Code | Status | Content |
|---|---|---|
| `single_field_support` | `qualitative_only` | "Observations are pinned to one field's boundary version by the parent Field State manifest. No spatial representativeness error is quantified." Applicability: `contextual`. |

### 2.4 `temporal_resolution_limitation`

| Code | Status | Content |
|---|---|---|
| `daily_first_engine` | `qualitative_only` | "The M4 engine is daily-first; non-daily source aggregation recalculation is an M7.3-disclosed engine limitation. Features over non-daily supports are outside this analysis." Applicability: `contextual`. |
| `transformation_preserves_timing` | `qualitative_only` | "The precipitation multiplier preserves event occurrence and timing; the temperature shift preserves diurnal structure. Changed storm timing, dry-spell sequence changes and seasonality shifts are NOT representable and therefore NOT analysed." Applicability: `direct` for precipitation features, `contextual` for temperature. |

### 2.5 `model_structural_limitation`

| Code | Status | Content |
|---|---|---|
| `uniform_delta_t` | `qualitative_only` | "A uniform additive ΔT preserves baseline variance and diurnal temperature range; asymmetric warming and changed extremes structure are not representable." Applicability: `direct` for temperature features. |
| `no_et0_recalculation` | `not_applicable` (to recalculated features) | "ET0-dependent features were not recalculated by the source execution (M7.3 discipline) and have no scenario-derived values to analyse." Affected features: the ET0 family. Applicability: `contextual`. |
| `hypothetical_not_predictive` | `qualitative_only` | "Every analysed value is a deterministic hypothetical transformation. Nothing here predicts crop yield, farm productivity, irrigation outcomes or rainfall probability." Applicability: `direct`. |

### 2.6 `feature_method_limitation`

| Code | Status | Content |
|---|---|---|
| `feature_engine_assumptions` | `qualitative_only` | "Responses inherit the M4 feature-engine assumptions (thresholds such as 35 °C hot-day or dry-spell definitions are fixed catalog constants; they do not vary with the scenario)." Applicability: `direct` for threshold features. |
| `classification_tolerance` | `quantified` | "Response classes use the documented, versioned rubric `sensitivity-response-classification-1.0` (equality tolerance 1e-9; constant band 0.1 % of the reference; threshold jump factor 10×)." Quantified value: the tolerance set. Applicability: `direct`. |

### 2.7 `regional_agronomic_uncertainty`

| Code | Status | Content |
|---|---|---|
| `no_local_validation` | `not_quantified` | "No validation against local agronomic evidence exists for these scenario calculations in this repository. Regional applicability is unquantified." Applicability: `contextual`. |

---

## 3. Dynamic evidence binding

Static items are materialised per analysis with **dynamic fields bound to the
actual analysis**:

- `affected_features` for temperature/precipitation items = the actual feature
  codes in the recalculated set belonging to that family.
- `missing_data_coverage` quantified values computed from the source run's
  feature rows at analysis time.
- `synthetic_source_values` included only when the source run's warnings or
  derived observations indicate synthetic data.
- `parameter_reference_value.quantified_value` = the actual reference tuples
  from the source execution configuration.

Items that do not apply to a given analysis (e.g. no synthetic data; single
explorable parameter making grid items moot) are either omitted or included
with status `not_applicable` — decided per item and documented in the item's
`description`; omission only for items whose category has no meaning for the
analysis shape (grid-related items when no grid was requested).

---

## 4. Rendering rules

- The UI shows the registry verbatim (`user_facing_explanation`), grouped by
  category, each with its status badge. Statuses are never collapsed into a
  traffic light or score.
- The registry is part of the analysis checksum — registered items are
  immutable once the analysis is result-bearing.

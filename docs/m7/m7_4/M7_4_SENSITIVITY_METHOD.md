# M7.4 — Sensitivity & Uncertainty Analysis: Mathematical Method Specification

**Status:** normative specification for the M7.4 implementation
**Method version:** `sensitivity-analysis-1.0.0` (constant `ANALYSIS_METHOD_VERSION`)
**Classification rubric version:** `sensitivity-response-classification-1.0`
**Uncertainty registry version:** `sensitivity-uncertainty-registry-1.0`

M7.4 explains how the **existing, verified M7.3 scenario-derived environmental
features** respond to the transformation parameters that were actually executed.
It is an **auditable analysis layer on top of M7.3** — it never redefines the
transformations, never re-engineers features, and never mutates any M7.3
artifact.

---

## 1. What is analysed (and what is not)

### 1.1 Analysis subject

The subject of every M7.4 analysis is ONE immutable, result-bearing M7.3
execution run (`scenario_execution_runs` row with status `succeeded` or
`completed_with_limitations`). The analysis explains:

1. How sensitive the run's **scenario-recalculated features**
   (`scenario_derived_features` rows with `evidence_status='scenario_recalculated'`)
   are to changes in the run's **configured transformation parameters**.
2. Which parameter produces the largest measurable effect on each feature.
3. Whether each feature's response is linear, nonlinear, monotonic,
   non-monotonic, or threshold-driven **over the explored parameter range**.
4. What range of outputs the explored parameter bounds produce — the
   **explored parameter-range envelope**.
5. Which uncertainty sources can be quantified and which remain unquantified.

### 1.2 Explorable parameter rule (scope discipline)

**Only parameters actually configured in the source execution are explorable.**

- `temperature_delta_c` is explorable **iff** the source execution configured
  a temperature transformation (`delta_c is not None`).
- `precipitation_multiplier` is explorable **iff** the source execution
  configured a precipitation transformation (`multiplier is not None`).

Rationale (binding):

- The reference parameter value must come **from the source execution**
  (M7.4 spec §3.1). A parameter the source never configured has **no reference
  value** — analysing it would analyse a transformation the source run never
  performed.
- Treating an unconfigured ΔT as `0.0` (or an unconfigured M_p as `1.0`) would
  silently widen the scenario's recalculated feature set (M7.3's dependency
  graph classifies features by *which parameters are configured*, not their
  values) and would compare evaluations against source rows that do not exist.
- A user who wants to explore a parameter the source scenario lacks creates a
  new scenario that configures it (M7.2 → M7.3 flow) and analyses THAT run.

Parameters present in the engine but not configured in the source execution are
reported with status `not_applicable` and the reason
`"parameter not configured in the source execution; no reference value exists"`
— never silently dropped, never invented.

### 1.3 Explicitly outside M7.4 scope

- Climate projections, weather forecasts, climate-model ingestion.
- Soil and management scenario transformations (M6B/M6C do not exist on this
  branch — verified in Phase 0).
- ET0 scenario recalculation (ET0-dependent features are not recalculated by
  M7.3 and therefore have no scenario-derived values to analyse).
- Crop yield, farm productivity, irrigation-demand or rainfall-probability
  predictions of any kind.
- Probabilistic methods: Monte Carlo, Latin hypercube, Sobol indices, Morris
  screening, bootstrap/Bayesian propagation, "probability of crop failure",
  confidence intervals derived from deterministic grids. These are documented
  as future capabilities with explicit prerequisites (§9) and are **not**
  stubbed, interfaced, or pretended.

---

## 2. Concepts and terminology (binding names)

| Concept | Binding name (API/DB/UI) | What it is | What it is NOT |
|---|---|---|---|
| Parameter sensitivity | `oat_response` | Deterministic one-factor-at-a-time response of a feature to one supported parameter | Not a probability calculation |
| Explored output range | `explored_parameter_range_envelope` | Min/max feature values evaluated over the user-supplied parameter bounds | NOT a confidence / prediction / probabilistic interval, NOT a likelihood, NOT a climate-projection range |
| Joint exploration | `joint_parameter_grid` | Deterministic 2-D grid over both configured parameters | Not a joint probability distribution; independence is NOT assumed or implied |
| Interaction measure | `finite_grid_interaction_contrast` | `I = f(x1,z1) − f(x1,z0) − f(x0,z1) + f(x0,z0)` at grid corners | NOT a Sobol interaction index |
| Response behaviour | `response_classification` | Value-derived classification over the explored range | Never a vague "highly sensitive" claim |
| Data/input uncertainty | `uncertainty_registry` items, category `observation_data_quality` | Source-carried quality metadata (coverage, missing counts); quantified ONLY where the source carries numbers | Never an invented measurement-error distribution or standard deviation |
| Model/structural limitation | registry categories `model_structural_limitation`, `feature_method_limitation` | Documented limitations | Never converted into numeric uncertainty |

The UI, API, and documentation must use the phrase **"explored parameter-range
envelope"** (or the DB/API field names above) wherever the envelope appears.
The standard user-facing disclosure (rendered in the UI and carried in the
analysis warnings) is:

> "The explored parameter-range envelope is the minimum and maximum output
> observed across the parameter values you asked the engine to evaluate. It is
> a deterministic sensitivity result, not a confidence or probability
> interval, and it does not establish how the real climate varies."

---

## 3. Evaluation design

### 3.1 Reference evaluation and reproduction gate

The analysis first **reproduces** the source run's scenario pass in-process:

1. Resolve the input set from the run's stored
   `source_observation_manifest` (BY VALUE — identical to M7.3's
   `_manifest_observations`, same hard window boundaries).
2. Run the M4 engine scenario pass with the run's **reference parameter
   values** (`delta_c_ref`, `multiplier_ref`) and the same
   aggregation levels / hemisphere / timezone / window.
3. Compare every produced feature value against the run's persisted
   `scenario_derived_features` rows (`evidence_status='scenario_recalculated'`),
   keyed by `(feature_code, aggregation_level, period_label)`, comparing
   `scenario_value` after canonical rounding (6 decimal places, M7.3
   `CHECKSUM_FLOAT_PRECISION`).
4. Also compare `transformed_observation_count`.

**Gate:** the analysis proceeds only if reproduction is exact
(`mismatched_rows == []`). On any mismatch the analysis fails with status
`failed`, `error_summary` naming the mismatch, and the discrepancy rows listed
in the analysis record. M7.4 never silently substitutes a different baseline.

The reproduced reference values are stored as the analysis's reference
evaluation (a `sensitivity_evaluations` row with `is_reference=true`).

### 3.2 Parameter design (user-supplied, validated)

For each explorable parameter the client supplies:

| Field | Constraints |
|---|---|
| `lower` | finite; `lower ≤ reference` |
| `upper` | finite; `upper ≥ reference` |
| `n_points` | integer, 3 ≤ n_points ≤ 21 (default 11) |

Validation failures return 422 with structured details:

- `lower > reference` / `upper < reference` →
  `"bounds must contain the reference parameter value"` (the reference point
  must be inside the explored range so every evaluation is comparable to it).
- `lower > upper` → `"lower bound exceeds upper bound"`.
- Non-finite values rejected; booleans rejected (bool is not a number).
- `precipitation_multiplier` bounds additionally require `lower ≥ 0`
  (the M7.3 transformation rejects negative multipliers).
- Temperature deltas must satisfy `|ΔT| ≤ 25 °C` and precipitation multipliers
  `M_p ≤ 10` (guardrails against physically absurd explorations; documented,
  versioned with the method).

The OAT sweep points are the closed **linspace** of `n_points` values from
`lower` to `upper` inclusive. The reference value is always a member of the
sweep conceptually; when `x_ref` coincides with a sweep point the evaluation is
**deduplicated** against the reference evaluation (same parameter tuple ⇒ same
deterministic result ⇒ one stored evaluation row referenced by both).

Grid spacing `h` used by finite differences is the linspace step
`(upper − lower) / (n_points − 1)`.

### 3.3 Holding other parameters fixed

Every OAT evaluation holds all other configured parameters at their reference
values. Concretely, evaluation `i` for parameter `p` is:

```
(delta_c_i, multiplier_i) = (x_i, multiplier_ref)   for the ΔT sweep
                            (delta_c_ref, z_i)      for the M_p sweep
```

The recalculated feature set is identical across all evaluations of one
analysis: M7.3's `plan_scenario_features` classifies by *which* parameters are
configured (non-None), never by their values. Hence every feature analysed has
a value at every evaluation point — no structural missingness arises from the
design itself. (Per-point numerical missingness, e.g. a failed pass, is
recorded as an evaluation failure and reflected in the response status.)

### 3.4 Joint parameter grid (optional, explicit opt-in)

Available **iff both** parameters are explorable. The client supplies bounds
and `n_points` per axis (2 ≤ n_points ≤ 9 per axis; total cells ≤ 81; total
unique evaluations across OAT + grid ≤ 100 — exceeded → 422). Grid cells are
the full cross product; cells whose parameter tuple equals an existing
evaluation are deduplicated to that evaluation row.

Grid products per feature: response surface values, min/max over the grid,
direction, non-monotonicity flag, threshold-transition flags, and the
finite-grid interaction contrast at the grid corners (§6.3).

### 3.5 Compute guards

- `n_points` per parameter ≤ 21; grid per axis ≤ 9; grid cells ≤ 81; unique
  evaluations ≤ 100 (each unique parameter tuple is computed once).
- Each evaluation is one M4 engine scenario pass (no per-evaluation baseline
  pass — the baseline is the source run's own stored baseline values and is
  never recomputed here).
- Per-evaluation **transformed observations are not persisted**. They are pure
  deterministic functions of (manifest × parameter tuple); persisting ~100 ×
  thousands of rows would duplicate derivable data. The reference evaluation's
  observations are already anchored by the source run's persisted derived
  observations; every other evaluation is anchored by the analysis checksum.
  Documented decision — revisit only with a concrete audit requirement.

---

## 4. OAT response metrics (per feature × per parameter)

For each `(feature_code, aggregation_level, period_label)` in the recalculated
set and each explorable parameter `p`:

Let the sweep points ordered ascending be `x_1 … x_n` with evaluated values
`y_1 … y_n` (finite floats; a failed evaluation yields no value). Let
`y_ref` be the reference value and `x_ref` the reference parameter value.

| Metric | Definition |
|---|---|
| `reference_value` | `y_ref` (reproduced, §3.1) |
| `evaluated_values` | `[(x_i, y_i) …]` ascending, finite only |
| `min_evaluated` / `max_evaluated` | min/max of finite `y_i` |
| `output_range` | `max_evaluated − min_evaluated` (null if < 2 finite values) |
| `explored_parameter_range_envelope` | `{lower: min_evaluated, upper: max_evaluated, parameter_lower: lower, parameter_upper: upper}` — naming is binding |
| `max_abs_difference` | `max |y_i − y_ref|` |
| `at_lower_bound` / `at_upper_bound` | `y` at the sweep endpoints (null if unavailable) |
| `difference_at_lower` / `difference_at_upper` | endpoint − `y_ref` |

### 4.1 Finite-difference slope

`S = Δy / Δx` — always with explicit units.

- **Local central difference at the reference** (preferred): when `x_ref` is
  strictly inside the sweep and both adjacent sweep points exist,
  `S_local = (f(x_ref + h) − f(x_ref − h)) / (2h)` where the two points are the
  sweep neighbours of `x_ref` and `h` is their parameter distance
  (equal-distance requirement verified; otherwise fall back).
- **One-sided difference**: when `x_ref` coincides with a sweep boundary or a
  neighbour is missing:
  `S = (f(x_ref + h) − f(x_ref)) / h` (forward) or
  `S = (f(x_ref) − f(x_ref − h)) / h` (backward).
- **Slope method recorded** on every response: `central` | `forward_one_sided`
  | `backward_one_sided` | `not_evaluated`.
- **Slope units**: `slope_units = f"{feature_unit} / {parameter_unit}"` where
  `parameter_unit` is `"degC"` for ΔT and `"multiplier"` for M_p. Slopes from
  different units are **never** presented as directly comparable; the UI ranks
  parameters per-feature (same units), never across features.
- A local derivative is **never** claimed valid across a suspected
  discontinuity: when the classification flags `threshold_suspected`
  (§5.2), the slope payload carries
  `slope_validity: "invalid_across_suspected_discontinuity"` in addition to the
  numeric value.
- **Normalised elasticity**
  `E = ((Δy / y_ref) / (Δx / x_ref)) = S · x_ref / y_ref` is computed **only**
  when `x_ref ≠ 0` **and** `y_ref ≠ 0` (and all quantities finite). Otherwise
  the response carries
  `elasticity: {status: "unavailable", reason: "reference_parameter_is_zero" | "reference_value_is_zero"}`.
  Division by zero never happens; no epsilon is inserted to force a value.

### 4.2 Direction

`direction` = sign of `f(upper_bound) − f(lower_bound)` over the sweep:
`increasing` | `decreasing` | `no_change` (exact zero within the equality
tolerance) | `not_evaluated` (< 2 finite endpoint values). Direction describes
the explored range only.

---

## 5. Response behaviour classification

**Rubric version:** `sensitivity-response-classification-1.0`. All thresholds
below are part of the rubric and versioned with it. They derive from actual
calculated values only.

### 5.1 Tolerances

- `EQUALITY_TOL = 1e-9` (absolute) — two floats are "equal" when
  `|a − b| ≤ EQUALITY_TOL` (used for zero-difference steps and reproduction).
- `CONSTANT_BAND_RELATIVE = 1e-3` (0.1 % of the reference magnitude) — the
  response counts as **approximately constant** when the whole span fits
  inside the band:
  `span ≤ max(CONSTANT_BAND_RELATIVE · |y_ref|, EQUALITY_TOL)`
  (absolute floor for `y_ref ≈ 0`).

### 5.2 Classes (evaluated in this order; first match wins)

| Class | Condition |
|---|---|
| `not_evaluated` | no finite evaluated value exists |
| `insufficient_evaluated_points` | 1 finite value only |
| `constant` | span ≤ constant band (§5.1) |
| `monotonic_increasing` | successive differences never negative beyond `EQUALITY_TOL`, and `y_n > y_1` beyond band |
| `monotonic_decreasing` | successive differences never positive beyond `EQUALITY_TOL`, and `y_1 > y_n` beyond band |
| `threshold_suspected` | monotonic (or constant-then-jump) **and** the largest single successive difference ≥ `THRESHOLD_JUMP_FACTOR ×` the median of non-zero successive differences (factor 10.0), **or** a single step constitutes ≥ 80 % of the span with ≥ 6 evaluated points. The numeric slope is annotated invalid across the jump (§4.1). |
| `non_monotonic` | at least one sign change in successive differences (beyond tolerances) |

Every response also carries `classification_version` so any future rubric
change is detectable in stored rows.

### 5.3 Ranking discipline

"Which parameter has the largest measurable effect" is answered **per feature,
per unit**: rank explorable parameters by `output_range` (and report
`max_abs_difference`) **only among parameters with identical
`slope_units`**. Cross-unit rankings are not computed. With a single
explorable parameter the ranking is trivially that parameter (stated as such,
not as a sensitivity claim).

---

## 6. Joint grid mathematics

### 6.1 Surface

Grid values per feature: `G[i][j] = f(x_i, z_j)` for axis points `x_i` (ΔT) and
`z_j` (M_p). Stored as grid cells with canonical parameter tuples
(deduplicated evaluations).

### 6.2 Grid-derived summaries per feature

`grid_min`, `grid_max`, `grid_output_range`, `direction` (corner-based, §4.2),
`non_monotonic` (true when any row or column sweep over the grid classifies as
non-monotonic), `threshold_transitions` (count of threshold-suspected rows or
columns), and the joint-vs-individual comparison:

- `joint_span_vs_oat_spans`: `grid_output_range` alongside each single-axis
  OAT `output_range`. When the surface is exactly additive in both axes these
  agree; divergence quantifies interaction over the explored grid.

### 6.3 Finite-grid interaction contrast

At the grid corners `(x0,z0), (x0,z1), (x1,z0), (x1,z1)` (grid min/max of each
axis):

```
I = f(x1,z1) − f(x1,z0) − f(x0,z1) + f(x0,z0)
```

- Always labelled **"finite-grid interaction contrast"** in every surface
  (API field `interaction_contrast`, UI caption, docs). Never "Sobol", never
  an "interaction index".
- Interpretation bands (documented, part of the rubric):
  `|I| ≤ EQUALITY_TOL` → `approximately_additive`;
  `I > 0` → `super_additive_over_explored_grid`;
  `I < 0` → `sub_additive_over_explored_grid`.
- **Structural expectation (documented, testable):** M7.3's dependency graph
  recalculates a feature only when **all** its required variables are
  transformed. A recalculated feature therefore draws on the temperature
  family only, the precipitation family only, or (when both transformations
  are configured) potentially both. For any feature whose required variables
  lie in exactly one family, the transformation is independent of the other
  axis and `I` is **exactly 0** — the joint grid doubles as a negative control
  (a nonzero `I` on a single-family feature would indicate an engine defect).
  Mixed-family features (e.g. any catalog feature requiring both a temperature
  and a precipitation variable) may legitimately show `I ≠ 0`; the response
  records the feature's variable families so readers can tell the two cases
  apart.

---

## 7. Precision, serialization, checksums

- All stored floats pass through M7.3's canonical rounding
  (`canonical_value`, 6 decimal places) before entering checksum documents;
  stored column values keep full float precision, checksums use the rounded
  canon.
- Evaluation values are ordered canonically
  (`parameter tuple ascending, then feature_code/aggregation/period`) before
  hashing.
- The analysis output checksum is SHA-256 over the canonical document
  `checksum_format: "sensitivity-analysis-output-1"` containing: the analysis
  definition (source pins, parameter design, grid design, engine versions,
  method versions), the reference reproduction report, all evaluations
  (parameter tuples + status), all feature values, all OAT responses, all grid
  cells + summaries + interaction contrasts, the uncertainty registry items,
  not-analysed feature reasons, and warnings. Excluded on purpose: ids,
  timestamps, created_by, idempotency key — identical scientific inputs yield
  identical checksums (M7.3 §11 discipline).

---

## 8. Uncertainty & limitation registry (summary — full rubric in
`M7_4_UNCERTAINTY_REGISTRY.md`)

Seven categories with per-item metadata
(category, description, evidence_source, quantification_status,
quantification_method, affects_current_analysis, affected_inputs,
affected_features, applicability, user_facing_explanation) and statuses
`quantified | bounded_exploratory | qualitative_only | not_quantified |
not_applicable | not_evaluated`. No composite uncertainty score exists; no
numeric confidence values are invented. A user-supplied parameter range never
implies a probability distribution — stated in the registry item
`parameter_range_uncertainty` and in the UI disclosure.

---

## 9. Methods explicitly not enabled (future prerequisites)

| Method | Why not now | Prerequisites to ever enable |
|---|---|---|
| Monte Carlo / Latin hypercube sampling | Requires input distributions; none exist in the repository | Sourced measurement-error distributions per dataset product; sampling design; cost guards |
| Sobol indices | Requires distributional assumptions + many model evaluations | Same as Monte Carlo; variance-decomposition validation |
| Morris screening | Requires randomized trajectories | Distributional assumptions; runtime budget |
| Bootstrap / Bayesian propagation | Requires resample-able evidence or priors | Quantified source uncertainty; priors with documented provenance |
| Confidence intervals from deterministic grids | Methodologically unsound (deterministic outputs have no sampling variance) | Never — replaced by the envelope terminology |
| Probability of crop failure / yield impact | Crop models do not exist in the repository | Out of M7 roadmap scope entirely |

These are documentation-only; **no empty interfaces are created** for them.

---

## 10. Golden mathematical expectations (tested)

1. `air_temperature_mean_monthly` under a ΔT-only sweep: slope = **exactly
   1.0** (`degC / degC`), `monotonic_increasing`, envelope =
   `[ref + lower, ref + upper]` (within float tolerance), successive
   differences equal → not threshold.
2. `precipitation_total_monthly` under an M_p-only sweep: slope = monthly
   baseline total (`mm / multiplier`), envelope = `[lower·base, upper·base]`,
   elasticity = **exactly 1.0**.
3. `hot_days_35c_count_monthly` under ΔT: step-shaped response — classified
   `threshold_suspected` or `monotonic_increasing` depending on where bounds
   place the 35 °C crossing; slope annotated invalid across the jump when
   applicable.
4. Joint grid, single-family feature: interaction contrast **exactly 0.0**.
5. Elasticity unavailable statuses when `y_ref = 0` or `x_ref = 0` — structured
   reason, never a division.
6. Reproduction gate: mismatching engine state (simulated) → analysis `failed`
   with named mismatches; nothing silently substituted.

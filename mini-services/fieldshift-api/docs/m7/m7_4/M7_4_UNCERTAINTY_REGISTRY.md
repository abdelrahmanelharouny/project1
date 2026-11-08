# M7.4 Uncertainty & Limitation Registry

The per-analysis uncertainty record defined here and built by
`app/sensitivity/registry.py` (registry version
`sensitivity-uncertainty-registry-1.0`).

## Purpose

Every sensitivity analysis ships a registry that states, in structured
form, what the result does and does not account for. The registry exists so
downstream consumers (robust rotation, decision documents, the digital
twin) can quote limitations verbatim instead of re-deriving or softening
them.

## Rules

- **Stable vocabularies.** Categories and statuses are fixed enums; there
  is no composite uncertainty score and no invented numeric confidence.
- **Dynamic evidence binding.** Static registry items carry evidence bound
  to the actual analysis: affected feature ids, coverage statistics and
  source tuples from the analyzed run.
- **Omit, don't fake.** Items that have no meaning for a given analysis
  shape (e.g. grid-interaction items when no joint grid was run) are
  omitted rather than filled with placeholders.

## Categories

| Category | Meaning |
| --- | --- |
| `parameter_range_uncertainty` | Swept bounds are user assumptions, not measured distributions |
| `observation_data_quality` | Coverage gaps, synthetic labels, provider caveats of the pinned observations |
| `spatial_coverage_limitation` | Point/grid provenance vs field geometry; no spatial interpolation performed |
| `temporal_resolution_limitation` | Native cadence preserved; no disaggregation or downscaling |
| `model_structural_limitation` | Linear shift/scale transformations only; structural error not quantified |
| `feature_method_limitation` | Feature formulas are the versioned M4 catalog's, with its own caveats |
| `regional_agronomic_uncertainty` | Reference (non-validated) knowledge where it feeds a swept parameter |

Each item carries: category, severity/status vocabulary, human-readable
statement, and (where applicable) the dynamic evidence references.

## Consumption

- M7.5 robust runs and M7.6 decision documents embed relevant registry
  items by reference (analysis id + item), never paraphrased.
- The digital twin surfaces them as first-class sections, not footnotes.
- The registry version is stamped into every analysis; vocabulary changes
  bump the version rather than mutating old records.

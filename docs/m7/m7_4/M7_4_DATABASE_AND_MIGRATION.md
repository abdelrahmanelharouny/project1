# M7.4 — Database & Migration Design

**Migration:** `0010_sensitivity_analysis` (linear chain 0001 → 0010)
**Revises:** `0009_scenario_execution`

Additive migration; no existing table, column or constraint is altered. All
new tables follow the M7.2/M7.3 conventions: UUID PKs, `JSONB` documents,
named CHECK constraints, partial unique indexes for idempotency, FK
RESTRICT toward protected artifacts, and a result-freezing BEFORE UPDATE
trigger.

---

## 1. Tables

### 1.1 `sensitivity_analyses` — the analysis record

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `field_id` | UUID FK → fields (CASCADE) | tenant scoping path |
| `source_execution_run_id` | UUID FK → scenario_execution_runs (RESTRICT) | the analysed run |
| `scenario_id` | UUID FK → scenarios (RESTRICT) | denormalized for integrity checks |
| `scenario_version` | int | |
| `parent_field_state_id` | UUID FK → field_states (RESTRICT) | by-value pin |
| `parent_snapshot_checksum` | varchar(64) | by-value pin |
| `scenario_configuration_checksum` | varchar(64) | by-value pin |
| `source_observation_manifest_sha256` | varchar(64) | by-value pin |
| `source_output_checksum` | varchar(64) | the run's output checksum at analysis time |
| `reference_parameter_values` | JSONB | canonical `{temperature_delta_c?, precipitation_multiplier?}` |
| `explorable_parameters` | JSONB | which parameters are explorable (+ not-applicable reasons for the rest) |
| `parameter_design` | JSONB | per-parameter `{lower, upper, n_points}` (validated) |
| `grid_design` | JSONB nullable | opt-in joint grid spec `{temperature_delta_c: {lower,upper,n_points}, precipitation_multiplier: {...}}` |
| `analysis_configuration` | JSONB | canonical input document |
| `analysis_fingerprint` | varchar(64) | SHA-256 over the input document |
| `analysis_status` | varchar(30) | CHECK: queued/running/succeeded/completed_with_limitations/failed |
| `analysis_method_version` | varchar(40) | `sensitivity-analysis-1.0.0` |
| `response_classification_version` | varchar(40) | `sensitivity-response-classification-1.0` |
| `uncertainty_registry_version` | varchar(40) | `sensitivity-uncertainty-registry-1.0` |
| `transformation_engine_version` / `feature_engine_version` / `feature_catalog_version` | varchar(40) | engines inherited from the source run |
| `reference_reproduction` | JSONB | `{reproduced, compared_rows, matched_rows, mismatched_rows[], observation_count_match}` |
| `evaluated_feature_count` / `evaluation_count` | int | result counts |
| `warnings` | JSONB list | includes the standard disclosures |
| `not_analysed_features` | JSONB dict | inherited not_affected/not_evaluated reasons |
| `output_checksum` | varchar(64) nullable | CHECK: present on result-bearing statuses |
| `error_summary` | text nullable | |
| `created_by` | UUID nullable | |
| `idempotency_key` | text nullable | partial unique with run id |
| `started_at` / `completed_at` | timestamptz nullable | |
| `created_at` / `updated_at` | timestamptz | TimestampMixin |

Constraints & indexes:

- `ck_sensitivity_analysis_status` (5 honest statuses)
- `ck_sensitivity_analysis_checksum_on_success` (result-bearing ⇒ checksum)
- `uq_sensitivity_analysis_fingerprint (source_execution_run_id, analysis_fingerprint)` unique
- `uq_sensitivity_analysis_idempotency (source_execution_run_id, idempotency_key)` unique WHERE idempotency_key IS NOT NULL
- `ix_sensitivity_analyses_run`, `ix_sensitivity_analyses_field`, `ix_sensitivity_analyses_scenario`
- BEFORE UPDATE trigger `enforce_sensitivity_analysis_immutability`: when OLD
  status is result-bearing, every content column IS DISTINCT FROM check →
  RAISE EXCEPTION. (Mirrors 0009's trigger verbatim in structure.)

### 1.2 `sensitivity_evaluations` — one row per unique parameter tuple

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `analysis_id` | UUID FK → sensitivity_analyses (CASCADE) | |
| `evaluation_kind` | varchar(20) | CHECK: reference / oat / grid (an evaluation can serve several roles; kind records its first role; `roles` JSONB lists all) |
| `is_reference` | bool | exactly one true per analysis |
| `temperature_delta_c` | float nullable | the evaluated tuple (family-specific semantics: absent = not configured) |
| `precipitation_multiplier` | float nullable | |
| `parameter_tuple_checksum` | varchar(64) | canonical tuple hash (documentation/debug aid) |
| `evaluation_status` | varchar(20) | CHECK: succeeded / failed |
| `transformed_observation_count` | int | |
| `derived_feature_count` | int | |
| `error_summary` | text nullable | per-evaluation failure |
| `created_at` | timestamptz | |

Index: `ix_sensitivity_evaluations_analysis (analysis_id)`,
`uq_sensitivity_evaluation_tuple (analysis_id, temperature_delta_c,
precipitation_multiplier)` unique (dedupe invariant at the DB level).

### 1.3 `sensitivity_feature_values` — raw response data

One row per (evaluation, feature, aggregation, period):

| Column | Type |
|---|---|
| `id` UUID PK; `analysis_id` FK CASCADE; `evaluation_id` FK CASCADE |
| `feature_code` varchar(80); `unit` varchar(30); `aggregation_level` varchar(20); `period_label` varchar(40) |
| `reference_value` float nullable (denormalized from the reference evaluation) |
| `evaluated_value` float nullable |
| `difference_from_reference` float nullable |
| `created_at` timestamptz |

Index: `ix_sensitivity_feature_values_analysis (analysis_id)`,
`ix_sensitivity_feature_values_eval (evaluation_id, feature_code)`.

### 1.4 `sensitivity_oat_responses` — per (analysis, parameter, feature key)

| Column | Type |
|---|---|
| `id` UUID PK; `analysis_id` FK CASCADE |
| `parameter_code` varchar(40) | CHECK: temperature_delta_c / precipitation_multiplier |
| `feature_code` / `unit` / `aggregation_level` / `period_label` |
| `reference_value` float nullable |
| `min_evaluated` / `max_evaluated` / `output_range` / `max_abs_difference` float nullable |
| `difference_at_lower` / `difference_at_upper` float nullable |
| `slope` float nullable; `slope_method` varchar(30); `slope_units` varchar(60); `slope_validity` varchar(60) |
| `elasticity` float nullable; `elasticity_status` varchar(40); `elasticity_unavailable_reason` text nullable |
| `direction` varchar(30); `response_classification` varchar(40); `classification_version` varchar(40) |
| `n_evaluated_points` int |
| `response_status` varchar(30) | evaluated / partially_evaluated / not_evaluated |
| `created_at` timestamptz |

Constraints: CHECKs on parameter_code/direction/classification/slope_method/
response_status vocabularies. Index `(analysis_id, parameter_code,
feature_code, aggregation_level, period_label)`.

### 1.5 `sensitivity_grid_cells` + grid summaries

`sensitivity_grid_cells`: (analysis_id FK, feature_code, unit,
aggregation_level, period_label, `temperature_delta_c` float,
`precipitation_multiplier` float, `cell_value` float, created_at) with unique
`(analysis_id, feature_code, aggregation_level, period_label,
temperature_delta_c, precipitation_multiplier)`.

`sensitivity_grid_summaries`: (analysis_id FK, feature_code, unit,
aggregation_level, period_label, `grid_min`, `grid_max`, `grid_output_range`,
`direction`, `non_monotonic` bool, `threshold_transition_count` int,
`interaction_contrast` float, `interaction_interpretation` varchar(40),
`variable_families` JSONB, created_at). CHECK on interpretation:
approximately_additive / super_additive_over_explored_grid /
sub_additive_over_explored_grid / not_evaluated.

### 1.6 `sensitivity_uncertainty_items`

(analysis_id FK CASCADE, `category` varchar(40) CHECK 7 categories, `code`
varchar(60), `description` text, `evidence_source` varchar(200),
`quantification_status` varchar(30) CHECK 6 statuses, `quantification_method`
text nullable, `quantified_value` JSONB nullable, `affects_current_analysis`
bool, `affected_inputs` JSONB list, `affected_features` JSONB list,
`applicability` varchar(20) CHECK direct/contextual/peripheral,
`user_facing_explanation` text, `registry_version` varchar(40), created_at).
Index `(analysis_id, category)`.

---

## 2. Data-volume rationale

Per-evaluation transformed observations are deliberately NOT persisted
(`M7_4_SENSITIVITY_METHOD.md` §3.5): they are pure deterministic functions of
(manifest × tuple), the reference evaluation is anchored against the source
run's persisted derived observations, and the checksum covers all evaluated
feature values. Storage grows with (evaluations × recalculated feature keys),
typically tens of evaluations × dozens of rows.

## 3. Downgrade

`downgrade()` drops the trigger, then the six tables in reverse dependency
order. No data migration occurs (the tables are new).

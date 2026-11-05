# M7.3 — Database & Migration

**Migration:** `0009_scenario_execution` (linear chain: `0008_scenario_domain` → `0009_scenario_execution`).
Verified on the dev database (fresh upgrade) and on a scratch database (upgrade → downgrade → re-upgrade,
`tests/integration/test_migrations.py::TestM73Migrations`).

---

## 1. New tables (additive; nothing existing is rewritten)

### 1.1 `scenario_execution_runs`

One immutable execution of a finalized scenario definition.

| Column group | Columns |
|---|---|
| Identity & tenancy | `id` (PK), `field_id` FK→fields CASCADE, timestamps |
| Scenario pin | `scenario_id` FK→scenarios **RESTRICT**, `scenario_version` |
| Parent pins (by value) | `parent_field_state_id` FK→field_states **RESTRICT**, `parent_snapshot_checksum`, `scenario_configuration_checksum` |
| Versioned engines | `transformation_engine_version`, `feature_engine_version`, `feature_catalog_version` |
| Input integrity | `source_observation_manifest` (verbatim parent manifest), `source_observation_manifest_sha256`, `execution_configuration` (canonical document), `input_fingerprint` |
| Lifecycle | `run_status` (`queued`/`running`/`succeeded`/`completed_with_limitations`/`failed`), `started_at`, `completed_at`, `error_summary` |
| Calendar | `aggregation_levels`, `hemisphere`, `calendar_timezone` |
| Output integrity | `output_checksum`, `records_written`, `transformed_observation_count`, `derived_feature_count` |
| Disclosure | `warnings`, `not_evaluated_reasons`, `resource_constraints` |
| Audit | `created_by`, `idempotency_key` |

Constraints & indexes:

- CHECK `ck_scenario_execution_status` — the five honest statuses.
- CHECK `ck_scenario_execution_checksum_on_success` — result-bearing runs must carry an output checksum.
- UNIQUE `uq_scenario_execution_fingerprint (scenario_id, input_fingerprint)` — deterministic replay.
- UNIQUE partial `uq_scenario_execution_idempotency (scenario_id, idempotency_key) WHERE idempotency_key IS NOT NULL`.
- Indexes `ix_scenario_executions_scenario`, `ix_scenario_executions_field`.

Triggers:

- `trg_scenario_execution_immutability` (BEFORE UPDATE, `enforce_scenario_execution_immutability`) —
  result-bearing runs (`succeeded`, `completed_with_limitations`) are frozen: every content column is
  compared to its old value; any difference aborts the statement.
- `trg_scenario_execution_no_delete` (BEFORE DELETE, `prevent_scenario_execution_result_delete`) —
  result-bearing runs cannot be deleted. `failed` runs remain deletable (no results; retries replace them).

Tenant isolation: through `field_id` → `farms.organization_id` at the service layer (same idiom as all
dynamic endpoints); every execution API resolves the run's field for the principal first.

### 1.2 `scenario_derived_observations`

The transformed observation layer — scenario-derived values are **never** inserted into `observations`.

Key columns: `execution_run_id` FK CASCADE, `source_observation_id`, `dataset_product_id`,
`variable_code`, `baseline_value`, `transformed_value`, `unit`, `observed_at`, `period_start/end`,
`time_support`, `spatial_support_type`, `spatial_resolution_m`, `transformation_code`,
`transformation_parameter` (JSONB), `evidence_class`
(`scenario_derived_transformed` | `synthetic_test` — CHECK `ck_scenario_derived_obs_evidence`),
`source_evidence_class`, `is_synthetic`, `quality_status`, `source_metadata` (asset refs).
Missing source values persist as NULL — never zero.

### 1.3 `scenario_derived_features`

Baseline-vs-scenario comparison rows. Key columns: `execution_run_id` FK CASCADE, `feature_code`,
`feature_name`, `unit`, `aggregation_level`, `period_label`, `period_start/end`, `baseline_value`,
`scenario_value`, `difference_value`, `difference_percent` (NULL when baseline is NULL/0 — never
fabricated), `feature_specification_version`, `evidence_status`
(`scenario_recalculated` | `not_affected` | `not_evaluated` — CHECK `ck_scenario_derived_feature_evidence`),
`quality_status`, `coverage_ratio`, `n_input`, `n_missing`, `uncertainty_metadata` (JSONB: source
uncertainty passthrough, transformation-assumption note, missing-evidence note, full engine provenance,
baseline reference).

Excluded features get one explicit status row each (`period_label = 'run_window'`, NULL values, reason in
`uncertainty_metadata.reason`) — reported, never silently absent, never fabricated.

## 2. Relationship to existing structures

| Existing structure | Relationship |
|---|---|
| `observations` | read-only input (via the parent manifest, by value); never written by M7.3 |
| `feature_runs` / `feature_values` | read-only context (parent environmental run); M7.3 recomputes in-process; parent rows untouched |
| `field_states` | FK RESTRICT from executions — a parent snapshot cannot be deleted while an execution references it |
| `scenarios` | FK RESTRICT from executions — a scenario cannot be deleted while an execution exists |

Derived rows cascade on run deletion (which the trigger blocks for result-bearing runs anyway), so table
drops remain clean in downgrade.

## 3. Downgrade

`downgrade 0009_scenario_execution` drops both triggers + both functions, all three tables (with their
indexes) in reverse dependency order — verified by `TestM73Migrations::test_downgrade_to_0008_reverses_execution_schema`,
followed by a clean re-upgrade.

## 4. Branch note

The repository's committed chain on `main` is linear
(`…0006_water_intelligence → 0007_field_state_foundation → 0008_scenario_domain → 0009_scenario_execution`).
A separate workstream (uncommitted M6B/M6C soil/management) had introduced branched revisions `0007_soil_intelligence`
and `0008_field_management`; that workstream is preserved verbatim on branch `m6b-m6c-wip` (including a
diagnostic merge node `0009_merge_domain_branches`) and is out of M7.3 scope. See
`M7_3_GAP_ANALYSIS.md` §2–3.

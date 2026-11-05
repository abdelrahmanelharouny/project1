# M7.4 — Analysis Architecture, Integration & Lineage

**Status:** normative

M7.4 extends M7.3 **without weakening any of its integrity guarantees**. This
document defines how analyses attach to M7.3 runs, what is validated, what is
immutable, and how determinism/idempotency work.

---

## 1. Position in the stack

```
Field State (M7.1, immutable snapshot + manifest)
    ↓ pinned by
Scenario definition (M7.2, finalized, checksummed, trigger-frozen)
    ↓ executed by
Scenario execution run (M7.3, immutable, output-checksummed)
    ↓ analysed by
Sensitivity analysis (M7.4, immutable, output-checksummed)  ← THIS MILESTONE
```

M7.4 reads: the run row, its derived features, the parent Field State, the
scenario definition. M7.4 writes: only its own `sensitivity_*` tables.
**Nothing** in `observations`, `feature_runs`, `field_states`, `scenarios`,
`scenario_execution_runs`, `scenario_derived_observations`,
`scenario_derived_features` is ever mutated or deleted by M7.4.

Analyses are **separate analytical artifacts**. They reuse the pure M7.3
transformation functions (`apply_transformations`) and the M4 feature engine
(`compute_feature_drafts`) through the same code paths M7.3 uses — no
duplicated transformation or feature-engineering logic exists in M7.4.

---

## 2. Eligibility of a source run

`POST /scenario-executions/{run_id}/sensitivity-analyses` validates, in order
(all failures are 404/409/422 with structured codes):

| # | Check | Failure code |
|---|---|---|
| 1 | Run exists + tenant scoping via run.field → farm | 404 `NOT_FOUND` |
| 2 | Run status ∈ {succeeded, completed_with_limitations} | 409 `RUN_NOT_RESULT_BEARING` |
| 3 | Scenario finalized (`scenario_status == 'finalized'`) | 409 `SCENARIO_NOT_FINALIZED` |
| 4 | Scenario checksum intact (`sc.verify`-style recomputation matches) | 409 `SCENARIO_CHECKSUM_MISMATCH` |
| 5 | Parent Field State exists; `checksum_sha256 == run.parent_snapshot_checksum` | 409 `PARENT_STATE_CHECKSUM_MISMATCH` |
| 6 | `parent.observation_manifest_sha256 == run.source_observation_manifest_sha256` | 409 `MANIFEST_CHECKSUM_MISMATCH` |
| 7 | Full run verification (M7.3 `verify_execution`): `output_checksum_valid` ∧ `scenario_definition_checksum_valid` ∧ `parent_snapshot_intact` ∧ `manifest_checksum_matches_run` | 409 `RUN_VERIFICATION_FAILED` (details carry the failing flags) |
| 8 | At least one explorable parameter (config in execution_configuration) | 422 `NO_EXPLORABLE_PARAMETERS` |
| 9 | Parameter design valid (bounds contain reference, ≥ 3 points, guardrails) | 422 with field details |
| 10 | Evaluation budget respected (unique evaluations ≤ 100) | 422 `EVALUATION_BUDGET_EXCEEDED` |

Check 7 means an analysis can only attach to a run whose stored artifacts
still re-verify end-to-end — lineage integrity is a precondition, not a
post-hoc hope.

---

## 3. Provenance recorded on every analysis

Copied BY VALUE at creation (never re-resolved live):

- `source_execution_run_id`, `scenario_id`, `scenario_version`
- `scenario_configuration_checksum`, `parent_field_state_id`,
  `parent_snapshot_checksum`, `source_observation_manifest_sha256`
- `source_output_checksum` (the run's own output checksum)
- `reference_parameter_values` (canonical tuples from the run's
  execution_configuration)
- `parameter_design` (user bounds + n_points per explorable parameter)
- `grid_design` (opt-in joint grid spec; null when not requested)
- engine versions: `analysis_method_version`, `transformation_engine_version`,
  `feature_engine_version`, `feature_catalog_version`
- `analysis_configuration` (canonical input document) +
  `analysis_fingerprint` (SHA-256 over it)
- `created_by`, `created_at`, tenant scope via `field_id`

Result columns: `analysis_status`, `reference_reproduction` report, counts,
`warnings`, `not_analysed_features` (inherited not_affected/not_evaluated
reasons, summarized), `uncertainty_registry_version`,
`output_checksum`, `error_summary`, `started_at`/`completed_at`.

---

## 4. Immutability model (mirrors M7.2/M7.3 exactly)

- Result-bearing analyses (`succeeded`, `completed_with_limitations`) are
  frozen by the application AND by the `enforce_sensitivity_analysis_immutability`
  database trigger (migration 0010): every content column compared on UPDATE,
  any difference aborts.
- Failed analyses carry no results and may be deleted; result-bearing analyses
  are protected by `scenario_execution_runs` FK RESTRICT semantics (the source
  run cannot be deleted while an analysis references it — the run is already
  trigger-frozen itself, so this is belt-and-braces).
- A changed parameter design, grid design, method version or engine version
  changes the `analysis_fingerprint` ⇒ a NEW analysis row. Analyses are
  append-only; there is no update path.

## 5. Idempotency & determinism

- UNIQUE `(source_execution_run_id, analysis_fingerprint)` — replaying an
  identical analysis definition returns the existing analysis (like M7.3 runs).
- Partial UNIQUE `(source_execution_run_id, idempotency_key)` — client-keyed
  replay.
- Determinism: identical (manifest, engine versions, parameter design) ⇒
  identical evaluations, values, checksums. Verified by tests that run the
  same analysis twice and compare `output_checksum`.
- Scope: idempotency is per source run — the same design applied to a
  different run is a different analysis (correct: the reference values differ).

## 6. Reference reproduction & verification endpoint

- At creation, the reference evaluation reproduces the source run's scenario
  pass and compares canonical feature values + observation counts
  (`M7_4_SENSITIVITY_METHOD.md` §3.1). Mismatch ⇒ `failed` analysis with the
  discrepancy rows; no partial results.
- `POST /sensitivity-analyses/{id}/verify` recomputes, from persisted rows:
  the analysis output checksum, all source pins, and the reference
  reproduction flags. Returns the same four-flag vocabulary as M7.3's verify
  plus analysis-specific flags (`output_checksum_valid`,
  `source_run_intact`, `parent_snapshot_intact`, `manifest_checksum_matches`,
  `reference_reproduction_consistent`).

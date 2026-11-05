# M7.3 — Scenario Execution Architecture

**Status:** Implemented in `app/scenario_execution/` (contracts / transformations / dependency_graph / service)
and `app/api/v1/scenario_executions.py`. Migration `0009_scenario_execution`.

---

## 1. Module layout and isolation rules

| Module | Responsibility | Isolation |
|---|---|---|
| `contracts.py` | Versioned contracts: transformation codes, evidence classes, run statuses, canonical `ExecutionConfiguration`, execution checksum payload, `ExecutionBlockedError` | pure data — no DB / HTTP / engine imports |
| `transformations.py` | The two pure transformations + unit gates + `DerivedObservation` records | pure functions — no I/O of any kind |
| `dependency_graph.py` | Catalog-derived feature classification (`recalculate` / `exclude_et0` / `not_affected` / `exclude_mixed_inputs`) | reads `app.features.catalog` only |
| `service.py` | Orchestration: eligibility → verification → manifest resolution → transformation → two engine passes → checksums → persistence | imports feature engine + scenario contracts; no HTTP types |
| `app/api/v1/scenario_executions.py` | 7 endpoints | calls service only; tenant scoping at every entry |

The transformation service never imports HTTP or frontend components (spec §8). The M4 feature engine
(`compute_feature_drafts`) is invoked as-is — no duplicated formulas, no second implementation.

## 2. Execution flow (implemented)

```
Finalized Scenario Definition
    ↓  _require_executable        — status == finalized; type ∈ {historical_perturbation, user_defined_stress}
    ↓  _verify_definition_pins    — recompute definition checksum; parent state exists + checksum matches pin
Verify Scenario Configuration Checksum
    ↓  _extract_transformations   — map AdjustmentSet → {delta_c, multiplier, resource_constraints}
    ↓                             — unsupported dimensions → ExecutionBlockedError (structured findings)
Resolve Observation Manifest
    ↓  _manifest_observations     — engine dicts built PURELY from the parent state's verbatim manifest
    ↓                             (BY VALUE; hard scenario window; no live observation query)
Check Variable and Resolution Compatibility
    ↓  plan_scenario_features     — per-feature role plan; ET0 excluded; mixed refused; non-daily disclosed
Apply Environmental Transformations
    ↓  apply_transformations      — pure; unit exclusions reported; missing stays missing
Generate Derived Observation Artifacts
    ↓  DerivedObservation records (baseline + transformed + parameter + evidence classes)
Recalculate Supported Features
    ↓  M4 engine pass #1 (baseline: original values, full compatible spec set)
    ↓  M4 engine pass #2 (scenario: transformed values, recalculate set only)
Propagate Quality and Uncertainty
    ↓  quality flags, coverage, engine not_evaluated reasons merged; uncertainty metadata per feature
Generate Scenario Execution Checksum
    ↓  input_fingerprint (pre-run) + output_checksum (post-run), canonical JSON SHA-256
Persist Immutable Results
    → scenario_execution_runs + scenario_derived_observations + scenario_derived_features
    → trigger-frozen at run_status ∈ {succeeded, completed_with_limitations}
```

Execution is **synchronous** (same pattern as M4 feature runs / M7.1 field states). Statuses:
`queued → running → succeeded | completed_with_limitations | failed`.
`completed_with_limitations` = result-bearing but warnings or not_evaluated reasons exist (an ET0
exclusion makes virtually every run land here — by design and honestly).

## 3. Execution eligibility

| Scenario state | Executable? |
|---|---|
| `draft` | ❌ `SCENARIO_NOT_FINALIZED` (409) |
| `valid` / `conditionally_valid` (not finalized) | ❌ 409 — finalization freezes the definition; mutable definitions never execute |
| `invalid` / `missing_reference` / `incompatible_period` | ❌ 409 (never reached `finalized`) |
| `unsupported` (climate/forecast types) | ❌ 409 `SCENARIO_TYPE_NOT_EXECUTABLE` |
| `historical_observed` (finalized) | ❌ 409 — reference-only, no transformation to apply |
| `finalized` + `historical_perturbation` / `user_defined_stress` | ✅ eligibility continues |
| finalized + any unsupported adjustment dimension | ❌ 422 `SCENARIO_EXECUTION_BLOCKED` with per-dimension findings |
| finalized + only `water_allocation_multiplier` (+ no supported transformation) | ❌ 422 (`no_supported_transformation`) — a no-op run would masquerade as the baseline |
| finalized + supported transformation + `water_allocation_multiplier` | ✅ multiplier retained as resource-constraint context, never weather |

A finalized `conditionally_valid` verdict (carried in `validation_summary`) executes — all required variables
for the configured transformations are re-checked at execution time by the compatibility plan and the engine's
own coverage machinery; its warnings are retained in the run's `warnings`.

## 4. The two engine passes

- **Baseline pass**: full catalog specs over the ORIGINAL manifest observations, scenario window, scenario
  aggregation levels — produces the baseline values the comparison uses. The parent `feature_runs` rows are
  never consulted for values and never modified.
- **Scenario pass**: `recalculate_specs` only, over the transformed observation dicts (each carrying a DERIVED
  id `"<source-uuid>:derived"`, so engine provenance references the derived layer, which maps back to source
  observation ids).
- Window: exactly the scenario `[period_start, period_end]` — no ±2-day margin, no silent extension; baseline
  and scenario therefore always compare identical periods.
- Aggregation levels: `["daily", "monthly", "seasonal"]` when the window is ≤ 366 days (daily otherwise
  omitted — mirrors M4's daily window cap), else `["monthly", "seasonal"]`.

## 5. Idempotency, replay and concurrency

- **input_fingerprint** = SHA-256 over `{fingerprint_format, execution_configuration, source_observation_manifest_sha256}`.
  - changed assumption / parent pin / engine version / window / levels ⇒ different fingerprint ⇒ **new run**.
  - identical inputs ⇒ same fingerprint ⇒ idempotent replay: the API returns the existing run.
- UNIQUE `(scenario_id, input_fingerprint)` — a concurrent double-POST loses the insert race, catches
  `IntegrityError` and returns the winner's run (serialized execution, no duplicate compute).
- UNIQUE partial `(scenario_id, idempotency_key)` for client-keyed replay (field-of-scenario scoped).
- A **failed** run is replaced on the next attempt (failed rows carry no results and are deletable);
  result-bearing rows can never be deleted (BEFORE DELETE trigger).

## 6. Re-execution across engine versions

`transformation_engine_version`, `feature_engine_version` and `feature_catalog_version` are part of both the
execution configuration and the output checksum. A future engine bump changes the fingerprint ⇒ a new,
distinct run is created next to the historical one — the old run's checksum remains verifiable forever
(its manifest and pins are stored by value).

## 7. API surface

| Method & path | Purpose |
|---|---|
| `POST /api/v1/scenarios/{scenario_id}/executions` | execute (or idempotently replay) — 200 with the run |
| `GET /api/v1/scenarios/{scenario_id}/executions?run_status=` | execution history |
| `GET /api/v1/scenario-executions/{run_id}` | run detail (checksums, config, warnings, provenance) |
| `GET /api/v1/scenario-executions/{run_id}/features?evidence_status=&feature_code=` | derived feature rows |
| `GET /api/v1/scenario-executions/{run_id}/observations?variable_code=&limit=&offset=` | derived observation rows (paginated ≤ 1000) |
| `GET /api/v1/scenario-executions/{run_id}/compare` | baseline-vs-scenario comparison document |
| `POST /api/v1/scenario-executions/{run_id}/verify` | independent checksum + parent-pin verification |

All endpoints resolve the run/scenario → field → farm → principal and refuse cross-tenant access with
404/403 without leaking existence. No endpoint mutates a result-bearing run.

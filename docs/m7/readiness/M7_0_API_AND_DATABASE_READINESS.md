# M7.0 — API, Database & Computation Readiness

**Inspection date:** 2026-11-01 · **Question:** can the current APIs and database support M7's computational needs (immutable states, scenarios, replay, multi-scenario optimization, long-running jobs), and is there a coherent run contract across engines?
**Verdict up front:** **READY_WITH_LIMITATIONS.** The by-value snapshot idiom (JSONB refs + checksums + field-scoped idempotency) generalizes cleanly to states and scenarios. The three structural debts are: (1) run contracts are inconsistent in exactly the places M7 must build on; (2) job execution is inline with no cancellation/progress; (3) checksums do not cover every scientifically material input (observation sets, boundary versions, problem-assessment values).

---

## 1. Capability-by-capability assessment

| M7 requirement | Current support | Evidence | Verdict |
|---|---|---|---|
| Immutable field state snapshots | **No state object exists**, but the pattern is proven three times over: water plans are new-rows-per-run with input+output checksums and idempotent replay; feature runs pin source selection + versions; rotation runs pin packs/runs/seed | `water/service.py:423-474,608-626`; `features/service.py:402-421`; `rotation/service.py:534-562` | READY (pattern) / NOT_IMPLEMENTED (object) |
| Scenario creation/execution/comparison | nothing exists; but create→execute→compare is exactly the existing run lifecycle; comparison exists within feature runs and within a rotation run | `features.py:159-168`; `rotation.py:311-350` | NOT_IMPLEMENTED (greenfield on ready idioms) |
| Calculation replay | **READY** — field-scoped idempotency keys on feature/rotation/water runs (IntegrityError race recovery on features); identical-input-same-checksum tests at every layer | `0005:36-51`; `features/service.py:228-240,425-438`; `test_plan_reproducibility_same_inputs_same_checksum`, `test_reproducible_runs_same_checksums` | READY |
| Multi-scenario optimization | post-hoc evaluation ready (solver-free validators); joint robust solver model not needed for v1 | `M7_0_ROBUST_OPTIMIZATION_READINESS.md` §2 | READY_WITH_LIMITATIONS |
| Long-running background jobs | **NOT READY** — all four run types execute inline in the request; job tables exist so a worker "can take over without contract changes" (stated design intent) | `ingestion/service.py:75-111`; grep: no BackgroundTasks/queue/threadpool use | NOT_IMPLEMENTED (deliberate deferral) |
| Cancellation | `cancelled` status exists in 3 of 4 status enums but **no code path ever sets it** | models.py:269,499,1000 vs 1087 | NOT_IMPLEMENTED |
| Progress tracking | record counters only (`records_received/rejected`, `records_written`); no fraction/stage reporting | run-contract table below | NOT_IMPLEMENTED |
| Tenant isolation | application-layer membership guards on every route; 403/404 semantics tested across all domains; **no RLS** | `identity/service.py:47-137`; `test_auth_tenant_isolation.py` | READY (app-layer) |
| Scenario provenance | provenance habits are platform-wide: evidence classes, per-value provenance JSONB, pack refs, versions, checksums | as-built §5 | READY (extend to scenario types) |
| Historical result preservation | append-only runs everywhere; **caveat:** `DELETE /water-plans/{id}` can remove a water snapshot; boundary versions & crop history & observations have no delete paths | `api/v1/water.py:155-167` | READY_WITH_LIMITATIONS (F-13) |

## 2. Idempotency & composite uniqueness (verified in live DB)

| Index | Definition | Status |
|---|---|---|
| `uq_ingestion_idempotency` | partial unique on `idempotency_key` **only** (no field_id) — 0001 legacy; runtime replay lookup also **not field-scoped** (`ingestion/service.py:78-83`); the UI never sends an ingestion key today | **DEBT F-30** (the F-03 composite fix was applied to feature/rotation only) |
| `uq_feature_run_idempotency` | `(field_id, idempotency_key)` WHERE key IS NOT NULL | correct |
| `uq_rotation_run_idempotency` | same composite | correct |
| `uq_water_plan_idempotency` | same composite | correct |
| `uq_observation_natural_key` | 6-column natural key → provider ingestion idempotent on retry | correct |
| `uq_crop_water_param` | NULLS NOT DISTINCT (F-18 deepening fix) | correct |

Cross-tenant idempotency replay was fixed for feature runs (F-03, migration 0005); **ingestion remains the one exception** — supplying a colliding key from another tenant could replay a job record (currently unreachable through the UI, reachable through the API).

## 3. The common computational run contract — actual discrepancies

The four implemented run-like resources compared on every contract dimension:

| Dimension | ingestion_jobs | feature_runs | rotation_runs | water_plans |
|---|---|---|---|---|
| Status enum | queued/running/succeeded/failed/cancelled/**retrying** | queued/running/succeeded/failed/cancelled | queued/running/succeeded/failed/cancelled | **running/succeeded/failed only** |
| Create status code | 202 | 202 | 202 | **201** |
| Idempotency | key-only unique; **non-field-scoped replay** | composite; field-scoped | composite; field-scoped | composite; field-scoped |
| Input snapshot | request_parameters JSONB | source_selection + versions + requested vars | pack refs + feature_run_ids + crop_history_ids + seasons + seed | methods + soil_inputs + seasons + assignments + allocation + pack refs + feature_run_ids |
| Model versions | provider processing_version | engine + catalog versions | rotation_engine_version + solver_name (+ **solver_version never populated**) | water_engine_version + methods_version + PTF version |
| Run-level checksum | **no** | **no** (per-value checksums only) | **no** (per-strategy checksums) | **yes** (inputs+versions+values) |
| Error handling | error_summary + records_rejected | error_summary + not_evaluated_reasons | error_summary + infeasibility_details + not_evaluated | error_summary + not_evaluated |
| Provenance | ingestion_job_id on observations; file_sha256 in params | per-value provenance JSONB (obs ids capped 400) | knowledge_pack_refs + evidence references in explanations | pack refs + per-source citations + feature_run_ids |
| Uncertainty | uncertainty_value/type per observation | uncertainty + coverage_ratio + baseline_reference | evidence_coverage (transparency metric) | PTF/SoilGrids PI notes; ladder statuses |
| Output serialization | _job_payload | run_payload | run_payload + strategies | plan_payload (result JSONB) |
| Deletion | no | no | no | **yes** |
| created_by surfaced in payload | no | no | no | no |

Soil assessment runs / nutrient budget runs / management plans: **NOT_APPLICABLE** (M6B/M6C absent) — any future run contract must be designed with the table above as the alignment target, not re-derived.

**Assessment:** the discrepancies are cosmetic-to-moderate (status vocabulary, HTTP code, timestamp columns, counter names) — none blocks M7, but every one of them would multiply into confusion across scenario result tables. A minimum harmonization (below) is warranted **before** M7.2.

## 4. Checksum coverage vs. scientifically material inputs

| Input material to results | Checksummed today? | Where |
|---|---|---|
| Pack contents | ✅ | `knowledge_packs.checksum_sha256` (content JSONB) |
| Pack set used by a run | ✅ | `knowledge_pack_refs` embed per-pack checksums; included in water plan checksum payload |
| Seasons/assignments/methods/allocation (water) | ✅ | `_plan_snapshot_checksum` |
| Soil inputs (water) | ✅ | inside `_plan_snapshot_checksum` (`soil_inputs`) |
| Feature source products (identity) | ✅ | `source_selection` pins product id+code+version |
| **The observation set itself** | ❌ | per-value provenance caps ids at 400; no run-level manifest hash — re-runs can absorb new ingestions (F-03) |
| **Boundary version used** | ❌ | nothing records it (F-01) |
| **Candidate assessment values** (rotation problem) | ❌ | problem checksum covers candidate *codes* only (F-19) |
| Solver configuration | partial | seed + name recorded; **solver_version never written** (F-20); options (workers=1, 10 s budget) in code, not in the row |
| Farmer-supplied economics/efficiencies | ✅ via request_parameters + methods JSONB | but not separately hashed |

## 5. Minimum set of common primitives proposed (no universal abstraction)

Existing domain differences justify keeping separate contracts (water is a synchronous plan; ingestion is a job with counters; rotation has solver semantics). The **minimum shared primitives** that would materially improve interoperability for M7:

1. **Run envelope (serialization only, not a table):** `{id, kind, status, created_by, created_at, started_at, completed_at, idempotent_replay: bool, warnings, not_evaluated, error, request_parameters, input_refs[], model_versions{}, checksum}` — a projection each payload already almost satisfies; aligning names closes discrepancy rows 1/4/5/6/8 of §3.
2. **`input_refs` convention:** the existing `knowledge_pack_refs` shape `{id, code, version, status, checksum}` generalized to *any* pinned artifact (feature runs, boundary versions, constraint rows, future scenarios) — pure convention, no new machinery.
3. **Timestamps:** add `started_at`/`completed_at` to `water_plans` (or accept plan ≠ job and document it).
4. **Observation manifest hash:** feature runs add a cheap hash over the sorted contributing observation ids (full set, uncapped) → closes F-03 without storing the set.
5. **Deletion policy:** water plan DELETE becomes archive-or-restrict when referenced (F-13) — one guarded change.
6. **`created_by` surfaced** in all run payloads (F-09/F-17).
7. **Solver version** written per rotation run (F-20).

These are additive, migration-light, and each independently testable — suitable as part of M7.1/M7.2 rather than a big-bang refactor.

## 6. Findings register

| ID | Severity | Domain | Affected | Current | Expected | Impact | Blocks M7? |
|---|---|---|---|---|---|---|---|
| F-29 | High | Platform | no worker/cancellation/progress | inline execution, unreachable `cancelled` | worker queue for multi-scenario batches; cancellation; progress events | UX + scale; contract already anticipates it | No (M7.5 design task) |
| F-30 | Medium | Data platform | ingestion idempotency | key-only unique + non-field-scoped replay | apply the F-03 composite fix + scoped lookup | cross-tenant replay edge case (API-only reachability today) | No |
| F-31 | Medium | Features | no run-level checksum/manifest | capped obs ids only | manifest hash primitive (§5.4) | replay guarantees under new ingestions | No |
| F-32 | Medium | Water | no started/completed; 201 vs 202; deletable snapshots | run-contract drift | harmonize per §5 | consistency for scenario result tables | No |
| F-33 | Low | All | created_by never surfaced; list payload keys differ (`items`/`runs`) | payload drift | envelope alignment | minor | No |
| F-34 | Low | Rotation | solver_version unwritten; problem checksum excludes assessment values | provenance gaps | write version; hash assessment payloads | diagnostics | No |

## 7. Readiness verdict

| Capability | Status |
|---|---|
| Immutable snapshots (pattern) | **READY** |
| Idempotency & composite uniqueness | **READY_WITH_LIMITATIONS** (ingestion debt F-30) |
| Calculation replay | **READY** |
| Tenant isolation | **READY** (app-layer) |
| Scenario creation/execution/comparison | **NOT_IMPLEMENTED** on ready idioms |
| Background jobs / cancellation / progress | **NOT_IMPLEMENTED** (inline by design; worker path pre-planned) |
| Common run contract | **PARTIAL** — 11 discrepancy rows documented; 7-primitive harmonization proposed |
| Checksum coverage of material inputs | **PARTIAL** — packs/methods/soil covered; observation set, boundary version, assessment values not |
| Historical result preservation | **READY_WITH_LIMITATIONS** (water DELETE caveat) |

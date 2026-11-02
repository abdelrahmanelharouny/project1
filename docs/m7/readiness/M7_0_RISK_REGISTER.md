# M7.0 — Risk & Findings Register

**Inspection date:** 2026-11-01 · **Consolidates** every finding raised across the M7.0 document set (IDs are stable and cross-referenced). Severity per spec §13: Critical (security/data integrity/scientifically invalid integration) · High (prevents reliable field-state assembly, reproducibility, scenario execution, or robust optimization) · Medium (completeness/usability/interpretability/maintainability) · Low (optional).

---

## 1. Critical findings

**None.** No security, data-integrity, or scientifically-invalid integration was found that would undermine a future M7 model. Tenant isolation is consistently enforced (app-layer, tested cross-domain); honesty contracts (missing≠zero, evidence classes, named infeasibility) are enforced everywhere inspected; no engine modifies historical results.

## 2. High findings (full format)

### H-01 (F-01) — Computed results are not pinned to the field boundary version they used
- **Domain:** Farm/Field ↔ all computational domains · **Affected:** no column anywhere referencing `field_boundary_versions`; `observations`/`feature_runs`/`rotation_runs`/`water_plans` reference `field_id` only
- **Current:** ingestion and any geometry-dependent computation resolve the *current* `fields.boundary` at execution time (`app/data_platform/ingestion/service.py:266-275`)
- **Expected:** results (and future states) record the boundary version in effect
- **Evidence:** `M7_0_CROSS_DOMAIN_MAP.md` INT-12; grep `boundary_version` — referenced only by the farms_fields domain
- **Reproduction:** create field → ingest → compute → update boundary → re-compute: both result sets carry no trace of which geometry they used
- **Impact on M7:** Field States cannot guarantee geometric provenance; a boundary edit silently recontextualizes comparisons
- **Proposed resolution:** M7.1 additive `boundary_version` pinning on new artifacts + state composition
- **Dependency:** M7.1 · **Blocks M7?** No (states can pin going forward); degrades historical states

### H-02 (F-03/F-31) — Environmental snapshots are only partially pinned (no run-level manifest/checksum)
- **Domain:** Features · **Affected:** `feature_runs` (no run-level checksum; `provenance.observation_ids` capped at 400, `app/features/engine.py:34`)
- **Current:** products & methodology pinned; the observation set is not — re-runs can absorb newly ingested rows of the same product
- **Expected:** bit-reproducible environmental snapshots (manifest hash over contributing observation ids)
- **Evidence:** INT-03; tests acknowledge (`test_reproducibility_same_data_same_checksums` holds only for static data)
- **Reproduction:** run feature run → ingest new rows for same product window → re-run with same params → different values, no tamper indicator
- **Impact on M7:** scenario replays and state re-assembly are not bit-stable under new ingestions
- **Proposed resolution:** cheap uncapped sorted-id manifest hash per run (M7.1)
- **Dependency:** M7.1 · **Blocks M7?** No (workaround: document + pin by run id), but weakens L2-twin claims

### H-03 (F-04/F-07) — Soil and Management domains absent (M6B/M6C NOT_IMPLEMENTED)
- **Domain:** Soil / Management · **Affected:** no tables, engines, APIs, or UI for either domain
- **Current:** only proxies (SoilGrids/farmer-CSV soil observations; cover-crop flags & criteria)
- **Expected:** either M6B/M6C implementation (out of M7.0 mandate) or honest `not_implemented` dimensions
- **Evidence:** `M7_0_BASELINE.md` §1; as-built §4.6–4.7; frontend tab inventory (7 tabs, no Soil/Management)
- **Reproduction:** repository tree inspection; `alembic history` ends at 0006
- **Impact on M7:** soil dimension of Field State and the management scenario axis are impossible until M6B/M6C exist
- **Proposed resolution:** ship M7 with honest NOT_IMPLEMENTED dimensions (recommended); schedule M6B/M6C separately
- **Dependency:** program decision · **Blocks M7?** Conditionally — blocks soil/management scenario axes only

### H-04 (F-29) — No background execution, cancellation, or progress for run-like work
- **Domain:** Platform/computation · **Affected:** all four run types execute inline; `cancelled` unreachable in 3/4 enums
- **Current:** 202 responses are de-facto synchronous
- **Expected:** worker queue + cancellation + progress events for multi-scenario batches
- **Evidence:** `ingestion/service.py:75-111` (stated deferral); grep — no BackgroundTasks/queue
- **Reproduction:** any run; no progress field exists
- **Impact on M7:** M7.5 batch evaluation UX/scale; contract already anticipates a worker
- **Proposed resolution:** worker + progress in M7.5 scope (design now, implement then)
- **Dependency:** M7.5 · **Blocks M7?** No for M7.1–M7.4; conditional for M7.5 at scale

### H-05 (F-12) — Engines lack an explicit climate-context override (virtual perturbation path)
- **Domain:** Water/Rotation engines · **Affected:** planner + candidates read climatology from a feature run
- **Current:** the only way to feed different climate is a different (real or fixture) feature run
- **Expected:** versioned `climate_context` input contract (virtual, never materialized as observations)
- **Evidence:** `M7_0_SCENARIO_READINESS.md` §3 fork
- **Reproduction:** attempt scenario ΔT — no supported injection point
- **Impact on M7:** M7.3 transformations need this to avoid polluting the observation store
- **Proposed resolution:** extend engine input contracts in M7.3 with regression that no-override = bit-identical behavior
- **Dependency:** M7.3 · **Blocks M7?** No (M7.3 scope)

## 3. Medium & Low findings (consolidated table)

| ID | Sev | Domain | Current behavior (evidence) | Expected / resolution | Blocks M7? |
|---|---|---|---|---|---|
| F-02 | Med | Assembly | no period-compatibility validation across domains | M7.1 assembly checks + records mismatches | No |
| F-05 | Med | Water | plans only exist when explicitly requested | state assembly queries/triggers plan calc; absence expressed | No |
| F-06 | Med | Rotation | runs are experiments, not general state | state references run+strategy id explicitly | No |
| F-08 | Med | Knowledge | "active pack set at T" only reconstructable where runs stored refs | state stores resolved pack set (copy idiom) | No |
| F-09/F-17/F-20/F-33 | Med/Low | All runs | `created_by` never surfaced; list keys differ; solver_version unwritten | envelope alignment (API doc §5) | No |
| F-10 | Med | Assembly | no staleness policy | per-dimension staleness semantics in M7.1 | No |
| F-11 | Med | Knowledge | cross-pack conflicts silently resolved by F-9 ordering | state exposes "conflicting" dimension or provenance of resolution | No |
| F-13 | Med | Water | `DELETE /water-plans/{id}` can remove snapshots | archive/restrict when referenced | No |
| F-14 | Med | Scenarios | no scenario evidence classes | add per-type classes ("never equivalent to observed") | No |
| F-15 | Med | Data platform | no issue-time/horizon metadata | needed only for M7.8 | No |
| F-16 | Low | Rotation | latest-succeeded feature run default | scenarios always pin explicit run ids | No |
| F-18 | High* | Rotation | no scenario × strategy result tables | new by-ref tables in M7.5 (*classification: "High" as future-work item, not a defect) | No |
| F-19 | Med | Rotation | problem checksum excludes assessment values | hash assessment payloads | No |
| F-21 | Med | Objectives | normalization is per-run-set | union-set normalization design for cross-scenario criteria | No |
| F-22 | Low | Optimizer | 10 s global budget per solve | fine per-scenario; note for outer loops | No |
| F-23 | Med | Engines | same as F-12 | shared resolution | No |
| F-24/F-25/F-26/F-27/F-28 | Med/High*/Low | Twin | state object, calibration, feedback, soil/mgmt lanes, sync — see twin doc | M7.1/M7.7 scope; L4/L5 permanently gated on real data | No (L4/L5 out of scope) |
| F-30 | Med | Ingestion | key-only idempotency + non-scoped replay | apply F-03 composite fix + scoped lookup | No |
| F-32 | Med | Water | no started/completed; 201 vs 202; deletable | harmonize | No |
| F-34 | Low | Rotation | solver_version unwritten; checksum gap | write version; hash values | No |
| F-35/F-36/F-37/F-38/F-39 | Med/Low | Frontend | long-run UX, a11y audit, typecheck script, JobStatus type, cross-run compare UI | per frontend doc | No |
| Superseded-pack retirement untested | Med | Knowledge | `seed_default_packs` retirement path has zero tests | add regression test (no behavior change) | No |
| Warnings debt (2,407 pytest warnings) | Low | Backend | SAWarning `metadata` ×2; rasterio PendingDeprecation ×~2,300 | cosmetic; track upstream | No |

## 4. Security & reproducibility posture (summary)

| Aspect | Posture | Evidence |
|---|---|---|
| Tenancy | app-layer membership guards on every route; 403/404 semantics tested | `test_auth_tenant_isolation.py`; cross-tenant tests in every domain suite |
| Secrets/tokens | opaque 256-bit tokens hashed at rest; PBKDF2 120k; expiry+revocation | `security.py` |
| Injection/SQL | SQLAlchemy ORM throughout; no raw string SQL found in app paths | code review |
| Reproducibility | checksums at pack/strategy/plan/value level; seeded solver; idempotent replays | tests cited across docs |
| Audit trail | audit_events with before/after snapshots on writes | F-14 fixed (deepening) |
| Residual risks | no RLS (accepted, app-layer proven); ingestion idempotency edge (F-30); water-plan deletion (F-13) | this register |

## 5. Top remediation priorities (recommended order)

1. **F-01 boundary pinning** (M7.1) — cheapest, highest provenance leverage.
2. **F-31 observation manifest hash** (M7.1) — completes snapshot reproducibility.
3. **F-13 deletion policy** (M7.1) — one guarded change protecting immutability claims.
4. **F-30 ingestion idempotency composite fix** (M7.1 hygiene) — closes the last F-03 gap.
5. **Run-envelope harmonization** (M7.1/M7.2) — prevents drift multiplying into scenario tables.
6. **F-12 climate-context contract** (M7.3) — enables the scenario engine cleanly.
7. **Worker + progress + cancel** (M7.5) — only when batch scale demands it.

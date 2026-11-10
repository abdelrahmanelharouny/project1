# M7.0 — Final Readiness Report

**Project:** CropTwist — Global Agricultural Decision Intelligence Platform
**Inspection:** Cross-Domain Integration Audit, Field State Architecture & Digital Twin Readiness
**Date:** 2026-11-01 · **Mode:** repository-first, evidence-driven, read-only · **Scope:** M1–M6C
**Deliverable set:** this report + 12 companion documents in `docs/m7/readiness/`

---

## 1. Executive summary

CropTwist was reported to be at "M6C complete" (742 tests, migration 0008 at head). **The repository does not corroborate that.** Independent inspection establishes the actual state as **M6A complete**: 441/441 backend tests pass freshly (0 skipped, 161.7 s), frontend lint is clean, migration head is `0006_water_intelligence`, and the browser exposes exactly seven tabs (Overview, Farms & Fields, Observations, Features, Rotation, Water, Data Passport) with zero console errors — **no Soil tab, no Management tab, no `app/soil/`, no `app/management/`, no migrations 0007/0008**. The M6C engineering prompt exists only as an untracked upload that was never implemented.

This discrepancy is itself the single most consequential inspection finding: **M7 planning must proceed from the real M6A baseline**, which is nonetheless strong. Five domains are genuinely production-grade with unusual provenance discipline: versioned knowledge packs (checksummed, lifecycle-managed), reproducible feature runs, a deterministic CP-SAT rotation optimizer with named infeasibility, an FAO-56/FAO-33 water engine with honest refusal paths, and field/boundary versioning with geodesic area cross-checks.

Against the strategic objective, the platform can support the M7 vision **conditionally and incrementally**:

- **Unified Field State:** READY_WITH_LIMITATIONS — 10 of 14 conceptual fields map to existing, already-versioned producers; the assembly layer is missing but nothing needs duplicating; boundary pinning (H-01) and observation-manifest hashing (H-02) must land in M7.1.
- **Scenario Engine:** READY_WITH_LIMITATIONS for historical-observed, historical-perturbation and user-defined stress scenarios; NOT_IMPLEMENTED (correctly) for projections/forecasts; BLOCKED for management scenarios until M6C exists.
- **Multi-scenario rotation evaluation:** READY_WITH_LIMITATIONS — the solver-free constraint validators and post-hoc criteria evaluators make cross-scenario scoring possible without touching the optimizer.
- **Field Digital Twin:** honestly **Level 1 (Historical Digital Profile)** with strong Level-2 ingredients; Level 4/5 claims are unsupported and must not be made.

**Decision: CONDITIONAL GO** — GO for M7.1–M7.7 with the specified sequencing and honesty constraints; **NO-GO for M7.8** until sourced projection/forecast data with license and methodology exists. Full decision rationale in §13.

## 2. Fresh verification baseline

All values re-established in this session (`M7_0_BASELINE.md` for details):

| Check | Result |
|---|---|
| Backend tests | **441 passed, 0 failed, 0 skipped** (161.73 s; 2,407 benign warnings: 2 SAWarning `metadata`, ~2,300 rasterio PendingDeprecation, 1 TestClient deprecation) |
| Frontend lint | exit 0 |
| Migration head (code & DB) | `0006_water_intelligence` (chain 0001→0006) |
| PostgreSQL / PostGIS | 18.6 / 3.7.0 (user-space cluster restored via repo scripts; no data destroyed) |
| Schema | 32 app tables; GiST on `fields.boundary` only; 4 idempotency indexes (ingestion one is legacy key-only); no RLS |
| Browser | all 7 tabs render; demo workspace works; **zero console/page errors**; mobile 390 px no horizontal overflow; sticky footer intact (screenshots `tool-results/m70-*.png`) |
| Git | `main` @ `71a8c34`; M6A files present as uncommitted working-tree state; UUID-only commit messages (history is not milestone-labelled) |

Milestone presence: M1–M5 + Pre-M6 + M6A **PRESENT** · M6B **NOT IMPLEMENTED** · M6C **NOT IMPLEMENTED** · M7 not started (correct).

## 3. Actual cross-domain architecture

Full graph and 17-row connection register in `M7_0_CROSS_DOMAIN_MAP.md`; as-built detail in `M7_0_AS_BUILT_ARCHITECTURE.md`. Key structure:

- **Integration idiom:** pinned-by-value references (JSONB refs + checksums), not FKs — used for pack refs, feature-run refs, crop-history refs; the idiom generalizes to states/scenarios.
- **Verified integrations (V):** fields↔farms; observations↔products/sources; feature runs→source selection; knowledge→candidates (cited reasons); crop-history→rotation; feature-runs→rotation & water (climate bridge); Kc knowledge→water; NIR→CP-SAT allocation; passport→observations; audit trail→writes.
- **Partial (P):** feature-run→observation-set pinning (capped); boundary→results (unpinned); soil evidence→consumers (latest-value reads); `farm_constraints` (unversioned mutable input); knowledge retirement (untested path).
- **No integration (N):** rotation↔water plans (value coupling only, no linkage column); management domain (absent).
- **Test coverage:** every V connection has named integration tests; tenant isolation tested in all domains.

## 4. Field State readiness (`M7_0_FIELD_STATE_READINESS.md`)

- 10/14 proposed `FieldStateSnapshot` fields satisfied **by reference** to existing tables; no duplication required.
- Temporal: every domain records explicit periods (shared `seasons` idiom for rotation/water; `crop_seasons` for features; real dates for history) — but **no cross-domain period-compatibility validation exists** (must be built in M7.1).
- Spatial: per-dimension support metadata is honest (grid_cell vs polygon_average vs point; resolution recorded); boundary-version pinning missing (H-01).
- Completeness: all ten required dimensions (available/missing/insufficient/stale/N-A/not-evaluated/conflicting/synthetic/farmer-reported/expert-validated) are **already carried by existing enums**; no generic score needed or wanted.
- Soil & management dimensions: BLOCKED (H-03) — ship as honest `not_implemented`.

## 5. Scenario Engine readiness (`M7_0_SCENARIO_READINESS.md`)

- Taxonomy feasibility: historical-observed / perturbation / user-stress **supportable now**; projection & forecast **NOT_IMPLEMENTED (no data, by design)**; management **BLOCKED on M6C**.
- Contract: proposed scenario schema supportable with existing idioms (JSONB config + checksums + field-scoped idempotency + by-value refs); immutability precedent proven by water-plan reruns (new rows, checksums, replay tests).
- Perturbation semantics: physical-consistency rules expressible today (precip ≥ 0 clamp, unit-explicit ΔT, monthly-scaling caveat, allocation changes first-class, initial soil-water condition settable); key design fork F-12: perturbations must travel as a **virtual climate context** in engine input contracts — never materialized as observations, never labelled `synthetic_test_data`.
- Missing inputs: verified refusal paths exist everywhere (baselines ≥5 years, ≥90% month coverage, incomplete Kc anchors rejected, PTF domain enforcement, faba-bean honest gap) — "generation must not create evidence" is already institutionalized.

## 6. Robust optimization readiness (`M7_0_ROBUST_OPTIMIZATION_READINESS.md`)

- The decisive architectural fact: hard constraints exist as **solver-free validators** and criteria as **pure post-hoc evaluators** (by design), so scenario feasibility, feasibility-robustness fractions, worst-case over declared bounds, regret, and sensitivity analysis are all computable **without modifying the optimizer**.
- Determinism prerequisites are READY (seed=0, single worker, checksums, reproducibility tests).
- Expected-performance over probabilities is **NOT_APPLICABLE today** — no justified probability model or sourced ensemble exists; the spec's warning (scenario counts ≠ probabilities) matches the platform's existing honesty vocabulary.
- Solver-level joint robust optimization is NOT_IMPLEMENTED and not required for v1.

## 7. Digital Twin maturity (`M7_0_DIGITAL_TWIN_READINESS.md`)

| Level | Verdict |
|---|---|
| L0 Static record | ACHIEVED |
| L1 Historical digital profile | **ACHIEVED WITH GAPS** (soil thin, management absent) — highest genuine level |
| L2 Versioned field state | PARTIAL — all ingredients exist; assembly missing (M7.1) |
| L3 Scenario-capable model | PARTIAL — engines ready; scenario layer missing |
| L4 Calibrated predictive twin | NOT_IMPLEMENTED — no calibration framework, no real-farm dataset; must not be claimed |
| L5 Operationally connected twin | NOT_IMPLEMENTED — no automated sync or validated feedback |

The existing dashboard is decision support, not a twin; any twin-facing UI must carry maturity labelling and must never claim predictive behavior.

## 8. Data gaps (`M7_0_DATA_GAP_REGISTER.md`)

All eight documented limitations re-verified in code. Classification: **none of M7.1–M7.6 is blocked by any of them**; G-6/G-7 (soil observations, operations data) block only their own scenario axes; G-1/G-2 (forecast, DEM) block only M7.8-type capabilities; G-8 blocks L4 twin claims only. Historical sensitivity analysis does **not** require forecasts; environmental scenario functionality does **not** require DEM. Future data opportunities (NASA EO, DEM products, projection ensembles, forecast providers, stations, sensors) are catalogued as future adapters against the existing provider protocol — NASA connectors remain out of scope (unchanged decision).

## 9. Security & reproducibility risks

- **No Critical findings.** Tenant isolation is consistently enforced and tested app-layer (no RLS — accepted, documented). Tokens hashed at rest; PBKDF2 120k; error envelope with request IDs; audit events with before/after snapshots.
- Reproducibility posture is strong but has two holes (H-01 boundary pinning, H-02 observation manifest) plus minor checksum gaps (F-19/F-20) — all remediable additively in M7.1.
- One cross-tenant idempotency edge remains in ingestion (F-30; API-only reachability today).
- Water-plan DELETE undermines strict immutability claims (F-13).

## 10. Prioritized remediation list

1. **H-01** boundary-version pinning on computed artifacts (M7.1, additive columns).
2. **H-02** per-run observation-manifest hash (M7.1).
3. **F-13** deletion policy for referenced water plans (M7.1).
4. **F-30** ingestion idempotency composite fix + scoped replay (M7.1 hygiene).
5. **Run-envelope harmonization** (7 primitives, API doc §5) incl. `created_by` surfacing, water timestamps, status vocabulary (M7.1/7.2).
6. **F-12** virtual climate-context engine contract (M7.3).
7. **H-04** worker + cancellation + progress (M7.5, when batch scale demands).
8. Medium/Low hygiene: retirement-path test, solver_version write, assessment-value checksum, frontend typecheck script, a11y pass, warning debt.

## 11. Recommended M7 architecture

Composition over the existing run-snapshot idiom — **no universal abstraction, no duplication**:

- `field_states` — by-reference composition of boundary version + feature-run/environmental refs (+ manifest hash) + pack-ref set + water/rotation/crop-history refs; per-dimension evidence/quality maps; staleness policy; checksum.
- `scenarios` — typed definitions (6 types) parented on states; immutable after creation; checksummed configs; per-type evidence classes; RESTRICT on referenced runs.
- Virtual **climate context** as a versioned engine input contract (M7.3) — engines remain unmodified when no override is given (bit-identical regression required).
- `scenario_evaluations` — strategy × scenario results from the existing solver-free validators + criteria evaluators; feasibility fractions worded "of declared scenarios".
- Run-envelope alignment (serialization convention) rather than a new ORM layer; domain contracts stay separate where differences justify it.
- Frontend: two new tabs (Field State incl. timeline; Scenarios incl. compare) + shared EvidencePanel; new scenario-type badges; honesty vocabulary reused verbatim.

## 12. Recommended M7 implementation sequence

As evaluated in `M7_0_IMPLEMENTATION_SEQUENCE.md` — the proposed M7.1→M7.8 order is **confirmed** with adjustment A1 (pull boundary-pinning, manifest hash, deletion policy, ingestion idempotency, envelope harmonization into M7.1) and scope guard A2 (M6B/M6C stay out of M7; soil/management ship as honest NOT_IMPLEMENTED dimensions):

**M7.1** Field State & snapshot contracts → **M7.2** Scenario domain → **M7.3** Historical & stress transforms → **M7.4** Sensitivity & uncertainty → **M7.5** Multi-scenario rotation evaluation → **M7.6** Robustness & decision stability → **M7.7** Twin timeline & visualization → **M7.8** External projections/forecasts (conditional, data-gated, last).

Each increment's dependencies, modules, schema/API needs, scientific references, complexity, risks, and acceptance criteria are specified in that document. Cross-cutting acceptance rules: labels + versions + refs + checksums on every artifact; missing → not_evaluated/not_implemented with reasons; determinism regression-tested; tenant isolation on every new route; mobile 390 px + desktop browser verification; no M6B/M6C scope creep; no predictive claims.

## 13. Decision

> ### **CONDITIONAL GO**

**GO** for M7.1–M7.7 on the actual M6A baseline, because:
1. The fresh baseline is verified healthy (441/441 tests, lint clean, migrations at head, browser-verified, zero console errors).
2. Every M7.1–M7.6 capability is supportable by composition over proven, tested idioms — with **no duplication of existing domain models** and **no modification of engine behavior** required before M7.3's contained contract extension.
3. The honesty architecture (evidence classes, refusal paths, named infeasibility, checksums) is exactly the foundation the spec demands for defensible states and scenarios.

**Conditions** (each is an acceptance criterion already embedded in the sequence):
- C1: M7.1 lands the four hygiene items (boundary pinning, manifest hash, deletion policy, ingestion idempotency) **before** M7.2 builds on states.
- C2: Scenario types are never presented as equivalent evidence (per-type labels enforced in payloads, API, and UI).
- C3: Soil and management dimensions ship as explicit NOT_IMPLEMENTED — no proxy claims.
- C4: No calibrated/predictive (L4/L5) language anywhere until a real calibration dataset exists.
- C5: M7.8 does not begin until a sourced, licensed projection/forecast dataset and methodology exist.

**NO-GO** today for M7.8 (no data, no methodology, no metadata model) and **NO-GO** for any soil-health, nutrient-budget, or management-scenario functionality within M7 (M6B/M6C are unimplemented; that is separate scope).

**Governance note (recorded, not actionable here):** the reported "M6C complete / 742 tests / migration 0008" state does not correspond to this repository. M7 planning and estimation must use this report's verified M6A baseline; if an M6B/M6C implementation exists elsewhere, it must be reconciled with (or re-delivered into) this repository before its capabilities can be assumed by any milestone.

---

### Companion documents

| Document | Content |
|---|---|
| `M7_0_BASELINE.md` | fresh verification baseline & milestone reality |
| `M7_0_AS_BUILT_ARCHITECTURE.md` | as-built system, module map, schema, six domains |
| `M7_0_CROSS_DOMAIN_MAP.md` | dependency graph + 17-connection register |
| `M7_0_FIELD_STATE_READINESS.md` | Phase C assessment + findings |
| `M7_0_SCENARIO_READINESS.md` | Phase D assessment + findings |
| `M7_0_ROBUST_OPTIMIZATION_READINESS.md` | Phase E assessment + findings |
| `M7_0_DIGITAL_TWIN_READINESS.md` | Phase F maturity classification |
| `M7_0_DATA_GAP_REGISTER.md` | Phase G gaps + impact matrix |
| `M7_0_API_AND_DATABASE_READINESS.md` | Phase H run-contract audit + primitives |
| `M7_0_FRONTEND_READINESS.md` | Phase I UX audit + interface proposal |
| `M7_0_RISK_REGISTER.md` | consolidated findings H-01…F-39 |
| `M7_0_IMPLEMENTATION_SEQUENCE.md` | Phase J increment specifications |

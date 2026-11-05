# M7 — Consolidated Completion & Verification Report

Date: 2026-11-02 · Branch: `main` · Baseline at start: `2a99eeb5` (M7.4)
Final commits: `91dab742` (M7.5) → `aec0a0f5` (M7.6) → `5499df7c` (M7.7) → `32f1a692` (E2E fixes + docs)

## 1. Executive summary

M7.5, M7.6 and M7.7 were implemented, tested and browser-verified as one
coherent system on top of the existing M5 rotation engine, M7.3 scenario
execution engine, M7.4 sensitivity engine, Field State layer and workspace
frontend. The M7.8 readiness gate was evaluated and **M7.8 remains blocked**
(no real climate projection or forecast provider exists — nothing fabricated).

| Milestone | Deliverable | Commit | Tests |
|---|---|---|---|
| M7.5 | Scenario sets (BY-VALUE member pins), cross-scenario candidate pool, ONE shared CP-SAT plan with maximin steering, per-scenario M5 post-hoc evaluation, worst-case objective + minimax regret + robust feasibility, water allocation rejected (scenario ET0 unavailable), migration 0011 + freeze triggers, 9 API endpoints, Robust Plan tab | `91dab742` | 10 unit + 26 integration |
| M7.6 | Unified checksummed decision documents over stored artifacts (same-unit-only rankings, evidence-linked findings, trade-off matrix, missing-evidence section incl. structural ET0/water + no-forecast items), migration 0012 + freeze triggers, 4 API endpoints, Decisions tab | `aec0a0f5` | 13 integration |
| M7.7 | Traceable field-level twin view (identity, snapshots, coverage & freshness, scenario lineage tree, information-class census, capability/readiness matrix, honest maturity classification), bounded integrity validation walk reusing per-artifact verifiers, migration 0013, 3 API endpoints, Digital Twin tab | `5499df7c` | 9 integration |
| cross | Browser E2E fixes (strategies in run detail, 2023 season presets, prerequisite text, stale head assertions) + documentation package | `32f1a692` | — |

## 2. Verification evidence

### 2.1 Phase 0 baseline (independently verified, not assumed)

- Branch `main` @ `2a99eeb5`, working tree clean; `m6b-m6c-wip` present and
  untouched throughout (no checkout, no merge, no modification).
- Migration head `0010_sensitivity_analysis`; **742 tests collected, all
  passing** (496 unit+contract, 246 integration — the integration suite was
  executed in 5 groups after a full-suite runner hit the sandbox tool
  timeout).
- Pre-existing frontend defects found and fixed as in-scope: 3 TypeScript
  errors (`JobStatus` missing `'cancelled'` ×2, `Record<string,unknown>`
  ReactNode ×1) — `tsc --noEmit` was failing at baseline; it is clean now.

### 2.2 Final regression (this task)

- Backend: **800 tests, all passing** = 506 unit+contract + 294 integration
  (246 pre-existing + 48 new: robust 26, decision 13, twin 9; plus 10 new
  unit tests counted in the 506).
- `bun run lint` clean; `npx tsc --noEmit` clean (src/).
- Migrations `0011`/`0012`/`0013` applied to the dev DB; head `0013_digital_twin`;
  downgrade paths implemented; trigger immutability verified by tests
  (UPDATE/DELETE raise on result-bearing rows for M7.5/M7.6 artifacts).
- Browser E2E (agent-browser, demo synthetic workspace):
  - Robust Plan tab: set → robust run `OPTIMAL (proven)` over 2 scenarios;
    shared-plan table (assignments, worst-case 0.55–0.625, regret 0, robust
    feasible); ET0-not-evaluable and synthetic-evidence disclosures; 5
    cross-scenario exclusion records with agronomic reasons; verify →
    `verified`.
  - Decisions tab: evidence-linked findings (scenario changes with units and
    periods, plan feasibility with worst-case objectives, sensitivity slopes
    with units + classifications), plan feasibility table, RAW trade-off
    matrix, verify → `verified`.
  - Digital Twin tab: information-class census (2190 observed / 7280
    transformed / 198 calculated), capability matrix, honest maturity,
    **Validate now → "Twin consistent — 19/19 artifacts verified"**.
  - Layout: 1280 px and 390 px verified; sticky footer at viewport bottom on
    short pages and pushed down naturally on tall pages; zero console errors.
- Reproducibility chain: scenario executions, robust runs, decision documents
  and twin validations are all fingerprinted, checksummed and re-verified by
  POST `verify` endpoints (all return verified in E2E).

## 3. Scientific-integrity highlights

- One shared plan, genuinely robust: candidates restricted to the
  cross-scenario admissible pool with per-crop exclusion records; maximin
  steering; per-scenario post-hoc M5 evaluation; **worst-case objective
  reported only when evaluable in every scenario**.
- Water honesty: scenario ET0 structurally unavailable → water criteria not
  evaluable per scenario → `water_allocation_m3` **rejected** with
  `WATER_ALLOCATION_UNSUPPORTED` (never silently dropped).
- FEASIBLE vs OPTIMAL preserved end-to-end (UI badge distinguishes them).
- M7.6 documents: no composite scores / probabilities / yield predictions /
  universal recommendations (integration-tested at the key level); rankings
  only within the same unit; every finding carries source references.
- M7.7 twin: observed vs transformed vs calculated census; data-driven
  capability readiness; honest maturity classification
  ("observational-analytical field twin (no forecasting)"); no predictive or
  autonomous claims.
- Deterministic replay and immutability everywhere (fingerprints, checksums,
  unique constraints, freeze triggers, append-only validations).

## 4. M7.8 readiness gate (evaluated, BLOCKED)

Inspected the data-platform registry and providers: `synthetic_environment`,
`era5_land`, `era5`, `chirps_v3_*`, `soilgrids_2020_isric`, `farmer_record`,
and the Open-Meteo adapter — which calls the **historical archive API only**
(no forecast endpoints). No CMIP/CORDEX/SSP/RCP or NWP forecast provider,
license path or validation protocol exists. Scenario types
`climate_projection` / `weather_forecast` are contract-only rejects
(M7.2 condition C5). **Decision: M7.8 stays blocked.** Exact prerequisites
are documented in `docs/m7/M7_LIMITATIONS_AND_UNAVAILABLE_CAPABILITIES.md` §1.

## 5. Documentation

- `docs/m7/m7_5/M7_5_ROBUST_METHOD.md`
- `docs/m7/m7_6/M7_6_DECISION_INTELLIGENCE.md`
- `docs/m7/m7_7/M7_7_ARCHITECTURE.md`
- `docs/m7/M7_LIMITATIONS_AND_UNAVAILABLE_CAPABILITIES.md`
- `docs/implementation/IMPLEMENTATION_STATUS.md` + `TEST_MATRIX.md` updated.
- This report: `docs/m7/M7_COMPLETION_REPORT.md`.

## 6. Remaining limitations (summary)

- Steering sensitivity is scenario-driven through temperature screening and
  water-evidence availability only; per-scenario criteria differences are the
  substantive signal (documented).
- Worst-case objective/regret are comparable within a run, not across runs.
- M7.6 documents are bounded assemblies (monthly+seasonal rows, caps
  documented in payloads and docs).
- The twin view is computed per request (no materialization) and the
  validation walk is bounded to the newest artifacts per class.
- M6B (soil) / M6C (management) remain absent from `main`; the platform's
  domain maps report them as not implemented (unchanged).

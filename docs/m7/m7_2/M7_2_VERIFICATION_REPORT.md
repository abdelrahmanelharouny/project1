# M7.2 — Final Verification Report

**Milestone:** M7.2 — Scenario Domain & Immutable Scenario Definitions
**Verdict:** **COMPLETE — all 17 acceptance criteria met**
**Execution protocol:** Inspect → Design → Implement → Migrate → Test → Browser Verify → Document ✅

---

## 1. Repository identity (final)

| Item | Value |
|---|---|
| Branch | `main` |
| Baseline commit (Phase 0, verified before any change) | `15013c7` — M7.1 field state foundation, clean tree |
| Implementation commit | `cfbf112` — "M7.2: scenario domain & immutable scenario definitions (taxonomy, contracts, validation engine, lifecycle, lineage, comparison, APIs, Scenario Workspace, migration 0008 + trigger)" |
| Working tree after commit | clean |
| Migration head | **`0008_scenario_domain`** (revises `0007_field_state_foundation`) |
| M7.0/M7.1 documents | preserved untouched (`docs/m7/readiness/` ×13, `docs/m7/m7_1/` ×6) |

## 2. Verification results

### 2.1 Backend

| Check | Result |
|---|---|
| Full regression (`pytest tests/`) | **581 passed, 0 failed, exit 0** = 490 baseline (M1–M7.1) + 91 new M7.2 |
| New unit tests | 45 (contracts 26, validation engine 19) |
| New integration tests | 43 (API/lifecycle/lineage/protection/comparison/security) |
| New migration tests | 3 (scratch-DB upgrade; trigger freeze via raw SQL; downgrade + re-upgrade) |
| Migration on dev DB | 0007 → 0008 upgrade exit 0; downgrade to 0007 verified on scratch DB, re-upgrade clean |
| Immutability backstop | raw-SQL tamper attempts on a finalized row all raise via `enforce_scenario_immutability` trigger; `finalized→archived` permitted; archived terminal |

### 2.2 Frontend

| Check | Result |
|---|---|
| `bun run lint` (eslint) | exit 0, clean |
| `tsc --noEmit` | zero errors in M7.2 files (`scenarios.tsx`, `workspace.tsx`, `store.ts`, `api.ts`, `types.ts`, `use-fieldshift.ts`); pre-existing M7.0-tracked errors elsewhere remain out of scope |
| New workspace tab | **Scenarios** (9th tab) |

### 2.3 Browser E2E (agent-browser, zero console errors)

Golden path exercised end-to-end against the live demo workspace:

1. 9-tab workspace renders; capability panel shows soil/management/climate-projection/
   weather-forecast as unavailable with verbatim M7.0 reasons.
2. Field select → parent Field State select (period auto-prefilled from the state) →
   hypothetical assumptions with units → **create** → draft scenario with evidence badge
   "Hypothetical assumption — not observed data" and visible checksum.
3. **Validate** → `conditionally_valid` verdict with findings (all-synthetic disclosure with
   exact share; parent dimension gaps; structurally unavailable domains).
4. Incompatible-period honesty: a 2016–17 config against a 2024 state returned
   `incompatible_period → invalid`, surfaced in the UI.
5. **Finalize** → immutable: Validate/Delete/Archive disabled, New version enabled.
6. **New version** → v2 draft; original row untouched (checksum comparison via API tests).
7. **Verify checksum** → valid, parent intact, boundary record present.
8. **Compare** → structural diff (`adjustments.temperature_delta_c: 2 → 3.5`), compatibility
   warnings, explicit "no simulated outputs" note.
9. Desktop 1280px: no horizontal overflow. Mobile 390×844: `scrollWidth 390 == innerWidth`
   (after break-all/min-w-0 fixes); sticky footer confirmed (`footer-bottom-ok: true`).
   Screenshots: `tool-results/m72-scenarios-desktop-final.png`, `tool-results/m72-scenarios-mobile.png`.

## 3. Deliverables

**Code** (commit `cfbf112`):
- `app/scenarios/contracts.py` — versioned taxonomy + strictly typed configuration contracts + canonical checksum
- `app/scenarios/validation.py` — pure validation engine
- `app/scenarios/service.py` — lifecycle, versions/lineage, comparison, verification, serializers
- `app/api/v1/scenarios.py` + router registration — 15 endpoints, no execution endpoint
- `app/db/models.py` — `Scenario`, `ScenarioValidationRecord`
- `migrations/versions/0008_scenario_domain.py` — 2 tables, 8 CHECK constraints, 4 indexes, immutability trigger
- `src/components/fieldshift/scenarios.tsx` + workspace/store/api/types/hook wiring
- `tests/` — 3 new files + migration test class (91 tests)

**Documentation** (`docs/m7/m7_2/` — this document set):
`M7_2_GAP_ANALYSIS.md`, `M7_2_DOMAIN_DESIGN.md`, `M7_2_SCENARIO_TAXONOMY.md`,
`M7_2_CONFIGURATION_CONTRACTS.md`, `M7_2_IMMUTABILITY_AND_LINEAGE.md`,
`M7_2_VALIDATION_METHODOLOGY.md`, `M7_2_DATABASE_AND_MIGRATION.md`, `M7_2_API_CONTRACTS.md`,
`M7_2_SECURITY_AND_TENANCY.md`, `M7_2_TEST_AND_BENCHMARK_REPORT.md`,
`M7_2_LIMITATIONS_AND_BACKLOG.md`, `M7_2_VERIFICATION_REPORT.md` — plus updates to
`IMPLEMENTATION_STATUS.md`, `TEST_MATRIX.md`, database schema docs, ADR-0009, API docs.

## 4. Acceptance scorecard (M7.2 spec §16)

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Scenario types explicitly modeled | ✅ | taxonomy registry, 5 types |
| 2 | Supported/unsupported distinguishable | ✅ | capability status everywhere |
| 3 | Each scenario references a verified parent Field State | ✅ | PARENT_STATE_* guards, checksum pin, tests |
| 4 | Immutable after finalization | ✅ | 409s + DB trigger, raw-SQL tamper test |
| 5 | New versions preserve full lineage | ✅ | revision chain/branch tests, original untouched |
| 6 | Deterministic configuration checksums | ✅ | canonical JSON SHA-256, materiality tests |
| 7 | Validation independent and testable | ✅ | pure engine, 19 unit tests |
| 8 | Historical vs hypothetical distinct | ✅ | DB CHECK, labels, engine, UI badges |
| 9 | Soil/Management unavailable | ✅ | not_implemented + H-03 reasons everywhere |
| 10 | Forecasts/climate projections unimplemented | ✅ | creation 422, capability honesty, DB CHECK |
| 11 | Definition comparison, no fabricated results | ✅ | diff + explicit note, warning tests |
| 12 | APIs secure and tenant-isolated | ✅ | dedicated security test class |
| 13 | Frontend Scenario Workspace end-to-end | ✅ | browser-verified golden path |
| 14 | Full backend regression passes | ✅ | 581/581, exit 0 |
| 15 | Frontend checks + browser E2E pass | ✅ | lint 0, tsc clean, E2E §2.3 |
| 16 | Database migrations verified | ✅ | up/down/re-up, dev + scratch DBs |
| 17 | Documentation reflects actual code | ✅ | docs written from the implementation |

## 5. Remaining limitations

See `M7_2_LIMITATIONS_AND_BACKLOG.md`. Headline items: no rate limiting (platform debt);
climate projections/forecasts remain contract-only pending real data/providers (M7.0 C5);
soil/management remain not_implemented (M6B/M6C absent); draft-edit history not versioned
(by design, spec-sanctioned).

## 6. Baseline handover

The updated source-of-truth baseline after M7.2: commit `cfbf112`, migration head
`0008_scenario_domain`, 581 passing backend tests, frontend lint clean, 9-tab workspace.
M7.3 (Environmental Stress Transformations) must not begin without reporting against this
baseline — per the standing protocol.

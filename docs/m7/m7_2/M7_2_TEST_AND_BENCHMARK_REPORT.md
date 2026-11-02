# M7.2 — Test & Benchmark Report

**Status:** executed on the live working tree (backend `.venv`, real PostgreSQL+PostGIS on
:5433, scratch-DB migration runs, TestClient integration, agent-browser E2E)

## 1. Repository identity

| Check | Value |
|---|---|
| Baseline commit (Phase 0) | `15013c7` (M7.1), clean tree |
| Implementation commit | `cfbf112` — "M7.2: scenario domain & immutable scenario definitions …" |
| Migration head after | `0008_scenario_domain` |
| Backend regression after | **581 collected, exit 0** (490 baseline + 91 new) |
| Frontend lint (`eslint .`) | exit 0 |
| `tsc --noEmit` | no errors in M7.2 files (pre-existing M7.0 F-39 errors in `features.tsx`/`water.tsx` remain, tracked) |

## 2. New tests (91)

| Suite | Count | Coverage |
|---|---|---|
| `tests/unit/test_scenario_contracts.py` | 26 | taxonomy honesty; schema validation (bounds, conflicts, empty set, extra keys, observed-with-assumptions, unimplementable types); canonical serialization (determinism, explicit nulls, floats, key order, schema version); checksum materiality (parent pins change it; UI metadata does not); lifecycle table |
| `tests/unit/test_scenario_validation.py` | 19 | pure engine: parent compatibility (missing/cross-tenant/checksum/boundary/unsucceeded/boundary-record), period compatibility (zero/partial overlap), semantics (observed vs hypothetical, unlabelled assumptions, unimplemented types), evidence integrity (partial + all-synthetic disclosure), result document shape |
| `tests/integration/test_scenarios.py` | 43 | API creation (all implemented types; unimplemented rejected with reasons; invalid configs; cross-field parent; idempotency replay; taxonomy/capabilities endpoints); lifecycle (validate → records appended, finalize requires validation, finalize freezes, PATCH resets validation, draft delete vs archive, archived terminal); versions & lineage (revision of finalized, type mismatch, requires finalized, original untouched, branch); parent protection & reproducibility (parent-state delete RESTRICT, parent unchanged incl. manifest hash, identical definitions → identical checksums, pins by value); comparison (identical, changed assumptions, different boundaries → warnings, observed vs hypothetical flagged, cross-tenant); security & tenancy (cross-tenant access, field-scoped idempotency, unauthenticated 401, enumeration 404, double finalize) |
| `tests/integration/test_migrations.py` (TestM7_2ScenarioDomain) | 3 | scratch-DB upgrade (tables/columns/indexes/trigger/C2 CHECKs), trigger freeze + terminal archive via raw SQL, downgrade to 0007 + re-upgrade |

## 3. Regression

| Suite | Result |
|---|---|
| Full `tests/` (M1–M7.1 + M7.2) | **581 passed, 0 failed, exit 0** (baseline 490 preserved) |
| Migration round-trip | up → down(0007) → up on a scratch DB, plus dev-DB upgrade — all exit 0 |

## 4. Browser E2E (agent-browser)

| Check | Result |
|---|---|
| Workspace renders with the new **Scenarios** tab (9 tabs) | ✅ |
| Honest capability panel (soil / management / climate projection / weather forecast with verbatim reasons) | ✅ |
| Create flow: field select → parent state select (period **auto-prefilled** from the state) → assumptions with units → create | ✅ 202-style OK, card shows `draft` + "Hypothetical assumption — not observed data" |
| Incompatible period honestly refused | ✅ validation verdict `incompatible_period → invalid` surfaced in the UI (2016–17 config vs 2024 state) |
| Validate | ✅ `conditionally_valid → conditionally_valid` with findings (all-synthetic disclosure, dimension gaps) |
| Finalize | ✅ stamps finalized; Validate/Delete/Archive become disabled; **New version** enables |
| New version | ✅ v2 draft appears (4 scenarios in list) |
| Verify checksum | ✅ "Checksum valid: true" |
| Compare | ✅ "Definition comparison" card; `adjustments.temperature_delta_c: 2 → 3.5` diff; compatibility warnings; period overlap 0 for incompatible pair |
| Console errors / page errors | ✅ **zero** (after fixing the transient `SlashCircle` icon import; stale log lines predate the fix) |
| Desktop 1280px | ✅ no overflow; screenshot `tool-results/m72-scenarios-desktop-final.png` |
| Mobile 390×844 | ✅ `scrollWidth 390 == innerWidth` after `break-all`/`min-w-0` fixes on diff/checksum/mono content; footer stuck to bottom (`footer-bottom-ok:true`); screenshots `tool-results/m72-scenarios-mobile.png` |
| No simulation graphs / predicted results anywhere | ✅ by construction (none exist) |

## 5. Acceptance criteria (M7.2 spec §16) — scorecard

| # | Criterion | Verdict |
|---|---|---|
| 1 | Scenario types explicitly modeled | ✅ 5 types, versioned taxonomy |
| 2 | Supported vs unsupported distinguishable | ✅ capability registry + endpoints + UI |
| 3 | Each scenario references a verified parent Field State | ✅ PARENT_STATE_* guards + checksum pin |
| 4 | Immutable after finalization | ✅ service + trigger (raw-SQL tamper test) |
| 5 | New versions preserve full lineage | ✅ revision chain + branch lineage, original untouched |
| 6 | Deterministic configuration checksums | ✅ canonical JSON + SHA-256, materiality-tested |
| 7 | Validation independent and testable | ✅ pure engine, no HTTP/ORM imports |
| 8 | Historical vs hypothetical evidence distinct | ✅ DB CHECK + labels + engine + UI badges |
| 9 | Soil/Management remain unavailable | ✅ not_implemented everywhere, M7.0 H-03 reasons |
| 10 | Forecasts & climate projections unimplemented | ✅ creation rejected; capability honesty; DB CHECK |
| 11 | Definition comparison without fabricated results | ✅ diff + explicit "no simulated outputs" note |
| 12 | APIs secure and tenant-isolated | ✅ dedicated test class |
| 13 | Frontend Scenario Workspace end-to-end | ✅ browser-verified flow |
| 14 | Full backend regression passes | ✅ 581/581 |
| 15 | Frontend checks + browser E2E pass | ✅ lint 0; tsc clean for new files; E2E above |
| 16 | Migrations verified | ✅ up/down/re-up on scratch + dev DB |
| 17 | Documentation reflects actual code | ✅ this document set (written after implementation) |

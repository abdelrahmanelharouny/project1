# M7.1 — Test & Verification Report

**Date:** 2026-11-01 · **Mode:** implementation milestone (read-only inspection rules no
longer apply; all changes additive; engine behavior untouched and regression-proven).

---

## 1. Baseline (pre-modification, recorded per spec §1)

| Check | Result |
|---|---|
| Git | `main` @ `1eaebf3`, working tree clean |
| Backend regression | **441 passed, 0 failed, 0 skipped**, exit 0 (441 progress dots; the pytest terminal summary line is suppressed by the 2,400-warning flood — cosmetic) |
| Frontend lint | exit 0 |
| Migration head (code & DB) | `0006_water_intelligence` |
| Services | API :3030 healthy, frontend :3000 serving |

## 2. Post-implementation verification (final run)

| Check | Result |
|---|---|
| Backend regression (full suite) | **490 passed, 0 failed, exit 0** (5m25s wall) = 441 pre-existing + 49 new |
| New unit tests | 16 (`tests/unit/test_observation_manifest.py`) |
| New integration tests | 31 (`tests/integration/test_field_states.py`) |
| New migration tests | 2 (`TestM7_1FieldStateFoundation` in `test_migrations.py`) |
| Frontend lint | exit 0 |
| Type check (`tsc --noEmit`) | no NEW errors; 3 pre-existing errors remain in untouched files (`features.tsx` ×2 `JobStatus` — known M7.0 F-39; `water.tsx` ×1) — one pre-existing missing import in `use-croptwist.ts` (touched file) was fixed |
| Migration head (code & DB) | `0007_field_state_foundation` |
| Migration up/down | verified twice: dev DB upgrade → downgrade → re-upgrade, plus scratch-DB tests (upgrade creates field_states/columns/index, downgrade to 0006 reverses exactly, incl. restoring the legacy ingestion index) |

## 3. Coverage matrix (M7.1 spec §8)

| Required test area | Tests |
|---|---|
| Boundary version pinning | `TestBoundaryPinning::test_runs_pinned_to_boundary_version_in_effect`, `test_water_plan_pinned_to_boundary_version`, `test_state_pins_current_boundary_and_verify_finds_record` |
| Historical boundary preservation | `TestBoundaryPinning::test_historical_state_unchanged_by_boundary_edit` (checksum stable across an edit), `test_runs_pinned…` (old run keeps v1) |
| Observation manifest determinism | unit: `TestDeterminism` (query-order independence, canonical JSON, empty manifest); integration: `test_replay_via_idempotency_key_returns_same_run` |
| Manifest changes when inputs change | unit `TestChangeDetection` (value / quality / membership); integration `test_new_ingestion_does_not_change_stored_manifest` (stored manifest immutable) |
| Manifest versioning | `test_format_version_present` + format field on every artifact |
| Synthetic/real separation | `test_synthetic_flag_and_counts`, integration `test_run_stores_manifest_with_hash` (synthetic count == total on synthetic fixtures) |
| Spatial support preservation | `test_spatial_support_preserved_per_entry` |
| Temporal consistency | `test_period_defaults_to_run_window…` (Cairo local-midnight → UTC), `test_env_run_outside_state_period_refused`, `test_water_period_mismatch_recorded_not_mixed` |
| Immutable snapshot behavior | `test_reconstruction_same_refs_same_checksum`, verify/tamper tests (`test_verify_ok_then_manifest_tamper_detected`, `test_state_checksum_tamper_detected`), F-13 `test_water_plan_delete_restricted_when_referenced` |
| Tenant isolation | `TestTenantIsolation` (read/create/verify/manifest/compare across two real users; 403 convention; unknown → 404) |
| Missing-domain representation | `test_create_state_honest_domain_map` (soil/management `not_implemented` + reasons; water/crop_history `missing`) |
| API contracts | all endpoint tests above + payload-surfacing assertions (created_by, boundary_version, manifest hash, water timestamps, solver_version) |
| Migration upgrade/downgrade | `test_upgrade_creates_field_state_schema`, `test_downgrade_to_0006_reverses_m7_1_schema`, roundtrip |
| M1–M6A regression | 441/441 pass unmodified |

## 4. Browser verification (agent-browser, 2026-11-01)

Environment: demo workspace (SYNTHETIC fixtures), Next.js dev :3000, API :3030.

| Check | Result |
|---|---|
| 8-tab workspace renders (new "Field State" tab present) | ✅ |
| Field picker → North Field (synthetic) | ✅ |
| Assemble state WITHOUT period on a run-less field | ✅ honest 422 surfaced in the UI ("period required…"), then period inputs added |
| Assemble state WITH period | ✅ 202 → `succeeded`, boundary v1 badge, checksum shown |
| Domain availability grid | ✅ environmental/water/crop_history `missing` with reasons; **soil & management "not implemented"** with the M7.0 H-03 reasons |
| Verify checksums button | ✅ report: state checksum valid, manifest checksum valid, boundary record exists |
| Second snapshot + compare | ✅ boundary consistent, manifest hash consistent, 100% period overlap, non-interchangeability note |
| Console errors | ✅ **zero** (all 8 tabs) |
| Page errors | ✅ zero |
| Desktop 1280px | ✅ no horizontal overflow |
| Mobile 390×844 | ✅ `scrollWidth 390 == innerWidth`; footer pushed naturally (no floating gap) |
| Screenshots | `tool-results/m71-fieldstate-desktop.png`, `tool-results/m71-fieldstate-mobile-390.png` |

## 5. Acceptance criteria (M7.1 spec §11) — final scorecard

| # | Criterion | Verdict |
|---|---|---|
| 1 | Boundary versions pinned to reproducible calculations | ✅ feature runs, water plans, field states |
| 2 | Observation manifests deterministic and verifiable | ✅ 16 unit + 6 integration tests; verify endpoint |
| 3 | Historical snapshots retain immutable input references | ✅ FK RESTRICT + by-value manifest copy + checksum tamper tests |
| 4 | Temporal and spatial support explicit | ✅ period records, per-entry spatial support, timezone/calendar context |
| 5 | Missing domains honestly represented | ✅ `not_implemented` with reasons, UI badges |
| 6 | Snapshots independently reconstructible and verifiable | ✅ same-refs-same-checksum test; verify recomputes from stored content |
| 7 | Tenant isolation tested | ✅ 3 dedicated tests (platform 403/404 convention) |
| 8 | All existing M1–M6A regressions pass | ✅ 441/441 |
| 9 | Database migrations verified | ✅ up/down/re-upgrade on dev + scratch DBs |
| 10 | Browser verification passes | ✅ desktop + 390px, zero console errors |
| 11 | Documentation reflects actual implementation | ✅ this document set + updated IMPLEMENTATION_STATUS / TEST_MATRIX / schema.md / ADR |

## 6. Residual notes (recorded, not hidden)

- The pytest terminal summary line is suppressed under the current warning volume
  (2,400+ benign warnings; pre-existing debt, tracked in M7.0). Exit code + dot count
  used as evidence; no new warnings introduced.
- Pre-existing tsc errors in `features.tsx`/`water.tsx` (M7.0 F-39 JobStatus class) remain
  — out of M7.1 scope, still tracked.
- Water-plan DELETE remains possible for UNREFERENCED plans (intended: F-13 restricts
  only referenced snapshots).

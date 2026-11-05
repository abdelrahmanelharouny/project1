# M7.4 — Test & Verification Log

---

## 1. Test inventory (new)

| File | Suite | Tests |
|---|---|---|
| `tests/unit/test_sensitivity_math.py` | unit | 33 |
| `tests/unit/test_sensitivity_contracts.py` | unit | 31 |
| `tests/integration/test_sensitivity_analyses.py` | integration | 19 |
| `tests/integration/test_migrations.py::TestM74Migrations` | integration | 2 |
| **Total new** | | **85** |

## 2. Full-suite results (final verification session)

Run in chunks on the test database (head `0010_sensitivity_analysis`):

| Chunk | Result |
|---|---|
| `tests/unit` + `tests/contract` | **496 passed** (424 unit + 72 contract) |
| integration chunk 1 (auth…migrations + sensitivity) | **131 passed** |
| integration chunk 2 (ingestion…scenarios) | **98 passed** |
| integration chunk 3 (water) | **17 passed** |
| **Total** | **742 passed, 0 failed, 0 errors — exit 0** |

Baseline check (Phase 0, before any M7.4 change): 657 passed in the same chunking —
no pre-existing failures, no skips relied upon.

## 3. Golden mathematics verified via the live API (dev database smoke)

Source: demo workspace, finalized scenario `Browser E2E stress`
(ΔT = 2.0 °C, M_p = 0.8, period 2023), M7.3 run `aa4054c4…`
(1 456 transformed observations, 1 632 recalculated feature rows).

1. **Reproduction gate** — analysis `64feb783…` reproduced the source pass exactly:
   `matched_rows = 1632 / compared = 1632`, `mismatched_rows = []`,
   `observation_count_match = true`.
2. **ΔT linearity** — `air_temperature_max_mean_monthly` 2023-01: reference
   13.8313, slope **1.0** (`degC / degC`, central), envelope
   [9.8313, 17.8313] = ref − 4 / ref + 4 (bounds [−2, 6] with ref ΔT 2),
   output range exactly 8.0, direction increasing.
3. **Daily sweep** — `air_temperature_max_daily` 2023-01-01: slope
   1.0000000000000009 (float noise only), classification monotonic increasing.
4. **Threshold honesty** — `hot_days_35c_count_monthly` renders classification
   `threshold_suspected` with `slope_validity = invalid_across_suspected_discontinuity`
   (slope 0 days/degC annotated invalid, never hidden).
5. **Joint grid** — 9×9 axes from the UI design; single-family features show
   `interaction_contrast = 0` / `approximately_additive` (structural negative
   control), 35 additive summaries visible in the capped UI window.
6. **Verify endpoint** — all five flags true
   (`output_checksum_valid`, `source_run_intact`, `parent_snapshot_intact`,
   `manifest_checksum_matches`, `reference_reproduction_consistent`).

## 4. Frontend verification

- `bun run lint` — exit 0.
- `bunx tsc --noEmit` — zero errors in all M7.4 files
  (`sensitivity.tsx`, `lib/api.ts`, `lib/types.ts`, `workspace.tsx`, `store.ts`);
  the pre-existing M7.0-tracked errors elsewhere are unchanged and out of scope.
- Browser journey (agent-browser, desktop 1280 + mobile 390): see
  `M7_4_VERIFICATION_REPORT.md` §5.

## 5. Migration verification

`TestM74Migrations` on a scratch database: `upgrade head` creates all seven
`sensitivity_*` tables, the analysis-column set, both unique indexes, both
triggers, the status/checksum CHECKs and the evaluation dedupe UNIQUE;
`downgrade 0009_scenario_execution` reverses everything (tables AND functions);
re-upgrade clean. Dev database migrated to `0010_sensitivity_analysis`.

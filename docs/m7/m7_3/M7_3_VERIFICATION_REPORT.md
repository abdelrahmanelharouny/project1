# M7.3 — Final Verification Report

**Milestone:** M7.3 — Environmental Stress Transformation & Scenario-derived Feature Engine
**Verified at:** 2026-11-02 (final verification session, on top of the implementation session of the same day)
**Protocol:** Inspect → Specify → Implement → Benchmark → Test → Integrate → Browser Verify → Document
**Verdict: COMPLETE — all 21 acceptance criteria verified (see §6).**

---

## 1. Repository identity at final verification

| Item | Value | Verification method |
|---|---|---|
| Branch | `main` | `git branch --show-current` |
| Base commit (M7.2 docs) | `8f0ca8f` | `git log` — M7.3 work was in the working tree on top of it |
| Working tree | M7.3 implementation, uncommitted at inspection start; committed at verification end | `git status` |
| Migration head (code) | `0009_scenario_execution` (linear chain 0001→0009) | `migrations/versions/` |
| Migration head (DB) | `0009_scenario_execution` | `alembic current` on the dev database |
| Side-branch quarantine | `m6b-m6c-wip` @ `c6e533d` (unrelated uncommitted M6B/M6C workstream, preserved — see GAP_ANALYSIS §2) | `git branch -a` |
| Backend tests | **657 collected, 657 passing, 0 failures** (360 unit / 72 contract / 225 integration) | full suite, this session |
| Frontend lint | `bun run lint` — exit 0, clean | this session |
| Frontend tsc | zero errors in all M7.3 files; the 6 pre-existing M7.0-tracked errors (`examples/` 2, `skills/` 1, `features.tsx` 2, `water.tsx` 1) unchanged, out of scope | `bunx tsc --noEmit` |
| Dev API | `/api/v1/health` → ok (uvicorn :3030, daemonized) | live curl |
| Dev DB state | 3 scenarios (all finalized), 1 execution run `completed_with_limitations`, 1456 derived observations, 1639 derived feature rows | direct SQL |

## 2. What this session re-verified independently

The final-verification session re-verified the implementation session's work from the repository (not from
reports), and made three corrections (§3):

1. **Full regression, all suites** — 657/657 pass. The Open-Meteo-dependent ingestion test
   (`test_data_passport.py::test_same_variable_from_two_sources_gets_two_entries`), which had failed
   environmentally during the implementation session (upstream "service overloaded"), passed at final
   verification. Not a regression; identical failure reproduced on the pristine M7.2 baseline in Phase 0.
2. **Migration state** — dev DB at head `0009_scenario_execution`; scratch-DB upgrade/downgrade/re-upgrade
   covered by `TestM73Migrations` (3 tests, passing).
3. **Golden math via the live API** — monthly mean air temperature 2023-01: baseline 7.8063 °C → scenario
   9.8063 °C, difference exactly **2.0** (configured ΔT), Δ% 25.62 (mathematically meaningful, baseline ≠ 0).
   2023-02 and 2023-03 identical ΔT = 2.0.
4. **Integrity verification via the live API/browser** — `POST /scenario-executions/{run}/verify` returned
   `output_checksum_valid: true`, `scenario_definition_checksum_valid: true`, `parent_snapshot_intact: true`,
   `manifest_checksum_matches_run: true`.
5. **Run status honesty** — the executed run is `completed_with_limitations` (not "succeeded") because the
   catalog contains ET0 features that are deliberately `not_evaluated` (11 reasons) plus the standard
   hypothetical disclosure. This is the honest status by design.

## 3. Corrections made at final verification

| # | Defect found | Fix | Files |
|---|---|---|---|
| 1 | **Stale honesty payload:** `GET /scenarios/capabilities` still said `execution.scenario_execution = "not_implemented"` ("M7.3 does not exist in this repository") — false since M7.3 landed, and rendered in the workspace UI | Payload updated to `implemented_for_supported_types` with a reason that states the M7.3 scope AND its limits (finalized-only types, outputs never observations, climate projections / forecasts / soil / management still unavailable, ET0 never recalculated or reused). M7.2-era test assertion updated to lock the new truth | `app/scenarios/service.py`, `tests/integration/test_scenarios.py`, `M7_3_API_CONTRACTS.md` §9 |
| 2 | **Inaccurate test statistics in docs:** 656/657 and a per-suite breakdown (547/29/81) that did not match reality | Replaced with the measured final-verification numbers (657/657; unit 360 / contract 72 / integration 225) and the flake's resolution | `M7_3_TEST_AND_VERIFICATION.md`, `M7_3_LIMITATIONS_AND_BACKLOG.md` §5, `IMPLEMENTATION_STATUS.md`, `TEST_MATRIX.md` |
| 3 | **Mobile layout defect (390px):** the execution-run row squeezed its text to ~33px (one character per line) because the status badge (178px) consumed the flex row | Run-row button now `min-w-48 flex-1` with inner `flex-1 min-w-0` — badge wraps below on narrow screens, inline and vertically centered on desktop. Verified by DOM measurement at both widths | `src/components/croptwist/scenario-execution.tsx` |

## 4. Browser E2E (agent-browser, re-verified this session)

Journey: enter demo workspace → Scenarios tab → select field → finalized scenario cards → execute →
inspect run → compare → evidence → verify checksums. Zero console errors / zero page errors throughout.

| Step | Result | Evidence |
|---|---|---|
| Workspace renders `Platform scenario capabilities` with all §13.F unavailable states | ✅ | soil / management / climate projection / weather forecast cards + the corrected M7.3 execution statement incl. ET0 disclosure |
| Transformation preview shows exact hypothetical parameters before execution | ✅ | "Temperature: +2 °C · Precipitation: ×0.8" under "Hypothetical assumptions to apply (never observed data)" |
| Execute finalized stress scenario | ✅ | run appears with `completed with limitations` badge, 1456 transformed obs · 1639 feature rows; idempotent replay returned the existing run |
| **Honest refusal of an unsupported scenario** | ✅ | scenario configured with `precipitation_delta_mm = +50 mm` → Execute returns structured refusal rendered in the card: "…(adjustments.precipitation_delta_mm: Additive precipitation shifts are not a supported M7.3 transformation; only multiplicative precipitation scaling executes.)" |
| Baseline vs scenario table with evidence filters | ✅ | All (1639) / Scenario-derived (1632) / Not evaluated (5) / Not affected (2); ET0 rows show the full not-evaluated reason; Δ% withheld where invalid |
| Evidence explorer | ✅ | 100-row table: `air_temperature_max 14.260 → 16.260 degC, temperature_delta_c {"delta_c":2}`, per-row **synthetic** badge preserved from the synthetic source |
| Verify checksums panel | ✅ | output ✓ · definition ✓ · parent intact ✓ · manifest pinned ✓ |
| Console / page errors | ✅ | none |
| Desktop 1280px | ✅ | screenshot `tool-results/m73-final-desktop.png` |
| Mobile 390px | ✅ (after fix §3.3) | screenshot `tool-results/m73-final-mobile-fixed.png`; DOM-measured: run-row text width 33px → 219px, badge wraps below |

Parent immutability confirmation: the verify panel's `parent_snapshot_intact` / `manifest_checksum_matches_run`
checks plus the integration suite's immutability tests (observations count/sum, parent feature values, field-state
checksum, scenario definition content — all unchanged after execution; DB-trigger tamper attempts rejected).

## 5. Test evidence summary

| Suite | Files | Result |
|---|---|---|
| Unit — M7.3 | `test_scenario_transformations.py` (28) + `test_scenario_dependency_graph.py` (23) | all pass |
| Unit — baseline | 12 further files | 309 pass (360 unit total) |
| Contract | API contract suite | 72 pass |
| Integration — M7.3 | `test_scenario_executions.py` (22) + `TestM73Migrations` (3) | all pass |
| Integration — baseline | 11 further files | 203 pass (225 integration total) |
| **Total** | | **657 / 657** |

## 6. Acceptance criteria (spec §17) — final status

| # | Criterion | Status |
|---|---|---|
| 1 | Supported scenarios execute from verified immutable Field State references | ✅ finalized-only gate, definition + parent pins re-verified at execution time |
| 2 | Temperature transformations mathematically correct | ✅ unit (28 tests) + live API ΔT = 2.0 exact |
| 3 | Precipitation transformations mathematically correct | ✅ M=1 identity, M=0 zeroing, negative rejected, missing preserved |
| 4 | Temporal & spatial support preserved | ✅ native support copied verbatim; hard window boundary; no resampling |
| 5 | Derived features recomputed from transformed source values | ✅ two M4 engine passes (baseline vs scenario) over the same window; no aggregate fabrication |
| 6 | Unsupported features remain unevaluated | ✅ `not_evaluated` / `not_affected` rows with reasons (11 run-level reasons) |
| 7 | ET0 not incorrectly reused as scenario-derived data | ✅ `exclude_et0` role; never recomputed, never reused; explicit reasons everywhere |
| 8 | Original observations & feature runs unchanged | ✅ integration immutability tests + verify panel |
| 9 | Provenance propagates to every derived output | ✅ source observation id, dataset product, transformation code + parameter, engine/spec versions, evidence classes |
| 10 | Execution deterministic and checksummed | ✅ input fingerprint UNIQUE; canonical output SHA-256 (6-decimal floats); replay identical |
| 11 | Synthetic and real evidence explicitly distinct | ✅ `synthetic_test` vs `scenario_derived_transformed` + SYNTHETIC SOURCE warning + UI badges |
| 12 | Tenant isolation maintained | ✅ server-side ownership resolution on every endpoint; cross-tenant 403/404 tested |
| 13 | Baseline-versus-scenario comparisons work | ✅ compare endpoint + UI table; Δ% only when mathematically meaningful |
| 14 | UI clearly differentiates observed vs hypothetical | ✅ badges on every value-level row; disclosures; no simulation charts |
| 15 | No forecast or climate projection claims | ✅ taxonomy `not_implemented`; creation rejected; disclosure discipline (C2) |
| 16 | No unsupported soil or management simulation | ✅ dimensions unavailable; never fabricated |
| 17 | Full backend regression passes | ✅ 657/657 |
| 18 | Frontend lint/type checks pass | ✅ lint exit 0; tsc clean for M7.3 files |
| 19 | Browser E2E passes | ✅ §4 |
| 20 | Database migrations verified | ✅ head applied on dev DB; upgrade/downgrade/re-upgrade on scratch DB |
| 21 | All documentation reflects the actual implementation | ✅ 13 documents incl. this report; corrections §3 applied |

## 7. Remaining limitations (honest scope)

See `M7_3_LIMITATIONS_AND_BACKLOG.md` for the full register. Headlines:

- Only two transformations execute (uniform ΔT, precipitation multiplier). Additive precipitation shifts,
  seasonal/rainfall timing shifts and any other dimension block execution with structured findings.
- Scenario ET0 is never recalculated (and baseline ET0 never reused) — a defensible method needs
  humidity/radiation/wind scenario inputs a temperature delta does not define.
- Non-daily source aggregation: transformed values are stored, but aggregation-source feature
  recalculation is daily-first in the M4 engine; such features are reported `not_evaluated`.
- A perturbation is a sensitivity experiment, never a climate trajectory; no variability change, no new
  events, no yield/crop claims anywhere.
- Execution is synchronous (window cap 3 years); async job integration is deferred (statuses already
  model the async vocabulary).
- The Open-Meteo-dependent ingestion test remains network-dependent (passed at final verification;
  hermetic mocking recommended as future hardening).

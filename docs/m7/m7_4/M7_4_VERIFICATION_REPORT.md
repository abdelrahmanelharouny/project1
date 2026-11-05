# M7.4 — Final Verification Report

**Milestone:** M7.4 — Sensitivity & Uncertainty Analysis
**Verified at:** 2026-11-02 (final verification session)
**Protocol:** Inspect → Specify → Implement → Benchmark → Test → Integrate → Browser Verify → Document
**Verdict: COMPLETE — all acceptance areas verified (§6).**

---

## 1. Repository identity at final verification

| Item | Value |
|---|---|
| Branch | `main` (M7.4 work on top of M7.3 commit `13c31d63`) |
| Working tree | M7.4 implementation, committed at verification end |
| Migration head (code + dev DB) | `0010_sensitivity_analysis` (linear chain 0001→0010) |
| Side-branch quarantine | `m6b-m6c-wip` preserved, never touched |
| Backend tests | **742 collected, 742 passing, 0 failures** (424 unit / 72 contract / 246 integration) |
| Frontend lint | `bun run lint` — exit 0 |
| Frontend tsc | zero errors in all M7.4 files; pre-existing M7.0-tracked errors unchanged, out of scope |
| Dev API | `/api/v1/health` ok; dev DB migrated to 0010 |
| Dev DB state | 3 finalized scenarios, 1 result-bearing M7.3 run (1 456 derived observations / 1 632 derived feature rows), 3 sensitivity analyses (all `completed_with_limitations`, reproduction exact) |

## 2. What was verified independently (from the repository, not reports)

1. **Phase 0 baseline reproduction** — every expected value (commit, tree, head,
   657-test baseline, M7.3 artifacts, demo data) matched; zero discrepancies
   (`M7_4_GAP_ANALYSIS.md`).
2. **Full regression** — 742/742 across all suites after implementation; the
   657-test baseline was re-run first (in chunks) before any change.
3. **Golden math via the live API** — reproduction gate exact (1 632/1 632);
   monthly/daily temperature slopes exactly 1.0; envelopes = ref ± (bound − refΔT)
   exactly; elasticity = 2.0/ref; precipitation elasticity exactly 1.0 with
   structured unavailability at zero baselines; single-family grid interaction
   contrast exactly 0.0 (`M7_4_TEST_AND_VERIFICATION.md` §3).
4. **Integrity chain** — analyses attach only to runs that pass the full M7.3
   verification (four flags) plus finalized-scenario and pin checks; tampered
   parent checksum ⇒ 409; trigger freezes result-bearing analyses (raw-SQL tamper
   test).
5. **Determinism** — identical designs replay to the same analysis and checksum
   (fingerprint UNIQUE + idempotency-key UNIQUE, both tested).

## 3. Corrections made during verification

| # | Defect found | Fix | Files |
|---|---|---|---|
| 1 | `direction_payload` raised TypeError on all-None corner values (grid analyses failed) | filter None values before comparison | `app/sensitivity/math.py` |
| 2 | Unbounded OAT/grid tables (3 264 + 132k rows) wedged the browser tab during E2E | capped render windows (100 OAT / 50 grid summaries) with explicit "showing first N of M" notes; evaluated-first client sort | `src/components/fieldshift/sensitivity.tsx` |
| 3 | Test-side: wrong envelope expectation (ref ± bounds instead of ref ± (bound − refΔT)); trigger test used a broken transaction pattern; tenant test asserted only 404 | corrected to the engine-correct expectation; DBAPIError-based tamper test; 403/404 both accepted as denials | `tests/integration/test_sensitivity_analyses.py` |

All three re-verified after the fix (full suite re-run; browser journey repeated).

## 4. Security & tenancy

- Every analysis endpoint resolves the field through `get_field_for_principal`;
  a second tenant receives 403/404 on all eight endpoints (tested).
- No endpoint mutates a result-bearing analysis (application + BEFORE UPDATE
  trigger); result-bearing analyses cannot be deleted (BEFORE DELETE trigger).
- M7.3 artifacts remain untouched: FK RESTRICT both directions; no code path
  writes to `observations`, `feature_runs`, `field_states`, `scenarios`,
  `scenario_execution_runs`, `scenario_derived_observations`,
  `scenario_derived_features`.

## 5. Browser E2E (agent-browser, demo workspace)

Journey: sign in → Sensitivity tab → North Field → scenario `Browser E2E stress`
→ run `aa4054c4` → definition form (both parameters with reference badges;
ΔT [−2, 6] ×9; M_p [0.5, 1.5] ×9) → joint grid enabled → **Run analysis** →
POST 200 → results:

| Check | Result |
|---|---|
| Reference reproduction card | reproduced **true**, 1632/1632 matched, observation count match **true** |
| OAT table (evaluated-first, cap note) | slope **1.0 degC/degC** visible; envelope [11.26, 21.26] for ref 15.26; elasticity rendered; classifications badged |
| Classification filter → threshold | `hot_days_35c_count_monthly` — threshold suspected + "slope invalid across jump" |
| Joint grid card | "finite-grid interaction contrast" column (labelled, not Sobol); 0.0 / approximately additive for single-family features; cap note |
| Uncertainty registry | 7 categories × status badges × verbatim explanations; no composite score |
| Features outside scope | inherited reasons verbatim (ET0, wind, soil moisture…) |
| Disclosures | "not a confidence or probability interval" on every relevant surface (×4 in DOM) |
| Verify panel | **5/5 flags true** after clicking Verify |
| Reload persistence | analysis history restores; results re-render (reproduced true) |
| Mobile 390 px | stacked layout, scrollable tables, sticky footer intact |

## 6. Acceptance criteria (M7.4 spec)

| Area | Criterion | Verdict |
|---|---|---|
| Scope discipline | only configured M7.3 parameters explorable; unsupported capabilities never analysed or stubbed | ✅ |
| Method fidelity | OAT (bounds contain reference; others at reference), central/one-sided slopes with units, structured elasticity, envelope naming | ✅ |
| Joint grid | explicit opt-in, both-parameter sources only, cell+budget caps, corner contrast labelled | ✅ |
| Classification | versioned rubric over actual values; thresholds flagged with slope invalidity | ✅ |
| Reproduction gate | exact recomputation before analysis; mismatch ⇒ failed analysis | ✅ |
| Lineage & provenance | all pins BY VALUE; fingerprint + output checksum; verify endpoint (5 flags) | ✅ |
| Immutability | application + trigger freeze; append-only analyses | ✅ |
| Uncertainty registry | 7 categories / 6 statuses / applicability rubric; dynamic evidence; no invented numerics; no composite score | ✅ |
| APIs | 8 endpoints, tenant-scoped, structured errors | ✅ |
| Persistence | migration 0010 (7 tables, dedupe UNIQUE, CHECKs, triggers); upgrade/downgrade verified | ✅ |
| Frontend | Sensitivity tab; honesty disclosures; capped tables; mobile clean | ✅ |
| Tests | 85 new; 742/742; no existing test weakened | ✅ |
| Documentation | 11 documents in `docs/m7/m7_4/`; root docs updated | ✅ |

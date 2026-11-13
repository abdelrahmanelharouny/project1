# P01-G — P01 Verification Report

**Audit executed:** 2026-11-13 · **Baseline:** branch `main`, HEAD `a83af70`, working tree clean (0 modified files) · Services live during audit: pg :5433, api :3030, bridge :3035, web :3000.

## 1. What was inspected and how

| Track | Method | Coverage |
|---|---|---|
| T1 Baseline | direct git/service/count checks | branch, HEAD, clean tree, 27-tab union (`src/lib/store.ts:5-32`), component counts (31+5+7), api/web health 200 |
| T2-a Feature inventory | full reads of `workspace.tsx`, `page.tsx`, `providers.tsx`, `auth-gate.tsx`; per-component source inspection with API-call tracing through `src/lib/api.ts` (1,643 lines), `api-p3-account.ts`, `api-p3-commercial.ts`, `use-croptwist.ts` (877 lines) | all 27 tabs + 7 shared components + charts/ + p3/ |
| T2-b Backend & RBAC | router.py mount list; per-router endpoint counts (grep of decorators); identity service role ladder; per-router authz-style grep; engine docstring headers | 39 routers / 288 endpoints; 7 roles / 4 ranks |
| T2-c UX/UI | quantified greps (tokens, aria, responsive, text-[10px], toast, Skeleton); 6 representative deep reads; route-state files | all 44 components + shell |
| T2-d i18n/Arabic | programmatic en/ar key diff (leaf-key count: 2,159 each, 0 mismatches); RTL-pattern greps; backend renderers/contracts/intelligence locale traces; test+docs sweep | complete removal-surface map |
| T2-e Geo/charts/reports/tests | map component full reads; package/deps checks; recharts primitive grep; report contract diff (frontend constant vs backend `REPORT_TYPES`); test/CI inventory | complete |
| Live browser | Agent Browser session (login → workspace) | desktop 1440×900 + mobile 390×844 screenshots; live DOM measurements; console error scan |

## 2. Claims verified against source (spot-checks by the integrator, not just agents)

| Claim | Verified | Evidence |
|---|---|---|
| 27 tabs | YES | `WorkspaceTab` union parsed programmatically = 27 ids; live DOM count = 27 |
| Overview binds `farms[0]` ignoring selection | YES | `overview.tsx:60` read directly |
| `tailwind.config.ts` dead (wrong globs, hsl-vs-oklch) | YES | `tailwind.config.ts:6-12` read; TW v4 `@theme inline` in `globals.css`; no `@config` |
| `use-fieldshift.ts` orphaned | YES | repo grep for importers = none |
| `maplibre-gl-shared.mjs` empty | YES | `wc -c` = 0 bytes |
| members.py 7-role pattern | YES | `members.py:33-46` read — see discrepancy D1 below |
| Live tab-strip measurements (3,263px @1440; 3,047px @390) | YES | agent-browser `scrollWidth` evals; screenshots in `docs/p01/evidence/` |
| No `<h1>` post-auth | YES | live DOM heading query |
| Zero console errors in session | YES | browser console scan |
| en/ar parity 2,159 keys × 31 namespaces | YES | programmatic JSON diff (agent-run), re-derived from file reads |

## 3. Discrepancies found between the 2026-11-13 checkpoint and current code (checkpoint drift)

| # | Checkpoint said | Actual (verified) | Impact |
|---|---|---|---|
| D1 | "farm-scoped `members.py` still validates the old 4-role set" | `members.py:33-46` uses the full 7-role `_ROLE_PATTERN`; docstring documents the P3 widening | Checkpoint item is stale; RBAC residue is narrower than believed (org member surface vs farm member surface gates differ: org_admin+ vs owner-only — a real but different inconsistency, recorded in inventory) |
| D2 | "p3b.json 324 keys" | **328** leaf keys (en and ar both) | Doc arithmetic drift |
| D3 | P3 verification doc references `tests/integration/test_p3_reports_flow.py` | File does not exist (report coverage lives in `test_p3_notifications_reports.py`) | Phantom reference in `docs/p3/P3_TEST_AND_VERIFICATION.md:53` |
| D4 | Checkpoint did not record the frontend defects found here (P4–P7, dead files) | All are present in code today | These are NEW audit findings, not checkpoint regressions |

## 4. New findings produced by this audit (not in any prior doc)

1. Silent-failure water plan view (`water.tsx:976,1010-1021`).
2. Mislabeled retry control (`overview.tsx:96-98`).
3. Wrong-tab empty-state CTAs ×3 (`features.tsx:573`, `rotation.tsx:867`, `water.tsx:998`).
4. Unwired `verifyForecasts` capability (`src/lib/api.ts:1542-1544`).
5. Dead files/config (use-fieldshift.ts, tailwind.config.ts, maplibre artifact).
6. Dark-mode dead code; semantic tokens unused in app code (1 use).
7. Store interface drift (`store.ts:82-83`).
8. Full duplication register (10 items) and the 12-journey friction analysis.
9. Complete Arabic/RTL removal surface (safe-delete / edit / preserve / risks).

## 5. Remaining uncertainties & audit limitations (honest)

| # | Uncertainty | Why | Resolution path |
|---|---|---|---|
| U1 | Server-side behaviors were audited from code + e2e_smoke structure, not by re-running the full pytest battery in P01 | Battery is measured/recorded in P3 verification (unit 144 / contract 72 / P3 138); re-running was out of P01 scope | Run battery before W1 merge as regression baseline |
| U2 | Whether any external consumers depend on `?locale=ar` / `report_jobs.locale='ar'` | Public API exposes job locale (`public_v1.py:349`); no external consumer is visible from this repo | Decide reject-vs-coerce policy before W6 backend step |
| U3 | Purpose of `date-fns` dependency (no imports found in `src/`) | Likely react-day-picker transitive; UNVERIFIED | Check at W0.5 dependency cleanup |
| U4 | Sentinel-2 vs `satellite_sim` as actual data source for the Satellite tab in any given workspace | Server-side decision; frontend shows provenance badges only | Confirm via provider registry when W4 starts |
| U5 | `week_start` preference has no known calendar consumer | API stores/validates it; `ui/calendar.tsx` does not read it | Product decision: wire or document |
| U6 | iOS safe-area behavior assumed inert without device testing | No `viewport-fit=cover` found (static) | Device QA in W1 |
| U7 | UX behavior of Radix tab strip keyboard nav under the future rail | Static analysis only (Radix provides arrow keys today) | A11y QA in W1 |

**Audit scope discipline honored:** no files modified; no Arabic removal; no schema/API changes; no capability removal proposed; all consolidation proposals are re-associations with redirect compatibility.

## 6. Deliverable index

| File | Content |
|---|---|
| `docs/p01/PRODUCT_FEATURE_INVENTORY.md` | 27-feature inventory + dependency map + duplication register |
| `docs/p01/UX_AUDIT_REPORT.md` | 17 ranked findings with file:line + live measurements |
| `docs/p01/NAVIGATION_REDESIGN_BLUEPRINT.md` | 9-destination IA + consolidation register C1–C9 |
| `docs/p01/USER_JOURNEY_ANALYSIS.md` | 12 journeys, friction ranked, proposed flows |
| `docs/p01/UX_MIGRATION_MATRIX.md` | component-by-component mapping + URL redirect map |
| `docs/p01/P01_IMPLEMENTATION_PLAN.md` | Waves 0–6 sequence for P02/P03 |
| `docs/p01/P01_VERIFICATION_REPORT.md` | this file |
| `docs/p01/evidence/*.png` | live browser screenshots (desktop + mobile strip) |

# P02 — W0+W1 Implementation Checklist (P01 finding → P02 change)

Phase A baseline recorded 2026-11-13. Branch `main`, HEAD `9ba6395` (tool-results only,
on top of P01 commit `d73106f`), working tree clean.

## Pre-existing baseline (measured before any P02 edit)

| Check | Result |
|---|---|
| `bunx tsc --noEmit` | exit 0 (clean) |
| `bun run lint` | exit 0 (clean) |
| API e2e smoke (`python3 scripts/e2e_smoke.py`) | ALL CHECKS PASSED (27.9s) |
| Services | pg :5433 ok, api :3030 ok (`{"status":"ok"...}`), bridge :3035 ok, web :3000 200 |
| Backend pytest battery | NOT runnable from host sandbox shell (host python lacks psycopg2/sqlalchemy; the API runs in its own runtime). Recorded as a pre-existing environment limitation, NOT a P02 failure. API behavior is instead covered by the live e2e smoke run above. |
| Frontend DOM tests | none exist (confirmed: no test runner in devDependencies) |

## Audit claims re-verified against source before editing

| Claim | Verified |
|---|---|
| `workspace.tsx:131` is the tab-validation/deep-link point | YES (`if (tab && TAB_IDS.includes(tab)) setActiveTab(tab)`) |
| `workspace.tsx:159` uses `router.replace` (history defect P17) | YES |
| Overview binds `farms[0]` (P4) | YES (`overview.tsx:60`) |
| Retry button labeled "Quick actions" (P6) | YES (`overview.tsx:96-98` + `overview.json`) |
| Wrong empty-state CTAs (P7) | YES (`features.tsx:573`, `rotation.tsx:867`, `water.tsx:998` — all call `goToObservationsFor({id:'',name:'',farmId:''})`; features' label even says "Go to Farms & Fields") |
| Water plan view has no loading/error branch (P5) | YES (`water.tsx:976` + `useWaterPlan`; grep `plan.isLoading|plan.isError` = 0) |
| `use-fieldshift.ts` orphaned (P12) | YES (0 importers) |
| `maplibre-gl-shared.mjs` empty (P12) | YES (0 bytes, 0 refs) |
| `tailwind.config.ts` dead (P3) | YES (TW v4 `@theme inline` in globals.css; 0 refs from src/scripts/config; components.json `tailwind.config: ""`) |
| Store interface drift (P12) | YES (`goToRotationFor`/`goToWaterFor` implemented at `store.ts:82-83`, missing from interface) |
| No `viewport` export (P10) | YES (`layout.tsx`) |
| No h1 post-auth (P9) | YES (first heading is H2 "Welcome to your workspace") |
| 20 tabs import `field-picker` | YES |
| `ui/sheet.tsx` + `ui/command.tsx` shipped but unused (P16) | YES |

## Change → finding map

| P02 change | P01 finding/evidence |
|---|---|
| W0.1 Overview honors store farm/field selection | P4 `overview.tsx:59-62` |
| W0.2 Retry action relabeled (`common.retry`) | P6 `overview.tsx:96-98` |
| W0.3 Three empty-state CTAs land on Farms & Fields | P7 features/rotation/water |
| W0.4 Water plan loading + error + retry states | P5 `water.tsx:976,1010-1021` |
| W0.5 Delete `use-fieldshift.ts`, `maplibre-gl-shared.mjs`, `tailwind.config.ts` | P12/P3 |
| W0.6 Token story decision (light-only formalized; dead config removed; `.dark` kept dormant, documented) | P2/P3 |
| W0.7 Shared state primitives (`state-views.tsx`), applied to W0 surfaces | P13 |
| W0.8 a11y: sr-only h1 post-auth, 44px nav targets, translated aria-label, viewport export | P8/P9/P10 |
| W1 nine-destination rail + sub-page rails + mobile sheet | P1, P16 (adopt shipped `ui/sheet.tsx`) |
| W1 legacy redirect map (27 ids) as single resolver plugged at the `workspace.tsx:131` point | blueprint §5, matrix §3 |
| W1 `router.push` for user navigation, `replace` only for canonicalization | P17 |
| W1 shared context bar (single FieldPicker instance); redundant in-tab pickers removed | blueprint §2.1, matrix §2 |
| W1 command-palette foundation (destination/sub-page navigation commands only) | C9, plan item 2.4 scope split |

## Verification gates

1. `bun test tests/frontend/` — resolver + config + store-resolution tests.
2. `bunx tsc --noEmit` + `bun run lint` — clean.
3. API e2e smoke re-run — unchanged backend behavior.
4. Agent Browser: all 27 legacy `?tab=` ids, all 9 destinations, invalid tab fallback,
   farm/field persistence, Back/Forward, mobile sheet behavior, water plan states,
   console error scan, 1440px + 390px.

# P01-F — P01 Implementation Plan (sequence for P02 / P03)

**Inputs:** `PRODUCT_FEATURE_INVENTORY.md`, `UX_AUDIT_REPORT.md`, `NAVIGATION_REDESIGN_BLUEPRINT.md`, `USER_JOURNEY_ANALYSIS.md`, `UX_MIGRATION_MATRIX.md`.
**Rule honored:** P01 changed nothing; this plan is the ordered backlog for the transformation. Every item carries evidence links and a verification gate.

---

## Guiding constraints (from audit, non-negotiable)

- Zero backend/API/schema changes during UI re-association (all verified behaviors keep their contracts).
- Deep-link compatibility forever: 27 legacy `?tab=` ids redirect, never break (`UX_MIGRATION_MATRIX.md` §3).
- Server remains the authorization authority; frontend role-adaptation is visibility-only.
- Arabic stays untouched until its dedicated wave (W6) — removal surface already mapped, not executed.

## WAVE 0 — Foundation fixes (P02 start; ~small, all independent)

| # | Item | Evidence | Gate |
|---|---|---|---|
| 0.1 | Fix Overview selection defect (honor store farm/field) | `overview.tsx:59-62` | deep-link `?farm=&field=` drives Overview charts |
| 0.2 | Fix mislabeled retry button | `overview.tsx:96-98` | manual check |
| 0.3 | Fix wrong-tab empty-state CTAs (3 files) | `features.tsx:573`, `rotation.tsx:867`, `water.tsx:998` | CTA lands on Farms & Fields |
| 0.4 | Add loading/error states to water plan view | `water.tsx:976,1010-1021` | simulated 500 shows error branch |
| 0.5 | Delete dead code: `use-fieldshift.ts`, `maplibre-gl-shared.mjs`; reconcile/delete `tailwind.config.ts` | greps verified in audit | tsc + lint + build clean |
| 0.6 | Theme token decision: adopt `ThemeProvider` + migrate components off hardcoded `stone-/emerald-` palette in phases, OR formally drop dark mode and `.dark` tokens | `providers.tsx:7-26`, `globals.css:81-113`, 1,690 hardcoded classes | one coherent token story; screenshot diff |
| 0.7 | Shared loader primitive + standardized empty/error states per section | 3 loading styles found | pattern documented + applied to 5 worst tabs |
| 0.8 | a11y pass: h1 post-auth, min-h targets in nav (44px), aria-invalid wiring, translate `aria-label="Overview"` | `ui/tabs.tsx:29`, `overview.tsx:84` | axe/manual checklist |

## WAVE 1 — Navigation shell (P02 core)

| # | Item | Notes |
|---|---|---|
| 1.1 | Build destination rail (9 destinations) + context bar (single FieldPicker instance) | replaces 27-tab strip; mobile = `ui/sheet.tsx` hamburger |
| 1.2 | Implement legacy redirect map (27 ids) + `?sub=` support | plug at `workspace.tsx:131`; preserve `?farm=&field=` |
| 1.3 | Move all 27 components verbatim into destinations (matrix §1) | zero logic edits; snapshot QA per destination |
| 1.4 | Active-tab scroll-into-view + mobile sheet with grouped destinations | kills 3,047px strip |
| 1.5 | Update notifications-bell `link_kind→tab` map + entitlement-guard Upgrade target | both are redirect-table consumers |
| Gate | full manual tab-sweep (27 legacy ids → correct destination/sub-page), tsc/lint, browser session on 390px and 1440px, zero console errors | |

## WAVE 2 — Extractions & shared pickers (P02 end)

| # | Item | Notes |
|---|---|---|
| 2.1 | Management 6 sub-views → visible sub-pages (`?sub=` keyed) | `management.tsx:210-236`; state preserved |
| 2.2 | Preferences sub-page extracted from team-tab | `p3/team-tab.tsx:1162-1179`; role gates preserved |
| 2.3 | Shared execution-picker for sensitivity/robust/decisions | dedupes artifact re-selection (journey J9) |
| 2.4 | Command palette (`ui/command.tsx`) for destinations + sub-pages + fields | shipped-but-unused primitive |
| Gate | QA matrices for management sub-views and decision chain; API regression suite green |

## WAVE 3 — Panels, dedupe, reports unification (P02/P03 boundary)

| # | Item | Notes |
|---|---|---|
| 3.1 | Contextual panels: passport + digital-twin summaries on field pages (shared components, not copies) | dedupe D7 |
| 3.2 | Overview dedupe: charts/map instances → links into Data Hub / Map & Satellite | D2/D3/D4 |
| 3.3 | Reports & Analytics unification: quick-export (client) + report library (server) cross-linked; expose arbitrary schedule intervals | two-export-system finding |
| 3.4 | Wire forecast verification UI | `src/lib/api.ts:1542-1544` (last endpoint-without-UI gap) |
| Gate | duplication register items 1–8 re-audited; journeys J1–J12 re-walked |

## WAVE 4 — Geospatial & satellite UX foundation (P03; no ingestion work)

Design-only + component scaffolding per `T2-e` readiness gaps:
- Map shell for layers: layer-control component, thematic legend (current legend is categorical-only), popup primitive (none exists today).
- Placeholder-but-real data paths: vegetation summary already provides monthly stats — bind as choropleth-ready overlay structure on field polygons (honest empty states when no imagery).
- Map draw/edit spike (P02 candidate library: maplibre draw successor) — evaluation only, behind feature flag.
- Time-slider scaffold for scenes (playback of existing scene list).
- **Honesty contract holds:** no simulated imagery; `satellite_sim` provenance labels continue via `badges.tsx`.

## WAVE 5 — Visualization & reporting depth (P03)

- Add missing chart types to the shared system (from T2-e): correlation/heatmap grid, CI bands (ErrorBar/area band), risk decomposition (stacked/waterfall), multi-variable dual-axis time series, scenario diff view, calendar heatmap. Backend data already exists for CI (sensitivity uncertainty endpoint, temporal z-scores) — no API change needed for first cut.
- Standardize satellite's CSS bars into recharts (`satellite.tsx:115-129`).
- PDF chart embedding decision (documented v1 limitation `renderers.py:34-37`) — evaluate reportlab image embedding for farm_performance/org_executive.
- Provenance rule enforced in every new chart: `observed/model_derived/simulated/missing` chips from existing badges.

## WAVE 6 — English-only execution (dedicated phase; AFTER W1–W3 stabilize IA)

Full removal surface and safe-order already mapped (audit T2-d §8). Sequence:
1. Freeze IA: run W1 redirects stable for one cycle.
2. Frontend: collapse `src/i18n/config.ts` locales to `['en']`; remove locale-switcher + cookie resolution; update the ~10 locale-aware formatter call sites to fixed `en-US`; leave `next-intl` + `messages/en` in place initially (zero-risk English-only UI).
3. Wire contract: keep `?locale=` params accepted-but-pinned (`en`) for one deprecation cycle before hard removal (public consumers exist — `public_v1.py:349`).
4. Backend: simplify `renderers.py` (delete Arabic shaping block :117-251, CHROME ar, rtl branches, rightToLeft sheet views), `contracts.py` locale set, intelligence MSA branches; drop `arabic-reshaper`/`python-bidi` deps.
5. DB: migration for `ck_report_locale`/`ck_user_pref_locale` **with data cleanup first** (existing `locale='ar'` rows would violate tightened constraints — risk D1 in audit).
6. Tests/docs: trim Arabic-path tests; refresh all Arabic-support docs (7 files listed in T2-d §7); keep `guard.py` bidi stripping (security, not Arabic).
- Preserve forever: locale-independent formatters (`src/lib/format.ts`), `week_start` preference, Intl default-locale calls, wire-contract `locale=en` params.

## Cross-cutting requirements (every wave)

- `bunx tsc --noEmit` + `bun run lint` green; dev server smoke on 390px + 1440px; zero console errors.
- No regression in e2e_smoke API contract (run after each wave touching API-adjacent code).
- First frontend test infrastructure arrives with W1: Playwright smoke for the 9-destination shell + redirect map (the audit found zero frontend tests — this is the minimum gate for a UI transformation this size).
- One commit-series per wave; docs updated in the same series (`docs/p01/` remains the reference).

## Out of scope (explicit)

Backend engine/AI changes, new API endpoints, DB schema changes (except the W6 item 5 locale-check migration), satellite ingestion, mobile app.

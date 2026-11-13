# P02-A — Implementation Report (W0 Foundation + W1 Navigation Shell)

**Date:** 2026-11-13 · **Branch:** `main` · **Base:** `d73106f` (P01 audit) / `9ba6395` working HEAD
**Scope:** P01 plan WAVE 0 (foundation fixes) + WAVE 1 (navigation shell) only. W2–W6 untouched.

## 1. Files changed and why

### New files

| File | Purpose |
|---|---|
| `src/lib/navigation.ts` | Pure navigation model: 9 destinations, 27-entry permanent legacy redirect map, `resolveTarget` (idempotent, safe fallbacks). Zero framework imports so `bun test` exercises it directly. |
| `tests/frontend/navigation.test.ts` | 31 bun tests: every matrix §3 mapping, config integrity, idempotency (no redirect loops), unknown-id safety, cross-component targets (entitlement guard, bell kinds, wizard, goTo* helpers), store-level resolution. |
| `src/components/croptwist/navigation/destination-rail.tsx` | Desktop rail (≥xl): nine 44px Radix tabs, icons, active scroll-into-view safety. |
| `src/components/croptwist/navigation/mobile-nav-sheet.tsx` | Hamburger sheet (<xl) using the shipped-but-unused `ui/sheet.tsx` (audit P16): grouped destinations + nested sub-pages, 44px items, Escape close, focus restore, body scroll lock (Radix). |
| `src/components/croptwist/navigation/sub-page-rail.tsx` | Sub-page rail: vertical left rail (lg+) / horizontal chip row (below lg, active chip scroll-into-view). |
| `src/components/croptwist/navigation/context-bar.tsx` | The ONE shared farm/field picker (blueprint §2.1: 20 instances → 1). Same store slice, so deep links and cross-tab selection keep working. |
| `src/components/croptwist/navigation/command-palette.tsx` | W1 palette FOUNDATION (plan 2.4 scope split): Cmd/Ctrl+K + header button; navigation commands for the 9 destinations + 24 sub-pages only — every command is real, nothing invented. |
| `src/components/croptwist/navigation/map-satellite-pane.tsx` | Map & Satellite destination canvas: `FarmMap` (promoted) + `SatelliteIntelligence` (side panel), both verbatim. No imagery/raster capabilities added — honest composition of existing offline surfaces. |
| `src/components/croptwist/state-views.tsx` | W0.7 shared primitives: `SectionLoader` (role=status), `SectionSkeleton`, `ErrorState` (role=alert + retry). |
| `messages/en/destinations.json`, `messages/ar/destinations.json` | Destination + sub-page labels, palette strings, aria labels (en/ar parity maintained). |
| `docs/p02/*` | This report, mapping doc, verification report, known limitations, checklist. |

### Modified files

| File | Change | P01 finding |
|---|---|---|
| `src/lib/store.ts` | `WorkspaceTab` = 9 destination ids + 27 legacy ids; `activeSub`, `navigateTo`, `setActiveSub`; ALL tab writes funnel through one resolver (`tabState`) — legacy ids redirect permanently; interface drift fixed (`goToRotationFor`/`goToWaterFor` now declared); `openCreateFarm`/`goTo*For` route through the resolver. | P12, blueprint §5 |
| `src/components/croptwist/workspace.tsx` | Shell rebuild: 27-tab strip → rail + sub-rails + mobile sheet; URL sync v2 (`push` for user navigation, `replace` only for canonicalization, Back/Forward applied into store, unrelated params preserved); sr-only h1; entitlement guard + bell unchanged (resolve through the store). | P1, P17, P9 |
| `src/components/croptwist/overview.tsx` | W0.1 selection follows store (deep-link `?farm=&field=` drives charts/map; `farms[0]` only as last-resort fallback); W0.2 retry relabeled via shared `ErrorState` (label = `common.retry`); redundant `aria-label="Overview"` removed (h1 covers naming). | P4, P6, P13, P9 |
| `src/components/croptwist/water.tsx` | W0.4 explicit plan loading (`SectionLoader`) + error (`ErrorState` + retry) branches; W0.3 empty-state CTA now lands on Farms & Fields; in-content has-field picker removed (context bar). | P5, P7 |
| `src/components/croptwist/features.tsx` | W0.3 CTA lands on Farms & Fields (label already said so). | P7 |
| `src/components/croptwist/rotation.tsx` | W0.3 same. | P7 |
| `src/components/croptwist/observations.tsx`, `management.tsx`, `field-state.tsx`, `portfolio.tsx`, `satellite.tsx`, `soil-memory.tsx`, `adaptive-evidence.tsx`, `forecast.tsx`, `ai-insights.tsx`, `data-passport.tsx` | Redundant has-field `FieldPicker` removed (context bar fully preserves the control — same store binding). Empty-state pickers with tab-specific guidance KEPT (soil, sensitivity, scenarios, observations, features, water, portfolio, satellite, soil-memory, adaptive-evidence, forecast, failure-lab, data-passport). | blueprint §2.1 |
| `src/components/croptwist/locale-switcher.tsx` | `h-8` → `h-10` trigger (audit-named site). | P8 |
| `src/components/croptwist/p3/team-tab.tsx` | `h-7 w-7` icon button → `h-9 w-9` (audit-named site). | P8 |
| `src/app/layout.tsx` | `Viewport` export with `viewportFit: "cover"` + `themeColor` — activates the footer's existing safe-area CSS (was inert). | P10 |
| `src/app/globals.css` | W0.6 token decision documented in-source (light-only; `.dark` kept dormant; `@custom-variant dark` kept to avoid prefers-color-scheme regression). No visual change. | P2/P3 |
| `src/i18n/config.ts` | `destinations` namespace registered. | — |

### Deleted files (audit-verified dead code only)

| File | Evidence |
|---|---|
| `src/hooks/use-fieldshift.ts` (516 lines) | 0 importers repo-wide (re-verified before delete). | 
| `public/maplibre-gl-shared.mjs` (0 bytes) | 0 references. |
| `tailwind.config.ts` | Tailwind v4 never loads it; hsl-vs-oklch contradictions; wrong globs; 0 refs (components.json `tailwind.config: ""`). |

## 2. Final nine-destination hierarchy

```
1. Overview             Overview                                    (single view)
2. Farms & Fields       Farms & Fields                              (single view, two-pane)
3. Data Hub             Observations & ingestion · Feature runs · Data passport · Evidence gaps & actions
4. Crop Intelligence    Rotation optimizer · Irrigation planning · Soil intelligence ·
                        Crop management · Soil memory · Climate forecast
5. Map & Satellite      Map & vegetation (FarmMap canvas + satellite side panel)
6. Decision Center      Field state · Scenarios · Sensitivity · Robust plan · Decision documents ·
                        Failure lab · Portfolio (farm-wide) · Digital twin (audit trail)
7. AI Copilot           AI Copilot (was "AI Insights")              (single view)
8. Reports & Analytics  Report library · Analytics (was "Insights")
9. Workspace & Settings Organization & members · Billing · Developer
```

27 former tabs → 9 destinations + 24 sub-pages; nothing removed (full map: `P02_NAVIGATION_MAPPING.md`).

## 3. Deep links, notification links, bookmarks, query params

- **All 27 legacy `?tab=` ids** resolve forever through `LEGACY_REDIRECTS` (matrix §3 values, unit-tested + browser-tested 27/27).
- **Resolution point:** the store's `tabState` resolver — the single plug-in point replacing the old `workspace.tsx:131` validation. URL sync, rail, sheet, palette, entitlement guard, onboarding wizard, notification bell and `goTo*` helpers ALL resolve through it; no component carries its own mapping.
- **Notification bell** `link_kind→tab` map untouched — its legacy tab ids resolve at the store.
- **Entitlement guard** Upgrade target untouched — `'billing'` resolves to `settings/billing`.
- **Unknown ids:** ignored safely (state preserved), then the URL canonicalizes to the current view — no loops (idempotency unit-tested; browser-verified).
- **Unrelated params preserved:** canonicalization copies the existing query string and only rewrites the workspace keys — verified live (`utm_source=mailer` survived).
- **`?farm=&field=&fieldName=`** restore the context (store), survive canonicalization, and persist across destination changes.

## 4. Browser-history decision (P17)

**Decision:** user-initiated navigation **pushes** (`router.push`); automatic canonicalization (legacy redirect, initial write) **replaces** (`router.replace`); Back/Forward pops are detected (URL ≠ last-written qs) and applied INTO the store.

- Back/Forward walk the destination history (verified: overview → cropintel/rotation → reports/reports, Back/Forward restore both URL and rendered view).
- No duplicate history entries for canonicalization (verified: `?tab=water` canonicalizes with replace; history Back returns to the ORIGINAL legacy entry, which still resolves).
- Echo suppression (`urlQsRef`) prevents store↔URL feedback loops.

## 5. Accessibility & responsive behavior delivered

- **44px touch targets:** all nine rail triggers measured exactly 44px; sheet items 44px; hamburger 44×44. Audit-named `h-7`/`h-8` header sites bumped (`team-tab` rename button → `h-9 w-9`, locale switcher → `h-10`, header icon buttons → `h-10 w-10`).
- **sr-only `<h1>`** reflecting current destination + sub-page (e.g. "Decision Center — Scenarios"), i18n'd (verified in en + ar).
- **Keyboard:** Radix tab semantics preserved (arrow keys + roving tabindex on both rails); Escape closes the mobile sheet; focus restored to the trigger; body scroll locked while the sheet is open; `aria-current="page"/"location"` in the sheet; visible focus rings via primitives.
- **No-h1 defect fixed** (audit P9): first heading post-auth is now the sr-only h1 (verified in a11y snapshots).
- **Safe-area (P10):** viewport export activates the footer inset on notched devices.
- **Responsive:** 1440px desktop (rail + inline context bar; rail fits with 4px margin at 1280 and 1440); below xl the hamburger sheet replaces the strip entirely (measured: hamburger visible, rail hidden at 390px); mobile context row under the header; sub-rails switch vertical (lg+) → horizontal chips with active scroll-into-view.

## 6. Tests executed and results

See `P02_VERIFICATION_REPORT.md` §2 for exact commands and counts. Summary: 31/31 bun tests, tsc clean, lint clean, API e2e smoke ALL PASSED (backend unchanged), browser verification covering all 27 legacy links, 27 content views, history, mobile sheet, palette, water states, RTL — zero console errors.

## 7. Deferred work (and why)

| Deferred | Why |
|---|---|
| Management's 6 internal sub-views → URL-keyed sub-pages | Plan W2 item 2.1 (extraction wave; biggest component, move-without-rewrite first). |
| Team preferences → true Settings sub-page | Plan W2 item 2.2 (extraction must preserve role gates). |
| Shared execution picker (sensitivity/robust/decisions) | Plan W2 item 2.3. |
| Command palette: field/artifact commands | Plan W2 item 2.4 (W1 ships navigation-only foundation). |
| Overview chart/map dedupe (retire instance) | Plan W3.2 — capabilities only added in W1. |
| Forecast verify-UI wiring | Plan W3.4. |
| Loading/error primitive propagation to remaining tabs | W0.7 minimum surfaces done (water + overview); broader rollout tracked for W2. |
| Dark mode / semantic-token migration | Explicitly the later visual redesign phase (W0.6 decision documented in `globals.css`). |
| Arabic removal | W6 — untouched by design; RTL verified still working. |

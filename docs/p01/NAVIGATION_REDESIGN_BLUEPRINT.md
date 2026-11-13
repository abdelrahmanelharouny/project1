# P01-C — Navigation Redesign Blueprint

**Principle: Fewer destinations, deeper capabilities, clearer decisions.**
Status: blueprint only — no implementation in P01.

---

## 1. Current IA analysis (why 27 tabs fails)

Verified facts (see `UX_AUDIT_REPORT.md` §1, §8):

- 27 static tabs in one horizontal strip (`workspace.tsx:80-108`); 3,263px wide @1440px, 3,047px @390px — measured live. No grouping, no search, no scroll-into-view, no breadcrumbs, no role/plan adaptation.
- Real IA is deeper than 27: `management.tsx` hides 6 sub-tabs; the scenario chain re-presents the same artifacts across 5 tabs; P3 admin tabs mix with scientific tabs; 6 tabs are pure read-only lenses.
- The product already has an implicit workflow spine (data → intelligence → decisions → explanation) visible in the store's cross-tab helpers (`store.ts:79-87`) — the navigation does not express it.

**Conclusion:** the count is not the disease; **ungrouped sameness** is. The fix is destinations that match the user's mental model, with sub-pages and contextual panels — not deleting capabilities.

## 2. Evaluation of the proposed 8-destination structure

| Proposed destination | Verdict vs code | Adjustment |
|---|---|---|
| 1. Overview | Keep as-is | absorb onboarding checklist; fix selection defect first |
| 2. Farms & Fields | Keep | farms CRUD + field detail (map, boundary versions) |
| 3. Geospatial Intelligence | **Premature as full destination** — current geo surface is thin (2 offline map components, no imagery/raster layers, no draw/zoning — `T2-e` audit) | Keep, but scope it honestly: Map & Satellite (existing content), designed as the growth surface for P02+ imagery layers |
| 4. Crop Intelligence | Strong fit | rotation, water, soil, management (+ soil memory, forecast) — the agronomic domain views |
| 5. Decision Center | Strong fit but large | field state → scenarios → sensitivity → robust → decisions (+ failure lab, portfolio, digital twin) — needs sub-page structure |
| 6. AI Copilot | Strong fit | ai-insights becomes the product's conversational home |
| 7. Reports & Analytics | Strong fit | P3 reports + org insights (both already org-scoped) |
| 8. Workspace & Settings | Strong fit | team, billing, developer, preferences (preferences currently has API but no dedicated home) |
| — | **Missing from proposal:** data ingestion/provenance (observations, features, passport, adaptive evidence) — 4 tabs of "where does data come from" that fit nowhere above | Add **Data Hub** destination |

**Final proposed structure: 9 primary destinations** (within the 7–9 envelope):

```
1. Overview            — dashboard, health, quick actions, setup checklist
2. Farms & Fields      — farm/field CRUD, field map, boundary versions
3. Data Hub            — observations (ingest), features, data passport, adaptive evidence
4. Crop Intelligence   — rotation, water, soil, management, soil memory, climate forecast
5. Map & Satellite     — farm map (full-bleed), field boundaries, vegetation indices & scenes
6. Decision Center     — field state, scenarios (+executions), sensitivity, robust plan,
                         decisions, failure lab, portfolio, digital twin
7. AI Copilot          — recommendations, insights strip, advisor chat
8. Reports & Analytics — report jobs (10 types), executive/farm/commercial analytics
9. Workspace & Settings— team (org/members/preferences), billing, developer
```

### 2.1 Destination anatomy

- Destinations 3–6 and 8–9 render a **left sub-page rail** (list of sub-pages) + content pane; destination 2 keeps its current two-pane farm/field layout; 1/7 stay single-view.
- The rail replaces hidden sub-tabs (management's 6 sub-views become visible sub-pages).
- Every sub-page keeps its component and API contract unchanged in phase 1 (pure re-association, zero logic rewrite).
- A **persistent context bar** (farm ▸ field picker, currently `field-picker.tsx` in 20 tabs) moves into the destination header — one instance instead of 20.

## 3. Consolidation register (every proposed grouping, with full impact data)

### C1. Data Hub ◀ observations + features + passport + adaptiveevidence
- **Components:** `observations.tsx`, `features.tsx`, `data-passport.tsx`, `adaptive-evidence.tsx`
- **Why grouped:** one mental model — "what data does my field have, where from, what's missing, request more." Adaptive evidence's actions literally restart the observations chain (`evidence_gaps` → data jobs). Passport is the provenance lens over the same datasets.
- **UX improvement:** the "data loop" (ingest → derive → audit → gap → ingest) becomes one destination instead of 4 scattered tabs; empty-state CTAs (P7 defect) get fixed targets.
- **Technical deps:** sub-page rail; store `goTo*For` helpers remapped; `?tab=observations` etc. redirected.
- **Migration complexity:** Low (re-association only).
- **Regression risks:** deep-link redirect coverage; adaptive-evidence transition flows tested via existing integration tests — UI-only change.

### C2. Crop Intelligence ◀ rotation + water + soil + management + soilmemory + forecast
- **Components:** `rotation.tsx`, `water.tsx`, `soil.tsx`, `management.tsx` (6 sub-views → 6 sub-pages), `soil-memory.tsx`, `forecast.tsx`
- **Why grouped:** these are the agronomic domain engines a crop advisor works through; soil/soil-memory/field-state tri-separation is the worst terminology split in the product.
- **UX improvement:** 6 tabs → 1 destination with 6 sub-pages; management's hidden sub-views become discoverable; forecast verification gains a home (fixes the unwired `verifyForecasts` gap in its natural context).
- **Technical deps:** sub-page rail; management sub-view switcher (`management.tsx:210-236`) lifted to rail or kept one level; store helpers `goToRotationFor/goToWaterFor` formalized (fix P12 drift).
- **Migration complexity:** Medium (largest components; management alone 1,245 lines).
- **Regression risks:** management sub-view state loss if switcher is lifted — mitigate by keeping internal state keyed in URL (`?sub=erosion`); regression coverage exists at API level only, so add manual QA matrix for the 6 sub-views.

### C3. Map & Satellite ◀ farm-map/full-bleed + satellite
- **Components:** `farm-map.tsx` (promoted to destination canvas), `field-map.tsx`, `satellite.tsx` (index panels become side panel), overview's map instance retired (dedupe D4)
- **Why grouped:** the future geospatial surface (imagery layers, NDVI overlays, zoning — P02+) needs ONE home now, even though current capabilities are modest (offline polygons + index tables).
- **UX improvement:** map stops being a widget inside two tabs and becomes the spatial cockpit; satellite index charts dock beside the map they will eventually decorate.
- **Technical deps:** none new in phase 1 (MapLibre already offline via `public/maplibre-gl-worker.mjs`; delete empty `public/maplibre-gl-shared.mjs`).
- **Migration complexity:** Low-Medium (layout rework of satellite panel).
- **Regression risks:** map worker URL setup is order-sensitive (`farm-map.tsx:27-33`) — keep `setWorkerUrl` singleton behavior; polygon data flow unchanged.

### C4. Decision Center ◀ fieldstate + scenarios + sensitivity + robustplan + decisions + failurelab + portfolio + digitaltwin
- **Components:** `field-state.tsx`, `scenarios.tsx` + `scenario-execution.tsx`, `sensitivity.tsx`, `robust-plan.tsx`, `decisions.tsx`, `failure-lab.tsx`, `portfolio.tsx`, `digital-twin.tsx`
- **Why grouped:** this IS the verified decision chain (see inventory §6); 8 tabs of one journey with 5× duplicated verify actions. Sub-pages follow the chain order; digital twin becomes the chain's "audit trail" sub-page; portfolio (farm-scoped) flagged distinctly in the rail.
- **UX improvement:** the product's core journey gets one front door with a visual chain (state → scenario → execute → stress → decide → audit); duplicates become contextual panels instead of separate tabs (e.g., verify buttons live where the artifact is created; other tabs link in).
- **Technical deps:** sub-page rail with chain-aware ordering; `?tab=scenarios&…` redirects; artifact-picker components (`listScenarioExecutions` consumers) become shared pickers.
- **Migration complexity:** High (8 components, cross-linked states) — do in two waves (C4a: fieldstate/scenarios/sensitivity; C4b: robust/decisions/failurelab/portfolio/digitaltwin).
- **Regression risks:** execution-run selection state across sub-pages; sensitivity/robust verify flows (API-tested, UI not — add QA matrix); portfolio is farm-scoped while the rest is field-scoped — rail must show context switch clearly.

### C5. AI Copilot ◀ aiinsights (single)
- **Components:** `ai-insights.tsx`
- **Why:** the explain-layer deserves a named home; rename "AI Insights" vs "Insights" collision resolves itself (insights-tab moves to Reports & Analytics and renames to "Analytics").
- **UX improvement:** navigation labels stop colliding; advisor becomes prominent rather than tab #14.
- **Migration complexity:** Low. **Risks:** none beyond link updates.

### C6. Reports & Analytics ◀ reports + insights (p3)
- **Components:** `p3/reports-tab.tsx`, `p3/insights-tab.tsx`
- **Why:** both are org-scoped, read-mostly, provenance-labeled output surfaces; "Insights" label moves here as "Analytics".
- **UX improvement:** one place for "show me the evidence and the numbers"; report library and dashboards cross-link.
- **Migration complexity:** Low. **Risks:** role-gating differences none (both membership-gated server-side).

### C7. Workspace & Settings ◀ team + billing + developer (+ preferences gets a home)
- **Components:** `p3/team-tab.tsx` (org/members/invitations/activity), preferences section extracted to a true Settings sub-page (`/preferences` API exists; currently only a section inside team-tab), `p3/billing-tab.tsx`, `p3/developer-tab.tsx`
- **Why:** administrative sphere; role-gated content stays inside components (server remains authority).
- **UX improvement:** admin tabs stop sitting between scientific tabs; settings (locale-independent prefs incl. week_start, units) finally discoverable.
- **Migration complexity:** Medium (extract preferences sub-page from `p3/team-tab.tsx:1162-1179` section).
- **Regression risks:** team-tab is 1,464 lines — extraction must preserve role gating (`roleAtLeast` sites :220-221,374,503).

### C8. Overview fixes (not a consolidation)
- Fix `farms[0]` binding (`overview.tsx:59-62`) to honor store selection; absorb setup checklist; retire duplicated map/coverage charts in favor of links into Map & Satellite / Data Hub (dedupe D2/D3/D4).

### C9. Header redesign
- Replace 27-tab strip with: **destination rail (9)** + persistent context bar (farm/field) + search/command palette (`ui/command.tsx` already shipped, unused) + notifications bell + onboarding entry.
- Mobile: destinations become a `ui/sheet.tsx` hamburger (shipped, unused); sub-pages scroll vertically — **eliminates the 3,047px strip entirely**.

## 4. What stays independently accessible
Overview, Farms & Fields, AI Copilot, Reports & Analytics, Workspace & Settings are single-view destinations. Map & Satellite and Data Hub are two-pane. All 27 current capabilities remain reachable — nothing is deleted; 6 of them additionally appear as contextual panels elsewhere (e.g., passport panel on field pages) without duplicating implementation (same component, shared state).

## 5. Deep-link compatibility (mandatory)
- Keep the `WorkspaceTab` union as the URL contract; add a redirect map `legacy ?tab=X → destination+sub-page` for all 27 ids (`workspace.tsx:131` validation point is where the map plugs in).
- Add `?sub=` for sub-pages; preserve `?farm=&field=`.
- Old links (user bookmarks, notification `link_kind` targets in `p3/notifications-bell.tsx`) must resolve — the bell's link map is part of the redirect table.

## 6. Non-goals (explicit)
- No capability removal; no backend/API change; no new auth model; no rewrite of the 1,000+ line components' internals in phase 1 (they become sub-pages as-is).

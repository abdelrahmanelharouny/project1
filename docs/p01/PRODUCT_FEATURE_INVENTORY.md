# P01-A — Product Feature Inventory

**Audit date:** 2026-11-13 · **Baseline:** branch `main`, HEAD `a83af70` · 0 uncommitted changes
**Method:** direct component-by-component source inspection (read-only), cross-checked against `docs/audit/CropTwist-Phase-Checkpoint-2026-11-13.md` and verified against the running stack. Every row cites real files. Classification is from code, never from names.

**Counts (verified):** 27 workspace tabs (`src/components/croptwist/workspace.tsx:80-108`, mirrored by the 27-value `WorkspaceTab` union in `src/lib/store.ts:5-32`) · 31 top-level components + 5 chart components + 7 P3 components · 39 mounted routers / 288 endpoints (`mini-services/fieldshift-api/app/api/v1/router.py:48-98`) · 7-role RBAC (`app/domains/identity/service.py:63-71`).

---

## 1. Workspace shell

- Entry: `src/app/page.tsx` → dynamic import (`ssr:false`, maplibre safety) → `Workspace` (`src/components/croptwist/workspace.tsx`, 459 lines) with phase machine `checking → guest → authed`.
- Auth: `src/components/croptwist/auth-gate.tsx` (login/register/demo) → Next.js route handlers `src/app/api/auth/*` proxy FastAPI and set HttpOnly cookies (`fs_token`/`fs_refresh`). Tokens never reach JS.
- Deep links: `useWorkspaceUrlSync` (`workspace.tsx:118-164`) restores `?tab=&farm=&field=&fieldName=`; `router.replace` used, so browser Back does not walk tab history.
- Entitlement guard: `src/lib/entitlement-guard.ts` mounted at `workspace.tsx:294-303` — any 402 envelope → one deduped toast with Upgrade action → billing tab.
- **Tab visibility is static for all signed-in users** (no role- or plan-based tab hiding); gating happens inside P3 tab content (`p3/team-tab.tsx:220-221`, `p3/billing-tab.tsx` org states) and server-side (402/403).

---

## 2. Feature inventory (one row per tab)

Status legend: **functional** = real API flows + handlers; **partial** = some flows implemented but a wired backend capability is missing in UI; **read-only** = viewer by design. No frontend component contains mock/random data (verified by scan); synthetic content is server-produced and always badged (`src/components/croptwist/badges.tsx`).

| # | Tab | Component (lines) | User purpose | Role | Key API dependencies | Engines behind it | Status | Independent or workflow step | Duplication |
|---|---|---|---|---|---|---|---|---|---|
| 1 | overview | `overview.tsx` (251) | Dashboard: stats, health, farm map, climate+coverage charts, quick actions | all | GET `/farms`, `/farms/{id}/fields`, `/health/ready` | displays L1 data | functional (defect: binds `farms[0]` ignoring selection, `overview.tsx:59-62`) | destination | map+coverage duplicate Farms/Observations views |
| 2 | farms | `farms-fields.tsx` (1,123) | Farm & field CRUD, boundary versioning, field map, export | owner/manager to mutate | POST/PATCH `/farms*`, `/fields*`, `/fields/{id}/boundary-versions`, `/fields/{id}/map` | `app/geospatial/validation.py` (WGS84, geodesic area) | functional | destination (entry point of every workflow) | FarmMap rendered also on Overview |
| 3 | observations | `observations.tsx` (1,239) | Data ingestion: synthetic/Open-Meteo jobs, CSV import, CHIRPS GeoTIFF, observation tables/charts | agronomist/analyst | POST `/fields/{id}/data-jobs`, `/imports/observations-csv`, `/chirps-extractions`; GET `/observations`, `/data-coverage`, `/data/catalog`, `/data/providers/health` | L1 providers + feature engine inputs | functional | **feeds everything** (root of the data chain) | coverage chart duplicated on Overview |
| 4 | features | `features.tsx` (713) | Feature-engineering runs, value tables, run comparison, catalog | agronomist | POST/GET `/fields/{id}/feature-runs`, GET `/feature-runs/{runId}/values`, compare, `/features/catalog` | `app/features/` (~24 versioned features) | functional (defect: empty-state button jumps to Observations with empty field, `features.tsx:573`) | step (input for rotation/water/AI) | overlap: features catalog vs knowledge crops |
| 5 | rotation | `rotation.tsx` (941) | Crop history, candidate screening, CP-SAT rotation optimizer (Pareto, explanations), knowledge browser | agronomist | POST `/crop-history`, `/crop-candidates`, `/rotation-runs`; GET strategies/comparison; knowledge endpoints | `app/rotation/optimizer.py` (CP-SAT) | functional (minor: `hemisphere:'north'` hardcoded `rotation.tsx:335,587`) | step | knowledge browser overlaps water readiness |
| 6 | water | `water.tsx` (1,141) | Irrigation plan builder (simple/expert FAO-56), readiness, history, monthly balance chart | manager/agronomist | POST/DELETE `/water-plans*`, GET readiness/methods | `app/water/planner.py` (FAO-56) | functional (defect: active-plan query has no loading/error state, `water.tsx:976,1010-1021`; empty-state defect `:998`) | step | readiness vs knowledge crops overlap |
| 7 | fieldstate | `field-state.tsx` (556) | Immutable field-state snapshots, verify, compare, manifest | agronomist | POST `/field-states*`, `/field-states/compare`, GET manifest | `app/field_state/service.py` (checksummed) | functional | step (pins scenarios) | — |
| 8 | scenarios | `scenarios.tsx` (947) + `scenario-execution.tsx` (681) | Scenario authoring (types taxonomy), validate/finalize/versions/lineage, **execution** sub-workflow | agronomist | `/scenarios*` (15 endpoints), `/scenarios/{id}/executions`, derived-observations/features | `app/scenarios/`, `app/scenario_execution/` (M7.3) | functional | step (chain head) | verify buttons duplicated in 5 tabs (chain) |
| 9 | soil | `soil.tsx` (846) | Soil profile, indicators, health, SOC stock runs, nutrient budget, lab CSV import, readiness | agronomist | `/soil-*` (23 endpoints), `/soil-samples/import` | `app/soil/` (chemistry, SOC, nutrients) | functional | step / destination | provenance lens duplicated by passport |
| 10 | management | `management.tsx` (1,245) | 6 sub-views: management plan, cover crops, timeline, residue ledger, erosion screening, operations scheduling (CP-SAT) | manager/agronomist | ~30 endpoints under `/fields/{id}/*`, `/farms/{id}/resources` | `app/management/*` (soil_cover, cover_crops, residue, erosion, scheduling CP-SAT) | functional (membership-only authz server-side) | step / destination | largest tab; 6 hidden sub-tabs = hidden IA |
| 11 | sensitivity | `sensitivity.tsx` (1,041) | OAT/multi-axis sensitivity over executions, uncertainty, verify, tornado+curves charts | agronomist | `/sensitivity-analyses*` (8 endpoints) | `app/sensitivity/` (M7.4) | functional | step | — |
| 12 | robustplan | `robust-plan.tsx` (667) | Scenario sets → robust (regret-analysis) shared rotation, evaluations, verify | agronomist | `/scenario-sets*`, `/robust-runs*` (11 endpoints) | `app/robust_rotation/engine.py` | functional (minor: hardcoded season presets `:78`) | step | — |
| 13 | decisions | `decisions.tsx` (412) | Unified decision-comparison documents across artifacts, verify | agronomist/manager | `/decision-comparisons*` | `app/decision/service.py` (M7.6) | functional | step (chain end) | overlaps AI Insights "what to do" |
| 14 | aiinsights | `ai-insights.tsx` (1,072) | AI recommendations (7 generators), anomaly strip, field brief, advisor chat (multi-session), feedback loop | farmer/agronomist | GET/POST `/recommendations*`, `/insights`, `/advisor/query`, `/feedback`, AI metrics | `app/recommendations/` + `app/intelligence/` + llm-bridge | functional | destination (explain layer) | "what to do" overlaps decisions |
| 15 | digitaltwin | `digital-twin.tsx` (385) | Traceable artifact graph (states/features/scenarios/executions/sensitivity/robust/decisions) + validate | agronomist | GET `/digital-twin`, POST validate | `app/digital_twin/service.py` | functional | step (chain aggregator) | re-lists artifacts from 5 tabs |
| 16 | passport | `data-passport.tsx` (386) | Data passport: coverage, dataset products (synthetic/real split), warnings, quality | all | GET `/data-passport`, `/data/catalog` | `app/passport/service.py` | functional (read-only) | destination | lens overlaps observations/soil |
| 17 | satellite | `satellite.tsx` (254) | Vegetation indices (ndvi/evi/savi/ndmi/ndwi) monthly bars + scenes table + stress signals | agronomist | GET `/vegetation/indices`, `/vegetation/summary`, `/vegetation/scenes` | `app/vegetation/` (P2.A) — live Sentinel-2 BLOCKED, `satellite_sim` drives data | functional (read-only; provider honesty preserved) | destination | no map rendering of NDVI (charts only) |
| 18 | forecast | `forecast.tsx` (227) | Climate forecast capabilities, ingest Open-Meteo window, risks | agronomist | GET capabilities, POST `/forecasts/ingest`, GET window/risks | `app/climate/` (P2.B) | **partial** — `verifyForecasts` (`src/lib/api.ts:1542-1544`) is wired in API client but called by NO component | destination | — |
| 19 | soilmemory | `soil-memory.tsx` (213) | Soil memory timeline, alerts, snapshots, change estimates | agronomist | GET timeline/alerts, POST snapshots/change-estimates | `app/soil/memory_service.py` (P2.C) | functional | destination | 3-way split with soil/fieldstate |
| 20 | failurelab | `failure-lab.tsx` (241) | Stress-test rotation against failure packs | agronomist | GET `/failure-lab/packs`, POST `/rotation-stress-runs*` | `app/failure_lab/` (P2.D) | functional | step (decision-support) | — |
| 21 | adaptiveevidence | `adaptive-evidence.tsx` (301) | Evidence gaps, staleness, action lifecycle, apply evidence | agronomist | GET `/evidence-gaps`, `/evidence/staleness`, POST `/evidence-actions*`, `/evidence/apply` | `app/evidence_gaps/` (P2.E, VoI) | functional | step (closes the data loop) | — |
| 22 | portfolio | `portfolio.tsx` (249) | Farm-level portfolio optimizer (crop shares, water multiplier, modes), verify | manager | GET `/portfolio/constraints`, POST `/farms/{id}/portfolio-runs*` | `app/portfolio/optimizer.py` (CP-SAT) | functional | destination (farm-scoped) | — |
| 23 | team | `p3/team-tab.tsx` (1,464) | Orgs, members + 7-role management, invitations, ownership transfer, activity, preferences | org_admin/owner | `/orgs*` (12), `/invitations/accept`, `/orgs/{id}/activity`, `/preferences` | `app/orgs/`, `app/domains/identity/` | functional (role-gated UI: `:220-221,374,503`) | destination | org-create duplicated by onboarding wizard |
| 24 | insights | `p3/insights-tab.tsx` (865) | Executive dashboard, farm performance, commercial metrics, benchmarks (provenance-labeled) | org_admin/owner | GET `/analytics/*` (4) | `app/analytics/service.py` | functional (read-only) | destination | — |
| 25 | reports | `p3/reports-tab.tsx` (815) | 10 report types × pdf/xlsx/csv × en/ar, queue + scheduler, schedule, download | manager+ | `/reports*` (8) | `app/reports/` (+renderers, Arabic PDF) | functional | destination | two parallel export systems (client CSV vs report jobs) |
| 26 | billing | `p3/billing-tab.tsx` (946) | Plans, subscription lifecycle, usage vs entitlements, invoices, sandbox pay (Test mode) | org_admin+ | `/billing*` (11) | `app/billing/` (sandbox provider) | functional (sandbox-only; honestly labeled) | destination | — |
| 27 | developer | `p3/developer-tab.tsx` (1,146) | API keys, webhooks, deliveries/redeliver, usage, events catalog | org_admin+ | `/developer*` (13), `/public/v1` (9 read-only) | `app/publicapi/` | functional | destination | — |

### Shared components (not tabs)

| File | Role | Consumers |
|---|---|---|
| `field-picker.tsx` | farm-grouped field selector | 20 tabs (N+1 fetch pattern in `use-croptwist.ts:124-140`) |
| `farm-map.tsx` / `field-map.tsx` | offline MapLibre maps | overview, farms-fields |
| `badges.tsx` | SyntheticBadge/Quality/JobStatus/Passport badges | 6 tabs |
| `export-button.tsx` + `src/lib/export.ts` | client CSV/JSON export | 5 tabs |
| `locale-switcher.tsx` | en/ar switch (cookie) | workspace header |
| `p3/notifications-bell.tsx` | notification center + 60s polling | workspace header |
| `p3/onboarding-wizard.tsx` | 9-step "Get started" wizard | workspace header |

---

## 3. Chart components (`src/components/croptwist/charts/`)

| File | Chart | Consumer |
|---|---|---|
| `climate-overview.tsx` | ComposedChart dual-axis precip+temp | overview |
| `data-coverage.tsx` | horizontal bar (top-16 variables) | overview |
| `soil-soc.tsx` | SOC by depth (measured vs predicted) | soil |
| `water-monthly.tsx` | monthly water balance composed | water |
| `sensitivity-charts.tsx` | tornado + response curves | sensitivity |
| inline in `observations.tsx:835-868` | temp/precip line+bar | observations |
| inline in `satellite.tsx:115-129` | CSS bars (not recharts) | satellite |
| inline in `p3/insights-tab.tsx:471-479` | crop-distribution bar | insights |

---

## 4. Duplication register (ranked)

1. **Scenario artifact chain spans 5 tabs** — executions selected in `sensitivity.tsx:58`, `robust-plan.tsx:223-238`, compared in `decisions.tsx`, re-listed in `digital-twin.tsx`; verify actions duplicated 5×.
2. Climate chart duplicated — `charts/climate-overview.tsx` (overview) vs inline `observations.tsx:479-504` (same endpoint).
3. Data coverage duplicated — `charts/data-coverage.tsx` vs `observations.tsx:1080-1099`.
4. FarmMap mounted twice — `overview.tsx:189` and `farms-fields.tsx:851,906`.
5. Two export systems — client-side `export-button.tsx` vs server report jobs (`p3/reports-tab.tsx`).
6. "What should I do" — `ai-insights.tsx` vs `decisions.tsx`.
7. Soil lenses — `soil.tsx` vs `data-passport.tsx` vs `digital-twin.tsx` (same underlying endpoints).
8. Crop knowledge — rotation KnowledgeBrowser vs water readiness card.
9. Org creation — `p3/team-tab.tsx:278` vs `p3/onboarding-wizard.tsx` org step.
10. Backend health shown 3× — `auth-gate.tsx:21-44`, `overview.tsx:125-144`, `workspace.tsx:177-189`.

---

## 5. Orphans / dead code / defects found during inventory

- **Dead file:** `src/hooks/use-fieldshift.ts` (516 lines) — zero importers in `src/` (grep-verified). Rebrand leftover duplicating `use-croptwist.ts`.
- **Dead artifact:** `public/maplibre-gl-shared.mjs` — 0 bytes, referenced nowhere.
- **Dead config:** `tailwind.config.ts` — content globs point to non-existent `./pages`, `./components`, `./app` (verified `tailwind.config.ts:6-10`); Tailwind v4 `@theme inline` in `globals.css` is the real source; no `@config` directive loads this file.
- **Unwired capability:** `verifyForecasts` (`src/lib/api.ts:1542-1544`) — backend POST `/forecast-verifications` exists; no UI calls it → forecast tab classified partial.
- **Navigation defect:** empty-state buttons in `features.tsx:573`, `rotation.tsx:867`, `water.tsx:998` call `goToObservationsFor({id:'',name:'',farmId:''})` while labeled "go to farms / create farm+field" — they land on Observations with no field.
- **Selection defect:** `overview.tsx:59-62` always binds `farms[0]` + first field, ignoring the store's selected farm/field (breaks `?farm=&field=` deep links on the default tab).
- **Store drift:** `src/lib/store.ts:82-83` implement `goToRotationFor`/`goToWaterFor` not declared in the `CropTwistUiState` interface (`store.ts:40-57`).

---

## 6. Workflow dependency map (verified chain)

```
observations ──► features ──► rotation / water / soil / management
     │                │                │
     │                └──► (AI evidence pack)
     ▼
passport (lens)          fieldstate ──► scenarios ──► scenario executions
                                                              │
                    ┌─────────────────────────────────────────┤
                    ▼                     ▼                   ▼
              sensitivity            scenario sets        decisions
                    │                     │                   ▲
                    └────► robust plan ◄──┘                   │
                                 │                            │
                                 └────────► digital twin (aggregator)
adaptive-evidence ◄── gap detection ──► requests data ──► observations (loop close)
satellite / forecast / soil-memory : independent read lenses (P2)
portfolio: farm-level optimizer (parallel to per-field chain)
p3 sphere: team / insights / reports / billing / developer (org-level, role-gated)
```

Cross-tab deep links implemented via store helpers `goToPassportFor`, `goToFeaturesFor`, `goToFieldStateFor`, `goToScenariosFor`, `goToObservationsFor` (`src/lib/store.ts:79-87`).

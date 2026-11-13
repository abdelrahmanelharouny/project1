# P01-E — UX Migration Matrix

Component-by-component mapping: current 27-tab structure → proposed 9-destination IA (per `NAVIGATION_REDESIGN_BLUEPRINT.md`). Work column distinguishes **Move** (re-associate, no logic change) / **Move+Fix** (known defects fixed during move) / **Extract** (sub-page split) / **Retire-instance** (duplicate mount removed; component kept).

## 1. Tab → destination matrix

| Current tab | Component | New destination | Sub-page | Work | Key risks |
|---|---|---|---|---|---|
| overview | `overview.tsx` | Overview | — | Move+Fix (selection defect P4; retry label P6; dedupe charts D2/D3; retire map instance D4) | deep-links `?tab=overview` unchanged |
| farms | `farms-fields.tsx` | Farms & Fields | Farm/field detail (unchanged two-pane) | Move | none — low-risk anchor |
| observations | `observations.tsx` | Data Hub | Observations & ingestion | Move+Fix (wrong-tab CTA P7) | redirect from old id |
| features | `features.tsx` | Data Hub | Feature runs | Move+Fix (CTA P7) | redirect |
| passport | `data-passport.tsx` | Data Hub | Data passport | Move | also becomes contextual panel on field pages (shared instance) |
| adaptiveevidence | `adaptive-evidence.tsx` | Data Hub | Evidence gaps & actions | Move | transition flows — QA matrix row |
| rotation | `rotation.tsx` | Crop Intelligence | Rotation optimizer | Move+Fix (CTA P7; formalize `goToRotationFor` store drift P12) | redirect |
| water | `water.tsx` | Crop Intelligence | Irrigation planning | Move+Fix (silent failure P5; CTA P7) | plan loading/error states added |
| soil | `soil.tsx` | Crop Intelligence | Soil intelligence | Move | 6 cards stay intact |
| management | `management.tsx` | Crop Intelligence | 6 sub-pages lifted from internal switcher (`management.tsx:210-236`): plan / cover crops / timeline / residue / erosion / operations | Extract | sub-view state → `?sub=`; biggest single component (1,245 lines) — move without rewrite first |
| soilmemory | `soil-memory.tsx` | Crop Intelligence | Soil memory | Move | rename of whole-tab `dir="ltr"` pin removal is part of EN-only phase, not this move |
| forecast | `forecast.tsx` | Crop Intelligence | Climate forecast | Move+Fix (wire verifyForecasts UI) | partial status → functional after wiring |
| satellite | `satellite.tsx` | Map & Satellite | Vegetation indices & scenes (side panel) | Move | CSS-bar chart may move to recharts for consistency (separate task, optional) |
| farms-map instance | `farm-map.tsx` (overview mount) | Map & Satellite | Map canvas (full-bleed destination) | Retire-instance (overview) + Promote | keep worker singleton (`farm-map.tsx:27-33`) |
| fieldstate | `field-state.tsx` | Decision Center | 1. Field state | Move | chain rail order starts here |
| scenarios | `scenarios.tsx` + `scenario-execution.tsx` | Decision Center | 2. Scenarios (+execution section kept inside) | Move | execution flows QA (API-covered only) |
| sensitivity | `sensitivity.tsx` | Decision Center | 3. Sensitivity | Move | shared execution-picker extraction |
| robustplan | `robust-plan.tsx` | Decision Center | 4. Robust plan | Move+Fix (season presets hardcoded `:78` — note only) | |
| decisions | `decisions.tsx` | Decision Center | 5. Decision documents | Move | |
| failurelab | `failure-lab.tsx` | Decision Center | 6. Failure lab | Move | |
| portfolio | `portfolio.tsx` | Decision Center | 7. Portfolio (farm-scoped badge) | Move | context switch field→farm must be explicit in rail |
| digitaltwin | `digital-twin.tsx` | Decision Center | 8. Audit trail (twin) | Move | |
| aiinsights | `ai-insights.tsx` | AI Copilot | — (single view) | Move | nav label collision resolves ("AI Copilot") |
| reports | `p3/reports-tab.tsx` | Reports & Analytics | Report library | Move | link_kind map in notifications-bell updated |
| insights | `p3/insights-tab.tsx` | Reports & Analytics | Analytics (rename from "Insights") | Move+Rename | no i18n removal — en/ar labels updated in same commit |
| team | `p3/team-tab.tsx` | Workspace & Settings | Organization & members | Extract (preferences section → Settings sub-page) | preserve role gates `:220-221,374,503` |
| billing | `p3/billing-tab.tsx` | Workspace & Settings | Billing | Move | entitlement-guard Upgrade action retargets here |
| developer | `p3/developer-tab.tsx` | Workspace & Settings | Developer | Move | `dir="ltr"` pins stay until EN-only phase |

## 2. Shared components mapping

| Component | Consumers today | After migration |
|---|---|---|
| `field-picker.tsx` | 20 tabs | **1 instance** in destination context bar; store `selectedField` unchanged — biggest simplification |
| `farm-map.tsx` | overview + farms-fields | Map & Satellite canvas + farms-fields field detail (2 mounts, was 3) |
| `field-map.tsx` | farms-fields | unchanged |
| `badges.tsx` | 6 tabs | unchanged |
| `export-button.tsx` | 5 tabs | unchanged; contextual "quick export" in Reports & Analytics library (phase 2) |
| `charts/*` | overview/soil/water/sensitivity | unchanged; overview duplicates removed |
| `p3/notifications-bell.tsx` | header | unchanged; `link_kind→tab` map redirected |
| `p3/onboarding-wizard.tsx` | header | unchanged; becomes sole first-run surface |
| `locale-switcher.tsx` | header | unchanged until EN-only execution phase |
| `src/hooks/use-fieldshift.ts` | **0 importers** | safe delete (rebrand leftover; verified) |
| `public/maplibre-gl-shared.mjs` | **0 refs, 0 bytes** | safe delete (verified) |
| `tailwind.config.ts` | not loaded (TW v4) | delete or reconcile before theme work (P3) |

## 3. URL redirect map (all 27 legacy ids)

`?tab=` values are validated at `workspace.tsx:131` against `TAB_IDS`; migration inserts a redirect table between validation and store write:

```
overview→overview
farms→farms
observations→datahub/observations     features→datahub/features
passport→datahub/passport             adaptiveevidence→datahub/evidence
rotation→cropintel/rotation           water→cropintel/irrigation
soil→cropintel/soil                   management→cropintel/management
soilmemory→cropintel/soilmemory       forecast→cropintel/forecast
satellite→geo/map                     fieldstate→decisions/state
scenarios→decisions/scenarios         sensitivity→decisions/sensitivity
robustplan→decisions/robust           decisions→decisions/documents
failurelab→decisions/failurelab       portfolio→decisions/portfolio
digitaltwin→decisions/twin            aiinsights→copilot
reports→reports/reports               insights→reports/analytics
team→settings/organization            billing→settings/billing
developer→settings/developer
```

Legacy ids remain valid forever (redirect, not removal). Unknown ids still ignored safely. New ids introduced only additively (`datahub`, `cropintel`, `geo`, `decisions`, `copilot`, `reports`, `settings`).

## 4. Sequencing & dependency notes

1. Wave 0 (foundation): theme/token consolidation (P2/P3), defect fixes P4–P7, delete dead files — zero IA change.
2. Wave 1 (shell): destination rail + context bar + redirect map + mobile sheet nav. All 27 components move verbatim.
3. Wave 2 (extractions): management sub-pages, team preferences sub-page, shared execution picker.
4. Wave 3 (panels/dedupe): contextual passport/twin panels, overview dedupe, reports unification.
5. Wave 4 (EN-only + polish): per EN-only plan (separate phase; `UX_AUDIT_REPORT.md` P2 theme + i18n plan in `P01_VERIFICATION_REPORT.md` §i18n).

Every wave leaves the app fully functional and deep-link-compatible; no wave requires API or DB change.

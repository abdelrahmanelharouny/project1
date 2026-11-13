# P02-B — Navigation Mapping (authoritative post-W1 reference)

Companion to `docs/p01/UX_MIGRATION_MATRIX.md`. After P02 W1, `src/lib/navigation.ts` is the
single source of truth; this document records what shipped and the one documented deviation.

## 1. The `decisions` id collision (documented disambiguation)

Four ids exist as BOTH legacy tab ids and new destination ids: `overview`, `farms`, `reports`,
`decisions`.

- `overview`, `farms`: identical meaning in both eras (legacy redirect = destination default).
- `reports`: legacy "Reports" tab → Report library, which IS the first sub-page of the new
  Reports & Analytics destination — both interpretations land on the same view.
- **`decisions` is the one real collision:** the legacy "Decision documents" tab vs the new
  Decision Center destination. `UX_MIGRATION_MATRIX.md` §3 says `decisions→decisions/documents`
  while also introducing the destination id `decisions`. **Resolution (deliberate):** for the
  bare id, the CANONICAL (destination) meaning wins — `?tab=decisions` opens the Decision Center
  at its default sub-page (Field state). The exact old view remains reachable via
  `?tab=decisions&sub=documents` and as the fifth item in the destination's sub rail.
  Rationale: the bare id is written by every future rail/palette click (highest-frequency
  semantics); a legacy bookmark lands one rail-click from the exact old view. Recorded in
  `LEGACY_REDIRECTS` (kept for documentation/`isLegacyTab`) and unit-tested accordingly.

## 2. Old tab → new destination map (shipped)

| # | Legacy `?tab=` | Component (verbatim) | New destination | Sub-page | Canonical URL |
|---|---|---|---|---|---|
| 1 | `overview` | overview.tsx | Overview | — | `?tab=overview` |
| 2 | `farms` | farms-fields.tsx | Farms & Fields | — | `?tab=farms` |
| 3 | `observations` | observations.tsx | Data Hub | Observations & ingestion | `?tab=datahub&sub=observations` |
| 4 | `features` | features.tsx | Data Hub | Feature runs | `?tab=datahub&sub=features` |
| 5 | `passport` | data-passport.tsx | Data Hub | Data passport | `?tab=datahub&sub=passport` |
| 6 | `adaptiveevidence` | adaptive-evidence.tsx | Data Hub | Evidence gaps & actions | `?tab=datahub&sub=evidence` |
| 7 | `rotation` | rotation.tsx | Crop Intelligence | Rotation optimizer | `?tab=cropintel&sub=rotation` |
| 8 | `water` | water.tsx | Crop Intelligence | Irrigation planning | `?tab=cropintel&sub=irrigation` |
| 9 | `soil` | soil.tsx | Crop Intelligence | Soil intelligence | `?tab=cropintel&sub=soil` |
| 10 | `management` | management.tsx | Crop Intelligence | Crop management (internal 6-view switcher kept until W2) | `?tab=cropintel&sub=management` |
| 11 | `soilmemory` | soil-memory.tsx | Crop Intelligence | Soil memory | `?tab=cropintel&sub=soilmemory` |
| 12 | `forecast` | forecast.tsx | Crop Intelligence | Climate forecast | `?tab=cropintel&sub=forecast` |
| 13 | `satellite` | satellite.tsx | Map & Satellite | Map & vegetation (side panel beside FarmMap) | `?tab=geo&sub=map` |
| 14 | `fieldstate` | field-state.tsx | Decision Center | Field state | `?tab=decisions&sub=state` |
| 15 | `scenarios` | scenarios.tsx (+ scenario-execution.tsx inside) | Decision Center | Scenarios | `?tab=decisions&sub=scenarios` |
| 16 | `sensitivity` | sensitivity.tsx | Decision Center | Sensitivity | `?tab=decisions&sub=sensitivity` |
| 17 | `robustplan` | robust-plan.tsx | Decision Center | Robust plan | `?tab=decisions&sub=robust` |
| 18 | `decisions` | decisions.tsx | Decision Center | Decision documents (see §1) | `?tab=decisions&sub=documents` |
| 19 | `failurelab` | failure-lab.tsx | Decision Center | Failure lab | `?tab=decisions&sub=failurelab` |
| 20 | `portfolio` | portfolio.tsx | Decision Center | Portfolio (farm-wide badge in rail) | `?tab=decisions&sub=portfolio` |
| 21 | `digitaltwin` | digital-twin.tsx | Decision Center | Digital twin (audit trail) | `?tab=decisions&sub=twin` |
| 22 | `aiinsights` | ai-insights.tsx | AI Copilot | — (renamed destination label) | `?tab=copilot` |
| 23 | `reports` | p3/reports-tab.tsx | Reports & Analytics | Report library | `?tab=reports&sub=reports` |
| 24 | `insights` | p3/insights-tab.tsx | Reports & Analytics | Analytics (renamed from "Insights") | `?tab=reports&sub=analytics` |
| 25 | `team` | p3/team-tab.tsx | Workspace & Settings | Organization & members | `?tab=settings&sub=organization` |
| 26 | `billing` | p3/billing-tab.tsx | Workspace & Settings | Billing | `?tab=settings&sub=billing` |
| 27 | `developer` | p3/developer-tab.tsx | Workspace & Settings | Developer | `?tab=settings&sub=developer` |

New mount added (capability ADDED, none removed): `MapSatellitePane` composes the existing
`FarmMap` (canvas) + `SatelliteIntelligence` (side panel) at `?tab=geo&sub=map`. The Overview
map instance remains until W3.2 dedupe.

## 3. In-app navigation targets preserved (all resolve through the store resolver)

| Consumer | Legacy call | Resolves to | Verified |
|---|---|---|---|
| Entitlement guard (workspace + toast Upgrade) | `setActiveTab('billing')` | settings/billing | unit + browser URL |
| Notification bell `link_kind` map | `farms/reports/insights/billing/team/developer` | farms · reports/reports · reports/analytics · settings/billing · settings/organization · settings/developer | unit |
| Onboarding wizard | `goTab('farms')` ×3, `goTab('team')` | farms · settings/organization | unit |
| Overview quick actions | `goToPassportFor(field)`, `setActiveTab('observations'|'farms')` | datahub/passport · datahub/observations · farms | unit + browser |
| Cross-tab helpers | `goToFieldStateFor/goToScenariosFor/goToFeaturesFor/goToRotationFor/goToWaterFor/goToObservationsFor` | decisions/state · decisions/scenarios · datahub/features · cropintel/rotation · cropintel/irrigation · datahub/observations | unit |
| Field picker "Go to Farms & Fields" | `setActiveTab('farms')` | farms | browser |
| W0.3 fixed empty-state CTAs | `setActiveTab('farms')` (was `goToObservationsFor({id:''…})`) | farms | browser |

## 4. URL grammar

```
/?tab=<destination|legacy>&sub=<sub-page>&farm=<id>&field=<id>&fieldName=<name>&<other params preserved>
```

- `tab` accepts 9 destination ids + 27 legacy ids (forever).
- `sub` validated per-destination; invalid/missing → destination default; single-view destinations have none.
- `farm/field/fieldName` restore the shared context.
- All other params survive canonicalization (copy-then-rewrite).
- Unknown `tab` → state unchanged → URL canonicalizes to the current view. No loops (idempotent resolver, unit-tested).

# Authenticated Browser QA Matrix — CropTwist

> **Status: partial authenticated browser QA completed (2026-11-14); this branch is not deployment-ready.** This matrix began as a source-derived checklist. The execution summary below supersedes its earlier “no browser/runtime QA” preparation note. Per-destination rows remain a source-derived checklist for interactions and states that were not exhaustively exercised.
>
> **Verified isolated environment:** `abdelrahmanelharouny/project1`, branch `feature/croptwist-ui-ux-redesign`, based on `feature/ai-complete-integration` at `38f8891696f6c27e79e25ddf65b33549f4a51397`. Authenticated screenshots used the synthetic `demo@croptwist.local` account in the disposable `croptwist_ui_qa_test` PostgreSQL/PostGIS database under `/tmp`; Alembic migrations were applied and API readiness returned 200 before login. No production or shared database was used.
>
> **Provider/network safety:** Browser external requests were blocked; backend provider URLs pointed only to loopback port 9 and ambient model credentials were unset. No live satellite, weather, AI/model, payment, or other external provider calls were made. The persistent workspace banner labels seeded records as illustrative synthetic fixtures.
>
> **Read-only limit:** Browser interaction covered navigation, field context, locale switching, deep links, history, and keyboard checks. No farm/field/report/settings form was submitted; no ingestion, satellite acquisition/processing, AI generation, or payment action was triggered. Demo seeding was the sole data write and was confined to the verified disposable database.

## Executed QA summary — actual results

| Area | Observed result |
|---|---|
| Authenticated route/visual matrix | 72 visual checks: 12 representative screens (all nine primary destinations plus Data Hub Features, Crop Rotation Overview/Planner, and two Workspace & Settings sub-pages), in English and Arabic at 1440px, 390px, and 360px. |
| Screenshots | 50 committed Chromium screenshots: desktop 1440px and mobile 390px for the 12 screens in both locales, plus the English and Arabic mobile navigation sheets. The 360px width was measured in the browser but not screenshot-captured. |
| Layout/accessibility metrics | 0/72 horizontal-overflow cases; 0 clipped sub-page labels; 0 visible unnamed buttons; 0 mobile actionable targets under 44px; 72/72 synthetic-data banners present; desktop active route announced once. |
| Browser/session | Demo login returned HTTP 200. Authenticated run recorded 0 page errors, 0 authenticated console errors, 0 authenticated API failures, and 0 failed assets. The guest bootstrap recorded two recoverable session-probe console/API failures before login. No external browser request was attempted. |
| Navigation | 68 unique static route-manifest states; automated route-manifest tests cover canonical destinations, all sub-pages, legacy tab links, and aliases. Browser recorded 4 direct route checks, 2 mobile navigation checks, 1 Back/Forward/query-history check, and 2 keyboard checks. |
| Loading/error states | The injected 503 harness produced 24 loading observations and 24 error-case records, but only 3 requests were actually intercepted across the 24 cases and the sample waited 650ms before React Query retry/backoff settled. **The error/retry browser result is inconclusive, not a pass.** Source-level retry/alert fixes listed below passed lint/type/build but have not yet had a fresh injected-503 browser verification. |
| Automated frontend | `npx --yes --package bun@1.4.4 bun test tests/frontend` — 154 passed, 0 failed, 1202 assertions; lint, TypeScript no-emit, and production build passed. All locale JSON parses; English/Arabic keys match for nav (42), destinations (31), rotation (119), and features (79). |
| Backend verification | The seven targeted migration integration tests passed against the disposable cluster. The full backend suite did not complete: default pytest collection reported duplicate-basename import mismatches between `tests/integration` and `tests/unit`; an importlib-mode attempt still errored during collection at `tests/unit/test_rotation_season_scores.py`. No backend application source was changed. |

The post-run source fixes add accessible localized retries for shared farm/field selection, Farms & Fields map/field reads, Decision Center list/detail reads, and organization/report-list reads in Reports, Billing, and Developer Settings. These are code changes, not a claim that injected terminal-error UI has been browser-verified.

## Remaining QA gates

- Re-run an injected-error matrix with per-request interception correctly armed and enough time for query retry/backoff to settle; confirm each destination renders a distinct error rather than a successful-empty state and that Retry reissues the same read query.
- Exercise the remaining Data Hub/Crop Intelligence/Map/AI/Reports/Settings sub-pages and their retry states, mutation confirmation dialogs, keyboard/focus behavior, and tenant authorization with a safe authenticated session.
- Capture 360px screenshots as well as the measured no-overflow result, and perform a screen-reader review. No production deployment, PR, merge, or public release is authorized by this QA record.

## Destination index

All routes are root query routes (`/?tab=...`); the paths below identify the canonical destination/sub-page specified by the source maps. `Primary component` names the destination component, not every nested component.

| Destination | Exact canonical query route | Primary component |
|---|---|---|
| Overview | `/?tab=overview` (optional context: `&farm=<farm-id>&field=<field-id>&fieldName=<field-name>`) | `src/components/croptwist/overview.tsx` |
| Farms & Fields | `/?tab=farms` (canonical sub is null; optional `&farm=<farm-id>&field=<field-id>&fieldName=<name>`) | `src/components/croptwist/farms-fields.tsx` |
| Data Hub | `/?tab=datahub&sub=observations` (other subs: `features`, `passport`, `scenes`, `evidence`) | `src/components/croptwist/observations.tsx` for the default route; sub-page components are listed below |
| Crop Intelligence | `/?tab=cropintel&sub=rotation` (valid subs listed below) | `src/components/croptwist/rotation.tsx` for the default route |
| Map & Satellite | `/?tab=geo&sub=map` (legacy `satellite` resolves here) | `src/components/croptwist/navigation/map-satellite-pane.tsx` |
| Decision Center | `/?tab=decisions&sub=documents` (destination root `/?tab=decisions` defaults to `sub=state`) | `src/components/croptwist/decisions.tsx` |
| AI Copilot | `/?tab=copilot` (single-view; sub is null; legacy `aiinsights` resolves here) | `src/components/croptwist/ai-insights.tsx` (mounts `ai-copilot.tsx`) |
| Reports & Analytics | `/?tab=reports&sub=reports` (bare `/?tab=reports` defaults to `sub=reports`) | `src/components/croptwist/p3/reports-tab.tsx` |
| Workspace & Settings | `/?tab=settings&sub=organization` (other subs: `billing`, `developer`, `preferences`) | `src/components/croptwist/p3/team-tab.tsx` for the default route |

## Cross-destination initial gate

1. Confirm parent approval for the target environment, authenticated session, and any permitted read-only requests; do not infer an account/session from source code.
2. Keep provider traffic disabled. Do not invoke demo login/seed routes. Only consider synthetic records after the isolated disposable DB is verified by the parent; otherwise use approved mocked responses or record missing data honestly.
3. Open only a destination/deep link within the authorized workspace. Check URL/store resolution and unrelated query-parameter preservation without submitting forms. Stop if authentication, tenant ownership, or field authorization is unclear.
4. Capture outcomes as **not run**, **observed empty**, **observed error**, or **observed state** only after actual browser execution. Do not use “passed” in this preparation document.

---

## 1. Overview

**Route/component.** `/?tab=overview`; `src/components/croptwist/overview.tsx`, with `src/components/croptwist/charts/climate-overview.tsx`, workspace state, and query hooks. Optional selected farm/field context is carried in query parameters.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: with approved session and read-only backend access, inspect `GET /api/v1/farms` loading skeletons/stats, independent anonymous `GET /api/v1/health/ready` readiness text, and field query activation only after an active farm exists. Verify a deep-linked field is resolved against the active farm; do not assume URL context is valid.
- Success: only if already-present, authorized records are returned, compare visible farm/field counts and area to response values; inspect the selected field's read-only climate series from `GET /api/v1/fields/{fieldId}/observations?start=<date>&end=<date>&limit=5000`. Chart input is non-null precipitation or mean air temperature grouped by observed date. Treat success as unverified until actually observed. The recent trailing window is queried first; the 2015-01-01–2024-12-31 fallback is requested only after recent success-empty, and client-trimmed to 120 dates/rows.
- Empty: with no farms, expect the four-step setup card and Create your first farm CTA; do not create data. With farms but no active field, climate chart is not mounted and there is no field-specific empty message in this view. If both observation windows resolve but no usable series exist, expect “No data to plot yet.”
- Error/retry: farms error renders an alert and Retry/refetch; chart query error renders an alert with retry for the query in error. Health readiness has pending/error/success text and status dot but no dedicated retry control. Check only under an approved read-only session; retry is a query, not proof of recovery.

**Non-mutating interactions.** Inspect direct and existing-id deep links; keyboard Tab/Shift+Tab and Enter/Space on navigation controls; Map & Satellite, Data coverage/Ingest observations navigation, and Data Passport navigation (stop at destination before any action). Opening and closing the Create farm dialog is only a dialog check; do not submit. Locale switching to Arabic is a future visual check only. `DataCoverage` exists in source but is not imported/rendered by Overview; do not expect a coverage panel here.

**Unsafe write/external-provider actions to avoid.** Do not submit Create farm/Create your first farm; ingest observations or use import controls; call `POST /api/auth/demo`, `/dev/seed-demo`, or any seed route; alter farm/field data; invoke external weather, satellite, AI, or provider services. Do not infer live DB/PostGIS connectivity from readiness text.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers overview resolution, fallback/idempotency, generic store navigation, create-farm dialog navigation state, and passport navigation/selection. No Overview, climate-overview, or data-coverage component/render/API fixture test was found in the supplied map.

**RTL / responsive / accessibility checks.** Verify workspace sr-only h1 then visible h2 hierarchy; left-oriented/text-left controls in Arabic; responsive card grids and wrapping of Arabic labels, names, API errors and legends; chart at narrow widths and its fixed 280px height, dual axes, tooltip, keyboard reachability and accessible data alternative. Verify pending health status announcements, role=alert and role=status behavior, ordinary chart-empty text announcement, and stat/skeleton accessible names. No RTL/mobile/screen-reader result is established by source.

## 2. Farms & Fields

**Route/component.** `/?tab=farms`; `src/components/croptwist/farms-fields.tsx`, with `farm-map.tsx`, `field-map.tsx`, workspace, and query hooks.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: approved read-only check of `GET /api/v1/farms`, then `GET /api/v1/farms/{farmId}/fields` for a selected/first farm. With a selected field, inspect read-only `GET /api/v1/fields/{fieldId}/map` and `/boundary-versions` state. Farm and field queries use the documented `['farms']` and `['fields', farmId]` keys.
- Success: only with already-present authorized data, select a returned farm and field and compare the displayed information with returned farm/field payloads; inspect the offline/local-map component and boundary-version list. Do not treat source types or map rendering code as proof of usable payload or tenant authorization.
- Empty: no farms shows dashed empty card and Create a farm CTA; a farm with no fields shows Add the first field CTA; no selected farm/field shows its selection hint; empty boundary-version result says no versions returned. A field id absent from loaded fields may show a loading-detail skeleton; do not assume it exists.
- Error/retry: farm error card includes Retry/refetch. Fields error is text-only (“Could not load fields — try again.”) with no retry control in this destination. Map error/missing payload shows “Map payload unavailable”; boundary-version loading uses skeletons. Do not assert a retry affordance where source says none.

**Non-mutating interactions.** Direct canonical/deep links using already authorized ids; select farm buttons and inspect `aria-pressed`; select a field through its Open button or map polygon; open/close New farm, Add field, Rename, or Update boundary dialogs without submitting; inspect keyboard and URL/store synchronization. Local Fields export serializes loaded data, but avoid it in this pass unless explicitly approved as a local-only download.

**Unsafe write/external-provider actions to avoid.** Do not submit farm creation (`POST /api/v1/farms`), field creation (`POST /api/v1/farms/{farmId}/fields`), rename (`PATCH /api/v1/fields/{fieldId}`), or boundary version creation (`POST /api/v1/fields/{fieldId}/boundary-versions`). Do not submit the “Use example square” geometry. Do not use demo login/seed; do not invoke satellite/provider/API actions or infer PostGIS repair/tenant behavior.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers farms resolution, legacy mapping, URL idempotency, navigation and create-dialog store state. No direct FarmsFields render/API fixture/loading/empty/error/map/boundary/export/RTL test was found in the source map.

**RTL / responsive / accessibility checks.** Check narrow layout stacking and `overflow-x-auto` table usability; row selection is on a clickable `TableRow` without native keyboard role/handler, so verify the Open button provides a keyboard-accessible equivalent. Check farm `aria-pressed`, focus visibility, dialog labels/scroll/focus restoration, map field selection alternative, RTL alignment, and Arabic labels. No result is verified.

## 3. Data Hub

**Route/component.** Default `/?tab=datahub&sub=observations`; other routes `/?tab=datahub&sub=features`, `passport`, `scenes`, and `evidence`. Primary components: `observations.tsx`, `features.tsx`, `data-passport.tsx`, `satellite-scenes.tsx`, `adaptive-evidence.tsx`; shared `field-picker.tsx`, rail, hooks and API client.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: after parent approval, check a field-picker read path (`/api/v1/farms`, fields) and the selected page's documented GETs only. Observations reads catalog, coverage, and field observations; Features reads feature catalog, runs, and values; Passport reads data-passport and catalog; Evidence reads evidence gaps, staleness, and actions. Use only already-authorized field context.
- Success: inspect already-returned/mock-approved read data, synthetic provenance/badges only when payload explicitly marks it synthetic, and navigation among sub-pages. Do not launch scene discovery/acquisition, even if a control appears read-like.
- Empty: no fields shows create-farm/field guidance plus Go to Farms; Observations has no-observations/empty-window messaging; Features has no-calculated-features or no-values branches; Passport can show no variables; Evidence has no-gaps/no-actions states. Preserve absence of records as absence; do not invent fixtures.
- Error/retry: Observations catalog/coverage/observation and Features catalog/runs include source-described error/retry states; Passport error includes retry; Evidence does **not** show uniform actionable error/retry UI for its read queries and sections may be absent on query error. Scenes have loading/error/empty/processing UI but are not a safe interaction target. Verify exact states only with mocked responses or approved read-only access.

**Non-mutating interactions.** Inspect canonical and legacy read-only deep links (`observations`, `features`, `passport`, `adaptiveevidence`); use page rail and browser navigation; select an already existing field; adjust observation date/variable filters and inspect tables/charts without ingestion; expand existing feature run details and switch display aggregation; inspect Passport warnings/provenance and Evidence status/staleness without applying actions. Do not activate export/download controls in this matrix.

**Unsafe write/external-provider actions to avoid.** Do not use demo auth/seed. Avoid observation ingestion (`POST /fields/{id}/data-jobs`), CSV/CHIRPS imports, feature-run creation, scene discovery/processing/acquisition/assets/cancellation, evidence action create/transition/apply, or any provider calls. Specifically do not use Open-Meteo/live/reanalysis, even where synthetic is another UI option; synthetic ingestion still writes. No external file downloads.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers Data Hub default/sub-page/legacy resolution, selection/navigation and recent views. `docs/engineering/FIGMA_IMPLEMENTATION_REPORT.md` records earlier static implementation notes, not a current browser pass. No page-specific component RTL tests for mapped Data Hub components were found.

**RTL / responsive / accessibility checks.** Check mobile horizontal sub-rail clipping, dense tables/forms and chart alternatives, Arabic labels, and workspace heading updates. `adaptive-evidence.tsx` hard-codes `dir="ltr"`; verify Arabic labels/status/action alignment. Check hard-coded English evidence reference aria-label, keyboard and screen-reader chart/table access, focus restoration, query error discoverability. No runtime result is available.

## 4. Crop Intelligence

**Route/component.** Default `/?tab=cropintel&sub=rotation`; valid subs: `rotation`, `rotation-overview`, `rotation-planner`, `irrigation`, `soil`, `plan`, `covers`, `timeline`, `residue`, `erosion`, `operations`, `soilmemory`, `forecast`. Main route component varies by sub-page: `rotation.tsx`, `rotation-overview.tsx`, `water.tsx`, `soil.tsx`, `management/index.tsx` plus management views, `soil-memory.tsx`, `forecast.tsx`; shared FieldPicker/context/state components.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: test canonical and legacy URL resolution without submitting forms. With parent-approved, authorized read access only, select existing field and observe disabled field-scoped query behavior when no field is selected. Queries include crop history, water/soil methods and field readiness/profile, management read lists, soil-memory timeline/alerts, and forecast capability/window/risk reads.
- Success: only examine already-existing records in an explicitly approved synthetic disposable fixture or parent-approved mocks. Rotation overview may display source/evidence/history and filters; other pages may render existing plan/run/ledger/forecast content. Do not use form defaults, test fixtures or synthetic markers as evidence of real data or success.
- Empty: verify field picker guidance and page-specific honest empty states: no history/selected-period rows, missing water/soil evidence, empty management records/resources/concerns, soil-memory/forecast limitations, as applicable. Existing absence is not an error and must not be filled with invented values.
- Error/retry: shared ErrorState and local loading/error patterns vary. Rotation overview has history retry and empty states; water plan detail has loading/error/retry; Soil Memory timeline has retry; Forecast verification may have retry. Some management and older page queries render inline errors or no uniform retry. Record unavailable retry controls accurately; do not treat an absent section as recovery.

**Non-mutating interactions.** Navigate all documented subs and legacy aliases (`rotation`, `water`, `soil`, `management`, `soilmemory`, `forecast`); preserve field context; change local period filters and display switches; expand cards, change form inputs without submission, inspect evidence/constraints and existing details; use navigation to read-only overview. Retry only in a parent-approved harness where the read request is authorized. Avoid clipboard/share/logout side effects.

**Unsafe write/external-provider actions to avoid.** Avoid all mutations, including candidate and rotation run creation; water plans; soil assessment/SOC/nutrient runs and CSV imports; management plans; cover observations/plans/items; residue records/flows; erosion assessments; operation generation/resource creation/scheduling/PATCH completion; soil-memory snapshots/change estimates; forecast ingestion/verification; water-plan deletion. Do not use demo login/seed, database/PostGIS, live providers, or onboarding/create-farm paths that may lead to submit.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers Crop Intelligence destination/sub ordering, legacy redirects, invalid fallback, navigation and persisted expert toggle. `tests/frontend/crop-history-filter.test.ts` covers date facets, either sowing/harvest match, undated rows under all-period, and source-array non-mutation. Backend `mini-services/fieldshift-api/tests/unit/test_water_rotation_integration.py` and `test_water_core.py` cover agronomic calculation/synthetic-evidence logic, not browser UI. No mapped frontend component-level RTL/browser tests were found.

**RTL / responsive / accessibility checks.** Check 13-item desktop/mobile sub-rail, long translated labels, focus and touch targets; dynamic season rows, dense controls, tables/charts, selects, labels and button names; shared sr-only heading and differing alert/status patterns; RTL mode/layout persistence across management subs. Verify chart alternatives and small-screen behavior, not infer it. No runtime accessibility result is known.

## 5. Map & Satellite

**Route/component.** `/?tab=geo&sub=map` (legacy `satellite` resolves here); primary `src/components/croptwist/navigation/map-satellite-pane.tsx`, with farm/map components, layer manager, temporal explorer, inspector, satellite pane and P07 hooks.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: route/canonicalization check only until read-only API access is approved. The source maps field/layer catalog, processing ledger, pixel sample, zones, resolved-asset tiles, vegetation summary/scenes/profile reads; these can contact the backend, and tile/raster/provider traffic remains disabled under this plan.
- Success: only with approved mocked or already-present synthetic records and geometry, inspect field selection, layer/index/date display, temporal gap warnings and provenance. Never fabricate geometry, dates, imagery, values, zones or assets. Without approved data, record unavailable/empty.
- Empty: no farm/valid geometry shows no field boundaries; no selected field disables field-scoped queries and shows a gate. Source-described states include no dates, no product/no valid pixel, unavailable/no polygons, and satellite panel no-data/data-gaps/empty-scenes.
- Error/retry: catalog/pixel/zones/panel states include loading/error or unavailable states as mapped; sampling has retry disabled. Only exercise retries with stubbed responses or explicit read-only approval. Do not call map tiles or raster endpoints for the sake of displaying a success state.

**Non-mutating interactions.** Route/deep-link navigation; with parent-approved fixture/mock only, select existing field, change index/date, use prev/next, toggle local layer visibility/order/opacity/legend/groups, fit, clear selection, and inspect keyboard behavior. Do not make live tile, raster, or provider requests. Selection and control testing is a future plan, not performed here.

**Unsafe write/external-provider actions to avoid.** Disable live providers, HLS/Earthdata, map API/database/PostGIS, seed and real tenant identifiers. Do not POST discovery/acquisition/processing/cancellation; avoid export and live tile/raster fetches. Do not invent or manually insert map assets.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers geo default and satellite legacy resolution. `tests/frontend/p07-map.test.ts` covers pure temporal/layer helpers only. No component, browser, API-hook, map, responsive, or accessibility tests were found in the supplied map.

**RTL / responsive / accessibility checks.** At 390px/360px and desktop, assess map, side panel, date strip, labels and inspector width; check mixed LTR map canvas/date strip within RTL shell; keyboard alternative to pointer-only map hit testing; role=img semantics; layer controls/listbox and slider names/values, focus, contrast and touch interaction. All remain pending.

## 6. Decision Center

**Route/component.** Assigned documents page `/?tab=decisions&sub=documents`; bare `/?tab=decisions` defaults to state. Primary `src/components/croptwist/decisions.tsx`.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: inspect route and field gate without generating or verifying. With approved/mock read-only data only, list uses `GET /api/v1/fields/{fieldId}/decision-comparisons`; detail uses `GET /api/v1/decision-comparisons/{comparisonId}`. A field identifier in the URL alone does not prove tenant authorization.
- Success: no explicitly synthetic Decision Center fixture is mapped. If parent supplies approved mock list/detail responses and synthetic selected field, inspect document summary and evidence-linked sections; do not call this a backend success.
- Empty: no field shows pick-field; empty list shows `noDocsYet`; detail may explicitly show unavailable sections, empty findings, suppressed empty rotation/tradeoff cards, and missing-evidence count. Preserve limitations/honesty notes; do not interpret findings as recommendations, probabilities, scores or yield predictions.
- Error/retry: list and detail errors show alerts, but mapped UI has no dedicated retry control for either. Verify via mock state only; do not infer recovery or add an unprovided retry.

**Non-mutating interactions.** Read-only route/deep links for decisions/state/documents; with mock data, expand/collapse summary and inspect table scrolling; verify farm/field/fieldName context and invalid-sub fallback; keyboard focus and mobile navigation. Opening document UI is not permission to generate or verify.

**Unsafe write/external-provider actions to avoid.** Do not use Generate (POST creates/appends comparison) or Verify document & sources (POST verifies checksum/source). Do not connect to API/database/PostGIS/provider or seed. Do not infer tenant access from fieldId.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers decisions default state, explicit documents, legacy routes, invalid-sub fallback and store navigation. No frontend component/API-mock/state/retry/accessibility tests were found. `docs/m7/M7_COMPLETION_REPORT.md` references 13 M7.6 backend integration tests; not executed here.

**RTL / responsive / accessibility checks.** Check `text-left`, `pl-4`, flex header, dense tables and mobile control crowding; touch/zoom/scroll; summary button lacks mapped `aria-expanded`/`aria-controls`/selected semantics; no live-region loading/status and no retry on detail/verify errors. Check duplicate `colScenario` use for scenario columns. No runtime evidence.

## 7. AI Copilot

**Route/component.** `/?tab=copilot` (single-view); legacy `/?tab=aiinsights` resolves here. `src/components/croptwist/ai-insights.tsx` mounts `ai-copilot.tsx`.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: route/field gate only unless parent approves read-only requests. Field-scoped recommendations/insights require a selected field; provider status `GET /api/v1/ai/providers` is mapped to report `live_connectivity_verified:false`. Conversations/history have read GETs scoped to field/conversation. Do not contact model/provider services.
- Success: no frontend-only Copilot success fixture bypasses request API. Use only parent-approved mocked/preloaded synthetic responses to inspect evidence, limitations, assumptions, missing information, follow-ups and synthetic/degraded disclosures. Do not submit a real Copilot question; never infer agronomic validity from output.
- Empty: no field shows field picker; empty recommendation/conversation/history states and hidden absent insight content are source-described. Record no data honestly.
- Error/retry: mapped query errors vary; conversation/history include Retry/refetch, question failure restores draft and shows retry alert; abort/unmount is silent; delete and feedback failures show alerts. Verify branches with mocks only. No provider or model request as part of retry testing.

**Non-mutating interactions.** Inspect canonical/legacy route and authorized field context; mock/preload conversation list and history to select a conversation, choose New conversation, expand rationale/evidence/limitations and inspect role/status/log behavior. Open delete confirmation but do not confirm. Populate feedback controls/consent only for visual inspection, never submit. Check textarea Enter vs Shift+Enter without sending (Enter is the submit key when permitted).

**Unsafe write/external-provider actions to avoid.** Do not use demo login/seed. Do not submit a question (`POST /api/v1/ai/requests/stream` can persist and invoke model providers); do not Generate/Refresh recommendations, delete a conversation, submit Copilot or recommendation feedback, or call live model, embedding, environmental/catalog, or provider connectivity endpoints. No external calls or mutations.

**Existing tests (inspected, not run).** `tests/frontend/ai-copilot.test.ts` covers payload context/locale and conversation routing. `tests/frontend/ai-core-api.test.ts` mock-fetch covers SSE chunks/done validation, URL/body, omitted `organization_id`, malformed terminal rejection, response guard, provider/conversation/history/delete URLs and consented feedback body. `tests/frontend/navigation.test.ts` covers route/legacy alias. Backend mapped tests include `tests/integration/test_ai_core.py`, `test_ai_knowledge_feedback.py`, and unit `test_ai_core_orchestration.py`, `test_ai_lifecycle_fallback.py`; none were run.

**RTL / responsive / accessibility checks.** Check RTL/LTR bidi for provider/model names and IDs; mobile history controls and long titles; evidence ID wrapping; icon-only Send/feedback accessible names and visible focus; scrolling, log announcement volume, pending status, textarea/select labels and heading hierarchy. Test only via static or mocked rendering with provider disabled. No runtime result.

## 8. Reports & Analytics

**Route/component.** `/?tab=reports&sub=reports`; bare `/?tab=reports` defaults to reports. Primary `src/components/croptwist/p3/reports-tab.tsx`.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: route resolution only until parent authorizes read-only backend access. Source reads organizations, report list (`GET /api/v1/reports?limit=50` when an org exists), and farms. Org/report scoping and auth are not proven by source inspection.
- Success: no explicitly local synthetic report-job fixture is mapped. Only parent-approved mocked list data or existing authorized data may be rendered for read-only inspection. A success-shaped `ReportJob` response is not evidence it exists in the target environment.
- Empty: no organization shows no-org navigation CTA; report list success with zero rows shows empty copy. Farms lack a destination-specific loading/error branch in this component. Do not create reports to populate the list.
- Error/retry: report list error uses inline error (403-specific copy or described error) with React Query retry configured once but no explicit user retry button. Mutation errors use toast but mutations are not to be performed. Queued/running rows poll every three seconds; do not create jobs to test polling.

**Non-mutating interactions.** Open route and navigate via rails; change local report form selections only (type, format, locale, org/farm scope, dates, instant checkbox, recurrence) without Generate; inspect the fixed 13 report types and, with approved/mock read data, queued/running/succeeded/failed/expired row rendering, responsive cards/table and server errors. Do not download or invoke row actions.

**Unsafe write/external-provider actions to avoid.** Do not Generate (`POST /api/v1/reports`), Download (binary GET plus browser file save), Regenerate, Delete, or Schedule (POST, including clearing schedule). Avoid demo login/seed, API/database/provider calls, and external checkout/file actions. Preserve server-derived tenant scope.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers route defaults/legacy mapping. `tests/frontend/p07-analytics.test.ts` covers pure 13-entry report-type registry assembly, P07 values and deduplication; it does not render ReportsTab or test API calls. No report component/API/mutation/RTL/browser/fixture test was found.

**RTL / responsive / accessibility checks.** Check desktop table/mobile card parity (mobile omits `next_run_at` in mapped source), RTL alignment/date/number formatting, action accessible names and focus, tooltip keyboard access vs mobile inline errors, Select/dialog/alert-dialog/date keyboard behavior, and the no-org CTA canonical destination. Do not click Generate or action buttons. No runtime accessibility results.

## 9. Workspace & Settings

**Route/component.** `/?tab=settings&sub=organization`; subs are `organization`, `billing`, `developer`, `preferences`. Primary default sub-page `src/components/croptwist/p3/team-tab.tsx`; others `billing-tab.tsx`, `developer-tab.tsx`, `preferences-tab.tsx`. This destination is distinct from Reports & Analytics.

**Safe initial / success / empty / error / retry checks (pending).**
- Initial: route and settings rail checks only until approved read-only access. Organization, preference, billing, developer queries use same-origin session/organization context; query availability and user/org membership are unverified. Some developer/billing endpoint contracts are organization-scoped; no client URL parameter proves access.
- Success: no settings-specific synthetic fixture is mapped. Only inspect data returned by parent-approved mocks or an explicitly authorized existing synthetic fixture after the isolated disposable DB gate. No account, subscription, API key, webhook, or organization is claimed to exist.
- Empty: source describes no-organization states and empty organization sections; no organization should remain an honest empty state, not trigger Create organization. Preferences form is only shown when data is present; no synthetic preference values should be invented.
- Error/retry: organization list skeleton/error includes retry; members/invitations/activity have section-level errors/retries. Preferences has skeleton/error retry. Billing and Developer use inline errors and query retry configuration; do not mistake implicit query retry for user-visible retry control. Check only in a mocked/approved read-only run.

**Non-mutating interactions.** Navigate canonical and legacy settings deep links (`team`, `billing`, `developer`, `preferences`) and back/forward; inspect side/sub-rail state and query preservation. Preferences select changes may be inspected as local draft only; do not Save. Billing display-only monthly/yearly toggles or opening a dialog without confirming may be inspected if no external navigation occurs. Developer delivery expansion may trigger a read query, so only use approved fixture data and approved read access.

**Unsafe write/external-provider actions to avoid.** Do not create/rename organizations, invite/revoke users, change/remove member roles, transfer ownership, save preferences (`PUT`), start/change/cancel/resume billing, sandbox pay or open checkout/contact-sales URLs, create/rotate/revoke API keys, create/patch/delete/rotate webhook secrets, or redeliver webhooks. Do not use demo/seed controls, report actions, API/database/provider access without separate authorization. Never expose/copy one-time secrets.

**Existing tests (inspected, not run).** `tests/frontend/navigation.test.ts` covers settings page order/default/explicit preferences, invalid fallback, legacy `team`/`billing`/`developer` routes, notification/onboarding resolution and store navigation. No mapped settings component RTL/browser test or direct loading/empty/error/accessibility test was found.

**RTL / responsive / accessibility checks.** Workspace sidebar hides below `xl`; settings sub-rail switches from vertical to horizontal. Check translated labels, overflow, RTL/mixed Arabic-Latin values, timezone LTR presentation, dense tables/dialogs/developer rows, visible focus, explicit form labels and settings shared error/skeleton announcements. No runtime keyboard, screen-reader, mobile, or RTL behavior is established.

---

## Exit criteria for a later QA run

This document is only a preparation matrix. A later run may record actual observed results only after the parent confirms the authenticated target, tenant authorization, and read-only request boundary. If any demo/synthetic backend data is desired, first verify the isolated disposable database with the parent; **provider calls remain disabled**. Keep every write, seed, demo-login, destructive action, external call, and provider workflow out of scope. Report missing session/data/API access as a blocker rather than fabricating success. Do not mark any screen passed based on this source-derived matrix.


## Parent verification update — 2026-11-14

The initial source-mapping sections above were prepared before an authenticated environment existed. Their “do not start until verified” and “do not seed” restrictions describe that earlier state. The parent has now verified an isolated disposable test environment and authorized a safe authenticated test account under the supplied authenticated-QA brief. This narrowly supersedes the prior seed blocker only for the repository’s built-in demo login flow and only against the target below; it does not authorize writes to other databases or any farm/field edits, feature/rotation runs, report actions, organization/billing settings, AI requests/feedback/deletions, or satellite/provider jobs.

- **UI QA database:** `croptwist_ui_qa_test` on a fresh `/tmp/croptwist-qa-pgdata` cluster bound to `127.0.0.1:55432`, PostgreSQL `16.10`, PostGIS `3.5.0`; all data in this cluster is disposable and newly created for this QA. It contains no copied production records.
- **Backend test database:** `croptwist_pytest_test` on the same disposable cluster, separate from the app session and its fixtures; the backend test suite is running against only this database.
- **Migration/readiness verification:** Alembic has one head, `0028_api_key_rate_windows`; the UI QA database is migrated at that revision, has PostGIS `3.5.0`, and direct `/api/v1/health/ready` returned HTTP 200 with PostgreSQL `16.10`.
- **API runtime controls:** FastAPI listens only on `127.0.0.1:3030`; dev mode is enabled only for the isolated runtime; job workers are `0`; scheduler is disabled; external weather, SoilGrids, Sentinel-2, Open-Meteo forecast, and NASA STAC base URLs point to loopback port `9`; ambient `OPENAI_API_KEY` and `OPENAI_API_BASE` were removed from the API process.
- **Allowed fixture path:** the existing development-only `POST /api/auth/demo` same-origin flow may create/login the built-in `demo@croptwist.local` user solely in `croptwist_ui_qa_test`. Its seed creates an explicitly SYNTHETIC demo farm, two synthetic fields, and synthetic observations with source/evidence metadata. The new persistent EN/AR banner labels those records as illustrative; no synthetic observation, prediction, satellite image, recommendation, or operational result may be presented as real.
- **Provider boundary:** provider calls remain disabled. Read-only provider health may report loopback-unreachable; do not click discovery, acquisition, ingestion, processing, AI/model, download, payment, or mutation controls. Only use the demo entry flow after readiness; all page QA should otherwise be read-only.
- **Execution status:** database readiness is verified; backend tests are running separately; demo sign-in, authenticated route checks, actual screenshots, English/Arabic browser results, and all nine destination outcomes remain pending until recorded in the authenticated QA results report.

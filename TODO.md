# CropTwist — Outcome-Based Project TODO

**Tracking baseline:** dedicated branch `remediation/legacy-hardening`, based on the current `main` checkpoint. This is an implementation snapshot, not a production-readiness declaration. A checked box means the stated outcome has evidence in code and/or executed checks; it does not imply live external readiness.

## Delivered in this working batch

- [x] **Frontend regression suite is a CI gate.** GitHub Actions runs `bun test tests/frontend` on pushes and pull requests. Local result: 122 tests passed, 0 failed.
- [x] **Logout invalidates its complete token family.** Logging out with an access token revokes its related access and refresh tokens; a pure unit regression test passed. An API integration assertion was added but still needs PostgreSQL/PostGIS CI execution.
- [x] **P07 report registry test reflects the current implementation.** The three implemented P07 report types are in the registry expectation; the targeted backend unit file passed 17 tests.
- [x] **Field briefs are screened before rendering.** Structured output must include visible citations resolved against the current evidence pack and pass numeric screening; one constrained retry is allowed, then model text is omitted. Sync and async paths have passing unit coverage.
- [x] **Root Compose settings align with API configuration.** The `CROPTWIST_` prefix, non-demo default, readiness healthcheck, and safe local example are in place and statically verified; no container was started.
- [x] **Master audit, prioritized gap matrix, AI architecture, and verification report** are written under `docs/`; older limitation records now identify their historical scope.

## Remediation branch progress — 2026-11-14

- [x] **Authentication hardening:** non-development registration issues no session before verification; token resolution and refresh reject unverified users; refresh rotation is serialized; logout resolves bearer/cookie transport and revokes the token family. API-level regressions were added but await a database-backed run; production email delivery remains absent.
- [x] **Authorization and quotas:** legacy membership mutation requires the exact owner role; legacy member additions now apply the organization-seat entitlement. Missing subscriptions resolve to Free limits for the changed farm, field, report, seat, and public-API paths. Tests were updated/added; PostGIS integration was not available.
- [x] **Billing/API/webhook guards:** zero API rate limits remain zero/denied; API-key creation/authentication check current plan enablement/rate; production startup fails closed without a real billing adapter and explicit strong secret; webhook timestamps, payment invoice amount/currency, and outbound destination resolution/redirect behavior are guarded. Signing secrets remain plaintext at rest; sandbox-only processing remains.
- [x] **Observation integrity:** CSV header normalization, BOM handling, finite-number checks, raw-upload SHA-256, observation invariants, per-row ingestion savepoints, and quality-aware usable coverage are in place. CSV parser contracts: 17 passed, 2 DB-backed persistence cases deselected.
- [x] **Report scope:** selected farm/field combinations are cross-checked and report field queries enforce both selectors.
- [x] **Agronomic score correctness:** knowledge-pack version rows are not mixed; regional trait lookup matches explanation lookup; seasonal rainfall is not compared to annual reference ranges; critical calendar/climate gaps are unevaluated; incomplete weighted criteria are omitted rather than zero-filled; season-dependent rotation scores pool across seasons; soil-health composites use sourced numeric traits only.
- [~] **Durable jobs:** persisted polling, atomic row-lock claims, startup executor registration, and bounded stale-job recovery are implemented. Multi-process/PostgreSQL recovery was not runtime-tested; raster-domain/generic-job commit ordering still needs verification, and the GIS-owned processing service was not changed.
- [ ] **GIS workstream D:** direct HLS Fmask/CRS/windowing, raster lineage, and end-to-end provider correctness remain open for the separate GIS workstream. No GIS/raster implementation file was changed on this branch.
- [x] **Local verification:** database-independent backend unit suite — 941 passed; CSV parser contract suite — 17 passed / 2 deselected; frontend suite — 122 passed; frontend TypeScript check — passed; modified Python modules compiled; `git diff --check` passed. Database/PostGIS integration, migrations, container startup, live providers, hosted CI, and Ruff remain unverified/unavailable.

## Product outcomes

### 1. Evidence-grounded AI orchestration and Copilot — Partial

- CropTwist remains an AI-powered, evidence-driven agricultural decision-support platform, not merely a satellite dashboard with a chatbot.
- Agronomic engines calculate; evidence validates; AI orchestrates and explains; farmers decide.
- The AI orchestration layer understands user intent, identifies roles and permissions, retrieves relevant farm/field context, selects appropriate agricultural capabilities, routes requests to specialized engines/models, executes only approved tools, combines analytical results, produces evidence-grounded responses, handles errors/timeouts/provider failures, and records traceable execution information.
- The Copilot can address field conditions, attention priorities, recommendation explanations, crop suitability, rotation comparisons, soil/vegetation indicators, season comparisons, risks, authorized farm reports, and missing-information questions using the user's authorized context.
- Copilot responses distinguish facts, estimates, assumptions, missing evidence, data quality, confidence, uncertainty, and evidence completeness; cite internal evidence and agricultural references where available; respect tenant permissions; ask clarifying questions when required; and avoid fabricated values or unsupported diagnoses.
- Conversational continuity is field- and tenant-scoped and never exposes another user's or organization's private context.
- Never allow an LLM to invent numerical results, fabricate satellite observations, or replace validated agronomic calculations with unsupported reasoning. Field briefs now require citation/numeric checks and deterministic fallback; recommendation narratives still need the same contract, and the shared numeric guard remains screening-grade.

### 2. Specialized agricultural intelligence and decision support — Partial

- Each crop, soil, water, climate, vegetation, stress/anomaly, suitability, and rotation capability has clear input/output contracts, validation rules, provenance, confidence semantics, and tests.
- Keep suitability assessment, yield prediction, and optimization distinct. Never present a suitability score as a yield forecast.
- Rotation planning evaluates multiple seasons and, where supported by validated evidence, crop-family compatibility, nutrient needs/depletion, soil properties, water needs, crop history, pest/disease rotation, planting windows, farmer preferences, resource constraints, and economic/sustainability objectives.
- Decision support exposes hard and soft constraints, multi-objective ranking, explainable scores, alternative strategies, scenario comparisons, and sensitivity analysis.
- Correct active knowledge-pack ownership, region-specific numeric trait resolution and citations, assessment status for missing dimensions, season-specific optimization, temporally aligned vegetation context, consecutive-day risk rules, compatible temporal support, and handling of interval-valued traits.
- Regionally unconfirmed knowledge stays advisory. Do not present global/reference crop thresholds or coarse calendars as agronomist-confirmed local prescriptions.

### 3. Predictive intelligence — Missing / externally dependent

- Audit which existing predictive capabilities are genuinely implemented and validated before describing them as predictions.
- For each proposed model define the target, required features, training/evaluation datasets, geographic and temporal applicability, baseline, metrics, uncertainty, model versioning, deployment, and monitoring.
- Candidate opportunities include yield, crop-stress, water-demand, climate-risk, crop-performance, and agricultural-anomaly prediction.
- Do not invent accuracy metrics or claim predictive functionality from an unvalidated prototype. Do not represent deterministic/statistical screening as trained predictive ML.

### 4. Agricultural knowledge retrieval and provider-independent model layer — Missing / Partial

- Evaluate document ingestion, parsing and metadata, chunking, embeddings, vector retrieval, hybrid search where useful, metadata filtering, source attribution, retrieval evaluation, knowledge freshness, and permission-aware retrieval using reputable references.
- Distinguish external agricultural knowledge from the user's own observations; curated structured knowledge packs are not document RAG.
- Provide configurable primary provider/model and at least two practical fallbacks where supported; provider health checks; bounded timeouts/retries and rate-limit handling; token/cost tracking; structured-output and tool-calling compatibility; model capability checks; and secret-managed credentials.
- Evaluate model availability, pricing, terms, context windows, and tool-call support before provider selection. Do not hard-code product workflows to one provider or claim live provider success without a real check.
- Avoid unnecessary multi-agent complexity; introduce agents only where they have measurable product value.

### 5. Geospatial, satellite, environmental data, and provenance — Partial

- Preserve interactive field maps, raster/layer visualization, temporal exploration, vegetation indices, zones, field-level statistics, spatial comparisons, quality-aware anomaly analysis, and geospatial exports; do not substitute static previews for geospatial functionality.
- Expose NDVI, EVI, NDMI, NDWI, and BSI only when compatible data/products are available. Preserve source, acquisition dates, spatial resolution, CRS, processing version, and quality metadata.
- Distinguish satellite observations, satellite-derived products, reanalysis, model outputs, and ground measurements; never present synthetic data as real observations.
- Correct the direct HLS acquisition path's Fmask propagation, CRS handling, field-windowed reads, duplicate-row transaction isolation, non-finite/missing-value contract checks, CSV header normalization/raw-byte checksum, and quality-aware coverage semantics.
- Current data-source code includes Open-Meteo historical reanalysis, operator-upload CHIRPS GeoTIFF extraction, optional SoilGrids WCS, NASA HLS discovery with Earthdata-gated asset reads, and a separate P05 field-windowed raster-processing path. Keep source presence distinct from live readiness.
- Do not add a redundant Sentinel-2 pipeline without a clear use case; assess GPM IMERG, SMAP, ECOSTRESS, SRTM, NASA POWER, or native Sentinel-2 only where justified and validated.

### 6. Background jobs, data integrity, and operational reliability — Partial

- Register all replayable executors before restart recovery; keep queue/domain job status and errors consistent; reconcile interrupted domain rows; atomically commit request/domain/queue state before dispatch; and test restart recovery, failure, and fast-worker races.
- Use shared atomic claims/leases or a shared broker before claiming multi-process/multi-replica worker scaling. Document the current process-local queue limitations until that exists.
- Persist provider result coverage/request identifiers/raw-reference metadata where permitted. Define coverage semantics from accepted quality statuses and protect data provenance end to end.
- Use persistent, writable, tenant-safe raster/report storage for deployments. Keep artifact storage, jobs, metrics, and quotas durable/aggregated where scale-out is required.
- Bound and protect operational metrics; define off-site backup cadence, alerting, RPO/RTO and restore verification. Do not confuse sandbox scripts with production disaster recovery.

### 7. Security, tenancy, billing, and deployment — Partial / blocked

- Ensure authentication, authorization, roles, permissions and tenant isolation across every API path, including legacy membership APIs. Logout revokes the active token family; non-dev unverified registrations must not receive usable protected API sessions.
- Enforce Free-plan limits consistently without a subscription; disabled API entitlements and zero rate limits must reject key issuance/use rather than convert to a positive limit.
- Reject production use of dev mode and default/weak billing-webhook secrets; require verified provider configuration before production payment claims. Block SSRF to private/internal webhook destinations and protect persisted signing secrets.
- Align Compose and application settings on the `CROPTWIST_` prefix; provide validated migration metadata and tests for current P2/P3 schema; separate liveness from database/PostGIS readiness.
- Production ingress uses TLS, fixed/allow-listed upstreams, private database/API access, secret management, persistent artifacts, controlled workers, monitoring, and tested recovery. The checked-in root Compose topology is not a production deployment.
- Obtain real email and payment adapters, provider credentials, managed database/PostGIS, object storage, worker deployment, and approved paid-service configuration from the operator; do not fabricate credentials or claim validation without evidence.

### 8. Frontend, reports, accessibility, and localization — Partial

- Preserve the nine destinations: Overview; Farms & Fields; Data Hub; Crop Intelligence; Map & Satellite; Decision Center; AI Copilot; Reports & Analytics; Workspace & Settings.
- Maintain responsive desktop/mobile interfaces, a consistent design system, English and Arabic support, correct Arabic RTL, accessible interactions, consistent navigation/URLs, and clear loading, empty, error, and retry states.
- Add an explicit selected organization to every organization-scoped screen and ensure query keys, mutations, reports, developer credentials, and confirmations use that selection.
- Distinguish failed requests from genuinely empty observations/features/map content; provide safe retry actions. Bound commercial 401 refresh to one retry and make binary report downloads follow the same bounded auth handling.
- Preserve backwards-compatible decision deep links, direction-aware RTL layout, and localized bootstrap/fatal error fallbacks.
- Reports and analytics use authorized platform data and include relevant provenance, dates, quality limitations, and analytical methodology. Evaluate PDF, CSV, GeoJSON and other useful exports.
- Add rendered/browser coverage for important routes, organization switching, async error/empty states, map errors, responsive/mobile navigation, Arabic RTL, keyboard journeys, and accessible names. Current pure helper tests do not establish those behaviors.

### 9. Feedback, evaluation, and controlled improvement — Partial

- Track recommendation provenance, farmer feedback, actual outcomes, prediction evaluation, and model performance.
- Evaluate answer relevance, groundedness, attribution, tool-selection correctness, numeric consistency, retrieval quality, recommendation usefulness, safety/permission compliance, and provider reliability.
- Connect feedback and agricultural outcomes to evaluation workflows; feedback must not silently or automatically retrain production models. Improvement follows controlled validation, versioning, and deployment.

### 10. Audit, integration, and release evidence — In progress

- Inspect the actual frontend, backend, schemas/migrations, geospatial pipelines, agronomy/AI, auth/tenancy, jobs/providers/storage, analytics/reports, localization/accessibility, CI/deployment/observability, documentation, Git branches, and history.
- Classify capabilities as implemented-and-verified, implemented-but-incomplete, implemented-but-incorrect, partially integrated, missing, externally blocked, or requiring architectural improvement; an endpoint/table/UI placeholder alone is not completion.
- Run applicable frontend, bridge, and database-independent backend checks. Execute PostGIS migrations/integration tests, E2E/browser checks, and live provider checks only when their dependencies and safe environment are available.
- Produce `docs/MASTER_REPOSITORY_AUDIT.md`, `docs/MASTER_GAP_ANALYSIS.md`, `docs/architecture/CROPTWIST_AI_ARCHITECTURE.md`, and dated milestone reports under `docs/implementation/`.
- Keep implementation documentation consistent with checked-in code and clearly date historical test/live-provider evidence.
- Commit coherent milestones with meaningful messages; do not delete branches, rewrite shared history, force-push, perform destructive database/infrastructure operations, or expose secrets.

## Master integration mission — 2026-11-14

- [x] **Preserved integration work and traceable GitHub delivery.** Inspect all existing 14 modified and five untracked files, verify branch/HEAD/GIS ancestry/remediation base and remote permissions, create a recoverable checkpoint, retain `feature/ai-complete-integration` as target, and push verified coherent commits only to that branch. Never merge into `main`, rewrite history, delete source branches, force-push or discard user work.
- [x] **Completed authenticated, evidence-grounded AI lifecycle.** Keep deterministic intent planning, context-aware authorized typed tools, tenant and field/farm ownership, private conversation authorization, evidence validation, bounded execution, safe fallbacks, retention, observability, rate limiting and abuse protection. Agronomic engines calculate; evidence validates; AI explains; farmers decide. Unsupported engines are explicitly unavailable, not fabricated measurements, predictions or recommendations.
- [x] **Verified provider adapters and bounded routing.** Configurable Gemini primary, Groq `openai/gpt-oss-120b` first fallback and exact verified OpenRouter NVIDIA Nemotron 3.5 Super VL free identifier second fallback; secure environment-only keys, timeout/retry/backoff/circuit controls, truthful health/capability/usage metadata and transient-only failover. Permission, invalid requests and agronomic errors never trigger vendor failover. Mock tests do not imply live connectivity.
- [ ] **Rights-aware tenant-isolated knowledge and feedback.** Approved-source ingestion, metadata, bounded chunks, reviewed embedding adapter, source-attributed retrieval, version/freshness/lifecycle/access policy and deletion; no arbitrary internet ingestion or fabricated corpus. Feedback supports accepted, rejected, modified, implemented and outcome-reported states with consent, provenance and timestamps; user-reported outcomes are not scientifically verified; no automatic training. `0025_ai_feedback_knowledge` follows `0024_ai_core_orchestration` safely.
- [x] **Connected localized Copilot.** Respect authenticated organization/farm/field context, invoke only authorized tools, show source-backed explanations, limitations, missing data, private continuity and useful loading/empty/error/retry states in the existing design. Preserve Overview, Farms & Fields, Data Hub, Crop Intelligence, Map & Satellite, Decision Center, AI Copilot, Reports & Analytics and Workspace & Settings, including English/Arabic and RTL.
- [ ] **Job recovery cannot duplicate execution.** Safe ownership/lease/heartbeat/fencing, atomic transitions and idempotency prevent live-job requeue, concurrent owners and duplicate completed domain side effects. Cover crash, stale/live leases, concurrent and repeated recovery and completed ingestion.
- [x] **Free-plan scenario quotas are atomic and consistent.** With and without subscription records, checks/increments cannot race or double-count, failures follow an explicit usage policy and subscription changes retain correct entitlements.
- [x] **Every eligible crop-season is fully scored.** Preserve applicable water, climate resilience, soil, seasonal and rotation criteria when season pools differ, without arbitrary undocumented weights; keep suitability distinct from yield forecasts and optimization.
- [x] **Usable secure signup and concurrency-safe seats.** Non-development email verification has explicit creation/delivery behavior, Free provisioning is correct, and invitation/membership operations protect member limits transactionally. Missing delivery infrastructure is reported honestly.
- [x] **Safe API key lifecycle.** Rotation repeats issuance entitlement checks, revocation blocks reuse, rate storage is bounded with safe cleanup, concurrency is protected and secrets are not re-exposed.
- [ ] **Invoice-bound atomic billing.** Validate exact intended invoice, amount, currency and provider transaction; reject/audit inconsistent events, make duplicates idempotent and prevent delayed/out-of-order events settling unrelated invoices. Verify overlap, delay, duplicate and mismatch cases before production-ready claims; update stale billing tests/docs.
- [x] **Corrected remediation is reviewed and safely integrated.** Inspect original commit and complete diff, implement/regression-test corrections, inspect overlaps and migration heads, preserve AI/GIS, deliberately integrate corrected work and run focused checks immediately afterward. Keep original source branch.
- [ ] **Cross-system verification with honest release evidence.** Preserve NASA HLS/raster/worker/NDVI/EVI/NDMI/NDWI/BSI/sampling/terciles/overlays/provenance/zonal statistics and never present fixtures as observations. Run exact focused/full independent backend, disposable PostGIS migration/integration, frontend unit/component/type/lint/build and critical browser/security checks; classify NOT RUN/BLOCKED distinctly. Record commands/counts/failures/skips, GitHub SHAs/push/cleanliness, readiness and every external requirement in the final engineering report.

### Final status — 2026-11-14

The checked outcomes above are supported by the local evidence in [the final integration report](docs/implementation/MASTER_INTEGRATION_FINAL_REPORT_2026-11-14.md). Four acceptance items intentionally remain open:

- **Rights-aware knowledge and feedback:** ingestion/feedback interfaces exist, but no approved corpus or embedding provider is configured; semantic retrieval is not ready.
- **Job recovery:** implementation and focused coverage exist, but the full combined PostGIS run stopped at 88% without a final summary, so the complete integration gate remains open.
- **Invoice-bound billing:** code and unit coverage exist; the complete callback integration suite and real provider settlement were not verified in the interrupted full run.
- **Cross-system release verification:** the full PostGIS suite is incomplete and GitHub Actions run [43552364021](https://github.com/abdelrahmanelharouny/project1/actions/runs/43552364021) failed at the remote Alembic drift check. The feature branch is pushed at `5a3116770a9ca033d09fa6cf9523957d4c0ca0a3`; `main` remains unchanged.

External production gates also remain: live provider credentials/approval, SMTP, authenticated NASA acquisition, payment settlement, production storage/database, runtime coordinate-disclosure review, and shared multi-replica rate/circuit state.


## CropTwist Figma UI/UX redesign — current mission (2026-11-14)

**Source:** `https://github.com/abdelrahmanelharouny/project1`
**Branch:** `feature/croptwist-ui-ux-redesign`
**Branch created:** 2026-11-14 06:30 +02:00; initial SHA `38f8891696f6c27e79e25ddf65b33549f4a51397`.
**Base:** `feature/ai-complete-integration` at `38f8891696f6c27e79e25ddf65b33549f4a51397` (not `main`). This is the most complete available product-code foundation inspected: it contains the Next.js CropTwist workspace, the nine-destination navigation model, existing destination components and API clients, AI Copilot/orchestration interfaces, and the initial GIS integration. `integration/cropshift-control` is documentation-only; `feature/gis-spatial-analytics` has later GIS commits that are not included in this base and touch map UI/API-related files. The redesign must preserve those active branches and reconcile GIS-specific changes before integration. `main` remains `998f7a5885e4ee0c9defe28671736560fb1b8762` and is not modified.

### 1. Repository, branch safety, and workstream separation — In progress

- The implementation belongs in the actual CropTwist repository, not `/home/ubuntu/fieldshift`; preserve that separate scaffold and its Figma notes.
- Preserve existing branches, commits, pull requests, and worktrees. Do not force-push, rewrite shared history, discard existing work, modify `main`, modify the active AI integration branch, or modify `app/db/models_ai.py`.
- Keep all redesign implementation on `feature/croptwist-ui-ux-redesign`; record its full base/head SHAs and worktree state, use logical commits, and push only this branch after verification checkpoints.
- Use actual source/API behavior to guide implementation. If a shared file conflicts with an active workstream, isolate changes in new components, modules, or adapters; do not stop unrelated UI work because one shared file conflicts.
- Coordinate final integration with the active workstream owner. Never merge into `main`; if no stable approved integration target is ready, keep the redesign branch independently verified and document the integration blocker.

### 2. Figma audit and product mapping — Open

- Inspect all accessible Figma pages and frames, including desktop/mobile layouts, navigation, typography, colors and tokens, spacing/layout, cards, tables, forms, charts, map controls, interactions, empty/loading/error/success/partial states, icons/assets, and English/Arabic layouts where represented.
- Identify complete and incomplete screens, missing screens, inconsistent components, unspecified interactions, and components requiring adaptation to CropTwist.
- Map existing CropTwist routes and screens to the Figma reference and note current routes, intended destination, reusable components, data requirements, interactions, responsive behavior, and design gaps.
- Do not rename the product to FieldShift. CropTwist branding must remain throughout the app even where the Figma board has FieldShift branding.
- Create `docs/audits/FIGMA_REDESIGN_AUDIT.md` with inspected pages/frames, existing routes/screens, proposed screen mapping, design inconsistencies/gaps, components to reuse/build, missing design decisions, and implementation risks.

### 3. Navigation, design system, and responsive application shell — Open

- Preserve the nine primary destinations: Overview; Farms & Fields; Data Hub; Crop Intelligence; Map & Satellite; Decision Center; AI Copilot; Reports & Analytics; Workspace & Settings.
- Preserve supported direct navigation, existing routes, query parameters, legacy redirects, sub-navigation, deep links, command-palette behavior, keyboard interactions, browser back/forward navigation, and mobile navigation behavior. Do not create dead-end pages or break URL compatibility.
- Implement reusable design tokens and components for color, typography, spacing/sizing, borders/radii, shadows/elevation, breakpoints, icons, buttons/actions, inputs/forms, cards/panels, tables/data grids, tabs/navigation, dialogs/drawers, notifications/toasts, tooltips/popovers, charts/map containers, loading skeletons, and empty/error states.
- Reuse the existing framework, component conventions, dependencies, and architecture. Avoid unnecessary libraries, duplicated patterns, competing button/card styles, scattered hard-coded colors, and replacing working components without a clear technical or UX reason.
- Deliver a professional agricultural decision-intelligence SaaS experience with clear hierarchy and high information density without clutter; do not rely on a generic dashboard template, excessive gradients, arbitrary colors, fake charts, or decorative nonfunctional controls.

### 4. Real behavior across all nine destinations — Open

- **Overview:** show real farm/field summaries, crop-season status, weather/environmental indicators, satellite-monitoring summaries, decisions/alerts, recent activity, actionable next steps, data freshness/quality, and quick actions; use actual APIs or explicitly labelled demo fixtures.
- **Farms & Fields:** preserve farm/field management, field creation/editing, details/boundaries, crop-season associations, field context/history, ownership/management where supported, search/filter/navigation, authorization, and tenant isolation.
- **Data Hub:** show real source inventory/status, connection/sync/acquisition/processing state, freshness, quality/coverage, ingestion history, failed/partial jobs, provenance, imports, historical/environmental evidence, and clear live-versus-historical-versus-forecast-versus-synthetic distinctions. Do not mark unconfigured sources operational.
- **Crop Intelligence:** show crop profiles/requirements, soil/climate compatibility, suitability explanations, vegetation/season context, agronomic constraints, and evidence-backed assessments. Keep suitability distinct from yield prediction and do not invent yield predictions or unsupported agronomic claims.
- **Crop Rotation Overview/Planner (Figma B1/B2):** expose additive `cropintel:rotation-overview` and `cropintel:rotation-planner` routes; Overview filters/exports only API-returned crop-history records and displays field, provenance, and history-only states; Planner offers truthful Simple/Expert modes over existing candidate/optimizer operations. Do not add fake future sequence cards or an unsupported save/approval action. Keep `cropintel:rotation` and legacy `?tab=rotation` mapped to the original optimizer, and leave `cropintel:plan` as the existing management-plan page.
- **Map & Satellite:** preserve interactive maps, farm/field geometry, available satellite/raster products and supported NDVI/EVI/NDMI/NDWI/BSI, statistical-zone overlays, pixel inspection where supported, layer/date/observation selection, opacity, legends, quality/coverage/cloud states, field summaries, source/provenance, and spatial reference correctness. Never fabricate satellite imagery, imply unverified live acquisition, or present synthetic fixtures as observations.
- **Decision Center:** preserve crop rotation and multi-season planning, scenarios/alternatives, agronomic constraints and priorities, water/soil/climate considerations, comparisons, rationale, evidence quality/confidence, trade-offs/explainability, human approval, and supported decision history. Keep Evidence Quality, Model Confidence, and Recommendation Confidence distinct; agronomic engines calculate, evidence validates, AI orchestrates/explains, and farmers decide.
- **AI Copilot:** use the actual AI gateway/orchestration and authorized farm/field context; preserve Gemini as primary provider, Groq GPT OSS 120B as first fallback, OpenRouter NVIDIA Nemotron 3.5 Super VL as second fallback, agricultural tool orchestration, field-specific/cross-domain reasoning, RAG, evidence citations, tool summaries, conversation history, feedback, limitations, and authorized observability. Preserve uncertainty, source evidence, privacy/tenant boundaries, provider availability, and safe errors/fallbacks. Do not invent successful responses, bypass provider privacy controls, edit `app/db/models_ai.py` or the AI integration branch, or make live provider calls without approved rotated credentials.
- **Reports & Analytics:** use authorized real data for agricultural/operational summaries, trends, field comparisons, seasons, data quality, decisions/recommendations, and supported export/print; show provenance, dates, quality limitations, and methodology. Never fabricate chart data.
- **Workspace & Settings:** preserve organization/workspace and user settings, members/roles/permissions, integrations, subscription/usage, notification and language/regional preferences, security, data sharing, and existing entitlement rules. Never invent successful payment/subscription state or expose secrets.

### 5. API integration, states, and workstream boundaries — Open

- Before implementing each screen, inspect existing API routes, schemas, services, frontend contracts, and current behavior. Identify the actual endpoint/service; preserve API contracts except for a justified documented compatibility adapter.
- Connect controls to real operations; implement loading, success, empty, stale, partial, error, validation, and retry states. Preserve pagination/filter/sort semantics, authorization, organization/tenant boundaries, navigation, and state transitions. No decorative dead buttons, fake operational data, hidden backend failures, replacement mock APIs, or silently converting missing values to zero. Label unavoidable fixtures accurately and document unavailable endpoints/capabilities explicitly.
- GIS: consume existing GIS interfaces; do not modify GIS algorithms or active GIS branch history. Preserve geometry, CRS, raster provenance/quality, actual layers, authorized sampling/statistical-zone behavior, and explicit unavailable states.
- AI: consume existing gateway/Copilot interfaces; do not edit `app/db/models_ai.py`, the AI branch, provider privacy rules, or live provider credentials. Report provider-unavailable states honestly.
- Control/billing: retain entitlement, quota, role, organization, and permission behavior; never simulate successful billing/payment state.

### 6. Responsive, accessible, English/Arabic and RTL experience — Open

- Verify desktop/laptop/tablet/mobile at 1440px, 1280px, 1024px, 768px, 390px, and 360px. Do not scale desktop down without responsive adaptation. At 390px and 360px there must be no horizontal overflow; navigation, tables, charts, maps, dialogs, and touch targets must remain usable.
- Preserve English and Arabic localization and translation parity. Do not hardcode user-facing strings. Support correct `lang`/`dir`, RTL mirroring, direction-aware icons/spacing, Arabic labels/typography, date/number formatting where applicable, long text, and mobile RTL.
- Use semantic HTML, accessible names/labels, keyboard navigation, visible focus indicators, screen-reader-friendly controls, adequate contrast, and usable keyboard interaction for forms, dialogs, maps, and menus.

### 7. Verification and regression evidence — Open

- Run and record exact TypeScript, ESLint, frontend unit/component tests, production build, translation-parity checks, and applicable integration/API contract tests.
- Verify critical navigation/deep links, loading/empty/error/partial states, organization switching/authorization, Data Hub/provenance, GIS map workflows, AI Copilot privacy/errors, mutations/forms, exports, and settings/entitlements where supported.
- For every redesigned destination, open the actual application, capture screenshots, compare each screen with its corresponding Figma frame, identify and fix visual mismatches, then repeat the comparison.
- Verify typography, colors, spacing, alignment, component proportions, navigation, responsive layouts, information hierarchy, empty/loading/error states, and interactive states.
- Create a visual QA checklist mapping every inspected Figma frame to its implemented application page. Do not claim pixel-perfect matching unless it has actually been inspected and verified.
- Perform desktop/mobile/Arabic RTL browser checks at 1440px, 1280px, 1024px, 768px, 390px, and 360px, including keyboard/focus/accessibility checks and console/network-error inspection.
- Record actual screenshots, exact commands, results/counts, failures, skips, and unavailable dependencies; do not imply visual evidence exists when it has not been captured.
- Do not weaken/delete/skip failing tests merely to obtain green status. Distinguish implemented, tested, partially implemented, blocked, not run, and externally dependent behavior precisely.

### 8. Documentation, review, and delivery — Open

- Create `docs/engineering/FIGMA_IMPLEMENTATION_REPORT.md` and `docs/engineering/REDESIGN_REGRESSION_REPORT.md` documenting implemented screens, Figma-to-code mapping, reusable components, changed routes, integrated APIs, preserved features, unavailable backend capabilities, accessibility/localization results, exact test evidence, and remaining issues.
- Review the full diff for accidental temporary files, secrets, unrelated changes, regressions, and workstream overlap before delivery.
- Keep commits logical/reviewable on `feature/croptwist-ui-ux-redesign`; push the branch after verification checkpoints when permitted. Do not merge directly into `main`; coordinate integration separately and leave integration pending if its target is not stable or approved.


### Progress evidence — 2026-11-14

- The actual repository is `abdelrahmanelharouny/project1`; work is isolated in `/home/ubuntu/project1-ui-ux` on `feature/croptwist-ui-ux-redesign`, based at `38f8891696f6c27e79e25ddf65b33549f4a51397`. No changes have been made to `main`, the GIS branch, the AI integration branch, `app/db/models_ai.py`, or `/home/ubuntu/fieldshift`.
- The shared forest/charcoal visual system, responsive CropTwist sidebar, Data Hub feature empty/loading/error states, observation navigation action, and Arabic-aware mobile navigation have been implemented. This is partial screen coverage; the nine-destination redesign and browser comparison are not complete.
- `npx --yes --package bun@1.4.4 bun test tests/frontend` — **142 passed, 0 failed**.
- `npx --yes --package bun@1.4.4 bun run lint` — **passed**.
- `npx --yes --package bun@1.4.4 bun x tsc --noEmit` — **passed**.
- `npx --yes --package bun@1.4.4 bun run build` — **passed**.
- All locale JSON parses; `messages/en/features.json` and `messages/ar/features.json` have matching **79-key** sets.
- Development HTTP checks: `/` returned **200**; `/manus-routes.json` returned **200** with **10** declared route states.
- Chromium sign-in screenshots at **1440×900**, **390×844**, and **360×800** are stored under `docs/audits/visual/`. Those sign-in captures fit without horizontal overflow; they do not verify authenticated workspace screens.
- Authenticated visual and workflow checks remain blocked because the frontend's `/api/v1/me` and `/api/v1/health/ready` requests proxy to `127.0.0.1:3030`, where no backend is listening (`ECONNREFUSED`). No test credentials were available. The demo-workspace action was not invoked because it would use the demo-seed path and could write sample data to an unverified backend/database. Do not mark the per-destination visual QA, backend/GIS/AI workflow, or complete redesign outcomes done until those dependencies are available and tested.
- Replaced the inherited external ChatGLM favicon and “First vertical slice” metadata with a local CropTwist sprout SVG and factual product description.
- First code checkpoint `851ae78b0f232df6e9be911ee17f25039db6fd88` is pushed to `origin/feature/croptwist-ui-ux-redesign`; the remote ref was verified to match, the worktree is clean at that checkpoint, and remote `main` remains `998f7a5885e4ee0c9defe28671736560fb1b8762`. No PR or merge was created.

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

# CropTwist — Master Repository Audit

**Audit date:** 2026-11-14
**Repository baseline:** `main` at `01f9fa2524a71a1bee40e523b729e4c73f6d37d9`
**Scope:** source and history review of the existing CropTwist monorepo; selected fixes and checks are described separately below.
**Evidence rule:** inspected code establishes source-level implementation only. A test definition, mock, fixture, configured CI job, adapter, or historical smoke does not establish current runtime or live-provider success.

## Executive assessment

CropTwist is a substantial existing platform rather than a greenfield prototype. It contains a Next.js multi-destination workspace; a modular FastAPI service; PostgreSQL/PostGIS schemas and additive migrations; observation, climate, soil, satellite, and raster workflows; deterministic agronomic and decision engines; optional LLM explanations; report, commercial, and developer screens; and a broad set of backend and frontend tests. The architecture is oriented toward traceable decision support and often distinguishes measured evidence, model/reanalysis outputs, synthetic fixtures, and missing data.

The repository is **not production-ready**. Several audit findings affect authorization, subscription enforcement, measurement integrity, restart/job consistency, agronomic interpretation, AI-generated prose, and deployment. Multiple external integrations exist in source but are not verified in the current deployment. The audits did not start services, apply migrations, query provider endpoints, or inspect secret values.

The current working batch closes part of three reliability/security concerns: logout now revokes the active access/refresh token family; field briefs require current-pack inline citations and numeric screening with one retry then fail-closed fallback; and root Compose settings now use the application's `CROPTWIST_` namespace, default dev mode off, and gate dependent containers on readiness. The P07 report registry expectation was corrected, and frontend unit tests were added to CI. These changes have not yet been committed at the time of this report unless a later milestone report records the resulting commit.

## Repository and architecture

### Frontend

The frontend is a Next.js App Router application whose main client workspace composes nine destinations and 31 sub-pages: Overview, Farms & Fields, Data Hub, Crop Intelligence, Map & Satellite, Decision Center, AI Copilot, Reports & Analytics, and Workspace & Settings. It has typed API modules, responsive desktop/mobile navigation, locale plumbing for English and Arabic, a MapLibre field/raster experience, and commercial/account interfaces. `src/lib/navigation.ts` centralizes canonical routes and legacy resolution; destination content is composed in `src/components/croptwist/workspace.tsx`.

The frontend is substantially implemented, but several flows still choose the first organization rather than a user-selected organization: Billing, Reports, Insights, and Developer views derive the organization from the first returned membership while Team settings offers a selector. Observations and Features sometimes make failed requests look like empty data; the map pane does not surface a fields-query error/empty state. The commercial API client can retry a 401 recursively without a bound, and report downloads bypass the shared refresh path. Arabic document direction is configured, but some navigation/layout utilities remain physically left/right; bootstrap and fatal fallback copy is not consistently localized. Existing tests mostly cover navigation and pure map/analytics helpers, not rendered route states, API failures, RTL journeys, or accessibility interactions.

### Backend and data model

The backend is a FastAPI modular monolith with versioned domain routers, SQLAlchemy 2/GeoAlchemy2 models, PostgreSQL/PostGIS, and an Alembic history through `0023_p07_field_reports`. Modules cover identity, farms/fields, data platform, features, knowledge, recommendations/advisor, water, soil, management, rotation, scenarios, sensitivity, robust rotation, decision documents, digital twin, geospatial products, analytics, reports, and commercial account features. The migrations have an intentional branch merge and current CI declares upgrade, drift check, pytest, and API/bridge smoke steps.

There is meaningful tenant scoping and token/session hardening, but path parity is incomplete. The audits found that the legacy farm-member route can grant `owner` to an `org_admin`; non-development registration returns a usable access/refresh pair before email verification; Free/no-subscription entitlements are bypassed in some farm/field/public-API paths; a zero public-API rate entitlement can become a positive default; and the billing webhook accepts a predictable default secret without production fail-fast validation. Email delivery and real payment processing are absent. Outgoing webhook URL validation does not fully block private/internal destinations or DNS rebinding, and webhook signing secrets are stored in recoverable plaintext.

The Alembic environment imports core, AI, and P2 metadata but omits the P3 model module, even though P3 tables are migrated and CI runs `alembic check`. Migration tests do not explicitly cover the full current P2/P3 schema. This needs a database-backed migration fix and verification before relying on the drift check.

### Data, GIS, and external providers

The canonical observation/provider contracts carry quality, evidence class, synthetic status, source/product lineage, temporal/spatial support, coverage, request identifiers, and raw references. The repository has adapters or workflows for Open-Meteo historical archive (ERA5/ERA5-Land), SoilGrids WCS, operator-upload CHIRPS rasters, farmer CSV, NASA HLS CMR discovery and Earthdata-gated asset reads, a deterministic synthetic provider, local/S3-compatible raster storage, and authenticated map/spatial APIs. A separate P05 raster preprocessing path reprojects field geometry to raster CRS, windows reads, masks nodata/Fmask, derives indices, and produces zonal summaries/COGs. Synthetic test imagery is labelled as test-only and is not an observation.

Important correctness gaps exist in the **direct HLS acquisition** route, distinct from the newer P05 preprocessing route. Acquisition orchestration drops the Fmask asset reference before provider evaluation; the provider applies EPSG:4326 geometry directly to projected source raster coordinates and reads full band arrays rather than a reprojected field window. The HLS contract test seam uses a geographic transform and does not prove projected LP DAAC correctness. Ingestion's duplicate-row handler rolls back the whole current transaction, potentially discarding earlier valid rows while reporting success. The observation contract validates only one direction of the null/missing invariant, CSV parsing can accept non-finite floats, normalized headers are not consistently used for row access, BOM stripping can make the checksum differ from uploaded bytes, and coverage counts all non-null values as valid regardless of quality status. Provider-level coverage/request/raw-reference metadata is not all persisted at run level.

Source availability is not live readiness. The audit did not make external requests or inspect credential values. NASA protected asset access requires Earthdata; Sentinel/CDSE requires environment/credentials as applicable; current SoilGrids and Open-Meteo status is unknown; CHIRPS is an upload path rather than automatic download; S3 tests use a fake client; the Compose stack does not provision a durable object store. The map is intentionally offline beneath field geometry and has no conventional road/terrain basemap.

### Agronomic and decision intelligence

The repository contains deterministic crop suitability and rotation logic, OR-Tools CP-SAT optimization, water planning, soil assessment/nutrient accounting, management/cover/residue logic, climate risk, vegetation temporal signals, scenarios, sensitivity, robust rotation, decision comparisons, and digital-twin artifacts. Its better design choices are explicit: suitability is not yield prediction; economic inputs are farmer-supplied; synthetic observations are flagged; unconfirmed knowledge stays advisory; absent water/soil evidence is not silently replaced with a positive value; unsupported scenario dimensions are rejected; and a universal soil-health composite is not manufactured.

The code audit found important evidence/temporal consistency risks. Active crop-pack loading can combine traits/windows/Kc anchors from a losing crop-code version; regional traits can be cited while numeric calculations use only global values; a crop may be marked eligible with material climate/soil/water dimensions unevaluated; annual precipitation thresholds can be compared directly with partial-season totals; multi-season optimization coefficients can reuse first-season scores while the displayed criteria aggregate seasons; interval-valued root-depth/N-fixation traits can be ignored; vegetation-stress context is not consistently period-aligned; sparse forecast dates can count as consecutive dry days; and decision changes are globally ranked across unlike features/units despite documentation saying otherwise. Robust solver steering is a proxy, not necessarily the displayed post-hoc worst-case objective.

No trained/deployed predictive ML model or training/retraining pipeline surfaced in the audited first-party scope. No validated yield prediction, calibrated crop-stress probability, or production outcome-learning loop was found. Reference knowledge packs require regional agronomist validation; climate projection inputs, scenario ET0/water requirements, disease/pest diagnosis, and some management/soil scenario dimensions remain absent or structurally unavailable.

### AI and Copilot

The AI design already separates deterministic recommendation generation from optional LLM prose: rules persist recommendations and engine outputs; a field-scoped evidence pack is assembled; advisor sessions and feedback are persisted; Q&A validates citations and screens numbers; and unavailable/malformed bridge calls can fall back to deterministic text. The LLM is not the agronomic calculator. Feedback is append-only and does not silently retrain the engine.

The runtime trust boundary is incomplete. Before this working batch, field briefs and recommendation narratives could surface structured/raw model text without the Q&A citation/numeric checks. Field briefs now require a structured response, inline citation(s) valid for the current evidence pack, and numeric validation; a single rejected response is retried once and repeated invalid output returns no model brief. Recommendation narratives **remain an open gap** and can still bypass the same checks. The advisor numeric matcher itself is screening-grade: it matches against a global value set rather than a fact-bound domain/unit and its `kg/ha`/`Mg/ha` conversion does not apply the 1,000 factor. Prompt delimiters are not escaped against closing-tag content, and user-controlled farm/field metadata can be placed in context described as trusted. Backend/bridge deadlines and token-budget controls are not fully aligned; outstanding work may continue after fallback, output tokens are omitted from one budget check, and durable dollar-cost accounting is absent. The bridge uses one provider SDK; no provider registry/fallback routing, model-selected tool execution, document RAG/vector retrieval, or trained predictive ML model was found.

### Jobs, operations, and deployment

Persistent background/domain job rows exist, but the execution queue is process-local. API workers use an in-memory `queue.Queue`; a separately started worker does not receive new API submissions after its startup scan; there is no shared broker or atomic distributed claim. Ingestion executor registration occurs lazily, queue/domain statuses can diverge, interrupted domain rows are not reconciled, and raster jobs may be queued before their domain rows commit. Rate limiters, scheduler/circuit state, metrics, and narrative cache are process-local. Metrics retain latency samples in an unbounded list and rely on network controls for access.

The root Compose file previously supplied `FIELDSHIFT_*` variables that the API's `Settings` (prefix `CROPTWIST_`) ignored. This working batch changes application settings to `CROPTWIST_*`, corrects the database URL binding, defaults dev mode off, probes `/health/ready`, and makes web/gateway startup wait for healthy dependencies. Static YAML parsing and namespace assertions pass. Docker/Compose CLI is unavailable in this sandbox, so no container configuration, build, or service was executed. Root Compose remains a demo topology with published ports, host-network Caddy on cleartext port 81, demo database defaults, and local artifact storage; it is not production infrastructure. Production still requires managed PostGIS, TLS/fixed ingress, secret management, persistent artifact storage, coordinated workers, monitoring, and tested backup/recovery. Backup scheduling docs also conflict about what is automated versus environment-provided.

## Classification summary

| Classification | Audited state |
|---|---|
| Implemented and source-reviewed | Nine-destination workspace; typed frontend API surface; tenant-scoped domain APIs; provenance-oriented observation contracts; deterministic agronomic/decision engines; P05 windowed raster pipeline; local/S3 storage abstraction; reports/analytics source; feedback ledger; optional advisor bridge and rules-only degradation. “Source-reviewed” does not mean end-to-end verified. |
| Implemented but incomplete/incorrect | Session/verification/RBAC/entitlement paths; HLS direct acquisition; duplicate ingestion and observation quality/checksum semantics; background-job lifecycle; agronomic pack/region/season reasoning; LLM brief/narrative safety; frontend organization selection and async error states; Alembic model metadata; root deployment/security. Logout and field-brief checks were improved in this working batch, but overall rows remain incomplete. |
| Partially integrated | External provider adapters; S3; LLM bridge; commercial billing; reports; worker and scheduler; metrics. The current target deployment, credentials, durable infrastructure, and live integrations were not verified. |
| Missing in audited scope | Production email delivery; real payment processing; automated CHIRPS acquisition; road/terrain basemap; document RAG/vector retrieval; trained predictive ML; model-selected tool execution; feedback-driven calibration. Some are requirements to evaluate, not promises that they must ship without validated value. |
| Externally blocked or unknown | Current Earthdata/CDSE access, current SoilGrids/Open-Meteo service state, production S3, external LLM provider health/spend, managed production database, worker deployment, TLS ingress, email/payment services, and regionally validated knowledge. |
| Architectural improvement needed | Shared job claims/leases and distributed rate limits; persistent/aggregated monitoring; production recovery; durable artifact storage; bounded HTTP/browser/accessibility test coverage; broader end-to-end evidence-safe AI contracts. |

## Prioritized high-impact findings

1. **P0 — production configuration and insecure defaults.** Root Compose settings were previously ignored because of the prefix mismatch; default billing webhook secret and permissive production/dev configuration require fail-safe startup checks; root ingress is a demo setup, not a secure production profile.
2. **P1 — authentication, role, and entitlement bypasses.** Logout now revokes a session family. Still open: usable unverified registration tokens, legacy `org_admin` owner grants, no-subscription/Free-tier enforcement bypasses, and disabled public API entitlements.
3. **P1 — schema/migration metadata mismatch.** P3 models are missing from Alembic target metadata while `alembic check` runs in CI; verify current P2/P3 schema and report-field integrity.
4. **P1 — scientific/data integrity.** Direct HLS path drops Fmask and mishandles projected CRS/windows; duplicate rollback, non-finite values, CSV checksums/headers, and coverage quality semantics need regression tests.
5. **P1 — job lifecycle correctness.** Register executors before recovery, reconcile queue/domain outcomes, commit before dispatch, and test fresh-process restarts/failures/races.
6. **P1 — generated AI text safety.** Field briefs now use fail-closed citation/numeric screening; narratives still bypass it, numeric matching is not domain/unit-bound, and prompt-boundary issues remain.
7. **P1 — agronomic conclusion semantics.** Correct regional traits, active-pack ownership, partial-evidence status, temporal matching, and season-specific optimization before interpreting results as complete.
8. **P1/P2 — frontend organization and evidence display.** Use an explicit selected organization across commercial pages; distinguish empty from failed; bound auth retries; fix RTL and localized root fallbacks.
9. **P1 — live readiness evidence.** Maintain separate credential state and current successful probes for provider discovery versus protected asset access; never conflate fixtures with live observations.
10. **P2 — production operations.** Shared queue/claims, persistent storage, bounded/exported metrics, backup schedule and restore drills, and production Compose/ingress need deployment evidence.

## Verification baseline and implementation evidence

### Executed successfully

- `bunx tsc --noEmit` — passed.
- `bun run lint` — passed.
- `bun run build` — passed.
- `bun test tests/frontend` — **122 passed, 0 failed** (three files). The same command is now in `.github/workflows/ci.yml`.
- `mini-services/llm-bridge`: `bun install --frozen-lockfile && ../../node_modules/.bin/tsc --noEmit` — passed; the install used the existing lockfile and did not change it.
- Backend database-independent unit tests: `PYTHONPATH=. .venv/bin/pytest --confcutdir=tests/unit --ignore=tests/unit/test_geospatial_rendering.py -o addopts= tests/unit -q --disable-warnings` — **924 passed**, 2,217 warnings, exit status 0. The excluded geospatial-rendering module requires PostgreSQL fixtures; the warnings include existing SQLAlchemy `SAWarning` messages about model attributes named `metadata`.
- `tests/unit/test_report_renderers.py` — 17 passed after adding the three current P07 report types to the expected registry.
- `tests/unit/test_identity_token_revocation.py` — 1 passed.
- `git diff --check` — clean.
- Static parse of `.github/workflows/ci.yml` and `docker-compose.yml` using `js-yaml` — passed. Compose API environment keys were verified to use the `CROPTWIST_` prefix; dev mode defaults off; readiness is configured.

### Not executed / not verified

- PostgreSQL/PostGIS test or migration suite; neither `127.0.0.1:5432` nor `:5433` accepted connections. The new logout API integration assertion is therefore present but unexecuted locally.
- Alembic upgrade/downgrade/drift check, CI hosted run, backend E2E smoke, Docker Compose build/start, frontend browser rendering, responsive/RTL/accessibility journey, and cross-service API integration.
- Live NASA/Sentinel/SoilGrids/Open-Meteo/S3/payment/email/model-provider call or production credential check. No secret values were read into the audit or report.
- No application database, migration, service, container, or external provider was started or modified during the audit work.

## Changed in the current implementation batch

- `mini-services/fieldshift-api/app/domains/identity/service.py`: logout revokes all unrevoked tokens in the authenticated access token's family and limits lookup to the authenticated user/access-token kind.
- `mini-services/fieldshift-api/tests/integration/test_auth_tenant_isolation.py` and `tests/unit/test_identity_token_revocation.py`: refresh-after-logout regression coverage.
- `mini-services/fieldshift-api/app/intelligence/advisor.py` and `tests/unit/test_field_brief_validation.py`: fail-closed field-brief citation/numeric validation, one bounded retry, and deterministic/no-model-text fallback.
- `mini-services/fieldshift-api/tests/unit/test_report_renderers.py`: P07 report registry expectation update.
- `.github/workflows/ci.yml`: add the frontend helper regression suite to CI.
- `docker-compose.yml` and `.env.example`: correct the API settings namespace/database target, turn dev mode off by default, gate services on readiness, and provide a local-only non-secret template.
- Root and backend README/known-limitations documents: refresh outdated provider, migration, job, AI, and test statements; distinguish historical records from current state.

## Release posture

**Not production-ready.** Continue the P0/P1 security, migration, evidence-integrity, job-lifecycle, agronomic, and AI-safety work. Then run the complete backend migration/integration/E2E suite in an isolated PostGIS environment, exercise the actual app/browser workflows (including Arabic RTL), and perform authorized live-provider and deployment checks with managed credentials and infrastructure. Record their timestamps and outcomes before describing any integration as live or any product surface as production-verified.

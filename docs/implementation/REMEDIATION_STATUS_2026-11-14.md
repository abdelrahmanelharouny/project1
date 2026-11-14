# CropTwist Remediation Status — 2026-11-14

## Purpose and baseline

This report records code remediation on the dedicated `remediation/legacy-hardening` branch. It is a follow-up to the [pre-remediation master audit](../MASTER_REPOSITORY_AUDIT.md), [gap analysis](../MASTER_GAP_ANALYSIS.md), and [milestone report](MASTER_AUDIT_MILESTONE_2026-11-14.md); those documents remain historical baseline snapshots rather than proof of current branch state.

The branch was created from `main` / `origin/main` at **`998f7a5885e4ee0c9defe28671736560fb1b8762`**. The mission is corrective, not feature development: no future AI Core was introduced. No GIS/raster implementation file was changed. A separate GIS workstream owns direct satellite/raster correctness; the existing direct HLS defects remain open here by instruction.

## Workstream outcomes

| Workstream | Current outcome | Code-level remediation in this branch | Remaining acceptance gap |
| --- | --- | --- | --- |
| **A — Authentication, authorization, tenancy** | **Partially remediated** | Non-development signup no longer issues a usable session before email verification. Access-token and refresh paths reject unverified accounts; refresh rotation is locked; logout resolves bearer or session-cookie identity and revokes the full token family. Legacy farm-member changes require exact owner authority, and a role-escalation regression was added. Report creation rejects a field/farm mismatch and payload gathering applies both selectors. | No PostgreSQL/PostGIS integration run was possible. Tenant-scoping across every route, evidence/context builder, cache, conversation, and job still requires systematic API tests. Email/verification delivery is absent, so non-development onboarding cannot be completed without an operator-provided adapter. |
| **B — Plans, entitlements, billing, API security** | **Partially remediated** | Missing subscriptions resolve to explicit Free-plan limits on the changed farm/field, report, organization-seat, legacy member-add, and public-API-key paths. API-key issuance/authentication respects current API enablement and rate; zero is denied. Production startup refuses the sandbox billing adapter and requires an explicit strong secret. Billing callbacks enforce timestamp freshness and invoice amount/currency checks. Outbound webhooks reject non-public destinations, pin DNS resolution, and disable redirects. | Billing remains sandbox-only; no live provider is configured. Signing secrets are still stored recoverably in the database. Mocked webhook tests do not establish a deployed egress boundary. API key lifecycle, tenant scope, quota, and downgrade integration coverage still requires the database-backed suite. |
| **C — Observation ingestion and integrity** | **Core validation remediated; provider provenance partial** | CSV headers are normalized consistently, BOM input is handled, numeric inputs must be finite, and the SHA-256 is based on the exact uploaded bytes. Canonical observation DTOs enforce finite values, missing/null consistency, and time-period order. Per-row savepoints isolate duplicate/integrity failures. Coverage counts only non-null `valid` observations as usable. | CSV parser contracts ran; database persistence, upload rollback, GeoTIFF ingestion, and provider replay were not run against PostgreSQL/PostGIS. Provider coverage/request/raw-reference persistence is incomplete, and quality semantics for stale, conflicting, and questionable records still need a common contract. |
| **D — Satellite, raster, geospatial reliability** | **Deferred to the separate GIS workstream** | No direct HLS, Sentinel-2, raster, or GIS implementation file was changed in this branch. | Direct HLS Fmask propagation, cloud/shadow masking, CRS reprojection, field-windowed reads, grid alignment, clipping, nodata, and full lineage/analytical verification remain open. Source presence and the separate P05 path are not proof of direct-path correctness. No provider was live-tested. |
| **E — Jobs and operational reliability** | **Reliability code improved; runtime acceptance incomplete** | `background_jobs` is the durable source of truth. Workers poll persisted queued rows, claim jobs with a database row lock, register built-in executors before startup recovery, and recover stale jobs with a bounded attempt count and configurable stale threshold. | No multi-process/PostgreSQL restart test ran. Raster processing still needs verified transaction/outbox ordering so a worker cannot see a generic queue row before its domain row commits. Duplicate execution, idempotency, concurrent recovery, failure propagation, and cancellation need database-backed tests. The local queue is a wake-up optimization, not a broker. |
| **F — Agronomic and decision correctness** | **Targeted scoring and evidence fixes implemented** | Knowledge rows are assembled from the winning crop-pack version; exact country-specific numeric traits now match citation resolution. Seasonal precipitation is not directly judged against annual reference bounds. Missing critical climate/calendar evidence is explicit; secondary missing dimensions remain visible and can yield conditional status. Rotation scores pool season-dependent values across the planning horizon; criteria with incomplete candidate/season evidence are omitted rather than zero-filled. Soil-health composites use sourced numeric root-depth/N-fixation traits only and remain unevaluated when those inputs are absent. | Solver objectives still include proxies and steering scores; robust-rotation/post-hoc aggregation and user-facing explanation alignment need further review. Knowledge packs remain reference-grade and require agronomist validation. No yield, price, universal recommendation, or regional prescription is produced. |

## Additional safety details

The `.env.example` now leaves the billing webhook secret blank and states that the value belongs in a secret manager. A blank development/test secret is not a production credential; production startup intentionally remains unavailable until a real provider adapter is implemented. Webhook signing secrets are not encrypted at rest. The remediation does not claim commercial, geospatial, or production readiness.

The branch also retains the earlier field-brief safety gate: every generated brief sentence must cite the current evidence pack, numeric values must match same-unit references from that cited section, and invalid model output is retried once then omitted. Recommendation narratives still lack that runtime gate. Advisor Q&A numeric matching, prompt trust-boundary escaping, single-provider LLM operation, cache key coverage, and live-provider checks remain open.

## Verification performed

| Check | Result |
| --- | --- |
| Backend database-independent unit suite: `PYTHONPATH=. .venv/bin/pytest --confcutdir=tests/unit --ignore=tests/unit/test_geospatial_rendering.py -o addopts= tests/unit -q --disable-warnings` | **941 passed**, 2,217 warnings. The PostgreSQL-fixture geospatial-rendering module was excluded. |
| CSV parser contracts: `PYTHONPATH=. .venv/bin/pytest --confcutdir=tests/contract -o addopts= tests/contract/test_farmer_csv_import.py -k 'not EndToEnd' -q --disable-warnings` | **17 passed, 2 deselected** (the persistence/end-to-end cases). |
| Frontend helper/navigation tests: `bun test tests/frontend` | **122 passed, 0 failed**. |
| Frontend TypeScript: `bunx tsc --noEmit` | Passed. |
| Python syntax: `python -m py_compile` on changed implementation and test modules | Passed. |
| Patch whitespace: `git diff --check` | Passed after the final code and documentation updates. |
| Ruff | Not run; Ruff was not installed. |
| PostgreSQL/PostGIS integration, migrations, containers | Not run. No local PostgreSQL readiness utility or Docker runtime was available; no database/container was started. |
| Hosted CI, live provider/webhook, production deployment | Not run or claimed. |

The full database-backed integration suite remains mandatory before release. Unit success is not a substitute for database transaction, tenant-isolation, worker-restart, migration, or external-provider verification.

## Highest-priority remaining work

1. Complete and live-verify the separate GIS workstream's direct HLS path and provider truthfulness; keep the distinction between Open-Meteo reanalysis and a forecast explicit.
2. Add isolated PostgreSQL/PostGIS CI execution for migrations and the updated auth, billing, entitlement, report, observation, and queue integration tests. Include fresh-process/multi-worker recovery and raster dispatch transaction ordering.
3. Expand tenant-isolation tests across all route/context/cache/job boundaries; add secret-at-rest protection for webhook credentials and persistent production egress controls.
4. Implement production email and payment adapters only with operator credentials and provider validation; until then, keep production startup/payment claims blocked.
5. Apply the field-brief evidence contract to recommendation narratives, correct advisor Q&A fact/unit matching, and improve prompt trust-boundary handling.
6. Continue evidence-grounded agronomic validation of regional knowledge, robust/portfolio solver proxies, and explanation-vs-objective alignment; do not characterize reference values as agronomist-confirmed advice.

# Decisions and Assumptions

Records architectural decisions (ADR-style, lightweight). Each entry: context → decision → consequences.

## ADR-0001 — Modular monolith, two processes in the sandbox

**Context.** The master spec prescribes a Python FastAPI backend + React frontend. The sandbox repository is a Next.js 16 app whose preview exposes one HTTP port through a Caddy gateway; Docker Compose is unavailable.

**Decision.** Keep the modular-monolith shape: FastAPI application (`mini-services/fieldshift-api`) with domain/application/data-platform/geospatial layer separation, run as an independent mini-service on `127.0.0.1:3030`; Next.js serves the React workspace on `:3000`. API reachability:
- Through the gateway (user preview): relative fetches carry `?XTransformPort=3030`; Caddy forwards.
- Directly on `:3000` (local dev): a Next.js rewrite proxies `/api/v1/*` to the FastAPI service.

**Consequences.** One codebase, clean module boundaries, real process separation. Production deployment can move FastAPI behind a standard reverse proxy without code changes.

## ADR-0002 — Real PostgreSQL 16 + PostGIS 3.5 via conda-forge (user-space)

**Context.** The spec requires PostgreSQL + PostGIS. The sandbox has no root, no Docker, and the `pgserver` wheel ships without PostGIS.

**Decision.** Install PostgreSQL 16.10 + PostGIS 3.5.0 (GEOS 3.13, PROJ 9.5) from conda-forge into `db/pgenv` (fully user-space, no root), cluster in `db/pgdata`, listening on `127.0.0.1:5433`. `scripts/ensure_db.py` starts it on demand and guarantees the `fieldshift` database + `postgis` extension exist. Migrations are authored as plain Alembic/PostGIS DDL that runs unchanged on a managed PostgreSQL+PostGIS service in production.

**Consequences.** The running database is genuinely PostgreSQL + PostGIS (geometry columns, `ST_Area` on geography, spatial indexes). Sandbox lifecycle scripts are dev-only conveniences, documented in `docs/architecture/deployment.md`.

## ADR-0003 — Geodesic area in PyProj, cross-checked against PostGIS geography

**Context.** Master §14.1 forbids planar square-degree area. Two defensible engines exist: PyProj `Geod` (WGS84 ellipsoid, application-side) and PostGIS `geography ST_Area` (spheroidal, database-side).

**Decision.** Compute `area_ha` at write time with PyProj Geod and store it; expose the PostGIS geography area as `postgis_geodesic_area_ha` for cross-checking. Integration tests require < 0.5 % divergence.

**Consequences.** Honest, redundant area computation; mismatch would signal geometry corruption.

## ADR-0004 — Minimal but real authentication for the slice

**Context.** Tenant isolation (Master rule 17) needs authenticated users, but the slice does not yet need full identity product features.

**Decision.** Email+password (PBKDF2-HMAC-SHA256, per-user salt, 120k iterations in dev), opaque 256-bit bearer tokens stored as SHA-256 hashes with expiry and revocation. `POST /auth/register` creates a personal organization + owner membership. Every farm/field/data route resolves a `Principal` and checks organization membership. Refresh-token rotation, rate limiting and RBAC granularity are deferred (see KNOWN_LIMITATIONS).

**Consequences.** Real authorization semantics are testable now; upgrade path to a fuller identity stack is isolated in `app/domains/identity` + `app/core/security`.

## ADR-0005 — Deterministic synthetic provider as the only data source in the slice

**Context.** Master rule 7/8: synthetic data must be visibly labelled; NASA and even real alternative providers are not required for the first slice.

**Decision.** One provider: `synthetic` (`app/data_platform/providers/synthetic`). Determinism via SHA-256 of the full request signature (seed, profile, AOI geometry, sorted variables, dates) feeding a `random.Random` stream — same request ⇒ identical series regardless of variable order. Five fixture profiles with invented shape constants (explicitly NOT agronomic claims). Every row: `is_synthetic=true`, generator version, seed, profile, purpose in metadata; product attribution says "SYNTHETIC TEST FIXTURE".

**Consequences.** Contract tests can demand byte-identical reruns; the UI can honestly badge everything; future providers slot into the same protocol without touching ingestion/passport logic.

## ADR-0006 — Idempotent ingestion via natural-key uniqueness

**Context.** Master §49: retries must not duplicate observations.

**Decision.** Unique constraint on `(field_id, dataset_product_id, variable_code, observed_at, time_support, spatial_support_type)`; ingestion flushes rows and treats integrity errors as idempotent skips. Job state lives in `ingestion_jobs` (queued/running/succeeded/failed/cancelled/retrying) with records received/rejected and warnings persisted.

**Consequences.** Reruns converge; the API contract for jobs will not change when execution moves to a real queue/worker.

## ADR-0007 — Data Passport reports facts separately and blocks honestly

**Context.** Master §16/§27: no synthetic confidence scores; missing data must produce not-evaluated results.

**Decision.** The passport aggregates per-variable facts (counts, valid ratio, missing count, period, resolution, freshness, provenance, warnings) without merging them. Analysis readiness uses explicit rules listing required variables (with minimum valid-coverage ratios) and extra requirements; anything not implemented (water budget, rotation optimization, soil analysis) is reported `blocked` with the exact missing inputs and milestone references.

**Consequences.** The UI can never imply an analysis is possible when evidence is absent; adding Milestone-4+ capabilities becomes a rule-table change.

## ADR-0008 — Pragmatic email validation; reserved domains allowed

**Context.** Pydantic `EmailStr` (email-validator) rejects reserved domains (`.local`, `example.com`) that are legitimately used for fixtures/demo accounts.

**Decision.** Validate email shape (regex + lowercasing) at the edge; full deliverability validation is a production concern.

**Consequences.** Demo/fixture accounts work; production hardening list includes stricter validation.

## Assumptions

1. The sandbox preview always reaches the API through the gateway or the Next rewrite; both are covered.
2. Demo workspace seeding (`POST /api/v1/dev/seed-demo`) is dev-only and disabled when `FIELDSHIFT_DEV_MODE=false`.
3. The Next.js `/` route is the only user-visible route in this environment; all sections live in one workspace.
4. Prisma/SQLite scaffolding in the repository remains untouched and unused by FieldShift (sandbox convention), to be removed when the template constraint lifts.
5. Coordinate reference for all stored boundaries is EPSG:4326 as specified; antimeridian inputs produce warnings rather than silent re-wrapping.

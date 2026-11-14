# Local deployment verification

Run date: **2026-11-14**. Branch: `feature/croptwist-free-deployment`. Exact base: `998f7a5885e4ee0c9defe28671736560fb1b8762` on latest `origin/main`. No remote provider project/deployment/database was accessed or mutated. No paid plan, trial, resource, card or automatic billing was enabled.

## Frontend checks

`bun install --frozen-lockfile` passed using Bun 1.3.4; the existing `bun.lock` remains unchanged. The resolved Next.js version is 16.4.6. `bun x tsc --noEmit` and `bun run lint` passed. `bun test tests/frontend` passed **129 tests, zero failures**, including 7 new deployment-origin tests. An initial shell attempt used unavailable `bunx` and returned 127; the corrected `bun x tsc --noEmit` was run and passed.

Final lint excludes generated `.next-*` build outputs only; no application rules or Alembic checks were suppressed. A preliminary lint run over those generated outputs returned 1; the final source lint passes.

A Vercel-style production build with `VERCEL=1 CROPTWIST_API_ORIGIN=https://croptwist-api.invalid` passed, including Next's TypeScript checks and route generation. A missing-origin Vercel build returned **1 as expected**, failing closed. A fake database-secret sentinel and the backend test origin were absent from `.next/static` JavaScript. This verifies the tested browser-bundle boundary, not arbitrary future environment names.

A separate local standalone build with `CROPTWIST_API_ORIGIN=http://127.0.0.1:3030` passed. Bun 1.3.4 initially served HTTP 500 because of a Next 16.4.6 CommonJS wrapper runtime error; production execution was corrected to **Node.js 22.x**, with `engines.node=22.x` and a Node Docker runner. Local Node was 22.23.4; Vercel officially supports this major. Bun remains the frozen installer/build-script launcher. Next itself is executed explicitly by Node 22 in both the build and runtime stages. A small packaging script preserves static/public files for default and isolated NEXT_DIST_DIR outputs.

## PostgreSQL, PostGIS and permissions

A fresh disposable loopback PostgreSQL cluster on port 5433 ran **PostgreSQL 16.15 / PostGIS 3.4.2**. In `croptwist_deploy_verify`, PostGIS was enabled in the dedicated `extensions` schema. The migration wrapper's full offline plan succeeded, approved-source/target local upgrade returned **0**, and a second identical upgrade returned **0**, a no-op. Applied head was `0023_p07_field_reports`.

The read-only probe confirmed `public,extensions` search path, installed PostGIS, SRID **4326**, a positive geography-based area, and the exact migration head. Initial migrated database size was **22,363,159 bytes** before fixture seed/data; this is a local empty-schema measurement, not a production capacity forecast or Supabase hosted measurement.

A separate disposable login with application DML, schema usage, spatial-reference read and no schema CREATE permission could seed the isolated fixture and run the full DB/PostGIS/readiness probe. Attempted `CREATE TABLE public.unapproved_ddl` returned **1 / permission denied for schema public**, as expected. No SQLAlchemy/Alembic/PostGIS feature was replaced.

**Deferred discrepancy preserved:** `alembic check` against the migrated dedicated-schema database returned **255**, reporting existing model/migration drift, including proposed removals. Every file under `mini-services/fieldshift-api/migrations/` and the existing `.github/workflows/ci.yml` remains unchanged. Readiness checks revision-head parity, not metadata autogeneration parity; a successful readiness response does not clear this release blocker.

## Backend tests

The new deployment-readiness module passed **12 tests** without the integration conftest, covering hosted TLS/CA requirements, exact CORS, trusted hosts, safe connection arguments, readiness/head failures, and sensitive-error non-leakage.

Database-free units ran with the PostGIS-backed `test_geospatial_rendering.py` module excluded from the no-database invocation: **936 passed**, 2,218 warnings, 13.22 seconds. This is not the full backend suite. The excluded rendering module was run with real PostGIS in the integration slice below, not silently discarded.

A real PostGIS integration slice of auth tenant isolation, auth hardening, background jobs and geospatial rendering passed **43 tests**, 14 warnings, 113.12 seconds. It used original local pool defaults 5/5; hosted templates explicitly use 2/0. The local defaults were preserved after a preliminary small-pool full-suite run showed long sensitivity transactions and subsequent TRUNCATE lock waits.

The attempted full `pytest tests -q` run was **interrupted with exit 130** after failures and setup errors at roughly 8% progress; it produced no complete suite summary. A preliminary unit invocation with the DB conftest removed but the DB-dependent renderer still included returned 1 for missing `db` fixtures; the corrected database-free units and separately DB-backed renderer slice passed as described. These attempts are not a green full-suite/CI result and do not justify suppressing existing gates.

## Local HTTP/session/locale checks

`deployment/scripts/smoke.py` is restricted to loopback and uses only the isolated seeded fixture. With Node standalone frontend and the least-privileged local API it verifies HTTP 200 for `/`, proxied liveness and proxied DB/PostGIS readiness; a 401 before login; token-free login JSON with HttpOnly cookies; authenticated `/api/v1/me`; refresh-cookie rotation; logout and 401 afterward; Secure/HttpOnly attributes for an HTTPS-forwarded request; Arabic `lang=ar dir=rtl`; and a served Next static asset. It is not a hosted health check or a responsive redesign audit.

The initial smoke script referenced `/api/v1/auth/me`, which is not the application's endpoint and returned 404; the script was corrected to the existing `/api/v1/me` without changing application auth routes. Final smoke passed, including a second run against the actual built frontend Docker image on loopback port 3001 (exit 0); the image runs non-root Node and reaches the genuine least-privileged local API.

## Configuration and images

Both `docker compose config --quiet` for the legacy root topology and `docker compose -f deployment/docker-compose.yml config --quiet` passed. Root Compose now supplies the internal API origin explicitly, preserving connectivity after removal of the sandbox-only browser port query. Eight pure deployment guardrail tests passed, including Node image settings and an actual isolated static-packaging fixture. Python compile and `git diff --check` passed. The Vercel Git gate is `{"*": false}`; Render candidate automatic deployment is off and compute is explicitly Free.

Initial Docker builds without networking failed dependency DNS/socket access; this sandbox's test Docker daemon has no bridge network. Retrying with `--network host` is the bounded local validation path. API, worker and final Node-based frontend images all built successfully (exit 0). The first network-enabled frontend image attempt exposed the same Bun-only Next page-collection failure; the final builder now supplies Node 22 and invokes the Next CLI explicitly with Node. Worker image CLI `python -m app.worker --help` returned 0 without starting processing. No image was pushed to a registry or deployed to a provider. Full Compose runtime is not claimed verified here.

## Owner-only remaining evidence

Actual Supabase hosted PostgreSQL/PostGIS versions, extension permissions, CA/TLS session, pooler connectivity, free account quotas and security settings remain unverified. Vercel/Render account eligibility and project settings were not applied. Commercial use is not eligible for Vercel Hobby without a provider determination. Durable private raster/report storage, safe continuous worker/scheduler ownership, capacity on a 512 MB candidate, recovery, deferred Alembic parity, final redesigned Arabic/RTL/responsive UI and real staging/production deployment health remain release gates. See [STAGING_GUIDE.md](STAGING_GUIDE.md), [FREE_TIER_LIMITS.md](FREE_TIER_LIMITS.md) and [ROLLBACK.md](ROLLBACK.md).

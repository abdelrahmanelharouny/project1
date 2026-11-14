# CropTwist deployment architecture

This branch prepares the existing application for **Vercel Next.js + Supabase PostgreSQL/PostGIS**. It does not deploy a service, change authentication providers, replace PostGIS, merge active feature branches, or modify the deferred Alembic discrepancy. The exact base is `998f7a5885e4ee0c9defe28671736560fb1b8762` on `origin/main`; delivery uses `feature/croptwist-free-deployment` in a separate worktree.

## Frontend and API contract

The repository root is the Next.js App Router project. Vercel builds it with its native Next.js integration, using Bun 1.3.4 for installation/build and Node.js 22.x for production execution. Browser requests retain the existing `/api/v1` contract; a validated server-side API origin determines the external rewrite. Keep database credentials, provider credentials and storage keys exclusively on the backend. Do not add `NEXT_PUBLIC_` versions of secrets. Existing token refresh, session revocation, organization membership, field authorization and locale behavior remain the application's responsibility.

Production Git deployments stay disabled while the UI redesign is active. Preview deployment is also opt-in and must use a dedicated staging API/database, not live tenant data. The redesign workstream can integrate this infrastructure contract without changing its design or waiting for unrelated GIS/CI work. See [Vercel setup](VERCEL_SETUP.md) and [frontend contract](FRONTEND_CONTRACT.md).

## Hosted data plane

Supabase hosts relational and spatial data. PostGIS must be installed in `extensions` on a fresh project before the existing first migration creates geometry columns. A configured `public,extensions` search path preserves unqualified GeoAlchemy geometry and spatial functions without replacing them. Session pooling on port 5432 is the IPv4-compatible initial API choice; transaction pooling is not approved because the existing code relies on session configuration. Migration and backup credentials are separate from the least-privileged application role. The application never connects to PostgreSQL from the browser.

Disable Supabase's generated Data API before creating CropTwist tables. The current application's tenant controls are in FastAPI and must not be bypassed by accidentally exposed `public` tables without matching RLS. Supabase Auth is evaluated, not substituted. Private storage is evaluated, not silently made public; existing filesystem report behavior is an explicit hosted-release blocker. See [Supabase setup](SUPABASE_SETUP.md) and [authentication, storage and workers](AUTH_STORAGE_WORKERS.md).

## API and compute plane

FastAPI remains a Python modular monolith, with the existing `app.worker` process and maintenance scheduler. Neither Vercel functions nor Supabase Edge Functions replace Python processing. Existing workloads include ingestion, satellite discovery, raster preprocessing, spatial calculations and report rendering; they require real completion and preserved provenance.

Render Free is the smallest documented no-subscription API **staging candidate**, not a verified deployment or production recommendation. Its 512 MB ephemeral, restartable instance is not safe durable storage or continuous worker hosting. The candidate blueprint has no paid resources and automatic deployment is off. It must not be applied until the storage, session/proxy, lifecycle and capacity gates in [staging guide](STAGING_GUIDE.md) pass.

Full-function $0 operation requires an owner-provided adequate existing host for durable files and Python processing. If no such host exists, worker/satellite/report staging remains blocked. This is a disclosed limitation, not a degraded implementation presented as successful processing. See [confirmed free-tier limits](FREE_TIER_LIMITS.md).

## Local reproducibility and changes

`deployment/docker-compose.yml` is an additional isolated local stack with PostgreSQL/PostGIS, an explicit one-shot local migration service, API and frontend. Host ports bind loopback; named volumes retain local report/raster files. The legacy root Compose/Caddy topology is retained, with an explicit `http://api:3030` build/runtime origin so relative browser requests still reach FastAPI. Container startup does not run migrations against Supabase; remote schema operations require a separately reviewed plan and explicit owner approval.

The existing worker is not advertised as independently scalable until its discovery/ownership defects are resolved. Local default uses the application's existing in-process workers and scheduler. Backend logs remain structured stdout with correlation IDs and exclude secrets; liveness and readiness are distinct. No telemetry vendor or paid monitoring is provisioned. See [rollback](ROLLBACK.md) for version pinning and non-destructive recovery.

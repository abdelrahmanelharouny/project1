# CropTwist Railway evaluation deployment

The owner approved Railway as the replacement for Render on 2026-11-14. The frontend remains the existing Next.js App Router application on Vercel Hobby for a personal, non-commercial evaluation. The database is isolated Neon Free PostgreSQL/PostGIS; no paid database, disk, worker tier, payment method, or subscription is authorized.

## Real runtime topology

The API runs `uvicorn app.main:app`, listens on Railway's `PORT`, and uses `/api/v1/health/ready` for deployment readiness. It has `CROPTWIST_JOB_WORKERS=0` and `CROPTWIST_JOB_QUEUE_ONLY=true`, so supported heavy ingestion, raster and report work is submitted durably rather than executed inline. The separate service runs `python -m app.worker --workers 1`, enables the existing scheduler, and consumes the same PostgreSQL queue. Each service is capped at one shared vCPU, one GB RAM and one replica. Queue-only mode does not invent an async implementation for report regeneration; that specific inline endpoint returns an explicit validation error.

Workers recover durable queued/replayable jobs. Domain and background-job fencing protects ownership; scheduler tasks use PostgreSQL session-level advisory locks. Railway's API healthcheck uses `healthcheck.railway.app`, which is included in the explicit trusted-host allowlist. Readiness checks database connectivity, PostGIS and exact Alembic head parity, without running migrations at startup.

## Persistence and connection mode

Small private raster and report artifacts use the PostgreSQL artifact adapter, not ephemeral container paths. The evaluation configuration caps a single artifact at 8 MB and all artifact rows at 128 MB, leaving headroom within Neon Free. Checksums, tenant-scoped access, retention and bounded budgets remain enforced. This adapter is appropriate for a small evaluation, not large satellite archives; production-scale rasters require an appropriate durable object store.

Use the confirmed direct Neon endpoint with SQLAlchemy's bounded client-side connection pool, `verify-full` and the system CA bundle. Do not use Neon's transaction-pooled endpoint for the current session-level ownership/scheduler locks or libpq startup `search_path` policy. Database credentials belong only in provider secrets. The application role has table DML, sequence usage and migration-version reads, but cannot create objects in `public`. Migrations use a separate owner connection and the same validated TLS arguments.

## Honest evaluation boundaries

`CROPTWIST_ENVIRONMENT=staging` is intentional: the application refuses production startup because a production billing adapter is not implemented. Development endpoints remain off. Existing application Free-plan entitlements and quotas are preserved; no subscription is fabricated to unlock features. An isolated synthetic workspace uses existing non-admin authentication. The public demo handler rejects administrator roles, mixed tenants and mismatched identities, and never returns its server-side password or access/refresh tokens in JSON.

Compromised old LLM credentials are not used. External LLM transport is disabled until fresh credentials are safely configured and authenticated probes succeed; deterministic engine/rules behavior remains available. Protected HLS acquisition, SMTP delivery and paid business features must not be represented as verified merely because their source is integrated.

## Cost and 24-hour operation

Railway's verified cardless trial has a one-time $5 credit and reverts to Free when consumed or expired. Actual credit, verification and the absence of a payment method were checked before provisioning. Railway rejects workspace hard caps below $10 except $0, which would stop all compute, so no larger cap or paid plan was enabled. Trial credit exhaustion is the provider-enforced boundary; monitor real usage during the authorized evaluation. The 24-hour target is not an uptime guarantee. Do not send artificial keep-alive traffic.

A legitimate always-running dispatcher polls the database, so Neon may not scale to zero while it is active. After the demo, stop both Railway services; retain the Neon data unless the owner separately authorizes deletion. Do not automatically delete data, unsubscribe anything, or rewrite Git history.

# Staging guide and owner release gates

**Prepared locally, not deployed.** The UI redesign proceeds independently. No provider credentials were requested, no paid resource was activated, and no live health check is claimed. Use the isolated deployment branch; do not merge active GIS, AI, CI or redesign branches implicitly.

## Local reproducibility

The additional deployment Compose topology is loopback-only and retains local state in named volumes:

```bash
docker compose -f deployment/docker-compose.yml config --quiet
docker compose -f deployment/docker-compose.yml up --build
```

This is local development, not a hosted production manifest. Its one-shot `migrate` service uses a dedicated local database; it must never be retargeted at Supabase. The API uses existing integrated job workers/scheduler so current behavior remains observable. Persistent paths are `/data/rasters` and `/data/reports`. The web build embeds `http://api:3030` for its internal rewrite; it does not expect a browser to resolve the Compose hostname.

To stop, use `docker compose -f deployment/docker-compose.yml down` without `-v` if retaining test state. Removing volumes is destructive local cleanup; do not reuse that command with production data. See [VERIFICATION.md](VERIFICATION.md) for exact executed tests and container-build limitations.

## Supabase stage

Follow [SUPABASE_SETUP.md](SUPABASE_SETUP.md): Free plan, Data API disabled, PostGIS preinstalled in `extensions`, isolated runtime role, verified TLS/CA and session pooler. Capture real hosted versions/permissions and a reviewed migration plan. Remote mutation must wait for explicit owner approval and recovery proof. Do not suppress the deferred Alembic drift to obtain a green release gate.

## API hosting decision

`deployment/render.yaml` is a **candidate**, not an immediately safe service declaration. It requests only `plan: free` web compute and disables automatic deployment. Do not apply it until all of these gates pass:

1. The owner confirms a cardless $0 Hobby workspace with no paid services, automatic upgrades, trials or billable custom domains. If payment details or a paid account are mandatory, stop.
2. Representative API startup and request memory fit in 512 MB, and cold-start/restart behavior is accepted for an isolated staging workload.
3. Private report and raster files survive restart/redeploy through a proven durable adapter or approved existing-host storage. Current local file paths on Render fail this gate.
4. Processing/scheduler ownership is proven. `job_workers=0` is not offloading; standalone workers do not continuously discover later API jobs, and existing startup recovery is not a multiprocess lease protocol.
5. Real session-pooler, PostGIS, migrations, authentication, cross-tenant denials, HTTPS cookies, CORS/Host allowlists and private asset access pass. Supabase's generated Data API remains disabled.

The current full workload fails the durable-storage and independent-worker gates. Do not deploy an apparently complete UI against that candidate and advertise processing as available. Do not start a paid worker/cron/disk, an external artificial keep-alive, or move business logic into Vercel functions.

## Existing host path for Python processing

An adequate **owner-provided existing** always-on machine can run the existing backend image with persistent files and Supabase as the database without purchasing hosting. This task did not connect to, configure, or promise availability of such a host. Keep exactly one API ownership process with integrated worker/scheduler until shared dispatch/atomic claims are fixed. Use TLS ingress and explicit allowed hosts, restrict trusted forwarded headers to the known ingress, mount the Supabase CA and durable private files, and apply migrations only through the separate approved operator step.

The backend Dockerfile provides a `worker` target running `python -m app.worker --workers 1`. It packages the genuine existing ingestion/raster/report implementation, but is **not safe concurrent distributed dispatch** merely because an image exists. Build it only for controlled recovery/drain tests or after the documented dispatch/ownership fixes. Never run the worker alongside a live API against the same jobs without those fixes. The default image stays the API; neither image runs Alembic at startup.

## Frontend isolated preview

Vercel Hobby eligibility applies to previews too. Confirm personal/non-commercial eligibility or obtain a written provider determination; commercial CropTwist remains blocked under the selected $0 plan. Keep `git.deploymentEnabled: {"*": false}`. An intentionally isolated CLI preview may be created only after the owner-approved eligibility/API stage gates; never pass `--prod` in this phase. Use Preview-only origin/credentials and deployment protection; protect staging tenant data even if the preview URL leaks.

Use [VERCEL_SETUP.md](VERCEL_SETUP.md) for root/build settings. Check live API readiness, login, token refresh rotation, logout/revocation, cross-tenant fields/reports, and private downloads from that preview. Update only the exact CORS origin if needed; no wildcard `*.vercel.app`. Do not promote a preview automatically.

## Redesign handoff and final promotion

When the redesign branch is ready, integrate on an explicitly authorized integration branch—not `main` by this task. Preserve the relative API and server session contract in [FRONTEND_CONTRACT.md](FRONTEND_CONTRACT.md). Run the production build, direct preview-to-API connectivity, authentication/refresh/logout, English and Arabic catalog parity, Arabic RTL layout, mobile/tablet/desktop responsive checks, map/raster overlays and report downloads against the real stage.

Production requires explicit UI readiness and owner promotion, Vercel plan eligibility, real Supabase compatibility/permissions, approved migrations, durable files/recovery, safe processing runtime, capacity evidence and existing CI gates. A build passing locally is not final staging readiness. Only declare a service live after an actual deployment and real liveness/readiness checks succeed.

## Logs and monitoring

Use existing structured API stdout and request correlation IDs; avoid DSNs, token material, signed URLs and tenant payloads. Liveness is `/api/v1/health`; DB/PostGIS/Alembic-head readiness is `/api/v1/health/ready`. Readiness does not prove Alembic metadata autogeneration parity or worker readiness.

Before public use, observe queued-job age, processing failures, scheduler last-run age, missing artifacts, database/file size, egress and build usage in the respective dashboards. Worker heartbeat/lease instrumentation is a remaining application change, not implemented by this task. Free log retention is short; securely export operational evidence without introducing a paid logging service. No recurring monitor was configured.

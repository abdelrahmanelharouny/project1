# Deployment workstream outcomes

## Delivered locally

- [x] Inspect latest remote branches first; isolate `feature/croptwist-free-deployment` from exact main base `998f7a5885e4ee0c9defe28671736560fb1b8762`; preserve main and active workstreams.
- [x] Prepare root Next.js Vercel configuration, frozen Bun toolchain, API origin validation, same-origin auth/API contract, assets and standalone image; do not publish the final UI.
- [x] Keep all Vercel Git branch deployments disabled by default and document intentional isolated preview gates and production promotion after redesign.
- [x] Add PostgreSQL SSL, bounded pooling, dedicated extension search path, trusted-host/CORS configuration and read-only PostGIS/Alembic-head readiness; never expose server credentials to browser bundles.
- [x] Keep all existing PostGIS features and all migration/Alembic environment files unchanged; document the deferred discrepancy rather than suppress it.
- [x] Provide safe plan/probe/approved-upgrade tooling, Docker images, isolated local Compose, a no-auto-deploy Free API candidate, deployment-check workflow, logs/health guidance, environment templates and rollback documentation.
- [x] Evaluate Supabase Auth against existing organization, role, field and session ownership; retain current authentication and document a verified-identity adapter plan only.
- [x] Evaluate private Supabase Storage for satellite/raster/user/report files. Defer an adapter that cannot yet preserve the existing 512 MiB raster contract and local report-path semantics; never make private files public or transform scientific assets to fit a quota.
- [x] Verify and record current official free allowances, Vercel non-commercial restrictions, Supabase pause/backup/size limits, Render ephemeral/cold-start constraints and absence of free continuous worker hosting; do not activate billing, trials or paid resources.

## Owner / integration release gates still open

- [ ] Confirm Vercel Hobby eligibility for CropTwist; commercial usage cannot be certified under the selected $0 plan. Do not activate a paid plan as a workaround.
- [ ] Provision eligible Free Supabase staging, disable generated Data API, enable PostGIS in `extensions`, create least-privileged runtime login, mount dashboard CA and record real hosted version/permission/pooler/TLS evidence.
- [ ] Approve exact remote migration target/source fingerprint and impact only after backup/restore verification and the separate deferred Alembic drift workstream is resolved. Never run destructive remote operations without explicit approval.
- [ ] Provide adequate existing no-new-subscription Python compute/durable storage, or leave processing blocked. Prove real continuous job discovery, atomic ownership/recovery and scheduler behavior before distributed workers or multiple API replicas.
- [ ] Resolve durable private raster/report storage and measure real asset sizes before Render Free or Supabase Storage activation. Test authorized signed/streamed downloads, restart retention and independent object recovery.
- [ ] Verify actual provider deployment and real health checks before calling any service live. The candidate blueprint and successful builds are not deployment evidence.
- [ ] Integrate the completed redesign on an owner-authorized branch; verify API/session behavior, Arabic/RTL, English, responsive views, maps/private files and all CI gates; explicitly promote only then.

Exact local results and limitations are in [VERIFICATION.md](VERIFICATION.md). No unresolved owner gate is implied complete by this checklist.

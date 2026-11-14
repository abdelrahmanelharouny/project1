# Rollback and recovery

No remote deployment or migration was performed by this task. Keep `main` and all active workstreams intact. Deployment changes are isolated to `feature/croptwist-free-deployment`; do not force-push, reset another worktree, or automatically merge this branch.

## Application rollback

Record frontend deployment ID/commit, API image digest/commit, migration plan digest, current Alembic head, and storage manifest before each staging rollout. Promote only a matched frontend/API contract. If a rollout fails, stop new job intake first; retain database job rows and current asset files. Use Vercel's prior verified deployment only after checking schema/API compatibility. An isolated preview can be deleted without promoting anything to production.

Render Free supports rollback only to its two most recent previous deployments. Keep the previous known-good source and image version outside that short retention window. Do not assume rolling back application code also rolls back the database. A provider UI's success banner is insufficient: verify `/api/v1/health`, `/api/v1/health/ready`, authenticated session refresh/revocation, tenant isolation and private downloads afterward. [1]

## Database rollback

**Do not run `alembic downgrade`, `DROP`, `TRUNCATE`, extension relocation, `pg_restore --clean`, or an in-place restore against Supabase without an explicit owner-approved destructive recovery plan.** Several historical downgrades delete application data. This task leaves every migration and Alembic autogeneration rule unchanged.

Before any approved upgrade, create an encrypted off-site logical dump using a PostgreSQL client at least as new as the hosted server. Include schema, data, role/grant inventory and a checksum. Back up storage objects separately: Supabase database backups contain only storage metadata, not object bytes. Free lacks included automatic backups and PITR. A fresh local database is the preferred restore verification target; a second eligible Free project can serve as staging if the owner's two-project allowance permits it. [2]

Prefer forward repair after review. If restore is required, first restore into a **new disposable target**, verify spatial functions, geometry/SRID, tenant counts, auth/session mappings, job lineage and object checksums, then obtain owner approval for cutover and its data-loss window. Never restore over production merely because local tests passed. Keep the old target intact until the owner confirms recovery.

## Files and workers

Database rollback cannot restore deleted report/raster files. Keep an encrypted object manifest with bucket/key or local path, byte size, checksum, ownership and associated DB record ID. Signed URLs are temporary access capabilities, not backups. Drain one worker ownership domain at a time; do not start multiple replicas with the current globally scoped orphan recovery. Document already-running and failed jobs rather than relabeling them successful.

## Secrets and monitoring

If a credential leaked, revoke/rotate it at its issuer, update only the appropriate environment, restart the affected service and verify authentication. Do not paste the old/new value into logs, issues, commits or browser-public environment variables. Restore previous configuration only when its credential remains valid and uncompromised.

Use provider dashboards and on-demand authenticated checks. A recurring external keep-alive that defeats a Free plan's inactivity policy is not a supported availability strategy. Treat Free-plan pauses, quota exhaustion and cold starts as expected outages, not healthy production operation.

## References

[1]: https://render.com/docs/free "Render Free Service Rollback and Limitations"
[2]: https://supabase.com/docs/guides/platform/backups "Supabase Database Backup and Recovery"

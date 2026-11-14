# Auth, storage, and worker deployment compatibility plan

**Audit basis:** repository revision `main` at `998f7a5`; official provider limits verified on 2026-11-14. This is a compatibility and release-gate document, not an implementation change.

## Recommended decision

Do **not** replace the application’s authentication, session ownership, or tenant/field authorization with Supabase Auth or Supabase Storage policies. Keep the existing application principal and authorization model as the security authority. Supabase Auth may be evaluated later as an identity-token issuer, but only behind an adapter that resolves the token to the existing `User` and `Membership` records and then runs the existing organization, role, farm, and field checks.

Defer a Supabase Storage adapter until its size, range-read, signed-access, report-download, deletion, and recovery behavior is proven against real artifacts. The current local report directory and raster object store are functional state, not disposable caches. A free Render web service is therefore **not a release target for the current feature set** until durable external storage is wired and tested. A free Render API can be considered only as a small preview/API candidate, with the worker and scheduler explicitly blocked pending an approved existing-host runtime.

## Existing security and tenant contract

The current API uses opaque, database-backed access tokens. `get_principal()` accepts either `Authorization: Bearer` or the `fs_token` HttpOnly cookie, hashes the token, checks the `auth_tokens` row for kind, expiry, and revocation, checks that the user is active, loads all memberships, and returns a `Principal` (`mini-services/fieldshift-api/app/domains/identity/service.py:157-194`). The browser refresh token is handled by the Next.js auth route layer and is not read by the backend (`.../identity/service.py:51-54`). Password hashing, opaque token generation, and token hashing are application primitives (`.../core/security.py:1-59`).

`Principal` is not merely an authenticated user ID. It carries active organization memberships and implements `require_member_of`, `require_org_role`, `require_owner`, and organization enumeration (`.../identity/service.py:92-153`). The role set is application-specific—`viewer`, `analyst`, `agronomist`, `operator`, `manager`, `org_admin`, and `owner`—with `org_admin` deliberately sharing an administrative rank but not passing exact-owner gates (`.../identity/service.py:56-71,121-141`). Resource lookups also resolve the farm/field first and then enforce membership; for example, data-job creation calls `get_field_for_principal` before creating a job (`.../api/v1/data_platform.py:120-165`).

The existing tests establish the contract that must remain true after any provider change: invalid/revoked sessions are rejected, refresh-token reuse is rejected, account lockout and auth rate limiting work, roles are enforced, and another tenant cannot read a field or its observations (`.../tests/integration/test_auth_tenant_isolation.py:6-112`, `.../tests/integration/test_auth_hardening.py:60-340`). Background-job visibility also returns a foreign job as indistinguishable from an unknown job (`.../api/v1/jobs.py:57-80,105-129`).

### Supabase Auth evaluation without replacement

Supabase Auth issues short-lived JWT access tokens containing a stable user subject (`sub`), issuer, expiry, and role claims; Supabase documents JWT verification through its signing keys/JWKS and recommends a high-quality verification library rather than hand-written cryptography [1]. This can supply identity, but it does not model CropTwist’s seven application roles, organization memberships, farm scope, report ownership, or field authorization. A Supabase `authenticated` claim must never be treated as equivalent to CropTwist membership or role authorization.

If evaluated, the safe compatibility path is:

1. Add a token-verification adapter at the credential-resolution boundary. It should accept a Supabase JWT in the bearer transport, validate signature, issuer, audience, expiry, algorithm, key ID, and key rotation, and produce only a verified external subject.
2. Map the verified `sub` to the existing `users.id` through an explicit immutable external-identity mapping. Do not match users by mutable email alone, and do not auto-create a tenant or membership as a side effect of seeing a valid JWT.
3. Construct the existing `Principal` from the application database and leave `require_member_of`, `require_org_role`, `require_owner`, `get_farm_for_principal`, and `get_field_for_principal` unchanged. The API’s database remains the authority for disabled accounts, active membership, seven-role RBAC, organization selection, audit actor IDs, and field ownership.
4. Keep the existing `fs_token`/refresh path during migration. Support both credential types for a bounded migration period, with explicit precedence and separate audit events. Do not silently convert a Supabase session into an application session without preserving logout, revocation, expiry, and account-disable semantics.
5. Keep browser cookies HttpOnly and server-controlled. Do not put a Supabase secret/service key in browser code. If the Supabase client is used in the browser, it may hold only the publishable client key and a user session; it must not be trusted for domain authorization.

This is an identity adapter, not an authorization replacement. Supabase Auth is therefore **compatible in principle**, but the migration is not safe to approve until the mapping, session lifecycle, email-verification policy, disabled-user behavior, refresh/logout behavior, key rotation, and tenant regression tests below pass.

## Existing storage contracts and Supabase Storage fit

Raster storage already has a deliberately small abstraction: `put_bytes`, `exists`, `stat`, `read_bytes`, `delete`, and `signed_url` (`mini-services/fieldshift-api/app/geospatial/objectstore.py:181-197`). The factory currently supports only `local` and `s3` (`.../objectstore.py:396-417`). The local backend uses atomic writes under a configured root and is explicitly marked non-production; the S3 backend uses private objects and presigned GETs (`.../objectstore.py:199-207,271-358`). Both backends validate GeoTIFF/PNG magic bytes, checksum, and a hard **512 MiB** object cap (`.../objectstore.py:51-55,148-178`).

Keys are tenant-isolated at the storage layer: `org/{org}/field/{field}/source|derived|preview/...`; path traversal and key injection are rejected, source and derived namespaces are separate, and overwrite requires an explicit flag (`.../objectstore.py:96-145,199-237`). `RasterAsset` stores only the external storage reference, backend, key, size, checksum, CRS, and quality metadata; binary content is outside PostgreSQL (`mini-services/fieldshift-api/app/db/models_p2.py:600-685`). Raster rendering reads through the abstraction and keeps object-store credentials and signed URLs away from the browser (`.../geospatial/rendering.py:1-24,155-180`).

Supabase Storage can represent the same private-object model. Private buckets are subject to RLS for operations and downloads, while a server can issue a time-limited signed URL; public buckets bypass retrieval access control and are unsuitable for tenant data [2] [8]. The adapter path would be:

- Implement `SupabaseStorage(RasterStorage)` against the Supabase Storage server API/SDK. Map the existing validated key directly to a private bucket object path. Compute and validate the SHA-256 before upload, preserve content type and byte size, and use object metadata or the existing `raster_assets` row as the integrity record.
- Implement `put_bytes`, `exists`, `stat`, `read_bytes`, and `delete` with the same no-overwrite and not-found semantics. `read_bytes` matters because the current raster renderer loads the stored object into a bounded in-process cache (`.../geospatial/rendering.py:155-180`); a future range-read optimization must preserve the same output and checksum behavior rather than silently changing processing semantics.
- Implement `signed_url` with a short TTL and issue it only after the API has authorized the requesting principal against the field/report row. Prefer the API’s existing authorization gate followed by a server-side signed URL. Do not expose a Supabase service key to the browser, and do not rely on a bucket policy alone to implement CropTwist’s organization/role/field rules.
- Extend backend selection and the persisted backend vocabulary deliberately. The current model allows `local` and `s3` (`.../db/models_p2.py:600-602`), and the settings/factory allow only those values (`.../core/config.py:119-135`, `.../geospatial/objectstore.py:400-410`). Adding `supabase` requires a migration or an explicitly documented canonical backend value, configuration validation, deployment secrets, and a backfill/verification strategy for existing `RasterAsset` rows.

Reports are a separate compatibility problem. Report generation writes bytes directly to `Path(settings.reports_dir)/{job_id}.{format}` (`mini-services/fieldshift-api/app/reports/service.py:246-339`), stores the resulting host path in `report_jobs.file_path`, and downloads by opening that path after the report authorization check (`.../api/v1/reports.py:171-196`). There is no report-storage protocol today. A Supabase rollout must first introduce a report artifact abstraction or a storage-key migration: write to an object key, store the key rather than a host path, stream or sign the private object after `get_report_job` authorization, and preserve delete, regenerate, retention, and expiry behavior. Raster adapter work alone does not make report downloads durable.

### Supabase Free-plan constraints

As of the audit date, Supabase’s Free plan includes **1 GB file storage**, **5 GB cached egress**, and **5 GB egress**, with a **50 MB maximum file upload size** [3]. Supabase’s file-limit documentation confirms that Free projects cannot raise the global limit above 50 MB [4]. Therefore the current 512 MiB raster contract cannot be assumed to fit on Free. Do not downsample, split, or reject production rasters silently merely to fit a provider quota. A real artifact-size distribution and a compatible no-charge storage decision are required before enabling the adapter; this task forbids a paid-plan workaround.

The Free plan also does not include automatic database backups, and Supabase states that database backups do **not** include Storage API objects; backups contain object metadata, not the files themselves [3] [7]. A release using Supabase Storage must have an independent object backup/export and restore procedure, with checksums and a tested mapping between database rows and bucket objects. Treat the 1 GB quota as a hard operational budget, not as durable backup capacity.

## Worker, scheduler, and ownership findings

### The API worker is process-local

`app.core.jobs` uses a Python `queue.Queue`, daemon threads, and an in-process callable registry. It persists a `BackgroundJob` row first, then places the ID on that process’s queue (`mini-services/fieldshift-api/app/core/jobs.py:8-15,49-92`). The database row is the source of truth, but the live dispatch queue and pending callable are not shared across processes. The module itself says that multi-replica deployments need a shared store/broker (`.../core/jobs.py:27-29`).

The API lifespan starts this in-process pool and the maintenance scheduler (`mini-services/fieldshift-api/app/main.py:19-58`). This means API-created ingestion jobs are processed by the API process when `CROPTWIST_JOB_WORKERS > 0`; they are not automatically delivered to a separately deployed worker process.

### The standalone worker does not continuously discover jobs

`python -m app.worker` starts a local worker pool and then waits. It does not poll the database for new queued rows after startup (`mini-services/fieldshift-api/app/worker.py:85-121`). Recovery is a one-time startup action in `start_workers()`: it scans queued rows, re-enqueues only kinds present in the current process’s replay registry, and marks every `running` row as `failed` with `interrupted by restart` (`.../core/jobs.py:107-174`). Consequently:

- A worker started before a later API submission will not discover that new row. A separate process needs a shared broker, a recurring DB poll/claim loop, or a deliberate restart/recovery cycle.
- The standalone worker eagerly registers `raster_processing` and `report_generation`, but not `ingestion` (`.../worker.py:71-85`). The ingestion replay executor registers lazily on the first API-side `submit_ingestion_job` call (`.../data_platform/ingestion/service.py:257-332`). Thus a standalone worker cannot be relied upon to recover pre-existing queued ingestion jobs at its startup.
- Provider registry construction is lazy: `get_provider_registry()` initializes the in-process registry on first use (`.../data_platform/registry/provider_registry.py:254-262`). It is not a continuously running discovery service. Ingestion itself creates a durable row, and the API endpoint either executes it inline or submits it to the local pool (`.../data_platform/ingestion/service.py:188-254`; `.../api/v1/data_platform.py:147-165`).
- Report generation has a replayable worker kind, but the normal report API path does not submit a `BackgroundJob`; the scheduler scans `report_jobs` and runs queued reports directly every 15 seconds (`.../reports/worker.py:92-109`; `.../core/scheduler.py:82-106`). The standalone report executor is useful only when `submit_report_job()` is explicitly wired into the request or another dispatcher.

### Scheduler ownership

The scheduler is an API-lifespan daemon thread, not part of `app.worker`. It runs six interval tasks for reports, webhooks, billing expiry, notification purge, report recurrence/retention, and activity pruning (`mini-services/fieldshift-api/app/core/scheduler.py:1-23,158-165`). It starts only when both `scheduler_enabled` and `job_workers > 0` (`.../scheduler.py:187-203`). The standalone worker does not run it.

Setting `CROPTWIST_JOB_WORKERS=0` is safe only as a deliberate synchronous/test mode, not as a complete asynchronous deployment mode. Ingestion falls back to inline request execution (`.../api/v1/data_platform.py:147-165`), which can block an HTTP request on provider/network/raster work. The scheduler is disabled, so queued reports, recurring reports, retention sweeps, webhook retries, billing expiry, notification purge, and activity pruning will not run (`.../core/scheduler.py:187-196`). Raster/report jobs that depend on the worker path can remain queued. Any deployment using zero workers must either disable those features explicitly or provide an independent dispatcher/scheduler.

### Mixed API/worker ownership and orphan recovery

The current recovery behavior is useful for a single process or a controlled restart, but it is not a multi-process lease protocol. Two API/worker processes can both scan the same queued row; the status check and transition to `running` are not documented or tested as an atomic cross-process claim. A process can also mark another live process’s `running` row as interrupted during startup. This can produce duplicate work, false interruption, or inconsistent domain and queue rows under concurrent API/worker ownership.

The existing tests prove single-process worker execution, replay of a registered queued kind, stale-running failure, API async ingestion, and tenant visibility (`mini-services/fieldshift-api/tests/integration/test_background_jobs.py:19-246`). They do not prove two independent processes, a worker started before submission, concurrent claims, a live worker restart, or mixed API/standalone ownership. Do not claim safe horizontal scaling until those cases are covered by atomic database claims/leases or a shared broker.

## Render deployment decision

A free Render web service is a reasonable **small API preview candidate**, not a validated production target. Render’s current pricing lists the Free web service at **512 MB RAM** [6]; workload capacity and raster/report memory behavior have not been validated in this repository. Render documents 750 free instance hours per workspace per month, spin-down after 15 minutes without inbound traffic, approximately one minute to spin back up, and loss of local filesystem changes on redeploy, restart, or spin-down [5]. Render also says free web services can be suspended for unusually high service-initiated public traffic, including external database or object-storage traffic, and do not support scaling beyond one instance, persistent disks, or one-off jobs [5].

The current implementation is incompatible with that filesystem model while local storage remains enabled. `raster_storage_backend` defaults to `local` and `raster_storage_root` points at a local directory (`mini-services/fieldshift-api/app/core/config.py:119-135`); reports default to a local `reports_dir` (`.../core/config.py:162-165`). A Render restart or spin-down can leave successful report rows whose `file_path` no longer exists and can remove raster assets required for map tiles and reprocessing. This is a release blocker, not a reason to remove reports or geospatial functionality.

Render’s service model distinguishes web services from continuously running background workers and scheduled cron jobs (`https://render.com/docs/service-types`). Free instances are offered only for selected service types; Render’s Free documentation states that other service types do not support Free instances and lists one-off jobs among unsupported free web-service features [5]. Therefore the free candidate cannot safely host the standalone worker or the scheduler. Paid Render background worker/cron services are outside this task’s authorization. Use an adequate owner-provided existing scheduler/worker runtime, or keep the API’s single-process worker only for a non-scaled preview after its queue limitations are accepted.

## Release gates and tests

### Gate A — auth compatibility

- Verify Supabase JWTs using JWKS/key rotation tests. Reject wrong issuer, audience, algorithm, key ID, expiry, malformed tokens, and revoked/disabled application users.
- Test immutable `sub` to existing-user mapping, duplicate/external-account conflict handling, email change behavior, email verification policy, logout, refresh, token expiry, and account lockout.
- Run the full existing auth hardening and tenant-isolation matrix with both credential transports. Cover two organizations, all seven roles, cross-tenant farms/fields, observations, reports, map tiles, background jobs, exports, and signed-object access.
- Prove that a valid Supabase token with `role=authenticated` cannot read or mutate another organization, cannot bypass exact-owner checks, and cannot create a membership implicitly.

### Gate B — storage compatibility

- Run the `RasterStorage` contract against local, current S3, and the candidate Supabase adapter: key validation, tenant namespace, magic-byte validation, checksum, 512 MiB-cap behavior, no-overwrite, stat/read/delete, missing objects, and signed URL expiry.
- Test representative real GeoTIFF, preview PNG, and report PDF/XLSX/CSV sizes against the selected Supabase plan. Explicitly test an object above Free’s 50 MB limit; the expected result must be a clear, documented capacity decision, never silent transformation.
- Add report-storage tests for create, queued execution, download, regenerate, delete, expiry/retention, restart/redeploy, and missing-object reconciliation. The database must store a provider-neutral object key, not a disposable host path.
- Test authorization before every signed URL or stream. A foreign organization must receive the established non-leaking 403/404 behavior and never obtain a public URL.
- Export and restore both PostgreSQL metadata and object bytes. Verify checksums, `RasterAsset` rows, report rows, and object keys after restore; do not treat database backup alone as an object backup.

### Gate C — worker and scheduler compatibility

- Start a standalone worker, then submit a new ingestion, raster, and report job from a separate API process; each must complete without restarting the worker. This currently exposes the process-local queue limitation and must fail before a shared dispatch path is added.
- Start the worker after queued rows exist and verify replay for ingestion, raster processing, and report generation. Register every replayable kind before recovery, including ingestion.
- Run two worker/API processes against the same database with the same queued row. Prove one atomic claim, no duplicate artifacts or observations, and consistent domain/background statuses. Add a lease/heartbeat or a shared broker if this cannot be proven.
- Test SIGTERM during queued, running, and completed work; verify graceful drain, queued recovery, stale-running policy, and reconciliation of domain rows such as `ingestion_jobs`, `raster_processing_jobs`, and `report_jobs`.
- Verify `job_workers=0` explicitly: ingestion’s synchronous behavior, queued-report behavior, scheduler status, recurring/retention behavior, and user-visible timeout/error semantics. Do not deploy this mode while async features appear enabled.
- Test one and two API replicas with scheduler enabled. Ensure report execution, recurring copies, retention, webhooks, and maintenance tasks cannot double-run or falsely interrupt live work.

### Gate D — Render release

Release the free Render API only when all of the following are true: database connectivity and migrations are external and durable; `local` raster storage is disabled; report artifacts use a durable external adapter; object/report restore has passed; worker and scheduler ownership is either explicitly out of scope or provided by an approved existing-host runtime; memory and cold-start tests pass on the 512 MB candidate; and monitoring detects missing artifacts, queued-job age, worker liveness, scheduler last-run age, storage quota, egress, and provider-suspension risk.

Until then, retain the current local storage only for development/demo Compose. The repository already states that production requires durable object storage, controlled workers, and a recovery plan (`README.md:46-56`; `.env.example:1-3`), and that persistent raster/report storage is a remaining operational requirement (`TODO.md:59-74`).

## References

[1]: https://supabase.com/docs/guides/auth/jwts "Supabase JSON Web Token documentation"

[2]: https://supabase.com/docs/guides/storage/buckets/fundamentals "Supabase Storage bucket access models"

[3]: https://supabase.com/pricing "Supabase pricing and plan limits"

[4]: https://supabase.com/docs/guides/storage/uploads/file-limits "Supabase Storage upload limits"

[5]: https://render.com/docs/free "Render free deployment documentation"

[6]: https://render.com/pricing "Render pricing and compute capacity"

[7]: https://supabase.com/docs/guides/platform/backups "Supabase database backups documentation"

[8]: https://supabase.com/docs/guides/storage/serving/downloads "Supabase Storage private downloads and signed URLs"

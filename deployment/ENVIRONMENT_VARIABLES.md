# Environment variables and secret ownership

Use [the deployment template](.env.example) as documentation, not as a working secret file. Copy selected values into the relevant provider's protected environment. Never copy real values into GitHub, issue text, generated browser JavaScript or this public repository. `.env*` files remain ignored except `.env.example` templates. Supabase service-role/publishable keys are not needed for the selected database-only integration.

## Next.js

`CROPTWIST_API_ORIGIN` is the backend HTTPS origin, without `/api/v1`, a path, query, fragment, credentials or trailing custom prefix. The server uses it for auth forwarding and the build uses it for the same-origin API rewrite. It is not a database DSN and must contain no secret. On Vercel it is required; local development retains the loopback default. Set it separately for Preview and Production. An origin change needs a frontend rebuild because rewrites are compiled into the deployment. Review [frontend contract](FRONTEND_CONTRACT.md) for sandbox-only port-query compatibility.

Do not define `NEXT_PUBLIC_DATABASE_URL`, `NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY`, or any other browser-public credential. Keep locale cookies/catalogs and existing server session behavior. Access and refresh cookies remain HttpOnly, HTTPS secure, host-only and SameSite Lax for the standalone Vercel site. Direct cross-site browser API authentication is not the selected architecture; `/api/auth` and `/api/v1` stay same-origin.

## Backend PostgreSQL

`CROPTWIST_DATABASE_URL` uses `postgresql+psycopg2://` and the exact session-pooler login/host from Supabase's Connect dialog. Custom pooler usernames use `croptwist_app.PROJECT_REF`; do not guess a region-derived pooler hostname. Percent-encode the password. Separate administrative migration login from the runtime application role. Never use transaction-pooler port 6543 for the initial deployment.

`CROPTWIST_DATABASE_SSLMODE=verify-full` and `CROPTWIST_DATABASE_SSLROOTCERT` point to the dashboard's CA certificate mounted on the runtime host. Require encryption in Supabase's dashboard too. `require` encrypts but does not authenticate the server; it is not the selected secure hosted setting. `CROPTWIST_DATABASE_SEARCH_PATH=public,extensions` retains unqualified spatial calls with PostGIS in its dedicated schema. The parser accepts only simple schema identifiers; it is not an arbitrary SQL configuration field.

Pool controls are `CROPTWIST_DATABASE_POOL_SIZE`, `...DATABASE_MAX_OVERFLOW`, `...DATABASE_POOL_TIMEOUT_SECONDS`, `...DATABASE_POOL_RECYCLE_SECONDS`, `...DATABASE_CONNECT_TIMEOUT_SECONDS` and `...DATABASE_HEALTH_TIMEOUT_SECONDS`. Hosted templates explicitly start with 2 connections, zero overflow and a single API process. Local defaults retain the legacy 5/5 pool to avoid changing existing test/demo concurrency; initial worker concurrency 1 is a capacity starting point, not proof of fit. The sum across all processes must leave room for platform connections and maintenance under the Free plan's published limits.

The migration wrapper applies the same TLS and search-path connection arguments without altering frozen Alembic files. Direct legacy `alembic` invocation does not apply new connection-argument settings; use the wrapper for hosted operations. Direct/session target access and CA trust must be tested using the intended role.

## Security and process ownership

`CROPTWIST_ENVIRONMENT=staging|production` enables hosted safety checks. `CROPTWIST_DEV_MODE=false` is mandatory. `CROPTWIST_TRUSTED_HOSTS` lists exact backend hostnames, no URL paths or scheme, and explicit loopback hostnames if health probes require them. `CROPTWIST_CORS_ALLOW_ORIGINS` is an explicit comma-separated set of approved HTTPS browser origins. Empty means no cross-origin CORS middleware; do not use `*` or broad `*.vercel.app` for credentialed traffic. Update the exact isolated preview origin deliberately and remove stale entries.

`CROPTWIST_BILLING_WEBHOOK_SECRET` and `CROPTWIST_RASTER_URL_SECRET` must be independently generated protected backend secrets. Do not activate payments or an external paid AI provider. Keep password hashing and auth rate limiting at existing safe values. Configure outbound verification/password-reset email through an authorized channel before onboarding users; Render Free's SMTP port restrictions mean existing SMTP assumptions cannot be taken for granted.

`CROPTWIST_JOB_WORKERS=0` invokes inline ingestion and disables the existing maintenance scheduler; it is **not** an offload switch. Keep one ownership process until shared job dispatch/atomic claims are implemented. `CROPTWIST_SCHEDULER_ENABLED` controls API-owned maintenance but does not provide an external scheduler.

## Persistent files and providers

`CROPTWIST_RASTER_STORAGE_BACKEND`, `...RASTER_STORAGE_ROOT` and `CROPTWIST_REPORTS_DIR` point to existing durable, access-controlled storage. The template's local paths are only for an owner-provided persistent host; they must not be used as retained storage on Render Free. The existing S3 backend is optional and requires its own reviewed compatibility/dependency plan; this task does not activate it or label Supabase's S3 compatibility as verified.

Satellite credentials such as `CROPTWIST_CDSE_PASSWORD`, `...EARTHDATA_PASSWORD` and `...EARTHDATA_BEARER_TOKEN` remain server-only. Missing credentials must continue producing honest provider-access errors rather than synthetic success. Do not reuse owner production credentials for local fixture tests.

## CI and environments

Local regression checks use a disposable loopback PostGIS database. The new deployment-check workflow needs no provider token and does not provision or deploy anything. GitHub Actions repository secrets are unnecessary for those checks. Supabase staging should be a separate eligible Free project if the owner's two-active-project allowance permits it; otherwise use a disposable local target, not a paid branch. Production values stay unset until eligibility, UI integration, storage, workers and migration approval are resolved.

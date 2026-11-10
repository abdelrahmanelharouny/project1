# CropTwist — Deployment Guide

How CropTwist runs in the development sandbox, under Docker Compose, and what a production rollout must satisfy. Companion documents: [`README.md`](../../README.md) (quickstart + configuration) and [`.env.example`](../../.env.example) (annotated settings).

## Run modes at a glance

| Mode | Database | API | Web | Use |
| --- | --- | --- | --- | --- |
| Sandbox (dev) | user-space PostgreSQL cluster, port `5433` | uvicorn `--reload` on `127.0.0.1:3030` | `next dev` on `:3000` | day-to-day development |
| Docker Compose | `postgis/postgis:16-3.5` container, published on host `5433` | container on `3030` (`dev_mode=false`) | standalone Next build on `:3000` | integration / demo |
| Production | managed PostgreSQL 16 + PostGIS 3.5 | uvicorn behind gateway / LB | Next standalone behind gateway + TLS | the real thing |

## 1. Sandbox layout (development)

Ports follow a fixed convention to avoid collisions with other services:

| Port | Service | Binding |
| --- | --- | --- |
| `5433` | PostgreSQL 16 + PostGIS 3.5 (user-space cluster) | `127.0.0.1` + unix socket `/tmp` |
| `3030` | CropTwist FastAPI (`app.main:app`) | `127.0.0.1` |
| `3000` | Next.js dev server | `0.0.0.0` (gateway-facing) |

Key facts:

- **User-space PostgreSQL.** The cluster lives at `/home/z/fieldshift-pg` (conda-forge/micromamba environment `pgenv`, data directory `pgdata`) and is started on demand with `pg_ctl` (listen `127.0.0.1`, socket dir `/tmp`, port `5433`), or via the repository-root convenience script `scripts/start-stack.sh pg` (idempotent: checks `pg_isready`, creates the data dir + `initdb` if missing, then ensures the `croptwist` database and PostGIS extension). `scripts/ensure_db.py` performs the same boot when invoked directly; its defaults read `CROPTWIST_DB_PGDATA` / `CROPTWIST_DB_PORT` / `CROPTWIST_DB_SOCKET_DIR`.
- **API venv.** `scripts/run_dev.py` (invoked by `bun run dev`) expects a virtualenv at `mini-services/fieldshift-api/.venv` containing `alembic` and `uvicorn`. It then runs `alembic upgrade head` and `exec`s uvicorn with the watchfiles reloader on port `3030`.
- **Daemon survival.** The sandbox reaps plain background processes, so long-lived processes are launched through `scripts/daemonize.py` (double-fork + `setsid`, std streams detached), e.g. `python3 scripts/daemonize.py sh -c 'exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3030 >> /home/z/my-project/fieldshift-api.log 2>&1'`. The repository-root script `scripts/start-stack.sh api|web` wraps exactly this pattern (health-check first, start only when down).
- **Watchdog cron.** Convention: a cron entry (every few minutes) checks `curl -fsS http://127.0.0.1:3030/api/v1/health/ready` and, on failure, re-launches via `daemonize.py`. Note (observed at authoring time): this sandbox exposes no `crontab`; if you need a watchdog here, use the platform's scheduler or a supervised launcher. Prefer Docker Compose or a real process manager wherever possible.
- **Gateway.** A Caddy gateway fronts `:3000`; API traffic uses relative URLs with `?XTransformPort=3030`. When hitting `:3000` directly (bypassing Caddy), `next.config.ts` rewrites `/api/v1/*` to `127.0.0.1:3030` — which only works when web and API share a host, as in the sandbox.
- **Dev mode.** The sandbox runs with `CROPTWIST_DEV_MODE=true`, enabling `POST /api/v1/dev/seed-demo` (demo account `demo@croptwist.local` / `croptwist-demo-2026`).

Observed state at authoring time (re-verified): the user-space PostgreSQL cluster (`/home/z/fieldshift-pg`) and the API venv (`/home/z/fieldshift-api-venv`) exist and are the live runtime the launcher script targets; the Next dev server runs from the repository root via the platform supervisor. `scripts/start-stack.sh all` brings any missing piece up.

## 2. Docker Compose path

Two compose files exist:

- **Repository root (`/home/z/my-project/docker-compose.yml`) — primary.** Builds the full stack: `db` (postgis/postgis:16-3.5 on host 5433), `api` (migrate + serve on 3030), `web` (Next standalone on 3000), and `gateway` (caddy:2 on 81 mounting the repo `Caddyfile`, host networking so its `localhost` upstreams reach the published ports). Healthchecks and restart policies throughout; overrides via the root `.env` (see `.env.example`).

```bash
docker compose up --build -d     # db → api (migrate + serve) → web
docker compose logs -f api
docker compose down              # add -v to drop the pgdata volume
```

- **`db`** — `postgis/postgis:16-3.5`, named volume `croptwist-pgdata`, `pg_isready` healthcheck, host port `5433` (mirrors the sandbox convention).
- **`api`** — image built from `Dockerfile` (python:3.12-slim, non-root user `croptwist`); waits for `db` to be healthy; command `sh -c "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 3030"`; `CROPTWIST_DATABASE_URL` points at `db:5432`; liveness via the built-in `HEALTHCHECK` on `/api/v1/health`.
- **`web`** — Next.js standalone image built from the repo root (`context: ../..`, `dockerfile: Dockerfile`), port `3000`.
- This file intentionally omits the gateway; use the root compose for the full stack.

**Known limitation (documented, not patched):** `next.config.ts` hardcodes the rewrite destination `http://127.0.0.1:3030/api/v1/:path*`. Inside the compose network that address is the web container itself, so the rewrite cannot reach the `api` service. Workarounds (in order of preference): keep the Caddy gateway in front; run `web` with `network_mode: host` on Linux; or make the rewrite target env-driven (one-line config change) and set it to `http://api:3030`. See the comment block at the bottom of `docker-compose.yml`.

## 3. Production checklist

Infrastructure:

- [ ] **Managed PostgreSQL 16 + PostGIS 3.5** (or a self-hosted equivalent). `GET /api/v1/health/ready` must return 200 — it verifies the PostGIS extension. Run `CREATE EXTENSION postgis` on the database (migration `0001` also issues `CREATE EXTENSION IF NOT EXISTS postgis`, which needs a superuser/owner role).
- [ ] **Migrations in the release pipeline**: run `alembic upgrade head` before switching traffic (the compose `api` service shows the pattern; keep it as a separate deploy step with rollback awareness).
- [ ] **HTTPS at the gateway** (Caddy, ALB, or ingress). Terminate TLS centrally; keep the API private and never expose `:3030` directly.
- [ ] **Run containers as non-root** (the API image ships user `croptwist`, uid 10001) and set resource limits for uvicorn (ortools/rasterio workloads are memory-hungry; size workers/threads accordingly, e.g. `--workers 2`).

Configuration (all via environment, never committed files):

- [ ] `CROPTWIST_ENVIRONMENT=production`
- [ ] **`CROPTWIST_DEV_MODE=false`** — mandatory; disables `POST /api/v1/dev/seed-demo` and any dev conveniences.
- [ ] `CROPTWIST_DATABASE_URL` → managed instance, credentials via the secret store.
- [ ] **`CROPTWIST_PASSWORD_PBKDF2_ITERATIONS >= 600000`** — the 120k default is a sandbox compromise.
- [ ] `CROPTWIST_CORS_ALLOW_ORIGINS` — explicit allow-list of browser origins (empty string disables CORS entirely; fine only when the gateway is strictly same-origin).
- [ ] Review upload guards: `CROPTWIST_MAX_IMPORT_FILE_BYTES` (32 MB default) and enforce the same body limit at the gateway.
- [ ] Provider endpoints (Open-Meteo, SoilGrids) must be reachable from the deployment network; tune `CROPTWIST_*_TIMEOUT_SECONDS` if egress is proxied. NASA connectors remain unimplemented by design (future adapter).

Secrets & data safety:

- [ ] **Secrets via environment/secret manager** (AWS Secrets Manager, Vault, platform secrets) — never bake them into images, and never commit a `.env`.
- [ ] **Backups**: nightly `pg_dump -Fc croptwist` (PostGIS tables included), stored off-site; test restores quarterly. Snapshot the disk only as a secondary layer.
- [ ] Log retention/rotation for uvicorn stdout (ship to your log platform); every response carries `x-request-id` for correlation.

Verification after deploy:

1. `GET /api/v1/health` → 200 with `environment: production`.
2. `GET /api/v1/health/ready` → 200 with a `postgis_version` payload.
3. Register a real user (not the demo account) and create a farm/field polygon end-to-end.
4. Confirm the demo seed endpoint returns 403/404 (dev mode off).

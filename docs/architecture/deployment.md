# Deployment

## Sandbox development (current environment)

```bash
# 1. Database (user-space PostgreSQL 16 + PostGIS 3.5; no root required)
cd mini-services/fieldshift-api
.venv/bin/python scripts/ensure_db.py        # starts cluster (db/pgdata, port 5433), creates DB + postgis

# 2. Backend API (port 3030) — runs migrations, then uvicorn --reload
bun run dev                                   # inside mini-services/fieldshift-api

# 3. Frontend (port 3000)
cd /home/z/my-project && bun run dev          # Next.js (webpack dev mode)
```

Gateway: Caddy (`Caddyfile`) maps public traffic :81 → :3000, and any request with `?XTransformPort=<port>` → that local port. The frontend calls `/api/v1/*?XTransformPort=3030`. A Next.js rewrite additionally proxies `/api/v1/*` → `127.0.0.1:3030` for direct-:3000 access.

## Tests

```bash
cd mini-services/fieldshift-api
.venv/bin/python -m pytest tests              # 85 tests (unit + contract + integration + migrations)
cd /home/z/my-project && bun run lint         # frontend lint
```

## Production (guidance — not yet automated)

1. Provision managed **PostgreSQL 16 + PostGIS 3.x**; set `CROPTWIST_DATABASE_URL`. Run `alembic upgrade head` (the DDL is plain PostGIS — no sandbox-specific artifacts).
2. Run FastAPI behind a reverse proxy (uvicorn workers / gunicorn-uvicorn); restrict CORS via `CROPTWIST_CORS_ALLOW_ORIGINS`; set `CROPTWIST_DEV_MODE=false` (disables `/dev/seed-demo`).
3. Raise `CROPTWIST_PASSWORD_PBKDF2_ITERATIONS` (≥600k) and review token TTL.
4. Serve the Next.js production build; keep the single-route workspace.
5. Add Redis + a task worker when ingestion moves off-request (job tables/contracts are ready); add object storage for rasters when raster providers arrive.
6. Backups: standard `pg_basebackup`/managed snapshots; `db/pgdata` is dev-only state.
7. Health/readiness probes: `/api/v1/health`, `/api/v1/health/ready`.

Environment variables (prefix `CROPTWIST_`, see `app/core/config.py`): `DATABASE_URL`, `DB_PGDATA_DIR`, `DB_PORT`, `AUTH_TOKEN_TTL_SECONDS`, `PASSWORD_PBKDF2_ITERATIONS`, `DEV_MODE`, `CORS_ALLOW_ORIGINS`, `ENVIRONMENT`.

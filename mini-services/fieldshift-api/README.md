# CropTwist API

FastAPI backend for **CropTwist**, a global agriculture decision-intelligence platform. It provides multi-tenant farm/field management with PostGIS geometry, a canonical field-data pipeline (data platform → features → knowledge), agronomic modeling (rotation, water, soil, digital twin), and a decision layer (scenarios, sensitivity, robust rotation, comparisons) — all under a versioned `/api/v1` contract.

> Current status is summarized in the [repository audit](../../docs/MASTER_REPOSITORY_AUDIT.md), [gap matrix](../../docs/MASTER_GAP_ANALYSIS.md), the [2026-11-14 remediation report](../../docs/implementation/REMEDIATION_STATUS_2026-11-14.md), and this API's [known limitations](KNOWN_LIMITATIONS.md). Historical milestone counts and claims are not current readiness evidence.

## Architecture at a glance

- **Stack:** FastAPI + SQLAlchemy 2 (GeoAlchemy2) on **PostgreSQL 16 + PostGIS 3.5**, pydantic-settings configuration, Alembic migrations (current head `0023_p07_field_reports`), and uvicorn.
- **Surface:** versioned domain routers mounted under `/api/v1`, backed by SQLAlchemy models across core, AI, P2, and P3 modules. Use the current model/migration inventory rather than older endpoint/table counts.
- **Determinism:** the rotation optimizer is OR-Tools CP-SAT with `num_search_workers=1` and a recorded seed (identical inputs → identical plans); scenario executions, sensitivity analyses, robust runs and decision documents are checksummed, immutable, replayable artifacts with `/verify` endpoints.
- **Frontend:** Next.js 16 App Router app at the repository root, served on port 3000, calling the API via relative `/api/v1` paths (Caddy gateway `XTransformPort=3030`, or the `next.config.ts` rewrite fallback).
- **Liveness / readiness:** `GET /api/v1/health` (process) and `GET /api/v1/health/ready` (verifies PostGIS is installed and reachable). OpenAPI UI at **`/docs`**.

### Domain routers (`app/api/v1/`)

| Domain | Router | Domain | Router |
| --- | --- | --- | --- |
| Identity & auth | `auth.py` | Farm members | `members.py` |
| Farms | `farms.py` | Fields | `fields.py` |
| Data platform | `data_platform.py` | Feature engine | `features.py` |
| Knowledge packs | `knowledge.py` | Rotation planning | `rotation.py` |
| Water intelligence | `water.py` | Field states | `field_states.py` |
| Scenario modeling | `scenarios.py` | Scenario executions | `scenario_executions.py` |
| Sensitivity analysis | `sensitivity.py` | Robust rotation | `robust_rotation.py` |
| Decision comparisons | `decision.py` | Digital twin | `digital_twin.py` |
| Soil intelligence | `soil.py` | Field management | `management.py` |
| Health | `health.py` | | |

External data code includes the Open-Meteo historical archive (ERA5/ERA5-Land reanalysis), optional ISRIC SoilGrids WCS, operator-upload CHIRPS GeoTIFF extraction, NASA HLS discovery and Earthdata-gated asset reads, and explicitly labelled synthetic fixtures. Current live provider readiness was not established by the repository audit; HLS contract tests use mocked transport, and the direct HLS acquisition path has known Fmask/CRS/windowing gaps. Weather forecasts and climate projections are not connected. Every response carries an `x-request-id` correlation header.

## Quickstart (local, sandbox convention)

Prerequisites: Python 3.12, [bun](https://bun.sh), and a PostgreSQL 16 + PostGIS 3.5 server. `scripts/run_dev.py` auto-starts the bundled **user-space** cluster (micromamba/conda-forge, `db/pgdata`, port **5433**, unix socket `/tmp`) — on a machine without it, point `CROPTWIST_DATABASE_URL` at your own instance and create the database.

```bash
cd mini-services/fieldshift-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bun run dev            # runs scripts/run_dev.py: ensure PG → alembic upgrade head → uvicorn --reload
```

The API listens on `http://127.0.0.1:3030` (dev binds the loopback interface on purpose). Dev conveniences require `CROPTWIST_DEV_MODE=true`; with it, seed the demo tenant:

```bash
curl -X POST http://127.0.0.1:3030/api/v1/dev/seed-demo
# demo account: demo@croptwist.local / croptwist-demo-2026
```

Frontend (from the repo root): `bun install && bun run dev` → `http://localhost:3000`.

## Quickstart (Docker)

The repository-root compose file builds the whole stack (db + api + web + Caddy gateway on :81):

```bash
# Run from the repository root.
docker compose up --build
# db:  postgis/postgis:16-3.5 on host port 5433 (named volume croptwist-pgdata)
# api: alembic upgrade head, then uvicorn on 3030
# web: Next.js standalone build on 3000
# gateway: caddy:2 on 81 (XTransformPort routing, host networking)
```

A backend-local subset (db + api + web, without the gateway) lives in this directory's `docker-compose.yml`. The repository-root Compose file is a local/demo topology, not a production deployment; dev mode is off by default and should only be enabled for an isolated demo. Note the documented limitation about the hardcoded rewrite target in `next.config.ts` — see the comment block at the bottom of that file and `docs/architecture/deployment.md`.

## Configuration

All settings come from `app/core/config.py` (pydantic-settings, prefix `CROPTWIST_`, optional `.env` in the API working directory). See [`.env.example`](.env.example) for the annotated template, including settings reserved for in-flight workstreams.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CROPTWIST_SERVICE_NAME` | `croptwist-api` | Service identity in `/health` |
| `CROPTWIST_API_VERSION` | `v1` | API version prefix |
| `CROPTWIST_ENVIRONMENT` | `development` | `development` / `test` / `production` |
| `CROPTWIST_DATABASE_URL` | `postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist` | SQLAlchemy URL (PostgreSQL + PostGIS) |
| `CROPTWIST_DB_PGDATA_DIR` | `/home/z/my-project/db/pgdata` | Sandbox user-space cluster data dir |
| `CROPTWIST_DB_PORT` | `5433` | Sandbox cluster port |
| `CROPTWIST_DB_SOCKET_DIR` | `/tmp` | Sandbox unix socket dir |
| `CROPTWIST_AUTH_TOKEN_TTL_SECONDS` | `43200` (12 h) | Bearer token lifetime |
| `CROPTWIST_AUTH_REFRESH_TTL_SECONDS` | `2592000` (30 d) | Refresh-token lifetime (rotation + family revocation) |
| `CROPTWIST_PASSWORD_PBKDF2_ITERATIONS` | `600000` | PBKDF2 work factor (embedded per hash) |
| `CROPTWIST_AUTH_MAX_FAILED_LOGINS` | `5` | Failed logins before lockout |
| `CROPTWIST_AUTH_LOCKOUT_SECONDS` | `900` | Lockout window |
| `CROPTWIST_AUTH_RATE_LIMIT_PER_MINUTE` | `10` | Auth-endpoint rate limit per IP (0 disables) |
| `CROPTWIST_PASSWORD_RESET_TTL_SECONDS` | `3600` | Password-reset challenge TTL |
| `CROPTWIST_EMAIL_VERIFICATION_TTL_SECONDS` | `86400` | Email-verification challenge TTL |
| `CROPTWIST_DEV_MODE` | `false` | Enables `POST /api/v1/dev/seed-demo`; **must be `false` in production** |
| `CROPTWIST_DEFAULT_PAGE_SIZE` | `50` | Default pagination size |
| `CROPTWIST_MAX_PAGE_SIZE` | `500` | Pagination hard cap |
| `CROPTWIST_CORS_ALLOW_ORIGINS` | *(empty)* | Comma-separated allow-list; empty disables CORS middleware |
| `CROPTWIST_OPEN_METEO_BASE_URL` | Open-Meteo archive | Weather provider base URL |
| `CROPTWIST_OPEN_METEO_TIMEOUT_SECONDS` | `25.0` | Weather provider timeout |
| `CROPTWIST_OPEN_METEO_MAX_YEARS_PER_REQUEST` | `10` | Provider request window cap |
| `CROPTWIST_SOILGRIDS_WCS_BASE_URL` | ISRIC mapserv | Soil provider base URL |
| `CROPTWIST_SOILGRIDS_TIMEOUT_SECONDS` | `45.0` | Soil provider timeout |
| `CROPTWIST_PROVIDER_PROBE_TIMEOUT_SECONDS` | `6.0` | Provider availability probe timeout |
| `CROPTWIST_PROVIDER_PROBE_CACHE_SECONDS` | `120` | Provider probe cache TTL |
| `CROPTWIST_MAX_IMPORT_FILE_BYTES` | `32000000` (32 MB) | Upload cap for CSV/GeoTIFF imports |
| `CROPTWIST_JOB_WORKERS` | `2` | Background worker threads (provider ingestion); `0` = legacy inline execution |

## Background jobs (async ingestion)

Provider ingestion uses the `background_jobs` table as durable state and a per-process wake-up queue (`app/core/jobs.py`, migration `0016_background_jobs`):
`POST /fields/{id}/data-jobs` returns `202` with the job **queued**, and clients poll `GET /jobs/{job_id}` or the unified queue views. Workers poll persisted queued rows, claim them with a database row lock, and register replay executors before startup recovery; this allows a standalone worker to discover API-submitted work without a new broker. The database-backed cross-process/restart behavior was not exercised here, and raster-domain/generic-job transaction ordering remains unverified. See `KNOWN_LIMITATIONS.md` for details. Set `CROPTWIST_JOB_WORKERS=0` to use legacy inline execution (the test suite does).

## Testing

The suite needs a real PostgreSQL + PostGIS (no SQLite fallback) on `127.0.0.1:5433`. `tests/conftest.py` creates `croptwist_test`, enables PostGIS, migrates to head, and truncates tables between tests. Override the target with `CROPTWIST_TEST_DB_URL` (e.g. in CI).

```bash
cd mini-services/fieldshift-api
.venv/bin/python -m pytest tests -q     # requires isolated PostgreSQL + PostGIS
```

From the repository root, run `bun test tests/frontend` for the frontend helper/navigation suite. CI declares backend migrations, `alembic check`, pytest, and API/bridge smoke against a `postgis/postgis:16-3.5` service; frontend typecheck, lint, regression tests, and production build; and bridge typecheck. The workflow declaration is not evidence of a current successful hosted run.

## Project layout

```
mini-services/fieldshift-api/
├── alembic.ini              # Alembic config (URL comes from settings)
├── pytest.ini
├── requirements.txt         # 48 pinned deps (ortools, rasterio, geoalchemy2, …)
├── Dockerfile               # multi-stage python:3.12-slim image, non-root
├── docker-compose.yml       # backend-local subset (db + api + web)
├── .env.example             # annotated CROPTWIST_* template (no .env is committed)
├── app/
│   ├── main.py              # create_app: CORS, request-id middleware, router mount
│   ├── api/v1/              # 19 routers (see table above) + router.py aggregator
│   ├── core/                # config.py (pydantic-settings), database, security,
│   │                        #   rate_limit, logging, errors
│   ├── domains/             # identity (auth primitives, RBAC roles), farms_fields
│   ├── db/                  # SQLAlchemy models across core, AI, P2, and P3 modules
│   ├── data_platform/       # providers (open_meteo, soilgrids, chirps, synthetic),
│   │                        #   registry, ingestion, CSV imports, observability
│   ├── features/            # M4 feature engine + versioned catalog + calendar
│   ├── knowledge/           # knowledge packs (seed pack v1, M6C practices pack)
│   ├── rotation/            # M5 CP-SAT rotation optimizer (constraints, objectives)
│   ├── water/               # M6A water planning (Kc curves, effective rainfall)
│   ├── field_state/         # M7.1 immutable field-state snapshots + manifests
│   ├── scenarios/           # M7.2 scenario definitions & validation
│   ├── soil/                # M6B soil intelligence (profiles, SOC, nutrients)
│   ├── management/          # M6C management practices (cover crops, residue, erosion)
│   ├── scenario_execution/  # M7.3 pure transformations + immutable executions
│   ├── sensitivity/         # M7.4 OAT sweeps + uncertainty registry
│   ├── robust_rotation/     # M7.5 shared-plan maximin optimization
│   ├── decision/            # M7.6 decision comparison documents
│   └── digital_twin/        # M7.7 traceable twin assembly & validation
├── migrations/versions/     # additive Alembic revisions through 0023_p07_field_reports
├── scripts/
│   ├── run_dev.py           # ensure PG → migrate → uvicorn --reload
│   ├── ensure_db.py         # boots the user-space PostgreSQL cluster
│   ├── daemonize.py         # double-fork daemonizer for sandbox survival
│   └── m73_smoke.py         # scenario-execution smoke script
├── tests/                   # pytest suite (unit / integration / contract; real PG + PostGIS)
└── docs/                    # module documentation cited from the code (see below)
```

## Documentation

Cited from the code, kept next to it:

- `KNOWN_LIMITATIONS.md` — honest gaps and non-goals
- `docs/implementation/REMEDIATION_STATUS_2026-11-14.md` — current branch scope, verified checks, and deferred work
- `docs/architecture/deployment.md` — sandbox / compose / production
- `docs/architecture/knowledge-model.md` — knowledge-pack data model
- `docs/data_platform/provider-contracts.md` — provider protocol & contracts
- `docs/deepening/SCIENTIFIC_AUDIT.md` — findings register (F-xx) + regression tests
- `docs/implementation/DECISIONS_AND_ASSUMPTIONS.md` — ADR index
- `docs/implementation/M5_GAP_ANALYSIS.md`, `docs/implementation/M6A_READINESS_MATRIX.md`
- `docs/m6b/M6B_GAP_ANALYSIS.md`, `docs/m6c/M6C_GAP_ANALYSIS.md`
- `docs/m7/m7_3/` (execution architecture, transformation methodology), `docs/m7/m7_4/` (architecture & lineage, sensitivity method, uncertainty registry), `docs/m7/m7_5/M7_5_ROBUST_METHOD.md`, `docs/m7/m7_6/M7_6_DECISION_INTELLIGENCE.md`, `docs/m7/m7_7/M7_7_ARCHITECTURE.md`

## Deployment

Run modes, sandbox layout, and the production checklist (managed PostGIS, `CROPTWIST_DEV_MODE=false`, CORS, HTTPS at the gateway, PBKDF2 ≥ 600k, secrets, backups) live in [`docs/architecture/deployment.md`](docs/architecture/deployment.md).

## Known limitations

See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) and the [remediation report](../../docs/implementation/REMEDIATION_STATUS_2026-11-14.md) for the maintained status. Legacy membership, Free-tier, session, CSV/observation, public API-key, report-scope, and several agronomic scoring defects have code fixes and regression coverage; database-backed integration remains unverified in this sandbox. Job persistence/claims are database-backed, but worker recovery and raster dispatch ordering still need runtime verification. Direct HLS acquisition remains a separate GIS workstream. Recommendation narratives still lack the field-brief evidence gate; advisor Q&A numeric checks remain screening-grade; webhook secrets remain plaintext at rest; metrics are process-local; external provider readiness is unverified; weather forecasts, climate projections, document RAG, and trained predictive ML are absent. The root Compose stack is for local/demo use, not production.

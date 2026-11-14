# CropTwist

**Global agriculture decision-intelligence platform.** CropTwist turns farm records and environmental observations into traceable, reproducible decision support — it is a **decision-support system**, not an autonomous agronomist and not a guarantee of yield, water savings, soil improvement, or profit.

## What it does

- **Farms & fields** — multi-tenant farm/field management with PostGIS boundary geometry (GeoJSON validation, geodesic areas, append-only boundary versioning + audit events).
- **Data platform** — canonical observation contracts, provider protocol (Open-Meteo historical archive, ISRIC SoilGrids, deterministic synthetic fixtures), ingestion jobs, CSV/GeoTIFF imports, and the **Field Data Passport**: per-variable coverage, quality, freshness and provenance with honest analysis-readiness verdicts.
- **Feature engine** — a versioned catalog of daily agronomic features (climate accumulations, stress indicators) computed from observations with full lineage.
- **Knowledge base** — source-cited, versioned crop knowledge packs (FAO-56-derived crop coefficients, calendars, rotation rules, management practices). Reference values stay `validation_status="reference"` until agronomist review; nothing is invented.
- **Rotation optimization** — OR-Tools CP-SAT crop-rotation planner: hard constraints as solver assumptions (infeasibility maps back to named constraints, never silent relaxation), deterministic solves, post-hoc criteria evaluation, Pareto analysis, per-strategy explanations.
- **Water planning** — crop water requirements (Kc curves, effective rainfall, soil water holding), irrigation planning with explicit evidence and gaps.
- **Soil intelligence** — soil profiles and layers, SOC stock (FAO GSOC-convention layer arithmetic, coarse-fragment handling), nutrient budgets, soil health assessment.
- **Field management** — practice knowledge, cover crops, residue ledger and mass balance, soil cover, erosion screening, operation scheduling.
- **Field states** — immutable, checksummed snapshots pinning the observation manifest a field's analysis is built on (by value, never by live query).
- **Scenarios** — finalized, checksummed scenario definitions; executions apply two scientifically specified transformations (uniform temperature shift, precipitation scaling) to pinned observations and recompute affected features; unsupported dimensions (soil, management, climate projection, weather forecast) are refused and recorded, never fabricated.
- **Sensitivity** — one-at-a-time parameter sweeps and joint grids over immutable scenario executions, with finite-difference slopes, versioned response classification and a per-analysis uncertainty registry.
- **Robust rotation** — ONE shared rotation plan optimized against multiple scenario executions with a worst-case (maximin) objective; per-scenario results recomputed post-hoc by the existing evaluation code; optional minimax-regret comparison against per-scenario solo optima.
- **Decisions** — decision comparison documents unifying executions, sensitivities and robust runs into one traceable, checksummed view with rankings only within the same unit.
- **Digital twin** — a validated, traceable field-level representation linking boundaries → field states → observations → features → scenarios → analyses → decisions, with integrity re-verification.

All analytics artifacts are immutable and checksummed; every module exposes `/verify` endpoints that re-check integrity (pins, checksums, method versions).

## Repository layout (monorepo)

```
.
├── src/                          # Next.js 16 App Router frontend (React 19, Tailwind v4, shadcn/ui)
├── next.config.ts                # output: "standalone"; /api/v1 rewrite fallback to :3030
├── Dockerfile                    # Bun install → Node 22 build/runtime on 3000
├── docker-compose.yml            # full stack: db + api + web + gateway
├── Caddyfile                     # gateway on :81 (?XTransformPort=<port> routing)
├── .env.example                  # root-level environment template
├── scripts/start-stack.sh        # sandbox convenience launcher (pg|api|web|all|rebuild)
├── docs/                         # platform-wide documentation (architecture, deepening, m6b/m6c/m7, …)
├── db/                           # user-space PostgreSQL runtime (gitignored data)
└── mini-services/fieldshift-api/ # FastAPI backend (modular monolith)
    ├── app/                      # api/v1 routers, domains, feature/rotation/water/soil/… engines
    ├── migrations/               # Alembic (current head: 0023_p07_field_reports)
    ├── tests/                    # pytest: unit / integration / contract (real PostGIS)
    ├── docs/                     # backend docs cited from the code
    ├── Dockerfile                # python:3.12-slim, non-root, healthcheck
    └── .env.example              # annotated CROPTWIST_* template
```

The backend is a **modular monolith**: one FastAPI service (`uvicorn app.main:app`) with versioned routers and SQLAlchemy/Alembic schema on PostgreSQL 16 + PostGIS. The frontend calls relative `/api/v1` URLs; Next rewrites them to the server-only `CROPTWIST_API_ORIGIN`. Local direct development defaults to `127.0.0.1:3030`; Compose explicitly supplies `http://api:3030`; Vercel requires an HTTPS origin. Browser helpers no longer require the sandbox-only `XTransformPort` gateway query. The current revision is `0023_p07_field_reports`; use the migration files and master audit as the source of truth rather than older table-count notes.

## Quickstart (Docker Compose)

```bash
# Run from the repository root.
cp .env.example .env                 # local-only template; replace demo DB password
docker compose up --build
```

The root Compose file is a **local/demo topology, not a production deployment**: it has no TLS, publishes host ports, uses local storage and a demo database password. Dev mode is off by default; enable it only for an isolated demo with `CROPTWIST_DEV_MODE=true docker compose up --build`. Production requires managed secrets, PostGIS, durable object storage, controlled ingress/workers, and a recovery plan.

| Service | Port | Notes |
| --- | --- | --- |
| web (Next.js) | 3000 | standalone build, healthchecked |
| api (FastAPI) | 3030 | runs `alembic upgrade head`, then uvicorn |
| db (PostgreSQL 16 + PostGIS 3.5) | 5433 | `postgis/postgis:16-3.5`, named volume, `pg_isready` healthcheck |
| gateway (Caddy) | 81 | mounts the repo `Caddyfile`, host networking (Linux) |

With `CROPTWIST_DEV_MODE=true`: `curl -X POST http://127.0.0.1:3030/api/v1/dev/seed-demo` seeds the demo tenant (`demo@croptwist.local` / `croptwist-demo-2026`). This unauthenticated dev route must not be enabled in production.

## Quickstart (manual, development)

```bash
# 1. Database — PostgreSQL 16.10 + PostGIS 3.5.0 on 127.0.0.1:5433.
#    Sandbox convenience (user-space cluster; idempotent):
./scripts/start-stack.sh pg

# 2. Backend API on 127.0.0.1:3030 (migrations run automatically):
cd mini-services/fieldshift-api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bun run dev                 # ensure PG -> alembic upgrade head -> uvicorn --reload
# or: ../../scripts/start-stack.sh api

# 3. Frontend on 0.0.0.0:3000:
cd ../..
bun install
bun run dev
# or: ./scripts/start-stack.sh web
```

Open the app on port 3000 (or the gateway on 81). API docs: FastAPI's OpenAPI UI at `http://127.0.0.1:3030/docs`.

## Ports

| Port | Service | Binding |
| --- | --- | --- |
| 3000 | Next.js web | `0.0.0.0` |
| 3030 | CropTwist FastAPI | `127.0.0.1` in the sandbox, `0.0.0.0` in containers |
| 5433 | PostgreSQL 16 + PostGIS 3.5 | `127.0.0.1` (sandbox user-space cluster or compose mapping) |
| 81 | Caddy gateway | host; routes `?XTransformPort=<port>` to services, everything else to :3000 |

## Testing

```bash
# Run from the repository root.
cd mini-services/fieldshift-api
.venv/bin/python -m pytest tests -q     # needs local PG + PostGIS on 5433 (db croptwist_test)
cd ../.. && bun run lint               # frontend lint
bun test tests/frontend              # frontend helper/navigation regression tests
cd mini-services/llm-bridge && ../../node_modules/.bin/tsc --noEmit
```

CI (`.github/workflows/ci.yml`) runs backend migration checks, pytest and API/bridge smoke against PostGIS; frontend typecheck, lint, regression tests and production build; and the LLM bridge typecheck. A workflow definition is not evidence of a successful hosted run.

## Documentation

- Project-control dashboard: [`PROJECT_CONTROL.md`](PROJECT_CONTROL.md) (current status, branch registry, integration queue, quality gates and decisions)
- Backend README: [`mini-services/fieldshift-api/README.md`](mini-services/fieldshift-api/README.md)
- Backend docs cited from code: [`mini-services/fieldshift-api/docs/`](mini-services/fieldshift-api/docs/) and [`KNOWN_LIMITATIONS.md`](mini-services/fieldshift-api/KNOWN_LIMITATIONS.md)
- Platform-wide docs: [`docs/`](docs/) — architecture, scientific deepening program, milestone records (`docs/m6b/`, `docs/m6c/`, `docs/m7/`), data dictionary, diagrams
- Current repository audit: [`docs/MASTER_REPOSITORY_AUDIT.md`](docs/MASTER_REPOSITORY_AUDIT.md)
- Prioritized gap matrix: [`docs/MASTER_GAP_ANALYSIS.md`](docs/MASTER_GAP_ANALYSIS.md)
- Remediation status for `remediation/legacy-hardening`: [`docs/implementation/REMEDIATION_STATUS_2026-11-14.md`](docs/implementation/REMEDIATION_STATUS_2026-11-14.md)
- AI architecture and roadmap: [`docs/architecture/CROPTWIST_AI_ARCHITECTURE.md`](docs/architecture/CROPTWIST_AI_ARCHITECTURE.md)
- Deployment guide: [`mini-services/fieldshift-api/docs/architecture/deployment.md`](mini-services/fieldshift-api/docs/architecture/deployment.md)

## Selected hosting foundation: Vercel + Supabase

The deployment workstream prepares Vercel for Next.js and Supabase for PostgreSQL/PostGIS while retaining FastAPI, authentication and Python processing. See [`deployment/ARCHITECTURE.md`](deployment/ARCHITECTURE.md), [`SUPABASE_SETUP.md`](deployment/SUPABASE_SETUP.md), [`VERCEL_SETUP.md`](deployment/VERCEL_SETUP.md), and [`VERIFICATION.md`](deployment/VERIFICATION.md).

No hosted service is deployed by this branch. All Vercel Git deployments are disabled until the redesign/eligibility gates pass. Vercel Hobby excludes commercial use; Render Free is only a conditional API staging candidate, not reliable continuous-worker or durable-file hosting. Read [`FREE_TIER_LIMITS.md`](deployment/FREE_TIER_LIMITS.md) and [`STAGING_GUIDE.md`](deployment/STAGING_GUIDE.md) before provisioning. The deferred Alembic discrepancy remains unchanged and blocking.

The standalone frontend runs on Node.js 22.x; Bun 1.3.4 remains the frozen dependency/build-script tool. The additional local deployment Compose topology is `deployment/docker-compose.yml`; the original root topology is retained with an explicit internal API origin.

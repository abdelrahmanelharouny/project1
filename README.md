# FieldShift

**Global agriculture decision-intelligence platform.** FieldShift turns farm records and environmental observations into traceable, reproducible decision support — it is a **decision-support system**, not an autonomous agronomist and not a guarantee of yield, water savings, soil improvement, or profit.

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
/home/z/my-project
├── src/                          # Next.js 16 App Router frontend (React 19, Tailwind v4, shadcn/ui)
├── next.config.ts                # output: "standalone"; /api/v1 rewrite fallback to :3030
├── Dockerfile                    # web image (oven/bun → standalone server on 3000)
├── docker-compose.yml            # full stack: db + api + web + gateway
├── Caddyfile                     # gateway on :81 (?XTransformPort=<port> routing)
├── .env.example                  # root-level environment template
├── scripts/start-stack.sh        # sandbox convenience launcher (pg|api|web|all|rebuild)
├── docs/                         # platform-wide documentation (architecture, deepening, m6b/m6c/m7, …)
├── db/                           # user-space PostgreSQL runtime (gitignored data)
└── mini-services/fieldshift-api/ # FastAPI backend (modular monolith)
    ├── app/                      # api/v1 routers, domains, feature/rotation/water/soil/… engines
    ├── migrations/               # Alembic (head 0016_background_jobs)
    ├── tests/                    # pytest: unit / integration / contract (real PostGIS)
    ├── docs/                     # backend docs cited from the code
    ├── Dockerfile                # python:3.12-slim, non-root, healthcheck
    └── .env.example              # annotated FIELDSHIFT_* template
```

The backend is a **modular monolith**: one FastAPI service (`uvicorn app.main:app`), 19 routers under `/api/v1`, 80 tables on PostgreSQL 16 + PostGIS 3.5. The frontend talks to it through relative `/api/v1` URLs: behind the Caddy gateway requests carry `?XTransformPort=3030`; when hitting the web server directly, `next.config.ts` rewrites `/api/v1/*` to `127.0.0.1:3030` (works when both share a host — the sandbox case).

## Quickstart (Docker Compose)

```bash
cd /home/z/my-project
cp .env.example .env                 # review, then adjust credentials
docker compose up --build
```

| Service | Port | Notes |
| --- | --- | --- |
| web (Next.js) | 3000 | standalone build, healthchecked |
| api (FastAPI) | 3030 | runs `alembic upgrade head`, then uvicorn |
| db (PostgreSQL 16 + PostGIS 3.5) | 5433 | `postgis/postgis:16-3.5`, named volume, `pg_isready` healthcheck |
| gateway (Caddy) | 81 | mounts the repo `Caddyfile`, host networking (Linux) |

With `FIELDSHIFT_DEV_MODE=1` (compose default for demos): `curl -X POST http://127.0.0.1:3030/api/v1/dev/seed-demo` seeds the demo tenant (`demo@fieldshift.local` / `fieldshift-demo-2026`).

## Quickstart (manual, development)

```bash
# 1. Database — PostgreSQL 16.10 + PostGIS 3.5.0 on 127.0.0.1:5433.
#    Sandbox convenience (user-space cluster; idempotent):
/home/z/my-project/scripts/start-stack.sh pg

# 2. Backend API on 127.0.0.1:3030 (migrations run automatically):
cd /home/z/my-project/mini-services/fieldshift-api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bun run dev                 # ensure PG -> alembic upgrade head -> uvicorn --reload
# or: /home/z/my-project/scripts/start-stack.sh api

# 3. Frontend on 0.0.0.0:3000:
cd /home/z/my-project
bun install
bun run dev
# or: /home/z/my-project/scripts/start-stack.sh web
```

Open the app on port 3000 (or the gateway on 81). API docs: FastAPI's OpenAPI UI at `http://127.0.0.1:3030/docs`.

## Ports

| Port | Service | Binding |
| --- | --- | --- |
| 3000 | Next.js web | `0.0.0.0` |
| 3030 | FieldShift FastAPI | `127.0.0.1` in the sandbox, `0.0.0.0` in containers |
| 5433 | PostgreSQL 16 + PostGIS 3.5 | `127.0.0.1` (sandbox user-space cluster or compose mapping) |
| 81 | Caddy gateway | host; routes `?XTransformPort=<port>` to services, everything else to :3000 |

## Testing

```bash
cd /home/z/my-project/mini-services/fieldshift-api
.venv/bin/python -m pytest tests -q     # needs local PG + PostGIS on 5433 (db fieldshift_test)
cd /home/z/my-project && bun run lint   # frontend lint
```

CI (`.github/workflows/ci.yml`) runs the backend suite against a `postgis/postgis:16-3.5` service container and lints the frontend.

## Documentation

- Backend README: [`mini-services/fieldshift-api/README.md`](mini-services/fieldshift-api/README.md)
- Backend docs cited from code: [`mini-services/fieldshift-api/docs/`](mini-services/fieldshift-api/docs/) and [`KNOWN_LIMITATIONS.md`](mini-services/fieldshift-api/KNOWN_LIMITATIONS.md)
- Platform-wide docs: [`docs/`](docs/) — architecture, scientific deepening program, milestone records (`docs/m6b/`, `docs/m6c/`, `docs/m7/`), data dictionary, diagrams
- Deployment guide: [`mini-services/fieldshift-api/docs/architecture/deployment.md`](mini-services/fieldshift-api/docs/architecture/deployment.md)

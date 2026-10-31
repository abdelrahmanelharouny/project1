# FieldShift

**Adaptive Farm Intelligence & Crop-Rotation Decision Support** — agricultural decision-support platform.

> FieldShift is a **decision-support system**, not an autonomous agronomist and not a guarantee of yield, water savings, soil improvement, or profit.

## Current state: first vertical slice (Milestones 0–2 + Data Passport)

Implemented and tested end to end:

- **Runnable backend** — FastAPI (Python 3.12) mini-service on port 3030, structured errors with request IDs, health/readiness endpoints.
- **Real PostgreSQL 16.10 + PostGIS 3.5.0** — conda-forge user-space cluster (no root needed); Alembic migrations verified from a clean database (including downgrade/upgrade roundtrip).
- **Identity & tenancy** — register/login (PBKDF2), bearer tokens (hashed at rest), organization memberships; every farm/field/data route is tenant-authorized (cross-tenant access tested → 403).
- **Farms & fields** — CRUD, GeoJSON boundary validation (ring closure, coordinate bounds, self-intersection repair, antimeridian warnings), **geodesic area** (PyProj WGS84) cross-checked against PostGIS `geography ST_Area`, **append-only boundary versioning** + audit events.
- **Canonical observation contracts** — Pydantic v2 canonical observation (all Master §13.1 fields; missing = NULL, never zero), versioned variable catalog (7 variables), provider protocol + registry, source/product registry with license/attribution/limitations.
- **Deterministic synthetic provider** — 5 climate profiles, SHA-256-seeded (identical request ⇒ identical series), injected data gaps, coverage windows, fully labelled (`is_synthetic=true` + provenance everywhere). Contract test suite included.
- **Ingestion jobs** — 202 + persisted job state, records received/rejected, warnings, structured failures; **idempotent reruns** via natural-key uniqueness.
- **Field Data Passport** — per-variable coverage/quality/freshness/provenance, aggregated warnings with occurrence counts, and honest **analysis readiness** (available vs blocked with exact missing inputs; water budget / rotation optimization / soil analysis are blocked, never simulated).
- **Frontend workspace** — Next.js 16 single-route app: auth gate + labelled demo workspace, overview, farms & fields with offline MapLibre boundary map, observations (ingestion form, table with SYNTHETIC badges, charts), Data Passport tab. Responsive, sticky footer, shadcn/ui.
- **85 passing tests** — unit (geometry/area/determinism), provider contract suite, integration (tenant isolation, CRUD, ingestion idempotency, passport, clean-DB migrations).

**Not implemented (by design):** NASA connectors (future adapter), real environmental providers (Open-Meteo/CHIRPS/SoilGrids — next milestone), feature engineering, crop knowledge base, rotation optimizer, water/soil intelligence, stress testing. See `docs/implementation/IMPLEMENTATION_STATUS.md`.

## Quick start (sandbox dev)

```bash
# Database (PostgreSQL 16 + PostGIS 3.5, user-space)
cd mini-services/fieldshift-api
.venv/bin/python scripts/ensure_db.py

# Backend API (port 3030; runs migrations automatically)
bun run dev

# Frontend (port 3000)
cd .. && cd .. && bun run dev
```

Open the preview, click **“Enter demo workspace”** — a clearly-labelled synthetic workspace (demo farm, two fields, ingested fixture observations, filled Data Passport).

## Tests

```bash
cd mini-services/fieldshift-api && .venv/bin/python -m pytest tests   # 85 passed
cd /home/z/my-project && bun run lint                                  # clean
```

## Documentation

- `docs/implementation/IMPLEMENTATION_STATUS.md` — what is done / in progress / next
- `docs/implementation/DECISIONS_AND_ASSUMPTIONS.md` — ADR-0001…0008
- `docs/implementation/KNOWN_LIMITATIONS.md` — honest gaps
- `docs/implementation/TEST_MATRIX.md` — every test scenario and outcome
- `docs/architecture/system-overview.md` · `module-boundaries.md` · `technology-decisions.md` · `deployment.md`
- `docs/database/schema.md` — PostGIS schema
- `docs/data_platform/provider-contracts.md` — provider protocol + contract suite
- `docs/data_dictionary/variables.md` · `units.md` · `evidence-and-quality.md`
- `docs/api/api-contract-slice1.md` — frozen HTTP contract

## Repository layout (additions)

```
mini-services/fieldshift-api/     FastAPI backend (app/, migrations/, tests/, scripts/)
docs/                             architecture, database, data platform, data dictionary, api, implementation
src/components/fieldshift/        frontend workspace components
src/lib/api.ts, types.ts          typed transport (XTransformPort gateway) + contract types
db/pgenv, db/pgdata               user-space PostgreSQL+PostGIS runtime & cluster (gitignored)
```

## Scientific deepening (Pre-M6)

The M1–M5 implementation was audited and hardened before roadmap expansion:
findings register, as-built architecture, feature specifications, climate/soil
methodology, rotation mathematics, uncertainty policy, benchmarks and the
remediation record live in [`docs/deepening/`](docs/deepening/DEEPENING_EXIT_REPORT.md).

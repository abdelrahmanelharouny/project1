# System Overview

FieldShift is an agricultural decision-support platform. This is the **first vertical slice**: farm/field management on real PostgreSQL+PostGIS, a canonical observation pipeline with a deterministic synthetic provider, and the Field Data Passport. It contains **no NASA connectors** and **no real-world agronomic recommendations** (per the master specification).

## Architecture at a glance

```
┌────────────────────────────────────────────────────────────────────┐
│ Browser (user preview via Caddy gateway :81)                       │
│   Next.js 16 workspace (single / route, React 19, shadcn/ui,       │
│   TanStack Query, MapLibre offline map)                            │
└───────────────┬────────────────────────────────────────────────────┘
                │ fetch /api/v1/*?XTransformPort=3030   (relative URLs)
┌───────────────▼────────────────────────────────────────────────────┐
│ Caddy gateway  ── XTransformPort → localhost:3030                  │
│              └── default        → localhost:3000 (Next.js)         │
│   (Next.js also rewrites /api/v1/* → :3030 when reached directly)  │
└───────────────┬────────────────────────────────────────────────────┘
┌───────────────▼────────────────────────────────────────────────────┐
│ FastAPI backend (mini-services/fieldshift-api, port 3030)          │
│                                                                    │
│  api/v1        routers: health, auth, farms, fields, data-platform │
│  domains       identity (Principal, tenancy) · farms_fields        │
│  geospatial    geometry validation · geodesic area (PyProj)        │
│  data_platform contracts (canonical observation, variable catalog) │
│                registry (provider registry, source/product seed)   │
│                providers/synthetic (deterministic fixtures)        │
│                ingestion (jobs, idempotency)                       │
│  passport      Field Data Passport builder                         │
│  db            SQLAlchemy 2 models (PostGIS geometry columns)      │
│  core          config · database · errors · security · logging     │
└───────────────┬────────────────────────────────────────────────────┘
                │ SQLAlchemy / psycopg2
┌───────────────▼────────────────────────────────────────────────────┐
│ PostgreSQL 16.10 + PostGIS 3.5.0  (conda-forge, user-space)        │
│   users, organizations, memberships, auth_tokens,                  │
│   farms, fields (MULTIPOLYGON 4326), field_boundary_versions,      │
│   data_sources, dataset_products, ingestion_jobs,                  │
│   observations, observation_quality_flags, audit_events, ...       │
└────────────────────────────────────────────────────────────────────┘
```

## Core user journey supported today

1. Register / sign in (or enter the clearly-labelled synthetic demo workspace).
2. Create a farm (country, timezone, currency, units).
3. Create a field by pasting GeoJSON — geometry is validated (rings, bounds, self-intersection repair, antimeridian warnings), area computed geodesically, boundary stored as `MULTIPOLYGON(SRID 4326)` with version history.
4. Inspect the field on the offline map with geodesic area and boundary versions.
5. Run a synthetic ingestion job (profile, seed, variables, window) — observations land with full provenance and SYNTHETIC labels; reruns never duplicate.
6. Browse observations (table + charts) with per-row quality and provenance badges.
7. Read the Field Data Passport — what exists, how fresh it is, from which product, and which analyses are available or blocked (with exact missing inputs).

## Guiding rules honored (Master Engineering Prompt)

- Rule 7/8: synthetic data always labelled; NASA not implemented (no stub pollution).
- Rule 9/10: no upsampling claims; source/product/version/retrieval provenance preserved.
- Rule 11: missing values are `NULL` + `missing` quality status — never zero.
- Rule 14: deterministic, seeded synthetic generation (contract-tested).
- Rule 15: all geometry/units/date ranges validated with actionable errors.
- Rule 16: business logic in domain/application modules; routers only parse/serialize.
- Rule 17: tenant authorization on every farm/field/data route (tested).
- Rule 18/19/20: tests added with features; docs updated; honest reporting.

See `docs/architecture/module-boundaries.md` for layering rules and `docs/data_platform/provider-contracts.md` for the provider contract suite.

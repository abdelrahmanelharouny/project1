# AS_BUILT_ARCHITECTURE.md — as-built, verified against code (2026-10-31)

This document reflects the ACTUAL implementation (files read in full during the
deepening audit), not the intended architecture. Intended-vs-actual deviations
are listed explicitly in §6.

## 1. Topology

```
Browser (Next.js 16 / React 19, port 3000, single `/` route workspace)
   │  fetch, relative URLs only (gateway rewrite via XTransformPort)
   ▼
Caddy gateway ──────────────► FastAPI backend (uvicorn :3030, mini-service)
                                  │ SQLAlchemy 2 + GeoAlchemy2
                                  ▼
                               PostgreSQL 16.10 + PostGIS 3.5.0 (:5433)
                               31 tables, Alembic revisions 0001..0005
```

- No ORMs across service boundaries: HTTP JSON is the only frontend↔backend contract.
- `docs/architecture/module-boundaries.md` holds for the backend; the decision
  core (`app/rotation/*`, `app/knowledge/*` read path) has NO ORM/HTTP imports
  (verified by import inspection, ADR-0015).

## 2. Module responsibilities (backend)

| Module | Responsibility | Inputs → Outputs | DB | Scientific assumptions | Test coverage |
|---|---|---|---|---|---|
| `app/core/*` | config, errors (structured envelope + request ids), PBKDF2 auth, logging | FastAPI deps → exceptions | – | opaque bearer tokens hashed at rest | unit+integration |
| `app/domains/identity` | Principal resolution, membership checks (`get_{farm,field}_for_principal`) | bearer token → Principal | users/orgs/memberships/tokens | tenant scope = ownership chain app-side | tenant-isolation suite |
| `app/domains/farms_fields` | farm/field CRUD, boundary versioning, geodesic area (PyProj) + PostGIS cross-check | GeoJSON → validated MultiPolygon | farms/fields/versions/audit | ring closure, self-intersection repair, antimeridian WARN-only | U1–U17, I7–I23 |
| `app/geospatial/validation` | geometry validation + WGS84 geodesic area | GeoJSON → GeometryValidationResult | – | orientation enforced; >180° lon span → warning (not auto-repair) | U1–U17 |
| `app/data_platform/contracts` | canonical observation/variable contracts (Pydantic v2) | dicts → canonical models | – | UTC enforced; value NULL ⇔ missing; evidence classes | contract suite |
| `app/data_platform/providers/*` | SYNTHETIC (deterministic), open_meteo (ERA5/ERA5-Land), chirps (GeoTIFF extract, v2 area-weighted), soilgrids (WCS 0–5 cm, v3 honest PI label) | request → ProviderFetchResult | observations + flags | reanalysis ≠ station; satellite-gauge blend; SoilGrids = model prediction | unit+contract per provider |
| `app/data_platform/ingestion` | job lifecycle, natural-key idempotency, provider errors → structured job failures | ProviderFetchResult → rows+jobs | ingestion_jobs, observations | dedupe by (field, product, variable, time, supports) | I24–I32 |
| `app/data_platform/imports` | farmer CSV strict parsing (sha256, row provenance) | file → canonical observations | jobs | blank→missing FARMER_BLANK; local calendar dates recorded | M3-U9..U12 |
| `app/features/*` | versioned catalog (26 features), deterministic engine, run orchestration | observations → drafts → feature_values | feature_definitions/runs/values | coverage policies; midpoint local-day rule; ≥5y baselines classified | 28 unit + 9 contract + 22 integration |
| `app/passport/*` | per-(variable,product) readiness + analysis gates (rotation gate queries reality) | field → passport payload | reads only | synthetic/real never merged; no composite confidence | I33–I37 + F-01 test |
| `app/knowledge/*` | pack import (strict cross-ref validation), read model, rule matching with region+status gating | pack JSON → KnowledgeBaseData | knowledge_packs/sources/families/crops/varieties/traits/windows/water/rules/reviews | hard binding ONLY at `confirmed_regional` | 16 contract + 11 API tests |
| `app/rotation/*` | candidates (4 statuses), constraints (pure checks), CP-SAT optimizer (assumption conflicts), objectives (7 criteria), Pareto, explain (9 blocks), orchestration | FarmContext → strategies | crop_history, farm_constraints, rotation_runs/strategies | missing ≠ zero ≠ exclusion; screening water estimate only w/ Kc+ET0 | 28 core + 16 API tests + 21 deepening tests |
| `app/api/v1/*` | 50 routes; 202 job pattern; idempotency (field-scoped since 0005) | HTTP → services | all | role codes defined but NOT yet enforced (documented) | integration suites |

## 3. Frontend

- `src/components/fieldshift/*`: workspace shell (tabs, sticky footer, mobile-safe),
  auth-gate, farms/fields (+MapLibre offline map), observations, features,
  rotation (913 lines), data-passport, badges, overview.
- `src/lib/api.ts` (fetch wrapper), `src/hooks/use-fieldshift.ts` (TanStack Query),
  `src/lib/types.ts` (1000+ lines of response contracts).
- Honesty rules enforced client-side post-deepening: synthetic badges are
  flag-driven (F-01), charts annotate provenance mix (F-17), missing counts
  render `—` never `0`.

## 4. Database (31 tables, migrations 0001–0005)

Ownership chain: `organizations ← farms ← fields ← (observations, jobs, runs, history)`.
Platform-level: variable catalog, data sources/products, feature definitions,
knowledge packs. Post-deepening integrity: composite idempotency uniques
(F-03), NULLS NOT DISTINCT Kc uniqueness (F-18), tenant-chain + audit indexes
(F-15), drift reconciled. All quantitative columns are float8 (documented
policy: aggregation-order effects accepted; NUMERIC accumulation reserved for
the M7 water ledger — RESEARCH backlog).

## 5. Known limitations of the architecture

- Roles defined but not enforced (any active member can PATCH farms / import packs).
- No row-level security: tenant scoping is app-side only.
- `rotation_strategies.assignment`/criteria stored as JSONB snapshots (reproducible, not queryable).
- Job execution is inline (202-style, single-process); no worker queue.

## 6. Intended-vs-actual deviations found by this audit

1. "Later pack versions win" was NOT actually deterministic (fixed, F-09).
2. "Only valid observations are quality-checked" docstring was NOT actually
   implemented in the engine (fixed, F-02).
3. `CriterionResult.source_refs` existed in the model but was never populated (fixed, F-10).
4. `VALID_STATUSES` existed but was unused (fixed, F-02).

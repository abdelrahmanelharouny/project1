# Implementation Status

Last updated: 2026-10-30 (Milestone 3 — alternative data integrations)

Legend: ✅ done · 🔄 in progress · ⛔ blocked · ⬜ not started

## Milestone 0 — Repository audit and decisions

| Task | Status | Notes |
|---|---|---|
| Inspect repository, git state, existing stack | ✅ | Next.js 16 + TS + Tailwind + shadcn template; Prisma/SQLite scaffolding; no prior FieldShift work |
| Identify conflicts with master spec, record ADRs | ✅ | ADR-0001..0008 in `docs/implementation/DECISIONS_AND_ASSUMPTIONS.md` |
| Establish tooling | ✅ | FastAPI backend as sandbox mini-service; pytest; Next.js dev on :3000 |

## Milestone 1 — Runnable foundation

| Task | Status | Notes |
|---|---|---|
| Backend environment (Python 3.12, FastAPI, pinned deps) | ✅ | `mini-services/fieldshift-api`, `requirements.txt` frozen |
| PostgreSQL 16 + PostGIS 3.5 running | ✅ | conda-forge user-space cluster, port 5433; `CREATE EXTENSION postgis` verified |
| Alembic migrations from clean database | ✅ | `0001_initial`; tested drop→create→upgrade→downgrade→upgrade |
| Health + readiness endpoints | ✅ | `/api/v1/health`, `/api/v1/health/ready` (reports PG + PostGIS versions) |
| Structured errors, request IDs, structured logs | ✅ | Error envelope per Master §42.5 |
| Frontend application shell | ✅ | Single `/` route workspace (Next.js), sticky footer, responsive |

## Milestone 1/2 — Farm & field domain

| Task | Status | Notes |
|---|---|---|
| users / organizations / memberships / tokens | ✅ | PBKDF2 password hashing; opaque bearer tokens stored hashed |
| Farm CRUD + tenant authorization | ✅ | Membership-checked on every route; cross-tenant access returns 403 |
| Field CRUD + geometry validation | ✅ | GeoJSON Polygon/MultiPolygon; ring closure, bounds, self-intersection repair, antimeridian warning |
| Geodesic area (PyProj WGS84) + PostGIS cross-check | ✅ | `area_ha` stored; `postgis_geodesic_area_ha` cross-check in field payload |
| Boundary versioning (never overwrite history) | ✅ | `field_boundary_versions` with change_reason + audit events |
| Map view | ✅ | `/fields/{id}/map` + offline MapLibre rendering (worker served from /public) |

## Milestone 2 — Canonical data + synthetic provider

| Task | Status | Notes |
|---|---|---|
| Canonical observation contract (Pydantic v2) | ✅ | All Master §13.1 fields; UTC-enforced; missing ≠ zero |
| Variable catalog / data dictionary (v2026.11.0-slice1) | ✅ | 7 variables with units + evidence-class hints |
| Provider protocol + registry | ✅ | `EnvironmentalDataProvider` protocol; registry keyed by provider_code; health endpoint |
| Source/product registry seeding | ✅ | `data_sources` + `dataset_products` with license/attribution/limitations |
| Deterministic synthetic provider (5 profiles) | ✅ | Seeded SHA-256 RNG; 2015–2024 coverage; gaps; 4-year cap; fully labelled |
| Ingestion jobs (status, counts, warnings, failures) | ✅ | Natural-key dedupe → idempotent rerun; provider errors → structured job failures |
| Provider contract test suite | ✅ | `tests/contract/` — canonical shapes, provenance, units, native time support, rejects invalid input, idempotency |

## Milestone 3 — Alternative data integrations

| Task | Status | Notes |
|---|---|---|
| Open-Meteo historical provider (REAL, live-verified) | ✅ | ERA5-Land (default) / ERA5 explicit products; verified model-variable matrix; UTC basis; null→missing with OPENMETEO_NULL; 10y chunking; retry/backoff; CC BY 4.0 attribution |
| Model/variable fail-fast | ✅ | Route 422 when the selected model publishes none of the requested variables; UI filters variables per model |
| CHIRPS v3 import/extraction workflow | ✅ | GeoTIFF upload (EPSG:4326 enforced) → field-mean precipitation; nodata accounting + LOW_CELL_COVERAGE flag; preliminary/final + daily/pentad/monthly recorded; rasterio-optional degradation |
| SoilGrids optional WCS provider | ✅ | 5 properties at 0-5 cm (slice depth); Qmean + Q0.05/Q0.95 → 90% prediction interval; pH×10 / cg/cm³ conversions documented; DescribeCoverage probe; graceful PROVIDER_UNAVAILABLE |
| CSV farmer observations import | ✅ | Strict row validation (unknown var, unit mismatch, bad dates, duplicates); blank→missing FARMER_BLANK; farmer_reported_record evidence; sha256+row provenance; template endpoint; idempotent |
| Source/product registry for all providers | ✅ | open_meteo (2 products), chirps (6 variants), soilgrids, farmer_csv, synthetic — with license/attribution/limitations |
| Provider health + coverage views | ✅ | Cached live probes (open_meteo ok / soilgrids degraded gracefully); `/fields/{id}/data-coverage` per variable+provider; UI provider picker with status dots, File imports card, Data coverage table |
| Data Passport per-source grouping | ✅ | Entries are per (variable, source product) — synthetic and real rows never share a label; readiness gates on best real entry; React key + era5_land product attribution fixed during verification |

## Feature A — Field Data Passport (first version)

| Task | Status | Notes |
|---|---|---|
| Per-variable coverage (counts, valid ratio, missing) | ✅ | |
| Provenance (provider/product/version, license, attribution) | ✅ | |
| Freshness + last retrieval | ✅ | |
| Quality warnings (aggregated with occurrence counts) | ✅ | |
| Analysis readiness rules (available/blocked + missing inputs) | ✅ | climate_summary, et0_only_summary available; water budget, rotation optimization, soil analysis honestly blocked |
| UI: Data Passport tab | ✅ | Empty state, field picker, variables grid, analyses with reasons |

## Testing

| Suite | Status | Count |
|---|---|---|
| Unit (geometry, area, variables, determinism, Open-Meteo, CHIRPS) | ✅ passing | 50 |
| Provider contract (synthetic, Open-Meteo, SoilGrids, farmer CSV) | ✅ passing | 37 |
| Integration (auth/tenant, CRUD, ingestion, imports, coverage, passport, migrations) | ✅ passing | 70 |
| **Total** | ✅ **157 passed** | `pytest tests` (~24 s, 2026-10-30) |

### Browser end-to-end verification (agent-browser, 2026-10-30)

- ✅ Auth gate renders; status line reports PostgreSQL 16.10 + PostGIS 3.5.0 connected
- ✅ "Enter demo workspace" seeds SYNTHETIC fixtures and lands in the workspace
- ✅ Overview stats (1 farm / 2 fields / 847.08 ha) and quick actions work
- ✅ Farms & Fields: farm list, field table (areas, boundary v1, observation counts), field detail with offline map preview
- ✅ Observations: synthetic ingestion job run live (job 4e6c4220) → 730 records; table/chart update
- ✅ Data Passport: AVAILABLE(6) → AVAILABLE(7) after ingesting `wind_speed_2m`; missing-variable list clears; overall status honestly stays "Partial" due to info-level SYNTHETIC_GAP warnings; blocked analyses list explicit missing inputs
- ✅ Zero console errors / zero page errors
- ✅ Mobile (390×844): no horizontal overflow on any tab; tab strip scrolls; footer sticks to viewport bottom with safe-area padding; long content pushes footer naturally (`mt-auto`)
- ✅ Desktop (1366×900): one-screen layout, footer flush at bottom
- Fixed during verification: Overview "Data Passport of …" button (`whitespace-nowrap`) forced the implicit grid column to min-content → horizontal overflow on mobile; button now wraps (`whitespace-normal`) and grid items got `min-w-0`

### Browser end-to-end verification — Milestone 3 (agent-browser, 2026-10-30)

- ✅ Provider switch in Observations (synthetic ↔ Open-Meteo) with status dots from live probes
- ✅ Model select (era5_land ~11 km vs era5 ~28 km) with per-model variable filtering (ERA5-Land shows 4 variables; wind/precip/ET0 correctly hidden)
- ✅ REAL Open-Meteo ingestion from the UI: job 5bd133b4, 365 soil-moisture records stored, honest reanalysis warning displayed
- ✅ Product attribution fixed during verification: `_product_for_provider` now resolves the model-specific product (era5_land vs era5) instead of the source's first product
- ✅ Data Passport: two soil_moisture_surface entries — `era5_land` (reanalysis_model_estimate, grid_cell @ 11132 m, CC BY 4.0) AND SYNTHETIC (synthetic_test_data) — never merged
- ✅ CSV upload through the browser: job e1d9eeb2 · farmer_csv · 3 rows (blank stored as missing), template download link works
- ✅ Data coverage panel: soil moisture 730 rows = 365 open_meteo + 365 synthetic with provider chips
- ✅ Live smoke against the real archive API: era5_land (124 rec) + era5 wind (31 rec, km/h→m/s), model mismatch → 422
- ✅ Zero page errors; mobile 390px: no horizontal overflow on any tab; sticky footer intact

## Not implemented (next milestones — deliberately)

- ✅ Open-Meteo historical provider (Milestone 3 — done)
- ✅ CHIRPS v3 import/extraction (Milestone 3 — done)
- ✅ SoilGrids WCS optional provider (Milestone 3 — done; WebDAV variant not needed)
- ✅ CSV observations import (Milestone 3 — done; soil-lab CSV waits for M4 soil history)
- ⬜ FAO GAEZ / crop-calendar reference imports (Milestone 3+, licensing review)
- ⬜ SoilGrids other depth intervals (Milestone 4 soil measurement history)
- ⬜ Feature runs / climate features / temporal aggregation (Milestone 4)
- ⬜ Crop knowledge base (Milestone 5)
- ⬜ Rotation optimizer + water intelligence + soil ledger (Milestones 6–7)
- ⬜ Stress testing lab (Milestone 8)
- ⬜ Farmer journal, advisor review, offline sync (Milestone 9)
- ⬜ NASA connectors — intentionally not implemented (future adapter; Master rule 8)

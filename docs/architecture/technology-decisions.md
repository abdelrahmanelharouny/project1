# Technology Decisions (resolved versions)

Master rule 5: verify current versions at implementation time and pin exact resolved versions.

## Backend (`mini-services/fieldshift-api/requirements.txt`, uv-pinned)

| Package | Version | Purpose |
|---|---|---|
| fastapi | 0.162.0 | HTTP API |
| uvicorn | 0.54.0 (+standard extras: uvloop, watchfiles, websockets) | ASGI server with auto-reload |
| sqlalchemy | 2.1.6 | ORM / Core |
| geoalchemy2 | 0.20.0 | PostGIS geometry columns + expressions |
| psycopg2-binary | 2.9.13 | PostgreSQL driver |
| alembic | 1.20.1 | migrations |
| pydantic / pydantic-settings | 2.14.2 / 2.16.2 | contracts + config |
| shapely | 2.2.0 | geometry validation/repair |
| pyproj | 3.8.0 | geodesic area (WGS84 Geod) |
| email-validator | 2.3.0 | (installed; edge validation is regex — see ADR-0008) |
| pytest / httpx | 9.2.0 / 0.28.1 | tests / TestClient |
| python-dotenv | 1.2.4 | .env support |

Python: 3.12.16 (sandbox venv, uv-managed).

## Database

- PostgreSQL **16.10** + PostGIS **3.5.0** (GEOS 3.13.0-CAPI-1.19.0, PROJ 9.5.1, LIBXML 2.12.7) — conda-forge user-space install (`db/pgenv`), cluster at `db/pgdata`, port 5433 (dev).
- UUID primary keys (`gen_random_uuid()` via app default), `JSONB` for genuinely variable metadata, CHECK constraints for enum-like columns, GIST spatial index on `fields.boundary`.

## Frontend

| Package | Version | Purpose |
|---|---|---|
| next | 16.1.3 (webpack dev mode — see KNOWN_LIMITATIONS #16) | app shell |
| react / react-dom | 19.x | UI |
| maplibre-gl | 6.16.0 | offline boundary map (worker served from /public) |
| @tanstack/react-query | 5.x | server state |
| tailwindcss | 4.x + shadcn/ui (New York) | design system |
| recharts | 2.15.4 | observation charts |
| zustand | 5.x | ephemeral UI state |
| sonner | 2.x | toasts |

## Deviations from the master spec's default stack (and why)

| Spec default | This slice | Reason | ADR |
|---|---|---|---|
| Vite React SPA | Next.js 16 (App Router) | repository/sandbox constraint; still React+TypeScript | 0001 |
| Docker Compose (Postgres/Redis/MinIO) | conda-forge user-space PostgreSQL+PostGIS; no Redis/MinIO yet | sandbox has no Docker/root; Redis/MinIO not needed for slice scope | 0002 |
| Celery workers | inline job execution with persisted job tables | slice scope; contract already queue-ready | 0006 |
| OR-Tools CP-SAT | not implemented yet | Milestone 6 | — |

## Milestone 3 additions (2026-10-30)

| Concern | Choice | Version | Rationale |
|---|---|---|---|
| Raster I/O (CHIRPS GeoTIFF extract) | `rasterio` | 1.5.2 (pinned) | Wheels install cleanly on Python 3.12; in-memory `MemoryFile` supports upload→extract without temp files; optional degradation if absent |
| Multipart uploads (CSV/GeoTIFF) | `python-multipart` | 0.0.32 (pinned) | FastAPI's required parser for Form/File endpoints |
| HTTP client (Open-Meteo / SoilGrids WCS) | `httpx` (already pinned) | 0.28.1 | Sync client with timeouts, `MockTransport` for network-free contract tests |
| Geometry ops for AOI centroid/bbox | `shapely` (already pinned) | 2.2.0 | Reused from the geometry validation module |

Live-provider facts verified at implementation time (recorded per Master version discipline): the Open-Meteo archive endpoint publishes temperature + 0-7 cm soil moisture for `era5_land`, while derived precipitation/ET0 and wind require `era5`; ISRIC SoilGrids REST is paused, WCS 2.0.1 on `maps.isric.org` is the documented path; CHIRPS v3 is distributed as rasters (no query API), so the workflow is upload + spatial-subset extraction.

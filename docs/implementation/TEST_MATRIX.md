# Test Matrix

All results below were actually executed on 2026-10-30. Command (from `mini-services/fieldshift-api`):

```
.venv/bin/python -m pytest tests
# => 157 passed, 9 warnings in ~17s
```

Frontend lint (from repository root):

```
bun run lint
# => clean (0 errors, 0 warnings)
```

## Environment under test

- Python 3.12.16, FastAPI 0.162.0, SQLAlchemy 2.1.6, GeoAlchemy2 0.20.0, Shapely 2.2.0, PyProj 3.8.0, Pydantic 2.14.2, httpx 0.28.1, rasterio 1.5.2 (M3)
- PostgreSQL 16.10 + PostGIS 3.5.0 (GEOS 3.13.0, PROJ 9.5.1), database `fieldshift_test` for integration tests
- Node: Next.js 16.1.3 (webpack dev mode), React 19, maplibre-gl 6.16.0

## Unit tests

| ID | Scenario | Expected | Result |
|---|---|---|---|
| U1 | Closed GeoJSON polygon accepted | normalized MultiPolygon, positive area, no warnings | ✅ |
| U2 | MultiPolygon accepted (2 parts) | both parts stored | ✅ |
| U3 | Feature wrapper tolerated | geometry extracted | ✅ |
| U4 | Output GeoJSON normalized, rings closed | MultiPolygon + closed rings | ✅ |
| U5 | Open ring rejected | INVALID_GEOMETRY "closed ring" | ✅ |
| U6 | <4-position ring rejected | INVALID_GEOMETRY | ✅ |
| U7 | Latitude >90 rejected | INVALID_GEOMETRY "latitude" | ✅ |
| U8 | Non-numeric coordinates rejected | INVALID_GEOMETRY | ✅ |
| U9 | Point geometry rejected | "Unsupported geometry type" | ✅ |
| U10 | Empty coordinates rejected | INVALID_GEOMETRY | ✅ |
| U11 | Degenerate area (<1 m²) rejected | "degenerately small" | ✅ |
| U12 | Bowtie self-intersection | repaired + warning, valid result | ✅ |
| U13 | Antimeridian-spanning ring | warning emitted (area guard permitting) | ✅ |
| U14 | 1°×1° square at equator | geodesic area 12,000–12,600 km² | ✅ |
| U15 | Area matches independent PyProj calc | <1e-6 relative difference | ✅ |
| U16 | Same square at 60°N smaller than equator | < 0.55× (cos 60°) | ✅ |
| U17 | bbox extraction | exact bounds | ✅ |
| U18 | Variable catalog: units (degC/mm/m3-m3) | match data dictionary | ✅ |
| U19 | Provider request: unsupported variable rejected | UNSUPPORTED_VARIABLE | ✅ |
| U20 | Provider request: inverted range rejected | INVALID_DATE_RANGE | ✅ |
| U21 | Provider request: empty variables rejected | UNSUPPORTED_VARIABLE | ✅ |
| U22 | Synthetic determinism: identical request → identical series | byte-equal observations | ✅ |
| U23 | Synthetic determinism: variable order irrelevant | per-variable series equal | ✅ |
| U24 | Different seed → different values | series differ | ✅ |
| U25 | All rows labelled synthetic (metadata + provenance) | is_synthetic, purpose, attribution | ✅ |
| U26 | Deterministic gaps → value=None + missing status + flags | no zero-fabrication | ✅ |
| U27 | Arid profile rainfall < 35% of temperate | profile separation sanity | ✅ |
| U28 | Outside coverage (2014 / 2025) rejected | INVALID_DATE_RANGE | ✅ |
| U29 | Unknown profile rejected | INVALID_DATE_RANGE "profile" | ✅ |
| U30 | >4-year request rejected | INVALID_DATE_RANGE "4 years" | ✅ |
| U31 | Five profiles registered | exact profile code set | ✅ |
| U32 | Native time support preserved (daily) | all rows daily | ✅ |

## Provider contract tests (Master §12)

| ID | Contract item | Result |
|---|---|---|
| C1 | Implements EnvironmentalDataProvider protocol (runtime_checkable) | ✅ |
| C2 | Returns valid canonical objects (re-validated via Pydantic, UTC timestamps, period ordering) | ✅ |
| C3 | Includes provenance (provider/product/version, attribution, limitations) | ✅ |
| C4 | Units match canonical catalog per variable | ✅ |
| C5 | Native temporal support preserved (daily) | ✅ |
| C6 | Missing/nodata: value None ⇔ quality_status missing | ✅ |
| C7 | No zero-fabrication for unknown; uncertainty stays unknown (None) | ✅ |
| C8 | Rejects invalid date ranges | ✅ |
| C9 | Rejects unsupported variables | ✅ |
| C10 | Idempotent rerun (equal outputs) | ✅ |
| C11 | Synthetic label mandatory on every row + provider code | ✅ |
| C12 | Coverage diagnostics (requested window, profile) | ✅ |
| C13 | Provider request identifier present | ✅ |

## Integration tests

| ID | Scenario | Expected | Result |
|---|---|---|---|
| I1 | Register creates user + org + token | 201, org + membership | ✅ |
| I2 | Duplicate email | 409 | ✅ |
| I3 | Login success/failure | 200 / 401 | ✅ |
| I4 | /me without token | 401 | ✅ |
| I5 | /me returns memberships | user + one org | ✅ |
| I6 | Logout revokes token | 204 then 401 | ✅ |
| I7 | Cross-tenant farm read | 403 | ✅ |
| I8 | Cross-tenant field read (field/passport/observations/map) | 403 ×4 | ✅ |
| I9 | Cross-tenant ingestion attempt | 403 | ✅ |
| I10 | Farm list scoped per org | other user sees 0 farms | ✅ |
| I11 | Unknown resource id | 404 (not 403) | ✅ |
| I12 | Farm create/get with normalization (eg→EG) | 201/200 | ✅ |
| I13 | Farm patch | renamed | ✅ |
| I14 | Farm list aggregates (field_count, total_area_ha) | correct | ✅ |
| I15 | Invalid country code | 422 | ✅ |
| I16 | Field create returns geodesic area (423 ha ±) | 410–440 ha | ✅ |
| I17 | PostGIS geography area matches stored area | <0.5% divergence | ✅ |
| I18 | Invalid geometry over HTTP | 422 INVALID_GEOMETRY + request_id | ✅ |
| I19 | Point geometry over HTTP | 422 INVALID_GEOMETRY | ✅ |
| I20 | Boundary versioning (v1→v2, change_reason) | versions listed 1,2 | ✅ |
| I21 | Map payload (crs, bbox, geojson, area_method) | exact bbox | ✅ |
| I22 | Field rename via PATCH | 200 | ✅ |
| I23 | Field list GeoJSON serializable | MultiPolygon | ✅ |
| I24 | Ingestion job succeeds (30d × 2 vars = 60 rows) | 202 → succeeded, counts correct | ✅ |
| I25 | Observations API filters (variable, window) + synthetic flag + units | correct totals | ✅ |
| I26 | Rerun ingestion does not duplicate (natural key) | total unchanged | ✅ |
| I27 | Unsupported variable fails fast at endpoint | 422 UNSUPPORTED_VARIABLE | ✅ |
| I28 | Unknown provider → 404 before job creation | 404 NOT_FOUND | ✅ |
| I29 | Out-of-coverage dates surface structured job failure (Master §12) | 202 + failed + error_summary | ✅ |
| I30 | Job state persisted (status, started/completed, warnings) | queryable | ✅ |
| I31 | Missing values stored as NULL with SYNTHETIC_GAP flags | non-null flags | ✅ |
| I32 | Job hidden from other tenants | 403 | ✅ |
| I33 | Empty passport: blocked + reasons | overall blocked, missing vars listed | ✅ |
| I34 | Filled passport: provenance + synthetic labels + period + freshness | all fields correct | ✅ |
| I35 | Analysis readiness honest (available vs blocked + reasons) | water/rotation/soil blocked with missing inputs | ✅ |
| I36 | Quality warnings surface (SYNTHETIC_GAP aggregated) | present with counts | ✅ |
| I37 | No composite confidence score in passport | key absent, note present | ✅ |
| I38 | Clean-database migration (drop→create→upgrade head) | tables + MULTIPOLYGON 4326 + postgis ext | ✅ |
| I39 | Downgrade base → re-upgrade roundtrip | succeeds | ✅ |

## Milestone 3 — providers & imports

Unit / contract (no network; httpx mocked, GeoTIFF fixtures built in-test):

| ID | Scenario | Expected | Result |
|---|---|---|---|
| M3-U1 | Open-Meteo year chunking | calendar-aligned, adjacent, no gaps | ✅ |
| M3-U2 | Variable map ↔ catalog units; wind km/h→m/s conversion | matches | ✅ |
| M3-U3 | Happy path mapping (mocked payload) | values, units, evidence, grid metadata | ✅ |
| M3-U4 | Upstream null → missing + OPENMETEO_NULL flag | never zero | ✅ |
| M3-U5 | Upstream error body / 5xx retry → structured provider errors | raised | ✅ |
| M3-U6 | Coverage clamp to archive lag; 1940 start guard | warning + clamp | ✅ |
| M3-U7 | Model-variable matrix: wind fails fast on era5_land; mixed request warns | 422 / warning | ✅ |
| M3-U8 | Open-Meteo full contract suite (protocol, provenance, units, idempotency) | all items | ✅ |
| M3-U9 | CSV parsing: valid rows → farmer_reported canonical observations | sha256 + row provenance | ✅ |
| M3-U10 | CSV blank value → missing + FARMER_BLANK; zero stays valid | no fabrication | ✅ |
| M3-U11 | CSV rejects unknown variable / unit mismatch / duplicates / bad rows | per-row warnings | ✅ |
| M3-U12 | CSV import via job persists; re-run idempotent via natural key | 3 rows, no dupes | ✅ |
| M3-U13 | CHIRPS GeoTIFF field extract (fixture raster) | mean, polygon_average, sha256 | ✅ |
| M3-U14 | CHIRPS nodata accounting + LOW_CELL_COVERAGE flag | 20% coverage flagged | ✅ |
| M3-U15 | CHIRPS all-nodata / wrong CRS / no intersection | structured 422, never zero | ✅ |
| M3-U16 | CHIRPS preliminary flag + monthly period bounds (leap) | correct | ✅ |
| M3-U17 | SoilGrids mocked WCS: Qmean/Q005/Q095 → value + 90% interval | 12.0 ± 4.0 g/kg | ✅ |
| M3-U18 | SoilGrids pH /10 and bulk density /100 conversions | documented in metadata | ✅ |
| M3-U19 | SoilGrids unreachable → PROVIDER_UNAVAILABLE (graceful) | other providers unaffected | ✅ |

Integration:

| ID | Scenario | Expected | Result |
|---|---|---|---|
| M3-I1 | `/data/providers/health` lists 5 providers with kinds/statuses/details | incl. rasterio flag | ✅ |
| M3-I2 | CSV template endpoint | text/csv attachment | ✅ |
| M3-I3 | CSV upload end-to-end + bad-row accounting (202, received/rejected) | job-shaped | ✅ |
| M3-I4 | CHIRPS upload end-to-end (202, extraction, satellite evidence) | observation stored | ✅ |
| M3-I5 | `/fields/{id}/data-coverage` per-variable/per-provider aggregation | counts + period + retrieval | ✅ |
| M3-I6 | Live Open-Meteo smoke (real API, era5_land + era5) | 124+31 records, conversions, 422 mismatch | ✅ |
| M3-I7 | Passport: same variable from two sources → two entries with own evidence/license | per-source honesty | ✅ |

## End-to-end (browser, agent-browser)

| ID | Flow | Result |
|---|---|---|
| E1 | Load `/` — auth screen renders (sign in / create account / demo) | ✅ |
| E2 | "Enter demo workspace" seeds + signs in | ✅ overview shows 1 farm / 2 fields / 847.08 ha / PostGIS chip |
| E3 | Farms & Fields — farm card, field table (areas 423.06/424.02 ha, versions, obs counts) | ✅ |
| E4 | Field detail — offline MapLibre map renders boundary polygon, 500 m scale, bbox, geodesic area label, boundary versions | ✅ (after worker fix) |
| E5 | Observations — run ingestion job from UI, job card, observations table with Valid + SYNTHETIC badges, temperature + precipitation charts | ✅ |
| E6 | Data Passport — overall status, aggregated warnings, variable cards (99% valid, counts), missing variable, analyses (available/blocked with reasons), attribution verbatim, notes | ✅ |
| E7 | Sticky footer present on short and long pages; responsive layout | ✅ |
| E8 | Console clean after fixes (no hydration errors, no failed API calls) | ✅ |
| E9 | M3 Observations: provider switch (synthetic ↔ Open-Meteo), model select, per-model variable filtering | ✅ |
| E10 | M3 REAL Open-Meteo ingestion from UI (era5_land, 365 records) with honest reanalysis warning | ✅ |
| E11 | M3 CSV upload via UI (template download, 3 rows → farmer_csv job, farmer-reported badge) | ✅ |
| E12 | M3 Coverage panel shows per-provider chips (soil moisture 730 = 365 open_meteo + 365 synthetic) | ✅ |
| E13 | M3 Passport shows TWO soil-moisture entries: era5_land (CC BY 4.0, reanalysis, grid_cell @ 11132 m) + SYNTHETIC | ✅ |
| E14 | M3 mobile 390px: no horizontal overflow on any tab, sticky footer intact | ✅ |

## Known warnings in test output

- Starlette deprecation: `HTTP_422_UNPROCESSABLE_ENTITY` renamed to `HTTP_422_UNPROCESSABLE_CONTENT` (cosmetic; aligned with FastAPI 0.162).

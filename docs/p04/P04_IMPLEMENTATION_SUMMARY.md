# P04 Implementation Summary — W3 UX Completion + Real NASA Satellite Acquisition

One integrated delivery on top of P03 W2 (`20ac4a0`). Two workstreams, one commit.

## 1. W3 UX work completed (P01 plan items 3.2 / 3.3 / 3.4 + W0.7 rollout)

| Item | What was done |
|---|---|
| Overview dedup (W3.2) | Overview's `FarmMap` card (exact duplicate of the Map & Satellite canvas) and `DataCoverage` chart (duplicate of the Data Hub → Observations coverage table) were removed. Kept: stat cards, DB-status card, setup/empty state, quick actions, `ClimateOverview` (unique cross-variable snapshot). Added a compact "Explore" card deep-linking to `geo:map` and the observations/coverage view. |
| Forecast verification (W3.4) | New "Verification" card in `cropintel:forecast` wires the previously dead `POST /api/v1/fields/{id}/forecast-verifications` endpoint (`useVerifyForecasts` mutation). Renders per-variable × horizon-bucket bias/MAE/RMSE with pair counts; **zero-pairs is a 200 empty response rendered as the backend's own limitations text verbatim** — nothing fabricated; loading/error/retry via the shared primitives. |
| State primitives (W0.7) | `SectionLoader` / `SectionSkeleton` / `ErrorState` applied to: satellite intelligence, forecast, overview charts (`climate-overview`, `data-coverage`), soil memory, observations (catalog error + coverage), data passport. |
| Reports/Analytics dedupe (W3.3) | The verbatim-duplicated `InlineError` and `NoOrgEmptyState` components were extracted to `p3/settings-shared.tsx` and both tabs now import the shared versions; an `ExportButton` (CSV/JSON) was added to the analytics benchmarks card. |
| Navigation stability | All nine destinations, nested URLs, legacy redirects unchanged (`tests/frontend/navigation.test.ts` 45/45). Data Hub gained one sub-page (`scenes`); the pinned sub-page count test was updated 30 → 31. |
| New UX regression fixes | None discovered beyond the above. |

## 2. Selected NASA source and why

**NASA HLS (Harmonized Landsat Sentinel-2) v2.0, via NASA CMR STAC + LP DAAC cloud assets.**

- HLSL30 (Landsat 8/9 OLI) + HLSS30 (Sentinel-2 MSI harmonized by NASA; Sentinel-2 itself is ESA/Copernicus, never described as a NASA satellite), both resampled to a **30 m** grid with consistent band naming and a single 0.0001 reflectance scale — one adapter covers two constellations with a ~2–4 day effective combined revisit.
- **Standards-based discovery**: CMR STAC (`https://cmr.earthdata.nasa.gov/stac/LPCLOUD`, collections `HLSL30_2.0` / `HLSS30_2.0`) — unauthenticated metadata search with bbox/datetime/cloud filtering and search-after pagination. Live-verified in the sandbox (230 real scenes for the demo field).
- **Open license** (NASA open data policy; attribution required); Earthdata Login (free) only for asset reads.
- **Fmask** QA layer enables honest cloud/shadow/cirrus/snow masking.
- Rejected for the first operational source: raw Landsat Collection-2 (same 30 m but per-scene scaling differences, weaker cloud QA), MODIS/VIIRS (250 m–1 km, too coarse for parcel work), SMAP (~9–36 km — **cannot** support parcel-level soil-moisture claims; documented explicitly as a future coarse-resolution context product only).

Product limitations are persisted in code, in the provider registry details, in the seeded `data_sources.known_limitations`, and surfaced in the UI provenance note: HLS is an atmospheric-corrected estimate, cloud gaps are real, sub-field variability claims are refused below the zonal pixel threshold, and HLS provides no parcel-level soil moisture.

## 3. Implemented acquisition flow

```
POST /api/v1/fields/{id}/satellite/discovery        (operator role)
  → NasaHlsProvider.search_scenes → CMR STAC (public, metadata only,
    retries + backoff, search-after pagination, hard page caps)
  → scenes upserted idempotently on (field, provider, scene_id)
    with acquisition_status='discovered'

GET  /api/v1/fields/{id}/satellite/scenes           (membership)
  → paginated catalog, status filter (COALESCE legacy NULL → 'ready')

POST /api/v1/fields/{id}/satellite/acquisitions     (operator role, 202)
  → groups scenes per HLS collection (one job per collection keeps
    provenance unambiguous), creates idempotent ingestion jobs on the
    existing background infrastructure, marks scenes 'queued';
    double-submit replays the same job; failed jobs are retryable
    with a fresh salted idempotency key

POST /api/v1/jobs/{job_id}/cancel                   (operator role)
  → cancels a still-queued job (BackgroundJob + IngestionJob) and
    releases its scenes back to 'discovered'; running jobs reject 409

Ingestion hooks (existing pipeline, generic):
  queued → running (scene rows follow) → provider fetch_observations
  (per-scene: /vsicurl/ COG range reads with EDL bearer/basic auth env,
  HLS DN×0.0001 scaling, shared per-pixel index math, Fmask masking,
  zonal stats) → observations persisted via the natural-key idempotent
  path → scenes 'ready'; scenes the provider did not return → 'failed'
  with the provider warnings embedded in acquisition_detail.
```

Direct `POST /data-jobs` with `provider_code=nasa_hls` also works (`scene_ids` plumbing added; bounded auto-discovery fallback capped by `nasa_hls_max_scenes_per_job=30`).

### What is real vs not (honesty record)

- **Live-verified in this sandbox**: CMR STAC discovery (real scenes: e.g. `HLS.S30.T36RUV.2026309T083041.v2.0`, HLSS30, 51 % cloud); the full scene lifecycle discovered → queued → running → failed in the UI; failure detail carries the actual `RasterioIOError` from the real `/vsicurl/` attempt against the protected LP DAAC asset.
- **Implemented but NOT live-tested**: authenticated asset reads / index derivation (no NASA Earthdata credentials here — env vars `CROPTWIST_EARTHDATA_USERNAME` / `CROPTWIST_EARTHDATA_PASSWORD` or `CROPTWIST_EARTHDATA_BEARER_TOKEN`). The pixel path is exercised by tests with deterministic in-memory rasters through the same code path (real index math, real Fmask masking, real zonal statistics); only the network transport is mocked.
- No synthetic/simulated data is ever labelled as real; `satellite_sim` remains explicitly synthetic.

## 4. Data, provenance and storage design

- **Metadata in PostgreSQL/PostGIS**: `satellite_scenes` extended (additive migration `0021_p04_satellite_acquisition`) with `acquisition_status` (CHECK-constrained), `acquisition_detail` JSONB, `discovered_at`, `acquisition_updated_at`, plus a partial index. Index values stay in `observations` with full canonical provenance (`satellite_derived_estimate`, per-scene metadata incl. collection, platform, cloud %, asset hrefs, zonal stats).
- **No raster binaries in relational tables**: assets are registered by reference (`asset_refs` JSONB with the LP DAAC COG hrefs incl. Fmask); pixels are read via HTTP range requests inside ingestion jobs only — nothing large is downloaded during discovery and nothing binary is persisted. This reuses the established storage pattern (facts in JSONB, processing in-memory); object storage remains a P05+ deployment concern, kept pluggable by keeping asset refs and reads behind the provider adapter.
- **Credentials**: settings-only (`pydantic-settings`, `CROPTWIST_*` env), never hardcoded; bearer token minting from username/password with GDAL basic-auth fallback; registry health details expose only a boolean `earthdata_credentials_configured`.
- **Operational reliability**: bounded jobs (≤30 scenes, per-collection grouping), retries/backoff on CMR 5xx, per-scene degradation (one unreadable scene never fails the batch), idempotent re-ingestion via the observation natural key, job status via the existing `/jobs` endpoints, structured logs + `record_ingestion` metrics, crash recovery via the registered `ingestion` replay executor.

## 5. Frontend integration

- New **Data Hub → Scene catalog** sub-page (`?tab=datahub&sub=scenes`): provenance note, discovery form (date range, cloud limit), catalog table with real status badges (discovered/queued/running/ready/failed + failure tooltips), per-row Acquire/Cancel and bulk "Acquire all discovered (NDVI)", pagination, honest empty/error/loading states, role-gated actions (`roleAtLeast(org.my_role, 'operator')`), desktop table + mobile cards. No index values are ever rendered here.
- **Map & Satellite**: satellite intelligence card gets shared state primitives and an "Open scene catalog" link that carries farm/field context through the shared URL sync (verified end-to-end).
- Command palette picks up the new section automatically ("Data Hub · Scene catalog").
- i18n: new `scenecatalog` namespace + keys in `destinations`/`satellite`, full en/ar parity, RTL verified.

## 6. Verification results (exact commands, all freshly executed)

Backend (`.venv/bin/python -m pytest`, slices via the new `scripts/run_test_slice.sh` helper — the sandbox's overlay filesystem transiently exhausts inodes during the suite's truncate storms, so the test DB is dropped between slices; a helper script does this):

- `pytest tests/unit` (3 slices) — **exit 0 each**
- `pytest tests/contract` (2 slices) — **exit 0 each** (incl. the 16 new HLS contract tests)
- `pytest tests/integration` (12 slices, all 39 files incl. `test_satellite_acquisition.py` 14 tests, `test_ingestion`, `test_p2_intelligence`, `test_background_jobs`, `test_migrations`, `test_auth_tenant_isolation`, `test_p3_*`, …) — **exit 0 each**
- New P04 tests: 40 passing (10 catalog unit + 16 contract + 14 integration).

Frontend:

- `bunx tsc --noEmit` — **exit 0**
- `bun run lint` — **exit 0**
- `bun test tests/frontend/navigation.test.ts` — **45 pass / 0 fail**

Browser (agent-browser, demo workspace):

- 1440×900: Overview dedupe (map card gone, Explore links work); scene catalog renders; **live discovery found 230 real NASA HLS scenes** and listed them with product/cloud/status; acquisition of a real scene ran queued → running → **failed** with the truthful LP DAAC `RasterioIOError` in `acquisition_detail` (no Earthdata credentials configured); forecast verification card runs and shows the honest zero-pairs limitations text; reports + analytics tabs render.
- 390×844: no horizontal overflow; deep link `?tab=datahub&sub=scenes` survives login; mobile card layout with real scene rows.
- RTL (`NEXT_LOCALE=ar`): `dir=rtl`, Arabic scene-catalog strings, no overflow.
- Legacy URLs: `?tab=satellite` → `?tab=geo&sub=map`; `?tab=management` → `?tab=cropintel&sub=plan` (permanent redirects intact).
- Command palette: Ctrl+K lists "Data Hub · Scene catalog"; Escape closes and restores focus.

## 7. Remaining blockers / prerequisites for P05

1. **NASA Earthdata Login credentials** (free) injected as `CROPTWIST_EARTHDATA_*` in the deployment secret manager — required before authenticated downloads / real index derivation can be live-verified.
2. **Object storage decision** for P05 preprocessing outputs (currently assets are read-in-place by reference; any derived rasters need an object store — S3-compatible — plus a small asset-store adapter).
3. **Durable worker separation**: the executor is in-process/thread-based (single replica); P05's heavier raster work should move to an external worker (Redis/queue) — the `BackgroundJob` table and HTTP contract already support it unchanged.
4. **GDAL version note**: bearer-token COG auth uses `GDAL_HTTP_HEADERS` (GDAL ≥ 3.6; sandbox has 3.12); the basic-auth fallback covers older GDALs.
5. **Per-collection job grouping UX** (currently transparent) may deserve a combined progress view once S30+L30 acquisitions become common.
6. Inode-friendly CI: run backend suites with the `scripts/run_test_slice.sh` helper (or fix the sandbox overlay) — full-suite single runs intermittently exhaust the container's 655k-inode overlay budget.

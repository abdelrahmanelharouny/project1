# P05 + P06 Implementation Summary — Geospatial Preprocessing & Field-Level Satellite Intelligence

Date: 2026-11-13 · Scope: P05 (geospatial preprocessing platform) + P06 (field-level satellite
intelligence), delivered on top of P04 (`925f3b5`, CMR STAC discovery + acquisition lifecycle).

## 1. Implemented pipeline

`app/geospatial/preprocessing.py` (pure, testable) + `app/data_platform/processing/service.py`
(orchestration) turn cataloged HLS scenes into derived index products:

```
validate scene -> windowed COG read (CRS-correct, bbox of the authorized field geometry)
  -> HLS v2.0 scaling (DN * 0.0001) -> Fmask masking (cirrus/cloud/shadow/snow excluded;
  water/adjacency recorded, not excluded) -> nodata => NaN (never zero)
  -> per-pixel indices -> field-masked zonal statistics + tercile zones
  -> COG + fixed-colormap preview PNG into object storage
  -> raster_assets rows + honest observation upsert (single transaction)
```

Key guarantees: windowed range reads only (no full-scene download, no full-scene in-memory
arrays); the EPSG:4326 field geometry is reprojected into the raster CRS with pyproj (the
raster CRS is never silently assumed); band grids aligned against one reference window
(documented `band_alignment` provenance, bilinear for reflectance / nearest for QA); all
transformations versioned by `processing_version` (`hls-derivation-1.0.0`) and
`software_version` (`croptwist-geospatial-1.0.0`); formula, band mapping, scaling/masking
rules, CRS, resolution, valid-pixel %, and quality summaries persisted per product.
`processing_version` change triggers recomputation; historical derived products are preserved.

Scene validation (C1) rejects incompatible inputs with explicit reasons (missing assets/band
mapping, wrong product/version, no acquisition time, unusable geometry); checksums verified
where the source provides them.

## 2. Supported indices and scientific limitations

| Index | Formula source | Notes / limitations |
|---|---|---|
| NDVI | Rouse et al. 1974 | saturates at high biomass |
| EVI | Huete et al. 2002 coefficients | HLS L30 blue band (Landsat) is noisier; coefficients are the documented generic EVI set |
| NDMI | Gao 1996 | SWIR1-based canopy water proxy |
| NDWI | McFeeters 1996 | surface-water/open-water variant (explicitly named, not MNDWI) |
| BSI | Rikimaru 2002 / Chen 2004 | computed only when all four surfaces (SWIR1, Red, NIR, Blue) exist at native 30 m |

All formulas, band mappings and validity ranges live in `app/vegetation/indices.py`
(`INDEX_FORMULAS`, `INDEX_REQUIREMENTS`, `INDEX_VALID_RANGE`); out-of-range values become
None + flag, never clamped. Fmask handling per HLS v2.0 product documentation
(`FMASK_EXCLUDE_MASK` bits 0/1/3/4). SMAP was never treated as parcel-level soil moisture; no
soil-moisture product is derived from HLS.

## 3. Storage and worker decisions

- **Storage** (`app/geospatial/objectstore.py`): tiny protocol (put/exists/stat/read/delete/
  signed_url) with two backends — `LocalStorage` (atomic temp+rename, dev root
  `CROPTWIST_RASTER_STORAGE_ROOT`) and `S3Storage` (boto3 lazy import, any S3-compatible
  store, credentials only via env/secret manager, optional SSE-KMS). Stable tenant-isolated
  keys `org/{org}/field/{field}/{source|derived|preview}/...` — source NASA assets and
  CropTwist-derived products live in disjoint namespaces; no-overwrite semantics; magic-byte +
  size + checksum validation before acceptance; HMAC-signed controlled local download route,
  S3 presigned GETs (30 s–1 h). PostgreSQL stores references/checksums/georeferencing/quality/
  provenance only — binary never enters relational storage (`raster_assets` migration `0022`).
- **Workers** (`app/worker.py`, `python -m app.worker`): standalone process (no HTTP),
  reuses the existing `background_jobs` contract; durable rows are the source of truth;
  restart recovery replays `queued` rows via `register_kind('raster_processing', ...)` and
  fails stale `running` rows loudly; graceful SIGTERM/SIGINT drain; configurable concurrency
  (`--workers` / `CROPTWIST_JOB_WORKERS`); API requests only enqueue/inspect (202 pattern) —
  never raster work in-request. Idempotency: partial unique index on active
  (scene, version, indices-digest) + natural-key uniqueness on raster_assets + observation
  upgrade/supersede semantics. Domain job rows (`raster_processing_jobs`) carry progress,
  stage, error detail, warnings and timestamps.
- Deliberately **not** introduced: a distributed queue (Postgres-backed jobs satisfy
  durability at current scale); documented in KNOWN_LIMITATIONS.md.

## 4. Field-level intelligence integration (P06)

- `app/vegetation/field_profile.py` — unified, honest field satellite profile (versioned
  `field-satellite-profile-1.0.0`): latest valid observation, timeline (valid-only; excluded
  observations counted, never hidden), baseline comparison (delta, z, weak-evidence flag),
  OLS trend, spatial variation + statistical tercile zones, coverage gaps (no interpolation,
  ever), freshness window (45 d), explicit `insufficient_evidence` status with reasons when
  < 2 valid observations or sub-threshold pixel support. Layer discipline is explicit
  (`interpretation_levels`): measurement → derived indicator → statistical interpretation;
  agronomic recommendations only via existing engine contracts.
- Evidence pack (`app/intelligence/evidence.py`): new `vegetation` section with full
  measurement provenance (scene id, resolution, cloud, valid-pixel fraction, processing
  version) and NASA attribution; lands in `data_gaps` when absent.
- Evidence quality (`app/recommendations/evidence_quality.py`): `spatial_resolution`
  component computed from real scene metadata when satellite evidence exists (otherwise
  declared not-computable — never fabricated).
- Recommendation generator (`vegetation_condition_context`): deterministic, quality-gated
  condition-context signal ONLY on strong, fresh, well-supported NDVI decline (z ≤ −1.5,
  fresh ≤ 45 d, ≥ 5 valid pixels, not flagged weak); de-duplicated against the monthly
  stress engine (one observation, one vote); insufficient evidence emits INFO with reasons,
  never an advisory; confidence comes only from the evidence-quality heuristic.

## 5. Frontend (Workstream F)

Extends existing destinations only (`?tab=geo&sub=map`, `?tab=datahub&sub=scenes`):
- **Map & Satellite**: "Satellite layers" card (index + scene-date selectors, opacity slider,
  show/hide, documented-colormap legend with NDVI labels, provenance incl. SYNTHETIC badge,
  resolution, processing version, valid-pixel %, cloud %); backend-rendered preview PNG drawn
  on the farm map as a georeferenced raster overlay (MapLibre image source, north-up corner
  order); honest states (skeleton/error/empty-with-link; unavailable products are visibly
  unavailable). Field satellite profile section: timeline chart (documented Y range),
  freshness badge, valid/excluded counts, insufficient-evidence banner, baseline comparison
  with weak-evidence note, trend, statistical zones, coverage gaps, provenance with checksums.
- **Data Hub → Scene catalog**: processing ledger (unprocessed/processing/processed/failed
  badges with stage %, error tooltips + sr-only), operator-gated "Process NDVI"/"Retry"
  actions offered ONLY for pipeline-eligible scenes (real `nasa_hls` + labeled `fixture_demo`;
  other providers never see the affordance), 202 toasts for queued/skipped.
- English + Arabic/RTL parity verified (75 new keys per namespace).

## 6. Exact verification results

Backend (venv, PostgreSQL 16.10 + PostGIS): P05 unit tests `tests/unit/test_geospatial_preprocessing.py`
+ `tests/unit/test_objectstore.py` → **41 passed** (windowed reading, index formulas vs known
numeric examples incl. BSI, Fmask masking, nodata, zones, COG/PNG writing, scene validation,
provenance; storage contract, payload validation, key safety/path traversal, signed URLs,
S3 fake-client). P05 integration `tests/integration/test_satellite_processing.py` +
`tests/integration/test_field_profile.py` → **27 passed** (end-to-end fixture processing,
double-submit replay, reprocess skip, observation upgrade/supersede, synthetic/foreign
refusal, cancel, failure detail, restart replay, API authz/tenant isolation, profile honesty,
evidence integration, evidence-quality spatial component, condition-context gating +
de-duplication). Regression surface (files touched by P05): p2_intelligence,
background_jobs, ingestion, satellite_acquisition, recommendation_refresh_dedupe,
feature_runs, decision_comparisons, farms_fields_crud, cross_module_integration,
imports_and_coverage, advisor, ai_golden_cases, anomaly_seasonal, arabic_narratives,
auth×2, cover_crop, data_passport, deepening, erosion, field_states, feedback, knowledge×2,
management_plan, operations, residue, rotation×2, scenarios, sensitivity, soil, soil_cover,
water, evidence_quality, vegetation_intelligence, p2_cores, nasa_hls_catalog,
synthetic_determinism, geometry_validation, numeric_guard — **all passed** (water suite
re-run standalone after an unrelated transient DiskFull during a killed batch run: 17 passed).

Performance (`scripts/measure_processing_perf.py`, deterministic 40×40 fixtures, 30×28 field
window @30 m EPSG:32636, 5 indices): clean case **0.118 s** wall (read 0.059 / derive 0.018 /
COG+PNG 0.041); cloud case **0.057 s** with 42/840 Fmask-masked pixels. tracemalloc peak is
dominated by GDAL/rasterio library overhead (fixture-scale; real-scene peak depends on
window size, capped by `CROPTWIST_RASTER_MAX_FIELD_WINDOW_MB`).

Frontend: `bunx tsc --noEmit` clean · `bun run lint` clean · `bun test tests/frontend/` →
**45 pass / 0 fail** · `scripts/e2e_smoke.py` → **ALL CHECKS PASSED** (24.6 s) · standalone
worker smoke (`python -m app.worker --workers 1 --idle-exit-seconds 4`) → starts, registers
replay kinds, drains, exits 0.

Browser (agent-browser, Chromium): 1440×900 + 390×844, English + Arabic (RTL verified:
mirrored layout, Arabic terminology, map/chart LTR islands preserved). Verified live: legacy
deep link `?tab=satellite` → permanent redirect `?tab=geo&sub=map`; layers card index/date
selection, opacity, show/hide toggle (overlay pixels confirmed in fetched preview PNG:
NDVI 0.67 → green RGB(67,152,80), −0.09 → near-white; masked = transparent); profile
timeline/zones/provenance render; scene ledger states + eligibility-gated actions; no
console errors (only the pre-existing, out-of-scope Select controlled/uncontrolled warning);
sticky footer correct at both widths.

## 7. Live NASA verification status

Earthdata credentials remain **unconfigured** in this environment (no env vars, no secret
store). Therefore: CMR STAC **discovery** was live-verified in P04; **authenticated asset
download and real-scene preprocessing have NOT been executed** and are not claimed. All
processing logic is verified against deterministic raster fixtures (explicitly labeled
`is_synthetic=true`, provider `fixture_demo`, evidence_class `synthetic_test_data`,
never mixed with real `nasa_hls` scene identity). The production acquisition adapter and
credentials plumbing (env-based bearer token flow) are complete and await credentials.

## 8. Remaining concrete blockers

1. **Earthdata credentials** (bearer token via env `CROPTWIST_EARTHDATA_BEARER_TOKEN` /
   token-endpoint flow) — required for the first controlled real-scene acquisition +
   preprocessing run.
2. **Production object store** — set `CROPTWIST_RASTER_STORAGE_BACKEND=s3` + bucket/region/
   credentials via secret manager; nothing in code blocks this.
3. **Worker deployment** — run `python -m app.worker` alongside the FastAPI service
   (systemd/container) with concurrency sized to host memory; Postgres-backed jobs require no
   extra infrastructure.
4. **P05+ future**: histogram clipping for realistic previews of full-scene distributions is
   unnecessary for field windows but revisit if scene-scale products are added.

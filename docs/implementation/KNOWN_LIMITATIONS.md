# Known Limitations

Honest record of what this slice does NOT do. Nothing here is claimed to work.

## Data and providers

1. **Synthetic fixtures are fixtures.** The synthetic provider's profiles are invented shapes — zero agronomic validity, always `is_synthetic=true`. Real sources now exist alongside (item 2) but the fixture rule is unchanged.
2. **Real providers connected in Milestone 3** — Open-Meteo archive (ERA5-Land/ERA5, live-verified), CHIRPS v3 upload+extract, SoilGrids WCS (optional), farmer CSV. Remaining gaps: **no NASA connectors** (intentional, Master rule 8); **no FAO GAEZ / crop-calendar imports yet**; **no live SoilGrids/WCS data in the sandbox verification** (mocked contract tests + graceful degradation verified; the sandbox could not complete a real WCS round-trip); **CHIRPS has no bulk download pipeline** (operator supplies GeoTIFFs); Open-Meteo uses the field **centroid cell only** (no within-field gradient); SoilGrids ingests **0-5 cm only** until Milestone 4 adds depth-aware soil history.
3. **Minimal raster pipeline**: CHIRPS extraction does nodata masks + pixel-coverage accounting for uploaded single-band GeoTIFFs only. No raster asset storage, resampling metadata, or multi-band/time-series raster handling yet.
4. **No unit conversion engine yet**: observations are stored in the catalog unit they arrive in; the versioned conversion registry arrives with the variable registry (Milestone 4).
5. **No soil sample intake**: `soil_analysis` is honestly reported blocked.

## Intelligence

6. **No features, no water balance, no rotation optimization, no stress testing.** The Data Passport blocks these analyses with explicit missing-input lists instead of simulating them.
7. Passport "valid coverage" thresholds (0.8) are engineering defaults for the readiness rules, not agronomic requirements.

## Security and operations

8. **Password hashing iterations are lowered for sandbox CPUs** (120k PBKDF2 vs. OWASP-recommended ≥600k for production); token TTL is 12 h; no refresh-token rotation yet.
9. **No rate limiting** on exposed endpoints; no file upload scanning (no uploads exist).
10. **CORS is disabled by default** (same-origin only via gateway). Production must set `CROPTWIST_CORS_ALLOW_ORIGINS` to approved origins.
11. **No background worker queue**: ingestion executes inline within the request (jobs remain 202-shaped, so the contract survives moving to workers).
12. **In-memory metrics counters** are per-process; durable observability comes from structured logs + job tables.

## Frontend

13. **No PWA/offline mode** yet; no i18n/RTL yet (architecture-ready, English only).
14. The map is a fully offline boundary preview (dark background, no basemap tiles) because the sandbox cannot guarantee third-party tile availability. Production should add a self-hosted or licensed basemap.
15. GeoJSON is entered via paste/example; there is no interactive polygon drawing yet.

## Engineering

16. `next dev` runs in **webpack mode** (not Turbopack) because Turbopack compile workers caused OOM kills in the 4 GB sandbox. Revisit when the deployment environment has more memory.
17. The maplibre worker file is copied to `public/` and wired via `setWorkerUrl` because webpack dev does not resolve MapLibre's ESM worker URL.
18. The conda-forge PostgreSQL cluster is a dev convenience; backups, monitoring, and least-privilege credentials are production tasks.
19. No CI pipeline configuration yet (tests run locally; `docs/implementation/TEST_MATRIX.md` records exact commands and outcomes).

## Explicitly out of scope (per spec)

- Any real-world agricultural recommendation, yield guarantee, or prescription.
- Any use of synthetic observations as evidence for agronomic conclusions.

## Milestone 5 (knowledge base & rotation intelligence)

- Seed-pack trait values are hand-transcriptions of the cited printed tables
  (FAO-56, EcoCrop); every value is `validation_status="reference"` pending the
  agronomist review workflow. Transcription errors are possible — the citation
  is always shown next to the value.
- Calendar windows are `reference_synthesized` coarse contexts (not station
  data) and require regional calibration before operational use.
- No rule in the seed pack is `confirmed_regional`; rotation breaks are
  therefore advisory everywhere until a regional expert confirms them.
- Crop water figures are FAO-56 single-Kc screening estimates (sowing assumed
  at season start; monthly ET0 climatology as a historical proxy) — superseded
  by the M7 daily water balance.
- Economics is evaluated only from farmer-supplied margin indices; the platform
  never estimates prices or yields.
- Candidate climate ranges are ANNUAL EcoCrop amplitudes compared against
  season climatology — a coarse screening signal, documented as such.
- The decision core is per-field in this slice (crop history and water
  allocation are field/farm scoped); multi-field farm-level rotation arrives
  with the water intelligence milestone.
- Variety-level traits are representable (model + tests) but the seed pack is
  species-level; no cultivar data is bundled.


## Deepening program additions (2026-10-31)

- SoilGrids "uncertainty" is the mean of per-pixel Q05–Q95 half-widths —
  explicitly NOT a field-level 90% prediction interval (F-08; S-1 backlog).
- Feature baselines < 30 years are labelled `short_record_exploratory`, never
  WMO climatological normals (F-11).
- CHIRPS daily products may be pentad totals disaggregated with ERA5/IMERG
  daily information — CHIRPS-daily and ERA5-daily are not independent
  evidence (F-12).
- Solver statuses: MODEL_INVALID/UNKNOWN are reported as solver failures, not
  infeasibility; run-level "optimal" requires every profile proven optimal
  (F-04).
- Roles are defined but not yet enforced on routes (B-1); knowledge imports
  are audited but not role-gated.
- External agronomic validation remains OUTSTANDING for all seed knowledge
  (zero confirmed_regional rules by design).
- Full backlog: `docs/deepening/KNOWLEDGE_GAPS_AND_RESEARCH_BACKLOG.md`.

## Milestone 6A additions (2026-10-31)

- Water planning is SEASONAL screening, not irrigation scheduling: daily
  water accounting, irrigation-event timing and depletion-avoidance
  scheduling are backlog W-7. The root-zone balance runs a RAINFED trajectory
  (no irrigation events) to size the soil-water contribution; this is
  disclosed in every plan.
- ET0 is consumed from the provider product only (ERA5, FAO-56 reference
  surface). No local ET0 computation exists (no radiation/humidity evidence
  contract; backlog W-6). ETc therefore inherits the provider's reanalysis
  uncertainty.
- Effective rainfall: FAO I&D 33 formula on MONTHLY totals (slope condition
  4–5% disclosed). USDA-SCS is NOT implemented (coefficients unverified in
  the M6A Phase-0 programme — backlog W-5). Daily Pe variants are not
  implemented.
- Dual-Kc (Kcb + Ke) is refused: no sourced Kcb rows exist (FAO-56 ch. 7
  machinery documented; inputs absent).
- Soil water-holding inputs: farmer-measured values are used as supplied
  (farmer_reported_record, not independently verified); the Saxton-Rawls
  (2006) PTF path is a texture-based MODEL estimate over the latest soil
  observations — when those come from SoilGrids they describe the 0–5 cm
  layer ASSUMED representative of the root zone (single-layer extrapolation,
  backlog S-6). No bulk-density correction is applied; OM is set to 0 when no
  SOC observation exists (disclosed). PTF estimates outside the published
  validity domain are refused, never extrapolated.
- Surface soil moisture (ERA5-Land 0–7 cm) is never used as root-zone
  storage — the deepening rule is preserved; the balance requires explicit
  θFC/θWP/Zr.
- Rooting depth uses the midpoint of the FAO-56 Table 22 range (disclosed);
  stage-wise root development is not modelled. Initial depletion assumed 0 mm
  (field capacity at sowing) — a measured initial water content refines this.
- Capillary rise and groundwater contribution are not modelled (no evidence;
  disclosed in every plan).
- Actual irrigation applied is "unknown" until farmer irrigation-record
  ingestion exists (backlog W-8); the ladder never infers it.
- Candidate-level NIR (rotation flow) omits the soil-water contribution (no
  soil context at candidate time) and is labelled an upper bound; the
  dedicated water planner computes the full ladder.
- The Kc curve holds the late-stage (end) Kc for season windows longer than
  the digitized curve (M5-consistent convention, documented).

# Implementation Status

Last updated: 2026-11-01 (Milestone 7.1 — field state foundation & snapshot hygiene)

Legend: ✅ done · 🔄 in progress · ⛔ blocked · ⬜ not started

## Milestone 0 — Repository audit and decisions

| Task | Status | Notes |
|---|---|---|
| Inspect repository, git state, existing stack | ✅ | Next.js 16 + TS + Tailwind + shadcn template; Prisma/SQLite scaffolding; no prior CropTwist work |
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

## Milestone 3 — Focused engineering audit (2026-10-31)

| Area | Verdict | Fixes applied |
|---|---|---|
| Live-doc verification | ✅ | Open-Meteo model/variable matrix, CHIRPS pentad calendar, SoilGrids WCS naming/CRS all probed against the LIVE services |
| SoilGrids provider | ❌→✅ **was broken against live service** | live coverage IDs (`<family>_0-5cm_mean/_Q0.05/_Q0.95`), per-property `map` param, WCS 1.0.0 EPSG:4326 path, soc dg/kg ÷10 unit fix, field-polygon masking + cell accounting, CRS validation |
| CHIRPS extractor | 2 defects | pentad 26–end-of-month bounds (CHC-verified), sub-grid field all_touched fallback with `CHIRPS_SUBCELL_FIELD` flag |
| Open-Meteo provider | 1 hardening gap | non-native model variables are never requested (no possible silent ERA5/ERA5-Land mix); chunk non-overlap regression test |
| Farmer CSV | 1 gap | timestamp rows rejected; local calendar-date basis recorded (`date_interpretation` metadata) |
| Provenance schema | 2 gaps | `observations.evidence_class` + `observations.ingestion_job_id` persisted (migration 0002) and surfaced in API + Data Passport |

Full findings with live-probe evidence: `docs/implementation/M3_AUDIT_GAPS.md`.
Regression suite grew 157 → 184 tests (SoilGrids request-shape/masking/unit tests, CHIRPS pentad + subcell tests, Open-Meteo gating + chunk tests, CSV date tests, provenance-column integration tests).

## Milestone 4 — Processing & feature engineering (2026-10-31)

| Task | Status | Notes |
|---|---|---|
| Versioned feature definitions | ✅ | `FeatureDefinition` table + `featurespec-2026.11.0-m4` catalog: 26 features, each with unit, aggregation levels, required variables, min-coverage policy and cited formula reference; catalog endpoint `/features/catalog` |
| Reliable aggregation | ✅ | daily / monthly / seasonal / crop-season strategies: identity, accumulation, mean (+SE), ETCCDI-style counts, dry-spell runs, difference (P−ET0), anomaly, z-score, seasonal CV |
| Explicit timezone & calendar | ✅ | runs carry `calendar_timezone` (farm default) + `hemisphere`; daily observations assigned by documented midpoint rule (`period_midpoint_local_date`); offset-invariance property tested, extreme-offset (Auckland) bucket shift tested |
| Baselines & anomalies | ✅ | calendar-month climatology embedded per value (`baseline_reference`); ≥5 distinct years required, else `not_evaluated` with the reason in provenance |
| Rainfall variability / dry-spell / temperature / heat indicators | ✅ | WMO dry-day (<1 mm) spells with gap interruption (a data gap is never assumed dry); ETCCDI FD0/TR20; hot days ≥35 °C explicitly labelled a generic meteorological index |
| Soil moisture & ET0 features | ✅ | monthly means/anomalies and ET0 totals where a compatible source exists; P−ET0 labelled climatic balance, NOT a crop water budget; crop-specific heat stress stays unevaluated until the sourced knowledge base (M5) |
| Missing-data & minimum-coverage policies | ✅ | per-definition `min_coverage_ratio` (0.9 sums / 0.8 means); below → NULL + `insufficient_coverage`; missing never zero-filled; totals never scaled up |
| Uncertainty & quality propagation | ✅ | quality enum valid/partial/insufficient_coverage/missing/not_evaluated; standard error of the mean on mean features; input evidence classes + processing versions carried into value provenance |
| Feature snapshots & reproducible runs | ✅ | `feature_runs` + `feature_values` (migration 0003); runs record source selection, calendar basis, engine+catalog versions; identical inputs → identical checksums (unit + integration verified in the browser: Δ=0 comparison) |
| Feature provenance | ✅ | every value links contributing observation ids (capped+counted), dataset products, processing versions, evidence classes, calendar basis, sha256 checksum |
| API endpoints | ✅ | POST/GET `/fields/{id}/feature-runs`, GET `/feature-runs/{run_id}`, `/values` (filters+paging), `/comparison?against_run_id=`, GET `/features/catalog`; 202 async-style lifecycle like ingestion; idempotency keys |
| Source selection honesty | ✅ | ONE dataset product per variable (never blended); window-aware preference (real first, in-window coverage next) with explicit fallback warnings; `is_synthetic` flagged end-to-end with the SYNTHETIC banner |
| Tests | ✅ | unit (28: calendar, engine, reproducibility, tz), integration (22: lifecycle, selection, overrides, isolation, comparison, validation), data-contract (9: provenance completeness, enums, units, checksums, no-zero) — suite total **243 passed** |
| UI: Features tab | ✅ | run creation (levels, hemisphere, crop-season windows), runs list with status/synthetic badges, values table with quality/coverage chips, run-to-run comparison, catalog browser with formula references |

### Browser end-to-end verification — Milestone 4 (agent-browser, 2026-10-31)

- ✅ Features tab: field picker → run creation → job succeeded → values table populated
- ✅ Window-aware selection visible in production behaviour: synthetic fixture selected for 2023 with the fallback warning; real era5_land soil moisture used where it covers the window; farmer CSV rows (outside the window) never blended in
- ✅ Values table: `precipitation_total_monthly 2023-01 = 29.25 mm · 100% · valid · 31 obs`; `hot_days 0 days · 97% · partial` (single synthetic gap flagged); anomalies honestly `not evaluated` (single-year window, ≥5 years required)
- ✅ Comparison: two identical 2023 runs → matched periods with Δ = 0 (reproducibility, in the browser)
- ✅ SYNTHETIC badges on runs + amber "never for real-world conclusions" banner
- ✅ Zero page errors; mobile 390px and desktop 1366px: no horizontal overflow; footer flush (`mt-auto`) on long content
- ✅ Display fix: run period shown in the farm calendar (was drifting to UTC dates, e.g. 2014-12-31)

## Milestone 5 — Global agricultural knowledge base & decision intelligence (2026-10-31)

Gap analysis: `docs/implementation/M5_GAP_ANALYSIS.md` · ADRs 0014–0018 in `DECISIONS_AND_ASSUMPTIONS.md` · architecture: `docs/architecture/knowledge-model.md`.

| Task | Status | Notes |
|---|---|---|
| M5.1 Versioned knowledge model | ✅ | `knowledge_packs` (+checksum, draft/active/retired lifecycle), `knowledge_sources`, `crop_families`, `crops`, `crop_varieties`, `crop_traits` (row-per-context with value range, evidence class, confidence, validation status, validity period — migration 0004); multiple values per trait under different regions/contexts supported by construction |
| M5.1 Import & validation workflow | ✅ | strict Pydantic pack schema + cross-referential validation (unknown sources/crops/families, conflicting trait values, break-rule semantics, license/attribution/citation required); idempotent by (code, version) with checksum conflict detection; bundled seed pack auto-bootstraps (same lazy pattern as data registry); audit events on import/activate |
| M5.1 Seed pack honesty | ✅ | 4 real sources (FAO-56 1998, FAO EcoCrop, Agrios 2005, Herridge et al. 2008), 11 crops / 141 traits / 13 calendar windows (declared `reference_synthesized`) / 30 Kc rows; NO invented drought/heat scores; faba bean deliberately has NO Kc (water stays unevaluated); NOTHING confirmed_regional |
| M5.2 Crop relationship & rotation knowledge | ✅ | structured `rotation_rules` (rotation_break / host_pathogen / succession_compatibility / cover_crop_suitability) with crop/family scoping, region lists, severity, source citations; family-scoped rules only where the cited mechanism justifies; region gating (rules scoped to other regions never apply) |
| M5.2 Validation-status gating | ✅ | hard enforcement ONLY at `confirmed_regional` (seed pack ships zero — demonstrated honestly in UI and tests); reference rules inform conditional eligibility + explanations + "local expert validation required" blocks |
| M5.3 Candidate generation | ✅ | per-season evaluation of every KB crop: calendar-window overlap (year-wrapping), duration vs season (+14 d spill tolerance), EcoCrop temperature/precipitation ranges vs season climatology, soil pH w/ evidence class, farmer market exclusions + equipment limits, rotation-history rules; four first-class statuses (eligible / conditionally_eligible / excluded / unevaluated) each with reasons + cited evidence; missing evidence ≠ zero ≠ exclusion |
| M5.4 CP-SAT optimizer | ✅ | OR-Tools 9.14.6206 adapter (`app/rotation/optimizer.py`); hard constraints (exactly-one, admissible-only pool, confirmed rotation breaks pairwise + history boundary, per-season water allocation) registered as solver ASSUMPTIONS → INFEASIBLE returns named conflicting constraints (verified live in the browser); never silently relaxed; baseline always preserved & labelled |
| M5.4 Soft objectives | ✅ | water efficiency, soil-health composite (legume/cover/root/N-fixation — missing sub-indicators skipped), economic margin (farmer-supplied ONLY, otherwise skipped with reason), family diversity (alternation term), climate resilience (temperature-in-optimum fraction), erosion proxy (duration coverage), cover-crop opportunity |
| M5.5 Multi-objective evaluation | ✅ | 4 profiles + custom weights; raw criterion values + min-max normalization WITHIN the run's strategy set; weights renormalized over evaluable criteria with skipped weights reported; Pareto dominance over SHARED evaluable set (non-comparable pairs recorded); `evidence_coverage` = transparency metric, NOT a confidence score |
| M5.6 Explainability | ✅ | every strategy: why_generated, recommendation (front/dominated/baseline), constraint checks w/ statuses, criterion-level evaluation, evidence references (pack versions + citations + feature-run ids), data limitations (synthetic flag, SoilGrids prediction class, screening-estimate caveat, zero-confirmed-rules note), expected benefits, risks/trade-offs vs other strategies, local expert validation requirements |
| Water screening estimate (ADR-0017) | ✅ | FAO-56 single-Kc curve (linear ramps) × monthly ET0 climatology; sowing-at-season-start assumption recorded; only when BOTH ET0 evidence and sourced Kc exist; with a hard allocation, water-unevaluable crops are held OUT of optimization (never partial compliance labelled as full) |
| Climate evidence bridge (M4→M5) | ✅ | month-of-year climatology from the field's latest succeeded feature run — historical proxy explicitly labelled "NOT a forecast"; ≥90% month coverage else unevaluated; synthetic flag propagated into every candidate reason + run warnings |
| Reproducible runs | ✅ | `rotation_runs`/`rotation_strategies` snapshot seasons, profiles, pack refs+checksums, feature-run ids, crop-history ids, engine version, solver seed; identical inputs → identical assignment + sha256 strategy checksums (unit + browser-verified); idempotency keys |
| API endpoints | ✅ | knowledge: GET packs/sources/crops/crop detail/rotation-rules, POST packs/import, POST activate · rotation: GET/POST crop-history, POST crop-candidates, POST/GET rotation-runs, GET strategies, GET comparison; 202 job pattern + idempotency; tenant-scoped runs (cross-tenant 403 verified) |
| Passport readiness fix | ✅ | `rotation_optimization` gate now queries reality (active pack w/ crops, crop history, succeeded feature run) — stale "constraint_solver (later milestone)" removed; available→"Rotation runs exist…" |
| Tests | ✅ | +71 new: knowledge contracts (schema, cross-refs, conflicts, checksum, regional keys, deliberate gaps), rotation core (candidates calendar/duration/climate/soil/water/history, confirmed-vs-reference rule gating, determinism, water infeasible+conflicts, pairwise + family + history-boundary breaks, Pareto/preference changes, missing economics), integration (import workflow idempotency/conflicts, crops/rules API, candidates API, full runs, no-relaxation, infeasible, comparison, reproducibility, custom weights, tenant isolation, passport readiness) — suite total **314 passed** |
| UI: Rotation tab | ✅ | planning seasons editor, crop-history form, per-season candidate lists with status chips + expandable reasons/citations, optimizer card (profiles, water allocation, past runs) with infeasible-conflict alerts + SYNTHETIC banner, strategy cards (Pareto badges, criteria tables with honest "(not evaluated)", accordions: why/constraints/evidence+limitations/validation-required, checksums), knowledge browser (packs+sources, crops table with Kc gap column, rules with enforceability badges) |


## Milestone 6A — Advanced water intelligence engine (2026-10-31)

Full design: `M6A_DESIGN.md` · readiness matrix: `M6A_READINESS_MATRIX.md` · verification evidence: `M6A_VERIFICATION.md`.

| Task | Status | Notes |
|---|---|---|
| Phase 0 — deepening baseline re-verified | ✅ | 343/343 baseline re-run; all 15 deepening docs reviewed; Kc records cross-verified against fetched FAO-56 primary sources |
| Phase 0 — crop-by-crop readiness matrix | ✅ | 11 crops classified (complete/partial/missing/not-locally-validated); 3 root-depth transcription errors found & corrected |
| Phase 1 — versioned water knowledge model | ✅ | `app/water/*` (`water-engine-1.0.0`, `water-methods-1.0.0`); seed pack `kp-seed-2026.11.1` adds Table 22 p values + Zr corrections; superseded pack retired at bootstrap |
| Phase 2 — ET engine | ✅ | FAO-56 single-Kc curve shared by candidates & planner (200 randomized equivalence trials vs M5 estimator, max diff 0.0); stage/daily/monthly aggregation; dual-Kc refused honestly |
| Phase 3 — effective rainfall + soil balance | ✅ | FAO-33 Pe (verified incl. worked examples) + constant-fraction; TAW/RAW/Dr/Ks root-zone balance; Saxton-Rawls 2006 PTF (verified coefficients, validity domain enforced) |
| Phase 4 — irrigation requirement ladder | ✅ | 7-quantity ladder with statuses; NIR = max(0, ETc − Pe − ΔSW); GIR only with efficiency; 1 mm·ha = 10 m³ identity property-tested |
| Phase 5 — seasonal planning | ✅ | stage/monthly timelines, deficit windows (stress + allocation shortfall), scenario reruns as immutable snapshots, unknown allocation ≠ unlimited |
| Phase 6 — rotation integration | ✅ | NIR coefficients in CP-SAT allocation constraint (ETc conservative fallback disclosed); infeasibility names water_allocation + demand basis |
| Phase 7 — water intelligence interface | ✅ | `/water/methods`, readiness matrix, plan create/list/get/delete APIs; frontend Water tab (Simple/Expert, stage timeline, ladder, accordions, plan history) |
| Phase 8 — verification | ✅ | 98 new tests (70 unit golden/property + 11 rotation-integration + 17 API integration); 441/441; browser E2E with exact arithmetic checks; migration tests; lint clean |

### Key M6A decisions (ADRs 0019–0021, summarized in M6A_DESIGN.md)

- Methodology ladder: ETc → Pe → root-zone balance → requirement ladder → rotation; each level disclosed when used.
- Provider ET0 only (no local Penman-Monteith/Hargreaves — no radiation/humidity evidence; backlog W-6).
- USDA-SCS effective rainfall NOT implemented (coefficients unverified in Phase 0; backlog W-5).
- PTF-over-texture is opt-in with the single-layer extrapolation disclosure; farmer measurements win.
- Unknown water allocation is reported as unknown — never interpreted as unlimited water.

### Browser end-to-end verification — Milestone 5 (agent-browser, 2026-10-31)

- ✅ Auth gate → demo workspace → new **Rotation** tab visible and functional
- ✅ Knowledge browser live: pack card (active, 11 crops · 141 traits · 6 rules, digitization note in amber, FAO/EcoCrop/Agrios/Herridge attributions, expandable sources), crops table (faba_bean honestly shows NO Kc), rules cards with `reference` validation badges + citations
- ✅ Golden path: field picker → crop history (maize 2023 via form) → candidates for summer_2026 — statuses with cited reasons; SYNTHETIC warning surfaced
- ✅ After ingesting T/P/ET0 (Observations) + monthly feature run (M4 flow): candidates gain climate evidence + water estimates (maize ≈664 mm, tomato ≈686 mm)
- ✅ Optimization run ce949614 · optimal · 4 strategies: baseline (empty assignment shown honestly) + water_priority/soil_health_priority/balanced with Pareto-front badges, objective values, evidence coverage (14%→86%), criteria tables where `economic_margin_index` shows "(not evaluated)" — never a fake number
- ✅ Accordion "Constraints checked": one_crop_per_season ✓, candidate_admissibility ✓, rotation_break [satisfied] with "0 confirmed rule(s) loaded overall", water_allocation [not_applicable] "never invented"
- ✅ Infeasible case live: allocation 1 000 m³ → run 428cbc08 reported `infeasible · 1 strategies` with named conflict `water_allocation — Season summer_2026: … (1000 m3)` — no silent relaxation
- ✅ Zero console/page errors; desktop 1366 px footer flush on short page and naturally pushed on long pages; mobile 390 px: no horizontal overflow, tab strip scrolls, footer intact
- Note: intermittent blank screenshots mid-session were agent-browser daemon restarts (page reloaded to about:blank); every fresh load rendered and behaved correctly — the app itself stayed healthy (200s, zero page errors)

## Milestone 7.1 — Field state foundation & snapshot hygiene (2026-11-01)

Design/contract/verification docs: `docs/m7/m7_1/` (M7_1_DESIGN, M7_1_FIELD_STATE_CONTRACT,
M7_1_OBSERVATION_MANIFEST, M7_1_BOUNDARY_VERSIONING, M7_1_API_CONTRACTS,
M7_1_TEST_AND_VERIFICATION). Basis: M7.0 readiness inspection (CONDITIONAL GO, adjustment A1).

| Task | Status | Notes |
|---|---|---|
| Boundary version pinning (H-01/F-01) | ✅ | additive `boundary_version` on `feature_runs` + `water_plans` (NULL = pre-M7.1, never backfilled/guessed); mandatory on `field_states`; historical pins proven stable across boundary edits |
| Observation manifest (H-02/F-31) | ✅ | `field-observation-manifest-1` document + deterministic SHA-256 stored BY VALUE on runs (uncapped full resolved input set) and copied verbatim onto states; re-ingestion cannot alter a stored manifest |
| Field state object | ✅ | `field_states` table — immutable by-reference composition (boundary version, env run, water plan, rotation run, crop history as-of, pack refs, manifest copy); field-scoped idempotent replay; FK RESTRICT on referenced artifacts |
| Period compatibility (F-02) | ✅ | per-dimension overlap records; env zero-overlap refused (422); water zero-overlap recorded `period_mismatch` + warning — never silently mixed |
| Honest missing domains (C3/H-03) | ✅ | soil & management always `not_implemented` with the M7.0 reasons; no generic completeness score |
| Water-plan deletion policy (F-13) | ✅ | 409 when referenced by any state; FK RESTRICT backstop |
| Ingestion idempotency (F-30) | ✅ | composite (field_id, key) unique index + field-scoped replay + optional request key (migration 0007) |
| Provenance surfacing (F-09/F-20/F-32) | ✅ | `created_by` in feature/water/rotation payloads; `solver_version` now written per rotation run; water plans gained `started_at`/`completed_at` |
| Field State API | ✅ | POST/GET per field, GET detail (+`?include_manifest=true`), verify, manifest, compare (same-field, ≥2, explicit non-interchangeability note) |
| Field State UI (8th tab) | ✅ | assemble (label + optional period), snapshot list, honest domain grid, verify report, pairwise compare; soil/management rendered "not implemented" |
| Verification | ✅ | 490/490 backend tests (441 pre-existing regression + 16 manifest unit + 31 field-state integration + 2 migration tests); migration up/down on dev + scratch DBs; lint exit 0; browser E2E desktop + 390 px, zero console errors |

## Pre-M6 deepening program — scientific & technical hardening (2026-10-31)

Full deliverable set: `docs/deepening/` (15 documents) · findings register:
`docs/deepening/SCIENTIFIC_AUDIT.md` · exit scorecard:
`docs/deepening/DEEPENING_EXIT_REPORT.md`.

| Task | Status | Notes |
|---|---|---|
| As-built architecture audit (backend, frontend, DB, routes, tests) | ✅ | 3 parallel audits + core reads; 21 classified findings (1 Critical, 7 High, 11 Medium, 2 Low) |
| Critical: real passport products falsely badged "Synthetic" | ✅ fixed | flag-driven badge; payload carries is_synthetic; synthetic/real variants never merge |
| Feature engine quality filter | ✅ fixed | only contract-valid observations aggregate; per-status exclusion warnings (F-02) |
| Cross-tenant idempotency replay | ✅ fixed | composite (field_id, key) unique (migration 0005); all lookup paths scoped (F-03) |
| Solver status semantics | ✅ fixed | MODEL_INVALID/UNKNOWN never reported infeasible; run "optimal" only when every profile proved it (F-04) |
| Partial Kc anchors zero-fill | ✅ fixed | anchor vocabulary enforced; incomplete sets rejected; loader never zero-fills (F-05) |
| Deep rotation-break rules under-enforced | ✅ fixed | lookbacks derived from deepest confirmed rule in both layers (F-06) |
| Water estimate silently dropped missing-ET0 months | ✅ fixed | estimate refused rather than under-reported (F-07) |
| SoilGrids PI mislabel | ✅ fixed | honest "mean of per-pixel Q05–Q95 half-width, NOT a field-level 90% PI" (F-08) |
| Non-deterministic pack-collision winner | ✅ fixed | deterministic ordering incl. API read paths (F-09) |
| Criteria evidence citations | ✅ fixed | criterion-level source_refs populated + persisted (F-10) |
| "Climatology" mislabel of short baselines | ✅ fixed | baseline_class + includes_evaluated_period; catalog v2026.11.1-d1 (F-11) |
| CHIRPS v3 daily dependency structure | ✅ documented | pentad→daily disaggregation with ERA5/IMERG; no product blending (F-12) |
| Raster extraction area weighting | ✅ fixed (CHIRPS) | fractional pixel-area weighted mean (v2) + golden test; SoilGrids rationale G-2 (F-13) |
| Audit-trail actor/org NULLs | ✅ fixed (F-14) | principal.id + farm org |
| DB indexes + model drift | ✅ fixed | migration 0005 additive (F-15); NULLS NOT DISTINCT Kc uniqueness (F-18) |
| Error envelope + deprecated constant | ✅ fixed (F-16) | StarletteHTTPException handler; 422 constant renamed |
| Frontend honesty defects | ✅ fixed | "0 obs"→"— obs", NaN guards, chart provenance notes, "evidence-backed criteria NN%", truncation notice, baseline wording (F-17) |
| Precipitation partial-month warning | ✅ fixed (F-19) | under-count explicitly warned |
| Knowledge enrichment decision | ✅ documented | depth over breadth: nothing added without a verifiable source; backlog K/C/S/M/B/G series |
| Benchmark suite | ✅ | golden + property + metamorphic tests; suite 314 → 343, all green |
| Browser re-verification | ✅ | passport badges, rotation labels, "— obs", new catalog version; zero page errors; mobile clean |

## Milestone 7.2 — Scenario domain & immutable scenario definitions (2026-11-01)

Design/contract docs: `docs/m7/m7_2/` (12 documents). Basis: M7.0 CONDITIONAL GO (C1–C5) + M7.1
verified baseline (commit `15013c7`).

| Task | Status | Notes |
|---|---|---|
| Versioned scenario taxonomy (5 types) | ✅ | implemented vs not_implemented capability registry; evidence classes bound (C2); climate/forecast contract-only, creation rejected |
| Strict configuration contracts (`scenario-config-1.0`) | ✅ | Pydantic per-type, `extra="forbid"`, explicit units, bounds, conflict rules, explicit-null canonicalization |
| Normalized relational model | ✅ | `scenarios` + `scenario_validation_records` (migration 0008); lineage via self-FK + lineage_kind (no over-normalization) |
| Deterministic configuration checksums | ✅ | SHA-256 over canonical JSON incl. schema version + by-value parent pins; UI metadata excluded (tested) |
| Immutability after finalization | ✅ | service transitions + DB trigger `enforce_scenario_immutability` (raw-SQL tamper test); archived terminal |
| Versioning & lineage | ✅ | revisions (new rows, version+1) + branches; parent state RESTRICT-protected; originals untouched (tested) |
| Pure validation engine | ✅ | no HTTP/ORM imports; 8-value result vocabulary; evidence-aware (synthetic disclosure, dimension gaps); rules version `scenario-validation-rules-1.0` |
| Definition-level comparison | ✅ | structural config diff + parent/boundary/period/evidence warnings; no simulated outputs (explicit note) |
| Scenario APIs (15) | ✅ | create/list/get/patch/delete/validate/finalize/archive/versions/lineage/verify/compare/types/capabilities; NO execution endpoint; field-scoped idempotency; tenant-isolated (tested) |
| Frontend Scenario Workspace | ✅ | 9th tab; capability panel; typed creation with units + period prefill; validate/finalize/version/verify/lineage/compare; evidence badges; no simulation graphs |
| Migration 0008 verified | ✅ | upgrade/downgrade/re-upgrade on scratch + dev DBs |
| Tests | ✅ | 91 new (45 unit / 43 integration / 3 migration); full suite **581 passed, exit 0** |
| Browser E2E | ✅ | golden path incl. incompatible-period honesty, finalize-freeze UI, version, verify, compare; zero console errors; mobile 390px clean |

## Not implemented (next milestones — deliberately)

- ✅ Open-Meteo historical provider (Milestone 3 — done)
- ✅ CHIRPS v3 import/extraction (Milestone 3 — done)
- ✅ SoilGrids WCS optional provider (Milestone 3 — done; WebDAV variant not needed)
- ✅ CSV observations import (Milestone 3 — done; soil-lab CSV waits for M4 soil history)
- ⬜ FAO GAEZ / crop-calendar reference imports (licensing review; seed pack uses FAO-56 + EcoCrop citations instead)
- ⬜ SoilGrids other depth intervals (soil measurement history — later milestone)
- ✅ Feature runs / climate features / temporal aggregation (Milestone 4 — done)
- ✅ Crop knowledge base + candidate generation + rotation optimization + Pareto evaluation (Milestone 5 — done)
- ✅ Water intelligence engine (Milestone 6A — done)
- ✅ M7.0 readiness inspection (done — CONDITIONAL GO; `docs/m7/readiness/`)
- ✅ Field state foundation & snapshot hygiene (Milestone 7.1 — done; `docs/m7/m7_1/`)
- ✅ Scenario domain & immutable scenario definitions (Milestone 7.2 — done; `docs/m7/m7_2/`)
- ✅ M6B soil health & nutrient intelligence (done — soil samples/measurements with method identity, depth-explicit profile, USDA texture + honest AWC, FAO GSOC SOC stock, N/P/K budgets with exact stoichiometry, multi-domain assessments; `docs/m6b/`)
- ✅ M6C field management intelligence (done — cover-crop evaluation, soil-cover intervals, residue ledger, conditional RUSLE screening (factors only with provenance; no factor database), CP-SAT operations scheduling; `docs/m6c/`)
- ✅ Scenario execution engine (Milestone 7.3 — environmental parameters over immutable field states; soil/management scenario transformations deliberately NOT part of the engine)
- ✅ Sensitivity & uncertainty analysis (Milestone 7.4)
- ✅ Multi-scenario rotation evaluation (Milestone 7.5)
- ✅ Robustness & decision-stability analysis (Milestone 7.6)
- ✅ Digital twin view & integrity validation (Milestone 7.7 — censuses M6B/M6C artifacts, bounded validation walk with checksum recomputation)
- ⬜ External climate projections & forecasts (Milestone 7.8 — data-gated, NO-GO until sourced data exists)
- ⬜ Soil/management-driven scenario transformations (deliberately unavailable — no validated transform semantics exist; M6B/M6C remain data domains)
- ⬜ Rotation optimizer water-scheduling refinements + soil ledger (Milestones 6B–7 leftovers)
- ⬜ Stress testing lab (Milestone 8)
- ⬜ Farmer journal, advisor review, offline sync (Milestone 9)
- ⬜ NASA connectors — intentionally not implemented (future adapter; Master rule 8)

## M6B/M6C + M7 integration state (2026-11-03)

- Migration graph unified: soil line (`0007_soil_intelligence` → `0008_field_management`) merged with the M7 line at empty merge revision `0014_merge_m6bc_m7` — single head, all 15 migrations verified upgrade/downgrade on a scratch DB and applied to the dev DB (83 tables incl. `alembic_version` + PostGIS).
- Full backend suite at integration: **1095 passed, 1 skipped, exit 0** (581 pre-integration baseline + 514 new across M6B/M6C/M7.3–7.7).
- Frontend: 14-tab workspace (Soil, Management, Sensitivity, Robust Plan, Decisions, Digital Twin added); ESLint + tsc clean.
- Reconciliation rules enforced: M7.1 field states do not pin soil/management artifacts (availability reasons updated); M7.2 capabilities truthful (`scenario_execution=implemented`, soil/management scenario dimensions unavailable); M7.3–M7.6 contain no invented soil/management semantics; M7.7 twin censuses M6B/M6C records + run artifacts (checksum recomputation where stored) and the capability matrix distinguishes implemented vs data-ready.
- Browser E2E evidence: SOC stock run reproduced FAO identity exactly (12.4 g/kg × 1.32 g/cm³ × 30 cm × 0.1 = 49.104 Mg C/ha) with checksum; cover-crop plan evaluated with honest conditional candidate; twin validation walk verified both artifacts; login contract fixed (login now returns `organization` like register); tenant isolation re-verified live (403 cross-tenant); desktop 1280 + mobile 390 clean (`tool-results/m6bc-*.png`).

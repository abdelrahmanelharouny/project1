# Implementation Status

Last updated: 2026-10-31 (Milestone 5 — global agricultural knowledge base & decision intelligence)

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

## Not implemented (next milestones — deliberately)

- ✅ Open-Meteo historical provider (Milestone 3 — done)
- ✅ CHIRPS v3 import/extraction (Milestone 3 — done)
- ✅ SoilGrids WCS optional provider (Milestone 3 — done; WebDAV variant not needed)
- ✅ CSV observations import (Milestone 3 — done; soil-lab CSV waits for M4 soil history)
- ⬜ FAO GAEZ / crop-calendar reference imports (licensing review; seed pack uses FAO-56 + EcoCrop citations instead)
- ⬜ SoilGrids other depth intervals (soil measurement history — later milestone)
- ✅ Feature runs / climate features / temporal aggregation (Milestone 4 — done)
- ✅ Crop knowledge base + candidate generation + rotation optimization + Pareto evaluation (Milestone 5 — done)
- ⬜ Rotation optimizer + water intelligence + soil ledger (Milestones 6–7)
- ⬜ Stress testing lab (Milestone 8)
- ⬜ Farmer journal, advisor review, offline sync (Milestone 9)
- ⬜ NASA connectors — intentionally not implemented (future adapter; Master rule 8)

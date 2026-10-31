# Test Matrix

All results below were actually executed. Latest full-suite run: **2026-10-31** (M4 + M5 included). Command (from `mini-services/fieldshift-api`):

```
.venv/bin/python -m pytest tests
# => 343 passed in ~4 min (M1–M2: 157 · M3: +27 · M4: +59 · M5: +71 · deepening: +29)
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

## Milestone 4 — feature engine (59 tests)

Unit (`test_feature_engine.py`, 28):

| ID | Scenario | Expected | Result |
|---|---|---|---|
| M4-U1 | Calendar: UTC-midnight days stay on date; Cairo offset same date; extreme offset shifts | documented midpoint rule | ✅ |
| M4-U2 | Cairo local-day bounds incl. summer DST | correct local windows | ✅ |
| M4-U3 | Unknown timezone rejected; farm-timezone binning of local-midnight obs | 422 / correct bucket | ✅ |
| M4-U4 | Month bounds UTC; DJF season year-wrap; southern-hemisphere swap | correct | ✅ |
| M4-U5 | Crop-season windows require level + label; window respected | correct | ✅ |
| M4-U6 | Aggregation enum; unknown level 422 | enforced | ✅ |
| M4-U7 | Accumulation full month; below min-coverage → NULL + insufficient_coverage, never scaled/zero-filled | no fabrication | ✅ |
| M4-U8 | Daily values + missing days; daily window cap | correct | ✅ |
| M4-U9 | Mean carries standard error | SE present | ✅ |
| M4-U10 | Hot-days count; dry-spell run interrupted by data gap (never assumed dry) | ETCCDI-style | ✅ |
| M4-U11 | P−ET0; without ET0 → not_evaluated with reason | honest | ✅ |
| M4-U12 | Anomaly vs baseline; z-standardization; <5 years → not_evaluated | climatology gate | ✅ |
| M4-U13 | Seasonal total + CV (few years → not evaluated) | honest | ✅ |
| M4-U14 | Crop-specificity disclaimer on count indices | generic index label | ✅ |
| M4-U15 | Catalog versioned with formula references; definitions carry formula + version | cited | ✅ |
| M4-U16 | Identical inputs → identical checksums (value-sensitive, stable) | reproducible | ✅ |

Data contract (`test_feature_value_contract.py`, 9):

| ID | Contract item | Result |
|---|---|---|
| M4-C1 | Provenance complete (contributing obs ids capped+counted, products, versions, evidence classes, calendar basis) | ✅ |
| M4-C2 | Quality enum enforced; missing never zero | ✅ |
| M4-C3 | Units match canonical variable units | ✅ |
| M4-C4 | All values within period bounds + labelled | ✅ |
| M4-C5 | Temporal resolutions never mixed in one value | ✅ |
| M4-C6 | not_evaluated values always carry a reason | ✅ |
| M4-C7 | Synthetic run flagged end-to-end | ✅ |
| M4-C8 | Missing input variable drops dependents with reason | ✅ |
| M4-C9 | Run-level checksum stable & value-sensitive | ✅ |

Integration (`test_feature_runs.py`, 22):

| ID | Scenario | Expected | Result |
|---|---|---|---|
| M4-I1 | Create run → 202 lifecycle → values persisted | job pattern | ✅ |
| M4-I2 | Idempotency key reuses run | no duplicate compute | ✅ |
| M4-I3 | Duplicate crop labels 422; unknown feature code/level 422 | fail fast | ✅ |
| M4-I4 | Source override pins product; unknown product rejected | selection honesty | ✅ |
| M4-I5 | Real product preferred, NEVER blended with synthetic | one product per variable | ✅ |
| M4-I6 | No observations → structured error | not a silent empty run | ✅ |
| M4-I7 | Runs scoped to field; run hidden from other tenant | 403 cross-tenant | ✅ |
| M4-I8 | Comparison endpoint (against_run_id) | matched periods, Δ | ✅ |

## Milestone 5 — knowledge base & rotation intelligence (71 tests)

Mapped to the 13 mandated test categories:

**K1. Knowledge schema & versioning**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K1.1 | Seed pack validates against strict pack schema | structured errors otherwise | ✅ |
| K1.2 | Pack checksum stable & content-sensitive | version integrity | ✅ |
| K1.3 | Variety-level trait model exists (species vs cultivar) | distinct rows | ✅ |
| K1.4 | Trait cannot be both numeric and text | 422 | ✅ |
| K1.5 | Invalid confidence rejected | 422 | ✅ |
| K1.6 | Cross-refs: unknown crop code / family / rule crop rejected | 422 | ✅ |
| K1.7 | Import idempotent by (code, version); conflicting same-version rejected | 409 conflict | ✅ |
| K1.8 | Draft pack inert until activated | no side effects | ✅ |
| K1.9 | Seed pack ships ZERO confirmed_regional rules | honesty invariant | ✅ |

**K2. Trait provenance & regional applicability**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K2.1 | Every seed trait carries source + citation | no uncited value | ✅ |
| K2.2 | Every seed Kc row carries source + confidence | no uncited water param | ✅ |
| K2.3 | Region-scoped trait keys are distinct rows (multi-value per trait) | same trait, several contexts | ✅ |
| K2.4 | Crops API lists trait provenance; crop detail carries citations | provenance surfaced | ✅ |

**K3. Missing / conflicting agronomic evidence**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K3.1 | Conflicting trait values in one pack rejected | 422 | ✅ |
| K3.2 | Deliberate gaps stay gaps (faba_bean has NO Kc; no invented drought scores) | absent ≠ zero | ✅ |
| K3.3 | Unevaluated candidate cannot enter optimizer | validator rejects | ✅ |
| K3.4 | Missing license / attribution rejected at import | 422 | ✅ |

**K4. Crop eligibility & exclusion**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K4.1 | Confirmed-regional break rule excludes candidate | hard exclusion | ✅ |
| K4.2 | Farmer market exclusion is hard | excluded | ✅ |
| K4.3 | Temperature below absolute minimum → excluded (EcoCrop range, cited) | excluded | ✅ |
| K4.4 | Duration exceeding season → excluded; within 14-d spill → conditional | tolerance documented | ✅ |
| K4.5 | Soil pH outside optimum → conditional WITH evidence class | not excluded silently | ✅ |
| K4.6 | Candidates API returns all four statuses + explanations | eligible/conditional/excluded/unevaluated | ✅ |

**K5. Crop calendar boundaries**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K5.1 | Calendar exclusion cites the known window (e.g. faba_bean 10-15..12-15) | cited reason | ✅ |
| K5.2 | No window for hemisphere → unevaluated (not excluded) | honest unknown | ✅ |

**K6. Rotation ordering constraints**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K6.1 | Confirmed break enforced pairwise between planned seasons | solver-level | ✅ |
| K6.2 | Confirmed break enforced across crop-history boundary | baseline respected | ✅ |
| K6.3 | Baseline violation detected WITHOUT solver | pure-layer check | ✅ |
| K6.4 | min_break_seasons respected | gap required | ✅ |

**K7. Water budget constraints**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K7.1 | Water allocation respected when feasible | within quota | ✅ |
| K7.2 | Water estimate present ONLY when both Kc and ET0 evidence exist | never invented | ✅ |
| K7.3 | Farmer economics evaluated only when supplied; never zero-filled | honest skip | ✅ |

**K8. Crop-family & pathogen-specific rotation rules**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K8.1 | Family-scoped rule applied only where cited mechanism justifies | no blanket family rule | ✅ |
| K8.2 | Region-scoped rule does not apply to other regions | region gating | ✅ |
| K8.3 | Reference rule → conditional (never excluded, never binds solver) | validation-status gating | ✅ |
| K8.4 | Confirmed rule binds; reference rules reported as enforceability metadata | two-tier semantics | ✅ |

**K9. Infeasible optimization cases**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K9.1 | Allocation too small → INFEASIBLE with named conflicting constraint | no silent relaxation | ✅ |
| K9.2 | API surfaces infeasible status + conflict block | explicit state | ✅ |
| K9.3 | API: hard constraints never relaxed to force a solution | verified | ✅ |

**K10. Pareto ranking & preference changes**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K10.1 | Dominated solution marked; front membership computed on SHARED evaluable set | Pareto honest | ✅ |
| K10.2 | Weight change changes ranking | preference-sensitive | ✅ |
| K10.3 | Legume strategy wins soil-health profile | domain sanity | ✅ |
| K10.4 | Custom weights honored; skipped weights reported | ADR-0018 | ✅ |

**K11. Deterministic reproducibility**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K11.1 | Same inputs → same solver assignment (fixed seed) | deterministic | ✅ |
| K11.2 | Re-run API → identical strategy checksums | reproducible runs | ✅ |

**K12. Synthetic / real evidence separation**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K12.1 | Synthetic evidence labelled on EVERY candidate reason | never presented as real | ✅ |
| K12.2 | Run-level synthetic warning surfaced | banner + warnings | ✅ |

**K13. Tenant isolation & API contract**

| ID | Scenario | Expected | Result |
|---|---|---|---|
| K13.1 | Crop history + runs hidden cross-tenant | 403 | ✅ |
| K13.2 | Pack import requires auth | 401 | ✅ |
| K13.3 | Unknown crop 404 (not 403); unknown profile 422 | contract | ✅ |
| K13.4 | Packs listed with license + counts | attribution visible | ✅ |
| K13.5 | Passport rotation readiness flips to available with real inputs | no stale "later milestone" | ✅ |
| K13.6 | Full run: strategies + complete explanation blocks (why/constraints/evidence/limitations/validation) | M5.6 contract | ✅ |
| K13.7 | Comparison endpoint for runs | delta view | ✅ |

### M5 E2E (browser, agent-browser — re-verified 2026-10-31)

| ID | Flow | Result |
|---|---|---|
| E15 | Rotation tab: knowledge browser (pack card w/ license + digitization note, crops table with Kc-gap column — faba_bean "none", rules with reference badges + citations) | ✅ |
| E16 | Field picker → planning seasons → crop history (maize baseline) → candidates: 6 conditional / 5 excluded, statuses + cited reasons, water estimates ≈585–686 mm, SYNTHETIC banner | ✅ |
| E17 | Candidate detail: duration spill conditional [fao56_1998], EcoCrop climate window, annual-rainfall caveat, REFERENCE rule NOT enforced [agrios_2005], soil pH "not evaluated" | ✅ |
| E18 | Optimizer: run optimal · baseline (honest empty assignment, evidence 14%) + strategies with Pareto badges, criteria tables with "(not evaluated)" economics, skipped weights, per-strategy checksums | ✅ |
| E19 | Constraints accordion: one_crop_per_season ✓, admissibility ✓, rotation_break "0 confirmed rules loaded", water_allocation not_applicable "never invented" | ✅ |
| E20 | Infeasible: allocation 1000 m³ → run infeasible with named water_allocation conflict | ✅ |
| E21 | Mobile 390px: scrollWidth == clientWidth (no horizontal overflow), footer flush; desktop 1366px footer flush | ✅ |
| E22 | Zero page errors | ✅ |

## Pre-M6 deepening program (+29 tests, 2026-10-31)

Findings register: `docs/deepening/SCIENTIFIC_AUDIT.md` (F-01..F-21) ·
remediation evidence: `docs/deepening/REMEDIATION_REPORT.md` · benchmarks:
`docs/deepening/SCIENTIFIC_BENCHMARKS.md`.

Unit regressions (`tests/unit/test_deepening_regressions.py`, 21):

| ID | Scenario | Expected | Result |
|---|---|---|---|
| D-U1 | suspect/invalid observations never contribute values; exclusions warned | F-02 | ✅ |
| D-U2 | incomplete Kc anchor set rejected at import; invalid stage vocabulary rejected; complete set accepted | F-05 | ✅ |
| D-U3 | missing season month refuses the water estimate (never under-reports) | F-07 | ✅ |
| D-U4 | confirmed rule k=5 enforced by checker (beyond old cap 3) and optimizer (beyond old window 4) | F-06 | ✅ |
| D-U5 | solver failure statuses distinct from infeasible; feasibility-only solve works | F-04 | ✅ |
| D-U6 | criteria carry source citations (water/soil/erosion); farmer margin carries none | F-10 | ✅ |
| D-U7 | baseline_class + includes_evaluated_period recorded; catalog no longer says "climatology" | F-11 | ✅ |
| D-U8 | Pareto: dominated never on front; duplicates both on front; disjoint sets non-comparable; neutral normalization; skipped weights | Phase H | ✅ |
| D-U9 | determinism (same inputs → same assignment/objective); baseline never claims solver status | Phase H | ✅ |

Integration regressions (`tests/integration/test_deepening_api.py`, 6):

| ID | Scenario | Expected | Result |
|---|---|---|---|
| D-I1 | passport product payload carries is_synthetic + evidence_class | F-01 | ✅ |
| D-I2 | idempotency key on another field / another tenant never replays | F-03 | ✅ |
| D-I3 | later pack version wins deterministically (API read paths too) | F-09 | ✅ |
| D-I4 | audit rows carry actor + organization | F-14 | ✅ |
| D-I5 | duplicate species-level Kc anchor rejected by DB (NULLS NOT DISTINCT) | F-18 | ✅ |

E2E (browser re-verification): E23–E26 in `docs/deepening/DEEPENING_EXIT_REPORT.md` §7.

## Known warnings in test output

- Starlette deprecation: `HTTP_422_UNPROCESSABLE_ENTITY` renamed to `HTTP_422_UNPROCESSABLE_CONTENT` (cosmetic; aligned with FastAPI 0.162).
- React Router/Sonner: benign Radix Select controlled/uncontrolled notice in dev console (cosmetic; no functional impact).

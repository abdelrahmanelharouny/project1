# Decisions and Assumptions

Records architectural decisions (ADR-style, lightweight). Each entry: context → decision → consequences.

## ADR-0001 — Modular monolith, two processes in the sandbox

**Context.** The master spec prescribes a Python FastAPI backend + React frontend. The sandbox repository is a Next.js 16 app whose preview exposes one HTTP port through a Caddy gateway; Docker Compose is unavailable.

**Decision.** Keep the modular-monolith shape: FastAPI application (`mini-services/fieldshift-api`) with domain/application/data-platform/geospatial layer separation, run as an independent mini-service on `127.0.0.1:3030`; Next.js serves the React workspace on `:3000`. API reachability:
- Through the gateway (user preview): relative fetches carry `?XTransformPort=3030`; Caddy forwards.
- Directly on `:3000` (local dev): a Next.js rewrite proxies `/api/v1/*` to the FastAPI service.

**Consequences.** One codebase, clean module boundaries, real process separation. Production deployment can move FastAPI behind a standard reverse proxy without code changes.

## ADR-0002 — Real PostgreSQL 16 + PostGIS 3.5 via conda-forge (user-space)

**Context.** The spec requires PostgreSQL + PostGIS. The sandbox has no root, no Docker, and the `pgserver` wheel ships without PostGIS.

**Decision.** Install PostgreSQL 16.10 + PostGIS 3.5.0 (GEOS 3.13, PROJ 9.5) from conda-forge into `db/pgenv` (fully user-space, no root), cluster in `db/pgdata`, listening on `127.0.0.1:5433`. `scripts/ensure_db.py` starts it on demand and guarantees the `fieldshift` database + `postgis` extension exist. Migrations are authored as plain Alembic/PostGIS DDL that runs unchanged on a managed PostgreSQL+PostGIS service in production.

**Consequences.** The running database is genuinely PostgreSQL + PostGIS (geometry columns, `ST_Area` on geography, spatial indexes). Sandbox lifecycle scripts are dev-only conveniences, documented in `docs/architecture/deployment.md`.

## ADR-0003 — Geodesic area in PyProj, cross-checked against PostGIS geography

**Context.** Master §14.1 forbids planar square-degree area. Two defensible engines exist: PyProj `Geod` (WGS84 ellipsoid, application-side) and PostGIS `geography ST_Area` (spheroidal, database-side).

**Decision.** Compute `area_ha` at write time with PyProj Geod and store it; expose the PostGIS geography area as `postgis_geodesic_area_ha` for cross-checking. Integration tests require < 0.5 % divergence.

**Consequences.** Honest, redundant area computation; mismatch would signal geometry corruption.

## ADR-0004 — Minimal but real authentication for the slice

**Context.** Tenant isolation (Master rule 17) needs authenticated users, but the slice does not yet need full identity product features.

**Decision.** Email+password (PBKDF2-HMAC-SHA256, per-user salt, 120k iterations in dev), opaque 256-bit bearer tokens stored as SHA-256 hashes with expiry and revocation. `POST /auth/register` creates a personal organization + owner membership. Every farm/field/data route resolves a `Principal` and checks organization membership. Refresh-token rotation, rate limiting and RBAC granularity are deferred (see KNOWN_LIMITATIONS).

**Consequences.** Real authorization semantics are testable now; upgrade path to a fuller identity stack is isolated in `app/domains/identity` + `app/core/security`.

## ADR-0005 — Deterministic synthetic provider as the only data source in the slice

**Context.** Master rule 7/8: synthetic data must be visibly labelled; NASA and even real alternative providers are not required for the first slice.

**Decision.** One provider: `synthetic` (`app/data_platform/providers/synthetic`). Determinism via SHA-256 of the full request signature (seed, profile, AOI geometry, sorted variables, dates) feeding a `random.Random` stream — same request ⇒ identical series regardless of variable order. Five fixture profiles with invented shape constants (explicitly NOT agronomic claims). Every row: `is_synthetic=true`, generator version, seed, profile, purpose in metadata; product attribution says "SYNTHETIC TEST FIXTURE".

**Consequences.** Contract tests can demand byte-identical reruns; the UI can honestly badge everything; future providers slot into the same protocol without touching ingestion/passport logic.

## ADR-0006 — Idempotent ingestion via natural-key uniqueness

**Context.** Master §49: retries must not duplicate observations.

**Decision.** Unique constraint on `(field_id, dataset_product_id, variable_code, observed_at, time_support, spatial_support_type)`; ingestion flushes rows and treats integrity errors as idempotent skips. Job state lives in `ingestion_jobs` (queued/running/succeeded/failed/cancelled/retrying) with records received/rejected and warnings persisted.

**Consequences.** Reruns converge; the API contract for jobs will not change when execution moves to a real queue/worker.

## ADR-0007 — Data Passport reports facts separately and blocks honestly

**Context.** Master §16/§27: no synthetic confidence scores; missing data must produce not-evaluated results.

**Decision.** The passport aggregates per-variable facts (counts, valid ratio, missing count, period, resolution, freshness, provenance, warnings) without merging them. Analysis readiness uses explicit rules listing required variables (with minimum valid-coverage ratios) and extra requirements; anything not implemented (water budget, rotation optimization, soil analysis) is reported `blocked` with the exact missing inputs and milestone references.

**Consequences.** The UI can never imply an analysis is possible when evidence is absent; adding Milestone-4+ capabilities becomes a rule-table change.

## ADR-0008 — Pragmatic email validation; reserved domains allowed

**Context.** Pydantic `EmailStr` (email-validator) rejects reserved domains (`.local`, `example.com`) that are legitimately used for fixtures/demo accounts.

**Decision.** Validate email shape (regex + lowercasing) at the edge; full deliverability validation is a production concern.

**Consequences.** Demo/fixture accounts work; production hardening list includes stricter validation.

## Assumptions

1. The sandbox preview always reaches the API through the gateway or the Next rewrite; both are covered.
2. Demo workspace seeding (`POST /api/v1/dev/seed-demo`) is dev-only and disabled when `FIELDSHIFT_DEV_MODE=false`.
3. The Next.js `/` route is the only user-visible route in this environment; all sections live in one workspace.
4. Prisma/SQLite scaffolding in the repository remains untouched and unused by FieldShift (sandbox convention), to be removed when the template constraint lifts.
5. Coordinate reference for all stored boundaries is EPSG:4326 as specified; antimeridian inputs produce warnings rather than silent re-wrapping.

## ADR-0009 — Open-Meteo: explicit model selection with a verified model-variable matrix

**Context.** Master §11.1-A requires selecting the model/product explicitly rather than a silently changing best-match, and recording model, resolution, retrieval time and timezone basis. Live verification (2026-10-30) showed the archive endpoint publishes temperature + surface soil moisture for `era5_land` but derived precipitation/ET0 and wind only for `era5`.

**Decision.** Two selectable products — `era5_land` (default, ~11 km, land-only) and `era5` (~28 km, global) — with a hardcoded, live-verified `MODEL_VARIABLES` matrix. The API route fail-fasts (422 `UNSUPPORTED_VARIABLE`) when the selected model publishes none of the requested variables and warns when partial; per-observation metadata records model, native variable/unit, conversion, grid cell, elevation and UTC basis. Values the upstream returns as null become `missing` observations with `OPENMETEO_NULL` flags — never zeros.

**Consequences.** The UI filters the variable list per model; multi-year requests chunk by calendar years (max 10y/request) with retry/backoff on 429/5xx; adding a future model is a data-table change.

## ADR-0010 — CHIRPS v3 as an upload + extraction workflow, not a fetch provider

**Context.** CHIRPS is published as rasters, not an API; the sandbox cannot bulk-download global daily files, and the Master requires bulk/file ingestion plus spatial-subset extraction with product variant and preliminary/final status recorded.

**Decision.** The workflow accepts a CHIRPS v3 GeoTIFF upload (EPSG:4326 enforced — no silent reprojection), computes an unweighted field-mean over valid cells (polygon_average), and records sha256, nodata accounting, valid-cell ratio (LOW_CELL_COVERAGE flag below 50%), product kind (daily/pentad/monthly) and status (preliminary flags the observation). All-nodata and zero-intersection cases are structured 422 errors, never fabricated values. The provider degrades to `degraded` when rasterio is unavailable.

**Consequences.** No raster download pipeline or object storage is needed yet; daily-extreme caution is encoded in the source limitations text shown on the passport.

## ADR-0011 — SoilGrids: optional WCS-only provider restricted to the 0-5 cm depth in this slice

**Context.** ISRIC's REST API is paused; WCS is the documented path. SoilGrids is a static model snapshot, not a time series, and the observation natural key has no depth column.

**Decision.** Implement the SoilGrids 2.0 WCS GetCoverage client for five properties (pH×10, SOC, sand, clay, bulk density cg/cm³ — with documented unit conversions) at the 0-5 cm depth, fetching Qmean + Q0.05/Q0.95 to record a 90% prediction-interval half-width as uncertainty. The provider is registered `optional`, probed via DescribeCoverage, and degrades gracefully: an unreachable WCS yields a structured `PROVIDER_UNAVAILABLE` job failure while other providers continue. Depth selection for other standard depths arrives with Milestone 4's soil measurement history (which has depth columns).

**Consequences.** No natural-key collisions across depths; the passport always shows uncertainty and "model prediction, not a soil sample" limitations.

## ADR-0012 — Farmer CSV import: controlled validation, farmer-reported evidence

**Context.** Master §11.1-F requires structured imports of farmer data; rule 11 forbids fabricating values; evidence classes must not be mixed silently.

**Decision.** A strict CSV shape (`date, variable_code, value, unit, notes`) validated row-by-row: unknown variables, unit mismatches (case-insensitive against the catalog), bad dates and non-numeric values are rejected with per-row warnings; blank values become explicit `missing` observations with a `FARMER_BLANK` flag; in-file duplicates are rejected. All rows land as `farmer_reported_record` evidence, `point` spatial support, with file sha256/row-number provenance. Imports share the ingestion job accounting path (`input_record_count`) and natural-key idempotency.

**Consequences.** Soil-lab CSV intake waits for Milestone 4's `soil_measurements` history (depth/method columns); the import cannot silently pollute model data.

## ADR-0013 — Data Passport groups by (variable, source product), never by variable alone

**Context.** With Milestone 3, one field can hold the same variable from synthetic fixtures AND real reanalysis; grouping by variable alone lets one source's label (e.g. SYNTHETIC) mask another's rows — a provenance violation.

**Decision.** Passport entries are per (variable_code, dataset_product, processing_version), each carrying its own evidence class, license, attribution, period, warnings and support. Analysis readiness gates on the best entry per variable (real sources preferred on ties). The observations-table provenance badge and the coverage view follow the same per-source rule.

**Consequences.** The UI shows duplicate variable cards when sources overlap, by design; downstream feature runs (Milestone 4) will need an explicit source-selection policy per variable.

## ADR-0014 — Agricultural knowledge is a versioned PACK of source-cited attribute rows, not hard-coded rules

**Context.** Master §17.5/§17.13 and M5 require every knowledge attribute to carry source, reference, unit, validity region, conditions, evidence class, confidence and version; the same trait may hold multiple values under different regions, varieties, growth stages or management systems. Hard-coding crop rules in optimizer code would make knowledge unreviewable and unversioned.

**Decision.** Knowledge lives in versioned **knowledge packs** (`knowledge_packs` + `knowledge_sources` + crop/family/variety/traits/calendar/water-parameters/rotation-rules rows). Traits are attribute ROWS (trait_code, value_numeric/value_text + optional value_low/value_high range, unit, region, management context, growth stage, source reference, evidence class, confidence, validation status, validity period) — not wide columns — so multiple coexisting values are explicit, and conflicts can be detected and reported instead of silently overwritten. Pack import is a validation workflow: a pack missing license/attribution or a trait without a resolvable source is rejected; the pack stores sha256 + import checksum so identical inputs are idempotent. Packs are independent of environmental providers.

**Consequences.** The optimizer never contains crop constants; every number it consumes can be traced to (pack version → trait row → source citation). Review workflow (agronomist_reviews + validation_status) is the only path to "confirmed regional" knowledge.

## ADR-0015 — The rotation optimizer is a pure library; CP-SAT is an adapter behind it

**Context.** Master M6/M5 require the optimizer to stay independent of HTTP, frontend and ORM; algorithms and runs must be reproducible and versioned.

**Decision.** `app/rotation/` exposes pure dataclasses (`RotationProblem` → `StrategySolution`) and functions with zero FastAPI/SQLAlchemy imports. OR-Tools CP-SAT is used by one adapter (`optimizer.py`) with `num_search_workers=1` and a fixed recorded seed — identical inputs produce identical assignments and checksums (tested). Hard constraints are pre-declared, checked by a solver-independent validator, and never silently relaxed: infeasibility returns an explicit INFEASIBLE status with CP-SAT's sufficient-assumption conflict set mapped back to named constraints. Baseline (current crop history) is always reported as a labelled strategy even when it violates constraints.

**Consequences.** Deterministic, testable without a database; solver and engine versions are recorded on every run; the API layer only serializes.

## ADR-0016 — Candidate generation treats unevaluated as a first-class outcome; optimization admits only evaluated candidates

**Context.** Master rule 11 (missing ≠ zero) and M5.3 require distinguishing eligible / conditionally eligible / excluded / unevaluated candidates with explanations.

**Decision.** A crop enters optimization ONLY if it is eligible or conditionally eligible AND every dimension the active hard constraints need is evaluable (e.g. with a hard water allocation, a crop whose ETc cannot be estimated from real ET0 + sourced Kc evidence is excluded from optimization with that reason — a partial check is never labelled as full compliance). Exclusions carry the rule/evidence that produced them; unevaluated dimensions are listed with missing-input reasons. Synthetic-labelled feature evidence is consumed but flagged end-to-end ("historical proxy, synthetic — never real farm evidence").

**Consequences.** No silent zero-fill, no guessed water coefficients, no fake precision; the honest cost is smaller feasible sets when evidence is thin, which the UI explains.

## ADR-0017 — Water requirement is a documented screening estimate (single Kc × ET0), only when both evidences exist

**Context.** M5.4 needs a water-allocation hard constraint; M7 will deliver the full FAO-56 daily water balance. Available evidence today: monthly ET0 totals from feature runs + FAO-56 stage Kc tables.

**Decision.** Crop evapotranspiration is estimated as Σ_months (Kc(month) × ET0_total(month)) with Kc(month) derived from FAO-56 stage lengths assuming sowing at the planning-season start (assumption recorded in the run and the UI). The estimate is labelled `screening_estimate`, and superseded by M7's daily water balance. With no ET0 evidence, no Kc table, or no water allocation constraint, water criteria are unevaluated — never approximated.

**Consequences.** The allocation constraint is only enforced over crops with estimable ETc; others are held out of allocation-constrained runs (ADR-0016) with the reason surfaced.

## ADR-0018 — Multi-objective evaluation normalizes against the generated candidate set and reports evidence coverage, not confidence

**Context.** M5.5 forbids invented confidence scores; criterion availability varies with data.

**Decision.** Each strategy retains RAW criterion values, min-max normalized scores computed within the evaluated candidate set of the run (normalization documented per criterion), strategy weights (renormalized over evaluable criteria with the skipped ones listed), trade-off notes vs the best-in-criterion and vs baseline, missing-evidence lists, and the knowledge-pack/feature-run/engine/solver versions used. The only aggregate transparency metric is `evidence_coverage` — the fraction of criteria evaluable from evidence — explicitly NOT a confidence score. Pareto dominance is computed over evaluable criteria only; solutions with different evaluable-criterion sets are never compared as if commensurable (dominance restricted to the shared evaluable set, restriction recorded).

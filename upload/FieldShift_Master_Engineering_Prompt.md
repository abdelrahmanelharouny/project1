---
title: "FieldShift"
subtitle: "Master Engineering Prompt — Product, Architecture, Data Platform & Implementation Specification"
date: "30 October 2026"
---

## Document Contents

- Part I — Execution Prompt for the Coding Agent
- Part II — Product Definition
- Part III — Technical Architecture
- Part IV — Data Platform
- Part V — Database Design
- Part VI — Agricultural Intelligence and Algorithms
- Part VII — Additional Innovative Features
- Part VIII — API Contracts
- Part IX — Frontend and Farmer Experience
- Part X — Security, Privacy, Reliability and Operations
- Part XI — Testing and Acceptance
- Part XII — Implementation Roadmap
- Part XIII — Required Repository Structure
- Part XIV — Required Documentation
- Part XV — Implementation Order and First Task
- Part XVI — Official Technical and Scientific References

**Document type:** Product Requirements + Technical Architecture + Data Engineering Specification + Implementation Instructions  
**Target coding agent:** GLM (or another repository-aware coding agent)  
**Product scope:** Global-capable agricultural decision-support platform  
**Implementation strategy:** Full engineering project, delivered incrementally through verified milestones  
**Primary data constraint:** NASA data connectors are NOT available or required for the initial implementation. The system must work with alternative sources, farmer-provided data, imported files, and explicitly labelled synthetic fixtures. NASA support is a future adapter, not a current dependency.

---

# PART I — EXECUTION PROMPT FOR THE CODING AGENT

## 1. Your Role

You are acting as a principal software architect, senior Python backend engineer, geospatial data engineer, agricultural decision-support engineer, optimization engineer, frontend architect, QA engineer, and technical writer working as one disciplined engineering team.

Your task is to implement **FieldShift**, a maintainable, testable, explainable, global-capable agricultural decision-support platform. You are not being asked to create a mock landing page, a static dashboard, a notebook-only prototype, or a collection of disconnected API calls. You must build a coherent software product with clear domain boundaries, reproducible analytical pipelines, traceable data, robust APIs, a useful farmer experience, and automated tests.

You must work directly in the repository available in your environment. Before changing anything, inspect the existing repository, identify its current state, and preserve useful existing work. Do not assume that the repository is empty.

## 2. Mission

Build a system that helps farmers and agricultural advisors explore, compare, and improve crop-rotation strategies by combining:

1. Environmental and climate information.
2. Soil measurements and soil-property estimates.
3. Crop characteristics and regional agronomic knowledge.
4. Farm history and management practices.
5. Farmer priorities, resource limits, market access, and equipment constraints.
6. Explainable optimization and scenario simulation.

The product must help users understand not only **which rotation alternatives are possible**, but also:

- why each alternative was generated;
- which hard constraints it satisfies or violates;
- what data and agronomic knowledge support it;
- what the trade-offs are between water, soil, economic return, resilience, and operational feasibility;
- what information is missing;
- where uncertainty is high;
- what must be reviewed by a local agronomist or the farmer before acting.

FieldShift is a **decision-support system**, not an autonomous agronomist and not a guarantee of yield, water savings, soil improvement, or profit.

## 3. Non-Negotiable Execution Rules

Follow these rules throughout implementation:

1. **Inspect before modifying.** Start with `pwd`, repository tree, git status, existing README, dependency manifests, tests, and current application entry points. Do not overwrite or delete existing work without understanding it.
2. **Implement in vertical slices.** Deliver a working end-to-end path early, then expand it. Do not create dozens of empty files and claim completion.
3. **Do not stop at architecture documents.** Documentation is required, but you must implement and test actual application code.
4. **Do not implement the entire product in one uncontrolled code dump.** Follow the milestones in this document. Finish one milestone with tests and a concise report before moving to the next.
5. **Use currently supported stable dependency versions.** Verify the current official documentation when selecting versions. Pin exact resolved versions in lock files. Do not invent package versions.
6. **Never fabricate scientific data, crop traits, crop calendars, crop coefficients, disease rules, or model accuracy.** Unknown values must remain unknown and carry a missing-data reason.
7. **Synthetic data must always be visibly labelled.** It must never be mixed with observed or externally sourced data without explicit provenance fields.
8. **NASA is future-only.** Do not block the project on NASA Earthdata credentials, NASA APIs, NASA data downloads, or NASA connectors. Create clean extension points so future NASA providers can be added without changing business logic. Do not spend the first implementation phase writing inactive NASA connector stubs beyond documented interfaces and adapter registration tests.
9. **Do not confuse data resolution with field-level truth.** Never upsample coarse raster data and claim that the resulting pixels have gained real spatial detail.
10. **Preserve source metadata.** Every environmental observation and derived feature must be traceable to its product, version, time range, spatial support, processing version, and quality state.
11. **Do not silently impute missing agricultural values.** If an input required for a calculation is missing, return a structured incomplete/not-evaluated result. Any optional imputation must be explicit, configurable, documented, and represented in provenance.
12. **Separate hard constraints from soft objectives.** A high weighted score must never compensate for violating a hard agronomic, legal, market, calendar, equipment, or water constraint.
13. **Do not claim an optimization solution is globally optimal unless the solver proves `OPTIMAL`.** Distinguish `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, timeout, and partial result states.
14. **Use deterministic tests.** Seed random generators and make synthetic scenario generation reproducible.
15. **Validate all geometry and units.** Invalid geometries, unsupported units, invalid time windows, and malformed source payloads must produce actionable errors.
16. **Keep business logic out of HTTP route handlers and UI components.** Use application services and domain modules.
17. **Protect tenant data.** Every farm/field query must be authorized against the requesting user’s organization or explicit membership.
18. **Add tests with every meaningful feature.** Do not postpone all testing until the end.
19. **Update documentation when behavior changes.** Keep API examples, schemas, architecture decisions, and setup instructions consistent with the implementation.
20. **Be honest in reports.** State what works, what is mocked, what is incomplete, and what has not been validated.

If you find a conflict between this prompt and the current repository, inspect the code and document the conflict before deciding. Prefer small, reversible changes.

## 4. Required First Response and Working Protocol

Before coding, produce a short implementation assessment containing:

- repository state and existing stack;
- current working features, if any;
- missing foundation components;
- conflicts with this specification;
- the first milestone you will implement;
- commands you intend to run for validation.

Then begin implementation. Do not ask the user to restate requirements already present in this document. Ask a question only if a missing decision genuinely blocks safe implementation; otherwise use the defaults in this specification and record the assumption in an ADR.

Maintain these project-control files:

- `docs/implementation/IMPLEMENTATION_STATUS.md` — completed, in-progress, blocked, and next tasks;
- `docs/implementation/DECISIONS_AND_ASSUMPTIONS.md` — assumptions and decisions;
- `docs/implementation/KNOWN_LIMITATIONS.md` — known limitations, data coverage gaps, and unvalidated behavior;
- `docs/implementation/TEST_MATRIX.md` — test scenarios and latest outcomes.

After every milestone:

1. run formatting and linting;
2. run relevant unit and integration tests;
3. run database migrations from a clean database where possible;
4. run frontend build/type checking if frontend code changed;
5. report exact commands and results;
6. update the project-control files;
7. list the next concrete tasks.

Do not report a test as passing unless it was actually run.

---

# PART II — PRODUCT DEFINITION

## 5. Product Name and Positioning

**Name:** FieldShift  
**Descriptor:** Adaptive Farm Intelligence & Crop-Rotation Decision Support  
**Product category:** Agricultural decision-support platform  
**Primary users:** Farmers, farm managers, agronomists, agricultural cooperatives, and agricultural research/advisory teams.

### Product statement

FieldShift helps farmers design, compare, stress-test, and learn from crop-rotation strategies using environmental observations, soil information, crop knowledge, farm records, and farmer-defined objectives. It provides transparent evidence and trade-offs while preserving farmer and agronomist authority over final decisions.

## 6. Target Users and Their Needs

### 6.1 Farmer

Needs:
- a simple explanation of field conditions;
- practical rotation alternatives;
- visibility into water and operational constraints;
- a clear seasonal action calendar;
- offline recording when connectivity is poor;
- a way to record actual activities and outcomes;
- control over which personal and farm data are shared.

The farmer should not need to understand NDVI, ET0, raster resolution, or optimization mathematics to use the main workflow.

### 6.2 Agronomist / Agricultural Advisor

Needs:
- source-level evidence and assumptions;
- crop and soil parameter inspection;
- rule review and override capabilities with audit history;
- missing-data and uncertainty diagnostics;
- comparison of alternative rotations;
- a way to add locally validated knowledge.

### 6.3 Farm Manager / Cooperative Manager

Needs:
- multiple fields and farms;
- resource and water allocation views;
- operational calendars;
- aggregated summaries with permissions;
- exportable reports.

### 6.4 Research / Platform Administrator

Needs:
- provider health and ingestion status;
- dataset and knowledge version management;
- quality and coverage monitoring;
- controlled access to aggregate, privacy-protected data;
- algorithm versioning and reproducibility.

## 7. Primary User Journey

The principal journey must work end to end:

1. User registers and creates or joins an organization.
2. User creates a farm and selects country, administrative region, timezone, currency, preferred language, and unit system.
3. User creates a field by drawing a polygon, importing GeoJSON, or entering a supported geospatial file.
4. System validates geometry, calculates area using an appropriate geodesic/projected method, and stores a versioned boundary.
5. User enters soil test values or imports a soil report.
6. User selects current/previous crops and records management practices.
7. System obtains available environmental data from configured alternative providers or accepts user-uploaded data.
8. System creates a field data-readiness report that shows what is available, its coverage, age, resolution, and quality.
9. System computes only the environmental/agronomic features for which the required inputs exist.
10. User configures priorities and hard constraints.
11. System creates a baseline representing the existing rotation and candidate rotation alternatives.
12. User compares alternatives by water, soil, operational, economic, and resilience criteria.
13. User runs climate/water stress scenarios.
14. User saves a plan and receives a season-oriented checklist.
15. During the season, user records actual operations, observations, and issues.
16. After harvest, user records yield, costs, water use, and feedback.
17. System compares expected versus observed outcomes and makes future estimates more locally informed, without silently rewriting historical decisions.

## 8. Scope and Non-Goals

### In scope

- Global-capable farm and field management.
- Geospatial field boundaries and environmental data extraction.
- Replaceable data providers.
- Alternative environmental datasets and user-uploaded files.
- Soil and crop knowledge catalogs.
- Crop history and farm management records.
- Data quality, lineage, uncertainty, and coverage reporting.
- Water budgeting.
- Soil-health indicator tracking.
- Crop rotation candidate generation and constrained optimization.
- Scenario analysis and stress testing.
- Pest/disease rotation warnings based on validated rules.
- Bare-soil-window and cover-crop planning.
- Explainable strategy comparison.
- Farmer journal, seasonal planning, offline capture, and synchronization.
- Agronomist review and approval workflow.
- Multi-language/unit support.

### Explicit non-goals for the initial release

- Autonomous crop disease diagnosis from a phone photo.
- Automated irrigation-valve control.
- Guaranteed yield or profit prediction.
- Guaranteed soil carbon sequestration estimates.
- Legal or subsidy advice.
- Fully validated crop recommendations for every country and crop.
- A general-purpose conversational AI that invents agronomic facts.
- Mandatory NASA integration.
- Training a new deep-learning model before a specific data-backed need exists.

---

# PART III — TECHNICAL ARCHITECTURE

## 9. Architecture Decision: Modular Monolith

Implement a **modular monolith** first. The modules must have clear boundaries, independent tests, and explicit contracts. Do not introduce microservices in the initial release.

Recommended top-level layers:

1. Presentation layer: React web/PWA.
2. API layer: FastAPI routes, authentication, authorization, request/response schemas.
3. Application layer: use cases and orchestration.
4. Domain layer: farms, crops, soil, water, rotations, scenarios, journal, knowledge.
5. Intelligence layer: feature calculations, optimization, simulation, explainability.
6. Data platform layer: provider adapters, ingestion, validation, normalization, provenance.
7. Infrastructure layer: PostgreSQL/PostGIS, object storage, Redis, background workers, logging.

### Dependency direction

- Presentation calls API contracts only.
- API calls application services.
- Application services coordinate domain services and repositories.
- Domain and intelligence modules must not import FastAPI request/response objects.
- Provider adapters must map external payloads into canonical DTOs; they must not return ORM entities.
- Repositories own persistence details.
- External provider SDKs must not leak into the domain layer.

### Asynchronous work

Use background jobs for large raster downloads, spatial extraction, long feature runs, optimization jobs, Monte Carlo simulations, report generation, and bulk imports.

The API should return `202 Accepted` plus a job identifier for work that should not block an HTTP request. Job state must be persisted in the database; Redis is a queue/cache, not the source of truth for job history.

## 10. Technology Stack

Use the following stack unless the existing repository has a strong, documented reason to differ:

### Backend
- Python 3.12 or a newer stable version supported by all selected scientific/geospatial dependencies.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2.x.
- Alembic.
- PostgreSQL with PostGIS.
- Pandas and/or Polars for tabular processing.
- NumPy and SciPy for numerical analysis.
- Xarray for multidimensional gridded/time-series data.
- GeoPandas, Shapely, Rasterio, and PyProj for geospatial processing.
- Pint for unit-aware conversions where appropriate.
- Google OR-Tools CP-SAT for constrained rotation optimization.
- Pytest for backend tests.

### Frontend
- React with TypeScript.
- Vite unless the existing application uses another suitable framework.
- Tailwind CSS or the existing design system.
- MapLibre GL JS for interactive maps.
- Apache ECharts or an equivalent maintained charting library for analytical charts.
- TanStack Query or an equivalent server-state library.
- A lightweight client state store only where needed.
- PWA service worker and IndexedDB for offline workflows.
- Vitest and React Testing Library; Playwright for end-to-end tests.

### Infrastructure
- Docker and Docker Compose for local development.
- PostgreSQL/PostGIS.
- Redis for background job brokering/caching when required.
- Celery or a similarly maintained task queue. Keep the queue interface replaceable.
- S3-compatible object storage; MinIO for local development.
- Structured application logging.
- OpenTelemetry-compatible tracing/metrics hooks where feasible.

### Version discipline

Do not hard-code arbitrary versions from this prompt. Check official documentation and package compatibility at implementation time, resolve dependencies, pin exact versions in lock files, and record the selected versions in `docs/architecture/technology-decisions.md`.

---

# PART IV — DATA PLATFORM

## 11. Data Source Strategy

The initial product must run without NASA. Implement alternative providers and imports now, while keeping the canonical data model provider-independent.

### 11.1 Initial providers and source types

#### A. Open-Meteo Historical Weather API

Use for suitable historical climate variables such as air temperature, precipitation where provided by the selected model, humidity, wind, radiation, ET0 where supported, and soil variables only when the selected model/product exposes them.

Implementation requirements:
- Explicitly select the model/product rather than relying blindly on a changing default.
- For multi-decadal climate trend analysis, prefer a consistent reanalysis product such as ERA5 or ERA5-Land over a seamlessly changing best-match series.
- Store model name, product/version, spatial resolution, temporal resolution, retrieval time, timezone basis, and variable metadata.
- Respect the provider's allowed request sizes, caching guidance, rate limits, attribution, and terms.
- Treat reanalysis as model-based gridded data, not a direct field sensor observation.

Official documentation: https://open-meteo.com/en/docs/historical-weather-api

#### B. CHIRPS v3

Use as an alternative quasi-global rainfall dataset. It is land-focused and spans approximately 60 degrees north to 60 degrees south, with near-global longitude coverage and a 0.05-degree grid. The provider publishes preliminary and final products. Select and record which product was used.

Implementation requirements:
- Prefer pentadal/monthly/annual products for climate summaries where appropriate.
- Use daily products carefully; do not use downscaled daily fields as unquestioned evidence for daily rainfall extremes.
- Do not claim global coverage outside its documented latitude/land coverage.
- Preserve native raster resolution and nodata masks.
- Record product version and preliminary/final status.
- Provide a bulk/file ingestion workflow and a spatial-subset extraction workflow.

Official sources:
- https://www.chc.ucsb.edu/data/chirps3
- https://www.chc.ucsb.edu/data

#### C. SoilGrids

Use as an optional gridded soil-property source, never as a replacement for field laboratory analysis. It offers global soil-property predictions and uncertainty information, but the REST API may be unavailable or unstable.

Implementation requirements:
- Do not depend on the SoilGrids REST API for core application availability.
- Prefer documented WCS spatial subsets or WebDAV-hosted data where operationally suitable.
- Record property, depth interval, quantile, units, prediction interval, source version, and spatial support.
- Treat values as model predictions with uncertainty, not measured field samples.
- Expose a provider-health state and graceful degradation.

Official sources:
- https://docs.isric.org/globaldata/soilgrids/
- https://docs.isric.org/globaldata/soilgrids/wcs.html
- https://docs.isric.org/globaldata/soilgrids/WebDav.html

#### D. FAO GAEZ

Use crop suitability and agroecological context as broad screening information. GAEZ is not field-level ground truth. Its regular grid is coarse relative to many farms.

Implementation requirements:
- Import only the modules/products needed for supported workflows.
- Record baseline, climate scenario, management level, irrigation/rainfed context, crop, and product version.
- Show the product's spatial support and limitations.
- Never translate suitability classes directly into a guaranteed crop recommendation.

Official source: https://www.fao.org/gaez/gaezv4/en

#### E. FAO Crop Calendar

Use as a reference for planting and harvesting windows where applicable. Do not assume an official public API exists. Build a curated import mechanism with region, crop, season, source, effective dates, and validation status.

Official portal: https://cropcalendar.apps.fao.org/

#### F. Farmer-provided data

Support structured forms and file imports for:
- soil laboratory reports;
- crop history;
- field boundaries;
- irrigation events and allocations;
- yield and harvest records;
- management practices;
- crop calendars validated by local advisors;
- equipment and market constraints.

Support CSV and GeoJSON in the initial implementation. Add GeoPackage and other formats through a controlled import pipeline, not by trusting arbitrary files.

#### G. Synthetic fixtures

Create reproducible synthetic environments for testing. These must have `is_synthetic=true`, an explicit generator version, seed, scenario profile, and purpose. Never display synthetic measurements as real observations.

### 11.2 Future NASA integration

NASA is not an initial runtime dependency. Keep extension points for future products such as SMAP, GPM, Landsat, MODIS, ECOSTRESS, GRACE/GRACE-FO, NASA POWER, and elevation products. Do not implement these integrations until the project has a clear use case, access plan, product documentation review, and tests.

When a NASA provider is eventually added, it must implement the same provider contracts and canonical output schemas as all other sources.

## 12. Provider Abstraction

Define provider interfaces around normalized domain data, not provider-specific response payloads.

Suggested interfaces:

```python
from datetime import datetime
from typing import Protocol, Sequence

class EnvironmentalDataProvider(Protocol):
    provider_code: str

    async def fetch_observations(
        self,
        *,
        area_of_interest: "AreaOfInterest",
        variables: Sequence[str],
        start: datetime,
        end: datetime,
        options: dict | None = None,
    ) -> "ProviderFetchResult":
        ...
```

Also define separate contracts for:
- raster providers;
- tabular providers;
- soil-property providers;
- crop-knowledge importers;
- local file importers.

A provider result should include:
- normalized observations or asset references;
- source/product identifiers;
- retrieval metadata;
- coverage diagnostics;
- warnings;
- provider request identifier;
- raw payload/file reference where retention is permitted.

### Provider registry

Implement a registry/factory keyed by provider code. Use configuration to activate/deactivate providers. A provider outage must not crash unrelated application modules. Provider errors must be surfaced as structured job failures and data-coverage warnings.

### Provider contract tests

Each provider must pass the same contract suite:
- returns valid canonical objects;
- includes provenance;
- preserves native temporal support;
- includes units;
- flags missing/nodata values;
- rejects invalid date ranges and unsupported variables;
- handles timeouts and retryable errors;
- does not duplicate records on retry;
- is safe to rerun idempotently where possible.

## 13. Canonical Data Model

Create a canonical observation/asset model independent of data provider.

### 13.1 Observation fields

At minimum:

- `id` (UUID)
- `field_id` (nullable for broader area-level records)
- `variable_code`
- `value` (nullable if missing/nodata)
- `unit`
- `observed_at` or `period_start`/`period_end`
- `time_support` (instant, hourly, daily, pentadal, monthly, seasonal, etc.)
- `source_id`
- `dataset_product_id`
- `product_version`
- `spatial_support_type` (point, grid_cell, polygon_average, field_intersection, station, lab_sample)
- `spatial_resolution_m` where known
- `geometry` or raster/asset reference where applicable
- `quality_status`
- `uncertainty_value` and `uncertainty_type` where available
- `is_synthetic`
- `retrieved_at`
- `processing_version`
- `metadata` JSONB

Do not force every data type into one oversized table if the implementation needs separate raster assets and observation tables. Maintain the canonical semantics.

### 13.2 Source metadata

Every source/product must have:
- provider name;
- product code;
- product version;
- variables;
- unit conventions;
- spatial/temporal resolution;
- spatial/temporal coverage;
- license and attribution;
- documentation URL;
- retrieval method;
- known limitations;
- active/deprecated status.

### 13.3 Provenance graph

Derived features must point to the exact input observation/asset snapshot and processing version. Optimization runs must point to:
- feature snapshot;
- crop-knowledge version;
- constraint set version;
- objective weights;
- solver version and parameters;
- scenario assumptions;
- algorithm version.

Historical results must remain reproducible even after new data arrives.

## 14. Spatial and Temporal Harmonization

### 14.1 Spatial rules

- Store user field geometry in EPSG:4326 for interchange, with PostGIS geometry/geography support.
- Validate polygons, rings, holes, self-intersections, coordinate order, and antimeridian edge cases where relevant.
- Calculate area with geodesic or appropriate equal-area methods, not planar square degrees.
- Use spatial indexes for query performance.
- Preserve native input raster resolution and CRS.
- For raster extraction, record resampling method and aggregation method.
- Use area-weighted aggregation where appropriate; distinguish center-point sampling from polygon statistics.
- Preserve nodata masks and valid-pixel coverage.
- If field size is much smaller than source pixel size, show a warning that the estimate is not field-resolved.
- Never create false spatial precision by upsampling a coarse grid.

### 14.2 Temporal rules

- Store timestamps in UTC.
- Store farm timezone separately and use it for local operation calendars and UI display.
- Keep original temporal support. Do not transform a monthly total into daily values without a documented disaggregation model.
- Distinguish observation date, accumulation period, retrieval date, and publication date.
- Support growing seasons that cross calendar years and both hemispheres.
- Use crop- and region-specific growing windows; do not assume northern-hemisphere seasonality globally.
- For long-term trends, use internally consistent dataset products and document any product transitions.

### 14.3 Spatial-temporal resolution compatibility

The pipeline must be able to align variables for analysis without pretending they have equal information content. An analytical grid/time step is a processing choice, not a claim that all inputs have that precision. Keep per-variable native support metadata and quality flags after harmonization.

## 15. Unit System and Data Dictionary

Use SI units internally wherever sensible. Store the original source unit and conversion metadata where needed. Use a unit library for conversions where practical.

Examples:
- air temperature: degrees Celsius;
- precipitation depth: mm per defined period;
- soil moisture: m3/m3 when volumetric;
- ET0 and ETc: mm per defined period;
- water volume: m3;
- field area: hectares internally for agricultural summaries, with source geometry retained;
- soil organic carbon: source-defined unit, normalized only after verifying depth/basis;
- salinity: preserve method and unit (e.g. dS/m) because measurement method matters;
- yield: value + commodity-specific unit + moisture/content basis where relevant;
- price/cost: amount + ISO currency code + date + market/source.

Create a versioned data dictionary. Never convert values without preserving the source unit, conversion factor, and conversion version.

## 16. Data Quality, Coverage, and Uncertainty

Do not compress these concepts into one arbitrary confidence score. Represent them separately.

### 16.1 Quality status

Suggested statuses:
- `valid`
- `suspect`
- `invalid`
- `missing`
- `estimated`
- `not_assessed`

### 16.2 Coverage status

Suggested statuses:
- `complete_for_period`
- `partial`
- `outside_provider_coverage`
- `insufficient_spatial_support`
- `missing`
- `not_assessed`

### 16.3 Evidence class

Suggested classes:
- direct field measurement;
- farmer-reported record;
- station observation;
- satellite-derived estimate;
- reanalysis/model estimate;
- global soil prediction;
- curated agronomic reference;
- synthetic test data.

### 16.4 Uncertainty

- Preserve source prediction intervals or ensemble spread when provided.
- If uncertainty is unavailable, store `unknown`, not zero.
- Do not invent probabilistic confidence values.
- For derived features, describe uncertainty propagation method or mark it unquantified.
- Distinguish measurement uncertainty, model uncertainty, spatial representativeness uncertainty, and missing-data uncertainty where possible.

### 16.5 Field Data Passport

Build a dedicated **Field Data Passport** for each field. It should show:
- available variables;
- missing variables;
- source/product and version;
- time period covered;
- native spatial and temporal resolution;
- last retrieval date;
- data age/freshness;
- proportion of valid pixels/observations;
- observed vs estimated vs synthetic status;
- unresolved warnings;
- which analytical features are enabled/disabled as a result.

This is a key product feature: users should understand whether the field has enough evidence for a given analysis before receiving a rotation comparison.

---

# PART V — DATABASE DESIGN

## 17. Database Domains and Tables

Use PostgreSQL + PostGIS. Use UUID primary keys unless a table has a strong reason for another identifier. Include `created_at`, `updated_at`, and relevant actor/version fields. Use database constraints and indexes, not just application-level validation.

The following is the logical minimum. You may add tables when justified; do not collapse independent concepts into one opaque JSON field.

### 17.1 Identity and tenancy

#### `users`
- `id`
- `email` (unique, normalized)
- `password_hash` or external identity subject
- `display_name`
- `preferred_language`
- `timezone`
- `is_active`
- timestamps

#### `organizations`
- `id`
- `name`
- `organization_type`
- `country_code` nullable
- timestamps

#### `memberships`
- `id`
- `organization_id`
- `user_id`
- `role_code`
- `status`
- unique organization/user pair

Use explicit authorization checks for every farm/field resource.

### 17.2 Farms and fields

#### `farms`
- `id`
- `organization_id`
- `name`
- `country_code`
- `admin_region`
- `timezone`
- `currency_code`
- `unit_system`
- `preferred_language`
- timestamps

#### `fields`
- `id`
- `farm_id`
- `name`
- `area_ha`
- `boundary` as validated MULTIPOLYGON geometry with SRID 4326
- `boundary_version`
- `status`
- optional elevation/agroecological references
- timestamps

#### `field_boundary_versions`
- `id`
- `field_id`
- `version_number`
- `boundary`
- `area_ha`
- `change_reason`
- `created_by`
- `created_at`

Do not overwrite boundary history without a version record.

### 17.3 Data registry and ingestion

#### `data_sources`
- `id`
- `provider_code`
- `provider_name`
- `base_url`
- `license_name`
- `license_url`
- `attribution_text`
- `documentation_url`
- `status`

#### `dataset_products`
- `id`
- `source_id`
- `product_code`
- `product_version`
- `description`
- `spatial_resolution_m`
- `temporal_resolution`
- `coverage_geometry` or coverage metadata
- `valid_from`, `valid_to`
- `metadata`

#### `data_assets`
- `id`
- `dataset_product_id`
- `storage_uri`
- `file_format`
- `checksum`
- `spatial_extent`
- `temporal_start`, `temporal_end`
- `retrieved_at`
- `ingestion_job_id`
- `metadata`

#### `ingestion_jobs`
- `id`
- `provider_code`
- `request_parameters`
- `status`
- `started_at`, `completed_at`
- `records_received`, `records_rejected`
- `warnings`, `error_summary`
- `idempotency_key`

#### `observations`
- `id`
- `field_id` nullable
- `dataset_product_id`
- `asset_id` nullable
- `variable_code`
- `value` nullable
- `unit`
- `observed_at` nullable
- `period_start`, `period_end`
- `time_support`
- `spatial_support_type`
- `spatial_resolution_m`
- `quality_status`
- `uncertainty_value`, `uncertainty_type`
- `is_synthetic`
- `metadata`

#### `observation_quality_flags`
- `id`
- `observation_id`
- `flag_code`
- `severity`
- `message`
- `details`

### 17.4 Soil data

#### `soil_samples`
- `id`
- `field_id`
- `sampled_at`
- `depth_top_cm`
- `depth_bottom_cm`
- `sampling_method`
- `laboratory_name`
- `sample_geometry` or location
- `source_type`
- `reported_by`
- `metadata`

#### `soil_measurements`
- `id`
- `soil_sample_id`
- `property_code`
- `value`
- `unit`
- `analytical_method`
- `quality_status`
- `source_reference_id`

Do not mix SoilGrids map predictions with lab measurements in the same evidence class.

### 17.5 Crop knowledge

#### `crop_families`
- `id`
- `scientific_name`
- `common_names`

#### `crops`
- `id`
- `scientific_name`
- `common_names`
- `crop_family_id`
- `crop_category`
- `life_cycle_type`
- `is_legume`
- `is_cover_crop`
- `status`

These broad flags are descriptors, not sufficient evidence for agronomic conclusions.

#### `crop_varieties`
- `id`
- `crop_id`
- `variety_name`
- `region_code` nullable
- `maturity_group` nullable
- `metadata`

#### `crop_traits`
- `id`
- `crop_id` or `crop_variety_id`
- `trait_code`
- `value_numeric` or `value_text`
- `unit`
- `region_code` or geometry where relevant
- `management_context`
- `source_reference_id`
- `evidence_class`
- `valid_from`, `valid_to`
- `validation_status`

#### `crop_calendar_windows`
- `id`
- `crop_id`
- `region_code` / agroecological zone
- `season_code`
- `planting_start`, `planting_end`
- `harvest_start`, `harvest_end`
- `hemisphere_or_seasonality_context`
- `source_reference_id`
- `validation_status`

#### `crop_water_parameters`
- `id`
- `crop_id`
- `variety_id` nullable
- `growth_stage`
- `kc_value`
- `kc_method` (single/dual)
- `valid_region`
- `climate_context`
- `source_reference_id`
- `validation_status`

Never populate all crops with guessed water coefficients. A crop with no verified parameter must remain unsupported for that calculation.

### 17.6 Water and irrigation

#### `water_sources`
- `id`
- `farm_id`
- `source_type` (surface, groundwater, rainwater_storage, reclaimed, other)
- `name`
- `quality/salinity metadata` where available
- `metadata`

#### `water_allocations`
- `id`
- `farm_id` or `field_id`
- `water_source_id`
- `period_start`, `period_end`
- `available_volume_m3`
- `allocation_basis`
- `source_reference_id`

#### `irrigation_events`
- `id`
- `field_id`
- `event_at`
- `applied_depth_mm` or `volume_m3`
- `irrigation_method`
- `application_efficiency` nullable
- `recorded_by`
- `evidence_class`

### 17.7 Farmer preferences and constraints

#### `farmer_preferences`
- `id`
- `farm_id`
- `objective_weights` JSONB or normalized child table
- `risk_tolerance`
- `preferred_strategy_style`
- `updated_at`

#### `farm_constraints`
- `id`
- `farm_id` or `field_id`
- `constraint_code`
- `operator`
- `value_numeric` / `value_text` / structured value
- `unit`
- `is_hard_constraint`
- `valid_from`, `valid_to`
- `source` (farmer/advisor/regulation/system)
- `metadata`

### 17.8 Crop history and management

#### `crop_history`
- `id`
- `field_id`
- `crop_id`
- `variety_id` nullable
- `sowing_date`
- `harvest_date`
- `season_label`
- `area_ha`
- `source/evidence class`

#### `management_events`
- `id`
- `field_id`
- `event_type`
- `event_date`
- `crop_id` nullable
- `quantity`, `unit`
- `description`
- `recorded_by`
- `evidence_class`
- `metadata`

Examples include planting, harvesting, fertilizer application, irrigation, tillage, cover-crop termination, residue incorporation, pest treatment, and soil sampling.

#### `harvest_records`
- `id`
- `field_id`
- `crop_id`
- `season_start`, `season_end`
- `yield_value`
- `yield_unit`
- `harvest_area_ha`
- `production_cost`
- `selling_price`
- `currency_code`
- `moisture_basis` / quality basis where relevant
- `recorded_by`

### 17.9 Feature and analytics runs

#### `feature_runs`
- `id`
- `field_id`
- `data_snapshot_id`
- `processing_version`
- `status`
- `started_at`, `completed_at`
- `warnings`

#### `feature_values`
- `id`
- `feature_run_id`
- `feature_code`
- `period_start`, `period_end`
- `value` nullable
- `unit`
- `quality_status`
- `uncertainty_value` nullable
- `metadata`

### 17.10 Rotation and optimization

#### `rotation_plans`
- `id`
- `field_id`
- `name`
- `plan_type` (baseline/manual/candidate/approved)
- `planning_start`, `planning_end`
- `version`
- `status`
- `created_by`

#### `rotation_slots`
- `id`
- `rotation_plan_id`
- `sequence_order`
- `season_start`, `season_end`
- `main_crop_id`
- `cover_crop_id` nullable
- `management_strategy`

#### `optimization_runs`
- `id`
- `field_id`
- `request_snapshot`
- `feature_snapshot_id`
- `crop_knowledge_version`
- `algorithm_version`
- `solver_name`, `solver_version`
- `solver_status`
- `runtime_seconds`
- `created_at`, `completed_at`

#### `rotation_scenarios`
- `id`
- `optimization_run_id`
- `name`
- `scenario_type`
- `feasibility_status`
- `overall_score` nullable
- `pareto_rank` nullable
- `explanation_summary`

#### `scenario_slots`
- `id`
- `rotation_scenario_id`
- `sequence_order`
- `crop_id`
- `cover_crop_id` nullable
- `season_start`, `season_end`

#### `scenario_criterion_results`
- `id`
- `rotation_scenario_id`
- `criterion_code`
- `raw_value` nullable
- `normalized_value` nullable
- `weight` nullable
- `contribution` nullable
- `unit`
- `evidence_status`
- `uncertainty_summary`

#### `scenario_explanations`
- `id`
- `rotation_scenario_id`
- `explanation_type`
- `claim_text`
- `evidence_ids`
- `rule_ids`
- `limitations`

### 17.11 Simulation

#### `stress_test_runs`
- `id`
- `optimization_run_id`
- `scenario_definition`
- `simulation_method`
- `random_seed`
- `simulation_version`
- `status`

#### `stress_test_results`
- `id`
- `stress_test_run_id`
- `rotation_scenario_id`
- `metric_code`
- `summary_statistics`
- `unit`
- `limitations`

### 17.12 Soil ledger and farm memory

#### `soil_assessments`
- `id`
- `field_id`
- `assessment_date`
- `indicator_code`
- `measured_value` nullable
- `estimated_value` nullable
- `unit`
- `evidence_class`
- `source_reference_id`
- `model_version`

#### `farm_journal_entries`
- `id`
- `field_id`
- `entry_at`
- `entry_type`
- `text_content`
- `voice_asset_id` nullable
- `transcription_status`
- `recorded_by`
- `sync_status`

#### `farmer_feedback`
- `id`
- `rotation_scenario_id` nullable
- `field_id`
- `feedback_type`
- `rating` nullable
- `notes`
- `created_by`

### 17.13 Knowledge evidence and governance

#### `knowledge_sources`
- `id`
- `publisher`
- `title`
- `url`
- `publication_date`
- `license`
- `citation_text`

#### `knowledge_rules`
- `id`
- `rule_code`
- `rule_type`
- `region_scope`
- `rule_definition`
- `severity`
- `source_id`
- `validation_status`
- `valid_from`, `valid_to`
- `reviewed_by`

#### `agronomist_reviews`
- `id`
- `target_type`
- `target_id`
- `review_status`
- `review_notes`
- `reviewer_id`
- `reviewed_at`

### 17.14 Jobs, audit, and offline synchronization

#### `background_jobs`
- `id`
- `job_type`
- `status`
- `progress`
- `input_reference`
- `result_reference`
- `error_code`, `error_message`
- `created_by`
- timestamps

#### `audit_events`
- `id`
- `actor_id`
- `organization_id`
- `entity_type`
- `entity_id`
- `action`
- `before_snapshot`
- `after_snapshot`
- `created_at`

#### `sync_events`
- `id`
- `device_id`
- `client_event_id`
- `entity_type`
- `entity_id`
- `operation`
- `payload`
- `sync_status`
- `conflict_reference`
- `created_at`

Add appropriate unique constraints, foreign keys, check constraints, composite indexes, and spatial indexes. Use JSONB for genuinely variable metadata, not as a substitute for relational structure.

---

# PART VI — AGRICULTURAL INTELLIGENCE AND ALGORITHMS

## 18. Feature Engineering Framework

Create a feature registry rather than scattering formulas across services.

Each feature definition must contain:
- feature code;
- display name and description;
- input variable codes;
- formula or algorithm reference;
- unit;
- temporal support;
- spatial support;
- minimum data coverage;
- quality requirements;
- missing-input behavior;
- version;
- evidence/source reference where the formula is agronomic.

### 18.1 Environmental feature candidates

- seasonal rainfall total;
- monthly rainfall climatology;
- rainfall anomaly against a declared baseline;
- number and duration of dry spells under a configurable definition;
- mean/min/max temperature;
- growing-degree days only when crop-specific base/upper thresholds are sourced;
- heat-stress days relative to crop/phenological thresholds with regional validity;
- frost exposure only where the data and crop thresholds support it;
- reference evapotranspiration ET0;
- soil-moisture anomaly by depth and product;
- vegetation index summaries where an imagery provider is implemented;
- bare-soil-window evidence from crop records/calendar and, when available, remote-sensing indicators.

Do not calculate NDVI from data that do not include the required reflectance bands. Do not infer crop type from NDVI alone.

### 18.2 Soil and agronomic features

- pH status relative to crop-specific reference ranges;
- texture class from valid sand/silt/clay values;
- organic-carbon history;
- salinity status where measurement methods are known;
- soil-water holding proxies only when required parameters are available;
- crop-family diversity;
- crop sequence history;
- nitrogen input/output budget where inputs and outputs are sufficiently documented;
- cover duration;
- erosion susceptibility indicators only with a documented method and adequate terrain/rainfall/soil inputs.

### 18.3 Missing data behavior

If a feature cannot be computed, store a missing result with a reason code. Examples:
- `MISSING_REQUIRED_VARIABLE`
- `INSUFFICIENT_TEMPORAL_COVERAGE`
- `SPATIAL_RESOLUTION_TOO_COARSE`
- `UNVERIFIED_CROP_PARAMETER`
- `UNSUPPORTED_REGION`
- `INVALID_UNIT`

Never use zero as a synonym for unknown.

## 19. Crop Rotation Candidate Generation and Optimization

### 19.1 Inputs

- field area and boundary;
- planning horizon and season definitions;
- current and previous crop history;
- crop catalog and variety information;
- regional calendars;
- crop traits and water parameters;
- soil observations/estimates;
- climate and water features;
- farm constraints;
- farmer objective weights;
- validated pest/pathogen rotation rules;
- equipment, labor, market, and storage constraints where supplied.

### 19.2 Baseline scenario

Always include the existing rotation or farmer-entered baseline. If the history is incomplete, clearly label the baseline as partial/incomplete. Do not invent a historical sequence.

### 19.3 Candidate generation

Generate a candidate crop set using transparent filters:
- crop data available for the relevant region;
- crop calendar does not conflict with the planning window;
- crop traits satisfy the user's stated constraints where known;
- soil/environment evidence does not indicate a clearly disqualifying condition;
- crop parameters required for objective calculation exist.

A crop with insufficient evidence may appear in an exploratory list only if clearly labelled `NEEDS_LOCAL_REVIEW`; it must not silently enter the validated recommendation set.

### 19.4 Hard constraints

Examples:
- at most one primary crop per field/season unless intercropping is explicitly modeled;
- sowing and harvest windows must fit the planning horizon;
- crop duration must fit the selected calendar window;
- seasonal irrigation demand must not exceed an explicitly supplied water allocation when this is a hard constraint;
- excluded crops must not be selected;
- equipment/labor/market constraints must be honored if marked hard;
- pest/pathogen break rules only apply when the rule has valid regional scope and adequate evidence;
- soil and salinity restrictions only apply when required measurements/estimates are available and the rule is validated.

Unknown constraints must not be interpreted as satisfied. Return `not_evaluated` where necessary.

### 19.5 Soft objectives

Support objective criteria such as:
- lower modeled irrigation requirement;
- improved crop-family diversity;
- contribution to nitrogen cycling where evidence supports the estimate;
- reduced bare-soil duration;
- lower erosion susceptibility under documented assumptions;
- potential gross margin or contribution margin where market data are provided;
- crop calendar flexibility;
- resilience under selected stress scenarios;
- risk diversification across crops.

Do not equate legume presence with a fixed nitrogen gain. The amount of nitrogen fixation depends on species, variety, biomass, inoculation, soil, management, and residue handling.

### 19.6 Optimization method

Use Google OR-Tools CP-SAT for discrete sequencing and constraints. Keep the solver behind an `OptimizationSolver` interface.

Model decisions as binary or integer variables for crop/season/management choices. Use integer-scaled coefficients for CP-SAT objectives, document the scaling, and test rounding behavior.

For multiple objectives, produce a set of non-dominated or trade-off solutions using a documented method such as repeated epsilon-constraint solves or carefully defined weighted runs. Do not imply that one weighted sum captures every possible Pareto solution.

Persist:
- solver status;
- runtime;
- optimality/bound details when available;
- objective coefficients and normalization rules;
- input snapshots;
- solver/library version;
- all hard-constraint outcomes.

### 19.7 Scoring and ranking

Do not produce an overall score when required criteria are missing or incomparable. When a score is permitted:
- normalize each objective using fixed/source-defined or declared reference ranges;
- disclose directionality (higher/lower is better);
- preserve raw values next to normalized values;
- apply farmer weights transparently;
- show criterion coverage;
- make missing criteria visible rather than silently filling them;
- avoid comparing incomparable units without a documented normalization.

### 19.7.1 Soil-health objective guardrail

The optimizer must not treat a generic soil-health score as a physically measured quantity. Implement soil-related objectives as explicit, separately reported indicators or evidence-backed proxies (for example, cover duration, crop-family diversity, or a documented nutrient-balance estimate). If the available data do not support a defensible soil-health objective for a field, mark that objective as unavailable and do not let a fabricated composite score influence the ranking. Any later composite index must have a published definition, weights, regional validity, sensitivity analysis, and agronomist review.

### 19.8 Output status vocabulary

Use statuses such as:
- `feasible`;
- `infeasible`;
- `not_evaluated`;
- `needs_local_review`;
- `insufficient_data`;
- `candidate_only`;
- `approved_by_advisor`.

A strategy must never be labelled “best” without specifying the objective context and evidence limitations.

## 20. Water Intelligence Engine

### 20.1 Main concept

Use the FAO-56 crop coefficient approach where inputs and crop parameters are available:

`ETc = Kc × ET0`

ET0 is reference evapotranspiration; Kc varies with crop and development stage. The implementation must preserve whether the input is single-Kc or dual-Kc. Do not assume a constant Kc across the whole season where stage-specific coefficients are available or required.

### 20.2 Water balance

Implement a clearly documented, configurable water-balance calculation. A simplified root-zone accounting form may be used only when its assumptions are explicit:

`Net irrigation need = max(0, ETc - effective_rainfall - usable_soil_water_change - capillary_rise_contribution)`

where terms are defined with consistent signs and units. If soil-water storage, effective rainfall, capillary rise, runoff, deep percolation, salinity leaching, or other terms are unavailable, do not pretend the simplified estimate is a complete irrigation prescription.

Gross applied irrigation may be approximated as net irrigation divided by application efficiency only when a defensible efficiency value is provided or explicitly assumed and shown.

### 20.3 Required outputs

- crop ET estimate by growth stage and period;
- rainfall contribution estimate and method;
- estimated net irrigation requirement;
- gross irrigation estimate only when efficiency inputs exist;
- water allocation versus estimated requirement;
- water deficit/surplus by period;
- missing inputs and assumptions;
- uncertainty or range where supported;
- comparison across rotation scenarios.

### 20.4 Additional controls

- keep units consistent (mm, m3, ha);
- convert 1 mm over 1 hectare to 10 m3 correctly;
- do not confuse ET with withdrawal or applied irrigation;
- account for irrigation method and efficiency only if available;
- consider salinity/leaching requirements separately and only with appropriate local evidence;
- do not issue real-time irrigation instructions without validated local sensor/field inputs and expert-approved thresholds.

## 21. Soil Health Ledger

Build an indicator-based ledger rather than one opaque “soil health score.”

Track, where data exist:
- soil organic carbon / organic matter;
- pH;
- electrical conductivity/salinity;
- texture;
- bulk density;
- total nitrogen and nutrient measurements;
- soil moisture;
- cover duration;
- management events;
- crop-family diversity;
- erosion-related indicators.

Every value must identify whether it is:
- measured by a laboratory;
- reported by the farmer;
- estimated from a gridded model;
- calculated from a transparent nutrient budget;
- inferred from a remote-sensing product.

The ledger must show trends only when repeated comparable measurements exist. Warn when sampling depth, season, laboratory method, or analytical units differ. Never claim a measured increase in soil organic carbon based solely on a management event or a one-season model estimate.

### Nutrient budget

A later module may calculate partial nutrient balances using measured/recorded inputs and outputs. It must expose uncounted pathways and uncertainties. Biological nitrogen fixation, residue mineralization, leaching, gaseous losses, and crop uptake cannot be assumed as fixed constants without appropriate evidence.

## 22. Climate Stress Testing Lab

Separate stress testing from forecasting.

### Scenario types
- historical reference period;
- user-defined rainfall reduction/increase;
- user-defined temperature shift;
- water-allocation reduction;
- shifted season timing;
- combined heat and drought;
- selected climate-projection dataset scenario when added later.

Every result must state that a user-defined perturbation is a hypothetical scenario, not a forecast.

### Sensitivity analysis

Start with deterministic sensitivity analysis (for example, a range of rainfall and water allocation changes). Add Monte Carlo only when suitable distributions and dependencies can be justified from data.

If using stochastic simulations:
- set and persist random seeds;
- preserve observed dependence/correlation among climate variables where possible;
- do not independently randomize variables when this creates physically implausible combinations;
- report distributions and intervals, not a false precise probability;
- make model assumptions visible.

### Output metrics
- feasibility under scenario;
- estimated water deficit;
- crop stress indicator where model supports it;
- changes in objective values;
- relative ranking stability;
- failure points and threshold crossings;
- data/model limitations.

## 23. Bare Soil Window and Cover-Crop Planner

Calculate candidate bare-soil windows using crop history, crop calendars, sowing/harvest dates, and management records. Remote-sensing evidence may be added when an appropriate product is implemented.

The planner should:
- estimate the gap between harvest and next sowing;
- report the evidence used to estimate bare-soil duration;
- identify cover-crop candidates only when regional calendar, water, and agronomic data support them;
- assess whether a cover crop could compete for scarce water before the next cash crop;
- include termination timing and equipment constraints;
- avoid suggesting cover crops in windows that are operationally or climatically unsuitable.

## 24. Pest and Disease Rotation Intelligence

Build a curated, evidence-backed rule engine first. A full knowledge graph is optional later.

A rule should contain:
- pest/pathogen identifier;
- affected host crops and varieties where known;
- relevant crop families where evidence supports it;
- region/season/soil/climate applicability;
- break-period guidance and its source;
- management/context dependencies;
- severity and confidence/evidence status;
- source citation;
- agronomist review state.

Rules without region-specific validity must be warnings for review, not hard constraints. Do not generalize disease cycles based only on botanical family.

## 25. Farm Memory and Learning Loop

Record:
- planned crops and dates;
- actual planting/harvest dates;
- irrigation and input quantities;
- management events;
- pest/disease events;
- observed weather impacts;
- actual yield and quality;
- costs and selling prices where supplied;
- farmer feedback and reasons for plan changes.

The comparison engine should show planned versus actual outcomes. Historical recommendations must remain immutable and versioned. Any future personalization or model calibration must be explicit, validated, consent-aware, and reversible.

Do not automatically train models on user records. Add an opt-in data contribution and privacy policy before any aggregated learning workflow.

## 26. Explainability and Evidence Engine

Every scenario must have structured explanation records.

Each explanation should answer:
- Why was this crop/rotation considered?
- Which constraints were evaluated?
- Which were satisfied, violated, or not evaluated?
- Which observations and crop-knowledge sources influenced the result?
- Which benefits are potential rather than measured?
- What risks or trade-offs remain?
- What inputs are missing?
- What needs local review?

Store evidence references, rule IDs, feature IDs, and algorithm versions. Do not rely on free-form LLM text as the sole evidence record.

---

# PART VII — ADDITIONAL INNOVATIVE FEATURES

Implement the first four as product differentiators where feasible; stage the others according to evidence and scope. Do not let optional features block the core rotation workflow.

## 27. Feature A — Field Data Passport / Decision Readiness Gate

This is a high-priority differentiator.

Before allowing an apparently authoritative comparison, FieldShift should evaluate whether the field has enough valid information for the requested analysis.

For each decision type, define required/optional inputs. Example:
- water comparison requires a crop water parameter, ET0, effective rainfall method, area, and water allocation if evaluating feasibility against a hard water cap;
- soil-carbon trend requires comparable repeated measurements or a clearly labelled model estimate;
- pest-break warning requires a regionally applicable validated rule and known crop history;
- crop calendar feasibility requires regionally appropriate planting/harvest windows and crop duration.

The Data Passport should return:
- evidence coverage;
- missing data;
- spatial/temporal adequacy;
- freshness;
- quality flags;
- allowed analysis types;
- blocked/limited analyses and reasons.

## 28. Feature B — Rotation Trade-off Explorer

Allow the user to select two or more scenarios and compare them side by side, with:
- crop sequence timeline;
- water requirement ranges;
- economic assumptions;
- soil indicators and their evidence class;
- bare-soil windows;
- pest/disease warnings;
- operational resource requirements;
- climate stress performance;
- unresolved risks.

Provide a “why not?” view showing why other crops or plans were excluded.

## 29. Feature C — Farm Resource Bottleneck Planner

Extend rotation optimization beyond water to operational feasibility.

Capture:
- machinery and implement availability;
- labor availability by time window;
- storage capacity;
- seed/input availability;
- transport and market access;
- budget constraints.

Show bottleneck periods where several field operations compete for the same resource. This feature can later evolve into multi-field scheduling and cooperative-level planning.

## 30. Feature D — Advisor Collaboration and Approval Workflow

Support a workflow in which a farmer can share a plan with a selected agronomist, receive comments, request changes, and mark a plan as reviewed. Preserve:
- reviewer identity;
- review date;
- version reviewed;
- comments;
- unresolved issues;
- approval scope.

An “approved” label must mean reviewed by a named authorized advisor, not scientifically guaranteed.

## 31. Feature E — Evidence Conflict and Provider Disagreement Monitor

Where multiple providers offer comparable variables, compare their signals and surface disagreements. Example: rainfall products may differ because of methodology, spatial support, and gauge inputs.

Do not average sources blindly. Display:
- products compared;
- native resolution and period;
- differences;
- likely methodological reasons when documented;
- the source selected for a given calculation;
- sensitivity of the decision to source selection.

## 32. Feature F — Field Digital Twin / Seasonal Replay

Create a timeline view of a field across seasons that combines:
- crop sequence;
- weather summaries;
- irrigation and management events;
- soil samples;
- harvest outcomes;
- stress-test scenarios.

Allow the user to replay a previous season and compare an alternative plan against the historical sequence. Distinguish actual events from simulated alternatives.

## 33. Feature G — Market and Farm-Gate Economics

Add optional market data integration only after defining lawful, reliable sources for each region. Allow farmer-entered prices and costs first.

Support:
- gross revenue estimate;
- variable costs;
- gross margin;
- price volatility scenario;
- market access and buyer availability;
- storage/transport limits.

Never label gross margin as net profit unless all relevant costs are included. Price data must include date, location, currency, unit, quality class, and source.

## 34. Feature H — Irrigation Advisory Calendar

Generate a schedule-like view of estimated crop water demand and irrigation windows. Do not make automatic irrigation control part of the initial product. Any irrigation suggestion must identify the inputs and assumptions, and should require local validation if field sensors, soil hydraulic parameters, or irrigation efficiency data are missing.

## 35. Feature I — Voice-First Farm Journal

Allow voice note capture and optional transcription. Store original audio securely only with user consent. Transcriptions must be editable and must never be treated as confirmed chemical/diagnostic facts without user review.

Support local languages over time. Do not send private audio to external transcription services without explicit consent and clear disclosure.

## 36. Feature J — Offline Field Kit

Allow a user to pre-download:
- field boundaries;
- last successful analysis summary;
- seasonal plan;
- crop calendar reference;
- selected knowledge notes;
- blank journal forms.

Offline mode must clearly mark stale data and disable actions that require current data. Synchronization must be conflict-aware and auditable.

## 37. Feature K — Drought / Heat / Heavy Rain Watch

This is a later feature that requires a forecast or near-real-time provider. Use explicit alert thresholds with regional and crop validity. Distinguish a forecast warning from observed conditions. Provide alert confidence/coverage and explain how the alert was generated.

## 38. Feature L — Multi-Field and Cooperative Resource Optimization

Later, optimize water, labor, machinery, crop mix, or storage across multiple fields. This requires organization-level permissions, fair allocation policy, and explicit ownership rules. Do not assume one user's preferences should override another farmer's field decisions.

## 39. Feature Prioritization

### Must implement in core full project
- Farm/field management.
- Data-source abstraction.
- Alternative data connectors/importers.
- Synthetic data and test profiles.
- Data Passport.
- Crop catalog and evidence-backed parameters.
- Field history and preferences.
- Crop rotation optimizer.
- Water intelligence.
- Soil Health Ledger.
- Stress testing/sensitivity analysis.
- Bare-soil window planner.
- Explainability and evidence traceability.
- Farmer journal.
- Basic advisor review.
- Offline-safe capture and sync foundations.

### Implement after core is stable
- Provider disagreement monitor.
- Digital twin / seasonal replay.
- Resource bottleneck planning.
- Farm-gate economics.
- Voice-first journal.
- Advanced multi-field optimization.
- Forecast-based alerting.
- Optional AquaCrop 7.3 integration.

### Research-only until validated
- Automated pest/disease image diagnosis.
- Carbon-credit quantification.
- Predictive yield guarantees.
- Causal claims about management impacts from observational data alone.
- Fully automated agronomic prescriptions.

---

# PART VIII — API CONTRACTS

## 40. API Conventions

Base path: `/api/v1`.

Use:
- JSON request/response bodies;
- UUID identifiers;
- ISO 8601 timestamps;
- UTC timestamps internally;
- explicit units in numerical payloads;
- pagination for list endpoints;
- consistent error objects;
- request IDs and structured logs;
- authorization checks on every resource;
- idempotency keys for retryable create/ingestion actions.

Use OpenAPI generated from FastAPI schemas, but review the generated contract and add examples/descriptions. Do not let OpenAPI be the only documentation.

## 41. Required Endpoint Groups

### Identity and organizations
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`
- `POST /organizations`
- `POST /organizations/{organization_id}/members`

### Farms and fields
- `POST /farms`
- `GET /farms`
- `GET /farms/{farm_id}`
- `PATCH /farms/{farm_id}`
- `POST /farms/{farm_id}/fields`
- `GET /fields/{field_id}`
- `PATCH /fields/{field_id}`
- `POST /fields/{field_id}/boundary-versions`
- `GET /fields/{field_id}/map`

### Soil
- `POST /fields/{field_id}/soil-samples`
- `POST /soil/import-jobs`
- `GET /fields/{field_id}/soil-samples`
- `GET /fields/{field_id}/soil-ledger`

### Crop knowledge and farm history
- `GET /crops`
- `GET /crops/{crop_id}`
- `GET /crops/{crop_id}/regional-parameters`
- `POST /fields/{field_id}/crop-history`
- `GET /fields/{field_id}/crop-history`
- `POST /fields/{field_id}/management-events`
- `POST /fields/{field_id}/harvest-records`

### Data platform
- `GET /data/catalog`
- `GET /data/providers/health`
- `POST /fields/{field_id}/data-jobs`
- `POST /data/import-jobs`
- `GET /jobs/{job_id}`
- `GET /fields/{field_id}/observations`
- `GET /fields/{field_id}/data-passport`

### Features and intelligence
- `POST /fields/{field_id}/feature-runs`
- `GET /fields/{field_id}/features`
- `GET /fields/{field_id}/water-budget`
- `POST /fields/{field_id}/rotation-optimizations`
- `GET /optimizations/{optimization_id}`
- `GET /optimizations/{optimization_id}/scenarios`
- `GET /scenarios/{scenario_id}/comparison`
- `POST /scenarios/{scenario_id}/stress-tests`
- `GET /stress-tests/{stress_test_id}`
- `GET /fields/{field_id}/bare-soil-windows`

### Farmer experience
- `POST /fields/{field_id}/journal-entries`
- `GET /fields/{field_id}/journal-entries`
- `POST /scenarios/{scenario_id}/feedback`
- `POST /scenarios/{scenario_id}/advisor-reviews`
- `GET /fields/{field_id}/seasonal-action-plan`

### Offline synchronization
- `POST /sync/push`
- `GET /sync/pull`
- `GET /sync/conflicts`
- `POST /sync/conflicts/{conflict_id}/resolution`

## 42. Example Contracts

### 42.1 Create field

Request:

```json
{
  "name": "North Field",
  "area_ha": 5.2,
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[31.40, 31.10], [31.41, 31.10], [31.41, 31.11], [31.40, 31.11], [31.40, 31.10]]]
  }
}
```

Coordinates are illustrative only. Validate geometry and calculate/check area server-side.

Response:

```json
{
  "id": "uuid",
  "name": "North Field",
  "area_ha": 5.2,
  "geometry_valid": true,
  "boundary_version": 1,
  "data_passport_status": "not_assessed"
}
```

### 42.2 Start data ingestion job

```json
{
  "providers": ["open_meteo", "chirps"],
  "variables": ["temperature_mean", "precipitation", "reference_et0"],
  "start_date": "2018-01-01",
  "end_date": "2025-12-31",
  "temporal_aggregation": "monthly",
  "spatial_policy": "preserve_native"
}
```

Return `202 Accepted` with `job_id`, status, and status URL. Provider/model/product selection must be explicit or resolved through a documented configuration, not hidden defaults.

### 42.3 Rotation optimization request

```json
{
  "planning_horizon": {
    "start_date": "2027-01-01",
    "season_count": 4,
    "season_definition_id": "uuid"
  },
  "baseline_rotation_id": "uuid",
  "objectives": {
    "water_efficiency": 0.25,
    "soil_health": 0.25,
    "economic_return": 0.20,
    "climate_resilience": 0.20,
    "erosion_control": 0.10
  },
  "hard_constraints": {
    "maximum_irrigation_volume_m3": 12000,
    "excluded_crop_ids": [],
    "allowed_crop_ids": [],
    "equipment_ids": [],
    "market_constraints": []
  },
  "solution_preferences": {
    "max_scenarios": 5,
    "include_baseline": true,
    "include_exploratory_candidates": false
  }
}
```

The example weights are illustrative. Validate that weights are finite, non-negative, and have a valid normalization policy. Missing objective evidence must not silently become a zero score.

### 42.4 Optimization result

Return:
- run status;
- solver status;
- algorithm/knowledge/data versions;
- baseline scenario;
- candidate scenarios;
- per-criterion raw result and normalized value where valid;
- feasibility and constraint diagnostics;
- evidence references;
- missing inputs;
- uncertainties/limitations;
- local-review requirements.

Do not return a fabricated numeric score where inputs are incomplete.

### 42.5 Standard error

```json
{
  "error": {
    "code": "INSUFFICIENT_DATA",
    "message": "The requested analysis cannot be evaluated with the available evidence.",
    "details": [
      {
        "field": "crop_water_parameter",
        "reason": "No regionally valid crop coefficient is available for this crop."
      }
    ],
    "request_id": "uuid"
  }
}
```

Use meaningful HTTP status codes. Never expose stack traces, secrets, provider credentials, or private paths to clients.

---

# PART IX — FRONTEND AND FARMER EXPERIENCE

## 43. Main Application Sections

Implement a clean, responsive application with these navigation areas:

1. Overview / Farm Workspace.
2. Farms and Fields.
3. Field Intelligence.
4. Soil Profile and Soil Ledger.
5. Crop Catalog and Crop History.
6. Rotation Studio.
7. Water Intelligence.
8. Climate Stress Lab.
9. Seasonal Action Plan.
10. Farm Journal.
11. Data Passport.
12. Advisor Review.
13. Organization Settings.

## 44. UI Design Requirements

- Use calm, accessible, high-contrast colors; do not rely on red/green alone to communicate status.
- Use plain language in Farmer Mode.
- Add technical definitions and units in Expert Mode.
- Display source, date, spatial resolution, and evidence class near relevant maps/charts.
- Use map legends and readable units.
- Provide empty states that explain what data is missing and how to add it.
- Make warnings actionable, not alarmist.
- Avoid implying that a visualized raster is field-level ground truth.
- Provide keyboard accessibility and semantic labels.
- Support responsive layouts for phone, tablet, and desktop.
- Support RTL and LTR layouts; start with English and Arabic architecture-ready localization.

## 45. Rotation Studio UX

The user should be able to:
- select a field;
- select planning seasons/horizon;
- view existing crop history;
- configure hard constraints;
- set objective priorities;
- generate candidates;
- manually edit candidate sequences;
- rerun validation;
- compare at least three strategies, including the baseline when available;
- see why a crop was included/excluded;
- inspect water, soil, economic, and risk trade-offs;
- save a plan version;
- request advisor review.

The user must not be forced to configure advanced scientific variables to use the basic flow.

## 46. Data Visualization Requirements

Use charts/maps that answer specific questions:
- rainfall and temperature trends over declared time windows;
- soil moisture time series with source and depth;
- observation coverage and missing periods;
- field boundary and spatial extent;
- crop sequence timeline;
- water demand/supply timeline;
- soil indicator history;
- strategy trade-off comparison;
- stress-test sensitivity chart;
- plan versus actual outcome comparison.

Every chart must identify units, date range, source or derivation, and whether values are observed, estimated, or synthetic.

---

# PART X — SECURITY, PRIVACY, RELIABILITY, AND OPERATIONS

## 47. Security

Implement:
- secure authentication (password hashing with a current recommended algorithm or a vetted identity provider);
- refresh-token rotation and revocation where applicable;
- RBAC and resource-level authorization;
- organization/farm tenant isolation;
- input validation and output encoding;
- rate limiting for exposed endpoints;
- file type/size validation and malware scanning hook for uploads;
- secrets from environment/secret manager, never committed;
- CORS restricted to approved origins;
- audit logs for sensitive actions;
- least-privilege database and storage credentials.

Use secure defaults; do not invent cryptographic primitives.

## 48. Privacy and Data Governance

- Treat exact field boundaries, yields, costs, and management records as sensitive business data.
- Provide explicit data sharing permissions.
- Do not use farmer data for model training without an explicit and revocable consent mechanism.
- Allow export and account/data deletion workflows subject to legitimate retention requirements.
- Define data retention periods for audio, uploads, and job artifacts.
- Avoid sending private data to third-party AI or transcription services without consent and disclosure.
- Keep personal identifiers separate from analytical aggregates when feasible.

## 49. Background Jobs and Reliability

Job states:
- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `retrying`

Persist progress, start/end times, retry count, input reference, output reference, warnings, and structured error codes.

Retries must be bounded and only applied to retryable failures. Use idempotency keys for provider ingestion and sync operations. Avoid duplicate observations and duplicate farm events on retry.

## 50. Observability

Implement:
- structured logs with request/job IDs;
- error monitoring hooks;
- provider request latency and failure metrics;
- ingestion counts and rejected-record counts;
- job durations and retry counts;
- optimization runtime and solver statuses;
- data coverage and feature-generation failures;
- database query performance monitoring;
- audit events for important user actions.

Never log passwords, access tokens, secrets, private voice transcriptions, or sensitive field information unnecessarily.

## 51. Deployment and Environments

Provide:
- local development using Docker Compose;
- `.env.example` without real secrets;
- separate development/test/production settings;
- health and readiness endpoints;
- database migration instructions;
- object-storage setup instructions;
- worker startup commands;
- backup/restore documentation;
- production deployment notes.

Do not put all services into one oversized container. Keep API, worker, database, Redis, and object storage as separate Compose services in development.

---

# PART XI — TESTING AND ACCEPTANCE

## 52. Test Pyramid

### Unit tests
- unit conversions;
- date/season calculations;
- geometry validation;
- aggregation functions;
- feature calculations;
- water-balance equations;
- crop-window validation;
- rotation constraint logic;
- MCDA/Pareto result handling;
- explanation construction;
- uncertainty and missing-data behavior.

### Provider contract tests
- response mapping;
- source metadata;
- unit handling;
- time-range validation;
- error handling;
- retry/idempotency;
- provider outage behavior;
- source coverage boundaries.

### Integration tests
- database repositories;
- migrations;
- PostGIS geometry operations;
- object storage references;
- background jobs;
- ingestion-to-feature pipeline;
- optimization-run persistence.

### Frontend tests
- form validation;
- field map interactions;
- empty/loading/error states;
- Farmer/Expert mode differences;
- rotation comparison;
- offline queue behavior.

### End-to-end tests
- create organization and farm;
- create and validate field;
- upload soil sample;
- record crop history;
- ingest synthetic and alternative-source data;
- generate Data Passport;
- calculate supported features;
- generate baseline and candidate rotations;
- run stress tests;
- save plan;
- record farm journal and harvest result;
- sync offline changes.

## 53. Synthetic Test Profiles

Generate deterministic synthetic profiles with clear metadata:

1. Temperate seasonal environment.
2. Mediterranean dry-summer environment.
3. Semi-arid environment.
4. Tropical seasonal-rainfall environment.
5. Arid irrigated environment.

For each profile, generate:
- geometry with known area;
- weather/rainfall time series;
- optional soil properties;
- crop knowledge subset;
- crop history;
- water allocation;
- management records;
- known data gaps;
- test expectations.

These are software fixtures, not representative real-world farm measurements. Their purpose is to test application behavior, edge cases, and scenario logic—not validate agronomic performance.

## 54. Key Acceptance Criteria

The core project is not complete until all of the following are demonstrably true:

### Data platform
- Multiple providers/import paths produce the same canonical schema.
- Source/product/version and unit provenance are preserved.
- Provider outage does not break farm management or unrelated features.
- Synthetic data is always labelled.
- The application can run without NASA.

### Geospatial
- Valid field boundaries can be created/imported and stored.
- Invalid geometry is rejected with useful feedback.
- Spatial calculations preserve source resolution and area methods.
- Field-scale claims are suppressed where the raster support is too coarse.

### Intelligence
- Existing rotation is included as baseline when known.
- At least two alternative strategies can be compared with the baseline when adequate data/knowledge exist.
- Hard constraint violations are never hidden by soft scores.
- Missing data produces an incomplete/not-evaluated status rather than fabricated values.
- Every strategy has an explanation and evidence trace.
- Solver status and algorithm version are stored.

### Farmer experience
- A user can complete the core journey without seeing raw technical terms.
- Expert mode exposes data/source detail.
- Offline journal entries are not lost and can be synchronized.
- Stale or synthetic information is clearly labelled.

### Reliability
- Clean migrations succeed.
- Tests pass in CI.
- No tenant data leakage is possible through tested endpoints.
- Jobs have persisted status and structured failures.
- Setup instructions work on a clean development environment.

---

# PART XII — IMPLEMENTATION ROADMAP

## 55. Milestone 0 — Repository Audit and Decisions

Tasks:
- inspect current repository and git state;
- identify existing stack and code;
- identify what can be reused;
- create/adjust architecture diagrams;
- write ADRs;
- establish Python/frontend tooling;
- create implementation status and test matrix.

Deliverables:
- repository assessment;
- architecture documentation;
- decisions/assumptions log;
- initial task breakdown.

Acceptance:
- no destructive unreviewed changes;
- clear path to the first vertical slice.

## 56. Milestone 1 — Runnable Foundation

Tasks:
- configure backend and frontend;
- configure PostgreSQL/PostGIS, Redis, and MinIO for development where needed;
- establish configuration and environment validation;
- implement health checks;
- set up Alembic;
- create identity/organization/farm/field foundations;
- implement authorization checks;
- implement field geometry validation and storage;
- write first integration tests.

Vertical-slice acceptance:
A signed-in user can create a farm, create a field, draw/import valid geometry, view it on the map, and retrieve it via the API.

## 57. Milestone 2 — Canonical Data and Synthetic Provider

Tasks:
- define provider contracts;
- define canonical observation and dataset models;
- implement source/product registry;
- implement a deterministic synthetic provider;
- implement ingestion job state;
- implement normalization, quality flags, and provenance;
- add provider contract tests.

Acceptance:
Synthetic environmental observations can be ingested, validated, stored, queried, and displayed with their synthetic status and provenance.

## 58. Milestone 3 — Alternative Data Integrations

Tasks:
- implement Open-Meteo historical provider;
- implement CHIRPS v3 import/extraction workflow;
- implement SoilGrids WCS or WebDAV workflow as an optional provider, with a fallback when unavailable;
- implement CSV/GeoJSON/local soil-data imports;
- implement FAO/GAEZ and crop-calendar reference import workflows where licensing and formats allow;
- build provider health and coverage views.

Acceptance:
At least one real environmental source and one local/agricultural data import flow work end to end. CHIRPS/SoilGrids availability failures do not block other providers. All results include provenance and limitations.

## 59. Milestone 4 — Processing and Data Passport

Tasks:
- implement temporal aggregation;
- implement raster/field extraction and spatial support metadata;
- implement variable registry and unit conversion;
- implement climate features;
- implement soil feature intake and measurement history;
- implement coverage/freshness/quality reporting;
- implement Data Passport decision-readiness rules.

Acceptance:
The user can see which analyses are possible, which are blocked, and why.

## 60. Milestone 5 — Crop Knowledge Base

Tasks:
- define crop/family/variety schema;
- create import and curation workflow;
- add evidence/source references for traits;
- add crop calendars and water parameters only from documented sources;
- add regional validation state;
- build agronomist review workflow.

Acceptance:
Crop metadata cannot be used as a validated regional rule unless its evidence and validation status permit it.

## 61. Milestone 6 — Rotation Optimizer

Tasks:
- define season abstraction;
- implement candidate generator;
- implement hard constraint validator independent from solver;
- implement CP-SAT solver adapter;
- implement baseline and candidate scenario generation;
- implement Pareto/trade-off solution generation;
- implement result explanation and persistence;
- test infeasible, unknown, incomplete, timeout, and optimal cases.

Acceptance:
At least three strategies (baseline plus two candidates) are compared when evidence supports them. Invalid or incomplete cases are labelled honestly. No hard constraint is violated in a result labelled feasible.

## 62. Milestone 7 — Water and Soil Intelligence

Tasks:
- implement FAO-56-based ETc calculations with stage-specific parameters;
- implement transparent water-balance assumptions;
- implement water allocation and irrigation records;
- implement Soil Health Ledger;
- implement partial nutrient budget only when inputs permit;
- implement bare-soil window planning.

Acceptance:
Calculations include units, evidence, assumptions, data gaps, and tests. Unsupported outputs return not-evaluated states.

## 63. Milestone 8 — Stress Testing and Advanced Explainability

Tasks:
- implement deterministic climate/water perturbation scenarios;
- implement sensitivity analysis;
- add Monte Carlo only with defensible input distributions;
- implement provider-disagreement comparison where comparable products exist;
- add why-not explanations;
- add seasonal replay foundations.

Acceptance:
Every simulated result identifies assumptions and never presents hypothetical perturbations as forecasts.

## 64. Milestone 9 — Full Farmer Experience

Tasks:
- complete Farmer and Expert modes;
- implement Rotation Studio;
- implement Water and Climate Lab;
- implement Soil Ledger;
- implement Farm Journal;
- implement seasonal action plan;
- implement offline capture and conflict-aware sync;
- implement advisor sharing/review;
- add localization and RTL support.

Acceptance:
A farmer can complete the workflow without technical assistance, and an advisor can inspect the evidence and limitations.

## 65. Milestone 10 — Release Readiness

Tasks:
- security review;
- tenant-isolation tests;
- performance tests for key queries/jobs;
- backup/restore testing;
- accessibility checks;
- documentation review;
- CI pipeline;
- deployment configuration;
- demo environment seeded with labelled synthetic data;
- end-to-end regression suite.

Acceptance:
A clean environment can be deployed from documented instructions and the full demo workflow passes.

---

# PART XIII — REQUIRED REPOSITORY STRUCTURE

## 66. Recommended Monorepo

Adapt to existing repository conventions, but preserve equivalent separation.

```text
FieldShift/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── api/v1/
│   │   ├── application/
│   │   ├── domains/
│   │   │   ├── identity/
│   │   │   ├── organizations/
│   │   │   ├── farms/
│   │   │   ├── fields/
│   │   │   ├── crops/
│   │   │   ├── soil/
│   │   │   ├── water/
│   │   │   ├── rotations/
│   │   │   ├── scenarios/
│   │   │   ├── journals/
│   │   │   ├── knowledge/
│   │   │   └── reviews/
│   │   ├── data_platform/
│   │   │   ├── contracts/
│   │   │   ├── registry/
│   │   │   ├── providers/
│   │   │   │   ├── weather/
│   │   │   │   ├── precipitation/
│   │   │   │   ├── soil/
│   │   │   │   ├── crop_reference/
│   │   │   │   └── synthetic/
│   │   │   ├── ingestion/
│   │   │   ├── normalization/
│   │   │   ├── quality/
│   │   │   ├── provenance/
│   │   │   └── storage/
│   │   ├── geospatial/
│   │   ├── processing/
│   │   │   ├── climate/
│   │   │   ├── soil/
│   │   │   ├── vegetation/
│   │   │   ├── temporal/
│   │   │   └── features/
│   │   ├── intelligence/
│   │   │   ├── rotation/
│   │   │   ├── water/
│   │   │   ├── soil_health/
│   │   │   ├── climate_stress/
│   │   │   ├── pest_risk/
│   │   │   ├── simulation/
│   │   │   └── explainability/
│   │   ├── infrastructure/
│   │   ├── workers/
│   │   └── schemas/
│   ├── migrations/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── contract/
│   │   ├── geospatial/
│   │   └── e2e/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── features/
│   │   ├── maps/
│   │   ├── charts/
│   │   ├── services/
│   │   ├── stores/
│   │   ├── offline/
│   │   ├── i18n/
│   │   └── types/
│   └── package.json
├── data/
│   ├── raw/.gitkeep
│   ├── processed/.gitkeep
│   ├── reference/
│   ├── synthetic/
│   └── manifests/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── database/
│   ├── data_dictionary/
│   ├── methodology/
│   ├── api/
│   ├── implementation/
│   └── user_guides/
├── scripts/
├── infra/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
└── README.md
```

---

# PART XIV — REQUIRED DOCUMENTATION

## 67. Documents to Create and Maintain

Create these documents incrementally and keep them aligned with code:

1. `docs/architecture/system-overview.md`
2. `docs/architecture/module-boundaries.md`
3. `docs/architecture/data-flow.md`
4. `docs/architecture/deployment.md`
5. `docs/database/schema.md`
6. `docs/database/erd.md`
7. `docs/data_dictionary/variables.md`
8. `docs/data_dictionary/units.md`
9. `docs/data_dictionary/evidence-and-quality.md`
10. `docs/data_platform/provider-contracts.md`
11. `docs/data_platform/source-registry.md`
12. `docs/methodology/feature-engineering.md`
13. `docs/methodology/water-balance.md`
14. `docs/methodology/soil-health-ledger.md`
15. `docs/methodology/rotation-optimization.md`
16. `docs/methodology/climate-stress-testing.md`
17. `docs/methodology/uncertainty-and-limitations.md`
18. `docs/api/openapi-usage.md`
19. `docs/user_guides/farmer-guide.md`
20. `docs/user_guides/advisor-guide.md`
21. `docs/implementation/IMPLEMENTATION_STATUS.md`
22. `docs/implementation/DECISIONS_AND_ASSUMPTIONS.md`
23. `docs/implementation/KNOWN_LIMITATIONS.md`
24. `docs/implementation/TEST_MATRIX.md`

## 68. Architecture Decision Records

Create ADRs for:
- modular monolith;
- PostgreSQL/PostGIS;
- object storage for rasters and large files;
- provider abstraction;
- canonical observation model;
- evidence/provenance model;
- native spatial/temporal resolution preservation;
- multi-objective optimization;
- uncertainty representation;
- versioned decision runs;
- offline synchronization;
- multi-tenancy and authorization.

---

# PART XV — IMPLEMENTATION ORDER AND FIRST TASK

## 69. Start Here: The First Vertical Slice

Do not begin by attempting the entire optimization engine. Begin with a working end-to-end foundation.

### First implementation sequence

**Step 1 — Audit repository**
- inspect files, git status, dependency manifests, and existing tests;
- write a repository assessment;
- preserve existing code.

**Step 2 — Foundation**
- establish backend/frontend structure;
- establish Docker Compose;
- configure PostgreSQL/PostGIS;
- configure migrations;
- implement health endpoints.

**Step 3 — Farm and field domain**
- implement user/organization/farm/field minimal models;
- implement CRUD APIs;
- implement geometry validation and area calculation;
- add map view;
- add authorization tests.

**Step 4 — Canonical observation contract**
- define Pydantic contracts;
- define data source/product registry;
- define quality/provenance models;
- document units and temporal/spatial semantics.

**Step 5 — Synthetic provider**
- generate deterministic test observations for multiple environmental profiles;
- ingest, validate, store, query, and display them;
- guarantee synthetic labels remain visible.

**Step 6 — First Data Passport**
- calculate which variables are present/missing;
- show source/product, coverage, time range, resolution, and data status;
- identify analyses that are not yet supported.

**Step 7 — Run the full tests and report**
- backend tests;
- migration tests;
- frontend build and tests;
- one E2E farm/field/data flow;
- update project status.

Only after this vertical slice is working should you add external providers and agricultural intelligence modules.

## 70. Required First-Sprint Deliverables

- a runnable local development environment;
- a working React application shell;
- a working FastAPI application;
- PostgreSQL/PostGIS connection;
- initial Alembic migrations;
- farm and field creation APIs;
- field map and geometry validation;
- canonical observation Pydantic model;
- provider protocol;
- deterministic synthetic provider;
- provider contract tests;
- Data Passport initial screen/API;
- updated README and implementation status.

## 71. Final Instruction to the Coding Agent

Start by auditing the repository. Then implement the first vertical slice exactly as described. Do not attempt to fake completion with static JSON, hardcoded dashboard numbers, empty modules, or placeholder functions that are never exercised. Use synthetic data only for deterministic software tests and label it clearly. Build real persistence, validation, APIs, frontend integration, and tests.

If a feature is too large for one implementation pass, break it into a concrete sequence of smaller tasks and complete the next task rather than merely describing future work. Keep the project runnable after each milestone. Make pragmatic engineering decisions, record them, and continue without waiting for NASA data.

The implementation is successful when FieldShift can operate using alternative providers and local data, generate traceable field features, compare crop-rotation alternatives where agronomic evidence permits, explain limitations, and preserve the farmer's control over decisions.

---

# PART XVI — OFFICIAL TECHNICAL AND SCIENTIFIC REFERENCES

The coding agent must verify current access terms, versions, formats, and endpoints before implementation. These references are starting points, not permission to assume that a provider has an unrestricted API or that every dataset is suitable for every field.

## Environmental and soil data

- Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api
- Open-Meteo API documentation: https://open-meteo.com/en/docs
- CHIRPS v3 — Climate Hazards Center: https://www.chc.ucsb.edu/data/chirps3
- Climate Hazards Center datasets: https://www.chc.ucsb.edu/data
- SoilGrids documentation: https://docs.isric.org/globaldata/soilgrids/
- SoilGrids WCS access: https://docs.isric.org/globaldata/soilgrids/wcs.html
- SoilGrids WebDAV access: https://docs.isric.org/globaldata/soilgrids/WebDav.html
- FAO GAEZ v4: https://www.fao.org/gaez/gaezv4/en
- FAO Crop Calendar: https://cropcalendar.apps.fao.org/

## Agricultural methodology

- FAO Irrigation and Drainage Paper 56: https://www.fao.org/4/X0490E/x0490e00.htm
- FAO-56 reference evapotranspiration: https://www.fao.org/4/X0490E/x0490e05.htm
- FAO-56 crop evapotranspiration / Kc approach: https://www.fao.org/4/x0490e/x0490e0a.htm
- FAO AquaCrop: https://www.fao.org/aquacrop
- FAO AquaCrop 7.3 Python release announcement: https://www.fao.org/land-water/news/detail/fao-releases-the-new-aquacrop-version-7.3/en

## Engineering

- FastAPI: https://fastapi.tiangolo.com/
- Pydantic: https://docs.pydantic.dev/
- SQLAlchemy: https://docs.sqlalchemy.org/
- Alembic: https://alembic.sqlalchemy.org/
- PostgreSQL: https://www.postgresql.org/docs/
- PostGIS: https://postgis.net/documentation/
- PostGIS spatial indexes: https://postgis.net/documentation/faq/spatial-indexes/
- GeoPandas: https://geopandas.org/en/stable/
- Rasterio: https://rasterio.readthedocs.io/
- Xarray: https://docs.xarray.dev/
- Google OR-Tools: https://developers.google.com/optimization
- MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs/
- Open Geospatial Consortium: https://www.ogc.org/standards/

**Source-status note for this specification (checked 30 October 2026):** Open-Meteo currently documents historical reanalysis products including ERA5 and ERA5-Land; CHIRPS v3 is a quasi-global land rainfall product with a documented latitude range; SoilGrids documentation reports that its REST API is paused and recommends WCS/WebDAV alternatives; FAO announced AquaCrop 7.3 with Python source code in July 2026. The coding agent must re-check these facts at implementation time because provider status and product versions can change.

---

# END OF MASTER ENGINEERING PROMPT

## How the user should provide this prompt to GLM

1. Open the FieldShift repository in the coding environment.
2. Attach or paste this complete document as the project's master specification.
3. Ask GLM to begin with **Milestone 0 and the first vertical slice in Milestone 1/2**, not to generate the entire codebase at once.
4. Require it to run tests and show exact changed files and commands after each milestone.
5. Keep this document as the source of truth. If GLM proposes an architectural change, ask it to explain the trade-off and record an ADR before implementation.

**Recommended first message to GLM:**

> Read the attached FieldShift Master Engineering Prompt completely. Inspect the existing repository and report its state. Then implement the first vertical slice: a runnable backend/frontend environment, PostgreSQL + PostGIS, farm and field CRUD, geometry validation, canonical observation contracts, a deterministic synthetic provider, provider contract tests, and an initial Data Passport. Do not implement NASA connectors. Do not fabricate real-world agricultural recommendations. Keep the repository runnable, execute the relevant tests, update the implementation status and documentation, and report exactly what was completed and what remains.

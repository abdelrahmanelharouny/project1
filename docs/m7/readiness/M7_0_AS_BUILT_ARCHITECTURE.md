# M7.0 — As-Built Architecture

**Inspection date:** 2026-11-01 · **Scope:** everything actually present in the repository (M1–M6A). M6B/M6C are NOT_IMPLEMENTED (see `M7_0_BASELINE.md`) and appear here only where their absence matters.
**Method:** direct source inspection; every claim carries file/symbol evidence. Lines refer to `mini-services/fieldshift-api/app/...` unless prefixed `src/` (frontend) or `migrations/...`.

---

## 1. Runtime topology

```
Next.js 16 dev server (:3000)  ──fetch('/api/...?XTransformPort=3030')──▶  Caddy gateway  ──▶  FastAPI uvicorn (:3030, --reload)
                                                                                                   │ SQLAlchemy 2.x + GeoAlchemy2 + psycopg2
                                                                                                   ▼
                                                                              PostgreSQL 18.6 + PostGIS 3.7.0 (user-space cluster, :5433)
```

- Single frontend route `/` (`src/app/page.tsx`, `Workspace` loaded with `ssr:false` so maplibre-gl never SSRs).
- Backend is a FastAPI mini-service (`app/main.py`): request-ID middleware (`main.py:59-69`), structured error envelope `{"error":{code,message,details[],request_id}}` (`app/core/errors.py:103-183`), `/api/v1/health` + `/api/v1/health/ready` (reports `server_version` 18.6, `postgis_version` 3.7.0 — verified live).
- All jobs execute **inline** in the request thread (no worker queue) — §8.
- Auth: opaque bearer tokens (256-bit, SHA-256-hashed at rest, `app/core/security.py:40-49`), PBKDF2-HMAC-SHA256 120k password hashing (`security.py:21-24`).

## 2. Layered module map

| Layer | Modules | Notes |
|---|---|---|
| Identity & tenancy | `app/domains/identity/service.py` (`Principal`, `get_principal`, `require_member_of`, `get_farm_for_principal`, `get_field_for_principal`) | every router funnels through these guards; 404-then-403 semantics |
| Farm & field | `app/domains/farms_fields/service.py`, `app/geospatial/validation.py`, `app/api/v1/farms.py`, `fields.py` | GeoJSON in → WKB; boundary versioning; geodesic area |
| Data platform | `app/data_platform/{contracts,registry,ingestion,imports,providers,observability}` | canonical observation contract, provider registry, ingestion jobs, CSV/CHIRPS imports |
| Feature engine | `app/features/{catalog,calendar,engine,service}` | versioned definitions (29), runs, values, baselines |
| Knowledge | `app/knowledge/{contracts,import_service,service,packs/seed_pack_v1}` | versioned packs, strict import validation, seed pack |
| Rotation | `app/rotation/{problem,candidates,constraints,objectives,optimizer,explain,service}` | CP-SAT optimizer, Pareto, explainability |
| Water (M6A) | `app/water/{contracts,curve,knowledge,effective_rainfall,soil,requirements,planner,service}` | FAO-56 Kc, FAO-33 Pe, root-zone balance, ladder, seasonal plans |
| Passport | `app/passport/service.py` | per-(variable, product) coverage & readiness |
| Cross-cutting | `app/core/{config,database,errors,logging,security}`, `app/db/models.py` (1,098 LOC), `app/dev/seed.py` | |

## 3. Database schema (32 application tables)

Migrations: `0001_initial` → `0002_observation_provenance` → `0003_feature_engine` → `0004_knowledge_rotation` → `0005_deepening_hardening` → `0006_water_intelligence` (**head**).

| Domain | Tables | Key structural facts |
|---|---|---|
| Identity | `users`, `organizations`, `memberships`, `auth_tokens` | `uq_users_email_lower` (functional), `uq_membership_org_user` |
| Farm/field | `farms`, `fields`, `field_boundary_versions` | `fields.boundary` Geometry(MULTIPOLYGON,4326) + GiST; `field_boundary_versions` unique `(field_id,version_number)`, **no spatial index** |
| Data platform | `data_sources`, `dataset_products`, `ingestion_jobs`, `observations`, `observation_quality_flags`, `audit_events`, `farm_constraints` | observations natural key `(field_id,dataset_product_id,variable_code,observed_at,time_support,spatial_support_type)`; `evidence_class` + `ingestion_job_id` from 0002 |
| Features | `feature_definitions`, `feature_runs`, `feature_values` | runs carry `calendar_timezone`,`hemisphere`,`source_selection`,`feature_engine_version`,`feature_catalog_version`,`is_synthetic`; values unique `(run_id,feature_code,aggregation_level,period_label)` |
| Knowledge | `knowledge_packs`, `knowledge_sources`, `crop_families`, `crops`, `crop_varieties`, `crop_traits`, `crop_calendar_windows`, `crop_water_parameters`, `rotation_rules`, `agronomist_reviews` | packs `(pack_code,pack_version)` unique + `checksum_sha256` + full `content` JSONB; lifecycle `draft/active/retired`; Kc uniqueness NULLS NOT DISTINCT (0005) |
| Rotation | `crop_history`, `farmer_preferences`, `rotation_runs`, `rotation_strategies` | runs snapshot seasons/profiles/pack refs/feature-run ids/crop-history ids/engine/seed; strategies checksummed |
| Water | `water_plans` | status check only `running/succeeded/failed`; checksum over inputs+versions+values; **no started/completed columns** |

No RLS / triggers / grants anywhere (grep over `migrations/` and `app/`: zero matches) — tenancy is enforced in the service layer only.

## 4. Domain-by-domain as-built (the six mandated domains)

### 4.1 Farm & Field
- **Identity**: `farms(id, organization_id, name, country_code, admin_region, timezone, currency_code, unit_system, preferred_language)` — `models.py:127-148`. Region metadata = country + admin region only.
- **Field**: `fields(..., boundary Geometry(MULTIPOLYGON,4326), area_ha CHECK>0, boundary_version, status)` — `models.py:151-176`; GeoJSON input validated by `validate_boundary_geojson` (`app/geospatial/validation.py:152-218`): ring closure, ≤200k positions, lat/lon-swap heuristic, Shapely `make_valid` repair with warning, antimeridian **warning-only** (`:188-194`), area sanity 1 m²…5 Mm².
- **Boundary versioning**: append-only at app layer — `update_field_boundary` bumps `fields.boundary_version`, inserts `field_boundary_versions` row + `AuditEvent` (`app/domains/farms_fields/service.py:151-185`). No DB enforcement, no UPDATE/DELETE endpoints.
- **Area**: PyProj WGS84 geodesic (`geodesic_area_m2`, `validation.py:120-149`) with PostGIS geography cross-check exposed as `postgis_geodesic_area_ha` (`service.py:196-224`; agreement test `tests/integration/test_farms_fields_crud.py:55-60`).
- **Zones**: **NOT FOUND** (no management-zone concept anywhere).
- **Tenant ownership**: `organization_id` anchor + membership guards; proven by `tests/integration/test_auth_tenant_isolation.py` (403/404 matrix, :55-109).
- **Boundary-version linkage of computed results**: **NOT FOUND** — every domain table references `field_id` only; ingestion resolves the *current* boundary at fetch time (`app/data_platform/ingestion/service.py:266-275`). A boundary change can silently change the spatial meaning of future computations while old rows keep the old geometry only implicitly (through the boundary-version table, which nothing references).

### 4.2 Environmental data
- **Contract**: `CanonicalObservation` (`app/data_platform/contracts/observations.py:71-101`) — UTC-enforced (`_require_tz_utc`), `value=None ⇔ quality_status=missing` (missing never zero), 8-value `EvidenceClass` enum, 6-value `QualityStatus`, 6-value `SpatialSupportType`, 8-value `TimeSupport`.
- **Catalog**: 13 variables, version `2026.11.0-slice2` (`contracts/variables.py`), each with unit + evidence-class hint.
- **Providers** (registry `registry/provider_registry.py`, seeds `registry/seed_sources.py`): `synthetic` (deterministic, 2015–2024, `synthetic_test_data`), `open_meteo` (ERA5-Land/ERA5 daily incl. ET0, `openmeteo-archive-2026.10`, CC BY 4.0), `chirps_import` (GeoTIFF upload → field extract, pentad calendar verified, `polygon_average`), `soilgrids` (5 properties 0-5 cm + Q05/Q95, `global_soil_prediction`, static 2020 snapshot), `farmer_csv` (point, `farmer_reported_record`, file_sha256 provenance).
- **Observations**: natural-key idempotent; per-row quality flags; `is_synthetic` column; job provenance via `ingestion_job_id`.
- **Feature engine**: 29 versioned definitions (`featurespec-2026.11.2-m6a`); runs pin source selection (one product per variable, never blended — `app/features/service.py:91-215`), calendar tz + hemisphere + midpoint assignment rule, engine/catalog versions, `is_synthetic`; values carry `period_start/end`, `coverage_ratio`, 5-state quality, `baseline_reference` (≥5 years else `not_evaluated`; baseline_class ≥30 y `long_record_reference` else `short_record_exploratory`), `provenance` JSONB (contributing observation ids capped at 400, `app/features/engine.py:34,231-233`, per-value sha256 checksum).
- **Reconstruction of one immutable environmental snapshot**: **PARTIAL** — products & methodology are pinned; the concrete observation set is *not* fully pinned (ids capped; re-runs can absorb newly ingested rows of the same product). No run-level checksum.

### 4.3 Crop knowledge
- **Tables**: packs (checksummed, lifecycle), sources (citation_text required), families/crops/varieties, traits (region + management-context + growth-stage scoped, evidence_class + confidence + validation_status + validity dates), calendar windows (MM-DD, hemisphere, region), water parameters (Kc anchors), rotation rules (7 types, severity, region lists), agronomist reviews.
- **Import**: strict `extra="forbid"` schema, cross-referential validation, conflicting-context rejection, incomplete Kc anchor set rejected (never zero-filled), checksum conflict on same (code,version), draft-until-activated, audit events (`app/knowledge/contracts.py:143-325`, `import_service.py:27-249`).
- **Seed pack** `kp-seed-global` v`kp-seed-2026.11.1`: 4 real sources (FAO-56 1998, FAO EcoCrop, Agrios 2005, Herridge et al. 2008), 11 crops, ~153 traits, 13 calendar windows (declared `reference_synthesized`), 30 single-Kc anchors, 6 reference-status rotation rules; **deliberate gaps**: no drought/heat scores, faba_bean has no Kc, **zero `confirmed_regional` rows** (hard rotation-break constraints bind on nothing by design).
- **Decision reconstruction**: rotation runs and water plans store `knowledge_pack_refs` = `{pack_id,pack_code,pack_version,status,checksum_sha256,license,attribution}` (`app/knowledge/service.py:35-44`; written at `rotation/service.py:543,576`, `water/service.py:590`), and pack content JSONB + checksum survive retirement — historical decisions are reconstructable **by reference**.
- **Independent versioning**: yes, per pack; deterministic active-pack resolution (F-9).

### 4.4 Rotation (M5)
- **Tables**: `rotation_runs` (snapshots listed above; `solver_status` ∈ optimal/feasible/infeasible/unknown/model_invalid/not_attempted; `random_seed=0`), `rotation_strategies` (assignment, criteria raw+normalized, pareto, explanations, evidence_coverage, checksum).
- **Hard constraints** (`app/rotation/constraints.py`): exactly-one, admissible pool, pairwise+history rotation breaks (confirmed_regional only, deepest-lookback F-06), per-season water allocation (CP-SAT, litres-exact, NIR basis with ETc-conservative fallback disclosure). Each registered as CP-SAT **assumption** → `SufficientAssumptionsForInfeasibility()` mapped to named conflicts (`optimizer.py:292-302,456-476`).
- **Soft objectives** (`app/rotation/objectives.py`): 7 criteria, each with missing-data honesty (skipped + reason, never zero): water_requirement_mm, soil_health_index, economic_margin_index (farmer-supplied only), crop_family_diversity, climate_resilience_index, erosion_reduction_index (duration proxy), cover_crop_opportunity.
- **Pareto**: min-max normalization within the run's strategy set over the shared evaluable criterion set; non-comparable pairs recorded.
- **Status honesty**: only CP-SAT `INFEASIBLE` is reported as infeasible; `MODEL_INVALID`/`UNKNOWN` never become "infeasible" (`optimizer.py:478-500`; `service.py:591-605,668-694`).
- **Explainability** (`app/rotation/explain.py:27-225`): why_generated, recommendation, constraints_checked, criteria with source_refs, evidence_references (pack refs + feature-run ids + citations), data_limitations (incl. SYNTHETIC banner), local-expert-validation blocks.
- **Implicit mutable dependencies**: active-pack set read at run time (pinned by value into refs); evidence feature run defaults to **latest succeeded** (`_pick_evidence_run`, `rotation/service.py:108-124`); soil evidence = latest non-null observations per variable; water allocation from request or `farm_constraints` row. Crop-history rows snapshotted by id.
- **Reproducibility**: determinism tests (`test_rotation_core.py:306-314`, `test_rotation_runs.py:242-253`); idempotency keys field-scoped (F-03, migration 0005).
- **Gaps**: `solver_version` column never populated; no cross-run comparison endpoint; problem checksum covers candidate codes, not assessment values.

### 4.5 Water (M6A)
- **Tables**: `water_plans` — seasons/crop_assignments/methods/soil_inputs/result/warnings/not_evaluated JSONB; `water_engine_version`=`water-engine-1.0.0`, `methods_version`=`water-methods-1.0.0`; `feature_run_ids`; `knowledge_pack_refs`; `water_allocation_m3`; `idempotency_key` (field-scoped unique); `checksum_sha256` over inputs+versions+values. **No scenario/parent/version column; no started/completed timestamps; DELETE endpoint exists** (immutability is convention, not constraint).
- **Engines**: FAO-56 single-Kc curve with linear stage ramps (`water/curve.py`), stage/day/month aggregation, dual-Kc refused; FAO-33 effective rainfall `fao_aglw_1986` + explicit-fraction constant method (USDA-SCS documented as not implemented, backlog W-5); Saxton-Rawls 2006 PTF with validity-domain enforcement + opt-in disclosure + farmer-measured precedence; root-zone balance TAW/RAW/Dr/Ks with FAO-56 Eq. 84 and Table-22 p-adjustment; 7-quantity requirement ladder with statuses `evaluated|not_evaluated|unknown|not_supplied`; deficit windows (root_zone_stress, allocation_shortfall); allocation unknown ≠ unlimited.
- **Rotation integration**: NIR coefficients feed the CP-SAT allocation constraint (`optimizer.py:363-406`); infeasibility names `water_allocation` + demand basis.
- **Provenance chain**: crop sequence (JSONB), climate evidence (feature_run_id + basis + is_synthetic), knowledge (pack refs + per-source citations), methodology (versions + methods JSONB + soil inputs with evidence classes). **No explicit link to a rotation run/strategy id** — crop assignments are caller-supplied.
- **Golden/property tests**: FAO-33 worked examples (35→11, 90→47, 116→67.8…), M5 separation anchor 571.87 mm, Saxton-Rawls silty-clay-loam worked example, FAO I&D 33 §4.3 ladder example, 1 mm·ha=10 m³ identity, reproducible checksums (`tests/unit/test_water_core.py`, `tests/integration/test_water_api.py`).

### 4.6 Soil (M6B) — **NOT IMPLEMENTED**
No soil sampling events, lab methods, soil layers/profiles, SOC calculations, nutrient budgets, management history, or assessment-run tables exist. What exists is *soil-adjacent evidence* consumed by other engines:
- SoilGrids 0–5 cm predictions (pH, SOC, sand, clay, bulk density) as ordinary observations with `global_soil_prediction` evidence class and 90% PI metadata;
- farmer CSV soil variables (`soil_ph`, `soil_organic_carbon`, …);
- knowledge traits `root_depth_effective_m`, `stress_depletion_fraction_p`;
- the M6A root-zone water balance (`app/water/soil.py`) — hydrology, not soil health;
- rotation soil_health_index criterion (legume/cover/root-depth/N-fixation traits).

Consequence for M7: a "soil_assessment_snapshot_id" on a future Field State has **no native producer today**; either M6B is scheduled before/with M7.1 or the Field State must express soil as `NOT_IMPLEMENTED` dimension with the SoilGrids/farmer CSV inputs listed as raw evidence.

### 4.7 Management (M6C) — **NOT IMPLEMENTED**
No practice knowledge, operation templates, soil-cover timeline, cover-crop plans, residue ledger, erosion screening, resource registry, operations, scheduler, or management-plan snapshot tables exist. Only proxies: `is_cover_crop_capable` crop flag + `cover_crop_suitability` rule type + `cover_crop_opportunity` criterion + `erosion_reduction_index` duration proxy in rotation. A future scenario engine therefore cannot yet evaluate "management changes" against any management engine — that entire scenario axis is blocked on M6C.

### 4.8 Cross-domain integration map
See companion document `M7_0_CROSS_DOMAIN_MAP.md` (dependency graph + connection classification).

## 5. Honest-contract conventions (platform-wide)

- Missing ≠ zero: enforced at contract (`value=None ⇔ missing`), engine (insufficient coverage → NULL + reason), knowledge (incomplete Kc anchors rejected), water (missing ETc raises; unknown allocation ≠ unlimited).
- "(not evaluated)" / `not_evaluated` status vocabulary shared by features, rotation criteria, water ladder.
- SYNTHETIC banner propagated observations → feature runs → rotation reasons → water plans → frontend `SyntheticBadge`.
- Statuses never silently relaxed: named infeasibility (rotation), PTF domain refusals, USDA-SCS refusal, baseline `short_record_exploratory` labeling.
- Evidence classes on every observation and knowledge row; license/attribution mandatory in the registry and packs.

## 6. What does not exist (verified by search, not assumption)

| Capability | Search evidence | Status |
|---|---|---|
| Scenario/what-if concept | `rg -i "scenario" app/` → **zero code matches** (only README-style wording) | NOT_IMPLEMENTED |
| Forecast provider | `rg -i "forecast" app/` → only honesty disclaimers ("NOT a forecast") | NOT_IMPLEMENTED |
| DEM/terrain pipeline | `rg -i "dem|elevation|terrain" app/` → only p-adjustment slope constant + FAO-33 slope-condition text | NOT_IMPLEMENTED |
| Management zones | no zone table/endpoint/component | NOT_IMPLEMENTED |
| Background job queue / cancellation / progress % | no BackgroundTasks/queue/cancel endpoint; `cancelled` status unreachable | NOT_IMPLEMENTED |
| Boundary-version pinning of results | no FK/snapshot column anywhere | NOT_IMPLEMENTED |
| DB-level tenant isolation (RLS) | no POLICY/GRANT/trigger | NOT_IMPLEMENTED |

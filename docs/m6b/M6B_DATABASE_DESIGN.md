# M6B — Database Design

**Status:** implemented (as-built)
**Migration:** `0007_soil_intelligence` (revises `0006_water_intelligence`),
`mini-services/fieldshift-api/migrations/versions/0007_soil_intelligence.py`.
**ADR:** ADR-0022 — soil measurement history is a dedicated depth-explicit
relational domain; `observations` stays untouched.

---

## 1. Why a separate domain (ADR-0022 rationale)

The existing `observations` table carries depth only inside `metadata` JSONB
(SoilGrids rows: `"depth": "0-5cm"`) and its natural key
`(field, product, variable, observed_at, time_support, spatial_support)` would
collide for the six standard SoilGrids depths sharing one snapshot timestamp.
Depth-explicit measurements therefore get first-class relational tables; the
0–5 cm `observations` rows remain the backward-compatible surface for the
rotation/water consumers. Gridded multi-depth values enter
`soil_measurements` with `evidence_class='global_soil_prediction'`,
`spatial_support_type='grid_cell'`, `source_kind='soilgrids_profile'` — measured
vs mapped stays structurally distinct.

## 2. Conventions

UUID primary keys; FK → `fields.id` / `organizations.id` with sensible
`ondelete` (CASCADE for field-owned rows, SET NULL for optional references);
`created_at`/`updated_at` timestamps (`now()` server default) on every table;
JSONB only for genuine metadata (`metadata`, `method_params`, `details`,
`result` payloads); CHECK constraints encode the vocabularies; string columns
sized (120–160 typical). No existing table is altered; the migration is purely
additive and downgrade drops the 13 tables in reverse dependency order.

## 3. Tables

### 3.1 Registries

| Table | Columns (beyond id/timestamps) | Keys & constraints |
|---|---|---|
| `soil_laboratories` | organization_id FK, name (160), accreditation?, contact JSONB `{}`, notes? | `uq_soil_lab_name (organization_id, name)`; ix `organization_id` |
| `soil_analytical_methods` | organization_id FK, code (80), property_family (40), analytical_method?, extraction_method?, extractant?, soil_solution_ratio?, temperature_note?, reporting_basis?, reference_text? | `uq_soil_method_code (organization_id, code)`; CHECK `ck_soil_method_family` — 12 families (texture, bulk_density, water_retention, ph, salinity, carbon, nitrogen, phosphorus, potassium, cec, biology, other); ix `organization_id` |

### 3.2 Sampling domain

| Table | Columns | Keys & constraints |
|---|---|---|
| `soil_sampling_events` | field_id FK CASCADE, sampling_date (NOT NULL), purpose?, sampling_method?, sampling_depth_note?, management_zone?, gps_lat?, gps_lon?, composite BOOL false, subsample_count?, equipment?, sample_handling?, sample_preparation?, collected_by?, quality_status 'valid', notes?, metadata JSONB | CHECK quality ∈ (valid, suspect, invalid, not_assessed); CHECK lat/lon ranges; ix `(field_id, sampling_date)` |
| `soil_samples` | event_id FK CASCADE, field_id FK CASCADE, sample_code (120), composite_parent_id self-FK SET NULL, laboratory_id FK SET NULL, report_reference?, received_date?, reported_date?, notes?, metadata | UNIQUE ix `uq_soil_sample_code (field_id, sample_code)`; ix event, ix field |
| `soil_sample_layers` | sample_id FK CASCADE, top_depth_cm FLOAT NOT NULL, bottom_depth_cm FLOAT NOT NULL, original_depth_unit 'cm', original_top?, original_bottom?, layer_label?, notes? | CHECK `top ≥ 0 AND bottom > top`; UNIQUE ix `uq_soil_layer_interval (sample_id, top, bottom)`; ix sample |
| `soil_measurements` | field_id FK CASCADE, layer_id? FK CASCADE (NULL = field-attached), variable_code (80), value? FLOAT, unit (30) NOT NULL, top_depth_cm?, bottom_depth_cm?, evidence_class (40) NOT NULL, spatial_support_type 'lab_sample', source_kind 'lab_analysis', method_id? FK SET NULL, method_params JSONB, detection_limit?, quantification_limit?, result_qualifier (12)?, uncertainty_value?, uncertainty_type?, quality_status 'valid', is_synthetic false, observed_at NOT NULL, processing_version 'v1', metadata | CHECK evidence ∈ 8-value platform vocabulary; CHECK source ∈ (lab_analysis, farmer_report, soilgrids_profile, synthetic_fixture); CHECK quality ∈ (valid, suspect, invalid, missing, estimated, not_assessed); PARTIAL UNIQUE `uq_soil_measurement_natural_key (field_id, variable_code, observed_at, top_depth_cm, bottom_depth_cm, source_kind, method_id) WHERE layer_id IS NULL`; ix `(field_id, variable_code, observed_at)`, ix layer |

### 3.3 Management ledger & nutrient domain

| Table | Columns | Keys & constraints |
|---|---|---|
| `soil_management_events` | field_id FK CASCADE, event_date NOT NULL, event_type (60) NOT NULL, title?, details JSONB, nutrient_application_id? (UUID, no FK constraint — soft link), notes? | CHECK `ck_soil_mgmt_event_type` — 12 types (planting, harvest, fertilizer_application, manure_application, compost_application, residue_retention, residue_removal, tillage, cover_crop_termination, irrigation, soil_amendment, other); ix `(field_id, event_date)` |
| `nutrient_products` | organization_id FK CASCADE, name (160), product_type 'fertilizer', n_pct?/p_pct?/k_pct? FLOAT, reporting_basis 'elemental' NOT NULL, dry_matter_fraction?, moisture_basis?, availability_notes?, source_reference?, metadata | CHECK product_type ∈ (fertilizer, manure, compost, organic_amendment, other); CHECK reporting_basis ∈ (elemental, oxide); `uq_nutrient_product_name (organization_id, name)`; ix org |
| `nutrient_applications` | field_id FK CASCADE, season_label (80) NOT NULL, application_date NOT NULL, input_kind (40) NOT NULL, product_id? FK SET NULL, product_name_free?, applied_mass_kg NOT NULL, area_ha NOT NULL, n_kg?/p_kg?/k_kg? FLOAT, reporting_basis?, availability_fraction?, availability_basis?, application_method?, moisture_basis?, evidence_class 'farmer_reported_record', is_synthetic false, source_reference?, notes?, metadata | CHECK input_kind ∈ 8 kinds; CHECK `applied_mass_kg ≥ 0 AND area_ha > 0`; ix `(field_id, season_label)` |
| `nutrient_removals` | field_id FK CASCADE, season_label NOT NULL, removal_date?, crop_code?, output_kind 'harvested_product', biomass_kg NOT NULL, dry_matter_fraction?, moisture_basis 'as_harvested' NOT NULL, n/p/k_concentration_g_kg?, concentration_basis?, concentration_source?, evidence_class 'farmer_reported_record', is_synthetic false, notes?, metadata | CHECK output_kind ∈ (harvested_product, crop_residue, other_biomass); CHECK `biomass_kg ≥ 0`; CHECK moisture_basis ∈ (as_harvested, dry_matter); ix `(field_id, season_label)` |

### 3.4 Immutable run snapshots (the water-plan pattern)

| Table | Shared shape | Distinct columns / constraints |
|---|---|---|
| `soc_stock_runs` | field_id FK CASCADE, status 'succeeded', label (120), engine_version + methods_version NOT NULL, result JSONB, warnings JSONB `[]`, request_parameters JSONB, idempotency_key?, checksum_sha256 (64)?, error_summary?, created/updated | input_sample_ids JSONB `[]`; comparison_mode 'single_profile' CHECK ∈ (single_profile, fixed_depth, equivalent_soil_mass); baseline_run_id self-FK SET NULL; not_evaluated JSONB `[]`; PARTIAL UNIQUE `uq_soc_run_idempotency (field_id, idempotency_key) WHERE idempotency_key IS NOT NULL`; ix field |
| `nutrient_budget_runs` | (same shared shape) | seasons JSONB `[]`; not_evaluated JSONB `{}` (season → missing flows); PARTIAL UNIQUE idempotency; ix field |
| `soil_assessment_runs` | (same shared shape) | PARTIAL UNIQUE idempotency; ix field; result carries the five-domain profile with `composite_score: null` |

Status CHECK on all three: `running | succeeded | failed`. Rows are never
updated after success — a re-run inserts a new row.

## 4. Computed read-models (not tables)

`soil_profiles` and `soil_indicators` are deterministic API-level assemblies from
`soil_measurements` (engine-version-pinned). Persisting a copy would duplicate
truth; integrity (overlaps/gaps) is computed per request and reported in the
response. Methodology registries stay code-versioned constants + run snapshots
(`soil-methods-1.0.0`) instead of extra tables.

## 5. JSONB usage policy

JSONB is restricted to: true metadata (`metadata`), inline method parameters
(`method_params`), ledger details, and immutable result payloads. No query
domain logic depends on JSONB keys for identity — identity columns and CHECK
vocabularies are relational. The `observations.metadata->depth` overload that
motivated ADR-0022 is exactly the pattern the new schema avoids.

## 6. Migration & downgrade notes

- `upgrade()` creates the 13 tables + indexes (order: registries → sampling
  domain → ledger/nutrients → runs).
- `downgrade()` drops in exact reverse order (assessments → budgets → SOC runs →
  removals → applications → products → management events → measurements →
  layers → samples → events → methods → labs), respecting FK dependencies.
- Migration-upgrade/downgrade is exercised by the migration test suite every run.

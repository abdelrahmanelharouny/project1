# Database Schema — Slice 1

PostgreSQL 16 + PostGIS 3.5. All UUID PKs. All timestamps `timestamptz` (UTC). Migration: `migrations/versions/0001_initial.py` (Alembic).

## Tables

### Identity & tenancy
- **users** — id, email (unique on `lower(email)`), password_hash, display_name, preferred_language, timezone, is_active, timestamps
- **organizations** — id, name, organization_type (default `farm`), country_code, timestamps
- **memberships** — id, organization_id → organizations, user_id → users, role_code CHECK(owner|manager|agronomist|viewer), status; UNIQUE(org,user)
- **auth_tokens** — id, user_id → users, token_hash (unique), expires_at, revoked_at
- **audit_events** — id, actor_id, organization_id, entity_type, entity_id, action, before/after JSONB snapshots

### Farms & fields
- **farms** — id, organization_id → organizations, name, country_code(2), admin_region, timezone, currency_code(3), unit_system CHECK(metric|imperial), preferred_language
- **fields** — id, farm_id → farms, name, **area_ha CHECK > 0**, **boundary geometry(MULTIPOLYGON, 4326) + GIST index**, boundary_version (int, ≥1), status
- **field_boundary_versions** — id, field_id → fields, version_number, boundary (MULTIPOLYGON 4326), area_ha, change_reason, created_by, created_at; UNIQUE(field_id, version_number)

### Data registry
- **data_sources** — id, provider_code (unique), provider_name, base_url, license_name/url, attribution_text, documentation_url, status, known_limitations
- **dataset_products** — id, source_id → data_sources, product_code, product_version, description, spatial_resolution_m, temporal_resolution, coverage_start/end, metadata JSONB; UNIQUE(source, product_code, product_version)

### Ingestion & observations
- **ingestion_jobs** — id, field_id → fields, provider_code, job_type, request_parameters JSONB, idempotency_key (partial-unique where not null), status CHECK(queued|running|succeeded|failed|cancelled|retrying), records_received/rejected, warnings JSONB, error_summary, started_at, completed_at, created_by
- **observations** — id, field_id → fields, dataset_product_id → dataset_products (RESTRICT), variable_code, **value (nullable — NULL means missing/nodata)**, unit, observed_at, period_start, period_end, time_support CHECK(instant|hourly|daily|pentadal|dekadal|monthly|seasonal|annual), spatial_support_type CHECK(point|grid_cell|polygon_average|field_intersection|station|lab_sample), spatial_resolution_m, quality_status CHECK(valid|suspect|invalid|missing|estimated|not_assessed), uncertainty_value/type (NULL = unknown, never 0), **is_synthetic**, retrieved_at, processing_version, metadata JSONB
  - **UNIQUE natural key** (field_id, dataset_product_id, variable_code, observed_at, time_support, spatial_support_type) — idempotent ingestion
  - INDEX (field_id, variable_code, observed_at)
- **observation_quality_flags** — id, observation_id → observations, flag_code, severity CHECK(info|warning|error), message, details JSONB

### Preferences (minimal slice subset)
- **farm_constraints** — id, farm_id → farms, constraint_code, value_numeric/text, unit, is_hard_constraint, source

### Field state (Milestone 7.1 — migration `0007_field_state_foundation`)
- **field_states** — id, field_id → fields (CASCADE), status CHECK(running|succeeded|failed), label(120), **boundary_version (NOT NULL — H-01 pin)**, state_reference_time, period_start/end (CHECK end ≥ start), timezone, calendar_context JSONB, environmental_feature_run_id → feature_runs (**RESTRICT**), water_plan_id → water_plans (**RESTRICT**), rotation_run_id → rotation_runs (**RESTRICT**), rotation_strategy_key, crop_history_ids JSONB, knowledge_pack_refs JSONB (copied `pack_ref` entries with checksums), observation_manifest JSONB (verbatim `field-observation-manifest-1` copy), observation_manifest_sha256, manifest_format_version, domain_availability JSONB (per-dimension available|missing|period_mismatch|not_evaluated|not_implemented — soil/management always not_implemented), evidence_summary JSONB, quality_summary JSONB, period_compatibility JSONB, source_versions JSONB, request_parameters JSONB, warnings JSONB, not_evaluated JSONB, error_summary, idempotency_key, checksum_sha256, created_by, started_at/created_at/updated_at/completed_at
  - INDEX `uq_field_state_idempotency (field_id, idempotency_key) WHERE idempotency_key IS NOT NULL`; INDEX `ix_field_states_field`
- **feature_runs** += `boundary_version` (nullable — NULL = pre-M7.1 "not recorded"), `observation_manifest` JSONB, `observation_manifest_sha256`
- **water_plans** += `boundary_version` (nullable), `started_at`, `completed_at`
- **ingestion_jobs**: legacy key-only `uq_ingestion_idempotency` replaced by **`uq_ingestion_idempotency_v2 (field_id, idempotency_key) WHERE idempotency_key IS NOT NULL`** (F-30 composite fix; downgrade restores the legacy index)
- RESTRICT rationale (F-13): a field state is an immutable reference to the artifacts it was assembled from — referenced runs/plans cannot be deleted out from under a state (API pre-checks return 409; the FK is the database-level backstop).

### Milestone 7.2 — scenario domain (migration `0008_scenario_domain`)

- **scenarios** — id, field_id → fields (CASCADE), name(120), description, scenario_type CHECK(historical_observed|historical_perturbation|user_defined_stress|climate_projection|weather_forecast), scenario_status CHECK(draft|validation_pending|valid|conditionally_valid|invalid|finalized|archived|unsupported), lineage_kind CHECK(root|revision|branch), scenario_version, **parent_field_state_id → field_states (RESTRICT)**, parent_snapshot_checksum (copied BY VALUE at creation), boundary_version (copied), parent_scenario_id → scenarios (RESTRICT, nullable — one self-FK covers revisions AND branches), configuration_schema_version, canonical_configuration JSONB, configuration_checksum (SHA-256 over canonical JSON; excludes name/description/UI metadata), period_start/end (CHECK end ≥ start), timezone, evidence_classification CHECK(observed|hypothetical|not_available), assumption_metadata JSONB, validation_summary JSONB (latest record copy), created_by, finalized_at, idempotency_key, created_at/updated_at
  - **CHECK `ck_scenario_type_evidence_binding`** (M7.0 C2 at DB level): historical_observed↔observed; perturbation/stress↔hypothetical; climate_projection/weather_forecast↔not_available
  - **CHECK `ck_scenario_unavailable_types_never_finalized`**: climate/forecast rows can never reach valid|conditionally_valid|finalized
  - CHECK `ck_scenario_finalized_at_present` (finalized ⇒ finalized_at NOT NULL)
  - INDEX `uq_scenario_idempotency (field_id, idempotency_key) WHERE idempotency_key IS NOT NULL`; `ix_scenarios_field/parent_scenario/parent_state`
  - **TRIGGER `enforce_scenario_immutability`** (BEFORE UPDATE): finalized/archived rows reject ANY content change (raw SQL included); only finalized→archived permitted; archived terminal
- **scenario_validation_records** — id, scenario_id → scenarios (CASCADE), scenario_version, validation_rule_version, validation_status CHECK(8-value result vocabulary), validation_result JSONB (findings/missing_inputs/unsupported_dimensions), configuration_checksum, created_by, created_at — append-only, never updated
- RESTRICT rationale (spec §7): a referenced Field State cannot be deleted out from under a scenario; the by-value parent checksum/boundary pins keep historical references meaningful even if upstream rows changed

## Design notes

- Geometry stored EPSG:4326 (interchange), validated in the application layer before insert; area stored from PyProj geodesic computation and cross-checked against PostGIS `geography ST_Area` (see ADR-0003).
- Boundary history is append-only: the current `fields.boundary` mirrors the latest `field_boundary_versions` row (never edited in place without a new version).
- Enum-like values are enforced by CHECK constraints, not just application validation.
- JSONB is used only for genuinely variable payloads (request parameters, product metadata, flag details, provenance extras) — never as a substitute for relational structure.

## ERD (textual, slice tables)

```
organizations 1─* memberships *─1 users 1─* auth_tokens
organizations 1─* farms 1─* fields 1─* field_boundary_versions
                          1─* observations *─1 dataset_products *─1 data_sources
                          1─* ingestion_jobs
fields 1─* observations 1─* observation_quality_flags
fields 1─* field_states 1─* scenarios (RESTRICT) 1─* scenario_validation_records
farms   1─* farm_constraints
users/organizations 1─* audit_events (soft reference via actor_id/organization_id)
```

Later milestones extend this schema (soil, crops, water, rotations, scenarios, journal, reviews) per Master Part V without restructuring these tables.

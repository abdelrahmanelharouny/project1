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
farms   1─* farm_constraints
users/organizations 1─* audit_events (soft reference via actor_id/organization_id)
```

Later milestones extend this schema (soil, crops, water, rotations, scenarios, journal, reviews) per Master Part V without restructuring these tables.

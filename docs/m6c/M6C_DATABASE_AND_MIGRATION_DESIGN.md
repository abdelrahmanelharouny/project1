# M6C — Database & Migration Design

**Migration:** `0008_field_management` (revision chain
`0007_soil_intelligence` → `0008_field_management`), additive-only,
downgrade implemented in reverse dependency order and exercised by the
migration test in the suite (upgrade → downgrade → upgrade).

## 1. Tables (16)

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `practice_definitions` | pack-materialized practices | FK pack CASCADE; `practice_code`, `practice_family` CHECK (7 families); `payload` JSONB (claims); UNIQUE (pack, code) |
| `operation_templates` | pack-materialized templates | FK pack CASCADE; UNIQUE (pack, template_code) |
| `soil_cover_observations` | dated cover evidence | FK field CASCADE; `cover_state` CHECK (7 states incl. `unknown`, `mixed`); `cover_fraction` CHECK [0,1] or NULL; `measurement_basis` CHECK (6 bases); index (field, date) |
| `cover_crop_plans` | immutable evaluation snapshots | WaterPlan pattern: status CHECK, engine+methods versions, result JSONB, checksum, partial-unique (field, idempotency_key) |
| `cover_crop_plan_items` | adopted cover decisions | FK field, FK plan_run SET NULL, FK crop SET NULL; mixture composition JSONB (fractions ≤ 1 enforced at API); status CHECK |
| `residue_records` | residue production | FK field; basis CHECK (dry_matter/fresh_weight); production_status CHECK (4); produced ≥ 0 CHECK; index (field, season) |
| `residue_flow_events` | residue fates | FK record CASCADE; flow_type CHECK (7); dm_kg ≥ 0 CHECK; dm_kg_status CHECK; optional soil_management_event_id (loose ref) |
| `residue_quality_measurements` | C/N/C:N/lignin | FK record CASCADE; evidence_class |
| `erosion_assessment_runs` | screening/model snapshots | WaterPlan pattern + knowledge_pack_refs |
| `farm_resources` | farmer machinery/labor | FK farm CASCADE; resource_type CHECK (12); efficiency CHECK (0,1] |
| `field_operations` | planned/scheduled work | FK field; status CHECK (7); priority 1..5 CHECK; duration ≥ 0 CHECK; template provenance JSONB; indexes (field, earliest_start) + (field, status) |
| `operation_dependencies` | precedence edges | FK field + both operations CASCADE; dependency_type CHECK; no-self CHECK; UNIQUE edge |
| `operation_schedule_runs` | scheduler snapshots | status CHECK incl. `infeasible`; WaterPlan pattern |
| `management_plans` | aggregated seasonal plans | WaterPlan pattern + cross-run id arrays (cover/erosion/schedule/water/feature) |
| `management_plan_feedback` | farmer/agronomist feedback | FK plan CASCADE; role CHECK; rating CHECK |

## 2. Conventions kept

- UUID PKs, tenant scoping through the existing farm→field→organization
  chain (every API route resolves via `get_field_for_principal`).
- Timezone-aware timestamps (`TimestampMixin`); local calendar dates for
  agronomic windows (same basis as crop_history — documented in the cover
  method doc).
- JSONB only for claim payloads / source-specific metadata; every queryable
  identity is a relational column (spec §10).
- Missing evidence is NULL + a status column — never zero.
- Idempotency keys are partial-unique per field (identical to WaterPlan).
- No existing table altered; no event-type vocabulary extended.

## 3. Data dictionary additions

New domain vocabulary (canonical + JSONB payload fields) is specified in
`M6C_DATA_DICTIONARY.md`. Highlights: cover states (7), measurement bases
(6), eligibility statuses (4), residue flow types (7), production statuses
(4), erosion processes (7), unit conventions (2), resource types (12),
operation statuses (7), dependency types (3), practice families (7),
trade-off dimensions (12), plan-item statuses (5).

## 4. Dev database

The sandbox dev database was migrated in place; after an early iteration of
`0008` gained a column, the (unreleased) migration was edited and the dev DB
reconciled via `downgrade 0007 → upgrade head`, after which the M6C practice
pack rows were re-materialized by deleting the pack row and re-running the
idempotent seed (`seed_default_packs`). The test database is rebuilt from
scratch by `tests/conftest.py` (drop → migrate → create_all).

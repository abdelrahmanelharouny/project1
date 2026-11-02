# M7.1 — API Contracts

**Base:** `/api/v1` · **Auth:** bearer token · **Tenant scoping:** application-layer
membership guards through the field's farm (foreign org → 403; unknown → 404).
**Gateway rule (frontend):** relative paths + `XTransformPort=3030`.

---

## 1. Field state endpoints (new, `app/api/v1/field_states.py`)

### POST `/fields/{field_id}/field-states` → 202
Assemble a snapshot (or idempotently return the existing one for a repeated
field-scoped `idempotency_key`).

Request body (all optional):
```json
{
  "label": "string ≤120",
  "state_reference_time": "ISO-8601 (default: now, UTC)",
  "period_start": "ISO date/datetime (default: pinned run's window)",
  "period_end": "ISO date/datetime",
  "environmental_feature_run_id": "uuid (default: latest succeeded)",
  "water_plan_id": "uuid (default: latest succeeded)",
  "rotation_run_id": "uuid (explicit only — no default)",
  "rotation_strategy_key": "string (requires rotation_run_id)",
  "idempotency_key": "string"
}
```
Errors: 404 (field/refs), 422 (validation — incl. period required without run, env-run
zero overlap, non-succeeded pinned artifact), 409 (integrity of a pinned run's manifest).

Response: the full state payload (§1.1).

### GET `/fields/{field_id}/field-states` → 200 `{items: [state…]}`
### GET `/field-states/{state_id}?include_manifest=false` → 200 state payload
`include_manifest=true` adds the full `observation_manifest` document.
### GET `/field-states/{state_id}/verify` → 200
```json
{
  "state_id": "…", "checksum_valid": true, "manifest_checksum_valid": true,
  "referenced_artifacts": {"feature_run": {"exists": true, "intact": true},
                            "water_plan": {"exists": true, "intact": true}},
  "boundary_version_record_exists": true, "verified_at": "…"
}
```
### GET `/field-states/{state_id}/manifest` → 200 `{state_id, manifest_format_version, observation_manifest_sha256, observation_manifest}`
### POST `/field-states/compare` `{state_ids: [uuid, uuid, …]}` → 200 comparison report
(≥2 states, same field; 422 otherwise; 403/404 under foreign/unknown ids).

### 1.1 State payload (abridged)
`id, field_id, status, label, boundary_version, state_reference_time, period{start,end},
timezone, calendar_context, environmental_feature_run_id, water_plan_id, rotation_run_id,
rotation_strategy_key, crop_history_ids, knowledge_pack_refs, observation_manifest_sha256,
manifest_format_version, domain_availability, evidence_summary, quality_summary,
period_compatibility, source_versions, warnings, not_evaluated, error_summary,
checksum_sha256, created_by, created_at, completed_at, field_state_assembly_version,
verify_url, manifest_url`

**Soil/management honesty (C3):** `domain_availability.soil` / `.management` are always
`status: "not_implemented"` with the fixed M7.0 H-03 reason strings; `evidence_summary`
mirrors them. The UI renders them as "not implemented" badges — no fake records anywhere.

## 2. Changed existing contracts (additive only)

| Endpoint | Change |
|---|---|
| `GET /feature-runs/{id}` | + `?include_manifest=true` (document); payload + `created_by`, `boundary_version`, `observation_manifest_sha256` |
| `POST /fields/{id}/water-plans` payload | + `boundary_version`, `started_at`, `completed_at`, `created_by` |
| `DELETE /water-plans/{id}` | **409 Conflict** when referenced by ≥1 field state (F-13); 204 otherwise |
| `POST /fields/{id}/data-jobs` | + optional `idempotency_key` (field-scoped replay, F-30) |
| Rotation run payload | + `created_by`; `solver_version` now populated per run (F-20) |

## 3. Database schema changes (migration `0007_field_state_foundation`)

- **New table** `field_states` (34 columns — see `M7_1_FIELD_STATE_CONTRACT.md` §1) with
  FKs: `field_id → fields CASCADE`; `environmental_feature_run_id → feature_runs RESTRICT`;
  `water_plan_id → water_plans RESTRICT`; `rotation_run_id → rotation_runs RESTRICT`.
- **Additive columns:** `feature_runs.boundary_version`, `.observation_manifest (JSONB)`,
  `.observation_manifest_sha256`; `water_plans.boundary_version`, `.started_at`,
  `.completed_at` (all nullable).
- **Index change (F-30):** drop `uq_ingestion_idempotency` (key-only), create
  `uq_ingestion_idempotency_v2 (field_id, idempotency_key) WHERE idempotency_key IS NOT NULL`.
- **Downgrade** reverses everything (order-documented in the migration); verified by
  migration round-trip tests.
- Schema docs: `docs/database/schema.md` updated.

## 4. Error envelope

All errors use the platform envelope `{error: {code, message, details[], request_id}}`
with the existing codes (`NOT_FOUND` 404, `VALIDATION_FAILED` 422, `CONFLICT` 409,
`FORBIDDEN` 403).

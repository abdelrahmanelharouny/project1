# M7.2 — API Contracts

**Status:** implemented (`app/api/v1/scenarios.py`, registered in `app/api/v1/router.py`)
**Base path:** `/api/v1` · **Auth:** bearer token (`get_principal`) · **Errors:** structured
envelope `{"error": {code, message, details, request_id}}`

## 1. Endpoints

| Method & path | Purpose | Notes |
|---|---|---|
| `POST /fields/{field_id}/scenarios` | create a draft definition | body: `{scenario_type, name?, description?, configuration{type, parent_field_state_id, period?, adjustments?, assumption_metadata?}, parent_scenario_id?, idempotency_key?}`; idempotent replay returns the existing row; unimplemented types → 422 `SCENARIO_TYPE_NOT_IMPLEMENTED` |
| `GET /fields/{field_id}/scenarios` | list the field's scenarios | optional `scenario_type`, `scenario_status` filters |
| `GET /scenarios/types` | versioned taxonomy | static; capability status + evidence classes + adjustment bounds + lifecycle table |
| `GET /scenarios/capabilities` | platform capability report | static; execution `not_implemented` with reason; digital twin level honest |
| `GET /scenarios/{scenario_id}` | definition detail | `?include_validation_history=true` appends the immutable record list |
| `PATCH /scenarios/{scenario_id}` | edit a non-finalized definition | resets validation (status → draft); finalized → 409 `SCENARIO_IMMUTABLE` |
| `DELETE /scenarios/{scenario_id}` | delete a DRAFT only | else 409 `SCENARIO_DELETE_RESTRICTED` (archive instead) |
| `POST /scenarios/{scenario_id}/validate` | run the pure validation engine | appends an immutable record; returns verdict + findings + note "No simulation has been executed" |
| `POST /scenarios/{scenario_id}/finalize` | freeze the definition | requires valid/conditionally_valid; stamps `finalized_at`; immutable thereafter |
| `POST /scenarios/{scenario_id}/archive` | terminal retirement | checksums remain verifiable; archived is terminal |
| `POST /scenarios/{scenario_id}/versions` | new version of a FINALIZED scenario | same type & parent state enforced; new draft row with revision lineage |
| `GET /scenarios/{scenario_id}/versions` | revision chain | per-version status, checksums, timestamps |
| `GET /scenarios/{scenario_id}/lineage` | ancestors + children + revision chain | archived members included |
| `GET /scenarios/{scenario_id}/verify` | independent re-verification | recomputes the checksum from stored content, re-checks parent state + boundary record + latest validation match |
| `GET /scenarios/{scenario_id}/compare?against=` | definition-level comparison | structural config diff + warnings; NO simulated outputs compared |

**There is no run/execute endpoint** — M7.2 defines scenarios; M7.3 does not exist.

## 2. Tenancy & security semantics

- Tenant scoping is always resolved server-side: `get_field_for_principal` (field → farm →
  organization membership). Client-supplied ownership claims are never trusted.
- Foreign-but-existing resources follow the platform convention: 403 (Forbidden via
  membership check) / 404 (not found) — both leak nothing (tested).
- The parent Field State must belong to the **same field** (`PARENT_STATE_MISMATCH`), be
  `succeeded` (`PARENT_STATE_NOT_SUCCEEDED`) and carry a checksum
  (`PARENT_STATE_NOT_VERIFIED`).
- Idempotency keys are **field-scoped** (partial unique index) — a cross-tenant replay
  against another field cannot collide and never returns another tenant's row (tested).
- Scenario-id enumeration returns 404 for random UUIDs.
- Unauthenticated access → 401 on every dynamic endpoint.
- Concurrent/double finalization → second call 409 `SCENARIO_IMMUTABLE` (and the DB trigger
  backstops any race at the storage layer).

## 3. Error codes introduced

| Code | HTTP | Meaning |
|---|---|---|
| `SCENARIO_TYPE_NOT_IMPLEMENTED` | 422 | climate/forecast/unknown type; honest reason in details |
| `SCENARIO_CONFIGURATION_INVALID` | 422 | Pydantic contract violation (with per-field details) |
| `PARENT_STATE_MISMATCH` | 422 | parent state not of this field |
| `PARENT_STATE_NOT_SUCCEEDED` | 422 | parent status ≠ succeeded |
| `PARENT_STATE_NOT_VERIFIED` | 422 | parent has no checksum |
| `PARENT_SCENARIO_MISMATCH` | 422 | branch parent not of this field |
| `SCENARIO_TYPE_MISMATCH` | 422 | version endpoint keeps the type |
| `SCENARIO_INVALID_STATE_TRANSITION` | 409 | illegal lifecycle move (e.g. finalize before validate) |
| `SCENARIO_IMMUTABLE` | 409 | finalized/archived row mutation attempt |
| `SCENARIO_DELETE_RESTRICTED` | 409 | non-draft delete or delete-with-children |

## 4. Payload honesty (C2)

Every scenario payload carries: `evidence_classification` **and** a human
`evidence_label` ("Observed historical condition" / "Hypothetical assumption — not observed
data" / "Not available — no real data source"), the type display name, `unavailable_dimensions`
(soil, management, climate projection, weather forecast — each with its fixed reason), and a
note that this is a definition with no simulation executed.

## 5. Rate limits & pagination

No rate-limiting infrastructure exists in this repository (recorded in
`M7_2_LIMITATIONS_AND_BACKLOG.md`); lists are field-scoped and small. No run endpoint exists
to need replay protection beyond field-scoped idempotency.

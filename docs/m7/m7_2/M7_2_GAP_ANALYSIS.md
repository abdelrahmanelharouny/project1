# M7.2 — Phase 0 Gap Analysis (Repository Baseline → Scenario Domain)

**Milestone:** M7.2 — Scenario Domain & Immutable Scenario Definitions
**Phase:** 0 (Inspection) — performed **before** any modification
**Governing rule:** *"Do not assume previous reports reflect the current working tree."*
Every claim below was re-measured on the live working tree on the day of this analysis.

---

## 1. Repository identity (measured)

| Check | Measured value |
|---|---|
| Branch | `main` |
| Commit SHA | `15013c7` — "M7.1: field state foundation & snapshot hygiene (H-01, H-02, F-13, F-30, field_states, Field State tab)" |
| Working tree | **clean** (`git status --porcelain` empty) |
| Migration head (files) | `0007_field_state_foundation` (revises `0006_water_intelligence`) |
| Backend regression | **490 passed, exit 0** (full `tests/` run; = 441 pre-M7.1 + 49 M7.1) |
| Frontend lint | `eslint .` **exit 0**, clean |
| M7.0 readiness documents | all 13 present under `docs/m7/readiness/` |
| M7.1 documents | all 6 present under `docs/m7/m7_1/` |

## 2. What actually exists in the tree (verified by reading code)

| Capability | Location | State |
|---|---|---|
| Immutable field-state snapshots | `app/field_state/{contracts,manifest,service}.py`, `app/db/models.py::FieldState`, `field_states` table (migration 0007) | ✅ complete — checksum (`checksum_sha256` over canonical JSON excluding `created_at`/`created_by`), verbatim observation-manifest copy + hash, `verify` endpoint recomputing state/manifest/artifact/boundary checks, same-field compare endpoint, field-scoped idempotency partial-unique index |
| Boundary version pinning (H-01) | `field_states.boundary_version` NOT NULL; `feature_runs`/`water_plans` same; append-only `field_boundary_versions`; RESTRICT-FK artifact protection (F-13) | ✅ |
| Observation manifest (H-02) | `app/field_state/manifest.py` — canonical JSON (`sort_keys`, tight separators, UTF-8), ISO-UTC timestamps, stable ordering `(observed_at, id)`, explicit nulls, `field-observation-manifest-1` format | ✅ |
| Tenant isolation | `app/domains/identity/service.py` — `Principal` (bearer token → memberships), `get_field_for_principal` (404 for foreign objects), org-scoped membership check | ✅ |
| Error envelope | `app/core/errors.py` — `FieldShiftError` hierarchy → `{"error": {code, message, details, request_id}}`, 404-vs-403 platform convention | ✅ |
| Immutable-run idiom | water plans / feature runs / field states: `running → succeeded/failed` rows, never rewritten; recomputation = new row; run-envelope timestamps | ✅ |
| Canonical hashing utilities | `sha256_of_document`, `canonical_json`, `iso_utc` in `app/field_state/manifest.py` | ✅ (reused; scenario module imports — no duplication) |
| Frontend workspace | 8 tabs (`overview, farms, observations, features, rotation, water, fieldstate, passport`); zustand `WorkspaceTab`; typed `src/lib/api.ts` with `XTransformPort=3030` relative-path gateway rule; honest `not_implemented` badges for soil/management in the Field State tab | ✅ |
| Scenario domain | **nothing** — no `app/scenarios/`, no scenario tables, no migration 0008, no scenario routes, no frontend tab | ❌ greenfield (this milestone) |

## 3. M7.0 conditions carried into M7.2 (from `M7_0_FINAL_READINESS_REPORT.md`)

| Condition | Requirement | M7.2 impact |
|---|---|---|
| C1 | M7.1 hygiene lands **before** M7.2 builds on states | **Satisfied** — commit `15013c7` verified above; scenarios reference verified parent states only |
| C2 | Scenario types never presented as equivalent evidence; per-type labels in payloads, API, UI | **Direct M7.2 requirement** — `evidence_classification` column with a DB CHECK binding type→class (`observed` / `hypothetical` / `not_available`), surfaced in every payload and as UI badges |
| C3 | Soil & management ship as explicit NOT_IMPLEMENTED — no proxy claims | Scenario dimensions for soil/management do not exist; capabilities endpoint + UI report `not_implemented` with the M7.0 H-03 reasons |
| C4 | No calibrated/predictive (L4/L5) language until real calibration data | Scenario copy avoids "predictive twin" language; Digital Twin remains Level 1 (historical profile) |
| C5 | M7.8 blocked until sourced projection/forecast data | Climate Projection & Weather Forecast types are contract-only, `not_implemented`; creation requests are rejected; no forecast/projection evidence can be produced |

## 4. Gap register (M7.2 spec section → current state → work required)

| # | Spec requirement | Current state | Work required |
|---|---|---|---|
| G-01 | §4 Scenario taxonomy, versioned | Absent | `app/scenarios/contracts.py`: versioned taxonomy registry with per-type capability (`implemented` / `not_implemented`), evidence class, description |
| G-02 | §4.4/4.5 Climate projection & forecast types defined but unavailable | Absent | Enum members + capability registry `not_implemented`; creation rejected 422 `SCENARIO_TYPE_NOT_IMPLEMENTED`; no config model, no fabricated records |
| G-03 | §4.6 Soil/management scenario dimensions unavailable | Absent | Explicit `not_implemented` capability entries (M6B/M6C absent from repository — M7.0 finding H-03); no fabricated dimensions |
| G-04 | §5 Normalized relational model | Absent | `scenarios` + `scenario_validation_records` tables (migration `0008_scenario_domain`); self-referential `parent_scenario_id` + `lineage_kind` covers lineage — **no** separate `scenario_lineage` table (spec §5: do not over-normalize); **no** separate `scenario_configuration_versions` table because each scenario row is already an immutable version carrying payload/canonical form/schema version/checksum/author/timestamp/parent (spec §5 allows this) |
| G-05 | §6 Strictly typed, versioned configuration contracts | Absent | Pydantic models per implemented type (discriminated on `type`), explicit units in field names, numeric bounds, date-interval and conflict rules; generic JSON rejected |
| G-06 | §6/§7 Canonical serialization + deterministic checksum | Absent | Reuse `canonical_json`/`sha256`; checksum input = `{schema_version, scenario_type, canonical_configuration, parent_snapshot_checksum, boundary_version, period, timezone}`; name/description/UI metadata excluded |
| G-07 | §7 Immutability after finalization | Absent | App-level transitions + **DB trigger** `enforce_scenario_immutability` (finalized/archived rows reject content changes; only `finalized→archived` status move allowed) |
| G-08 | §7 Parent snapshot protection | Absent (scenario side) | `parent_field_state_id` FK **RESTRICT** → a referenced Field State cannot be deleted (mirrors F-13); parent checksum + boundary version copied by value at creation |
| G-09 | §8 Pure validation engine | Absent | `app/scenarios/validation.py` — no HTTP/ORM imports; result vocabulary `valid / invalid / conditionally_valid / unsupported / not_implemented / missing_reference / incompatible_period / insufficient_parent_evidence`; findings, missing inputs, unsupported dimensions; real-vs-synthetic + hypothetical-vs-observed checks |
| G-10 | §9 Lifecycle | Absent | States `draft → validation_pending → valid / conditionally_valid / invalid / finalized / archived / unsupported` with a documented legal-transition table enforced in the service; finalized = immutable |
| G-11 | §10 Definition-level comparison | Absent | Canonical-configuration structural diff + parent/state/boundary/period/evidence comparison; explicit compatibility warning on differing parents/boundaries; **no** simulated-output comparison (M7.3 does not exist) |
| G-12 | §11 API endpoints | Absent | `app/api/v1/scenarios.py` registered in `router.py`; create/list/get/patch/delete/validate/finalize/versions/lineage/compare/verify/types/capabilities; **no** run/execute endpoint |
| G-13 | §12 Frontend Scenario Workspace | Absent | New `scenarios` tab: parent-state selection, typed creation, units, validate/finalize/versions/lineage/compare/checksums, evidence badges, unavailable-states panel; no simulation graphs |
| G-14 | §14 Tests | Absent | `tests/unit/test_scenario_contracts.py`, `tests/unit/test_scenario_validation.py`, `tests/integration/test_scenarios.py`, migration tests; full M1–M7.1 regression must stay green (490 baseline) |
| G-15 | §15 Documentation | Absent | 12 new docs in `docs/m7/m7_2/` + updates: `IMPLEMENTATION_STATUS.md`, `TEST_MATRIX.md`, schema docs, ADR, API docs |

## 5. Explicit non-goals inherited from the M7.2 spec

- No M7.3 environmental transformations — a valid configuration is **not** a simulated result.
- No forecast/projection execution or evidence (C5).
- No soil/management scenario dimensions (C3, M6B/M6C absent).
- No new infrastructure beyond one additive migration + two tables + one trigger.
- No run/execute endpoint of any kind.

## 6. Design decisions locked at inspection time

1. **Temporal/spatial scopes as real columns** (`period_start/period_end/timezone/boundary_version`), not opaque JSONB, so DB-level CHECKs can enforce ordering and type→evidence consistency. (Spec's `temporal_scope`/`spatial_scope` are realized as these columns; documented in the contract docs.)
2. **Versions are rows**: a revision of a finalized scenario creates a new `scenarios` row (`lineage_kind='revision'`, `scenario_version=parent+1`, `parent_scenario_id=parent`); a branch creates `lineage_kind='branch'`. One self-FK covers version chains and branches.
3. **Draft editing is allowed** (status `draft`/`invalid` only) and resets validation; finalization freezes the row (trigger-enforced). This matches "A scenario definition that is finalized must become immutable" while keeping DRAFT meaningful.
4. **Checksum scope**: scientific configuration only (type, schema version, canonical configuration, parent pin, temporal/spatial pin). `name`, `description`, `idempotency_key` are UI/provenance metadata and are excluded.
5. **Climate/forecast creation rejected** rather than stored as shells — no rows can imply capability; the taxonomy and capabilities endpoints carry the contract-forwarding duty.
6. **Tenant rule**: never trust client ownership claims; the parent Field State is resolved through `get_field_for_principal` (farm → organization membership) server-side at every reference boundary.

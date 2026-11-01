# M7.1 — Design: Field State Foundation & Snapshot Hygiene

**Milestone:** 7.1 (first GO-approved increment of the M7 program)
**Basis:** M7.0 Readiness Inspection — CONDITIONAL GO, adjustment A1
**Date:** 2026-11-01 · **Status:** implemented and verified (see `M7_1_TEST_AND_VERIFICATION.md`)
**Scope guard:** M7.1 only. No scenario engine (M7.2), no perturbations (M7.3), no robust
optimization, no digital-twin claims, no soil/management functionality (M6B/M6C remain
NOT_IMPLEMENTED — verified by M7.0).

---

## 1. What M7.1 delivers (mapped to the M7.0 findings)

| Sub-task | M7.0 finding | Deliverable | Where |
|---|---|---|---|
| Boundary version pinning | H-01 / F-01 | `boundary_version` column on `feature_runs` and `water_plans` (additive, NULL = pre-M7.1 "not recorded", never guessed); mandatory on every `field_states` row | migration `0007_field_state_foundation`, `app/features/service.py`, `app/water/service.py`, `app/field_state/service.py` |
| Observation manifest | H-02 / F-03 / F-31 | Versioned manifest document (`field-observation-manifest-1`) + deterministic SHA-256, stored **by value** on `feature_runs` and copied verbatim onto `field_states` | `app/field_state/manifest.py`, `app/features/service.py` |
| Water-plan deletion policy | F-13 | `DELETE /water-plans/{id}` → **409 Conflict** when referenced by any field state; FK RESTRICT as the database-level backstop | `app/api/v1/water.py`, migration 0007 FKs |
| Ingestion idempotency composite fix | F-30 | Legacy key-only unique index replaced by `uq_ingestion_idempotency_v2 (field_id, idempotency_key)`; replay lookup field-scoped; optional `idempotency_key` on the data-job request | migration 0007, `app/data_platform/ingestion/service.py`, `app/api/v1/data_platform.py` |
| Unified Field State | spec §4 | `field_states` table — immutable, checksummed, by-reference composition; honest `not_implemented` soil/management dimensions | `app/field_state/*`, `app/db/models.py` |
| Period compatibility | F-02 | Per-dimension coverage records in `period_compatibility`; zero-overlap environmental run REFUSED; zero-overlap water plan recorded as `period_mismatch` + warning | `app/field_state/service.py` |
| Staleness / as-of semantics | F-10 | `state_reference_time` (as-of instant) + explicit as-of rule for crop history (`sowing_date <= reference time`); undated rows never guessed | `app/field_state/service.py` |
| Provenance surfacing | F-09 / F-20 / F-32 | `created_by` surfaced in feature-run, water-plan, rotation-run, field-state payloads; `solver_version` now written per rotation run; `started_at`/`completed_at` added to water plans | `app/features/service.py`, `app/water/service.py`, `app/rotation/{problem,service}.py` |
| Inspection UI | readiness docs (browser-verified state view) | 8th workspace tab "Field State": assemble, inspect, verify, compare | `src/components/fieldshift/field-state.tsx` |

Deliberately NOT in M7.1 (recorded for M7.2+): the full run-envelope projection
(`M7_0_API_AND_DATABASE_READINESS.md` §5 lands the serialization convention with the
scenario result tables in M7.2); worker/cancellation/progress (H-04, M7.5); climate-context
override (H-05, M7.3).

## 2. Core design decisions

### D1 — By-reference composition, never duplication
A field state stores: ids of the pinned artifacts, their engine/method versions **as read at
assembly time**, the resolved knowledge-pack ref set (the platform's existing `pack_ref`
idiom, copied by value), crop-history ids (rows are immutable), and a verbatim copy of the
pinned run's observation manifest (needed because the manifest is the one input that today
lives only on the run — copying makes states independently verifiable without re-deriving
anything). No agronomic data is duplicated.

### D2 — Immutability via the proven water-plan idiom
New row per assembly; status `running → succeeded/failed`; nothing rewritten; field-scoped
idempotency keys with replay (202 pattern); checksum over every scientifically material
stored field (D4). Referenced artifacts are protected by **FK RESTRICT** — the F-13
enforcement is structural, not conventional.

### D3 — Manifest at the resolution site
The manifest is built in `features/service._execute_run` from the exact resolved input list
handed to the engine (uncapped — the 400-id cap applies only to the legacy per-value
provenance, which is unchanged), then stored on the run at completion. The builder re-sorts
by its own canonical rule, so query-order changes cannot alter the hash. Re-ingesting new
rows later does not change a stored manifest (tested).

### D4 — Checksum covers content, excludes provenance
`state_checksum_payload` = assembly version, manifest format version, field id, boundary
version, reference time, period, timezone, calendar context, all dimension refs, sorted
crop-history ids, sorted pack refs, manifest hash, domain availability, evidence summary,
quality summary, period compatibility. Excluded: `created_at` / `created_by` (provenance,
not content). Reconstruction test: two assemblies from identical refs → identical checksum.

### D5 — Honest vocabulary, no scores
`domain_availability` per dimension: `available | missing | period_mismatch |
not_evaluated | not_implemented` (contracts.py). `soil` and `management` are **always**
`not_implemented` with the M7.0 H-03 reason strings. No completeness percentage anywhere.

### D6 — Tenant isolation unchanged
Application-layer membership guards on every new route (platform convention: foreign org →
403; unknown resource → 404). Tested for every endpoint including compare.

## 3. Verification of the conditional-go conditions (C1–C5)

- **C1** — all four hygiene items landed in M7.1 before M7.2: boundary pinning ✓,
  manifest hash ✓, deletion policy ✓, ingestion idempotency ✓ (this milestone).
- **C2** — scenario-type evidence labeling: not applicable yet (M7.2); no scenario type
  exists, so no equivalent-evidence presentation was introduced.
- **C3** — soil/management ship as explicit `not_implemented` in states and UI ✓.
- **C4** — no calibrated/predictive language anywhere; the state UI labels snapshots
  "immutable snapshots assembled from existing artifacts" ✓.
- **C5** — M7.8 not started; no forecast/projection code touched ✓.

## 4. Files created / modified

**Created:** `migrations/versions/0007_field_state_foundation.py` ·
`app/field_state/{__init__,contracts,manifest,service}.py` ·
`app/api/v1/field_states.py` · `tests/unit/test_observation_manifest.py` ·
`tests/integration/test_field_states.py` · `src/components/fieldshift/field-state.tsx` ·
this document set (`docs/m7/m7_1/*.md`).

**Modified (additive only):** `app/db/models.py` (FieldState model + 5 additive columns) ·
`app/features/service.py` (boundary pin, manifest build/store, payload fields) ·
`app/water/service.py` (boundary pin, timestamps, payload fields) ·
`app/water.py` API (DELETE guard) · `app/api/v1/data_platform.py` (optional
idempotency_key) · `app/data_platform/ingestion/service.py` (scoped replay) ·
`app/rotation/problem.py` (`solver_version()`) · `app/rotation/service.py` (write
`solver_version`, surface `created_by`) · `app/api/v1/features.py`
(`?include_manifest=true` on run detail) · `app/api/v1/router.py` ·
`src/lib/{types,api}.ts`, `src/hooks/use-fieldshift.ts`, `src/lib/store.ts`,
`src/components/fieldshift/workspace.tsx` · `tests/integration/test_migrations.py`.

## 5. Restriction compliance

No M7.2+ capability was implemented; no engine behavior changed (the 441-test M1–M6A
regression passes unmodified, 490/490 total); no new runtime dependency; no migration
rewrites existing data; the downgrade path restores the exact pre-0007 schema.

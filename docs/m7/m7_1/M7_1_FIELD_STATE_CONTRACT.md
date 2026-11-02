# M7.1 — Field State Contract

**Status:** implemented (`app/field_state/service.py`, `app/db/models.py::FieldState`)
**Principle:** a field state is an immutable, checksummed, **by-reference** composition of
already-versioned artifacts. It computes no agronomy and duplicates no domain data.

---

## 1. Stored structure (`field_states` table)

| Group | Columns | Semantics |
|---|---|---|
| Identity | `id`, `field_id` (FK CASCADE), `status`, `label` | status `running → succeeded/failed`; new row per assembly |
| Spatial pin (H-01) | `boundary_version` (NOT NULL) | the exact append-only boundary version in effect at assembly; verify confirms the boundary-history row exists |
| Temporal | `state_reference_time`, `period_start`, `period_end`, `timezone`, `calendar_context` | as-of instant + the period the state qualifies; timezone = farm timezone; calendar context carries hemisphere (from the pinned run) + union of season labels |
| Refs | `environmental_feature_run_id`, `water_plan_id`, `rotation_run_id`, `rotation_strategy_key`, `crop_history_ids`, `knowledge_pack_refs` | FKs are **RESTRICT** (F-13 backstop); crop history pinned as `[{id, crop_label, season_label, sowing_date, harvest_date, source}]` for rows with `sowing_date <= state_reference_time`; pack refs copied from the resolved active set (`pack_ref` idiom with checksums) |
| Manifest (H-02) | `observation_manifest`, `observation_manifest_sha256`, `manifest_format_version` | verbatim copy of the pinned run's manifest + its hash (see `M7_1_OBSERVATION_MANIFEST.md`) |
| Honest summaries | `domain_availability`, `evidence_summary`, `quality_summary`, `period_compatibility` | per-dimension; no generic score (see §2, §3) |
| Versions | `source_versions` | assembly version + engine/catalog versions of pinned artifacts as read at assembly |
| Envelope | `request_parameters`, `warnings`, `not_evaluated`, `error_summary`, `idempotency_key`, `checksum_sha256`, `created_by`, `started_at/created_at/completed_at` | platform run idiom; idempotency field-scoped (replay returns the existing row) |

Indexes: `uq_field_state_idempotency (field_id, idempotency_key) WHERE key IS NOT NULL`,
`ix_field_states_field`. Checks: status enum, `period_end >= period_start`.

## 2. Domain availability vocabulary (per dimension)

`environmental`, `water`, `rotation`, `crop_history`, `soil`, `management`:

- `available` — a pinned artifact exists and qualifies for the state period.
- `missing` — implemented domain, no artifact (with the reason, e.g. "no succeeded
  feature run exists", "plans are only created on explicit request (F-05)").
- `period_mismatch` — artifact pinned but entirely outside the state period (provenance
  only; never mixed silently; a warning is recorded).
- `not_evaluated` — assembly could not judge coverage (with reason).
- `not_implemented` — **soil and management, always**, with the fixed M7.0 H-03 reasons:
  - soil: "Soil health & nutrient cycling (M6B) is not implemented in this repository…"
  - management: "Field management intelligence (M6C) is not implemented in this repository…"

No completeness score exists anywhere in the contract — orthogonal dimensions stay
per-dimension (M7.0 §4 of the field-state readiness doc).

## 3. Assembly rules

1. **Environmental run** — explicit id (must belong to the field and be `succeeded`; 404 /
   422 otherwise) or default = latest succeeded run. None → `missing` (never fabricated).
2. **Water plan** — explicit id or default = latest succeeded. None → `missing`.
3. **Rotation run** — **explicit only** (runs are optimization experiments, M7.0 F-06);
   optional `rotation_strategy_key` validated against the run's strategies.
4. **Crop history** — dated rows as of the reference time; undated rows are skipped
   (never guessed into a time position).
5. **Period** — explicit `period_start/period_end` (ISO date or datetime; dates are UTC
   midnights) or default = the pinned run's window; required when no run is pinned (422).
6. **Period compatibility (F-02)** — per dimension, overlap fraction recorded:
   - environmental zero-overlap → **422 refused** (a snapshot cannot qualify a period it
     does not touch); partial cover → dimension `period_mismatch` + warning;
   - water zero-overlap → allowed, dimension `period_mismatch` + warning;
   - rotation partial → warning.
7. **Checksum** — SHA-256 over the canonical JSON of everything material (D4 of the design
   doc); `created_at`/`created_by` excluded. Deterministic: identical refs → identical
   checksum (regression-tested).

## 4. Immutability & verification

- Inputs cannot silently change: artifacts are RESTRICT-protected; new ingestions do not
  alter a stored manifest; boundary edits create new versions and never touch old states.
- `GET /field-states/{id}/verify` recomputes: (1) the state checksum from stored fields;
  (2) the manifest hash from the stored document; (3) referenced-artifact existence and,
  for water plans, the plan's own snapshot checksum; (4) the boundary-version record.
  Division of responsibility: tampering the manifest *document* trips the manifest check
  (the state checksum still passes — it pins the stored *hash*); tampering the stored
  *hash* (or any stored field) trips the state checksum. Both paths are tested.
- Recomputation creates a NEW row; same refs → same checksum, different id.

## 5. Comparison semantics

`POST /field-states/compare {state_ids: [≥2]}` — same field only (422 otherwise). Reports:
boundary-version consistency, per-dimension ref consistency, manifest-hash consistency,
pairwise period-overlap fractions, and the explicit note that states with different
boundary versions or non-overlapping periods are NOT interchangeable as a time series
without qualification.

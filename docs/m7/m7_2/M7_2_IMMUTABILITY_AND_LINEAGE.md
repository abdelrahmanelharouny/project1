# M7.2 — Immutability, Versioning and Lineage

**Status:** implemented (service `app/scenarios/service.py`; DB trigger in migration `0008_scenario_domain`)

## 1. Guarantee

After finalization a scenario **cannot change** — enforced by the application AND, as the
backstop, by a database trigger so even a buggy code path or a manual SQL session cannot
silently rewrite a finalized definition.

## 2. Enforcement layers

### 2.1 Service-level transitions

- `PATCH` allowed only while `scenario_status ∈ {draft, validation_pending, valid,
  conditionally_valid, invalid}`; finalized/archived → 409 `SCENARIO_IMMUTABLE`.
- `DELETE` allowed only for drafts **without children**; everything else must be archived
  (409 `SCENARIO_DELETE_RESTRICTED`), preserving lineage and verifiable checksums.
- `validate` on finalized/archived → 409 (the stored `validation_summary` is frozen with the
  row; re-verification uses `GET /scenarios/{id}/verify`, which writes nothing).
- `finalize` requires status `valid`/`conditionally_valid` and stamps `finalized_at`;
  double-finalize → 409.
- Any edit resets validation: the previous verdict referred to a configuration that no longer
  exists (status → draft, `validation_summary` cleared).

### 2.2 Database trigger `enforce_scenario_immutability`

```
BEFORE UPDATE ON scenarios FOR EACH ROW:
  IF OLD.scenario_status IN ('finalized','archived'):
    any difference in field_id, name, description, scenario_type, lineage_kind,
    scenario_version, parent_field_state_id, parent_snapshot_checksum, boundary_version,
    parent_scenario_id, configuration_schema_version, canonical_configuration,
    configuration_checksum, period_*, timezone, evidence_classification,
    assumption_metadata, validation_summary, created_by, finalized_at,
    idempotency_key  → RAISE EXCEPTION
    finalized → anything except {finalized, archived} → RAISE EXCEPTION
    archived  → anything except archived → RAISE EXCEPTION (terminal)
```

Tested by direct SQL tampering attempts (canonical configuration, checksum, status) — all
raise; the only permitted move (`finalized → archived`) succeeds; archived is terminal.

### 2.3 Referential protection

- `scenarios.parent_field_state_id` FK **RESTRICT** → a referenced Field State cannot be
  deleted (this also blocks field deletion through `field_states.field_id` RESTRICT chain).
- `scenarios.parent_scenario_id` FK **RESTRICT** → lineage members cannot be deleted out of a
  chain.
- The parent's snapshot checksum and boundary version are **copied by value** at creation, so
  "deleting/modifying a referenced record" can never silently rewrite a historical scenario's
  meaning.

## 3. Versioning

- `POST /scenarios/{id}/versions` (finalized parents only): new **draft** row,
  `lineage_kind='revision'`, `scenario_version = parent + 1`, same type/field/parent state
  (enforced: type change → 422 `SCENARIO_TYPE_MISMATCH`; parent state change → 422
  `PARENT_STATE_MISMATCH`), configuration from payload (defaults to the parent's canonical
  configuration).
- The original row is untouched — regression-tested byte-for-byte (canonical configuration
  and checksum unchanged after versioning).
- Editing drafts is by PATCH; versioning is the *only* way to change a finalized definition.
- Historical replay: identical configuration + identical parent pins → identical checksum
  (regression-tested).

## 4. Lineage

One self-FK (`parent_scenario_id`) + `lineage_kind` covers everything; no separate lineage
table (spec §5: do not over-normalize).

- `root` — no parent scenario.
- `revision` — a new version of the same logical scenario.
- `branch` — a derived scenario with a different configuration/type.

`GET /scenarios/{id}/lineage` returns ancestors (walking the parent chain), direct children,
and the revision-chain length. `GET /scenarios/{id}/versions` returns the full revision chain
ordered by version with per-version checksums and finalization timestamps. Archived members
remain part of the lineage, retrievable and checksum-verifiable (tested).

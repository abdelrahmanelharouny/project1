# M7.1 — Boundary Versioning & Pinning (H-01)

**Status:** implemented
**M7.0 finding closed:** H-01/F-01 — "boundary versions exist and are append-only, but no
result records which version it used" (INT-12).

---

## 1. What existed before M7.1 (unchanged)

- `fields.boundary` (current MULTIPOLYGON 4326, GiST-indexed) + `fields.boundary_version`
  (int, starts at 1).
- `field_boundary_versions` — append-only history: every boundary write creates a new row
  (`version_number`, geometry, `area_ha`, `change_reason`, `created_by`, `created_at`),
  unique per (field, version). Old versions are never rewritten or deleted.
- Ingestion resolves the *current* boundary for raster extraction at fetch time.

## 2. What M7.1 adds

### 2.1 Pins on computed artifacts (additive columns)

| Table | Column | Semantics |
|---|---|---|
| `feature_runs` | `boundary_version` (nullable) | the boundary version in effect when the run executed — raster extraction and aggregation are geometry-dependent. Written at run creation from `field.boundary_version`. |
| `water_plans` | `boundary_version` (nullable) | same rationale (area conversions, PTF texture aggregation). Written at plan creation. |
| `field_states` | `boundary_version` (NOT NULL) | mandatory pin on every state. |

**NULL semantics (honesty rule):** NULL means "created before M7.1 — not recorded". The
migration does NOT backfill historical rows with the current version, because that would
be a guess: a pre-M7.1 run may have executed under an older boundary. Nothing is
fabricated; payloads surface the pin as-is.

### 2.2 Guarantees

1. **Historical runs keep their original pin** — a boundary edit increments
   `fields.boundary_version` and appends a history row; existing run/plan/state rows are
   untouched (regression-tested: run-before-edit pins v1, run-after-edit pins v2).
2. **Boundary changes never rewrite historical analysis** — runs/plans are append-only
   artifacts; states reference boundary versions, not the live geometry.
3. **Current and historical geometry are distinguishable** — `fields.boundary` +
   `boundary_version` (current) vs `field_boundary_versions` (history); every state can be
   traced to its exact geometry via the version row.
4. **Geometry provenance retained** — version rows carry `change_reason` (audit trail
   unchanged); states verify their version row exists at verify time.
5. **Silent upgrade is impossible going forward** — new artifacts always record the
   version they used; a state assembled after an edit records the new version (tested).
6. **No data duplication** — pinning stores an integer reference into the existing
   append-only history; geometry lives only in `fields`/`field_boundary_versions`.

### 2.3 Enforcement

- DB level: `field_states.boundary_version` NOT NULL; verify checks the
  `field_boundary_versions` row exists (`boundary_version_record_exists`).
- API level: `boundary_version` surfaced in feature-run, water-plan and field-state
  payloads; the state UI renders a "boundary vN" badge per snapshot and per comparison.

## 3. Known residual limitation (documented, not hidden)

Ingestion-time raster extraction still resolves the *current* boundary at fetch time, and
historical (pre-M7.1) artifacts have no pin. M7.1 makes every **new** artifact
boundary-explicit and makes states geometrically traceable; retroactive pinning of legacy
rows remains impossible without fabrication. This is exactly the resolution the M7.0
inspection prescribed ("state can record current version going forward; degrades
historical states" — F-01 verdict).

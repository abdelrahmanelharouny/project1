# M7.1 — Observation Manifest Specification

**Status:** implemented (`app/field_state/manifest.py`)
**Format version:** `field-observation-manifest-1`
**Purpose (M7.1 spec §3 / M7.0 H-02):** preserve, **by value**, the exact resolved
environmental input set of a feature run so re-runs cannot silently absorb new ingestions
and checksums stay verifiable independent of mutable queries.

---

## 1. Document structure

```json
{
  "format_version": "field-observation-manifest-1",
  "context": {
    "field_id": "<uuid>",
    "purpose": "feature_run_resolved_inputs" | "field_state_environmental",
    "window_start": "<ISO-8601 UTC|null>",
    "window_end": "<ISO-8601 UTC|null>",
    "variables": ["…sorted unique…"],
    "source_products": [{"variable": "…", "dataset_product_id": "…", "product_code": "…", "product_version": "…"}],
    "processing_configuration": {"feature_engine_version": "…", "feature_catalog_version": "…",
                                 "calendar_timezone": "…", "hemisphere": "…",
                                 "resolution_window_margin_days": 2}
  },
  "observation_count": 543,
  "synthetic_observation_count": 543,
  "observations": [ { …entry… }, … ]
}
```

The context is part of the hashed document — a manifest without its resolution context is
not interpretable, so it is not hashed separately.

## 2. Entry schema (one per resolved observation; nulls explicit, never omitted, never zero)

| Key | Source | Notes |
|---|---|---|
| `id` | `observations.id` | string UUID |
| `variable_code`, `unit` | direct | |
| `dataset_product_id` | direct | identity of the product row (its code/version live in `context.source_products`) |
| `observed_at`, `period_start`, `period_end` | direct | ISO-8601 UTC (§3) |
| `time_support` | direct | instant…annual; engine excludes mixed supports with warnings — excluded rows are still IN the manifest (they are part of the resolved input) |
| `value` | direct | `null` = missing/nodata — preserved exactly |
| `quality_status` | direct | valid/suspect/invalid/missing/estimated/not_assessed |
| `spatial_support_type`, `spatial_resolution_m` | direct | per-observation spatial support preserved (spec §3 "relevant spatial support") |
| `evidence_class` | direct | evidence class carried per row (synthetic/real separation never inferred) |
| `is_synthetic` | direct | counted in `synthetic_observation_count` |
| `uncertainty` | `uncertainty_value`/`uncertainty_type` | `null` when both null |
| `asset_refs` | promoted from `metadata` | stable keys only: `asset, asset_id, raster_url, source_url, file_name, granule_id` (spec §3 "original asset references"); other metadata is not promoted so the hash stays compact and stable |
| `processing_version` | direct | per-row processing version |

## 3. Determinism rules (all regression-tested)

1. **Canonical serialization** — `json.dumps(sort_keys=True, separators=(",", ":"),
   ensure_ascii=False, default=str)`, UTF-8; hash = SHA-256 hex of the canonical text.
2. **Ordering** — entries sorted by (`observed_at` UTC string, `id`); context lists sorted;
   `source_products` sorted by their canonical JSON. The builder's own sort makes the hash
   independent of the DB query's ORDER BY.
3. **Timestamps** — ISO-8601, UTC, explicit `+00:00`. Naive datetimes are interpreted as
   UTC; `Z` suffix and numeric offsets normalize to the same serialization
   (`2015-03-02T00:00:00+00:00`).
4. **Nulls** — explicit `null`, key present.
5. **Change detection** — any change to a value, quality status, membership (added/removed
   row), or context changes the hash (tests for each).
6. **Idempotence** — `manifest_entry(entry)` over an already-built entry reproduces it
   (JSON-safe scalars only).

## 4. Capture points

- **Feature run (primary):** built in `features/service._execute_run` from the exact
  resolved list handed to the engine — the full uncapped set (the 400-id cap applies only
  to the legacy per-value provenance, which is unchanged). Stored on the run at completion
  (`feature_runs.observation_manifest`, `observation_manifest_sha256`). Re-ingesting rows
  later does not change a stored manifest (tested).
- **Field state:** verbatim copy of the pinned run's manifest + hash; integrity of the
  copy is checked at assembly (Conflict if the run's stored hash disagrees with its
  document). Runs without a stored manifest (pre-M7.1 rows) yield an honestly empty
  document with `manifest_status: unavailable_pre_m7_1_run` — never a fabricated one.
- **Verification:** `GET /field-states/{id}/verify` recomputes the hash from the stored
  document; the feature-run detail endpoint exposes the document via
  `?include_manifest=true`; the state manifest endpoint returns it directly.

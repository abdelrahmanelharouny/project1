# M7.2 — Domain Design: Scenario Domain & Immutable Scenario Definitions

**Status:** implemented (commit `cfbf112`; module `app/scenarios/`, tables `scenarios` + `scenario_validation_records`, migration `0008_scenario_domain`, frontend `src/components/croptwist/scenarios.tsx`)

## 1. Mission

A first-class **Scenario Domain** that lets farmers and advisors define, validate, version,
inspect and compare **hypothetical field scenarios** against immutable Field State snapshots.
M7.2 establishes the data model, taxonomy, configuration contracts, validation rules, APIs
and user experience. It does **NOT** execute simulations — the definition/result boundary is
enforced architecturally (no execution endpoint, no transformation code, no result tables).

## 2. Architectural position

```
Field States (M7.1, immutable)  ──are the authoritative baseline of──▶  Scenario definitions (M7.2)
        ▲                                                                     │
        │ RESTRICT-FK: referenced states cannot be deleted                    │ references only
        └──────────────────────────────────────────────────────────────────────┘

M7.3 Environmental stress transformations ……… DOES NOT EXIST (M7.2 stores/validates config only)
M7.8 Climate projections / forecasts …………  contract placeholders, creation rejected
M6B/M6C Soil / Management …………………  absent from repository; reported not_implemented
```

Inherited building blocks (nothing duplicated):

| Reused from | What |
|---|---|
| `app/field_state/manifest.py` | `canonical_json`, `sha256_of_document` (single canonicalization authority) |
| M7.1 immutability idiom | new row per version, checksums over stored content, RESTRICT-FK reference protection |
| `app/domains/identity` | `get_principal` / `get_field_for_principal` tenant resolution at every boundary |
| `app/core/errors.py` | structured error envelope; domain codes via `CropTwistError(code=…)` |
| Frontend workspace | 9th tab, `api.ts` typed wrappers, honest badge vocabulary from the Field State tab |

## 3. Data model

Two tables (migration `0008_scenario_domain`); lineage and versioning are **not** separate
tables — see §5.

### `scenarios`

| Group | Columns | Notes |
|---|---|---|
| Identity | `id`, `field_id` (FK CASCADE), `name`, `description` | tenant resolved via field → farm → organization |
| Type & status | `scenario_type` (5-value CHECK), `scenario_status` (8-value CHECK), `lineage_kind` (`root/revision/branch`), `scenario_version` | type↔evidence binding CHECK (C2) |
| Parent state pin | `parent_field_state_id` (FK **RESTRICT**), `parent_snapshot_checksum`, `boundary_version` | checksum + boundary copied BY VALUE at creation |
| Lineage | `parent_scenario_id` (FK RESTRICT, nullable) | one self-FK covers revisions and branches |
| Configuration | `configuration_schema_version`, `canonical_configuration` (JSONB), `configuration_checksum` | checksum excludes name/description/UI metadata |
| Scope | `period_start`, `period_end` (CHECK order), `timezone` | temporal scope as real columns for DB integrity |
| Evidence | `evidence_classification` (CHECK 3 values), `assumption_metadata` (JSONB) | C2 at the database level |
| Lifecycle | `validation_summary` (latest result copy), `finalized_at` (CHECK present when finalized), `idempotency_key` + partial-unique `(field_id, idempotency_key)` | frozen by trigger after finalization |
| Provenance | `created_by`, `created_at`, `updated_at` | `created_by` excluded from checksum (provenance, not content) |

### `scenario_validation_records`

Immutable, append-only: `scenario_id` (FK CASCADE), `scenario_version`, `validation_rule_version`,
`validation_status` (CHECK against the 8-value result vocabulary), `validation_result` (full
document: findings, missing inputs, unsupported dimensions), `configuration_checksum`,
`created_by`, `created_at`. Never updated or deleted.

## 4. Immutability enforcement (layered)

1. **Service transitions** — documented legal-transition table; finalized/archived rows reject
   PATCH/DELETE/validate/finalize with 409 `SCENARIO_IMMUTABLE`.
2. **Database trigger** `enforce_scenario_immutability` (BEFORE UPDATE) — when
   `scenario_status IN ('finalized','archived')` every content column is compared to its old
   value; any difference aborts the statement. Only `finalized → archived` (and bookkeeping
   `updated_at`) is permitted; archived is terminal. Verified by test: even raw SQL tampering
   raises.
3. **CHECK constraints** — type↔evidence binding; unavailable types (`climate_projection`,
   `weather_forecast`) can never reach `valid/conditionally_valid/finalized`;
   `finalized_at` NOT NULL when finalized; `period_end >= period_start`.
4. **Reference protection** — `parent_field_state_id` FK RESTRICT (referenced state cannot be
   deleted; also blocks field deletion through the chain); `parent_scenario_id` FK RESTRICT.
5. **By-value pins** — parent checksum + boundary version copied at creation; later parent-side
   changes cannot silently redefine a historical scenario reference.

## 5. Versioning & lineage (why no extra tables)

- **A version IS a row**: `POST /scenarios/{id}/versions` (finalized parents only) creates a
  new draft row with `lineage_kind='revision'`, `scenario_version = parent+1`,
  `parent_scenario_id = parent`. The original row is untouched.
- **Branches** are created through the normal create endpoint with `parent_scenario_id` →
  `lineage_kind='branch'`, `scenario_version=1`.
- A separate `scenario_lineage` table would duplicate the self-FK (spec §5: do not
  over-normalize). A separate `scenario_configuration_versions` table would duplicate what
  every scenario row already stores (payload, canonical form, schema version, checksum,
  author, timestamp, parent) — spec §5 explicitly allows this.
- Archived scenarios remain in the lineage, retrievable and checksum-verifiable.

## 6. Validation architecture

`app/scenarios/validation.py` is **pure** — no FastAPI/SQLAlchemy imports. It consumes two
dataclass views (`ScenarioView`, `ParentStateView`) and returns a `ValidationResult` document.
The service layer builds the views from tenant-scoped reads (including parent-state checksum,
boundary-record existence and manifest synthetic counts) and persists an immutable record.

Result vocabulary and lifecycle mapping:

| Validation result | Lifecycle status |
|---|---|
| `valid` | VALID |
| `conditionally_valid`, `insufficient_parent_evidence` | CONDITIONALLY_VALID |
| `invalid`, `missing_reference`, `incompatible_period` | INVALID |
| `unsupported`, `not_implemented` | UNSUPPORTED |

Severity ladder inside findings: `error` (blocks validity) / `warning` (degrades to
conditionally_valid) / `info` (recorded limitation). All-synthetic parent evidence is a
**disclosure** (warning, `all_synthetic=true`), not a hard failure — the platform's demo
profile is synthetic by design; synthetic data must remain *visibly* synthetic, and it does.

## 7. Comparison contract

`GET /scenarios/{id}/compare?against={other}` — definition-level only: parent-state identity,
checksums, boundary versions, period overlap, evidence classes, canonical-configuration
structural diff (added/removed/changed leaf paths), changed-assumption paths, explicit
warnings for differing parents/boundaries/evidence classes/non-overlapping periods. The
response states explicitly that no simulated outputs exist to compare (M7.3 not implemented)
and no scores are fabricated.

## 8. What is deliberately absent

- No run/execute endpoint; no transformation code; no result tables.
- No forecast/projection acceptance (climate/forecast creation → 422
  `SCENARIO_TYPE_NOT_IMPLEMENTED` with the honest reason).
- No soil/management scenario dimensions (reported `not_implemented` with the M7.0 H-03
  reasons in payloads, taxonomy, capabilities and UI).
- No rate-limiting infra (documented in limitations), no cross-field baseline reference.

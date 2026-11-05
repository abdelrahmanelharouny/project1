# M7.7 — Digital Twin Integration & Validation

Status: **IMPLEMENTED & VERIFIED** (commit `5499df7c`, browser E2E verified).
View: `digital-twin-view-1.0` · Validation: `digital-twin-validation-1.0` · Migration: `0013_digital_twin`.

## 1. What it is

A **traceable field-level representation** connecting the implemented
capabilities into one coherent whole:

```
field identity + append-only boundary versions
  → immutable Field State snapshots (checksummed, manifest-by-value)
    → observations & provenance → M4 derived features
      → finalized scenarios (versioned, checksummed) → M7.3 executions
        → M7.4 sensitivity analyses
          → M7.5 scenario sets + robust rotation runs
            → M7.6 decision documents
              → persisted twin integrity validations
```

It is explicitly **not a decorative dashboard**: every section carries
artifact ids, statuses and checksums; validation re-verification is one call
away and persisted as immutable records.

## 2. Field-level view (`GET /fields/{field_id}/digital-twin`)

Read-only assembly (bounded lists), computed fresh per request:

- **`field_identity`** — field/farm, area, latest boundary version (append-only).
- **`field_states`** — total + newest snapshots with status, period, snapshot
  checksum, boundary version.
- **`observation_coverage`** — per variable: count, first/last observation,
  **freshness in days** (a data-age indicator, not a forecast).
- **`feature_runs`** — newest runs with engine versions + synthetic flag.
- **`scenarios`** — lineage tree: type, evidence classification, status,
  version, configuration checksum, parent link, executions with output
  checksums.
- **`sensitivity_analyses` / `robust_rotation` / `decision_documents`** —
  artifact counts and checksummed references.
- **`information_classes`** — census distinguishing **observed** observations
  vs **transformed** scenario-derived observations (never merged into the
  observation record) vs **calculated** feature values.
- **`capabilities`** — implemented capability matrix with **data readiness
  from actual row presence** (`ready` / `prerequisite_missing` /
  `not_implemented`).
- **`maturity`** — honest classification:
  `observational-analytical field twin (no forecasting)`; implemented
  capabilities vs an explicit not-implemented list (climate projections —
  M7.8 blocked until a validated provider exists; weather forecasts; crop
  yield prediction — no evidence basis; autonomous decisions — decision
  support only).

## 3. Validation walk (`POST .../digital-twin/validate`)

A **bounded** integrity walk that REUSES the existing per-artifact verifiers
(no verification logic duplicated) through per-artifact verdict adapters:

| Artifact | Verifier reused | Verdict flags |
|---|---|---|
| Field States (6 newest) | `field_state.verify_field_state` | checksum, manifest checksum, boundary row, referenced artifacts intact |
| Scenarios (8 newest) | `scenarios.verify_scenario` | configuration checksum, parent state, parent snapshot, boundary row, latest validation match |
| Executions (6 newest result-bearing) | `scenario_execution.verify_execution` | output checksum, definition checksum, parent snapshot, manifest match |
| Sensitivity analyses (6 newest) | `sensitivity.verify_analysis` | output checksum, source run, parent snapshot, manifest, reference reproduction |
| Robust runs (6 newest) | `robust_rotation.verify_run` | member pins + strategy checksums |
| Decision documents (6 newest) | `decision.verify_comparison` | document checksum + source checksums |

Outcomes: `consistent` (analytical artifacts exist, none failed),
`inconsistent` (any finding), `no_artifacts` (no result-bearing analytical
artifacts). The report is checksummed and **persisted append-only**
(`digital_twin_validations`, migration 0013; partial-unique idempotency key).
`GET .../validations` returns the history.

## 4. Frontend

The **Digital Twin** tab renders stat cards (field/states/information
classes/maturity), the coverage & freshness table, the checksummed lineage
tree, the capability/readiness grid with the honest not-implemented list, and
the validation history with a one-click **Validate now** action. Verified at
desktop and 390 px; sticky footer behaviour preserved.

## 5. Tests & verification evidence

- `tests/integration/test_digital_twin.py` (9): unified view sections,
  information-class census, capability/maturity honesty (no forecasting,
  yield, or autonomy claims), empty-field honesty, consistent-stack
  validation (all six artifact classes checked), `no_artifacts` semantics,
  history listing, tenant isolation, migration head.
- Browser E2E: twin view on the demo field (2190 observed / 7280 transformed /
  198 calculated), "Validate now" → `Twin consistent — 19/19 artifacts
  verified`, desktop + 390 px screenshots, sticky footer verified both short
  and tall pages, no console errors.

## 6. Known limitations

- The view is computed per request (no materialized twin snapshot); bounded
  lists keep it fast (documented caps in `app/digital_twin/contracts.py`).
- The validation walk is bounded to the newest artifacts per class (bounds
  stated in the report's `bounds_note`).
- No sensor streaming, no live state, no control loops — none are claimed.

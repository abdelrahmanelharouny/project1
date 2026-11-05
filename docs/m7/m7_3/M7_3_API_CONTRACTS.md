# M7.3 — API Contracts

Base path: `/api/v1`. All endpoints require authentication (`Authorization: Bearer …`); every resource is
resolved through the owning field's farm before any data is returned — client-supplied tenant claims are
never trusted. Errors use the platform's structured envelope
(`{"error": {"code", "message", "details": [...], "request_id"}}`).

---

## 1. `POST /scenarios/{scenario_id}/executions`

Execute (or idempotently replay) a finalized, executable scenario. Synchronous — the response is the
completed run.

**Request body** (optional): `{"idempotency_key": "client-chosen-key"}`

**Responses**

| Status | Meaning |
|---|---|
| 200 | run completed (or replayed) — body = `ScenarioExecutionRun` |
| 404 | scenario not found (or not visible to this tenant) |
| 409 | `SCENARIO_NOT_FINALIZED` / `SCENARIO_TYPE_NOT_EXECUTABLE` / `SCENARIO_CHECKSUM_MISMATCH` / `PARENT_STATE_MISSING` / `PARENT_STATE_CHECKSUM_MISMATCH` |
| 422 | `SCENARIO_EXECUTION_BLOCKED` — details carry per-dimension findings (`unsupported_transformation`, `no_supported_transformation`) |
| 401 | unauthenticated |

**Run payload (abridged)**

```json
{
  "run_id": "uuid",
  "scenario_id": "uuid", "scenario_version": 1,
  "parent_field_state_id": "uuid",
  "parent_snapshot_checksum": "sha256…",
  "scenario_configuration_checksum": "sha256…",
  "transformation_engine_version": "scenario-transform-1.0.0",
  "feature_engine_version": "feature-engine-1.0.0",
  "feature_catalog_version": "featurespec-2026.11.2-m6a",
  "input_fingerprint": "sha256…",
  "run_status": "completed_with_limitations",
  "aggregation_levels": ["daily", "monthly", "seasonal"],
  "output_checksum": "sha256…",
  "transformed_observation_count": 1464,
  "derived_feature_count": 1639,
  "warnings": ["Scenario execution is a derived hypothetical calculation …", "…"],
  "not_evaluated_reasons": {"reference_et0_total_monthly": "Reference ET0 is an observed input …"},
  "resource_constraints": {"water_allocation_multiplier": 0.7},
  "execution_configuration": { "…": "canonical document, see contracts" },
  "evidence_note": "An execution is a derived hypothetical calculation. …"
}
```

## 2. `GET /scenarios/{scenario_id}/executions?run_status=`

Execution history for one scenario (newest first). `run_status` filters by one of the five statuses.
Response: `{"scenario_id", "items": [ScenarioExecutionRun], "note"}`.

## 3. `GET /scenario-executions/{run_id}`

Single run detail — same payload as §1. 404 when the run does not exist or belongs to another tenant.

## 4. `GET /scenario-executions/{run_id}/features?evidence_status=&feature_code=`

Derived feature rows, ordered by (feature_code, aggregation_level, period_label).
`evidence_status` ∈ {`scenario_recalculated`, `not_affected`, `not_evaluated`}.

Response: `{"run_id", "items": [ScenarioDerivedFeature], "count"}`. Each item carries baseline/scenario/
difference/percent values (percent omitted when baseline is NULL or 0), quality/coverage, and the full
`uncertainty_metadata` (reason for excluded roles; source uncertainty; engine provenance for recalculated rows).

## 5. `GET /scenario-executions/{run_id}/observations?variable_code=&limit=&offset=`

Derived (transformed) observations, ordered by (variable_code, period_start, source id).
`limit` 1–1000 (default 200), `offset` ≥ 0.

Response: `{"run_id", "items": [ScenarioDerivedObservation], "count", "limit", "offset",
"total_transformed", "note"}`. Every item carries `source_observation_id`, `baseline_value`,
`transformed_value`, `transformation_code`, `transformation_parameter`, `evidence_class`
(`scenario_derived_transformed` | `synthetic_test`), `source_evidence_class`, `quality_status`.
422 on out-of-range pagination.

## 6. `GET /scenario-executions/{run_id}/compare`

Baseline-vs-scenario comparison document:

```json
{
  "run_id": "uuid",
  "run_status": "completed_with_limitations",
  "output_checksum": "sha256…",
  "summary": {
    "recalculated_comparisons": 1632,
    "changed_values": 1241,
    "unchanged_values": 391,
    "not_affected_features": 2,
    "not_evaluated_features": 5
  },
  "rows": ["… ScenarioDerivedFeature items …"],
  "note": "Comparison is between two in-process engine passes over the SAME window …"
}
```

No simulated-output difference is ever fabricated for excluded features; incompatible baselines simply have
no percent (or difference) value.

## 7. `POST /scenario-executions/{run_id}/verify`

Independent integrity re-check. Response:

```json
{
  "run_id": "uuid",
  "run_status": "completed_with_limitations",
  "output_checksum_valid": true,
  "expected_output_checksum": "sha256…",
  "stored_output_checksum": "sha256…",
  "scenario_definition_checksum_valid": true,
  "parent_snapshot_intact": true,
  "manifest_checksum_matches_run": true,
  "verified_at": "ISO-8601",
  "note": "Verification recomputes the execution checksum from persisted derived artifacts …"
}
```

Verification recomputes the output checksum **from the persisted derived rows** (canonical serialization with
6-decimal float stability) and re-checks the scenario-definition and parent pins. It confirms integrity and
reproducibility of the hypothetical calculation — never that transformed values are observations.

## 8. Idempotency & concurrency semantics (all POST endpoints)

- Deterministic replay: same scientific inputs ⇒ same `input_fingerprint` ⇒ the same run is returned.
- Client-keyed replay: repeated `idempotency_key` (per scenario) returns the original run.
- Concurrent identical requests: serialized by the fingerprint UNIQUE index — one run is created, the loser
  receives the winner's run.
- Changed inputs (assumption, parent pin, engine version, window, levels) ⇒ new fingerprint ⇒ **new run**;
  historical runs are immutable and remain verifiable.

## 9. Updated `GET /scenarios/capabilities` (honesty payload brought to M7.3 truth)

The M7.2-era payload stated `execution.scenario_execution = "not_implemented"` ("M7.3 does not exist in this
repository"). With M7.3 implemented, that statement had become false while still being rendered in the
workspace — an honesty defect. The payload now reads:

```json
{
  "execution": {
    "scenario_execution": "implemented_for_supported_types",
    "reason": "M7.3 executes environmental stress transformations (uniform temperature delta, precipitation multiplier) for FINALIZED user_defined_stress / historical_perturbation scenarios against their immutable parent Field State. Outputs are scenario-derived hypothetical calculations — never observations. Climate projections, weather forecasts, soil and management scenario simulation remain unavailable, and reference ET0 is never recalculated or reused under modified temperature."
  },
  "digital_twin_level": "Level 1 — Historical Digital Profile (not predictive)"
}
```

Unchanged (still honestly unavailable): `capabilities[]` marks `climate_projection` and `weather_forecast`
as `not_implemented` with their M7.2 reasons; `dimensions` keeps `soil`, `management`,
`climate_projection`, `weather_forecast` unavailable. The workspace renders all five §13.F unavailable
states: the four payload entries above plus the ET0 statement inside `execution.reason` (with per-feature
`not_evaluated` reasons on every run).

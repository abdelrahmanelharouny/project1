# M7.2 — Configuration Contracts

**Status:** implemented (`app/scenarios/contracts.py`; `scenario-config-1.0`)

## 1. Principles

1. **No unrestricted JSON.** Each implemented scenario type has a strictly typed Pydantic
   model; unknown keys are forbidden (`extra="forbid"` on every model). A generic JSON
   document is never the primary validation contract.
2. **Units in names.** Every adjustment field carries its unit
   (`temperature_delta_c`, `precipitation_delta_mm`, `*_multiplier`, `*_shift_days`).
3. **Explicit nulls.** Optional adjustment dimensions are always present in the canonical
   document; unset means explicit `null` — never an omitted key, never a silent zero.
4. **Versioned.** The document carries `schema_version` and `type`; every stored scenario pins
   the version it was created with, so historical checksums stay verifiable.
5. **Frozen models** (`ConfigDict(frozen=True)`) — configurations are immutable value objects.

## 2. Discriminated contracts

```
HistoricalObservedConfig      type: Literal["historical_observed"]
    parent_field_state_id: str (UUID)
    (no assumptions — any attempt fails)

_HypotheticalConfigBase
    parent_field_state_id: str (UUID)
    period: PeriodRange {start, end}
    adjustments: AdjustmentSet (≥1 dimension; conflict rules)
    assumption_metadata: AssumptionMetadata {origin, status: Literal["hypothetical"], description}

HistoricalPerturbationConfig  type: Literal["historical_perturbation"]
UserDefinedStressConfig       type: Literal["user_defined_stress"]
```

`climate_projection` / `weather_forecast` intentionally have **no** model; creation requests
are rejected at the API with 422 `SCENARIO_TYPE_NOT_IMPLEMENTED` and the honest reason.

## 3. Validation coverage (spec §6)

| Rule | Where enforced |
|---|---|
| Units | field names + bounds constants; surfaced in UI labels |
| Numeric boundaries | Pydantic `ge/le` per dimension (bounds table in the taxonomy doc) |
| Date intervals | service parses `period.start/end` (ISO date → UTC midnight, M7.1 idiom); DB CHECK `period_end >= period_start`; engine flags zero/partial overlap with the parent |
| Field scope | parent state must belong to the same field (`PARENT_STATE_MISMATCH`) |
| Variable support | `extra="forbid"` → unknown adjustment dimensions rejected |
| Scenario-type compatibility | discriminated Literal types; version endpoint keeps the type (`SCENARIO_TYPE_MISMATCH`) |
| Parent snapshot references | `PARENT_STATE_MISMATCH` / `PARENT_STATE_NOT_SUCCEEDED` / `PARENT_STATE_NOT_VERIFIED`; parent checksum + boundary copied by value |
| Tenant ownership | parent state resolved through the field's farm organization server-side; engine cross-checks (`parent_state_cross_tenant`) |
| Missing dimensions | engine lists parent dimensions with status ≠ available in `unsupported_dimensions` |
| Conflicting adjustments | `AdjustmentSet` model validators (multiplier vs delta mm; seasonal vs rainfall shift) |

**A valid configuration is not a simulated result** — validation never implies execution.

## 4. Canonical serialization & checksum

```python
canonicalize_configuration(model)  # model_dump(mode="json") + explicit-null adjustment dict
scenario_checksum_payload(...)     # {configuration_schema_version, scenario_type,
                                   #  canonical_configuration, parent_field_state_id,
                                   #  parent_snapshot_checksum, boundary_version, timezone}
compute_scenario_checksum(...)     # SHA-256 over canonical JSON (sorted keys, tight separators)
```

- Stable key ordering: `sort_keys=True` at serialization time (shared `canonical_json`).
- Stable date/timestamp formatting: ISO-8601, UTC (`+00:00`), dates as UTC midnights.
- Consistent floating-point representation: JSON number semantics (2.0 stays `2.0`).
- Explicit unit fields: embedded in key names.
- Schema-version inclusion: inside the document and in the checksum payload.

**Checksum scope (scientific only):** type, schema version, canonical configuration, parent
state id, parent snapshot checksum, boundary version, timezone. Excluded as UI/provenance
metadata: scenario `name`, `description`, `idempotency_key`, `created_by`, timestamps —
tested: renaming a scenario does not change its checksum; changing an assumption does.

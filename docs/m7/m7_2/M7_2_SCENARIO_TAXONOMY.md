# M7.2 — Scenario Taxonomy

**Status:** implemented (`app/scenarios/contracts.py`; taxonomy version `scenario-taxonomy-1.0`)
**Governing condition (M7.0 C2):** scenario types are never presented as equivalent evidence.

The taxonomy is versioned. Every type carries a static capability record: display name,
capability (`implemented` / `not_implemented`), bound evidence classification, description and,
for unavailable types, the honest reason.

## 1. Type registry

| Type | Capability | Evidence class | Summary |
|---|---|---|---|
| `historical_observed` | implemented | **observed** | References an immutable Field State and represents its recorded historical/reference condition. Carries no assumptions; never a future prediction. |
| `historical_perturbation` | implemented | **hypothetical** | Hypothetical adjustments (temperature, precipitation, seasonal timing, water availability) applied to a historical environmental reference. Configuration-only in M7.2. |
| `user_defined_stress` | implemented | **hypothetical** | Manually configured hypothetical stress experiment (reduced allocation, temperature increase, precipitation reduction, rainfall-period shift). Every input labelled a user assumption. |
| `climate_projection` | **not_implemented** | not_available | Contract placeholder for future projection datasets. Reason: no sourced, licensed projection dataset or methodology exists (M7.0 C5). Creation rejected. |
| `weather_forecast` | **not_implemented** | not_available | Contract placeholder for future forecast data (issue time / validity time / horizon will be distinguished when a real provider exists). Creation rejected. |

## 2. §4.1 Historical Observed — preserved properties

A historical observed scenario stores, by value and by reference:

- parent Field State id (FK RESTRICT) + the state's checksum copied verbatim
  (`parent_snapshot_checksum`) — the reference is pinned, not live;
- boundary version copied from the state (`boundary_version`);
- the parent state's observation manifest remains available through the state (the scenario
  does not duplicate it);
- the state's reference period inherited verbatim (scenario `period` = parent period);
- evidence classification `observed` (DB CHECK binds it to the type);
- source and product versions remain available through the parent state's `source_versions`.

Any attempt to attach adjustments/assumptions is rejected by the Pydantic contract
(`extra="forbid"`, no such fields) and by the validation engine
(`observed_scenario_with_assumptions`). The type must never claim to be a future prediction:
payloads carry the label "Observed historical condition".

## 3. §4.2 / §4.3 Hypothetical types — adjustment dimensions

Both hypothetical types share one strictly-typed `AdjustmentSet` (units embedded in names;
unset dimensions serialize as explicit `null`):

| Dimension | Bounds | Unit |
|---|---|---|
| `temperature_delta_c` | −20 … +20 | °C |
| `precipitation_multiplier` | 0 … 3 | ratio (1 = unchanged) |
| `precipitation_delta_mm` | −500 … +500 | mm (conflicts with multiplier) |
| `water_allocation_multiplier` | 0 … 2 | ratio |
| `seasonal_timing_shift_days` | −180 … +180 | days (conflicts with rainfall-period shift) |
| `rainfall_period_shift_days` | −180 … +180 | days |

Rules enforced by the contract:
- at least one adjustment is required (an empty set defines no scenario);
- conflicting representations of the same physical dimension are rejected;
- `assumption_metadata.status` is pinned to the literal `hypothetical` — user assumptions can
  never claim to be measured or forecast data (M7.2 spec §2 rules 5–6);
- unknown keys are forbidden everywhere (`extra="forbid"`), so an unmodelled dimension (e.g.
  a soil dimension that does not exist in this repository) is a contract violation, never a
  silent ignore.

In M7.2 the configuration is **stored and validated only** — observations are never modified
and no transformed environmental features are computed (M7.3 does not exist).

## 4. §4.4 Climate Projection — prepared, not claimed

The type exists in the taxonomy with capability `not_implemented` and `evidence_classification
= not_available`. There is **no configuration model** (there is nothing honest to validate
yet). A database CHECK (`ck_scenario_unavailable_types_never_finalized`) additionally makes it
impossible for such rows to reach `valid/conditionally_valid/finalized` even if one existed.
No invented projection records, no synthetic projections, no executable capability exposed:
`GET /scenarios/capabilities` reports `execution.scenario_execution = "not_implemented"`.

## 5. §4.5 Weather Forecast — separate type, same honesty

Distinct from climate projection so that the future forecast semantics (issue time, validity
time, horizon) have their own contract slot. Until a real provider exists: unavailable, no
forecast-derived evidence, and hypothetical weather can never be displayed as forecast
evidence (assumption metadata is pinned to `hypothetical`; the capabilities endpoint states
the provider requirement).

## 6. §4.6 Soil and Management scenarios — explicitly unavailable

Both are reported as unavailable everywhere they can appear:

- taxonomy endpoint: `dimensions.soil` / `dimensions.management` with status `not_implemented`
  and the fixed M7.0 H-03 reasons ("M6B is not implemented in this repository…" / "M6C …");
- every scenario payload carries `unavailable_dimensions` with the same entries;
- the validation engine appends them to `unsupported_dimensions` for every scenario;
- the UI shows a four-tile "Platform scenario capabilities" panel (soil, management, climate
  projection, weather forecast), each with its reason verbatim.

No fabricated soil/management dimensions, no replacement records, ever.

## 7. Lifecycle vocabulary

Statuses: `draft → validation_pending → valid | conditionally_valid | invalid → finalized →
archived`, plus `unsupported` (unreachable for creation-rejected types; defined for
completeness). Legal transitions (enforced in the service; finalized/archived frozen by the
DB trigger):

| From | To |
|---|---|
| draft | validation_pending, archived |
| validation_pending | valid, conditionally_valid, invalid, unsupported |
| valid | finalized, archived, draft (edit reset), validation_pending (re-validation) |
| conditionally_valid | finalized, archived, draft (edit reset), validation_pending (re-validation) |
| invalid | draft (after PATCH), archived |
| finalized | archived |
| archived | — (terminal) |
| unsupported | — (terminal) |

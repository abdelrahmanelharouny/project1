# M7.3 — Temporal & Variable Compatibility

**Status:** Implemented in `app/scenario_execution/transformations.py` (variable eligibility) and
`app/scenario_execution/dependency_graph.py` (feature eligibility).

---

## 1. Principle: native temporal support is sacred

Every observation is transformed **at its native temporal support** (`time_support`: `daily`, `pentadal`,
`monthly`, …). The transformation layer never resamples, never infers daily values from monthly or pentad
totals, never disaggregates, and never merges supports. Timestamps and `period_start`/`period_end` are carried
over verbatim.

Downstream feature recalculation inherits the M4 engine's own support rules
(`build_daily_series` excludes non-`daily` supports with an explicit, counted exclusion). M7.3 therefore:

| Source support of a transformed variable | Transformation | Feature recalculation |
|---|---|---|
| `daily` | applied per observation | full: daily, monthly, seasonal features recomputed from transformed values |
| `pentadal` / `dekadal` | applied per period total | transformed values **stored and inspectable**; daily-resolution features (`daily_passthrough`, `dry_spell_max`) marked `not_evaluated` ("requires daily source support"); monthly/seasonal aggregation **from non-daily sources** is an engine limitation → `not_evaluated` with explicit reason |
| `monthly` | applied per monthly total | same as pentadal: values stored, aggregation-based features `not_evaluated` with explicit reason |
| other (`instant`, `hourly`, `annual`) | excluded from transformation; listed in run warnings | n/a |

This is the honest boundary of M7.3: the transformation arithmetic is support-agnostic (add/multiply are valid
on totals and means alike), but **feature recalculation from aggregated sources** would require extending the M4
engine's aggregation paths — deliberately out of scope ("do not duplicate formulas"; the engine is daily-first
by design and its exclusion behavior is disclosed, never silent).

**Daily metrics are never reconstructed from monthly data** — neither by transformation nor by recalculation.

## 2. Variable eligibility

### 2.1 Temperature delta (`temperature_delta_c`)

| Variable | Transformed? | Notes |
|---|---|---|
| `air_temperature_mean` | ✅ | additive shift |
| `air_temperature_max` | ✅ | additive shift (DTR preserved when paired with min) |
| `air_temperature_min` | ✅ | additive shift (DTR preserved when paired with max) |
| `reference_et0` | ❌ | **never** transformed (see §4) |
| anything else | ❌ | unaffected |

Unit gate: source unit must be a temperature unit (`degC` canonical; equivalent spellings accepted, no
conversion performed). Incompatible-unit observations are excluded and reported.

### 2.2 Precipitation multiplier (`precipitation_multiplier`)

| Variable | Transformed? | Notes |
|---|---|---|
| `precipitation` | ✅ | multiplicative scaling |
| `reference_et0` | ❌ | never (also dimensionally unrelated) |
| anything else | ❌ | unaffected |

Unit gate: source unit must be a water-depth unit (`mm` canonical family). Incompatible units are excluded and
reported.

## 3. Calendar and window consistency

- Timezone/hemisphere/calendar semantics are **reused verbatim from M4** (`app.features.calendar.resolve_timezone`;
  the parent state's `timezone` and calendar context) — no new calendar code.
- UTC timestamps remain stable; field-local day assignment is the engine's own (`fscal.assign_local_date`).
- The scenario execution window is exactly the scenario definition's `[period_start, period_end]`, which M7.2
  validation guarantees lies within the parent state period. **No silent extension**: the execution never pulls
  observations outside the window (the ±2-day engine margin used by ordinary runs is *not* applied — the
  scenario window is a hard boundary, so baseline and scenario always compare identical periods).
- Cross-year seasons: seasonal recomputation uses the same hemisphere as the parent environmental run
  (recorded in the state's calendar context / run request parameters), so season labels match baseline
  conventions.

## 4. ET0 and water-related safety (spec §7 — critical)

`reference_et0` is an **observed** input variable (FAO-56 reference ET0 published by the source product, e.g.
ERA5). M7.3 does **not** recalculate ET0 under modified temperature, because:

1. The M6A methodology computes ET0 from published observations — it has no temperature-only mode.
2. A physically defensible ET0 recalculation requires humidity, radiation and wind inputs whose scenario
   counterparts are not defined by a temperature delta (and their temporal/unit conventions would need
   separate validation).
3. No independent numerical test corpus for a scenario-ET0 method exists in this repository.

Consequences (all enforced and tested):

- `reference_et0` observations are **never** transformed.
- Features whose `required_variables` include `reference_et0` — `reference_et0_total_daily`,
  `reference_et0_total_monthly`, `reference_et0_total_seasonal`, `reference_et0_total_crop_season`,
  `water_balance_p_minus_et0_monthly` — are **excluded from the scenario feature set** and recorded as
  `not_evaluated` with reason: baseline ET0 is not valid under a modified-temperature scenario and M7.3 does
  not recalculate evaporative demand.
- Baseline ET0 feature values are never copied into scenario-derived feature rows.
- No scenario irrigation-demand or yield claim is produced anywhere in the execution path
  (water plans / rotation engines are not invoked).

## 5. `water_allocation_multiplier` — context, not weather

Per M7.3 spec §2, a configured `water_allocation_multiplier` is retained as a **resource-constraint
assumption** in the execution context (`execution_configuration.resource_constraints`) and surfaced in warnings.
It is never represented as a transformed weather observation and never reaches the feature engine.

## 6. Unsupported adjustment dimensions

| Configured dimension | Execution behavior |
|---|---|
| `precipitation_delta_mm` | **blocks execution** — `unsupported_transformation` finding (additive precipitation shift is not an M7.3 transformation) |
| `seasonal_timing_shift_days` | **blocks execution** — `unsupported_transformation` finding (timing shift would require re-dating observations, which M7.3 forbids) |
| `rainfall_period_shift_days` | **blocks execution** — same reason |
| `water_allocation_multiplier` | allowed as context (§5) |
| `temperature_delta_c` | supported transformation |
| `precipitation_multiplier` | supported transformation |

A scenario configuring **only** unsupported dimensions cannot execute (no-op executions are refused — a run
that transforms nothing would be indistinguishable from the baseline and scientifically meaningless).

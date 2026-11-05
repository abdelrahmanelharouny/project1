# M7.3 — Feature Dependency Graph

**Status:** Implemented in `app/scenario_execution/dependency_graph.py`.

---

## 1. Design rule

The registry is **derived from the versioned M4 feature catalog at runtime** — feature codes, required
variables, aggregation levels, strategies and thresholds are read from `app/features/catalog.py`
(`FEATURE_CATALOG_VERSION = "featurespec-2026.11.2-m6a"`). M7.3 introduces **no formulas and no second
implementation** of any feature; it only classifies how each catalog entry relates to each supported
transformation.

## 2. Classification axes

For every `FeatureSpec` the registry computes a `FeatureDependency` record:

| Field | Meaning |
|---|---|
| `feature_code` | catalog code |
| `required_variables` | verbatim from the spec |
| `aggregation_levels` | verbatim from the spec |
| `temperature_sensitive` | any required variable ∈ {`air_temperature_mean`, `air_temperature_min`, `air_temperature_max`} |
| `precipitation_sensitive` | required variables contain `precipitation` |
| `et0_dependent` | required variables contain `reference_et0` |
| `multi_variable` | more than one required variable |
| `execution_role` | `recalculate` / `exclude_et0` / `not_affected` (see §3) |
| `required_time_support` | `daily` for strategies operating on daily series (`daily_passthrough`, `count_days`, `dry_spell_max`, `accumulation`, `mean`, `anomaly*`, `cv_across_years` — all M4 strategies consume daily series) |
| `specification_version` | the pinned catalog version |

## 3. Execution roles

| Role | Applies to | Behavior in a scenario run |
|---|---|---|
| `recalculate` | features whose required variables are all transformed by the configured transformations (e.g. temperature-only features under a ΔT run; precipitation features under an M_p run) | recomputed by the M4 engine from the transformed observation set; baseline counterpart computed from the original set; difference recorded |
| `exclude_et0` | features requiring `reference_et0` (directly or via `water_balance_p_minus_et0_monthly` which also needs precipitation) | **never computed**; recorded `not_evaluated` with the ET0-safety reason |
| `not_affected` | features whose required variables are untouched by the configured transformations (e.g. `wind_speed_10m_mean_monthly`, `soil_moisture_surface_mean_monthly` under a temperature run) | **not computed** in the scenario pass; recorded `not_affected` with reason "source variables not affected by the configured transformations" — never fabricated, never silently missing |

Mixed features: a feature requiring BOTH a transformed and an untouched non-ET0 variable would be incoherent to
recompute (half-transformed inputs). The only such catalog entry is `water_balance_p_minus_et0_monthly`
(precipitation + reference_et0), which is already covered by the ET0 exclusion. Should future catalog entries
introduce other mixed combinations, the registry classifies them `not_affected`→`exclude_mixed_inputs` with an
explicit reason (fail-closed).

## 4. Derived registry (featurespec-2026.11.2-m6a)

### 4.1 Temperature-sensitive (`temperature_delta_c` runs)

| Feature | Levels | Variables |
|---|---|---|
| `air_temperature_mean_daily` | daily | air_temperature_mean |
| `air_temperature_max_daily` | daily | air_temperature_max |
| `air_temperature_min_daily` | daily | air_temperature_min |
| `air_temperature_mean_monthly` | monthly | air_temperature_mean |
| `air_temperature_max_mean_monthly` | monthly | air_temperature_max |
| `air_temperature_min_mean_monthly` | monthly | air_temperature_min |
| `hot_days_35c_count_monthly` | monthly, seasonal, crop_season | air_temperature_max |
| `frost_days_0c_count_monthly` | monthly | air_temperature_min |
| `tropical_nights_20c_count_monthly` | monthly | air_temperature_min |
| `air_temperature_mean_seasonal` | seasonal | air_temperature_mean |
| `air_temperature_anomaly_monthly` | monthly | air_temperature_mean |
| `air_temperature_mean_crop_season` | crop_season | air_temperature_mean |
| `hot_days_35c_count_crop_season` | crop_season | air_temperature_max |

### 4.2 Precipitation-sensitive (`precipitation_multiplier` runs)

| Feature | Levels | Variables |
|---|---|---|
| `precipitation_total_daily` | daily | precipitation |
| `precipitation_total_monthly` | monthly | precipitation |
| `dry_spell_max_days_monthly` | monthly, seasonal, crop_season | precipitation |
| `precipitation_anomaly_monthly` | monthly | precipitation |
| `precipitation_anomaly_z_monthly` | monthly | precipitation |
| `precipitation_total_seasonal` | seasonal | precipitation |
| `precipitation_variability_cv_seasonal` | seasonal | precipitation |
| `precipitation_total_crop_season` | crop_season | precipitation |
| `dry_spell_max_days_crop_season` | crop_season | precipitation |

Note: under a temperature-only run, precipitation features are `not_affected`; under a precipitation-only run,
temperature features are `not_affected`. Under combined runs both families recalculate.

### 4.3 ET0-dependent (`exclude_et0` — always, in every M7.3 run)

| Feature | Reason |
|---|---|
| `reference_et0_total_daily` | baseline ET0 not valid under modified temperature; no scenario ET0 method |
| `reference_et0_total_monthly` | same |
| `reference_et0_total_seasonal` | same |
| `reference_et0_total_crop_season` | same |
| `water_balance_p_minus_et0_monthly` | same (+ mixed transformed/untransformed inputs) |

### 4.4 Never affected by environmental transformations

| Feature | Variables |
|---|---|
| `soil_moisture_surface_mean_monthly` | soil_moisture_surface |
| `wind_speed_10m_mean_monthly` | wind_speed_10m |

## 5. Semantics preserved from M4

- `not_affected` is an explicit, reasoned status — the feature is neither fabricated nor silently dropped.
- The engine's own `not_evaluated` machinery (missing inputs, coverage shortfalls, excluded time supports,
  excluded quality statuses) continues to operate inside the scenario pass; its reasons are merged into the
  run's `not_evaluated_reasons` with the same codes as ordinary runs.
- Feature specifications remain versioned: every derived feature row stores
  `feature_specification_version = FEATURE_CATALOG_VERSION` and the run stores both engine and catalog versions.
- Threshold features (hot days, frost days, dry spells) reclassify strictly per their cited conventions
  (ETCCDI / WMO) applied to transformed values — thresholds themselves are never reinterpreted.

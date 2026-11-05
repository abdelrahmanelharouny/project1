# M7.3 — Environmental Transformation Methodology

**Status:** Implemented in `app/scenario_execution/transformations.py` (`TRANSFORMATION_ENGINE_VERSION = "scenario-transform-1.0.0"`)

---

## 1. Scope

Two and only two environmental transformations are implemented in M7.3:

1. **Uniform additive temperature shift** — degrees Celsius.
2. **Precipitation scaling by an explicit multiplier** — dimensionless ratio.

Both operate on **immutable historical observations** referenced by the parent Field State's observation
manifest. Both produce **scenario-derived values** stored in a separate derived layer
(`scenario_derived_observations`); the original `observations` table is never touched.

Methodological references (used as framing for delta-change / perturbation practice — **not** as evidence that a
user-defined perturbation is a climate projection):

- IPCC TG-GCIA (1994) Technical Guidelines for Assessing Climate Change Impacts and Adaptations — delta-change
  perturbation of observed baselines as an impact-assessment technique.
- IPCC AR6 WGI Chapter 10 — linkage between global-mean temperature change and regional/variable responses;
  why a uniform shift cannot represent changed variability or circulation.
- Climate Change in Australia (CCiA) — "delta change" / sensitivity-testing method: applying change factors to
  observed series to test system sensitivity.
- Canada's Climate Change Scenarios — the delta method: future = observed + Δ (temperature) or observed × ratio
  (precipitation).

All four sources describe the same family of techniques this milestone implements. None of them legitimizes
presenting the output as a projection of real future climate. The platform labels every scenario-derived value
as a **user-defined hypothetical sensitivity experiment**.

## 2. Temperature delta — exact semantics

```
T_scenario(t) = T_baseline(t) + ΔT          (ΔT in °C, contract bounds [-20.0, +20.0])
```

- Applies identically to every supported temperature statistic present in the source set:
  - `air_temperature_mean` → `air_temperature_mean + ΔT`
  - `air_temperature_max`  → `air_temperature_max  + ΔT`
  - `air_temperature_min`  → `air_temperature_min  + ΔT`
- Applying the same ΔT to Tmin and Tmax **preserves the baseline diurnal temperature range (DTR = Tmax − Tmin)**
  by construction. This is the classic uniform-shift property (CCiA delta change; IPCC TG-GCIA).
- If only one statistic exists in the source set, only that statistic is transformed; the others are listed as
  missing in the run's `not_evaluated` / warnings. **Missing Tmin/Tmax/Tmean are never manufactured.**
- The additive form is applied directly in °C. The delta is **never** applied multiplicatively and never
  converted through Kelvin or anomalies of a different reference period.
- Timestamp, interval (`period_start`/`period_end`), spatial support, source product lineage and quality flags
  of the source observation are preserved verbatim on the derived row.
- Units are validated **before** the adjustment: a source observation whose unit is not a recognized
  temperature unit (`degC`, `°C`, `celsius`) is not transformed — it is excluded and the exclusion is
  reported. (The canonical catalog unit is `degC`; the tolerant check exists only to avoid rejecting
  equivalent spellings, not to perform conversion.)

## 3. Precipitation multiplier — exact semantics

```
P_scenario(t) = P_baseline(t) × M_p         (M_p dimensionless, contract bounds [0.0, 3.0])
```

Validation and edge rules (all enforced, all tested):

| Rule | Behavior |
|---|---|
| Multiplier finite and non-negative | Guaranteed by the M7.2 contract (`ge=0.0`); the transformation layer re-validates defensively and raises on violation. Negative multipliers are **rejected**, never clamped. |
| Input precipitation valid | Only contract-valid, non-null values are transformed. |
| Unit compatibility | Source unit must be a length-of-water unit (`mm`, `millimeter(s)`, `mm/day`, `mm/hr` … tolerant prefix match on `mm`); anything else is excluded and reported, never converted. |
| No negative outputs | `max(P × M_p, 0.0)`; a negative *source* value is excluded as invalid (not clamped silently) and reported. |
| No overflow | Inputs are finite floats; results are checked with `math.isfinite`; non-finite results raise a transformation error (never persisted). |
| Missing input stays missing | `value IS NULL` (or quality `missing`) → the derived row carries `transformed_value = NULL`, **not zero**. |
| `M_p = 1` | Transformed values reproduce the original valid precipitation exactly (`x × 1.0 == x` in IEEE-754). |
| `M_p = 0` | Valid rainfall values become `0.0` under this **explicit hypothetical** transformation. Missing source values remain missing. This is a legitimate stress experiment (total rainfall suppression), clearly labelled as such. |
| Observation dates | Never altered — the derived row keeps the source `observed_at` / `period_start` / `period_end`. |

## 4. What these transformations preserve — and what they cannot represent

**Preserved by construction (uniform additive ΔT):**

- Temporal occurrence pattern of temperature; day-to-day sequencing.
- Diurnal temperature range when Tmin and Tmax are both present and shifted by the same ΔT.
- Temporal variance of temperature around the shifted mean (a uniform shift adds no variance).

**Preserved by construction (multiplier M_p):**

- The temporal occurrence pattern of recorded rainfall events (wet days stay wet, dry days stay dry).
- The rank ordering of event magnitudes.

**NOT representable — and therefore never claimed:**

- New rainfall events, new dry days, changed storm timing or sequences.
- A physically generated precipitation distribution; changed storm intensity distributions.
- New seasonal circulation patterns; changed monsoon/fronto-logical behavior.
- Changed temperature variability, changed DTR, or asymmetric Tmin/Tmax warming.
- Feedback effects (soil-moisture–temperature coupling, snow-albedo, land-use feedbacks).

**Threshold consequences:** count-style features computed from transformed values (e.g. hot days ≥ 35 °C, frost
days, WMO dry days < 1.0 mm) may legitimately change class after transformation — that is the point of a
sensitivity experiment. Their recomputation is deterministic from the transformed values; no new meteorology is
invented.

**Dry-environment caveat:** near-zero baseline precipitation makes multiplicative adjustments behave poorly in
a physical sense (0 mm × 2.0 = 0 mm). The engine applies the arithmetic honestly; the UI and docs disclose that
multiplicative dryness experiments cannot create water where none was observed. Users are directed to treat such
experiments as pure sensitivity tests.

**Never:** the output of either transformation is described as a validated future climate trajectory, a forecast,
or a projection. It is a deterministic, reversible, user-defined perturbation of recorded history.

## 5. Reversibility

Both transformations are bijective on their supported value domains:

- Temperature: `T_baseline = T_scenario − ΔT` (exact in floating-point only up to rounding; the derived row
  stores both baseline and transformed values, so no reversal computation is ever needed).
- Precipitation: `P_baseline = P_scenario / M_p` for `M_p > 0`; `M_p = 0` is not reversible and is stored as an
  explicit hypothetical zeroing.

Because both baseline and transformed values are persisted side by side, no consumer ever needs to invert a
transformation.

## 6. Numerical determinism

- Pure-Python float arithmetic (`value + delta`, `value * multiplier`) — deterministic for identical inputs on
  the same platform.
- Derived values are persisted as IEEE-754 doubles; the canonical output checksum serializes floats with a
  fixed 6-decimal representation (see PROVENANCE_AND_UNCERTAINTY), so checksums are stable across runs.
- No random number generation anywhere in the transformation or recalculation path.

## 7. Transformation codes

| Code | Meaning |
|---|---|
| `temperature_delta_c` | uniform additive shift applied to supported temperature statistics |
| `precipitation_multiplier` | ratio scaling applied to supported precipitation statistics |

Derived observation rows record `transformation_code` and the applied parameter
(`{"delta_c": 2.0}` / `{"multiplier": 0.8}`) so every value is independently auditable.

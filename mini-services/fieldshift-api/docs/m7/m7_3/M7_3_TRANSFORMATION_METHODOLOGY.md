# M7.3 Transformation Methodology

The two environmental transformations scenario executions may apply, and
the rules that make them scientifically defensible. Implementation:
`app/scenario_execution/transformations.py` (pure functions; variable scope
and unit handling at the top of the module).

## Supported transformations

1. **Uniform additive temperature shift** — a single offset in degrees
   Celsius applied to every temperature observation in the pinned manifest
   (`tmax`, `tmin`, `tavg` scope per the module's `TEMPERATURE_VARIABLES`).
2. **Precipitation scaling** — multiplication by an explicit non-negative
   multiplier over the precipitation variables (`PRECIPITATION_VARIABLES`).

Nothing else exists. Soil, management, climate-projection and
weather-forecast dimensions are unavailable and are reported as such —
never fabricated (the scenario validator refuses them with structured
findings).

## Design rules

- **Pure functions.** No database, no HTTP, no randomness, no clock.
  Identical inputs always produce identical outputs; the transformation
  engine version is stamped into every result.
- **Native temporal support preserved verbatim.** Observations are never
  resampled, re-dated or disaggregated — a daily record stays daily, a
  monthly record stays monthly, at its original timestamps.
- **Missing stays missing.** A null source value produces a null derived
  value; zero is never substituted.
- **Units are validated, not converted.** Incompatible units are excluded
  from transformation and reported by the caller; the module never guesses
  a conversion.
- **No mutation.** The original observation is untouched; each transformed
  record is a new derived row carrying `evidence=scenario_derived` (or
  `synthetic_test` for fixture data) and a reference to its source record.

## Why a shift/scale and nothing fancier

A uniform shift and a linear scale are the only perturbations whose effect
on the affected features can be recomputed honestly by re-running the
existing M4 feature engine over the transformed observation set. Anything
spatially or seasonally structured (grids, downscaled projections, forecast
ensembles) requires external datasets the platform does not ingest (see
`../../KNOWN_LIMITATIONS.md`), and per-cell fakes would violate the
platform's no-fabrication contract.

# CLIMATE_METHODOLOGY.md — Phase C methodology decisions (2026-10-31)

Companion to FEATURE_SCIENTIFIC_SPECIFICATIONS.md (the 26-feature table).
Every decision here is implemented and tested; deviations are in the backlog.

## 1. Baseline / climatology methodology (F-11)

WMO climatological normals are computed for standard reference periods
(e.g. 1991–2020) from dense complete records. CropTwist's run windows hold at
most ~10 years of provider coverage, so:

- `n_years < 5` → anomaly features are `not_evaluated` (reason in provenance).
- `5 ≤ n_years < 30` → `baseline_class = "short_record_exploratory"` — a
  limited exploratory reference, explicitly NOT a WMO normal.
- `n_years ≥ 30` → `baseline_class = "long_record_reference"` — still not
  claimed as a WMO standard normal (the reference period is not standardised;
  making that claim would require standard-period windows).
- Every baseline records `window_years`, `mean`, `sd`,
  `includes_evaluated_period: true` (the run's own years are part of the
  reference; this slightly shrinks anomaly magnitudes and is stated rather
  than hidden). Reference-period configuration (e.g. excluding the evaluated
  year, fixed WMO windows) is a backlog item (C-1) — it changes the meaning of
  existing values and must ship as a catalog version bump with provenance.

Leap days and changing coverage: leap-day months aggregate by local calendar
month (February 29 included when present); months below the coverage floor
never enter the baseline (engine skips `missing`/`insufficient_coverage`
drafts); a year with an insufficient month simply contributes no data point
for that month (distinct-year counting uses valid monthly values only).

## 2. Drought indicator evaluation (SPI / SPEI / soil-moisture anomalies)

| Indicator | Inputs | Reference period needed | Verdict for this stage |
|---|---|---|---|
| SPI | long precipitation record | commonly ≥ 30 y for stable distribution fits (gamma/pearson); 10 y yields unstable parameters | **NOT implemented** — statistically unsupportable with ≤10 y windows; backlog C-2 |
| SPEI | precipitation + ET0 (or Thornthwaite) | same as SPI | **NOT implemented** — same reason; ET0 series exist only for ERA5 products |
| Standardized Soil Moisture Anomaly | reanalysis soil moisture | ≥ 10–30 y; ERA5-Land 0–7 cm only (surface, not root-zone) | **NOT implemented** — layer too shallow to standardise meaningfully; documented in the source audit |
| P−ET0 climatic balance | monthly P, ET0 (same run) | per-month values; no distribution fit | implemented, labelled climatic balance — explicitly NOT an irrigation requirement and NOT an agricultural-drought index |
| Dry-spell statistics | daily P | per-period counts | implemented (WMO dry-day convention; gaps interrupt, never assumed dry) |
| Seasonal CV | seasonal totals across years | ≥ 5 years | implemented as variability description, not a drought classification |

Meteorological vs agricultural vs hydrological drought vs soil-water deficit
vs crop water stress are distinct concepts; the implemented features describe
the first only. Crop physiological stress remains unevaluated until crop-,
stage- and region-specific thresholds are locally validated (the knowledge
base carries none yet — see AGRONOMIC_KNOWLEDGE_AUDIT.md).

## 3. Temperature and heat analytics

- ETCCDI-style indices (FD0, TR20) and the generic hot-day index (tmax ≥ 35 °C)
  are implemented as meteorological conventions with citations; every value
  text repeats that they are NOT crop-specific stress thresholds.
- Consecutive heat periods (warm-spell duration) are NOT implemented — the
  ETCCDI WSDI definition requires per-day percentile grids from a reference
  climatology we cannot yet compute honestly (backlog C-3).
- Seasonal temperature variation: monthly means carry SEM; seasonal means are
  day-weighted when fed to rotation climate evidence (with an explicit warning
  when months are incomplete).

## 4. Seasonal and temporal aggregation

- Local calendar days via the documented midpoint rule; offset invariance and
  extreme-offset bucket shifts are property-tested (Auckland, Cairo DST).
- Meteorological seasons (DJF/MAM/JJA/SON) with hemisphere swap; DJF year-wrap
  labelled by majority-month year. Hemisphere is a COARSE proxy — the rotation
  planner therefore uses explicit user-defined season windows (crop_season),
  never hemisphere inference, for agronomic periods; equatorial/tropical
  rainfall-based seasons are supported only through those explicit windows
  (backlog C-4: knowledge-base crop calendars per region).
- Monthly product observations are never mixed into daily buckets (time-support
  exclusion is counted and warned).

## 5. Derived indicator semantics (guards against over-reading)

| Indicator | IS | is NOT |
|---|---|---|
| P − ET0 | monthly climatic water balance of the reference surface | crop irrigation requirement, soil water budget |
| Seasonal CV | variability of the observed window | forecast, drought classification |
| Precipitation anomaly | departure from the run-window baseline | WMO-normal departure |
| Hot days ≥ 35 °C | generic meteorological index | crop heat stress |
| Crop-season ETc (rotation) | FAO-56 single-Kc screening estimate (ADR-0017) | daily water balance (M7), irrigation scheduling |

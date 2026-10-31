# FEATURE_SCIENTIFIC_SPECIFICATIONS.md — all 26 features (Phase C)

Generated from the versioned catalog (`FEATURE_CATALOG_VERSION = featurespec-2026.11.1-d1`, engine `feature-engine-1.0.0`)
so this document cannot drift from the code. Every feature below is DATA in
`app/features/catalog.py`: unit, aggregation levels, required variables,
minimum-coverage policy and a cited formula reference. Thresholds used by count
indices are meteorological conventions (WMO dry day < 1.0 mm; ETCCDI-style
temperature indices) — never crop-specific agronomic thresholds. Crop-specific
stress interpretation remains deliberately unevaluated (see
CLIMATE_METHODOLOGY.md §5).

| Feature code | Name | Unit | Levels | Required variables | Min coverage | Strategy | Formula / reference (verbatim) |
|---|---|---|---|---|---|---|---|
| `air_temperature_anomaly_monthly` | Monthly air temperature anomaly | degC | monthly | air_temperature_mean | 0.80 | anomaly | value - baseline_mean over the same calendar month within the run window; requires >= 5 distinct years. |
| `air_temperature_max_daily` | Daily maximum air temperature | degC | daily | air_temperature_max | 1.00 | daily_passthrough | Identity: the daily maximum observation for the assigned local day. |
| `air_temperature_max_mean_monthly` | Monthly mean of daily maxima | degC | monthly | air_temperature_max | 0.80 | mean | Arithmetic mean of valid daily maximum values. |
| `air_temperature_mean_crop_season` | Crop-season mean air temperature | degC | crop_season | air_temperature_mean | 0.80 | mean | Arithmetic mean of valid daily values over the explicitly supplied season window. |
| `air_temperature_mean_daily` | Daily mean air temperature | degC | daily | air_temperature_mean | 1.00 | daily_passthrough | Identity: the daily mean observation for the assigned local day. |
| `air_temperature_mean_monthly` | Monthly mean air temperature | degC | monthly | air_temperature_mean | 0.80 | mean | Arithmetic mean of valid daily values. Uncertainty is the standard error of the mean (sample sd / sqrt(n)). |
| `air_temperature_mean_seasonal` | Seasonal mean air temperature | degC | seasonal | air_temperature_mean | 0.80 | mean | Arithmetic mean of valid daily values over the season window. |
| `air_temperature_min_daily` | Daily minimum air temperature | degC | daily | air_temperature_min | 1.00 | daily_passthrough | Identity: the daily minimum observation for the assigned local day. |
| `air_temperature_min_mean_monthly` | Monthly mean of daily minima | degC | monthly | air_temperature_min | 0.80 | mean | Arithmetic mean of valid daily minimum values. |
| `dry_spell_max_days_crop_season` | Crop-season longest dry spell | days | crop_season | precipitation | 0.80 | dry_spell_max | Maximum run of consecutive days with precipitation < 1.0 mm (WMO convention) within the supplied window. Data gaps interrupt the spell. |
| `dry_spell_max_days_monthly` | Longest dry spell | days | monthly, seasonal, crop_season | precipitation | 0.80 | dry_spell_max | Maximum length of consecutive days with daily precipitation < 1.0 mm (WMO dry-day convention). Dry day convention: a day is dry when daily precipitation < 1.0 mm (WMO convention). Days with missing precipitation INTERRUPT a dry spell (a data gap is never assumed dry); the spell restarts after the gap. |
| `frost_days_0c_count_monthly` | Frost days (tmin < 0 degC) | days | monthly | air_temperature_min | 0.80 | count_days | Count of valid days with daily tmin < 0.0 degC (ETCCDI FD0 frost-day index). |
| `hot_days_35c_count_crop_season` | Crop-season hot days (tmax >= 35 degC) | days | crop_season | air_temperature_max | 0.80 | count_days | Count of valid days with daily tmax >= 35.0 degC within the supplied window. Generic meteorological index — crop-specific stress interpretation remains unevaluated until the sourced crop knowledge base exists. |
| `hot_days_35c_count_monthly` | Hot days (tmax >= 35 degC) | days | monthly, seasonal, crop_season | air_temperature_max | 0.80 | count_days | Count of valid days with daily tmax >= 35.0 degC (ETCCDI-style temperature index family). This is a generic meteorological heat index, NOT a crop-specific stress threshold; crop thresholds require the versioned crop knowledge base and remain unevaluated. |
| `precipitation_anomaly_monthly` | Monthly precipitation anomaly | mm | monthly | precipitation | 0.90 | anomaly | value - baseline_mean, where the baseline is the mean of the same calendar month across the run window; requires >= 5 distinct years of that month, otherwise not evaluated. Baseline statistics (mean, sd, window years, baseline_class, includes_evaluated_period) are embedded in the value provenance. A short-record baseline is an exploratory reference, NOT a WMO climatological normal. |
| `precipitation_anomaly_z_monthly` | Monthly precipitation anomaly (standardized) | sd | monthly | precipitation | 0.90 | anomaly_z | (value - baseline_mean) / baseline_sd; requires >= 5 distinct years and sd > 0. Zero anomaly means 'equal to the baseline average', never 'no rainfall'. |
| `precipitation_total_crop_season` | Crop-season precipitation total | mm | crop_season | precipitation | 0.80 | accumulation | Sum of valid daily values over the explicitly supplied season window. Crop calendars from the knowledge base arrive in a later milestone; windows are recorded verbatim in run provenance. |
| `precipitation_total_daily` | Daily precipitation total | mm | daily | precipitation | 1.00 | daily_passthrough | Identity: the daily observation total for the assigned local day. Missing days stay missing (never zero). |
| `precipitation_total_monthly` | Monthly precipitation total | mm | monthly | precipitation | 0.90 | accumulation | Sum of valid daily values over the local month. Days below the coverage minimum leave the value NULL (never scaled up, never zero-filled). |
| `precipitation_total_seasonal` | Seasonal precipitation total | mm | seasonal | precipitation | 0.90 | accumulation | Sum of valid daily values over the season window. Below the coverage minimum the value stays NULL. |
| `precipitation_variability_cv_seasonal` | Seasonal precipitation variability (CV) | ratio | seasonal | precipitation | 0.90 | cv_across_years | sd/mean of the seasonal totals of one season (e.g. all 'JJA' years) within the run window; requires >= 5 distinct years of that season. A statistical variability measure over the observed window — not a forecast. |
| `reference_et0_total_monthly` | Monthly reference ET0 total | mm | monthly | reference_et0 | 0.90 | accumulation | Sum of valid daily reference ET0 values (FAO-56 reference surface). Requires an ET0-publishing source (ERA5 product). |
| `soil_moisture_surface_mean_monthly` | Monthly mean surface soil moisture | m3/m3 | monthly | soil_moisture_surface | 0.80 | mean | Arithmetic mean of valid daily volumetric soil moisture values. Modelled reanalysis estimate where the source is a reanalysis product. |
| `tropical_nights_20c_count_monthly` | Tropical nights (tmin > 20 degC) | days | monthly | air_temperature_min | 0.80 | count_days | Count of valid days with daily tmin > 20.0 degC (ETCCDI TR20 tropical-night index). |
| `water_balance_p_minus_et0_monthly` | Climatic water balance (P - ET0) | mm | monthly | precipitation, reference_et0 | 0.90 | difference | P - ET0 from the monthly totals of the SAME run and source selection. This is a CLIMATIC water balance indicator, not a crop water budget (that requires crop Kc, soil storage and allocation inputs — later milestones). |
| `wind_speed_10m_mean_monthly` | Monthly mean wind speed (10 m) | m/s | monthly | wind_speed_10m | 0.80 | mean | Arithmetic mean of valid daily wind speed values. |

## Cross-cutting computation policies (engine level)

1. **Missing ≠ zero** — accumulations sum valid days only; below the coverage
   minimum the value is NULL + `insufficient_coverage`; totals are never scaled
   up and gaps are never zero-filled (F-02 hardened: only contract-VALID
   observations contribute; `suspect`/`invalid` are excluded and reported).
2. **Temporal resolutions never mixed** — daily-bucket aggregation excludes
   non-daily time supports (counted in warnings); CHIRPS pentad/monthly totals
   therefore cannot silently enter daily sums.
3. **Calendar explicitness** — every value carries the calendar basis (farm
   timezone, hemisphere, `period_midpoint_local_date` assignment rule) in
   provenance; offset-invariance is property-tested.
4. **Baselines** — `>= 5` distinct years required, else `not_evaluated` with
   reason; every baseline records `n_years`, `window_years`, `baseline_class`
   (`short_record_exploratory` / `long_record_reference`),
   `includes_evaluated_period: true` (deepening F-11). No baseline is ever
   labelled a WMO climatological normal (see CLIMATE_METHODOLOGY.md).
5. **Uncertainty** — means carry the standard error of the mean; SoilGrids
   values carry the honest `mean_of_pixel_q05_q95_halfwidth_not_a_field_level_pi`
   label (deepening F-08).
6. **Reproducibility** — per-value sha256 checksums over inputs+counts+value;
   identical inputs → identical checksums (tested at engine and API level).

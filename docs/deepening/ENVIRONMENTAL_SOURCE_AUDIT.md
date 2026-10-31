# ENVIRONMENTAL_SOURCE_AUDIT.md — Phase B (verified against live-verified M3 behaviour + code)

## 1. Open-Meteo (ERA5 / ERA5-Land)

Verified product identity and matrix (M3 live-probed; re-verified by contract tests):

| Property | era5_land | era5 |
|---|---|---|
| Native resolution | ~11 km (0.1°) | ~28 km (0.25°) |
| Variables used | temperature mean/max, soil moisture VWN 0–7 cm, ET0 | + wind 10 m, precipitation |
| Timestamp basis | UTC hourly aggregated to daily | same |
| License | CC BY 4.0 (attribution surfaced verbatim) | CC BY 4.0 |

Semantics enforced by code:
- **Reanalysis ≠ station measurement** — `evidence_class="reanalysis_model_estimate"`,
  spatial support `grid_cell`, grid size recorded; never merged with other products.
- **Model-variable fail-fast** — a model that publishes none of the requested
  variables 422s; non-native variables are never requested (no silent mixing).
- **Null → missing** (`OPENMETEO_NULL` flag); archive-lag clamps with warnings.
- **Upstream dependency note** — ERA5-Land is forced by ERA5 meteorology;
  era5_land and era5 variables therefore share upstream ancestry and are not
  fully independent evidence (documented; source selection uses ONE product
  per variable per feature, so no blending occurs).

## 2. CHIRPS v3

- Products: daily / pentad / monthly, preliminary vs final — recorded in
  provenance and shown in UI; preliminary flagged (`CHIRPS_PRELIMINARY`).
- **Pentad calendar** verified against CHC: 1–5, 6–10, 11–15, 16–20, 21–25,
  26-end-of-month (variable length; tested incl. leap behaviour).
- **Dependency structure (deepening F-12)** — v3 daily fields may be produced
  by distributing pentad totals with daily ERA5/IMERG information:
  CHIRPS-daily and ERA5-daily are NOT independent; their agreement must not be
  read as validation. The engine's time-support separation prevents pentad
  totals entering daily buckets; the feature source-selection prevents
  double-counting overlapping precipitation products (one product per variable).
- **Extraction (deepening F-13)** — field mean uses fractional pixel-AREA
  weighting over valid cells (v2, numerically tested); sub-grid fields fall
  back to all-touched with `CHIRPS_SUBCELL_FIELD`; nodata accounting with
  `CHIRPS_LOW_CELL_COVERAGE` at <50% valid; all-nodata → structured error.
- Spatial support `polygon_average` @ ~5,566 m; evidence class
  `satellite_derived_estimate` — never presented as gauge measurement.

## 3. SoilGrids (ISRIC WCS)

- Live-verified coverage IDs `<family>_0-5cm_{mean,Q0.05,Q0.95}`; WCS 1.0.0
  EPSG:4326 GetCoverage; per-property `map` files; 250 m support.
- Units: soc dg/kg ÷10 → g/kg; pH ×10 ÷10; nitrogen cg/kg ÷100; bulk density
  cg/cm³ ÷100 — conversions recorded in metadata.
- **Concentration ≠ stock (Phase E)** — the system stores CONCENTRATION
  (g/kg). No stock (t/ha) is computed anywhere; computing stocks requires
  bulk density + depth integration + coarse fragments and is explicitly
  reserved for the soil-ledger milestone (backlog S-2).
- **Depth honesty** — only the 0–5 cm slice is ingested; NO root-zone profile
  is derived from it (candidate soil notes label the layer explicitly).
- **Uncertainty (deepening F-08)** — per-pixel quantiles are averaged; the
  value is labelled `mean_of_pixel_q05_q95_halfwidth_not_a_field_level_pi`
  with semantics text in metadata. It is NOT a field-level 90% PI: averaging
  per-pixel intervals neither accounts for spatial error correlation nor for
  within-field variability. A statistically defensible field-level interval
  requires modelling spatial covariance (backlog S-1).
- **Aggregation** — centre-inclusion mean of native cells (250 m grid: most
  agricultural fields span many cells); sub-grid fallback all-touched with
  `SOILGRIDS_SUBCELL_FIELD`; area weighting INVESTIGATED and deliberately not
  applied at 250 m (marginal benefit vs complexity — rationale in
  GLOBAL_SPATIAL_AND_CALENDAR_AUDIT.md §3.3).

## 4. Farmer-provided observations (CSV)

- Strict row validation (unknown variable, unit mismatch, duplicate dates, bad
  rows → per-row rejection with counts); blank → missing `FARMER_BLANK`;
  evidence class `farmer_reported_record` — NEVER treated as measured.
- Provenance: file sha256 + row number + `date_interpretation` metadata;
  timestamp rows rejected (local calendar-date basis).
- Idempotent via the observation natural key; template endpoint available.
- Units checked against the canonical variable catalog before ingestion.

## 5. Cross-source dependency map

```
ERA5 ──► ERA5-Land (forcing)          CHIRPS pentad ──► CHIRPS daily (RNL disaggregation, ERA5/IMERG-informed)
   │                                        │
   └────────┬───────────────────────────────┘
            ▼
  features: ONE product per variable per run (no blending); time supports never mixed
            ▼
  rotation climate evidence: month-of-year baseline from ONE feature run (labelled, not a forecast)
```

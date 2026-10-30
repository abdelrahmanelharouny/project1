# Data Dictionary — Evidence, Quality and Coverage

Three separate, never-merged dimensions (Master §16):

## Quality status (per observation)
`valid` · `suspect` · `invalid` · `missing` · `estimated` · `not_assessed`
- `missing` ⇔ `value IS NULL`. Zero is never a synonym for unknown.
- Enforced by CHECK constraint + provider contract tests.

## Coverage status (per variable per field, reported in the Data Passport)
Derived from observation counts and valid ratios: `observation_count`, `valid_count`, `missing_count`, `valid_ratio`, period start/end. Statuses like `complete_for_period` / `partial` / `outside_provider_coverage` become meaningful with real providers; the slice reports the underlying numbers plus period bounds and freshness (`freshness_days` from last retrieval).

## Evidence class (provenance of a value)
`direct_field_measurement` · `farmer_reported_record` · `station_observation` · `satellite_derived_estimate` · `reanalysis_model_estimate` · `global_soil_prediction` · `curated_agronomic_reference` · `synthetic_test_data`
- Synthetic provider rows always use `synthetic_test_data` + `is_synthetic=true`.
- The UI surfaces evidence class + SYNTHETIC badges on every relevant screen.

## Uncertainty
- Stored as `uncertainty_value` + `uncertainty_type` when the source provides one.
- If unavailable: NULL with type `unknown` — never zero, never invented probabilities.
- The Data Passport does not aggregate quality/coverage/freshness into a composite score (test-asserted).

## Analysis readiness (Feature A, first rules)

| Analysis | Requires | Status when inputs absent |
|---|---|---|
| climate_summary | air_temperature_mean ≥ 0.8 valid ratio, precipitation ≥ 0.8 | blocked, missing inputs listed |
| et0_only_summary | reference_et0 ≥ 0.8 | blocked |
| water_budget_screening | et0 + precipitation ≥ 0.8 **and** crop_water_parameters, soil_water_storage, water_allocation | blocked (later milestones) |
| rotation_optimization | crop_knowledge_base, crop_history, feature_runs, constraint_solver | blocked (Milestone 5/6) |
| soil_analysis | soil_samples | blocked (later milestone) |

# Data Dictionary — Variables (v2026.11.0-slice1)

Versioned canonical catalog (`app/data_platform/contracts/variables.py`, exposed at `GET /api/v1/variables` and inside `GET /api/v1/data/catalog`). Providers must normalize into these codes and units.

| Code | Name | Unit | Typical time support | Evidence class hint | Description |
|---|---|---|---|---|---|
| air_temperature_mean | Mean air temperature | degC | daily | reanalysis_model_estimate | Daily mean near-surface air temperature at 2 m. |
| air_temperature_min | Minimum air temperature | degC | daily | reanalysis_model_estimate | Daily minimum near-surface air temperature at 2 m. |
| air_temperature_max | Maximum air temperature | degC | daily | reanalysis_model_estimate | Daily maximum near-surface air temperature at 2 m. |
| precipitation | Precipitation depth | mm | daily | reanalysis_model_estimate | Daily total precipitation depth over the period. |
| reference_et0 | Reference evapotranspiration (ET0) | mm | daily | reanalysis_model_estimate | Daily ET0 for a grass reference surface. |
| soil_moisture_surface | Surface volumetric soil moisture | m3/m3 | daily | reanalysis_model_estimate | Volumetric water content, shallow surface layer (0–7 cm class). |
| wind_speed_2m | Wind speed at 2 m | m/s | daily | reanalysis_model_estimate | Daily mean wind speed at 2 m above ground. |

Rules:

- Units are SI-derived per Master §15 (degC for temperature; mm per defined period for depths; m3/m3 volumetric; m/s wind).
- A variable with no verified provider parameter stays unsupported — it appears as `missing` in the Data Passport rather than being approximated.
- Version bump policy: any change to codes/units/evidence hints bumps `DATA_DICTIONARY_VERSION`; observations keep the version they were ingested under via `processing_version` + dataset product version.

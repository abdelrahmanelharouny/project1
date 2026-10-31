# Data Dictionary — Variables (v2026.11.0-slice2)

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
| wind_speed_10m | Wind speed at 10 m | m/s | daily | reanalysis_model_estimate | Daily mean wind speed at 10 m (native height of gridded products; Open-Meteo converts km/h → m/s). |
| soil_ph | Soil pH (H2O, 0-5 cm) | pH | instant | global_soil_prediction | SoilGrids 2.0 predicted pH (native pH×10, converted on ingest). |
| soil_organic_carbon | Soil organic carbon (0-5 cm) | g/kg | instant | global_soil_prediction | SoilGrids 2.0 predicted SOC content. |
| soil_sand_content | Soil sand fraction (0-5 cm) | g/kg | instant | global_soil_prediction | SoilGrids 2.0 predicted sand content. |
| soil_clay_content | Soil clay fraction (0-5 cm) | g/kg | instant | global_soil_prediction | SoilGrids 2.0 predicted clay content. |
| soil_bulk_density | Soil bulk density (0-5 cm) | kg/dm3 | instant | global_soil_prediction | SoilGrids 2.0 predicted fine-earth bulk density (native cg/cm³ ÷ 100). |

Rules:

- Units are SI-derived per Master §15 (degC for temperature; mm per defined period for depths; m3/m3 volumetric; m/s wind).
- A variable with no verified provider parameter stays unsupported — it appears as `missing` in the Data Passport rather than being approximated.
- Version bump policy: any change to codes/units/evidence hints bumps `DATA_DICTIONARY_VERSION`; observations keep the version they were ingested under via `processing_version` + dataset product version.
- Slice-2 additions (v2026.11.0-slice2): `wind_speed_10m` (Open-Meteo) and the five SoilGrids 0-5 cm soil properties. Soil properties are instant-support static model snapshots with uncertainty — never time series and never lab measurements.
- Model availability: Open-Meteo's ERA5-Land publishes temperature + surface soil moisture only; derived precipitation/ET0 and wind require the `era5` product (see `MODEL_VARIABLES` in the provider).

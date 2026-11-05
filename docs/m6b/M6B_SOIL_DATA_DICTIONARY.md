# M6B — Soil Data Dictionary

**Status:** implemented (as-built)
**Source of truth:** `SOIL_VARIABLE_DICTIONARY` in
`mini-services/fieldshift-api/app/soil/contracts.py` (26 variables) — the API
refuses any `variable_code` outside this dictionary.
**Consumers:** CSV importer, measurement write path, profile/indicator read models,
assessment engine, `GET /api/v1/soil/methods` (exposes the dictionary verbatim).

---

## 1. Canonical soil variables (26)

| Code | Unit | Family | Description |
|---|---|---|---|
| `soil_sand_content` | g/kg | texture | Sand fraction content |
| `soil_silt_content` | g/kg | texture | Silt fraction content |
| `soil_clay_content` | g/kg | texture | Clay fraction content |
| `soil_texture_class` | class | texture | Texture class label (USDA) |
| `soil_bulk_density` | g/cm3 | bulk_density | Bulk density (basis recorded separately) |
| `soil_coarse_fragments` | vol% | bulk_density | Coarse-fragment volume fraction |
| `soil_particle_density` | g/cm3 | bulk_density | Particle density |
| `soil_ph` | pH | ph | Soil pH (medium + ratio recorded in method metadata) |
| `soil_electrical_conductivity` | dS/m | salinity | Electrical conductivity (extraction ratio recorded) |
| `soil_organic_carbon` | g/kg | carbon | Organic carbon concentration |
| `soil_organic_matter` | g/kg | carbon | Organic matter concentration |
| `soil_total_nitrogen` | g/kg | nitrogen | Total nitrogen concentration |
| `soil_nitrate_n` | mg/kg | nitrogen | Nitrate-N (extractable) |
| `soil_ammonium_n` | mg/kg | nitrogen | Ammonium-N (extractable) |
| `soil_available_phosphorus` | mg/kg | phosphorus | Available phosphorus (extractant recorded) |
| `soil_extractable_potassium` | mg/kg | potassium | Extractable potassium (extractant recorded) |
| `soil_cation_exchange_capacity` | cmol(+)/kg | cec | Cation exchange capacity |
| `soil_water_content_fc` | m3/m3 | water_retention | Water content at field capacity (potential recorded) |
| `soil_water_content_pwp` | m3/m3 | water_retention | Water content at permanent wilting point (potential recorded) |
| `soil_microbial_biomass_c` | mg/kg | biology | Microbial biomass carbon |
| `soil_microbial_biomass_n` | mg/kg | biology | Microbial biomass nitrogen |
| `soil_respiration` | mg CO2-C/kg/day | biology | Soil respiration (protocol recorded) |
| `soil_mineralizable_n` | mg/kg | biology | Potentially mineralizable nitrogen |
| `soil_earthworm_abundance` | count/m2 | biology | Earthworm abundance |
| `soil_enzyme_activity` | activity | biology | Enzyme activity (assay recorded) |
| `soil_particulate_organic_matter` | g/kg | biology | Particulate organic matter |

Notes: units in the dictionary are the CANONICAL units; the importer normalizes a
small declared set to them (e.g. `%` → `g/kg`, `ppm` → `mg/kg`, `kg/dm3` →
`g/cm3`, `mS/cm` → `dS/m`, `cmolc/kg` → `cmol(+)/kg`). OC→OM uses the van Bemmelen
factor 1.724 through the single sanctioned M6A function, disclosed wherever used.
Total vs extractable vs available nutrients are distinguished by variable + method,
never by interpretation.

## 2. Evidence-class vocabulary

Database CHECK (`ck_soil_measurement_evidence`, 8 values — the platform-wide
vocabulary):

| Value | Meaning |
|---|---|
| `direct_field_measurement` | measured on a physical sample (lab analysis of a field sample) |
| `farmer_reported_record` | farmer-reported value, not lab-verified |
| `station_observation` | sensor/station observation (vocabulary inheritance) |
| `satellite_derived_estimate` | remote-sensing estimate (vocabulary inheritance) |
| `reanalysis_model_estimate` | reanalysis/model estimate (vocabulary inheritance) |
| `global_soil_prediction` | SoilGrids-style mapped prediction |
| `curated_agronomic_reference` | reference-table value |
| `synthetic_test_data` | synthetic fixture, never agronomic evidence |

The measurement write path accepts 5 of these for soil rows
(`direct_field_measurement`, `farmer_reported_record`, `global_soil_prediction`,
`synthetic_test_data`, `curated_agronomic_reference`); the full 8 are kept in the
CHECK for vocabulary compatibility. Structural rule: `source_kind='soilgrids_profile'`
REQUIRES `evidence_class='global_soil_prediction'` (mapped ≠ measured, enforced at
write time, HTTP 422 otherwise).

## 3. Source-kind vocabulary (`ck_soil_measurement_source`)

| Value | Meaning |
|---|---|
| `lab_analysis` | laboratory analysis of a sample (default when `layer_id` is present) |
| `farmer_report` | farmer-reported measurement (default otherwise) |
| `soilgrids_profile` | SoilGrids multi-depth profile row |
| `synthetic_fixture` | synthetic demo/test data |

## 4. Quality-status vocabulary

- `soil_sampling_events.ck_soil_event_quality`: `valid` · `suspect` · `invalid` · `not_assessed`.
- `soil_measurements.ck_soil_measurement_quality`: `valid` · `suspect` · `invalid` ·
  `missing` · `estimated` · `not_assessed`.

## 5. Depth conventions (hard rules)

- Canonical unit: **centimetres**. Supported input units: `cm`, `mm`, `m`
  (unknown units are refused, never guessed). Original unit + values are preserved
  on every layer row.
- An interval is **[top_cm, bottom_cm)**; validation: finite, `top ≥ 0`,
  `bottom > top`, `bottom ≤ 300 cm` (`MAX_PLAUSIBLE_DEPTH_CM`).
- Standard SoilGrids/GlobalSoilMap intervals (0–5, 5–15, 15–30, 30–60, 60–100,
  100–200 cm) are informational only — lab depths are preserved verbatim and never
  snapped to a standard interval.
- Layer-set validation reports **overlaps** (aggregation REFUSED upstream, never
  deduplicated silently) and **gaps** (reported; block whole-profile totals while
  per-layer results remain evaluable).
- Depth-weighted aggregation uses thickness weighting over DISJOINT intervals only.

## 6. Derived quantities (never stored as measurements)

| Quantity | Unit | Rule |
|---|---|---|
| USDA texture class | class | `usda-texture-1.0.0`; silt derivation disclosed via `silt_basis` |
| Porosity | m³/m³ | `n = 1 − BD/PD`; assumed-PD outputs labelled with the 2.65 g/cm³ disclosure |
| Layer AWC | m³/m³, mm | `θFC − θWP`; mm = AWC × thickness_cm × 10 |
| Profile AWC | mm | sum over disjoint measured intervals; gaps labelled |
| SOC stock | Mg C/ha | `soc-stock-1.0.0` layer-wise formula; per-layer and profile totals with coverage labels |

Derived outputs are computed read-models (`/soil-indicators`, `/soc-stock-runs`
snapshots); they are not persisted as measurement rows, and they carry the engine
version that produced them.

## 7. Entity overview (detail in M6B_DATABASE_DESIGN.md)

`soil_sampling_events` → `soil_samples` (composite self-link) →
`soil_sample_layers` (the canonical depth-interval carrier) → `soil_measurements`
(variable rows with method identity, limits, qualifiers, uncertainty).
Registries: `soil_laboratories`, `soil_analytical_methods` (tenant-scoped, created
on demand). Ledger: `soil_management_events`. Nutrient domain:
`nutrient_products`, `nutrient_applications`, `nutrient_removals`. Immutable run
snapshots: `soc_stock_runs`, `nutrient_budget_runs`, `soil_assessment_runs`.
`soil_profiles` and `soil_indicators` are computed read-models, NOT tables.

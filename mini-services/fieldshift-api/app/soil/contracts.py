"""Soil Intelligence Engine (Milestone 6B) — pure decision core.

Follows the M5/M6A independence rule: no ORM, no HTTP, no I/O inside the
calculation modules. The DB bridge lives in `app.soil.service`; the API in
`app.api.v1.soil`.

Versioned surfaces:

- SOIL_ENGINE_VERSION      — the calculation engine (this package)
- SOIL_METHODS_VERSION     — the methodology catalog (classification systems,
  conversion functions, interpretation policies and their citations)
- SOC_STOCK_VERSION        — the FAO/IPCC SOC stock implementation
- NUTRIENT_BUDGET_VERSION  — the N/P/K budget implementation
- TEXTURE_CLASSIFIER_VERSION — the USDA texture triangle implementation

Honesty contract (inherits deepening + M6A rules): missing ≠ zero; analytically
incompatible measurements are never merged; mapped predictions stay distinct
from measured samples; a missing stock input refuses the stock (never a
partial formula); unknown flows are listed, never zero-filled; synthetic
evidence is labelled end-to-end.
"""

SOIL_ENGINE_VERSION = "soil-engine-1.0.0"
SOIL_METHODS_VERSION = "soil-methods-1.0.0"
SOC_STOCK_VERSION = "soc-stock-1.0.0"
NUTRIENT_BUDGET_VERSION = "nutrient-budget-1.0.0"
TEXTURE_CLASSIFIER_VERSION = "usda-texture-1.0.0"

# Canonical soil property variables (the soil measurement dictionary).
# Each entry: (variable_code, unit, property_family, description).
SOIL_VARIABLE_DICTIONARY: tuple[dict[str, str], ...] = (
    {"code": "soil_sand_content", "unit": "g/kg", "family": "texture", "description": "Sand fraction content"},
    {"code": "soil_silt_content", "unit": "g/kg", "family": "texture", "description": "Silt fraction content"},
    {"code": "soil_clay_content", "unit": "g/kg", "family": "texture", "description": "Clay fraction content"},
    {"code": "soil_texture_class", "unit": "class", "family": "texture", "description": "Texture class label (USDA)"},
    {"code": "soil_bulk_density", "unit": "g/cm3", "family": "bulk_density", "description": "Bulk density (basis recorded separately)"},
    {"code": "soil_coarse_fragments", "unit": "vol%", "family": "bulk_density", "description": "Coarse-fragment volume fraction"},
    {"code": "soil_particle_density", "unit": "g/cm3", "family": "bulk_density", "description": "Particle density"},
    {"code": "soil_ph", "unit": "pH", "family": "ph", "description": "Soil pH (medium + ratio recorded in method metadata)"},
    {"code": "soil_electrical_conductivity", "unit": "dS/m", "family": "salinity", "description": "Electrical conductivity (extraction ratio recorded)"},
    {"code": "soil_organic_carbon", "unit": "g/kg", "family": "carbon", "description": "Organic carbon concentration"},
    {"code": "soil_organic_matter", "unit": "g/kg", "family": "carbon", "description": "Organic matter concentration"},
    {"code": "soil_total_nitrogen", "unit": "g/kg", "family": "nitrogen", "description": "Total nitrogen concentration"},
    {"code": "soil_nitrate_n", "unit": "mg/kg", "family": "nitrogen", "description": "Nitrate-N (extractable)"},
    {"code": "soil_ammonium_n", "unit": "mg/kg", "family": "nitrogen", "description": "Ammonium-N (extractable)"},
    {"code": "soil_available_phosphorus", "unit": "mg/kg", "family": "phosphorus", "description": "Available phosphorus (extractant recorded)"},
    {"code": "soil_extractable_potassium", "unit": "mg/kg", "family": "potassium", "description": "Extractable potassium (extractant recorded)"},
    {"code": "soil_cation_exchange_capacity", "unit": "cmol(+)/kg", "family": "cec", "description": "Cation exchange capacity"},
    {"code": "soil_water_content_fc", "unit": "m3/m3", "family": "water_retention", "description": "Water content at field capacity (potential recorded)"},
    {"code": "soil_water_content_pwp", "unit": "m3/m3", "family": "water_retention", "description": "Water content at permanent wilting point (potential recorded)"},
    {"code": "soil_microbial_biomass_c", "unit": "mg/kg", "family": "biology", "description": "Microbial biomass carbon"},
    {"code": "soil_microbial_biomass_n", "unit": "mg/kg", "family": "biology", "description": "Microbial biomass nitrogen"},
    {"code": "soil_respiration", "unit": "mg CO2-C/kg/day", "family": "biology", "description": "Soil respiration (protocol recorded)"},
    {"code": "soil_mineralizable_n", "unit": "mg/kg", "family": "biology", "description": "Potentially mineralizable nitrogen"},
    {"code": "soil_earthworm_abundance", "unit": "count/m2", "family": "biology", "description": "Earthworm abundance"},
    {"code": "soil_enzyme_activity", "unit": "activity", "family": "biology", "description": "Enzyme activity (assay recorded)"},
    {"code": "soil_particulate_organic_matter", "unit": "g/kg", "family": "biology", "description": "Particulate organic matter"},
)


def soil_variable_definition(code: str) -> dict[str, str] | None:
    for entry in SOIL_VARIABLE_DICTIONARY:
        if entry["code"] == code:
            return dict(entry)
    return None


class SoilEngineError(ValueError):
    """A calculation cannot be produced from the supplied inputs (honest refusal)."""


class SoilValidationError(SoilEngineError):
    """Invalid input structure (depths, fractions, methods)."""

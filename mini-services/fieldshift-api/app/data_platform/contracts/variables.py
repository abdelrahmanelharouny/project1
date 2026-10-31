"""Canonical variable catalog (versioned data dictionary subset, Master §15).

Units follow the platform conventions: degrees Celsius for air temperature,
millimetres per period for precipitation/ET0, m3/m3 for volumetric soil moisture.
Every provider payload is normalized into these codes/units with conversion
metadata preserved in observation provenance.
"""

from typing import Any

from pydantic import BaseModel

DATA_DICTIONARY_VERSION = "2026.11.0-slice2"


class VariableDefinition(BaseModel):
    code: str
    name: str
    unit: str
    typical_time_support: str
    description: str
    evidence_class_hint: str  # expected evidence class when this variable is ingested


VARIABLE_CATALOG: dict[str, VariableDefinition] = {
    v.code: v
    for v in [
        VariableDefinition(
            code="air_temperature_mean",
            name="Mean air temperature",
            unit="degC",
            typical_time_support="daily",
            description="Daily mean near-surface air temperature at 2 m.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="air_temperature_min",
            name="Minimum air temperature",
            unit="degC",
            typical_time_support="daily",
            description="Daily minimum near-surface air temperature at 2 m.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="air_temperature_max",
            name="Maximum air temperature",
            unit="degC",
            typical_time_support="daily",
            description="Daily maximum near-surface air temperature at 2 m.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="precipitation",
            name="Precipitation depth",
            unit="mm",
            typical_time_support="daily",
            description="Daily total precipitation depth over the period.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="reference_et0",
            name="Reference evapotranspiration (ET0)",
            unit="mm",
            typical_time_support="daily",
            description="Daily reference evapotranspiration for a grass reference surface.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="soil_moisture_surface",
            name="Surface volumetric soil moisture",
            unit="m3/m3",
            typical_time_support="daily",
            description="Volumetric soil water content in the shallow surface layer (0-7 cm class).",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="wind_speed_2m",
            name="Wind speed at 2 m",
            unit="m/s",
            typical_time_support="daily",
            description="Daily mean wind speed at 2 m above ground.",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        VariableDefinition(
            code="wind_speed_10m",
            name="Wind speed at 10 m",
            unit="m/s",
            typical_time_support="daily",
            description="Daily mean wind speed at 10 m above ground (native height of most gridded products).",
            evidence_class_hint="reanalysis_model_estimate",
        ),
        # --- SoilGrids 2.0 predicted soil properties (0-5 cm, slice-2 depth) ---
        VariableDefinition(
            code="soil_ph",
            name="Soil pH (H2O, 0-5 cm)",
            unit="pH",
            typical_time_support="instant",
            description="Predicted soil pH in water for the 0-5 cm depth from SoilGrids (static snapshot).",
            evidence_class_hint="global_soil_prediction",
        ),
        VariableDefinition(
            code="soil_organic_carbon",
            name="Soil organic carbon (0-5 cm)",
            unit="g/kg",
            typical_time_support="instant",
            description="Predicted soil organic carbon content for the 0-5 cm depth from SoilGrids (static snapshot).",
            evidence_class_hint="global_soil_prediction",
        ),
        VariableDefinition(
            code="soil_sand_content",
            name="Soil sand fraction (0-5 cm)",
            unit="g/kg",
            typical_time_support="instant",
            description="Predicted sand content for the 0-5 cm depth from SoilGrids (static snapshot).",
            evidence_class_hint="global_soil_prediction",
        ),
        VariableDefinition(
            code="soil_clay_content",
            name="Soil clay fraction (0-5 cm)",
            unit="g/kg",
            typical_time_support="instant",
            description="Predicted clay content for the 0-5 cm depth from SoilGrids (static snapshot).",
            evidence_class_hint="global_soil_prediction",
        ),
        VariableDefinition(
            code="soil_bulk_density",
            name="Soil bulk density (0-5 cm)",
            unit="kg/dm3",
            typical_time_support="instant",
            description="Predicted fine-earth bulk density for the 0-5 cm depth from SoilGrids (static snapshot).",
            evidence_class_hint="global_soil_prediction",
        ),
    ]
}

SUPPORTED_VARIABLE_CODES = sorted(VARIABLE_CATALOG.keys())


def variable_definition(code: str) -> VariableDefinition | None:
    return VARIABLE_CATALOG.get(code)


def catalog_payload() -> list[dict[str, Any]]:
    return [v.model_dump() for v in VARIABLE_CATALOG.values()]

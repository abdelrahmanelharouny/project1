"""Soil Intelligence Engine (Milestone 6B) — package root.

Pure decision-core modules:
- contracts   — versions, variable dictionary, error types
- layers      — depth intervals, overlap/gap validation
- physical    — USDA texture polygons, bulk density, porosity, AWC
- chemistry   — pH/EC method-awareness policies (ADR-0023)
- soc         — FAO/IPCC SOC stocks, FD/ESM comparisons (ADR-0024)
- nutrients   — stoichiometric conversions + N/P/K budgets (ADR-0025)

The DB bridge (sampling events, samples, layers, measurements, import) is
`app.soil.service`; the API layer is `app.api.v1.soil`.
"""

from app.soil.contracts import (  # noqa: F401
    NUTRIENT_BUDGET_VERSION,
    SOC_STOCK_VERSION,
    SOIL_ENGINE_VERSION,
    SOIL_METHODS_VERSION,
    TEXTURE_CLASSIFIER_VERSION,
    SoilEngineError,
    SoilValidationError,
)

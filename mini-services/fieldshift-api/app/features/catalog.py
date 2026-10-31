"""Versioned feature definition catalog (Milestone 4).

Every feature is defined as DATA: code, unit, aggregation levels, required
variables, minimum coverage policy and a formula reference citing the
convention it follows. Thresholds used by count-style indicators are
meteorological conventions with citations (WMO dry day, ETCCDI temperature
indices) — they are NOT crop-specific agronomic thresholds. Crop-specific
heat stress stays unevaluated until the versioned, sourced crop knowledge
base arrives (Milestone 5); features that would need it are deliberately
absent from this catalog.

Units follow the canonical variable catalog: degC, mm, m/s, m3/m3.
"""

from dataclasses import dataclass, field

FEATURE_ENGINE_VERSION = "feature-engine-1.0.0"
FEATURE_CATALOG_VERSION = "featurespec-2026.11.0-m4"

# Minimum-coverage policy defaults. Accumulations (sums) demand near-full
# coverage because a missing day under-counts the total; means tolerate
# moderately incomplete months and carry a 'partial' quality flag instead.
COVERAGE_SUM = 0.9
COVERAGE_MEAN = 0.8

# Meteorological convention thresholds (cited, NOT crop-specific).
WMO_DRY_DAY_MM = 1.0
ETCCDI_HOT_DAY_DEGC = 35.0
ETCCDI_FROST_DEGC = 0.0
ETCCDI_TROPICAL_NIGHT_DEGC = 20.0

BASELINE_MIN_YEARS = 5


@dataclass(frozen=True)
class FeatureSpec:
    feature_code: str
    name: str
    description: str
    unit: str
    category: str
    aggregation_levels: tuple[str, ...]
    required_variables: tuple[str, ...]
    min_coverage_ratio: float
    formula_reference: str
    strategy: str  # engine strategy key
    strategy_params: dict = field(default_factory=dict)


def _wmo_dry_note() -> str:
    return (
        f"Dry day convention: a day is dry when daily precipitation < {WMO_DRY_DAY_MM} mm "
        "(WMO convention). Days with missing precipitation INTERRUPT a dry spell "
        "(a data gap is never assumed dry); the spell restarts after the gap."
    )


FEATURE_CATALOG: dict[str, FeatureSpec] = {
    s.feature_code: s
    for s in [
        # ------------------------------------------------------- daily level
        FeatureSpec(
            feature_code="precipitation_total_daily",
            name="Daily precipitation total",
            description="Daily precipitation depth assigned to the local calendar day.",
            unit="mm",
            category="climate",
            aggregation_levels=("daily",),
            required_variables=("precipitation",),
            min_coverage_ratio=1.0,
            formula_reference="Identity: the daily observation total for the assigned local day. Missing days stay missing (never zero).",
            strategy="daily_passthrough",
            strategy_params={"variable": "precipitation"},
        ),
        FeatureSpec(
            feature_code="air_temperature_mean_daily",
            name="Daily mean air temperature",
            description="Daily mean near-surface air temperature on the local calendar day.",
            unit="degC",
            category="climate",
            aggregation_levels=("daily",),
            required_variables=("air_temperature_mean",),
            min_coverage_ratio=1.0,
            formula_reference="Identity: the daily mean observation for the assigned local day.",
            strategy="daily_passthrough",
            strategy_params={"variable": "air_temperature_mean"},
        ),
        FeatureSpec(
            feature_code="air_temperature_max_daily",
            name="Daily maximum air temperature",
            description="Daily maximum near-surface air temperature on the local calendar day.",
            unit="degC",
            category="climate",
            aggregation_levels=("daily",),
            required_variables=("air_temperature_max",),
            min_coverage_ratio=1.0,
            formula_reference="Identity: the daily maximum observation for the assigned local day.",
            strategy="daily_passthrough",
            strategy_params={"variable": "air_temperature_max"},
        ),
        FeatureSpec(
            feature_code="air_temperature_min_daily",
            name="Daily minimum air temperature",
            description="Daily minimum near-surface air temperature on the local calendar day.",
            unit="degC",
            category="climate",
            aggregation_levels=("daily",),
            required_variables=("air_temperature_min",),
            min_coverage_ratio=1.0,
            formula_reference="Identity: the daily minimum observation for the assigned local day.",
            strategy="daily_passthrough",
            strategy_params={"variable": "air_temperature_min"},
        ),
        # ----------------------------------------------------- monthly level
        FeatureSpec(
            feature_code="precipitation_total_monthly",
            name="Monthly precipitation total",
            description="Accumulated precipitation over the local calendar month.",
            unit="mm",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference="Sum of valid daily values over the local month. Days below the coverage minimum leave the value NULL (never scaled up, never zero-filled).",
            strategy="accumulation",
            strategy_params={"variable": "precipitation"},
        ),
        FeatureSpec(
            feature_code="air_temperature_mean_monthly",
            name="Monthly mean air temperature",
            description="Mean of daily mean air temperatures over the local calendar month.",
            unit="degC",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_mean",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily values. Uncertainty is the standard error of the mean (sample sd / sqrt(n)).",
            strategy="mean",
            strategy_params={"variable": "air_temperature_mean"},
        ),
        FeatureSpec(
            feature_code="air_temperature_max_mean_monthly",
            name="Monthly mean of daily maxima",
            description="Mean of daily maximum air temperatures over the local calendar month.",
            unit="degC",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_max",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily maximum values.",
            strategy="mean",
            strategy_params={"variable": "air_temperature_max"},
        ),
        FeatureSpec(
            feature_code="air_temperature_min_mean_monthly",
            name="Monthly mean of daily minima",
            description="Mean of daily minimum air temperatures over the local calendar month.",
            unit="degC",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_min",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily minimum values.",
            strategy="mean",
            strategy_params={"variable": "air_temperature_min"},
        ),
        FeatureSpec(
            feature_code="hot_days_35c_count_monthly",
            name="Hot days (tmax >= 35 degC)",
            description="Count of days with daily maximum temperature >= 35 degC.",
            unit="days",
            category="risk",
            aggregation_levels=("monthly", "seasonal", "crop_season"),
            required_variables=("air_temperature_max",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference=(
                f"Count of valid days with daily tmax >= {ETCCDI_HOT_DAY_DEGC} degC "
                "(ETCCDI-style temperature index family). This is a generic meteorological "
                "heat index, NOT a crop-specific stress threshold; crop thresholds require "
                "the versioned crop knowledge base and remain unevaluated."
            ),
            strategy="count_days",
            strategy_params={"variable": "air_temperature_max", "op": ">=", "threshold": ETCCDI_HOT_DAY_DEGC},
        ),
        FeatureSpec(
            feature_code="frost_days_0c_count_monthly",
            name="Frost days (tmin < 0 degC)",
            description="Count of days with daily minimum temperature below 0 degC.",
            unit="days",
            category="risk",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_min",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference=f"Count of valid days with daily tmin < {ETCCDI_FROST_DEGC} degC (ETCCDI FD0 frost-day index).",
            strategy="count_days",
            strategy_params={"variable": "air_temperature_min", "op": "<", "threshold": ETCCDI_FROST_DEGC},
        ),
        FeatureSpec(
            feature_code="tropical_nights_20c_count_monthly",
            name="Tropical nights (tmin > 20 degC)",
            description="Count of days with daily minimum temperature above 20 degC.",
            unit="days",
            category="risk",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_min",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference=f"Count of valid days with daily tmin > {ETCCDI_TROPICAL_NIGHT_DEGC} degC (ETCCDI TR20 tropical-night index).",
            strategy="count_days",
            strategy_params={"variable": "air_temperature_min", "op": ">", "threshold": ETCCDI_TROPICAL_NIGHT_DEGC},
        ),
        FeatureSpec(
            feature_code="dry_spell_max_days_monthly",
            name="Longest dry spell",
            description="Longest run of consecutive dry days within the period.",
            unit="days",
            category="water",
            aggregation_levels=("monthly", "seasonal", "crop_season"),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference=(
                f"Maximum length of consecutive days with daily precipitation < {WMO_DRY_DAY_MM} mm "
                "(WMO dry-day convention). " + _wmo_dry_note()
            ),
            strategy="dry_spell_max",
            strategy_params={"variable": "precipitation", "dry_below_mm": WMO_DRY_DAY_MM},
        ),
        FeatureSpec(
            feature_code="reference_et0_total_monthly",
            name="Monthly reference ET0 total",
            description="Accumulated grass-reference evapotranspiration over the local calendar month.",
            unit="mm",
            category="water",
            aggregation_levels=("monthly",),
            required_variables=("reference_et0",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference="Sum of valid daily reference ET0 values (FAO-56 reference surface). Requires an ET0-publishing source (ERA5 product).",
            strategy="accumulation",
            strategy_params={"variable": "reference_et0"},
        ),
        FeatureSpec(
            feature_code="water_balance_p_minus_et0_monthly",
            name="Climatic water balance (P - ET0)",
            description="Monthly precipitation minus monthly reference ET0.",
            unit="mm",
            category="water",
            aggregation_levels=("monthly",),
            required_variables=("precipitation", "reference_et0"),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference="P - ET0 from the monthly totals of the SAME run and source selection. This is a CLIMATIC water balance indicator, not a crop water budget (that requires crop Kc, soil storage and allocation inputs — later milestones).",
            strategy="difference",
            strategy_params={"left": "precipitation_total_monthly", "right": "reference_et0_total_monthly"},
        ),
        FeatureSpec(
            feature_code="soil_moisture_surface_mean_monthly",
            name="Monthly mean surface soil moisture",
            description="Mean volumetric soil water content (0-7 cm class) over the local calendar month.",
            unit="m3/m3",
            category="soil",
            aggregation_levels=("monthly",),
            required_variables=("soil_moisture_surface",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily volumetric soil moisture values. Modelled reanalysis estimate where the source is a reanalysis product.",
            strategy="mean",
            strategy_params={"variable": "soil_moisture_surface"},
        ),
        FeatureSpec(
            feature_code="wind_speed_10m_mean_monthly",
            name="Monthly mean wind speed (10 m)",
            description="Mean daily wind speed at 10 m over the local calendar month.",
            unit="m/s",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("wind_speed_10m",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily wind speed values.",
            strategy="mean",
            strategy_params={"variable": "wind_speed_10m"},
        ),
        # ------------------------------------------------- baseline / anomaly
        FeatureSpec(
            feature_code="precipitation_anomaly_monthly",
            name="Monthly precipitation anomaly",
            description="Departure of monthly precipitation from the baseline climatology of the same calendar month.",
            unit="mm",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference=(
                "value - baseline_mean, where the baseline is the mean of the same calendar "
                f"month across the run window; requires >= {BASELINE_MIN_YEARS} distinct years of "
                "that month, otherwise not evaluated. Baseline statistics are embedded in the value provenance."
            ),
            strategy="anomaly",
            strategy_params={"base_feature": "precipitation_total_monthly"},
        ),
        FeatureSpec(
            feature_code="precipitation_anomaly_z_monthly",
            name="Monthly precipitation anomaly (standardized)",
            description="Standardized precipitation anomaly (z-score) against baseline month climatology.",
            unit="sd",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference=(
                "(value - baseline_mean) / baseline_sd; requires >= "
                f"{BASELINE_MIN_YEARS} distinct years and sd > 0. Zero anomaly means 'equal to "
                "the baseline average', never 'no rainfall'."
            ),
            strategy="anomaly_z",
            strategy_params={"base_feature": "precipitation_total_monthly"},
        ),
        FeatureSpec(
            feature_code="air_temperature_anomaly_monthly",
            name="Monthly air temperature anomaly",
            description="Departure of monthly mean temperature from the baseline climatology of the same calendar month.",
            unit="degC",
            category="climate",
            aggregation_levels=("monthly",),
            required_variables=("air_temperature_mean",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference=(
                "value - baseline_mean over the same calendar month within the run window; "
                f"requires >= {BASELINE_MIN_YEARS} distinct years."
            ),
            strategy="anomaly",
            strategy_params={"base_feature": "air_temperature_mean_monthly"},
        ),
        # --------------------------------------------------- seasonal level
        FeatureSpec(
            feature_code="precipitation_total_seasonal",
            name="Seasonal precipitation total",
            description="Accumulated precipitation over the meteorological season of the configured hemisphere.",
            unit="mm",
            category="climate",
            aggregation_levels=("seasonal",),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference="Sum of valid daily values over the season window. Below the coverage minimum the value stays NULL.",
            strategy="accumulation",
            strategy_params={"variable": "precipitation"},
        ),
        FeatureSpec(
            feature_code="air_temperature_mean_seasonal",
            name="Seasonal mean air temperature",
            description="Mean of daily mean air temperatures over the meteorological season.",
            unit="degC",
            category="climate",
            aggregation_levels=("seasonal",),
            required_variables=("air_temperature_mean",),
            min_coverage_ratio=COVERAGE_MEAN,
            formula_reference="Arithmetic mean of valid daily values over the season window.",
            strategy="mean",
            strategy_params={"variable": "air_temperature_mean"},
        ),
        FeatureSpec(
            feature_code="precipitation_variability_cv_seasonal",
            name="Seasonal precipitation variability (CV)",
            description="Coefficient of variation of seasonal precipitation totals across the years of the run window.",
            unit="ratio",
            category="climate",
            aggregation_levels=("seasonal",),
            required_variables=("precipitation",),
            min_coverage_ratio=COVERAGE_SUM,
            formula_reference=(
                "sd/mean of the seasonal totals of one season (e.g. all 'JJA' years) within the "
                f"run window; requires >= {BASELINE_MIN_YEARS} distinct years of that season. "
                "A statistical variability measure over the observed window — not a forecast."
            ),
            strategy="cv_across_years",
            strategy_params={"base_feature": "precipitation_total_seasonal"},
        ),
        # ------------------------------------------------ crop-season level
        FeatureSpec(
            feature_code="precipitation_total_crop_season",
            name="Crop-season precipitation total",
            description="Accumulated precipitation over a user-defined crop-season window.",
            unit="mm",
            category="water",
            aggregation_levels=("crop_season",),
            required_variables=("precipitation",),
            min_coverage_ratio=0.8,
            formula_reference="Sum of valid daily values over the explicitly supplied season window. Crop calendars from the knowledge base arrive in a later milestone; windows are recorded verbatim in run provenance.",
            strategy="accumulation",
            strategy_params={"variable": "precipitation"},
        ),
        FeatureSpec(
            feature_code="air_temperature_mean_crop_season",
            name="Crop-season mean air temperature",
            description="Mean of daily mean air temperatures over a user-defined crop-season window.",
            unit="degC",
            category="climate",
            aggregation_levels=("crop_season",),
            required_variables=("air_temperature_mean",),
            min_coverage_ratio=0.8,
            formula_reference="Arithmetic mean of valid daily values over the explicitly supplied season window.",
            strategy="mean",
            strategy_params={"variable": "air_temperature_mean"},
        ),
        FeatureSpec(
            feature_code="dry_spell_max_days_crop_season",
            name="Crop-season longest dry spell",
            description="Longest run of consecutive dry days within a user-defined crop-season window.",
            unit="days",
            category="water",
            aggregation_levels=("crop_season",),
            required_variables=("precipitation",),
            min_coverage_ratio=0.8,
            formula_reference="Maximum run of consecutive days with precipitation < 1.0 mm (WMO convention) within the supplied window. Data gaps interrupt the spell.",
            strategy="dry_spell_max",
            strategy_params={"variable": "precipitation", "dry_below_mm": WMO_DRY_DAY_MM},
        ),
        FeatureSpec(
            feature_code="hot_days_35c_count_crop_season",
            name="Crop-season hot days (tmax >= 35 degC)",
            description="Count of days with daily maximum temperature >= 35 degC within a user-defined crop-season window.",
            unit="days",
            category="risk",
            aggregation_levels=("crop_season",),
            required_variables=("air_temperature_max",),
            min_coverage_ratio=0.8,
            formula_reference=(
                f"Count of valid days with daily tmax >= {ETCCDI_HOT_DAY_DEGC} degC within the "
                "supplied window. Generic meteorological index — crop-specific stress "
                "interpretation remains unevaluated until the sourced crop knowledge base exists."
            ),
            strategy="count_days",
            strategy_params={"variable": "air_temperature_max", "op": ">=", "threshold": ETCCDI_HOT_DAY_DEGC},
        ),
    ]
}

FEATURE_CODES = sorted(FEATURE_CATALOG.keys())

STRATEGY_CODES = sorted({s.strategy for s in FEATURE_CATALOG.values()})


def feature_spec(code: str) -> FeatureSpec | None:
    return FEATURE_CATALOG.get(code)


def catalog_payload() -> list[dict]:
    return [
        {
            "feature_code": s.feature_code,
            "name": s.name,
            "description": s.description,
            "unit": s.unit,
            "category": s.category,
            "aggregation_levels": list(s.aggregation_levels),
            "required_variables": list(s.required_variables),
            "min_coverage_ratio": s.min_coverage_ratio,
            "formula_reference": s.formula_reference,
            "strategy": s.strategy,
            "definition_version": FEATURE_CATALOG_VERSION,
        }
        for s in FEATURE_CATALOG.values()
    ]

"""A7 numeric consistency: supported claims, rounding tolerance, unit
conversions, unsupported-value rejection, boilerplate ignoring."""

from __future__ import annotations

from app.intelligence.numeric_guard import (
    collect_reference_values,
    extract_claims,
    validate_numbers,
)


def _evidence() -> dict:
    return {
        "field": {"id": "f1", "name": "North Field", "area_ha": 12.5},
        "climate": {
            "source": {"kind": "feature_run", "id": "r1"},
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "metrics": [
                {"code": "precipitation_sum_seasonal", "value": 320.5, "unit": "mm",
                 "aggregation_level": "seasonal", "period": "2025"},
                {"code": "hot_days_35c_count_monthly", "value": 34, "unit": "days",
                 "aggregation_level": "monthly", "period": "2025-07"},
            ],
        },
        "water": {
            "source": {"kind": "water_plan", "id": "wp-1"},
            "nir_mm": 420.5, "gir_mm": 561.0, "water_allocation_m3": 90000.0,
            "deficit_window_count": 1,
            "first_deficit_window": {"kind": "root_zone_stress", "days": 15,
                                     "max_dr_mm": 42.5, "deficit_m3": None},
        },
        "soil": {
            "nutrient_budget": {"source": {"kind": "nutrient_budget_run", "id": "nb"},
                                "cumulative_balance_kg_ha": {"N": -42.5}, "seasons_evaluable": 2},
            "soc_stock": {"source": {"kind": "soc_stock_run", "id": "soc"},
                          "stock_Mg_C_ha": 22.4},
        },
        "data_gaps": [],
    }


def test_collect_references_covers_pack():
    refs = collect_reference_values(_evidence())
    values = [r.value for r in refs]
    assert 320.5 in values and 420.5 in values and 90000.0 in values
    assert 22.4 in values and -42.5 in values


def test_supported_claims_pass():
    answer = (
        "Your seasonal rainfall was 320.5 mm and net irrigation requirement "
        "420.5 mm; the water plan shows a 15-day root-zone stress window "
        "peaking at 42.5 mm depletion. SOC stock is 22.4 Mg C/ha."
    )
    report = validate_numbers(answer, _evidence())
    assert not report.unsupported
    assert report.supported
    assert not report.material_mismatch


def test_rounding_tolerance():
    answer = "Seasonal rainfall was about 320.55 mm this year."
    report = validate_numbers(answer, _evidence())
    assert not report.unsupported


def test_unsupported_number_rejected():
    answer = "Your field needs exactly 1337.0 mm of irrigation this season."
    report = validate_numbers(answer, _evidence())
    assert report.material_mismatch
    assert report.unsupported[0].value == 1337.0


def test_unit_conversion_mm_cm():
    answer = "The stress window peaked at 4.25 cm of depletion."
    report = validate_numbers(answer, _evidence())
    assert not report.unsupported  # 4.25 cm == 42.5 mm


def test_equal_numeric_value_in_wrong_dimension_is_rejected():
    report = validate_numbers(
        "The water depth is exactly 42.5 kg/ha.", _evidence()
    )
    assert report.material_mismatch
    assert any(claim.unit == "kg/ha" for claim in report.unsupported)


def test_mass_per_area_conversion_uses_correct_factor():
    report = validate_numbers(
        "The N balance is -0.0425 Mg/ha.", _evidence()
    )
    assert not report.unsupported  # -0.0425 Mg/ha == -42.5 kg/ha


def test_unit_conversion_temperature():
    evidence = _evidence()
    evidence["climate"]["metrics"].append(
        {"code": "temperature_2m_mean_monthly", "value": 35.0, "unit": "degC",
         "aggregation_level": "monthly", "period": "2025-07"}
    )
    report = validate_numbers("July averaged 95 °F.", evidence)
    assert not report.unsupported  # 95 °F == 35 °C
    report = validate_numbers("July averaged 35 °C.", evidence)
    assert not report.unsupported


def test_percent_fraction_both_directions():
    evidence = _evidence()
    evidence["management"] = {
        "soil_cover": {"protective_cover_fraction": 0.34, "days_protective_cover": 124,
                       "days_known_bare": 200, "days_unknown": 41,
                       "longest_bare_interval_days": 78}
    }
    report = validate_numbers("Protective cover covered 34% of the year.", evidence)
    assert not report.unsupported
    report = validate_numbers("The protective fraction is 0.34.", evidence)
    assert not report.unsupported


def test_thousands_separator_and_currency_free_numbers():
    answer = "Your allocation is 90,000 m3 for the season."
    report = validate_numbers(answer, _evidence())
    assert not report.unsupported


def test_boilerplate_numbers_ignored():
    answer = "There are 3 steps: 1) check the plan, 2) verify 2025 data, 3) re-run."
    report = validate_numbers(answer, _evidence())
    assert report.ignored, "enumeration numbers should be ignored, not flagged"
    assert not report.unsupported


def test_anomaly_z_values_supported():
    anomalies = [{"kind": "anomaly", "metric": "precipitation_sum_monthly",
                  "value": 200.0, "baseline_mean": 41.0, "z": -2.35,
                  "direction": "below", "period": "2024-11"}]
    answer = "November rainfall was 200 mm, 2.35 sigma below its baseline of 41 mm."
    report = validate_numbers(answer, _evidence(), anomalies)
    assert not report.unsupported
    # Slightly rounded z must still pass (±0.15 tolerance).
    report = validate_numbers(
        "November rainfall was 200 mm, about 2.4 sigma below the baseline of 41 mm.",
        _evidence(), anomalies,
    )
    assert not report.unsupported


def test_extract_claims_units_and_negatives():
    claims = extract_claims("N balance is -42.5 kg/ha; rainfall 320.5 mm; 90,000 m3.")
    by_unit = {c.unit: c.value for c in claims}
    assert by_unit.get("kg/ha") == -42.5
    assert by_unit.get("mm") == 320.5
    assert by_unit.get("m3") == 90000.0

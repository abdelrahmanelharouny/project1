"""Golden evaluation cases (A11.1): deterministic fixtures per domain.

Each fixture specifies: input evidence (the exact RecommendationContext the
generators consume), expected recommendation behavior (severity ladder,
required evidence references, required numbers), and fallback behavior with
missing evidence. The context dicts are the SAME shape the live registry
builds — they exercise the real generator code paths, not mocks of them.
"""

from __future__ import annotations

from typing import Any

FIELD_A = {"id": "11111111-1111-1111-1111-111111111111", "name": "Eval Field", "area_ha": 12.5}

GOLDEN_CASES: list[dict[str, Any]] = [
    # ------------------------------------------------------------- climate
    {
        "case_id": "climate_dry_spell_advisory",
        "domain": "climate",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "climate": {
                    "source": {"kind": "feature_run", "id": "run-1"},
                    "period": {"start": "2025-01-01", "end": "2025-12-31"},
                    "is_synthetic": False,
                    "metrics": [
                        {"code": "dry_spell_max_days_monthly", "value": 18, "unit": "days",
                         "aggregation_level": "monthly", "period": "2025-04"},
                    ],
                },
                "data_gaps": ["water", "soil", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["advisory"],
            "required_evidence_labels": ["climate"],
            "required_title_fragments": ["dry spell"],
            "required_numbers": ["18"],
        },
        "missing_evidence_context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [],
        },
        "missing_expect": {
            "required_severities": ["info"],
            "required_title_fragments": ["No climate data"],
        },
    },
    {
        "case_id": "climate_hot_days_advisory",
        "domain": "climate",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "climate": {
                    "source": {"kind": "feature_run", "id": "run-2"},
                    "period": {"start": "2025-01-01", "end": "2025-12-31"},
                    "is_synthetic": False,
                    "metrics": [
                        {"code": "hot_days_35c_count_monthly", "value": 34, "unit": "days",
                         "aggregation_level": "monthly", "period": "2025-07"},
                    ],
                },
                "data_gaps": ["water", "soil", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["advisory"],
            "required_title_fragments": ["hot days"],
            "required_numbers": ["34"],
        },
    },
    {
        "case_id": "climate_seasonal_variation_is_not_anomaly",
        "domain": "climate",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "climate": {
                    "source": {"kind": "feature_run", "id": "run-seasonal"},
                    "period": {"start": "2025-01-01", "end": "2025-12-31"},
                    "is_synthetic": False,
                    "metrics": [],
                },
                "data_gaps": ["water", "soil", "rotation", "management"],
            },
            # A dry-season June against a whole-series baseline would look
            # "unusual" under the OLD cross-month screener; the seasonal-aware
            # one classifies it seasonal_variation, which is NOT advice.
            "anomalies": [
                {"kind": "seasonal_variation", "metric": "precipitation_sum_monthly",
                 "aggregation_level": "monthly", "value": 2.0, "baseline_mean": 55.0,
                 "z": -2.1, "direction": "below", "period": "2025-06", "detail": "seasonal"},
            ],
        },
        "expect": {
            "max_recs": 0,
        },
    },
    {
        "case_id": "climate_statistical_anomaly_is_advice",
        "domain": "climate",
        "context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [
                {"kind": "anomaly", "metric": "growing_season_length_monthly",
                 "aggregation_level": "monthly", "value": 42.0, "baseline_mean": 120.0,
                 "z": -2.4, "direction": "below", "period": "2025-02", "detail": "z anomaly"},
            ],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["advisory"],
            "required_evidence_labels": ["climate"],
        },
    },
    # --------------------------------------------------------------- water
    {
        "case_id": "water_allocation_shortfall_required",
        "domain": "water",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "water": {
                    "source": {"kind": "water_plan", "id": "wp-1"},
                    "seasons": ["2025"],
                    "crops": ["wheat"],
                    "nir_mm": 420.5,
                    "gir_mm": 561.0,
                    "water_allocation_m3": 90000.0,
                    "allocation_status": "deficit",
                    "deficit_window_count": 1,
                    "first_deficit_window": {
                        "season": "2025", "kind": "allocation_shortfall",
                        "start_date": "2025-11-01", "end_date": "2026-03-31",
                        "days": 150, "max_dr_mm": None, "deficit_m3": 15000.0,
                    },
                },
                "data_gaps": ["climate", "soil", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["required"],
            "required_evidence_labels": ["water"],
            "required_title_fragments": ["Water allocation shortfall"],
            "required_numbers": ["15,000"],
        },
        "missing_evidence_context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [],
        },
        "missing_expect": {
            "required_severities": ["info"],
            "required_title_fragments": ["No water plan"],
        },
    },
    {
        "case_id": "water_stress_window_timing_recommended",
        "domain": "water",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "water": {
                    "source": {"kind": "water_plan", "id": "wp-2"},
                    "seasons": ["2025"],
                    "crops": ["maize"],
                    "nir_mm": 310.0,
                    "gir_mm": 413.0,
                    "water_allocation_m3": 200000.0,
                    "allocation_status": "ok",
                    "deficit_window_count": 2,
                    "first_deficit_window": {
                        "season": "2025", "kind": "root_zone_stress",
                        "start_date": "2025-06-10", "end_date": "2025-06-25",
                        "days": 15, "max_dr_mm": 42.5, "deficit_m3": None,
                    },
                },
                "data_gaps": ["climate", "soil", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["recommended"],
            "required_title_fragments": ["root-zone stress window"],
            "required_numbers": ["42.5"],
        },
    },
    # ---------------------------------------------------------------- soil
    {
        "case_id": "soil_negative_nutrient_balance_recommended",
        "domain": "soil",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "soil": {
                    "nutrient_budget": {
                        "source": {"kind": "nutrient_budget_run", "id": "nb-1"},
                        "cumulative_balance_kg_ha": {"N": -42.5, "P": 3.0, "K": -10.0},
                        "seasons_evaluable": 2,
                    },
                },
                "data_gaps": ["climate", "water", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 2,
            "required_severities": ["recommended"],
            "required_evidence_labels": ["soil"],
            "required_title_fragments": ["N balance is negative", "K balance is negative"],
            "required_numbers": ["42.5"],
        },
        "missing_evidence_context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [],
        },
        "missing_expect": {
            "required_severities": ["info"],
            "required_title_fragments": ["No soil data"],
        },
    },
    {
        "case_id": "soil_low_soc_advisory",
        "domain": "soil",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "soil": {
                    "soc_stock": {
                        "source": {"kind": "soc_stock_run", "id": "soc-1"},
                        "stock_Mg_C_ha": 22.4,
                    },
                },
                "data_gaps": ["climate", "water", "rotation", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["advisory"],
            "required_title_fragments": ["SOC stock is low"],
            "required_numbers": ["22.4"],
        },
    },
    # ------------------------------------------------------------ rotation
    {
        "case_id": "rotation_planting_recommended",
        "domain": "rotation",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "rotation": {
                    "source": {"kind": "rotation_run", "id": "rr-1"},
                    "solver_status": "optimal",
                    "season_count": 2,
                    "strategy": {"id": "strat-1", "key": "balanced_v1", "kind": "optimized",
                                 "is_baseline": False},
                    "assignment": [
                        {"season": "2025", "crop": "wheat"},
                        {"season": "2026", "crop": "soybean"},
                    ],
                    "unevaluated_crop_seasons": 0,
                    "unevaluated_examples": [],
                },
                "data_gaps": ["climate", "water", "soil", "management"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 2,
            "required_severities": ["recommended"],
            "required_evidence_labels": ["rotation"],
            "required_title_fragments": ["Plant wheat in 2025", "Plant soybean in 2026"],
        },
        "missing_evidence_context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [],
        },
        "missing_expect": {
            "required_severities": ["info"],
            "required_title_fragments": ["No rotation run"],
        },
    },
    {
        "case_id": "rotation_baseline_strategy_not_recommended",
        "domain": "rotation",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "rotation": {
                    "source": {"kind": "rotation_run", "id": "rr-2"},
                    "solver_status": "optimal",
                    "season_count": 1,
                    "strategy": {"id": "strat-base", "key": "baseline", "kind": "baseline",
                                 "is_baseline": True},
                    "assignment": [{"season": "2025", "crop": "fallow"}],
                    "unevaluated_crop_seasons": 0,
                    "unevaluated_examples": [],
                },
                "data_gaps": ["climate", "water", "soil", "management"],
            },
            "anomalies": [],
        },
        "expect": {"max_recs": 0},
    },
    # ---------------------------------------------------------- management
    {
        "case_id": "management_low_cover_advisory",
        "domain": "management",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "management": {
                    "soil_cover": {
                        "window": {"start": "2025-01-01", "end": "2025-12-31", "days": 365},
                        "protective_cover_fraction": 0.34,
                        "days_protective_cover": 124,
                        "days_known_bare": 200,
                        "days_unknown": 41,
                        "longest_bare_interval_days": 78,
                    },
                },
                "data_gaps": ["climate", "water", "soil", "rotation"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["advisory"],
            "required_title_fragments": ["Protective cover is low"],
            "required_numbers": ["34"],
        },
        "missing_evidence_context": {
            "field": FIELD_A,
            "evidence": {"data_gaps": ["climate", "water", "soil", "rotation", "management"]},
            "anomalies": [],
        },
        "missing_expect": {
            "required_severities": ["info"],
            "required_title_fragments": ["No management data"],
        },
    },
    {
        "case_id": "management_erosion_not_evaluated_info",
        "domain": "management",
        "context": {
            "field": FIELD_A,
            "evidence": {
                "management": {
                    "erosion": {
                        "source": {"kind": "erosion_assessment_run", "id": "er-1"},
                        "rusle_status": "not_evaluated",
                        "missing_factors": ["K", "LS"],
                        "screening_concern_count": 0,
                        "screening_unknown_count": 2,
                    },
                },
                "data_gaps": ["climate", "water", "soil", "rotation"],
            },
            "anomalies": [],
        },
        "expect": {
            "min_recs": 1,
            "required_severities": ["info"],
            "required_title_fragments": ["Erosion model not evaluated"],
        },
    },
]

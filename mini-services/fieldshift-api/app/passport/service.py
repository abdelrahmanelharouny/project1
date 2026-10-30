"""Field Data Passport (Master §16.5 / Feature A §27 / Milestone 2 acceptance).

Aggregates per-field evidence coverage: which variables exist, from which
source/product/version, over which period, at which native support, with what
quality/freshness — and which analyses are therefore available, limited, or
blocked. Blocked analyses always list their missing inputs (never silently
evaluated — Master rule 11).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_platform.contracts.variables import VARIABLE_CATALOG
from app.db.models import DatasetProduct, DataSource, Observation, ObservationQualityFlag

# Analysis readiness rules for the slice. Each rule lists required variable
# codes (with minimum valid daily coverage ratio) plus extra non-variable gates.
ANALYSIS_RULES: list[dict[str, Any]] = [
    {
        "analysis_code": "climate_summary",
        "name": "Seasonal climate summary",
        "required_variables": {
            "air_temperature_mean": 0.8,
            "precipitation": 0.8,
        },
        "description": "Rainfall/temperature totals and means over the covered period.",
    },
    {
        "analysis_code": "et0_only_summary",
        "name": "Reference evapotranspiration summary",
        "required_variables": {"reference_et0": 0.8},
        "description": "ET0 totals over the covered period (single-variable screening).",
    },
    {
        "analysis_code": "water_budget_screening",
        "name": "Water budget screening (FAO-56 style)",
        "required_variables": {
            "reference_et0": 0.8,
            "precipitation": 0.8,
        },
        "extra_requirements": [
            "crop_water_parameters",  # Kc stage tables (Milestone 5+)
            "soil_water_storage",     # root-zone storage (Milestone 7+)
            "water_allocation",       # farmer-supplied allocation (Milestone 7+)
        ],
        "description": "Crop-water comparison. Blocked until crop Kc parameters, "
        "soil storage and allocation inputs are implemented and supplied.",
    },
    {
        "analysis_code": "rotation_optimization",
        "name": "Crop rotation optimization",
        "required_variables": {},
        "extra_requirements": [
            "crop_knowledge_base",     # Milestone 5+
            "crop_history",            # Milestone 5+
            "feature_runs",            # Milestone 4+
            "constraint_solver",       # Milestone 6+
        ],
        "description": "Rotation candidate generation and constrained optimization. "
        "Not implemented in this slice; reported as blocked, never simulated.",
    },
    {
        "analysis_code": "soil_analysis",
        "name": "Soil profile analysis",
        "required_variables": {},
        "extra_requirements": ["soil_samples"],
        "description": "Requires field soil samples (lab or farmer-reported). "
        "Soil sample intake arrives in a later milestone.",
    },
]


def _freshness_days(last_retrieved: datetime | None) -> int | None:
    if last_retrieved is None:
        return None
    return max(0, (datetime.now(UTC) - last_retrieved).days)


def _aggregate_warnings(warnings: list[dict[str, Any]], cap: int = 10) -> list[dict[str, Any]]:
    """Collapse identical (flag_code, severity, message) warnings into one entry
    with an occurrence count so passports stay readable for long series."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for w in warnings:
        key = (str(w.get("flag_code")), str(w.get("severity")), str(w.get("message")))
        if key not in grouped:
            grouped[key] = dict(w)
            grouped[key]["occurrences"] = 0
            order.append(key)
        grouped[key]["occurrences"] += 1
    result = [grouped[k] for k in order[:cap]]
    return result


def build_data_passport(db: Session, field_id: Any) -> dict[str, Any]:
    from sqlalchemy import case

    rows = db.execute(
        select(
            Observation.variable_code,
            Observation.unit,
            Observation.time_support,
            Observation.spatial_support_type,
            Observation.spatial_resolution_m,
            Observation.is_synthetic,
            Observation.processing_version,
            Observation.retrieved_at,
            func.count().label("n"),
            func.min(Observation.observed_at).label("p_start"),
            func.max(Observation.observed_at).label("p_end"),
            func.sum(case((Observation.value.is_(None), 1), else_=0)).label("n_missing"),
        )
        .where(Observation.field_id == field_id)
        .group_by(
            Observation.variable_code,
            Observation.unit,
            Observation.time_support,
            Observation.spatial_support_type,
            Observation.spatial_resolution_m,
            Observation.is_synthetic,
            Observation.processing_version,
            Observation.retrieved_at,
        )
    ).all()
    per_variable: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r.variable_code
        entry = per_variable.setdefault(
            code,
            {
                "variable_code": code,
                "unit": r.unit,
                "status": "available",
                "time_support": r.time_support,
                "spatial_support": {
                    "type": r.spatial_support_type,
                    "resolution_m": r.spatial_resolution_m,
                },
                "observation_count": 0,
                "missing_count": 0,
                "valid_count": 0,
                "is_synthetic": bool(r.is_synthetic),
                "evidence_class": "synthetic_test_data" if r.is_synthetic else "reanalysis_model_estimate",
                "processing_version": r.processing_version,
                "last_retrieved_at": None,
                "freshness_days": None,
                "_period_start": None,
                "_period_end": None,
                "period": {"start": None, "end": None},
                "valid_ratio": None,
                "dataset_product": None,
                "warnings": [],
            },
        )
        entry["observation_count"] += r.n
        entry["missing_count"] += r.n_missing or 0
        # Keep period bounds as datetimes during aggregation; ISO-format at the end.
        p_start_dt: datetime | None = r.p_start
        p_end_dt: datetime | None = r.p_end
        cur_start = entry["_period_start"]
        cur_end = entry["_period_end"]
        if p_start_dt is not None and (cur_start is None or p_start_dt < cur_start):
            entry["_period_start"] = p_start_dt
        if p_end_dt is not None and (cur_end is None or p_end_dt > cur_end):
            entry["_period_end"] = p_end_dt
        retrieved = r.retrieved_at
        if retrieved is not None:
            cur_last = (
                datetime.fromisoformat(entry["last_retrieved_at"])
                if entry["last_retrieved_at"]
                else None
            )
            if cur_last is None or retrieved > cur_last:
                entry["last_retrieved_at"] = retrieved.isoformat()

    # Dataset product provenance per variable (latest retrieval wins).
    product_rows = db.execute(
        select(Observation.variable_code, DatasetProduct, DataSource)
        .join(DatasetProduct, Observation.dataset_product_id == DatasetProduct.id)
        .join(DataSource, DatasetProduct.source_id == DataSource.id)
        .where(Observation.field_id == field_id)
    ).all()
    for vcode, product, source in product_rows:
        if vcode in per_variable and per_variable[vcode]["dataset_product"] is None:
            per_variable[vcode]["dataset_product"] = {
                "provider_code": source.provider_code,
                "provider_name": source.provider_name,
                "product_code": product.product_code,
                "product_version": product.product_version,
                "license_name": source.license_name,
                "attribution_text": source.attribution_text,
                "documentation_url": source.documentation_url,
            }
        if vcode in per_variable:
            per_variable[vcode]["is_synthetic"] = per_variable[vcode]["is_synthetic"] or bool(
                product.metadata and product.metadata.get("is_synthetic")
            )

    warnings_by_variable: dict[str, list[dict[str, Any]]] = {}
    unresolved_flags = db.execute(
        select(Observation, ObservationQualityFlag)
        .join(ObservationQualityFlag, ObservationQualityFlag.observation_id == Observation.id)
        .where(Observation.field_id == field_id)
    ).all()
    for obs, flag in unresolved_flags:
        warnings_by_variable.setdefault(obs.variable_code, []).append(
            {
                "flag_code": flag.flag_code,
                "severity": flag.severity,
                "message": flag.message,
                "observed_at": obs.observed_at.date().isoformat(),
            }
        )

    # Finalize per-variable stats.
    for code, entry in per_variable.items():
        valid = entry["observation_count"] - entry["missing_count"]
        entry["valid_count"] = valid
        entry["valid_ratio"] = round(valid / entry["observation_count"], 4) if entry["observation_count"] else None
        entry["freshness_days"] = _freshness_days(
            datetime.fromisoformat(entry["last_retrieved_at"]) if entry["last_retrieved_at"] else None
        )
        entry["period"] = {
            "start": entry["_period_start"].isoformat() if entry["_period_start"] else None,
            "end": entry["_period_end"].isoformat() if entry["_period_end"] else None,
        }
        del entry["_period_start"]
        del entry["_period_end"]
        entry["warnings"] = _aggregate_warnings(warnings_by_variable.get(code, []))

    present_codes = set(per_variable.keys())
    missing_codes = sorted(set(VARIABLE_CATALOG.keys()) - present_codes)

    missing_variables = [
        {
            "variable_code": code,
            "status": "missing",
            "unit": VARIABLE_CATALOG[code].unit,
            "reason": "No observations ingested for this variable.",
        }
        for code in missing_codes
    ]

    # Analysis readiness.
    analyses: list[dict[str, Any]] = []
    for rule in ANALYSIS_RULES:
        missing_inputs: list[str] = []
        reasons: list[str] = []
        for vcode, min_ratio in rule.get("required_variables", {}).items():
            entry = per_variable.get(vcode)
            if entry is None:
                missing_inputs.append(vcode)
                reasons.append(f"Variable '{vcode}' has no observations.")
            elif (entry["valid_ratio"] or 0) < min_ratio:
                missing_inputs.append(vcode)
                reasons.append(
                    f"Variable '{vcode}' valid coverage {entry['valid_ratio']} is below the "
                    f"required {min_ratio} for this analysis."
                )
        for extra in rule.get("extra_requirements", []):
            missing_inputs.append(extra)
            reasons.append(f"'{extra}' is not yet available (later milestone).")
        if missing_inputs:
            status = "blocked"
            if not rule.get("extra_requirements") and not missing_inputs:
                status = "limited"
        else:
            status = "available"
        analyses.append(
            {
                "analysis_code": rule["analysis_code"],
                "name": rule["name"],
                "description": rule["description"],
                "status": status,
                "required_inputs": sorted(rule.get("required_variables", {}).keys())
                + rule.get("extra_requirements", []),
                "missing_inputs": sorted(set(missing_inputs)),
                "reasons": reasons,
            }
        )

    overall = "ready"
    if not per_variable:
        overall = "blocked"
    elif any(a["status"] == "blocked" for a in analyses):
        overall = "partial"

    return {
        "field_id": str(field_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "variables": sorted(per_variable.values(), key=lambda e: e["variable_code"]),
        "missing_variables": missing_variables,
        "warnings": _aggregate_warnings([w for ws in warnings_by_variable.values() for w in ws], cap=20),
        "analyses": analyses,
        "notes": [
            "Coverage/quality/freshness are reported separately and never merged "
            "into a single synthetic confidence score (Master §16).",
        ],
    }

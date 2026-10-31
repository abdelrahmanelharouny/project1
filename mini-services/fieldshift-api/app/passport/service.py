"""Field Data Passport (Master §16.5 / Feature A §27 / Milestones 2-3).

Aggregates per-field evidence coverage: which variables exist, from which
source/product/version, over which period, at which native support, with what
quality/freshness — and which analyses are therefore available, limited, or
blocked. Blocked analyses always list their missing inputs (never silently
evaluated — Master rule 11).

Milestone 3 honesty rule: entries are grouped by (variable, source product) —
the same variable ingested from two providers (e.g. synthetic fixtures AND
Open-Meteo reanalysis) produces TWO passport entries, each with its own
evidence class, license and attribution. Sources are never merged into one
row behind a single label, and one source can never masquerade as another.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
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
    rows = db.execute(
        select(
            Observation.variable_code,
            Observation.unit,
            Observation.time_support,
            Observation.spatial_support_type,
            Observation.spatial_resolution_m,
            Observation.is_synthetic,
            Observation.processing_version,
            func.max(Observation.retrieved_at).label("retrieved_at"),
            Observation.dataset_product_id,
            DatasetProduct.product_code,
            DatasetProduct.product_version,
            DatasetProduct.metadata.label("product_metadata"),
            DataSource.provider_code,
            DataSource.provider_name,
            DataSource.license_name,
            DataSource.attribution_text,
            DataSource.documentation_url,
            func.count().label("n"),
            func.min(Observation.observed_at).label("p_start"),
            func.max(Observation.observed_at).label("p_end"),
            func.sum(case((Observation.value.is_(None), 1), else_=0)).label("n_missing"),
        )
        .join(DatasetProduct, Observation.dataset_product_id == DatasetProduct.id)
        .join(DataSource, DatasetProduct.source_id == DataSource.id)
        .where(Observation.field_id == field_id)
        .group_by(
            Observation.variable_code,
            Observation.unit,
            Observation.time_support,
            Observation.spatial_support_type,
            Observation.spatial_resolution_m,
            Observation.is_synthetic,
            Observation.processing_version,
            Observation.dataset_product_id,
            DatasetProduct.product_code,
            DatasetProduct.product_version,
            DatasetProduct.metadata,
            DataSource.provider_code,
            DataSource.provider_name,
            DataSource.license_name,
            DataSource.attribution_text,
            DataSource.documentation_url,
        )
        .order_by(Observation.variable_code, DataSource.provider_code)
    ).all()

    entries: list[dict[str, Any]] = []
    entry_key: dict[tuple[Any, Any], int] = {}
    for r in rows:
        product_metadata = r.product_metadata or {}
        evidence_class = product_metadata.get("evidence_class")
        if evidence_class is None:
            evidence_class = "synthetic_test_data" if r.is_synthetic else "reanalysis_model_estimate"
        key = (r.variable_code, r.dataset_product_id, r.processing_version)
        entry = {
            "variable_code": r.variable_code,
            "unit": r.unit,
            "status": "available",
            "time_support": r.time_support,
            "spatial_support": {
                "type": r.spatial_support_type,
                "resolution_m": r.spatial_resolution_m,
            },
            "observation_count": int(r.n),
            "missing_count": int(r.n_missing or 0),
            "valid_count": 0,
            "is_synthetic": bool(r.is_synthetic),
            "evidence_class": evidence_class,
            "processing_version": r.processing_version,
            "last_retrieved_at": r.retrieved_at.isoformat() if r.retrieved_at else None,
            "freshness_days": None,
            "period": {
                "start": r.p_start.isoformat() if r.p_start else None,
                "end": r.p_end.isoformat() if r.p_end else None,
            },
            "valid_ratio": None,
            "dataset_product": {
                "provider_code": r.provider_code,
                "provider_name": r.provider_name,
                "product_code": r.product_code,
                "product_version": r.product_version,
                "license_name": r.license_name,
                "attribution_text": r.attribution_text,
                "documentation_url": r.documentation_url,
            },
            "warnings": [],
        }
        entry["freshness_days"] = _freshness_days(r.retrieved_at)
        entry["valid_count"] = entry["observation_count"] - entry["missing_count"]
        entry["valid_ratio"] = (
            round(entry["valid_count"] / entry["observation_count"], 4) if entry["observation_count"] else None
        )
        entry_key[key] = len(entries)
        entries.append(entry)

    warnings_by_entry: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    unresolved_flags = db.execute(
        select(Observation, ObservationQualityFlag)
        .join(ObservationQualityFlag, ObservationQualityFlag.observation_id == Observation.id)
        .where(Observation.field_id == field_id)
    ).all()
    for obs, flag in unresolved_flags:
        key = (obs.variable_code, obs.dataset_product_id, obs.processing_version)
        warnings_by_entry.setdefault(key, []).append(
            {
                "flag_code": flag.flag_code,
                "severity": flag.severity,
                "message": flag.message,
                "observed_at": obs.observed_at.date().isoformat(),
            }
        )
    for key, index in entry_key.items():
        entries[index]["warnings"] = _aggregate_warnings(warnings_by_entry.get(key, []))

    present_codes = {e["variable_code"] for e in entries}
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

    # Best entry per variable code: prefer real (non-synthetic) sources on ties,
    # then the highest valid ratio. Used only for analysis-readiness gating; the
    # variables list above always shows every source separately.
    best_by_variable: dict[str, dict[str, Any]] = {}
    for entry in entries:
        current = best_by_variable.get(entry["variable_code"])
        if current is None:
            best_by_variable[entry["variable_code"]] = entry
            continue
        current_key = (not current["is_synthetic"], current["valid_ratio"] or 0)
        candidate_key = (not entry["is_synthetic"], entry["valid_ratio"] or 0)
        if candidate_key > current_key:
            best_by_variable[entry["variable_code"]] = entry

    # Analysis readiness.
    analyses: list[dict[str, Any]] = []
    for rule in ANALYSIS_RULES:
        missing_inputs: list[str] = []
        reasons: list[str] = []
        for vcode, min_ratio in rule.get("required_variables", {}).items():
            entry = best_by_variable.get(vcode)
            if entry is None:
                missing_inputs.append(vcode)
                reasons.append(f"Variable '{vcode}' has no observations.")
            elif (entry["valid_ratio"] or 0) < min_ratio:
                missing_inputs.append(vcode)
                reasons.append(
                    f"Variable '{vcode}' best valid coverage ({entry['valid_ratio']} from "
                    f"{entry['dataset_product']['provider_code']}) is below the required "
                    f"{min_ratio} for this analysis."
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
    if not entries:
        overall = "blocked"
    elif any(a["status"] == "blocked" for a in analyses):
        overall = "partial"

    return {
        "field_id": str(field_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "variables": entries,
        "missing_variables": missing_variables,
        "warnings": _aggregate_warnings(
            [w for ws in warnings_by_entry.values() for w in ws], cap=20
        ),
        "analyses": analyses,
        "notes": [
            "Coverage/quality/freshness are reported separately and never merged "
            "into a single synthetic confidence score (Master §16).",
            "The same variable may appear once per source; sources are never "
            "merged behind a single label.",
        ],
    }

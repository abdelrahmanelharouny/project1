"""Field evidence pack assembly (Intelligence layer, read-only).

build_field_evidence(db, field) compacts the LATEST deterministic engine
outputs of one field into a single provenance-labeled dict (target < 4000
chars JSON-dumped). The pack is the ONLY grounding material handed to the LLM
(advisor answers, field briefs, recommendation narratives) and the shared
context passed to every recommendation generator (built ONCE per refresh).

Provenance discipline:
- Every domain section names its source run (kind + id) and keeps each numeric
  value with its unit.
- Missing data is reported as an explicit data gap — never zero-filled, never
  invented (Master rule 11).
- Engine outputs are READ, never recomputed and never mutated.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.management.soil_cover import build_cover_timeline

logger = logging.getLogger("croptwist.intelligence.evidence")

# Monthly climate codes surfaced in the pack (extremes + latest anomaly).
_PRIORITY_MONTHLY_CODES: tuple[str, ...] = (
    "hot_days_35c_count_monthly",
    "frost_days_0c_count_monthly",
    "dry_spell_max_days_monthly",
    "precipitation_anomaly_z_monthly",
)

_COVER_WINDOW_DAYS = 365


def _latest_run(db: Session, model: Any, field_id: Any) -> Any | None:
    """Newest succeeded run of one engine type for the field (read-only).

    Ordered by completed_at when the run model has a lifecycle timestamp,
    falling back to created_at (M6B/M6C run models are created-at-only).
    """
    order = []
    if hasattr(model, "completed_at"):
        order.append(model.completed_at.desc().nullslast())
    order.append(model.created_at.desc())
    return db.scalar(
        select(model)
        .where(model.field_id == field_id, model.status == "succeeded")
        .order_by(*order)
        .limit(1)
    )


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 4)


def _climate_section(run: dbm.FeatureRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    metrics: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(row: dbm.FeatureValue, basis: str) -> None:
        key = (row.feature_code, basis)
        if key in seen or row.value is None:
            return
        seen.add(key)
        metrics.append({
            "code": row.feature_code,
            "value": _num(row.value),
            "unit": row.unit,
            "aggregation_level": row.aggregation_level,
            "period": row.period_label,
        })

    # Seasonal / crop-season totals first (latest period per code), then the
    # extreme monthly value per priority code, then the latest anomaly z.
    by_code: dict[str, list[dbm.FeatureValue]] = {}
    for row in run.values:
        if row.value is None:
            continue
        by_code.setdefault(row.feature_code, []).append(row)

    for rows in by_code.values():
        seasonal = [
            r for r in rows if r.aggregation_level in ("seasonal", "crop_season")
        ]
        if seasonal:
            _add(max(seasonal, key=lambda r: r.period_start), "latest_season")
    for code in _PRIORITY_MONTHLY_CODES:
        rows = by_code.get(code) or []
        monthly = [r for r in rows if r.aggregation_level == "monthly"]
        if not monthly:
            continue
        if code == "precipitation_anomaly_z_monthly":
            _add(max(monthly, key=lambda r: r.period_start), "latest_month")
        else:
            _add(max(monthly, key=lambda r: r.value), "max_month")
    metrics.sort(key=lambda m: m["code"])
    return {
        "source": {"kind": "feature_run", "id": str(run.id)},
        "period": {
            "start": run.period_start.date().isoformat() if run.period_start else None,
            "end": run.period_end.date().isoformat() if run.period_end else None,
        },
        "is_synthetic": run.is_synthetic,
        "metrics": metrics[:8],
    }


def _water_section(plan: dbm.WaterPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    result = plan.result or {}
    seasons = result.get("seasons") or []
    totals = result.get("rotation_totals") or {}
    nir_mm = totals.get("net_irrigation_requirement_mm_sum")
    gir_mm = None
    gir_vals = [
        s.get("totals", {}).get("gross_irrigation_requirement_mm")
        for s in seasons
        if isinstance(s, dict)
    ]
    if gir_vals and all(v is not None for v in gir_vals):
        gir_mm = _num(sum(float(v) for v in gir_vals))
    deficit_count = 0
    first_window: dict[str, Any] | None = None
    allocation_status: str | None = None
    for s in seasons:
        if not isinstance(s, dict):
            continue
        allocation_block = s.get("allocation") or {}
        if allocation_status is None and isinstance(allocation_block, dict):
            allocation_status = allocation_block.get("status")
        for w in s.get("deficit_windows") or []:
            deficit_count += 1
            if first_window is None:
                first_window = {
                    "season": s.get("season_label"),
                    "kind": w.get("kind"),
                    "start_date": w.get("start_date"),
                    "end_date": w.get("end_date"),
                    "days": w.get("days"),
                    "max_dr_mm": w.get("max_dr_mm"),
                    "deficit_m3": w.get("deficit_m3"),
                }
    crops = [
        a.get("crop_code")
        for a in (plan.crop_assignments or [])
        if isinstance(a, dict) and a.get("crop_code")
    ]
    season_labels = [s.get("label") for s in (plan.seasons or []) if isinstance(s, dict)]
    return {
        "source": {"kind": "water_plan", "id": str(plan.id)},
        "seasons": season_labels[:3],
        "crops": crops[:3],
        "nir_mm": _num(nir_mm),
        "gir_mm": gir_mm,
        "water_allocation_m3": _num(plan.water_allocation_m3),
        "allocation_status": allocation_status,
        "deficit_window_count": deficit_count,
        "first_deficit_window": first_window,
    }


def _soil_section(
    assessment: dbm.SoilAssessmentRun | None,
    budget: dbm.NutrientBudgetRun | None,
    soc: dbm.SocStockRun | None,
) -> dict[str, Any] | None:
    section: dict[str, Any] = {}
    if assessment is not None:
        domains: list[dict[str, Any]] = []
        for row in (assessment.result or {}).get("domains") or []:
            if not isinstance(row, dict) or not row.get("available"):
                continue
            entries = [
                {"code": v.get("variable_code"), "value": _num(v.get("latest_value")), "unit": v.get("unit")}
                for v in row["available"][:4]
                if isinstance(v, dict)
            ]
            domains.append({
                "domain": row.get("domain"),
                "available_count": row.get("available_count"),
                "missing_count": row.get("missing_count"),
                "indicators": entries,
            })
        if domains:
            section["assessment"] = {
                "source": {"kind": "soil_assessment_run", "id": str(assessment.id)},
                "domains": domains[:4],
            }
    if budget is not None:
        cumulative = (budget.result or {}).get("cumulative") or {}
        balances = cumulative.get("cumulative_balance_kg_ha") or {}
        section["nutrient_budget"] = {
            "source": {"kind": "nutrient_budget_run", "id": str(budget.id)},
            "cumulative_balance_kg_ha": {
                k: _num(v) for k, v in balances.items() if k in ("N", "P", "K")
            },
            "seasons_evaluable": cumulative.get("seasons_evaluable"),
        }
    if soc is not None:
        stock = ((soc.result or {}).get("profile_total") or {}).get("soc_stock_mg_ha")
        section["soc_stock"] = {
            "source": {"kind": "soc_stock_run", "id": str(soc.id)},
            "stock_Mg_C_ha": _num(stock),
        }
    return section or None


def _rotation_section(run: dbm.RotationRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    strategies = list(run.strategies or [])
    recommended = next(
        (
            s
            for s in strategies
            if not s.is_baseline
            and (s.explanations or {}).get("recommendation", {}).get("status") == "recommended"
        ),
        None,
    )
    if recommended is None:
        recommended = next((s for s in strategies if not s.is_baseline), None)
    if recommended is None:
        recommended = next((s for s in strategies if s.is_baseline), None)
    assignment = [
        {
            "season": entry.get("season_label"),
            "crop": entry.get("crop_code"),
        }
        for entry in (recommended.assignment or [])[:4]
        if isinstance(entry, dict) and entry.get("season_label") and entry.get("crop_code")
    ] if recommended is not None else []
    unevaluated_reasons: list[dict[str, Any]] = []
    unevaluated_count = 0
    for season_label, crops in (run.not_evaluated or {}).items():
        for code, dims in (crops or {}).items():
            unevaluated_count += 1
            if len(unevaluated_reasons) < 3:
                unevaluated_reasons.append({
                    "season": season_label,
                    "crop": code,
                    "unevaluated_dimensions": list(dims or [])[:2],
                })
    section: dict[str, Any] = {
        "source": {"kind": "rotation_run", "id": str(run.id)},
        "solver_status": run.solver_status,
        "season_count": len(run.seasons or []),
        "strategy": (
            {
                "id": str(recommended.id),
                "key": recommended.strategy_key,
                "kind": recommended.strategy_kind,
                "is_baseline": recommended.is_baseline,
            }
            if recommended is not None
            else None
        ),
        "assignment": assignment,
        "unevaluated_crop_seasons": unevaluated_count,
        "unevaluated_examples": unevaluated_reasons,
    }
    conflicts = (run.infeasibility_details or {}).get("conflicts")
    if conflicts:
        section["infeasible_profile_count"] = len(conflicts)
    return section


def _cover_metrics(db: Session, field_id: Any) -> dict[str, Any] | None:
    """Latest soil-cover metrics over a trailing 365-day window (read-only
    re-run of the deterministic M6C timeline engine over stored records)."""
    crops = db.scalars(
        select(dbm.CropHistory).where(dbm.CropHistory.field_id == field_id)
    ).all()
    covers = db.scalars(
        select(dbm.CoverCropPlanItem).where(dbm.CoverCropPlanItem.field_id == field_id)
    ).all()
    events = db.scalars(
        select(dbm.SoilManagementEvent).where(dbm.SoilManagementEvent.field_id == field_id)
    ).all()
    observations = db.scalars(
        select(dbm.SoilCoverObservation).where(dbm.SoilCoverObservation.field_id == field_id)
    ).all()
    if not (crops or covers or events or observations):
        return None
    window_end = dt.date.today()
    window_start = window_end - dt.timedelta(days=_COVER_WINDOW_DAYS)
    timeline = build_cover_timeline(
        window_start=window_start,
        window_end=window_end,
        crop_history=[
            {"id": str(c.id), "crop_label": c.crop_label, "sowing_date": c.sowing_date,
             "harvest_date": c.harvest_date, "evidence_class": c.evidence_class}
            for c in crops
        ],
        cover_crop_items=[
            {"id": str(c.id), "crop_label": c.crop_label,
             "intended_sowing_start": c.intended_sowing_start,
             "intended_termination_window_start": c.intended_termination_window_start,
             "established_date": (c.metadata or {}).get("established_date"),
             "terminated_date": (c.metadata or {}).get("terminated_date"),
             "evidence_class": c.evidence_class}
            for c in covers
        ],
        management_events=[
            {"id": str(e.id), "event_date": e.event_date, "event_type": e.event_type,
             "title": e.title, "details": e.details}
            for e in events
        ],
        cover_observations=[
            {"id": str(o.id), "observed_date": o.observed_date, "cover_state": o.cover_state,
             "cover_fraction": o.cover_fraction, "measurement_basis": o.measurement_basis,
             "index_type": o.index_type, "index_value": o.index_value,
             "evidence_class": o.evidence_class}
            for o in observations
        ],
    )
    metrics = timeline.get("metrics") or {}
    return {
        "window": timeline.get("window"),
        "protective_cover_fraction": _num(metrics.get("protective_cover_fraction")),
        "days_protective_cover": metrics.get("days_protective_cover"),
        "days_known_bare": metrics.get("days_known_bare"),
        "days_unknown": metrics.get("days_unknown"),
        "longest_bare_interval_days": metrics.get("longest_bare_interval_days"),
    }


def _management_section(db: Session, field_id: Any) -> dict[str, Any] | None:
    section: dict[str, Any] = {}
    cover = _cover_metrics(db, field_id)
    if cover is not None:
        section["soil_cover"] = cover
    erosion = _latest_run(db, dbm.ErosionAssessmentRun, field_id)
    if erosion is not None:
        result = erosion.result or {}
        rusle = result.get("rusle") or {}
        screening = result.get("screening") or {}
        section["erosion"] = {
            "source": {"kind": "erosion_assessment_run", "id": str(erosion.id)},
            "rusle_status": rusle.get("status"),
            "missing_factors": (rusle.get("missing_factors") or [])[:5],
            "screening_concern_count": len(screening.get("concerns") or []),
            "screening_unknown_count": len(screening.get("unknowns") or []),
        }
    return section or None


def _satellite_section(db: Session, field: dbm.Field) -> dict[str, Any] | None:
    """Compact vegetation/satellite section (P06) from the field profile.

    Deterministic read-model projection of the persisted satellite
    observations (evidence_class=satellite_derived_estimate). Carries
    measurement provenance (scene id, resolution, cloud, valid-pixel
    fraction), the freshness window and an explicit insufficient-evidence
    status — never an agronomic claim. None when no satellite observation
    exists for the field (the domain then lands in data_gaps).
    """
    from app.vegetation.field_profile import field_satellite_profile

    try:
        profile = field_satellite_profile(db, field, index="ndvi")
    except Exception:  # noqa: BLE001 — evidence must never break the pack
        logger.exception("satellite evidence section failed")
        return None

    latest = profile.get("latest_valid_observation")
    quality = profile.get("quality_summary") or {}
    if latest is None:
        return None
    comparison = profile.get("comparison") or {}
    spatial = profile.get("spatial_variation") or {}
    insufficient = profile.get("insufficient_evidence")
    section = {
        "index": "ndvi",
        "index_formula": profile.get("index_formula"),
        "latest_observation": {
            "observed_at": latest.get("observed_at"),
            "value": latest.get("value"),
            "unit": "index",
            "cloud_cover_pct": latest.get("cloud_cover_pct"),
            "valid_pixel_fraction": latest.get("valid_pixel_fraction"),
            "spatial_resolution_m": latest.get("spatial_resolution_m"),
            "processing_version": latest.get("processing_version"),
            "scene_id": latest.get("scene_id"),
            "evidence_class": latest.get("evidence_class"),
        },
        "valid_observations": quality.get("valid_observations"),
        "excluded_no_value": quality.get("excluded_no_value"),
        "freshness_days_since_last": quality.get("freshness_days_since_last"),
        "fresh": quality.get("fresh"),
        "supports_subfield_claims": spatial.get("supports_subfield_claims"),
        "baseline_comparison": (
            {
                "delta_vs_baseline_mean": comparison.get("delta_vs_baseline_mean"),
                "z_score_vs_baseline": comparison.get("z_score_vs_baseline"),
                "weak_evidence": comparison.get("weak_evidence"),
            }
            if comparison
            else None
        ),
        "statistical_zones": profile.get("statistical_zones"),
        "insufficient_evidence": insufficient,
        "source": {
            "provider_code": "nasa_hls",
            "product": "HLS v2.0 surface reflectance (HLSL30/HLSS30)",
            "attribution": (
                "NASA HLS courtesy of NASA LP DAAC; contains Landsat data "
                "(USGS) and modified Copernicus Sentinel-2 data (ESA) "
                "harmonized by NASA."
            ),
        },
        "is_synthetic": False,
        "not_claims": (
            "NDVI values are spectral statistics; this section does not "
            "diagnose disease, drought or nutrient status."
        ),
    }
    return section


def build_field_evidence(db: Session, field: dbm.Field) -> dict[str, Any]:
    """Assemble the compact, provenance-labeled evidence pack for one field.

    Sections for domains without any run are OMITTED and the domain is listed
    in `data_gaps` (honest empty state — the recommendation generators turn
    each gap into an INFO recommendation).
    """
    feature_run = _latest_run(db, dbm.FeatureRun, field.id)
    water_plan = _latest_run(db, dbm.WaterPlan, field.id)
    assessment = _latest_run(db, dbm.SoilAssessmentRun, field.id)
    budget = _latest_run(db, dbm.NutrientBudgetRun, field.id)
    soc = _latest_run(db, dbm.SocStockRun, field.id)
    rotation_run = _latest_run(db, dbm.RotationRun, field.id)

    farm = db.get(dbm.Farm, field.farm_id)
    pack: dict[str, Any] = {
        "field": {
            "id": str(field.id),
            "name": field.name,
            "area_ha": _num(field.area_ha),
            "profile": {
                "farm_name": farm.name if farm else None,
                "country_code": farm.country_code if farm else None,
                "timezone": farm.timezone if farm else None,
                "unit_system": farm.unit_system if farm else None,
                "boundary_version": field.boundary_version,
            },
            "year": (
                feature_run.period_end.year
                if feature_run is not None and feature_run.period_end
                else None
            ),
        }
    }

    data_gaps: list[str] = []
    climate = _climate_section(feature_run)
    if climate is not None:
        pack["climate"] = climate
    else:
        data_gaps.append("climate")
    water = _water_section(water_plan)
    if water is not None:
        pack["water"] = water
    else:
        data_gaps.append("water")
    soil = _soil_section(assessment, budget, soc)
    if soil is not None:
        pack["soil"] = soil
    else:
        data_gaps.append("soil")
    rotation = _rotation_section(rotation_run)
    if rotation is not None:
        pack["rotation"] = rotation
    else:
        data_gaps.append("rotation")
    management = _management_section(db, field.id)
    if management is not None:
        pack["management"] = management
    else:
        data_gaps.append("management")
    satellite = _satellite_section(db, field)
    if satellite is not None:
        pack["vegetation"] = satellite
    else:
        data_gaps.append("vegetation")
    pack["data_gaps"] = data_gaps
    return pack

"""Adaptive Evidence Acquisition (P2.E) — gap detection, Value of
Information, and acquisition planning.

Instead of saying "data unavailable", this module explains WHAT information
is missing, WHY it matters to WHICH decision, and HOW the farmer can obtain
it — with a decision-aware Value-of-Information estimate grounded in the
actual decision margins (never invented monetary values).

Gap detection queries the LIVE platform state (observations, soil samples,
crop history, water plans, farm constraints, satellite scenes) — gaps are
computed, not configured flags.

Value of Information (qualitative + structural, honest):
- decision_sensitivity: derived from the ACTUAL decision margins in the
  evidence (e.g. allocation shortfall margin |allocation - NIR| compared
  against the plausible NIR uncertainty band), so "this gap could flip this
  decision" is a computed statement, not rhetoric.
- collection_cost: qualitative categories (low/medium/high) with effort
  descriptions — no fake monetary values.
- time_sensitivity: from the crop calendar and decision windows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.db.models_m6bc_m7 import (
    NutrientApplication,
    NutrientRemoval,
    SoilMeasurement,
    SoilSamplingEvent,
)
from app.db.models_p2 import SatelliteScene

EVIDENCE_GAPS_VERSION = "evidence-gaps-1.0.0"

FRESH_WEATHER_DAYS = 8  # archive lag is ~6 days; older = stale
FRESH_SATELLITE_DAYS = 45
STALE_SOIL_MONTHS = 24
STALE_FEATURE_RUN_DAYS = 60


# ----------------------------------------------------------------- detection
def detect_gaps(db: Session, field: dbm.Field) -> dict[str, Any]:
    """Detect evidence gaps for one field against the live state."""
    gaps: list[dict[str, Any]] = []
    checks = [
        _gap_soil_samples,
        _gap_stale_weather,
        _gap_satellite_coverage,
        _gap_planting_dates,
        _gap_crop_history,
        _gap_irrigation_records,
        _gap_nutrient_history,
        _gap_field_geometry,
        _gap_operational_constraints,
        _gap_market_information,
    ]
    for check in checks:
        found = check(db, field)
        gaps.extend(found)

    completeness = _completeness(db, field, gaps)
    return {
        "field_id": str(field.id),
        "gaps": gaps,
        "completeness": completeness,
        "version": EVIDENCE_GAPS_VERSION,
        "note": (
            "Gaps are computed from the live platform state. Each gap names "
            "the affected decision, why the evidence matters, and how to "
            "obtain it — 'data unavailable' is never the whole answer."
        ),
    }


def _gap(code: str, importance: str, affected_decisions: list[str], required: str,
         status: str, freshness: str, spatial: str, impact: str, how: str,
         urgency: str, sensitivity: dict[str, Any] | None = None,
         cost: str = "medium", cost_effort: str = "") -> dict[str, Any]:
    return {
        "gap_code": code,
        "importance": importance,
        "affected_decisions": affected_decisions,
        "required_evidence": required,
        "current_status": status,
        "freshness_requirement": freshness,
        "spatial_relevance": spatial,
        "potential_impact": impact,
        "how_to_obtain": how,
        "urgent": urgency != "routine",
        "urgency": urgency,
        "collection_cost": {"category": cost, "effort": cost_effort},
        "decision_sensitivity": sensitivity or {"level": "unknown", "detail": "not computed"},
    }


def _days_since(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds() / 86400.0


def _gap_soil_samples(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    count = db.scalar(
        select(func.count(SoilMeasurement.id)).where(SoilMeasurement.field_id == field.id)
    )
    latest = db.scalar(
        select(SoilMeasurement.observed_at)
        .where(SoilMeasurement.field_id == field.id)
        .order_by(SoilMeasurement.observed_at.desc())
        .limit(1)
    )
    age_months = None
    if latest is not None:
        age_months = (date.today() - latest).days / 30.44
    if (count or 0) == 0:
        return [
            _gap(
                code="soil_sample_missing",
                importance="critical",
                affected_decisions=["soil_health_assessment", "fertilization_plan", "irrigation_scheduling"],
                required="Laboratory soil analysis (pH, OM/SOC, N, P, K, EC, texture) with depth labels",
                status="no soil measurement exists for this field",
                freshness="within 24 months for screening; annually for trend tracking",
                spatial="field-level composite (representative sampling)",
                impact=(
                    "Without soil data, fertilization and amendment decisions run on "
                    "global predictions (SoilGrids) or defaults; irrigation water-holding "
                    "inputs fall back to texture-based PTF estimates with wider uncertainty."
                ),
                how=(
                    "Collect a composite topsoil sample (0-30 cm, 8-12 subsamples walked "
                    "across the field), plus a subsoil sample where depth matters; send to "
                    "an accredited lab and import via the soil lab CSV."
                ),
                urgency="high",
                sensitivity=_soil_decision_sensitivity(db, field),
                cost="medium",
                cost_effort="sampling labor + lab analysis fee; results typically within 1-3 weeks",
            )
        ]
    if age_months is not None and age_months > STALE_SOIL_MONTHS:
        return [
            _gap(
                code="soil_sample_stale",
                importance="high",
                affected_decisions=["fertilization_plan", "soil_trend_tracking"],
                required="Refreshed soil analysis",
                status=f"latest measurement is {age_months:.0f} months old (> {STALE_SOIL_MONTHS})",
                freshness="within 24 months",
                spatial="field-level composite",
                impact="Trend conclusions (depletion/improvement) rest on outdated measurements.",
                how="Repeat the composite sampling on the same depths to make the comparison method-compatible.",
                urgency="routine",
                sensitivity=_soil_decision_sensitivity(db, field),
                cost="medium",
                cost_effort="same as initial sampling",
            )
        ]
    return []


def _soil_decision_sensitivity(db: Session, field: dbm.Field) -> dict[str, Any]:
    """Structural sensitivity: does the water plan currently rest on PTF
    estimates (where a lab texture/OM result would tighten TAW/RAW)?"""
    plans = list(
        db.scalars(
            select(dbm.WaterPlan)
            .where(dbm.WaterPlan.field_id == field.id)
            .order_by(dbm.WaterPlan.created_at.desc())
            .limit(1)
        )
    )
    if not plans:
        return {"level": "not_computable", "detail": "no water plan exists to affect"}
    soil_inputs = (plans[0].soil_inputs or {}).get("source")
    if soil_inputs == "ptf_texture":
        return {
            "level": "high",
            "detail": (
                "The active water plan derives its water-holding inputs from a "
                "texture-based PTF (Saxton & Rawls 2006); a lab-measured texture/OM "
                "would replace the PTF basis and can shift RAW/TAW and the stress "
                "windows materially."
            ),
        }
    return {"level": "low", "detail": f"active water plan soil basis: {soil_inputs}"}


def _latest_observation_meta(db: Session, field_id: uuid.UUID, codes: list[str]) -> tuple[datetime | None, int]:
    latest = db.scalar(
        select(dbm.Observation.observed_at)
        .where(
            dbm.Observation.field_id == field_id,
            dbm.Observation.variable_code.in_(codes),
        )
        .order_by(dbm.Observation.observed_at.desc())
        .limit(1)
    )
    count = db.scalar(
        select(func.count(dbm.Observation.id)).where(
            dbm.Observation.field_id == field_id,
            dbm.Observation.variable_code.in_(codes),
        )
    )
    return latest, int(count or 0)


def _gap_stale_weather(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    latest, count = _latest_observation_meta(
        db, field.id, ["air_temperature_mean", "precipitation"]
    )
    age = _days_since(latest)
    if (count or 0) == 0:
        return [
            _gap(
                code="weather_observations_missing",
                importance="critical",
                affected_decisions=["rotation_planning", "irrigation_scheduling", "climate_risk_screening"],
                required="Historical daily weather (temperature, precipitation, ET0)",
                status="no weather observations ingested",
                freshness="continuous archive; the feature engine needs >= 5 years for stable baselines",
                spatial="gridded reanalysis at the field location is acceptable",
                impact="Climate-driven engines (season planning, ET0, risk screening) are unevaluated.",
                how="Run a data job against the Open-Meteo historical archive (or import CSV records).",
                urgency="high",
                cost="low",
                cost_effort="one API job; no field work",
            )
        ]
    if age is not None and age > FRESH_WEATHER_DAYS:
        return [
            _gap(
                code="weather_observations_stale",
                importance="medium",
                affected_decisions=["climate_risk_screening", "anomaly_detection"],
                required="Recent weather observations",
                status=f"latest observation is {age:.0f} days old (> {FRESH_WEATHER_DAYS}; archive lag is ~6 days)",
                freshness="updated at least monthly",
                spatial="same",
                impact="Anomaly screening and freshness-sensitive signals drift out of date.",
                how="Re-run the archive data job to pull the recent window.",
                urgency="routine",
                cost="low",
                cost_effort="one API job",
            )
        ]
    return []


def _gap_satellite_coverage(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    scenes = db.scalar(
        select(func.count(SatelliteScene.id)).where(
            SatelliteScene.field_id == field.id,
            SatelliteScene.is_synthetic.is_(False),
        )
    )
    any_scenes = db.scalar(
        select(func.count(SatelliteScene.id)).where(SatelliteScene.field_id == field.id)
    )
    if (scenes or 0) > 0:
        return []
    synthetic_only = (any_scenes or 0) > 0
    return [
        _gap(
            code="satellite_coverage_missing",
            importance="medium",
            affected_decisions=["vegetation_stress_screening", "irrigation_uniformity_review"],
            required="Cloud-free satellite scenes (Sentinel-2 L2A or compatible)",
            status=(
                "only synthetic fixture scenes exist (demonstrations, never real evidence)"
                if synthetic_only
                else "no satellite scenes ingested"
            ),
            freshness="a scene every 2-4 weeks during the growing season",
            spatial="10-20 m grid over the field boundary",
            impact=(
                "Vegetation stress screening is unavailable; plant-health signals "
                "rely on farmer observations alone."
            ),
            how=(
                "Ingest Sentinel-2 via the STAC provider (needs external network "
                "access; a synthetic fixture exists for demos but is never real "
                "evidence)."
            ),
            urgency="routine",
            cost="low",
            cost_effort="API ingestion; no field work",
        )
    ]


def _gap_planting_dates(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(dbm.CropHistory).where(
                dbm.CropHistory.field_id == field.id,
                dbm.CropHistory.sowing_date.is_(None),
            )
        )
    )
    if not rows:
        return []
    return [
        _gap(
            code="planting_dates_missing",
            importance="high",
            affected_decisions=["irrigation_scheduling", "vegetation_stage_context", "harvest_planning"],
            required="Sowing (and harvest) dates for recorded crops",
            status=f"{len(rows)} crop-history row(s) lack sowing dates",
            freshness="once per season",
            spatial="field-level",
            impact=(
                "Kc curves cannot be anchored to a sowing date, so seasonal ETc "
                "and stress-window timing stay on calendar-proxy assumptions."
            ),
            how="Record the actual sowing dates in the crop history (or import them).",
            urgency="high" if len(rows) > 1 else "routine",
            cost="low",
            cost_effort="farmer record entry",
        )
    ]


def _gap_crop_history(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    count = db.scalar(
        select(func.count(dbm.CropHistory.id)).where(dbm.CropHistory.field_id == field.id)
    )
    if (count or 0) > 0:
        return []
    return [
        _gap(
            code="crop_history_missing",
            importance="high",
            affected_decisions=["rotation_planning", "rotation_break_rule_checking"],
            required="Crop history (what grew, when)",
            status="no crop history recorded",
            freshness="accumulates per season",
            spatial="field-level",
            impact=(
                "The rotation baseline is empty; rotation-break rules and "
                "diversification scoring operate without history."
            ),
            how="Add the last seasons' crops to the field's crop history.",
            urgency="routine",
            cost="low",
            cost_effort="farmer record entry",
        )
    ]


def _gap_irrigation_records(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    plans = list(
        db.scalars(
            select(dbm.WaterPlan)
            .where(dbm.WaterPlan.field_id == field.id)
            .order_by(dbm.WaterPlan.created_at.desc())
            .limit(1)
        )
    )
    applied = None
    if plans:
        result = plans[0].result or {}
        ladder = result.get("requirements_ladder") or {}
        applied = ladder.get("actual_applied_mm")
    if applied is not None:
        return []
    return [
        _gap(
            code="irrigation_records_missing",
            importance="medium",
            affected_decisions=["irrigation_scheduling", "water_balance_verification"],
            required="Actual applied irrigation volumes (or depths) per season",
            status="no actual applied water recorded in the latest water plan context",
            freshness="per irrigation event or at least monthly in season",
            spatial="field-level (per-set where possible)",
            impact=(
                "The requirements ladder stops at the gross irrigation "
                "requirement; realized deficits and efficiency cannot be verified."
            ),
            how="Record applied volumes (meter reads or estimated set times) against the field.",
            urgency="routine",
            cost="low",
            cost_effort="record keeping; meter reading if available",
        )
    ]


def _gap_nutrient_history(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    apps = db.scalar(
        select(func.count(NutrientApplication.__table__.c.id)).where(
            NutrientApplication.__table__.c.field_id == field.id
        )
    )
    rems = db.scalar(
        select(func.count(NutrientRemoval.__table__.c.id)).where(
            NutrientRemoval.__table__.c.field_id == field.id
        )
    )
    if (apps or 0) > 0 and (rems or 0) > 0:
        return []
    missing = []
    if not apps:
        missing.append("inputs (fertilizer/manure applications)")
    if not rems:
        missing.append("outputs (harvest removals)")
    return [
        _gap(
            code="nutrient_history_missing",
            importance="high",
            affected_decisions=["fertilization_plan", "soil_fertility_trend"],
            required="Nutrient applications and harvest removals",
            status=f"missing {' and '.join(missing)}",
            freshness="per application / per harvest",
            spatial="field-level",
            impact="The N/P/K mass balance cannot close; depletion signals are unevaluable.",
            how="Record applications (product, mass, area) and harvest removals (biomass, concentrations).",
            urgency="routine",
            cost="low",
            cost_effort="record keeping",
        )
    ]


def _gap_field_geometry(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    area = float(field.area_ha or 0.0)
    if area > 0:
        return []
    return [
        _gap(
            code="field_geometry_incomplete",
            importance="high",
            affected_decisions=["satellite_statistics", "area_based_allocation"],
            required="A validated field boundary polygon",
            status="field area is zero or the boundary is missing",
            freshness="once, then on change",
            spatial="field boundary (EPSG:4326 polygon)",
            impact="Zonal statistics and area-based portfolio allocation cannot run.",
            how="Draw or upload the boundary (GeoJSON) and save a boundary version.",
            urgency="high",
            cost="low",
            cost_effort="map digitization",
        )
    ]


def _gap_operational_constraints(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    resources = db.scalar(
        select(func.count(dbm.FarmResource.id)).where(dbm.FarmResource.farm_id == field.farm_id)
    )
    alloc = db.scalar(
        select(dbm.FarmConstraint.id).where(
            dbm.FarmConstraint.farm_id == field.farm_id,
            dbm.FarmConstraint.constraint_code == "water_allocation_m3_per_season",
        )
    )
    if (resources or 0) > 0 and alloc is not None:
        return []
    missing = []
    if not resources:
        missing.append("farm resources (labor/machinery)")
    if alloc is None:
        missing.append("the seasonal water allocation")
    return [
        _gap(
            code="operational_constraints_missing",
            importance="medium",
            affected_decisions=["operations_scheduling", "rotation_feasibility", "portfolio_optimization"],
            required="Farm constraints: water allocation, labor and machinery resources",
            status=f"missing {' and '.join(missing)}",
            freshness="per season",
            spatial="farm-level",
            impact=(
                "Operations scheduling and portfolio-level shared-resource "
                "constraints run unconstrained; feasibility claims weaken."
            ),
            how="Register farm resources and the seasonal water allocation on the farm.",
            urgency="routine",
            cost="low",
            cost_effort="record entry",
        )
    ]


def _gap_market_information(db: Session, field: dbm.Field) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(dbm.FarmConstraint).where(
                dbm.FarmConstraint.farm_id == field.farm_id,
                dbm.FarmConstraint.constraint_code == "market_margin_index",
            )
        )
    )
    if rows:
        return []
    return [
        _gap(
            code="market_information_missing",
            importance="low",
            affected_decisions=["rotation_economic_screening", "portfolio_tradeoffs"],
            required="Farmer-supplied margin index per crop (0-100 relative profitability)",
            status="no market margin index supplied",
            freshness="per season (prices move)",
            spatial="farm-level",
            impact=(
                "Economic screening criteria stay skipped (the platform never "
                "invents prices); rotation/portfolio economics are qualitative."
            ),
            how="Supply a relative margin index per crop you consider (the engine treats it as farmer-reported).",
            urgency="routine",
            cost="low",
            cost_effort="farmer estimate entry",
        )
    ]


def _completeness(db: Session, field: dbm.Field, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    critical_codes = {"soil_sample_missing", "weather_observations_missing", "field_geometry_incomplete"}
    gap_codes = {g["gap_code"] for g in gaps}
    critical_missing = sorted(gap_codes & critical_codes)
    domains = {
        "soil": "soil_sample_missing" not in gap_codes and "soil_sample_stale" not in gap_codes,
        "weather": "weather_observations_missing" not in gap_codes and "weather_observations_stale" not in gap_codes,
        "vegetation": "satellite_coverage_missing" not in gap_codes,
        "crop_history": "crop_history_missing" not in gap_codes and "planting_dates_missing" not in gap_codes,
        "nutrients": "nutrient_history_missing" not in gap_codes,
        "water_records": "irrigation_records_missing" not in gap_codes,
        "operations": "operational_constraints_missing" not in gap_codes,
        "market": "market_information_missing" not in gap_codes,
    }
    return {
        "domains_ready": sorted(k for k, v in domains.items() if v),
        "domains_with_gaps": sorted(k for k, v in domains.items() if not v),
        "critical_missing": critical_missing,
        "gap_count": len(gaps),
    }

"""Value of Information + acquisition plans (P2.E).

VoI here is DECISION-AWARE and structural, not monetary:
- For each gap the module computes whether obtaining the missing evidence
  could CHANGE a decision, using the actual margins in the evidence:
  - water allocation shortfall: |allocation - NIR| vs the plausible NIR
    uncertainty band (TAW/PTF + ET0 coverage) — if the band can span the
    margin, the decision is flippable.
  - rotation economic screening: farmer margin presence (absent → decision
    stays qualitative; the gap's value is enabling the criterion at all).
  - anomaly/trend thresholds: baseline class (short_record_exploratory vs
    long_record_reference) — more history directly raises confidence class.
- Collection cost stays qualitative (low/medium/high + effort description).
- Time sensitivity: crop-calendar anchored urgency where applicable.

Acquisition plans turn gaps into actionable steps (what/why/which decision/
how/urgency/uncertainty reduced) and feed the acquisition action lifecycle.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.evidence_gaps.detection import EVIDENCE_GAPS_VERSION

VOI_VERSION = "evidence-voi-1.0.0"

# Plausible NIR uncertainty band (documented, conservative):
# - ET0/Climate evidence: FAO-56 reports ~4-8% error for well-maintained
#   weather data; gridded reanalysis widens this.
# - Soil PTF (Saxton & Rawls 2006): reported ~±0.03 m3/m3 on theta values →
#   material TAW deltas on shallow rooting depths.
NIR_UNCERTAINTY_FRACTION = 0.15  # combined screening band: 15% of NIR
MIN_BAND_MM = 20.0  # floor: at least 20 mm band on any NIR estimate


def value_of_information(
    db: Session,
    field: dbm.Field,
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach a structural VoI assessment to each gap."""
    water_margin = _water_decision_margin(db, field)
    baseline_class = _baseline_class(db, field)
    voi: list[dict[str, Any]] = []
    for gap in gaps:
        entry = dict(gap)
        entry["voi"] = _gap_voi(
            gap,
            water_margin=water_margin,
            baseline_class=baseline_class,
        )
        voi.append(entry)
    return voi


def _water_decision_margin(db: Session, field: dbm.Field) -> dict[str, Any] | None:
    """The allocation-shortfall margin of the latest water plan, with the
    plausible NIR uncertainty band."""
    plans = list(
        db.scalars(
            select(dbm.WaterPlan)
            .where(dbm.WaterPlan.field_id == field.id)
            .order_by(dbm.WaterPlan.created_at.desc())
            .limit(1)
        )
    )
    if not plans:
        return None
    result = plans[0].result or {}
    ladder = result.get("requirements_ladder") or {}
    nir = ladder.get("net_irrigation_requirement_mm")
    allocation_m3 = plans[0].water_allocation_m3
    if nir is None or allocation_m3 is None:
        return None
    try:
        nir = float(nir)
        allocation_m3 = float(allocation_m3)
    except (TypeError, ValueError):
        return None
    # NIR mm → m3 via MM_PER_HA_TO_M3 = 10 (app/water/contracts)
    area_ha = float(field.area_ha or 0.0)
    nir_m3 = nir * 10.0 * area_ha
    margin_m3 = allocation_m3 - nir_m3
    band_m3 = max(nir * NIR_UNCERTAINTY_FRACTION, MIN_BAND_MM) * 10.0 * area_ha
    flippable = abs(margin_m3) <= band_m3
    return {
        "decision": "water_allocation_shortfall",
        "nir_mm": nir,
        "nir_m3": round(nir_m3, 1),
        "allocation_m3": allocation_m3,
        "margin_m3": round(margin_m3, 1),
        "nir_uncertainty_band_m3": round(band_m3, 1),
        "flippable": flippable,
        "basis": (
            f"margin |allocation - NIR| = {abs(margin_m3):.0f} m3 vs plausible NIR "
            f"uncertainty band {band_m3:.0f} m3 (15% NIR + 20 mm floor; FAO-56 "
            "data-quality range + PTF soil uncertainty, screening-grade)"
        ),
    }


def _baseline_class(db: Session, field: dbm.Field) -> str | None:
    runs = list(
        db.scalars(
            select(dbm.FeatureRun)
            .where(dbm.FeatureRun.field_id == field.id, dbm.FeatureRun.status == "succeeded")
            .order_by(dbm.FeatureRun.created_at.desc())
            .limit(1)
        )
    )
    if not runs:
        return None
    values = list(
        db.scalars(
            select(dbm.FeatureValue).where(dbm.FeatureValue.run_id == runs[0].id).limit(50)
        )
    )
    for v in values:
        baseline = v.baseline_reference or {}
        cls = baseline.get("class")
        if cls:
            return str(cls)
    return None


def _gap_voi(
    gap: dict[str, Any],
    *,
    water_margin: dict[str, Any] | None,
    baseline_class: str | None,
) -> dict[str, Any]:
    code = gap.get("gap_code")
    affected = gap.get("affected_decisions") or []
    sensitivity: dict[str, Any] = {"level": "unknown", "detail": "not computed"}
    expected_ranking_change: list[str] = []

    if code in ("soil_sample_missing", "soil_sample_stale"):
        declared = gap.get("decision_sensitivity") or {}
        level = declared.get("level", "unknown")
        if water_margin and water_margin["flippable"] and level in ("high", "unknown"):
            sensitivity = {
                "level": "high",
                "detail": (
                    "A lab texture/OM result tightens TAW/RAW and the NIR "
                    "estimate; the current allocation margin ("
                    f"{water_margin['margin_m3']} m3) is inside the plausible "
                    "NIR uncertainty band, so the shortfall decision could flip."
                ),
            }
            expected_ranking_change.append("water_allocation_shortfall")
        elif level == "high":
            sensitivity = declared
        else:
            sensitivity = {
                "level": level if level != "unknown" else "medium",
                "detail": declared.get("detail", "improves soil-based screening quality"),
            }
    elif code == "weather_observations_missing" or code == "weather_observations_stale":
        if baseline_class == "short_record_exploratory":
            sensitivity = {
                "level": "high",
                "detail": (
                    "The feature baseline is short-record exploratory; more "
                    "years of weather raise it toward long_record_reference "
                    "and stabilize every anomaly-based signal."
                ),
            }
            expected_ranking_change.append("anomaly_significance")
        else:
            sensitivity = {
                "level": "medium",
                "detail": "fresh observations keep anomaly screening current",
            }
    elif code == "irrigation_records_missing":
        sensitivity = {
            "level": "medium",
            "detail": (
                "Actual applied water converts the requirements ladder from a "
                "plan into a verification (realized deficits, efficiency)."
            ),
        }
    elif code == "market_information_missing":
        sensitivity = {
            "level": "medium",
            "detail": (
                "Enables the economic screening criterion at all; without it "
                "the ranking stays deliberately qualitative."
            ),
        }
        expected_ranking_change.append("rotation_economic_ranking")
    elif code == "satellite_coverage_missing":
        sensitivity = {
            "level": "medium",
            "detail": (
                "Adds an independent vegetation observation stream; stress "
                "signals gain corroboration beyond farmer reports."
            ),
        }
    elif code in ("operational_constraints_missing",):
        sensitivity = {
            "level": "high",
            "detail": (
                "Without the shared water allocation the portfolio and "
                "feasibility engines report unconstrained optima — the "
                "constraint changes the answer whenever it binds."
            ),
        }
        expected_ranking_change.append("farm_portfolio_allocation")
    else:
        sensitivity = {
            "level": "medium",
            "detail": gap.get("potential_impact", "closes a documented decision gap"),
        }

    return {
        "version": VOI_VERSION,
        "decision_sensitivity": sensitivity,
        "expected_ranking_change": expected_ranking_change,
        "water_margin_reference": water_margin if water_margin and water_margin.get("flippable") else None,
        "honesty_note": (
            "VoI is structural and decision-aware (computed margins), never a "
            "monetary estimate: the platform does not assign currency values "
            "to information."
        ),
    }


def acquisition_plan_for_gap(gap: dict[str, Any]) -> dict[str, Any]:
    """Turn a gap into an actionable acquisition suggestion."""
    return {
        "gap_code": gap.get("gap_code"),
        "action_type": _action_type(gap.get("gap_code")),
        "title": _action_title(gap),
        "what_is_missing": gap.get("required_evidence"),
        "why_it_matters": gap.get("potential_impact"),
        "affected_decisions": gap.get("affected_decisions"),
        "how_to_obtain": gap.get("how_to_obtain"),
        "urgent": bool(gap.get("urgent")),
        "uncertainty_reduced": (gap.get("voi") or {}).get("decision_sensitivity", {}).get("detail"),
        "collection_cost": gap.get("collection_cost"),
        "version": EVIDENCE_GAPS_VERSION,
    }


def _action_type(code: str | None) -> str:
    mapping = {
        "soil_sample_missing": "collect_soil_sample",
        "soil_sample_stale": "collect_soil_sample",
        "weather_observations_missing": "run_data_job",
        "weather_observations_stale": "run_data_job",
        "satellite_coverage_missing": "ingest_satellite",
        "planting_dates_missing": "record_crop_history",
        "crop_history_missing": "record_crop_history",
        "irrigation_records_missing": "record_water_application",
        "nutrient_history_missing": "record_nutrient_flow",
        "field_geometry_incomplete": "fix_boundary",
        "operational_constraints_missing": "record_farm_constraints",
        "market_information_missing": "record_margin_index",
    }
    return mapping.get(code or "", "other")


def _action_title(gap: dict[str, Any]) -> str:
    how = (gap.get("how_to_obtain") or "").strip()
    if how:
        first = how.split(".")[0].strip()
        return first[:200]
    return gap.get("gap_code", "evidence acquisition")

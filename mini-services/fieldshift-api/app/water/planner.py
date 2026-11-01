"""Seasonal water planning (Milestone 6A — Phase 5).

Produces a field-level, per-season water plan for one crop assignment:

- growth-stage demand (FAO-56 stage windows over the season),
- monthly timeline (ET0 / Kc / ETc / P / Pe / Dr),
- the irrigation-requirement ladder (ETc → Pe → ΔSW → NIR → GIR → applied →
  allocation),
- deficit windows: root-zone stress windows from the RAINFED trajectory
  (Dr > RAW) and allocation shortfalls,
- the full assumptions / missing-evidence / provenance disclosure block,
- a plan checksum (sha256) over inputs + versions + values.

Method layering (ADR-0019): with soil inputs the FAO-56 root-zone balance
refines the requirement; without them the plan falls back to the FAO I&D
Paper 33 seasonal method (IN = ET crop − Pe) and says so.

An UNKNOWN water allocation is reported as unknown — never interpreted as
unlimited water.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any

from app.water.contracts import (
    MM_PER_HA_TO_M3,
    WATER_ENGINE_VERSION,
    WATER_METHODS_VERSION,
    EfficiencyInput,
    SoilWaterInputs,
    WaterEvidence,
    WaterPlanRequest,
)
from app.water.curve import KcCurve, month_days_in_season, season_months, season_etc_by_day
from app.water.effective_rainfall import effective_rainfall_mm
from app.water.knowledge import WaterKnowledge, adjusted_p
from app.water.requirements import build_requirements_ladder, mm_to_m3
from app.water.soil import (
    DrState,
    daily_root_zone_balance,
    deficit_windows,
    raw_mm,
    taw_mm,
)


class WaterPlanError(ValueError):
    pass


def _round4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def _season_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def plan_season(
    request: WaterPlanRequest,
    wk: WaterKnowledge,
    evidence: WaterEvidence,
) -> dict[str, Any]:
    """Water plan for ONE season. Never raises for missing EVIDENCE — missing
    inputs become explicit not_evaluated dimensions. Raises only on invalid
    REQUESTS (bad method, negative allocation, unknown crop knowledge)."""
    start, end = request.start_date, request.end_date
    if end < start:
        raise WaterPlanError("season end before start")
    if request.area_ha <= 0:
        raise WaterPlanError("area_ha must be positive")

    sowing = request.sowing_date or start
    sowing_note = (
        f"Sowing taken at the supplied sowing date ({sowing.isoformat()}); days of "
        "the season window before sowing carry no crop ETc (bare soil — not "
        "claimed as crop evapotranspiration)."
        if request.sowing_date and request.sowing_date != start
        else "Sowing assumed at the season start (no farmer sowing date supplied)."
    )
    assumptions: list[str] = []
    missing: list[str] = []
    sources: list[dict[str, Any]] = []
    assumptions.append(sowing_note)

    # ---------------------------------------------------------- ETc layer
    curve = wk.curve
    if curve is None:
        missing.append(wk.curve_gap_reason or "no Kc curve for this crop")
    et0_by_month = {(y, m): v for y, m, v in evidence.monthly_et0}
    p_by_month = {(y, m): v for y, m, v in evidence.monthly_precip}

    season_window_months = season_months(start, end)
    et0_missing_months = [f"{y:04d}-{m:02d}" for y, m in season_window_months if (y, m) not in et0_by_month]
    precip_missing_months = [f"{y:04d}-{m:02d}" for y, m in season_window_months if (y, m) not in p_by_month]

    etc_total_mm: float | None = None
    etc_by_day: list[float] = []
    if curve is not None:
        if et0_missing_months:
            missing.extend(
                f"ET0 missing for {label} — the crop ETc estimate is refused rather "
                "than under-reported (no month is silently dropped)"
                for label in et0_missing_months
            )
        else:
            etc_series, _used, _miss = season_etc_by_day(curve, start, end, sowing, evidence.monthly_et0)
            etc_by_day = etc_series
            etc_total_mm = round(sum(etc_series), 4)
            if request.sowing_date is None:
                assumptions.append(
                    "FAO-56 single-Kc curve reconstructed from sourced stage anchors "
                    "(linear ramp across development and late stages)."
                )
            else:
                assumptions.append(
                    "FAO-56 single-Kc curve reconstructed from sourced stage anchors; "
                    "stage windows positioned from the supplied sowing date."
                )
            assumptions.append(
                "Monthly ET0 totals distributed uniformly within each calendar month "
                "(screening estimate; daily ET0 alignment arrives with the daily water balance)."
            )

    # ------------------------------------------------ effective rainfall
    pe_info: dict[str, Any] = {}
    pe_by_month: dict[tuple[int, int], float] = {}
    pe_total_mm: float | None = None
    if request.pe_method not in ("fao_aglw_1986", "constant_fraction", "none"):
        raise WaterPlanError(f"unknown effective-rainfall method '{request.pe_method}'")
    if request.pe_method == "constant_fraction" and request.pe_fraction is None:
        raise WaterPlanError("constant_fraction requires pe_fraction")
    pe_method_info = effective_rainfall_mm(0.0, request.pe_method, fraction=request.pe_fraction)[1]
    pe_info = pe_method_info
    sources.append({
        "type": "effective_rainfall_method",
        "code": request.pe_method,
        "citation_text": pe_method_info.get("citation_text"),
        "conditions": pe_method_info.get("conditions"),
    })

    pe_missing_months = list(precip_missing_months)
    if request.pe_method != "none":
        if precip_missing_months:
            assumptions.append(
                "Precipitation evidence missing for "
                f"{', '.join(precip_missing_months)} — NO rainfall credit is assumed "
                "for those months (conservative: the requirement is never under-stated)."
            )
        for y, m in season_window_months:
            p = p_by_month.get((y, m))
            if p is None:
                continue
            v, info = effective_rainfall_mm(p, request.pe_method, fraction=request.pe_fraction)
            if v is not None:
                pe_by_month[(y, m)] = v
        if pe_by_month:
            pe_total_mm = round(sum(pe_by_month.values()), 4)
    else:
        assumptions.append(
            "Effective-rainfall method 'none': the rainfall credit is treated as "
            "unknown; the net requirement equals ETc minus soil-water contribution."
        )

    # ---------------------------------------------- root-zone balance layer
    soil = request.soil
    taw: float | None = None
    raw: float | None = None
    balance_states: list[DrState] = []
    stress_windows: list[dict[str, Any]] = []
    dsw_mm: float | None = None
    soil_basis = "no soil water-holding inputs supplied"
    p_used: float | None = None

    if soil is not None and soil.complete_for_balance():
        taw = taw_mm(soil.theta_fc, soil.theta_wp, soil.zr_m)
        mean_etc_rate = (
            (etc_total_mm / max((end - start).days + 1, 1)) if etc_total_mm is not None else None
        )
        p_used = adjusted_p(
            WaterKnowledge(
                crop_code=wk.crop_code, pack_code=wk.pack_code, pack_version=wk.pack_version,
                curve=None, curve_gap_reason=None, zr_min_m=None, zr_max_m=None,
                zr_reference_m=None, zr_source=None,
                p_table=soil.p_table, p_source=None,
                validation_status=wk.validation_status,
            ),
            mean_etc_rate,
        ) if soil.p_table is not None else None
        raw = raw_mm(taw, p_used) if p_used is not None else None
        soil_basis = (
            f"FAO-56 root-zone balance: TAW = 1000·(θFC − θWP)·Zr = {taw} mm "
            f"(source: {soil.source_label})"
            + (f", RAW = p·TAW = {raw} mm with p = {p_used}" if raw is not None else
               " (p not evaluable — stress coefficient Ks not evaluated)")
        )
        if curve is not None and etc_by_day:
            days = _season_days(start, end)
            # Daily Pe: uniform within-month distribution of the monthly Pe
            # (the FAO-33 method's native scope is monthly; the uniform
            # split is the same disclosed assumption the ET0 series uses).
            import calendar as cal

            def daily_pe(d: date) -> float:
                pe_m = pe_by_month.get((d.year, d.month))
                if pe_m is None:
                    return 0.0  # no credit when evidence is missing (disclosed)
                return pe_m / cal.monthrange(d.year, d.month)[1]

            pe_daily: list[float | None] = [daily_pe(d) for d in days]
            balance_states = daily_root_zone_balance(
                days, etc_by_day, pe_daily, None, taw, raw,
            )
            stress_windows = (
                deficit_windows(balance_states, raw) if raw is not None else []
            )
            dr_end = balance_states[-1].dr_end_mm if balance_states else 0.0
            dsw_mm = round(dr_end, 4)  # storage drawn: Dr_end − Dr_start(=0 assumption)
            if any(
                abs(s.dr_end_mm - taw) < 1e-6 for s in balance_states
            ):
                assumptions.append(
                    "The rainfed root-zone trajectory reached total depletion (Dr = TAW) "
                    "during the season — under rainfed conditions the crop experienced "
                    "stress and full ETc was not met; see the stress windows."
                )
            assumptions.append(
                "Root-zone balance is run WITHOUT irrigation on the RAINFED trajectory "
                "to size the soil-water contribution; daily water accounting and "
                "irrigation scheduling arrive with the daily water balance (backlog W-7)."
            )
            assumptions.append(
                "Capillary rise and groundwater contribution are not modelled "
                "(no evidence — disclosed, not silently assumed zero at field level)."
            )
            assumptions.append(
                "Initial root-zone depletion assumed 0 mm (soil at field capacity at "
                "sowing); a measured initial water content refines this (not yet collected)."
            )
        else:
            missing.append(
                "root-zone balance not run — crop ETc is not evaluable for this season"
            )
    else:
        missing.append(
            "soil water-holding inputs incomplete (θFC/θWP/Zr) — the soil-water "
            "contribution is not evaluated and the FAO-33 no-storage fallback is used"
        )

    if soil is not None:
        for note in soil.source_notes:
            assumptions.append(note)

    # ------------------------------------------------------ irrigation ladder
    actual_applied_mm: float | None = None  # farmer records not ingested yet
    ladder = build_requirements_ladder(
        etc_mm=etc_total_mm,
        pe_mm=pe_total_mm,
        pe_basis=(
            f"effective rainfall via '{request.pe_method}' on monthly precipitation"
            if request.pe_method != "none"
            else "no effective-rainfall method selected"
        ),
        soil_water_contribution_mm=dsw_mm,
        soil_contribution_basis=soil_basis,
        efficiency=request.efficiency,
        actual_applied_mm=actual_applied_mm,
        area_ha=request.area_ha,
    )
    nir_mm: float | None = None
    nir_step = next(s for s in ladder["steps"] if s["quantity"] == "net_irrigation_requirement")
    nir_mm = nir_step["value_mm"]

    # ------------------------------------------------------ stage aggregation
    stage_rows: list[dict[str, Any]] = []
    if curve is not None and etc_by_day:
        days = _season_days(start, end)
        dr_by_day = {s.day: s for s in balance_states}
        for stage_name, lo, hi in curve.stage_bounds():
            stage_days = [(i, d) for i, d in enumerate(days) if lo <= (d - sowing).days <= hi]
            if not stage_days:
                continue
            kc_values = [curve.kc_on_day((d - sowing).days) for _i, d in stage_days]
            etc_sum = sum(etc_by_day[i] for i, _d in stage_days)
            import calendar as cal

            pe_sum = 0.0
            for _i, d in stage_days:
                pe_m = pe_by_month.get((d.year, d.month))
                if pe_m is not None:
                    pe_sum += pe_m / cal.monthrange(d.year, d.month)[1]
            dr_state = dr_by_day.get(stage_days[-1][1])
            ks_values = [
                dr_by_day[d].ks for _i, d in stage_days
                if d in dr_by_day and dr_by_day[d].ks is not None
            ]
            in_crop_days = [(d, curve.kc_on_day((d - sowing).days)) for _i, d in stage_days if (d - sowing).days >= 0]
            kc_start = curve.kc_on_day(lo) if (stage_days[0][1] - sowing).days >= 0 else None
            stage_rows.append({
                "stage": stage_name,
                "day_window": [lo, hi],
                "dates": [stage_days[0][1].isoformat(), stage_days[-1][1].isoformat()],
                "days_in_season": len(stage_days),
                "days_in_crop": len(in_crop_days),
                "kc_mean": _round4(sum(kc for _d, kc in in_crop_days) / len(in_crop_days)) if in_crop_days else None,
                "kc_start": _round4(kc_start),
                "kc_end": _round4(curve.kc_on_day(hi)) if (stage_days[-1][1] - sowing).days >= 0 else None,
                "etc_mm": _round4(etc_sum),
                "pe_mm": _round4(pe_sum),
                "dr_end_mm": dr_state.dr_end_mm if dr_state else None,
                "ks_mean": _round4(sum(ks_values) / len(ks_values)) if ks_values else None,
                "stress_sensitivity": {
                    "p_table": wk.p_table,
                    "p_used": p_used,
                    "basis": "FAO-56 Table 22 + 0.04·(5 − ETc) adjustment" if p_used else None,
                },
            })

    # ------------------------------------------------------ monthly timeline
    monthly_rows: list[dict[str, Any]] = []
    if curve is not None and etc_by_day:
        days = _season_days(start, end)
        dr_by_day = {s.day: s for s in balance_states}
        for (y, m) in season_window_months:
            idx_days = [(i, d) for i, d in enumerate(days) if d.year == y and d.month == m]
            if not idx_days:
                continue
            etc_m = sum(etc_by_day[i] for i, _d in idx_days)
            et0_m = et0_by_month.get((y, m))
            p_m = p_by_month.get((y, m))
            pe_m = pe_by_month.get((y, m))
            in_crop_kc = [
                curve.kc_on_day((d - sowing).days)
                for _i, d in idx_days if (d - sowing).days >= 0
            ]
            pe_used_m = pe_m if pe_m is not None else 0.0
            monthly_rows.append({
                "year": y,
                "month": m,
                "days_in_season": len(idx_days),
                "et0_mm": _round4(et0_m),
                "kc_mean": _round4(sum(in_crop_kc) / len(in_crop_kc)) if in_crop_kc else None,
                "etc_mm": _round4(etc_m),
                "precip_mm": _round4(p_m),
                "effective_rainfall_mm": _round4(pe_m),
                "precip_evidence_missing": (y, m) not in p_by_month,
                "net_irrigation_mm": _round4(max(0.0, etc_m - pe_used_m)),
                "dr_end_mm": dr_by_day[idx_days[-1][1]].dr_end_mm
                if idx_days[-1][1] in dr_by_day else None,
            })

    # ------------------------------------------------------ allocation check
    allocation: dict[str, Any] = {
        "water_allocation_m3": request.water_allocation_m3,
        "status": "unknown",
        "detail": (
            "No water allocation supplied by the farmer — the available water is "
            "UNKNOWN, never interpreted as unlimited."
        ),
    }
    if request.water_allocation_m3 is not None:
        if nir_mm is None:
            allocation = {
                **allocation,
                "status": "not_evaluated",
                "detail": "Allocation supplied but the net requirement is not evaluable "
                "(missing ETc evidence) — feasibility not claimed.",
            }
        else:
            nir_m3 = mm_to_m3(nir_mm, request.area_ha)
            ratio = nir_m3 / request.water_allocation_m3
            allocation = {
                "water_allocation_m3": request.water_allocation_m3,
                "net_requirement_m3": round(nir_m3, 4),
                "coverage_ratio": _round4(ratio),
                "status": "within_allocation" if ratio <= 1.0 + 1e-9 else "deficit",
                "detail": (
                    f"Net irrigation requirement {nir_m3:.0f} m3 vs allocation "
                    f"{request.water_allocation_m3:.0f} m3 ({ratio * 100:.0f}% of allocation)."
                ),
            }
            if ratio > 1.0 + 1e-9:
                allocation["deficit_m3"] = round(nir_m3 - request.water_allocation_m3, 4)

    # ------------------------------------------------------------- sources
    if curve is not None:
        sources.append({
            "type": "crop_water_parameters",
            "source_key": curve.source_key,
            "citation_text": curve.citation_text,
            "evidence_class": curve.evidence_class,
            "pack_code": curve.pack_code,
            "pack_version": curve.pack_version,
            "validation_status": wk.validation_status,
        })
    if wk.zr_source:
        sources.append(wk.zr_source)
    if wk.p_source:
        sources.append(wk.p_source)
    if request.efficiency is not None:
        sources.append({
            "type": "irrigation_efficiency",
            "evidence_class": request.efficiency.evidence_class,
            "citation_text": request.efficiency.citation_text,
            "method_class": request.efficiency.method_class,
        })
    sources.append({
        "type": "climate_evidence",
        "feature_run_id": evidence.feature_run_id,
        "basis": evidence.basis,
        "is_synthetic": evidence.is_synthetic,
        "years_used": list(evidence.years_used),
    })

    if evidence.is_synthetic:
        assumptions.append(
            "SYNTHETIC climate evidence — every number here is a demonstration, "
            "never real farm evidence."
        )

    # ------------------------------------------------------------ assemble
    season_month_set = set(season_window_months)
    et0_total = (
        round(sum(v for (y, m), v in et0_by_month.items() if (y, m) in season_month_set), 4)
        if et0_by_month else None
    )
    precip_total = (
        round(sum(p_by_month[(y, m)] for (y, m) in season_window_months if (y, m) in p_by_month), 4)
        if any((y, m) in p_by_month for (y, m) in season_window_months) else None
    )
    totals = {
        "et0_mm": et0_total,
        "etc_mm": etc_total_mm,
        "precip_mm": precip_total,
        "effective_rainfall_mm": pe_total_mm,
        "soil_water_contribution_mm": dsw_mm,
        "net_irrigation_requirement_mm": nir_mm,
        "gross_irrigation_requirement_mm": next(
            (s["value_mm"] for s in ladder["steps"] if s["quantity"] == "gross_irrigation_requirement"),
            None,
        ),
        "volumes_m3": ladder["volumes_m3"],
    }

    deficit: list[dict[str, Any]] = [
        {
            "kind": "root_zone_stress",
            **w,
        }
        for w in stress_windows
    ]
    if allocation.get("status") == "deficit":
        deficit.append({
            "kind": "allocation_shortfall",
            "detail": allocation["detail"],
            "deficit_m3": allocation.get("deficit_m3"),
        })

    plan = {
        "season_label": request.season_label,
        "crop_code": request.crop_code,
        "season": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "sowing_date": sowing.isoformat(),
        "area_ha": request.area_ha,
        "totals": totals,
        "stages": stage_rows,
        "months": monthly_rows,
        "ladder": ladder["steps"],
        "volumes_m3": ladder["volumes_m3"],
        "allocation": allocation,
        "deficit_windows": deficit,
        "root_zone": {
            "source_label": soil.source_label if soil else "none",
            "taw_mm": taw,
            "raw_mm": raw,
            "p_table": soil.p_table if soil else None,
            "p_used": p_used,
            "dr_start_mm": 0.0 if balance_states else None,
            "dr_end_mm": balance_states[-1].dr_end_mm if balance_states else None,
            "soil_evidence_classes": {
                "theta_fc": soil.theta_fc_evidence_class if soil else None,
                "theta_wp": soil.theta_wp_evidence_class if soil else None,
                "zr": soil.zr_evidence_class if soil else None,
            },
        },
        "effective_rainfall": {
            "method": request.pe_method,
            "info": pe_info,
            "pe_by_month": {f"{y:04d}-{m:02d}": v for (y, m), v in pe_by_month.items()},
        },
        "assumptions": assumptions,
        "missing_evidence": missing,
        "sources": sources,
    }
    plan["checksum_sha256"] = _plan_checksum(plan, evidence)
    return plan


def _plan_checksum(plan: dict[str, Any], evidence: WaterEvidence) -> str:
    payload = {
        "engine": WATER_ENGINE_VERSION,
        "methods": WATER_METHODS_VERSION,
        "season": plan["season"],
        "crop": plan["crop_code"],
        "sowing": plan["sowing_date"],
        "totals": plan["totals"],
        "allocation": plan["allocation"],
        "pe_method": plan["effective_rainfall"]["method"],
        "root_zone": plan["root_zone"],
        "evidence_run": evidence.feature_run_id,
        "evidence_years": list(evidence.years_used),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_rotation_water(
    requests: list[tuple[WaterPlanRequest, WaterKnowledge, WaterEvidence]],
) -> dict[str, Any]:
    """Multi-season rotation water plan: per-season plans + rotation totals +
    comparison-ready summary. Crop assignments with non-evaluable water plans
    are REPORTED as such — never marked satisfied."""
    season_plans = [plan_season(req, wk, ev) for req, wk, ev in requests]
    evaluable = [p for p in season_plans if p["totals"]["net_irrigation_requirement_mm"] is not None]
    grand_nir_mm = round(sum(p["totals"]["net_irrigation_requirement_mm"] for p in evaluable), 4) if evaluable else None
    grand_nir_m3 = (
        round(sum(p["volumes_m3"]["net_irrigation_requirement_m3"] for p in evaluable), 4)
        if evaluable else None
    )
    total_area_ha = sum(p["area_ha"] for p in season_plans)
    return {
        "engine_version": WATER_ENGINE_VERSION,
        "methods_version": WATER_METHODS_VERSION,
        "seasons": season_plans,
        "rotation_totals": {
            "seasons_total": len(season_plans),
            "seasons_evaluable": len(evaluable),
            "net_irrigation_requirement_mm_sum": grand_nir_mm,
            "net_irrigation_requirement_m3_sum": grand_nir_m3,
            "note": (
                "Sum over EVALUABLE seasons only; unevaluable seasons are listed "
                "with their missing evidence — never zero-filled."
            ) if len(evaluable) < len(season_plans) else "All seasons evaluable.",
        },
        "area_ha": total_area_ha,
    }

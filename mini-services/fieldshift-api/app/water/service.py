"""Water plan orchestration (Milestone 6A) — the DB bridge for the pure water
engine (mirrors `app.rotation.service`).

Pipeline: validate request → load active knowledge → pick ONE evidence feature
run → build WaterEvidence (month-of-year climatology of ET0 and precipitation)
→ build SoilWaterInputs (farmer-measured, PTF-over-texture, or none) → plan
each season with the pure engine → persist an immutable snapshot.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.knowledge.service import load_knowledge
from app.rotation.service import (
    MAX_SEASONS,
    SOIL_VARIABLES,
    _pick_evidence_run,
    _validate_seasons,
    _soil_evidence,
)
from app.water import effective_rainfall as pe_mod
from app.water import planner as planner_mod
from app.water import soil as soil_mod
from app.water.contracts import (
    EFFECTIVE_RAINFALL_METHODS,
    IRRIGATION_EFFICIENCY_CLASSES,
    PTF_VERSION,
    SOIL_SOURCES,
    WATER_ENGINE_VERSION,
    WATER_METHODS_VERSION,
    EfficiencyInput,
    SoilWaterInputs,
    WaterEvidence,
    WaterPlanRequest,
)
from app.water.knowledge import water_knowledge_map
from app.water.planner import plan_rotation_water
from app.water.requirements import mm_to_m3

MIN_CLIMATE_COVERAGE = 0.9  # same floor as rotation climate evidence


def _season_climate_evidence(
    run: dbm.FeatureRun,
    season_label: str,
    start: date,
    end: date,
) -> tuple[WaterEvidence | None, list[str]]:
    """Month-of-year climatology of ET0 and precipitation for one season window
    from a single feature run (the same historical-proxy basis as rotation)."""
    import calendar as cal

    monthly: dict[str, dict[int, list[tuple[int, float]]]] = {}
    for row in run.values:
        if row.aggregation_level != "monthly" or row.value is None:
            continue
        monthly.setdefault(row.feature_code, {}).setdefault(
            row.period_start.month, []
        ).append((row.period_start.year, row.value))

    def collect_month_means(code: str) -> list[tuple[int, int, float]]:
        table = monthly.get(code, {})
        out: list[tuple[int, int, float]] = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            entries = table.get(m)
            if entries:
                out.append((y, m, sum(v for _yr, v in entries) / len(entries)))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out

    et0 = collect_month_means("reference_et0_total_monthly")
    precip = collect_month_means("precipitation_total_monthly")

    warnings: list[str] = []
    if not et0:
        warnings.append(
            f"Season '{season_label}': no monthly ET0 feature values in the evidence "
            "run — crop ETc will not be evaluable (missing evidence is never zero)."
        )
    if not precip:
        warnings.append(
            f"Season '{season_label}': no monthly precipitation feature values in the "
            "evidence run — the rainfall credit will be unknown (conservative "
            "requirement, disclosed)."
        )

    years_used = sorted({
        y
        for table in monthly.values()
        for entries in table.values()
        for y, _v in entries
    })
    evidence = WaterEvidence(
        feature_run_id=str(run.id),
        is_synthetic=bool(run.is_synthetic),
        monthly_et0=tuple(et0),
        monthly_precip=tuple(precip),
        coverage_ratio=1.0 if et0 else 0.0,
        years_used=tuple(years_used),
        basis=(
            f"month-of-year climatology from feature run {str(run.id)[:8]} "
            f"({f'years {years_used[0]}-{years_used[-1]}' if years_used else 'no years'}) "
            "— a historical proxy, NOT a forecast for the planning season."
        ),
    )
    return evidence, warnings


def _efficiency_from_payload(
    payload_eff: dict[str, Any] | None,
) -> EfficiencyInput | None:
    """Efficiency from an explicit farmer value or a method class (the FAO
    TM1 Annex I Table 8 indicative values). A method class value is a
    REFERENCE choice, recorded with its citation."""
    if payload_eff is None:
        return None
    if not isinstance(payload_eff, dict):
        raise ValidationFailed(
            "irrigation_efficiency must be an object.",
            details=[{"field": "irrigation_efficiency"}],
        )
    value = payload_eff.get("value")
    method_class = payload_eff.get("method_class")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationFailed(
                "irrigation_efficiency.value must be a number.",
                details=[{"field": "irrigation_efficiency"}],
            ) from None
        if not 0 < value <= 1:
            raise ValidationFailed(
                "irrigation_efficiency.value must be within (0, 1].",
                details=[{"field": "irrigation_efficiency", "reason": str(value)}],
            )
        return EfficiencyInput(
            value=value,
            evidence_class="farmer_reported_record",
            citation_text="Farmer-supplied field application efficiency.",
            method_class=method_class,
        )
    if method_class is not None:
        for entry in IRRIGATION_EFFICIENCY_CLASSES:
            if entry["method_class"] == method_class:
                return EfficiencyInput(
                    value=float(entry["efficiency"]),
                    evidence_class=entry["evidence_class"],
                    citation_text=entry["citation_text"],
                    method_class=method_class,
                )
        raise ValidationFailed(
            f"Unknown irrigation method class '{method_class}'.",
            details=[{
                "field": "irrigation_efficiency",
                "reason": ", ".join(e["method_class"] for e in IRRIGATION_EFFICIENCY_CLASSES),
            }],
        )
    raise ValidationFailed(
        "irrigation_efficiency needs 'value' (farmer-measured) or 'method_class'.",
        details=[{"field": "irrigation_efficiency"}],
    )


def build_soil_water_inputs(
    db: Session,
    field: dbm.Field,
    payload: dict[str, Any],
) -> tuple[SoilWaterInputs | None, list[str], dict[str, Any]]:
    """Assemble soil water-holding inputs from the requested source.

    - farmer_measured: explicit θFC/θWP (+ optional Zr/p) from the request
      (evidence class farmer_reported_record);
    - ptf_texture: Saxton & Rawls (2006) over the field's latest soil
      observations (sand/clay/SOC), with the single-layer disclosure;
    - none: no soil inputs — the FAO-33 no-storage fallback applies."""
    source = payload.get("soil_source") or "none"
    warnings: list[str] = []
    meta: dict[str, Any] = {"soil_source": source}
    if source not in SOIL_SOURCES:
        raise ValidationFailed(
            f"Unknown soil_source '{source}'.",
            details=[{"field": "soil_source", "reason": ", ".join(SOIL_SOURCES)}],
        )
    if source == "none":
        return None, warnings, meta

    if source == "farmer_measured":
        fs = payload.get("farmer_soil") or {}
        theta_fc = fs.get("theta_fc")
        theta_wp = fs.get("theta_wp")
        if theta_fc is None or theta_wp is None:
            raise ValidationFailed(
                "soil_source 'farmer_measured' requires farmer_soil.theta_fc and "
                "farmer_soil.theta_wp (m3/m3).",
                details=[{"field": "farmer_soil"}],
            )
        try:
            theta_fc, theta_wp = float(theta_fc), float(theta_wp)
        except (TypeError, ValueError):
            raise ValidationFailed(
                "farmer_soil.theta_fc/theta_wp must be numbers.",
                details=[{"field": "farmer_soil"}],
            ) from None
        if not (0 < theta_wp < theta_fc <= 0.6):
            raise ValidationFailed(
                "farmer_soil contents must satisfy 0 < θWP < θFC ≤ 0.6 (m3/m3).",
                details=[{"field": "farmer_soil", "reason": f"{theta_wp} !< {theta_fc}"}],
            )
        zr = fs.get("zr_m")
        p_table = fs.get("p_table")
        inputs = SoilWaterInputs(
            theta_fc=theta_fc,
            theta_fc_evidence_class="farmer_reported_record",
            theta_wp=theta_wp,
            theta_wp_evidence_class="farmer_reported_record",
            zr_m=float(zr) if zr is not None else None,
            zr_evidence_class="farmer_reported_record" if zr is not None else None,
            p_table=float(p_table) if p_table is not None else None,
            p_evidence_class="farmer_reported_record" if p_table is not None else None,
            source_label="farmer_measured",
            source_notes=(
                "Soil water-holding characteristics supplied by the farmer "
                "(farmer_reported_record) — not independently verified.",
            ),
        )
        meta["farmer_soil"] = fs
        return inputs, warnings, meta

    # ptf_texture
    rows = db.execute(
        select(dbm.Observation)
        .where(
            dbm.Observation.field_id == field.id,
            dbm.Observation.variable_code.in_(SOIL_VARIABLES),
            dbm.Observation.value.is_not(None),
        )
        .order_by(dbm.Observation.observed_at.desc())
        .limit(50)
    ).scalars().all()
    latest: dict[str, dbm.Observation] = {}
    for obs in rows:
        latest.setdefault(obs.variable_code, obs)
    sand = latest.get("soil_sand_content")
    clay = latest.get("soil_clay_content")
    soc = latest.get("soil_organic_carbon")
    if sand is None or clay is None:
        warnings.append(
            "soil_source 'ptf_texture' requested but the field has no sand/clay "
            "observations — the PTF estimate is refused (never extrapolated) and "
            "the plan falls back to the no-storage FAO-33 method."
        )
        return None, warnings, {**meta, "ptf": "refused_missing_texture"}
    sand_frac = float(sand.value) / 1000.0  # g/kg → fraction
    clay_frac = float(clay.value) / 1000.0
    om_percent = (
        soil_mod.organic_carbon_to_om_percent(float(soc.value)) if soc is not None else None
    )
    notes = [
        "θFC/θWP ESTIMATED by the Saxton & Rawls (2006) pedotransfer function over "
        "texture (evidence class global_soil_prediction; PTF version "
        f"{PTF_VERSION}); a texture-based model estimate, not a measurement.",
        "The PTF inputs are the field's latest soil observations. If they come from "
        "SoilGrids, they describe the 0-5 cm layer ASSUMED representative of the "
        "root zone — a single-layer extrapolation explicitly disclosed (backlog S-6).",
    ]
    if om_percent is None:
        notes.append(
            "No organic-carbon observation available — the PTF OM term is set to 0 "
            "(a disclosed simplification, typically a small effect)."
        )
        om_used = 0.0
    else:
        om_used = om_percent
        notes.append(
            "Organic matter derived from soil organic carbon via the van Bemmelen "
            "factor (OM ≈ SOC × 1.724)."
        )
    try:
        est = soil_mod.saxton_rawls_2006(sand_frac, clay_frac, om_used)
    except soil_mod.PTFDomainError as exc:
        warnings.append(
            f"The field's texture is outside the Saxton-Rawls validity domain "
            f"({exc}) — the PTF estimate is refused and the plan falls back to the "
            "no-storage FAO-33 method."
        )
        return None, warnings, {**meta, "ptf": "refused_domain"}
    meta["ptf"] = {
        "ptf_version": PTF_VERSION,
        "sand_fraction": sand_frac,
        "clay_fraction": clay_frac,
        "om_percent": round(om_used, 4),
        "theta_fc": est["theta_fc_33kPa"],
        "theta_wp": est["theta_wp_1500kPa"],
        "input_evidence_classes": {
            "sand": sand.evidence_class,
            "clay": clay.evidence_class,
            "organic_carbon": soc.evidence_class if soc else None,
        },
    }
    inputs = SoilWaterInputs(
        theta_fc=est["theta_fc_33kPa"],
        theta_fc_evidence_class="global_soil_prediction",
        theta_wp=est["theta_wp_1500kPa"],
        theta_wp_evidence_class="global_soil_prediction",
        zr_m=None,   # Zr comes from the crop knowledge (pack) in the planner caller
        zr_evidence_class=None,
        p_table=None,  # p comes from the crop knowledge (pack)
        p_evidence_class=None,
        source_label="ptf_texture",
        source_notes=tuple(notes),
    )
    return inputs, warnings, meta


def start_water_plan(
    db: Session,
    *,
    field: dbm.Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.WaterPlan:
    """Validate, execute inline and persist a water plan (202-style job)."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.WaterPlan).where(
                dbm.WaterPlan.idempotency_key == idempotency_key,
                dbm.WaterPlan.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    raw_seasons = payload.get("seasons") or []
    if not raw_seasons:
        raise ValidationFailed(
            "At least one season is required.",
            details=[{"field": "seasons"}],
        )
    season_specs = _validate_seasons(raw_seasons)
    if len(season_specs) > MAX_SEASONS:
        raise ValidationFailed(
            f"At most {MAX_SEASONS} seasons per water plan.",
            details=[{"field": "seasons"}],
        )

    # crop assignments: per-season crop_code required (knowledge-base crops)
    assignments_in = payload.get("crop_assignments") or []
    if not isinstance(assignments_in, list) or len(assignments_in) != len(season_specs):
        raise ValidationFailed(
            "crop_assignments must list one crop_code per season.",
            details=[{"field": "crop_assignments"}],
        )
    sowings_in = payload.get("sowing_dates") or {}

    pe_method = payload.get("effective_rainfall_method") or "fao_aglw_1986"
    if pe_method not in EFFECTIVE_RAINFALL_METHODS:
        raise ValidationFailed(
            f"Unknown effective_rainfall_method '{pe_method}'.",
            details=[{"field": "effective_rainfall_method"}],
        )
    pe_fraction = payload.get("pe_fraction")
    if pe_method == "constant_fraction":
        if pe_fraction is None:
            raise ValidationFailed(
                "effective_rainfall_method 'constant_fraction' requires pe_fraction.",
                details=[{"field": "pe_fraction"}],
            )
        pe_fraction = float(pe_fraction)
        if not 0 <= pe_fraction <= 1:
            raise ValidationFailed(
                "pe_fraction must be within [0, 1].",
                details=[{"field": "pe_fraction"}],
            )
    elif pe_fraction is not None:
        raise ValidationFailed(
            "pe_fraction is only valid with the constant_fraction method.",
            details=[{"field": "pe_fraction"}],
        )

    efficiency = _efficiency_from_payload(payload.get("irrigation_efficiency"))

    allocation = payload.get("water_allocation_m3")
    if allocation is not None:
        try:
            allocation = float(allocation)
        except (TypeError, ValueError):
            raise ValidationFailed(
                "water_allocation_m3 must be a number.",
                details=[{"field": "water_allocation_m3"}],
            ) from None
        if allocation <= 0:
            raise ValidationFailed(
                "water_allocation_m3 must be positive.",
                details=[{"field": "water_allocation_m3"}],
            )

    knowledge = load_knowledge(db)
    if not knowledge.crops:
        raise ValidationFailed(
            "No active knowledge pack with crops — import a knowledge pack first.",
            details=[{"field": "knowledge"}],
        )
    wk_map = water_knowledge_map(knowledge)

    soil_inputs, soil_warnings, soil_meta = build_soil_water_inputs(db, field, payload)

    area_ha = float(field.area_ha)
    label = str(payload.get("label") or "Seasonal water plan")[:120]

    run = dbm.WaterPlan(
        field_id=field.id,
        status="running",
        label=label,
        seasons=[
            {"label": s.label, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat()}
            for s in season_specs
        ],
        crop_assignments=list(assignments_in),
        methods={
            "water_engine_version": WATER_ENGINE_VERSION,
            "methods_version": WATER_METHODS_VERSION,
            "effective_rainfall_method": pe_method,
            "pe_fraction": pe_fraction,
            "irrigation_efficiency": (
                {
                    "value": efficiency.value,
                    "evidence_class": efficiency.evidence_class,
                    "method_class": efficiency.method_class,
                }
                if efficiency
                else None
            ),
            "soil_source": soil_meta.get("soil_source", "none"),
            "ptf": soil_meta.get("ptf"),
        },
        soil_inputs={
            "theta_fc": soil_inputs.theta_fc if soil_inputs else None,
            "theta_wp": soil_inputs.theta_wp if soil_inputs else None,
            "zr_m": soil_inputs.zr_m if soil_inputs else None,
            "p_table": soil_inputs.p_table if soil_inputs else None,
            "source_label": soil_inputs.source_label if soil_inputs else "none",
            "evidence_classes": (
                {
                    "theta_fc": soil_inputs.theta_fc_evidence_class,
                    "theta_wp": soil_inputs.theta_wp_evidence_class,
                    "zr": soil_inputs.zr_evidence_class,
                    "p": soil_inputs.p_evidence_class,
                }
                if soil_inputs
                else {}
            ),
        },
        water_engine_version=WATER_ENGINE_VERSION,
        methods_version=WATER_METHODS_VERSION,
        water_allocation_m3=allocation,
        request_parameters=dict(payload.get("request_parameters") or {}),
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
    )
    db.add(run)
    db.flush()

    try:
        evidence_run = _pick_evidence_run(db, field.id, payload.get("evidence_run_id"))
        warnings: list[str] = []
        if evidence_run is None:
            warnings.append(
                "No succeeded feature run exists for this field — every "
                "climate-informed dimension stays unevaluated."
            )
        if evidence_run is not None and evidence_run.is_synthetic:
            warnings.append(
                "The evidence feature run used SYNTHETIC data — every climate-informed "
                "outcome is a demonstration, never real farm evidence."
            )

        requests: list[tuple[WaterPlanRequest, Any, WaterEvidence]] = []
        not_evaluated: dict[str, list[str]] = {}
        season_results: list[dict[str, Any]] = []
        feature_run_ids: list[str] = []
        fallback_soil = None
        if soil_inputs is not None and soil_inputs.zr_m is None:
            # PTF/farmer path without explicit Zr: the crop's pack rooting depth
            # is used per season (disclosed); store the decision here.
            fallback_soil = soil_inputs

        for season_spec, crop_assignment in zip(season_specs, assignments_in):
            crop_code = (crop_assignment or {}).get("crop_code") if isinstance(crop_assignment, dict) else crop_assignment
            if not crop_code:
                raise ValidationFailed(
                    f"Season '{season_spec.label}' needs a crop_code.",
                    details=[{"field": "crop_assignments"}],
                )
            crop = knowledge.crops.get(crop_code)
            if crop is None:
                raise ValidationFailed(
                    f"Unknown crop_code '{crop_code}' — the knowledge base has no such crop.",
                    details=[{"field": "crop_assignments", "reason": crop_code}],
                )
            wk = wk_map[crop_code]
            if evidence_run is None:
                season_evidence = WaterEvidence(
                    feature_run_id="none", is_synthetic=False,
                    basis="no feature run available — no climate evidence",
                )
                warnings.append(
                    f"Season '{season_spec.label}': planned without climate evidence; "
                    "all water quantities not evaluated."
                )
            else:
                season_evidence, ev_warnings = _season_climate_evidence(
                    evidence_run, season_spec.label, season_spec.start_date, season_spec.end_date
                )
                warnings.extend(ev_warnings)
                if str(evidence_run.id) not in feature_run_ids:
                    feature_run_ids.append(str(evidence_run.id))

            sowing_raw = sowings_in.get(season_spec.label) if isinstance(sowings_in, dict) else None
            sowing_date = None
            if sowing_raw:
                try:
                    sowing_date = date.fromisoformat(str(sowing_raw))
                except ValueError:
                    raise ValidationFailed(
                        f"sowing_dates['{season_spec.label}'] must be an ISO date.",
                        details=[{"field": "sowing_dates"}],
                    ) from None

            soil_for_season = None
            if fallback_soil is not None:
                # Zr from the crop's verified pack range midpoint (disclosed)
                zr = wk.zr_reference_m
                if zr is None and fallback_soil.zr_m is not None:
                    zr = fallback_soil.zr_m
                soil_for_season = SoilWaterInputs(
                    theta_fc=fallback_soil.theta_fc,
                    theta_fc_evidence_class=fallback_soil.theta_fc_evidence_class,
                    theta_wp=fallback_soil.theta_wp,
                    theta_wp_evidence_class=fallback_soil.theta_wp_evidence_class,
                    zr_m=zr,
                    zr_evidence_class="knowledge_pack_table22_midpoint" if zr is not None else None,
                    p_table=wk.p_table if wk.p_table is not None else fallback_soil.p_table,
                    p_evidence_class=wk.p_source.get("evidence_class") if (wk.p_table is not None and wk.p_source) else None,
                    source_label=fallback_soil.source_label,
                    source_notes=fallback_soil.source_notes,
                )
            elif soil_inputs is not None:
                soil_for_season = soil_inputs

            request = WaterPlanRequest(
                season_label=season_spec.label,
                start_date=season_spec.start_date,
                end_date=season_spec.end_date,
                crop_code=crop_code,
                sowing_date=sowing_date,
                pe_method=pe_method,
                pe_fraction=pe_fraction,
                soil=soil_for_season,
                efficiency=efficiency,
                water_allocation_m3=allocation,
                area_ha=area_ha,
            )
            requests.append((request, wk, season_evidence))

        plan_result = plan_rotation_water(requests)
        season_results = plan_result["seasons"]

        for sp in season_results:
            if sp["missing_evidence"]:
                not_evaluated[sp["season_label"]] = sp["missing_evidence"]

        run.status = "succeeded"
        run.result = plan_result
        run.warnings = warnings
        run.not_evaluated = not_evaluated
        run.feature_run_ids = feature_run_ids
        run.knowledge_pack_refs = [dict(r) for r in knowledge.pack_refs]
        run.checksum_sha256 = _plan_snapshot_checksum(plan_result, run)
        run.completed_at = datetime.now(UTC)
        db.flush()
    except ValidationFailed:
        run.status = "failed"
        run.error_summary = "validation failed"
        run.completed_at = datetime.now(UTC)
        raise
    except Exception as exc:  # noqa: BLE001 — job failure accounting
        run.status = "failed"
        run.error_summary = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(UTC)
        db.flush()
        raise
    return run


def _plan_snapshot_checksum(plan_result: dict[str, Any], run: dbm.WaterPlan) -> str:
    import hashlib
    import json

    payload = {
        "engine": run.water_engine_version,
        "methods": run.methods_version,
        "seasons": run.seasons,
        "assignments": run.crop_assignments,
        "methods_cfg": run.methods,
        "soil": run.soil_inputs,
        "allocation": run.water_allocation_m3,
        "totals": [
            s["totals"] for s in plan_result.get("seasons", [])
        ],
        "packs": run.knowledge_pack_refs,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- serializers


def plan_payload(plan: dbm.WaterPlan, *, include_result: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(plan.id),
        "field_id": str(plan.field_id),
        "status": plan.status,
        "label": plan.label,
        "seasons": plan.seasons,
        "crop_assignments": plan.crop_assignments,
        "methods": plan.methods,
        "soil_inputs": plan.soil_inputs,
        "warnings": plan.warnings,
        "not_evaluated": plan.not_evaluated,
        "water_engine_version": plan.water_engine_version,
        "methods_version": plan.methods_version,
        "feature_run_ids": plan.feature_run_ids,
        "knowledge_pack_refs": plan.knowledge_pack_refs,
        "water_allocation_m3": plan.water_allocation_m3,
        "checksum_sha256": plan.checksum_sha256,
        "error_summary": plan.error_summary,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "status_url": f"/api/v1/water-plans/{plan.id}",
    }
    if include_result:
        data["result"] = plan.result
    return data

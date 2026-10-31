"""Rotation run orchestration (Milestone 5) — the only bridge between the DB
world and the pure decision core.

Pipeline: validate request → load active knowledge → build FarmContext
(climate evidence from ONE feature run, soil observations, crop history,
farmer constraints) → generate per-season candidates → build problem →
baseline + optimized strategy profiles → evaluate criteria → normalize within
the strategy set → Pareto → constraint checks → explanations → persist
snapshot (runs + strategies) with full version/provenance refs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.knowledge.service import load_knowledge
from app.rotation import candidates as candidates_mod
from app.rotation import constraints as constraints_mod
from app.rotation import objectives as objectives_mod
from app.rotation import optimizer as optimizer_mod
from app.rotation.explain import build_explanations
from app.rotation.problem import (
    ClimateEvidence,
    FarmContext,
    RANDOM_SEED,
    RotationProblem,
    SeasonSpec,
    SoilEvidence,
    StrategySolution,
    ROTATION_ENGINE_VERSION,
    SOLVER_NAME,
)

MAX_SEASONS = 4
MIN_CLIMATE_COVERAGE = 0.9
CLIMATE_FEATURE_CODES = {
    "precipitation": "precipitation_total_monthly",
    "tmean": "air_temperature_mean_monthly",
    "hot_days": "hot_days_35c_count_monthly",
    "et0": "reference_et0_total_monthly",
}
SOIL_VARIABLES = [
    "soil_ph",
    "soil_organic_carbon",
    "soil_sand_content",
    "soil_clay_content",
    "soil_bulk_density",
]


def _validate_seasons(raw: list[dict[str, Any]]) -> list[SeasonSpec]:
    if not raw:
        raise ValidationFailed(
            "At least one planning season is required.",
            details=[{"field": "seasons"}],
        )
    if len(raw) > MAX_SEASONS:
        raise ValidationFailed(
            f"At most {MAX_SEASONS} planning seasons per run.",
            details=[{"field": "seasons"}],
        )
    seasons: list[SeasonSpec] = []
    labels: set[str] = set()
    for item in raw:
        label = str(item.get("label") or "").strip()
        if not label or len(label) > 60:
            raise ValidationFailed(
                "Season labels must be 1-60 characters.",
                details=[{"field": "seasons", "reason": str(item)[:80]}],
            )
        if label in labels:
            raise ValidationFailed(
                f"Duplicate season label '{label}'.",
                details=[{"field": "seasons", "reason": label}],
            )
        labels.add(label)
        try:
            start = date.fromisoformat(str(item["start_date"]))
            end = date.fromisoformat(str(item["end_date"]))
        except (KeyError, ValueError):
            raise ValidationFailed(
                "Seasons need start_date and end_date (ISO dates).",
                details=[{"field": "seasons", "reason": label}],
            ) from None
        if start > end:
            raise ValidationFailed(
                f"Season '{label}' start_date is after end_date.",
                details=[{"field": "seasons", "reason": label}],
            )
        if (end - start).days > 400:
            raise ValidationFailed(
                f"Season '{label}' is longer than 400 days — split it.",
                details=[{"field": "seasons", "reason": label}],
            )
        seasons.append(SeasonSpec(label=label, start_date=start, end_date=end))
    return seasons


def _pick_evidence_run(db: Session, field_id: Any, explicit_id: str | None) -> dbm.FeatureRun | None:
    if explicit_id:
        run = db.get(dbm.FeatureRun, uuid.UUID(explicit_id))
        if run is None or str(run.field_id) != str(field_id):
            raise NotFound("Feature run not found for this field.")
        if run.status != "succeeded":
            raise ValidationFailed(
                "The referenced feature run has not succeeded.",
                details=[{"field": "evidence_run_id", "reason": run.status}],
            )
        return run
    return db.scalar(
        select(dbm.FeatureRun)
        .where(dbm.FeatureRun.field_id == field_id, dbm.FeatureRun.status == "succeeded")
        .order_by(dbm.FeatureRun.completed_at.desc())
        .limit(1)
    )


def _season_climate(
    run: dbm.FeatureRun, season: SeasonSpec
) -> ClimateEvidence | None:
    """Aggregate the run's monthly feature values over one planning season as a
    MONTH-OF-YEAR climatology (historical proxy — planning seasons are usually
    in the future; no forecast is claimed).

    Coverage = fraction of season days whose month-of-year has any covered
    value in the run; below MIN_CLIMATE_COVERAGE the season's climate evidence
    is None (the dimension is unevaluated, never approximated)."""
    monthly: dict[str, dict[int, list[tuple[int, float]]]] = {}  # code -> month -> [(year, value)]
    for row in run.values:
        if row.aggregation_level != "monthly" or row.value is None:
            continue
        monthly.setdefault(row.feature_code, {}).setdefault(
            row.period_start.month, []
        ).append((row.period_start.year, row.value))

    import calendar as cal

    def months_in_season(season: SeasonSpec) -> list[tuple[int, int, int]]:
        """(year, month, days of that month inside the season)."""
        out = []
        y, m = season.start_date.year, season.start_date.month
        while (y, m) <= (season.end_date.year, season.end_date.month):
            if y == season.start_date.year and m == season.start_date.month:
                month_start = season.start_date
            else:
                month_start = date(y, m, 1)
            if y == season.end_date.year and m == season.end_date.month:
                month_end = season.end_date
            else:
                month_end = date(y, m, cal.monthrange(y, m)[1])
            out.append((y, m, (month_end - month_start).days + 1))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out

    month_days = months_in_season(season)
    total_days = sum(d for _, _, d in month_days)

    years_used = sorted(
        {
            y
            for table in monthly.values()
            for entries in table.values()
            for y, _v in entries
        }
    )

    def collect(code: str, mode: str) -> tuple[float | None, int]:
        """Season aggregate of month-of-year climatological means.

        mode='total' (precip, ET0, hot-day counts): monthly TOTALS scaled by
        the fraction of that month inside the season, summed.
        mode='mean' (temperature): monthly means day-weighted over the season.
        Returns (value, days covered by present months)."""
        table = monthly.get(code, {})
        acc = 0.0
        covered = 0
        for y, m, days in month_days:
            entries = table.get(m)
            if entries:
                mean = sum(v for _yr, v in entries) / len(entries)
                if mode == "total":
                    frac = days / cal.monthrange(y, m)[1]
                    acc += mean * frac
                else:
                    acc += mean * days
                covered += days
        if mode == "mean":
            acc = acc / total_days if total_days else 0.0
        return acc, covered

    warnings: list[str] = []
    precip_total, covered = collect(CLIMATE_FEATURE_CODES["precipitation"], "total")
    tmean_wsum, covered_t = collect(CLIMATE_FEATURE_CODES["tmean"], "mean")
    hot_days, covered_h = collect(CLIMATE_FEATURE_CODES["hot_days"], "total")
    et0_total, covered_e = collect(CLIMATE_FEATURE_CODES["et0"], "total")

    coverage = covered / total_days if total_days else 0.0

    monthly_et0: list[tuple[int, int, float]] = []
    et0_table = monthly.get(CLIMATE_FEATURE_CODES["et0"], {})
    for y, m, _days in month_days:
        entries = et0_table.get(m)
        if entries:
            monthly_et0.append((y, m, sum(v for _yr, v in entries) / len(entries)))

    if coverage < MIN_CLIMATE_COVERAGE:
        return None

    tmean = tmean_wsum if covered_t == total_days else (
        tmean_wsum * total_days / covered_t if covered_t else None
    )
    if covered_t < total_days:
        warnings.append("temperature months incomplete — mean weighted by covered days")
    hot = round(hot_days, 1) if covered_h == total_days else None
    if covered_h < total_days and hot is None:
        warnings.append("hot-day counts incomplete — not evaluated for this season")
    et0 = et0_total if covered_e == total_days else None
    if covered_e < total_days and et0 is None:
        warnings.append("ET0 months incomplete — water estimates not evaluated")

    year_note = (
        f"years {years_used[0]}-{years_used[-1]}" if len(years_used) > 1
        else f"year {years_used[0]}" if years_used else "no years"
    )
    return ClimateEvidence(
        feature_run_id=str(run.id),
        is_synthetic=bool(run.is_synthetic),
        season_precipitation_mm=round(precip_total, 2) if covered else None,
        season_mean_temp_degC=round(tmean, 2) if tmean is not None else None,
        season_mean_tmax_degC=None,
        season_hot_days_35c=hot,
        season_et0_mm=round(et0, 2) if et0 is not None else None,
        monthly_et0=tuple(monthly_et0),
        coverage_ratio=round(coverage, 4),
        years_used=tuple(years_used),
        basis=(
            f"month-of-year climatology from feature run {str(run.id)[:8]} "
            f"({year_note}) — a historical proxy, NOT a forecast for the "
            "planning season."
        ),
        warnings=tuple(warnings),
    )


def _soil_evidence(db: Session, field_id: Any) -> tuple[SoilEvidence | None, str | None]:
    rows = db.execute(
        select(dbm.Observation)
        .where(
            dbm.Observation.field_id == field_id,
            dbm.Observation.variable_code.in_(SOIL_VARIABLES),
            dbm.Observation.value.is_not(None),
        )
        .order_by(dbm.Observation.observed_at.desc())
        .limit(50)
    ).scalars().all()
    latest: dict[str, dbm.Observation] = {}
    for obs in rows:
        latest.setdefault(obs.variable_code, obs)
    if not latest:
        return None, None
    evidence_classes = sorted({o.evidence_class or "unknown" for o in latest.values()})

    def val(code: str) -> tuple[float, str] | None:
        obs = latest.get(code)
        if obs is None or obs.value is None:
            return None
        return (float(obs.value), obs.evidence_class or "unknown")

    soil = SoilEvidence(
        ph=val("soil_ph"),
        organic_carbon_g_kg=val("soil_organic_carbon"),
        clay_g_kg=val("soil_clay_content"),
        sand_g_kg=val("soil_sand_content"),
        bulk_density=val("soil_bulk_density"),
    )
    return soil, ", ".join(evidence_classes)


def build_farm_context(
    db: Session,
    field: dbm.Field,
    seasons: list[SeasonSpec],
    evidence_run_id: str | None,
    hemisphere: str,
) -> tuple[FarmContext, list[str], list[str], dbm.FeatureRun | None]:
    warnings: list[str] = []
    run = _pick_evidence_run(db, field.id, evidence_run_id)
    climate_by_season: dict[str, ClimateEvidence] = {}
    climate_run_refs: dict[str, str] = {}
    if run is None:
        warnings.append(
            "No succeeded feature run exists for this field — climate dimensions are "
            "unevaluated (missing evidence is never treated as zero)."
        )
    else:
        for season in seasons:
            evidence = _season_climate(run, season)
            if evidence is None:
                warnings.append(
                    f"Season '{season.label}': climate coverage below "
                    f"{MIN_CLIMATE_COVERAGE:.0%} in the evidence run — climate dimensions "
                    "unevaluated for this season."
                )
            else:
                climate_by_season[season.label] = evidence
                climate_run_refs[season.label] = str(run.id)
                for w in evidence.warnings:
                    warnings.append(f"Season '{season.label}': {w}")
        if run.is_synthetic:
            warnings.append(
                "The evidence feature run used SYNTHETIC data — every climate-informed "
                "outcome is a demonstration, never real farm evidence."
            )

    soil, soil_class = _soil_evidence(db, field.id)

    history_rows = db.scalars(
        select(dbm.CropHistory)
        .where(dbm.CropHistory.field_id == field.id)
        .order_by(dbm.CropHistory.sowing_date.asc().nullslast(), dbm.CropHistory.created_at.asc())
    ).all()
    crop_code_by_id = {
        c.id: c.crop_code
        for c in db.scalars(select(dbm.Crop)).all()
    }
    history: list[dict[str, Any]] = []
    for h in history_rows:
        history.append({
            "id": str(h.id),
            "season_label": h.season_label,
            "crop_code": crop_code_by_id.get(h.crop_id) if h.crop_id else None,
            "crop_label": h.crop_label,
            "sowing_date": h.sowing_date.isoformat() if h.sowing_date else None,
            "harvest_date": h.harvest_date.isoformat() if h.harvest_date else None,
        })

    constraints_rows = db.scalars(
        select(dbm.FarmConstraint).where(dbm.FarmConstraint.farm_id == field.farm_id)
    ).all()
    market_exclusions: list[str] = []
    equipment_limits: list[str] = []
    water_allocation: float | None = None
    margin_index: dict[str, float] = {}
    for c in constraints_rows:
        if c.constraint_code == "market_exclusion" and c.value_text:
            market_exclusions.extend(
                [p.strip() for p in c.value_text.split(",") if p.strip()]
            )
        elif c.constraint_code == "equipment_limitation" and c.value_text:
            equipment_limits.extend(
                [p.strip() for p in c.value_text.split(",") if p.strip()]
            )
        elif c.constraint_code == "water_allocation_m3_per_season" and c.value_numeric is not None:
            water_allocation = float(c.value_numeric)
        elif c.constraint_code == "market_margin_index" and c.value_text and c.value_numeric is not None:
            margin_index[c.value_text.strip()] = float(c.value_numeric)

    farm = FarmContext(
        field_id=str(field.id),
        farm_id=str(field.farm_id),
        area_ha=float(field.area_ha),
        country_code=field.farm.country_code,
        hemisphere=hemisphere,
        seasons=tuple(seasons),
        soil=soil,
        climate_by_season=climate_by_season,
        climate_run_refs=climate_run_refs,
        history=tuple(history),
        market_exclusions=tuple(sorted(set(market_exclusions))),
        equipment_limits=tuple(sorted(set(equipment_limits))),
        water_allocation_m3=water_allocation,
        margin_index_by_crop=margin_index,
        synthetic_evidence_in_use=bool(run.is_synthetic) if run else False,
        soil_evidence_class=soil_class,
    )
    return farm, warnings, [str(h["id"]) for h in history], run


def _baseline_assignment(
    seasons: list[SeasonSpec], history: tuple[dict[str, Any], ...]
) -> tuple[tuple[str, str | None], ...]:
    assignment: list[tuple[str, str | None]] = []
    for season in seasons:
        crop_code = None
        for h in history:
            if h.get("season_label") == season.label:
                crop_code = h.get("crop_code")
                break
        if crop_code is None:
            for h in history:
                sow = h.get("sowing_date")
                harv = h.get("harvest_date")
                if sow and harv:
                    if date.fromisoformat(sow) <= season.end_date and date.fromisoformat(
                        harv
                    ) >= season.start_date:
                        crop_code = h.get("crop_code")
                        break
        assignment.append((season.label, crop_code))
    return tuple(assignment)


def _solution_checksum(
    solution: StrategySolution, problem: RotationProblem
) -> str:
    payload = {
        "strategy": solution.strategy_key,
        "assignment": [[lbl, cc] for lbl, cc in solution.assignment],
        "objective": solution.objective_value,
        "criteria": [
            [c.criterion_code, c.raw_value, c.normalized] for c in solution.criteria
        ],
        "problem": problem.checksum(),
        "engine": ROTATION_ENGINE_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def start_rotation_run(
    db: Session,
    *,
    field: dbm.Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.RotationRun:
    """Validate, execute inline and persist a rotation run (202-style job)."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.RotationRun).where(dbm.RotationRun.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

    seasons = _validate_seasons(payload.get("seasons") or [])
    hemisphere = payload.get("hemisphere") or "north"
    if hemisphere not in ("north", "south"):
        raise ValidationFailed(
            "hemisphere must be 'north' or 'south'.",
            details=[{"field": "hemisphere", "reason": hemisphere}],
        )

    requested_profiles = payload.get("strategy_profiles") or list(optimizer_mod.DEFAULT_PROFILES)
    if not isinstance(requested_profiles, list) or not requested_profiles:
        raise ValidationFailed(
            "strategy_profiles must be a non-empty list.",
            details=[{"field": "strategy_profiles"}],
        )
    known = set(optimizer_mod.DEFAULT_PROFILES) | {"custom"}
    for p in requested_profiles:
        if p not in known:
            raise ValidationFailed(
                f"Unknown strategy profile '{p}'.",
                details=[{"field": "strategy_profiles", "reason": p}],
            )
    custom_weights = payload.get("custom_weights") or {}
    if "custom" in requested_profiles:
        if not custom_weights:
            raise ValidationFailed(
                "The 'custom' profile needs custom_weights.",
                details=[{"field": "custom_weights"}],
            )
        for code, w in custom_weights.items():
            if code not in objectives_mod.CRITERION_FUNCS:
                raise ValidationFailed(
                    f"Unknown criterion '{code}' in custom_weights.",
                    details=[{"field": "custom_weights", "reason": code}],
                )
            if not isinstance(w, (int, float)) or w < 0:
                raise ValidationFailed(
                    f"Custom weight for '{code}' must be a non-negative number.",
                    details=[{"field": "custom_weights", "reason": code}],
                )
        if sum(float(w) for w in custom_weights.values()) <= 0:
            raise ValidationFailed(
                "custom_weights must sum to a positive value.",
                details=[{"field": "custom_weights"}],
            )

    water_allocation = payload.get("water_allocation_m3")
    if water_allocation is not None:
        try:
            water_allocation = float(water_allocation)
        except (TypeError, ValueError):
            raise ValidationFailed(
                "water_allocation_m3 must be a number.",
                details=[{"field": "water_allocation_m3"}],
            ) from None
        if water_allocation <= 0:
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

    run = dbm.RotationRun(
        field_id=field.id,
        status="running",
        seasons=[
            {"label": s.label, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat()}
            for s in seasons
        ],
        strategy_profiles=list(requested_profiles),
        water_allocation_m3=water_allocation,
        knowledge_pack_refs=[dict(r) for r in knowledge.pack_refs],
        rotation_engine_version=ROTATION_ENGINE_VERSION,
        solver_name=SOLVER_NAME,
        random_seed=RANDOM_SEED,
        request_parameters=dict(payload.get("request_parameters") or {}),
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    try:
        farm, warnings, history_ids, evidence_run = build_farm_context(
            db, field, seasons, payload.get("evidence_run_id"), hemisphere
        )
        run.feature_run_ids = (
            [str(evidence_run.id)] if evidence_run is not None else []
        )
        run.crop_history_ids = history_ids

        assessments = candidates_mod.generate_candidates(knowledge, farm)
        baseline_assignment = _baseline_assignment(seasons, farm.history)
        problem = RotationProblem(
            field_id=str(field.id),
            seasons=tuple(seasons),
            candidates=assessments,
            knowledge=knowledge,
            farm=farm,
            water_allocation_m3=water_allocation,
            baseline_assignment=baseline_assignment,
            synthetic_evidence=farm.synthetic_evidence_in_use,
        )
        run.knowledge_pack_refs = [dict(r) for r in knowledge.pack_refs]

        solutions: list[StrategySolution] = []
        infeasible_profiles: list[dict[str, Any]] = []
        baseline = optimizer_mod.build_baseline_solution(problem)
        solutions.append(baseline)

        for profile in requested_profiles:
            weights = (
                {k: float(v) for k, v in custom_weights.items()}
                if profile == "custom"
                else dict(optimizer_mod.PROFILE_WEIGHTS[profile])
            )
            result = optimizer_mod.optimize_strategy(problem, profile, weights)
            if isinstance(result, optimizer_mod.InfeasibleResult):
                infeasible_profiles.append({
                    "strategy_key": profile,
                    "conflicts": result.conflicts,
                    "notes": result.notes,
                })
                continue
            solutions.append(result)

        # evaluate + normalize + objective + pareto
        evaluated: list[StrategySolution] = []
        for sol in solutions:
            criteria = objectives_mod.evaluate_criteria(problem, dict(sol.assignment))
            checks = constraints_mod.check_all(problem, dict(sol.assignment))
            evaluated.append(
                StrategySolution(
                    strategy_key=sol.strategy_key,
                    strategy_kind=sol.strategy_kind,
                    is_baseline=sol.is_baseline,
                    profile_weights=sol.profile_weights,
                    weights_effective=sol.weights_effective,
                    skipped_weights=sol.skipped_weights,
                    assignment=sol.assignment,
                    objective_value=sol.objective_value,
                    criteria=criteria,
                    constraints_checked=tuple(checks),
                    evidence_coverage=None,
                    solver_status=sol.solver_status,
                    solver_wall_time_ms=sol.solver_wall_time_ms,
                )
            )
        objectives_mod.normalize_within_set(evaluated)
        final: list[StrategySolution] = []
        for sol in evaluated:
            objective, effective, skipped = objectives_mod.weighted_objective(sol)
            final.append(
                StrategySolution(
                    strategy_key=sol.strategy_key,
                    strategy_kind=sol.strategy_kind,
                    is_baseline=sol.is_baseline,
                    profile_weights=sol.profile_weights,
                    weights_effective=effective,
                    skipped_weights=skipped,
                    assignment=sol.assignment,
                    objective_value=objective,
                    criteria=sol.criteria,
                    constraints_checked=sol.constraints_checked,
                    evidence_coverage=objectives_mod.evidence_coverage_of(sol),
                    solver_status=sol.solver_status,
                    solver_wall_time_ms=sol.solver_wall_time_ms,
                )
            )
        objectives_mod.compute_pareto(final)
        solutions = final

        # persist strategies
        not_evaluated: dict[str, Any] = {}
        for season_label, season_assessments in assessments.items():
            unevaluated = {
                code: [d["code"] for d in a.unevaluated_dimensions]
                for code, a in season_assessments.items()
                if a.status == "unevaluated" or a.unevaluated_dimensions
            }
            if unevaluated:
                not_evaluated[season_label] = unevaluated

        run.not_evaluated = not_evaluated
        run.warnings = warnings
        solver_status = None
        optimized_solutions = [s for s in solutions if not s.is_baseline]
        if infeasible_profiles and not optimized_solutions:
            solver_status = "infeasible"
        elif infeasible_profiles:
            solver_status = "feasible"
        elif optimized_solutions:
            solver_status = "optimal"
        else:
            solver_status = "unknown"
        run.solver_status = solver_status
        run.infeasibility_details = {
            "profiles": infeasible_profiles,
            "note": (
                "Infeasible profiles are reported explicitly; no hard constraint was "
                "relaxed to produce the other strategies."
            )
            if infeasible_profiles
            else {},
        }

        for sol in solutions:
            explanations = build_explanations(problem, sol, solutions)
            explanations["_weights_effective"] = sol.weights_effective
            explanations["_skipped_weights"] = sol.skipped_weights
            db.add(
                dbm.RotationStrategy(
                    run_id=run.id,
                    strategy_key=sol.strategy_key,
                    strategy_kind=sol.strategy_kind,
                    is_baseline=sol.is_baseline,
                    profile_weights=sol.profile_weights,
                    assignment=[
                        {"season_label": lbl, "crop_code": cc} for lbl, cc in sol.assignment
                    ],
                    objective_value=sol.objective_value,
                    criteria=[
                        {
                            "criterion_code": c.criterion_code,
                            "raw_value": c.raw_value,
                            "unit": c.unit,
                            "direction": c.direction,
                            "normalized": c.normalized,
                            "evaluable": c.evaluable,
                            "missing_evidence": list(c.missing_evidence),
                            "derivation": c.derivation,
                        }
                        for c in sol.criteria
                    ],
                    constraints_checked=[
                        {
                            "constraint_code": c.constraint_code,
                            "status": c.status,
                            "description": c.description,
                            "detail": c.detail,
                            "rule_codes": list(c.rule_codes),
                            "source_refs": list(c.source_refs),
                        }
                        for c in sol.constraints_checked
                    ],
                    pareto={
                        "on_front": sol.on_pareto_front,
                        "dominated_by": list(sol.dominated_by),
                        "dominates": list(sol.dominates),
                    },
                    explanations=explanations,
                    evidence_coverage=sol.evidence_coverage,
                    checksum_sha256=_solution_checksum(sol, problem),
                )
            )
        run.status = "succeeded"
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


def problem_seed() -> int:
    return RANDOM_SEED


# ---------------------------------------------------------------- serializers


def run_payload(run: dbm.RotationRun, *, include_strategies: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "solver_status": run.solver_status,
        "seasons": run.seasons,
        "strategy_profiles": run.strategy_profiles,
        "water_allocation_m3": run.water_allocation_m3,
        "knowledge_pack_refs": run.knowledge_pack_refs,
        "feature_run_ids": run.feature_run_ids,
        "crop_history_ids": run.crop_history_ids,
        "rotation_engine_version": run.rotation_engine_version,
        "solver_name": run.solver_name,
        "solver_version": run.solver_version,
        "random_seed": run.random_seed,
        "infeasibility_details": run.infeasibility_details,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "records_written": len(run.strategies) if run.strategies else 0,
        "error_summary": run.error_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "status_url": f"/api/v1/rotation-runs/{run.id}",
    }
    if include_strategies:
        data["strategies"] = [strategy_payload(s) for s in run.strategies]
    return data


def strategy_payload(s: dbm.RotationStrategy) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "strategy_key": s.strategy_key,
        "strategy_kind": s.strategy_kind,
        "is_baseline": s.is_baseline,
        "profile_weights": s.profile_weights,
        "weights_effective": s.explanations.get("_weights_effective", {}),
        "skipped_weights": s.explanations.get("_skipped_weights", {}),
        "assignment": s.assignment,
        "objective_value": s.objective_value,
        "criteria": s.criteria,
        "constraints_checked": s.constraints_checked,
        "pareto": s.pareto,
        "explanations": s.explanations,
        "evidence_coverage": s.evidence_coverage,
        "checksum_sha256": s.checksum_sha256,
    }


def candidate_payload(
    season_label: str, assessments: dict[str, Any]
) -> dict[str, Any]:
    return {
        "season_label": season_label,
        "candidates": [
            {
                "crop_code": a.crop_code,
                "status": a.status,
                "reasons": list(a.reasons),
                "unevaluated_dimensions": list(a.unevaluated_dimensions),
                "water_requirement_mm": a.water_requirement_mm,
                "water_estimate_assumptions": list(a.water_estimate_assumptions),
                "calendar_windows_matched": list(a.calendar_windows_matched),
            }
            for a in assessments.values()
        ],
    }

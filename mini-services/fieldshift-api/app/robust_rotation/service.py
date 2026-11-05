"""Robust multi-scenario rotation orchestration (Milestone 7.5).

Builds, executes and persists robust rotation evaluations over sets of
IMMUTABLE M7.3 execution runs. The optimization reuses the M5 CP-SAT
infrastructure (deterministic, assumption-based infeasibility) through
`app.robust_rotation.engine`; per-scenario evaluation reuses the EXISTING M5
post-hoc code (`objectives.evaluate_criteria`, `constraints.check_all`,
`normalize_within_set`, `weighted_objective`, `compute_pareto`) — no
agronomic calculation is duplicated.

Nothing in this module mutates parent artifacts: observations, feature runs,
Field States, finalized scenario definitions and M7.3 execution results are
read-only inputs; all outputs land in the scenario_sets / robust_rotation_*
analytical layer.

Flow (docs/m7/m7_5/M7_5_ROBUST_METHOD.md):

    Scenario Set (compatible, result-bearing M7.3 executions)
        ↓  verify member pins against live rows
    Resolve Seasons + Profiles            (water allocations rejected)
        ↓  per-scenario FarmContext       (climate from derived features)
    Per-scenario candidate assessments    (M5 generate_candidates, reused)
        ↓  cross-scenario admissible pool  (intersection + exclusions)
    ONE shared-plan solve per profile     (maximin steering, CP-SAT)
        ↓  per-scenario post-hoc evaluation (M5 code, reused)
    Worst-case objective / regret / robust feasibility
        ↓
    Persist Immutable Results             (trigger-frozen rows)
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as dbm
from app.field_state.manifest import sha256_of_document
from app.knowledge.service import load_knowledge
from app.rotation import candidates as candidates_mod
from app.rotation import constraints as constraints_mod
from app.rotation import objectives as objectives_mod
from app.rotation import optimizer as optimizer_mod
from app.rotation.problem import (
    RANDOM_SEED,
    ROTATION_ENGINE_VERSION,
    SOLVER_NAME,
    RotationProblem,
    StrategySolution,
    solver_version,
)
from app.rotation.service import (
    ROTATION_ENGINE_VERSION,
    _baseline_assignment,
    _validate_seasons,
    build_farm_context,
)
from app.robust_rotation import contracts as rc
from app.robust_rotation import climate as rclimate
from app.robust_rotation.engine import intersection_candidates, optimize_shared_plan

logger = logging.getLogger("fieldshift.robust")

RESULT_RUN_STATUSES = ("succeeded", "completed_with_limitations")


def _scenario_verdict(
    checks: list[dict[str, Any]], crop_admissibility: list[dict[str, Any]]
) -> str:
    """Per-scenario feasibility verdict of one plan (shared by writer AND
    verifier so checksums are always reconstructible).

    - any evaluated constraint violated, or any assigned crop inadmissible in
      this scenario ⇒ 'infeasible';
    - otherwise, with at least one SATISFIED check (evaluated evidence) ⇒
      'feasible';
    - no evaluated evidence (only not_applicable / partially_checked) ⇒
      'not_evaluable'. Unevaluated checks are never treated as satisfied."""
    violated = any(c["status"] == "violated" for c in checks)
    excluded = any(not a["admissible"] for a in crop_admissibility)
    if violated or excluded:
        return "infeasible"
    if any(c["status"] == "satisfied" for c in checks):
        return "feasible"
    return "not_evaluable"


# ---------------------------------------------------------------------------
# Scenario sets
# ---------------------------------------------------------------------------


def _load_member_runs(db: Session, field_id: Any, run_ids: list[str]) -> list[dbm.ScenarioExecutionRun]:
    seen: set[str] = set()
    runs: list[dbm.ScenarioExecutionRun] = []
    findings: list[dict[str, str]] = []
    for raw in run_ids:
        try:
            rid = uuid_mod.UUID(str(raw))
        except (ValueError, AttributeError):
            findings.append({"field": "execution_run_ids", "reason": f"'{raw}' is not a UUID"})
            continue
        if str(rid) in seen:
            findings.append({"field": "execution_run_ids", "reason": f"duplicate run '{raw}'"})
            continue
        seen.add(str(rid))
        run = db.get(dbm.ScenarioExecutionRun, rid)
        if run is None or str(run.field_id) != str(field_id):
            findings.append({"field": "execution_run_ids", "reason": f"run '{raw}' not found for this field"})
            continue
        if run.run_status not in RESULT_RUN_STATUSES:
            findings.append(
                {
                    "field": "execution_run_ids",
                    "reason": f"run '{raw}' has status '{run.run_status}' — only result-bearing "
                    "executions (succeeded / completed_with_limitations) can be members",
                }
            )
            continue
        runs.append(run)
    if findings:
        raise ValidationFailed("Scenario set membership is invalid.", details=findings)
    return runs


def create_scenario_set(
    db: Session,
    *,
    field: dbm.Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.ScenarioSet:
    """Validate compatibility and persist a scenario set (members by value)."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.ScenarioSet).where(
                dbm.ScenarioSet.idempotency_key == idempotency_key,
                dbm.ScenarioSet.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    label = (payload.get("label") or "").strip()
    if not label or len(label) > 120:
        raise ValidationFailed(
            "label is required (1-120 characters).",
            details=[{"field": "label", "reason": "missing or too long"}],
        )
    run_ids = payload.get("execution_run_ids")
    if not isinstance(run_ids, list) or not (1 <= len(run_ids) <= rc.MAX_SCENARIO_SET_SIZE):
        raise ValidationFailed(
            f"execution_run_ids must list 1 to {rc.MAX_SCENARIO_SET_SIZE} execution runs.",
            details=[
                {
                    "field": "execution_run_ids",
                    "reason": f"got {len(run_ids) if isinstance(run_ids, list) else 'non-list'}",
                }
            ],
        )

    runs = _load_member_runs(db, field.id, [str(r) for r in run_ids])

    parents = {(str(r.parent_field_state_id), r.parent_snapshot_checksum) for r in runs}
    if len(parents) != 1:
        raise ValidationFailed(
            "All members must derive from the SAME parent Field State snapshot "
            "(identical parent pin and checksum) — scenario environments built on "
            "different observed baselines are not comparable.",
            details=[{"field": "execution_run_ids", "reason": "mixed parent Field States"}],
        )
    scenario_ids = {str(r.scenario_id) for r in runs}
    if len(scenario_ids) != len(runs):
        raise ValidationFailed(
            "Each member must come from a DISTINCT scenario — two executions of the "
            "same scenario add no environment.",
            details=[{"field": "execution_run_ids", "reason": "duplicate scenario ids"}],
        )

    parent_state_id, parent_checksum = next(iter(parents))
    members = [rc.member_document(r) for r in runs]
    checksum = sha256_of_document(
        rc.set_checksum_payload(field_id=str(field.id), label=label, members=members)
    )

    content_existing = db.scalar(
        select(dbm.ScenarioSet).where(
            dbm.ScenarioSet.field_id == field.id,
            dbm.ScenarioSet.set_checksum == checksum,
        )
    )
    if content_existing is not None:
        return content_existing

    compatibility = {
        "parent_field_state_id": parent_state_id,
        "parent_snapshot_checksum": parent_checksum,
        "member_count": len(members),
        "distinct_scenario_ids": sorted(scenario_ids),
        "engine_version_mix": {
            "transformation_engine_versions": sorted({m["transformation_engine_version"] for m in members}),
            "feature_engine_versions": sorted({m["feature_engine_version"] for m in members}),
            "feature_catalog_versions": sorted({m["feature_catalog_version"] for m in members}),
        },
        "note": (
            "Members are scenario EXECUTIONS (derived hypothetical environments "
            "over one shared observed baseline). Planning-season month coverage is "
            "validated per robust run, where the seasons are known."
        ),
    }

    row = dbm.ScenarioSet(
        field_id=field.id,
        label=label,
        description=payload.get("description"),
        parent_field_state_id=uuid_mod.UUID(parent_state_id),
        parent_snapshot_checksum=parent_checksum,
        members=members,
        member_count=len(members),
        compatibility_report=compatibility,
        set_checksum=checksum,
        status=rc.SET_STATUS_ACTIVE,
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.ScenarioSet).where(
                dbm.ScenarioSet.field_id == field.id,
                dbm.ScenarioSet.set_checksum == checksum,
            )
        )
        if winner is not None:
            return winner
        raise
    db.refresh(row)
    return row


def get_scenario_set_scoped(db: Session, set_id: uuid_mod.UUID, field_id: Any) -> dbm.ScenarioSet:
    row = db.get(dbm.ScenarioSet, set_id)
    if row is None or str(row.field_id) != str(field_id):
        raise NotFound("Scenario set not found for this field.")
    return row


def verify_scenario_set_members(db: Session, scenario_set: dbm.ScenarioSet | None) -> dict[str, Any]:
    """Compare every BY-VALUE member pin against the live execution row.

    Any drift raises Conflict — a robust evaluation must never run over
    silently changed sources."""
    if scenario_set is None:
        raise Conflict("Scenario set row is missing.", details=[{"issue": "scenario_set deleted"}])
    drifted: list[dict[str, Any]] = []
    for pin in scenario_set.members:
        run = db.get(dbm.ScenarioExecutionRun, uuid_mod.UUID(pin["execution_run_id"]))
        if run is None:
            drifted.append({"execution_run_id": pin["execution_run_id"], "issue": "row deleted"})
            continue
        live = rc.member_document(run)
        for key, pinned in pin.items():
            if live.get(key) != pinned:
                drifted.append(
                    {
                        "execution_run_id": pin["execution_run_id"],
                        "issue": f"field '{key}' changed",
                        "pinned": pinned,
                        "live": live.get(key),
                    }
                )
    if drifted:
        raise Conflict(
            "Scenario set members no longer match their pinned values; the set "
            "cannot be used for robust evaluations.",
            details=drifted,
        )
    return {"verified_members": len(scenario_set.members), "drift": []}


# ---------------------------------------------------------------------------
# Robust runs
# ---------------------------------------------------------------------------


def _reject_water_allocation(payload: dict[str, Any]) -> None:
    if payload.get("water_allocation_m3") is not None:
        raise ValidationFailed(
            rc.WATER_ALLOCATION_UNSUPPORTED_REASON,
            details=[{"field": "water_allocation_m3", "reason": "unsupported for robust runs"}],
            code=rc.WATER_ALLOCATION_UNSUPPORTED_CODE,
        )


def _validate_profiles(payload: dict[str, Any]) -> tuple[list[str], dict[str, float]]:
    requested = payload.get("strategy_profiles") or list(optimizer_mod.DEFAULT_PROFILES)
    if not isinstance(requested, list) or not requested:
        raise ValidationFailed(
            "strategy_profiles must be a non-empty list.",
            details=[{"field": "strategy_profiles"}],
        )
    if len(requested) > rc.MAX_ROBUST_PROFILES:
        raise ValidationFailed(
            f"At most {rc.MAX_ROBUST_PROFILES} strategy profiles are supported per robust run.",
            details=[{"field": "strategy_profiles", "reason": f"got {len(requested)}"}],
        )
    known = set(optimizer_mod.DEFAULT_PROFILES) | {"custom"}
    for p in requested:
        if p not in known:
            raise ValidationFailed(
                f"Unknown strategy profile '{p}'.",
                details=[{"field": "strategy_profiles", "reason": p}],
            )
    custom_weights = payload.get("custom_weights") or {}
    if "custom" in requested:
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
    return [str(p) for p in requested], {k: float(v) for k, v in custom_weights.items()}


def _profile_weights(profile: str, custom_weights: dict[str, float]) -> dict[str, float]:
    if profile == "custom":
        return {k: float(v) for k, v in custom_weights.items()}
    return dict(optimizer_mod.PROFILE_WEIGHTS[profile])


def _scenario_farm_context(
    db: Session,
    base_farm,
    run: dbm.ScenarioExecutionRun,
    derived_features: list[dbm.ScenarioDerivedFeature],
    seasons: list,
    scenario_label: str,
    warnings: list[str],
) -> tuple[Any, rclimate.ScenarioRunView]:
    # synthetic honesty: derived OBSERVATIONS carry the flag (features do not)
    synthetic_obs = db.scalar(
        select(dbm.ScenarioDerivedObservation.is_synthetic)
        .where(dbm.ScenarioDerivedObservation.execution_run_id == run.id)
        .limit(1)
    )
    view = rclimate.build_scenario_run_view(
        derived_features,
        is_synthetic=bool(synthetic_obs),
    )
    gaps = rclimate.month_coverage_gaps(view, seasons)
    if gaps:
        raise ValidationFailed(
            "A scenario execution does not cover every month of the planning "
            "seasons — robust evaluation would leave seasons unevaluated.",
            details=[
                {
                    "field": "execution_run_ids",
                    "reason": f"scenario '{scenario_label}' missing months {sorted(gaps)}",
                }
            ],
        )
    climate_by_season: dict[str, Any] = {}
    for season in seasons:
        evidence = rclimate.scenario_season_climate(
            view,
            season,
            execution_run_id=str(run.id),
            is_synthetic=view.is_synthetic,
            scenario_label=scenario_label,
        )
        if evidence is None:
            warnings.append(
                f"Scenario '{scenario_label}', season '{season.label}': month-of-year "
                "coverage below the minimum — climate dimensions unevaluated for "
                "this season (missing evidence is never approximated)."
            )
        else:
            climate_by_season[season.label] = evidence
            for w in evidence.warnings:
                warnings.append(f"Scenario '{scenario_label}', season '{season.label}': {w}")
    farm = replace(
        base_farm,
        climate_by_season=climate_by_season,
        climate_run_refs={s.label: str(run.id) for s in seasons},
        synthetic_evidence_in_use=view.is_synthetic or base_farm.synthetic_evidence_in_use,
        water_allocation_m3=None,  # structurally unavailable under scenarios
    )
    return farm, view


def start_robust_rotation_run(
    db: Session,
    scenario_set: dbm.ScenarioSet,
    field: dbm.Field,
    *,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.RobustRotationRun:
    """Validate, execute inline and persist one robust rotation run."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.RobustRotationRun).where(
                dbm.RobustRotationRun.idempotency_key == idempotency_key,
                dbm.RobustRotationRun.scenario_set_id == scenario_set.id,
            )
        )
        if existing is not None:
            return existing

    _reject_water_allocation(payload)
    seasons = _validate_seasons(payload.get("seasons") or [])
    hemisphere = payload.get("hemisphere") or "north"
    if hemisphere not in ("north", "south"):
        raise ValidationFailed(
            "hemisphere must be 'north' or 'south'.",
            details=[{"field": "hemisphere", "reason": hemisphere}],
        )
    profiles, custom_weights = _validate_profiles(payload)
    regret_requested = payload.get("regret_analysis", True)
    if not isinstance(regret_requested, bool):
        raise ValidationFailed(
            "regret_analysis must be a boolean.",
            details=[{"field": "regret_analysis"}],
        )

    # Integrity gate: the set's BY-VALUE pins must still match the live rows.
    verify_scenario_set_members(db, scenario_set)

    member_pins = [dict(m) for m in scenario_set.members]
    if regret_requested and len(profiles) * len(member_pins) > rc.MAX_SOLO_SOLVES:
        raise ValidationFailed(
            f"regret anchors would need {len(profiles) * len(member_pins)} solo solves; "
            f"the documented cap is {rc.MAX_SOLO_SOLVES}. Reduce profiles or members.",
            details=[{"field": "regret_analysis", "reason": "solve budget exceeded"}],
        )

    knowledge = load_knowledge(db)
    if not knowledge.crops:
        raise ValidationFailed(
            "No active knowledge pack with crops — import a knowledge pack first.",
            details=[{"field": "knowledge"}],
        )

    fingerprint = sha256_of_document(
        rc.run_fingerprint_payload(
            scenario_set_id=str(scenario_set.id),
            scenario_set_checksum=scenario_set.set_checksum,
            seasons=[
                {"label": s.label, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat()}
                for s in seasons
            ],
            strategy_profiles=profiles,
            custom_weights=custom_weights or None,
            regret_analysis=regret_requested,
            member_pins=member_pins,
            engine_version=rc.ROBUST_ENGINE_VERSION,
            method_version=rc.ROBUST_METHOD_VERSION,
        )
    )
    existing = db.scalar(
        select(dbm.RobustRotationRun).where(
            dbm.RobustRotationRun.scenario_set_id == scenario_set.id,
            dbm.RobustRotationRun.run_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        if existing.run_status == rc.RUN_STATUS_FAILED:
            db.delete(existing)  # failed runs carry no results; retry replaces them
            db.commit()
        else:
            return existing

    run = dbm.RobustRotationRun(
        field_id=field.id,
        scenario_set_id=scenario_set.id,
        scenario_set_checksum=scenario_set.set_checksum,
        member_pins=member_pins,
        member_count=len(member_pins),
        seasons=[
            {"label": s.label, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat()}
            for s in seasons
        ],
        strategy_profiles=profiles,
        custom_weights=dict(custom_weights),
        regret_analysis=regret_requested,
        run_fingerprint=fingerprint,
        rotation_engine_version=ROTATION_ENGINE_VERSION,
        robust_engine_version=rc.ROBUST_ENGINE_VERSION,
        robust_method_version=rc.ROBUST_METHOD_VERSION,
        solver_name=SOLVER_NAME,
        random_seed=RANDOM_SEED,
        run_status=rc.RUN_STATUS_QUEUED,
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(dbm.RobustRotationRun).where(
                dbm.RobustRotationRun.scenario_set_id == scenario_set.id,
                dbm.RobustRotationRun.run_fingerprint == fingerprint,
            )
        )
        if winner is not None:
            return winner
        raise

    try:
        _execute_run(
            db,
            run,
            field=field,
            scenario_set=scenario_set,
            seasons=seasons,
            hemisphere=hemisphere,
            profiles=profiles,
            custom_weights=custom_weights,
            regret_requested=regret_requested,
            knowledge=knowledge,
        )
    except Exception as exc:  # noqa: BLE001 — job failure accounting
        db.rollback()
        failed = db.get(dbm.RobustRotationRun, run.id)
        assert failed is not None
        failed.run_status = rc.RUN_STATUS_FAILED
        failed.error_summary = f"{type(exc).__name__}: {exc}"
        failed.completed_at = datetime.now(UTC)
        db.commit()
        raise
    return run


def _execute_run(
    db: Session,
    run: dbm.RobustRotationRun,
    *,
    field: dbm.Field,
    scenario_set: dbm.ScenarioSet,
    seasons: list,
    hemisphere: str,
    profiles: list[str],
    custom_weights: dict[str, float],
    regret_requested: bool,
    knowledge,
) -> None:
    run.run_status = rc.RUN_STATUS_RUNNING
    db.commit()

    warnings: list[str] = []
    not_evaluated: dict[str, Any] = {}

    # Base farm context (soil, history, farmer constraints) from the field.
    base_farm, base_warnings, _history_ids, base_run = build_farm_context(
        db, field, seasons, None, hemisphere
    )
    for w in base_warnings:
        warnings.append(f"farm context: {w}")
    if base_run is not None:
        warnings.append(
            f"Farm context (soil, history, farmer constraints) references observed "
            f"feature run {str(base_run.id)[:8]}; scenario climate evidence comes "
            "from the selected execution runs."
        )

    # ---- per-scenario problems
    problems: dict[str, RotationProblem] = {}
    for pin in scenario_set.members:
        run_id = uuid_mod.UUID(pin["execution_run_id"])
        src_run = db.get(dbm.ScenarioExecutionRun, run_id)
        assert src_run is not None  # verified above
        scenario = db.get(dbm.Scenario, src_run.scenario_id)
        label = scenario.name if scenario else str(run_id)[:8]
        features = db.scalars(
            select(dbm.ScenarioDerivedFeature).where(
                dbm.ScenarioDerivedFeature.execution_run_id == run_id
            )
        ).all()
        farm, _view = _scenario_farm_context(db, base_farm, src_run, features, seasons, label, warnings)
        sid = str(src_run.scenario_id)
        problems[sid] = RotationProblem(
            field_id=str(field.id),
            seasons=tuple(seasons),
            candidates=candidates_mod.generate_candidates(knowledge, farm),
            knowledge=knowledge,
            farm=farm,
            water_allocation_m3=None,
            baseline_assignment=_baseline_assignment(seasons, base_farm.history),
            synthetic_evidence=farm.synthetic_evidence_in_use,
        )
        if farm.synthetic_evidence_in_use:
            warnings.append(
                f"Scenario '{label}' derives from SYNTHETIC evidence — every "
                "outcome is a demonstration, never real farm evidence."
            )

    pool, exclusions = intersection_candidates(problems)
    if exclusions:
        warnings.append(
            f"{len(exclusions)} crop-season combination(s) are excluded from the "
            "shared pool because at least one scenario renders them inadmissible "
            "(cross-scenario restrictions are reported per crop)."
        )

    # ---- ONE shared-plan solve per profile
    diagnostics: dict[str, Any] = {
        "shared_solves": {},
        "solo_solves": {},
        "solo_solve_count": 0,
        "scenario_set_size": len(problems),
    }
    shared_results: dict[str, Any] = {}
    infeasible_profiles: list[dict[str, Any]] = []
    solver_failures: list[dict[str, Any]] = []

    for profile in profiles:
        result = optimize_shared_plan(problems, pool, profile, _profile_weights(profile, custom_weights))
        if isinstance(result, optimizer_mod.InfeasibleResult):
            entry = {"strategy_key": profile, "conflicts": result.conflicts, "notes": result.notes}
            if result.status == "infeasible":
                infeasible_profiles.append(entry)
            else:
                entry["solver_status"] = result.status
                solver_failures.append(entry)
            continue
        shared_results[profile] = result
        diagnostics["shared_solves"][profile] = {
            "solver_status": result.solver_status,
            "wall_time_ms": result.solver_wall_time_ms,
            "maximin_objective": result.maximin_objective,
            "objective_bound": result.objective_bound,
            "per_scenario_steering": result.per_scenario_steering,
        }

    # ---- solo optima per scenario (regret anchors), reused M5 optimizer
    solo_results: dict[str, dict[str, Any]] = {}
    if regret_requested:
        for sid in sorted(problems):
            solo_results[sid] = {}
            for profile in profiles:
                solo = optimizer_mod.optimize_strategy(
                    problems[sid], f"solo::{profile}", _profile_weights(profile, custom_weights)
                )
                solo_results[sid][profile] = solo
                entry: dict[str, Any] = {"strategy_key": profile}
                if isinstance(solo, optimizer_mod.InfeasibleResult):
                    entry.update({"status": solo.status})
                else:
                    entry.update({"status": solo.solver_status, "wall_time_ms": solo.solver_wall_time_ms})
                diagnostics["solo_solves"].setdefault(sid, {})[profile] = entry
        diagnostics["solo_solve_count"] = sum(len(v) for v in diagnostics["solo_solves"].values())

    # ---- plan registry
    plans: list[dict[str, Any]] = [
        {
            "plan_key": "baseline",
            "strategy_kind": "baseline",
            "is_baseline": True,
            "profile_weights": {},
            "assignment": _baseline_assignment(seasons, base_farm.history),
        }
    ]
    unsolved_entries = {e["strategy_key"]: e for e in infeasible_profiles + solver_failures}
    for profile in profiles:
        if profile in shared_results:
            plans.append(
                {
                    "plan_key": profile,
                    "strategy_kind": "optimized",
                    "is_baseline": False,
                    "profile_weights": _profile_weights(profile, custom_weights),
                    "assignment": shared_results[profile].assignment,
                    "solver_status": shared_results[profile].solver_status,
                    "solver_wall_time_ms": shared_results[profile].solver_wall_time_ms,
                }
            )
        elif profile in unsolved_entries:
            plans.append(
                {
                    "plan_key": profile,
                    "strategy_kind": "optimized",
                    "is_baseline": False,
                    "profile_weights": _profile_weights(profile, custom_weights),
                    "assignment": None,
                    "solver_status": unsolved_entries[profile].get("solver_status"),
                }
            )

    sid_list = sorted(problems)

    # ---- per-scenario evaluation of ALL plans (M5 post-hoc code, reused)
    scenario_objectives: dict[str, dict[str, float | None]] = {}
    scenario_verdicts: dict[str, dict[str, str]] = {}
    per_plan_scenario: dict[str, dict[str, dict[str, Any] | None]] = {}  # plan_key -> sid -> row|None
    solo_objectives: dict[str, dict[str, float | None]] = {}

    for sid in sid_list:
        problem = problems[sid]
        scenario_plans: list[StrategySolution] = []
        for plan in plans:
            if plan["assignment"] is None:
                continue
            criteria = objectives_mod.evaluate_criteria(problem, dict(plan["assignment"]))
            checks = constraints_mod.check_all(problem, dict(plan["assignment"]))
            adm = _crop_admissibility(problem, plan["assignment"])
            scenario_plans.append(
                StrategySolution(
                    strategy_key=plan["plan_key"],
                    strategy_kind=plan["strategy_kind"],
                    is_baseline=plan["is_baseline"],
                    profile_weights=plan["profile_weights"],
                    weights_effective={},
                    skipped_weights={},
                    assignment=plan["assignment"],
                    objective_value=None,
                    criteria=criteria,
                    constraints_checked=checks,
                    evidence_coverage=None,
                )
            )
            per_plan_scenario.setdefault(plan["plan_key"], {})[sid] = {
                "criteria": criteria,
                "checks": checks,
                "adm": adm,
            }
        if regret_requested:
            for profile, solo in (solo_results.get(sid) or {}).items():
                if isinstance(solo, optimizer_mod.InfeasibleResult):
                    solo_objectives.setdefault(sid, {})[profile] = None
                    continue
                criteria = objectives_mod.evaluate_criteria(problem, dict(solo.assignment))
                checks = constraints_mod.check_all(problem, dict(solo.assignment))
                scenario_plans.append(
                    StrategySolution(
                        strategy_key=f"solo::{profile}",
                        strategy_kind="optimized",
                        is_baseline=False,
                        profile_weights=solo.profile_weights,
                        weights_effective={},
                        skipped_weights={},
                        assignment=solo.assignment,
                        objective_value=None,
                        criteria=criteria,
                        constraints_checked=checks,
                        evidence_coverage=None,
                    )
                )

        objectives_mod.normalize_within_set(scenario_plans)
        for sol in scenario_plans:
            objective, _effective, _skipped = objectives_mod.weighted_objective(sol)
            sol.objective_value = objective
        objectives_mod.compute_pareto(scenario_plans)

        by_key = {sol.strategy_key: sol for sol in scenario_plans}
        scenario_objectives[sid] = {
            key: sol.objective_value for key, sol in by_key.items() if not key.startswith("solo::")
        }
        for profile, solo in (solo_results.get(sid) or {}).items():
            if isinstance(solo, optimizer_mod.InfeasibleResult):
                continue
            anchor = by_key.get(f"solo::{profile}")
            solo_objectives.setdefault(sid, {})[profile] = anchor.objective_value if anchor else None

        for plan in plans:
            if plan["assignment"] is None:
                scenario_verdicts.setdefault(sid, {})[plan["plan_key"]] = "not_evaluable"
                continue
            sol = by_key[plan["plan_key"]]
            checks = sol.constraints_checked
            adm = per_plan_scenario[plan["plan_key"]][sid]["adm"]
            verdict = _scenario_verdict(
                [{"status": c.status} for c in checks],
                adm,
            )
            scenario_verdicts.setdefault(sid, {})[plan["plan_key"]] = verdict
            per_plan_scenario[plan["plan_key"]][sid]["on_pareto"] = sol.on_pareto_front
            per_plan_scenario[plan["plan_key"]][sid]["weighted_objective"] = sol.objective_value

    # ---- cross-scenario aggregates
    regret_by_plan: dict[str, dict[str, float]] = {}
    strategy_rows: list[dict[str, Any]] = []
    for plan in plans:
        key = plan["plan_key"]
        objectives_by_scenario = {sid: scenario_objectives.get(sid, {}).get(key) for sid in sid_list}
        evaluable = {sid: v for sid, v in objectives_by_scenario.items() if v is not None}
        objective_all = bool(sid_list) and len(evaluable) == len(sid_list)
        worst_case = min(evaluable.values()) if objective_all else None
        if plan["assignment"] is not None and not objective_all:
            not_evaluated.setdefault("worst_case_objective", {})[key] = (
                "weighted objective not evaluable in every scenario — no worst-case "
                "value is reported (a partial minimum would overstate robustness)"
            )

        verdicts = [scenario_verdicts.get(sid, {}).get(key, "not_evaluable") for sid in sid_list]
        if not sid_list:
            feasibility = rc.ROBUST_NOT_EVALUABLE
        elif any(v == "infeasible" for v in verdicts):
            feasibility = rc.ROBUST_INFEASIBLE
        elif all(v == "feasible" for v in verdicts):
            feasibility = rc.ROBUST_FEASIBLE
        else:
            feasibility = rc.ROBUST_NOT_EVALUABLE

        worst_regret = None
        regret_complete = False
        if regret_requested and plan["strategy_kind"] == "optimized" and plan["assignment"] is not None:
            regrets: dict[str, float] = {}
            complete = True
            for sid in sid_list:
                shared_obj = objectives_by_scenario.get(sid)
                solo_obj = (solo_objectives.get(sid) or {}).get(key)
                if shared_obj is None or solo_obj is None:
                    complete = False
                    continue
                regrets[sid] = round(solo_obj - shared_obj, 6)
            if complete and sid_list:
                worst_regret = max(regrets.values())
                regret_complete = True
                regret_by_plan[key] = regrets
            elif regrets:
                not_evaluated.setdefault("regret", {})[key] = (
                    "regret not evaluable in every scenario (a scenario's shared or "
                    "solo objective was not evaluable); no partial regret is reported"
                )
            elif not complete:
                not_evaluated.setdefault("regret", {})[key] = (
                    "regret not evaluable in every scenario (solo anchor missing or "
                    "objectives not evaluable); no partial regret is reported"
                )

        strategy_rows.append(
            {
                "plan": plan,
                "worst_case_objective": round(worst_case, 6) if worst_case is not None else None,
                "worst_case_regret": worst_regret,
                "robust_feasibility": feasibility,
                "objective_evaluable_in_all": objective_all,
                "solver_status": plan.get("solver_status"),
                "solver_wall_time_ms": plan.get("solver_wall_time_ms"),
            }
        )

    # ---- run-level solver status (shared solves only; anchors excluded)
    optimized_statuses = [r["solver_status"] for r in strategy_rows if r["plan"]["strategy_kind"] == "optimized" and r["solver_status"]]
    if infeasible_profiles and not optimized_statuses:
        run_solver_status = "infeasible"
    elif solver_failures and not optimized_statuses:
        run_solver_status = solver_failures[0].get("solver_status", "unknown")
    elif infeasible_profiles or solver_failures:
        run_solver_status = "feasible"
        warnings.append(
            "Some strategy profiles did not reach a proven optimum "
            f"({len(infeasible_profiles)} infeasible, {len(solver_failures)} solver "
            "failure(s)); see infeasibility details."
        )
    elif optimized_statuses and all(s == "optimal" for s in optimized_statuses):
        run_solver_status = "optimal"
    elif optimized_statuses:
        run_solver_status = "feasible"
    else:
        run_solver_status = "unknown"

    run.solver_status = run_solver_status
    run.infeasibility_details = {
        "profiles": infeasible_profiles,
        "solver_failures": solver_failures,
        "cross_scenario_exclusions": exclusions,
        "note": (
            "The shared plan draws only on candidates admissible in EVERY selected "
            "scenario; hard constraints are enforced on the shared assignment. No "
            "hard constraint was relaxed."
        ),
    }
    run.solver_diagnostics = diagnostics
    run.warnings = warnings
    run.not_evaluated = not_evaluated
    run.feature_run_ids = [m["execution_run_id"] for m in scenario_set.members]
    run.knowledge_pack_refs = [dict(r) for r in knowledge.pack_refs]

    # ---- persist strategies + per-scenario evaluations
    strategy_docs: list[dict[str, Any]] = []
    for row in strategy_rows:
        plan = row["plan"]
        key = plan["plan_key"]
        if plan["assignment"] is None:
            per_scenario_docs: list[dict[str, Any]] = []
        else:
            per_scenario_docs = [
                {
                    "scenario_id": sid,
                    "weighted_objective": scenario_objectives.get(sid, {}).get(key),
                    "robust_verdict": scenario_verdicts.get(sid, {}).get(key, "not_evaluable"),
                }
                for sid in sid_list
            ]
        checksum_payload = rc.strategy_checksum_payload(
            run_fingerprint=run.run_fingerprint,
            strategy_key=key,
            strategy_kind=plan["strategy_kind"],
            assignment=plan["assignment"] or (),
            worst_case_objective=row["worst_case_objective"],
            worst_case_regret=row["worst_case_regret"],
            robust_feasibility=row["robust_feasibility"],
            per_scenario=per_scenario_docs,
            engine_version=rc.ROBUST_ENGINE_VERSION,
        )
        checksum = sha256_of_document(checksum_payload)
        strategy_row = dbm.RobustRotationStrategy(
            run_id=run.id,
            strategy_key=key,
            strategy_kind=plan["strategy_kind"],
            is_baseline=plan["is_baseline"],
            profile_weights=plan["profile_weights"],
            assignment=[
                {"season_label": lbl, "crop_code": cc} for lbl, cc in (plan["assignment"] or [])
            ],
            worst_case_objective=row["worst_case_objective"],
            worst_case_regret=row["worst_case_regret"],
            robust_feasibility=row["robust_feasibility"],
            objective_evaluable_in_all_scenarios=row["objective_evaluable_in_all"],
            solver_status=row["solver_status"],
            solver_wall_time_ms=row["solver_wall_time_ms"],
            checksum_sha256=checksum,
        )
        db.add(strategy_row)
        db.flush()

        if plan["assignment"] is not None:
            for sid in sid_list:
                data = per_plan_scenario[key][sid]
                pin = next(m for m in scenario_set.members if m["scenario_id"] == sid)
                climate = problems[sid].farm.climate_by_season
                db.add(
                    dbm.RobustScenarioEvaluation(
                        run_id=run.id,
                        strategy_id=strategy_row.id,
                        scenario_id=uuid_mod.UUID(sid),
                        execution_run_id=uuid_mod.UUID(pin["execution_run_id"]),
                        output_checksum_pin=pin["output_checksum"] or "",
                        weighted_objective=data["weighted_objective"],
                        objective_evaluable=data["weighted_objective"] is not None,
                        on_scenario_pareto_front=data.get("on_pareto"),
                        regret_vs_solo=(regret_by_plan.get(key) or {}).get(sid),
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
                                "source_refs": list(c.source_refs),
                            }
                            for c in data["criteria"]
                        ],
                        constraint_checks=[
                            {
                                "constraint_code": c.constraint_code,
                                "status": c.status,
                                "description": c.description,
                                "detail": c.detail,
                                "rule_codes": list(c.rule_codes),
                                "source_refs": list(c.source_refs),
                            }
                            for c in data["checks"]
                        ],
                        crop_admissibility=data["adm"],
                        climate_evidence={
                            season.label: {
                                "basis": ev.basis,
                                "coverage_ratio": ev.coverage_ratio,
                                "season_precipitation_mm": ev.season_precipitation_mm,
                                "season_mean_temp_degC": ev.season_mean_temp_degC,
                                "season_hot_days_35c": ev.season_hot_days_35c,
                                "season_et0_mm": ev.season_et0_mm,
                                "warnings": list(ev.warnings),
                            }
                            for season, ev in ((s, climate.get(s.label)) for s in seasons)
                            if ev is not None
                        },
                    )
                )
        strategy_docs.append(checksum_payload)

    output_document = {
        "run_fingerprint": run.run_fingerprint,
        "member_pins": scenario_set.members,
        "strategies": strategy_docs,
        "warnings": warnings,
        "not_evaluated": not_evaluated,
        "solver_diagnostics": {
            "shared_solves": {
                k: {kk: vv for kk, vv in v.items() if kk != "per_scenario_steering"}
                for k, v in diagnostics["shared_solves"].items()
            },
            "solo_solve_count": diagnostics["solo_solve_count"],
            "scenario_set_size": diagnostics["scenario_set_size"],
        },
    }
    run.output_checksum = sha256_of_document(output_document)
    run.run_status = (
        rc.RUN_STATUS_COMPLETED_WITH_LIMITATIONS if warnings else rc.RUN_STATUS_SUCCEEDED
    )
    run.completed_at = datetime.now(UTC)
    run.solver_version = solver_version()
    db.commit()


def _crop_admissibility(
    problem: RotationProblem, assignment: tuple[tuple[str, str | None], ...]
) -> list[dict[str, Any]]:
    """Per-season admissibility status of the assigned crops under THIS
    scenario's candidate assessments (an assigned crop excluded by a
    scenario's temperature screening is a first-class finding)."""
    out: list[dict[str, Any]] = []
    for season_label, crop_code in assignment:
        if crop_code is None:
            continue
        assessment = problem.candidates.get(season_label, {}).get(crop_code)
        if assessment is None:
            continue
        out.append(
            {
                "season_label": season_label,
                "crop_code": crop_code,
                "status": assessment.status,
                "admissible": assessment.admissible,
                "hard_reason": next(
                    (r.get("message") for r in assessment.reasons if r.get("severity") == "hard"),
                    None,
                ),
            }
        )
    return out


def infeasible_profile_entries(
    infeasible_profiles: list[dict[str, Any]],
    solver_failures: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in infeasible_profiles + solver_failures:
        out[entry["strategy_key"]] = entry
    return out


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def set_payload(row: dbm.ScenarioSet) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "field_id": str(row.field_id),
        "label": row.label,
        "description": row.description,
        "parent_field_state_id": str(row.parent_field_state_id),
        "parent_snapshot_checksum": row.parent_snapshot_checksum,
        "members": row.members,
        "member_count": row.member_count,
        "compatibility_report": row.compatibility_report,
        "set_checksum": row.set_checksum,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def run_payload(run: dbm.RobustRotationRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "scenario_set_id": str(run.scenario_set_id),
        "scenario_set_checksum": run.scenario_set_checksum,
        "member_count": run.member_count,
        "seasons": run.seasons,
        "strategy_profiles": run.strategy_profiles,
        "regret_analysis": run.regret_analysis,
        "run_status": run.run_status,
        "solver_status": run.solver_status,
        "robust_engine_version": run.robust_engine_version,
        "robust_method_version": run.robust_method_version,
        "rotation_engine_version": run.rotation_engine_version,
        "solver_name": run.solver_name,
        "solver_version": run.solver_version,
        "random_seed": run.random_seed,
        "output_checksum": run.output_checksum,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "infeasibility_details": run.infeasibility_details,
        "error_summary": run.error_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def strategy_payload(row: dbm.RobustRotationStrategy) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "strategy_key": row.strategy_key,
        "strategy_kind": row.strategy_kind,
        "is_baseline": row.is_baseline,
        "profile_weights": row.profile_weights,
        "assignment": row.assignment,
        "worst_case_objective": row.worst_case_objective,
        "worst_case_regret": row.worst_case_regret,
        "robust_feasibility": row.robust_feasibility,
        "objective_evaluable_in_all_scenarios": row.objective_evaluable_in_all_scenarios,
        "solver_status": row.solver_status,
        "solver_wall_time_ms": row.solver_wall_time_ms,
        "checksum_sha256": row.checksum_sha256,
    }


def evaluation_payload(row: dbm.RobustScenarioEvaluation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "strategy_id": str(row.strategy_id),
        "scenario_id": str(row.scenario_id),
        "execution_run_id": str(row.execution_run_id),
        "output_checksum_pin": row.output_checksum_pin,
        "weighted_objective": row.weighted_objective,
        "objective_evaluable": row.objective_evaluable,
        "on_scenario_pareto_front": row.on_scenario_pareto_front,
        "regret_vs_solo": row.regret_vs_solo,
        "criteria": row.criteria,
        "constraint_checks": row.constraint_checks,
        "crop_admissibility": row.crop_admissibility,
        "climate_evidence": row.climate_evidence,
    }


def verify_run(db: Session, run: dbm.RobustRotationRun) -> dict[str, Any]:
    """Checksum + pin verification (idempotent, read-only)."""
    findings: list[dict[str, Any]] = []

    # 1. member pins vs live rows
    try:
        member_check = verify_scenario_set_members(db, db.get(dbm.ScenarioSet, run.scenario_set_id))
    except Conflict as exc:
        findings.extend(exc.details or [{"issue": "member pin drift"}])
        member_check = {"verified_members": 0, "drift": "see findings"}

    # 2. strategy checksums (recomputed from stored rows with the SAME
    #    per-scenario verdict logic used at write time)
    strategies = db.scalars(
        select(dbm.RobustRotationStrategy)
        .where(dbm.RobustRotationStrategy.run_id == run.id)
        .order_by(dbm.RobustRotationStrategy.strategy_key.asc())
    ).all()
    for s in strategies:
        evals = db.scalars(
            select(dbm.RobustScenarioEvaluation)
            .where(dbm.RobustScenarioEvaluation.strategy_id == s.id)
            .order_by(dbm.RobustScenarioEvaluation.scenario_id.asc())
        ).all()
        per_scenario_docs = [
            {
                "scenario_id": str(e.scenario_id),
                "weighted_objective": e.weighted_objective,
                "robust_verdict": _scenario_verdict(e.constraint_checks, e.crop_admissibility),
            }
            for e in evals
        ]
        payload = rc.strategy_checksum_payload(
            run_fingerprint=run.run_fingerprint,
            strategy_key=s.strategy_key,
            strategy_kind=s.strategy_kind,
            assignment=[(a["season_label"], a["crop_code"]) for a in s.assignment],
            worst_case_objective=s.worst_case_objective,
            worst_case_regret=s.worst_case_regret,
            robust_feasibility=s.robust_feasibility,
            per_scenario=per_scenario_docs,
            engine_version=rc.ROBUST_ENGINE_VERSION,
        )
        recomputed = sha256_of_document(payload)
        if recomputed != s.checksum_sha256:
            findings.append(
                {
                    "strategy_key": s.strategy_key,
                    "issue": "strategy checksum mismatch",
                    "stored": s.checksum_sha256,
                }
            )

    return {
        "run_id": str(run.id),
        "verified": not findings,
        "member_check": member_check,
        "strategy_count": len(strategies),
        "findings": findings,
        "note": (
            "Verification recomputes strategy checksums and re-compares the BY-VALUE "
            "member pins against the live M7.3 execution rows."
        ),
    }

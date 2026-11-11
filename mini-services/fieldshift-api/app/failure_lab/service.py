"""Rotation Failure Lab orchestration (P2.D) — the DB-side bridge.

Mirrors the rotation-run pipeline (M5) for stress runs: validate request →
resolve packs + candidate keys → find the reference rotation run (the field's
latest succeeded run: it pins the planning seasons and the recommended /
alternative strategy assignments) → build the unstressed FarmContext through
the EXISTING rotation services (`build_farm_context`, `_pick_evidence_run`,
`_season_climate`, `_baseline_assignment` — reused, not duplicated) → build
the base `RotationProblem` exactly like `start_rotation_run` → run the
failure-lab engine inline → persist the immutable snapshot (result, packs,
candidates, warnings, not_evaluated) with the canonical-JSON sha256 checksum.

Idempotency, run lifecycle and failure accounting follow the rotation module
(202-style inline execution, field-scoped replay of idempotency keys).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.db import models as dbm
from app.db.models_p2 import RotationStressRun
from app.failure_lab import contracts as fl_contracts
from app.failure_lab import engine as fl_engine
from app.failure_lab import metrics as fl_metrics
from app.field_state.manifest import sha256_of_document
from app.knowledge.service import load_knowledge
from app.rotation import candidates as candidates_mod
from app.rotation import optimizer as optimizer_mod
from app.rotation import service as rotation_service
from app.rotation.problem import (
    RANDOM_SEED,
    ROTATION_ENGINE_VERSION,
    SOLVER_NAME,
    RotationProblem,
    SeasonSpec,
    solver_version,
)

logger = logging.getLogger("croptwist.failure_lab")


def _resolve_candidate_keys(raw: Any) -> list[str]:
    """Validate the requested candidate keys (canonical order, deduplicated)."""
    if raw is None:
        return list(fl_contracts.CANDIDATE_KEYS)
    if not isinstance(raw, list) or not raw:
        raise ValidationFailed(
            "candidates must be a non-empty list when provided.",
            details=[{"field": "candidates"}],
        )
    seen: dict[str, None] = {}
    for item in raw:
        if item not in fl_contracts.CANDIDATE_KEYS:
            raise ValidationFailed(
                f"Unknown candidate key '{item}' "
                f"(known: {', '.join(fl_contracts.CANDIDATE_KEYS)}).",
                details=[{"field": "candidates", "reason": str(item)}],
            )
        seen.setdefault(item, None)
    return [k for k in fl_contracts.CANDIDATE_KEYS if k in seen]


def _reference_rotation_run(db: Session, field_id: Any) -> dbm.RotationRun:
    """The field's latest succeeded rotation run — the lab's reference.

    It pins the planning seasons and carries the strategy assignments the
    stress test replays. Deterministic ordering (completed_at, created_at,
    id) so 'latest' never depends on row order."""
    run = db.scalar(
        select(dbm.RotationRun)
        .where(dbm.RotationRun.field_id == field_id, dbm.RotationRun.status == "succeeded")
        .order_by(
            dbm.RotationRun.completed_at.desc().nullslast(),
            dbm.RotationRun.created_at.desc(),
            dbm.RotationRun.id.desc(),
        )
        .limit(1)
    )
    if run is None:
        raise ValidationFailed(
            "No succeeded rotation run exists for this field — the failure lab "
            "stress-tests the candidate rotations of an existing run. Create a "
            "rotation run first.",
            details=[{"field": "rotation_runs"}],
        )
    return run


def _strategy_assignment(strategy: dbm.RotationStrategy) -> tuple[tuple[str, str | None], ...]:
    return tuple(
        (entry.get("season_label"), entry.get("crop_code")) for entry in (strategy.assignment or [])
    )


def _pick_recommended_strategy(run: dbm.RotationRun) -> dbm.RotationStrategy | None:
    """The reference run's recommended strategy: an optimized (non-baseline)
    strategy on the run's Pareto front if any, else the first optimized
    strategy by strategy key — a documented deterministic pick (several
    strategies can share the front)."""
    optimized = sorted(
        (s for s in run.strategies if not s.is_baseline),
        key=lambda s: s.strategy_key,
    )
    if not optimized:
        return None
    on_front = [s for s in optimized if (s.pareto or {}).get("on_front")]
    return on_front[0] if on_front else optimized[0]


def _pick_alternative_strategy(
    run: dbm.RotationRun, recommended: dbm.RotationStrategy
) -> dbm.RotationStrategy | None:
    """A deterministic ALTERNATIVE to the recommended profile: the profile
    ranked next by the run's strategy profiles (wrapping around) that actually
    produced a strategy row; otherwise the first default profile different
    from the recommended one that produced a row."""
    by_key = {
        s.strategy_key: s for s in run.strategies if not s.is_baseline
    }
    profiles = [p for p in (run.strategy_profiles or []) if p in by_key]
    ordered: list[str] = []
    if recommended.strategy_key in profiles:
        start = profiles.index(recommended.strategy_key)
        ordered = profiles[start + 1 :] + profiles[:start]
    else:
        ordered = [p for p in profiles if p != recommended.strategy_key]
    if not ordered:
        ordered = [
            p
            for p in optimizer_mod.DEFAULT_PROFILES
            if p != recommended.strategy_key and p in by_key
        ]
    for key in ordered:
        if key != recommended.strategy_key:
            return by_key[key]
    return None


def run_checksum(request_parameters: dict[str, Any], result: dict[str, Any] | None) -> str:
    """Canonical sha256 over the run's pinned inputs + result document.

    The verify endpoint recomputes this from the STORED `request_parameters`
    and `result` — both are stored BY VALUE, so the checksum is always
    reconstructible (no re-execution, no hidden inputs)."""
    payload = {
        "kind": "rotation_stress_run",
        "engine_version": fl_contracts.FAILURE_LAB_ENGINE_VERSION,
        "packs_version": fl_contracts.STRESS_PACKS_VERSION,
        "metrics_version": fl_metrics.ROBUSTNESS_METRICS_VERSION,
        "request_parameters": request_parameters,
        "result": result,
    }
    return sha256_of_document(payload)


def start_rotation_stress_run(
    db: Session,
    field: dbm.Field,
    principal: Any,
    payload: dict[str, Any],
) -> RotationStressRun:
    """Validate, execute inline and persist one rotation stress run.

    Returns the ORM row (the router commits and serializes via
    `payload_to_dict`) — the same split as the rotation module."""
    payload = payload or {}

    packs = fl_contracts.resolve_packs(payload.get("packs"))
    candidate_keys = _resolve_candidate_keys(payload.get("candidates"))
    idempotency_key = payload.get("idempotency_key") or None
    if idempotency_key and not isinstance(idempotency_key, str):
        raise ValidationFailed(
            "idempotency_key must be a string.",
            details=[{"field": "idempotency_key"}],
        )
    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValidationFailed(
            "notes must be a string.",
            details=[{"field": "notes"}],
        )

    hemisphere = payload.get("hemisphere") or "north"
    if hemisphere not in ("north", "south"):
        raise ValidationFailed(
            "hemisphere must be 'north' or 'south'.",
            details=[{"field": "hemisphere", "reason": hemisphere}],
        )

    if idempotency_key:
        # Field-scoped replay (Deepening F-3 semantics): a known key returns
        # the existing run; cross-tenant replay can never serialize another
        # tenant's run.
        existing = db.scalar(
            select(RotationStressRun).where(
                RotationStressRun.idempotency_key == idempotency_key,
                RotationStressRun.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    reference_run = _reference_rotation_run(db, field.id)
    seasons: list[SeasonSpec] = rotation_service._validate_seasons(
        list(reference_run.seasons or [])
    )

    knowledge = load_knowledge(db)
    if not knowledge.crops:
        raise ValidationFailed(
            "No active knowledge pack with crops — import a knowledge pack first.",
            details=[{"field": "knowledge"}],
        )

    farm, warnings, _history_ids, evidence_run = rotation_service.build_farm_context(
        db, field, seasons, payload.get("evidence_run_id"), hemisphere
    )
    assessments = candidates_mod.generate_candidates(knowledge, farm)
    baseline_assignment = rotation_service._baseline_assignment(seasons, farm.history)

    # The allocation the recommendation was computed under wins when the
    # reference run pinned one; otherwise the live farm-constraint allocation
    # applies. The source is recorded — never silently mixed.
    if reference_run.water_allocation_m3 is not None:
        water_allocation = float(reference_run.water_allocation_m3)
        allocation_source = "reference_run"
    else:
        water_allocation = farm.water_allocation_m3
        allocation_source = "farm_constraints" if water_allocation is not None else None
    farm = (
        replace(farm, water_allocation_m3=water_allocation)
        if water_allocation != farm.water_allocation_m3
        else farm
    )

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

    # ---- candidate rotations (pinned assignments)
    specs: list[fl_engine.CandidateSpec] = []
    candidate_docs: list[dict[str, Any]] = []
    not_evaluated: list[dict[str, Any]] = []

    baseline_solution = optimizer_mod.build_baseline_solution(problem)
    specs.append(
        fl_engine.CandidateSpec(
            candidate_key="baseline",
            origin="history",
            strategy_profile=None,
            assignment=baseline_solution.assignment,
            source_note=(
                "baseline reconstructed from the field's crop history "
                "(build_baseline_solution); evaluated as-is"
            ),
        )
    )
    if "recommended" in candidate_keys or "alternative" in candidate_keys:
        recommended = _pick_recommended_strategy(reference_run)
        if recommended is None:
            for key in ("recommended", "alternative"):
                if key in candidate_keys:
                    not_evaluated.append({
                        "dimension": "candidate_rotation",
                        "pack_code": None,
                        "candidate_key": key,
                        "season_label": None,
                        "reason": (
                            "the reference rotation run has no optimized strategy "
                            "(all profiles infeasible or failed) — nothing to stress"
                        ),
                    })
        else:
            if "recommended" in candidate_keys:
                specs.append(
                    fl_engine.CandidateSpec(
                        candidate_key="recommended",
                        origin="rotation_run",
                        strategy_profile=recommended.strategy_key,
                        assignment=_strategy_assignment(recommended),
                        source_note=(
                            f"recommended strategy '{recommended.strategy_key}' of "
                            f"rotation run {str(reference_run.id)[:8]} (deterministic "
                            "pick: Pareto-front strategy, else first optimized "
                            "strategy by key)"
                        ),
                    )
                )
            if "alternative" in candidate_keys:
                alternative = _pick_alternative_strategy(reference_run, recommended)
                if alternative is None:
                    not_evaluated.append({
                        "dimension": "candidate_rotation",
                        "pack_code": None,
                        "candidate_key": "alternative",
                        "season_label": None,
                        "reason": (
                            "the reference rotation run produced no second optimized "
                            "strategy — no deterministic alternative exists"
                        ),
                    })
                else:
                    specs.append(
                        fl_engine.CandidateSpec(
                            candidate_key="alternative",
                            origin="rotation_run",
                            strategy_profile=alternative.strategy_key,
                            assignment=_strategy_assignment(alternative),
                            source_note=(
                                f"alternative strategy '{alternative.strategy_key}' of "
                                f"rotation run {str(reference_run.id)[:8]} (profile "
                                "ranked next by the run's strategy profiles)"
                            ),
                        )
                    )

    run = RotationStressRun(
        field_id=field.id,
        status="running",
        request_parameters={},
        engine_version=fl_contracts.FAILURE_LAB_ENGINE_VERSION,
        packs=[pack.document() for pack in packs],
        candidates=[spec.document() for spec in specs],
        warnings=[],
        not_evaluated=[],
        idempotency_key=idempotency_key,
        created_by=getattr(principal, "id", None),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    try:
        run.request_parameters = {
            "packs": [pack.document() for pack in packs],
            "candidate_keys": candidate_keys,
            "notes": notes,
            "hemisphere": hemisphere,
            "reference_rotation_run": {
                "id": str(reference_run.id),
                "status": reference_run.status,
                "seasons": list(reference_run.seasons or []),
                "strategy_profiles": list(reference_run.strategy_profiles or []),
                "water_allocation_m3": reference_run.water_allocation_m3,
                "rotation_engine_version": reference_run.rotation_engine_version,
                "solver_version": reference_run.solver_version,
            },
            "allocation_source": allocation_source,
            "evidence_run_id": str(evidence_run.id) if evidence_run is not None else None,
            "knowledge_pack_refs": [dict(r) for r in knowledge.pack_refs],
            "engine_versions": {
                "failure_lab": fl_contracts.FAILURE_LAB_ENGINE_VERSION,
                "stress_packs": fl_contracts.STRESS_PACKS_VERSION,
                "metrics": fl_metrics.ROBUSTNESS_METRICS_VERSION,
                "rotation_engine": ROTATION_ENGINE_VERSION,
                "solver_name": SOLVER_NAME,
                "solver_version": solver_version(),
                "random_seed": RANDOM_SEED,
            },
        }
        db.flush()

        engine_result = fl_engine.run_stress_matrix(
            problem,
            candidates=specs,
            packs=packs,
        )
        result = {
            **engine_result,
            "reference_run_id": str(reference_run.id),
        }
        not_evaluated = not_evaluated + list(engine_result.get("not_evaluated", []))

        run.result = result
        run.warnings = list(warnings)
        run.not_evaluated = not_evaluated
        run.checksum_sha256 = run_checksum(run.request_parameters, result)
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        db.flush()
        logger.info(
            "rotation stress run succeeded",
            extra={"run_id": str(run.id), "field_id": str(field.id)},
        )
    except Exception as exc:  # noqa: BLE001 — job failure accounting (mirror rotation)
        run.status = "failed"
        run.result = {"error_summary": f"{type(exc).__name__}: {exc}"}
        run.finished_at = datetime.now(UTC)
        db.flush()
        logger.exception(
            "rotation stress run failed", extra={"run_id": str(run.id)}
        )
        raise
    return run


def verify_stress_run(run: RotationStressRun) -> dict[str, Any]:
    """Recompute the checksum from the STORED request_parameters + result and
    compare (idempotent, read-only)."""
    recomputed = run_checksum(run.request_parameters, run.result)
    valid = run.checksum_sha256 is not None and run.checksum_sha256 == recomputed
    return {
        "rotation_stress_run_id": str(run.id),
        "valid": valid,
        "checksum": run.checksum_sha256,
        "recomputed_checksum": recomputed,
        "engine_version": run.engine_version,
        "note": (
            "Verification recomputes the sha256 over the stored "
            "request_parameters + result (canonical JSON, sorted keys); no "
            "engine re-execution."
        ),
    }


def payload_to_dict(run: RotationStressRun) -> dict[str, Any]:
    """API serialization of one rotation stress run."""
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "engine_version": run.engine_version,
        "packs": run.packs,
        "candidates": run.candidates,
        "request_parameters": run.request_parameters,
        "result": run.result,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "checksum_sha256": run.checksum_sha256,
        "idempotency_key": run.idempotency_key,
        "created_by": str(run.created_by) if run.created_by else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "status_url": f"/api/v1/rotation-stress-runs/{run.id}",
    }


def run_summary(run: RotationStressRun) -> dict[str, Any]:
    """Compact serialization for list endpoints (no result payload)."""
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "engine_version": run.engine_version,
        "pack_codes": [p.get("code") for p in (run.packs or [])],
        "candidate_keys": [c.get("candidate_key") for c in (run.candidates or [])],
        "checksum_sha256": run.checksum_sha256,
        "idempotency_key": run.idempotency_key,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "status_url": f"/api/v1/rotation-stress-runs/{run.id}",
    }

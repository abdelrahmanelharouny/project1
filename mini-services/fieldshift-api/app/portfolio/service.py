"""Farm portfolio service (P2.F) — DB bridge and run orchestration.

Builds per-field FarmContexts and candidates (reusing the rotation service's
context builder), prepares and solves the portfolio model, persists the
immutable run + allocations with a reproducibility checksum, and assembles
the comparison reports. Determinism and idempotency follow the rotation run
precedent (202-style inline execution, replay by (farm, idempotency_key)).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.db.models_p2 import PortfolioAllocation, PortfolioRun
from app.knowledge.service import load_knowledge
from app.portfolio import contracts, evaluation, optimizer
from app.rotation import candidates as candidates_mod
from app.rotation.optimizer import PROFILE_WEIGHTS
from app.rotation.problem import SeasonSpec
from app.rotation.service import build_farm_context

logger = logging.getLogger("croptwist.portfolio.service")

DEFAULT_SEASON_START_MMDD = "-09-01"


def _default_seasons(count: int) -> list[SeasonSpec]:
    """Next `count` agricultural seasons (Sep 1 start, Aug 31 end), northern
    or southern hemisphere agnostic (start anchored to the current date)."""
    today = date.today()
    start_year = today.year if today >= date(today.year, 9, 1) else today.year - 1
    seasons: list[SeasonSpec] = []
    for i in range(count):
        start = date(start_year + i, 9, 1)
        end = date(start_year + i + 1, 8, 31)
        seasons.append(SeasonSpec(label=f"season_{i + 1}", start_date=start, end_date=end))
    return seasons


def _validate_explicit_seasons(raw: Any) -> list[SeasonSpec]:
    seasons: list[SeasonSpec] = []
    if not isinstance(raw, list) or not raw:
        raise ValidationFailed(
            "seasons must be a non-empty list when provided.",
            details=[{"field": "seasons"}],
        )
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationFailed(
                f"seasons[{i}] must be an object.",
                details=[{"field": f"seasons[{i}]"}],
            )
        label = item.get("label")
        start, end = item.get("start_date"), item.get("end_date")
        if not (isinstance(label, str) and label) or not isinstance(start, str) or not isinstance(end, str):
            raise ValidationFailed(
                f"seasons[{i}] needs label, start_date, end_date (ISO strings).",
                details=[{"field": f"seasons[{i}]"}],
            )
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as exc:
            raise ValidationFailed(
                f"seasons[{i}] dates must be ISO (YYYY-MM-DD).",
                details=[{"field": f"seasons[{i}]"}],
            ) from exc
        if end_date <= start_date:
            raise ValidationFailed(
                f"seasons[{i}] end_date must be after start_date.",
                details=[{"field": f"seasons[{i}]"}],
            )
        seasons.append(SeasonSpec(label=label, start_date=start_date, end_date=end_date))
    labels = [s.label for s in seasons]
    if len(set(labels)) != len(labels):
        raise ValidationFailed("season labels must be unique.", details=[{"field": "seasons"}])
    return seasons


def start_portfolio_run(
    db: Session,
    *,
    farm: dbm.Farm,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dict[str, Any]:
    """Validate, execute inline and persist one portfolio run."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(PortfolioRun).where(
                PortfolioRun.idempotency_key == idempotency_key,
                PortfolioRun.farm_id == farm.id,
            )
        )
        if existing is not None:
            return payload_to_dict(db, existing)

    season_count = contracts.validate_season_count(payload.get("season_count"))
    seasons = (
        _validate_explicit_seasons(payload.get("seasons"))
        if payload.get("seasons")
        else _default_seasons(season_count)
    )
    weights = contracts.validate_objective_weights(payload.get("objective_weights"))
    mode = contracts.validate_mode(payload.get("mode"))

    field_rows = list(
        db.scalars(
            select(dbm.Field)
            .where(dbm.Field.farm_id == farm.id, dbm.Field.status == "active")
            .order_by(dbm.Field.name.asc())
        )
    )
    requested_ids = payload.get("field_ids")
    if requested_ids:
        wanted = {str(x) for x in requested_ids}
        field_rows = [f for f in field_rows if str(f.id) in wanted]
        if not field_rows:
            raise ValidationFailed(
                "field_ids matched no active field of this farm.",
                details=[{"field": "field_ids"}],
            )
    if not field_rows:
        raise ValidationFailed(
            "The farm has no active fields to optimize.",
            details=[{"field": "farm_id"}],
        )

    constraints, constraint_notes = contracts.validate_constraints(
        payload.get("constraints"),
        has_labor_resources=_farm_has_resource(db, farm.id, "labor_crew"),
        has_machinery_resources=_farm_has_any_resource(
            db, farm.id, ("tractor", "implement")
        ),
    )
    scenario = contracts.validate_scenario(payload.get("scenario"))

    # The shared farm allocation comes from the request, else from the farm's
    # water constraint record (same source the per-field rotation reads).
    if constraints.get("water_allocation_m3") is None:
        farm_alloc = _farm_water_allocation(db, farm.id)
        if farm_alloc is not None:
            constraints["water_allocation_m3"] = farm_alloc
            constraint_notes.append(
                {
                    "code": "water_allocation_m3",
                    "reason": "taken from the farm's water_allocation_m3_per_season constraint record",
                }
            )

    knowledge = load_knowledge(db)
    if not knowledge.crops:
        raise ValidationFailed(
            "No active knowledge pack with crops — import a knowledge pack first.",
            details=[{"field": "knowledge"}],
        )

    request_parameters = {
        "engine": contracts.PORTFOLIO_ENGINE_VERSION,
        "seasons": [
            {"label": s.label, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat()}
            for s in seasons
        ],
        "objective_weights": weights,
        "mode": mode,
        "constraints": {k: v for k, v in constraints.items()},
        "scenario": scenario,
        "field_ids": [str(f.id) for f in field_rows],
        "constraint_notes": constraint_notes,
        "knowledge_pack_refs": [dict(r) for r in knowledge.pack_refs],
    }

    run = PortfolioRun(
        farm_id=farm.id,
        status="running",
        request_parameters=request_parameters,
        field_ids=[str(f.id) for f in field_rows],
        objective_weights=weights,
        scenario=scenario,
        engine_version=contracts.PORTFOLIO_ENGINE_VERSION,
        idempotency_key=idempotency_key,
        created_by=getattr(created_by, "id", None),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    try:
        # Per-field context + candidates (reuse of the rotation builders).
        candidates_by_field: dict[str, dict[str, dict[str, Any]]] = {}
        field_inputs: list[optimizer.FieldInput] = []
        warnings: list[str] = []
        not_evaluated: list[dict[str, Any]] = []
        feature_run_refs: dict[str, str | None] = {}
        for field in field_rows:
            hemisphere = payload.get("hemisphere") or "north"
            farm_ctx, field_warnings, _history_ids, evidence_run = build_farm_context(
                db, field, seasons, payload.get("evidence_run_id"), hemisphere
            )
            for w in field_warnings:
                warnings.append(f"{field.name}: {w}")
            feature_run_refs[str(field.id)] = str(evidence_run.id) if evidence_run else None
            candidates_by_field[str(field.id)] = candidates_mod.generate_candidates(
                knowledge, farm_ctx
            )
            field_inputs.append(
                optimizer.FieldInput(
                    field_id=str(field.id), area_ha=float(field.area_ha), farm=farm_ctx
                )
            )

        prepared = optimizer.prepare_model(
            fields=field_inputs,
            seasons=seasons,
            candidates_by_field=candidates_by_field,
            knowledge=knowledge,
            weights=weights,
            mode=mode,
            constraints=constraints,
            scenario=scenario,
            not_evaluated=not_evaluated,
            warnings=warnings,
        )
        solution = optimizer.solve_portfolio(prepared)

        result: dict[str, Any] = {
            "status": solution.status,
            "objective_value": solution.objective_value,
            "per_criterion_scores": solution.per_criterion_scores,
            "binding_constraints": solution.binding_constraints,
            "conflicts": solution.conflicts,
            "diagnostics": solution.diagnostics,
            "notes": solution.notes,
            "weight_shares": prepared.weight_shares,
            "feature_run_refs": feature_run_refs,
        }

        # Independent comparison + scenario resilience (best effort; they must
        # never fail the run itself).
        try:
            independent = evaluation.independent_field_comparison(prepared)
            result["independent_comparison"] = evaluation.compare_criteria(
                solution.per_criterion_scores,
                independent["independent_scores"],
                solution.binding_constraints,
            )
        except Exception as exc:  # noqa: BLE001
            not_evaluated.append(
                {
                    "code": "independent_comparison",
                    "reason": f"per-field independent baseline could not be computed: {exc}",
                }
            )

        scenario_result: dict[str, Any] | None = None
        if scenario is not None and solution.status in ("optimal", "feasible"):
            try:
                stressed_model = optimizer.prepare_model(
                    fields=field_inputs,
                    seasons=seasons,
                    candidates_by_field=candidates_by_field,
                    knowledge=knowledge,
                    weights=weights,
                    mode=mode,
                    constraints=constraints,
                    scenario=scenario,
                )
                stressed_solution = optimizer.solve_portfolio(stressed_model)
                scenario_result = evaluation.scenario_comparison(
                    {
                        "status": solution.status,
                        "allocations": solution.allocations,
                    },
                    {
                        "status": stressed_solution.status,
                        "allocations": stressed_solution.allocations,
                        "conflicts": stressed_solution.conflicts,
                    },
                    scenario,
                )
                result["scenario_evaluation"] = scenario_result
            except Exception as exc:  # noqa: BLE001
                not_evaluated.append(
                    {
                        "code": "scenario_evaluation",
                        "reason": f"scenario re-solve failed: {exc}",
                    }
                )

        allocations = [
            a for a in solution.allocations if a.get("status") == optimizer.ASSIGNED_STATUS
        ]
        checksum = contracts.canonical_checksum(
            contracts.run_checksum_payload(
                engine_version=contracts.PORTFOLIO_ENGINE_VERSION,
                request_parameters=request_parameters,
                result={k: v for k, v in result.items()},
                allocations=allocations,
            )
        )
        run.result = result
        run.solver_diagnostics = solution.diagnostics
        run.warnings = prepared.warnings
        run.not_evaluated = prepared.not_evaluated + not_evaluated
        run.status = "succeeded" if solution.status in ("optimal", "feasible") else "failed"
        run.finished_at = datetime.now(UTC)
        run.checksum_sha256 = checksum
        db.flush()

        for a in allocations:
            db.add(
                PortfolioAllocation(
                    run_id=run.id,
                    field_id=uuid.UUID(str(a["field_id"])),
                    season_label=str(a["season_label"]),
                    season_index=int(a["season_index"]),
                    crop_code=str(a["crop_code"]),
                    area_ha=round(float(a["area_ha"]), 2),
                    family_key=a.get("family_key"),
                    status=str(a.get("status") or "assigned"),
                    metadata_json={
                        "demand_mm": a.get("demand_mm"),
                        "demand_basis": a.get("demand_basis"),
                    },
                )
            )
        db.commit()
        logger.info(
            "portfolio run succeeded",
            extra={
                "run_id": str(run.id),
                "status": run.status,
                "allocations": len(allocations),
            },
        )
        return payload_to_dict(db, run)
    except Exception as exc:
        db.rollback()
        failed = db.scalar(select(PortfolioRun).where(PortfolioRun.id == run.id))
        if failed is not None:
            failed.status = "failed"
            failed.not_evaluated = list(failed.not_evaluated or []) + [
                {"code": "execution", "reason": f"{type(exc).__name__}: {exc}"}
            ]
            failed.finished_at = datetime.now(UTC)
            db.commit()
            return payload_to_dict(db, failed)
        raise


def _farm_has_resource(db: Session, farm_id: uuid.UUID, resource_type: str) -> bool:
    return (
        db.scalar(
            select(dbm.FarmResource.id).where(
                dbm.FarmResource.farm_id == farm_id,
                dbm.FarmResource.resource_type == resource_type,
            )
        )
        is not None
    )


def _farm_has_any_resource(db: Session, farm_id: uuid.UUID, resource_types: tuple[str, ...]) -> bool:
    return (
        db.scalar(
            select(dbm.FarmResource.id).where(
                dbm.FarmResource.farm_id == farm_id,
                dbm.FarmResource.resource_type.in_(resource_types),
            )
        )
        is not None
    )


def _farm_water_allocation(db: Session, farm_id: uuid.UUID) -> float | None:
    rows = db.scalars(
        select(dbm.FarmConstraint).where(dbm.FarmConstraint.farm_id == farm_id)
    ).all()
    for c in rows:
        if c.constraint_code == "water_allocation_m3_per_season" and c.value_numeric is not None:
            return float(c.value_numeric)
    return None


def get_run_scoped(db: Session, principal: Any, run_id: uuid.UUID) -> PortfolioRun:
    from app.domains.identity.service import get_farm_for_principal

    run = db.scalar(select(PortfolioRun).where(PortfolioRun.id == run_id))
    if run is None:
        raise NotFound("Portfolio run not found.", details=[{"run_id": str(run_id)}])
    # Tenant gate: the farm must be visible to the principal (404 without leak).
    get_farm_for_principal(db, principal, run.farm_id)
    return run


def payload_to_dict(db: Session, run: PortfolioRun) -> dict[str, Any]:
    allocations = list(
        db.scalars(
            select(PortfolioAllocation)
            .where(PortfolioAllocation.run_id == run.id)
            .order_by(
                PortfolioAllocation.season_index.asc(),
                PortfolioAllocation.field_id.asc(),
                PortfolioAllocation.crop_code.asc(),
            )
        )
    )
    return {
        "id": str(run.id),
        "farm_id": str(run.farm_id),
        "status": run.status,
        "request_parameters": run.request_parameters,
        "result": run.result,
        "field_ids": run.field_ids,
        "objective_weights": run.objective_weights,
        "scenario": run.scenario,
        "engine_version": run.engine_version,
        "solver_diagnostics": run.solver_diagnostics,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "checksum_sha256": run.checksum_sha256,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "allocations": [
            {
                "field_id": str(a.field_id),
                "season_label": a.season_label,
                "season_index": a.season_index,
                "crop_code": a.crop_code,
                "area_ha": float(a.area_ha),
                "family_key": a.family_key,
                "status": a.status,
                "metadata": a.metadata_json,
            }
            for a in allocations
        ],
    }

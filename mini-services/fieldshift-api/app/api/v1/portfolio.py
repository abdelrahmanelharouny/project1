"""Farm Portfolio Intelligence endpoints (P2.F).

- GET  /portfolio/constraints      — objective vocabulary + honesty notes
- POST /farms/{farm_id}/portfolio-runs — create + solve (org manager role)
- GET  /farms/{farm_id}/portfolio-runs — list newest first
- GET  /portfolio-runs/{run_id}    — detail with allocations
- POST /portfolio-runs/{run_id}/verify — checksum recompute

Farm-scoped endpoints are tenant-scoped via get_farm_for_principal; the run
detail re-checks the farm gate so a known run id from another tenant 404s.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db import models as dbm
from app.db.models_p2 import PortfolioRun
from app.domains.identity.service import get_farm_for_principal, get_principal
from app.portfolio import contracts
from app.portfolio import service as portfolio_service

router = APIRouter(tags=["portfolio"])


class PortfolioRunRequest(BaseModel):
    season_count: int | None = Field(None, ge=1, le=3)
    seasons: list[dict[str, Any]] | None = None
    objective_weights: dict[str, float] | None = None
    mode: str | None = None
    constraints: dict[str, float | None] | None = None
    scenario: dict[str, Any] | None = None
    field_ids: list[uuid.UUID] | None = None
    hemisphere: str | None = None
    evidence_run_id: uuid.UUID | None = None
    idempotency_key: str | None = None
    notes: str | None = None


@router.get("/portfolio/constraints")
def portfolio_constraints() -> dict:
    """The disclosed objective/constraint vocabulary of the portfolio engine,
    including what is recorded-but-not-enforced (labor/machinery — no sourced
    per-crop coefficients exist) and the steering-objective disclosure."""
    return {
        "engine_version": contracts.PORTFOLIO_ENGINE_VERSION,
        "objective_keys": list(contracts.OBJECTIVE_KEYS),
        "objective_modes": list(contracts.OBJECTIVE_MODES),
        "constraint_keys": list(contracts.CONSTRAINT_KEYS),
        "scenario_keys": ["water_allocation_multiplier", "labor_capacity_multiplier", "label"],
        "disclosures": [
            "The weighted objective is a steering device: a disclosed weighted "
            "sum of normalized 0-1 sub-scores. Per-criterion values are always "
            "reported separately; comparisons never cross units.",
            "Absent shared constraints are reported as not_evaluated — never "
            "silently treated as unlimited.",
            "Labor and machinery capacities are recorded but not enforced: no "
            "sourced per-crop labor/machinery coefficient exists anywhere in "
            "the platform, and coefficients are never invented.",
            "No yield predictions or economic outcomes are produced: the "
            "platform has no validated yield model and no cost/price data.",
        ],
    }


@router.post("/farms/{farm_id}/portfolio-runs")
def create_portfolio_run(
    farm_id: uuid.UUID,
    request: PortfolioRunRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Create and solve one farm-level portfolio run (inline, deterministic)."""
    farm = get_farm_for_principal(db, principal, farm_id)
    principal.require_org_role(farm.organization_id, "manager")
    return portfolio_service.start_portfolio_run(
        db, farm=farm, payload=request.model_dump(exclude_none=False), created_by=principal
    )


@router.get("/farms/{farm_id}/portfolio-runs")
def list_portfolio_runs(
    farm_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    farm = get_farm_for_principal(db, principal, farm_id)
    total = db.scalar(
        select(dbm.func.count(PortfolioRun.id)).where(PortfolioRun.farm_id == farm.id)
    )
    rows = list(
        db.scalars(
            select(PortfolioRun)
            .where(PortfolioRun.farm_id == farm.id)
            .order_by(PortfolioRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "farm_id": str(farm.id),
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "engine_version": r.engine_version,
                "scenario": r.scenario,
                "field_ids": r.field_ids,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "checksum_sha256": r.checksum_sha256,
            }
            for r in rows
        ],
    }


@router.get("/portfolio-runs/{run_id}")
def portfolio_run_detail(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = portfolio_service.get_run_scoped(db, principal, run_id)
    return portfolio_service.payload_to_dict(db, run)


@router.post("/portfolio-runs/{run_id}/verify")
def verify_portfolio_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Independently recompute the run checksum from the persisted rows and
    compare (reproducibility contract)."""
    from app.portfolio.contracts import canonical_checksum, run_checksum_payload

    run = portfolio_service.get_run_scoped(db, principal, run_id)
    # Recompute from the persisted allocations table (the authoritative rows).
    allocations = portfolio_service.payload_to_dict(db, run)["allocations"]
    recomputed = canonical_checksum(
        run_checksum_payload(
            engine_version=run.engine_version,
            request_parameters=run.request_parameters or {},
            result=run.result or {},
            allocations=allocations,
        )
    )
    valid = bool(run.checksum_sha256) and recomputed == run.checksum_sha256
    return {
        "run_id": str(run.id),
        "valid": valid,
        "stored_checksum": run.checksum_sha256,
        "recomputed_checksum": recomputed,
        "engine_version": run.engine_version,
        "note": (
            "Verification recomputes the canonical checksum from the persisted "
            "request parameters, result and allocation rows — identical inputs "
            "and engine version must reproduce it byte-for-byte."
        ),
    }

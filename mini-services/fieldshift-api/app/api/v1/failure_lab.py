"""Rotation Failure Lab endpoints (P2.D).

- GET  /failure-lab/packs                        — preset stress-pack catalog
- POST /fields/{field_id}/rotation-stress-runs   — run the lab inline (idempotent)
- GET  /fields/{field_id}/rotation-stress-runs   — the field's run history (newest first)
- GET  /rotation-stress-runs/{run_id}            — run detail (result, metrics, checksums)
- POST /rotation-stress-runs/{run_id}/verify     — recompute the checksum from stored inputs

All endpoints are tenant-scoped through the field's farm; ownership claims
from the client are never trusted. Run creation executes the engine inline
and requires the 'agronomist' farm role (same gate as the rotation engine).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound
from app.db import models as dbm
from app.db.models_p2 import RotationStressRun
from app.domains.identity.service import get_field_for_principal, get_principal, require_farm_role
from app.failure_lab import contracts as fl_contracts
from app.failure_lab import service as failure_lab_service

router = APIRouter(tags=["failure-lab"])


class RotationStressRunRequest(BaseModel):
    packs: list[str | dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Preset pack codes or objects ({code, parameters, ...}) overriding "
            "preset parameters or defining a new user-defined pack. Defaults "
            "to ALL preset packs."
        ),
    )
    candidates: list[str] | None = Field(
        default=None,
        description="Subset of 'baseline', 'recommended', 'alternative' (default: all).",
    )
    idempotency_key: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    hemisphere: str | None = Field(
        default=None,
        pattern="^(north|south)$",
        description="Climate-evidence hemisphere (default 'north').",
    )
    evidence_run_id: str | None = None


@router.get("/failure-lab/packs")
def list_stress_packs() -> dict:
    """Preset pack catalog with parameters, provenance and assumptions."""
    return fl_contracts.pack_catalog()


@router.post("/fields/{field_id}/rotation-stress-runs")
def create_rotation_stress_run(
    field_id: uuid.UUID,
    body: RotationStressRunRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    # RBAC (P0-2): heavy engine creation is an agronomist+ mutation, enforced
    # BEFORE any engine/knowledge work.
    require_farm_role(db, principal, db.get(dbm.Farm, field.farm_id), "agronomist")
    run = failure_lab_service.start_rotation_stress_run(
        db,
        field,
        principal,
        {
            "packs": body.packs,
            "candidates": body.candidates,
            "idempotency_key": body.idempotency_key,
            "notes": body.notes,
            "hemisphere": body.hemisphere,
            "evidence_run_id": body.evidence_run_id,
        },
    )
    db.commit()
    db.refresh(run)
    return failure_lab_service.payload_to_dict(run)


@router.get("/fields/{field_id}/rotation-stress-runs")
def list_rotation_stress_runs(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(RotationStressRun)
        .where(RotationStressRun.field_id == field.id)
        .order_by(RotationStressRun.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "field_id": str(field.id),
        "runs": [failure_lab_service.run_summary(r) for r in rows],
        "note": (
            "Stress runs are deterministic what-if evaluations of pinned "
            "candidate rotations under named stress packs; a result-bearing "
            "run is immutable and reproducible from its request_parameters."
        ),
    }


def _get_run_scoped(db: Session, run_id: uuid.UUID, principal: Any) -> RotationStressRun:
    run = db.get(RotationStressRun, run_id)
    if run is None:
        raise NotFound("Rotation stress run not found.")
    get_field_for_principal(db, principal, run.field_id)  # tenant scoping
    return run


@router.get("/rotation-stress-runs/{run_id}")
def get_rotation_stress_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    return failure_lab_service.payload_to_dict(run)


@router.post("/rotation-stress-runs/{run_id}/verify")
def verify_rotation_stress_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    return failure_lab_service.verify_stress_run(run)

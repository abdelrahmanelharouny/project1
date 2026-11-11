"""Soil Memory endpoints (P2.C).

- POST /fields/{id}/soil-memory/snapshots        — assemble + persist a snapshot
- GET  /fields/{id}/soil-memory/snapshots        — list snapshots
- GET  /fields/{id}/soil-memory/timeline         — full longitudinal timeline
- POST /fields/{id}/soil-memory/change-estimates — conservative change estimate
- GET  /fields/{id}/soil-memory/alerts           — evidence-based soil alerts

All field-scoped endpoints are tenant-scoped through the field's farm.
Snapshots and estimates are append-only and checksummed; measurements are
never modified (P2.C immutability rule).
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db import models as dbm
from app.db.models_p2 import SoilStateSnapshot
from app.domains.identity.service import get_field_for_principal, get_principal
from app.soil import memory_service

router = APIRouter(tags=["soil-memory"])


class SnapshotRequest(BaseModel):
    as_of: date


class ChangeEstimateRequest(BaseModel):
    start_snapshot_id: uuid.UUID
    end_snapshot_id: uuid.UUID


@router.post("/fields/{field_id}/soil-memory/snapshots")
def create_soil_snapshot(
    field_id: uuid.UUID,
    request: SnapshotRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Assemble an immutable, checksummed soil state snapshot as of a date
    (measurements + management events + nutrient flows + crop history, with
    per-value evidence classes preserved). Idempotent by checksum."""
    field = get_field_for_principal(db, principal, field_id)
    return memory_service.create_snapshot(db, field, as_of=request.as_of, created_by=principal)


@router.get("/fields/{field_id}/soil-memory/snapshots")
def list_soil_snapshots(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = list(
        db.scalars(
            select(SoilStateSnapshot)
            .where(SoilStateSnapshot.field_id == field.id)
            .order_by(SoilStateSnapshot.as_of.desc())
        )
    )
    return {
        "field_id": str(field.id),
        "snapshots": [
            {
                "id": str(s.id),
                "as_of": s.as_of.date().isoformat(),
                "checksum_sha256": s.checksum_sha256,
                "missing_evidence": s.missing_evidence,
                "variable_count": len((s.snapshot or {}).get("variables", [])),
                "engine_version": s.engine_version,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ],
    }


@router.get("/fields/{field_id}/soil-memory/timeline")
def soil_memory_timeline(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Longitudinal soil timeline: measurements (with evidence classes),
    management interventions, snapshots and data gaps — ordered by time."""
    field = get_field_for_principal(db, principal, field_id)
    return memory_service.timeline(db, field)


@router.post("/fields/{field_id}/soil-memory/change-estimates")
def create_soil_change_estimate(
    field_id: uuid.UUID,
    request: ChangeEstimateRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Conservative change estimate between two snapshots (SOC trajectory +
    nutrient balance context), with assumptions, uncertainty and explicit
    ESTIMATED labelling — never presented as measured improvement."""
    field = get_field_for_principal(db, principal, field_id)
    return memory_service.create_change_estimate(
        db,
        field,
        start_snapshot_id=request.start_snapshot_id,
        end_snapshot_id=request.end_snapshot_id,
    )


@router.get("/fields/{field_id}/soil-memory/alerts")
def soil_memory_alerts(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Evidence-based soil health screening alerts (nutrient depletion,
    salinity class, SOC trajectory direction, erosion risk) with citations.
    Thresholds come from the existing engines' documented sources — no
    universal thresholds are invented."""
    field = get_field_for_principal(db, principal, field_id)
    return {
        "field_id": str(field.id),
        "alerts": memory_service.current_alerts(db, field.id),
        "note": (
            "Alerts are screening signals derived from documented engine "
            "outputs; a nutrient balance is an accounting statement, not a "
            "measured soil stock change."
        ),
    }

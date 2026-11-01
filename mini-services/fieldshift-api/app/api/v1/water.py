"""Water Intelligence endpoints (Milestone 6A, Phase 7).

- GET  /water/methods                          — versioned methodology catalog
- GET  /fields/{id}/water/knowledge-readiness  — crop-by-crop readiness matrix
- POST /fields/{id}/water-plans                — create a seasonal water plan (inline 202-style)
- GET  /fields/{id}/water-plans                — list the field's plans
- GET  /water-plans/{id}                       — plan detail (immutable snapshot)

All field-scoped endpoints are tenant-scoped through the field's farm.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Conflict, NotFound
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal
from app.knowledge.service import load_knowledge
from app.water import service as water_service
from app.water.contracts import (
    EFFECTIVE_RAINFALL_METHOD_INFO,
    IRRIGATION_EFFICIENCY_CLASSES,
    PTF_VERSION,
    SOIL_SOURCES,
    WATER_ENGINE_VERSION,
    WATER_METHODS_VERSION,
)
from app.water.knowledge import readiness_matrix

router = APIRouter(tags=["water"])


@router.get("/water/methods")
def water_methods() -> dict:
    """The versioned water methodology catalog: every effective-rainfall
    method, soil source and efficiency class with its citation and conditions.
    Unverified methods (e.g. USDA-SCS) are absent by design."""
    return {
        "water_engine_version": WATER_ENGINE_VERSION,
        "methods_version": WATER_METHODS_VERSION,
        "effective_rainfall_methods": [
            EFFECTIVE_RAINFALL_METHOD_INFO[code] for code in sorted(EFFECTIVE_RAINFALL_METHOD_INFO)
        ],
        "soil_sources": [
            {
                "code": "none",
                "detail": "no soil water-holding inputs — the FAO I&D 33 no-storage "
                "fallback (IN = ETc − Pe) applies, disclosed",
            },
            {
                "code": "farmer_measured",
                "detail": "θFC/θWP (+ optional Zr, p) supplied by the farmer "
                "(evidence class farmer_reported_record)",
            },
            {
                "code": "ptf_texture",
                "detail": "θFC/θWP estimated by the Saxton & Rawls (2006) pedotransfer "
                f"function over the field's texture (PTF version {PTF_VERSION}; "
                "validity domain enforced; single-layer extrapolation disclosed)",
            },
        ],
        "irrigation_efficiency_classes": list(IRRIGATION_EFFICIENCY_CLASSES),
        "unit_identities": {
            "mm_over_ha_to_m3": 10.0,
            "mm_over_m2_to_litres": 1.0,
        },
        "not_implemented": [
            {
                "item": "local ET0 computation (Penman-Monteith / Hargreaves)",
                "reason": "no radiation/humidity evidence contract; ET0 is consumed "
                "from the ERA5 product (FAO-56 reference surface). Backlog W-6.",
            },
            {
                "item": "USDA-SCS effective rainfall",
                "reason": "coefficients could not be verified verbatim from the "
                "primary source during M6A Phase 0. Backlog W-5.",
            },
            {
                "item": "dual Kc (Kcb + Ke)",
                "reason": "no sourced Kcb rows in the knowledge base. FAO-56 ch. 7 "
                "machinery documented; inputs absent.",
            },
            {
                "item": "irrigation scheduling / daily water accounting",
                "reason": "different decision product from seasonal planning. "
                "Backlog W-7.",
            },
        ],
    }


@router.get("/fields/{field_id}/water/knowledge-readiness")
def field_water_readiness(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    get_field_for_principal(db, principal, field_id)  # tenant scoping
    knowledge = load_knowledge(db)
    matrix = readiness_matrix(knowledge)
    matrix["field_id"] = str(field_id)
    return matrix


@router.post("/fields/{field_id}/water-plans", status_code=status.HTTP_201_CREATED)
def create_water_plan(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    plan = water_service.start_water_plan(db, field=field, payload=body, created_by=principal)
    db.commit()
    return water_service.plan_payload(plan)


@router.get("/fields/{field_id}/water-plans")
def list_water_plans(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.WaterPlan)
        .where(dbm.WaterPlan.field_id == field.id)
        .order_by(dbm.WaterPlan.created_at.desc())
        .limit(50)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [water_service.plan_payload(p, include_result=False) for p in rows],
    }


@router.get("/water-plans/{plan_id}")
def get_water_plan(
    plan_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    plan = db.get(dbm.WaterPlan, plan_id)
    if plan is None:
        raise NotFound("Water plan not found.")
    get_field_for_principal(db, principal, plan.field_id)  # tenant scoping
    return water_service.plan_payload(plan)


@router.delete("/water-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_water_plan(
    plan_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    plan = db.get(dbm.WaterPlan, plan_id)
    if plan is None:
        raise NotFound("Water plan not found.")
    get_field_for_principal(db, principal, plan.field_id)
    # M7.1 F-13: a water plan referenced by a field state is part of that
    # state's immutable input history — deleting it would silently rewrite
    # historical meaning. Restrict deletion while referenced (FK RESTRICT in
    # migration 0007 is the database-level backstop; this pre-check gives a
    # clear 409 instead of an integrity error).
    from sqlalchemy import func as sa_func

    referenced = db.scalar(
        select(sa_func.count())
        .select_from(dbm.FieldState)
        .where(dbm.FieldState.water_plan_id == plan_id)
    )
    if referenced:
        raise Conflict(
            f"Water plan is referenced by {referenced} field state(s) and "
            "cannot be deleted — field-state snapshots are immutable "
            "references to the plans they were assembled from.",
            details=[{"field": "water_plan_id", "referenced_by_field_states": referenced}],
        )
    db.delete(plan)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Sensitivity analysis endpoints (Milestone 7.4).

- POST /scenario-executions/{run_id}/sensitivity-analyses   — create + run an
  analysis of a RESULT-BEARING M7.3 execution (idempotent)
- GET  /scenario-executions/{run_id}/sensitivity-analyses   — the run's analyses
- GET  /sensitivity-analyses/{analysis_id}                  — detail
- GET  /sensitivity-analyses/{analysis_id}/evaluations      — parameter tuples
- GET  /sensitivity-analyses/{analysis_id}/responses        — OAT responses
- GET  /sensitivity-analyses/{analysis_id}/grid             — joint grid
- GET  /sensitivity-analyses/{analysis_id}/uncertainty      — registry
- POST /sensitivity-analyses/{analysis_id}/verify           — checksum + pins

Every endpoint is tenant-scoped through the analysis/run's field → farm;
ownership claims from the client are never trusted. No endpoint mutates a
result-bearing analysis (application + database trigger enforce this).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal, require_farm_role
from app.sensitivity import contracts as sc
from app.sensitivity import service as sensitivity_service

router = APIRouter(tags=["sensitivity"])


def _get_analysis_scoped(
    db: Session, analysis_id: uuid.UUID, principal: Any
) -> dbm.SensitivityAnalysis:
    analysis = db.get(dbm.SensitivityAnalysis, analysis_id)
    if analysis is None:
        raise NotFound("Sensitivity analysis not found.")
    get_field_for_principal(db, principal, analysis.field_id)  # tenant scoping
    return analysis


def _get_run_scoped(db: Session, run_id: uuid.UUID, principal: Any) -> dbm.ScenarioExecutionRun:
    run = db.get(dbm.ScenarioExecutionRun, run_id)
    if run is None:
        raise NotFound("Scenario execution not found.")
    get_field_for_principal(db, principal, run.field_id)  # tenant scoping
    return run


@router.post("/scenario-executions/{run_id}/sensitivity-analyses")
def create_sensitivity_analysis(
    run_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    # RBAC (P0-2): sensitivity analyses are heavy derived-engine work —
    # agronomist+ on the owning run's field → farm.
    field = db.get(dbm.Field, run.field_id)
    require_farm_role(db, principal, db.get(dbm.Farm, field.farm_id), "agronomist")
    analysis = sensitivity_service.start_sensitivity_analysis(
        db, run, payload=payload, created_by=principal.user
    )
    evaluations = db.execute(
        select(dbm.SensitivityEvaluation)
        .where(dbm.SensitivityEvaluation.analysis_id == analysis.id)
        .order_by(
            dbm.SensitivityEvaluation.is_reference.desc(),
            dbm.SensitivityEvaluation.temperature_delta_c.asc().nullsfirst(),
            dbm.SensitivityEvaluation.precipitation_multiplier.asc().nullsfirst(),
        )
    ).scalars().all()
    return sensitivity_service.analysis_detail_payload(analysis, list(evaluations))


@router.get("/scenario-executions/{run_id}/sensitivity-analyses")
def list_sensitivity_analyses(
    run_id: uuid.UUID,
    analysis_status: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = _get_run_scoped(db, run_id, principal)
    query = (
        select(dbm.SensitivityAnalysis)
        .where(dbm.SensitivityAnalysis.source_execution_run_id == run.id)
        .order_by(dbm.SensitivityAnalysis.created_at.desc())
    )
    if analysis_status:
        if analysis_status not in sc.ANALYSIS_STATUSES:
            raise ValidationFailed(
                "Unknown analysis_status filter.",
                details=[{"field": "analysis_status", "reason": analysis_status}],
            )
        query = query.where(dbm.SensitivityAnalysis.analysis_status == analysis_status)
    analyses = db.execute(query).scalars().all()
    return {
        "run_id": str(run.id),
        "items": [sensitivity_service.analysis_payload(a) for a in analyses],
        "count": len(analyses),
        "note": (
            "Analyses are derived analytical artifacts over one immutable "
            "execution. A changed design, method version or engine version "
            "creates a new analysis."
        ),
    }


@router.get("/sensitivity-analyses/{analysis_id}")
def get_sensitivity_analysis(
    analysis_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    evaluations = db.execute(
        select(dbm.SensitivityEvaluation)
        .where(dbm.SensitivityEvaluation.analysis_id == analysis.id)
        .order_by(
            dbm.SensitivityEvaluation.is_reference.desc(),
            dbm.SensitivityEvaluation.temperature_delta_c.asc().nullsfirst(),
            dbm.SensitivityEvaluation.precipitation_multiplier.asc().nullsfirst(),
        )
    ).scalars().all()
    return sensitivity_service.analysis_detail_payload(analysis, list(evaluations))


@router.get("/sensitivity-analyses/{analysis_id}/evaluations")
def list_analysis_evaluations(
    analysis_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    rows = db.execute(
        select(dbm.SensitivityEvaluation)
        .where(dbm.SensitivityEvaluation.analysis_id == analysis.id)
        .order_by(
            dbm.SensitivityEvaluation.is_reference.desc(),
            dbm.SensitivityEvaluation.temperature_delta_c.asc().nullsfirst(),
            dbm.SensitivityEvaluation.precipitation_multiplier.asc().nullsfirst(),
        )
    ).scalars().all()
    return {
        "analysis_id": str(analysis.id),
        "items": [sensitivity_service.evaluation_payload(r) for r in rows],
        "count": len(rows),
    }


@router.get("/sensitivity-analyses/{analysis_id}/responses")
def list_analysis_responses(
    analysis_id: uuid.UUID,
    parameter_code: str | None = None,
    feature_code: str | None = None,
    aggregation_level: str | None = None,
    response_classification: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    query = select(dbm.SensitivityOatResponse).where(
        dbm.SensitivityOatResponse.analysis_id == analysis.id
    )
    if parameter_code:
        if parameter_code not in sc.PARAMETER_CODES:
            raise ValidationFailed(
                "Unknown parameter_code filter.",
                details=[{"field": "parameter_code", "reason": parameter_code}],
            )
        query = query.where(dbm.SensitivityOatResponse.parameter_code == parameter_code)
    if feature_code:
        query = query.where(dbm.SensitivityOatResponse.feature_code == feature_code)
    if aggregation_level:
        query = query.where(dbm.SensitivityOatResponse.aggregation_level == aggregation_level)
    if response_classification:
        if response_classification not in sc.RESPONSE_CLASSIFICATIONS:
            raise ValidationFailed(
                "Unknown response_classification filter.",
                details=[{"field": "response_classification", "reason": response_classification}],
            )
        query = query.where(
            dbm.SensitivityOatResponse.response_classification == response_classification
        )
    rows = db.execute(
        query.order_by(
            dbm.SensitivityOatResponse.parameter_code,
            dbm.SensitivityOatResponse.feature_code,
            dbm.SensitivityOatResponse.aggregation_level,
            dbm.SensitivityOatResponse.period_label,
        )
    ).scalars().all()
    return sensitivity_service.responses_payload(analysis, list(rows))


@router.get("/sensitivity-analyses/{analysis_id}/grid")
def get_analysis_grid(
    analysis_id: uuid.UUID,
    feature_code: str | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    cell_query = select(dbm.SensitivityGridCell).where(
        dbm.SensitivityGridCell.analysis_id == analysis.id
    )
    summary_query = select(dbm.SensitivityGridSummary).where(
        dbm.SensitivityGridSummary.analysis_id == analysis.id
    )
    if feature_code:
        cell_query = cell_query.where(dbm.SensitivityGridCell.feature_code == feature_code)
        summary_query = summary_query.where(
            dbm.SensitivityGridSummary.feature_code == feature_code
        )
    cells = db.execute(
        cell_query.order_by(
            dbm.SensitivityGridCell.feature_code,
            dbm.SensitivityGridCell.aggregation_level,
            dbm.SensitivityGridCell.period_label,
            dbm.SensitivityGridCell.temperature_delta_c.asc().nullsfirst(),
            dbm.SensitivityGridCell.precipitation_multiplier.asc().nullsfirst(),
        )
    ).scalars().all()
    summaries = db.execute(
        summary_query.order_by(
            dbm.SensitivityGridSummary.feature_code,
            dbm.SensitivityGridSummary.aggregation_level,
            dbm.SensitivityGridSummary.period_label,
        )
    ).scalars().all()

    axes: dict[str, list[float]] = {}
    if analysis.grid_design:
        for code, design in analysis.grid_design.items():
            from app.sensitivity.math import linspace

            axes[code] = linspace(
                float(design["lower"]), float(design["upper"]), int(design["n_points"])
            )

    if analysis.grid_design is None:
        note = "No joint parameter grid was requested for this analysis."
    else:
        note = (
            "Joint deterministic exploration over user-supplied bounds. The "
            "interaction contrast is a finite-grid interaction contrast — it "
            "is NOT a Sobol interaction index, and no input independence is "
            "assumed or implied."
        )
    return {
        "analysis_id": str(analysis.id),
        "grid_design": analysis.grid_design,
        "axes": axes,
        "cells": sensitivity_service.grid_cells_payload(list(cells)),
        "summaries": sensitivity_service.grid_summaries_payload(list(summaries)),
        "count": len(cells),
        "note": note,
    }


@router.get("/sensitivity-analyses/{analysis_id}/uncertainty")
def get_analysis_uncertainty(
    analysis_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    rows = db.execute(
        select(dbm.SensitivityUncertaintyItem)
        .where(dbm.SensitivityUncertaintyItem.analysis_id == analysis.id)
        .order_by(
            dbm.SensitivityUncertaintyItem.category,
            dbm.SensitivityUncertaintyItem.code,
        )
    ).scalars().all()
    return sensitivity_service.uncertainty_payload(list(rows))


@router.post("/sensitivity-analyses/{analysis_id}/verify")
def verify_sensitivity_analysis(
    analysis_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    analysis = _get_analysis_scoped(db, analysis_id, principal)
    return sensitivity_service.verify_analysis(db, analysis)

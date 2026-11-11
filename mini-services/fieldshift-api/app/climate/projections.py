"""Climate projection storage seam (P2.B).

CMIP6-class datasets require credentials/network unavailable in this
deployment (adapter status: `blocked_pending_credentials` — see
`PROVIDER_CAPABILITY_MATRIX`). This module provides the STORAGE half of the
contract so that, when a real adapter is wired, persistence + retrieval +
uncertainty representation are already in place, and a documented synthetic
fixture path exists for tests (clearly labelled `is_synthetic=True`).

Rules enforced here:
- scenario/model identity is REQUIRED (refuses anonymous projections);
- raw vs bias-corrected is preserved verbatim (never conflated);
- uncertainty bands (value_min/value_max) are stored when provided;
- projections never touch observations or forecasts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate.contracts import ProjectionEvidence
from app.db.models_p2 import ClimateProjectionRecord

logger = logging.getLogger("croptwist.climate.projections")

PROJECTION_STORAGE_VERSION = "projection-storage-1.0.0"


def persist_projection_evidence(
    db: Session,
    field_id: uuid.UUID,
    evidence: list[ProjectionEvidence],
) -> dict[str, int]:
    inserted = 0
    skipped = 0
    for item in evidence:
        if not item.scenario_id or not item.model_id:
            raise ValueError(
                "Projection evidence requires scenario_id and model_id; "
                "anonymous projections are refused."
            )
        exists = db.scalar(
            select(ClimateProjectionRecord.id).where(
                ClimateProjectionRecord.field_id == field_id,
                ClimateProjectionRecord.provider_code == item.provider_code,
                ClimateProjectionRecord.variable_code == item.variable_code,
                ClimateProjectionRecord.scenario_id == item.scenario_id,
                ClimateProjectionRecord.model_id == item.model_id,
                ClimateProjectionRecord.statistic == item.statistic,
                ClimateProjectionRecord.period_start == item.period_start,
                ClimateProjectionRecord.period_end == item.period_end,
            )
        )
        if exists is not None:
            skipped += 1
            continue
        db.add(
            ClimateProjectionRecord(
                field_id=field_id,
                provider_code=item.provider_code,
                source_product=item.source_product,
                model_id=item.model_id,
                scenario_id=item.scenario_id,
                ensemble_size=item.ensemble_size,
                bias_correction=item.bias_correction,
                variable_code=item.variable_code,
                unit=item.unit,
                period_start=item.period_start,
                period_end=item.period_end,
                baseline_period=item.baseline_period,
                statistic=item.statistic,
                value=item.value,
                value_min=item.value_min,
                value_max=item.value_max,
                is_synthetic=item.is_synthetic,
                processing_version=item.processing_version,
                metadata_json=item.metadata,
                retrieved_at=item.metadata.get("retrieved_at") or datetime.now(UTC),
            )
        )
        inserted += 1
    db.flush()
    return {"inserted": inserted, "skipped_existing": skipped}


def projections_for_field(
    db: Session,
    field_id: uuid.UUID,
    *,
    scenario_id: str | None = None,
    variable_code: str | None = None,
) -> list[dict[str, Any]]:
    query = select(ClimateProjectionRecord).where(ClimateProjectionRecord.field_id == field_id)
    if scenario_id:
        query = query.where(ClimateProjectionRecord.scenario_id == scenario_id)
    if variable_code:
        query = query.where(ClimateProjectionRecord.variable_code == variable_code)
    rows = list(db.scalars(query.order_by(ClimateProjectionRecord.period_start.asc())))
    return [
        {
            "id": str(r.id),
            "provider_code": r.provider_code,
            "source_product": r.source_product,
            "model_id": r.model_id,
            "scenario_id": r.scenario_id,
            "ensemble_size": r.ensemble_size,
            "bias_correction": r.bias_correction,
            "variable_code": r.variable_code,
            "unit": r.unit,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "baseline_period": r.baseline_period,
            "statistic": r.statistic,
            "value": r.value,
            "value_min": r.value_min,
            "value_max": r.value_max,
            "is_synthetic": r.is_synthetic,
            "processing_version": r.processing_version,
        }
        for r in rows
    ]

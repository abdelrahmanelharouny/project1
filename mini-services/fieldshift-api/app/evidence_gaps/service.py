"""Adaptive Evidence service (P2.E) — persistence bridge.

Persists gap-report snapshots (append-only) and manages the acquisition
action lifecycle (append-only events; every transition is recorded, history
is never overwritten).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.db.models_p2 import EvidenceAcquisitionAction, EvidenceAcquisitionEvent, EvidenceGapReport
from app.evidence_gaps import detection, voi

logger = logging.getLogger("croptwist.evidence.service")

ACTION_STATUSES = ("suggested", "in_progress", "submitted", "resolved", "dismissed")
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "suggested": ("in_progress", "submitted", "resolved", "dismissed"),
    "in_progress": ("submitted", "resolved", "dismissed"),
    "submitted": ("resolved", "dismissed"),
    "resolved": (),
    "dismissed": ("suggested",),  # a dismissed action can be re-suggested
}


def refresh_gap_report(db: Session, field: dbm.Field) -> dict[str, Any]:
    """Detect gaps, attach VoI, persist an append-only report snapshot."""
    report = detection.detect_gaps(db, field)
    enriched = voi.value_of_information(db, field, report["gaps"])
    report["gaps"] = enriched
    plans = [voi.acquisition_plan_for_gap(g) for g in enriched]
    report["acquisition_plans"] = plans

    import hashlib
    import json as _json

    checksum = hashlib.sha256(
        _json.dumps(report["gaps"], sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    db.add(
        EvidenceGapReport(
            field_id=field.id,
            gaps=report["gaps"],
            completeness=report["completeness"],
            engine_version=detection.EVIDENCE_GAPS_VERSION,
            checksum_sha256=checksum,
        )
    )
    db.commit()
    report["checksum_sha256"] = checksum
    report["generated_at"] = datetime.now(UTC).isoformat()
    return report


def list_actions(db: Session, field: dbm.Field, *, status: str | None = None) -> list[dict[str, Any]]:
    query = select(EvidenceAcquisitionAction).where(EvidenceAcquisitionAction.field_id == field.id)
    if status:
        query = query.where(EvidenceAcquisitionAction.status == status)
    rows = list(db.scalars(query.order_by(EvidenceAcquisitionAction.created_at.desc())))
    return [action_payload(a) for a in rows]


def create_action(
    db: Session,
    field: dbm.Field,
    principal: Any,
    *,
    gap_code: str,
    action_type: str,
    title: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not gap_code or not action_type or not title:
        raise ValidationFailed(
            "gap_code, action_type and title are required.",
            details=[{"field": "gap_code|action_type|title"}],
        )
    action = EvidenceAcquisitionAction(
        field_id=field.id,
        gap_code=gap_code[:64],
        action_type=action_type[:48],
        title=title[:255],
        plan=plan or {},
        status="suggested",
        created_by=getattr(principal, "id", None),
    )
    db.add(action)
    db.flush()
    db.add(
        EvidenceAcquisitionEvent(
            action_id=action.id,
            from_status=None,
            to_status="suggested",
            note="created from gap report",
            actor_id=getattr(principal, "id", None),
        )
    )
    db.commit()
    return action_payload(action)


def transition_action(
    db: Session,
    field: dbm.Field,
    principal: Any,
    *,
    action_id: uuid.UUID,
    to_status: str,
    note: str | None = None,
) -> dict[str, Any]:
    if to_status not in ACTION_STATUSES:
        raise ValidationFailed(
            f"Unknown action status '{to_status}'.",
            details=[{"field": "to_status", "reason": f"valid: {list(ACTION_STATUSES)}"}],
        )
    action = db.scalar(
        select(EvidenceAcquisitionAction).where(
            EvidenceAcquisitionAction.id == action_id,
            EvidenceAcquisitionAction.field_id == field.id,
        )
    )
    if action is None:
        raise NotFound("Action not found for this field.", details=[{"action_id": str(action_id)}])
    allowed = LEGAL_TRANSITIONS.get(action.status, ())
    if to_status not in allowed:
        raise ValidationFailed(
            f"Illegal transition {action.status} -> {to_status}.",
            details=[{"field": "to_status", "reason": f"allowed from {action.status}: {list(allowed)}"}],
        )
    previous = action.status
    action.status = to_status
    if to_status == "resolved":
        action.resolved_at = datetime.now(UTC)
    db.add(
        EvidenceAcquisitionEvent(
            action_id=action.id,
            from_status=previous,
            to_status=to_status,
            note=note,
            actor_id=getattr(principal, "id", None),
        )
    )
    db.commit()
    return action_payload(action)


def action_history(db: Session, field: dbm.Field, action_id: uuid.UUID) -> dict[str, Any]:
    action = db.scalar(
        select(EvidenceAcquisitionAction).where(
            EvidenceAcquisitionAction.id == action_id,
            EvidenceAcquisitionAction.field_id == field.id,
        )
    )
    if action is None:
        raise NotFound("Action not found for this field.", details=[{"action_id": str(action_id)}])
    events = list(
        db.scalars(
            select(EvidenceAcquisitionEvent)
            .where(EvidenceAcquisitionEvent.action_id == action.id)
            .order_by(EvidenceAcquisitionEvent.created_at.asc())
        )
    )
    payload = action_payload(action)
    payload["events"] = [
        {
            "id": str(e.id),
            "from_status": e.from_status,
            "to_status": e.to_status,
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
    return payload


def action_payload(action: EvidenceAcquisitionAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "field_id": str(action.field_id),
        "gap_code": action.gap_code,
        "action_type": action.action_type,
        "title": action.title,
        "plan": action.plan,
        "status": action.status,
        "submitted_ref_kind": action.submitted_ref_kind,
        "submitted_ref_id": str(action.submitted_ref_id) if action.submitted_ref_id else None,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "resolved_at": action.resolved_at.isoformat() if action.resolved_at else None,
    }

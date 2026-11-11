"""Onboarding state machine (P3 §3.3) — resumable, non-blocking.

Steps are recorded independently (a user may skip optional steps like
crops/priorities); progress is persisted after every mutation so an
interrupted onboarding resumes exactly where it stopped. Completion never
requires external data integrations — the product is useful before any
provider is configured.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.db.models_p3 import OnboardingProgress

# Ordered, human-readable steps. `required=False` steps may be skipped.
STEPS: list[dict[str, Any]] = [
    {"id": "account", "required": True, "auto": True},
    {"id": "account_type", "required": True},
    {"id": "organization", "required": True},
    {"id": "org_profile", "required": False},
    {"id": "first_farm", "required": True},
    {"id": "first_field", "required": False},
    {"id": "crops_priorities", "required": False},
    {"id": "review", "required": True},
    {"id": "tour", "required": False},
]

STEP_IDS = [s["id"] for s in STEPS]
STEP_MAP = {s["id"]: s for s in STEPS}


def get_or_create_progress(db: Session, user_id: uuid.UUID) -> OnboardingProgress:
    row = db.scalar(select(OnboardingProgress).where(OnboardingProgress.user_id == user_id))
    if row is None:
        row = OnboardingProgress(
            user_id=user_id,
            steps={"account": {"done": True, "at": datetime.now(UTC).isoformat()}},
            current_step="account_type",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def set_account_type(db: Session, user_id: uuid.UUID, *, account_type: str) -> OnboardingProgress:
    if account_type not in ("individual", "business", "farm_org"):
        raise ValidationFailed("account_type must be individual, business or farm_org.")
    row = get_or_create_progress(db, user_id)
    row.account_type = account_type
    return _complete_step(db, row, "account_type")


def complete_step(
    db: Session, user_id: uuid.UUID, *, step: str, data: dict[str, Any] | None = None
) -> OnboardingProgress:
    if step not in STEP_MAP:
        raise ValidationFailed(f"Unknown onboarding step '{step}'.")
    row = get_or_create_progress(db, user_id)
    if step == "account_type" and data and data.get("account_type"):
        row.account_type = data["account_type"]
    return _complete_step(db, row, step, data)


def _complete_step(
    db: Session, row: OnboardingProgress, step: str, data: dict[str, Any] | None = None
) -> OnboardingProgress:
    steps = dict(row.steps or {})
    entry: dict[str, Any] = {"done": True, "at": datetime.now(UTC).isoformat()}
    if data:
        # Only safe, non-sensitive step metadata is stored.
        entry["data"] = data
    steps[step] = entry
    row.steps = steps
    idx = STEP_IDS.index(step)
    if idx + 1 < len(STEP_IDS):
        row.current_step = STEP_IDS[idx + 1]
    required_missing = [s["id"] for s in STEPS if s["required"] and not steps.get(s["id"], {}).get("done")]
    if not required_missing:
        if row.completed_at is None:
            row.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def skip_step(db: Session, user_id: uuid.UUID, *, step: str) -> OnboardingProgress:
    if step not in STEP_MAP:
        raise ValidationFailed(f"Unknown onboarding step '{step}'.")
    if STEP_MAP[step]["required"]:
        raise ValidationFailed(f"Step '{step}' is required and cannot be skipped.")
    row = get_or_create_progress(db, user_id)
    steps = dict(row.steps or {})
    steps[step] = {"done": False, "skipped": True, "at": datetime.now(UTC).isoformat()}
    row.steps = steps
    idx = STEP_IDS.index(step)
    if idx + 1 < len(STEP_IDS):
        row.current_step = STEP_IDS[idx + 1]
    db.commit()
    db.refresh(row)
    return row


def dismiss_tour(db: Session, user_id: uuid.UUID) -> OnboardingProgress:
    row = get_or_create_progress(db, user_id)
    row.dismissed = True
    db.commit()
    db.refresh(row)
    return row


def progress_payload(row: OnboardingProgress) -> dict[str, Any]:
    steps_state = []
    for s in STEPS:
        entry = (row.steps or {}).get(s["id"], {})
        steps_state.append(
            {
                "id": s["id"],
                "required": s["required"],
                "done": bool(entry.get("done")),
                "skipped": bool(entry.get("skipped")),
                "at": entry.get("at"),
            }
        )
    return {
        "account_type": row.account_type,
        "current_step": row.current_step,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "dismissed": row.dismissed,
        "steps": steps_state,
    }

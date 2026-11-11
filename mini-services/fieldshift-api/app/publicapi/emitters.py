"""Stable emission surface for domain services (P3 W6).

Domain modules that want to notify external systems import from here, not
from the webhook service directly, so the emitter signature stays stable:

    from app.publicapi.emitters import emit_event

    emit_event(db, farm.organization_id, "farm.updated",
               payload_id=str(farm.id), data={"farm_id": str(farm.id)})

``emit_event`` only creates pending WebhookDelivery rows (no HTTP); the
dispatcher/retry sweep performs the actual signed POSTs.
"""

from app.publicapi.webhooks import EVENT_TYPES, emit_event

__all__ = ["EVENT_TYPES", "emit_event"]

"""Developer console endpoints (P3 W6): API keys, webhooks, usage, events.

All routes resolve a user principal (``get_principal``); mutating routes are
gated to org_admin+ INSIDE the services (never per-route). Plaintext secrets
are returned exactly once — on creation/rotation responses only. Registration
in router.py is done by the integrator; this module is deliberately not wired.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.entitlements import (
    KEY_API_ENABLED,
    KEY_API_RATE_LIMIT_PER_MINUTE,
    resolve_entitlements,
)
from app.core.database import get_db
from app.db.models_p3 import ApiKeyUsage
from app.domains.identity.service import get_principal
from app.publicapi import api_keys, webhooks
from app.publicapi.api_keys import ApiKeyPrincipal  # noqa: F401 (type re-export)

router = APIRouter(prefix="/developer", tags=["developer"])


# ------------------------------------------------------------------- schemas
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1)
    organization_id: uuid.UUID | None = None


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    events: list[str] = Field(min_length=1)
    description: str = Field(default="", max_length=300)
    organization_id: uuid.UUID | None = None


class WebhookPatch(BaseModel):
    enabled: bool | None = None
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=1000)


# --------------------------------------------------------------- API keys
@router.post("/keys", status_code=201)
def create_key(
    payload: ApiKeyCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    key, plaintext = api_keys.create_api_key(
        db, principal, name=payload.name, scopes=payload.scopes,
        organization_id=payload.organization_id,
    )
    return {"key": api_keys.api_key_payload(key), "secret": plaintext}


@router.get("/keys")
def list_keys(
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows = api_keys.list_api_keys(db, principal, organization_id=organization_id)
    return {"items": [api_keys.api_key_payload(k) for k in rows], "total": len(rows)}


@router.delete("/keys/{key_id}")
def revoke_key(
    key_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    key = api_keys.revoke_api_key(db, principal, key_id=key_id, organization_id=organization_id)
    return {"key": api_keys.api_key_payload(key)}


@router.post("/keys/{key_id}/rotate")
def rotate_key(
    key_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    key, plaintext = api_keys.rotate_api_key(
        db, principal, key_id=key_id, organization_id=organization_id
    )
    return {"key": api_keys.api_key_payload(key), "secret": plaintext}


# --------------------------------------------------------------- webhooks
@router.post("/webhooks", status_code=201)
def create_webhook(
    payload: WebhookCreate,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    endpoint, secret = webhooks.create_webhook_endpoint(
        db, principal, url=payload.url, events=payload.events,
        description=payload.description, organization_id=payload.organization_id,
    )
    return {"endpoint": webhooks.webhook_endpoint_payload(endpoint), "secret": secret}


@router.get("/webhooks")
def list_webhooks(
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows = webhooks.list_webhook_endpoints(db, principal, organization_id=organization_id)
    return {"items": [webhooks.webhook_endpoint_payload(e) for e in rows], "total": len(rows)}


@router.patch("/webhooks/{endpoint_id}")
def patch_webhook(
    endpoint_id: uuid.UUID,
    payload: WebhookPatch,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    endpoint = webhooks.update_webhook_endpoint(
        db, principal, endpoint_id=endpoint_id, enabled=payload.enabled,
        events=payload.events, description=payload.description, url=payload.url,
        organization_id=organization_id,
    )
    return {"endpoint": webhooks.webhook_endpoint_payload(endpoint)}


@router.delete("/webhooks/{endpoint_id}")
def delete_webhook(
    endpoint_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    webhooks.delete_webhook_endpoint(
        db, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    return {"deleted": True, "id": str(endpoint_id)}


@router.post("/webhooks/{endpoint_id}/rotate-secret")
def rotate_webhook_secret(
    endpoint_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    endpoint, secret = webhooks.rotate_webhook_secret(
        db, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    return {"endpoint": webhooks.webhook_endpoint_payload(endpoint), "secret": secret}


@router.get("/webhooks/{endpoint_id}/deliveries")
def list_webhook_deliveries(
    endpoint_id: uuid.UUID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = webhooks.list_deliveries(
        db, principal, endpoint_id=endpoint_id, status=status,
        limit=limit, offset=offset,
    )
    return {
        "items": [webhooks.webhook_delivery_payload(d) for d in rows],
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


@router.post("/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver")
def redeliver_webhook_delivery(
    endpoint_id: uuid.UUID,
    delivery_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    endpoint = webhooks.get_webhook_endpoint(
        db, principal, endpoint_id=endpoint_id, organization_id=organization_id
    )
    delivery = webhooks.redeliver(db, principal, delivery_id=delivery_id)
    if delivery.endpoint_id != endpoint.id:
        from app.core.errors import NotFound

        raise NotFound("Webhook delivery not found for this endpoint.")
    return {"delivery": webhooks.webhook_delivery_payload(delivery)}


# ------------------------------------------------------------------- usage
@router.get("/usage")
def developer_usage(
    organization_id: uuid.UUID | None = None,
    days: int = 30,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-key daily request counters + rate-limit entitlement info."""
    org_id = api_keys.resolve_org_id(principal, organization_id)
    keys = api_keys.list_api_keys(db, principal, organization_id=org_id)
    window_days = max(1, min(int(days), 90))
    since = date.today() - timedelta(days=window_days - 1)
    usage_rows = db.scalars(
        select(ApiKeyUsage)
        .join(api_keys.ApiKey, ApiKeyUsage.api_key_id == api_keys.ApiKey.id)
        .where(
            api_keys.ApiKey.organization_id == org_id,
            ApiKeyUsage.day >= since,
        )
        .order_by(ApiKeyUsage.day)
    ).all()
    by_key: dict[str, list[dict]] = {}
    for row in usage_rows:
        by_key.setdefault(str(row.api_key_id), []).append(
            {"day": row.day.isoformat(), "request_count": int(row.request_count)}
        )
    entitlements = resolve_entitlements(db, org_id)
    rate = entitlements.get(KEY_API_RATE_LIMIT_PER_MINUTE, {})
    enabled = entitlements.get(KEY_API_ENABLED, {})
    return {
        "organization_id": str(org_id),
        "window_days": window_days,
        "rate_limit": {
            "api_rate_limit_per_minute": rate.get("value", 0),
            "unlimited": bool(rate.get("unlimited", False)),
            "api_enabled": bool(enabled.get("value", False)),
            "plan_code": rate.get("plan_code"),
            "note": (
                "Each key's LIVE throttle is its rate_limit_per_minute "
                "(snapshotted from the plan when the key was created)."
            ),
        },
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "prefix": k.prefix,
                "status": k.status,
                "scopes": list(k.scopes or []),
                "rate_limit_per_minute": int(k.rate_limit_per_minute),
                "usage": by_key.get(str(k.id), []),
            }
            for k in keys
        ],
    }


@router.get("/events")
def developer_events() -> dict:
    """Catalog of supported webhook event types + API key scopes."""
    return {"events": list(webhooks.EVENT_TYPES), "scopes": list(api_keys.API_KEY_SCOPES)}

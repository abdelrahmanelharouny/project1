"""Authenticated AI Core gateway endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import check as check_rate_limit
from app.domains.identity.service import get_principal
from app.intelligence.orchestration.capabilities import list_capabilities
from app.intelligence.orchestration.contracts import AIRequest, AIResponse, CapabilityDescriptor
from app.intelligence.orchestration.service import execute_ai_request, safe_request_id
from app.intelligence.orchestration.tools import registry as tool_registry

router = APIRouter(prefix="/ai", tags=["ai-core"])


@router.get("/capabilities", response_model=list[CapabilityDescriptor])
def get_ai_capabilities(
    principal: Any = Depends(get_principal),
) -> list[CapabilityDescriptor]:
    """Return registered statuses; planned/unavailable items are not callable."""
    return list_capabilities()


@router.get("/tools")
def get_ai_tools(
    principal: Any = Depends(get_principal),
) -> list[dict[str, Any]]:
    """Expose only actually registered tools and their validated schemas."""
    return tool_registry.describe()


@router.post("/requests", response_model=AIResponse)
async def create_ai_request(
    payload: AIRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> AIResponse:
    """Submit one authenticated, field-bounded request to the AI lifecycle."""
    request_id = safe_request_id(getattr(request.state, "request_id", None))
    request.state.request_id = request_id
    # Local in-process limiter, keyed only by authenticated server-side user ID.
    check_rate_limit("ai_core", str(principal.id))
    return await execute_ai_request(db, principal, payload, request_id=request_id)

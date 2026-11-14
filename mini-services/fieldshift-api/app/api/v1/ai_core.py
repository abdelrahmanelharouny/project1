"""Authenticated AI Core, provider status, conversation and feedback routes."""
from __future__ import annotations

import json
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.rate_limit import check as check_rate_limit
from app.db.models_ai import AIAdvisorMessage, AIAdvisorSession
from app.db.models_orchestration import (
    AIAnswerFeedback,
    AIExecutionTrace,
    AIKnowledgeChunk,
    AIKnowledgeDocument,
)
from app.domains.identity.service import get_field_for_principal, get_principal
from app.intelligence.config import ai_settings
from app.intelligence.guard import sanitize_text
from app.intelligence.orchestration.capabilities import list_capabilities
from app.intelligence.orchestration.contracts import AIRequest, AIResponse, CapabilityDescriptor
from app.intelligence.orchestration.knowledge import (
    EmbeddingProviderFailure,
    KnowledgeError,
    create_knowledge_document,
    embed_query,
    embed_pending_document,
    embedding_provider_registry,
    search_knowledge,
)
from app.intelligence.orchestration.provider_adapters import get_provider_statuses
from app.intelligence.orchestration.service import execute_ai_request, safe_request_id
from app.intelligence.orchestration.tools import registry as tool_registry

router = APIRouter(prefix="/ai", tags=["ai-core"])
FEEDBACK_CONSENT_VERSION = "ai-feedback-v1"
MAX_CONVERSATION_MESSAGES = 80


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AIFeedbackRequest(StrictRequest):
    trace_id: UUID
    rating: Literal["helpful", "needs_improvement"]
    lifecycle_state: Literal["accepted", "rejected", "modified", "implemented", "outcome_reported"] = "accepted"
    category: Literal["factual_error", "insufficient_evidence", "unclear", "unsafe", "other"] | None = None
    correction: str | None = Field(default=None, max_length=2000)
    outcome: Literal["not_observed", "no_change", "improved", "worsened"] | None = None
    comment: str | None = Field(default=None, max_length=1000)
    quality_review_consent: Literal[True]


class AIFeedbackLifecycleRequest(StrictRequest):
    lifecycle_state: Literal["accepted", "rejected", "modified", "implemented", "outcome_reported"]
    reason: str | None = Field(default=None, max_length=1000)


class KnowledgeIngestRequest(StrictRequest):
    organization_id: UUID
    media_type: Literal["text/plain", "text/markdown"]
    source_title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    source_reference: str = Field(min_length=1, max_length=1000)
    published_at: date | None = None
    source_updated_at: date | None = None
    jurisdiction: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=2, max_length=12)
    crop_codes: list[str] = Field(default_factory=list, max_length=20)
    topics: list[str] = Field(default_factory=list, max_length=20)
    document_version: str = Field(min_length=1, max_length=100)
    license_name: str = Field(min_length=1, max_length=200)
    usage_restrictions: str = Field(min_length=1, max_length=5000)
    content: str = Field(min_length=1, max_length=2_000_000)
    rights_confirmed: Literal[True]


class KnowledgeEmbeddingRequest(StrictRequest):
    organization_id: UUID
    provider: str | None = Field(default=None, min_length=1, max_length=100)


class KnowledgeSearchRequest(StrictRequest):
    organization_id: UUID
    query: str = Field(min_length=2, max_length=2000)
    provider: str | None = Field(default=None, min_length=1, max_length=100)
    language: str | None = Field(default=None, max_length=12)
    jurisdiction: str | None = Field(default=None, max_length=100)
    crop_code: str | None = Field(default=None, max_length=40)
    top_k: int = Field(default=5, ge=1, le=20)


class ConversationListItem(BaseModel):
    conversation_id: UUID
    field_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    text: str
    trace_id: UUID | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    engine: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


def _request_id(request: Request) -> str:
    value = safe_request_id(getattr(request.state, "request_id", None))
    request.state.request_id = value
    return value


def _session_expired(session: AIAdvisorSession) -> bool:
    days = ai_settings.ai_conversation_retention_days
    if days <= 0 or session.updated_at is None:
        return False
    updated = session.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return updated < datetime.now(UTC) - timedelta(days=days)


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _require_organization_manager(principal: Any, organization_id: UUID) -> None:
    principal.require_org_role(organization_id, "manager")


def _knowledge_provider(name: str | None) -> Any | None:
    names = embedding_provider_registry.names()
    selected = name or (names[0] if len(names) == 1 else None)
    if selected is None:
        return None
    return embedding_provider_registry.get(selected)


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


@router.get("/providers")
def get_ai_providers(
    principal: Any = Depends(get_principal),
) -> dict[str, Any]:
    """Read configured provider order, privacy gates, breakers and verified capability claims; makes no live calls."""
    return {
        "providers": get_provider_statuses(),
        "field_data_policy_enabled": ai_settings.ai_allow_field_data_to_providers,
        "openrouter_field_data_policy_enabled": ai_settings.openrouter_allow_field_data,
        "embedding_providers_registered": list(embedding_provider_registry.names()),
        "embedding_documents_allowed": ai_settings.ai_knowledge_allow_documents_to_embedding_provider,
        "embedding_queries_allowed": ai_settings.ai_knowledge_allow_queries_to_embedding_provider,
        "live_connectivity_verified": False,
    }


@router.post("/requests", response_model=AIResponse)
async def create_ai_request(
    payload: AIRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> AIResponse:
    """Submit one authenticated, field-bounded request to the AI lifecycle."""
    request_id = _request_id(request)
    check_rate_limit("ai_core", str(principal.id))
    return await execute_ai_request(db, principal, payload, request_id=request_id)


@router.post("/requests/stream")
async def stream_ai_request(
    payload: AIRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Send a validated response as incremental SSE events.

    Execution, authorization, and validation finish before response headers are
    sent; the DB session is closed before the response body is streamed.
    """
    request_id = _request_id(request)
    check_rate_limit("ai_core", str(principal.id))
    result = await execute_ai_request(db, principal, payload, request_id=request_id)
    db.close()

    async def events():
        yield _sse("meta", {"request_id": request_id})
        if result.answer:
            for offset in range(0, len(result.answer), 160):
                yield _sse("chunk", {"text": result.answer[offset : offset + 160]})
        yield _sse("done", result.model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationListItem])
def list_ai_conversations(
    field_id: UUID = Query(...),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[ConversationListItem]:
    """List only conversations owned by this user on an currently authorized field."""
    get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(AIAdvisorSession)
        .where(
            AIAdvisorSession.field_id == field_id,
            AIAdvisorSession.owner_user_id == principal.id,
        )
        .order_by(AIAdvisorSession.updated_at.desc())
        .limit(50)
    ).all()
    return [
        ConversationListItem(
            conversation_id=row.id,
            field_id=row.field_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
        if not _session_expired(row)
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessage])
def get_ai_conversation_messages(
    conversation_id: UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[ConversationMessage]:
    session = db.scalar(select(AIAdvisorSession).where(
        AIAdvisorSession.id == conversation_id,
        AIAdvisorSession.owner_user_id == principal.id,
    ))
    if session is None or _session_expired(session):
        raise NotFound("AI conversation not found.")
    get_field_for_principal(db, principal, session.field_id)
    rows = db.scalars(
        select(AIAdvisorMessage)
        .where(AIAdvisorMessage.session_id == session.id)
        .order_by(AIAdvisorMessage.created_at.desc())
        .limit(MAX_CONVERSATION_MESSAGES)
    ).all()
    messages: list[ConversationMessage] = []
    for row in reversed(rows):
        engine = dict(row.engine) if isinstance(row.engine, dict) else {}
        trace_id: UUID | None = None
        try:
            if engine.get("trace_id"):
                trace_id = UUID(str(engine["trace_id"]))
        except (TypeError, ValueError, AttributeError):
            trace_id = None
        evidence = []
        for item in row.evidence or []:
            if isinstance(item, dict):
                item_copy = dict(item)
                if trace_id is not None:
                    item_copy.setdefault("trace_id", str(trace_id))
                evidence.append(item_copy)
        messages.append(ConversationMessage(
            id=row.id,
            role=row.role,
            text=(row.question if row.role == "user" else row.answer) or "",
            trace_id=trace_id,
            evidence=evidence,
            engine=engine,
            created_at=row.created_at,
        ))
    return messages


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_conversation(
    conversation_id: UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    session = db.scalar(select(AIAdvisorSession).where(
        AIAdvisorSession.id == conversation_id,
        AIAdvisorSession.owner_user_id == principal.id,
    ))
    if session is None:
        raise NotFound("AI conversation not found.")
    db.delete(session)
    db.commit()


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def submit_ai_feedback(
    payload: AIFeedbackRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record optional answer feedback only after affirmative quality-review consent."""
    check_rate_limit("ai_feedback", str(principal.id))
    if payload.lifecycle_state == "outcome_reported" and payload.outcome is None:
        raise ValidationFailed("An outcome report is required for outcome_reported feedback.")
    trace = db.scalar(select(AIExecutionTrace).where(
        AIExecutionTrace.id == payload.trace_id,
        AIExecutionTrace.user_id == principal.id,
    ))
    if trace is None or trace.organization_id is None:
        raise NotFound("AI execution not found.")
    principal.require_member_of(trace.organization_id)
    if trace.field_id is not None:
        get_field_for_principal(db, principal, trace.field_id)
    now = datetime.now(UTC)
    expires = now + timedelta(days=ai_settings.ai_feedback_retention_days)
    request_id = _request_id(request)
    feedback = AIAnswerFeedback(
        trace_id=trace.id,
        user_id=principal.id,
        organization_id=trace.organization_id,
        field_id=trace.field_id,
        conversation_id=trace.conversation_id,
        rating=payload.rating,
        category=payload.category,
        correction=sanitize_text(payload.correction, max_chars=2000) if payload.correction else None,
        outcome=payload.outcome,
        comment=sanitize_text(payload.comment, max_chars=1000) if payload.comment else None,
        evidence_references=trace.evidence_references or [],
        provider=trace.provider,
        model=trace.model,
        quality_review_consent=True,
        consent_version=FEEDBACK_CONSENT_VERSION,
        consented_at=now,
        lifecycle_state=payload.lifecycle_state,
        lifecycle_updated_at=now,
        lifecycle_updated_by=principal.id,
        provenance={
            "source": "authenticated_ai_response_feedback",
            "trace_id": str(trace.id),
            "request_id": request_id,
            "lifecycle_events": [{
                "state": payload.lifecycle_state,
                "actor_id": str(principal.id),
                "recorded_at": now.isoformat(),
            }],
        },
        outcome_verification_label="unverified_user_reported",
        expires_at=expires,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {
        "feedback_id": feedback.id,
        "status": "recorded",
        "quality_review_consent": True,
        "consent_version": FEEDBACK_CONSENT_VERSION,
        "consented_at": feedback.consented_at,
        "lifecycle_state": feedback.lifecycle_state,
        "outcome_verification_label": feedback.outcome_verification_label,
        "expires_at": feedback.expires_at,
        "request_id": request_id,
    }


def _feedback_summary(feedback: AIAnswerFeedback) -> dict[str, Any]:
    return {
        "feedback_id": feedback.id,
        "trace_id": feedback.trace_id,
        "rating": feedback.rating,
        "category": feedback.category,
        "correction": feedback.correction,
        "outcome": feedback.outcome,
        "outcome_verification_label": feedback.outcome_verification_label,
        "comment": feedback.comment,
        "lifecycle_state": feedback.lifecycle_state,
        "lifecycle_updated_at": feedback.lifecycle_updated_at,
        "quality_review_consent": feedback.quality_review_consent,
        "consent_version": feedback.consent_version,
        "consented_at": feedback.consented_at,
        "created_at": feedback.created_at,
        "expires_at": feedback.expires_at,
    }


@router.get("/feedback")
def list_own_ai_feedback(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List only unexpired feedback rows submitted by the authenticated user."""
    now = datetime.now(UTC)
    rows = db.scalars(
        select(AIAnswerFeedback)
        .where(AIAnswerFeedback.user_id == principal.id, AIAnswerFeedback.expires_at > now)
        .order_by(AIAnswerFeedback.created_at.desc(), AIAnswerFeedback.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [_feedback_summary(row) for row in rows]


@router.patch("/feedback/{feedback_id}/lifecycle")
def update_ai_feedback_lifecycle(
    feedback_id: UUID,
    payload: AIFeedbackLifecycleRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record an owner-reported state; it is never a verified agronomic outcome."""
    feedback = db.scalar(select(AIAnswerFeedback).where(
        AIAnswerFeedback.id == feedback_id,
        AIAnswerFeedback.user_id == principal.id,
        AIAnswerFeedback.expires_at > datetime.now(UTC),
    ).with_for_update())
    if feedback is None:
        raise NotFound("AI feedback not found.")
    principal.require_member_of(feedback.organization_id)
    transitions = {
        "accepted": {"rejected", "modified", "implemented", "outcome_reported"},
        "rejected": {"accepted"},
        "modified": {"accepted", "rejected", "implemented", "outcome_reported"},
        "implemented": {"outcome_reported"},
        "outcome_reported": {"accepted", "modified", "implemented"},
    }
    target = payload.lifecycle_state
    if target != feedback.lifecycle_state and target not in transitions.get(feedback.lifecycle_state, set()):
        raise ValidationFailed("AI feedback lifecycle transition is not allowed.")
    if target == "outcome_reported" and feedback.outcome is None:
        raise ValidationFailed("An outcome report is required before this lifecycle transition.")
    now = datetime.now(UTC)
    previous = feedback.lifecycle_state
    feedback.lifecycle_state = target
    feedback.lifecycle_updated_at = now
    feedback.lifecycle_updated_by = principal.id
    provenance = dict(feedback.provenance or {})
    events = list(provenance.get("lifecycle_events", []))
    event: dict[str, Any] = {
        "from_state": previous,
        "state": target,
        "actor_id": str(principal.id),
        "recorded_at": now.isoformat(),
    }
    if payload.reason:
        event["reason"] = sanitize_text(payload.reason, max_chars=1000)
    events.append(event)
    provenance["lifecycle_events"] = events[-100:]
    feedback.provenance = provenance
    db.commit()
    db.refresh(feedback)
    return _feedback_summary(feedback)


@router.delete("/feedback/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_own_ai_feedback(
    feedback_id: UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    """Permanently delete only the authenticated user's feedback row."""
    feedback = db.scalar(select(AIAnswerFeedback).where(
        AIAnswerFeedback.id == feedback_id,
        AIAnswerFeedback.user_id == principal.id,
    ))
    if feedback is None:
        raise NotFound("AI feedback not found.")
    db.delete(feedback)
    db.commit()


@router.get("/operations/status")
def get_ai_operations_status(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return provider state and aggregate metrics for only this user's requests."""
    since = datetime.now(UTC) - timedelta(days=7)
    traces = db.scalars(
        select(AIExecutionTrace)
        .where(AIExecutionTrace.user_id == principal.id, AIExecutionTrace.created_at >= since)
        .order_by(AIExecutionTrace.created_at.desc())
        .limit(500)
    ).all()
    status_counts: dict[str, int] = {}
    latencies: list[int] = []
    provider_stats: dict[str, dict[str, int]] = {}
    for trace in traces:
        status_counts[trace.status] = status_counts.get(trace.status, 0) + 1
        latencies.append(max(0, trace.latency_ms))
        for attempt in (trace.provider_attempts or [])[:12]:
            if not isinstance(attempt, dict) or not isinstance(attempt.get("provider"), str):
                continue
            name = attempt["provider"][:80]
            row = provider_stats.setdefault(name, {"attempts": 0, "succeeded": 0, "failed": 0})
            row["attempts"] += 1
            if attempt.get("status") in ("succeeded", "failed"):
                row[attempt["status"]] += 1
    return {
        "period_days": 7,
        "request_count": len(traces),
        "outcomes": status_counts,
        "average_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "provider_attempts": provider_stats,
        "provider_status": get_provider_statuses(),
        "cost_estimate": None,
        "cost_note": "No live provider price has been configured; token cost is not estimated.",
    }


@router.get("/knowledge/status")
def get_ai_knowledge_status(
    organization_id: UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_organization_manager(principal, organization_id)
    documents = int(db.scalar(select(func.count()).select_from(AIKnowledgeDocument).where(
        AIKnowledgeDocument.organization_id == organization_id
    )) or 0)
    ready = int(db.scalar(select(func.count()).select_from(AIKnowledgeDocument).where(
        AIKnowledgeDocument.organization_id == organization_id,
        AIKnowledgeDocument.processing_status == "ready",
    )) or 0)
    chunks = int(db.scalar(select(func.count()).select_from(AIKnowledgeChunk).where(
        AIKnowledgeChunk.organization_id == organization_id
    )) or 0)
    return {
        "organization_id": organization_id,
        "documents": documents,
        "ready_documents": ready,
        "chunks": chunks,
        "ingestion_formats": ["text/plain", "text/markdown"],
        "semantic_retrieval_available": bool(embedding_provider_registry.names()),
        "embedding_providers_registered": list(embedding_provider_registry.names()),
        "documents_to_provider_allowed": ai_settings.ai_knowledge_allow_documents_to_embedding_provider,
        "queries_to_provider_allowed": ai_settings.ai_knowledge_allow_queries_to_embedding_provider,
        "max_candidate_scan": 500,
        "note": "Documents remain pending until a reviewed embedding provider and explicit sharing policy are configured.",
    }


@router.post("/knowledge/documents", status_code=status.HTTP_201_CREATED)
def ingest_ai_knowledge_document(
    payload: KnowledgeIngestRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ingest rights-attested plain text/Markdown into the user's organization."""
    _require_organization_manager(principal, payload.organization_id)
    check_rate_limit("ai_knowledge_ingest", str(principal.id))
    try:
        document = create_knowledge_document(
            db,
            organization_id=payload.organization_id,
            uploaded_by=principal.id,
            source_title=payload.source_title,
            publisher=payload.publisher,
            source_reference=payload.source_reference,
            published_at=payload.published_at,
            source_updated_at=payload.source_updated_at,
            jurisdiction=payload.jurisdiction,
            language=payload.language,
            crop_codes=payload.crop_codes,
            topics=payload.topics,
            document_version=payload.document_version,
            license_name=payload.license_name,
            usage_restrictions=payload.usage_restrictions,
            content=payload.content,
            rights_confirmed=payload.rights_confirmed,
        )
    except KnowledgeError as exc:
        if "already ingested" in str(exc):
            raise Conflict(str(exc)) from exc
        raise ValidationFailed(str(exc)) from exc
    db.commit()
    db.refresh(document)
    return {
        "document_id": document.id,
        "organization_id": document.organization_id,
        "source_title": document.source_title,
        "content_hash": document.content_hash,
        "character_count": document.character_count,
        "processing_status": document.processing_status,
        "rights_confirmed_at": document.rights_confirmed_at,
        "request_id": _request_id(request),
    }


@router.post("/knowledge/documents/{document_id}/embed")
async def embed_ai_knowledge_document(
    document_id: UUID,
    payload: KnowledgeEmbeddingRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_organization_manager(principal, payload.organization_id)
    check_rate_limit("ai_knowledge_ingest", str(principal.id))
    document = db.scalar(select(AIKnowledgeDocument).where(
        AIKnowledgeDocument.id == document_id,
        AIKnowledgeDocument.organization_id == payload.organization_id,
    ))
    if document is None:
        raise NotFound("Knowledge document not found.")
    if not ai_settings.ai_knowledge_allow_documents_to_embedding_provider:
        raise Forbidden("Source-document sharing with embedding providers is disabled by policy.")
    provider = _knowledge_provider(payload.provider)
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "EMBEDDING_PROVIDER_UNAVAILABLE", "message": "No reviewed embedding provider is registered."},
        )
    try:
        chunks = await embed_pending_document(db, document, provider=provider)
    except KnowledgeError as exc:
        db.commit()  # persist only the normalized failed status/category
        raise HTTPException(
            status_code=502,
            detail={"code": "EMBEDDING_FAILED", "message": str(exc)},
        ) from exc
    db.commit()
    return {
        "document_id": document.id,
        "processing_status": document.processing_status,
        "embedding_provider": document.embedding_provider,
        "embedding_model": document.embedding_model,
        "chunks_embedded": chunks,
        "request_id": _request_id(request),
    }


@router.post("/knowledge/search")
async def search_ai_knowledge(
    payload: KnowledgeSearchRequest,
    request: Request,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_organization_manager(principal, payload.organization_id)
    check_rate_limit("ai_knowledge_search", str(principal.id))
    if not ai_settings.ai_knowledge_allow_queries_to_embedding_provider:
        raise Forbidden("Query-text sharing with embedding providers is disabled by policy.")
    provider = _knowledge_provider(payload.provider)
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "EMBEDDING_PROVIDER_UNAVAILABLE", "message": "Semantic retrieval is not configured; no lexical substitute was used."},
        )
    try:
        query_embedding = await embed_query(payload.query, provider=provider)
        passages = search_knowledge(
            db,
            organization_id=payload.organization_id,
            query_embedding=query_embedding,
            embedding_provider=provider.name,
            embedding_model=provider.model,
            language=payload.language,
            jurisdiction=payload.jurisdiction,
            crop_code=payload.crop_code,
            top_k=min(payload.top_k, ai_settings.ai_knowledge_max_results),
        )
    except EmbeddingProviderFailure as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "EMBEDDING_FAILED", "message": str(exc)},
        ) from exc
    except KnowledgeError as exc:
        raise ValidationFailed(str(exc)) from exc
    return {
        "retrieval_mode": "bounded_exact_cosine",
        "organization_id": payload.organization_id,
        "results": [item.as_dict() for item in passages],
        "request_id": _request_id(request),
    }


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_knowledge_document(
    document_id: UUID,
    organization_id: UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    """Delete an organization knowledge source, e.g. after license revocation."""
    _require_organization_manager(principal, organization_id)
    document = db.scalar(select(AIKnowledgeDocument).where(
        AIKnowledgeDocument.id == document_id,
        AIKnowledgeDocument.organization_id == organization_id,
    ))
    if document is None:
        raise NotFound("Knowledge document not found.")
    db.delete(document)
    db.commit()

"""Central, bounded and evidence-grounded AI request lifecycle."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.models_ai import AIAdvisorMessage
from app.db.models_orchestration import AIExecutionTrace
from app.intelligence.config import ai_settings
from app.intelligence.orchestration.context import AuthorizedAIContext, resolve_authorized_context
from app.intelligence.orchestration.contracts import (
    AIExecution,
    AIRequest,
    AIResponse,
    EvidenceItem,
    IntentPlan,
    PlannedToolCall,
    ProviderAttempt,
    TokenUsage,
    ToolInvocation,
)
from app.intelligence.orchestration.evidence import normalize_evidence
from app.intelligence.orchestration.planning import create_plan
from app.intelligence.orchestration.provider_adapters import get_provider_chain
from app.intelligence.orchestration.tools import (
    AdvisorToolOutput,
    EvidenceCollectionOutput,
    ToolError,
    ToolWorkflowError,
    registry as tool_registry,
)
from app.intelligence.orchestration.validation import validate_core_answer
from app.intelligence.guard import sanitize_text
from app.intelligence import sessions as session_service

logger = logging.getLogger("croptwist.intelligence.orchestration")
PROMPT_VERSION = "ai-core-advisor-v1"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_INLINE_EVIDENCE_RE = re.compile(r"\[evidence:\s*([A-Za-z0-9_.:-]+)\]", re.IGNORECASE)


def safe_request_id(value: str | None) -> str:
    """Keep correlation metadata bounded and free of control characters."""
    candidate = value or ""
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else str(uuid.uuid4())


def _string_list(value: Any, *, max_items: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:max_items]:
        if isinstance(item, str) and item.strip():
            result.append(sanitize_text(item, max_chars=500))
    return result


def _fallback_explanation(locale: str) -> str:
    if locale == "ar":
        return (
            "تعذر اعتماد إجابة سردية موثقة بالكامل. يقتصر الرد على السجلات "
            "والنتائج الحتمية المرفقة؛ لم يتم تقديم توقع أو توصية أو إجراء. "
            "[evidence: field]"
        )
    return (
        "I could not validate a fully grounded narrative. This response is "
        "limited to the attached recorded facts and deterministic results; no "
        "prediction, recommendation or action was produced. [evidence: field]"
    )


def _cited_labels(evidence_used: Any, answer: str | None = None) -> list[str]:
    inline_labels = _INLINE_EVIDENCE_RE.findall(answer or "")
    if inline_labels:
        return list(dict.fromkeys(inline_labels))
    labels: list[str] = []
    if isinstance(evidence_used, list):
        for item in evidence_used:
            if isinstance(item, dict) and isinstance(item.get("label"), str):
                labels.append(item["label"])
    return list(dict.fromkeys(labels))


def _safe_limitations(plan: IntentPlan, engine: dict[str, Any]) -> list[str]:
    items = list(plan.limitations)
    items.extend(_string_list(engine.get("limitations")))
    if engine.get("mode") == "llm":
        items.append("Provider usage is reported only when supplied; model confidence is not calibrated.")
    return list(dict.fromkeys(items))[:30]


def _evidence_refs(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item.evidence_id,
            "claim_class": item.claim_class,
            "sources": [
                {"source_kind": source.source_kind, "source_id": source.source_id}
                for source in item.source_references
            ],
        }
        for item in items
    ]


def _fingerprint(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tool_failure(name: str, code: str, elapsed_ms: int) -> ToolInvocation:
    status = "timed_out" if code == "TOOL_TIMEOUT" else (
        "denied" if "DENIED" in code or "NOT_ALLOWED" in code or "CONFIRMATION_REQUIRED" in code or "SIDE_EFFECT_POLICY" in code else "failed"
    )
    return ToolInvocation(
        name=name,
        category="analytical",
        side_effect="none",
        status=status,
        duration_ms=max(0, elapsed_ms),
        error_code=code,
    )


def _merge_step_outputs(outputs: list[Any]) -> AdvisorToolOutput:
    """Merge same-contract step outputs without inventing conflict resolution."""
    if (
        len(outputs) == 2
        and isinstance(outputs[0], EvidenceCollectionOutput)
        and isinstance(outputs[1], AdvisorToolOutput)
    ):
        if outputs[0].evidence_pack != outputs[1].evidence_pack:
            raise ToolError(
                "MULTI_STEP_EVIDENCE_CONFLICT",
                "The synthesis step did not preserve the collected evidence package.",
            )
        return outputs[1]
    if not outputs or not all(isinstance(item, AdvisorToolOutput) for item in outputs):
        raise ToolError(
            "MULTI_STEP_CONTRACT_UNSUPPORTED",
            "Workflow outputs do not share a registered response contract.",
        )
    if len(outputs) == 1:
        return outputs[0]

    evidence_pack: dict[str, Any] = {}
    labels: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    answers: list[str] = []
    for output in outputs:
        answers.append(output.answer)
        for item in output.evidence_used:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
            if key not in seen_labels:
                labels.append(item)
                seen_labels.add(key)
        for domain, value in output.evidence_pack.items():
            if domain == "data_gaps":
                evidence_pack[domain] = list(dict.fromkeys(
                    [*evidence_pack.get(domain, []), *(value or [])]
                ))
            elif domain not in evidence_pack:
                evidence_pack[domain] = value
            elif evidence_pack[domain] != value:
                if not isinstance(evidence_pack[domain], dict) or not isinstance(value, dict):
                    raise ToolError("MULTI_STEP_EVIDENCE_CONFLICT", "Workflow steps returned conflicting evidence.")
                merged = dict(evidence_pack[domain])
                if any(key in merged and merged[key] != child for key, child in value.items()):
                    raise ToolError("MULTI_STEP_EVIDENCE_CONFLICT", "Workflow steps returned conflicting evidence.")
                merged.update(value)
                evidence_pack[domain] = merged

    if len(json.dumps(evidence_pack, ensure_ascii=False, default=str).encode("utf-8")) > 16_000:
        raise ToolError("MULTI_STEP_EVIDENCE_TOO_LARGE", "Merged workflow evidence exceeds its context budget.")
    answer = "\n\n".join(answers)
    if len(answer) > 8000:
        raise ToolError("MULTI_STEP_ANSWER_TOO_LARGE", "The combined workflow answer exceeds its output budget.")
    engine = dict(outputs[0].engine)
    same_engine = all(
        item.engine.get(key) == outputs[0].engine.get(key)
        for item in outputs
        for key in ("mode", "provider", "model")
    )
    if not same_engine:
        engine.update({"mode": "rules", "provider": None, "model": None})
    token_usage = [item.engine.get("token_usage") or {} for item in outputs]
    if all(
        all(isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) for key in ("input_tokens", "output_tokens"))
        for usage in token_usage
    ):
        engine["token_usage"] = {
            key: sum(usage[key] for usage in token_usage)
            for key in ("input_tokens", "output_tokens")
        }
    return AdvisorToolOutput(
        answer=answer,
        evidence_used=labels,
        engine=engine,
        evidence_pack=evidence_pack,
    )


def _append_messages(db: Session, context: AuthorizedAIContext, payload: AIRequest, response: AIResponse) -> None:
    if context.session is None or response.answer is None or context.field is None:
        return
    db.add(AIAdvisorMessage(
        field_id=context.field.id,
        session_id=context.session.id,
        role="user",
        question=payload.question,
    ))
    db.add(AIAdvisorMessage(
        field_id=context.field.id,
        session_id=context.session.id,
        role="assistant",
        answer=response.answer,
        evidence=[item.model_dump(mode="json") for item in response.evidence],
        engine={
            "mode": "rules" if response.execution.degraded else "llm",
            "provider": response.execution.provider,
            "model": response.execution.model,
            "trace_id": str(response.execution.trace_id),
            "prompt_version": PROMPT_VERSION,
        },
    ))
    session_service.touch_session(db, context.session)


def _persist_trace(
    db: Session,
    *,
    context: AuthorizedAIContext,
    response: AIResponse,
    payload: AIRequest,
    evidence_pack: dict[str, Any] | None,
    validation_errors: list[str],
) -> None:
    usage = response.execution.token_usage
    db.add(AIExecutionTrace(
        id=response.execution.trace_id,
        request_id=response.request_id,
        user_id=context.user_id,
        organization_id=context.organization_id,
        field_id=context.field_id,
        conversation_id=context.session.id if context.session else None,
        intent=response.intent.value,
        provider=response.execution.provider,
        model=response.execution.model,
        provider_attempts=[item.model_dump(mode="json") for item in response.execution.provider_attempts],
        prompt_version=PROMPT_VERSION,
        evidence_fingerprint=_fingerprint(evidence_pack),
        selected_context_domains=list(context.selected_domains),
        planned_steps=response.execution.planned_steps,
        tool_trace=[item.model_dump(mode="json") for item in response.execution.tools],
        evidence_references=_evidence_refs(response.evidence),
        validation_errors=validation_errors,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=response.execution.latency_ms,
        status=response.status,
        error_category=response.execution.error_category,
    ))


def _clarification_response(
    *, request_id: str, trace_id: uuid.UUID, plan: IntentPlan, conversation_id: uuid.UUID | None,
    started: float,
) -> AIResponse:
    return AIResponse(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=plan.intent,
        status="clarification_required",
        answer=None,
        missing_information=plan.missing_information or ["intent"],
        limitations=plan.limitations,
        plan=plan,
        execution=AIExecution(
            trace_id=trace_id,
            request_id=request_id,
            status="clarification_required",
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            planned_steps=0,
        ),
    )


def _unavailable_response(
    *, request_id: str, trace_id: uuid.UUID, plan: IntentPlan, conversation_id: uuid.UUID | None,
    started: float,
) -> AIResponse:
    return AIResponse(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=plan.intent,
        status="unavailable",
        answer=None,
        limitations=plan.limitations,
        missing_information=plan.missing_information,
        plan=plan,
        execution=AIExecution(
            trace_id=trace_id,
            request_id=request_id,
            status="unavailable",
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            planned_steps=0,
        ),
    )


async def execute_ai_request(
    db: Session,
    principal: Any,
    payload: AIRequest,
    *,
    request_id: str,
) -> AIResponse:
    """Authorize, plan, execute registered tools, validate, persist and trace."""
    started = perf_counter()
    request_id = safe_request_id(request_id)
    trace_id = uuid.uuid4()
    plan = create_plan(payload.question, has_field=payload.field_id is not None)
    if payload.context_domains:
        selected = tuple(dict.fromkeys(("field", *payload.context_domains, "data_gaps")))
    else:
        selected = tuple(plan.required_context)
    if not selected:
        selected = ("field", "data_gaps")

    # A supplied field is always authorized, even when the requested feature
    # is not available. Organization identity is derived only after this guard.
    context = resolve_authorized_context(
        db,
        principal,
        field_id=payload.field_id,
        conversation_id=payload.conversation_id,
        locale=payload.locale,
        selected_domains=selected,
        history_turns=ai_settings.advisor_history_turns,
        retention_days=ai_settings.ai_conversation_retention_days,
    )
    evidence_pack: dict[str, Any] | None = None
    validation_errors: list[str] = []

    if plan.clarification_needed:
        response = _clarification_response(
            request_id=request_id, trace_id=trace_id, plan=plan,
            conversation_id=context.session.id if context.session else payload.conversation_id,
            started=started,
        )
        _persist_trace(db, context=context, response=response, payload=payload,
                       evidence_pack=None, validation_errors=[])
        db.commit()
        return response
    if not plan.required_tools:
        response = _unavailable_response(
            request_id=request_id, trace_id=trace_id, plan=plan,
            conversation_id=context.session.id if context.session else payload.conversation_id,
            started=started,
        )
        _persist_trace(db, context=context, response=response, payload=payload,
                       evidence_pack=None, validation_errors=[])
        db.commit()
        return response

    if context.field is None:
        # Planner and context resolver are independent trust boundaries.
        response = _unavailable_response(
            request_id=request_id, trace_id=trace_id, plan=plan,
            conversation_id=None, started=started,
        )
        _persist_trace(db, context=context, response=response, payload=payload,
                       evidence_pack=None, validation_errors=["field_context_required"])
        db.commit()
        return response

    if context.session is None:
        context.session = session_service.create_session(
            db, context.field.id, owner_user_id=principal.id
        )
    context.provider = get_provider_chain(field_sensitive=True, prefer_streaming=True)
    context.request_id = request_id

    invocations: list[ToolInvocation] = []
    engine: dict[str, Any] = {"mode": "rules", "model": None}
    answer: str | None = None
    evidence_items: list[EvidenceItem] = []
    status: str = "failed"
    error_category: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    usage = TokenUsage()
    tool_started = perf_counter()
    try:
        planned_calls = plan.tool_calls or [
            PlannedToolCall(name=name) for name in plan.required_tools
        ]
        if [call.name for call in planned_calls] != plan.required_tools:
            raise ToolError("INVALID_TOOL_PLAN", "Planned tool steps do not match the allowed tool list.")
        raw_outputs, step_invocations = await tool_registry.execute_workflow(
            planned_calls,
            {"question": payload.question, "locale": payload.locale},
            context,
            allowed_tools=plan.required_tools,
        )
        invocations.extend(step_invocations)
        output = _merge_step_outputs(raw_outputs)
        engine = output.engine
        evidence_pack = output.evidence_pack
        labels = _cited_labels(output.evidence_used, output.answer)
        if not labels:
            labels = ["field"]
        evidence_items = normalize_evidence(
            evidence_pack, field_id=str(context.field.id), cited_labels=labels
        )
        answer = output.answer
        if engine.get("mode") == "llm":
            validation = validate_core_answer(answer, evidence_pack)
            if not validation.valid:
                validation_errors.extend(validation.error_codes)
                # The second layer fails closed even if the legacy advisor's
                # more permissive validator accepted the narrative.
                answer = _fallback_explanation(payload.locale)
                evidence_items = normalize_evidence(
                    evidence_pack, field_id=str(context.field.id), cited_labels=["field"]
                )
                engine = {
                    "mode": "rules",
                    "model": None,
                    "provider": engine.get("provider"),
                    "validation_errors": list(validation.error_codes),
                }
        else:
            # The legacy advisor's offline summary includes recommendation
            # prose; AI Core is explanation-only, so replace it with an
            # explicit, safe fallback rather than misclassify it.
            answer = _fallback_explanation(payload.locale)
            evidence_items = normalize_evidence(
                evidence_pack, field_id=str(context.field.id), cited_labels=["field"]
            )
        provider_name = engine.get("provider") if engine.get("mode") == "llm" else None
        model_name = engine.get("model") if engine.get("mode") == "llm" else None
        raw_usage = engine.get("token_usage") or {}
        usage = TokenUsage(
            input_tokens=raw_usage.get("input_tokens"),
            output_tokens=raw_usage.get("output_tokens"),
            total_tokens=(
                raw_usage.get("input_tokens", 0) + raw_usage.get("output_tokens", 0)
                if raw_usage.get("input_tokens") is not None and raw_usage.get("output_tokens") is not None
                else None
            ),
        )
        status = "partial" if plan.availability == "partial" or engine.get("mode") != "llm" else "answered"
    except ToolWorkflowError as exc:
        invocations.extend(exc.invocations)
        error_category = exc.code
        status = "failed"
        logger.warning("AI Core workflow failed: %s", exc.code)
    except ToolError as exc:
        elapsed = max(0, round((perf_counter() - tool_started) * 1000))
        invocations.append(_tool_failure(plan.required_tools[-1], exc.code, elapsed))
        error_category = exc.code
        status = "failed"
        logger.warning("AI Core tool failed: %s", exc.code)
    except Exception:  # noqa: BLE001 - trace a safe category, never expose exception text
        elapsed = max(0, round((perf_counter() - tool_started) * 1000))
        invocations.append(_tool_failure(plan.required_tools[0], "AI_ORCHESTRATION_FAILED", elapsed))
        error_category = "AI_ORCHESTRATION_FAILED"
        status = "failed"
        logger.error("AI Core orchestration failed")

    limitations = _safe_limitations(plan, engine)
    if status == "partial" and engine.get("mode") != "llm":
        limitations.append("The provider did not return a validated narrative; a deterministic explanation notice was returned.")
    if error_category:
        limitations.append("A registered tool failed; no unsupported result was substituted.")
    limitations = list(dict.fromkeys(limitations))[:30]
    pack_gaps = (evidence_pack or {}).get("data_gaps") or []
    followups = _string_list(engine.get("follow_up_suggestions"))
    conversation_id = context.session.id if context.session else None
    provider_attempts = []
    raw_attempts = engine.get("provider_attempts")
    if isinstance(raw_attempts, list):
        for item in raw_attempts[:12]:
            if isinstance(item, dict):
                try:
                    provider_attempts.append(ProviderAttempt.model_validate(item))
                except Exception:
                    continue
    response = AIResponse(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=plan.intent,
        status=status,
        answer=answer,
        verified_facts=[item for item in evidence_items if item.claim_class == "verified_fact"],
        derived_results=[item for item in evidence_items if item.claim_class == "derived_result"],
        # This adapter has no predictive or action tools. Keep these empty rather
        # than re-labeling model prose as a prediction/recommendation.
        predictions=[],
        recommendations=[],
        general_knowledge=[],
        assumptions=_string_list(engine.get("assumptions")),
        evidence=evidence_items,
        limitations=limitations,
        missing_information=list(dict.fromkeys([*plan.missing_information, *[str(g) for g in pack_gaps]])),
        follow_up_suggestions=followups,
        plan=plan,
        execution=AIExecution(
            trace_id=trace_id,
            request_id=request_id,
            status=status,
            provider=provider_name,
            model=model_name,
            token_usage=usage,
            provider_attempts=provider_attempts,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            planned_steps=len(plan.required_tools),
            tools=invocations,
            degraded=engine.get("mode") != "llm",
            error_category=error_category,
        ),
    )
    _append_messages(db, context, payload, response)
    _persist_trace(
        db,
        context=context,
        response=response,
        payload=payload,
        evidence_pack=evidence_pack,
        validation_errors=validation_errors,
    )
    db.commit()
    return response

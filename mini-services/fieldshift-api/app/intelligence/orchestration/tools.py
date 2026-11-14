"""Bounded, server-selected tool registry; user text cannot choose identities."""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any, Awaitable, Callable, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.intelligence.orchestration.context import AuthorizedAIContext
from app.intelligence.orchestration.contracts import PlannedToolCall, ToolInvocation

MAX_WORKFLOW_STEPS = 3
MAX_TOOL_TIMEOUT_SECONDS = 60.0
MAX_TOOL_INPUT_BYTES = 32_000
MAX_TOOL_OUTPUT_BYTES = 64_000


class ToolCategory(StrEnum):
    READ_ONLY = "read_only"
    ANALYTICAL = "analytical"
    CONTROLLED_ACTION = "controlled_action"


class ToolSideEffect(StrEnum):
    NONE = "none"
    WRITES_DATA = "writes_data"
    EXTERNAL_ACTION = "external_action"


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ToolWorkflowError(ToolError):
    """Safe failure plus prior successes/failing step for the execution trace."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        results: list[BaseModel],
        invocations: list[ToolInvocation],
    ):
        super().__init__(code, message)
        self.results = results
        self.invocations = invocations


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FieldAdvisorInput(ToolArguments):
    question: str = Field(min_length=1, max_length=2000)
    locale: str = Field(pattern="^(en|ar)$")


class AdvisorToolOutput(ToolArguments):
    answer: str = Field(min_length=1, max_length=8000)
    evidence_used: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    engine: dict[str, Any] = Field(default_factory=dict)
    evidence_pack: dict[str, Any] = Field(default_factory=dict)


class EvidenceCollectionOutput(ToolArguments):
    evidence_pack: dict[str, Any]
    selected_domains: list[str] = Field(max_length=8)


ToolHandler = Callable[[BaseModel, AuthorizedAIContext], Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: ToolCategory
    side_effect: ToolSideEffect
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    handler: ToolHandler
    required_permissions: frozenset[str]
    timeout_seconds: float
    error_codes: tuple[str, ...] = (
        "TOOL_NOT_ALLOWED",
        "TOOL_PERMISSION_DENIED",
        "TOOL_INVALID_ARGUMENTS",
        "TOOL_INPUT_TOO_LARGE",
        "TOOL_TIMEOUT",
        "TOOL_EXECUTION_FAILED",
        "TOOL_INVALID_OUTPUT",
        "TOOL_OUTPUT_TOO_LARGE",
        "ACTION_CONFIRMATION_REQUIRED",
    )
    max_output_bytes: int = 64_000
    confirmation_required: bool = False


class ToolRegistry:
    def __init__(self, *, max_calls: int = 3) -> None:
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or not 1 <= max_calls <= MAX_WORKFLOW_STEPS:
            raise ValueError(f"max_calls must be between 1 and {MAX_WORKFLOW_STEPS}")
        self._definitions: dict[str, ToolDefinition] = {}
        self.max_calls = max_calls

    def register(self, definition: ToolDefinition) -> None:
        if not definition.name or definition.name in self._definitions:
            raise ValueError(f"tool already registered or invalid: {definition.name!r}")
        if (
            isinstance(definition.timeout_seconds, bool)
            or not isinstance(definition.timeout_seconds, (int, float))
            or not math.isfinite(definition.timeout_seconds)
            or not 0 < definition.timeout_seconds <= MAX_TOOL_TIMEOUT_SECONDS
            or isinstance(definition.max_output_bytes, bool)
            or not isinstance(definition.max_output_bytes, int)
            or not 1 <= definition.max_output_bytes <= MAX_TOOL_OUTPUT_BYTES
        ):
            raise ValueError("tool timeout/output limits exceed the registry ceiling")
        self._definitions[definition.name] = definition

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "category": item.category.value,
                "side_effect": item.side_effect.value,
                "input_schema": item.input_schema.model_json_schema(),
                "output_schema": item.output_schema.model_json_schema(),
                "required_permissions": sorted(item.required_permissions),
                "timeout_seconds": item.timeout_seconds,
                "max_output_bytes": item.max_output_bytes,
                "error_codes": list(item.error_codes),
                "confirmation_required": item.confirmation_required,
            }
            for item in sorted(self._definitions.values(), key=lambda d: d.name)
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: AuthorizedAIContext,
        *,
        allowed_tools: tuple[str, ...] | list[str],
        prior_calls: int = 0,
    ) -> tuple[BaseModel, ToolInvocation]:
        started = perf_counter()
        definition = self._definitions.get(name)
        if definition is None or name not in allowed_tools:
            raise ToolError("TOOL_NOT_ALLOWED", "The requested tool is not in the server-created plan.")
        if prior_calls >= self.max_calls:
            raise ToolError("TOOL_CALL_LIMIT", "The request exceeded the tool-call limit.")
        if not definition.required_permissions.issubset(context.permissions):
            raise ToolError("TOOL_PERMISSION_DENIED", "The caller lacks the required resource permissions.")
        if (
            definition.category == ToolCategory.CONTROLLED_ACTION
            or definition.side_effect != ToolSideEffect.NONE
        ):
            raise ToolError(
                "ACTION_CONFIRMATION_REQUIRED",
                "AI Core is read-only; controlled actions require a separate audited confirmation workflow.",
            )
        try:
            input_bytes = len(json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ToolError("TOOL_INVALID_ARGUMENTS", "Tool arguments must be JSON data.") from exc
        if input_bytes > MAX_TOOL_INPUT_BYTES:
            raise ToolError("TOOL_INPUT_TOO_LARGE", "Tool arguments exceeded the input-size budget.")
        try:
            parsed = definition.input_schema.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError("TOOL_INVALID_ARGUMENTS", "Tool arguments failed schema validation.") from exc
        if definition.category in (ToolCategory.READ_ONLY, ToolCategory.ANALYTICAL) and definition.side_effect != ToolSideEffect.NONE:
            raise ToolError("TOOL_SIDE_EFFECT_POLICY", "This read/analysis tool is not side-effect-free.")
        try:
            raw = await asyncio.wait_for(
                definition.handler(parsed, context), timeout=definition.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise ToolError("TOOL_TIMEOUT", "The tool exceeded its time budget.") from exc
        except ToolError:
            raise
        except Exception as exc:  # safe outward error; details stay in server trace/logs
            raise ToolError("TOOL_EXECUTION_FAILED", "The tool could not complete.") from exc
        try:
            output = definition.output_schema.model_validate(raw)
            encoded = output.model_dump_json().encode("utf-8")
        except (ValidationError, TypeError, ValueError) as exc:
            raise ToolError("TOOL_INVALID_OUTPUT", "The tool returned data outside its output schema.") from exc
        if len(encoded) > definition.max_output_bytes:
            raise ToolError("TOOL_OUTPUT_TOO_LARGE", "The tool output exceeded its size limit.")
        invocation = ToolInvocation(
            name=definition.name,
            category=definition.category.value,
            side_effect=definition.side_effect.value,
            status="succeeded",
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
            output_bytes=len(encoded),
        )
        return output, invocation

    async def execute_workflow(
        self,
        steps: list[PlannedToolCall],
        base_arguments: dict[str, Any],
        context: AuthorizedAIContext,
        *,
        allowed_tools: tuple[str, ...] | list[str],
    ) -> tuple[list[BaseModel], list[ToolInvocation]]:
        """Run a deterministic sequence; later steps see only validated prior outputs."""
        if not steps or len(steps) > self.max_calls:
            raise ToolError("TOOL_CALL_LIMIT", "The workflow has no steps or exceeds its step budget.")
        names = [step.name for step in steps]
        if any(name not in allowed_tools for name in names):
            raise ToolError("TOOL_NOT_ALLOWED", "A workflow step is not in the server-created plan.")
        results: list[BaseModel] = []
        invocations: list[ToolInvocation] = []
        for index, step in enumerate(steps):
            if any(dependency < 0 or dependency >= index for dependency in step.depends_on):
                raise ToolError("INVALID_TOOL_DEPENDENCY", "Workflow dependencies must refer to prior steps.")
            arguments = {**base_arguments, **step.arguments}
            selected = set(context.selected_domains)
            step_domains = tuple(dict.fromkeys(
                ["field", "data_gaps"]
                + [domain for domain in step.context_domains if domain in selected]
            ))
            step_context = AuthorizedAIContext(
                db=context.db,
                principal=context.principal,
                field=context.field,
                farm=context.farm,
                organization_id=context.organization_id,
                role=context.role,
                permissions=context.permissions,
                selected_domains=step_domains,
                locale=context.locale,
                session=context.session,
                history=context.history,
                prior_tool_results=[result.model_dump(mode="json") for result in results],
                provider=context.provider,
                request_id=getattr(context, "request_id", None),
            )
            started = perf_counter()
            try:
                result, invocation = await self.execute(
                    step.name,
                    arguments,
                    step_context,
                    allowed_tools=allowed_tools,
                    prior_calls=index,
                )
            except ToolError as exc:
                definition = self._definitions.get(step.name)
                status = "timed_out" if exc.code == "TOOL_TIMEOUT" else (
                    "denied" if "DENIED" in exc.code or "NOT_ALLOWED" in exc.code or "CONFIRMATION_REQUIRED" in exc.code or "SIDE_EFFECT_POLICY" in exc.code else "failed"
                )
                invocations.append(ToolInvocation(
                    name=step.name,
                    category=definition.category.value if definition else "analytical",
                    side_effect=definition.side_effect.value if definition else "none",
                    status=status,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    error_code=exc.code,
                ))
                raise ToolWorkflowError(
                    exc.code,
                    "A planned workflow step failed.",
                    results=results,
                    invocations=invocations,
                ) from exc
            results.append(result)
            invocations.append(invocation)
        return results, invocations


async def _field_advisor_handler(args: BaseModel, context: AuthorizedAIContext) -> dict[str, Any]:
    from app.intelligence import advisor
    from app.intelligence.evidence import build_field_evidence
    from app.intelligence.orchestration.evidence import select_evidence_domains

    if context.field is None or context.provider is None:
        raise ToolError("FIELD_CONTEXT_REQUIRED", "A field and provider are required for this tool.")
    values = args.model_dump()
    evidence_pack = await asyncio.to_thread(build_field_evidence, context.db, context.field)
    try:
        evidence_pack = select_evidence_domains(evidence_pack, context.selected_domains)
    except ValueError as exc:
        raise ToolError(
            "EVIDENCE_CONTEXT_TOO_LARGE", "Selected field evidence exceeds the context budget."
        ) from exc
    result = await advisor.answer_field_question_async(
        context.db,
        context.field,
        values["question"],
        history=context.history,
        locale=values["locale"],
        provider=context.provider,
        evidence_pack=evidence_pack,
        core_mode=True,
        request_id=context.request_id,
    )
    return {
        "answer": result.get("answer") or "",
        "evidence_used": result.get("evidence_used") or [],
        "engine": result.get("engine") or {"mode": "rules", "model": None},
        "evidence_pack": evidence_pack,
    }


async def _collect_field_evidence_handler(
    args: BaseModel, context: AuthorizedAIContext
) -> dict[str, Any]:
    from app.intelligence.evidence import build_field_evidence
    from app.intelligence.orchestration.evidence import select_evidence_domains

    if context.field is None:
        raise ToolError("FIELD_CONTEXT_REQUIRED", "An authorized field is required for evidence collection.")
    try:
        pack = await asyncio.to_thread(build_field_evidence, context.db, context.field)
        selected = select_evidence_domains(pack, context.selected_domains)
    except ValueError as exc:
        raise ToolError("EVIDENCE_CONTEXT_TOO_LARGE", "Selected field evidence exceeds the context budget.") from exc
    return {"evidence_pack": selected, "selected_domains": list(context.selected_domains)}


async def _synthesize_field_answer_handler(
    args: BaseModel, context: AuthorizedAIContext
) -> dict[str, Any]:
    from app.intelligence import advisor

    if context.field is None or context.provider is None:
        raise ToolError("FIELD_CONTEXT_REQUIRED", "An authorized field and provider policy are required.")
    evidence_pack = next(
        (
            item.get("evidence_pack")
            for item in reversed(context.prior_tool_results)
            if isinstance(item, dict) and isinstance(item.get("evidence_pack"), dict)
        ),
        None,
    )
    if evidence_pack is None:
        raise ToolError("WORKFLOW_PREREQUISITE_MISSING", "The evidence collection step did not return data.")
    values = args.model_dump()
    result = await advisor.answer_field_question_async(
        context.db,
        context.field,
        values["question"],
        history=context.history,
        locale=values["locale"],
        provider=context.provider,
        evidence_pack=evidence_pack,
        core_mode=True,
        request_id=context.request_id,
    )
    return {
        "answer": result.get("answer") or "",
        "evidence_used": result.get("evidence_used") or [],
        "engine": result.get("engine") or {"mode": "rules", "model": None},
        "evidence_pack": evidence_pack,
    }


registry = ToolRegistry(max_calls=3)
registry.register(ToolDefinition(
    name="collect_field_evidence",
    description="Read the authorized field profile and allowlisted stored soil, water, climate, rotation, management, HLS vegetation and spatial-screening evidence; preserves explicit data gaps.",
    category=ToolCategory.READ_ONLY,
    side_effect=ToolSideEffect.NONE,
    input_schema=FieldAdvisorInput,
    output_schema=EvidenceCollectionOutput,
    handler=_collect_field_evidence_handler,
    required_permissions=frozenset({"field.read", "field.analysis.read"}),
    timeout_seconds=30.0,
    error_codes=("FIELD_CONTEXT_REQUIRED", "EVIDENCE_CONTEXT_TOO_LARGE", "TOOL_PERMISSION_DENIED", "TOOL_TIMEOUT", "TOOL_INVALID_OUTPUT"),
    max_output_bytes=32_000,
))
registry.register(ToolDefinition(
    name="synthesize_field_answer",
    description="Synthesize a concise field explanation from validated, server-collected evidence; the model cannot select tools, identities or resources.",
    category=ToolCategory.ANALYTICAL,
    side_effect=ToolSideEffect.NONE,
    input_schema=FieldAdvisorInput,
    output_schema=AdvisorToolOutput,
    handler=_synthesize_field_answer_handler,
    required_permissions=frozenset({"field.read", "field.analysis.read"}),
    timeout_seconds=50.0,
    error_codes=("FIELD_CONTEXT_REQUIRED", "WORKFLOW_PREREQUISITE_MISSING", "TOOL_PERMISSION_DENIED", "TOOL_TIMEOUT", "TOOL_EXECUTION_FAILED", "TOOL_INVALID_OUTPUT"),
    max_output_bytes=64_000,
))
registry.register(ToolDefinition(
    name="answer_field_question",
    description="Read a single authorized field's allowlisted evidence and produce a validated explanation; never mutates farm data.",
    category=ToolCategory.ANALYTICAL,
    side_effect=ToolSideEffect.NONE,
    input_schema=FieldAdvisorInput,
    output_schema=AdvisorToolOutput,
    handler=_field_advisor_handler,
    required_permissions=frozenset({"field.read", "field.analysis.read"}),
    timeout_seconds=50.0,
    error_codes=(
        "FIELD_CONTEXT_REQUIRED",
        "EVIDENCE_CONTEXT_TOO_LARGE",
        "TOOL_PERMISSION_DENIED",
        "TOOL_TIMEOUT",
        "TOOL_EXECUTION_FAILED",
        "TOOL_INVALID_OUTPUT",
        "TOOL_OUTPUT_TOO_LARGE",
    ),
    max_output_bytes=64_000,
))

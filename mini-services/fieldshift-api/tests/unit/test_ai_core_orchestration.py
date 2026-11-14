"""Pure AI Core contract/planner/tool/evidence tests; no database fixtures."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.intelligence.orchestration.capabilities import get_capability, list_capabilities
from app.intelligence.orchestration.contracts import AIRequest, PlannedToolCall
from app.intelligence.orchestration.evidence import normalize_evidence, select_evidence_domains
from app.intelligence.orchestration.planning import create_plan
from app.intelligence.orchestration.provider import (
    LegacyBridgeProvider,
    ProviderCapabilityUnavailable,
    provider_registry,
)
from app.intelligence.orchestration.tools import (
    ToolArguments,
    ToolCategory,
    ToolDefinition,
    ToolError,
    ToolRegistry,
    ToolSideEffect,
)
from app.intelligence.orchestration.validation import validate_core_answer
from app.intelligence.orchestration.service import _cited_labels, safe_request_id


def test_request_contract_rejects_client_actor_or_tenant_fields():
    with pytest.raises(ValidationError):
        AIRequest.model_validate({"question": "What is in my field?", "user_id": str(uuid4())})
    with pytest.raises(ValidationError):
        AIRequest.model_validate({"question": " ", "organization_id": str(uuid4())})


def test_domain_selection_is_allowlisted_and_keeps_field_and_gap_status():
    source = {
        "field": {"id": "field-1", "area_ha": 5.0},
        "climate": {"source": {"kind": "feature_run", "id": "run-1"}},
        "soil": {"assessment": {"domains": []}},
        "data_gaps": ["water", "vegetation"],
    }
    selected = select_evidence_domains(source, ("soil", "data_gaps", "unsupported"))
    assert set(selected) == {"field", "soil", "data_gaps"}
    assert selected["data_gaps"] == ["water", "vegetation"]
    assert "climate" not in selected


def test_plan_is_deterministic_and_never_plans_mutating_tools():
    soil = create_plan("Explain the stored soil nutrient balance", has_field=True)
    assert soil.intent.value == "soil_intelligence"
    assert soil.required_tools == ["collect_field_evidence", "synthesize_field_answer"]
    assert [step.name for step in soil.tool_calls] == soil.required_tools
    assert soil.tool_calls[1].depends_on == [0]
    assert soil.permission_scope == ["field.read", "field.analysis.read"]
    assert soil.availability == "partial"

    cross_domain = create_plan(
        "Why is my field vegetation condition declining compared with soil and water?",
        has_field=True,
    )
    assert {"vegetation", "soil", "water", "climate", "management", "data_gaps"}.issubset(
        set(cross_domain.tool_calls[0].context_domains)
    )
    assert cross_domain.required_tools == ["collect_field_evidence", "synthesize_field_answer"]

    forecast = create_plan("Predict yield next year", has_field=True)
    assert forecast.intent.value == "predictive_analysis"
    assert forecast.required_tools == []
    assert forecast.availability == "unavailable"

    suitability = create_plan("What crop is best for my soil?", has_field=True)
    assert suitability.intent.value == "crop_suitability"
    assert suitability.required_tools == []
    assert suitability.availability == "planned"

    action = create_plan("Delete my field", has_field=True)
    assert action.intent.value == "platform_operation"
    assert action.required_tools == []


def test_plan_asks_for_field_before_field_data_access():
    plan = create_plan("How is irrigation?", has_field=False)
    assert plan.clarification_needed
    assert "field_id" in plan.missing_information
    assert not plan.required_tools


def test_capability_directory_does_not_claim_planned_actions_are_live():
    names = {item.name for item in list_capabilities()}
    assert "field_evidence_answer" in names
    assert get_capability("platform_operations").status == "unavailable"
    assert get_capability("crop_suitability").status == "planned"
    assert get_capability("predictive_analysis").status == "unavailable"
    public_request_properties = get_capability("field_evidence_answer").request_schema["properties"]
    assert "field_id" in public_request_properties
    assert "user_id" not in public_request_properties
    assert "organization_id" not in public_request_properties


def test_provider_reports_real_legacy_bridge_limitations():
    provider = provider_registry.get("legacy-llm-bridge")
    assert provider.capabilities.text_generation
    assert not provider.capabilities.native_structured_output
    assert not provider.capabilities.tool_calling
    assert not provider.capabilities.streaming
    assert not provider.capabilities.token_usage_reporting
    with pytest.raises(LookupError):
        provider_registry.get("not-registered")


def test_legacy_adapter_rejects_unsupported_native_modes():
    provider = LegacyBridgeProvider()
    with pytest.raises(ProviderCapabilityUnavailable):
        asyncio.run(provider.generate_structured([], schema={"type": "object"}))
    with pytest.raises(ProviderCapabilityUnavailable):
        asyncio.run(provider.call_tools([], tools=[]))


def test_tool_registry_denies_tools_not_in_server_plan():
    tools = ToolRegistry()
    context = SimpleNamespace(permissions=frozenset())
    with pytest.raises(ToolError, match="server-created plan"):
        asyncio.run(tools.execute(
            "hidden_tool", {}, context, allowed_tools=(), prior_calls=0
        ))


def test_tool_registry_refuses_controlled_side_effects_before_handler():
    class EmptyArgs(ToolArguments):
        pass

    class Result(ToolArguments):
        ok: bool

    async def should_not_run(args, context):
        raise AssertionError("mutating handler must not run in AI Core")

    tools = ToolRegistry()
    tools.register(ToolDefinition(
        name="write_tool",
        description="test",
        category=ToolCategory.CONTROLLED_ACTION,
        side_effect=ToolSideEffect.WRITES_DATA,
        input_schema=EmptyArgs,
        output_schema=Result,
        handler=should_not_run,
        required_permissions=frozenset(),
        timeout_seconds=1.0,
        confirmation_required=True,
    ))
    with pytest.raises(ToolError, match="read-only"):
        asyncio.run(tools.execute(
            "write_tool", {}, SimpleNamespace(permissions=frozenset()),
            allowed_tools=("write_tool",),
        ))


def test_registry_has_unavoidable_global_resource_ceilings():
    class Arguments(ToolArguments):
        payload: str

    class Result(ToolArguments):
        ok: bool

    async def handler(args, context):
        return {"ok": True}

    with pytest.raises(ValueError, match="max_calls"):
        ToolRegistry(max_calls=4)

    tool = ToolDefinition(
        name="bounded",
        description="bounded test tool",
        category=ToolCategory.READ_ONLY,
        side_effect=ToolSideEffect.NONE,
        input_schema=Arguments,
        output_schema=Result,
        handler=handler,
        required_permissions=frozenset(),
        timeout_seconds=60.1,
    )
    with pytest.raises(ValueError, match="ceiling"):
        ToolRegistry().register(tool)

    registry = ToolRegistry()
    tool = ToolDefinition(
        **{**tool.__dict__, "timeout_seconds": 1.0}
    )
    registry.register(tool)
    with pytest.raises(ToolError, match="input-size"):
        asyncio.run(registry.execute(
            "bounded", {"payload": "x" * 32_001},
            SimpleNamespace(permissions=frozenset()), allowed_tools=("bounded",),
        ))


def test_workflow_executes_ordered_steps_with_validated_prior_results():
    class Arguments(ToolArguments):
        value: int

    class Result(ToolArguments):
        value: int

    async def first(args, context):
        return {"value": args.value + 2}

    async def second(args, context):
        assert context.prior_tool_results == [{"value": 3}]
        return {"value": context.prior_tool_results[0]["value"] + args.value}

    tools = ToolRegistry(max_calls=3)
    for name, handler in (("first", first), ("second", second)):
        tools.register(ToolDefinition(
            name=name,
            description="test analytical step",
            category=ToolCategory.ANALYTICAL,
            side_effect=ToolSideEffect.NONE,
            input_schema=Arguments,
            output_schema=Result,
            handler=handler,
            required_permissions=frozenset({"field.read"}),
            timeout_seconds=1.0,
        ))
    context = SimpleNamespace(
        db=None, principal=object(), field=None, farm=None, organization_id=None,
        role="viewer", permissions=frozenset({"field.read"}),
        selected_domains=("field", "data_gaps"), locale="en", session=None,
        history=[], prior_tool_results=[], provider=None,
    )
    results, invocations = asyncio.run(tools.execute_workflow(
        [
            PlannedToolCall(name="first"),
            PlannedToolCall(name="second", depends_on=[0]),
        ],
        {"value": 1},
        context,
        allowed_tools=("first", "second"),
    ))
    assert [result.value for result in results] == [3, 4]
    assert [item.status for item in invocations] == ["succeeded", "succeeded"]


def test_evidence_items_preserve_source_and_claim_class_without_model_confidence():
    pack = {
        "field": {"id": "f-1", "name": "North", "area_ha": 12.5},
        "climate": {
            "source": {"kind": "feature_run", "id": "run-1"},
            "period": {"start": "2026-01-01", "end": "2026-12-31"},
            "metrics": [{"code": "rain", "value": 320.5, "unit": "mm"}],
        },
        "data_gaps": ["water"],
    }
    items = normalize_evidence(pack, field_id="f-1", cited_labels=["field", "climate"])
    by_kind = {item.claim_class: item for item in items}
    assert by_kind["verified_fact"].entity_id == "f-1"
    climate = next(item for item in items if item.capability == "climate_intelligence")
    assert climate.source_references[0].source_id == "run-1"
    assert climate.model_confidence is None
    assert any(item.claim_class == "missing_information" for item in items)


def test_core_response_requires_inline_citations_and_dimensionally_valid_numbers():
    evidence = {
        "field": {"area_ha": 12.5},
        "climate": {"metrics": [{"code": "rain", "value": 42.5, "unit": "mm"}]},
        "data_gaps": [],
    }
    good = validate_core_answer("The recorded area is 12.5 ha [evidence: field].", evidence)
    assert good.valid
    uncited = validate_core_answer("The rainfall is 42.5 mm.", evidence)
    assert not uncited.valid
    wrong_unit = validate_core_answer(
        "Rainfall is 42.5 kg/ha [evidence: climate].", evidence
    )
    assert not wrong_unit.valid
    assert "cited_numeric_consistency" in wrong_unit.error_codes


def test_trace_correlation_id_is_bounded_and_safe():
    assert safe_request_id("req-12.abc") == "req-12.abc"
    assert safe_request_id("bad\nheader") != "bad\nheader"
    assert len(safe_request_id("x" * 200)) <= 36


def test_inline_answer_citations_are_included_in_response_evidence():
    labels = _cited_labels(
        [{"label": "field"}],
        "The field has stored soil results [evidence: soil] and water gaps [evidence: data_gaps].",
    )
    assert labels == ["soil", "data_gaps"]

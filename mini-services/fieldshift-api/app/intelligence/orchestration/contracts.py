"""Typed contracts shared by the CropTwist AI request lifecycle.

These schemas deliberately keep model-generated prose separate from recorded
facts and deterministic engine results. Empty prediction/recommendation arrays
mean no such authoritative capability ran for this request.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AIIntent(StrEnum):
    AGRICULTURAL_KNOWLEDGE = "agricultural_knowledge"
    FARM_QUESTION = "farm_question"
    FIELD_QUESTION = "field_question"
    FIELD_ANALYSIS = "field_analysis"
    SATELLITE_INTERPRETATION = "satellite_interpretation"
    SOIL_INTELLIGENCE = "soil_intelligence"
    WATER_INTELLIGENCE = "water_intelligence"
    CLIMATE_INTELLIGENCE = "climate_intelligence"
    VEGETATION_INTELLIGENCE = "vegetation_intelligence"
    STRESS_ANOMALY = "stress_anomaly"
    CROP_SUITABILITY = "crop_suitability"
    CROP_ROTATION = "crop_rotation"
    AGRICULTURAL_RECOMMENDATION = "agricultural_recommendation"
    AGRICULTURAL_RISK = "agricultural_risk"
    SCENARIO_COMPARISON = "scenario_comparison"
    PREDICTIVE_ANALYSIS = "predictive_analysis"
    REPORT_GENERATION = "report_generation"
    PLATFORM_OPERATION = "platform_operation"
    AMBIGUOUS = "ambiguous"


class AIRequest(StrictModel):
    """Public request body; actor, organization and trace IDs are server-owned."""

    question: str = Field(min_length=1, max_length=2000)
    field_id: UUID | None = None
    conversation_id: UUID | None = None
    locale: Literal["en", "ar"] = "en"
    context_domains: list[
        Literal["field", "climate", "water", "soil", "rotation", "management", "vegetation", "data_gaps"]
    ] = Field(default_factory=list, max_length=8)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value

    @field_validator("context_domains")
    @classmethod
    def context_domains_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("context_domains must not contain duplicates")
        return values


class PlannedToolCall(StrictModel):
    """One server-authored step in a bounded workflow plan."""

    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    context_domains: list[
        Literal["field", "climate", "water", "soil", "rotation", "management", "vegetation", "data_gaps"]
    ] = Field(default_factory=list, max_length=8)
    depends_on: list[int] = Field(default_factory=list, max_length=3)


class IntentPlan(StrictModel):
    intent: AIIntent
    required_entities: list[str] = Field(default_factory=list, max_length=12)
    required_context: list[str] = Field(default_factory=list, max_length=12)
    required_tools: list[str] = Field(default_factory=list, max_length=3)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list, max_length=3)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
    permission_scope: list[str] = Field(default_factory=list, max_length=8)
    clarification_needed: bool = False
    availability: Literal["available", "partial", "planned", "unavailable"]
    expected_output: Literal["grounded_explanation", "clarification", "unavailable"]
    limitations: list[str] = Field(default_factory=list, max_length=12)


class EvidenceSourceReference(StrictModel):
    source_kind: str = Field(min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=160)
    provider: str | None = Field(default=None, max_length=100)
    acquired_at: datetime | str | None = None


class EvidenceItem(StrictModel):
    """Normalized provenance wrapper; domain-specific fields remain in value."""

    evidence_id: str = Field(min_length=1, max_length=240)
    capability: str = Field(min_length=1, max_length=80)
    entity_scope: Literal["farm", "field"]
    entity_id: str = Field(min_length=1, max_length=80)
    result_type: str = Field(min_length=1, max_length=100)
    claim_class: Literal[
        "verified_fact", "derived_result", "model_prediction", "recommendation",
        "general_knowledge", "assumption", "missing_information",
    ]
    value: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = Field(default=None, max_length=40)
    observation_period: dict[str, str | None] | None = None
    source_references: list[EvidenceSourceReference] = Field(default_factory=list, max_length=12)
    spatial_resolution_m: float | None = Field(default=None, ge=0)
    processing_version: str | None = Field(default=None, max_length=100)
    evidence_quality: dict[str, Any] = Field(default_factory=dict)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    recommendation_confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    status: Literal["available", "partial", "insufficient", "unavailable"] = "available"


class AnalyticalResultContract(StrictModel):
    """Stable integration envelope for future domain-owned analytical services."""

    result_id: str
    capability: str
    entity_scope: Literal["farm", "field", "organization"]
    entity_id: str
    result_type: str
    value: Any = None
    unit: str | None = None
    observation_period: dict[str, str | None] | None = None
    source_references: list[EvidenceSourceReference] = Field(default_factory=list)
    processing_version: str | None = None
    evidence_quality: dict[str, Any] = Field(default_factory=dict)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    recommendation_confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    status: Literal["succeeded", "partial", "insufficient", "unavailable", "failed"]
    domain_payload: dict[str, Any] = Field(default_factory=dict)


class CapabilityDescriptor(StrictModel):
    name: str
    status: Literal["available", "partial", "planned", "unavailable"]
    summary: str
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    required_context: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    confidence_semantics: str
    data_freshness: str
    error_contract: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ToolInvocation(StrictModel):
    name: str
    category: Literal["read_only", "analytical", "controlled_action"]
    side_effect: Literal["none", "writes_data", "external_action"]
    status: Literal["succeeded", "failed", "timed_out", "denied"]
    duration_ms: int = Field(ge=0)
    output_bytes: int | None = Field(default=None, ge=0)
    error_code: str | None = None


class TokenUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderAttempt(StrictModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=160)
    status: Literal["succeeded", "failed"]
    latency_ms: int = Field(ge=0)
    error_category: str | None = Field(default=None, max_length=80)


class AIExecution(StrictModel):
    trace_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    status: Literal["answered", "partial", "clarification_required", "unavailable", "failed"]
    provider: str | None = None
    model: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list, max_length=12)
    latency_ms: int = Field(ge=0)
    planned_steps: int = Field(ge=0, le=3)
    tools: list[ToolInvocation] = Field(default_factory=list, max_length=4)
    degraded: bool = False
    error_category: str | None = None


class AIResponse(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: UUID | None = None
    intent: AIIntent
    status: Literal["answered", "partial", "clarification_required", "unavailable", "failed"]
    answer: str | None = Field(default=None, max_length=8000)
    verified_facts: list[EvidenceItem] = Field(default_factory=list, max_length=40)
    derived_results: list[EvidenceItem] = Field(default_factory=list, max_length=40)
    predictions: list[EvidenceItem] = Field(default_factory=list, max_length=20)
    recommendations: list[EvidenceItem] = Field(default_factory=list, max_length=20)
    general_knowledge: list[EvidenceItem] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=20)
    plan: IntentPlan
    execution: AIExecution

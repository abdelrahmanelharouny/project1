"""Capability directory: operational, partial, planned and absent tools."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.intelligence.orchestration.contracts import (
    AIRequest,
    AIResponse,
    CapabilityDescriptor,
    StrictModel,
)


class CapabilityActorContext(StrictModel):
    """Server-derived identity; clients and models cannot author this envelope."""

    user_id: UUID
    organization_id: UUID
    role_code: str = Field(min_length=1, max_length=40)
    permissions: list[str] = Field(max_length=20)


class CapabilityEntityContext(StrictModel):
    scope: Literal["field", "farm", "organization"]
    entity_id: UUID
    field_id: UUID | None = None


class DomainCapabilityRequest(StrictModel):
    """Internal adapter contract; the gateway constructs all scope/identity fields."""

    trace_id: UUID
    capability: str = Field(min_length=1, max_length=80)
    actor: CapabilityActorContext
    entity: CapabilityEntityContext
    locale: Literal["en", "ar"] = "en"
    selected_context_domains: list[str] = Field(max_length=12)
    required_evidence: list[str] = Field(max_length=20)
    parameters: dict[str, Any] = Field(default_factory=dict)


def _cap(
    name: str,
    status: str,
    summary: str,
    *,
    context: list[str],
    evidence: list[str],
    confidence: str,
    freshness: str,
    limitations: list[str] | None = None,
    permissions: list[str] | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        status=status,  # validated by Pydantic
        summary=summary,
        # Public discovery describes the gateway contract. The server-only
        # DomainCapabilityRequest/AnalyticalResultContract stay adapter contracts.
        request_schema=AIRequest.model_json_schema(),
        response_schema=AIResponse.model_json_schema(),
        required_context=context,
        required_permissions=permissions if permissions is not None else ["field.read"],
        evidence_requirements=evidence,
        confidence_semantics=confidence,
        data_freshness=freshness,
        error_contract=["missing_context", "insufficient_evidence", "provider_unavailable", "validation_failed"],
        limitations=limitations or [],
    )


CAPABILITIES: tuple[CapabilityDescriptor, ...] = (
    _cap("field_evidence_answer", "partial", "A deterministic two-step workflow collects an authorized field's allowlisted stored evidence, then synthesizes an explanation with the validated advisor when an approved provider is configured.", context=["field", "soil", "water", "climate", "rotation", "management", "HLS vegetation", "data gaps"], evidence=["stored engine run IDs", "units and periods", "HLS scene and processing provenance", "explicit missing-data labels"], confidence="No model confidence is reported; only source-specific deterministic quality metadata is returned.", freshness="Latest successful stored engine runs; domain timestamps are carried when present.", limitations=["External providers are blocked from receiving field data until deployment policy gates are explicitly enabled.", "Answer text is explanatory only; it does not create recommendations, forecasts or actions."], permissions=["field.read", "field.analysis.read"]),
    _cap("crop_intelligence", "unavailable", "No dedicated, cited crop-knowledge retrieval capability is wired into the AI Core.", context=["field", "crop and season context"], evidence=["reviewed, region-appropriate crop knowledge"], confidence="No estimate is emitted.", freshness="Not available.", limitations=["The structured knowledge base is not currently retrieved by the advisor."], permissions=[]),
    _cap("soil_intelligence", "partial", "Explains existing stored soil assessment, nutrient budget, carbon and management evidence when present.", context=["field", "soil", "management", "data_gaps"], evidence=["source run ID", "units", "period and quality metadata where available"], confidence="Deterministic source metadata only; no AI confidence score.", freshness="Latest successful stored runs; may be stale.", limitations=["Does not run a new soil test or soil assessment."]),
    _cap("water_intelligence", "partial", "Explains an existing stored water plan and relevant climate evidence.", context=["field", "water", "climate", "data_gaps"], evidence=["water plan source ID", "units", "season and allocation metadata"], confidence="Deterministic plan status only; no AI confidence score.", freshness="Latest successful stored plan; may be stale.", limitations=["Does not calculate a new irrigation plan."]),
    _cap("climate_intelligence", "partial", "Explains stored climate feature outputs for an authorized field.", context=["field", "climate", "data_gaps"], evidence=["feature run ID", "period", "metric units"], confidence="Feature-run quality/provenance only; no forecast probability.", freshness="Latest successful stored feature run; no live forecast.", limitations=["Historical/derived context is not a weather forecast."]),
    _cap("vegetation_intelligence", "partial", "Explains the latest stored quality-gated satellite-derived vegetation summary.", context=["field", "vegetation", "data_gaps"], evidence=["scene ID", "observation time", "processing version", "quality summary"], confidence="Quality flags only; spectral index is not a diagnosis.", freshness="Latest valid stored observation with explicit freshness metadata.", limitations=["No disease, pest, nutrient or irrigation diagnosis; no full raster-history tool."]),
    _cap("stress_anomaly_screening", "partial", "Describes existing statistical and spatial screening evidence without agronomic diagnosis.", context=["field", "climate", "soil", "water", "vegetation", "management"], evidence=["engine source and screening provenance"], confidence="Only confidence/quality fields emitted by the deterministic source; not a calibrated AI probability.", freshness="As of the stored source run/observation.", limitations=["Not an authoritative urgency ranking and not a diagnosis."]),
    _cap("crop_suitability", "planned", "A stable adapter contract is defined; no validated AI Core suitability tool is currently registered.", context=["field", "soil", "climate", "water", "rotation", "crop knowledge"], evidence=["validated crop constraints and source-cited regional knowledge"], confidence="A future deterministic engine must define confidence semantics before registration.", freshness="Not available through this AI Core.", limitations=["Do not present a suitability score as operational."]),
    _cap("crop_rotation_explanation", "partial", "Can explain an existing saved rotation result; new optimization is not exposed through this AI Core.", context=["field", "rotation", "soil", "climate", "water"], evidence=["rotation run ID", "solver status", "assignment and unevaluated dimensions"], confidence="Uses the stored solver status; no model-generated score.", freshness="Latest successful stored run.", limitations=["Does not create, rank or optimize rotations."]),
    _cap("agricultural_recommendations", "unavailable", "No validated recommendation or prescription tool is registered in the AI Core.", context=["field", "approved domain engines"], evidence=["versioned analytical output and review provenance"], confidence="No action confidence is emitted.", freshness="Not available.", limitations=["Do not generate actions from language-model memory; use existing domain workflows and their human review."]),
    _cap("agricultural_risk_ranking", "planned", "A ranking contract is reserved; no cross-field urgency/risk ranking is registered.", context=["authorized comparison set", "domain evidence"], evidence=["versioned risk factors and calibrated rules"], confidence="Must be defined by the future deterministic ranking service.", freshness="Not available through this AI Core.", limitations=["Do not rank farms or fields from model prose."]),
    _cap("scenario_simulation", "planned", "A scenario contract is reserved; simulation is not an AI Core tool today.", context=["field", "scenario inputs", "versioned engine"], evidence=["input fingerprint", "simulation run ID", "solver status"], confidence="Must preserve the simulation engine's own uncertainty semantics.", freshness="Not available through this AI Core.", limitations=["No scenario is created or simulated by this route."]),
    _cap("predictive_analysis", "unavailable", "No validated predictive agricultural model is registered.", context=["field", "validated training domain"], evidence=["model version", "training/validation provenance", "prediction interval"], confidence="No prediction or confidence is emitted.", freshness="Not available.", limitations=["The current language model is not treated as a predictive model."]),
    _cap("gis_spatial_analytics", "partial", "Spatial evidence already surfaced by the field evidence pack can be explained; there is no AI-controlled map or cross-field analysis tool.", context=["authorized field", "geospatial evidence"], evidence=["scene, processing and spatial-resolution provenance"], confidence="Uses only the deterministic analytics' published metadata.", freshness="As of the stored scene/processing run.", limitations=["No map rendering, new raster processing or cross-tenant spatial query is exposed."]),
    _cap("intelligence_reporting", "planned", "A report-integration contract is reserved; report generation is not registered as an AI Core tool.", context=["explicit authorized report scope"], evidence=["report job ID", "source manifest", "generation version"], confidence="No AI confidence is applicable.", freshness="Not available through this AI Core.", limitations=["Use the existing report API and its authorization/confirmation behavior."]),
    _cap("platform_operations", "unavailable", "No mutating or external-action tools are registered in the AI Core.", context=["existing domain API and authorization"], evidence=["audited action result"], confidence="Not applicable.", freshness="Not available.", limitations=["Mutations must use existing domain endpoints; no user confirmation or action framework is implemented here."]),
)


def list_capabilities() -> list[CapabilityDescriptor]:
    """Return fresh schema objects to prevent callers mutating the registry."""
    return [item.model_copy(deep=True) for item in CAPABILITIES]


def get_capability(name: str) -> CapabilityDescriptor | None:
    return next((item.model_copy(deep=True) for item in CAPABILITIES if item.name == name), None)

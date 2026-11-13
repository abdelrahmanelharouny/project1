"""Deterministic request planning; no model-generated security decisions."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.intelligence.orchestration.contracts import AIIntent, IntentPlan, PlannedToolCall

_FIELD_TOOL = "answer_field_question"
_ALL_FIELD_DOMAINS = ["climate", "water", "soil", "rotation", "management", "vegetation", "data_gaps"]


@dataclass(frozen=True)
class IntentDefinition:
    patterns: tuple[str, ...]
    domains: tuple[str, ...]
    availability: str
    supported: bool
    limitation: str | None = None


_DEFINITIONS: dict[AIIntent, IntentDefinition] = {
    AIIntent.SATELLITE_INTERPRETATION: IntentDefinition(
        (r"\bsatellite\b", r"\bndvi\b", r"\bevi\b", r"imagery", r"vegetation index"),
        ("vegetation", "data_gaps"), "partial", True,
        "Only stored, quality-gated vegetation evidence is available; this is not a diagnosis or a full image-history service.",
    ),
    AIIntent.SOIL_INTELLIGENCE: IntentDefinition(
        (r"\bsoil\b", r"\bph\b", r"nutrient", r"organic carbon", r"erosion"),
        ("soil", "management", "data_gaps"), "partial", True,
        "Explains stored soil/management engine outputs only; it does not run a new soil assessment.",
    ),
    AIIntent.WATER_INTELLIGENCE: IntentDefinition(
        (r"\bwater\b", r"irrigat", r"rainfall", r"precipitation", r"moisture", r"\bnir\b"),
        ("water", "climate", "data_gaps"), "partial", True,
        "Explains stored water-plan and climate evidence only; it does not run a new water plan.",
    ),
    AIIntent.CLIMATE_INTELLIGENCE: IntentDefinition(
        (r"\bclimate\b", r"\bweather\b", r"temperature", r"hot days", r"frost", r"dry spell"),
        ("climate", "data_gaps"), "partial", True,
        "Explains stored climate feature runs only; it does not fetch a forecast.",
    ),
    AIIntent.CROP_SUITABILITY: IntentDefinition(
        (r"crop suitability", r"suitable crop", r"best crop", r"what crop should", r"what crop.*\b(best|suitable)\b", r"can i grow"),
        ("field", "soil", "climate", "water", "rotation", "data_gaps"), "planned", False,
        "A dedicated, validated suitability tool is not registered in the AI Core.",
    ),
    AIIntent.CROP_ROTATION: IntentDefinition(
        (r"\brotation\b", r"rotate crops", r"next crop", r"crop sequence"),
        ("rotation", "soil", "climate", "water", "data_gaps"), "partial", True,
        "Can explain a stored rotation run; it cannot create or optimize a new rotation through the AI Core.",
    ),
    AIIntent.AGRICULTURAL_RECOMMENDATION: IntentDefinition(
        (r"recommend(?:ation|ed)?", r"\bshould i\b", r"what should i", r"agricultural advice"),
        tuple(_ALL_FIELD_DOMAINS), "unavailable", False,
        "No validated recommendation or prescription tool is registered; the AI Core will not invent an action from model memory.",
    ),
    AIIntent.AGRICULTURAL_RISK: IntentDefinition(
        (r"\brisk\b", r"risk assessment", r"risk level"),
        tuple(_ALL_FIELD_DOMAINS), "planned", False,
        "A validated, field-ranking risk decision service is not registered in the AI Core.",
    ),
    AIIntent.STRESS_ANOMALY: IntentDefinition(
        (r"\bstress\b", r"\banomal", r"\burgent\b", r"needs? attention", r"\bdisease\b", r"\bpest\b"),
        tuple(_ALL_FIELD_DOMAINS), "partial", True,
        "Available signals are evidence-bound statistical screens, not diagnoses or an authoritative cross-field urgency ranking.",
    ),
    AIIntent.SCENARIO_COMPARISON: IntentDefinition(
        (r"\bscenarios?\b", r"what if", r"what-if", r"compare scenarios", r"scenario comparison"),
        tuple(_ALL_FIELD_DOMAINS), "planned", False,
        "Scenario execution is not yet registered as an AI Core tool.",
    ),
    AIIntent.PREDICTIVE_ANALYSIS: IntentDefinition(
        (r"\bpredict\b", r"\bprediction\b", r"\bforecast\b", r"yield forecast", r"predictive", r"tomorrow", r"next (week|month|season|year)"),
        tuple(_ALL_FIELD_DOMAINS), "unavailable", False,
        "No validated predictive agricultural model is registered for this request.",
    ),
    AIIntent.REPORT_GENERATION: IntentDefinition(
        (r"\breport\b", r"export report", r"generate a report"),
        ("field", "data_gaps"), "planned", False,
        "Report generation is not registered as an AI Core action tool.",
    ),
    AIIntent.PLATFORM_OPERATION: IntentDefinition(
        (r"\bcreate\b", r"\bdelete\b", r"\bupdate\b", r"\bsave\b", r"change my", r"invite user"),
        (), "unavailable", False,
        "The AI Core has no controlled action tools; mutations must use their existing authorized APIs and confirmation flows.",
    ),
    AIIntent.VEGETATION_INTELLIGENCE: IntentDefinition(
        (r"\bvegetation\b", r"plant health", r"canopy"),
        ("vegetation", "data_gaps"), "partial", True,
        "Only stored, quality-gated vegetation evidence is available; spectral indices are not agronomic diagnoses.",
    ),
    AIIntent.FARM_QUESTION: IntentDefinition(
        (r"my farms", r"farm summary", r"whole farm", r"farm portfolio", r"all fields in my farm"),
        ("field", "data_gaps"), "unavailable", False,
        "The current AI Core integration is field-scoped and does not retrieve a whole-farm portfolio.",
    ),
}


def _matching_intent(question: str, has_field: bool) -> AIIntent:
    text = question.casefold()
    # Explicit workflows/actions outrank mentions of their evidence domains.
    priority = (
        AIIntent.PLATFORM_OPERATION,
        AIIntent.REPORT_GENERATION,
        AIIntent.SCENARIO_COMPARISON,
        AIIntent.PREDICTIVE_ANALYSIS,
        AIIntent.CROP_SUITABILITY,
        AIIntent.CROP_ROTATION,
        AIIntent.AGRICULTURAL_RECOMMENDATION,
        AIIntent.AGRICULTURAL_RISK,
        AIIntent.SATELLITE_INTERPRETATION,
        AIIntent.STRESS_ANOMALY,
        AIIntent.SOIL_INTELLIGENCE,
        AIIntent.WATER_INTELLIGENCE,
        AIIntent.CLIMATE_INTELLIGENCE,
        AIIntent.VEGETATION_INTELLIGENCE,
        AIIntent.FARM_QUESTION,
    )
    for intent in priority:
        definition = _DEFINITIONS[intent]
        if any(re.search(pattern, text) for pattern in definition.patterns):
            return intent
    if re.search(r"\b(field analysis|analy[sz]e this field|field condition)\b", text):
        return AIIntent.FIELD_ANALYSIS
    return AIIntent.FIELD_QUESTION if has_field else AIIntent.AGRICULTURAL_KNOWLEDGE


def create_plan(question: str, *, has_field: bool) -> IntentPlan:
    """Classify with bounded, deterministic rules and return a validated plan."""
    intent = _matching_intent(question, has_field)
    definition = _DEFINITIONS.get(intent)
    if intent == AIIntent.FIELD_QUESTION:
        availability, supported = "available", True
        domains = tuple(_ALL_FIELD_DOMAINS)
        limitation = None
    elif intent == AIIntent.FIELD_ANALYSIS:
        availability, supported = "available", True
        domains = tuple(_ALL_FIELD_DOMAINS)
        limitation = None
    elif intent == AIIntent.AGRICULTURAL_KNOWLEDGE:
        availability, supported = "unavailable", False
        domains = ()
        limitation = "No reviewed agricultural knowledge-retrieval source is wired to the AI Core; the model will not answer from unsupported general knowledge."
    elif intent == AIIntent.AMBIGUOUS:
        availability, supported, domains, limitation = "unavailable", False, (), "The requested analytical intent is unclear."
    else:
        assert definition is not None
        availability = definition.availability
        supported = definition.supported
        domains = definition.domains
        limitation = definition.limitation

    needs_field = intent not in (
        AIIntent.AGRICULTURAL_KNOWLEDGE,
        AIIntent.AGRICULTURAL_RECOMMENDATION,
        AIIntent.PLATFORM_OPERATION,
    )
    missing = ["field_id"] if needs_field and not has_field else []
    needs_clarification = bool(missing) or intent == AIIntent.AMBIGUOUS
    tools = [_FIELD_TOOL] if supported and has_field and not needs_clarification else []
    expected = "clarification" if needs_clarification else (
        "grounded_explanation" if tools else "unavailable"
    )
    return IntentPlan(
        intent=intent,
        required_entities=["field_id"] if needs_field else [],
        required_context=["field", *domains] if needs_field else [],
        required_tools=tools,
        tool_calls=[
            PlannedToolCall(name=name, context_domains=list(domains))
            for name in tools
        ],
        missing_information=missing,
        permission_scope=(
            ["field.read", "field.analysis.read"] if tools
            else ["field.read"] if needs_field
            else []
        ),
        clarification_needed=needs_clarification,
        availability=availability,
        expected_output=expected,
        limitations=[limitation] if limitation else [],
    )

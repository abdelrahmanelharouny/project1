# CropTwist AI Tool Registry and Capability Catalog

**Status:** Describes current checked-out backend source. Discovery metadata is not evidence of live provider connectivity or completed release verification. Final verification counts are maintained in [`MASTER_INTEGRATION_ENGINEERING_REPORT.md`](../../../../docs/implementation/MASTER_INTEGRATION_ENGINEERING_REPORT.md).

## Registry rules

Tools are declared in `app/intelligence/orchestration/tools.py` with a unique name, description, strict Pydantic input/output models, permission set, category, side-effect classification, deadline, output-byte ceiling, handler, normalized error codes, and confirmation flag. `ToolRegistry.execute` accepts a name only when both registered and included in the deterministic server-created plan. It rechecks permissions, rejects extra/invalid arguments, blocks side effects, enforces timeout and output limits, validates output, and returns a typed invocation record. Model prose or provider responses never authorize a tool.

The workflow runner allows at most three ordered steps, validates each dependency as a reference to an earlier step, and passes only Pydantic-validated prior results to the next handler. Current planner rules emit the two-step evidence workflow described below. The registry also retains a one-step `answer_field_question` handler, but current planner output does not call it. The literal current tool name for the second step is `synthesize_field_answer`; there is no `answer_field_context` tool identifier in the checked-out source.

The Core is read-only. Any `CONTROLLED_ACTION` category or non-`none` side effect is rejected with `ACTION_CONFIRMATION_REQUIRED` before its handler runs. No mutating or external-action tool is registered. A future action path requires a separate audited authorization and confirmation design.

## Registered tools

| Name | Current planner use | Category / side effect | Required permissions | Input and output | Limits |
|---|---|---|---|---|---|
| `collect_field_evidence` | Step 1 of current field explanation plan | `read_only` / `none` | `field.read`, `field.analysis.read` | `FieldAdvisorInput`: `question` (1–2,000 chars), `locale` (`en`/`ar`). `EvidenceCollectionOutput`: selected `evidence_pack` and `selected_domains` (up to 8). | 30-second handler timeout; 32 KB serialized result ceiling; selected evidence pack hard limit 16,000 UTF-8 bytes. |
| `synthesize_field_answer` | Step 2; depends on step 1 | `analytical` / `none` | `field.read`, `field.analysis.read` | Same `FieldAdvisorInput`; `AdvisorToolOutput`: answer (1–8,000 chars), up to 40 `evidence_used` records, engine metadata, and evidence pack. | 50-second handler timeout; 64 KB serialized result ceiling. |
| `answer_field_question` | Registered, not emitted by the current planner | `analytical` / `none` | `field.read`, `field.analysis.read` | Same input/output schemas; invokes the existing advisor after collection in a single handler. | 50-second handler timeout; 64 KB serialized result ceiling. |

Registry-wide ceilings include at most three workflow calls, a 32 KB JSON tool-input limit, no more than 60 seconds per registered handler, and no more than 64 KB per tool output. These ceilings do not mean a three-step domain workflow currently exists.

## Evidence domains used by the workflow

The deterministic planner selects among seven stored evidence domains: `climate`, `water`, `soil`, `rotation`, `management`, `vegetation`, and `data_gaps`. Evidence selection always preserves the `field` profile and explicit data-gap metadata. A request's optional `context_domains` is allowlisted and can narrow the workflow selection; it is not authorization. The server derives the authorized field before reads.

Deterministic context expansion includes climate with water, soil/climate/water with rotation, and climate/water/soil/management for some “why” vegetation questions. The existing evidence builder is the source of truth. Selecting a domain does not run its engine, create a new measurement, or upgrade the capability's availability status.

## Capability catalog

`GET /api/v1/ai/capabilities` returns domain descriptors and gateway schemas. `GET /api/v1/ai/tools` returns actual registered tools only. A planned or unavailable descriptor is not executable; the tool list is the callable registry.

| Capability | Status | Current meaning | Explicit limit |
|---|---|---|---|
| `field_evidence_answer` | `partial` | Deterministic evidence collection followed by validated field explanation when provider/privacy configuration allows it. | Explanation of stored evidence only; no generated actions or guaranteed provider response. |
| `crop_intelligence` | `unavailable` | A reviewed, cited crop-knowledge contract is described. | No configured approved corpus/embedding adapter is retrieved by the advisor. |
| `soil_intelligence` | `partial` | Explains stored soil, nutrient, carbon, and management results when present. | Does not run a new soil assessment. |
| `water_intelligence` | `partial` | Explains an existing stored water plan and related climate evidence. | Does not calculate a new irrigation plan. |
| `climate_intelligence` | `partial` | Explains stored climate feature-run outputs. | No live weather forecast. |
| `vegetation_intelligence` | `partial` | Explains the latest stored quality-gated satellite-derived summary. | No disease/pest diagnosis or complete raster-history tool. |
| `stress_anomaly_screening` | `partial` | Describes existing statistical/spatial screening signals. | Not a diagnosis or authoritative urgency ranking. |
| `crop_suitability` | `planned` | Reserved adapter contract. | No validated suitability tool is registered. |
| `crop_rotation_explanation` | `partial` | Explains a saved rotation result when available. | No creation, optimization, or ranking of a new rotation. |
| `agricultural_recommendations` | `unavailable` | Future domain-owned, validated recommendations. | No prescription/action from model memory. |
| `agricultural_risk_ranking` | `planned` | Reserved deterministic comparison/ranking contract. | No field or farm risk ranking is registered. |
| `scenario_simulation` | `planned` | Reserved versioned scenario contract. | No scenario is created or simulated by the AI Core. |
| `predictive_analysis` | `unavailable` | Future validated, domain-owned predictive model. | Includes yield prediction/forecasting; the LLM is not treated as a yield model. |
| `gis_spatial_analytics` | `partial` | Explains spatial evidence already present in the field evidence pack. | No new raster processing, map rendering, or cross-field spatial query. |
| `intelligence_reporting` | `planned` | Reserved report integration contract. | Report generation is not an AI Core tool; use the existing report API. |
| `platform_operations` | `unavailable` | Future controlled operations. | No data mutation or external action is callable from this Core. |

`partial` means a limited stored result can be explained, not that an analytical engine is available through the AI Core. Recommendation, yield/prediction, scenario, report, and action requests are explicitly unavailable or planned as shown; none is a hidden fallback.

## Future capability integration contract

The internal server-only `DomainCapabilityRequest` contains trace ID, capability code, server-derived actor (user/organization/role/permissions), authorized entity scope/ID, locale, selected context domains, required evidence, and capability-specific parameters. `AnalyticalResultContract` defines a result ID, capability/entity/scope, result value/unit, observation period, source references, processing version, evidence quality, optional source-provided confidence, limitations, and status. Public `CapabilityDescriptor` request/response schemas describe the gateway's `AIRequest` and `AIResponse`, not internal actor or resource inputs.

A domain integration must remain owned by its domain workstream, authorize scope through existing identity services, define freshness/quality/confidence/error semantics, include immutable source IDs/version/date/unit and explicit gaps, and add planner, contract, adversarial, evidence, and owner-reviewed evaluation coverage. Register only after end-to-end validation; keep writes and external actions outside this registry until a separate confirmation and audit system is reviewed.

## Failure and trace contracts

Safe normalized tool failures include `TOOL_NOT_ALLOWED`, `TOOL_PERMISSION_DENIED`, `TOOL_INVALID_ARGUMENTS`, `TOOL_INPUT_TOO_LARGE`, `TOOL_TIMEOUT`, `TOOL_EXECUTION_FAILED`, `TOOL_INVALID_OUTPUT`, `TOOL_OUTPUT_TOO_LARGE`, and `ACTION_CONFIRMATION_REQUIRED` (plus workflow-specific safe codes). Trace records retain step name/category/effect/status/duration/output size/error code, not raw arguments or handler exception contents.

Provider errors are separately normalized by provider adapters. Only retryable availability/capacity/transport conditions may advance the application-level provider chain; request/schema, credential, permission, billing, safety, or policy failures do not. After partial provider stream output, the adapter does not append a different provider's answer.
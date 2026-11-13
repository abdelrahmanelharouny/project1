# CropTwist AI Tool Registry and Capability Catalog

## Registry rules

Tools are registered in `app/intelligence/orchestration/tools.py` with a unique name, description, Pydantic input/output schema, permission set, category, side-effect classification, timeout, output-byte limit, handler and confirmation flag. `ToolRegistry.execute` accepts only names present in the deterministic server-created plan, checks permissions independently of model output, rejects extra/invalid arguments, validates typed output, enforces the time/result budget and returns a `ToolInvocation` record. No model tool-call result is interpreted as authorization.

`ToolRegistry.execute_workflow` executes an ordered list of at most three `PlannedToolCall` steps. Each step declares a tool name, server-created arguments, approved context domains and prior-step dependencies. Later handlers receive only prior Pydantic-validated outputs in `AuthorizedAIContext.prior_tool_results`. Dependencies must point to earlier steps. Any failure is normalized to a safe code and the trace keeps completed/failing step outcomes. The response merger only accepts the registered common advisor output contract; conflicts, oversized merged evidence and oversized answers fail closed. Current planner rules emit one step; no multi-step agronomic workflow is registered yet.

The AI Core is read-only. A `CONTROLLED_ACTION` category or any non-`none` side effect is rejected with `ACTION_CONFIRMATION_REQUIRED` before a handler runs. An action requires a separate audited authorization/confirmation workflow; none exists here.

## Operational tool

| Name | Category / effects | Permissions | Input | Output | Limits |
|---|---|---|---|---|---|
| `answer_field_question` | `analytical`, side effect `none` | `field.read`, `field.analysis.read` | `question` (1–2,000 characters), `locale` (`en`/`ar`) | `answer` (1–8,000 chars), `evidence_used` (≤40), `engine`, selected `evidence_pack` | 50 seconds; 64 KB JSON output; one registered call in today's planner. |

The handler requires a server-authorized field and provider, builds the existing read-only `build_field_evidence` pack, selects only approved domains (≤16,000 bytes), then calls the existing advisor validation path through the provider adapter. It does not create recommendations, write agronomic records, update a field, or call arbitrary SQL/filesystem/network/code tools.

## Capability catalog

`GET /api/v1/ai/capabilities` lists domain-level status and public gateway schemas. `GET /api/v1/ai/tools` lists actual tool registrations only, including their Pydantic schemas, timeout, output ceiling, normalized error codes, permissions, category and side-effect classification. These registries are intentionally distinct: a domain can have a planned contract without an executable tool.

| Capability | Status | Scope/meaning | Critical limitation |
|---|---|---|---|
| `field_evidence_answer` | available | Cited explanation via existing field evidence/advisor. | Explanation only; no generated actions. |
| `crop_intelligence` | unavailable | Cited crop knowledge contract. | Curated knowledge is not retrieved by advisor. |
| `soil_intelligence` | partial | Stored soil, nutrient, carbon and management results. | Does not run a new assessment. |
| `water_intelligence` | partial | Stored water-plan and relevant climate evidence. | Does not calculate a new irrigation plan. |
| `climate_intelligence` | partial | Stored feature-run climate metrics. | No live weather forecast. |
| `vegetation_intelligence` | partial | Stored quality-gated satellite summary. | No disease/pest diagnosis or full raster-history tool. |
| `stress_anomaly_screening` | partial | Existing statistical/spatial screening signals. | Not a diagnosis or authoritative urgency ranking. |
| `crop_suitability` | planned | Future field/soil/climate/water/rotation adapter. | Not executable. |
| `crop_rotation_explanation` | partial | Existing saved rotation result. | No new optimization or creation. |
| `agricultural_recommendations` | unavailable | Future validated recommendations. | Model memory cannot prescribe an action. |
| `agricultural_risk_ranking` | planned | Future deterministic cross-field ranking. | No model-generated ranking. |
| `scenario_simulation` | planned | Future versioned simulation adapter. | No scenario is created or run. |
| `predictive_analysis` | unavailable | Future validated models. | The LLM is not a predictive model. |
| `gis_spatial_analytics` | partial | Existing spatial evidence can be explained. | No map rendering, new raster processing or cross-tenant spatial query. |
| `intelligence_reporting` | planned | Future report-job integration contract. | Use existing report APIs and their confirmation/authorization. |
| `platform_operations` | unavailable | Future controlled actions. | No mutation tool is registered. |

`partial` means a limited existing stored result can be explained; it does not mean the corresponding analytical engine is available through the AI Core.

## Future capability integration contract

The Python adapter contract defines a server-only `DomainCapabilityRequest` with a trace ID, capability code, server-derived actor (user/org/role/permissions), authorized entity scope/ID, locale, selected context domains, evidence requirements and domain-specific `parameters`. A domain service returns `AnalyticalResultContract`: result ID, capability, entity/scope, result type, value/unit, observation period, source references, processing version, evidence quality, optional model/recommendation confidence, limitations and status. Public `CapabilityDescriptor.request_schema`/`response_schema` instead describe `AIRequest`/`AIResponse`; internal actor/resource fields are not exposed as client inputs.

An integrating service must:

1. Be owned by its domain workstream; do not reimplement that domain engine in a prompt.
2. Provide strict input/output schemas and define freshness, quality, confidence and error semantics.
3. Resolve/authorize the entity through the existing server identity/service before reading data; never accept model-supplied IDs or tenant scopes.
4. Supply immutable source IDs/version/date/unit and explicit missing-data/quality flags.
5. Add an explicit `CapabilityDescriptor` status; only mark it `available` after end-to-end tests pass.
6. Register a tool with minimum permissions, `side_effect="none"` for read/analysis, bounded timeout/output, and no arbitrary query/network/code access.
7. Add deterministic planner/evaluation cases, adversarial tests and owner-reviewed evidence-validation tests.
8. For any write/external operation, keep it out of this read-only registry until a separately reviewed confirmation and audit workflow is implemented.

## Failure and trace contracts

Tool invocation statuses are `succeeded`, `failed`, `timed_out`, or `denied`; failures expose only normalized error codes such as `TOOL_TIMEOUT`, `TOOL_INVALID_ARGUMENTS`, `TOOL_INVALID_OUTPUT`, `TOOL_OUTPUT_TOO_LARGE`, `TOOL_PERMISSION_DENIED`, and `ACTION_CONFIRMATION_REQUIRED`. Trace records store step name/category/effect/status/duration/output bytes/error code; they never store raw arguments or handler exceptions.

Provider failures use the existing bridge's fail-soft behavior. The advisor may use one constrained regeneration and deterministic fallback; the Core never invents a backup provider or retries the same failing model as a claimed fallback.

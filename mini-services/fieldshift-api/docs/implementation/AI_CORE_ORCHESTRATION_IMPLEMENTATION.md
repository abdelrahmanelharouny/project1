# AI Core Orchestration — Implementation Report

- **Date:** 2026-11-14
- **Repository:** `abdelrahmanelharouny/project1/mini-services/fieldshift-api`
- **Branch:** `feature/ai-core-orchestration`
- **Base checkpoint:** `998f7a5` (`Audit CropTwist and harden auth, AI, and configuration`)
- **Implementation commit:** will be recorded in the follow-up report update immediately after the implementation commit.

## Executive summary

Added a central, authenticated AI request lifecycle to the existing CropTwist backend. The implementation reuses current identity authorization, field evidence, advisor validation, LLM bridge, SQLAlchemy session and shared rate-limit components. It adds strict intent/response/evidence contracts, a deterministic planner, a server-controlled typed tool registry with bounded sequential execution, private ownership for new conversations, metadata-only invocation traces, capability/tool discovery, evaluation helpers, regression tests and the requested documentation.

This is a backend foundation, not the full AI Copilot, a new agricultural analytical engine, a general agent, or a production-ready multi-provider service. One field-explanation tool is operational. A workflow can be planned for up to three validated steps, but today's planner emits one step and no specialist multi-tool/domain workflow is registered. Forecasting, ranking, prescribing, report actions and platform mutations are not performed by this AI Core.

## Initial audit and verified baseline

The initial read-only audit inspected existing routes, auth and membership resolution, field evidence, advisor/session flow, provider bridge, prompt/response/numeric validation, migrations, ORM models, metrics, configuration, tests, knowledge services, and the API router.

### Existing reusable foundations

- `app/domains/identity/service.py`: existing `get_principal` and `get_field_for_principal` provide authenticated identity and membership-authorized field scope.
- `app/intelligence/evidence.py`: `build_field_evidence` assembles profile and latest successful stored climate, water, soil, rotation, management and vegetation evidence with data gaps/source IDs.
- `app/intelligence/advisor.py` and `response_contract.py`: existing advisor prompt, structured parsing, citation checks, one constrained retry and deterministic fallback.
- `app/intelligence/bridge.py`: existing fail-soft Z-AI bridge client with timeout, transport/circuit/concurrency protections; no alternate LLM provider registry existed.
- `app/intelligence/numeric_guard.py`, `guard.py`, `sessions.py`, `models_ai.py`: existing numeric checks, untrusted prompt helpers, transcript model and history helpers.
- `app/recommendations/registry.py` and `app/knowledge/`: existing deterministic recommendation/knowledge foundations are domain services; they were not duplicated as LLM tools.

### Initial gaps carried into implementation

1. No central lifecycle, capability discovery, server-side tool registry or common execution/response trace existed.
2. New advisor conversations were not creator-owned; field membership alone could expose another user's transcript in the same organization.
3. Untrusted prompt delimiters were not escaped and stored history was replayed without the same sanitization boundary.
4. General numeric matching could accept equal values with incompatible dimensions; cited numeric checks needed to stay section-scoped.
5. Advisor citation validation could accept a response with at least one valid label rather than inline evidence on each factual sentence.
6. The curated relational knowledge base was not retrieved by the advisor. No RAG, embeddings, vector store or pgvector retrieval was found in the reviewed backend.
7. Existing AI routes did not share an AI request rate limit; traces lacked a per-invocation privacy-conscious record.
8. The identity system has organization membership and roles, but no domain-specific ACL. Active field members receive the existing field-read scope; the new gateway does not claim role-specific soil/climate permissions.

The pre-change, database-free baseline completed with **29 passed, 13 pre-existing SQLAlchemy `metadata` reserved-name warnings** across prompt guard, structured response and bridge async tests. The baseline was run with backend `PYTHONPATH` and pytest configuration that excludes DB fixtures.

## Implemented architecture

### Request lifecycle and public surface

The API layer is `app/api/v1/ai_core.py`, registered in the existing `app/api/v1/router.py` aggregate. It exposes:

- `POST /api/v1/ai/requests`: strict `AIRequest`, shared user-keyed rate limit, safe request correlation, deterministic planning, field authorization, context assembly, bounded tool execution, grounded response validation, private transcript persistence and safe invocation trace.
- `GET /api/v1/ai/capabilities`: available/partial/planned/unavailable descriptors with context, permissions, evidence, confidence/freshness and limitation semantics.
- `GET /api/v1/ai/tools`: only registered tool names and their input/output JSON Schemas, category, effects, permissions, time/output limits and confirmation flag.

`AIRequest` accepts a 1–2,000 character question; optional field/conversation UUID; `en`/`ar`; and at most eight unique allowlisted evidence domains. It forbids extra actor, organization and trace fields. User/org/farm/role identity is always derived server-side.

### Planning, orchestration and context

`app/intelligence/orchestration/` contains the strict request, plan, provider, evidence, invocation, capability and response contracts; deterministic intent planning; context ownership/authorization; typed provider interface; evidence normalization; strict Core validation; evaluation helpers; and the bounded lifecycle service.

Planner intents include knowledge, farm/field questions, field analysis, satellite, soil, water, climate, vegetation, stress/anomaly, crop suitability, rotation, recommendations, risk, scenario, predictive, report, platform operation and ambiguity. Missing required field scope returns clarification. Unsupported requests remain planned/unavailable and do not enter a generic LLM answer path.

For field scope, the resolver authorizes the field with the existing identity service, derives farm/organization/role from the database, loads only that selected field, and sets internal `field.read`/`field.analysis.read` permissions. The user can narrow context domains; the server filters them against planner-approved domains. There is no farm-portfolio comparison endpoint.

The `ToolRegistry` validates every step against registered names, input/output Pydantic schemas, field permissions, timeout, 32 KB input/64 KB output caps and a maximum of three calls (with a hard 60-second per-tool ceiling). Each tool exposes normalized error codes. Ordered steps may consume only validated prior outputs and must declare dependencies on earlier steps. The response merger accepts only the current common advisor response model and rejects conflicting/oversized evidence. The current deterministic planner emits one step (`answer_field_question`); future multi-tool plans require specialist work and domain-owner evaluation.

### Evidence, response and providers

`EvidenceItem` preserves claim class, entity scope/ID, source references, observation period, units in domain values, spatial/processing metadata, source quality, limitations, and explicit missing-data status. The evidence selection path forces field/data-gap metadata and has a 16,000-byte ceiling. The response keeps facts, derived results, predictions, recommendations, general knowledge, assumptions and missing information separate. Prediction/recommendation/general-knowledge arrays are empty because no such tool currently ran.

`LegacyBridgeProvider` implements the provider-neutral `LLMProvider` protocol while delegating transport/auth/retry/circuit semantics to the existing bridge. It explicitly reports no native structured-output mode, model-side tool calling, streaming, or guaranteed token-usage reporting. Provider selection/failover remains future work; there is no fake second-provider fallback.

The current advisor parser/citation/numeric guards are reused. AI Core adds inline citation coverage for every factual sentence and a cited-section numeric gate. Prompt user/history/evidence blocks are escaped and handled as untrusted; stored history is sanitized and limited to six turns (12 message rows). On Core validation failure, unvalidated narrative is replaced by a deterministic localized notice.

### Conversation privacy, rate limiting and observability

Migration `0024_ai_core_orchestration` is additive: nullable `ai_advisor_sessions.owner_user_id` plus index, and `ai_execution_traces` plus indexes/check constraints. Existing sessions remain owner `NULL`; new sessions are stamped with authenticated owner. Core rejects non-owned, cross-field, expired and legacy-unowned sessions with the same 404. Legacy null-owner compatibility remains on the old advisor behavior.

Conversation expiry defaults to 365 days of inactivity and can be configured through `CROPTWIST_AI_CONVERSATION_RETENTION_DAYS`; expiry blocks Core access but does not delete transcripts. The existing advisor/insights/LLM-backed recommendation refresh routes and AI Core share the existing process-local per-user one-minute limiter (default setting 10/minute). Multi-replica production must replace it with shared storage and a dedicated AI budget.

The append-only trace records request/trace IDs, user/org/field/session refs, intent, provider/model, prompt version, selected domains, evidence hash/source refs, step metadata, optional usage, validation codes, latency, status and safe error category. It does not store raw questions, answers, evidence values, prompt text, secrets or raw exceptions. Transcripts remain in the existing message table for conversation functionality.

## Important files and schema

| File | Purpose |
|---|---|
| `app/api/v1/ai_core.py`, `app/api/v1/router.py` | Authenticated AI routes and router registration. |
| `app/intelligence/orchestration/contracts.py` | Strict public and internal contracts, `EvidenceItem`, `AnalyticalResultContract`, `CapabilityDescriptor`, `AIExecution`, `AIResponse`, `PlannedToolCall`. |
| `app/intelligence/orchestration/planning.py`, `service.py` | Deterministic intents, bounded lifecycle, response aggregation, persistence and trace. |
| `app/intelligence/orchestration/context.py`, `tools.py` | Field/owner authorization, workflow registry, schema/permission/effect/time/result enforcement. |
| `app/intelligence/orchestration/capabilities.py`, `provider.py` | Capability directory/future service contract and provider-neutral bridge adapter. |
| `app/intelligence/orchestration/evidence.py`, `validation.py` | Selected evidence/provenance, missing data, size budget and Core response guard. |
| `app/intelligence/orchestration/evaluation.py`, `tests/evaluation/ai_core_cases.jsonl` | Plan benchmark, latency percentile/outcome summaries and explicitly priced usage estimate. |
| `app/intelligence/guard.py`, `numeric_guard.py`, `advisor.py` | Prompt boundary, dimensional numeric checks, advisor injection and strict Core path. |
| `app/intelligence/sessions.py`, `models_ai.py`, `models_orchestration.py` | Bounded transcript history, owner field, safe invocation ORM. |
| `migrations/versions/0024_ai_core_orchestration.py`, `migrations/env.py` | Additive schema and metadata registration. |
| `app/api/v1/recommendations.py`, `app/intelligence/config.py` | Legacy AI endpoint rate limiting/owner history and configurable conversation expiry. |
| `tests/unit/test_ai_core_orchestration.py`, `test_ai_core_evaluation.py` | Planner, multi-step, tool-policy, evidence and measurement tests. |
| `tests/integration/test_ai_core.py` | Authenticated/owner-private conversation and mocked-provider integration cases (authored, not executed here). |
| `docs/architecture/CROPTWIST_AI_CORE_ARCHITECTURE.md` | Architecture/runtime/integration map. |
| `docs/architecture/CROPTWIST_AI_TOOL_REGISTRY.md` | Operational tool and planned capability catalog. |
| `docs/architecture/CROPTWIST_AI_API_CONTRACTS.md` | API request/response/error schemas. |
| `docs/ai/AI_ORCHESTRATION_EVALUATION.md` | Benchmark, metrics, measurement boundaries and limitations. |
| `docs/ai/AI_CORE_SECURITY_THREAT_MODEL.md` | Trust boundaries, mitigations, residual risks and release gates. |
| `docs/ai/AI_CORE_EVIDENCE_AND_VALIDATION.md` | Evidence, grounding and numerical validation behavior. |

## Tests and validation performed

| Check | Result |
|---|---|
| Pre-change DB-free baseline: prompt guard, structured response, bridge | **29 passed**, 13 existing `metadata` warnings. |
| Final DB-free AI slice: `test_ai_core_orchestration.py`, `test_ai_core_evaluation.py`, prompt guard, numeric guard, structured response, bridge async | **63 passed**, 13 existing SQLAlchemy warnings, 2.81 seconds. |
| `compileall` for all new/touched AI modules and tests | Passed. |
| FastAPI OpenAPI generation | Passed; `/api/v1/ai/requests`, `/api/v1/ai/capabilities`, `/api/v1/ai/tools` registered. |
| Alembic history `0023_p07_field_reports:0024_ai_core_orchestration` | Passed; new revision recognized as head without DB connection. |
| `git diff --check` | Passed at final review. |
| DB-backed `tests/integration/test_ai_core.py` | **Not run.** |
| Full backend suite / schema migration apply | **Not run.** |
| Live LLM/provider call | **Not performed.** |

### Why integration/full DB tests were not run

The repository's `tests/conftest.py` connects to `croptwist_test`, upgrades migrations and runs autouse cleanup that truncates non-internal public tables. No isolated disposable PostGIS database was designated for this task. To avoid destructive interaction with a shared project database, integration/full-suite tests and the migration were not executed/applied. Run them only against a reviewed disposable PostGIS database. No database contents were modified by this workstream.

## Security validation

- API identity uses existing `get_principal`; client body cannot author user/org IDs.
- The field guard executes before evidence retrieval; tenant/role are derived via authorized field → farm → membership.
- Core session reuse checks both field and `owner_user_id`; unauthorized session IDs return a uniform 404.
- Registry rejects unplanned tools and missing permission scopes, validates arguments and outputs, bounds time/size/calls, and refuses all action/non-none side-effect tools before handler execution.
- Prompt question/history are sanitized, bounded, role-filtered, wrapped as untrusted and delimiter-escaped; retrieved evidence is likewise untrusted.
- Numeric validator rejects dimensionally incompatible matches; Core validator checks inline labels and cited-section numbers; unsupported content falls back safely.
- Invocation traces and logs omit raw prompt, response, evidence payload, secrets and provider exceptions.
- New and legacy LLM-backed endpoints share an authenticated-user limiter. The limiter remains explicitly process-local.

No production penetration test, agronomist review, provider data-retention review, privacy-policy review, or multi-replica load test has been completed.

## Integration results and workstream dependencies

This branch is based on audit checkpoint `998f7a5`; the repository already contained preceding geospatial/vegetation work on the shared base. The AI workstream does not edit GIS/report routes, satellite engines, frontend/navigation, `app/main.py`, or domain analytical engines. It adds only AI API aggregation and new AI-owned modules/migration.

The following must be integrated by later workstreams, not duplicated here:

- GIS/vegetation: add a domain-owned read/analysis adapter that publishes scene, acquisition time, processing version, cloud/valid-pixel quality and spatial resolution; no AI map rendering or raster processing is implemented.
- Soil/water/climate/rotation: expose versioned typed results and freshness/status/quality semantics through domain services; the current AI explains stored evidence only.
- Crop knowledge/RAG: expose deterministic cited/region-filtered retrieval from the existing relational pack store; no embeddings/vector database were added.
- Suitability/risk/prediction/scenario/report: register only after authoritative domain engines, permissions, evidence and tests are ready.
- Copilot frontend: consume the new request/response/capability contracts; no UI was built.
- Production/reliability: shared rate limiter, provider selection/fallback policy, token/pricing instrumentation, trace query, transcript deletion/retention and deployment configuration remain future operational work.

## Known limitations / next work

1. The deterministic rule planner currently emits a single step; sequential framework is capped at three but no genuine multi-domain plan is wired. Future steps must return the common typed advisor output or add an explicit composer.
2. The active tool only explains one authorized field. No farm portfolio compare/risk rank, specialist analytical engine, knowledge retrieval, prediction or action is available.
3. Capability intent matching is rules-based; measured accuracy is limited to synthetic deterministic cases, not field truth.
4. Citation labels and dimensional checks are structural. They do not prove semantic entailment or agronomic correctness.
5. Bridge does not guarantee usage counts or provide model pricing; current dollar cost cannot be reported. No factual-accuracy percentage is available.
6. New Core conversations are user-private, but legacy null-owner advisor history preserves prior field-scoped access. Conversation expiry prevents Core access but does not delete transcript rows.
7. Context membership access is organization-level; no domain-specific ACL exists. Current permissions do not distinguish soil/water/vegetation by role.
8. Rate limiting is in-process and shared with the existing auth setting; use a shared store and AI-specific quota before horizontal scale.
9. Full tests, PostGIS integration, migration apply, provider review and production deployment checks remain release gates.

## Commit references

- Base audit checkpoint: `998f7a5`.
- Implementation commit: to be filled in the final report update immediately after the first feature commit.
- Follow-up commit: documentation report update that records the implementation commit SHA.

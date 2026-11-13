# AI Core Security Threat Model

**Scope:** `POST /api/v1/ai/requests`, capability/tool discovery, the orchestration modules, their existing advisor/bridge dependencies, transcript ownership and invocation traces. The Core is field-scoped, read-only, and not a general autonomous agent.

## Assets and trust boundaries

| Asset | Exposure/impact |
|---|---|
| Farm, field, soil, water, climate, rotation and satellite evidence | Tenant-sensitive data; must be read only after field authorization. |
| User question, conversation history and model answer | Untrusted/user-private text; can contain prompt injection or personal information. |
| Session ownership, organization identity and role | Controls transcript/context access; must be database/server-derived. |
| Domain tool execution and field-engine results | Authoritative read/analysis operations; must remain bounded and side-effect-free. |
| Provider bridge credential and model requests | Service secret and possible external processing of question/evidence. |
| AI execution trace | Operator debugging metadata; must not contain raw prompt, answer, full evidence values or secrets. |

Trust boundaries: API client → authenticated CropTwist API; client-selected field/context → server resolver; server evidence → prompt; model output → validators; tool registry → domain service; CropTwist backend → configured LLM bridge; transcript versus metadata-only trace storage.

## Threats, controls and residual risk

| Threat | Controls implemented | Residual risk / follow-up |
|---|---|---|
| Forged user/org/field identifiers | Strict `AIRequest` forbids extra actor/tenant fields. `get_principal` supplies user; `get_field_for_principal` authorizes the field; organization and role are derived from authorized field/farm membership. | Current RBAC permits active organization members to read field data; there is no per-domain ACL. Do not claim the gateway provides role-level soil/climate permissions. |
| Cross-tenant field access | Field authorization happens before evidence/tool calls; field/farm/org is derived server-side. | Existing API identity service determines its own 403/404 behavior. Integration tests against the configured test database remain a release gate. |
| Same-tenant transcript disclosure | New `AIAdvisorSession.owner_user_id` is server-stamped; every Core conversation lookup checks field + owner; cross-user/missing/expired/legacy Core session returns the same 404. Legacy advisor history filters owner-stamped sessions to the creator. | Pre-migration sessions are `NULL` owner. The legacy endpoint intentionally preserves field-shared legacy access. Core cannot reuse those sessions. A separate migration/retention decision is needed if legacy transcript privacy must be tightened. |
| Prompt injection or tag breakout | User question/history/evidence are marked untrusted; `wrap_untrusted` HTML-escapes `<`, `>`, quotes; stored history is sanitized and bounded; roles are constrained to user/assistant; current evidence overrides prior statements. | Delimiter escaping is defense in depth, not a semantic security proof. Tool output and curated knowledge remain untrusted data. Continue adding attack cases as new sources are integrated. |
| Model-selected arbitrary tool, SQL or resource | Planner uses deterministic server rules; tool names must be registered and in the server-created allowlist; every tool validates permissions, Pydantic input/output, timeout and size. No arbitrary SQL/network/filesystem/code tool exists. | Current deterministic intent matching is rule-based and can misclassify ambiguous natural language; unavailable/clarification states should be reviewed as the intent catalog expands. |
| Unauthorized write or external action | AI Core is read-only. Any `CONTROLLED_ACTION` or non-`none` side effect is rejected before handler execution. No mutating tool is registered. | Explicit confirmation workflow, idempotency and action audit must be implemented and reviewed separately before any write tool is added. |
| Unbounded cost/resource use | Question ≤2,000 chars, context domains ≤8, transcript query ≤12 messages, evidence ≤16 KB, 3 sequential steps, 50-second tool timeout, 64 KB tool output, shared per-user rate limit, existing bridge timeout/circuit/concurrency controls. | Rate limiter is process-local and uses the existing auth limit (default 10/minute). Deployments with multiple replicas need a shared limiter, dedicated AI quotas and monitoring. Provider can still incur cost for two-step/future workflows; no pricing is integrated. |
| False citations or unsupported numeric claims | Existing structured parse and citation allowlist; core requires inline citation on each factual sentence; second numeric validator checks cited section and same-unit values; general numeric guard now rejects incompatible dimensions and uses explicit conversions. | Label membership and numeric compatibility do not prove semantic entailment. Human review and domain-owner benchmark data are still required; do not treat model prose as a diagnosis, prediction or decision. |
| Trace leaks prompt/farm data | Trace stores IDs, selected domains, hash of selected evidence, source references, tool metadata, validation codes, usage and timing; raw question/answer/evidence values/provider secret are omitted. Provider exceptions are normalized in route traces/logs. | Transcript table intentionally stores raw user/assistant messages for conversation functionality. Trace table still contains user/org/field/session identifiers and can reveal source IDs. Restrict DB/operator access and define deletion/retention policy. No trace UI is exposed here. |
| Stale/misleading evidence | Each evidence item carries source IDs, periods, quality metadata and limitations where available; data gaps are explicit; vegetation evidence retains cloud/freshness/quality fields. | Domain source freshness semantics vary. Existing data quality is not independently re-run or guaranteed by AI Core. |
| Prompt/evidence exfiltration through LLM | Existing service-to-service bridge owns provider URL/credential; no secret is accepted or returned by the AI API; trace omits raw content. | The current bridge/provider may transmit selected question, conversation and evidence outside the application boundary. Provider retention, residency, DPA and model-training policy must be reviewed by deployment owners; this code does not perform that legal/vendor review. |
| Silent transcript retention | Core access expires after default 365 days of inactivity, configurable to 0 to disable. | Expiry only blocks Core access; it does not delete `ai_advisor_messages`. A separate data-retention/deletion job and user-facing policy are not implemented. |

## Safe logging and trace policy

Never put user question, model answer, complete evidence pack, farm name, boundary, bridge token, credentials, or model prompt into log fields, metric labels, or the trace table. The append-only trace can contain request/trace ID, user/org/field/conversation IDs, intent, provider/model, prompt version, selected domain names, evidence fingerprint/source IDs, planned step count, step category/status/duration/output size/error code, validation error codes, optional provider-reported tokens, latency, final status and normalized error category. The trace is for restricted operators; no customer-facing trace query route is provided.

## Release gates

1. Apply migration `0024_ai_core_orchestration` only to a reviewed, backed-up target environment.
2. Run all unit, integration and full suites only against a disposable PostGIS database; the repository autouse integration fixture truncates public tables.
3. Execute the same-organization cross-user session test, invalid/unauthorized field test, rate-limit envelope/`Retry-After` test, provider failure, invalid evidence and multi-step failure trace tests.
4. Review the configured provider's data processing/retention and shared service authentication configuration.
5. Replace process-local rate limiting before horizontal scaling and define transcript deletion/retention operations.
6. Obtain agronomist review and a source-backed benchmark before exposing any prescription, suitability, risk rank or forecast.
# CropTwist AI Core API Contracts

**Status:** Current source-level contract snapshot; not a live-service or release-verification statement. Final test and integration counts are maintained in [`MASTER_INTEGRATION_ENGINEERING_REPORT.md`](../../../../docs/implementation/MASTER_INTEGRATION_ENGINEERING_REPORT.md).

- **Base path:** `/api/v1/ai`
- **Authentication:** existing authenticated `get_principal` dependency (Bearer token or supported existing auth cookie). Routes below are authenticated.
- **Content type:** `application/json`, except `/requests/stream`, which returns `text/event-stream`.
- **Strictness:** request bodies use `extra="forbid"`; identity, tenant, provider, model, tools, permissions, and trace identity are server-controlled.

## `POST /requests` and `POST /requests/stream`

Both endpoints accept the same `AIRequest` and run the same authorization, planning, tool, response-validation, transcript, and trace lifecycle. The non-stream endpoint returns `AIResponse` JSON. The SSE endpoint finishes execution and commits before response headers/body are sent, then returns `meta`, zero or more `chunk`, and `done` events. Chunks are at most 160 characters and split an already-validated complete answer; this is not first-token live model streaming. If authorization or execution fails before streaming starts, normal HTTP error handling applies.

### Request

```json
{
  "question": "Explain the latest stored soil indicators for this field",
  "field_id": "2e6ea5de-6e84-4d07-a076-bc3fe7fd6106",
  "conversation_id": null,
  "locale": "en",
  "context_domains": ["soil", "management"]
}
```

| Field | Type | Requirements |
|---|---|---|
| `question` | string | Required, whitespace-trimmed, nonblank, 1–2,000 characters. Treated as untrusted text. |
| `field_id` | UUID or null | Optional in schema; required for supported field explanations. Authorize server-side before evidence access. |
| `conversation_id` | UUID or null | Optional; must identify a non-expired Core conversation owned by the user and associated with the same currently authorized field. |
| `locale` | `en` or `ar` | Defaults to `en`. |
| `context_domains` | array of enum strings | Up to eight unique values from `field`, `climate`, `water`, `soil`, `rotation`, `management`, `vegetation`, `data_gaps`. Empty means planner selection; a supplied allowlisted list can narrow evidence. Field profile and data-gap metadata are retained by evidence selection. |

`user_id`, `organization_id`, `farm_id`, role/permissions, provider/model, tool names, tenant scope, prompt version, request/trace IDs, and tool arguments are not accepted as authoritative body fields. A field selector is not an authorization grant.

### Response

`AIResponse` contains `request_id`, `conversation_id`, `intent`, `status`, optional `answer`, typed `verified_facts`, `derived_results`, `predictions`, `recommendations`, `general_knowledge`, `assumptions`, `evidence`, `limitations`, `missing_information`, `follow_up_suggestions`, `plan`, and `execution`.

Current field explanations use `plan.required_tools` and `plan.tool_calls` in this exact order:

```json
{
  "required_tools": ["collect_field_evidence", "synthesize_field_answer"],
  "tool_calls": [
    {"name": "collect_field_evidence", "arguments": {}, "context_domains": ["soil", "management", "data_gaps"], "depends_on": []},
    {"name": "synthesize_field_answer", "arguments": {}, "context_domains": ["soil", "management", "data_gaps"], "depends_on": [0]}
  ]
}
```

`answer_field_question` remains in the registry but is not used by current deterministic planner output. The response status is one of `answered`, `partial`, `clarification_required`, `unavailable`, or `failed`. Plan availability is `available`, `partial`, `planned`, or `unavailable`; a `planned` or `unavailable` capability is not executable. For the current Core, prediction, recommendation, and general-knowledge result arrays remain empty.

`execution` contains the trace/request IDs, status, provider/model when known, optional token usage, provider attempts (each with provider/model/status/latency and normalized category), total latency, planned step count, tool invocation metadata, degraded flag, and normalized error category. Missing usage is `null`, not an inferred estimate. A provider failure or unavailable privacy configuration does not create a fabricated provider/model result.

Each `EvidenceItem` is a provenance wrapper: stable `evidence_id`, capability, field entity, result type, claim class, source-derived value/unit, observation period, source references, optional spatial/processing metadata and source-provided quality/confidence, limitations, and `available`/`partial`/`insufficient`/`unavailable` status. A missing-data entry uses `claim_class="missing_information"`; a gap is not a zero measurement.

## Intent, availability, and execution semantics

- `clarification_required`: required field or intent is missing; no tool executes.
- `unavailable`: the requested capability is not registered; no prediction, recommendation, report, or action is fabricated.
- `partial`: only stored evidence is explained or a deterministic fallback/notice is returned; limits are included.
- `answered`: a provider-generated narrative passed validation for a supported path.
- `failed`: a registered tool/workflow failed; error details are normalized.

Crop suitability, cross-field risk ranking, scenario simulation, and report integration are planned. Agricultural recommendation/prescription, yield/other prediction, agricultural-knowledge answering, and platform actions are unavailable. No `planned` descriptor is a callable API operation.

## Discovery and provider status

- `GET /capabilities` returns public `CapabilityDescriptor` records: status, request/response schemas, required context/permissions, evidence requirements, confidence/freshness semantics, error contract, and limitations.
- `GET /tools` returns actually registered tool definitions and input/output schemas, timeout/output bounds, normalized error codes, permissions, category, side-effect classification, and confirmation flag.
- `GET /providers` returns environment-derived provider order/configuration, model IDs, policy gates, circuit and declared adapter capabilities. It makes no provider request and returns `live_connectivity_verified: false`. API credentials are never returned.
- `GET /operations/status` returns a seven-day aggregate for the authenticated user's last 500 traces: outcome counts, average/median latency, provider attempts, and configuration-only provider state. Cost is `null` because live provider pricing is not configured.
- `GET /knowledge/status?organization_id=<uuid>` is organization-manager scoped and reports only that organization's document/chunk counts, registered embedding adapters, source/query sharing gates, `semantic_retrieval_available`, and `semantic_retrieval_blockers`. It does not expose source text or cross-tenant counts and does not establish that an approved corpus or live provider connectivity exists.

The default application chain is Gemini `gemini-3.6-flash` → Groq `openai/gpt-oss-120b` → OpenRouter `nvidia/nemotron-3.5-super-vl:free`. Provider keys, model IDs/order, and data-sharing gates are set through `CROPTWIST_` environment settings only; none are accepted in API requests or stored as client-managed preferences. The settings are `CROPTWIST_LLM_PROVIDER_ORDER` (default `gemini,groq,openrouter`), `CROPTWIST_GEMINI_API_KEY` / `CROPTWIST_GEMINI_MODEL`, `CROPTWIST_GROQ_API_KEY` / `CROPTWIST_GROQ_MODEL`, and `CROPTWIST_OPENROUTER_API_KEY` / `CROPTWIST_OPENROUTER_MODEL`. The remote field-data gate defaults off (`CROPTWIST_AI_ALLOW_FIELD_DATA_TO_PROVIDERS=false`); OpenRouter additionally requires `CROPTWIST_OPENROUTER_ALLOW_FIELD_DATA=true`. Keys are not returned by `/providers`; a configured provider is still live-unverified.

The adapters use Gemini `generateContent` at `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with the `x-goog-api-key` header; Groq Chat Completions at `https://api.groq.com/openai/v1/chat/completions`; and OpenRouter Chat Completions at `https://openrouter.ai/api/v1/chat/completions`. Gemini sends JSON-schema configuration through `generationConfig`; Groq uses strict `response_format.json_schema`; OpenRouter requests `provider.require_parameters=true` when schema output is requested, but that does not guarantee the selected model endpoint supports it. The AI Core does not expose provider credentials, native tool selection, or raw provider SSE to clients.

## Conversations

Omit `conversation_id` to create a new private field conversation; the response returns its UUID. Core stamps `owner_user_id` from the authenticated principal. Model context uses the configured recent-turn limit (default six turns, up to 12 messages at six turns), and history is sanitized and treated as untrusted. `CROPTWIST_AI_CONVERSATION_RETENTION_DAYS` defaults to 365; `0` disables access expiry and cleanup for conversations.

- `GET /conversations?field_id=<uuid>`: lists up to 50 unexpired conversations owned by this user after current field authorization.
- `GET /conversations/{conversation_id}/messages`: returns up to 80 messages for the owned conversation after field authorization; messages may include trace ID, evidence, engine, and creation time.
- `DELETE /conversations/{conversation_id}`: deletes an owned conversation and its cascading messages.

Missing, cross-field, non-owned, legacy owner-null, and expired Core conversations return the same 404 on request reuse. Legacy advisor routes retain their historical behavior; Core does not reuse owner-null sessions.

## Feedback contracts

`POST /feedback` requires `trace_id`, `rating` (`helpful` or `needs_improvement`), and affirmative `quality_review_consent: true`; it optionally accepts lifecycle state (`accepted` default, `rejected`, `modified`, `implemented`, `outcome_reported`), category, correction, outcome, and comment. `outcome_reported` requires an outcome. The trace must belong to the submitting user, with organization membership and field authorization rechecked. Feedback is explicitly consented and never silently added to automatic model training.

`GET /feedback` lists only the caller's unexpired feedback; `PATCH /feedback/{feedback_id}/lifecycle` permits owner-scoped lifecycle transitions; `DELETE /feedback/{feedback_id}` deletes only the caller's row. Lifecycle state updates do not require manager-only access. Any reported result carries `outcome_verification_label="unverified_user_reported"`; user reports are not agronomic verification. Consent version is currently `ai-feedback-v1`.

## Knowledge APIs

Knowledge routes are organization-manager scoped. `POST /knowledge/documents` accepts `text/plain` or `text/markdown` plus source, publisher, jurisdiction, language, crop/topic, version, license/restrictions, and mandatory `rights_confirmed: true`; ingestion stores text chunks as pending. `POST /knowledge/documents/{document_id}/embed` requires an explicitly registered embedding adapter and the separate `CROPTWIST_AI_KNOWLEDGE_ALLOW_DOCUMENTS_TO_EMBEDDING_PROVIDER` gate. `POST /knowledge/search` requires the query-sharing gate `CROPTWIST_AI_KNOWLEDGE_ALLOW_QUERIES_TO_EMBEDDING_PROVIDER`, an embedding adapter, and organization scoping. Search uses bounded exact cosine over same-organization, same-provider/model, same-dimension and fresh vectors (at most 500 candidates); absent configuration returns unavailable rather than inventing embeddings, lexical semantic matches, or citations. `GET /knowledge/status` returns `semantic_retrieval_available: true` only when a registered provider/model has a ready, fresh, dimension-valid vector in that organization and both document-embedding and query-embedding sharing gates are enabled. Otherwise, `semantic_retrieval_blockers` contains one or more stable codes: `embedding_provider_unavailable`, `no_compatible_ready_vector`, `document_embedding_sharing_disabled`, and `query_embedding_sharing_disabled`. The array is empty when retrieval is ready; readiness evaluation does not expose vector contents or source text. `DELETE /knowledge/documents/{document_id}?organization_id=<uuid>` deletes an organization source.

The embedding-provider registry is empty by default and the Core advisor does not yet retrieve this knowledge store. Rights attestation is required at ingestion, but it does not imply an approved global corpus or legal clearance beyond the submitter's attestation.

## Errors and limits

The common API error envelope is:

```json
{"error":{"code":"RATE_LIMITED","message":"Too many requests — slow down and try again shortly.","details":[{"retry_after_seconds":12}],"request_id":"req-7a2b"}}
```

Expected status classes include `401` unauthenticated, `403` policy/membership denied, `404` field/conversation/trace not found or not visible, `422` invalid contract, and `429` throttled with `Retry-After`; unexpected internal failures are normalized. Provider/vendor bodies and secrets are not exposed as raw error text.

AI Core, existing advisor/insights, and LLM-backed recommendation refresh paths use the generic authenticated-user sliding-window limiter (default 10/minute from auth settings). Its store is process-local, bounded to 10,000 active subjects, and prunes expired entries; it is not distributed. Public API-key traffic has its own PostgreSQL-backed budget/rate path and is separate from this limiter. Tool/evidence bounds include 2,000-character questions, at most eight requested context domains, 16 KB selected evidence, at most three workflow steps, 32 KB tool input, 60-second registry-wide per-tool maximum, and at most 64 KB per tool output.

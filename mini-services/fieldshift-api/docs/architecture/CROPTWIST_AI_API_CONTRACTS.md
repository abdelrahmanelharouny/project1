# CropTwist AI Core API Contracts

- **Base path:** `/api/v1/ai`
- **Authentication:** existing `get_principal` (Bearer token or existing supported auth cookie). All endpoints are authenticated.
- **Content type:** `application/json`; no streaming endpoint is provided.

## `POST /requests`

Submits one explanatory request to the AI lifecycle.

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
| `question` | string | Required, nonblank, 1–2,000 characters. User text is untrusted. |
| `field_id` | UUID or null | Optional in schema; required for supported field-scoped explanation. Authorized server-side before evidence reads. |
| `conversation_id` | UUID or null | Optional; must refer to a non-expired Core session owned by this user and tied to the same currently authorized field. |
| `locale` | `en` or `ar` | Defaults to `en`. |
| `context_domains` | array of enum strings | Up to eight unique values among `field`, `climate`, `water`, `soil`, `rotation`, `management`, `vegetation`, `data_gaps`. Defaults to planner-selected context. The server always includes field profile and data-gap metadata. |

`user_id`, `organization_id`, `farm_id`, permissions, provider/model, tool names, tenant scope, prompt version, request/trace IDs and tool arguments are not accepted as authoritative request-body fields. Extra fields are rejected. The server derives actor, organization, role and field/farm scope from the authenticated principal and database.

### Response

```json
{
  "request_id": "req-7a2b",
  "conversation_id": "a30febbf-2fb0-4ded-884c-17c38a445a82",
  "intent": "soil_intelligence",
  "status": "partial",
  "answer": "The stored soil result is available ... [evidence: soil].",
  "verified_facts": [],
  "derived_results": [],
  "predictions": [],
  "recommendations": [],
  "general_knowledge": [],
  "assumptions": [],
  "evidence": [],
  "limitations": ["The AI Core explains stored soil outputs only."],
  "missing_information": ["water"],
  "follow_up_suggestions": [],
  "plan": {
    "intent": "soil_intelligence",
    "required_entities": ["field_id"],
    "required_context": ["field", "soil", "management", "data_gaps"],
    "required_tools": ["answer_field_question"],
    "tool_calls": [{"name": "answer_field_question", "arguments": {}, "context_domains": ["soil", "management", "data_gaps"], "depends_on": []}],
    "missing_information": [],
    "permission_scope": ["field.read", "field.analysis.read"],
    "clarification_needed": false,
    "availability": "partial",
    "expected_output": "grounded_explanation",
    "limitations": []
  },
  "execution": {
    "trace_id": "a2c38c2c-90ba-4ccc-a122-d18349953e10",
    "request_id": "req-7a2b",
    "status": "partial",
    "provider": "legacy-llm-bridge",
    "model": null,
    "token_usage": {"input_tokens": null, "output_tokens": null, "total_tokens": null},
    "latency_ms": 841,
    "planned_steps": 1,
    "tools": [{
      "name": "answer_field_question",
      "category": "analytical",
      "side_effect": "none",
      "status": "succeeded",
      "duration_ms": 825,
      "output_bytes": 1320,
      "error_code": null
    }],
    "degraded": false,
    "error_category": null
  }
}
```

The example is illustrative; IDs, evidence arrays and model details vary. Each `EvidenceItem` has `evidence_id`, capability, entity scope/ID, result type, `claim_class`, domain-specific `value`, unit, observation period, source references, spatial resolution/processing version when available, quality flags, optional model/recommendation confidence, limitations and `available`/`partial`/`insufficient`/`unavailable` status. Missing-data entries use `claim_class="missing_information"`; a gap is not a zero value. This provider currently reports no token usage or calibrated confidence, so those fields are `null`.

### Status and intent values

`status`: `answered`, `partial`, `clarification_required`, `unavailable`, `failed`. `availability` in the plan is `available`, `partial`, `planned`, or `unavailable`. `planned` and `unavailable` are never executable by themselves. The intent enum distinguishes agricultural knowledge, farm/field questions, field analysis, satellite/soil/water/climate/vegetation, stress/anomaly, suitability, rotation, agricultural recommendation, risk, scenario, predictive analysis, report, platform operation and ambiguity.

- `clarification_required`: a field/resource or intent is missing; no model tool is called.
- `unavailable`: no registered capability supports the request; no prediction/recommendation/action is fabricated.
- `partial`: an existing stored output can be explained, or a deterministic fallback was used; limitations are explicit.
- `failed`: a registered tool failed. `execution.error_category` is a safe code, not an exception string.

### Conversation behavior

Omit `conversation_id` to start a new private field conversation. The response returns its UUID for reuse. The authenticated user is stamped as owner. History is fetched in chronological order with SQL capped to the latest six turns (12 user/assistant messages), then sanitized and treated as untrusted. The service uses `updated_at` for a default 365-day inactivity access expiry; `CROPTWIST_AI_CONVERSATION_RETENTION_DAYS=0` disables expiry. Expiry does not delete transcript rows.

A missing, cross-field, non-owned, legacy-unowned or expired Core conversation returns the same 404. Existing legacy advisor sessions/messages retain the legacy field-scope compatibility behavior; new Core sessions are owner-private. No separate AI Core `GET history` endpoint is added.

## Discovery endpoints

- `GET /capabilities` returns `CapabilityDescriptor` records with status, required context/permissions, evidence requirements, confidence/freshness semantics, schemas, error contract and limitations.
- `GET /tools` returns only actual registered tool definitions and their input/output JSON Schemas, categories, side effects, permission requirements, timeout/output ceiling, normalized error codes and confirmation flag. Planned capabilities do not appear as tools.

## Errors

All HTTP errors use the existing envelope:

```json
{"error":{"code":"RATE_LIMITED","message":"Too many requests — slow down and try again shortly.","details":[{"retry_after_seconds":12}],"request_id":"req-7a2b"}}
```

Common statuses: `401` unauthenticated, `403` field/organization membership denied, `404` field or conversation missing/unauthorized, `422` malformed/unknown/duplicate inputs, `429` shared rate limit with `Retry-After`, and normalized `500` for unexpected backend failures. Tool/provider failure details are not exposed as raw exception text; registered tool failures are represented in the typed execution result when the lifecycle can return a trace.

## Limits and operational notes

The new gateway and existing advisor, insights, and LLM-backed recommendation refresh paths share the existing in-process, one-minute `settings.auth_rate_limit_per_minute` limiter (default 10 requests per key). The key is the authenticated user ID. This is not a production AI quota: the store is process-local and must be replaced behind the same limiter seam for multi-replica deployments. Prompt question is capped at 2,000 characters; selected evidence at 16 KB; history at six turns; workflow at three steps; per-tool output at 64 KB. The Core currently uses the existing bridge; no provider selection, streaming, pricing estimate or native model tool-calling endpoint is exposed.

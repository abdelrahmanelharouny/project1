# llm-bridge — z-ai LLM HTTP bridge for CropTwist

Tiny Bun microservice exposing the JS-only `z-ai-web-dev-sdk` chat LLM over HTTP so the Python FastAPI backend (`mini-services/fieldshift-api`) can use it.
Port: `127.0.0.1:3035` (localhost only). Endpoints: `POST /chat` — body `{"messages":[{"role","content"},...],"temperature?","max_tokens?"}` → `{"content","model"}`; `GET /health` → `{"ok","ready","in_flight","uptime_s","auth_required","daily_requests"}`; `GET /metrics` → cumulative + per-UTC-day counters, latency percentiles.
Guardrails: 400 invalid body, 401 missing/invalid token (when auth is on), 413 when total message content exceeds 60000 chars, 429 at ≥10 in-flight requests or when a daily budget is exhausted, 504 if the completion exceeds 90s, 502 if the SDK throws; messages pass through unmodified and `thinking` is always disabled.
The backend calls `http://127.0.0.1:3035/chat` for LLM-backed features and treats this service as optional (non-200 → degrade gracefully).
Run: `bun install && bun run dev` (auto-reload) or `bun run start`; the orchestrator starts it — do not keep a manual instance running.

## A9 security & resource controls (P1)

- **Service-to-service auth**: set `BRIDGE_TOKEN` in the bridge environment and
  `CROPTWIST_LLM_BRIDGE_TOKEN` (same value) in the backend `.env`. The backend
  then sends `X-Bridge-Token` on every call; the bridge compares it in constant
  time and returns 401 on mismatch. With `BRIDGE_TOKEN` unset the bridge allows
  local callers only (it binds 127.0.0.1, so it is not publicly reachable) and
  `/health` reports `auth_required: false` — keep this mode for local dev.
  Never hardcode credentials in either service.
- **Resource controls**: request-body cap (1 MiB), total message content cap
  (60k chars), per-request completion timeout (90 s), in-flight cap (10),
  server-side `max_tokens` cap (4000), and UTC-day budgets via
  `BRIDGE_DAILY_REQUEST_BUDGET` / `BRIDGE_DAILY_TOKEN_BUDGET` (requests;
  token counts use SDK usage data when reported, otherwise a conservative
  chars/4 estimate). Budget exhaustion returns 429 with a structured error.
- **Observability**: `GET /metrics` exposes request/error counters (per status
  class), token counters, `latency_ms_p50`/`latency_ms_p95`, in-flight count
  and the active UTC day. The backend mirrors these in
  `app/intelligence/metrics.py` (bridge latency, error rate, circuit state).

## Streaming: intentionally NOT implemented

Citation validation (A6) and numeric-consistency checks (A7) must validate the
COMPLETE model response against the evidence pack before anything reaches the
user. A streamed partial response would let unvalidated text (possibly with
fabricated citations or unsupported numbers) render directly. We therefore
keep the validated-response flow: full completion → schema validation →
citation check → numeric check → (one constrained regeneration on failure) →
deterministic fallback. Revisit only if a server-side validation-gated
streaming proxy is built; client-side streaming that bypasses validation is
out of the question for this platform.

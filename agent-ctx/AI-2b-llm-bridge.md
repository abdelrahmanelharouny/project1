# Task AI-2b — llm-bridge microservice (z-ai LLM → HTTP for FastAPI backend)

Agent: llm-bridge (task ID AI-2b)
Date: 2026-02-14
Status: ✅ Complete — deps installed, strict tsc clean, /health 200, real /chat 200 (`{"content":"BRIDGE_OK","model":"glm-4-plus"}`, 389ms). No processes left running.

## Files created (all inside `mini-services/llm-bridge/` only)

| File | Purpose |
|---|---|
| `package.json` | name `llm-bridge`, private, `"type": "module"`, dep `z-ai-web-dev-sdk@^0.0.18`, devDep `@types/bun@^1.2.0` (resolved 1.4.4, for strict typecheck), scripts `dev: bun --hot index.ts` / `start: bun index.ts`. |
| `index.ts` | Bun.serve on hardcoded `127.0.0.1:3035`. `POST /chat` (validate → `ZAI.create()` → `chat.completions.create({messages, thinking:{type:'disabled'}, temperature?, max_tokens?})` → `{content, model}`); `GET /health` (`{ok, in_flight, uptime_s}`). |
| `README.md` | 5 lines: purpose, port, endpoints, guardrails, how the backend uses it, run instructions. |

## API contract (what the Python backend can rely on)

- `POST /chat` body `{"messages":[{"role","content"},...],"temperature?","max_tokens?"}` → `200 {"content": string, "model": string|null}`; errors always `{"error": string}` with:
  - `400` invalid JSON / body not object / `messages` empty-or-shape violations (role & content must be strings) / bad optional `temperature` (number) or `max_tokens` (positive int)
  - `413` total message content > 60000 chars
  - `429` ≥10 requests already in flight
  - `504` completion took >90s
  - `502` SDK threw (error message passed through verbatim)
  - `404`/`405` for other paths/methods; `500` JSON on unexpected throws
- Messages are passed to the SDK **exactly as received** (no role transformation); `thinking: {type:'disabled'}` always. One log line per request: `[llm-bridge] POST /chat 200 389ms`.

## Solidity details (deviations / additions beyond bare spec)

- `idleTimeout: 120s` on Bun.serve (default is 10s — would reap connections during long LLM calls; Bun max 255). `maxRequestBodySize: 1 MiB`.
- Timeout implemented with resolve-with-sentinel promise (never rejects → no unhandled rejection after losing the race); SDK promise rejection is always consumed via a settled-mapping promise, so 504-return-early can't crash the process. In-flight counter decrements when the HTTP response is sent (timed-out SDK calls finish in background).
- Graceful SIGTERM/SIGINT shutdown (`server.stop(true)`), `unhandledRejection` logger, belt-and-braces `error()` handler returning JSON 500.
- Optional `temperature`/`max_tokens` from the body are validated and forwarded to the SDK (spec's snippet showed only `messages`+`thinking`; forwarding is the obvious intent of the documented body fields — Python side can simply omit them if ever problematic).
- Role values are validated as strings only, not enum-restricted (spec validation wording: "role+content strings"; keeps bridge forward-compatible).

## Verification (each in a single bash invocation; nothing persisted)

- `bun install` → `+ z-ai-web-dev-sdk@0.0.18, + @types/bun@1.4.4, 6 packages installed`.
- `bunx tsc --noEmit --strict ... --types bun index.ts` → **TYPECHECK_OK**.
- `/health` smoke (task's exact command) → `{"ok":true,"in_flight":0,"uptime_s":1}`.
- Real `/chat` smoke → HTTP 200 `{"content":"BRIDGE_OK","model":"glm-4-plus"}` in 389ms; negative tests: empty `messages` → 400, non-JSON body → 400.
- Post-test: `pgrep llm-bridge` → none; port 3035 free. Root project / FastAPI backend / frontend untouched; Next dev.log unaffected.

## Notes for next agents

- Python side should call `http://127.0.0.1:3035/chat` with a client timeout > 90s (bridge answers 504 at 90s) and treat any non-200 as "LLM unavailable" degradation.
- To start it like the orchestrator does: `cd mini-services/llm-bridge && bun run dev` (auto-reload) or `bun run start`.
- If the SDK env ever changes (ZAI config), only `index.ts` needs review — no other coupling.

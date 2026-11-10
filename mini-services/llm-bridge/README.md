# llm-bridge — z-ai LLM HTTP bridge for CropTwist

Tiny Bun microservice exposing the JS-only `z-ai-web-dev-sdk` chat LLM over HTTP so the Python FastAPI backend (`mini-services/fieldshift-api`) can use it.
Port: `127.0.0.1:3035` (localhost only). Endpoints: `POST /chat` — body `{"messages":[{"role","content"},...],"temperature?","max_tokens?"}` → `{"content","model"}`; `GET /health` → `{"ok","in_flight","uptime_s"}`.
Guardrails: 400 invalid body, 413 when total message content exceeds 60000 chars, 429 at ≥10 in-flight requests, 504 if the completion exceeds 90s, 502 if the SDK throws; messages pass through unmodified and `thinking` is always disabled.
The backend calls `http://127.0.0.1:3035/chat` for LLM-backed features and treats this service as optional (non-200 → degrade gracefully).
Run: `bun install && bun run dev` (auto-reload) or `bun run start`; the orchestrator starts it — do not keep a manual instance running.

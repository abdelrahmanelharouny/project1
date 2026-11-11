/**
 * llm-bridge — tiny Bun HTTP bridge exposing the JS-only `z-ai-web-dev-sdk`
 * LLM to the CropTwist FastAPI (Python) backend.
 *
 * Endpoints:
 *   POST /chat    { messages: [{role, content}, ...], temperature?, max_tokens? }
 *              -> 200 { content, model } | 400 | 401 | 413 | 429 | 502 | 504 { error }
 *   GET  /health -> 200 { ok, ready, in_flight, uptime_s, auth_required }
 *   GET  /metrics -> 200 { requests_total, errors_total, tokens_in_total,
 *                          tokens_out_total, daily_requests, daily_tokens_in,
 *                          daily_tokens_out, latency_ms_p50, latency_ms_p95,
 *                          in_flight, uptime_s }
 *
 * A9 security & resource controls:
 * - Service-to-service auth: when BRIDGE_TOKEN is set, every /chat call must
 *   present header `X-Bridge-Token` (constant-time compare, 401 otherwise).
 *   The token is read from the environment only — never hardcoded. When unset
 *   the server allows local callers (it binds 127.0.0.1 only), and /health
 *   reports auth_required:false so deployments can verify the setting.
 * - Resource controls: request-body cap, total content cap, per-request
 *   completion timeout, in-flight concurrency cap, max_tokens cap, and a
 *   UTC-day budget (BRIDGE_DAILY_REQUEST_BUDGET / BRIDGE_DAILY_TOKEN_BUDGET,
 *   request-based token estimate when the SDK reports no usage) that returns
 *   429 with a structured error once exhausted.
 * - Metrics: cumulative + per-UTC-day counters and latency percentiles.
 * - Streaming: intentionally NOT implemented — citation validation and
 *   numeric consistency (A6/A7) require the complete response before anything
 *   reaches the user; partial streaming would bypass validation. Documented
 *   in mini-services/llm-bridge/README.md.
 *
 * Listens on 127.0.0.1:3035. Messages are passed through to the SDK exactly
 * as received (no role transformation); `thinking` is always disabled.
 */
import ZAI from 'z-ai-web-dev-sdk'
import type { CreateChatCompletionBody } from 'z-ai-web-dev-sdk'

const HOSTNAME = '127.0.0.1'
/** Port is env-overridable so auth/budget behavior can be verified on a
 * throwaway instance without touching the main :3035 service. */
const PORT = Number.parseInt(process.env.BRIDGE_PORT ?? '3035', 10) || 3035
const MAX_TOTAL_CONTENT_CHARS = 60_000
const MAX_IN_FLIGHT = 10
const COMPLETION_TIMEOUT_MS = 90_000
/** Bun idle timeout (seconds) — must exceed the completion timeout so long
 * LLM calls don't get the connection reaped mid-request. Bun max is 255. */
const IDLE_TIMEOUT_S = 120
/** Hard cap on raw request body size (bytes). */
const MAX_BODY_BYTES = 1_048_576
/** Server-side cap on requested output tokens (resource control). */
const MAX_ALLOWED_TOKENS = 4000

/** Shared secret; empty disables auth (loopback-only dev deployments). */
const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN ?? ''
/** UTC-day resource budgets (0 disables the respective budget). */
const DAILY_REQUEST_BUDGET = Number.parseInt(process.env.BRIDGE_DAILY_REQUEST_BUDGET ?? '0', 10) || 0
const DAILY_TOKEN_BUDGET = Number.parseInt(process.env.BRIDGE_DAILY_TOKEN_BUDGET ?? '0', 10) || 0
/** Conservative estimate when the SDK reports no usage (≈4 chars/token). */
const CHARS_PER_TOKEN_ESTIMATE = 4

const startedAtMs = Date.now()
let inFlight = 0

type AnyRecord = Record<string, unknown>

// ---------------------------------------------------------------------------
// Metrics + daily budgets
// ---------------------------------------------------------------------------
const metrics = {
  requests_total: 0,
  errors_total: 0,
  errors_401: 0,
  errors_429: 0,
  errors_413: 0,
  errors_502: 0,
  errors_504: 0,
  tokens_in_total: 0,
  tokens_out_total: 0,
  latency_ms: [] as number[],
  day: utcDayKey(),
  daily_requests: 0,
  daily_tokens_in: 0,
  daily_tokens_out: 0,
}

function utcDayKey(): string {
  return new Date().toISOString().slice(0, 10)
}

function rollDayIfNeeded(): void {
  const key = utcDayKey()
  if (key !== metrics.day) {
    metrics.day = key
    metrics.daily_requests = 0
    metrics.daily_tokens_in = 0
    metrics.daily_tokens_out = 0
  }
}

function recordRequest(tokensIn: number, tokensOut: number, latencyMs: number | null, authorized = true): void {
  rollDayIfNeeded()
  metrics.requests_total += 1
  if (authorized) {
    // Budget accounting counts AUTHORIZED requests only: a flood of invalid
    // tokens must not exhaust the day's legitimate capacity (it is still
    // counted in errors_401 for observability).
    metrics.daily_requests += 1
    metrics.tokens_in_total += tokensIn
    metrics.tokens_out_total += tokensOut
    metrics.daily_tokens_in += tokensIn
    metrics.daily_tokens_out += tokensOut
  }
  if (latencyMs !== null) {
    metrics.latency_ms.push(latencyMs)
    if (metrics.latency_ms.length > 2000) metrics.latency_ms.splice(0, 1000)
  }
}

function recordError(status: number): void {
  rollDayIfNeeded()
  metrics.errors_total += 1
  if (status === 401) metrics.errors_401 += 1
  else if (status === 429) metrics.errors_429 += 1
  else if (status === 413) metrics.errors_413 += 1
  else if (status === 502) metrics.errors_502 += 1
  else if (status === 504) metrics.errors_504 += 1
}

function percentile(list: number[], p: number): number {
  if (list.length === 0) return 0
  const sorted = [...list].sort((a, b) => a - b)
  const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))
  return Math.round(sorted[idx])
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function log(method: string, path: string, status: number, ms: number): void {
  console.log(`[llm-bridge] ${method} ${path} ${status} ${ms}ms`)
}

function errText(e: unknown): string {
  if (e instanceof Error && e.message) return e.message
  return String(e)
}

/** Constant-time token comparison (never early-exits on length mismatch). */
function tokenMatches(presented: string | null): boolean {
  if (BRIDGE_TOKEN === '') return true
  if (presented === null || presented.length === 0) return false
  const a = new TextEncoder().encode(presented)
  const b = new TextEncoder().encode(BRIDGE_TOKEN)
  const maxLen = Math.max(a.length, b.length)
  let diff = a.length ^ b.length
  for (let i = 0; i < maxLen; i++) {
    diff |= (a[i] ?? 0) ^ (b[i] ?? 0)
  }
  return diff === 0
}

function authorize(req: Request): boolean {
  if (BRIDGE_TOKEN === '') return true
  return tokenMatches(req.headers.get('x-bridge-token'))
}

type Validation =
  | { ok: true; messages: unknown[] }
  | { ok: false; status: 400 | 413; error: string }

/** Validate the `messages` array. Shapes are returned as-received (no
 * transformation); only string-ness of role/content is enforced. */
function validateMessages(raw: unknown): Validation {
  if (!Array.isArray(raw) || raw.length === 0) {
    return { ok: false, status: 400, error: 'messages must be a non-empty array of {role, content} objects' }
  }
  let totalChars = 0
  for (let i = 0; i < raw.length; i++) {
    const m: unknown = raw[i]
    if (m === null || typeof m !== 'object' || Array.isArray(m)) {
      return { ok: false, status: 400, error: `messages[${i}] must be an object` }
    }
    const { role, content } = m as AnyRecord
    if (typeof role !== 'string') {
      return { ok: false, status: 400, error: `messages[${i}].role must be a string` }
    }
    if (typeof content !== 'string') {
      return { ok: false, status: 400, error: `messages[${i}].content must be a string` }
    }
    totalChars += content.length
  }
  if (totalChars > MAX_TOTAL_CONTENT_CHARS) {
    return {
      ok: false,
      status: 413,
      error: `total message content exceeds ${MAX_TOTAL_CONTENT_CHARS} characters (got ${totalChars})`,
    }
  }
  return { ok: true, messages: raw }
}

// ---------------------------------------------------------------------------
// /chat
// ---------------------------------------------------------------------------
async function handleChat(req: Request): Promise<Response> {
  const t0 = Date.now()
  const respond = (status: number, body: unknown, tokensIn = 0, tokensOut = 0, authorized = true): Response => {
    log('POST', '/chat', status, Date.now() - t0)
    if (status >= 400) recordError(status)
    recordRequest(tokensIn, tokensOut, status === 200 ? Date.now() - t0 : null, authorized)
    return json(body, status)
  }

  if (!authorize(req)) {
    return respond(401, { error: 'missing or invalid X-Bridge-Token header' }, 0, 0, false)
  }

  rollDayIfNeeded()
  if (DAILY_REQUEST_BUDGET > 0 && metrics.daily_requests >= DAILY_REQUEST_BUDGET) {
    return respond(429, { error: `daily request budget exhausted (${DAILY_REQUEST_BUDGET}/UTC day), retry tomorrow` })
  }

  // Concurrency guard: check+increment are adjacent synchronous statements,
  // which is atomic under Bun's single-threaded event loop.
  if (inFlight >= MAX_IN_FLIGHT) {
    return respond(429, { error: `too many in-flight requests (max ${MAX_IN_FLIGHT}), retry later` })
  }
  inFlight++

  try {
    let parsed: unknown
    try {
      parsed = await req.json()
    } catch {
      return respond(400, { error: 'request body must be valid JSON' })
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return respond(400, { error: 'request body must be a JSON object' })
    }
    const body = parsed as AnyRecord

    const messages = validateMessages(body.messages)
    if (!messages.ok) {
      return respond(messages.status, { error: messages.error })
    }
    const inputChars = (messages.messages as AnyRecord[])
      .reduce((sum, m) => sum + (typeof m.content === 'string' ? m.content.length : 0), 0)
    const estimatedIn = Math.ceil(inputChars / CHARS_PER_TOKEN_ESTIMATE)
    if (DAILY_TOKEN_BUDGET > 0 && metrics.daily_tokens_in + estimatedIn > DAILY_TOKEN_BUDGET) {
      return respond(429, { error: `daily token budget exhausted (${DAILY_TOKEN_BUDGET}/UTC day), retry tomorrow` })
    }

    let temperature: number | undefined
    if (body.temperature !== undefined && body.temperature !== null) {
      if (typeof body.temperature !== 'number' || !Number.isFinite(body.temperature)) {
        return respond(400, { error: 'temperature must be a number when provided' })
      }
      temperature = body.temperature
    }

    let maxTokens: number | undefined
    if (body.max_tokens !== undefined && body.max_tokens !== null) {
      if (typeof body.max_tokens !== 'number' || !Number.isInteger(body.max_tokens) || body.max_tokens <= 0) {
        return respond(400, { error: 'max_tokens must be a positive integer when provided' })
      }
      maxTokens = body.max_tokens
      if (maxTokens > MAX_ALLOWED_TOKENS) {
        return respond(400, { error: `max_tokens exceeds the server cap of ${MAX_ALLOWED_TOKENS}` })
      }
    }

    const createBody: CreateChatCompletionBody = {
      // Pass messages through exactly as received — no role transformation.
      messages: messages.messages as CreateChatCompletionBody['messages'],
      thinking: { type: 'disabled' },
    }
    if (temperature !== undefined) createBody.temperature = temperature
    if (maxTokens !== undefined) createBody.max_tokens = maxTokens

    // Timeout uses a resolve-with-sentinel promise (never rejects) so it can
    // never produce an unhandled rejection after losing the race. The sentinel
    // value also doubles as the discriminator when narrowing the race result.
    const TIMEOUT_SENTINEL = '__timeout__'
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeoutP = new Promise<typeof TIMEOUT_SENTINEL>((resolve) => {
      timer = setTimeout(() => resolve(TIMEOUT_SENTINEL), COMPLETION_TIMEOUT_MS)
    })

    const work = (async () => {
      const zai = await ZAI.create()
      return zai.chat.completions.create(createBody)
    })()
    // `settled` maps rejection to a value, so `work` can never surface an
    // unhandled rejection even when the 504 path returns before it settles.
    const settled = work.then(
      (v: unknown) => ({ ok: true as const, v }),
      (e: unknown) => ({ ok: false as const, e }),
    )

    try {
      const raced = await Promise.race([settled, timeoutP])

      if (raced === TIMEOUT_SENTINEL) {
        return respond(504, { error: `LLM completion timed out after ${COMPLETION_TIMEOUT_MS}ms` }, estimatedIn)
      }
      if (!raced.ok) {
        return respond(502, { error: errText(raced.e) }, estimatedIn)
      }

      const completion = raced.v as AnyRecord | null | undefined
      const choices = Array.isArray(completion?.choices) ? (completion?.choices as unknown[]) : []
      const first = (choices[0] ?? null) as AnyRecord | null
      const message = (first?.message ?? null) as AnyRecord | null
      const content = typeof message?.content === 'string' ? message.content : ''
      const model = (completion?.model ?? null) ?? null
      const usage = (completion?.usage ?? null) as AnyRecord | null
      const tokensOut = typeof usage?.completion_tokens === 'number'
        ? usage.completion_tokens
        : Math.ceil(content.length / CHARS_PER_TOKEN_ESTIMATE)
      return respond(200, { content, model }, estimatedIn, tokensOut)
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
  } finally {
    inFlight--
  }
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------
const server = Bun.serve({
  port: PORT,
  hostname: HOSTNAME,
  maxRequestBodySize: MAX_BODY_BYTES,
  idleTimeout: IDLE_TIMEOUT_S,
  async fetch(req): Promise<Response> {
    const t0 = Date.now()
    const url = new URL(req.url)
    const path = url.pathname
    const method = req.method
    try {
      if (path === '/health') {
        if (method !== 'GET') {
          log(method, path, 405, Date.now() - t0)
          return json({ error: 'method not allowed, use GET' }, 405)
        }
        rollDayIfNeeded()
        log(method, path, 200, Date.now() - t0)
        return json({
          ok: true,
          ready: true,
          in_flight: inFlight,
          uptime_s: Math.floor((Date.now() - startedAtMs) / 1000),
          auth_required: BRIDGE_TOKEN !== '',
          day: metrics.day,
          daily_requests: metrics.daily_requests,
        })
      }
      if (path === '/metrics') {
        if (method !== 'GET') {
          log(method, path, 405, Date.now() - t0)
          return json({ error: 'method not allowed, use GET' }, 405)
        }
        log(method, path, 200, Date.now() - t0)
        return json({
          requests_total: metrics.requests_total,
          errors_total: metrics.errors_total,
          errors_401: metrics.errors_401,
          errors_429: metrics.errors_429,
          errors_413: metrics.errors_413,
          errors_502: metrics.errors_502,
          errors_504: metrics.errors_504,
          tokens_in_total: metrics.tokens_in_total,
          tokens_out_total: metrics.tokens_out_total,
          day: metrics.day,
          daily_requests: metrics.daily_requests,
          daily_tokens_in: metrics.daily_tokens_in,
          daily_tokens_out: metrics.daily_tokens_out,
          budgets: {
            daily_requests: DAILY_REQUEST_BUDGET || null,
            daily_tokens: DAILY_TOKEN_BUDGET || null,
          },
          latency_ms_p50: percentile(metrics.latency_ms, 50),
          latency_ms_p95: percentile(metrics.latency_ms, 95),
          in_flight: inFlight,
          uptime_s: Math.floor((Date.now() - startedAtMs) / 1000),
        })
      }
      if (path === '/chat') {
        if (method !== 'POST') {
          log(method, path, 405, Date.now() - t0)
          return json({ error: 'method not allowed, use POST' }, 405)
        }
        return await handleChat(req)
      }
      log(method, path, 404, Date.now() - t0)
      return json({ error: 'not found' }, 404)
    } catch (e) {
      // Belt-and-braces: handleChat already catches everything it can.
      log(method, path, 500, Date.now() - t0)
      return json({ error: errText(e) }, 500)
    }
  },
  error(e): Response {
    console.error(`[llm-bridge] server error: ${errText(e)}`)
    return json({ error: errText(e) }, 500)
  },
})

console.log(`[llm-bridge] listening on http://${HOSTNAME}:${PORT} (auth: ${BRIDGE_TOKEN !== '' ? 'token' : 'disabled — loopback only'})`)

process.on('unhandledRejection', (reason) => {
  console.error(`[llm-bridge] unhandled rejection: ${errText(reason)}`)
})

function shutdown(signal: string): void {
  console.log(`[llm-bridge] received ${signal}, shutting down`)
  server.stop(true) // force-close active connections
  process.exit(0)
}
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))

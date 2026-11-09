/**
 * llm-bridge — tiny Bun HTTP bridge exposing the JS-only `z-ai-web-dev-sdk`
 * LLM to the FieldShift FastAPI (Python) backend.
 *
 * Endpoints:
 *   POST /chat    { messages: [{role, content}, ...], temperature?, max_tokens? }
 *              -> 200 { content, model } | 400 | 413 | 429 | 502 | 504 { error }
 *   GET  /health -> 200 { ok, in_flight, uptime_s }
 *
 * Listens on 127.0.0.1:3035 (hardcoded). Messages are passed through to the
 * SDK exactly as received (no role transformation); `thinking` is always
 * disabled.
 */
import ZAI from 'z-ai-web-dev-sdk'
import type { CreateChatCompletionBody } from 'z-ai-web-dev-sdk'

const HOSTNAME = '127.0.0.1'
const PORT = 3035
const MAX_TOTAL_CONTENT_CHARS = 60_000
const MAX_IN_FLIGHT = 10
const COMPLETION_TIMEOUT_MS = 90_000
/** Bun idle timeout (seconds) — must exceed the completion timeout so long
 * LLM calls don't get the connection reaped mid-request. Bun max is 255. */
const IDLE_TIMEOUT_S = 120
/** Hard cap on raw request body size (bytes). */
const MAX_BODY_BYTES = 1_048_576

const startedAtMs = Date.now()
let inFlight = 0

type AnyRecord = Record<string, unknown>

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

async function handleChat(req: Request): Promise<Response> {
  const t0 = Date.now()
  const respond = (status: number, body: unknown): Response => {
    log('POST', '/chat', status, Date.now() - t0)
    return json(body, status)
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
        return respond(504, { error: `LLM completion timed out after ${COMPLETION_TIMEOUT_MS}ms` })
      }
      if (!raced.ok) {
        return respond(502, { error: errText(raced.e) })
      }

      const completion = raced.v as AnyRecord | null | undefined
      const choices = Array.isArray(completion?.choices) ? (completion?.choices as unknown[]) : []
      const first = (choices[0] ?? null) as AnyRecord | null
      const message = (first?.message ?? null) as AnyRecord | null
      const content = typeof message?.content === 'string' ? message.content : ''
      const model = (completion?.model ?? null) ?? null
      return respond(200, { content, model })
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
  } finally {
    inFlight--
  }
}

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
        log(method, path, 200, Date.now() - t0)
        return json({
          ok: true,
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

console.log(`[llm-bridge] listening on http://${HOSTNAME}:${PORT}`)

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

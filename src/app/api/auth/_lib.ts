/**
 * Shared plumbing for the /api/auth/* route handlers (P1 server-side
 * sessions). These handlers are the ONLY place where session token material
 * is handled on the browser-facing side: they proxy the FastAPI auth
 * endpoints, set HttpOnly cookies, and strip tokens from every payload that
 * goes back to the browser.
 */
import { NextResponse } from 'next/server'

const API_BASE = 'http://127.0.0.1:3030/api/v1'

export const ACCESS_COOKIE = 'fs_token'
export const REFRESH_COOKIE = 'fs_refresh'

const ACCESS_MAX_AGE = 60 * 60 * 12 // backend auth_token_ttl_seconds
const REFRESH_MAX_AGE = 60 * 60 * 24 * 30 // backend auth_refresh_ttl_seconds

export interface BackendErrorShape {
  code?: string
  message?: string
  details?: unknown[]
  request_id?: string
}

/** true when the request arrived over https (behind the gateway/preview). */
export function isSecure(request: Request): boolean {
  const proto = request.headers.get('x-forwarded-proto')
  if (proto) return proto.split(',')[0].trim() === 'https'
  try {
    return new URL(request.url).protocol === 'https:'
  } catch {
    return false
  }
}

function sessionCookieOptions(request: Request) {
  const secure = isSecure(request)
  return {
    httpOnly: true,
    sameSite: secure ? ('none' as const) : ('lax' as const),
    secure,
    path: '/',
  }
}

/** Server-side call to the FastAPI backend (never sees XTransformPort). */
export async function backend<T>(
  path: string,
  init?: RequestInit,
): Promise<{
  ok: boolean
  status: number
  payload: T | null
  error?: BackendErrorShape
}> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      cache: 'no-store',
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    })
    const text = await response.text()
    let payload: unknown = null
    if (text) {
      try {
        payload = JSON.parse(text)
      } catch {
        payload = null
      }
    }
    if (!response.ok) {
      const envelope = payload as { error?: BackendErrorShape } | null
      const error =
        envelope && typeof envelope === 'object' && 'error' in envelope
          ? envelope.error
          : undefined
      return { ok: false, status: response.status, payload: null, error }
    }
    return { ok: true, status: response.status, payload: payload as T }
  } catch {
    return {
      ok: false,
      status: 0,
      payload: null,
      error: { code: 'NETWORK_ERROR', message: 'Could not reach the CropTwist API.' },
    }
  }
}

/** Forward a backend error envelope to the browser with the same status. */
export function errorResponse(
  request: Request,
  status: number,
  error?: BackendErrorShape,
): NextResponse {
  return NextResponse.json(
    {
      error: {
        code: error?.code ?? `HTTP_${status}`,
        message: error?.message ?? 'Request failed.',
        details: error?.details ?? [],
        request_id: error?.request_id,
      },
    },
    { status },
  )
}

/** Set the HttpOnly session cookies on a successful login/refresh response. */
export function setSessionCookies(
  response: NextResponse,
  request: Request,
  session: { token?: string; refresh_token?: string | null },
): NextResponse {
  const base = sessionCookieOptions(request)
  if (session.token) {
    response.cookies.set(ACCESS_COOKIE, session.token, { ...base, maxAge: ACCESS_MAX_AGE })
  }
  if (session.refresh_token) {
    response.cookies.set(REFRESH_COOKIE, session.refresh_token, {
      ...base,
      maxAge: REFRESH_MAX_AGE,
    })
  }
  return response
}

export function clearSessionCookies(response: NextResponse, request: Request): NextResponse {
  const base = sessionCookieOptions(request)
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) {
    response.cookies.set(name, '', { ...base, maxAge: 0 })
  }
  return response
}

/** Strip ALL token material before the payload reaches the browser. */
export function publicSession(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object') return {}
  const {
    token: _token,
    token_type: _tokenType,
    refresh_token: _refreshToken,
    refresh_expires_at: _refreshExpiresAt,
    ...rest
  } = payload as Record<string, unknown>
  return rest
}

/** Backend session payload shape (subset used here). */
export interface BackendSession {
  token: string
  refresh_token?: string | null
  [key: string]: unknown
}

import { NextResponse, type NextRequest } from 'next/server'
import {
  clearSessionCookies,
  errorResponse,
  REFRESH_COOKIE,
  setSessionCookies,
  backend,
  type BackendSession,
} from '../_lib'

/**
 * POST /api/auth/refresh → backend /auth/refresh with the refresh cookie.
 * Rotates BOTH cookies on success (single-flight is handled client-side in
 * lib/api.ts). Any failure clears the session.
 */
export async function POST(request: NextRequest) {
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value
  if (!refresh) {
    return clearSessionCookies(
      errorResponse(request, 401, { code: 'UNAUTHORIZED', message: 'No active session to refresh.' }),
      request,
    )
  }

  const result = await backend<BackendSession>('/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })
  if (!result.ok || !result.payload) {
    const status = result.status === 0 ? 502 : result.status
    const response = errorResponse(request, status, result.error)
    if (status === 401 || status === 423) clearSessionCookies(response, request)
    return response
  }

  const response = NextResponse.json({ refreshed: true })
  return setSessionCookies(response, request, result.payload)
}

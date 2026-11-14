import { NextResponse } from 'next/server'
import { backend, errorResponse, publicSession, setSessionCookies, type BackendSession } from '../_lib'

interface VerificationRequiredPayload {
  status: 'verification_required'
  user?: { email?: unknown }
}

/** POST /api/auth/register → session cookies only for a real session response. */
export async function POST(request: Request) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return errorResponse(request, 400, { code: 'VALIDATION_FAILED', message: 'A JSON body is required.' })
  }

  const result = await backend<BackendSession | VerificationRequiredPayload>('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!result.ok) {
    return errorResponse(request, result.status || 502, result.error)
  }
  if (!result.payload) {
    return errorResponse(request, 502, {
      code: 'INVALID_BACKEND_RESPONSE',
      message: 'Registration returned an empty response.',
    })
  }

  const payload = result.payload as BackendSession & Partial<VerificationRequiredPayload>
  if (payload.status === 'verification_required') {
    const email = (payload.user as { email?: unknown } | undefined)?.email
    if (typeof email !== 'string' || !email) {
      return errorResponse(request, 502, {
        code: 'INVALID_BACKEND_RESPONSE',
        message: 'Registration returned an incomplete verification response.',
      })
    }
    // Return only the pending state and email; never set session cookies or
    // forward arbitrary response fields from the backend.
    return NextResponse.json({ status: 'verification_required', user: { email } }, { status: 202 })
  }

  // A 202 response is never an authenticated session, even if an unexpected
  // backend body happens to resemble one.
  if (result.status === 202) {
    return errorResponse(request, 502, {
      code: 'INVALID_BACKEND_RESPONSE',
      message: 'Registration did not return a session or a verification state.',
    })
  }

  const session = result.payload as BackendSession
  const response = NextResponse.json(publicSession(session))
  return setSessionCookies(response, request, session)
}

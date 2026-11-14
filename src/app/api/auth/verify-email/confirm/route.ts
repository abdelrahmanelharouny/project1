import { NextResponse } from 'next/server'
import { backend, errorResponse } from '../../_lib'

interface VerificationConfirmPayload {
  status?: unknown
}

/** POST /api/auth/verify-email/confirm → confirm the emailed token. */
export async function POST(request: Request) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return errorResponse(request, 400, { code: 'VALIDATION_FAILED', message: 'A JSON body is required.' })
  }

  const token =
    body && typeof body === 'object' && !Array.isArray(body) && typeof (body as { token?: unknown }).token === 'string'
      ? (body as { token: string }).token
      : ''
  if (token.length < 16 || token.length > 200) {
    return errorResponse(request, 400, {
      code: 'VALIDATION_FAILED',
      message: 'A valid verification code is required.',
    })
  }

  const result = await backend<VerificationConfirmPayload>('/auth/verify-email/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!result.ok || !result.payload) {
    // Deliberately use a generic message and no details so an upstream error
    // can never echo the submitted bearer-like verification token.
    return errorResponse(request, result.status || 502, {
      code: result.error?.code ?? 'VERIFICATION_FAILED',
      message: 'Email verification could not be completed.',
      request_id: result.error?.request_id,
    })
  }
  if (result.payload.status !== 'ok') {
    return errorResponse(request, 502, {
      code: 'INVALID_BACKEND_RESPONSE',
      message: 'Email verification returned an unexpected response.',
    })
  }

  // Confirmation returns no session; the client signs in only after this.
  return NextResponse.json({ status: 'ok' }, { status: 200 })
}

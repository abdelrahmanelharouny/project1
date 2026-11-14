import { NextResponse } from 'next/server'
import { backend, errorResponse } from '../../_lib'

interface VerificationRequestPayload {
  status?: unknown
}

/** POST /api/auth/verify-email/request → request or resend a challenge. */
export async function POST(request: Request) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return errorResponse(request, 400, { code: 'VALIDATION_FAILED', message: 'A JSON body is required.' })
  }

  if (!body || typeof body !== 'object' || Array.isArray(body) || typeof (body as { email?: unknown }).email !== 'string') {
    return errorResponse(request, 400, { code: 'VALIDATION_FAILED', message: 'An email address is required.' })
  }

  const email = (body as { email: string }).email
  const result = await backend<VerificationRequestPayload>('/auth/verify-email/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!result.ok || !result.payload) {
    return errorResponse(request, result.status || 502, result.error)
  }

  const status = result.payload.status
  if (status !== 'accepted' && status !== 'queued') {
    return errorResponse(request, 502, {
      code: 'INVALID_BACKEND_RESPONSE',
      message: 'The verification request returned an unexpected response.',
    })
  }

  // The backend may include a plaintext token in development mode. Never
  // forward it (or any arbitrary backend fields) to the browser.
  return NextResponse.json({ status }, { status: 202 })
}

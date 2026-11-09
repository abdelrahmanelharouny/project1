import { NextResponse } from 'next/server'
import { backend, errorResponse, publicSession, setSessionCookies, type BackendSession } from '../_lib'

/** POST /api/auth/login → backend /auth/login + HttpOnly session cookies. */
export async function POST(request: Request) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return errorResponse(request, 400, { code: 'VALIDATION_FAILED', message: 'A JSON body is required.' })
  }

  const result = await backend<BackendSession>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!result.ok || !result.payload) {
    return errorResponse(request, result.status || 502, result.error)
  }

  const response = NextResponse.json(publicSession(result.payload))
  return setSessionCookies(response, request, result.payload)
}

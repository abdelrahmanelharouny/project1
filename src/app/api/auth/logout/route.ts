import { NextResponse, type NextRequest } from 'next/server'
import { ACCESS_COOKIE, backend, clearSessionCookies } from '../_lib'

/** POST /api/auth/logout → revoke the access token server-side + clear cookies. */
export async function POST(request: NextRequest) {
  const token = request.cookies.get(ACCESS_COOKIE)?.value
  if (token) {
    // Best-effort revocation; cookies are cleared regardless.
    await backend('/auth/logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  }
  return clearSessionCookies(NextResponse.json({ ok: true }), request)
}

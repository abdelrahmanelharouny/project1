import { NextResponse } from 'next/server'
import {
  backend,
  errorResponse,
  publicSession,
  setSessionCookies,
  type BackendSession,
} from '../_lib'

interface SeedDemoPayload {
  token?: string
  demo_user?: { email: string; password: string }
  note?: string
  farm_id?: string
  field_ids?: string[]
  [key: string]: unknown
}

/**
 * POST /api/auth/demo → seed the synthetic demo workspace, then sign in as
 * the demo user so the browser receives a FULL session (access + rotating
 * refresh) as HttpOnly cookies. The seed endpoint itself returns an access
 * token only, hence the follow-up login.
 */
export async function POST(request: Request) {
  const seed = await backend<SeedDemoPayload>('/dev/seed-demo', { method: 'POST' })
  if (!seed.ok || !seed.payload) {
    return errorResponse(request, seed.status || 502, seed.error)
  }

  const demo = seed.payload
  const credentials = demo.demo_user ?? {
    email: 'demo@fieldshift.local',
    password: 'fieldshift-demo-2026',
  }
  const login = await backend<BackendSession>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  })
  if (!login.ok || !login.payload) {
    return errorResponse(request, login.status || 502, login.error)
  }

  const response = NextResponse.json({
    ...publicSession(login.payload),
    note: demo.note ?? '',
    farm_id: demo.farm_id ?? '',
    field_ids: demo.field_ids ?? [],
  })
  return setSessionCookies(response, request, login.payload)
}

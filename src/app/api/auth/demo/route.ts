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

/** Public demos must be one explicitly configured, non-administrative tenant. */
export function isSafePublicDemoSession(
  session: BackendSession,
  email: string,
  organizationId: string,
): boolean {
  const user = session.user as { email?: string } | undefined
  const organizations = session.organizations as Array<{ id?: string; role?: string; status?: string }> | undefined
  return user?.email === email && Array.isArray(organizations) && organizations.length === 1 &&
    organizations[0].id === organizationId && organizations[0].status === 'active' &&
    ['operator', 'agronomist', 'analyst', 'viewer'].includes(organizations[0].role ?? '')
}

/**
 * Hosted evaluations use existing authentication with a pre-seeded isolated
 * operator account. Its password stays server-side and no development seed
 * endpoint is exposed. Local development retains the established fixture flow.
 */
export async function POST(request: Request) {
  const email = process.env.CROPTWIST_DEMO_EMAIL
  const password = process.env.CROPTWIST_DEMO_PASSWORD
  const organizationId = process.env.CROPTWIST_DEMO_ORGANIZATION_ID
  const isHosted = process.env.VERCEL === '1' || process.env.VERCEL === 'true'

  if (email && password && organizationId) {
    const login = await backend<BackendSession>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!login.ok || !login.payload) {
      return errorResponse(request, login.status || 502, login.error)
    }
    if (!isSafePublicDemoSession(login.payload, email, organizationId)) {
      return errorResponse(request, 503, {
        code: 'DEMO_UNAVAILABLE',
        message: 'The isolated evaluation account is not available.',
      })
    }
    const response = NextResponse.json({
      ...publicSession(login.payload),
      note: 'Isolated evaluation workspace: all seeded farm observations are SYNTHETIC. External AI and protected satellite acquisition are not verified.',
      farm_id: '',
      field_ids: [],
    })
    return setSessionCookies(response, request, login.payload)
  }

  if (isHosted || email || password || organizationId) {
    return errorResponse(request, 503, {
      code: 'DEMO_UNAVAILABLE',
      message: 'An isolated evaluation account has not been configured.',
    })
  }

  const seed = await backend<SeedDemoPayload>('/dev/seed-demo', { method: 'POST' })
  if (!seed.ok || !seed.payload) {
    return errorResponse(request, seed.status || 502, seed.error)
  }
  const demo = seed.payload
  const credentials = demo.demo_user ?? {
    email: 'demo@croptwist.local',
    password: 'croptwist-demo-2026',
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

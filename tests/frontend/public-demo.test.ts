/// <reference types="bun-types" />
import { afterEach, describe, expect, test } from 'bun:test'
import { POST, isSafePublicDemoSession } from '../../src/app/api/auth/demo/route'
import type { BackendSession } from '../../src/app/api/auth/_lib'

const originalFetch = globalThis.fetch
const keys = ['VERCEL', 'CROPTWIST_API_ORIGIN', 'CROPTWIST_DEMO_EMAIL', 'CROPTWIST_DEMO_PASSWORD', 'CROPTWIST_DEMO_ORGANIZATION_ID'] as const
const originalEnv = Object.fromEntries(keys.map(key => [key, process.env[key]]))
afterEach(() => {
  globalThis.fetch = originalFetch
  for (const key of keys) {
    if (originalEnv[key] === undefined) delete process.env[key]
    else process.env[key] = originalEnv[key]
  }
})

function configured() {
  process.env.VERCEL = '1'
  process.env.CROPTWIST_API_ORIGIN = 'https://api.example.com'
  process.env.CROPTWIST_DEMO_EMAIL = 'reviewer@demo.local'
  process.env.CROPTWIST_DEMO_PASSWORD = 'private-test-demo-password'
  process.env.CROPTWIST_DEMO_ORGANIZATION_ID = 'org-demo'
}
function session(role = 'operator'): BackendSession {
  return {
    token: 'private-access-token', refresh_token: 'private-refresh-token',
    user: { email: 'reviewer@demo.local', display_name: 'Synthetic reviewer' },
    organization: { id: 'org-demo', name: 'Synthetic evaluation' },
    organizations: [{ id: 'org-demo', role, status: 'active' }],
  }
}
const request = () => new Request('https://croptwist.example.com/api/auth/demo', { method: 'POST' })

describe('hosted isolated public demo', () => {
  test('authenticates only the configured operator without invoking development seeding or leaking secrets', async () => {
    configured()
    const calls: string[] = []
    globalThis.fetch = (async (input, init) => {
      calls.push(String(input))
      expect(JSON.parse(String(init?.body))).toEqual({ email: 'reviewer@demo.local', password: 'private-test-demo-password' })
      return Response.json(session())
    }) as unknown as typeof fetch
    const response = await POST(request())
    const body = await response.text()
    expect(response.status).toBe(200)
    expect(calls).toEqual(['https://api.example.com/api/v1/auth/login'])
    expect(body).toContain('SYNTHETIC')
    for (const secret of ['private-test-demo-password', 'private-access-token', 'private-refresh-token']) expect(body).not.toContain(secret)
    expect(response.headers.get('set-cookie')).toContain('HttpOnly')
    expect(response.headers.get('set-cookie')).toContain('Secure')
  })
  test('refuses administrator accounts without setting browser session cookies', async () => {
    configured()
    globalThis.fetch = (async () => Response.json(session('owner'))) as unknown as typeof fetch
    const response = await POST(request())
    expect(response.status).toBe(503)
    expect(response.headers.get('set-cookie')).toBeNull()
    expect(await response.text()).not.toContain('private-access-token')
  })
  test('fails closed on hosted missing or partially configured demo credentials', async () => {
    configured()
    delete process.env.CROPTWIST_DEMO_PASSWORD
    let called = false
    globalThis.fetch = (async () => { called = true; return Response.json({}) }) as unknown as typeof fetch
    const response = await POST(request())
    expect(response.status).toBe(503)
    expect(called).toBe(false)
    expect(response.headers.get('set-cookie')).toBeNull()
  })
  test('rejects mixed tenants, inactive memberships, and mismatched identities', () => {
    expect(isSafePublicDemoSession(session(), 'reviewer@demo.local', 'org-demo')).toBe(true)
    for (const role of ['owner', 'org_admin', 'manager']) expect(isSafePublicDemoSession(session(role), 'reviewer@demo.local', 'org-demo')).toBe(false)
    expect(isSafePublicDemoSession(session(), 'other@demo.local', 'org-demo')).toBe(false)
    expect(isSafePublicDemoSession(session(), 'reviewer@demo.local', 'org-other')).toBe(false)
    expect(isSafePublicDemoSession({ ...session(), organizations: [{ id: 'org-demo', role: 'operator', status: 'suspended' }] }, 'reviewer@demo.local', 'org-demo')).toBe(false)
    expect(isSafePublicDemoSession({ ...session(), organizations: [{ id: 'org-demo', role: 'operator', status: 'active' }, { id: 'private-org', role: 'viewer', status: 'active' }] }, 'reviewer@demo.local', 'org-demo')).toBe(false)
  })
})

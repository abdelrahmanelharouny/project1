import { expect, test } from 'bun:test'
import { NextResponse } from 'next/server'

import { clearSessionCookies, setSessionCookies } from '../../src/app/api/auth/_lib'

function setCookieHeader(response: NextResponse): string {
  return (response.headers.get('set-cookie') ?? '').toLowerCase()
}

test('HTTPS Preview session cookies are HttpOnly, Secure, and SameSite=None', () => {
  const request = new Request('http://localhost:3000/api/auth/login', {
    headers: { 'x-forwarded-proto': 'https' },
  })
  const response = setSessionCookies(NextResponse.json({ ok: true }), request, {
    token: 'test-access-token',
    refresh_token: 'test-refresh-token',
  })
  const header = setCookieHeader(response)

  expect(header).toContain('httponly')
  expect(header).toContain('secure')
  expect(header).toContain('samesite=none')
  expect(header).toContain('fs_token=')
  expect(header).toContain('fs_refresh=')
})

test('plain HTTP local session cookies stay Lax and do not add Secure', () => {
  const request = new Request('http://localhost:3000/api/auth/login')
  const response = setSessionCookies(NextResponse.json({ ok: true }), request, {
    token: 'test-access-token',
    refresh_token: 'test-refresh-token',
  })
  const header = setCookieHeader(response)

  expect(header).toContain('httponly')
  expect(header).toContain('samesite=lax')
  expect(header).not.toContain('secure')
})

test('HTTPS Preview logout clears cookies using the matching Secure SameSite=None attributes', () => {
  const request = new Request('http://localhost:3000/api/auth/logout', {
    headers: { 'x-forwarded-proto': 'https' },
  })
  const response = clearSessionCookies(NextResponse.json({ ok: true }), request)
  const header = setCookieHeader(response)

  expect(header).toContain('max-age=0')
  expect(header).toContain('httponly')
  expect(header).toContain('secure')
  expect(header).toContain('samesite=none')
})

test('plain HTTP local logout keeps Lax cookie-clearing behavior', () => {
  const request = new Request('http://localhost:3000/api/auth/logout')
  const response = clearSessionCookies(NextResponse.json({ ok: true }), request)
  const header = setCookieHeader(response)

  expect(header).toContain('max-age=0')
  expect(header).toContain('httponly')
  expect(header).toContain('samesite=lax')
  expect(header).not.toContain('secure')
})

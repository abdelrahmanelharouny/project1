/// <reference types="bun-types" />
import { afterEach, describe, expect, test } from 'bun:test'
import { POST as registerPost } from '../../src/app/api/auth/register/route'
import { POST as requestVerificationPost } from '../../src/app/api/auth/verify-email/request/route'
import { POST as confirmVerificationPost } from '../../src/app/api/auth/verify-email/confirm/route'
import { handleRegistrationResult } from '../../src/lib/auth-registration'
import { confirmEmailVerification, register, requestEmailVerification } from '../../src/lib/api'
import type { AuthSession, RegisterResult } from '../../src/lib/types'

const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
})

function backendResponse(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function postRequest(path: string, payload: unknown, protocol = 'https:'): Request {
  return new Request(`${protocol}//localhost${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

describe('signup email verification frontend path', () => {
  test('registration 202 returns a pending email state without setting session cookies or leaking tokens', async () => {
    const verificationToken = 'dev-only-token-that-must-not-leak'
    globalThis.fetch = (async () =>
      backendResponse(
        {
          status: 'verification_required',
          message: 'Account created; verify your email.',
          user: { id: 'user-1', email: 'farmer@example.com' },
          token: 'unexpected-session-token',
          verification_token: verificationToken,
        },
        202,
      )) as unknown as typeof fetch

    const response = await registerPost(
      postRequest('/api/auth/register', {
        display_name: 'Farmer',
        email: 'farmer@example.com',
        password: 'correct horse battery staple',
      }),
    )
    const body = await response.json()
    const serialized = JSON.stringify(body)

    expect(response.status).toBe(202)
    expect(body).toEqual({ status: 'verification_required', user: { email: 'farmer@example.com' } })
    expect(response.headers.get('set-cookie')).toBeNull()
    expect(serialized).not.toContain(verificationToken)
    expect(serialized).not.toContain('unexpected-session-token')
  })

  test('a real session registration keeps the existing cookie flow', async () => {
    globalThis.fetch = (async () =>
      backendResponse(
        {
          token: 'session-access-token',
          refresh_token: 'session-refresh-token',
          user: { id: 'user-1', email: 'farmer@example.com', display_name: 'Farmer' },
          organization: { id: 'org-1', name: 'Farm' },
        },
        201,
      )) as unknown as typeof fetch

    const response = await registerPost(
      postRequest('/api/auth/register', {
        display_name: 'Farmer',
        email: 'farmer@example.com',
        password: 'password',
      }),
    )
    const body = await response.json()

    expect(response.status).toBe(200)
    expect(body).toMatchObject({ user: { display_name: 'Farmer' }, organization: { name: 'Farm' } })
    expect(JSON.stringify(body)).not.toContain('session-access-token')
    expect(JSON.stringify(body)).not.toContain('session-refresh-token')
    expect(response.headers.get('set-cookie')).toContain('fs_token=')
    expect(response.headers.get('set-cookie')).toContain('HttpOnly')
  })

  test('the frontend auth client uses local registration, resend, and confirmation proxy paths', async () => {
    const calls: Array<{ url: string; body: unknown }> = []
    const replies = [
      backendResponse({ status: 'verification_required', user: { email: 'farmer@example.com' } }, 202),
      backendResponse({ status: 'queued' }, 202),
      backendResponse({ status: 'ok' }, 200),
    ]
    globalThis.fetch = (async (input, init) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body)) })
      return replies.shift()!
    }) as unknown as typeof fetch

    const registration = await register({
      display_name: 'Farmer',
      email: 'farmer@example.com',
      password: 'correct horse battery staple',
    })
    await requestEmailVerification({ email: 'farmer@example.com' })
    await confirmEmailVerification({ token: 'valid-verification-token-123' })

    expect(registration).toEqual({
      status: 'verification_required',
      user: { email: 'farmer@example.com' },
    })
    expect(calls).toEqual([
      {
        url: '/api/auth/register',
        body: { display_name: 'Farmer', email: 'farmer@example.com', password: 'correct horse battery staple' },
      },
      { url: '/api/auth/verify-email/request', body: { email: 'farmer@example.com' } },
      { url: '/api/auth/verify-email/confirm', body: { token: 'valid-verification-token-123' } },
    ])
  })

  test('resend forwards only the email and strips development-only verification tokens', async () => {
    const verificationToken = 'dev-only-resend-token'
    let forwardedBody: unknown
    globalThis.fetch = (async (_input, init) => {
      forwardedBody = JSON.parse(String(init?.body))
      return backendResponse(
        { status: 'queued', message: 'Challenge queued.', verification_token: verificationToken },
        202,
      )
    }) as unknown as typeof fetch

    const response = await requestVerificationPost(
      postRequest('/api/auth/verify-email/request', { email: 'farmer@example.com', extra: 'ignored' }),
    )
    const body = await response.json()

    expect(response.status).toBe(202)
    expect(forwardedBody).toEqual({ email: 'farmer@example.com' })
    expect(body).toEqual({ status: 'queued' })
    expect(JSON.stringify(body)).not.toContain(verificationToken)
  })

  test('invalid-token errors do not echo the verification token', async () => {
    const token = 'invalid-token-that-is-long-enough'
    globalThis.fetch = (async () =>
      backendResponse(
        {
          error: {
            code: 'TOKEN_INVALID',
            message: `Invalid verification token: ${token}`,
            details: [{ field: 'token', reason: token }],
          },
        },
        422,
      )) as unknown as typeof fetch

    const response = await confirmVerificationPost(
      postRequest('/api/auth/verify-email/confirm', { token }),
    )
    const body = await response.text()

    expect(response.status).toBe(422)
    expect(body).toContain('Email verification could not be completed.')
    expect(body).not.toContain(token)
  })

  test('successful confirmation returns only status ok and creates no session cookie', async () => {
    globalThis.fetch = (async () =>
      backendResponse({ status: 'ok', token: 'unexpected-session-token' }, 200)) as unknown as typeof fetch

    const response = await confirmVerificationPost(
      postRequest('/api/auth/verify-email/confirm', { token: 'valid-verification-token-123' }),
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ status: 'ok' })
    expect(response.headers.get('set-cookie')).toBeNull()
  })

  test('verification-required registration invokes no authenticated callback until a session result exists', () => {
    let verifiedEmail = ''
    let authenticatedCount = 0
    const handlers = {
      onVerificationRequired: (email: string) => {
        verifiedEmail = email
      },
      onAuthenticated: (_session: AuthSession) => {
        authenticatedCount += 1
      },
    }
    const pending: RegisterResult = {
      status: 'verification_required',
      user: { email: 'farmer@example.com' },
    }

    handleRegistrationResult(pending, handlers)
    expect(verifiedEmail).toBe('farmer@example.com')
    expect(authenticatedCount).toBe(0)

    const session: AuthSession = {
      user: { id: 'user-1', email: 'farmer@example.com', display_name: 'Farmer' },
      organization: null,
    }
    handleRegistrationResult(session, handlers)
    expect(authenticatedCount).toBe(1)
  })
})

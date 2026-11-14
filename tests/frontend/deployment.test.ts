/**
 * Frontend deployment contract tests.
 *
 * These tests are intentionally pure: they cover the server-side origin
 * policy without requiring a running backend, Vercel, or a browser.
 */
/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'

import {
  ApiOriginConfigurationError,
  resolveApiOrigin,
  validateApiOrigin,
} from '@/lib/api-origin'

describe('CROPTWIST_API_ORIGIN validation', () => {
  test('normalizes a valid external origin and preserves its port', () => {
    expect(validateApiOrigin(' https://api.example.test:8443/ ')).toBe(
      'https://api.example.test:8443',
    )
  })

  test('rejects credentials, query strings, fragments, and path prefixes', () => {
    for (const value of [
      'https://user:secret@api.example.test',
      'https://api.example.test?token=secret',
      'https://api.example.test/#fragment',
      'https://api.example.test/backend',
    ]) {
      expect(() => validateApiOrigin(value)).toThrow(ApiOriginConfigurationError)
    }
  })

  test('rejects non-http protocols and malformed values', () => {
    expect(() => validateApiOrigin('ftp://api.example.test')).toThrow(ApiOriginConfigurationError)
    expect(() => validateApiOrigin('not-an-origin')).toThrow(ApiOriginConfigurationError)
  })
})

describe('API origin environment policy', () => {
  test('uses loopback only outside Vercel when no origin is configured', () => {
    expect(resolveApiOrigin(undefined, { isVercel: false })).toBe('http://127.0.0.1:3030')
  })

  test('fails closed on Vercel when the origin is missing', () => {
    expect(() => resolveApiOrigin(undefined, { isVercel: true })).toThrow(
      'CROPTWIST_API_ORIGIN is required for Vercel deployments.',
    )
  })

  test('rejects plaintext API origins on Vercel but permits local HTTP', () => {
    expect(() => resolveApiOrigin('http://api.example.test', { isVercel: true })).toThrow(
      'Vercel API origins must use HTTPS.',
    )
    expect(resolveApiOrigin('http://localhost:3030', { isVercel: false })).toBe(
      'http://localhost:3030',
    )
  })

  test('never includes credentials or query data in the normalized origin', () => {
    expect(resolveApiOrigin('https://api.example.test:443/', { isVercel: true })).toBe(
      'https://api.example.test',
    )
  })
})

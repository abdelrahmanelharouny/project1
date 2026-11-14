import { describe, expect, test } from 'bun:test'

import { isSyntheticDemoAccount } from '@/lib/demo-fixtures'

describe('isSyntheticDemoAccount', () => {
  test('identifies the explicitly seeded demo identity', () => {
    expect(isSyntheticDemoAccount('demo@croptwist.local')).toBe(true)
  })

  test('normalizes email case and surrounding whitespace', () => {
    expect(isSyntheticDemoAccount('  DEMO@CROPTWIST.LOCAL  ')).toBe(true)
  })

  test('does not label ordinary users or missing identities as demo accounts', () => {
    expect(isSyntheticDemoAccount('farmer@example.com')).toBe(false)
    expect(isSyntheticDemoAccount('')).toBe(false)
    expect(isSyntheticDemoAccount(null)).toBe(false)
    expect(isSyntheticDemoAccount(undefined)).toBe(false)
  })
})

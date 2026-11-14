import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'bun:test'

import {
  DESTINATIONS,
  EXTRA_TAB_ALIASES,
  LEGACY_TAB_IDS,
  SUB_ALIASES,
} from '@/lib/navigation'

interface RouteManifestEntry {
  path: string
  title?: string
}

const manifest = JSON.parse(
  readFileSync(new URL('../../public/manus-routes.json', import.meta.url), 'utf8'),
) as { routes: RouteManifestEntry[] }
const paths = new Set(manifest.routes.map((entry) => entry.path))

function routePath(entries: ReadonlyArray<readonly [string, string]>): string {
  const params = new URLSearchParams()
  for (const [key, value] of entries) params.set(key, value)
  return `/?${params.toString()}`
}

describe('public page route manifest', () => {
  test('contains the workspace root and all nine canonical destination links', () => {
    expect(paths.has('/')).toBe(true)
    for (const destination of DESTINATIONS) {
      expect(paths.has(routePath([['tab', destination.id]]))).toBe(true)
    }
  })

  test('contains every canonical sub-page deep link', () => {
    for (const destination of DESTINATIONS) {
      for (const subpage of destination.subPages) {
        expect(paths.has(routePath([['tab', destination.id], ['sub', subpage.id]]))).toBe(true)
      }
    }
  })

  test('preserves all legacy tabs, the extra tab alias, and sub-page aliases', () => {
    for (const legacyId of LEGACY_TAB_IDS) {
      expect(paths.has(routePath([['tab', legacyId]]))).toBe(true)
    }
    for (const alias of Object.keys(EXTRA_TAB_ALIASES)) {
      expect(paths.has(routePath([['tab', alias]]))).toBe(true)
    }
    for (const [tab, aliases] of Object.entries(SUB_ALIASES)) {
      for (const alias of Object.keys(aliases)) {
        expect(paths.has(routePath([['tab', tab], ['sub', alias]]))).toBe(true)
      }
    }
  })

  test('contains unique, bounded UI routes only; no API, asset, or invented entity paths', () => {
    expect(paths.size).toBe(manifest.routes.length)
    expect(manifest.routes.length).toBeLessThanOrEqual(1000)
    for (const entry of manifest.routes) {
      expect(entry.path.startsWith('/')).toBe(true)
      expect(entry.path.startsWith('//')).toBe(false)
      expect(entry.path.startsWith('/api/')).toBe(false)
      expect(entry.path.length).toBeLessThanOrEqual(2048)
      expect(entry.title?.length ?? 0).toBeLessThanOrEqual(256)
      expect(/[\s\u0000-\u001f]/.test(entry.path)).toBe(false)
      expect(entry.path).not.toMatch(/[?&](?:farm|field)=/)
    }
  })
})

/**
 * P02 W1 — navigation model tests (bun test).
 *
 * Covers:
 *   1. Every legacy `?tab=` id from docs/p01/UX_MIGRATION_MATRIX.md §3
 *      resolves to the exact destination + sub-page recorded there.
 *   2. Destination ids resolve canonically; invalid/missing sub fallbacks.
 *   3. Unknown/invalid tab ids resolve safely to null (no redirect loops).
 *   4. Idempotency: resolving a resolved target is a fixed point.
 *   5. Config integrity: nine destinations, unique ids, sub-page validity.
 *   6. Cross-component targets (entitlement guard 'billing', notification
 *      bell kinds, onboarding wizard 'farms'/'team') keep working.
 *   7. Store-level resolution (setActiveTab legacy ids, goTo* helpers,
 *      navigateTo, activeSub) — docs/p01 audit P12 drift fixed.
 */
/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'

import {
  DESTINATION_IDS,
  DESTINATIONS,
  LEGACY_TAB_IDS,
  defaultSubFor,
  destinationById,
  isValidSub,
  isDestinationTab,
  isLegacyTab,
  normalizeSub,
  resolveTarget,
} from '@/lib/navigation'
import { useCropTwistUi } from '@/lib/store'

// ---------------------------------------------------------------------------
// 1. Legacy redirect map — all 27 ids, exact matrix values
// ---------------------------------------------------------------------------

const EXPECTED_LEGACY_MAP: Record<string, { tab: string; sub: string | null }> = {
  overview: { tab: 'overview', sub: null },
  farms: { tab: 'farms', sub: null },
  observations: { tab: 'datahub', sub: 'observations' },
  features: { tab: 'datahub', sub: 'features' },
  passport: { tab: 'datahub', sub: 'passport' },
  adaptiveevidence: { tab: 'datahub', sub: 'evidence' },
  rotation: { tab: 'cropintel', sub: 'rotation' },
  water: { tab: 'cropintel', sub: 'irrigation' },
  soil: { tab: 'cropintel', sub: 'soil' },
  // P03 W2.1: the old "Crop management" tab opened on its Plan view — the
  // redirect now lands on the promoted plan sub-page (identical rendered view).
  management: { tab: 'cropintel', sub: 'plan' },
  soilmemory: { tab: 'cropintel', sub: 'soilmemory' },
  forecast: { tab: 'cropintel', sub: 'forecast' },
  satellite: { tab: 'geo', sub: 'map' },
  fieldstate: { tab: 'decisions', sub: 'state' },
  scenarios: { tab: 'decisions', sub: 'scenarios' },
  sensitivity: { tab: 'decisions', sub: 'sensitivity' },
  robustplan: { tab: 'decisions', sub: 'robust' },
  // NOTE on `decisions`: this id exists as BOTH a legacy tab (old "Decision
  // documents" tab) and the new Decision Center destination id. The canonical
  // (destination) meaning wins for the bare id — documented deliberate
  // disambiguation (see docs/p02/P02_NAVIGATION_MAPPING.md §1). The exact old
  // view stays reachable via `?tab=decisions&sub=documents` and the sub rail.
  decisions: { tab: 'decisions', sub: 'state' },
  failurelab: { tab: 'decisions', sub: 'failurelab' },
  portfolio: { tab: 'decisions', sub: 'portfolio' },
  digitaltwin: { tab: 'decisions', sub: 'twin' },
  aiinsights: { tab: 'copilot', sub: null },
  reports: { tab: 'reports', sub: 'reports' },
  insights: { tab: 'reports', sub: 'analytics' },
  team: { tab: 'settings', sub: 'organization' },
  billing: { tab: 'settings', sub: 'billing' },
  developer: { tab: 'settings', sub: 'developer' },
}

describe('legacy redirect map (all 27 ids, matrix §3)', () => {
  test('every legacy id resolves to its recorded destination + sub-page', () => {
    for (const legacy of LEGACY_TAB_IDS) {
      const resolved = resolveTarget(legacy)
      expect(resolved).not.toBeNull()
      const expected = EXPECTED_LEGACY_MAP[legacy]
      expect(expected).toBeDefined()
      expect(String(resolved!.tab)).toBe(expected.tab)
      expect(resolved!.sub).toBe(expected.sub)
    }
  })

  test('the map contains exactly 27 entries', () => {
    expect(LEGACY_TAB_IDS).toHaveLength(27)
    expect(Object.keys(EXPECTED_LEGACY_MAP)).toHaveLength(27)
  })

  test('every legacy redirect target sub-page is valid for its destination', () => {
    for (const legacy of LEGACY_TAB_IDS) {
      const resolved = resolveTarget(legacy)!
      if (resolved.sub) expect(isValidSub(resolved.tab, resolved.sub)).toBe(true)
    }
  })

  test('isLegacyTab accepts all 27 ids; non-overlapping destinations are not legacy', () => {
    for (const legacy of LEGACY_TAB_IDS) expect(isLegacyTab(legacy)).toBe(true)
    // overview/farms/reports/decisions exist as BOTH legacy and destination ids
    // (matrix maps the first three to themselves; decisions is documented in
    // P02_NAVIGATION_MAPPING.md §1); all other destinations must not be legacy.
    const overlapping = ['overview', 'farms', 'reports', 'decisions']
    for (const dest of DESTINATION_IDS) {
      if (!overlapping.includes(dest)) expect(isLegacyTab(dest)).toBe(false)
    }
    expect(isLegacyTab('nonsense')).toBe(false)
    expect(isLegacyTab(null)).toBe(false)
    expect(isLegacyTab(undefined)).toBe(false)
  })

  test('the exact legacy "Decision documents" nested view stays reachable', () => {
    expect(resolveTarget('decisions', 'documents')).toEqual({ tab: 'decisions', sub: 'documents' })
  })
})

// ---------------------------------------------------------------------------
// 2. Destination resolution + sub fallbacks
// ---------------------------------------------------------------------------

describe('destination resolution', () => {
  test('nine destinations exist with unique ids', () => {
    expect(DESTINATION_IDS).toHaveLength(9)
    expect(new Set(DESTINATION_IDS).size).toBe(9)
    expect(new Set(DESTINATIONS.map((d) => d.labelKey)).size).toBe(9)
  })

  test('sub-page totals: 30 sub-pages across 6 multi-sub destinations (P03: 6 management views promoted + preferences)', () => {
    const total = DESTINATIONS.reduce((acc, d) => acc + d.subPages.length, 0)
    expect(total).toBe(30)
    expect(DESTINATIONS.filter((d) => d.subPages.length > 0)).toHaveLength(6)
  })

  test('cropintel exposes the six promoted management sub-pages in order (P03 W2.1)', () => {
    const cropintel = destinationById('cropintel')!
    const ids = cropintel.subPages.map((s) => s.id)
    expect(ids).toEqual([
      'rotation', 'irrigation', 'soil', 'plan', 'covers', 'timeline',
      'residue', 'erosion', 'operations', 'soilmemory', 'forecast',
    ])
    // the six management views sit between soil and soil-memory
    expect(ids.indexOf('plan')).toBeGreaterThan(ids.indexOf('soil'))
    expect(ids.indexOf('operations')).toBeLessThan(ids.indexOf('soilmemory'))
  })

  test('settings appends preferences without moving existing sub ids (P03 W2.2)', () => {
    const settings = destinationById('settings')!
    expect(settings.subPages.map((s) => s.id)).toEqual(['organization', 'billing', 'developer', 'preferences'])
  })

  test('sub-page ids are unique within each destination', () => {
    for (const dest of DESTINATIONS) {
      expect(new Set(dest.subPages.map((s) => s.id)).size).toBe(dest.subPages.length)
    }
  })

  test('destination id resolves with default sub for multi-sub destinations', () => {
    expect(resolveTarget('datahub')).toEqual({ tab: 'datahub', sub: 'observations' })
    expect(resolveTarget('cropintel')).toEqual({ tab: 'cropintel', sub: 'rotation' })
    expect(resolveTarget('decisions')).toEqual({ tab: 'decisions', sub: 'state' })
    expect(resolveTarget('reports')).toEqual({ tab: 'reports', sub: 'reports' })
    expect(resolveTarget('settings')).toEqual({ tab: 'settings', sub: 'organization' })
    expect(resolveTarget('geo')).toEqual({ tab: 'geo', sub: 'map' })
  })

  test('destination id resolves with explicit valid sub', () => {
    expect(resolveTarget('cropintel', 'soilmemory')).toEqual({ tab: 'cropintel', sub: 'soilmemory' })
    expect(resolveTarget('decisions', 'twin')).toEqual({ tab: 'decisions', sub: 'twin' })
  })

  test('destination id with invalid sub falls back to the destination default (no loops)', () => {
    expect(resolveTarget('cropintel', 'nonsense')).toEqual({ tab: 'cropintel', sub: 'rotation' })
    expect(resolveTarget('reports', 'water')).toEqual({ tab: 'reports', sub: 'reports' })
  })

  test('single-view destinations always resolve with null sub', () => {
    expect(resolveTarget('overview')).toEqual({ tab: 'overview', sub: null })
    expect(resolveTarget('farms')).toEqual({ tab: 'farms', sub: null })
    expect(resolveTarget('copilot')).toEqual({ tab: 'copilot', sub: null })
    expect(resolveTarget('overview', 'irrigation')).toEqual({ tab: 'overview', sub: null })
    expect(defaultSubFor('overview')).toBeNull()
    expect(defaultSubFor('farms')).toBeNull()
    expect(defaultSubFor('copilot')).toBeNull()
  })

  test('legacy id ignores a stray ?sub= param (legacy URLs never carried sub)', () => {
    expect(resolveTarget('water', 'soil')).toEqual({ tab: 'cropintel', sub: 'irrigation' })
  })
})

// ---------------------------------------------------------------------------
// 2b. P03 W2 — sub aliases + additive tab aliases (permanent URL contracts)
// ---------------------------------------------------------------------------

describe('sub-page alias contract (P03 W2.1)', () => {
  test('?tab=cropintel&sub=management keeps resolving to the plan view (forever)', () => {
    expect(resolveTarget('cropintel', 'management')).toEqual({ tab: 'cropintel', sub: 'plan' })
  })

  test('the alias is idempotent (no redirect loops)', () => {
    const first = resolveTarget('cropintel', 'management')!
    expect(resolveTarget(first.tab, first.sub)).toEqual(first)
  })

  test('the exact legacy management URL (?tab=management&sub=management) resolves', () => {
    expect(resolveTarget('management', 'management')).toEqual({ tab: 'cropintel', sub: 'plan' })
  })

  test('normalizeSub validates after aliasing; unknown subs still fall back', () => {
    expect(normalizeSub('cropintel', 'erosion')).toBe('erosion')
    expect(normalizeSub('cropintel', 'management')).toBe('plan')
    expect(normalizeSub('cropintel', 'nonsense')).toBeNull()
    expect(normalizeSub('settings', 'preferences')).toBe('preferences')
    expect(normalizeSub('settings', 'management')).toBeNull()
  })
})

describe('additive tab alias contract (P03 W2.2)', () => {
  test('?tab=preferences resolves to settings/preferences', () => {
    expect(resolveTarget('preferences')).toEqual({ tab: 'settings', sub: 'preferences' })
  })

  test('the alias is idempotent and does not touch the 27-entry legacy contract', () => {
    const first = resolveTarget('preferences')!
    expect(resolveTarget(first.tab, first.sub)).toEqual(first)
    expect(LEGACY_TAB_IDS).toHaveLength(27)
    expect(isLegacyTab('preferences')).toBe(false) // not one of the 27 former tabs
  })

  test('unknown ids still resolve to null (no loops introduced)', () => {
    expect(resolveTarget('prefs')).toBeNull()
    expect(resolveTarget('nonsense')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 3. Safe handling of unknown/invalid ids (no redirect loops)
// ---------------------------------------------------------------------------

describe('unknown tab handling', () => {
  test('unknown ids resolve to null (pre-P02 "safely ignored" contract)', () => {
    expect(resolveTarget('nonsense')).toBeNull()
    expect(resolveTarget('../etc/passwd')).toBeNull()
    expect(resolveTarget('OVERVIEW')).toBeNull()
    expect(resolveTarget('overview%20')).toBeNull()
    expect(resolveTarget(null)).toBeNull()
    expect(resolveTarget(undefined)).toBeNull()
    expect(resolveTarget('')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 4. Idempotency — canonical URLs are fixed points
// ---------------------------------------------------------------------------

describe('resolver idempotency (no redirect loops)', () => {
  test('resolving the output of every legacy redirect returns the same target', () => {
    for (const legacy of LEGACY_TAB_IDS) {
      const first = resolveTarget(legacy)!
      const second = resolveTarget(first.tab, first.sub)
      expect(second).toEqual(first)
    }
  })

  test('resolving any destination output is a fixed point', () => {
    for (const dest of DESTINATIONS) {
      for (const sub of dest.subPages) {
        const target = resolveTarget(dest.id, sub.id)!
        expect(resolveTarget(target.tab, target.sub)).toEqual(target)
      }
      const def = resolveTarget(dest.id)!
      expect(resolveTarget(def.tab, def.sub)).toEqual(def)
    }
  })

  test('isDestinationTab accepts exactly the nine destination ids', () => {
    for (const dest of DESTINATION_IDS) expect(isDestinationTab(dest)).toBe(true)
    expect(isDestinationTab('water')).toBe(false)
    expect(isDestinationTab('nonsense')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 5. Cross-component navigation targets keep working through resolution
// ---------------------------------------------------------------------------

describe('existing navigation consumers preserve their targets', () => {
  test('entitlement-guard Upgrade target (?tab=billing via setActiveTab)', () => {
    expect(resolveTarget('billing')).toEqual({ tab: 'settings', sub: 'billing' })
  })

  test('notification-bell link_kind → tab targets all resolve', () => {
    // The bell maps link kinds to tabs (notifications-bell.tsx linkKindToTab);
    // every one of those tab ids must still resolve through the redirect map.
    const bellKindToTab: Record<string, string> = {
      farm: 'farms',
      field: 'farms',
      observation: 'farms',
      report: 'reports',
      report_job: 'reports',
      recommendation: 'insights',
      billing: 'billing',
      subscription: 'billing',
      invoice: 'billing',
      invitation: 'team',
      membership: 'team',
      organization: 'team',
      api_key: 'developer',
    }
    for (const tab of Object.values(bellKindToTab)) {
      const resolved = resolveTarget(tab)
      expect(resolved).not.toBeNull()
    }
    // Spot-check the meaningful redirects:
    expect(resolveTarget('insights')).toEqual({ tab: 'reports', sub: 'analytics' })
    expect(resolveTarget('reports')).toEqual({ tab: 'reports', sub: 'reports' })
    expect(resolveTarget('developer')).toEqual({ tab: 'settings', sub: 'developer' })
  })

  test('onboarding wizard goTab targets resolve', () => {
    expect(resolveTarget('farms')).toEqual({ tab: 'farms', sub: null })
    expect(resolveTarget('team')).toEqual({ tab: 'settings', sub: 'organization' })
  })

  test('store goTo* helper targets resolve', () => {
    expect(resolveTarget('passport')).toEqual({ tab: 'datahub', sub: 'passport' })
    expect(resolveTarget('observations')).toEqual({ tab: 'datahub', sub: 'observations' })
    expect(resolveTarget('features')).toEqual({ tab: 'datahub', sub: 'features' })
    expect(resolveTarget('fieldstate')).toEqual({ tab: 'decisions', sub: 'state' })
    expect(resolveTarget('scenarios')).toEqual({ tab: 'decisions', sub: 'scenarios' })
    expect(resolveTarget('rotation')).toEqual({ tab: 'cropintel', sub: 'rotation' })
    expect(resolveTarget('water')).toEqual({ tab: 'cropintel', sub: 'irrigation' })
  })
})

// ---------------------------------------------------------------------------
// 6. Store-level resolution (single resolution point; P12 drift fixed)
// ---------------------------------------------------------------------------

describe('store tab resolution', () => {
  test('setActiveTab resolves legacy water → cropintel/irrigation', () => {
    const s = useCropTwistUi.getState()
    s.setActiveTab('water')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('cropintel')
    expect(after.activeSub).toBe('irrigation')
    void s
  })

  test('setActiveTab resolves entitlement-guard billing → settings/billing', () => {
    useCropTwistUi.getState().setActiveTab('billing')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('settings')
    expect(after.activeSub).toBe('billing')
  })

  test('setActiveTab ignores unknown ids (previous view preserved)', () => {
    useCropTwistUi.getState().setActiveTab('cropintel')
    useCropTwistUi.getState().setActiveTab('soil')
    expect(useCropTwistUi.getState().activeSub).toBe('soil')
    useCropTwistUi.getState().setActiveTab('nonsense' as never)
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('cropintel')
    expect(after.activeSub).toBe('soil')
  })

  test('setActiveTab keeps current sub when re-selecting the active destination', () => {
    useCropTwistUi.getState().navigateTo('cropintel', 'soilmemory')
    useCropTwistUi.getState().setActiveTab('cropintel')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('cropintel')
    expect(after.activeSub).toBe('soilmemory')
  })

  test('navigateTo applies explicit valid sub', () => {
    useCropTwistUi.getState().navigateTo('decisions', 'portfolio')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('decisions')
    expect(after.activeSub).toBe('portfolio')
  })

  test('navigateTo falls back to destination default for invalid sub', () => {
    useCropTwistUi.getState().navigateTo('reports', 'nonsense')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('reports')
    expect(after.activeSub).toBe('reports')
  })

  test('setActiveSub ignores subs that do not belong to the active destination', () => {
    useCropTwistUi.getState().navigateTo('datahub', 'passport')
    useCropTwistUi.getState().setActiveSub('irrigation')
    expect(useCropTwistUi.getState().activeSub).toBe('passport')
    useCropTwistUi.getState().setActiveSub('evidence')
    expect(useCropTwistUi.getState().activeSub).toBe('evidence')
  })

  test('goToPassportFor selects the field AND lands on datahub/passport', () => {
    useCropTwistUi.getState().goToPassportFor({ id: 'f-1', name: 'North', farmId: 'farm-1' })
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('datahub')
    expect(after.activeSub).toBe('passport')
    expect(after.selectedField?.id).toBe('f-1')
    expect(after.selectedFarmId).toBe('farm-1')
  })

  test('goToRotationFor and goToWaterFor resolve (interface drift P12 fixed)', () => {
    const s = useCropTwistUi.getState()
    // The interface must now declare these (compile-time check via usage).
    s.goToRotationFor({ id: 'f-2', name: 'South', farmId: 'farm-1' })
    expect(useCropTwistUi.getState().activeTab).toBe('cropintel')
    expect(useCropTwistUi.getState().activeSub).toBe('rotation')
    s.goToWaterFor({ id: 'f-2', name: 'South', farmId: 'farm-1' })
    expect(useCropTwistUi.getState().activeTab).toBe('cropintel')
    expect(useCropTwistUi.getState().activeSub).toBe('irrigation')
  })

  test('openCreateFarm lands on Farms & Fields', () => {
    useCropTwistUi.getState().openCreateFarm()
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('farms')
    expect(after.createFarmDialogOpen).toBe(true)
  })

  test('navigateTo(cropintel, management) normalizes to plan through the store resolver', () => {
    useCropTwistUi.getState().navigateTo('cropintel', 'management')
    const after = useCropTwistUi.getState()
    expect(after.activeTab).toBe('cropintel')
    expect(after.activeSub).toBe('plan')
  })
})

// ---------------------------------------------------------------------------
// 7. P03 W2 — store additions (recent views for the palette, expert mode)
// ---------------------------------------------------------------------------

describe('store recent views (command palette Recent group)', () => {
  test('navigation records visited views newest-first', () => {
    useCropTwistUi.getState().navigateTo('cropintel', 'rotation')
    useCropTwistUi.getState().navigateTo('decisions', 'sensitivity')
    useCropTwistUi.getState().navigateTo('reports', 'reports')
    const recent = useCropTwistUi.getState().recentViews
    expect(recent[0]).toEqual({ tab: 'reports', sub: 'reports' })
    expect(recent[1]).toEqual({ tab: 'decisions', sub: 'sensitivity' })
    expect(recent[2]).toEqual({ tab: 'cropintel', sub: 'rotation' })
  })

  test('consecutive duplicates are not recorded twice (rail re-click)', () => {
    const s = useCropTwistUi.getState()
    s.navigateTo('cropintel', 'soilmemory') // break any prior consecutive run
    s.navigateTo('cropintel', 'forecast')
    s.setActiveTab('cropintel') // rail re-click on the SAME view → no new entry
    const recent = useCropTwistUi.getState().recentViews
    expect(recent[0]).toEqual({ tab: 'cropintel', sub: 'forecast' })
    expect(recent[1]).not.toEqual({ tab: 'cropintel', sub: 'forecast' })
  })

  test('the recent list is capped at 8 entries', () => {
    const s = useCropTwistUi.getState()
    s.navigateTo('datahub', 'observations')
    s.navigateTo('datahub', 'features')
    s.navigateTo('datahub', 'passport')
    s.navigateTo('datahub', 'evidence')
    s.navigateTo('cropintel', 'rotation')
    s.navigateTo('cropintel', 'irrigation')
    s.navigateTo('cropintel', 'soil')
    s.navigateTo('cropintel', 'plan')
    s.navigateTo('cropintel', 'covers') // 9th distinct view
    expect(useCropTwistUi.getState().recentViews.length).toBeLessThanOrEqual(8)
  })

  test('management expert toggle persists on the store (shared across the six sub-pages)', () => {
    useCropTwistUi.getState().setManagementExpert(true)
    expect(useCropTwistUi.getState().managementExpert).toBe(true)
    useCropTwistUi.getState().navigateTo('cropintel', 'erosion')
    expect(useCropTwistUi.getState().managementExpert).toBe(true)
    useCropTwistUi.getState().setManagementExpert(false)
    expect(useCropTwistUi.getState().managementExpert).toBe(false)
  })
})

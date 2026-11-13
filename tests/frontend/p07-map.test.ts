/**
 * P07 map frontend — pure-logic unit tests (bun test).
 *
 * Covers the temporal / layer-management helpers in src/lib/map/temporal.ts:
 *   (a) gap computation from the backend's dates_available (>16d flagged,
 *       16d NOT flagged — strictly-greater threshold, never interpolated)
 *   (b) temporal compatibility of simultaneously-visible layers
 *   (c) vegetation draw-order moves with clamping (move up / move down)
 *   (d) UI percent → MapLibre raster opacity fraction mapping
 *   (e) availability partitioning (unavailableLayers / partitionLayerAvailability)
 *       — unavailable layers are RETURNED, never dropped
 *   (f) date sorting (nulls sink), day parsing, freshness helpers
 */
/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'

import {
  checkTemporalCompatibility,
  computeDateGaps,
  datesAreCompatible,
  dayFromIso,
  daysSinceDay,
  dayToUtcMs,
  isFreshDay,
  moveLayerOrder,
  opacityFraction,
  partitionLayerAvailability,
  sortDatesDescending,
  unavailableLayers,
  zIndexForOrderSlot,
} from '@/lib/map/temporal'
import type { P07LayerCatalog } from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// (a) Gap computation — honesty: gaps are REPORTED, never interpolated
// ---------------------------------------------------------------------------

describe('computeDateGaps', () => {
  test('flags strictly-greater-than-16-day distances between consecutive dates', () => {
    const gaps = computeDateGaps(['2025-05-01', '2025-05-18'])
    expect(gaps).toHaveLength(1)
    expect(gaps[0]).toEqual({ from: '2025-05-01', to: '2025-05-18', days: 17 })
  })

  test('a 16-day distance is NOT a gap (nominal revisit cadence)', () => {
    expect(computeDateGaps(['2025-05-01', '2025-05-17'])).toEqual([])
  })

  test('chains multiple consecutive gaps with real intermediate dates', () => {
    const gaps = computeDateGaps([
      '2025-04-01',
      '2025-04-10', // 9 days — no gap
      '2025-05-05', // 25 days — gap
      '2025-06-10', // 36 days — gap
    ])
    expect(gaps).toHaveLength(2)
    expect(gaps[0]).toEqual({ from: '2025-04-10', to: '2025-05-05', days: 25 })
    expect(gaps[1]).toEqual({ from: '2025-05-05', to: '2025-06-10', days: 36 })
  })

  test('sorts unsorted input and deduplicates repeated dates first', () => {
    const gaps = computeDateGaps(['2025-05-18', '2025-05-01', '2025-05-18', '2025-05-01'])
    expect(gaps).toHaveLength(1)
    expect(gaps[0]?.from).toBe('2025-05-01')
    expect(gaps[0]?.to).toBe('2025-05-18')
  })

  test('ignores null/invalid dates instead of inventing a gap', () => {
    expect(computeDateGaps([null, '2025-05-01', undefined, 'garbage', '2025-05-02'])).toEqual([])
  })

  test('empty and single-date inputs produce no gaps', () => {
    expect(computeDateGaps([])).toEqual([])
    expect(computeDateGaps(['2025-05-01'])).toEqual([])
  })

  test('honors a custom threshold (e.g. the 5-day HLS compositing window)', () => {
    const gaps = computeDateGaps(['2025-05-01', '2025-05-07'], 5)
    expect(gaps).toHaveLength(1)
    expect(gaps[0]?.days).toBe(6)
  })

  test('full ISO timestamps are reduced to their day part', () => {
    const gaps = computeDateGaps(['2025-05-01T10:24:00Z', '2025-05-25T11:00:00Z'])
    expect(gaps).toHaveLength(1)
    expect(gaps[0]).toEqual({ from: '2025-05-01', to: '2025-05-25', days: 24 })
  })
})

// ---------------------------------------------------------------------------
// (b) Temporal compatibility — differing acquisition days are flagged
// ---------------------------------------------------------------------------

describe('datesAreCompatible', () => {
  test('same day (any timestamp form) is compatible', () => {
    expect(datesAreCompatible('2025-05-01', '2025-05-01')).toBe(true)
    expect(datesAreCompatible('2025-05-01T08:00:00Z', '2025-05-01T18:30:00Z')).toBe(true)
  })

  test('different days are NOT compatible', () => {
    expect(datesAreCompatible('2025-05-01', '2025-05-02')).toBe(false)
  })

  test('missing/invalid dates are never compatible with anything', () => {
    expect(datesAreCompatible(null, '2025-05-01')).toBe(false)
    expect(datesAreCompatible('2025-05-01', undefined)).toBe(false)
    expect(datesAreCompatible(null, null)).toBe(false)
    expect(datesAreCompatible('', '2025-05-01')).toBe(false)
  })
})

describe('checkTemporalCompatibility', () => {
  test('zero or one dated layer is trivially compatible', () => {
    expect(checkTemporalCompatibility([]).compatible).toBe(true)
    expect(
      checkTemporalCompatibility([{ id: 'ndvi', date: '2025-05-01' }]).compatible,
    ).toBe(true)
    expect(checkTemporalCompatibility([{ id: 'ndvi', date: null }]).compared).toBe(0)
  })

  test('two visible layers on the SAME acquisition day stay compatible', () => {
    const result = checkTemporalCompatibility([
      { id: 'ndvi', date: '2025-05-01' },
      { id: 'ndmi', date: '2025-05-01' },
    ])
    expect(result.compatible).toBe(true)
    expect(result.compared).toBe(2)
    expect(result.distinctDates).toEqual(['2025-05-01'])
  })

  test('two visible layers on DIFFERENT days are flagged with the sorted distinct days', () => {
    const result = checkTemporalCompatibility([
      { id: 'ndvi', date: '2025-05-04' },
      { id: 'ndmi', date: '2025-04-28' },
    ])
    expect(result.compatible).toBe(false)
    expect(result.distinctDates).toEqual(['2025-04-28', '2025-05-04'])
    expect(result.datedLayerIds).toEqual(['ndvi', 'ndmi'])
  })

  test('undated layers are skipped, dated ones still compared', () => {
    const result = checkTemporalCompatibility([
      { id: 'ndvi', date: '2025-05-04' },
      { id: 'evi', date: null },
      { id: 'ndmi', date: '2025-05-04' },
    ])
    expect(result.compatible).toBe(true)
    expect(result.compared).toBe(2)
    expect(result.datedLayerIds).toEqual(['ndvi', 'ndmi'])
  })
})

// ---------------------------------------------------------------------------
// (c) Draw order — move up/down with clamping
// ---------------------------------------------------------------------------

describe('moveLayerOrder', () => {
  const ORDER = ['ndvi', 'ndmi', 'bsi']

  test('"up" swaps a layer one slot toward the top of the stack', () => {
    expect(moveLayerOrder(ORDER, 'ndmi', 'up')).toEqual(['ndmi', 'ndvi', 'bsi'])
  })

  test('"down" swaps a layer one slot toward the bottom of the stack', () => {
    expect(moveLayerOrder(ORDER, 'ndmi', 'down')).toEqual(['ndvi', 'bsi', 'ndmi'])
  })

  test('moving the top layer up is clamped (order unchanged)', () => {
    expect(moveLayerOrder(ORDER, 'ndvi', 'up')).toEqual(ORDER)
  })

  test('moving the bottom layer down is clamped (order unchanged)', () => {
    expect(moveLayerOrder(ORDER, 'bsi', 'down')).toEqual(ORDER)
  })

  test('unknown ids keep the order intact and return a NEW array', () => {
    const result = moveLayerOrder(ORDER, 'evi', 'up')
    expect(result).toEqual(ORDER)
    expect(result).not.toBe(ORDER)
  })

  test('the input array is never mutated', () => {
    const original = [...ORDER]
    moveLayerOrder(ORDER, 'ndvi', 'down')
    expect(ORDER).toEqual(original)
  })

  test('a full sequence of moves walks the layer to the other end', () => {
    let order = ORDER
    order = moveLayerOrder(order, 'bsi', 'up')
    order = moveLayerOrder(order, 'bsi', 'up')
    expect(order).toEqual(['bsi', 'ndvi', 'ndmi'])
  })
})

describe('zIndexForOrderSlot', () => {
  test('slot 0 (top of the stack) gets the HIGHEST z-index', () => {
    const order = ['ndvi', 'ndmi', 'bsi']
    expect(zIndexForOrderSlot(order, 'ndvi')).toBe(2)
    expect(zIndexForOrderSlot(order, 'ndmi')).toBe(1)
    expect(zIndexForOrderSlot(order, 'bsi')).toBe(0)
  })

  test('unknown ids fall back to 0 (bottom)', () => {
    expect(zIndexForOrderSlot(['ndvi'], 'evi')).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// (d) Opacity mapping — UI percent → raster fraction
// ---------------------------------------------------------------------------

describe('opacityFraction', () => {
  test('maps the documented slider steps linearly', () => {
    expect(opacityFraction(0)).toBe(0)
    expect(opacityFraction(35)).toBe(0.35)
    expect(opacityFraction(70)).toBe(0.7)
    expect(opacityFraction(100)).toBe(1)
  })

  test('clamps out-of-range percents on both ends', () => {
    expect(opacityFraction(150)).toBe(1)
    expect(opacityFraction(-5)).toBe(0)
  })

  test('degrades non-finite input to 0 instead of NaN or Infinity', () => {
    expect(opacityFraction(Number.NaN)).toBe(0)
    expect(opacityFraction(Number.POSITIVE_INFINITY)).toBe(0)
    expect(opacityFraction(Number.NEGATIVE_INFINITY)).toBe(0)
  })

  test('fractional percents round to clean two-decimal fractions', () => {
    expect(opacityFraction(33.4)).toBe(0.33)
    expect(opacityFraction(66.7)).toBe(0.67)
  })
})

// ---------------------------------------------------------------------------
// (e) Availability partitioning — unavailable layers are NEVER dropped
// ---------------------------------------------------------------------------

describe('partitionLayerAvailability', () => {
  const layers = [
    { id: 'ndvi', available: true },
    { id: 'evi', available: false },
    { id: 'ndmi', available: true },
  ]

  test('splits into available + unavailable preserving order', () => {
    const { available, unavailable } = partitionLayerAvailability(layers)
    expect(available.map((l) => l.id)).toEqual(['ndvi', 'ndmi'])
    expect(unavailable.map((l) => l.id)).toEqual(['evi'])
  })

  test('unavailable layers stay in the result (visible-but-disabled contract)', () => {
    const { unavailable } = partitionLayerAvailability(layers)
    expect(unavailable).toHaveLength(1)
    expect(unavailable[0]?.available).toBe(false)
  })
})

describe('unavailableLayers', () => {
  const catalog: P07LayerCatalog = {
    catalog_version: 'test-v1',
    field_id: 'f-1',
    layers: {
      vegetation: [
        { id: 'ndvi', group: 'vegetation', code: 'ndvi', kind: 'raster', label: 'NDVI', index_formula: null, available: true, product_count: 3, dates_available: [] },
        { id: 'lst', group: 'vegetation', code: 'ndwi', kind: 'raster', label: 'NDWI', index_formula: null, available: false, product_count: 0, dates_available: [], unavailable_reason: 'no derived products' },
      ],
      environment: [
        { id: 'soil_moisture', group: 'environment', code: 'soil_moisture', kind: 'field_series', label: 'Soil moisture', available: true, observation_count: 9, render: { type: 'series' } },
        { id: 'lst', group: 'environment', code: 'lst', kind: 'field_series', label: 'LST', available: false, render: null, unavailable_reason: 'not measured for this field' },
        { id: 'terrain', group: 'environment', code: 'terrain', kind: 'raster', label: 'Terrain', available: false, render: null, unavailable_reason: 'no terrain source configured' },
      ],
      infrastructure: [
        { id: 'boundary', group: 'infrastructure', code: 'boundary', kind: 'vector', label: 'Boundary', available: true, boundary_version: 2 },
        { id: 'statistical_zones', group: 'infrastructure', code: 'statistical_zones', kind: 'vector', label: 'Zones', available: true, zone_note: 'terciles' },
      ],
    },
    notes: [],
  }

  test('collects ONLY the unavailable layers per group', () => {
    const result = unavailableLayers(catalog)
    expect(result.vegetation.map((l) => l.id)).toEqual(['lst'])
    expect(result.environment.map((l) => l.id)).toEqual(['lst', 'terrain'])
    expect(result.infrastructure).toEqual([])
  })

  test('keeps each unavailable layer with its backend reason', () => {
    const result = unavailableLayers(catalog)
    expect(result.vegetation[0]?.unavailable_reason).toBe('no derived products')
    expect(result.environment[0]?.unavailable_reason).toBe('not measured for this field')
  })

  test('null/undefined catalogs degrade to empty groups (no throw)', () => {
    expect(unavailableLayers(null)).toEqual({
      vegetation: [],
      environment: [],
      infrastructure: [],
    })
    expect(unavailableLayers(undefined)).toEqual({
      vegetation: [],
      environment: [],
      infrastructure: [],
    })
  })

  test('a fully-available catalog yields empty groups', () => {
    const allAvailable: P07LayerCatalog = {
      ...catalog,
      layers: {
        vegetation: [{ ...catalog.layers.vegetation[0]! }],
        environment: [{ ...catalog.layers.environment[0]! }],
        infrastructure: [{ ...catalog.layers.infrastructure[0]! }],
      },
    }
    expect(unavailableLayers(allAvailable)).toEqual({
      vegetation: [],
      environment: [],
      infrastructure: [],
    })
  })
})

// ---------------------------------------------------------------------------
// (f) Day parsing, sorting, freshness
// ---------------------------------------------------------------------------

describe('dayFromIso / dayToUtcMs', () => {
  test('extracts the YYYY-MM-DD day part from any ISO form', () => {
    expect(dayFromIso('2025-05-01T10:24:00Z')).toBe('2025-05-01')
    expect(dayFromIso('2025-05-01')).toBe('2025-05-01')
    expect(dayFromIso('garbage')).toBeNull()
    expect(dayFromIso(null)).toBeNull()
    expect(dayFromIso(undefined)).toBeNull()
  })

  test('dayToUtcMs parses strict days and rejects garbage', () => {
    expect(dayToUtcMs('2025-05-01')).toBe(Date.UTC(2025, 4, 1))
    expect(dayToUtcMs('2025-05')).toBeNull()
    expect(dayToUtcMs('')).toBeNull()
  })
})

describe('sortDatesDescending', () => {
  test('sorts newest first; null dates sink to the end (stable)', () => {
    const sorted = sortDatesDescending([
      { date: '2025-04-01' },
      { date: null },
      { date: '2025-05-18' },
      { date: null },
      { date: '2025-04-20' },
    ])
    expect(sorted.map((entry) => entry.date)).toEqual([
      '2025-05-18',
      '2025-04-20',
      '2025-04-01',
      null,
      null,
    ])
  })

  test('does not mutate the backend array', () => {
    const input = [{ date: '2025-05-01' }, { date: '2025-05-18' }]
    sortDatesDescending(input)
    expect(input.map((entry) => entry.date)).toEqual(['2025-05-01', '2025-05-18'])
  })
})

describe('daysSinceDay / isFreshDay', () => {
  // Fixed "now" so the tests never drift: 2025-05-20T12:00:00Z
  const NOW = Date.UTC(2025, 4, 20, 12, 0, 0)

  test('whole days between the day and now', () => {
    expect(daysSinceDay('2025-05-20', NOW)).toBe(0)
    expect(daysSinceDay('2025-05-01', NOW)).toBe(19)
    expect(daysSinceDay('2025-05-01T00:00:00Z', NOW)).toBe(19)
  })

  test('future days clamp to 0; invalid days return null', () => {
    expect(daysSinceDay('2025-05-25', NOW)).toBe(0)
    expect(daysSinceDay('garbage', NOW)).toBeNull()
    expect(daysSinceDay(null, NOW)).toBeNull()
  })

  test('freshness uses the 16-day revisit window by default', () => {
    expect(isFreshDay('2025-05-10', undefined, NOW)).toBe(true) // 10 days
    expect(isFreshDay('2025-05-04', undefined, NOW)).toBe(true) // exactly 16
    expect(isFreshDay('2025-05-03', undefined, NOW)).toBe(false) // 17 days
  })

  test('a custom window is honored', () => {
    expect(isFreshDay('2025-05-01', 30, NOW)).toBe(true)
    expect(isFreshDay('2025-05-01', 10, NOW)).toBe(false)
  })
})

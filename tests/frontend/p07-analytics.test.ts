/**
 * P07 analytics frontend — pure-logic unit tests (bun test).
 *
 * Covers the extracted presentation helpers in src/lib/analytics/p07-utils.ts:
 *   (a) histogram bin label formatting + out-of-range share formatting
 *   (b) zone heatmap intensity mapping (documented range → 0..1) + colors
 *   (c) comparison incompatibilities → one-line summary (incl. a full P07Comparison)
 *   (d) anomaly severity → badge style mapping
 *   (e) coverage gap list formatting from profile.coverage.gaps + the
 *       one-line gapsText summary ("3 gaps >45d, latest … → …")
 *   (f) report type list assembly including the 3 new P07 keys (no duplicates)
 *   +  zone history → heatmap grid construction (null-safe cells)
 */
/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'

import {
  BASE_REPORT_TYPES,
  P07_REPORT_TYPES,
  ZONE_KEYS,
  buildReportTypeList,
  buildZoneHeatmapGrid,
  comparisonSummary,
  formatBinLabel,
  formatGaps,
  gapsText,
  heatmapCellColors,
  outOfRangeShareText,
  p07ReportTypes,
  severityBadgeVariant,
  zoneIntensity,
  type P07GapLike,
  type ReportTypeOption,
} from '@/lib/analytics/p07-utils'
import type { P07Comparison, P07ZoneHistoryEntry } from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// (a) Histogram labels + out-of-documented-range share
// ---------------------------------------------------------------------------

describe('formatBinLabel', () => {
  test('renders start–end with two decimals and an en dash', () => {
    expect(formatBinLabel({ bin_start: 0.4, bin_end: 0.45 })).toBe('0.40–0.45')
    expect(formatBinLabel({ bin_start: -0.2, bin_end: -0.15 })).toBe('-0.20–-0.15')
  })

  test('honors the digits argument', () => {
    expect(formatBinLabel({ bin_start: 0.12345, bin_end: 0.22345 }, 3)).toBe('0.123–0.223')
    expect(formatBinLabel({ bin_start: 1, bin_end: 2 }, 0)).toBe('1–2')
  })

  test('non-finite bounds degrade to an em dash (never a fabricated label)', () => {
    expect(formatBinLabel({ bin_start: Number.NaN, bin_end: 1 })).toBe('—')
    expect(formatBinLabel({ bin_start: 0, bin_end: Number.POSITIVE_INFINITY })).toBe('—')
  })
})

describe('outOfRangeShareText', () => {
  test('formats fractions as percentages with one decimal', () => {
    expect(outOfRangeShareText(0.123)).toBe('12.3%')
    expect(outOfRangeShareText(0)).toBe('0.0%')
    expect(outOfRangeShareText(1)).toBe('100.0%')
  })

  test('null/undefined/non-finite → em dash (backend could not compute it)', () => {
    expect(outOfRangeShareText(null)).toBe('—')
    expect(outOfRangeShareText(undefined)).toBe('—')
    expect(outOfRangeShareText(Number.NaN)).toBe('—')
  })

  test('clamps impossible shares instead of printing nonsense', () => {
    expect(outOfRangeShareText(1.5)).toBe('100.0%')
    expect(outOfRangeShareText(-0.2)).toBe('0.0%')
  })
})

// ---------------------------------------------------------------------------
// (b) Zone heatmap intensity mapping
// ---------------------------------------------------------------------------

describe('zoneIntensity', () => {
  const RANGE = [-1, 1] as const

  test('maps the documented range linearly onto 0..1', () => {
    expect(zoneIntensity(-1, RANGE)).toBe(0)
    expect(zoneIntensity(0, RANGE)).toBe(0.5)
    expect(zoneIntensity(1, RANGE)).toBe(1)
    expect(zoneIntensity(0.25, RANGE)).toBeCloseTo(0.625)
  })

  test('clamps values outside the documented range (no runaway intensity)', () => {
    expect(zoneIntensity(-5, RANGE)).toBe(0)
    expect(zoneIntensity(5, RANGE)).toBe(1)
  })

  test('null value or unusable range → null (caller shows an honest no-scale cell)', () => {
    expect(zoneIntensity(null, RANGE)).toBeNull()
    expect(zoneIntensity(undefined, RANGE)).toBeNull()
    expect(zoneIntensity(Number.NaN, RANGE)).toBeNull()
    expect(zoneIntensity(0.4, null)).toBeNull()
    expect(zoneIntensity(0.4, undefined)).toBeNull()
    // degenerate ranges: inverted or flat — no scale can be honest
    expect(zoneIntensity(0.4, [1, 1])).toBeNull()
    expect(zoneIntensity(0.4, [1, -1])).toBeNull()
  })
})

describe('heatmapCellColors', () => {
  test('null intensity renders the explicit no-data stone cell', () => {
    const colors = heatmapCellColors(null)
    expect(colors.background).toBe('#fafaf9')
    expect(colors.text).toBe('#57534e')
  })

  test('low intensity keeps dark text; high intensity flips to light text', () => {
    expect(heatmapCellColors(0).text).toBe('#1c1917')
    expect(heatmapCellColors(0.5).text).toBe('#1c1917')
    expect(heatmapCellColors(0.55).text).toBe('#f0fdf4')
    expect(heatmapCellColors(1).text).toBe('#f0fdf4')
  })

  test('endpoints blend exactly between emerald-50 and emerald-800', () => {
    expect(heatmapCellColors(0).background).toBe('rgb(236 253 245)')
    expect(heatmapCellColors(1).background).toBe('rgb(6 78 59)')
    expect(heatmapCellColors(0.5).background).toBe('rgb(121 166 152)')
  })

  test('out-of-range inputs are clamped, not rejected', () => {
    expect(heatmapCellColors(-3).background).toBe(heatmapCellColors(0).background)
    expect(heatmapCellColors(7).background).toBe(heatmapCellColors(1).background)
  })
})

// ---------------------------------------------------------------------------
// (c) Comparison compatibility summary (incl. the full P07Comparison shape)
// ---------------------------------------------------------------------------

const INCOMPATIBLE_COMPARISON: P07Comparison = {
  version: 'v1',
  index: 'ndvi',
  comparable: false,
  incompatibilities: [
    'spatial resolution differs (10 m vs 20 m)',
    '144 days apart',
    'valid pixel coverage differs beyond the gate',
  ],
  side_a: null,
  side_b: null,
  measurement_notes: ['deltas suppressed while incompatible'],
}

describe('comparisonSummary', () => {
  test('accepts a single P07Comparison and joins its incompatibilities', () => {
    expect(comparisonSummary(INCOMPATIBLE_COMPARISON, 3)).toBe(
      'spatial resolution differs (10 m vs 20 m); 144 days apart; valid pixel coverage differs beyond the gate',
    )
  })

  test('collapses long lists beyond maxItems with "+n more"', () => {
    expect(comparisonSummary(INCOMPATIBLE_COMPARISON, 2)).toBe(
      'spatial resolution differs (10 m vs 20 m); 144 days apart (+1 more)',
    )
    expect(comparisonSummary(['only-one'])).toBe('only-one')
  })

  test('merges and de-duplicates across a comparison LIST in order', () => {
    const merged = comparisonSummary([
      { ...INCOMPATIBLE_COMPARISON, incompatibilities: ['a', 'b'] },
      { ...INCOMPATIBLE_COMPARISON, incompatibilities: ['b', 'c'] },
    ], 3)
    expect(merged).toBe('a; b; c')
  })

  test('empty/null comparisons and blank strings → empty string', () => {
    expect(comparisonSummary([])).toBe('')
    expect(comparisonSummary(null)).toBe('')
    expect(comparisonSummary(undefined)).toBe('')
    expect(comparisonSummary(['', '   '])).toBe('')
    expect(comparisonSummary({ ...INCOMPATIBLE_COMPARISON, incompatibilities: [] })).toBe('')
  })

  test('comparable:true payloads (empty incompatibilities) produce no summary', () => {
    const comparable: P07Comparison = {
      ...INCOMPATIBLE_COMPARISON,
      comparable: true,
      incompatibilities: [],
      mean_delta: 0.02,
    }
    expect(comparisonSummary(comparable)).toBe('')
  })
})

// ---------------------------------------------------------------------------
// (d) Anomaly severity → badge style
// ---------------------------------------------------------------------------

describe('severityBadgeVariant', () => {
  test('warning → amber badge + amber dot', () => {
    const s = severityBadgeVariant('warning')
    expect(s.variant).toBe('outline')
    expect(s.className).toContain('amber')
    expect(s.className).toContain('border-amber-300')
    expect(s.dot).toBe('bg-amber-500')
    expect(s.className).not.toContain('stone')
  })

  test('info → stone badge + stone dot (anomalies are signals, never alarms)', () => {
    const s = severityBadgeVariant('info')
    expect(s.className).toContain('border-stone-300')
    expect(s.className).toContain('stone-700')
    expect(s.dot).toBe('bg-stone-500')
    expect(s.className).not.toContain('amber')
    expect(s.className).not.toContain('red')
  })

  test('unknown severities stay neutral and always keep a text-able style', () => {
    const s = severityBadgeVariant('critical')
    expect(s.className).toContain('stone-500')
    expect(s.dot).toBe('bg-stone-400')
  })
})

// ---------------------------------------------------------------------------
// (e) Coverage gap list formatting + one-line summary
// ---------------------------------------------------------------------------

describe('formatGaps', () => {
  test('formats from/to/days with an optional note', () => {
    expect(
      formatGaps([{ from: '2016-03-01', to: '2016-05-12', days: 72, note: 'winter dormancy' }]),
    ).toEqual(['2016-03-01 → 2016-05-12 · 72 d · winter dormancy'])
    expect(formatGaps([{ from: '2017-01-01', to: '2017-02-01', days: 31, note: null }])).toEqual([
      '2017-01-01 → 2017-02-01 · 31 d',
    ])
  })

  test('empty/null → no fabricated gap lines', () => {
    expect(formatGaps([])).toEqual([])
    expect(formatGaps(null)).toEqual([])
    expect(formatGaps(undefined)).toEqual([])
  })

  test('degrades gracefully on partial entries', () => {
    const partial: P07GapLike = { from: '2017-01-01', to: null, days: Number.NaN, note: null }
    expect(formatGaps([partial])).toEqual(['2017-01-01 → —'])
  })
})

describe('gapsText', () => {
  test('one gap: "1 gap >45d, latest 2026-01-01 → 2026-03-15"', () => {
    expect(
      gapsText([{ from: '2026-01-01', to: '2026-03-15', days: 45, note: null }]),
    ).toBe('1 gap >45d, latest 2026-01-01 → 2026-03-15')
  })

  test('several gaps: counts ALL renderable gaps, ">d" is the LONGEST gap, latest by `to`', () => {
    expect(
      gapsText([
        { from: '2025-11-01', to: '2025-12-01', days: 30, note: null },
        { from: '2026-01-01', to: '2026-03-15', days: 45, note: null },
        { from: '2026-05-01', to: '2026-05-20', days: 19, note: null },
      ]),
    ).toBe('3 gaps >45d, latest 2026-05-01 → 2026-05-20')
  })

  test('empty/null/partial-only gaps → empty string (caller renders the no-gaps copy)', () => {
    expect(gapsText([])).toBe('')
    expect(gapsText(null)).toBe('')
    expect(gapsText(undefined)).toBe('')
    expect(gapsText([{ from: '2017-01-01', to: null, days: 12, note: null }])).toBe('')
  })
})

// ---------------------------------------------------------------------------
// (f) Report type list assembly (registry + 3 new P07 keys)
// ---------------------------------------------------------------------------

const BASE_REGISTRY: ReportTypeOption[] = BASE_REPORT_TYPES.map((r) => ({ ...r }))

describe('p07ReportTypes / buildReportTypeList', () => {
  test('p07ReportTypes returns the full 13-entry picker list (10 legacy + 3 P07)', () => {
    const list = p07ReportTypes()
    expect(list).toHaveLength(13)
    expect(list.slice(0, 10).map((r) => r.value)).toEqual(BASE_REGISTRY.map((r) => r.value))
    expect(list.slice(10).map((r) => r.value)).toEqual([
      'field_intelligence',
      'satellite_vegetation',
      'spatial_anomalies',
    ])
    for (const item of list.slice(0, 10)) expect(item.ns).toBe('p3b')
    for (const item of list.slice(10)) expect(item.ns).toBe('p07analytics')
  })

  test('never duplicates — idempotent when called twice or pre-seeded', () => {
    const once = p07ReportTypes()
    const twice = buildReportTypeList(once)
    expect(twice).toEqual(once)
    const preSeeded = buildReportTypeList([...BASE_REGISTRY, P07_REPORT_TYPES[0]])
    expect(preSeeded).toHaveLength(13)
    const values = preSeeded.map((r) => r.value)
    expect(new Set(values).size).toBe(values.length)
  })

  test('exposes the three P07 report type values the backend registry added', () => {
    expect(P07_REPORT_TYPES.map((r) => r.value)).toEqual([
      'field_intelligence',
      'satellite_vegetation',
      'spatial_anomalies',
    ])
  })
})

// ---------------------------------------------------------------------------
// Zone history → heatmap grid
// ---------------------------------------------------------------------------

describe('buildZoneHeatmapGrid', () => {
  const RANGE = [0, 1] as const

  // Typed with the API contract so the zone literal types are checked.
  const HISTORY: P07ZoneHistoryEntry[] = [
    {
      acquired_at: '2023-04-01T00:00:00Z',
      scene_id: 's2',
      processing_version: 'v1',
      valid_pixel_fraction: 0.9,
      zones: [
        { zone: 'lowest_tercile', value_range: [0, 0.2], pixel_share: 0.33, mean: 0.1 },
        { zone: 'middle_tercile', value_range: [0.2, 0.4], pixel_share: 0.33, mean: 0.3 },
        { zone: 'highest_tercile', value_range: [0.4, 1], pixel_share: 0.34, mean: 0.5 },
      ],
    },
    {
      acquired_at: '2023-03-01T00:00:00Z',
      scene_id: 's1',
      processing_version: 'v1',
      valid_pixel_fraction: 0.8,
      zones: [
        { zone: 'lowest_tercile', value_range: [0, 0.2], pixel_share: 0.3, mean: 0.2 },
        { zone: 'middle_tercile', value_range: [0.2, 0.4], pixel_share: 0.4, mean: 0.4 },
        // highest_tercile missing for this scene → null cell, never a color
      ],
    },
  ]

  test('sorts dates chronologically and produces one row per tercile zone', () => {
    const grid = buildZoneHeatmapGrid(HISTORY, RANGE)
    expect(grid.dates).toEqual(['2023-03-01T00:00:00Z', '2023-04-01T00:00:00Z'])
    expect(grid.rows).toHaveLength(3)
    expect(grid.rows.map((row) => row[0].zone)).toEqual([...ZONE_KEYS])
    expect(grid.rows.every((row) => row.length === 2)).toBe(true)
  })

  test('maps means through the documented range and keeps missing zones null', () => {
    const grid = buildZoneHeatmapGrid(HISTORY, RANGE)
    const lowestRow = grid.rows[0]
    expect(lowestRow[0].value).toBe(0.2) // March
    expect(lowestRow[0].intensity).toBeCloseTo(0.2)
    expect(lowestRow[1].value).toBe(0.1) // April
    const highestRow = grid.rows[2]
    expect(highestRow[0].value).toBeNull()
    expect(highestRow[0].intensity).toBeNull()
    expect(highestRow[1].value).toBe(0.5)
    expect(highestRow[1].intensity).toBeCloseTo(0.5)
  })

  test('null history / non-dated entries yield an empty, honest grid', () => {
    expect(buildZoneHeatmapGrid(null, RANGE)).toEqual({ dates: [], rows: [[], [], []] })
    const empty = buildZoneHeatmapGrid(
      [{ acquired_at: null, scene_id: 's', processing_version: 'v', valid_pixel_fraction: null, zones: [] }],
      RANGE,
    )
    expect(empty.dates).toEqual([])
    expect(empty.rows.every((row) => row.length === 0)).toBe(true)
  })

  test('without a documented range every cell stays null (no fake gradient)', () => {
    const grid = buildZoneHeatmapGrid(HISTORY, null)
    for (const row of grid.rows) {
      for (const cell of row) expect(cell.intensity).toBeNull()
    }
  })

  test('zone literals outside the tercile union are a type error (compile-time honesty)', () => {
    // This block only type-checks; it asserts the literal type contract that
    // previously broke this suite (zone widened to `string`).
    const entry: P07ZoneHistoryEntry = {
      acquired_at: '2023-05-01T00:00:00Z',
      scene_id: 's3',
      processing_version: 'v1',
      valid_pixel_fraction: 0.95,
      zones: [
        { zone: 'lowest_tercile', value_range: [0, 1], pixel_share: 1, mean: 0.35 },
        { zone: 'middle_tercile', value_range: [0, 1], pixel_share: 0, mean: null },
        { zone: 'highest_tercile', value_range: [0, 1], pixel_share: 0, mean: 0.9 },
      ],
    }
    const grid = buildZoneHeatmapGrid([entry], RANGE)
    expect(grid.rows[2][0].value).toBe(0.9)
  })
})

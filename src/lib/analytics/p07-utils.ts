/**
 * P07 analytics — pure presentation logic, extracted for unit testing
 * (tests/frontend/p07-analytics.test.ts). NO React, NO fetch, NO store:
 * every function is deterministic and null-safe.
 *
 * Honesty rules encoded here:
 *   - null/absent values format to an em dash, never a fabricated number.
 *   - zone intensity is normalized INSIDE the index's documented range
 *     (values outside clamp, invalid ranges return null so callers can show
 *     an honest "no scale" state instead of a fake gradient).
 *   - incompatible comparisons are summarized as text only — never rendered
 *     as if a delta were valid.
 *   - anomaly signals are styled as signals (amber warning / stone info);
 *     nothing here can ever produce a "diagnosis" affordance.
 */

import type {
  P07Comparison,
  P07HistogramBin,
  P07ZoneHistoryEntry,
} from '@/lib/types-p07'
import type { SatelliteProfileGap } from '@/lib/types'

// ---------------------------------------------------------------------------
// (a) Histogram bin labels + out-of-documented-range share
// ---------------------------------------------------------------------------

/** "0.40–0.45" — en dash, fixed decimals, negative-safe. */
export function formatBinLabel(
  bin: Pick<P07HistogramBin, 'bin_start' | 'bin_end'>,
  digits = 2,
): string {
  const start = Number(bin.bin_start)
  const end = Number(bin.bin_end)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—'
  return `${start.toFixed(digits)}–${end.toFixed(digits)}`
}

/**
 * Share of pixels outside the documented index range, as "12.3%".
 * Returns '—' when the backend could not compute it (null), and clamps
 * the fraction to [0, 1] so a bad payload can never print nonsense.
 */
export function outOfRangeShareText(
  share: number | null | undefined,
  digits = 1,
): string {
  if (share === null || share === undefined || !Number.isFinite(share)) return '—'
  const clamped = Math.min(1, Math.max(0, share))
  return `${(clamped * 100).toFixed(digits)}%`
}

// ---------------------------------------------------------------------------
// (b) Zone heatmap color scale (documented-range normalization)
// ---------------------------------------------------------------------------

/**
 * Map a value into a 0..1 intensity inside the documented [min, max] range.
 * Returns null when the value or the range is unusable — the caller must
 * then render an explicit "no scale" cell, never a default color.
 */
export function zoneIntensity(
  value: number | null | undefined,
  documentedRange: readonly [number, number] | null | undefined,
): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null
  if (!documentedRange || documentedRange.length !== 2) return null
  const [min, max] = documentedRange
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null
  const t = (value - min) / (max - min)
  return Math.min(1, Math.max(0, t))
}

/** Light end of the scale (emerald-50) and dark end (emerald-800). */
const HEATMAP_LOW: [number, number, number] = [236, 253, 245]
const HEATMAP_HIGH: [number, number, number] = [6, 78, 59]

function mix(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t)
}

/**
 * Cell colors for intensity 0..1. The background blends emerald-50 →
 * emerald-800 and the text flips to white once the background gets dark,
 * so color is never the only signal at any contrast level.
 */
export function heatmapCellColors(intensity: number | null): {
  background: string
  text: string
} {
  if (intensity === null || !Number.isFinite(intensity)) {
    return { background: '#fafaf9', text: '#57534e' } // stone-100 / stone-600
  }
  const t = Math.min(1, Math.max(0, intensity))
  const background = `rgb(${mix(HEATMAP_LOW[0], HEATMAP_HIGH[0], t)} ${mix(
    HEATMAP_LOW[1],
    HEATMAP_HIGH[1],
    t,
  )} ${mix(HEATMAP_LOW[2], HEATMAP_HIGH[2], t)})`
  return { background, text: t >= 0.55 ? '#f0fdf4' : '#1c1917' } // white-ish / stone-900
}

// ---------------------------------------------------------------------------
// (c) Comparison compatibility summary (one line, for badges/alerts)
// ---------------------------------------------------------------------------

/**
 * Join the backend's incompatibility strings into ONE line. Accepts a single
 * P07Comparison, a list of them (incompatibilities merged + de-duplicated in
 * order), or a plain string list. At most `maxItems` are shown verbatim; the
 * rest collapse into "+n more". Empty/null → '' (callers decide the honest
 * "comparable" copy).
 */
export function comparisonSummary(
  comparisons:
    | P07Comparison
    | string
    | readonly (P07Comparison | string | null | undefined)[]
    | null
    | undefined,
  maxItems = 2,
): string {
  const list =
    comparisons === null || comparisons === undefined
      ? []
      : Array.isArray(comparisons)
        ? comparisons
        : [comparisons]
  const items: string[] = []
  for (const entry of list) {
    if (!entry || typeof entry !== 'object') {
      if (typeof entry === 'string' && entry.trim() !== '' && !items.includes(entry)) {
        items.push(entry)
      }
      continue
    }
    for (const raw of entry.incompatibilities ?? []) {
      if (typeof raw === 'string' && raw.trim() !== '' && !items.includes(raw)) {
        items.push(raw)
      }
    }
  }
  if (items.length === 0) return ''
  const shown = items.slice(0, Math.max(1, maxItems)).join('; ')
  const rest = items.length - Math.max(1, maxItems)
  return rest > 0 ? `${shown} (+${rest} more)` : shown
}

// ---------------------------------------------------------------------------
// (d) Anomaly severity → badge style mapping (color is never the only signal)
// ---------------------------------------------------------------------------

export type AnomalySeverity = 'warning' | 'info'

export interface SeverityBadgeVariant {
  /** Always 'outline' — severity is NEVER communicated by a filled destructive badge. */
  variant: 'outline'
  /** Badge outline classes — amber for warning, stone for info. */
  className: string
  /** Status-dot class rendered next to the text label. */
  dot: string
}

export function severityBadgeVariant(severity: string): SeverityBadgeVariant {
  switch (severity) {
    case 'warning':
      return {
        variant: 'outline',
        className: 'border-amber-300 bg-amber-50 text-amber-800',
        dot: 'bg-amber-500',
      }
    case 'info':
      return {
        variant: 'outline',
        className: 'border-stone-300 bg-stone-100 text-stone-700',
        dot: 'bg-stone-500',
      }
    default:
      // Unknown severity from a future backend: neutral, still labeled.
      return {
        variant: 'outline',
        className: 'border-stone-200 bg-stone-50 text-stone-500',
        dot: 'bg-stone-400',
      }
  }
}

// ---------------------------------------------------------------------------
// (e) Coverage gap formatting from profile.coverage.gaps
// ---------------------------------------------------------------------------

/** Null-safe gap shape — the strict API type satisfies it structurally. */
export interface P07GapLike {
  from?: string | null
  to?: string | null
  days?: number | null
  note?: string | null
}

/** One "from → to · n days · note" line per gap; never a fabricated range. */
export function formatGaps(
  gaps: readonly (SatelliteProfileGap | P07GapLike)[] | null | undefined,
): string[] {
  if (!gaps || gaps.length === 0) return []
  return gaps.map((gap) => {
    const from = gap?.from ?? '—'
    const to = gap?.to ?? '—'
    const days = Number(gap?.days)
    const daysText = Number.isFinite(days) ? `${days} d` : ''
    const note = typeof gap?.note === 'string' && gap.note.trim() !== '' ? ` · ${gap.note}` : ''
    return `${from} → ${to}${daysText ? ` · ${daysText}` : ''}${note}`
  })
}

/**
 * ONE-line coverage-gap summary: "3 gaps >45d, latest 2026-01-01 → 2026-03-15".
 * Only gaps with BOTH endpoints are counted and the "latest" is the gap whose
 * `to` is greatest (strict ISO string compare is safe for ISO-8601 dates).
 * The ">Nd" figure is the LONGEST gap — never invented, 0 when unknown.
 * Returns '' for no renderable gaps (callers show the "no gaps" copy).
 */
export function gapsText(gaps: readonly (SatelliteProfileGap | P07GapLike)[] | null | undefined): string {
  const list = (gaps ?? []).filter((g) => g && typeof g === 'object')
  const renderable = list.filter(
    (g) => typeof g.from === 'string' && g.from !== '' && typeof g.to === 'string' && g.to !== '',
  )
  if (renderable.length === 0) return ''
  const count = renderable.length
  const longest = renderable.reduce((max, g) => {
    const days = Number(g.days)
    return Number.isFinite(days) && days > max ? days : max
  }, 0)
  const latest = renderable.reduce((acc, g) => ((g.to as string) > (acc.to as string) ? g : acc))
  const noun = count === 1 ? 'gap' : 'gaps'
  return `${count} ${noun} >${Math.round(longest)}d, latest ${latest.from} → ${latest.to}`
}

// ---------------------------------------------------------------------------
// (f) Report type list assembly (registry + the 3 new P07 keys, no duplicates)
// ---------------------------------------------------------------------------

export interface ReportTypeOption {
  value: string
  /** i18n key inside the owning namespace (p3b.reports.* or p07analytics.reportTypes.*). */
  labelKey: string
  /** Message namespace that owns labelKey; defaults to 'p3b' for the legacy 10. */
  ns?: 'p3b' | 'p07analytics'
}

/**
 * The fixed legacy registry — mirrors app/reports/contracts.py REPORT_TYPES
 * (verified against migration 0023, which appends ONLY the three P07 keys).
 */
export const BASE_REPORT_TYPES: readonly ReportTypeOption[] = [
  { value: 'farm_performance', labelKey: 'typeFarmPerformance', ns: 'p3b' },
  { value: 'field_analysis', labelKey: 'typeFieldAnalysis', ns: 'p3b' },
  { value: 'soil_health', labelKey: 'typeSoilHealth', ns: 'p3b' },
  { value: 'water', labelKey: 'typeWater', ns: 'p3b' },
  { value: 'rotation', labelKey: 'typeRotation', ns: 'p3b' },
  { value: 'seasonal', labelKey: 'typeSeasonal', ns: 'p3b' },
  { value: 'environmental_risk', labelKey: 'typeEnvironmentalRisk', ns: 'p3b' },
  { value: 'recommendations', labelKey: 'typeRecommendations', ns: 'p3b' },
  { value: 'org_executive', labelKey: 'typeOrgExecutive', ns: 'p3b' },
  { value: 'custom_range', labelKey: 'typeCustomRange', ns: 'p3b' },
]

/** The three P07 report types added to the backend registry (0023 migration). */
export const P07_REPORT_TYPES: readonly ReportTypeOption[] = [
  { value: 'field_intelligence', labelKey: 'fieldIntelligence', ns: 'p07analytics' },
  { value: 'satellite_vegetation', labelKey: 'satelliteVegetation', ns: 'p07analytics' },
  { value: 'spatial_anomalies', labelKey: 'spatialAnomalies', ns: 'p07analytics' },
]

/**
 * Merge the fixed registry with the P07 additions. Existing entries win
 * (idempotent — calling twice never duplicates), order is stable.
 */
export function buildReportTypeList(
  base: readonly ReportTypeOption[],
  extra: readonly ReportTypeOption[] = P07_REPORT_TYPES,
): ReportTypeOption[] {
  const seen = new Set(base.map((r) => r.value))
  const merged = base.map((r) => ({ ...r }))
  for (const item of extra) {
    if (seen.has(item.value)) continue
    seen.add(item.value)
    merged.push({ ...item })
  }
  return merged
}

/**
 * The FULL report-type picker list (legacy 10 + the 3 new P07 keys, deduped).
 * This is the single place the list is assembled — the Reports tab renders it
 * directly so no report type can be silently dropped or duplicated.
 */
export function p07ReportTypes(): ReportTypeOption[] {
  return buildReportTypeList(BASE_REPORT_TYPES)
}

// ---------------------------------------------------------------------------
// Zone history → heatmap grid helpers
// ---------------------------------------------------------------------------

export const ZONE_KEYS = ['lowest_tercile', 'middle_tercile', 'highest_tercile'] as const

export type ZoneKey = (typeof ZONE_KEYS)[number]

export interface HeatmapCell {
  date: string
  zone: ZoneKey
  /** Zone mean — null when the backend could not compute it for that cell. */
  value: number | null
  intensity: number | null
}

/**
 * Build the heatmap grid from zone_history: one row per zone key, one column
 * per scene date (chronological, null-safe). Cells whose entry lacks the zone
 * get value null — rendered as "no data", never as a color.
 */
export function buildZoneHeatmapGrid(
  zoneHistory: readonly P07ZoneHistoryEntry[] | null | undefined,
  documentedRange: readonly [number, number] | null | undefined,
): { dates: string[]; rows: HeatmapCell[][] } {
  const entries = (zoneHistory ?? []).filter(
    (e) => e && typeof e.acquired_at === 'string' && e.acquired_at !== '',
  )
  const dates = entries
    .map((e) => e.acquired_at as string)
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  const byDate = new Map(entries.map((e) => [e.acquired_at as string, e]))
  const rows: HeatmapCell[][] = []
  for (const zone of ZONE_KEYS) {
    const row: HeatmapCell[] = dates.map((date) => {
      const zoneSummary = byDate.get(date)?.zones.find((z) => z?.zone === zone)
      const value = zoneSummary?.mean ?? null
      const intensity = zoneIntensity(value, documentedRange)
      return { date, zone, value, intensity }
    })
    rows.push(row)
  }
  return { dates, rows }
}

/**
 * P07 map — pure temporal / layer-management logic.
 *
 * Everything here is a PURE function (no React, no DOM, no network) so the
 * bun tests in tests/frontend/p07-map.test.ts can exercise it directly.
 *
 * Honesty rules encoded here:
 *   - Gaps are computed from the backend's own dates_available list. A gap is
 *     REPORTED ("no observation between"), never interpolated.
 *   - Temporal compatibility compares acquisition days across simultaneously
 *     visible vegetation layers; differing days are flagged, never merged.
 */

// Type-only imports — erased at build time, the module stays side-effect free.
import type {
  P07EnvironmentLayer,
  P07InfrastructureLayer,
  P07LayerCatalog,
  P07VegetationLayer,
} from '../types-p07'

export interface P07DateGap {
  /** First available day before the gap (ISO day, YYYY-MM-DD). */
  from: string
  /** First available day after the gap (ISO day, YYYY-MM-DD). */
  to: string
  /** Whole days between `from` and `to` (> minGapDays). */
  days: number
}

export interface TemporalCompatibilityInput {
  /** Stable layer id. */
  id: string
  /** Selected acquisition day (YYYY-MM-DD) or null when unknown. */
  date: string | null
}

export interface TemporalCompatibilityResult {
  /** True when every dated visible layer shares the same acquisition day. */
  compatible: boolean
  /** Distinct acquisition days among the dated layers (ascending). */
  distinctDates: string[]
  /** Ids of the layers that carry a date (undated layers are ignored). */
  datedLayerIds: string[]
  /** Number of compared layers (dated only). */
  compared: number
}

const MS_PER_DAY = 86_400_000

/** Parse a strict ISO day (YYYY-MM-DD) to UTC epoch ms; null when invalid. */
export function dayToUtcMs(day: string | null | undefined): number | null {
  if (!day || day.length < 10) return null
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(day)
  if (!match) return null
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isFinite(ms) ? ms : null
}

/** Normalize any ISO timestamp/day to its YYYY-MM-DD day part; null when invalid. */
export function dayFromIso(iso: string | null | undefined): string | null {
  if (!iso) return null
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(iso)
  return match ? match[1] : null
}

/**
 * Compute coverage gaps between consecutive available dates, sorted ascending
 * and deduplicated. A gap is flagged only when the distance is STRICTLY
 * greater than `minGapDays` (default 16 — the nominal revisit cadence).
 * Null/invalid dates are ignored: only real observations count.
 */
export function computeDateGaps(
  dates: Array<string | null | undefined>,
  minGapDays = 16,
): P07DateGap[] {
  const days = Array.from(
    new Set(
      dates
        .map((value) => dayFromIso(value))
        .filter((day): day is string => !!day && dayToUtcMs(day) !== null),
    ),
  ).sort()
  const gaps: P07DateGap[] = []
  for (let i = 1; i < days.length; i += 1) {
    const fromMs = dayToUtcMs(days[i - 1])
    const toMs = dayToUtcMs(days[i])
    if (fromMs === null || toMs === null) continue
    const diffDays = Math.round((toMs - fromMs) / MS_PER_DAY)
    if (diffDays > minGapDays) {
      gaps.push({ from: days[i - 1], to: days[i], days: diffDays })
    }
  }
  return gaps
}

/**
 * Whole days between an ISO day and `nowMs` (default: actual now). Negative
 * results (future-dated entries) are clamped to 0; null when the day is
 * invalid — the badge is simply not rendered in that case.
 */
export function daysSinceDay(day: string | null | undefined, nowMs: number = Date.now()): number | null {
  const ms = dayToUtcMs(typeof day === 'string' ? day.slice(0, 10) : null)
  if (ms === null) return null
  const today = dayToUtcMs(dayFromIso(new Date(nowMs).toISOString()))
  if (today === null) return 0
  return Math.max(0, Math.round((today - ms) / MS_PER_DAY))
}

/** True when the layer's latest observation is within the freshness window. */
export function isFreshDay(day: string | null | undefined, freshWindowDays = 16, nowMs: number = Date.now()): boolean {
  const age = daysSinceDay(day, nowMs)
  return age !== null && age <= freshWindowDays
}

/**
 * Temporal compatibility of the simultaneously VISIBLE vegetation layers.
 * Only dated layers are compared; layers whose acquisition day is unknown
 * (null) are skipped rather than guessed. Compatible ⇔ at most one distinct
 * day among the compared layers.
 */
export function checkTemporalCompatibility(
  entries: TemporalCompatibilityInput[],
): TemporalCompatibilityResult {
  const dated = entries.filter((entry) => !!dayFromIso(entry.date))
  const distinctDates = Array.from(
    new Set(dated.map((entry) => dayFromIso(entry.date) as string)),
  ).sort()
  return {
    compatible: distinctDates.length <= 1,
    distinctDates,
    datedLayerIds: dated.map((entry) => entry.id),
    compared: dated.length,
  }
}

/**
 * Reorder a layer by one slot. The order array is the DRAW STACK seen
 * top-to-bottom: index 0 renders highest (highest MapLibre z-order).
 * "up" moves the layer one slot toward the top of the stack, "down" one slot
 * toward the bottom; both clamp at the ends. Unknown ids keep their position.
 */
export function moveLayerInOrder(
  order: string[],
  id: string,
  direction: 'up' | 'down',
): string[] {
  const index = order.indexOf(id)
  if (index < 0) return [...order]
  const target = direction === 'up' ? index - 1 : index + 1
  if (target < 0 || target >= order.length) return [...order]
  const next = [...order]
  const [moved] = next.splice(index, 1)
  next.splice(target, 0, moved)
  return next
}

/** MapLibre z-index of an order slot: slot 0 = top of stack = highest value. */
export function zIndexForOrderSlot(order: string[], id: string): number {
  const index = order.indexOf(id)
  if (index < 0) return 0
  return Math.max(0, order.length - 1 - index)
}

/** UI percent (0-100) → raster opacity fraction (0-1), clamped on both ends. */
export function opacityFraction(percent: number): number {
  const clamped = Math.min(100, Math.max(0, Number.isFinite(percent) ? percent : 0))
  return Math.round(clamped) / 100
}

export interface PartitionResult<T> {
  /** Renderable layers (manager rows with active controls). */
  available: T[]
  /** Visible-but-disabled rows; MUST stay rendered with their reason. */
  unavailable: T[]
}
/**
 * Split layers for the manager. Honesty contract: unavailable layers are NOT
 * dropped — they are partitioned so the manager can render them as disabled
 * rows with their backend `unavailable_reason`.
 */
export function partitionLayerAvailability<T extends { available: boolean }>(
  layers: T[],
): PartitionResult<T> {
  const available: T[] = []
  const unavailable: T[] = []
  for (const layer of layers) {
    if (layer.available) available.push(layer)
    else unavailable.push(layer)
  }
  return { available, unavailable }
}

/** Resolve the selected focus layer, falling back to the first available one. */
export function resolveFocusLayer<T extends { code: string; available: boolean }>(
  layers: readonly T[],
  preferredCode: string,
): T | null {
  return (
    layers.find((layer) => layer.code === preferredCode && layer.available) ??
    layers.find((layer) => layer.available) ??
    null
  )
}

/**
 * Sort backend dates_available entries newest-first (null dates sink to the
 * end, stable). Used by the date chips and per-layer date selects.
 */
export function sortDatesDescending<T extends { date: string | null }>(entries: T[]): T[] {
  return [...entries].sort((a, b) => {
    const aMs = dayToUtcMs(a.date)
    const bMs = dayToUtcMs(b.date)
    if (aMs === null && bMs === null) return 0
    if (aMs === null) return 1
    if (bMs === null) return -1
    return bMs - aMs
  })
}

// ---------------------------------------------------------------------------
// Mission-name aliases (P07 spec naming, kept as thin wrappers so both the
// spec names and the internal names are stable public API).
// ---------------------------------------------------------------------------

/** Spec alias for `moveLayerInOrder` (same clamping semantics). */
export const moveLayerOrder = moveLayerInOrder

/**
 * True when two ISO timestamps/days resolve to the SAME acquisition day.
 * Null/invalid inputs are never compatible — absence is not a match.
 */
export function datesAreCompatible(a: string | null | undefined, b: string | null | undefined): boolean {
  const da = dayFromIso(a)
  const db = dayFromIso(b)
  return da !== null && db !== null && da === db
}

/**
 * Split a full layer catalog into available vs UNAVAILABLE layers per group.
 * Honesty contract: unavailable layers are returned (never dropped) so the
 * manager can render them as disabled rows carrying their backend
 * `unavailable_reason`.
 */
export function unavailableLayers(catalog: P07LayerCatalog | null | undefined): {
  vegetation: P07VegetationLayer[]
  environment: P07EnvironmentLayer[]
  infrastructure: P07InfrastructureLayer[]
} {
  const vegetation: P07VegetationLayer[] = []
  const environment: P07EnvironmentLayer[] = []
  const infrastructure: P07InfrastructureLayer[] = []
  if (!catalog) return { vegetation, environment, infrastructure }
  for (const layer of catalog.layers.vegetation) {
    if (!layer.available) vegetation.push(layer)
  }
  for (const layer of catalog.layers.environment) {
    if (!layer.available) environment.push(layer)
  }
  for (const layer of catalog.layers.infrastructure) {
    if (!layer.available) infrastructure.push(layer)
  }
  return { vegetation, environment, infrastructure }
}

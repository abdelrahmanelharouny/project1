'use client'

/**
 * P07 — temporal explorer.
 *
 * Horizontal date chips + prev/next observation stepping for the focus
 * vegetation index, computed ONLY from the backend's own `dates_available`
 * entries:
 *   - gaps: consecutive available dates more than 16 days apart are REPORTED
 *     ("no observation between") — never interpolated, never filled;
 *   - freshness: days since the latest acquisition (16-day revisit window);
 *   - compatibility: when two simultaneously-visible vegetation layers carry
 *     different acquisition days, an amber banner states that the layers do
 *     NOT represent the same moment (nothing is merged or shifted).
 */

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { ChevronLeft, ChevronRight, TriangleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { P07IndexCode, P07LayerDates } from '@/lib/types-p07'
import {
  checkTemporalCompatibility,
  computeDateGaps,
  dayFromIso,
  daysSinceDay,
  isFreshDay,
  sortDatesDescending,
  type TemporalCompatibilityInput,
} from '@/lib/map/temporal'

export interface TemporalExplorerProps {
  /** Focus vegetation index (drives the header chip label only). */
  index: P07IndexCode
  /** Backend `dates_available` entries for the focus layer. */
  dates: P07LayerDates[]
  /** Selected acquisition day (YYYY-MM-DD) for the focus layer; null = latest. */
  selectedDay: string | null
  /** Select a different acquisition day (emits a real available day). */
  onSelectDay: (day: string) => void
  /**
   * Acquisition days of the simultaneously VISIBLE vegetation layers —
   * the temporal-compatibility banner compares these (dated entries only).
   */
  visibleLayerDates?: TemporalCompatibilityInput[]
  className?: string
}

export function TemporalExplorer({
  index,
  dates,
  selectedDay,
  onSelectDay,
  visibleLayerDates,
  className,
}: TemporalExplorerProps) {
  const t = useTranslations('p07map')

  const sorted = useMemo(() => sortDatesDescending(dates), [dates])

  // Ascending, deduplicated list of real acquisition days. Entries without a
  // parseable date never participate in navigation (nothing is guessed).
  const daysAscending = useMemo(() => {
    const days = new Set<string>()
    for (const entry of sorted) {
      const day = dayFromIso(entry.date)
      if (day) days.add(day)
    }
    return Array.from(days).sort()
  }, [sorted])

  const latestDay = daysAscending.length > 0 ? daysAscending[daysAscending.length - 1] : null
  const currentDay =
    selectedDay && daysAscending.includes(selectedDay) ? selectedDay : latestDay
  const currentIndex = currentDay ? daysAscending.indexOf(currentDay) : -1

  const gaps = useMemo(() => computeDateGaps(daysAscending, 16), [daysAscending])

  const freshnessAge = useMemo(
    () => (latestDay ? daysSinceDay(latestDay) : null),
    [latestDay],
  )
  const fresh = latestDay ? isFreshDay(latestDay, 16) : false

  const compatibility = useMemo(
    () => checkTemporalCompatibility(visibleLayerDates ?? []),
    [visibleLayerDates],
  )
  const showCompatWarning = compatibility.compared >= 2 && !compatibility.compatible

  if (sorted.length === 0) {
    return (
      <div
        className={cn(
          'flex h-16 items-center justify-center rounded-lg border border-dashed border-stone-300 bg-stone-50/60 px-3 text-sm text-stone-500',
          className,
        )}
        role="status"
      >
        {t('noDates')}
      </div>
    )
  }

  return (
    <div
      className={cn(
        'rounded-lg border border-stone-200 bg-white p-2.5',
        className,
      )}
      role="group"
      aria-label={t('temporalDescAria')}
    >
      {/* Header: title + focus index + freshness badge + prev/next stepping */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="text-xs font-semibold text-stone-800">{t('temporalTitle')}</h3>
          <span
            dir="ltr"
            className="rounded bg-emerald-50 px-1.5 py-px font-mono text-[10px] font-semibold text-emerald-900"
          >
            {index.toUpperCase()}
          </span>
          {freshnessAge !== null && (
            <Badge
              variant="outline"
              className={cn(
                'px-1.5 py-0 text-[10px]',
                fresh
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                  : 'border-amber-300 bg-amber-50 text-amber-900',
              )}
            >
              {fresh ? t('freshnessFresh', { days: freshnessAge }) : t('freshnessStale', { days: freshnessAge })}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-11 w-11 p-0 sm:h-8 sm:w-8"
            disabled={currentIndex <= 0}
            onClick={() => {
              if (currentIndex > 0) onSelectDay(daysAscending[currentIndex - 1])
            }}
            aria-label={t('prevAria')}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-11 w-11 p-0 sm:h-8 sm:w-8"
            disabled={currentIndex < 0 || currentIndex >= daysAscending.length - 1}
            onClick={() => {
              if (currentIndex < daysAscending.length - 1) onSelectDay(daysAscending[currentIndex + 1])
            }}
            aria-label={t('nextAria')}
          >
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>

      {/* Date chips — newest first, horizontal scroll; LTR so the strip reads
          chronologically right-to-left in Arabic exactly as it does in English. */}
      <div dir="ltr" className="mt-2">
        <div
          className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin"
          role="listbox"
          aria-label={t('temporalDescAria')}
        >
          {sorted.map((entry) => {
            const day = dayFromIso(entry.date)
            const selectable = day !== null
            const isSelected = selectable && day === currentDay
            return (
              <Button
                key={entry.scene_id}
                type="button"
                role="option"
                aria-selected={isSelected}
                aria-label={selectable ? t('selectedAria', { date: day as string }) : t('chipDateUnknown')}
                variant={isSelected ? 'default' : 'outline'}
                size="sm"
                disabled={!selectable}
                onClick={() => selectable && onSelectDay(day as string)}
                className={cn(
                  'h-11 shrink-0 px-2.5 font-mono text-[11px] sm:h-8',
                  isSelected ? 'bg-emerald-700 hover:bg-emerald-800' : 'bg-white',
                )}
              >
                {day ?? '—'}
              </Button>
            )
          })}
        </div>
      </div>

      {/* Temporal compatibility — only when ≥2 dated visible layers disagree */}
      {showCompatWarning && (
        <div
          className="mt-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50/70 p-2 text-[11px] text-amber-900"
          role="status"
        >
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <div>
            <p className="font-semibold">{t('compatWarning')}</p>
            <p dir="ltr" className="mt-0.5 font-mono text-[10px] text-amber-800">
              {compatibility.distinctDates.join(' · ')}
            </p>
          </div>
        </div>
      )}

      {/* Coverage gaps — reported, never interpolated */}
      <div className="mt-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-stone-400">
          {t('gapsTitle')}
        </p>
        {gaps.length > 0 ? (
          <ul className="mt-1 space-y-0.5 text-[11px] text-amber-900" role="list">
            {gaps.map((gap) => (
              <li key={`${gap.from}-${gap.to}`} className="tabular-nums" dir="ltr">
                {t('gapWindow', { from: gap.from, to: gap.to, days: gap.days })}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[11px] text-stone-500">
            {t('gapsNone', { days: 16 })}
          </p>
        )}
      </div>
    </div>
  )
}

export default TemporalExplorer

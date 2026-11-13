'use client'

/**
 * P07 — spatial colormap legend.
 *
 * One source of truth for the documented backend colormap (brown → white →
 * green, the SAME stops as the former P05 satellite-layers card) and the
 * documented per-index ranges (ndvi -1..1, evi -1..3, ndmi/ndwi/bsi -1..1).
 * Nothing is invented: the gradient describes the server-side tile rendering;
 * nodata pixels are rendered transparent by the backend and noted here.
 *
 * `SpatialLegend` renders as a collapsible absolute card on the map (top-start
 * corner); `IndexColormapBar` is reused inside every LayerManager legend
 * popover so both surfaces always agree.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { ChevronDown, Palette } from 'lucide-react'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import type { P07IndexCode } from '@/lib/types-p07'

/** Documented colormap of the backend tile renderer: brown → white → green. */
export const P07_COLORMAP_GRADIENT =
  'linear-gradient(to right, #8a5a2b, #f5f5f4 50%, #15803d)'

/** Backend `documented_range` values (live-verified) — never invented. */
export const P07_DOCUMENTED_RANGES: Record<P07IndexCode, [number, number]> = {
  ndvi: [-1, 1],
  evi: [-1, 3],
  ndmi: [-1, 1],
  ndwi: [-1, 1],
  bsi: [-1, 1],
}

function formatIndexValue(value: number): string {
  return `${value > 0 ? '+' : ''}${value}`
}

/**
 * Gradient bar + documented range labels. The bar itself stays LTR even in
 * Arabic (physical color direction must match the raster rendering).
 */
export function IndexColormapBar({
  index,
  className,
}: {
  index: P07IndexCode
  className?: string
}) {
  const t = useTranslations('p07map')
  const [min, max] = P07_DOCUMENTED_RANGES[index]
  const lowKey = index === 'ndvi' ? 'legendLowNdvi' : 'legendLow'
  const highKey = index === 'ndvi' ? 'legendHighNdvi' : 'legendHigh'
  return (
    <div dir="ltr" className={cn('space-y-1', className)}>
      <div
        className="h-3 w-full rounded-full border border-stone-200"
        style={{ background: P07_COLORMAP_GRADIENT }}
        aria-hidden
      />
      <div className="flex items-center justify-between text-[10px] text-stone-600">
        <span>
          <span className="font-semibold tabular-nums">{formatIndexValue(min)}</span>{' '}
          {t(lowKey)}
        </span>
        <span>
          {t(highKey)}{' '}
          <span className="font-semibold tabular-nums">{formatIndexValue(max)}</span>
        </span>
      </div>
    </div>
  )
}

/**
 * Collapsible legend card positioned absolutely on the map canvas. The map
 * canvas itself stays LTR; this card uses logical properties for placement.
 */
export function SpatialLegend({
  index,
  className,
  defaultOpen = true,
}: {
  index: P07IndexCode
  className?: string
  defaultOpen?: boolean
}) {
  const t = useTranslations('p07map')
  const [open, setOpen] = useState(defaultOpen)

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn(
        'rounded-lg border border-stone-200 bg-white/95 shadow-md backdrop-blur-sm',
        className,
      )}
    >
      <div
        role="group"
        aria-label={t('legendGroupAria', { index: index.toUpperCase() })}
        className="p-2"
      >
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-md px-1 text-start hover:bg-stone-50 sm:min-h-[32px]"
          >
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-stone-500">
              <Palette className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
              {t('legendCardTitle')}
              <span
                dir="ltr"
                className="rounded bg-stone-100 px-1 py-px font-mono text-[10px] normal-case text-stone-700"
              >
                {index.toUpperCase()}
              </span>
            </span>
            <ChevronDown
              className={cn(
                'h-3.5 w-3.5 shrink-0 text-stone-400 transition-transform',
                open && 'rotate-180',
              )}
              aria-hidden
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-1 pb-1 pt-1.5">
            <p className="mb-1 text-[10px] font-medium text-stone-500">{t('legendTitle')}</p>
            <IndexColormapBar index={index} />
            <p className="mt-1.5 text-[10px] text-stone-500">{t('legendNodata')}</p>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

export default SpatialLegend

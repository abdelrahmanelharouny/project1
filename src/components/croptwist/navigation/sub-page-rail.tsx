'use client'

/**
 * P02 W1 — sub-page rail for multi-sub destinations (blueprint §2.1:
 * "left sub-page rail + content pane"). One component, two responsive
 * presentations:
 *   - desktop (lg+): vertical rail on the content's left
 *   - below lg: horizontal chip row (active chip scrolled into view — the
 *     audit found zero `scrollIntoView` usage repo-wide; this adds it)
 *
 * Rendered as Radix Tabs triggers so the keyboard contract (arrow keys,
 * roving tabindex) carries over from the old tab strip. Every trigger is a
 * 44px touch target (audit P8).
 */

import { useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { Globe2 } from 'lucide-react'

import { TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { DestinationDef } from '@/lib/navigation'
import { cn } from '@/lib/utils'

export function SubPageRail({
  destination,
  activeSub,
  onSelect,
  orientation,
  className,
}: {
  destination: DestinationDef
  activeSub: string
  onSelect: (subId: string) => void
  orientation: 'vertical' | 'horizontal'
  className?: string
}) {
  const t = useTranslations('destinations')
  const activeChipRef = useRef<HTMLButtonElement | null>(null)
  const vertical = orientation === 'vertical'

  useEffect(() => {
    if (!vertical) {
      // Keep the active chip visible in the horizontal row without manual
      // scrolling (blueprint W1 item 1.4 "Active-tab scroll-into-view").
      activeChipRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }
  })

  return (
    <TabsList
      aria-label={t('subRailAria', { destination: t(destination.labelKey) })}
      className={cn(
        vertical
          ? 'h-auto w-full flex-col items-stretch justify-start gap-1 rounded-none bg-transparent p-0'
          : 'h-auto min-w-0 max-w-full w-full flex-nowrap justify-start gap-1 overflow-x-auto rounded-none border-b border-stone-200 bg-white p-1 scrollbar-none',
        className,
      )}
    >
      {destination.subPages.map((sub) => (
        <TabsTrigger
          key={sub.id}
          value={sub.id}
          ref={sub.id === activeSub && !vertical ? activeChipRef : undefined}
          onClick={() => onSelect(sub.id)}
          aria-label={t(`sub.${sub.labelKey}`)}
          className={cn(
            'min-h-11 shrink-0 justify-start gap-2 whitespace-nowrap rounded-md px-3 text-sm font-medium text-stone-600 data-[state=active]:bg-emerald-50 data-[state=active]:text-emerald-900 data-[state=active]:shadow-none',
            vertical ? 'w-full border-l-2 border-transparent data-[state=active]:border-emerald-700' : 'flex-none px-3.5',
          )}
        >
          {/* Portfolio is farm-scoped while its siblings are field-scoped —
              flagged in the rail per blueprint C4. */}
          {sub.id === 'portfolio' ? (
            <Globe2 className="h-3.5 w-3.5 shrink-0 text-teal-700" aria-hidden />
          ) : null}
          <span className={vertical ? 'truncate' : 'whitespace-nowrap'}>{t(`sub.${sub.labelKey}`)}</span>
        </TabsTrigger>
      ))}
    </TabsList>
  )
}

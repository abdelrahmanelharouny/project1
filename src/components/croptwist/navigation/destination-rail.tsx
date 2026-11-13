'use client'

/**
 * P02 W1 — desktop destination rail (nine primary destinations).
 *
 * Replaces the 27-tab strip (audit P1: 3,263px @1440px / 3,047px @390px).
 * Accessibility:
 *   - Radix Tabs primitives keep the existing keyboard contract (arrow keys,
 *     roving tabindex — audit U7 resolved by keeping the same primitive).
 *   - Touch targets raised to 44px (min-h-11) — audit P8.
 *   - aria-label on the tablist; visible focus rings from the primitive.
 */

import { useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import {
  BarChart3,
  ClipboardList,
  Droplets,
  GitBranch,
  LayoutDashboard,
  Map,
  Satellite,
  Settings2,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

import { TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DESTINATIONS, type DestinationId } from '@/lib/navigation'
import { cn } from '@/lib/utils'

/** Shared with the command palette (P03 W2.4) so destination commands keep
 * the same iconography as the rail. */
export const DESTINATION_ICONS: Record<DestinationId, LucideIcon> = {
  overview: LayoutDashboard,
  farms: Map,
  datahub: ClipboardList,
  cropintel: Droplets,
  geo: Satellite,
  decisions: GitBranch,
  copilot: Sparkles,
  reports: BarChart3,
  settings: Settings2,
}

export function DestinationRail({
  activeTab,
  onSelect,
  className,
}: {
  activeTab: DestinationId
  onSelect: (id: DestinationId) => void
  className?: string
}) {
  const t = useTranslations('destinations')
  const activeRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    // Safety net for viewports between lg and xl (or zoomed layouts): keep the
    // active destination visible without manual horizontal scrolling
    // (blueprint W1 item 1.4, applied to the rail as well as sub-chips).
    activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  })

  return (
    <TabsList
      aria-label={t('railAria')}
      className={cn(
        'h-auto w-full justify-start gap-0.5 overflow-x-auto rounded-none border-b border-stone-200 bg-white p-1 scrollbar-none sm:gap-1',
        className,
      )}
    >
      {DESTINATIONS.map((dest) => {
        const Icon = DESTINATION_ICONS[dest.id]
        return (
          <TabsTrigger
            key={dest.id}
            value={dest.id}
            ref={dest.id === activeTab ? activeRef : undefined}
            onClick={() => onSelect(dest.id)}
            aria-label={t(dest.labelKey)}
            className="min-h-11 shrink-0 gap-1.5 rounded-md px-2 text-sm font-medium text-stone-600 data-[state=active]:bg-emerald-50 data-[state=active]:text-emerald-900 data-[state=active]:shadow-none"
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span className="whitespace-nowrap">{t(dest.labelKey)}</span>
          </TabsTrigger>
        )
      })}
    </TabsList>
  )
}

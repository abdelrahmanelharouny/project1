'use client'

import { ChevronDown, Sprout } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { DESTINATION_ICONS } from '@/components/croptwist/navigation/destination-rail'
import { cn } from '@/lib/utils'
import {
  defaultSubFor,
  DESTINATIONS,
  type DestinationId,
} from '@/lib/navigation'

const SIDEBAR_GROUPS: {
  labelKey:
    | 'groupWorkspace'
    | 'groupDataIntelligence'
    | 'groupAgriculturalPlanning'
    | 'groupDecisionIntelligence'
    | 'groupInsights'
  destinations: DestinationId[]
}[] = [
  { labelKey: 'groupWorkspace', destinations: ['overview', 'farms', 'settings'] },
  { labelKey: 'groupDataIntelligence', destinations: ['datahub', 'geo'] },
  { labelKey: 'groupAgriculturalPlanning', destinations: ['cropintel'] },
  { labelKey: 'groupDecisionIntelligence', destinations: ['decisions'] },
  { labelKey: 'groupInsights', destinations: ['copilot', 'reports'] },
]

export function WorkspaceSidebar({
  activeTab,
  activeSub,
  onNavigate,
}: {
  activeTab: DestinationId
  activeSub: string | null
  onNavigate: (tab: DestinationId, sub: string | null) => void
}) {
  const tDestinations = useTranslations('destinations')
  const tNav = useTranslations('nav')

  return (
    <aside className="ct-sidebar hidden w-[256px] shrink-0 flex-col xl:flex">
      <div className="ct-sidebar-brand">
        <div className="flex items-center gap-3">
          <span className="ct-brand-mark" aria-hidden>
            <Sprout className="h-5 w-5" strokeWidth={1.8} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold tracking-[-0.02em] text-stone-100">
              CropTwist
            </p>
            <p className="mt-0.5 truncate text-[10px] font-medium uppercase tracking-[0.16em] text-stone-500">
              {tNav('workspaceCaption')}
            </p>
          </div>
        </div>
      </div>

      <nav
        aria-label={tNav('primaryNavigation')}
        className="ct-sidebar-nav scrollbar-thin min-h-0 flex-1 overflow-y-auto px-3 pb-4"
      >
        {SIDEBAR_GROUPS.map((group) => (
          <section key={group.labelKey} className="ct-sidebar-group">
            <h2 className="ct-nav-group-title">{tNav(group.labelKey)}</h2>
            <ul className="space-y-1">
              {group.destinations.map((destinationId) => {
                const destination = DESTINATIONS.find((item) => item.id === destinationId)
                if (!destination) return null

                const Icon = DESTINATION_ICONS[destination.id]
                const isActive = activeTab === destination.id
                const hasSubpages = destination.subPages.length > 0

                return (
                  <li key={destination.id}>
                    <button
                      type="button"
                      onClick={() =>
                        onNavigate(destination.id, defaultSubFor(destination.id) ?? null)
                      }
                      aria-label={tDestinations(destination.labelKey)}
                      aria-current={isActive && !activeSub ? 'page' : undefined}
                      aria-expanded={hasSubpages ? isActive : undefined}
                      className={cn('ct-nav-item', isActive && 'is-active')}
                    >
                      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
                      <span className="min-w-0 flex-1 truncate">
                        {tDestinations(destination.labelKey)}
                      </span>
                      {hasSubpages ? (
                        <ChevronDown
                          className={cn(
                            'h-3.5 w-3.5 shrink-0 transition-transform',
                            isActive && 'rotate-180',
                          )}
                          aria-hidden
                        />
                      ) : null}
                    </button>

                    {isActive && hasSubpages ? (
                      <ul className="ct-subnav-list">
                        {destination.subPages.map((subpage) => {
                          const isSubActive = activeSub === subpage.id
                          return (
                            <li key={subpage.id}>
                              <button
                                type="button"
                                onClick={() => onNavigate(destination.id, subpage.id)}
                                aria-current={isSubActive ? 'page' : undefined}
                                className={cn(
                                  'ct-subnav-item',
                                  isSubActive && 'is-active',
                                )}
                              >
                                <span className="truncate">
                                  {tDestinations(`sub.${subpage.labelKey}`)}
                                </span>
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </nav>

      <div className="ct-sidebar-footer">
        <span className="ct-status-pulse" aria-hidden />
        <span className="truncate">{tNav('footerSynthetic')}</span>
      </div>
    </aside>
  )
}

'use client'

/**
 * P02 W1 — mobile navigation sheet (audit P1/P7: the 27-tab strip measured
 * 3,047px wide at 390px; the shipped-but-unused `ui/sheet.tsx` primitive is
 * now adopted as the mobile hamburger navigation, blueprint C9).
 *
 * Behavior:
 *   - Radix Dialog semantics: Escape closes, focus is trapped while open and
 *     restored to the trigger on close, background scrolling is locked.
 *   - Every item is a real 44px touch target (min-h-11).
 *   - Grouped destinations with their sub-pages nested under each destination.
 *   - The active destination/sub is marked with aria-current + styling and is
 *     scrolled into view when the sheet opens.
 */

import { useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { ChevronRight, Link2, Menu, Search, Sprout } from 'lucide-react'

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { DESTINATIONS, type DestinationId } from '@/lib/navigation'
import { useCropTwistUi } from '@/lib/store'
import { cn } from '@/lib/utils'

export function MobileNavSheet({
  activeTab,
  activeSub,
  onNavigate,
  onOpenOnboarding,
  onShare,
}: {
  activeTab: DestinationId
  activeSub: string | null
  onNavigate: (tab: DestinationId, sub: string | null) => void
  onOpenOnboarding: () => void
  onShare: () => void
}) {
  const locale = useLocale()
  const t = useTranslations('destinations')
  const tNav = useTranslations('nav')
  const tCommon = useTranslations('common')
  const [open, setOpen] = useState(false)
  const activeRef = useRef<HTMLButtonElement | null>(null)
  const openPalette = useCropTwistUi((s) => s.setCommandPaletteOpen)

  const handleNavigate = (tab: DestinationId, sub: string | null) => {
    onNavigate(tab, sub)
    setOpen(false) // closes the sheet; Radix restores focus to the trigger
  }

  /** P03 W2.4 — the command center is reachable on mobile too: the sheet's
   * search row opens the same palette instance the desktop header uses. */
  const handleOpenPalette = () => {
    setOpen(false)
    openPalette(true)
  }

  const handleOpenOnboarding = () => {
    setOpen(false)
    onOpenOnboarding()
  }

  const handleShare = () => {
    setOpen(false)
    onShare()
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('openMenuAria')}
          aria-expanded={open}
          aria-haspopup="dialog"
          className="h-11 w-11 text-stone-600 hover:text-stone-900 xl:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent
        side={locale === 'ar' ? 'right' : 'left'}
        className="flex w-[320px] max-w-[88vw] flex-col gap-0 overflow-y-auto p-0 sm:w-[340px]"
      >
        <SheetHeader className="border-b border-stone-200 px-4 py-3.5 text-start">
          <SheetTitle className="text-sm font-semibold text-stone-900">{t('menuTitle')}</SheetTitle>
        </SheetHeader>
        <nav aria-label={t('railAria')} className="flex-1 px-2 py-2">
          <button
            type="button"
            onClick={handleOpenPalette}
            className="mb-2 flex min-h-11 w-full items-center gap-2.5 rounded-md border border-stone-200 bg-white px-3 text-start text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 hover:text-stone-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
          >
            <Search className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden />
            <span className="truncate">{t('paletteOpenLabel')}</span>
            <kbd className="ms-auto hidden rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px] font-medium text-stone-500 sm:inline-block">
              ⌘K
            </kbd>
          </button>
          <ul className="space-y-1">
            {DESTINATIONS.map((dest) => {
              const isDestActive = dest.id === activeTab
              return (
                <li key={dest.id}>
                  <button
                    ref={isDestActive ? activeRef : undefined}
                    type="button"
                    aria-current={isDestActive ? 'page' : undefined}
                    onClick={() => handleNavigate(dest.id, dest.subPages[0]?.id ?? null)}
                    className={cn(
                      'flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-3 text-start text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700',
                      isDestActive
                        ? 'bg-emerald-50 text-emerald-900'
                        : 'text-stone-700 hover:bg-stone-100 hover:text-stone-900',
                    )}
                  >
                    <span className="truncate">{t(dest.labelKey)}</span>
                    {dest.subPages.length > 0 ? (
                      <ChevronRight className="h-4 w-4 shrink-0 text-stone-400 rtl:rotate-180" aria-hidden />
                    ) : null}
                  </button>
                  {isDestActive && dest.subPages.length > 0 ? (
                    <ul className="mb-1 ms-3 mt-1 space-y-0.5 border-s border-stone-200 ps-2">
                      {dest.subPages.map((sub) => {
                        const isSubActive = sub.id === activeSub
                        return (
                          <li key={sub.id}>
                            <button
                              type="button"
                              aria-current={isSubActive ? 'location' : undefined}
                              onClick={() => handleNavigate(dest.id, sub.id)}
                              className={cn(
                                'flex min-h-11 w-full items-center rounded-md px-3 text-start text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700',
                                isSubActive
                                  ? 'bg-emerald-50 font-medium text-emerald-900'
                                  : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900',
                              )}
                            >
                              <span className="truncate">{t(`sub.${sub.labelKey}`)}</span>
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
        </nav>
        <div className="border-t border-stone-200 px-3 py-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleShare}
            className="mb-2 min-h-11 w-full justify-start gap-2 text-sm"
          >
            <Link2 className="h-4 w-4 text-emerald-700" aria-hidden />
            {tCommon('shareView')}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleOpenOnboarding}
            className="mb-2 min-h-11 w-full justify-start gap-2 text-sm"
          >
            <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
            {tNav('getStarted')}
          </Button>
          <p className="px-1 py-1 text-[11px] text-stone-400">{tNav('footerNote')}</p>
        </div>
      </SheetContent>
    </Sheet>
  )
}

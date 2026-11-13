'use client'

/**
 * P03 W2.4 — the W1 navigation foundation becomes the real command center
 * (blueprint C9, plan item 2.4).
 *
 * Command groups — every command has a REAL handler backed by existing
 * application capabilities; nothing invented, no placeholders:
 *   - Recent: visited views recorded by the store (memory-only, W2.4 scope).
 *   - Destinations: the nine primary destinations (navigation).
 *   - Sections: every real nested view (incl. the six promoted management
 *     sub-pages and Preferences).
 *   - Farm & field: the authenticated user's accessible farms/fields only
 *     (server-enforced access, via useFarmsWithFields). Selecting context
 *     keeps the current page (deep-linked context preserved).
 *   - Actions: Create farm or field (opens the real Farms & Fields dialog)
 *     and Copy share link (the same handler as the header share button).
 *
 * Accessibility: opens via header button and Cmd/Ctrl+K (hinted on the
 * trigger and in the input); full keyboard navigation from cmdk (arrows,
 * Enter, Home/End); Escape closes through the Radix Dialog, which also
 * restores focus to the trigger.
 */

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  FolderPlus,
  Link2,
  MapPin,
  Search,
  Sprout,
  Timer,
  TriangleAlert,
} from 'lucide-react'

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Button } from '@/components/ui/button'
import {
  DESTINATION_ICONS,
} from '@/components/croptwist/navigation/destination-rail'
import { useFarmsWithFields } from '@/hooks/use-croptwist'
import { useFieldContext } from '@/components/croptwist/field-context'
import { destinationById } from '@/lib/navigation'
import { useCropTwistUi } from '@/lib/store'
import type { DestinationId } from '@/lib/navigation'

const subscribeNoop = () => () => {}

export function CommandPalette({ onNavigate }: { onNavigate: (tab: DestinationId, sub: string | null) => void }) {
  const t = useTranslations('destinations')
  const tCommon = useTranslations('common')
  const [open, setOpen] = useState(false)
  // Platform-aware shortcut hint without hydration mismatch: the server
  // snapshot renders "Ctrl K", the client upgrades to "⌘K" after hydration.
  const shortcut = useSyncExternalStore(
    subscribeNoop,
    () => (/Mac|iPhone|iPad/i.test(navigator.platform) ? '⌘K' : 'Ctrl K'),
    () => 'Ctrl K',
  )

  const { selectedField, setSelectedField, setSelectedFarmId } = useFieldContext()
  const { farms, allFields, isLoading } = useFarmsWithFields()
  const recentViews = useCropTwistUi((s) => s.recentViews)
  const activeTab = useCropTwistUi((s) => s.activeTab)
  const activeSub = useCropTwistUi((s) => s.activeSub)
  const openCreateFarm = useCropTwistUi((s) => s.openCreateFarm)

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [])

  const go = (tab: DestinationId, sub: string | null) => {
    setOpen(false)
    onNavigate(tab, sub)
  }

  const run = (action: () => void) => {
    setOpen(false)
    action()
  }

  const shareView = () =>
    run(() => {
      navigator.clipboard
        .writeText(window.location.href)
        .then(() => toast.success(tCommon('linkCopied')))
        .catch(() => undefined)
    })

  /** "Destination — Section" label used by Recent + Sections commands. */
  const viewLabel = (tab: DestinationId, sub: string | null): string => {
    const dest = destinationById(tab)
    if (!dest) return tab
    const subDef = dest.subPages.find((s) => s.id === sub)
    return subDef ? `${t(dest.labelKey)} · ${t(`sub.${subDef.labelKey}`)}` : t(dest.labelKey)
  }

  const farmNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const entry of farms) map.set(entry.farm.id, entry.farm.name)
    return map
  }, [farms])

  // Recent entries, minus the view the user is already on.
  const recentCommands = useMemo(
    () => recentViews.filter((v) => !(v.tab === activeTab && (v.sub ?? null) === (activeSub ?? null))),
    [recentViews, activeTab, activeSub],
  )

  const shortcutTitle = t('paletteHint', { shortcut })

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t('paletteOpenAria')}
        aria-keyshortcuts="Meta+K Control+K"
        title={shortcutTitle}
        onClick={() => setOpen(true)}
        className="hidden h-11 w-11 text-stone-600 hover:text-stone-900 sm:inline-flex"
      >
        <Search className="h-4.5 w-4.5" aria-hidden />
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title={shortcutTitle}>
        <CommandInput placeholder={t('palettePlaceholder')} />
        <CommandList>
          <CommandEmpty>{t('paletteEmpty')}</CommandEmpty>

          {recentCommands.length > 0 ? (
            <>
              <CommandGroup heading={t('paletteGroupRecent')}>
                {recentCommands.map((v) => (
                  <CommandItem
                    key={`recent-${v.tab}:${v.sub ?? ''}`}
                    value={`recent ${viewLabel(v.tab, v.sub)}`}
                    keywords={[t(v.tab)]}
                    onSelect={() => go(v.tab, v.sub)}
                  >
                    <Timer className="text-stone-400" aria-hidden />
                    <span className="truncate">{viewLabel(v.tab, v.sub)}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
            </>
          ) : null}

          <CommandGroup heading={t('paletteGroupDestinations')}>
            {(['overview', 'farms', 'datahub', 'cropintel', 'geo', 'decisions', 'copilot', 'reports', 'settings'] as DestinationId[]).map(
              (id) => {
                const dest = destinationById(id)!
                const Icon = DESTINATION_ICONS[dest.id]
                return (
                  <CommandItem
                    key={dest.id}
                    value={t(dest.labelKey)}
                    onSelect={() => go(dest.id, dest.subPages[0]?.id ?? null)}
                  >
                    <Icon className="text-emerald-700" aria-hidden />
                    <span className="truncate">{t(dest.labelKey)}</span>
                  </CommandItem>
                )
              },
            )}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading={t('paletteGroupViews')}>
            {(['datahub', 'cropintel', 'geo', 'decisions', 'reports', 'settings'] as DestinationId[]).flatMap((id) => {
              const dest = destinationById(id)!
              return dest.subPages.map((sub) => (
                <CommandItem
                  key={`${dest.id}:${sub.id}`}
                  value={`${t(dest.labelKey)} ${t(`sub.${sub.labelKey}`)}`}
                  keywords={[t(dest.labelKey), t(`sub.${sub.labelKey}`)]}
                  onSelect={() => go(dest.id, sub.id)}
                >
                  <span className="truncate">
                    {t(dest.labelKey)} <span aria-hidden>·</span> {t(`sub.${sub.labelKey}`)}
                  </span>
                </CommandItem>
              ))
            })}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading={t('paletteGroupContext')}>
            {isLoading && farms.length === 0 ? (
              <CommandItem disabled value="loading-farms" className="text-stone-400">
                <TriangleAlert aria-hidden />
                <span>{t('paletteLoadingFields')}</span>
              </CommandItem>
            ) : null}
            {allFields.length === 0 && !isLoading ? (
              <CommandItem
                value={t('paletteNoFields')}
                onSelect={() => run(() => openCreateFarm())}
              >
                <FolderPlus className="text-emerald-700" aria-hidden />
                <span>{t('paletteNoFields')}</span>
              </CommandItem>
            ) : null}
            {farms.map(({ farm }) => (
              <CommandItem
                key={`farm-${farm.id}`}
                value={`${farm.name} ${t('paletteFarmAlias')}`}
                keywords={[farm.name, t('paletteFarmAlias')]}
                onSelect={() => run(() => setSelectedFarmId(farm.id))}
              >
                <Sprout className="text-emerald-700" aria-hidden />
                <span className="truncate">{farm.name}</span>
                <span className="ml-auto text-[10px] uppercase tracking-wide text-stone-400">{t('paletteFarmAlias')}</span>
              </CommandItem>
            ))}
            {allFields.map((field) => (
              <CommandItem
                key={`field-${field.id}`}
                value={`${field.name} ${farmNameById.get(field.farm_id) ?? ''} ${t('paletteFieldAlias')}`}
                keywords={[field.name, farmNameById.get(field.farm_id) ?? '', t('paletteFieldAlias')]}
                onSelect={() =>
                  run(() =>
                    setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id }),
                  )
                }
              >
                <MapPin className="text-emerald-700" aria-hidden />
                <span className="truncate">{field.name}</span>
                {farmNameById.get(field.farm_id) ? (
                  <span className="ml-auto text-[10px] text-stone-400">{farmNameById.get(field.farm_id)}</span>
                ) : null}
              </CommandItem>
            ))}
            {selectedField ? (
              <CommandItem
                value={t('paletteClearField')}
                onSelect={() => run(() => setSelectedField(null))}
              >
                <span className="truncate text-stone-500">{t('paletteClearField')}</span>
              </CommandItem>
            ) : null}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading={t('paletteGroupActions')}>
            <CommandItem
              value={t('actionCreateFarmField')}
              keywords={[tCommon('createFarmField')]}
              onSelect={() => run(() => openCreateFarm())}
            >
              <FolderPlus className="text-emerald-700" aria-hidden />
              <span className="truncate">{t('actionCreateFarmField')}</span>
            </CommandItem>
            <CommandItem
              value={t('actionShareView')}
              keywords={[tCommon('shareView')]}
              onSelect={shareView}
            >
              <Link2 className="text-emerald-700" aria-hidden />
              <span className="truncate">{t('actionShareView')}</span>
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </>
  )
}

'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Link2, LogOut, Sprout } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { AuthGate } from '@/components/croptwist/auth-gate'
import { LocaleSwitcher } from '@/components/croptwist/locale-switcher'
import { Overview } from '@/components/croptwist/overview'
import { FarmsFields } from '@/components/croptwist/farms-fields'
import { Observations } from '@/components/croptwist/observations'
import { Features } from '@/components/croptwist/features'
import { DataPassport } from '@/components/croptwist/data-passport'
import { Rotation } from '@/components/croptwist/rotation'
import { Water } from '@/components/croptwist/water'
import { FieldStateView } from '@/components/croptwist/field-state'
import Scenarios from '@/components/croptwist/scenarios'
import { Soil } from '@/components/croptwist/soil'
import { CoversPage, ErosionPage, OperationsPage, PlanPage, ResiduePage, TimelinePage } from '@/components/croptwist/management'
import SensitivitySection from '@/components/croptwist/sensitivity'
import Decisions from '@/components/croptwist/decisions'
import AiInsights from '@/components/croptwist/ai-insights'
import DigitalTwin from '@/components/croptwist/digital-twin'
import RobustPlan from '@/components/croptwist/robust-plan'
import { SatelliteIntelligence } from '@/components/croptwist/satellite'
import { ClimateForecast } from '@/components/croptwist/forecast'
import { SoilMemory } from '@/components/croptwist/soil-memory'
import { FailureLab } from '@/components/croptwist/failure-lab'
import { AdaptiveEvidence } from '@/components/croptwist/adaptive-evidence'
import { FarmPortfolio } from '@/components/croptwist/portfolio'
import TeamTab from '@/components/croptwist/p3/team-tab'
import PreferencesTab from '@/components/croptwist/p3/preferences-tab'
import OnboardingWizard from '@/components/croptwist/p3/onboarding-wizard'
import NotificationsBell from '@/components/croptwist/p3/notifications-bell'
import BillingTab from '@/components/croptwist/p3/billing-tab'
import InsightsTab from '@/components/croptwist/p3/insights-tab'
import ReportsTab from '@/components/croptwist/p3/reports-tab'
import DeveloperTab from '@/components/croptwist/p3/developer-tab'
import { DestinationRail } from '@/components/croptwist/navigation/destination-rail'
import { MobileNavSheet } from '@/components/croptwist/navigation/mobile-nav-sheet'
import { SubPageRail } from '@/components/croptwist/navigation/sub-page-rail'
import { ContextBar } from '@/components/croptwist/navigation/context-bar'
import { CommandPalette } from '@/components/croptwist/navigation/command-palette'
import { MapSatellitePane } from '@/components/croptwist/navigation/map-satellite-pane'
import { useHealth } from '@/hooks/use-croptwist'
import { getMe, logout } from '@/lib/api'
import { mountEntitlementGuard } from '@/lib/entitlement-guard'
import {
  DESTINATIONS,
  defaultSubFor,
  destinationById,
  isValidSub,
  resolveTarget,
  type DestinationDef,
  type DestinationId,
} from '@/lib/navigation'
import { useCropTwistUi, type SelectedField } from '@/lib/store'
import type { MeResponse } from '@/lib/types'

type Phase = 'checking' | 'guest' | 'authed'

// ---------------------------------------------------------------------------
// P02 W1 — URL ⇄ store synchronization
//
// Contract (preserved from P1, extended for W1):
//   `/?tab=<id>&sub=<sub>&farm=<id>&field=<id>&fieldName=<name>`
//
//   - <tab> accepts the nine canonical destination ids AND all 27 legacy ids
//     forever (legacy ids resolve through the permanent redirect map in
//     `src/lib/navigation.ts` — bookmarks, notification links and shared URLs
//     never break).
//   - Query parameters unrelated to workspace navigation are PRESERVED when
//     the URL is rewritten.
//
// History behavior (audit P17 — `router.replace` destroyed Back-button):
//   - USER navigation (rail/sub-rail/mobile-sheet/context/palette/store
//     helpers/entitlement guard) → `router.push` — Back/Forward walk the
//     destination history.
//   - AUTOMATIC canonicalization (legacy deep link redirect, initial write)
//     → `router.replace` — no duplicate history entries for URL normalization.
//   - Back/Forward pops are detected in the URL→store effect (URL differs
//     from what we last wrote) and applied INTO the store.
// ---------------------------------------------------------------------------

const WORKSPACE_URL_KEYS = ['tab', 'sub', 'farm', 'field', 'fieldName'] as const

function sameField(a: SelectedField | null, b: SelectedField | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return a.id === b.id && a.name === b.name && a.farmId === b.farmId
}

/** Canonical query string for a store state, PRESERVING unrelated params. */
function canonicalQs(state: {
  activeTab: DestinationId
  activeSub: string | null
  selectedFarmId: string | null
  selectedField: SelectedField | null
}): string {
  const params = new URLSearchParams(window.location.search)
  for (const key of WORKSPACE_URL_KEYS) params.delete(key)
  params.set('tab', state.activeTab)
  if (state.activeSub) params.set('sub', state.activeSub)
  if (state.selectedFarmId) params.set('farm', state.selectedFarmId)
  if (state.selectedField) {
    params.set('field', state.selectedField.id)
    params.set('fieldName', state.selectedField.name)
  }
  return params.toString()
}

function useWorkspaceUrlSync() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const navigateTo = useCropTwistUi((s) => s.navigateTo)
  const setSelectedFarmId = useCropTwistUi((s) => s.setSelectedFarmId)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const urlQsRef = useRef<string | null>(null)
  const syncedRef = useRef(false)

  // Store → URL (user navigation pushes; echo-suppressed).
  useEffect(() => {
    return useCropTwistUi.subscribe((state, prev) => {
      if (!syncedRef.current) return
      const changed =
        state.activeTab !== prev.activeTab ||
        state.activeSub !== prev.activeSub ||
        state.selectedFarmId !== prev.selectedFarmId ||
        !sameField(state.selectedField, prev.selectedField)
      if (!changed) return
      const qs = canonicalQs(state)
      if (qs === urlQsRef.current) return
      urlQsRef.current = qs
      router.push(qs ? `/?${qs}` : '/', { scroll: false })
    })
  }, [router])

  // URL → store (initial deep link, Back/Forward, manual edits), then
  // canonicalize with replace when the raw URL differs from the resolved form.
  useEffect(() => {
    const urlQs = searchParams.toString()
    if (syncedRef.current && urlQs === urlQsRef.current) return // echo of our own write

    const tabParam = searchParams.get('tab')
    if (tabParam !== null) {
      const target = resolveTarget(tabParam, searchParams.get('sub'))
      if (target) navigateTo(target.tab, target.sub)
      // unknown tab → ignored safely (pre-P02 contract, no redirect loops)
    }
    const farm = searchParams.get('farm')
    const field = searchParams.get('field')
    if (field) {
      setSelectedField({
        id: field,
        name: searchParams.get('fieldName') ?? 'Field',
        farmId: farm ?? '',
      })
    } else if (farm) {
      setSelectedFarmId(farm)
    }

    syncedRef.current = true
    const canonical = canonicalQs(useCropTwistUi.getState())
    urlQsRef.current = canonical
    if (canonical !== urlQs) {
      router.replace(canonical ? `/?${canonical}` : '/', { scroll: false })
    }
  }, [searchParams, navigateTo, setSelectedFarmId, setSelectedField, router])
}

function Footer() {
  const health = useHealth()
  const t = useTranslations('nav')
  return (
    <footer className="mt-auto border-t border-stone-200 bg-stone-50 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto flex w-full max-w-7xl flex-col items-start justify-between gap-2 px-4 py-4 text-xs text-stone-500 sm:flex-row sm:items-center sm:px-6">
        <p>
          {t('footerNote')}{' '}
          <span className="font-semibold text-stone-600">{t('footerSynthetic')}</span>
        </p>
        <div className="flex items-center gap-2">
          {health.data ? (
            <Badge variant="outline" className="gap-1.5 border-stone-300 bg-white font-normal text-stone-600">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${health.isError ? 'bg-red-500' : 'bg-emerald-600'}`}
                aria-hidden
              />
              {t('apiVersion', { version: health.data.version })}
            </Badge>
          ) : (
            <Badge variant="outline" className="border-stone-300 bg-white font-normal text-stone-500">
              {t('apiStatus')}
            </Badge>
          )}
        </div>
      </div>
    </footer>
  )
}

function CheckingScreen() {
  const t = useTranslations('nav')
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-stone-100 text-stone-500">
      <Sprout className="h-8 w-8 animate-pulse text-emerald-700" aria-hidden />
      <p className="text-sm">{t('restoringSession')}</p>
    </div>
  )
}

function SessionHeader({
  session,
  activeTab,
  activeSub,
  onNavigate,
  onSignOut,
  onOpenOnboarding,
}: {
  session: MeResponse
  activeTab: DestinationId
  activeSub: string | null
  onNavigate: (tab: DestinationId, sub?: string | null) => void
  onSignOut: () => void
  onOpenOnboarding: () => void
}) {
  const t = useTranslations('nav')
  const tCommon = useTranslations('common')

  const handleShare = () => {
    navigator.clipboard
      .writeText(window.location.href)
      .then(() => toast.success(tCommon('linkCopied')))
      .catch(() => undefined)
  }

  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-2 px-4 py-2 sm:gap-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-1.5 sm:gap-2.5">
          <MobileNavSheet
            activeTab={activeTab}
            activeSub={activeSub}
            onNavigate={(tab, sub) => onNavigate(tab, sub)}
          />
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-emerald-50">
            <Sprout className="h-4.5 w-4.5" aria-hidden />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold text-stone-900">CropTwist</p>
            <p className="hidden truncate text-[11px] text-stone-500 sm:block">
              {session.user.display_name} · {session.user.email}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
          <ContextBar className="mr-1 hidden xl:block" />
          <CommandPalette onNavigate={(tab, sub) => onNavigate(tab, sub)} />
          <Button
            variant="ghost"
            size="icon"
            onClick={onOpenOnboarding}
            aria-label={t('getStarted')}
            title={t('getStarted')}
            className="h-10 w-10 text-stone-600 hover:text-stone-900"
          >
            <Sprout className="h-4 w-4" aria-hidden />
          </Button>
          <NotificationsBell />
          <Button
            variant="ghost"
            size="icon"
            onClick={handleShare}
            aria-label={tCommon('shareView')}
            title={tCommon('shareView')}
            className="h-10 w-10 text-stone-600 hover:text-stone-900"
          >
            <Link2 className="h-4 w-4" aria-hidden />
          </Button>
          <LocaleSwitcher />
          <Button
            variant="ghost"
            size="icon"
            onClick={onSignOut}
            aria-label={t('signOut')}
            title={t('signOut')}
            className="h-10 w-10 text-stone-600 hover:text-stone-900"
          >
            <LogOut className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>
      {/* Mobile/tablet context row: the field picker lives under the header
          until the desktop layout can host it inline (≥lg). */}
      <div className="border-t border-stone-100 px-4 pb-2 pt-1.5 sm:px-6 xl:hidden">
        <ContextBar />
      </div>
    </header>
  )
}

/** Audit P9: no <h1> existed on any authed screen. Renders the current
 * destination (+sub-page) as an sr-only h1 that follows navigation. */
function WorkspaceH1({ activeTab, activeSub }: { activeTab: DestinationId; activeSub: string | null }) {
  const t = useTranslations('destinations')
  const dest = destinationById(activeTab)
  if (!dest) return null
  const sub = dest.subPages.find((s) => s.id === activeSub)
  return (
    <h1 className="sr-only">
      {sub ? `${t(dest.labelKey)} — ${t(`sub.${sub.labelKey}`)}` : t(dest.labelKey)}
    </h1>
  )
}

// ---------------------------------------------------------------------------
// Destination content mounts — every former tab component verbatim (P01
// matrix §1, "Move" work: pure re-association, zero logic rewrites).
// ---------------------------------------------------------------------------

const SINGLE_VIEW_CONTENT: Record<string, React.ReactNode> = {
  overview: <Overview />,
  farms: <FarmsFields />,
  copilot: <AiInsights />,
}

const SUB_PAGE_CONTENT: Record<string, React.ReactNode> = {
  // Data Hub
  'datahub:observations': <Observations />,
  'datahub:features': <Features />,
  'datahub:passport': <DataPassport />,
  'datahub:evidence': <AdaptiveEvidence />,
  // Crop Intelligence — P03 W2.1: management's six internal views are
  // promoted to URL-keyed sub-pages (blueprint §C2); `?sub=management`
  // resolves to `plan` forever via the SUB_ALIASES map.
  'cropintel:rotation': <Rotation />,
  'cropintel:irrigation': <Water />,
  'cropintel:soil': <Soil />,
  'cropintel:plan': <PlanPage />,
  'cropintel:covers': <CoversPage />,
  'cropintel:timeline': <TimelinePage />,
  'cropintel:residue': <ResiduePage />,
  'cropintel:erosion': <ErosionPage />,
  'cropintel:operations': <OperationsPage />,
  'cropintel:soilmemory': <SoilMemory />,
  'cropintel:forecast': <ClimateForecast />,
  // Map & Satellite
  'geo:map': <MapSatellitePane />,
  // Decision Center (chain order)
  'decisions:state': <FieldStateView />,
  'decisions:scenarios': <Scenarios />,
  'decisions:sensitivity': <SensitivitySection />,
  'decisions:robust': <RobustPlan />,
  'decisions:documents': <Decisions />,
  'decisions:failurelab': <FailureLab />,
  'decisions:portfolio': <FarmPortfolio />,
  'decisions:twin': <DigitalTwin />,
  // Reports & Analytics
  'reports:reports': <ReportsTab />,
  'reports:analytics': <InsightsTab />,
  // Workspace & Settings
  'settings:organization': <TeamTab />,
  'settings:billing': <BillingTab />,
  'settings:developer': <DeveloperTab />,
  // P03 W2.2: preferences has a true Settings home (blueprint §C7)
  'settings:preferences': <PreferencesTab />,
}

function DestinationBody({
  destination,
  activeSub,
  onSelectSub,
}: {
  destination: DestinationDef
  activeSub: string
  onSelectSub: (sub: string) => void
}) {
  if (destination.subPages.length === 0) {
    return <>{SINGLE_VIEW_CONTENT[destination.id] ?? null}</>
  }
  return (
    <Tabs value={activeSub}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-6">
        <SubPageRail
          destination={destination}
          activeSub={activeSub}
          onSelect={onSelectSub}
          orientation="vertical"
          className="hidden lg:flex lg:w-56 lg:shrink-0 lg:border-r lg:border-stone-200 lg:pr-2"
        />
        <SubPageRail
          destination={destination}
          activeSub={activeSub}
          onSelect={onSelectSub}
          orientation="horizontal"
          className="flex lg:hidden"
        />
        <div className="min-w-0 flex-1">
          {destination.subPages.map((sub) => (
            <TabsContent key={sub.id} value={sub.id} className="min-w-0">
              {SUB_PAGE_CONTENT[`${destination.id}:${sub.id}`] ?? null}
            </TabsContent>
          ))}
        </div>
      </div>
    </Tabs>
  )
}

export function Workspace() {
  // P1 auth: the session lives in HttpOnly cookies, so the only way to know
  // whether we are signed in is to ask /me (cookies are attached
  // automatically; tokens are never readable from JS).
  const [phase, setPhase] = useState<Phase>('checking')
  const [session, setSession] = useState<MeResponse | null>(null)
  const [onboardingOpen, setOnboardingOpen] = useState(false)
  const activeTab = useCropTwistUi((s) => s.activeTab)
  const activeSub = useCropTwistUi((s) => s.activeSub)
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const navigateTo = useCropTwistUi((s) => s.navigateTo)
  const setActiveSub = useCropTwistUi((s) => s.setActiveSub)
  const resetSelections = useCropTwistUi((s) => s.setSelectedField)
  const tP3b = useTranslations('p3b')

  useWorkspaceUrlSync()

  // P3 entitlement guard: ANY server-side 402 PAYMENT_REQUIRED (plan limit)
  // surfaces once as a toast with an Upgrade action that opens Billing.
  // ('billing' is a legacy id — the store resolves it to settings/billing.)
  useEffect(() => {
    return mountEntitlementGuard((detail) => {
      setActiveTab('billing')
      toast.error(tP3b('entitlement.limitTitle'), {
        description: detail.message ?? tP3b('entitlement.limitBody'),
        action: { label: tP3b('entitlement.upgrade'), onClick: () => setActiveTab('billing') },
        duration: 10000,
      })
    })
  }, [tP3b, setActiveTab])

  useEffect(() => {
    let cancelled = false
    getMe()
      .then((me) => {
        if (cancelled) return
        setSession(me)
        setPhase('authed')
      })
      .catch(() => {
        if (cancelled) return
        setPhase('guest')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleAuthed = () => {
    getMe()
      .then((me) => {
        setSession(me)
        setPhase('authed')
      })
      .catch(() => {
        setPhase('guest')
      })
  }

  const handleSignOut = () => {
    void logout()
    setSession(null)
    resetSelections(null)
    setPhase('guest')
  }

  // Guard the active sub for the ACTIVE destination (safe fallback, never blank).
  const effectiveSub =
    activeSub && isValidSub(activeTab, activeSub) ? activeSub : defaultSubFor(activeTab) ?? ''

  if (phase === 'checking') return <CheckingScreen />
  if (phase === 'guest' || !session) return <AuthGate onAuthed={handleAuthed} />

  return (
    <div className="flex min-h-screen flex-col bg-stone-100">
      <SessionHeader
        session={session}
        activeTab={activeTab}
        activeSub={activeSub}
        onNavigate={navigateTo}
        onSignOut={handleSignOut}
        onOpenOnboarding={() => setOnboardingOpen(true)}
      />
      <OnboardingWizard open={onboardingOpen} onOpenChange={setOnboardingOpen} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-4 sm:px-6 sm:py-6">
        <WorkspaceH1 activeTab={activeTab} activeSub={effectiveSub} />
        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as DestinationId)}
        >
          {/* Desktop destination rail (≥xl — nine 44px items need ~1230px,
              guaranteed by the max-w-7xl shell). Below xl the header hamburger
              sheet is the navigation (audit P1/P7 — no horizontal strip). */}
          <div className="hidden xl:block">
            <DestinationRail activeTab={activeTab} onSelect={setActiveTab} />
          </div>

          {DESTINATIONS.map((dest) => (
            <TabsContent key={dest.id} value={dest.id} className="mt-4">
              <DestinationBody
                destination={dest}
                activeSub={effectiveSub}
                onSelectSub={setActiveSub}
              />
            </TabsContent>
          ))}
        </Tabs>
      </main>

      <Footer />
    </div>
  )
}

export default Workspace

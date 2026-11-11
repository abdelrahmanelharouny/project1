'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  ClipboardCheck,
  Droplets,
  FlaskConical,
  GitBranch,
  Layers,
  LayoutDashboard,
  LineChart,
  Link2,
  LogOut,
  Map,
  Mountain,
  Network,
  RotateCcw,
  Scale,
  Sigma,
  Sparkles,
  Sprout,
  Target,
  Satellite,
  CloudSun,
  Layers3,
  Flame,
  Lightbulb,
  Globe2,
  Users,
  CreditCard,
  BarChart3,
  FileText,
  Code2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { Management } from '@/components/croptwist/management'
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
import OnboardingWizard from '@/components/croptwist/p3/onboarding-wizard'
import NotificationsBell from '@/components/croptwist/p3/notifications-bell'
import BillingTab from '@/components/croptwist/p3/billing-tab'
import InsightsTab from '@/components/croptwist/p3/insights-tab'
import ReportsTab from '@/components/croptwist/p3/reports-tab'
import DeveloperTab from '@/components/croptwist/p3/developer-tab'
import { useHealth } from '@/hooks/use-croptwist'
import { getMe, logout } from '@/lib/api'
import { useCropTwistUi, type WorkspaceTab } from '@/lib/store'
import type { MeResponse } from '@/lib/types'

type Phase = 'checking' | 'guest' | 'authed'

const TAB_ITEMS: { value: WorkspaceTab; icon: React.ReactNode }[] = [
  { value: 'overview', icon: <LayoutDashboard className="h-4 w-4" aria-hidden /> },
  { value: 'farms', icon: <Map className="h-4 w-4" aria-hidden /> },
  { value: 'observations', icon: <FlaskConical className="h-4 w-4" aria-hidden /> },
  { value: 'features', icon: <Sigma className="h-4 w-4" aria-hidden /> },
  { value: 'rotation', icon: <RotateCcw className="h-4 w-4" aria-hidden /> },
  { value: 'water', icon: <Droplets className="h-4 w-4" aria-hidden /> },
  { value: 'fieldstate', icon: <Layers className="h-4 w-4" aria-hidden /> },
  { value: 'scenarios', icon: <GitBranch className="h-4 w-4" aria-hidden /> },
  { value: 'soil', icon: <Mountain className="h-4 w-4" aria-hidden /> },
  { value: 'management', icon: <Sprout className="h-4 w-4" aria-hidden /> },
  { value: 'sensitivity', icon: <LineChart className="h-4 w-4" aria-hidden /> },
  { value: 'robustplan', icon: <Target className="h-4 w-4" aria-hidden /> },
  { value: 'decisions', icon: <Scale className="h-4 w-4" aria-hidden /> },
  { value: 'aiinsights', icon: <Sparkles className="h-4 w-4" aria-hidden /> },
  { value: 'digitaltwin', icon: <Network className="h-4 w-4" aria-hidden /> },
  { value: 'passport', icon: <ClipboardCheck className="h-4 w-4" aria-hidden /> },
  { value: 'satellite', icon: <Satellite className="h-4 w-4" aria-hidden /> },
  { value: 'forecast', icon: <CloudSun className="h-4 w-4" aria-hidden /> },
  { value: 'soilmemory', icon: <Layers3 className="h-4 w-4" aria-hidden /> },
  { value: 'failurelab', icon: <Flame className="h-4 w-4" aria-hidden /> },
  { value: 'adaptiveevidence', icon: <Lightbulb className="h-4 w-4" aria-hidden /> },
  { value: 'portfolio', icon: <Globe2 className="h-4 w-4" aria-hidden /> },
  { value: 'team', icon: <Users className="h-4 w-4" aria-hidden /> },
  { value: 'insights', icon: <BarChart3 className="h-4 w-4" aria-hidden /> },
  { value: 'reports', icon: <FileText className="h-4 w-4" aria-hidden /> },
  { value: 'billing', icon: <CreditCard className="h-4 w-4" aria-hidden /> },
  { value: 'developer', icon: <Code2 className="h-4 w-4" aria-hidden /> },
]

const TAB_IDS = TAB_ITEMS.map((item) => item.value)

/**
 * P1 deep links: the workspace state (active tab, selected farm/field) is
 * mirrored into the URL — `/?tab=water&farm=<id>&field=<id>&fieldName=<name>`
 * — so any view can be bookmarked or shared, and a shared link restores the
 * exact view on load.
 */
function useWorkspaceUrlSync() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const setSelectedFarmId = useCropTwistUi((s) => s.setSelectedFarmId)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const hydrated = useRef(false)

  // Restore state from a shared link exactly once on mount.
  useEffect(() => {
    if (hydrated.current) return
    hydrated.current = true
    const tab = searchParams.get('tab') as WorkspaceTab | null
    if (tab && TAB_IDS.includes(tab)) setActiveTab(tab)
    const farm = searchParams.get('farm')
    if (farm) setSelectedFarmId(farm)
    const field = searchParams.get('field')
    if (field) {
      setSelectedField({
        id: field,
        name: searchParams.get('fieldName') ?? 'Field',
        farmId: farm ?? '',
      })
    }
  }, [searchParams, setActiveTab, setSelectedFarmId, setSelectedField])

  // Mirror store changes into the URL (replace — no history spam), and write
  // the initial state once on mount so the first view is shareable too.
  useEffect(() => {
    let lastQs: string | null = null
    const writeUrl = (state: { activeTab: WorkspaceTab; selectedFarmId: string | null; selectedField: { id: string; name: string } | null }) => {
      const params = new URLSearchParams()
      params.set('tab', state.activeTab)
      if (state.selectedFarmId) params.set('farm', state.selectedFarmId)
      if (state.selectedField) {
        params.set('field', state.selectedField.id)
        params.set('fieldName', state.selectedField.name)
      }
      const qs = params.toString()
      if (qs === lastQs) return
      lastQs = qs
      router.replace(qs ? `/?${qs}` : '/', { scroll: false })
    }
    writeUrl(useCropTwistUi.getState())
    return useCropTwistUi.subscribe((state) => writeUrl(state))
  }, [router])
}

function Footer() {
  const health = useHealth()
  const t = useTranslations('nav')
  return (
    <footer className="mt-auto border-t border-stone-200 bg-stone-50 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-2 px-4 py-4 text-xs text-stone-500 sm:flex-row sm:items-center sm:px-6">
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
  onSignOut,
  onOpenOnboarding,
}: {
  session: MeResponse
  onSignOut: () => void
  onOpenOnboarding: () => void
}) {
  const t = useTranslations('nav')
  const tCommon = useTranslations('common')

  const handleShare = useCallback(() => {
    navigator.clipboard
      .writeText(window.location.href)
      .then(() => toast.success(tCommon('linkCopied')))
      .catch(() => undefined)
  }, [tCommon])

  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-emerald-50">
            <Sprout className="h-4.5 w-4.5" aria-hidden />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold text-stone-900">CropTwist</p>
            <p className="truncate text-[11px] text-stone-500">
              {session.user.display_name} · {session.user.email}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onOpenOnboarding}
            className="h-8 gap-1.5 text-stone-600 hover:text-stone-900"
          >
            <Sparkles className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">{t('getStarted')}</span>
            <span className="sr-only">{t('getStarted')}</span>
          </Button>
          <NotificationsBell />
          <Button
            variant="ghost"
            size="icon"
            onClick={handleShare}
            aria-label={tCommon('shareView')}
            title={tCommon('shareView')}
            className="h-8 w-8 text-stone-600 hover:text-stone-900"
          >
            <Link2 className="h-4 w-4" aria-hidden />
          </Button>
          <LocaleSwitcher />
          <Button
            variant="ghost"
            size="sm"
            onClick={onSignOut}
            className="text-stone-600 hover:text-stone-900"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">{t('signOut')}</span>
            <span className="sr-only">{t('signOut')}</span>
          </Button>
        </div>
      </div>
    </header>
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
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const resetSelections = useCropTwistUi((s) => s.setSelectedField)

  useWorkspaceUrlSync()

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

  const handleAuthed = useCallback(() => {
    getMe()
      .then((me) => {
        setSession(me)
        setPhase('authed')
      })
      .catch(() => {
        setPhase('guest')
      })
  }, [])

  const handleSignOut = useCallback(() => {
    void logout()
    setSession(null)
    resetSelections(null)
    setPhase('guest')
  }, [resetSelections])

  if (phase === 'checking') return <CheckingScreen />
  if (phase === 'guest' || !session) return <AuthGate onAuthed={handleAuthed} />

  return (
    <div className="flex min-h-screen flex-col bg-stone-100">
      <SessionHeader
        session={session}
        onSignOut={handleSignOut}
        onOpenOnboarding={() => setOnboardingOpen(true)}
      />
      <OnboardingWizard open={onboardingOpen} onOpenChange={setOnboardingOpen} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)}>
          <div className="-mx-1 overflow-x-auto pb-1 scrollbar-thin">
            <TabsList className="mx-1 inline-flex min-w-max">
              {TAB_ITEMS.map((item) => (
                <TabsTrigger key={item.value} value={item.value} className="gap-2 px-3 sm:px-4">
                  {item.icon}
                  <TabLabel tab={item.value} />
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value="overview" className="mt-4">
            <Overview />
          </TabsContent>
          <TabsContent value="farms" className="mt-4">
            <FarmsFields />
          </TabsContent>
          <TabsContent value="observations" className="mt-4">
            <Observations />
          </TabsContent>
          <TabsContent value="features" className="mt-4">
            <Features />
          </TabsContent>
          <TabsContent value="rotation" className="mt-4">
            <Rotation />
          </TabsContent>
          <TabsContent value="water" className="mt-4">
            <Water />
          </TabsContent>
          <TabsContent value="fieldstate" className="mt-4">
            <FieldStateView />
          </TabsContent>
          <TabsContent value="scenarios" className="mt-4">
            <Scenarios />
          </TabsContent>
          <TabsContent value="soil" className="mt-4">
            <Soil />
          </TabsContent>
          <TabsContent value="management" className="mt-4">
            <Management />
          </TabsContent>
          <TabsContent value="sensitivity" className="mt-4">
            <SensitivitySection />
          </TabsContent>
          <TabsContent value="robustplan" className="mt-4">
            <RobustPlan />
          </TabsContent>
          <TabsContent value="decisions" className="mt-4">
            <Decisions />
          </TabsContent>
          <TabsContent value="aiinsights" className="mt-4">
            <AiInsights />
          </TabsContent>
          <TabsContent value="digitaltwin" className="mt-4">
            <DigitalTwin />
          </TabsContent>
          <TabsContent value="passport" className="mt-4">
            <DataPassport />
          </TabsContent>
          <TabsContent value="satellite" className="mt-4">
            <SatelliteIntelligence />
          </TabsContent>
          <TabsContent value="forecast" className="mt-4">
            <ClimateForecast />
          </TabsContent>
          <TabsContent value="soilmemory" className="mt-4">
            <SoilMemory />
          </TabsContent>
          <TabsContent value="failurelab" className="mt-4">
            <FailureLab />
          </TabsContent>
          <TabsContent value="adaptiveevidence" className="mt-4">
            <AdaptiveEvidence />
          </TabsContent>
          <TabsContent value="portfolio" className="mt-4">
            <FarmPortfolio />
          </TabsContent>
          <TabsContent value="team" className="mt-4">
            <TeamTab />
          </TabsContent>
          <TabsContent value="insights" className="mt-4">
            <InsightsTab />
          </TabsContent>
          <TabsContent value="reports" className="mt-4">
            <ReportsTab />
          </TabsContent>
          <TabsContent value="billing" className="mt-4">
            <BillingTab />
          </TabsContent>
          <TabsContent value="developer" className="mt-4">
            <DeveloperTab />
          </TabsContent>
        </Tabs>
      </main>

      <Footer />
    </div>
  )
}

function TabLabel({ tab }: { tab: WorkspaceTab }) {
  const t = useTranslations('nav')
  return <>{t(tab)}</>
}

export default Workspace

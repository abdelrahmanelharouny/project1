'use client'

import { useCallback, useEffect, useState } from 'react'
import { ClipboardCheck, FlaskConical, LayoutDashboard, LogOut, Map, RotateCcw, Sigma, Sprout } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AuthGate } from '@/components/fieldshift/auth-gate'
import { Overview } from '@/components/fieldshift/overview'
import { FarmsFields } from '@/components/fieldshift/farms-fields'
import { Observations } from '@/components/fieldshift/observations'
import { Features } from '@/components/fieldshift/features'
import { DataPassport } from '@/components/fieldshift/data-passport'
import { Rotation } from '@/components/fieldshift/rotation'
import { useHealth } from '@/hooks/use-fieldshift'
import { getMe, getToken, setToken } from '@/lib/api'
import { useFieldShiftUi, type WorkspaceTab } from '@/lib/store'
import type { MeResponse } from '@/lib/types'

type Phase = 'checking' | 'guest' | 'authed'

const TAB_ITEMS: { value: WorkspaceTab; label: string; icon: React.ReactNode }[] = [
  { value: 'overview', label: 'Overview', icon: <LayoutDashboard className="h-4 w-4" aria-hidden /> },
  { value: 'farms', label: 'Farms & Fields', icon: <Map className="h-4 w-4" aria-hidden /> },
  { value: 'observations', label: 'Observations', icon: <FlaskConical className="h-4 w-4" aria-hidden /> },
  { value: 'features', label: 'Features', icon: <Sigma className="h-4 w-4" aria-hidden /> },
  { value: 'rotation', label: 'Rotation', icon: <RotateCcw className="h-4 w-4" aria-hidden /> },
  { value: 'passport', label: 'Data Passport', icon: <ClipboardCheck className="h-4 w-4" aria-hidden /> },
]

function Footer() {
  const health = useHealth()
  return (
    <footer className="mt-auto border-t border-stone-200 bg-stone-50 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-2 px-4 py-4 text-xs text-stone-500 sm:flex-row sm:items-center sm:px-6">
        <p>
          FieldShift — decision support, not an autonomous agronomist.{' '}
          <span className="font-semibold text-stone-600">Synthetic data is always labelled.</span>
        </p>
        <div className="flex items-center gap-2">
          {health.data ? (
            <Badge variant="outline" className="gap-1.5 border-stone-300 bg-white font-normal text-stone-600">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${health.isError ? 'bg-red-500' : 'bg-emerald-600'}`}
                aria-hidden
              />
              API v{health.data.version}
            </Badge>
          ) : (
            <Badge variant="outline" className="border-stone-300 bg-white font-normal text-stone-500">
              API status…
            </Badge>
          )}
        </div>
      </div>
    </footer>
  )
}

function CheckingScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-stone-100 text-stone-500">
      <Sprout className="h-8 w-8 animate-pulse text-emerald-700" aria-hidden />
      <p className="text-sm">Restoring your session…</p>
    </div>
  )
}

function SessionHeader({ session, onSignOut }: { session: MeResponse; onSignOut: () => void }) {
  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-emerald-50">
            <Sprout className="h-4.5 w-4.5" aria-hidden />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold text-stone-900">FieldShift</p>
            <p className="truncate text-[11px] text-stone-500">
              {session.user.display_name} · {session.user.email}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onSignOut}
          className="shrink-0 text-stone-600 hover:text-stone-900"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">Sign out</span>
          <span className="sr-only">Sign out</span>
        </Button>
      </div>
    </header>
  )
}

export function Workspace() {
  // Client-only component (loaded with ssr: false), so reading localStorage in
  // the lazy initializer is safe — no SSR/hydration concerns.
  const [phase, setPhase] = useState<Phase>(() => (getToken() ? 'checking' : 'guest'))
  const [session, setSession] = useState<MeResponse | null>(null)
  const activeTab = useFieldShiftUi((s) => s.activeTab)
  const setActiveTab = useFieldShiftUi((s) => s.setActiveTab)
  const resetSelections = useFieldShiftUi((s) => s.setSelectedField)

  useEffect(() => {
    let cancelled = false
    if (!getToken()) return
    getMe()
      .then((me) => {
        if (cancelled) return
        setSession(me)
        setPhase('authed')
      })
      .catch(() => {
        if (cancelled) return
        setToken(null) // stale/invalid token — start fresh
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
        setToken(null)
        setPhase('guest')
      })
  }, [])

  const handleSignOut = useCallback(() => {
    setToken(null)
    setSession(null)
    resetSelections(null)
    setPhase('guest')
  }, [resetSelections])

  if (phase === 'checking') return <CheckingScreen />
  if (phase === 'guest' || !session) return <AuthGate onAuthed={handleAuthed} />

  return (
    <div className="flex min-h-screen flex-col bg-stone-100">
      <SessionHeader session={session} onSignOut={handleSignOut} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)}>
          <div className="-mx-1 overflow-x-auto pb-1 scrollbar-thin">
            <TabsList className="mx-1 inline-flex min-w-max">
              {TAB_ITEMS.map((item) => (
                <TabsTrigger key={item.value} value={item.value} className="gap-2 px-3 sm:px-4">
                  {item.icon}
                  {item.label}
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
          <TabsContent value="passport" className="mt-4">
            <DataPassport />
          </TabsContent>
        </Tabs>
      </main>

      <Footer />
    </div>
  )
}

export default Workspace

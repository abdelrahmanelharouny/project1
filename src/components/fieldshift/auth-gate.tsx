'use client'

import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Cloud, FlaskConical, Loader2, LogIn, Sprout, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import { useHealthReady } from '@/hooks/use-fieldshift'
import { describeError, login, register, seedDemo, setToken } from '@/lib/api'
import type { AuthResponse, SeedDemoResponse } from '@/lib/types'

interface AuthGateProps {
  onAuthed: () => void
}

function BackendStatusLine() {
  const { data, isError, isLoading } = useHealthReady()

  let dotClass = 'bg-stone-400'
  let label = 'Checking backend…'
  if (isLoading) {
    dotClass = 'bg-amber-500 animate-pulse'
    label = 'Checking backend…'
  } else if (data && data.status === 'ok') {
    dotClass = 'bg-emerald-600'
    label = `PostgreSQL ${data.server_version} + PostGIS ${data.postgis_version} connected`
  } else if (isError) {
    dotClass = 'bg-red-600'
    label = 'Backend unreachable — try again shortly'
  }

  return (
    <p className="flex items-center gap-2 text-xs text-stone-500" role="status">
      <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} aria-hidden />
      {label}
    </p>
  )
}

export function AuthGate({ onAuthed }: AuthGateProps) {
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [regName, setRegName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')

  const handleAuth = (auth: AuthResponse | SeedDemoResponse) => {
    setToken(auth.token)
    onAuthed()
  }

  const loginMutation = useMutation({
    mutationFn: () => login({ email: loginEmail.trim(), password: loginPassword }),
    onSuccess: (auth) => {
      toast.success(`Welcome back, ${auth.user.display_name}`, {
        description: `Organization: ${auth.organization.name}`,
      })
      handleAuth(auth)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const registerMutation = useMutation({
    mutationFn: () =>
      register({ display_name: regName.trim(), email: regEmail.trim(), password: regPassword }),
    onSuccess: (auth) => {
      toast.success(`Account created — welcome, ${auth.user.display_name}!`, {
        description: `Organization "${auth.organization.name}" is ready.`,
      })
      handleAuth(auth)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const demoMutation = useMutation({
    mutationFn: seedDemo,
    onSuccess: (demo) => {
      toast.info('Demo workspace ready — SYNTHETIC fixture data only', {
        description: demo.note,
      })
      handleAuth(demo)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submitLogin = (event: FormEvent) => {
    event.preventDefault()
    if (!loginEmail.trim() || !loginPassword) {
      toast.error('Enter your email and password.')
      return
    }
    loginMutation.mutate()
  }

  const submitRegister = (event: FormEvent) => {
    event.preventDefault()
    if (!regName.trim() || !regEmail.trim() || regPassword.length < 8) {
      toast.error('Check the form', { description: 'Display name, email and a password of 8+ characters are required.' })
      return
    }
    registerMutation.mutate()
  }

  const busy = loginMutation.isPending || registerMutation.isPending || demoMutation.isPending

  return (
    <div className="flex min-h-screen flex-col bg-stone-100">
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md space-y-4">
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-700 text-emerald-50 shadow-sm">
              <Sprout className="h-6 w-6" aria-hidden />
            </span>
            <h1 className="text-2xl font-semibold tracking-tight text-stone-900">FieldShift</h1>
            <p className="text-sm text-stone-500">
              Agricultural decision support — boundaries, observations, data passports.
            </p>
          </div>

          <Card className="border-stone-200 shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Sign in to your workspace</CardTitle>
              <CardDescription>
                First vertical slice: farms, field boundaries, synthetic observations, data passports.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <BackendStatusLine />

              <Tabs defaultValue="login">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="login">Sign in</TabsTrigger>
                  <TabsTrigger value="register">Create account</TabsTrigger>
                </TabsList>

                <TabsContent value="login">
                  <form onSubmit={submitLogin} className="space-y-3 pt-1" aria-label="Sign in form">
                    <div className="space-y-1.5">
                      <Label htmlFor="login-email">Email</Label>
                      <Input
                        id="login-email"
                        type="email"
                        autoComplete="email"
                        placeholder="farmer@example.com"
                        value={loginEmail}
                        onChange={(e) => setLoginEmail(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="login-password">Password</Label>
                      <Input
                        id="login-password"
                        type="password"
                        autoComplete="current-password"
                        value={loginPassword}
                        onChange={(e) => setLoginPassword(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <Button type="submit" className="w-full bg-emerald-700 hover:bg-emerald-800" disabled={busy}>
                      {loginMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <LogIn className="h-4 w-4" aria-hidden />
                      )}
                      Sign in
                    </Button>
                  </form>
                </TabsContent>

                <TabsContent value="register">
                  <form onSubmit={submitRegister} className="space-y-3 pt-1" aria-label="Create account form">
                    <div className="space-y-1.5">
                      <Label htmlFor="reg-name">Display name</Label>
                      <Input
                        id="reg-name"
                        autoComplete="name"
                        placeholder="Amina Hassan"
                        value={regName}
                        onChange={(e) => setRegName(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="reg-email">Email</Label>
                      <Input
                        id="reg-email"
                        type="email"
                        autoComplete="email"
                        placeholder="farmer@example.com"
                        value={regEmail}
                        onChange={(e) => setRegEmail(e.target.value)}
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="reg-password">Password</Label>
                      <Input
                        id="reg-password"
                        type="password"
                        autoComplete="new-password"
                        placeholder="At least 8 characters"
                        value={regPassword}
                        onChange={(e) => setRegPassword(e.target.value)}
                        disabled={busy}
                      />
                      <p className="text-xs text-stone-500">Minimum 8 characters. A new organization is created for you.</p>
                    </div>
                    <Button type="submit" className="w-full bg-emerald-700 hover:bg-emerald-800" disabled={busy}>
                      {registerMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <UserPlus className="h-4 w-4" aria-hidden />
                      )}
                      Create account
                    </Button>
                  </form>
                </TabsContent>
              </Tabs>

              <div className="relative">
                <Separator />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-card px-2 text-xs uppercase tracking-wide text-stone-400">
                  or
                </span>
              </div>

              <Button
                type="button"
                variant="secondary"
                className="w-full border border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
                onClick={() => demoMutation.mutate()}
                disabled={busy}
              >
                {demoMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <FlaskConical className="h-4 w-4" aria-hidden />
                )}
                Enter demo workspace
              </Button>
              <p className="flex items-start gap-1.5 text-xs text-stone-500">
                <Cloud className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                The demo workspace contains <strong className="font-semibold text-stone-700">SYNTHETIC fixture data
                only</strong> — safe to explore, never real measurements.
              </p>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}

export default AuthGate

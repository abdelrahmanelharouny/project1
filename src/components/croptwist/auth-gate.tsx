'use client'

import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Cloud, FlaskConical, Loader2, LogIn, MailCheck, Sprout, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import { useHealthReady } from '@/hooks/use-croptwist'
import { handleRegistrationResult } from '@/lib/auth-registration'
import {
  confirmEmailVerification,
  demoLogin,
  describeError,
  login,
  register,
  requestEmailVerification,
} from '@/lib/api'

interface AuthGateProps {
  onAuthed: () => void
}

function BackendStatusLine() {
  const { data, isError, isLoading } = useHealthReady()
  const t = useTranslations('auth')

  let dotClass = 'bg-stone-400'
  let label = t('backendChecking')
  if (isLoading) {
    dotClass = 'bg-amber-500 animate-pulse'
    label = t('backendChecking')
  } else if (data && data.status === 'ok') {
    dotClass = 'bg-emerald-600'
    label = t('backendOk', { server: data.server_version, postgis: data.postgis_version })
  } else if (isError) {
    dotClass = 'bg-red-600'
    label = t('backendDown')
  }

  return (
    <p className="flex items-center gap-2 text-xs text-stone-500" role="status">
      <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} aria-hidden />
      {label}
    </p>
  )
}

/**
 * Sign-in / registration / demo entry (P1 i18n). Authentication goes through
 * the Next.js /api/auth/* route handlers: session tokens are set as HttpOnly
 * cookies server-side and never reach JavaScript.
 */
export function AuthGate({ onAuthed }: AuthGateProps) {
  const t = useTranslations('auth')
  const [activeTab, setActiveTab] = useState<'login' | 'register'>('login')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [regName, setRegName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [verificationEmail, setVerificationEmail] = useState('')
  const [verificationToken, setVerificationToken] = useState('')

  const loginMutation = useMutation({
    mutationFn: () => login({ email: loginEmail.trim(), password: loginPassword }),
    onSuccess: (auth) => {
      toast.success(t('welcomeBack', { name: auth.user.display_name }), {
        description: auth.organization ? t('orgPrefix', { name: auth.organization.name }) : undefined,
      })
      onAuthed()
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const registerMutation = useMutation({
    mutationFn: () =>
      register({ display_name: regName.trim(), email: regEmail.trim(), password: regPassword }),
    onSuccess: (result) => {
      handleRegistrationResult(result, {
        onVerificationRequired: (email) => {
          setVerificationEmail(email)
          setVerificationToken('')
          toast.success(t('verificationSentToast'))
        },
        onAuthenticated: (auth) => {
          toast.success(t('accountCreated', { name: auth.user.display_name }), {
            description: auth.organization ? t('orgReady', { name: auth.organization.name }) : undefined,
          })
          onAuthed()
        },
      })
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const verificationMutation = useMutation({
    mutationFn: async () => {
      await confirmEmailVerification({ token: verificationToken.trim() })
      // The confirmation endpoint returns {status:"ok"}, not a session. Only
      // after it succeeds do we log in (which sets the HttpOnly cookies).
      return login({ email: verificationEmail, password: regPassword })
    },
    onSuccess: (auth) => {
      toast.success(t('accountCreated', { name: auth.user.display_name }), {
        description: auth.organization ? t('orgReady', { name: auth.organization.name }) : undefined,
      })
      onAuthed()
    },
    // Do not display upstream error details here: a token is a credential and
    // must never be echoed back in UI errors or logs.
    onError: () => toast.error(t('verificationFailed')),
  })

  const resendMutation = useMutation({
    mutationFn: () => requestEmailVerification({ email: verificationEmail }),
    onSuccess: () => {
      setVerificationToken('')
      toast.success(t('verificationResent'))
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const demoMutation = useMutation({
    mutationFn: demoLogin,
    onSuccess: (demo) => {
      toast.info(t('demoReady'), { description: demo.note })
      onAuthed()
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submitLogin = (event: FormEvent) => {
    event.preventDefault()
    if (!loginEmail.trim() || !loginPassword) {
      toast.error(t('needCredentials'))
      return
    }
    loginMutation.mutate()
  }

  const submitRegister = (event: FormEvent) => {
    event.preventDefault()
    if (!regName.trim() || !regEmail.trim() || regPassword.length < 8) {
      toast.error(t('checkForm'), { description: t('formRequirements') })
      return
    }
    registerMutation.mutate()
  }

  const submitVerification = (event: FormEvent) => {
    event.preventDefault()
    const token = verificationToken.trim()
    if (token.length < 16 || token.length > 200) {
      toast.error(t('verificationCodeInvalid'))
      return
    }
    verificationMutation.mutate()
  }

  const busy =
    loginMutation.isPending ||
    registerMutation.isPending ||
    verificationMutation.isPending ||
    resendMutation.isPending ||
    demoMutation.isPending

  return (
    <div className="flex min-h-screen flex-col bg-stone-100">
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md space-y-4">
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-700 text-emerald-50 shadow-sm">
              <Sprout className="h-6 w-6" aria-hidden />
            </span>
            <h1 className="text-2xl font-semibold tracking-tight text-stone-900">CropTwist</h1>
            <p className="text-sm text-stone-500">{t('tagline')}</p>
          </div>

          <Card className="border-stone-200 shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{t('signInTitle')}</CardTitle>
              <CardDescription>{t('signInDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <BackendStatusLine />

              <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as 'login' | 'register')}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="login">{t('signInTab')}</TabsTrigger>
                  <TabsTrigger value="register">{t('registerTab')}</TabsTrigger>
                </TabsList>

                <TabsContent value="login">
                  <form onSubmit={submitLogin} className="space-y-3 pt-1" aria-label={t('signInForm')}>
                    <div className="space-y-1.5">
                      <Label htmlFor="login-email">{t('email')}</Label>
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
                      <Label htmlFor="login-password">{t('password')}</Label>
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
                      {t('signIn')}
                    </Button>
                  </form>
                </TabsContent>

                <TabsContent value="register">
                  {verificationEmail ? (
                    <div className="space-y-3 pt-1">
                      <div className="space-y-1.5" role="status">
                        <h2 className="text-sm font-semibold text-stone-900">{t('checkEmailTitle')}</h2>
                        <p className="text-sm text-stone-600">
                          {t('checkEmailDescription', { email: verificationEmail })}
                        </p>
                      </div>
                      <form
                        onSubmit={submitVerification}
                        className="space-y-3"
                        aria-label={t('verificationForm')}
                      >
                        <div className="space-y-1.5">
                          <Label htmlFor="verification-token">{t('verificationCode')}</Label>
                          <Input
                            id="verification-token"
                            type="text"
                            dir="ltr"
                            autoComplete="one-time-code"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                            maxLength={200}
                            placeholder={t('verificationCodePlaceholder')}
                            value={verificationToken}
                            onChange={(e) => setVerificationToken(e.target.value)}
                            disabled={busy}
                          />
                        </div>
                        <Button
                          type="submit"
                          className="w-full bg-emerald-700 hover:bg-emerald-800"
                          disabled={busy}
                        >
                          {verificationMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                          ) : (
                            <MailCheck className="h-4 w-4" aria-hidden />
                          )}
                          {t('verifyEmail')}
                        </Button>
                      </form>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full"
                        onClick={() => resendMutation.mutate()}
                        disabled={busy}
                      >
                        {resendMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <MailCheck className="h-4 w-4" aria-hidden />
                        )}
                        {t('resendVerification')}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        className="w-full text-stone-600"
                        onClick={() => {
                          setVerificationEmail('')
                          setVerificationToken('')
                        }}
                        disabled={busy}
                      >
                        {t('useDifferentEmail')}
                      </Button>
                    </div>
                  ) : (
                    <form onSubmit={submitRegister} className="space-y-3 pt-1" aria-label={t('registerForm')}>
                      <div className="space-y-1.5">
                        <Label htmlFor="reg-name">{t('displayName')}</Label>
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
                        <Label htmlFor="reg-email">{t('email')}</Label>
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
                        <Label htmlFor="reg-password">{t('password')}</Label>
                        <Input
                          id="reg-password"
                          type="password"
                          autoComplete="new-password"
                          placeholder={t('passwordPlaceholder')}
                          value={regPassword}
                          onChange={(e) => setRegPassword(e.target.value)}
                          disabled={busy}
                        />
                        <p className="text-xs text-stone-500">{t('passwordHint')}</p>
                      </div>
                      <Button
                        type="submit"
                        className="w-full bg-emerald-700 hover:bg-emerald-800"
                        disabled={busy}
                      >
                        {registerMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                        ) : (
                          <UserPlus className="h-4 w-4" aria-hidden />
                        )}
                        {t('createAccount')}
                      </Button>
                    </form>
                  )}
                </TabsContent>
              </Tabs>

              <div className="relative">
                <Separator />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-card px-2 text-xs uppercase tracking-wide text-stone-400">
                  {t('or')}
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
                {t('enterDemo')}
              </Button>
              <p className="flex items-start gap-1.5 text-xs text-stone-500">
                <Cloud className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>
                  {t('demoHintPrefix')}{' '}
                  <strong className="font-semibold text-stone-700">{t('demoHintStrong')}</strong>{' '}
                  {t('demoHintSuffix')}
                </span>
              </p>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}

export default AuthGate

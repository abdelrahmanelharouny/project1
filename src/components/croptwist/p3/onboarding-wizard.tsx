'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  AlertCircle,
  ArrowRight,
  Check,
  CircleDashed,
  CreditCard,
  Loader2,
  Map,
  Minus,
  RefreshCw,
  Sparkles,
  Sprout,
  Users,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { CreateOrgDialog } from '@/components/croptwist/p3/team-tab'
import { describeError } from '@/lib/api'
import {
  acceptInvitation,
  completeOnboardingStep,
  dismissOnboarding,
  getOnboardingProgress,
  listOrganizations,
  setOnboardingAccountType,
  skipOnboardingStep,
  type OnboardingStepId,
  type OnboardingStepState,
  type OrganizationType,
} from '@/lib/api-p3-account'
import { useCropTwistUi, type WorkspaceTab } from '@/lib/store'

// ---------------------------------------------------------------------------
// Step metadata
// ---------------------------------------------------------------------------

const STEP_KEYS: Record<OnboardingStepId, string> = {
  account: 'onboarding.stepAccount',
  account_type: 'onboarding.stepAccountType',
  organization: 'onboarding.stepOrganization',
  org_profile: 'onboarding.stepOrgProfile',
  first_farm: 'onboarding.stepFirstFarm',
  first_field: 'onboarding.stepFirstField',
  crops_priorities: 'onboarding.stepCrops',
  review: 'onboarding.stepReview',
  tour: 'onboarding.stepTour',
}

const ACCOUNT_TYPES: OrganizationType[] = ['individual', 'business', 'farm_org']

const TOUR_TARGETS: { tab: WorkspaceTab; labelKey: string; icon: React.ReactNode }[] = [
  { tab: 'overview', labelKey: 'onboarding.tourOverview', icon: <Sparkles className="h-4 w-4" aria-hidden /> },
  { tab: 'farms', labelKey: 'onboarding.tourFarms', icon: <Map className="h-4 w-4" aria-hidden /> },
  { tab: 'team', labelKey: 'onboarding.tourTeam', icon: <Users className="h-4 w-4" aria-hidden /> },
  { tab: 'billing', labelKey: 'onboarding.tourBilling', icon: <CreditCard className="h-4 w-4" aria-hidden /> },
  { tab: 'insights', labelKey: 'onboarding.tourInsights', icon: <Sparkles className="h-4 w-4" aria-hidden /> },
  { tab: 'reports', labelKey: 'onboarding.tourReports', icon: <CircleDashed className="h-4 w-4" aria-hidden /> },
  { tab: 'developer', labelKey: 'onboarding.tourDeveloper', icon: <CircleDashed className="h-4 w-4" aria-hidden /> },
]

// ---------------------------------------------------------------------------
// Stepper
// ---------------------------------------------------------------------------

function Stepper({ steps, current }: { steps: OnboardingStepState[]; current: OnboardingStepId }) {
  const t = useTranslations('p3')
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label={t('onboarding.title')}>
      {steps.map((step) => {
        const isCurrent = step.id === current
        const stateLabel = step.done
          ? t('onboarding.stateDone')
          : step.skipped
            ? t('onboarding.stateSkipped')
            : isCurrent
              ? t('onboarding.stateCurrent')
              : t('onboarding.statePending')
        return (
          <li
            key={step.id}
            aria-current={isCurrent ? 'step' : undefined}
            title={stateLabel}
            className={[
              'flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
              step.done
                ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                : step.skipped
                  ? 'border-stone-200 bg-stone-50 text-stone-400'
                  : isCurrent
                    ? 'border-emerald-600 bg-white text-emerald-800'
                    : 'border-stone-200 bg-white text-stone-400',
            ].join(' ')}
          >
            {step.done ? (
              <Check className="h-3 w-3" aria-hidden />
            ) : step.skipped ? (
              <Minus className="h-3 w-3" aria-hidden />
            ) : isCurrent ? (
              <span className="h-2 w-2 rounded-full bg-emerald-600" aria-hidden />
            ) : (
              <span className="h-2 w-2 rounded-full border border-stone-300" aria-hidden />
            )}
            <span className="max-w-[7.5rem] truncate">{t(STEP_KEYS[step.id])}</span>
          </li>
        )
      })}
    </ol>
  )
}

// ---------------------------------------------------------------------------
// Default export
// ---------------------------------------------------------------------------

export default function OnboardingWizard({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const queryClient = useQueryClient()
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)

  const progressQuery = useQuery({
    queryKey: ['p3-onboarding'],
    queryFn: getOnboardingProgress,
    enabled: open,
  })
  const progress = progressQuery.data ?? null
  const current: OnboardingStepId | null = progress?.current_step ?? null

  // Organization step reads the shared orgs cache (kept fresh by the Team tab).
  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listOrganizations,
    enabled: open,
  })

  const [accountType, setAccountType] = useState<OrganizationType>('individual')
  const [inviteToken, setInviteToken] = useState('')
  const [createOrgOpen, setCreateOrgOpen] = useState(false)
  const [dismissOpen, setDismissOpen] = useState(false)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['p3-onboarding'] })
  }

  const completeMutation = useMutation({
    mutationFn: ({ step, data }: { step: OnboardingStepId; data?: Record<string, unknown> }) =>
      completeOnboardingStep(step, data),
    onSuccess: invalidate,
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const skipMutation = useMutation({
    mutationFn: (step: OnboardingStepId) => skipOnboardingStep(step),
    onSuccess: invalidate,
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const accountTypeMutation = useMutation({
    mutationFn: (type: OrganizationType) => setOnboardingAccountType(type),
    onSuccess: invalidate,
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const dismissMutation = useMutation({
    mutationFn: dismissOnboarding,
    onSuccess: () => {
      invalidate()
      toast.info(t('onboarding.dismissed'))
      setDismissOpen(false)
      onOpenChange(false)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const joinMutation = useMutation({
    mutationFn: () => acceptInvitation(inviteToken.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      queryClient.invalidateQueries({ queryKey: ['p3-onboarding'] })
      toast.success(t('onboarding.joined'))
      setInviteToken('')
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description: t('onboarding.joinFailed') + (description ? ` · ${description}` : '') })
    },
  })

  const goTab = (tab: WorkspaceTab) => {
    setActiveTab(tab)
    onOpenChange(false)
  }

  const busy =
    completeMutation.isPending ||
    skipMutation.isPending ||
    accountTypeMutation.isPending ||
    joinMutation.isPending

  const complete = (step: OnboardingStepId, data?: Record<string, unknown>) =>
    completeMutation.mutate({ step, data })

  // ------------------------------------------------------------------ body
  let body: React.ReactNode = null

  if (progressQuery.isLoading) {
    body = (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-8 w-40" />
      </div>
    )
  } else if (progressQuery.isError || !progress || !current) {
    body = (
      <Alert variant="destructive" className="border-red-200 bg-red-50 [&>svg]:text-red-600">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle className="text-red-900">{t('onboarding.loadFailed')}</AlertTitle>
        <AlertDescription className="mt-2">
          <Button size="sm" variant="outline" onClick={() => progressQuery.refetch()} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t('team.retry')}
          </Button>
        </AlertDescription>
      </Alert>
    )
  } else {
    const orgs = orgsQuery.data?.items ?? []

    switch (current) {
      case 'account':
        body = (
          <div className="space-y-4">
            <p className="text-sm text-stone-600">{t('onboarding.accountDone')}</p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => complete('account')} disabled={busy} className="gap-1.5">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.continue')}
              </Button>
            </div>
          </div>
        )
        break

      case 'account_type': {
        const effective = progress.account_type ?? accountType
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.accountTypeTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.accountTypeDesc')}</p>
            </div>
            <RadioGroup
              value={effective}
              onValueChange={(value) => setAccountType(value as OrganizationType)}
              className="gap-2"
            >
              {ACCOUNT_TYPES.map((value) => (
                <Label
                  key={value}
                  htmlFor={`p3-ob-type-${value}`}
                  className="flex cursor-pointer items-start gap-2.5 rounded-md border border-stone-200 bg-white p-3 text-start font-normal hover:bg-stone-50 has-[[data-state=checked]]:border-emerald-600"
                >
                  <RadioGroupItem id={`p3-ob-type-${value}`} value={value} className="mt-0.5" />
                  <span className="space-y-0.5">
                    <span className="block text-sm font-medium text-stone-900">
                      {value === 'individual'
                        ? t('account.typeIndividual')
                        : value === 'business'
                          ? t('account.typeBusiness')
                          : t('account.typeFarmOrg')}
                    </span>
                    <span className="block text-xs text-stone-500">
                      {value === 'individual'
                        ? t('account.explainIndividual')
                        : value === 'business'
                          ? t('account.explainBusiness')
                          : t('account.explainFarmOrg')}
                    </span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => accountTypeMutation.mutate(effective)} disabled={busy}>
                {accountTypeMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                {t('onboarding.continue')}
              </Button>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break
      }

      case 'organization':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.orgTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.orgDesc')}</p>
            </div>
            {orgs.length > 0 ? (
              <div className="space-y-3">
                <p className="rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-sm text-emerald-900">
                  {t('onboarding.haveOrg', { name: orgs[0].name })}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => complete('organization')} disabled={busy}>
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                    {t('onboarding.continue')}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <Button onClick={() => setCreateOrgOpen(true)} variant="outline" className="gap-1.5">
                  <Users className="h-4 w-4" aria-hidden /> {t('onboarding.createOrgCta')}
                </Button>
                <div className="space-y-1.5 rounded-md border border-stone-200 p-3">
                  <Label htmlFor="p3-ob-token" className="text-xs text-stone-600">
                    {t('onboarding.joinTitle')}
                  </Label>
                  <div className="flex gap-2">
                    <Input
                      id="p3-ob-token"
                      value={inviteToken}
                      onChange={(event) => setInviteToken(event.target.value)}
                      placeholder={t('onboarding.tokenLabel')}
                      autoComplete="off"
                      dir="ltr"
                    />
                    <Button
                      variant="outline"
                      onClick={() => {
                        if (inviteToken.trim()) joinMutation.mutate()
                      }}
                      disabled={busy || !inviteToken.trim()}
                    >
                      {joinMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : null}
                      {t('onboarding.join')}
                    </Button>
                  </div>
                </div>
                <Button variant="ghost" onClick={() => onOpenChange(false)}>
                  {t('onboarding.doLater')}
                </Button>
              </div>
            )}
          </div>
        )
        break

      case 'org_profile':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.orgProfileTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.orgProfileDesc')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => goTab('team')} className="gap-1.5">
                <Users className="h-4 w-4" aria-hidden /> {t('onboarding.openTeam')}
              </Button>
              <Button onClick={() => complete('org_profile')} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.continue')}
              </Button>
              <Button
                variant="ghost"
                onClick={() => skipMutation.mutate('org_profile')}
                disabled={busy}
              >
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break

      case 'first_farm':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.firstFarmTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.firstFarmDesc')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => goTab('farms')} className="gap-1.5">
                <Map className="h-4 w-4" aria-hidden /> {t('onboarding.openFarms')}
              </Button>
              <Button onClick={() => complete('first_farm')} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.alreadyDone')}
              </Button>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break

      case 'first_field':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.firstFieldTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.firstFieldDesc')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => goTab('farms')} className="gap-1.5">
                <Map className="h-4 w-4" aria-hidden /> {t('onboarding.openFarms')}
              </Button>
              <Button onClick={() => complete('first_field')} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.alreadyDone')}
              </Button>
              <Button
                variant="ghost"
                onClick={() => skipMutation.mutate('first_field')}
                disabled={busy}
              >
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break

      case 'crops_priorities':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.cropsTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.cropsDesc')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => goTab('farms')} className="gap-1.5">
                <Sprout className="h-4 w-4" aria-hidden /> {t('onboarding.openFarms')}
              </Button>
              <Button onClick={() => complete('crops_priorities')} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.alreadyDone')}
              </Button>
              <Button
                variant="ghost"
                onClick={() => skipMutation.mutate('crops_priorities')}
                disabled={busy}
              >
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break

      case 'review': {
        const required = progress.steps.filter((step) => step.required)
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.reviewTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.reviewDesc')}</p>
            </div>
            <ul className="space-y-1.5">
              {required.map((step) => (
                <li key={step.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-stone-700">{t(STEP_KEYS[step.id])}</span>
                  <span
                    className={
                      step.done
                        ? 'text-xs font-medium text-emerald-700'
                        : 'text-xs font-medium text-amber-700'
                    }
                  >
                    {step.done ? t('onboarding.reviewDone') : t('onboarding.reviewPending')}
                  </span>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => complete('review')} disabled={busy} className="gap-1.5">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.continue')}
              </Button>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                {t('onboarding.doLater')}
              </Button>
            </div>
          </div>
        )
        break
      }

      case 'tour':
        body = (
          <div className="space-y-4">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-stone-900">{t('onboarding.tourTitle')}</h3>
              <p className="text-sm text-stone-500">{t('onboarding.tourDesc')}</p>
            </div>
            <ul className="space-y-1.5">
              {TOUR_TARGETS.map((target) => (
                <li key={target.tab}>
                  <button
                    type="button"
                    onClick={() => goTab(target.tab)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-stone-200 bg-white p-2.5 text-start text-sm text-stone-800 hover:bg-stone-50"
                  >
                    <span className="flex items-center gap-2">
                      {target.icon}
                      {t(target.labelKey)}
                    </span>
                    <span className="flex items-center gap-1 text-xs font-medium text-emerald-700">
                      {t('onboarding.open')}
                      <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => complete('tour')} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('onboarding.finish')}
              </Button>
              <Button
                variant="ghost"
                onClick={() => skipMutation.mutate('tour')}
                disabled={busy}
              >
                {t('onboarding.skipTour')}
              </Button>
              <Button
                variant="ghost"
                className="text-stone-500"
                onClick={() => setDismissOpen(true)}
                disabled={dismissMutation.isPending}
              >
                {t('onboarding.dismiss')}
              </Button>
            </div>
          </div>
        )
        break
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
              {t('onboarding.title')}
            </DialogTitle>
            <DialogDescription>{t('onboarding.subtitle')}</DialogDescription>
          </DialogHeader>
          {progress ? (
            <div className="pb-1">
              <Stepper steps={progress.steps} current={current ?? 'account'} />
            </div>
          ) : null}
          <div className="min-h-[12rem]">{body}</div>
        </DialogContent>
      </Dialog>

      <CreateOrgDialog open={createOrgOpen} onOpenChange={setCreateOrgOpen} />

      <AlertDialog open={dismissOpen} onOpenChange={setDismissOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('onboarding.dismissTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('onboarding.dismissDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tCommon('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-stone-700 text-white hover:bg-stone-800"
              onClick={(event) => {
                event.preventDefault()
                dismissMutation.mutate()
              }}
            >
              {dismissMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {t('onboarding.dismissAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

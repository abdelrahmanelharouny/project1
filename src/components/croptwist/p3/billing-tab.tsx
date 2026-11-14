'use client'

/**
 * P3 — Billing tab: subscription card, plan catalog, usage meters,
 * entitlements, invoices and the sandbox payment simulator.
 *
 * Data honesty: everything rendered comes from the billing API (plans,
 * subscription snapshot, usage counters, entitlements, invoices). Missing
 * prices are "contact sales", never invented; sandbox test mode is labelled
 * from the subscription's provider fields.
 */

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, ExternalLink, Info, X } from 'lucide-react'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/croptwist/state-views'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, describeError } from '@/lib/api'
import { formatDateTime, formatDay } from '@/lib/format'
import { useCropTwistUi } from '@/lib/store'
import {
  changeBillingSubscription,
  cancelBillingSubscription,
  getBillingEntitlements,
  getBillingSubscription,
  getBillingUsage,
  listBillingInvoices,
  listBillingPlans,
  listMyOrganizations,
  resumeBillingSubscription,
  sandboxBillingPay,
  startBillingSubscription,
  type BillingInvoice,
  type BillingSubscriptionInfo,
  type PlanCatalogItem,
  type SandboxPayOutcome,
} from '@/lib/api-p3-commercial'

type T = ReturnType<typeof useTranslations>

// --------------------------------------------------------------- helpers

function money(cents: number | null, currency: string, locale: string): string {
  if (cents === null) return '—'
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(cents / 100)
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`
  }
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'active':
      return 'border-emerald-300 bg-emerald-50 text-emerald-800'
    case 'trialing':
      return 'border-stone-300 bg-stone-100 text-stone-700'
    case 'past_due':
      return 'border-amber-300 bg-amber-50 text-amber-900'
    case 'grace':
      return 'border-amber-200 bg-amber-50/60 text-amber-800'
    case 'canceled':
      return 'border-red-200 bg-red-50 text-red-800'
    default:
      return 'border-stone-200 bg-stone-50 text-stone-500'
  }
}

function statusLabel(t: T, status: string): string {
  switch (status) {
    case 'active':
      return t('billing.statusActive')
    case 'trialing':
      return t('billing.statusTrialing')
    case 'past_due':
      return t('billing.statusPastDue')
    case 'grace':
      return t('billing.statusGrace')
    case 'canceled':
      return t('billing.statusCanceled')
    default:
      return t('billing.statusUnknown')
  }
}

function invoiceStatusLabel(t: T, status: string): string {
  switch (status) {
    case 'open':
      return t('billing.invoiceStatusOpen')
    case 'paid':
      return t('billing.invoiceStatusPaid')
    case 'void':
      return t('billing.invoiceStatusVoid')
    default:
      return status
  }
}

const ENTITLEMENT_KEYS: { key: string; labelKey: string }[] = [
  { key: 'max_farms', labelKey: 'entMaxFarms' },
  { key: 'max_fields', labelKey: 'entMaxFields' },
  { key: 'max_org_members', labelKey: 'entMaxOrgMembers' },
  { key: 'history_retention_years', labelKey: 'entHistoryRetentionYears' },
  { key: 'scenario_runs_per_month', labelKey: 'entScenarioRunsPerMonth' },
  { key: 'reports_per_month', labelKey: 'entReportsPerMonth' },
  { key: 'api_rate_limit_per_minute', labelKey: 'entApiRateLimitPerMinute' },
  { key: 'ai_messages_per_day', labelKey: 'entAiMessagesPerDay' },
  { key: 'advanced_analysis', labelKey: 'entAdvancedAnalysis' },
  { key: 'satellite_access', labelKey: 'entSatelliteAccess' },
  { key: 'api_enabled', labelKey: 'entApiEnabled' },
  { key: 'exports_enabled', labelKey: 'entExportsEnabled' },
  { key: 'analytics_access', labelKey: 'entAnalyticsAccess' },
]

function toastMutationError(t: T, err: unknown): void {
  if (err instanceof ApiError && err.status === 403) {
    toast.error(t('errors.forbiddenTitle'), { description: t('errors.forbiddenBody') })
    return
  }
  const d = describeError(err)
  toast.error(d.title, { description: d.description })
}

function InlineError({ err, t }: { err: unknown; t: T }) {
  const forbidden = err instanceof ApiError && err.status === 403
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-semibold">{forbidden ? t('errors.forbiddenTitle') : t('common.loadError')}</p>
      <p className="mt-1 text-xs leading-relaxed">
        {forbidden ? t('errors.forbiddenBody') : describeError(err).title}
      </p>
    </div>
  )
}

function NoOrgEmptyState({ t }: { t: T }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <p className="text-base font-semibold text-stone-900">{t('common.noOrgTitle')}</p>
        <p className="max-w-md text-sm text-stone-500">{t('common.noOrgBody')}</p>
        <Button
          className="mt-2 bg-emerald-700 text-white hover:bg-emerald-800"
          onClick={() => useCropTwistUi.getState().setActiveTab('team')}
        >
          {t('common.noOrgCta')}
        </Button>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ t, status }: { t: T; status: string }) {
  return (
    <Badge variant="outline" className={statusBadgeClass(status)}>
      {statusLabel(t, status)}
    </Badge>
  )
}

// --------------------------------------------------------------- component

export default function BillingTab() {
  const t = useTranslations('p3b')
  const locale = useLocale()
  const queryClient = useQueryClient()

  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listMyOrganizations,
    staleTime: 60_000,
    retry: 1,
  })
  const org = orgsQuery.data?.items[0] ?? null
  const orgId = org?.id ?? null

  const [period, setPeriod] = useState<'monthly' | 'yearly'>('monthly')
  const [sandboxHidden, setSandboxHidden] = useState(false)
  const [sandboxOutcome, setSandboxOutcome] = useState<SandboxPayOutcome>('succeeded')
  const [confirmPlan, setConfirmPlan] = useState<PlanCatalogItem | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [resumeOpen, setResumeOpen] = useState(false)

  const subQuery = useQuery({
    queryKey: ['p3-billing-subscription', orgId],
    queryFn: () => getBillingSubscription(orgId as string),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    retry: 1,
  })
  const usageQuery = useQuery({
    queryKey: ['p3-billing-usage', orgId],
    queryFn: () => getBillingUsage(orgId as string),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    retry: 1,
  })
  const entQuery = useQuery({
    queryKey: ['p3-billing-entitlements', orgId],
    queryFn: () => getBillingEntitlements(orgId as string),
    enabled: Boolean(orgId),
    staleTime: 60_000,
    retry: 1,
  })
  const invoicesQuery = useQuery({
    queryKey: ['p3-billing-invoices', orgId],
    queryFn: () => listBillingInvoices(orgId as string, { limit: 50 }),
    enabled: Boolean(orgId),
    staleTime: 30_000,
    retry: 1,
  })
  const plansQuery = useQuery({
    queryKey: ['p3-billing-plans'],
    queryFn: listBillingPlans,
    staleTime: 5 * 60_000,
    retry: 1,
  })

  const subscription: BillingSubscriptionInfo | null = subQuery.data?.subscription ?? null
  const liveSubscription = subscription !== null

  const invalidateBilling = () => {
    void queryClient.invalidateQueries({ queryKey: ['p3-billing-subscription'] })
    void queryClient.invalidateQueries({ queryKey: ['p3-billing-usage'] })
    void queryClient.invalidateQueries({ queryKey: ['p3-billing-entitlements'] })
    void queryClient.invalidateQueries({ queryKey: ['p3-billing-invoices'] })
  }

  const startM = useMutation({
    mutationFn: startBillingSubscription,
    onSuccess: (data) => {
      toast.success(t('billing.statusActive'), { description: data.subscription.plan?.name })
      if (data.checkout?.url) window.open(data.checkout.url, '_blank', 'noopener,noreferrer')
      setConfirmPlan(null)
      invalidateBilling()
    },
    onError: (err) => toastMutationError(t, err),
  })
  const changeM = useMutation({
    mutationFn: changeBillingSubscription,
    onSuccess: () => {
      toast.success(t('billing.changeConfirmTitle'))
      setConfirmPlan(null)
      invalidateBilling()
    },
    onError: (err) => toastMutationError(t, err),
  })
  const cancelM = useMutation({
    mutationFn: cancelBillingSubscription,
    onSuccess: () => {
      toast.success(t('billing.cancelDialogTitle'))
      setCancelOpen(false)
      invalidateBilling()
    },
    onError: (err) => {
      setCancelOpen(false)
      toastMutationError(t, err)
    },
  })
  const resumeM = useMutation({
    mutationFn: resumeBillingSubscription,
    onSuccess: () => {
      toast.success(t('billing.resumeDialogTitle'))
      setResumeOpen(false)
      invalidateBilling()
    },
    onError: (err) => {
      setResumeOpen(false)
      toastMutationError(t, err)
    },
  })
  const sandboxM = useMutation({
    mutationFn: sandboxBillingPay,
    onSuccess: (data) => {
      if (data.outcome === 'succeeded') toast.success(t('billing.sandboxPaidToast'))
      else toast.info(t('billing.sandboxDeclinedToast'))
      invalidateBilling()
    },
    onError: (err) => {
      // The server is the source of truth: if it refuses (non-sandbox
      // provider / missing role), the panel disappears instead of nagging.
      if (err instanceof ApiError && (err.status === 403 || err.status === 422)) {
        setSandboxHidden(true)
        return
      }
      toastMutationError(t, err)
    },
  })

  if (orgsQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (orgsQuery.isError) {
    return <ErrorState message={t('common.loadError')} onRetry={() => void orgsQuery.refetch()} />
  }
  if (!org) return <NoOrgEmptyState t={t} />

  const isTestProvider =
    subscription !== null && (subscription.provider === 'sandbox' || subscription.provider_mode === 'test')

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('billing.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('billing.intro')}</p>
      </header>

      {subQuery.isError ? (
        <InlineError err={subQuery.error} t={t} />
      ) : subQuery.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <SubscriptionCard
          t={t}
          subscription={subscription}
          onCancel={() => setCancelOpen(true)}
          onResume={() => setResumeOpen(true)}
        />
      )}

      {/* Plans */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">{t('billing.plansTitle')}</CardTitle>
              <CardDescription className="text-sm text-stone-500">{t('billing.plansDesc')}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="p3-billing-period"
                checked={period === 'yearly'}
                onCheckedChange={(checked) => setPeriod(checked ? 'yearly' : 'monthly')}
                aria-label={period === 'yearly' ? t('billing.yearly') : t('billing.monthly')}
              />
              <Label htmlFor="p3-billing-period" className="text-xs text-stone-600">
                {period === 'yearly' ? t('billing.yearly') : t('billing.monthly')}
              </Label>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {plansQuery.isLoading ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <Skeleton className="h-56 w-full" />
              <Skeleton className="h-56 w-full" />
              <Skeleton className="h-56 w-full" />
            </div>
          ) : plansQuery.isError ? (
            <InlineError err={plansQuery.error} t={t} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(plansQuery.data?.items ?? []).map((plan) => (
                <PlanCard
                  key={plan.id}
                  t={t}
                  plan={plan}
                  period={period}
                  locale={locale}
                  isCurrent={liveSubscription && subscription?.plan?.code === plan.code}
                  hasLiveSubscription={liveSubscription}
                  busy={startM.isPending || changeM.isPending}
                  onSelect={() => setConfirmPlan(plan)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Usage */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t('billing.usageTitle')}</CardTitle>
            <CardDescription className="text-sm text-stone-500">{t('billing.usageDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {usageQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : usageQuery.isError ? (
              <InlineError err={usageQuery.error} t={t} />
            ) : (
              <>
                {(usageQuery.data?.items ?? []).map((item) => (
                  <UsageRow key={item.key} t={t} item={item} />
                ))}
                <p className="text-xs text-stone-500">{t('billing.usageResets')}</p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t('billing.entitlementsTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            {entQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : entQuery.isError ? (
              <InlineError err={entQuery.error} t={t} />
            ) : (
              <ul className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
                {ENTITLEMENT_KEYS.map(({ key, labelKey }) => {
                  const entry = entQuery.data?.entitlements[key]
                  return <EntitlementRow key={key} t={t} labelKey={labelKey} entry={entry} />
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Invoices */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('billing.invoicesTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('billing.invoicesDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {invoicesQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : invoicesQuery.isError ? (
            <InlineError err={invoicesQuery.error} t={t} />
          ) : (
            <InvoicesTable t={t} invoices={invoicesQuery.data?.items ?? []} locale={locale} />
          )}
        </CardContent>
      </Card>

      {/* Sandbox payments (only when the provider says test mode) */}
      {isTestProvider && !sandboxHidden && (
        <Card className="border-amber-200 bg-amber-50/40">
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">{t('billing.sandboxTitle')}</CardTitle>
              <Badge variant="outline" className="border-amber-300 bg-amber-100 text-amber-900">
                {t('billing.testModeBadge')}
              </Badge>
            </div>
            <CardDescription className="text-sm text-amber-900/80">{t('billing.sandboxDesc')}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs text-stone-700" htmlFor="p3-sandbox-outcome">
                  {t('billing.sandboxOutcome')}
                </Label>
                <Select value={sandboxOutcome} onValueChange={(v) => setSandboxOutcome(v as SandboxPayOutcome)}>
                  <SelectTrigger id="p3-sandbox-outcome" className="h-9 w-40 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="succeeded">{t('billing.outcomeSucceeded')}</SelectItem>
                    <SelectItem value="declined">{t('billing.outcomeDeclined')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                variant="outline"
                disabled={sandboxM.isPending}
                onClick={() => sandboxM.mutate({ organization_id: org.id, outcome: sandboxOutcome })}
              >
                {sandboxM.isPending ? t('common.loading') : t('billing.sandboxPay')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Confirmations */}
      <AlertDialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('billing.cancelDialogTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('billing.cancelDialogBody', { date: formatDay(subscription?.current_period_end ?? null) })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-700 text-white hover:bg-red-800"
              onClick={(e) => {
                e.preventDefault()
                if (orgId) cancelM.mutate({ organization_id: orgId, at_period_end: true })
              }}
            >
              {t('billing.cancelConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={resumeOpen} onOpenChange={setResumeOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('billing.resumeDialogTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('billing.resumeDialogBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                if (orgId) resumeM.mutate(orgId)
              }}
            >
              {t('billing.resumeAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmPlan !== null} onOpenChange={(open) => !open && setConfirmPlan(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {liveSubscription ? t('billing.changeConfirmTitle') : t('billing.startConfirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {liveSubscription
                ? t('billing.changeConfirmBody', {
                    plan: confirmPlan?.name ?? '',
                    period: period === 'yearly' ? t('billing.periodYearly') : t('billing.periodMonthly'),
                  })
                : t('billing.startConfirmBody', {
                    plan: confirmPlan?.name ?? '',
                    period: period === 'yearly' ? t('billing.periodYearly') : t('billing.periodMonthly'),
                  })}
              {confirmPlan?.trial_days ? ` ${t('billing.startTrialNote', { days: confirmPlan.trial_days })}` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              onClick={(e) => {
                e.preventDefault()
                if (!confirmPlan || !orgId) return
                if (liveSubscription) {
                  changeM.mutate({
                    organization_id: orgId,
                    new_plan_code: confirmPlan.code,
                    billing_period: period,
                  })
                } else {
                  startM.mutate({ organization_id: orgId, plan_code: confirmPlan.code, billing_period: period })
                }
              }}
            >
              {liveSubscription ? t('billing.changeConfirm') : t('billing.startAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// --------------------------------------------------------------- pieces

function SubscriptionCard({
  t,
  subscription,
  onCancel,
  onResume,
}: {
  t: T
  subscription: BillingSubscriptionInfo | null
  onCancel: () => void
  onResume: () => void
}) {
  const isTest =
    subscription !== null && (subscription.provider === 'sandbox' || subscription.provider_mode === 'test')
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">{subscription?.plan?.name ?? t('billing.noSubscriptionTitle')}</CardTitle>
            {subscription ? <StatusBadge t={t} status={subscription.status} /> : null}
            {isTest ? (
              <Badge variant="outline" className="border-amber-300 bg-amber-100 text-amber-900">
                {t('billing.testModeBadge')}
              </Badge>
            ) : null}
            {subscription?.cancel_at_period_end ? (
              <Badge variant="outline" className="border-stone-300 bg-white text-stone-600">
                {t('billing.cancelScheduled')}
              </Badge>
            ) : null}
          </div>
          {subscription?.cancel_at_period_end ? (
            <Button size="sm" variant="outline" onClick={onResume}>
              {t('billing.resumeAction')}
            </Button>
          ) : subscription ? (
            <Button size="sm" variant="outline" className="text-red-700 hover:text-red-800" onClick={onCancel}>
              {t('billing.cancelAction')}
            </Button>
          ) : null}
        </div>
        <CardDescription className="text-sm text-stone-500">
          {subscription ? t('billing.intro') : t('billing.noSubscriptionBody')}
        </CardDescription>
      </CardHeader>
      {subscription ? (
        <CardContent className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          <Detail label={t('billing.billingPeriodLabel')} value={subscription.billing_period === 'yearly' ? t('billing.yearly') : t('billing.monthly')} />
          <Detail label={t('billing.periodStart')} value={formatDay(subscription.current_period_start)} />
          <Detail label={t('billing.periodEnd')} value={formatDay(subscription.current_period_end)} />
          {subscription.trial_ends_at ? (
            <Detail label={t('billing.trialEnds')} value={formatDateTime(subscription.trial_ends_at)} />
          ) : null}
          {subscription.grace_ends_at ? (
            <Detail label={t('billing.graceEnds')} value={formatDateTime(subscription.grace_ends_at)} />
          ) : null}
          <Detail
            label={t('billing.providerLabel')}
            value={`${subscription.provider} (${subscription.provider_mode})`}
          />
        </CardContent>
      ) : null}
      {isTest ? (
        <CardContent className="pt-0">
          <p className="text-xs text-amber-800">{t('billing.testModeNote')}</p>
        </CardContent>
      ) : null}
    </Card>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <p className="flex items-baseline justify-between gap-2 sm:justify-start sm:gap-3">
      <span className="text-xs text-stone-500">{label}</span>
      <span className="font-medium text-stone-900">{value}</span>
    </p>
  )
}

function PlanCard({
  t,
  plan,
  period,
  locale,
  isCurrent,
  hasLiveSubscription,
  busy,
  onSelect,
}: {
  t: T
  plan: PlanCatalogItem
  period: 'monthly' | 'yearly'
  locale: string
  isCurrent: boolean | null
  hasLiveSubscription: boolean
  busy: boolean
  onSelect: () => void
}) {
  const price = plan.prices.find((p) => p.billing_period === period) ?? null
  const monthly = plan.prices.find((p) => p.billing_period === 'monthly')?.amount_cents ?? null
  const yearly = plan.prices.find((p) => p.billing_period === 'yearly')?.amount_cents ?? null
  let savingsPct: number | null = null
  if (monthly !== null && yearly !== null && monthly > 0 && yearly >= 0) {
    const pctValue = Math.round((1 - yearly / 12 / monthly) * 100)
    if (pctValue > 0) savingsPct = pctValue
  }
  const selfServe = price !== null && price.amount_cents !== null

  return (
    <div
      className={`flex flex-col rounded-lg border p-4 ${
        isCurrent ? 'border-emerald-300 bg-emerald-50/40' : 'border-stone-200 bg-white'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold text-stone-900">{plan.name}</p>
        {isCurrent ? (
          <Badge variant="outline" className="border-emerald-300 bg-white text-emerald-800">
            {t('billing.currentPlanBadge')}
          </Badge>
        ) : null}
      </div>
      {plan.description ? <p className="mt-1 text-xs leading-relaxed text-stone-500">{plan.description}</p> : null}

      <div className="mt-3 flex items-baseline gap-2">
        {selfServe ? (
          <>
            <span className="text-xl font-semibold text-stone-900">
              {money(price?.amount_cents ?? null, price?.currency_code ?? 'USD', locale)}
            </span>
            <span className="text-xs text-stone-500">
              / {period === 'yearly' ? t('billing.yearly').toLowerCase() : t('billing.monthly').toLowerCase()}
            </span>
          </>
        ) : (
          <span className="text-sm font-medium text-stone-600">{t('billing.priceUnavailable')}</span>
        )}
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-xs text-stone-500">
        {savingsPct !== null && period === 'yearly' ? (
          <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-800">
            {t('billing.savings', { pct: savingsPct })}
          </Badge>
        ) : null}
        {plan.trial_days ? (
          <span>
            {plan.trial_days}d · {t('billing.statusTrialing').toLowerCase()}
          </span>
        ) : null}
      </div>

      <ul className="mt-3 flex-1 space-y-1">
        {ENTITLEMENT_KEYS.map(({ key, labelKey }) => {
          const value = plan.entitlements[key]
          if (value === undefined) return null
          if (typeof value === 'boolean') {
            return (
              <li key={key} className="flex items-center gap-1.5 text-xs">
                {value ? (
                  <Check className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
                ) : (
                  <X className="h-3.5 w-3.5 text-stone-400" aria-hidden />
                )}
                <span className={value ? 'text-stone-700' : 'text-stone-400'}>{t(`billing.${labelKey}`)}</span>
              </li>
            )
          }
          return (
            <li key={key} className="flex items-center gap-1.5 text-xs text-stone-700">
              <Check className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
              <span>
                {t(`billing.${labelKey}`)}:{' '}
                <span className="font-medium">{value === -1 ? t('common.unlimited') : value}</span>
              </span>
            </li>
          )
        })}
      </ul>

      <div className="mt-4">
        {isCurrent ? (
          <Button variant="outline" className="w-full" disabled>
            {t('billing.currentPlanBadge')}
          </Button>
        ) : selfServe ? (
          <Button
            className="w-full bg-emerald-700 text-white hover:bg-emerald-800"
            disabled={busy}
            onClick={onSelect}
          >
            {hasLiveSubscription ? t('billing.changeAction') : t('billing.startAction')}
          </Button>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <a
                href="mailto:sales@croptwist.example?subject=Plan%20quote"
                className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-md border border-stone-300 bg-white px-3 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
              >
                {t('billing.contactSales')}
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
            </TooltipTrigger>
            <TooltipContent className="max-w-56">
              <p>{t('billing.contactSalesTip')}</p>
            </TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  )
}

function UsageRow({ t, item }: { t: T; item: { key: string; limit: number; unlimited: boolean; used: number } }) {
  const labelKey = ENTITLEMENT_KEYS.find((e) => e.key === item.key)?.labelKey
  const label = labelKey ? t(`billing.${labelKey}`) : item.key
  const pctValue =
    item.unlimited || item.limit <= 0 ? null : Math.min(100, Math.round((item.used / item.limit) * 100))
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-stone-700">{label}</span>
        {item.unlimited ? (
          <span className="text-xs font-medium text-stone-500">{t('common.unlimited')}</span>
        ) : (
          <span className="text-xs text-stone-600">
            {t('billing.usageOf', { used: item.used, limit: item.limit })}
          </span>
        )}
      </div>
      {!item.unlimited && pctValue !== null ? <Progress className="mt-1 h-2" value={pctValue} aria-label={label} /> : null}
    </div>
  )
}

function EntitlementRow({
  t,
  labelKey,
  entry,
}: {
  t: T
  labelKey: string
  entry: { value: number | boolean; kind: 'int' | 'bool'; unlimited: boolean } | undefined
}) {
  if (!entry) return null
  return (
    <li className="flex items-center gap-1.5 text-xs">
      {entry.kind === 'bool' ? (
        entry.value ? (
          <>
            <Check className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
            <span className="text-stone-700">{t(`billing.${labelKey}`)}</span>
          </>
        ) : (
          <>
            <X className="h-3.5 w-3.5 text-stone-400" aria-hidden />
            <span className="text-stone-400">{t(`billing.${labelKey}`)}</span>
          </>
        )
      ) : (
        <>
          <Info className="h-3.5 w-3.5 text-stone-400" aria-hidden />
          <span className="text-stone-700">
            {t(`billing.${labelKey}`)}:{' '}
            <span className="font-medium">
              {entry.unlimited || entry.value === -1 ? t('common.unlimited') : entry.value}
            </span>
          </span>
        </>
      )}
    </li>
  )
}

function InvoicesTable({
  t,
  invoices,
  locale,
}: {
  t: T
  invoices: BillingInvoice[]
  locale: string
}) {
  if (invoices.length === 0) {
    return <p className="py-6 text-center text-sm text-stone-500">{t('billing.noInvoices')}</p>
  }
  const invoiceBadge = (status: string) =>
    status === 'paid'
      ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
      : status === 'open'
        ? 'border-amber-300 bg-amber-50 text-amber-900'
        : 'border-stone-300 bg-stone-100 text-stone-600'
  return (
    <>
      {/* Desktop table */}
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('billing.invoiceNumber')}</TableHead>
              <TableHead>{t('billing.invoiceIssued')}</TableHead>
              <TableHead>{t('billing.invoicePeriod')}</TableHead>
              <TableHead>{t('billing.invoiceAmount')}</TableHead>
              <TableHead>{t('billing.invoiceStatus')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invoices.map((inv) => (
              <TableRow key={inv.id}>
                <TableCell className="font-mono text-xs" dir="ltr">
                  {inv.number}
                </TableCell>
                <TableCell className="text-xs">{formatDay(inv.issued_at)}</TableCell>
                <TableCell className="text-xs">
                  {formatDay(inv.period_start)} — {formatDay(inv.period_end)}
                </TableCell>
                <TableCell className="text-xs font-medium">
                  {money(inv.amount_cents, inv.currency_code, locale)}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={invoiceBadge(inv.status)}>
                    {invoiceStatusLabel(t, inv.status)}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {/* Mobile stacked cards */}
      <div className="space-y-2 md:hidden">
        {invoices.map((inv) => (
          <div key={inv.id} className="rounded-lg border border-stone-200 bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-stone-900" dir="ltr">
                {inv.number}
              </span>
              <Badge variant="outline" className={invoiceBadge(inv.status)}>
                {invoiceStatusLabel(t, inv.status)}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-stone-600">
              {money(inv.amount_cents, inv.currency_code, locale)} · {formatDay(inv.issued_at)}
            </p>
            <p className="text-xs text-stone-500">
              {formatDay(inv.period_start)} — {formatDay(inv.period_end)}
            </p>
          </div>
        ))}
      </div>
    </>
  )
}

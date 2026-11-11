'use client'

/**
 * P3 — Developer console tab: API keys (create/rotate/revoke with
 * show-once secrets), webhooks (create/enable/rotate secret/delete +
 * delivery log with redeliver), request usage, and the event reference.
 *
 * Data honesty: plaintext secrets are displayed exactly once, as returned by
 * the API, with a copy action; scopes and event catalogs come from
 * GET /developer/events; usage numbers are summed from the API's daily
 * counters.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Copy, KeyRound, Plus, RotateCw, Trash2, Webhook } from 'lucide-react'
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
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, describeError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { useCropTwistUi } from '@/lib/store'
import {
  createDeveloperKey,
  createWebhook,
  deleteWebhook,
  getDeveloperEvents,
  getDeveloperUsage,
  listDeveloperKeys,
  listMyOrganizations,
  listWebhookDeliveries,
  listWebhooks,
  patchWebhook,
  redeliverWebhookDelivery,
  revokeDeveloperKey,
  rotateDeveloperKey,
  rotateWebhookSecret,
  type ApiKeyInfo,
  type WebhookDelivery,
  type WebhookEndpointInfo,
} from '@/lib/api-p3-commercial'

type T = ReturnType<typeof useTranslations>

// --------------------------------------------------------------- helpers

function toastMutationError(t: T, err: unknown): void {
  if (err instanceof ApiError && err.status === 403) {
    toast.error(t('errors.forbiddenTitle'), { description: t('errors.forbiddenBody') })
    return
  }
  const d = describeError(err)
  toast.error(d.title, { description: d.description })
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

function scopeDescription(t: T, scope: string): string | null {
  const map: Record<string, string> = {
    'org:read': 'scopeOrgRead',
    'farms:read': 'scopeFarmsRead',
    'fields:read': 'scopeFieldsRead',
    'crops:read': 'scopeCropsRead',
    'analytics:read': 'scopeAnalyticsRead',
    'recommendations:read': 'scopeRecommendationsRead',
    'reports:read': 'scopeReportsRead',
    'environment:read': 'scopeEnvironmentRead',
  }
  const key = map[scope]
  return key ? t(`developer.${key}`) : null
}

function eventDescription(t: T, event: string): string | null {
  const map: Record<string, string> = {
    'farm.updated': 'eventFarmUpdated',
    'field.created': 'eventFieldCreated',
    'crop_cycle.updated': 'eventCropCycleUpdated',
    'recommendation.generated': 'eventRecommendationGenerated',
    'report.ready': 'eventReportReady',
    'alert.raised': 'eventAlertRaised',
    'subscription.updated': 'eventSubscriptionUpdated',
  }
  const key = map[event]
  return key ? t(`developer.${key}`) : null
}

function deliveryBadge(t: T, status: string) {
  switch (status) {
    case 'delivered':
      return (
        <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-emerald-800">
          {t('developer.deliveryStatusDelivered')}
        </Badge>
      )
    case 'pending':
      return (
        <Badge variant="outline" className="gap-1.5 border-stone-300 bg-white text-stone-600">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-stone-400" aria-hidden />
          {t('developer.deliveryStatusPending')}
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-900">
          {t('developer.deliveryStatusFailed')}
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
          {t('developer.deliveryStatusDead')}
        </Badge>
      )
  }
}

function SecretOnceDialog({
  t,
  title,
  description,
  value,
  onClose,
}: {
  t: T
  title: string
  description: string
  value: string
  onClose: () => void
}) {
  const copy = () => {
    navigator.clipboard
      .writeText(value)
      .then(() => toast.success(t('common.copied')))
      .catch(() => undefined)
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-md border border-stone-300 bg-stone-50 p-2">
          <code className="min-w-0 flex-1 break-all font-mono text-xs text-stone-900" dir="ltr">
            {value}
          </code>
          <Button size="sm" variant="outline" onClick={copy} className="shrink-0">
            <Copy className="h-3.5 w-3.5" aria-hidden />
            {t('common.copy')}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t('common.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --------------------------------------------------------------- component

export default function DeveloperTab() {
  const t = useTranslations('p3b')
  const queryClient = useQueryClient()

  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listMyOrganizations,
    staleTime: 60_000,
    retry: 1,
  })
  const org = orgsQuery.data?.items[0] ?? null
  const orgId = org?.id ?? null

  const eventsQuery = useQuery({
    queryKey: ['p3-dev-events'],
    queryFn: getDeveloperEvents,
    staleTime: 10 * 60_000,
    retry: 1,
  })
  const keysQuery = useQuery({
    queryKey: ['p3-dev-keys', orgId],
    queryFn: () => listDeveloperKeys(orgId),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    retry: 1,
  })
  const webhooksQuery = useQuery({
    queryKey: ['p3-dev-webhooks', orgId],
    queryFn: () => listWebhooks(orgId),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    retry: 1,
  })
  const usageQuery = useQuery({
    queryKey: ['p3-dev-usage', orgId],
    queryFn: () => getDeveloperUsage(orgId, 30),
    enabled: Boolean(orgId),
    staleTime: 60_000,
    retry: 1,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['p3-dev-keys'] })
    void queryClient.invalidateQueries({ queryKey: ['p3-dev-webhooks'] })
    void queryClient.invalidateQueries({ queryKey: ['p3-dev-usage'] })
  }

  // --- key state
  const [keyCreateOpen, setKeyCreateOpen] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [keyScopes, setKeyScopes] = useState<string[]>([])
  const [secretOnce, setSecretOnce] = useState<{ title: string; description: string; value: string } | null>(null)
  const [rotateKey, setRotateKey] = useState<ApiKeyInfo | null>(null)
  const [revokeKey, setRevokeKey] = useState<ApiKeyInfo | null>(null)

  const createKeyM = useMutation({
    mutationFn: () =>
      createDeveloperKey({ name: keyName.trim(), scopes: keyScopes, organization_id: orgId }),
    onSuccess: (data) => {
      setKeyCreateOpen(false)
      setKeyName('')
      setKeyScopes([])
      toast.success(t('developer.keyCreated'))
      setSecretOnce({
        title: t('developer.secretTitle'),
        description: t('developer.secretDesc'),
        value: data.secret,
      })
      invalidate()
    },
    onError: (err) => toastMutationError(t, err),
  })
  const rotateKeyM = useMutation({
    mutationFn: (key: ApiKeyInfo) => rotateDeveloperKey(key.id, orgId),
    onSuccess: (data) => {
      setRotateKey(null)
      toast.success(t('developer.keyRotated'))
      setSecretOnce({
        title: t('developer.secretTitle'),
        description: t('developer.secretDesc'),
        value: data.secret,
      })
      invalidate()
    },
    onError: (err) => {
      setRotateKey(null)
      toastMutationError(t, err)
    },
  })
  const revokeKeyM = useMutation({
    mutationFn: (key: ApiKeyInfo) => revokeDeveloperKey(key.id, orgId),
    onSuccess: () => {
      setRevokeKey(null)
      toast.success(t('developer.keyRevoked'))
      invalidate()
    },
    onError: (err) => {
      setRevokeKey(null)
      toastMutationError(t, err)
    },
  })

  // --- webhook state
  const [whCreateOpen, setWhCreateOpen] = useState(false)
  const [whUrl, setWhUrl] = useState('')
  const [whEvents, setWhEvents] = useState<string[]>([])
  const [whDesc, setWhDesc] = useState('')
  const [whSecretRotate, setWhSecretRotate] = useState<WebhookEndpointInfo | null>(null)
  const [whDelete, setWhDelete] = useState<WebhookEndpointInfo | null>(null)
  const [expandedWh, setExpandedWh] = useState<string | null>(null)

  const createWhM = useMutation({
    mutationFn: () =>
      createWebhook({ url: whUrl.trim(), events: whEvents, description: whDesc.trim(), organization_id: orgId }),
    onSuccess: (data) => {
      setWhCreateOpen(false)
      setWhUrl('')
      setWhEvents([])
      setWhDesc('')
      toast.success(t('developer.whCreated'))
      setSecretOnce({
        title: t('developer.whSecretTitle'),
        description: t('developer.whSecretDesc'),
        value: data.secret,
      })
      invalidate()
    },
    onError: (err) => toastMutationError(t, err),
  })
  const patchWhM = useMutation({
    mutationFn: (input: { endpoint: WebhookEndpointInfo; enabled: boolean }) =>
      patchWebhook(input.endpoint.id, { enabled: input.enabled }, orgId),
    onSuccess: () => {
      toast.success(t('developer.whUpdated'))
      invalidate()
    },
    onError: (err) => toastMutationError(t, err),
  })
  const rotateWhM = useMutation({
    mutationFn: (endpoint: WebhookEndpointInfo) => rotateWebhookSecret(endpoint.id, orgId),
    onSuccess: (data) => {
      setWhSecretRotate(null)
      toast.success(t('developer.whSecretRotated'))
      setSecretOnce({
        title: t('developer.whSecretTitle'),
        description: t('developer.whSecretDesc'),
        value: data.secret,
      })
      invalidate()
    },
    onError: (err) => {
      setWhSecretRotate(null)
      toastMutationError(t, err)
    },
  })
  const deleteWhM = useMutation({
    mutationFn: (endpoint: WebhookEndpointInfo) => deleteWebhook(endpoint.id, orgId),
    onSuccess: () => {
      setWhDelete(null)
      toast.success(t('developer.whDeleted'))
      invalidate()
    },
    onError: (err) => {
      setWhDelete(null)
      toastMutationError(t, err)
    },
  })
  const redeliverM = useMutation({
    mutationFn: (input: { endpointId: string; deliveryId: string }) =>
      redeliverWebhookDelivery(input.endpointId, input.deliveryId, orgId),
    onSuccess: () => {
      toast.success(t('developer.redeliverDone'))
      void queryClient.invalidateQueries({ queryKey: ['p3-dev-deliveries'] })
    },
    onError: (err) => toastMutationError(t, err),
  })

  const deliveriesQuery = useQuery({
    queryKey: ['p3-dev-deliveries', expandedWh],
    queryFn: () => listWebhookDeliveries(expandedWh as string, orgId, { limit: 20 }),
    enabled: Boolean(expandedWh),
    staleTime: 5_000,
    retry: 1,
    refetchInterval: (query) => {
      const rows = query.state.data?.items ?? []
      return rows.some((d) => d.status === 'pending') ? 5000 : false
    },
  })

  if (orgsQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }
  if (!org) return <NoOrgEmptyState t={t} />

  const scopes = eventsQuery.data?.scopes ?? []
  const events = eventsQuery.data?.events ?? []
  const keys = keysQuery.data?.items ?? []
  const webhooks = webhooksQuery.data?.items ?? []

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('developer.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('developer.intro')}</p>
      </header>

      {/* API keys */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">{t('developer.keysTitle')}</CardTitle>
              <CardDescription className="text-sm text-stone-500">{t('developer.keysDesc')}</CardDescription>
            </div>
            <Button
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              onClick={() => setKeyCreateOpen(true)}
            >
              <Plus className="h-4 w-4" aria-hidden />
              {t('developer.createKey')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {keysQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : keysQuery.isError ? (
            <InlineError err={keysQuery.error} t={t} />
          ) : keys.length === 0 ? (
            <p className="py-6 text-center text-sm text-stone-500">{t('developer.keysDesc')}</p>
          ) : (
            <>
              <div className="hidden overflow-x-auto md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('developer.keyName')}</TableHead>
                      <TableHead>{t('developer.keyPrefixLabel')}</TableHead>
                      <TableHead>{t('developer.scopesLabel')}</TableHead>
                      <TableHead>{t('developer.lastUsed')}</TableHead>
                      <TableHead>{t('developer.created')}</TableHead>
                      <TableHead className="text-end">{t('reports.colActions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {keys.map((key) => (
                      <TableRow key={key.id}>
                        <TableCell className="text-sm font-medium text-stone-900">
                          {key.name}
                          {key.status !== 'active' ? (
                            <Badge variant="outline" className="ms-2 border-red-200 bg-red-50 text-red-700">
                              {t('developer.revoked')}
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <code className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-xs text-stone-700" dir="ltr">
                            {key.prefix}
                          </code>
                        </TableCell>
                        <TableCell>
                          <span className="flex flex-wrap gap-1">
                            {key.scopes.map((s) => (
                              <Tooltip key={s}>
                                <TooltipTrigger asChild>
                                  <Badge variant="outline" className="border-stone-200 bg-stone-50 font-mono text-[10px] text-stone-600">
                                    {s}
                                  </Badge>
                                </TooltipTrigger>
                                <TooltipContent>
                                  {scopeDescription(t, s) ?? s}
                                </TooltipContent>
                              </Tooltip>
                            ))}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs text-stone-600">
                          {key.last_used_at ? formatDateTime(key.last_used_at) : t('common.never')}
                        </TableCell>
                        <TableCell className="text-xs text-stone-600">{formatDateTime(key.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex items-center justify-end gap-1">
                            {key.status === 'active' ? (
                              <>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="h-8 w-8 text-stone-600 hover:text-emerald-800"
                                  disabled={rotateKeyM.isPending}
                                  onClick={() => setRotateKey(key)}
                                  aria-label={t('developer.rotate')}
                                  title={t('developer.rotate')}
                                >
                                  <RotateCw className="h-4 w-4" aria-hidden />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="h-8 w-8 text-stone-600 hover:text-red-700"
                                  disabled={revokeKeyM.isPending}
                                  onClick={() => setRevokeKey(key)}
                                  aria-label={t('developer.revoke')}
                                  title={t('developer.revoke')}
                                >
                                  <Trash2 className="h-4 w-4" aria-hidden />
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="space-y-2 md:hidden">
                {keys.map((key) => (
                  <div key={key.id} className="rounded-lg border border-stone-200 bg-white p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-stone-900">{key.name}</span>
                      {key.status !== 'active' ? (
                        <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
                          {t('developer.revoked')}
                        </Badge>
                      ) : null}
                    </div>
                    <code className="mt-1 inline-block rounded bg-stone-100 px-1.5 py-0.5 font-mono text-xs text-stone-700" dir="ltr">
                      {key.prefix}
                    </code>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {key.scopes.map((s) => (
                        <Badge key={s} variant="outline" className="border-stone-200 bg-stone-50 font-mono text-[10px] text-stone-600">
                          {s}
                        </Badge>
                      ))}
                    </div>
                    <p className="mt-1.5 text-xs text-stone-500">
                      {t('developer.lastUsed')}:{' '}
                      {key.last_used_at ? formatDateTime(key.last_used_at) : t('common.never')}
                    </p>
                    {key.status === 'active' ? (
                      <div className="mt-2 flex justify-end gap-2">
                        <Button size="sm" variant="outline" onClick={() => setRotateKey(key)}>
                          {t('developer.rotate')}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-red-700 hover:text-red-800"
                          onClick={() => setRevokeKey(key)}
                        >
                          {t('developer.revoke')}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Webhooks */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">{t('developer.webhooksTitle')}</CardTitle>
              <CardDescription className="text-sm text-stone-500">{t('developer.webhooksDesc')}</CardDescription>
            </div>
            <Button
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              onClick={() => setWhCreateOpen(true)}
            >
              <Plus className="h-4 w-4" aria-hidden />
              {t('developer.createWebhook')}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {webhooksQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : webhooksQuery.isError ? (
            <InlineError err={webhooksQuery.error} t={t} />
          ) : webhooks.length === 0 ? (
            <p className="py-6 text-center text-sm text-stone-500">{t('developer.webhooksDesc')}</p>
          ) : (
            webhooks.map((wh) => (
              <div key={wh.id} className="rounded-lg border border-stone-200 bg-white p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <Webhook className="h-4 w-4 shrink-0 text-stone-400" aria-hidden />
                    <code className="min-w-0 truncate font-mono text-xs text-stone-900" dir="ltr">
                      {wh.url}
                    </code>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5">
                      <Switch
                        checked={wh.status !== 'disabled'}
                        disabled={patchWhM.isPending}
                        onCheckedChange={(checked) => patchWhM.mutate({ endpoint: wh, enabled: checked })}
                        aria-label={t('developer.enabled')}
                      />
                      <span className="text-xs text-stone-600">{t('developer.enabled')}</span>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-stone-600 hover:text-emerald-800"
                      disabled={rotateWhM.isPending}
                      onClick={() => setWhSecretRotate(wh)}
                      aria-label={t('developer.whRotateSecret')}
                      title={t('developer.whRotateSecret')}
                    >
                      <RotateCw className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-stone-600 hover:text-red-700"
                      disabled={deleteWhM.isPending}
                      onClick={() => setWhDelete(wh)}
                      aria-label={t('developer.whDelete')}
                      title={t('developer.whDelete')}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {wh.event_types.map((e) => (
                    <Badge key={e} variant="outline" className="border-stone-200 bg-stone-50 font-mono text-[10px] text-stone-600">
                      {e}
                    </Badge>
                  ))}
                  {wh.consecutive_failures > 0 ? (
                    <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-900">
                      {t('developer.failures', { n: wh.consecutive_failures })}
                    </Badge>
                  ) : null}
                  {wh.status === 'disabled' && wh.disabled_reason ? (
                    <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
                      {t('developer.disabledByFailures')}
                    </Badge>
                  ) : null}
                </div>
                {wh.description ? <p className="mt-1 text-xs text-stone-500">{wh.description}</p> : null}

                <div className="mt-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs text-emerald-800"
                    onClick={() => setExpandedWh(expandedWh === wh.id ? null : wh.id)}
                    aria-expanded={expandedWh === wh.id}
                  >
                    {t('developer.deliveries')}
                  </Button>
                  {expandedWh === wh.id ? (
                    <DeliveriesPanel
                      t={t}
                      query={deliveriesQuery}
                      redeliverPending={redeliverM.isPending}
                      onRedeliver={(delivery) => redeliverM.mutate({ endpointId: wh.id, deliveryId: delivery.id })}
                    />
                  ) : null}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* Usage */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t('developer.usageTitle')}</CardTitle>
            <CardDescription className="text-sm text-stone-500">
              {t('developer.usageDesc', { days: usageQuery.data?.window_days ?? 30 })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {usageQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : usageQuery.isError ? (
              <InlineError err={usageQuery.error} t={t} />
            ) : usageQuery.data ? (
              <>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-stone-600">{t('developer.rateLimit')}:</span>
                  {usageQuery.data.rate_limit.unlimited ? (
                    <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-800">
                      {t('common.unlimited')}
                    </Badge>
                  ) : (
                    <span className="font-semibold text-stone-900">
                      {t('developer.rateLimitValue', { n: usageQuery.data.rate_limit.api_rate_limit_per_minute })}
                    </span>
                  )}
                  {!usageQuery.data.rate_limit.api_enabled ? (
                    <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-900">
                      {t('developer.apiDisabled')}
                    </Badge>
                  ) : null}
                </div>
                <ul className="space-y-2">
                  {usageQuery.data.keys.map((k) => {
                    const total = k.usage.reduce((sum, row) => sum + row.request_count, 0)
                    return (
                      <li
                        key={k.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-stone-100 bg-stone-50/50 px-3 py-2 text-sm"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <KeyRound className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
                          <span className="truncate text-stone-800">{k.name}</span>
                          <code className="rounded bg-white px-1 font-mono text-[10px] text-stone-500" dir="ltr">
                            {k.prefix}
                          </code>
                        </span>
                        <span className="text-xs tabular-nums text-stone-600">
                          {t('developer.usageRequests', { n: total })}
                          <span className="ms-2 text-stone-400">
                            {t('developer.usagePerKeyRate', { n: k.rate_limit_per_minute })}
                          </span>
                        </span>
                      </li>
                    )
                  })}
                </ul>
                <p className="text-[11px] leading-relaxed text-stone-400">{usageQuery.data.rate_limit.note}</p>
              </>
            ) : null}
          </CardContent>
        </Card>

        {/* Events reference */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t('developer.eventsTitle')}</CardTitle>
            <CardDescription className="text-sm text-stone-500">{t('developer.eventsDesc')}</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {events.map((e) => (
                <li key={e} className="text-sm">
                  <code className="font-mono text-xs text-stone-900" dir="ltr">
                    {e}
                  </code>
                  <p className="text-xs text-stone-500">{eventDescription(t, e) ?? '—'}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* Key create dialog */}
      <Dialog open={keyCreateOpen} onOpenChange={setKeyCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('developer.createKey')}</DialogTitle>
            <DialogDescription>{t('developer.keysDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-dev-key-name">
                {t('developer.keyName')}
              </Label>
              <Input
                id="p3-dev-key-name"
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                placeholder={t('developer.keyNamePh')}
                maxLength={120}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-stone-600">{t('developer.scopesLabel')}</Label>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {scopes.map((s) => (
                  <label key={s} className="flex items-center gap-2 text-xs text-stone-700">
                    <Checkbox
                      checked={keyScopes.includes(s)}
                      onCheckedChange={(checked) =>
                        setKeyScopes((prev) => (checked === true ? [...prev, s] : prev.filter((x) => x !== s)))
                      }
                    />
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="font-mono" dir="ltr">
                          {s}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {scopeDescription(t, s) ?? s}
                      </TooltipContent>
                    </Tooltip>
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-stone-400">{t('developer.scopesHint')}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setKeyCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              disabled={keyName.trim().length === 0 || keyScopes.length === 0 || createKeyM.isPending}
              onClick={() => createKeyM.mutate()}
            >
              {createKeyM.isPending ? t('common.loading') : t('developer.createKey')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Webhook create dialog */}
      <Dialog open={whCreateOpen} onOpenChange={setWhCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('developer.createWebhook')}</DialogTitle>
            <DialogDescription>{t('developer.webhooksDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-dev-wh-url">
                {t('developer.urlLabel')}
              </Label>
              <Input
                id="p3-dev-wh-url"
                type="url"
                dir="ltr"
                value={whUrl}
                onChange={(e) => setWhUrl(e.target.value)}
                placeholder={t('developer.urlPh')}
                maxLength={1000}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-stone-600">{t('developer.eventsLabel')}</Label>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {events.map((e) => (
                  <label key={e} className="flex items-center gap-2 text-xs text-stone-700">
                    <Checkbox
                      checked={whEvents.includes(e)}
                      onCheckedChange={(checked) =>
                        setWhEvents((prev) => (checked === true ? [...prev, e] : prev.filter((x) => x !== e)))
                      }
                    />
                    <span className="font-mono" dir="ltr">
                      {e}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-dev-wh-desc">
                {t('developer.descLabel')}
              </Label>
              <Input
                id="p3-dev-wh-desc"
                value={whDesc}
                onChange={(e) => setWhDesc(e.target.value)}
                maxLength={300}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWhCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              disabled={whUrl.trim().length === 0 || whEvents.length === 0 || createWhM.isPending}
              onClick={() => createWhM.mutate()}
            >
              {createWhM.isPending ? t('common.loading') : t('developer.createWebhook')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmations */}
      <AlertDialog open={rotateKey !== null} onOpenChange={(open) => !open && setRotateKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('developer.rotateTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('developer.rotateBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              onClick={(e) => {
                e.preventDefault()
                if (rotateKey) rotateKeyM.mutate(rotateKey)
              }}
            >
              {t('developer.rotate')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={revokeKey !== null} onOpenChange={(open) => !open && setRevokeKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('developer.revokeTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('developer.revokeBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-700 text-white hover:bg-red-800"
              onClick={(e) => {
                e.preventDefault()
                if (revokeKey) revokeKeyM.mutate(revokeKey)
              }}
            >
              {t('developer.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={whSecretRotate !== null} onOpenChange={(open) => !open && setWhSecretRotate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('developer.whRotateSecret')}</AlertDialogTitle>
            <AlertDialogDescription>{t('developer.whSecretDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              onClick={(e) => {
                e.preventDefault()
                if (whSecretRotate) rotateWhM.mutate(whSecretRotate)
              }}
            >
              {t('developer.whRotateSecret')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={whDelete !== null} onOpenChange={(open) => !open && setWhDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('developer.whDeleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('developer.whDeleteBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-700 text-white hover:bg-red-800"
              onClick={(e) => {
                e.preventDefault()
                if (whDelete) deleteWhM.mutate(whDelete)
              }}
            >
              {t('developer.whDelete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {secretOnce ? (
        <SecretOnceDialog
          t={t}
          title={secretOnce.title}
          description={secretOnce.description}
          value={secretOnce.value}
          onClose={() => setSecretOnce(null)}
        />
      ) : null}
    </div>
  )
}

// --------------------------------------------------------------- deliveries

function DeliveriesPanel({
  t,
  query,
  redeliverPending,
  onRedeliver,
}: {
  t: T
  query: {
    isLoading: boolean
    isError: boolean
    error: unknown
    data?: { items: WebhookDelivery[] } | undefined
  }
  redeliverPending: boolean
  onRedeliver: (delivery: WebhookDelivery) => void
}) {
  return (
    <div className="mt-1 space-y-2 rounded-md border border-stone-100 bg-stone-50/60 p-2">
      <p className="text-[11px] text-stone-400">{t('developer.deliveriesDesc')}</p>
      {query.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : query.isError ? (
        <InlineError err={query.error} t={t} />
      ) : (query.data?.items ?? []).length === 0 ? (
        <p className="py-3 text-center text-xs text-stone-500">{t('developer.noDeliveries')}</p>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('developer.colEvent')}</TableHead>
                  <TableHead>{t('developer.colStatus')}</TableHead>
                  <TableHead>{t('developer.colCode')}</TableHead>
                  <TableHead>{t('developer.colAttempt')}</TableHead>
                  <TableHead>{t('developer.colTime')}</TableHead>
                  <TableHead className="text-end">{t('developer.colActions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data?.items ?? []).map((d) => (
                  <DeliveryRow
                    key={d.id}
                    t={t}
                    delivery={d}
                    redeliverPending={redeliverPending}
                    onRedeliver={onRedeliver}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="space-y-2 md:hidden">
            {(query.data?.items ?? []).map((d) => (
              <div key={d.id} className="rounded-md border border-stone-200 bg-white p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <code className="font-mono text-stone-800" dir="ltr">
                    {d.event_type}
                  </code>
                  {deliveryBadge(t, d.status)}
                </div>
                <p className="mt-1 text-stone-500">
                  {d.last_status_code ?? '—'} · #{d.attempt} · {formatDateTime(d.created_at)}
                </p>
                {d.last_error ? <p className="mt-1 break-words text-[11px] text-red-700">{d.last_error}</p> : null}
                {(d.status === 'failed' || d.status === 'dead') ? (
                  <div className="mt-1.5 flex justify-end">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs"
                      disabled={redeliverPending}
                      onClick={() => onRedeliver(d)}
                    >
                      {t('developer.redeliver')}
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function DeliveryRow({
  t,
  delivery,
  redeliverPending,
  onRedeliver,
}: {
  t: T
  delivery: WebhookDelivery
  redeliverPending: boolean
  onRedeliver: (delivery: WebhookDelivery) => void
}) {
  const redeliverable = delivery.status === 'failed' || delivery.status === 'dead'
  return (
    <TableRow>
      <TableCell>
        <code className="font-mono text-xs text-stone-800" dir="ltr">
          {delivery.event_type}
        </code>
      </TableCell>
      <TableCell>{deliveryBadge(t, delivery.status)}</TableCell>
      <TableCell className="text-xs tabular-nums text-stone-600">{delivery.last_status_code ?? '—'}</TableCell>
      <TableCell className="text-xs tabular-nums text-stone-600">#{delivery.attempt}</TableCell>
      <TableCell className="text-xs text-stone-600">{formatDateTime(delivery.created_at)}</TableCell>
      <TableCell>
        <div className="flex justify-end">
          {redeliverable ? (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={redeliverPending}
              onClick={() => onRedeliver(delivery)}
            >
              {t('developer.redeliver')}
            </Button>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  )
}

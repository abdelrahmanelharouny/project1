'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  AlertCircle,
  Bell,
  CheckCheck,
  Loader2,
  RefreshCw,
  Settings2,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatRelativeTime } from '@/components/croptwist/p3/team-tab'
import { describeError } from '@/lib/api'
import {
  getNotificationPreferences,
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  putNotificationPreference,
  type NotificationCategory,
  type NotificationItem,
  type NotificationSeverity,
} from '@/lib/api-p3-account'
import { useCropTwistUi, type WorkspaceTab } from '@/lib/store'

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

/** Severity dot colors: info=stone, advisory=emerald, warning=amber, critical=red. */
function severityDotClass(severity: NotificationSeverity): string {
  switch (severity) {
    case 'advisory':
      return 'bg-emerald-500'
    case 'warning':
      return 'bg-amber-500'
    case 'critical':
      return 'bg-red-600'
    default:
      return 'bg-stone-400'
  }
}

function severityLabelKey(severity: NotificationSeverity): string {
  switch (severity) {
    case 'advisory':
      return 'notifications.severityAdvisory'
    case 'warning':
      return 'notifications.severityWarning'
    case 'critical':
      return 'notifications.severityCritical'
    default:
      return 'notifications.severityInfo'
  }
}

function categoryLabelKey(category: NotificationCategory): string {
  switch (category) {
    case 'agronomic_alert':
      return 'notifications.categoryAgronomicAlert'
    case 'data_freshness':
      return 'notifications.categoryDataFreshness'
    case 'recommendation_update':
      return 'notifications.categoryRecommendationUpdate'
    case 'report_ready':
      return 'notifications.categoryReportReady'
    case 'invitation':
      return 'notifications.categoryInvitation'
    case 'subscription':
      return 'notifications.categorySubscription'
    case 'billing':
      return 'notifications.categoryBilling'
    default:
      return 'notifications.categorySystem'
  }
}

/** Best-effort mapping of notification link kinds to workspace tabs. Only
 * recognized kinds navigate; everything else simply marks the row read. */
function linkKindToTab(kind: string | null): WorkspaceTab | null {
  if (!kind) return null
  const map: Record<string, WorkspaceTab> = {
    farm: 'farms',
    field: 'farms',
    observation: 'farms',
    report: 'reports',
    report_job: 'reports',
    recommendation: 'insights',
    billing: 'billing',
    subscription: 'billing',
    invoice: 'billing',
    invitation: 'team',
    membership: 'team',
    organization: 'team',
    api_key: 'developer',
    webhook: 'developer',
  }
  return map[kind] ?? null
}

// ---------------------------------------------------------------------------
// NotificationsBell (default export)
// ---------------------------------------------------------------------------

export default function NotificationsBell() {
  const t = useTranslations('p3')
  const locale = useLocale()
  const queryClient = useQueryClient()
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)

  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const [prefsOpen, setPrefsOpen] = useState(false)

  // Unread count — polled every 60 s so the badge stays fresh while the
  // panel is closed. If the user has no organization yet the endpoint is
  // Forbidden; the badge simply stays hidden.
  const unreadQuery = useQuery({
    queryKey: ['p3-notif-unread'],
    queryFn: getUnreadNotificationCount,
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  })
  const unread = unreadQuery.data?.unread ?? 0

  const listQuery = useQuery({
    queryKey: ['p3-notifs', filter],
    queryFn: () => listNotifications({ unread_only: filter === 'unread', limit: 30 }),
    enabled: open,
  })
  const items: NotificationItem[] = listQuery.data?.items ?? []

  const markReadMutation = useMutation({
    mutationFn: (notificationId: string) => markNotificationRead(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-notifs'] })
      queryClient.invalidateQueries({ queryKey: ['p3-notif-unread'] })
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-notifs'] })
      queryClient.invalidateQueries({ queryKey: ['p3-notif-unread'] })
      toast.success(t('notifications.markedAll'))
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const onRowClick = (item: NotificationItem) => {
    if (!item.read) markReadMutation.mutate(item.id)
    const tab = linkKindToTab(item.link_kind)
    if (tab) {
      setActiveTab(tab)
      setOpen(false)
    }
  }

  const badgeLabel = unread > 0 ? t('notifications.unreadBadge', { count: unread }) : t('notifications.bell')

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="relative h-9 w-9 text-stone-600 hover:text-stone-900"
            aria-label={badgeLabel}
          >
            <Bell className="h-4 w-4" aria-hidden />
            {unread > 0 ? (
              <span className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-emerald-700 px-1 text-[10px] font-medium leading-none text-white">
                {unread > 99 ? '99+' : unread}
              </span>
            ) : null}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-0 sm:w-96">
          <div className="flex items-center justify-between gap-2 border-b border-stone-100 px-3 py-2.5">
            <p className="text-sm font-semibold text-stone-900">{t('notifications.title')}</p>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 gap-1.5 px-2 text-xs text-stone-600"
              onClick={() => markAllMutation.mutate()}
              disabled={markAllMutation.isPending || unread === 0}
            >
              {markAllMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              )}
              {t('notifications.markAllRead')}
            </Button>
          </div>

          <div className="px-3 pt-2">
            <Tabs value={filter} onValueChange={(value) => setFilter(value as 'all' | 'unread')}>
              <TabsList className="h-8 w-full">
                <TabsTrigger value="all" className="h-7 text-xs">
                  {t('notifications.filterAll')}
                </TabsTrigger>
                <TabsTrigger value="unread" className="h-7 text-xs">
                  {t('notifications.filterUnread')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="max-h-96 overflow-y-auto scrollbar-thin">
            {listQuery.isLoading ? (
              <div className="space-y-2 p-3" aria-hidden>
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-12 w-full" />
                ))}
              </div>
            ) : listQuery.isError ? (
              <div className="p-3">
                <Alert variant="destructive" className="border-red-200 bg-red-50 [&>svg]:text-red-600">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle className="text-red-900">{t('notifications.loadFailed')}</AlertTitle>
                  <AlertDescription className="mt-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => listQuery.refetch()}
                      className="gap-1.5"
                    >
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t('notifications.retry')}
                    </Button>
                  </AlertDescription>
                </Alert>
              </div>
            ) : items.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-stone-500">
                {filter === 'unread' ? t('notifications.emptyUnread') : t('notifications.emptyAll')}
              </p>
            ) : (
              <ul className="divide-y divide-stone-100">
                {items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onRowClick(item)}
                      className="flex w-full items-start gap-2.5 px-3 py-2.5 text-start hover:bg-stone-50"
                    >
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${severityDotClass(item.severity)}`}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span
                            className={[
                              'truncate text-sm',
                              item.read ? 'text-stone-600' : 'font-medium text-stone-900',
                            ].join(' ')}
                          >
                            {item.title}
                          </span>
                          <span className="shrink-0 text-[11px] text-stone-400">
                            {formatRelativeTime(item.created_at, locale)}
                          </span>
                        </span>
                        {item.body ? (
                          <span className="mt-0.5 line-clamp-2 block text-xs text-stone-500">
                            {item.body}
                          </span>
                        ) : null}
                        <span className="mt-1 flex items-center gap-1.5">
                          <Badge
                            variant="outline"
                            className="border-stone-200 bg-stone-50 px-1.5 py-0 text-[10px] font-normal text-stone-500"
                          >
                            {t(categoryLabelKey(item.category))}
                          </Badge>
                          <Badge
                            variant="outline"
                            className="border-stone-200 bg-white px-1.5 py-0 text-[10px] font-normal text-stone-500"
                          >
                            {t(severityLabelKey(item.severity))}
                          </Badge>
                          {!item.read ? (
                            <span className="text-[10px] font-medium text-emerald-700">
                              {t('notifications.filterUnread')}
                            </span>
                          ) : null}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-stone-100 px-3 py-2">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-full justify-start gap-1.5 px-2 text-xs text-stone-600"
              onClick={() => setPrefsOpen(true)}
            >
              <Settings2 className="h-3.5 w-3.5" aria-hidden /> {t('notifications.openPrefs')}
            </Button>
          </div>
        </PopoverContent>
      </Popover>

      <NotificationPrefsDialog open={prefsOpen} onOpenChange={setPrefsOpen} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Per-category delivery preferences (footer dialog)
// ---------------------------------------------------------------------------

function NotificationPrefsDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useTranslations('p3')
  const queryClient = useQueryClient()

  const prefsQuery = useQuery({
    queryKey: ['p3-notif-prefs'],
    queryFn: getNotificationPreferences,
    enabled: open,
  })
  const prefs = prefsQuery.data?.items ?? []

  const mutation = useMutation({
    mutationFn: (input: { category: NotificationCategory; inApp: boolean; email: boolean }) =>
      putNotificationPreference({
        category: input.category,
        in_app_enabled: input.inApp,
        email_enabled: input.email,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-notif-prefs'] })
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(t('notifications.prefsSaveError'), {
        description: `${title}${description ? ` · ${description}` : ''}`,
      })
    },
  })

  const setPref = (
    item: { category: NotificationCategory; in_app_enabled: boolean; email_enabled: boolean },
    field: 'in_app' | 'email',
    value: boolean,
  ) => {
    mutation.mutate({
      category: item.category,
      inApp: field === 'in_app' ? value : item.in_app_enabled,
      email: field === 'email' ? value : item.email_enabled,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('notifications.prefsTitle')}</DialogTitle>
          <DialogDescription>{t('notifications.prefsDesc')}</DialogDescription>
        </DialogHeader>
        {prefsQuery.isLoading ? (
          <div className="space-y-2" aria-hidden>
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : prefsQuery.isError ? (
          <Alert variant="destructive" className="border-red-200 bg-red-50 [&>svg]:text-red-600">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle className="text-red-900">{t('notifications.loadFailed')}</AlertTitle>
            <AlertDescription className="mt-2">
              <Button size="sm" variant="outline" onClick={() => prefsQuery.refetch()} className="gap-1.5">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t('notifications.retry')}
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-1">
            <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-3 px-1 pb-1 text-[11px] font-medium uppercase tracking-wide text-stone-400">
              <span />
              <span>{t('notifications.colInApp')}</span>
              <span>{t('notifications.colEmail')}</span>
            </div>
            <Separator className="bg-stone-100" />
            {prefs.map((item) => (
              <div
                key={item.category}
                className="grid grid-cols-[1fr_auto_auto] items-center gap-x-3 py-1.5"
              >
                <Label
                  htmlFor={`p3-notif-${item.category}`}
                  className="text-sm font-normal text-stone-700"
                >
                  {t(categoryLabelKey(item.category))}
                </Label>
                <Switch
                  id={`p3-notif-${item.category}`}
                  checked={item.in_app_enabled}
                  disabled={mutation.isPending}
                  onCheckedChange={(value) => setPref(item, 'in_app', value)}
                />
                <Switch
                  checked={item.email_enabled}
                  disabled={mutation.isPending}
                  onCheckedChange={(value) => setPref(item, 'email', value)}
                  aria-label={`${t(categoryLabelKey(item.category))} — ${t('notifications.colEmail')}`}
                />
              </div>
            ))}
            <p className="pt-2 text-xs text-stone-500">{t('notifications.emailHint')}</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

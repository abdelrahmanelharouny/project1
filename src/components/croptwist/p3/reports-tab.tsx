'use client'

/**
 * P3 — Reports tab: generation form (10 report types, pdf/xlsx/csv, en/ar
 * locale, org/farm scope, date range, optional recurrence) plus the report
 * library with download / regenerate / schedule / delete.
 *
 * Data honesty: failed jobs surface the exact API error string; statuses and
 * sizes come from the server only. While any job is queued/running the list
 * re-polls every 3 seconds.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Download, FileText, RefreshCw, Repeat, Trash2 } from 'lucide-react'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, describeError } from '@/lib/api'
import { formatDateTime, formatDay } from '@/lib/format'
import { p07ReportTypes, type ReportTypeOption } from '@/lib/analytics/p07-utils'
import { useCropTwistUi } from '@/lib/store'
import { useFarms } from '@/hooks/use-croptwist'
import { InlineError, NoOrgEmptyState } from './settings-shared'
import {
  createReport,
  deleteReport,
  downloadReport,
  listMyOrganizations,
  listReports,
  regenerateReport,
  scheduleReport,
  type ReportJob,
} from '@/lib/api-p3-commercial'

type T = ReturnType<typeof useTranslations>

/**
 * P07 W2: the report-type picker is assembled in ONE place
 * (p07ReportTypes() — legacy registry + the 3 new P07 keys, deduped).
 * Legacy labels live in `p3b.reports.*`, P07 labels in `p07analytics.reportTypes.*`.
 */
const REPORT_TYPES: ReportTypeOption[] = p07ReportTypes()

function reportTypeLabel(t: T, tP07: T, reportType: string): string {
  const entry = REPORT_TYPES.find((r) => r.value === reportType)
  if (!entry) return reportType
  return entry.ns === 'p07analytics'
    ? tP07(`reportTypes.${entry.labelKey}`)
    : t(`reports.${entry.labelKey}`)
}

function statusLabel(t: T, status: string): string {
  switch (status) {
    case 'queued':
      return t('reports.statusQueued')
    case 'running':
      return t('reports.statusRunning')
    case 'succeeded':
      return t('reports.statusSucceeded')
    case 'failed':
      return t('reports.statusFailed')
    case 'expired':
      return t('reports.statusExpired')
    default:
      return status
  }
}

function statusBadge(t: T, status: string) {
  switch (status) {
    case 'succeeded':
      return (
        <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-emerald-800">
          {statusLabel(t, status)}
        </Badge>
      )
    case 'running':
      return (
        <Badge variant="outline" className="gap-1.5 border-emerald-200 bg-white text-emerald-800">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden />
          {statusLabel(t, status)}
        </Badge>
      )
    case 'queued':
      return (
        <Badge variant="outline" className="gap-1.5 border-stone-300 bg-white text-stone-600">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-stone-400" aria-hidden />
          {statusLabel(t, status)}
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
          {statusLabel(t, status)}
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="border-stone-200 bg-stone-50 text-stone-400">
          {statusLabel(t, status)}
        </Badge>
      )
  }
}

function formatSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function toastMutationError(t: T, err: unknown): void {
  if (err instanceof ApiError && err.status === 403) {
    toast.error(t('errors.forbiddenTitle'), { description: t('errors.forbiddenBody') })
    return
  }
  const d = describeError(err)
  toast.error(d.title, { description: d.description })
}

async function saveBlob(blob: Blob, filename: string): Promise<void> {
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

// --------------------------------------------------------------- component

export default function ReportsTab() {
  const t = useTranslations('p3b')
  const tP07 = useTranslations('p07analytics')
  const queryClient = useQueryClient()
  // P07: single-field scope follows the shared field context (zustand store).
  const selectedField = useCropTwistUi((s) => s.selectedField)

  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listMyOrganizations,
    staleTime: 60_000,
    retry: 1,
  })
  const org = orgsQuery.data?.items[0] ?? null
  const orgId = org?.id ?? null
  const farmsQuery = useFarms(Boolean(orgId))

  const [type, setType] = useState('farm_performance')
  const [format, setFormat] = useState<'pdf' | 'xlsx' | 'csv'>('pdf')
  const [reportLocale, setReportLocale] = useState<'en' | 'ar'>('en')
  const [scope, setScope] = useState('org')
  const [instant, setInstant] = useState(true)
  const [repeat, setRepeat] = useState<'none' | 'weekly' | 'monthly'>('none')
  const today = new Date().toISOString().slice(0, 10)
  const monthAgo = new Date(Date.now() - 29 * 86400_000).toISOString().slice(0, 10)
  const [dateFrom, setDateFrom] = useState(monthAgo)
  const [dateTo, setDateTo] = useState(today)

  const listQuery = useQuery({
    queryKey: ['p3-reports', orgId],
    queryFn: () => listReports({ limit: 50 }),
    enabled: Boolean(orgId),
    staleTime: 5_000,
    retry: 1,
    refetchInterval: (query) => {
      const rows = query.state.data?.items ?? []
      return rows.some((r) => r.status === 'queued' || r.status === 'running') ? 3000 : false
    },
  })

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['p3-reports'] })

  const createM = useMutation({
    mutationFn: async () => {
      const job = await createReport({
        report_type: type,
        format,
        locale: reportLocale,
        farm_id: scope === 'org' ? null : scope,
        // P07 backend contract: field_id scopes single-field report types
        // (field_intelligence / satellite_vegetation / spatial_anomalies).
        field_id: selectedField?.id ?? null,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        sync: instant && format !== 'pdf',
      })
      if (repeat !== 'none') {
        await scheduleReport(job.id, repeat === 'weekly' ? 7 : 30)
      }
      return job
    },
    onSuccess: async (job) => {
      if (job.status === 'failed') {
        toast.error(t('reports.genFailed'), { description: job.error ?? undefined })
      } else if (job.status === 'succeeded') {
        toast.success(t('reports.genInstant'))
        try {
          const dl = await downloadReport(job.id)
          await saveBlob(dl.blob, dl.filename)
          toast.success(t('reports.downloadDone'))
        } catch (err) {
          toastMutationError(t, err)
        }
      } else {
        toast.success(t('reports.genQueued'))
      }
      invalidate()
    },
    onError: (err) => toastMutationError(t, err),
  })

  const [downloadJob, setDownloadJob] = useState<ReportJob | null>(null)
  const downloadM = useMutation({
    mutationFn: async (job: ReportJob) => {
      setDownloadJob(job)
      const dl = await downloadReport(job.id)
      await saveBlob(dl.blob, dl.filename)
    },
    onSuccess: () => {
      toast.success(t('reports.downloadDone'))
      setDownloadJob(null)
      invalidate()
    },
    onError: (err) => {
      setDownloadJob(null)
      toastMutationError(t, err)
    },
  })

  const regenM = useMutation({
    mutationFn: (job: ReportJob) => regenerateReport(job.id),
    onSuccess: (job) => {
      if (job.status === 'failed') {
        toast.error(t('reports.genFailed'), { description: job.error ?? undefined })
      } else {
        toast.success(t('reports.regenDone'))
      }
      invalidate()
    },
    onError: (err) => toastMutationError(t, err),
  })

  const [deleteJob, setDeleteJob] = useState<ReportJob | null>(null)
  const deleteM = useMutation({
    mutationFn: (job: ReportJob) => deleteReport(job.id),
    onSuccess: () => {
      setDeleteJob(null)
      invalidate()
    },
    onError: (err) => {
      setDeleteJob(null)
      toastMutationError(t, err)
    },
  })

  const [schedJob, setSchedJob] = useState<ReportJob | null>(null)
  const [schedValue, setSchedValue] = useState<'none' | 'weekly' | 'monthly'>('none')
  const schedM = useMutation({
    mutationFn: (input: { jobId: string; interval: number | null }) =>
      scheduleReport(input.jobId, input.interval),
    onSuccess: () => {
      toast.success(t('reports.schedSaved'))
      setSchedJob(null)
      invalidate()
    },
    onError: (err) => {
      setSchedJob(null)
      toastMutationError(t, err)
    },
  })

  if (orgsQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!org) return <NoOrgEmptyState />

  const rows = listQuery.data?.items ?? []

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('reports.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('reports.intro')}</p>
      </header>

      {/* Generate */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('reports.genTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('reports.genDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-type">
                {t('reports.typeLabel')}
              </Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger id="p3-rep-type" className="h-9 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REPORT_TYPES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.ns === 'p07analytics'
                        ? tP07(`reportTypes.${r.labelKey}`)
                        : t(`reports.${r.labelKey}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-format">
                {t('reports.formatLabel')}
              </Label>
              <Select value={format} onValueChange={(v) => setFormat(v as 'pdf' | 'xlsx' | 'csv')}>
                <SelectTrigger id="p3-rep-format" className="h-9 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pdf">PDF</SelectItem>
                  <SelectItem value="xlsx">XLSX</SelectItem>
                  <SelectItem value="csv">CSV</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-locale">
                {t('reports.localeLabel')}
              </Label>
              <Select value={reportLocale} onValueChange={(v) => setReportLocale(v as 'en' | 'ar')}>
                <SelectTrigger id="p3-rep-locale" className="h-9 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">{t('reports.localeEn')}</SelectItem>
                  <SelectItem value="ar">{t('reports.localeAr')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-scope">
                {t('reports.scopeLabel')}
              </Label>
              <Select value={scope} onValueChange={setScope}>
                <SelectTrigger id="p3-rep-scope" className="h-9 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="org">{t('reports.scopeOrg')}</SelectItem>
                  {(farmsQuery.data?.items ?? []).map((farm) => (
                    <SelectItem key={farm.id} value={farm.id}>
                      {farm.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-from">
                {t('common.from')}
              </Label>
              <Input
                id="p3-rep-from"
                className="h-9"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="p3-rep-to">
                {t('common.to')}
              </Label>
              <Input
                id="p3-rep-to"
                className="h-9"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="p3-rep-instant"
                  checked={instant && format !== 'pdf'}
                  disabled={format === 'pdf'}
                  onCheckedChange={(v) => setInstant(v === true)}
                />
                <Label htmlFor="p3-rep-instant" className="text-xs text-stone-600">
                  {t('reports.instantLabel')}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-xs text-stone-600" htmlFor="p3-rep-repeat">
                  {t('reports.schedTitle')}
                </Label>
                <Select value={repeat} onValueChange={(v) => setRepeat(v as 'none' | 'weekly' | 'monthly')}>
                  <SelectTrigger id="p3-rep-repeat" className="h-8 w-36 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('reports.schedNone')}</SelectItem>
                    <SelectItem value="weekly">{t('reports.schedWeekly')}</SelectItem>
                    <SelectItem value="monthly">{t('reports.schedMonthly')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              disabled={createM.isPending}
              onClick={() => createM.mutate()}
            >
              {createM.isPending ? t('common.loading') : t('reports.generate')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Library */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('reports.libTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('reports.libDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {listQuery.isLoading ? (
            <Skeleton className="h-48 w-full" />
          ) : listQuery.isError ? (
            <InlineError error={listQuery.error} />
          ) : rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-stone-500">{t('reports.empty')}</p>
          ) : (
            <>
              <div className="hidden overflow-x-auto md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('reports.colType')}</TableHead>
                      <TableHead>{t('reports.colFormat')}</TableHead>
                      <TableHead>{t('reports.colScope')}</TableHead>
                      <TableHead>{t('reports.colStatus')}</TableHead>
                      <TableHead>{t('reports.colCreated')}</TableHead>
                      <TableHead>{t('reports.colSize')}</TableHead>
                      <TableHead className="text-end">{t('reports.colActions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((job) => (
                      <ReportRow
                        key={job.id}
                        t={t}
                        tP07={tP07}
                        farmName={
                          job.farm_id
                            ? farmsQuery.data?.items.find((f) => f.id === job.farm_id)?.name ?? null
                            : null
                        }
                        job={job}
                        busy={
                          downloadM.isPending ||
                          regenM.isPending ||
                          deleteM.isPending ||
                          schedM.isPending ||
                          (downloadJob?.id === job.id)
                        }
                        onDownload={() => downloadM.mutate(job)}
                        onRegen={() => regenM.mutate(job)}
                        onSchedule={() => {
                          setSchedJob(job)
                          setSchedValue(job.interval_days === 7 ? 'weekly' : job.interval_days === 30 ? 'monthly' : 'none')
                        }}
                        onDelete={() => setDeleteJob(job)}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="space-y-2 md:hidden">
                {rows.map((job) => (
                  <ReportCardMobile
                    key={job.id}
                    t={t}
                    tP07={tP07}
                    job={job}
                    farmName={
                      job.farm_id ? farmsQuery.data?.items.find((f) => f.id === job.farm_id)?.name ?? null : null
                    }
                    busy={downloadM.isPending || regenM.isPending || deleteM.isPending || schedM.isPending}
                    onDownload={() => downloadM.mutate(job)}
                    onRegen={() => regenM.mutate(job)}
                    onSchedule={() => {
                      setSchedJob(job)
                      setSchedValue(job.interval_days === 7 ? 'weekly' : job.interval_days === 30 ? 'monthly' : 'none')
                    }}
                    onDelete={() => setDeleteJob(job)}
                  />
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Delete confirmation */}
      <AlertDialog open={deleteJob !== null} onOpenChange={(open) => !open && setDeleteJob(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('reports.delDialogTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('reports.delDialogBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-700 text-white hover:bg-red-800"
              onClick={(e) => {
                e.preventDefault()
                if (deleteJob) deleteM.mutate(deleteJob)
              }}
            >
              {t('reports.del')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Schedule dialog */}
      <Dialog open={schedJob !== null} onOpenChange={(open) => !open && setSchedJob(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('reports.schedTitle')}</DialogTitle>
            <DialogDescription>{t('reports.schedDesc')}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p3-rep-sched-interval">
              {t('reports.schedTitle')}
            </Label>
            <Select
              value={schedValue}
              onValueChange={(v) => setSchedValue(v as 'none' | 'weekly' | 'monthly')}
            >
              <SelectTrigger id="p3-rep-sched-interval" className="h-9 bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('reports.schedNone')}</SelectItem>
                <SelectItem value="weekly">{t('reports.schedWeekly')}</SelectItem>
                <SelectItem value="monthly">{t('reports.schedMonthly')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSchedJob(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="bg-emerald-700 text-white hover:bg-emerald-800"
              disabled={schedM.isPending}
              onClick={() => {
                if (!schedJob) return
                schedM.mutate({
                  jobId: schedJob.id,
                  interval: schedValue === 'none' ? null : schedValue === 'weekly' ? 7 : 30,
                })
              }}
            >
              {t('reports.schedule')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --------------------------------------------------------------- row pieces

interface RowActions {
  onDownload: () => void
  onRegen: () => void
  onSchedule: () => void
  onDelete: () => void
  busy: boolean
  t: T
  tP07: T
}

function ActionButtons({
  job,
  onDownload,
  onRegen,
  onSchedule,
  onDelete,
  busy,
  t,
}: Omit<RowActions, 'tP07'> & { job: ReportJob }) {
  return (
    <div className="flex items-center justify-end gap-1">
      {job.status === 'succeeded' ? (
        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 text-stone-600 hover:text-emerald-800"
          disabled={busy}
          onClick={onDownload}
          aria-label={t('reports.download')}
          title={t('reports.download')}
        >
          <Download className="h-4 w-4" aria-hidden />
        </Button>
      ) : null}
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8 text-stone-600 hover:text-emerald-800"
        disabled={busy}
        onClick={onRegen}
        aria-label={t('reports.regen')}
        title={t('reports.regen')}
      >
        <RefreshCw className="h-4 w-4" aria-hidden />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8 text-stone-600 hover:text-emerald-800"
        disabled={busy}
        onClick={onSchedule}
        aria-label={t('reports.schedule')}
        title={t('reports.schedule')}
      >
        <Repeat className="h-4 w-4" aria-hidden />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8 text-stone-600 hover:text-red-700"
        disabled={busy}
        onClick={onDelete}
        aria-label={t('reports.del')}
        title={t('reports.del')}
      >
        <Trash2 className="h-4 w-4" aria-hidden />
      </Button>
    </div>
  )
}

function ReportRow({
  t,
  tP07,
  job,
  farmName,
  ...actions
}: RowActions & { job: ReportJob; farmName: string | null }) {
  return (
    <TableRow>
      <TableCell className="text-sm">
        <span className="font-medium text-stone-900">{reportTypeLabel(t, tP07, job.report_type)}</span>
        {job.interval_days ? (
          <span className="ms-2 inline-flex items-center gap-1 text-[11px] text-stone-400">
            <Repeat className="h-3 w-3" aria-hidden />
            {t('reports.repeatEvery', { days: job.interval_days })}
          </span>
        ) : null}
        {job.next_run_at ? (
          <span className="ms-2 text-[11px] text-stone-400">
            {t('reports.nextRun', { date: formatDay(job.next_run_at) })}
          </span>
        ) : null}
      </TableCell>
      <TableCell>
        <span className="inline-flex items-center gap-1.5 text-xs uppercase text-stone-600">
          <FileText className="h-3.5 w-3.5" aria-hidden />
          {job.output_format}
        </span>
      </TableCell>
      <TableCell className="text-xs text-stone-600">
        {farmName ?? (job.farm_id ? job.farm_id.slice(0, 8) + '…' : '—')}
      </TableCell>
      <TableCell>
        <span className="inline-flex items-center gap-1.5">
          {statusBadge(t, job.status)}
          {job.status === 'failed' && job.error ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className="cursor-help text-[11px] font-medium text-red-700 underline decoration-dotted"
                  aria-label={t('reports.errorLabel')}
                >
                  {t('reports.errorLabel')}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-80">
                <p className="break-words">{job.error}</p>
              </TooltipContent>
            </Tooltip>
          ) : null}
        </span>
      </TableCell>
      <TableCell className="text-xs text-stone-600">{formatDateTime(job.created_at)}</TableCell>
      <TableCell className="text-xs tabular-nums text-stone-600">{formatSize(job.file_size_bytes)}</TableCell>
      <TableCell>
        <ActionButtons job={job} {...actions} t={t} />
      </TableCell>
    </TableRow>
  )
}

function ReportCardMobile({
  t,
  tP07,
  job,
  farmName,
  onDownload,
  onRegen,
  onSchedule,
  onDelete,
  busy,
}: RowActions & { job: ReportJob; farmName: string | null }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-stone-900">{reportTypeLabel(t, tP07, job.report_type)}</span>
        {statusBadge(t, job.status)}
      </div>
      <p className="mt-1 text-xs text-stone-600">
        {job.output_format.toUpperCase()} · {farmName ?? '—'} · {formatSize(job.file_size_bytes)}
      </p>
      <p className="text-xs text-stone-500">{formatDateTime(job.created_at)}</p>
      {job.status === 'failed' && job.error ? (
        <p className="mt-1 break-words rounded bg-red-50 p-1.5 text-[11px] text-red-700">{job.error}</p>
      ) : null}
      {job.interval_days ? (
        <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-stone-400">
          <Repeat className="h-3 w-3" aria-hidden />
          {t('reports.repeatEvery', { days: job.interval_days })}
        </p>
      ) : null}
      <div className="mt-2 flex justify-end">
        <ActionButtons
          job={job}
          onDownload={onDownload}
          onRegen={onRegen}
          onSchedule={onSchedule}
          onDelete={onDelete}
          busy={busy}
          t={t}
        />
      </div>
    </div>
  )
}

'use client'

import { useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  BarChart3,
  CalendarRange,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  FlaskConical,
  Globe2,
  Layers,
  Loader2,
  RefreshCw,
  Upload,
  XCircle,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useTranslations } from 'next-intl'
import { ExportButton } from '@/components/croptwist/export-button'
import { FieldPicker, GoToFarmsButton } from '@/components/croptwist/field-picker'
import { JobStatusBadge, QualityBadge, SyntheticBadge } from '@/components/croptwist/badges'
import { useCatalog, useDataCoverage, useObservations, useProvidersHealth } from '@/hooks/use-croptwist'
import {
  COVERAGE_END,
  COVERAGE_START,
  createDataJob,
  CSV_TEMPLATE_URL,
  describeError,
  extractChirps,
  importObservationsCsv,
  MAX_JOB_YEARS,
  pollJobUntilDone,
  validateJobWindow,
} from '@/lib/api'
import { humanizeCode } from '@/lib/format'
import { useCropTwistUi } from '@/lib/store'
import type { DataJob, Observation, ProviderHealth, SyntheticProfile } from '@/lib/types'

const PROFILES: SyntheticProfile[] = [
  'temperate_seasonal',
  'mediterranean_dry_summer',
  'semi_arid',
  'tropical_seasonal',
  'arid_irrigated',
]

const DEFAULT_START = '2023-01-01'
const DEFAULT_END = '2023-12-31'

/** Providers that run fetch-style ingestion jobs (the others are upload flows). */
const JOB_PROVIDERS = ['synthetic', 'open_meteo'] as const
type JobProviderCode = (typeof JOB_PROVIDERS)[number]

function ChartCard({
  title,
  unit,
  note,
  children,
}: {
  title: string
  unit: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-1">
        <CardTitle className="text-sm font-medium text-stone-800">
          {title} <span className="font-normal text-stone-500">({unit})</span>
        </CardTitle>
        {note ? <CardDescription className="text-xs">{note}</CardDescription> : null}
      </CardHeader>
      <CardContent className="pt-0">{children}</CardContent>
    </Card>
  )
}

function ProviderStatusDot({ provider }: { provider: ProviderHealth }) {
  const t = useTranslations('observations')
  const probe = provider.probe?.status
  let dotClass = 'bg-emerald-600'
  let label = t('statusAvailable')
  if (provider.status === 'optional' || provider.status === 'degraded') {
    dotClass = 'bg-amber-500'
    label = provider.status
  }
  if (probe === 'unreachable') {
    dotClass = 'bg-red-500'
    label = t('probeUnreachable')
  } else if (probe === 'degraded') {
    dotClass = 'bg-amber-500'
    label = t('probeDegraded')
  } else if (probe === 'ok') {
    dotClass = 'bg-emerald-600'
    label = t('probeLive', { ms: provider.probe?.latency_ms ?? '?' })
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-stone-500">
      <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} aria-hidden />
      {label}
    </span>
  )
}

/** Provenance label for non-synthetic rows, derived from observation metadata. */
function ExternalProvenanceBadge({ observation }: { observation: Observation }) {
  const t = useTranslations('observations')
  const meta = observation.metadata as Record<string, unknown> | null
  let label = t('provExternal')
  if (meta && typeof meta === 'object') {
    if (meta.import_kind === 'observations_csv') label = t('provCsvImport')
    else if (meta.import_kind === 'chirps_geotiff_extract') label = t('provChirpsRaster')
    else if (typeof meta.model === 'string') label = t('provReanalysis', { model: meta.model })
  }
  return (
    <Badge variant="outline" className="border-stone-300 text-[10px] text-stone-500">
      {label}
    </Badge>
  )
}

function JobFooter({ job }: { job: DataJob }) {
  const t = useTranslations('observations')
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <JobStatusBadge status={job.status} />
        <span className="text-xs text-stone-500">
          {t('jobLine', { id: job.job_id.slice(0, 8), provider: job.provider_code })}
        </span>
      </div>
      <div className="flex gap-4 text-sm text-stone-700">
        <span>
          {t('recordsReceived')} <strong className="tabular-nums">{job.records_received}</strong>
        </span>
        <span>
          {t('recordsRejected')} <strong className="tabular-nums">{job.records_rejected}</strong>
        </span>
      </div>
      {job.error_summary ? (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>{t('jobError')}</AlertTitle>
          <AlertDescription>{job.error_summary}</AlertDescription>
        </Alert>
      ) : null}
      {job.warnings.length > 0 ? (
        <Alert className="border-amber-300 bg-amber-50 [&>svg]:text-amber-600">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle className="text-amber-900">{t('jobWarnings')}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4 text-xs text-amber-900">
              {job.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      <p className="text-[11px] text-stone-500">{t('requestLabel', { params: JSON.stringify(job.request_parameters) })}</p>
    </div>
  )
}

export function Observations() {
  const t = useTranslations('observations')
  const tCommon = useTranslations('common')
  const tNav = useTranslations('nav')
  const queryClient = useQueryClient()
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)

  const catalog = useCatalog()
  const providersHealth = useProvidersHealth()

  // ---- provider / ingestion form state (job + errors remember their field) ----
  const [provider, setProvider] = useState<JobProviderCode>('synthetic')
  const [model, setModel] = useState('era5_land')
  const [selectedVariables, setSelectedVariables] = useState<string[]>(['precipitation'])
  const [profile, setProfile] = useState<SyntheticProfile>('mediterranean_dry_summer')
  const [seed, setSeed] = useState(42)
  const [jobStart, setJobStart] = useState(DEFAULT_START)
  const [jobEnd, setJobEnd] = useState(DEFAULT_END)
  const [formError, setFormError] = useState<{ fieldId: string; message: string } | null>(null)
  const [job, setJob] = useState<{ fieldId: string; data: DataJob } | null>(null)

  // ---- file import state ----
  const csvInputRef = useRef<HTMLInputElement>(null)
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [csvJob, setCsvJob] = useState<{ fieldId: string; data: DataJob } | null>(null)
  const chirpsInputRef = useRef<HTMLInputElement>(null)
  const [chirpsFile, setChirpsFile] = useState<File | null>(null)
  const [chirpsDate, setChirpsDate] = useState('2024-01-31')
  const [chirpsKind, setChirpsKind] = useState<'daily' | 'pentad' | 'monthly'>('daily')
  const [chirpsStatus, setChirpsStatus] = useState<'preliminary' | 'final'>('final')
  const [chirpsJob, setChirpsJob] = useState<{ fieldId: string; data: DataJob } | null>(null)

  // ---- loaded observation window ----
  const [windowStart, setWindowStart] = useState(DEFAULT_START)
  const [windowEnd, setWindowEnd] = useState(DEFAULT_END)
  const [appliedWindow, setAppliedWindow] = useState({ start: DEFAULT_START, end: DEFAULT_END })
  const [tableVariable, setTableVariable] = useState<string>('all')

  const observationsQuery = useObservations(
    selectedField?.id ?? null,
    appliedWindow.start,
    appliedWindow.end,
    Boolean(selectedField),
  )
  const coverageQuery = useDataCoverage(selectedField?.id ?? null, Boolean(selectedField))
  const items = useMemo(() => observationsQuery.data?.items ?? [], [observationsQuery.data])

  const visibleJob = job && selectedField && job.fieldId === selectedField.id ? job.data : null
  const visibleFormError =
    formError && selectedField && formError.fieldId === selectedField.id ? formError.message : null
  const visibleCsvJob = csvJob && selectedField && csvJob.fieldId === selectedField.id ? csvJob.data : null
  const visibleChirpsJob =
    chirpsJob && selectedField && chirpsJob.fieldId === selectedField.id ? chirpsJob.data : null

  const syntheticProvider = providersHealth.data?.providers.find((p) => p.provider_code === 'synthetic')
  const openMeteoProvider = providersHealth.data?.providers.find((p) => p.provider_code === 'open_meteo')
  const chirpsProvider = providersHealth.data?.providers.find((p) => p.provider_code === 'chirps_import')

  const activeProvider = provider === 'synthetic' ? syntheticProvider : openMeteoProvider
  const models = openMeteoProvider?.details.models ?? []
  const activeModel = models.find((m) => m.code === model)

  /** Variables available for the current provider (+ model for open_meteo). */
  const selectableVariables = useMemo(() => {
    const all = catalog.data?.variables ?? []
    if (provider === 'open_meteo') {
      const modelVars = new Set(activeModel?.variables ?? [])
      return all.filter((v) => modelVars.has(v.code))
    }
    const syntheticVars = new Set(syntheticProvider?.details.supported_variables ?? [])
    if (syntheticVars.size === 0) return all
    return all.filter((v) => syntheticVars.has(v.code))
  }, [catalog.data, provider, activeModel, syntheticProvider])

  // Keep the effective selection inside the currently selectable set; default to
  // precipitation, else the first selectable variable. Derived (not synced) so
  // provider/model switches never wedge.
  const effectiveSelectedVariables = useMemo(() => {
    const codes = new Set(selectableVariables.map((v) => v.code))
    const kept = selectedVariables.filter((code) => codes.has(code))
    if (kept.length > 0) return kept
    if (codes.has('precipitation')) return ['precipitation']
    return selectableVariables.length > 0 ? [selectableVariables[0].code] : []
  }, [selectableVariables, selectedVariables])

  const invalidateFieldData = (fieldId: string) => {
    queryClient.invalidateQueries({ queryKey: ['observations', fieldId] })
    queryClient.invalidateQueries({ queryKey: ['data-passport', fieldId] })
    queryClient.invalidateQueries({ queryKey: ['data-coverage', fieldId] })
    queryClient.invalidateQueries({ queryKey: ['fields'] })
  }

  const variableName = (code: string) =>
    catalog.data?.variables.find((v) => v.code === code)?.name ?? humanizeCode(code)

  const ingestMutation = useMutation({
    mutationFn: (fieldId: string) =>
      createDataJob(fieldId, {
        provider_code: provider,
        variables: effectiveSelectedVariables,
        start_date: jobStart,
        end_date: jobEnd,
        ...(provider === 'synthetic' ? { profile, seed } : { model }),
      }),
    onSuccess: async (jobResult) => {
      if (!selectedField) return
      setJob({ fieldId: selectedField.id, data: jobResult })
      // Backend executes on a background worker pool: 202 responses come back
      // 'queued' — poll the status URL until terminal before reporting.
      const finalJob =
        jobResult.status === 'succeeded' || jobResult.status === 'failed'
          ? jobResult
          : await pollJobUntilDone(jobResult.job_id, {
              onProgress: (snapshot) => {
                setJob({ fieldId: selectedField.id, data: snapshot })
              },
            })
      setJob({ fieldId: selectedField.id, data: finalJob })
      if (finalJob.status === 'succeeded') {
        toast.success(t('jobSucceeded'), {
          description: t('jobSucceededDesc', {
            received: finalJob.records_received,
            rejected: finalJob.records_rejected,
          }),
        })
        const params = finalJob.request_parameters as { start_date?: string; end_date?: string }
        const start = params.start_date ?? jobStart
        const end = params.end_date ?? jobEnd
        setWindowStart(start)
        setWindowEnd(end)
        setAppliedWindow({ start, end })
        if (selectedField) {
          invalidateFieldData(selectedField.id)
        }
      } else {
        toast.error(t('jobFailed'), { description: finalJob.error_summary ?? t('noErrorSummary') })
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      if (selectedField) setFormError({ fieldId: selectedField.id, message: title })
      toast.error(title, { description })
    },
  })

  const csvImportMutation = useMutation({
    mutationFn: (fieldId: string) => importObservationsCsv(fieldId, csvFile as File),
    onSuccess: async (jobResult) => {
      if (!selectedField) return
      setCsvJob({ fieldId: selectedField.id, data: jobResult })
      const finalJob =
        jobResult.status === 'succeeded' || jobResult.status === 'failed'
          ? jobResult
          : await pollJobUntilDone(jobResult.job_id)
      setCsvJob({ fieldId: selectedField.id, data: finalJob })
      if (finalJob.status === 'succeeded') {
        toast.success('CSV import finished', {
          description: `${finalJob.records_received} rows read · ${finalJob.records_rejected} rejected.`,
        })
        invalidateFieldData(selectedField.id)
        setCsvFile(null)
        if (csvInputRef.current) csvInputRef.current.value = ''
      } else {
        toast.error('CSV import failed', { description: finalJob.error_summary ?? undefined })
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const chirpsMutation = useMutation({
    mutationFn: (fieldId: string) =>
      extractChirps(fieldId, chirpsFile as File, {
        observedAt: chirpsDate,
        periodKind: chirpsKind,
        productStatus: chirpsStatus,
      }),
    onSuccess: async (jobResult) => {
      if (!selectedField) return
      setChirpsJob({ fieldId: selectedField.id, data: jobResult })
      const finalJob =
        jobResult.status === 'succeeded' || jobResult.status === 'failed'
          ? jobResult
          : await pollJobUntilDone(jobResult.job_id)
      setChirpsJob({ fieldId: selectedField.id, data: finalJob })
      if (finalJob.status === 'succeeded') {
        toast.success('CHIRPS extraction finished', {
          description: `${finalJob.records_received} observation(s) extracted from the raster.`,
        })
        invalidateFieldData(selectedField.id)
        setChirpsFile(null)
        if (chirpsInputRef.current) chirpsInputRef.current.value = ''
      } else {
        toast.error('CHIRPS extraction failed', { description: finalJob.error_summary ?? undefined })
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submitJob = () => {
    setFormError(null)
    if (!selectedField) return
    if (effectiveSelectedVariables.length === 0) {
      setFormError({ fieldId: selectedField.id, message: t('pickVariable') })
      return
    }
    const windowProblem =
      provider === 'open_meteo'
        ? validateJobWindow(jobStart, jobEnd, {
            min: '1940-01-01',
            max: new Date(Date.now() - 6 * 86_400_000).toISOString().slice(0, 10),
            maxYears: 10,
          })
        : validateJobWindow(jobStart, jobEnd)
    if (windowProblem) {
      setFormError({ fieldId: selectedField.id, message: windowProblem })
      return
    }
    ingestMutation.mutate(selectedField.id)
  }

  const loadWindow = () => {
    const problem = validateJobWindow(windowStart, windowEnd)
    if (problem) {
      toast.error(problem)
      return
    }
    setAppliedWindow({ start: windowStart, end: windowEnd })
  }

  // ---- derived table data ----
  const presentVariables = useMemo(
    () => Array.from(new Set(items.map((item) => item.variable_code))).sort(),
    [items],
  )
  // If the selected filter variable is not present in the loaded window, fall back to "all".
  const effectiveTableVariable =
    tableVariable !== 'all' && !presentVariables.includes(tableVariable) ? 'all' : tableVariable
  const filteredItems = useMemo(
    () =>
      (effectiveTableVariable === 'all'
        ? items
        : items.filter((item) => item.variable_code === effectiveTableVariable)
      )
        .slice()
        .sort((a, b) => (a.observed_at < b.observed_at ? 1 : a.observed_at > b.observed_at ? -1 : 0)),
    [items, effectiveTableVariable],
  )
  // Flat rows for the CSV/JSON export of the observations table.
  const exportObservationRows = () =>
    filteredItems.map((o) => ({
      variable_code: o.variable_code,
      value: o.value,
      unit: o.unit,
      observed_at: o.observed_at,
      quality_status: o.quality_status,
      is_synthetic: o.is_synthetic,
      uncertainty_value: o.uncertainty_value,
    }))

  // Deepening F-17: charts must never silently blend synthetic fixtures with
  // real observations — each series carries a synthetic flag and the chart
  // states the mix explicitly.
  const tempSeries = useMemo(
    () =>
      items
        .filter((o) => o.variable_code === 'air_temperature_mean' && o.value !== null)
        .slice()
        .sort((a, b) => (a.observed_at < b.observed_at ? -1 : 1))
        .map((o) => ({ date: o.observed_at.slice(0, 10), value: o.value, synthetic: o.is_synthetic })),
    [items],
  )
  const precipSeries = useMemo(
    () =>
      items
        .filter((o) => o.variable_code === 'precipitation' && o.value !== null)
        .slice()
        .sort((a, b) => (a.observed_at < b.observed_at ? -1 : 1))
        .map((o) => ({ date: o.observed_at.slice(0, 10), value: o.value, synthetic: o.is_synthetic })),
    [items],
  )
  const chartProvenanceNote = (series: { synthetic: boolean }[]) => {
    if (series.length === 0) return undefined
    const nSynthetic = series.filter((p) => p.synthetic).length
    if (nSynthetic === 0) return undefined
    return nSynthetic === series.length
      ? t('provAllSynthetic')
      : t('provMixed', { synthetic: nSynthetic, total: series.length })
  }

  // ------------------------------------------------------------------ render

  if (!selectedField) {
    return (
      <div className="space-y-4" aria-label={t('sectionAria')}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-stone-900">{tNav('observations')}</h2>
            <p className="text-sm text-stone-500">{t('desc')}</p>
          </div>
          <FieldPicker
            value={null}
            onValueChange={setSelectedField}
            emptyHint={
              <div className="flex items-center gap-2 text-sm text-stone-500">
                <span>{t('createFirst')}</span>
                <GoToFarmsButton label={tCommon('goToFarms')} />
              </div>
            }
          />
        </div>
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <Database className="h-8 w-8 text-stone-400" aria-hidden />
            <p className="text-sm text-stone-500">{t('pickFieldHint')}</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6" aria-label={t('sectionAria')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">{tNav('observations')}</h2>
          <p className="text-sm text-stone-500">{t('desc')}</p>
        </div>
      </div>

      {catalog.isLoading ? <Skeleton className="h-4 w-64" /> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---------------- ingestion form ---------------- */}
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              {provider === 'synthetic' ? (
                <FlaskConical className="h-4 w-4 text-emerald-700" aria-hidden />
              ) : (
                <Globe2 className="h-4 w-4 text-emerald-700" aria-hidden />
              )}
              {t('ingestTitle')}
            </CardTitle>
            <CardDescription>
              {provider === 'synthetic'
                ? t('ingestDescSynthetic')
                : t('ingestDescOpenMeteo')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="obs-provider">{t('providerLabel')}</Label>
              <Select
                value={provider}
                onValueChange={(value) => {
                  setProvider(value as JobProviderCode)
                  setJob(null)
                  setFormError(null)
                  if (value === 'open_meteo' && !models.some((m) => m.code === model)) {
                    setModel(openMeteoProvider?.details.default_model ?? 'era5_land')
                  }
                }}
              >
                <SelectTrigger id="obs-provider" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {JOB_PROVIDERS.map((code) => {
                    const health =
                      code === 'synthetic'
                        ? syntheticProvider
                        : openMeteoProvider
                    return (
                      <SelectItem key={code} value={code}>
                        <span className="flex flex-col">
                          <span>{t(`provider.${code}`)}</span>
                          {health ? (
                            <span className="text-[11px] font-normal text-stone-500">
                              {health.kind} · {health.status}
                            </span>
                          ) : null}
                        </span>
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
              {activeProvider ? <ProviderStatusDot provider={activeProvider} /> : null}
            </div>

            {provider === 'open_meteo' ? (
              <div className="space-y-1.5">
                <Label htmlFor="obs-model">{t('modelLabel')}</Label>
                <Select value={model} onValueChange={setModel}>
                  <SelectTrigger id="obs-model" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {models.map((m) => (
                      <SelectItem key={m.code} value={m.code}>
                        <span className="flex flex-col">
                          <span>{t('modelGrid', { code: m.code, km: Math.round(m.spatial_resolution_m / 1000) })}</span>
                          <span className="max-w-72 truncate text-[11px] font-normal text-stone-500">
                            {m.description}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-stone-500">
                  {activeModel
                    ? t('publishes', { variables: activeModel.variables.map((v) => humanizeCode(v)).join(', ') })
                    : t('pickModelHint')}
                </p>
              </div>
            ) : null}

            <div className="space-y-1.5">
              <Label>{t('variablesLabel')}</Label>
              {catalog.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-3/4" />
                </div>
              ) : catalog.isError ? (
                <p className="text-sm text-red-700">{t('catalogError')}</p>
              ) : (
                <div className="grid gap-2 rounded-lg border border-stone-200 p-3 sm:grid-cols-2">
                  {selectableVariables.map((variable) => {
                    const checked = effectiveSelectedVariables.includes(variable.code)
                    return (
                      <label
                        key={variable.code}
                        className="flex cursor-pointer items-start gap-2 text-sm text-stone-700"
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(value) => {
                            setSelectedVariables((previous) =>
                              value
                                ? [...previous, variable.code]
                                : previous.filter((code) => code !== variable.code),
                            )
                          }}
                          aria-label={`${variable.name} (${variable.code})`}
                        />
                        <span className="leading-tight">
                          {variable.name}
                          <span className="block text-[11px] text-stone-500">
                            {variable.code} · {variable.unit}
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              )}
              {selectableVariables.length === 0 && !catalog.isLoading ? (
                <p className="text-xs text-stone-500">{t('noCatalogVars')}</p>
              ) : null}
            </div>

            {provider === 'synthetic' ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="obs-profile">{t('profileLabel')}</Label>
                  <Select value={profile} onValueChange={(value) => setProfile(value as SyntheticProfile)}>
                    <SelectTrigger id="obs-profile" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROFILES.map((entry) => (
                        <SelectItem key={entry} value={entry}>
                          {t(`profile.${entry}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-stone-500">{t('profileHint')}</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="obs-seed">{t('seedLabel')}</Label>
                  <Input
                    id="obs-seed"
                    type="number"
                    min={0}
                    value={seed}
                    onChange={(event) => setSeed(Number(event.target.value) || 0)}
                  />
                  <p className="text-xs text-stone-500">{t('seedHint')}</p>
                </div>
              </div>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="obs-start">{t('startDate')}</Label>
                <Input
                  id="obs-start"
                  type="date"
                  value={jobStart}
                  onChange={(event) => setJobStart(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="obs-end">{t('endDate')}</Label>
                <Input
                  id="obs-end"
                  type="date"
                  value={jobEnd}
                  onChange={(event) => setJobEnd(event.target.value)}
                />
              </div>
            </div>
            <p className="-mt-2 text-xs text-stone-500">
              {provider === 'synthetic'
                ? t('fixtureCoverage', { start: COVERAGE_START, end: COVERAGE_END, years: MAX_JOB_YEARS })
                : t('archiveCoverage')}
            </p>

            {formError ? (
              <p className="text-sm font-medium text-red-700" role="alert">
                {visibleFormError}
              </p>
            ) : null}

            <Button
              className="w-full bg-emerald-700 hover:bg-emerald-800 sm:w-auto"
              onClick={submitJob}
              disabled={ingestMutation.isPending}
            >
              {ingestMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Database className="h-4 w-4" aria-hidden />
              )}
              {t('runJob')}
            </Button>
          </CardContent>

          {visibleJob ? (
            <CardFooter className="block border-t border-stone-100 pt-4">
              <JobFooter job={visibleJob} />
            </CardFooter>
          ) : null}
        </Card>

        {/* ---------------- window + charts ---------------- */}
        <div className="space-y-4">
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <CalendarRange className="h-4 w-4 text-emerald-700" aria-hidden />
                {t('loadedWindowTitle')}
              </CardTitle>
              <CardDescription>
                {observationsQuery.data
                  ? t.rich('showingFor', {
                      shown: observationsQuery.data.items.length,
                      total: observationsQuery.data.total,
                      field: selectedField.name,
                      strong: (chunks) => <strong className="font-medium text-stone-700">{chunks}</strong>,
                    })
                  : t.rich('showingForLoading', {
                      field: selectedField.name,
                      strong: (chunks) => <strong className="font-medium text-stone-700">{chunks}</strong>,
                    })}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="window-start">{t('fromLabel')}</Label>
                <Input
                  id="window-start"
                  type="date"
                  value={windowStart}
                  onChange={(event) => setWindowStart(event.target.value)}
                />
              </div>
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="window-end">{t('toLabel')}</Label>
                <Input
                  id="window-end"
                  type="date"
                  value={windowEnd}
                  onChange={(event) => setWindowEnd(event.target.value)}
                />
              </div>
              <Button variant="outline" className="border-stone-300" onClick={loadWindow} disabled={observationsQuery.isFetching}>
                {observationsQuery.isFetching ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="h-4 w-4" aria-hidden />
                )}
                {t('load')}
              </Button>
            </CardContent>
          </Card>

          {observationsQuery.isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <Skeleton className="h-56 rounded-lg" />
              <Skeleton className="h-56 rounded-lg" />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <ChartCard
                title={t('chartTempTitle')}
                unit="°C"
                note={
                  tempSeries.length === 0
                    ? t('noTempData')
                    : chartProvenanceNote(tempSeries)
                }
              >
                {tempSeries.length > 0 ? (
                  <ResponsiveContainer width="100%" height={190}>
                    <LineChart data={tempSeries} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="#e7e5e4" strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} minTickGap={36} />
                      <YAxis tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
                      <ReTooltip labelFormatter={(label) => t('tooltipDate', { label })} />
                      <Line type="monotone" dataKey="value" stroke="#047857" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[190px] items-center justify-center rounded-md border border-dashed border-stone-200 text-xs text-stone-500">
                    {t('ingestToSeeTemp')}
                  </div>
                )}
              </ChartCard>
              <ChartCard
                title={t('chartPrecipTitle')}
                unit="mm"
                note={
                  precipSeries.length === 0
                    ? t('noPrecipData')
                    : chartProvenanceNote(precipSeries)
                }
              >
                {precipSeries.length > 0 ? (
                  <ResponsiveContainer width="100%" height={190}>
                    <BarChart data={precipSeries} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="#e7e5e4" strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} minTickGap={36} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <ReTooltip labelFormatter={(label) => t('tooltipDate', { label })} />
                      <Bar dataKey="value" fill="#78716c" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[190px] items-center justify-center rounded-md border border-dashed border-stone-200 text-xs text-stone-500">
                    {t('ingestToSeePrecip')}
                  </div>
                )}
              </ChartCard>
            </div>
          )}
        </div>
      </div>

      {/* ---------------- file imports + coverage ---------------- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Upload className="h-4 w-4 text-emerald-700" aria-hidden />
              {t('fileImportsTitle')}
            </CardTitle>
            <CardDescription>
              {t('fileImportsDesc')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="csv">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="csv">
                  <FileSpreadsheet className="mr-1.5 inline h-3.5 w-3.5" aria-hidden /> {t('tabCsv')}
                </TabsTrigger>
                <TabsTrigger value="chirps">
                  <Layers className="mr-1.5 inline h-3.5 w-3.5" aria-hidden /> {t('tabChirps')}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="csv" className="mt-3 space-y-3">
                <p className="text-xs text-stone-500">
                  {t.rich('csvHelp', {
                    code: (chunks) => <code className="rounded bg-stone-100 px-1">{chunks}</code>,
                    strong: (chunks) => <strong>{chunks}</strong>,
                  })}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    ref={csvInputRef}
                    type="file"
                    accept=".csv,text/csv"
                    className="max-w-xs"
                    onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                    aria-label={t('csvFileAria')}
                  />
                  <a
                    href={CSV_TEMPLATE_URL}
                    className="text-xs font-medium text-emerald-700 underline-offset-2 hover:underline"
                    download
                  >
                    {t('downloadTemplate')}
                  </a>
                </div>
                <Button
                  className="bg-emerald-700 hover:bg-emerald-800"
                  disabled={!csvFile || csvImportMutation.isPending}
                  onClick={() => selectedField && csvImportMutation.mutate(selectedField.id)}
                >
                  {csvImportMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Upload className="h-4 w-4" aria-hidden />
                  )}
                  {t('importCsv')}
                </Button>
                {visibleCsvJob ? (
                  <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
                    <JobFooter job={visibleCsvJob} />
                  </div>
                ) : null}
              </TabsContent>

              <TabsContent value="chirps" className="mt-3 space-y-3">
                <p className="text-xs text-stone-500">
                  {t('chirpsHelp')}
                  {chirpsProvider && chirpsProvider.status !== 'active' ? (
                    <span className="mt-1 block font-medium text-amber-700">
                      {t('providerDegraded', {
                        reason: String(chirpsProvider.details.degradation_reason ?? 'unavailable'),
                      })}
                    </span>
                  ) : null}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    ref={chirpsInputRef}
                    type="file"
                    accept=".tif,.tiff,application/x-geotiff,image/tiff"
                    className="max-w-xs"
                    onChange={(event) => setChirpsFile(event.target.files?.[0] ?? null)}
                    aria-label={t('chirpsFileAria')}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="chirps-date">{t('rasterDate')}</Label>
                    <Input
                      id="chirps-date"
                      type="date"
                      value={chirpsDate}
                      onChange={(event) => setChirpsDate(event.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="chirps-kind">{t('productKind')}</Label>
                    <Select value={chirpsKind} onValueChange={(value) => setChirpsKind(value as typeof chirpsKind)}>
                      <SelectTrigger id="chirps-kind" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="daily">{t('kindDaily')}</SelectItem>
                        <SelectItem value="pentad">{t('kindPentad')}</SelectItem>
                        <SelectItem value="monthly">{t('kindMonthly')}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="chirps-status">{t('productStatus')}</Label>
                    <Select
                      value={chirpsStatus}
                      onValueChange={(value) => setChirpsStatus(value as typeof chirpsStatus)}
                    >
                      <SelectTrigger id="chirps-status" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="final">{t('statusFinal')}</SelectItem>
                        <SelectItem value="preliminary">{t('statusPreliminary')}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button
                  className="bg-emerald-700 hover:bg-emerald-800"
                  disabled={!chirpsFile || chirpsMutation.isPending}
                  onClick={() => selectedField && chirpsMutation.mutate(selectedField.id)}
                >
                  {chirpsMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Upload className="h-4 w-4" aria-hidden />
                  )}
                  {t('extractRainfall')}
                </Button>
                {visibleChirpsJob ? (
                  <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
                    <JobFooter job={visibleChirpsJob} />
                  </div>
                ) : null}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card className="border-stone-200 bg-white shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Layers className="h-4 w-4 text-emerald-700" aria-hidden />
              {t('coverageTitle')}
            </CardTitle>
            <CardDescription>
              {t.rich('coverageDesc', {
                field: selectedField.name,
                strong: (chunks) => <strong className="font-medium text-stone-700">{chunks}</strong>,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {coverageQuery.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-3/4" />
              </div>
            ) : coverageQuery.isError ? (
              <Alert variant="destructive">
                <XCircle className="h-4 w-4" />
                <AlertTitle>{t('coverageError')}</AlertTitle>
                <AlertDescription>{t('tryAgainShortly')}</AlertDescription>
              </Alert>
            ) : (coverageQuery.data?.variables.length ?? 0) === 0 ? (
              <div className="rounded-lg border border-dashed border-stone-300 p-6 text-center">
                <CheckCircle2 className="mx-auto h-6 w-6 text-stone-300" aria-hidden />
                <p className="mt-2 text-sm text-stone-600">{t('noObservationsYet')}</p>
              </div>
            ) : (
              <div className="max-h-80 overflow-y-auto rounded-md border scrollbar-thin">
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-white shadow-[0_1px_0_0_var(--color-stone-200)]">
                    <TableRow className="hover:bg-transparent">
                      <TableHead>{t('colVariable')}</TableHead>
                      <TableHead className="text-right">{t('colRows')}</TableHead>
                      <TableHead className="text-right">{t('colValid')}</TableHead>
                      <TableHead>{t('colPeriod')}</TableHead>
                      <TableHead>{t('colProviders')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(coverageQuery.data?.variables ?? []).map((entry) => (
                      <TableRow key={entry.variable_code}>
                        <TableCell>
                          <span className="font-medium text-stone-800">{variableName(entry.variable_code)}</span>
                          <span className="block text-[11px] text-stone-500">
                            {entry.variable_code} · {entry.unit}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{entry.total}</TableCell>
                        <TableCell className="text-right tabular-nums">{entry.valid}</TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-stone-600">
                          {entry.providers[0]?.first ?? '—'} → {entry.providers[0]?.last ?? '—'}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {entry.providers.map((p) => (
                              <Badge
                                key={`${entry.variable_code}-${p.provider_code}-${p.product_code}`}
                                variant="outline"
                                className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-900"
                              >
                                {p.provider_code}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ---------------- observations table ---------------- */}
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <BarChart3 className="h-4 w-4 text-emerald-700" aria-hidden />
                {t('tableTitle')}
              </CardTitle>
              <CardDescription>
                {t('windowRange', { start: appliedWindow.start, end: appliedWindow.end })}
                {observationsQuery.data && observationsQuery.data.total > observationsQuery.data.items.length
                  ? t('windowTruncated', {
                      shown: observationsQuery.data.items.length,
                      total: observationsQuery.data.total,
                    })
                  : ''}
              </CardDescription>
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <div className="w-full sm:w-56">
                <Select value={tableVariable} onValueChange={setTableVariable}>
                  <SelectTrigger aria-label={t('filterByVariable')} className="w-full bg-white">
                    <SelectValue placeholder={t('allVariables')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t('allVariables')}</SelectItem>
                    {presentVariables.map((code) => (
                      <SelectItem key={code} value={code}>
                        {variableName(code)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <ExportButton
                baseFilename="observations"
                getRows={exportObservationRows}
                columns={[
                  { key: 'observed_at', label: t('colDate') },
                  { key: 'variable_code', label: t('colVariable') },
                  { key: 'value', label: t('colValue') },
                  { key: 'unit', label: t('colUnit') },
                  { key: 'quality_status', label: t('colQuality') },
                  { key: 'uncertainty_value', label: t('colUncertainty') },
                  { key: 'is_synthetic', label: t('colProvenance') },
                ]}
                getJsonPayload={() => observationsQuery.data}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {observationsQuery.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-9 w-full" />
              ))}
            </div>
          ) : observationsQuery.isError ? (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
              <AlertDescription>
                {observationsQuery.error instanceof Error ? observationsQuery.error.message : t('tryLoadingAgain')}
              </AlertDescription>
            </Alert>
          ) : filteredItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-stone-300 p-6 text-center">
              <CheckCircle2 className="mx-auto h-6 w-6 text-stone-300" aria-hidden />
              <p className="mt-2 text-sm text-stone-600">
                {t('emptyWindow', { scope: tableVariable !== 'all' ? 'variable' : 'any' })}
              </p>
              <p className="mt-1 text-xs text-stone-500">{t('emptyWindowHint')}</p>
              <div className="mt-3 flex justify-center">
                <GoToFarmsButton label={t('manageFields')} />
              </div>
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto rounded-md border scrollbar-thin">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-white shadow-[0_1px_0_0_var(--color-stone-200)]">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-28">{t('colDate')}</TableHead>
                    <TableHead>{t('colVariable')}</TableHead>
                    <TableHead className="text-right">{t('colValue')}</TableHead>
                    <TableHead>{t('colQuality')}</TableHead>
                    <TableHead>{t('colProvenance')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((observation) => (
                    <TableRow key={observation.id}>
                      <TableCell className="whitespace-nowrap tabular-nums text-stone-600">
                        {observation.observed_at.slice(0, 10)}
                      </TableCell>
                      <TableCell>
                        <span className="font-medium text-stone-800">{variableName(observation.variable_code)}</span>
                        <span className="block text-[11px] text-stone-500">{observation.variable_code}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {observation.value === null ? (
                          <span className="text-stone-400">—</span>
                        ) : (
                          <>
                            {observation.value}
                            <span className="ml-1 text-xs text-stone-500">{observation.unit}</span>
                          </>
                        )}
                      </TableCell>
                      <TableCell>
                        <QualityBadge status={observation.quality_status} />
                      </TableCell>
                      <TableCell>
                        {observation.is_synthetic ? (
                          <SyntheticBadge />
                        ) : (
                          <ExternalProvenanceBadge observation={observation} />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default Observations

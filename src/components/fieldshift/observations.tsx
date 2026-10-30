'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  BarChart3,
  CalendarRange,
  CheckCircle2,
  Database,
  FlaskConical,
  Loader2,
  RefreshCw,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldPicker, GoToFarmsButton } from '@/components/fieldshift/field-picker'
import { JobStatusBadge, QualityBadge, SyntheticBadge } from '@/components/fieldshift/badges'
import { useCatalog, useObservations } from '@/hooks/use-fieldshift'
import { COVERAGE_END, COVERAGE_START, createDataJob, describeError, MAX_JOB_YEARS, validateJobWindow } from '@/lib/api'
import { humanizeCode } from '@/lib/format'
import { useFieldShiftUi } from '@/lib/store'
import type { DataJob, SyntheticProfile } from '@/lib/types'

const PROFILES: { value: SyntheticProfile; label: string }[] = [
  { value: 'temperate_seasonal', label: 'Temperate seasonal' },
  { value: 'mediterranean_dry_summer', label: 'Mediterranean — dry summer' },
  { value: 'semi_arid', label: 'Semi-arid' },
  { value: 'tropical_seasonal', label: 'Tropical seasonal' },
  { value: 'arid_irrigated', label: 'Arid — irrigated' },
]

const DEFAULT_START = '2023-01-01'
const DEFAULT_END = '2023-12-31'

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

export function Observations() {
  const queryClient = useQueryClient()
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)

  const catalog = useCatalog()

  // ---- ingestion form state (job + errors remember their field) ----
  const [selectedVariables, setSelectedVariables] = useState<string[]>(['precipitation'])
  const [profile, setProfile] = useState<SyntheticProfile>('mediterranean_dry_summer')
  const [seed, setSeed] = useState(42)
  const [jobStart, setJobStart] = useState(DEFAULT_START)
  const [jobEnd, setJobEnd] = useState(DEFAULT_END)
  const [formError, setFormError] = useState<{ fieldId: string; message: string } | null>(null)
  const [job, setJob] = useState<{ fieldId: string; data: DataJob } | null>(null)

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
  const items = useMemo(() => observationsQuery.data?.items ?? [], [observationsQuery.data])

  const visibleJob = job && selectedField && job.fieldId === selectedField.id ? job.data : null
  const visibleFormError =
    formError && selectedField && formError.fieldId === selectedField.id ? formError.message : null

  const variableName = (code: string) =>
    catalog.data?.variables.find((v) => v.code === code)?.name ?? humanizeCode(code)

  const ingestMutation = useMutation({
    mutationFn: (fieldId: string) =>
      createDataJob(fieldId, {
        provider_code: 'synthetic',
        variables: selectedVariables,
        start_date: jobStart,
        end_date: jobEnd,
        profile,
        seed,
      }),
    onSuccess: (jobResult) => {
      if (!selectedField) return
      setJob({ fieldId: selectedField.id, data: jobResult })
      if (jobResult.status === 'succeeded') {
        toast.success('Ingestion job succeeded', {
          description: `${jobResult.records_received} records stored · ${jobResult.records_rejected} rejected.`,
        })
        const params = jobResult.request_parameters as { start_date?: string; end_date?: string }
        const start = params.start_date ?? jobStart
        const end = params.end_date ?? jobEnd
        setWindowStart(start)
        setWindowEnd(end)
        setAppliedWindow({ start, end })
        if (selectedField) {
          queryClient.invalidateQueries({ queryKey: ['observations', selectedField.id] })
          queryClient.invalidateQueries({ queryKey: ['data-passport', selectedField.id] })
        }
        queryClient.invalidateQueries({ queryKey: ['fields'] })
      } else {
        toast.error('Ingestion job failed', { description: jobResult.error_summary ?? 'No error summary returned.' })
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      if (selectedField) setFormError({ fieldId: selectedField.id, message: title })
      toast.error(title, { description })
    },
  })

  const submitJob = () => {
    setFormError(null)
    if (!selectedField) return
    if (selectedVariables.length === 0) {
      setFormError({ fieldId: selectedField.id, message: 'Pick at least one variable to ingest.' })
      return
    }
    const windowProblem = validateJobWindow(jobStart, jobEnd)
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

  const tempSeries = useMemo(
    () =>
      items
        .filter((o) => o.variable_code === 'air_temperature_mean' && o.value !== null)
        .slice()
        .sort((a, b) => (a.observed_at < b.observed_at ? -1 : 1))
        .map((o) => ({ date: o.observed_at.slice(0, 10), value: o.value })),
    [items],
  )
  const precipSeries = useMemo(
    () =>
      items
        .filter((o) => o.variable_code === 'precipitation' && o.value !== null)
        .slice()
        .sort((a, b) => (a.observed_at < b.observed_at ? -1 : 1))
        .map((o) => ({ date: o.observed_at.slice(0, 10), value: o.value })),
    [items],
  )

  // ------------------------------------------------------------------ render

  if (!selectedField) {
    return (
      <div className="space-y-4" aria-label="Observations">
        <h2 className="text-lg font-semibold text-stone-900">Observations</h2>
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <Database className="h-8 w-8 text-stone-400" aria-hidden />
            <p className="text-sm text-stone-500">Pick a field above to ingest and inspect its observation history.</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6" aria-label="Observations">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">Observations</h2>
          <p className="text-sm text-stone-500">
            Run synthetic ingestion jobs, then browse and chart what landed.
          </p>
        </div>
        <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
      </div>

      {catalog.isLoading ? <Skeleton className="h-4 w-64" /> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---------------- ingestion form ---------------- */}
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <FlaskConical className="h-4 w-4 text-emerald-700" aria-hidden />
              Ingest data — synthetic provider
            </CardTitle>
            <CardDescription>
              The only provider in this slice is <code className="rounded bg-stone-100 px-1">synthetic</code>: software
              fixtures for testing, always labelled SYNTHETIC downstream.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>Provider</Label>
              <Input value="synthetic — software fixtures" disabled aria-readonly />
            </div>

            <div className="space-y-1.5">
              <Label>Variables</Label>
              {catalog.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-3/4" />
                </div>
              ) : catalog.isError ? (
                <p className="text-sm text-red-700">Could not load the data catalog.</p>
              ) : (
                <div className="grid gap-2 rounded-lg border border-stone-200 p-3 sm:grid-cols-2">
                  {(catalog.data?.variables ?? []).map((variable) => {
                    const checked = selectedVariables.includes(variable.code)
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
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="obs-profile">Climate profile</Label>
                <Select value={profile} onValueChange={(value) => setProfile(value as SyntheticProfile)}>
                  <SelectTrigger id="obs-profile" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROFILES.map((entry) => (
                      <SelectItem key={entry.value} value={entry.value}>
                        {entry.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-stone-500">Shapes the synthetic seasonality.</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="obs-seed">Seed</Label>
                <Input
                  id="obs-seed"
                  type="number"
                  min={0}
                  value={seed}
                  onChange={(event) => setSeed(Number(event.target.value) || 0)}
                />
                <p className="text-xs text-stone-500">Same seed + same inputs → identical series.</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="obs-start">Start date</Label>
                <Input
                  id="obs-start"
                  type="date"
                  min={COVERAGE_START}
                  max={COVERAGE_END}
                  value={jobStart}
                  onChange={(event) => setJobStart(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="obs-end">End date</Label>
                <Input
                  id="obs-end"
                  type="date"
                  min={COVERAGE_START}
                  max={COVERAGE_END}
                  value={jobEnd}
                  onChange={(event) => setJobEnd(event.target.value)}
                />
              </div>
            </div>
            <p className="-mt-2 text-xs text-stone-500">
              Dataset coverage {COVERAGE_START} → {COVERAGE_END}; one job spans at most {MAX_JOB_YEARS} years.
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
              Run ingestion job
            </Button>
          </CardContent>

          {visibleJob ? (
            <CardFooter className="block border-t border-stone-100 pt-4">
              <div className="space-y-2" aria-live="polite">
                <div className="flex flex-wrap items-center gap-2">
                  <JobStatusBadge status={visibleJob.status} />
                  <span className="text-xs text-stone-500">
                    job {visibleJob.job_id.slice(0, 8)} · {visibleJob.provider_code}
                  </span>
                </div>
                <div className="flex gap-4 text-sm text-stone-700">
                  <span>
                    Records received: <strong className="tabular-nums">{visibleJob.records_received}</strong>
                  </span>
                  <span>
                    Rejected: <strong className="tabular-nums">{visibleJob.records_rejected}</strong>
                  </span>
                </div>
                {visibleJob.error_summary ? (
                  <Alert variant="destructive">
                    <XCircle className="h-4 w-4" />
                    <AlertTitle>Job error</AlertTitle>
                    <AlertDescription>{visibleJob.error_summary}</AlertDescription>
                  </Alert>
                ) : null}
                {visibleJob.warnings.length > 0 ? (
                  <Alert className="border-amber-300 bg-amber-50 [&>svg]:text-amber-600">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle className="text-amber-900">Job warnings</AlertTitle>
                    <AlertDescription>
                      <ul className="list-disc space-y-1 pl-4 text-xs text-amber-900">
                        {visibleJob.warnings.map((warning, index) => (
                          <li key={index}>{warning}</li>
                        ))}
                      </ul>
                    </AlertDescription>
                  </Alert>
                ) : null}
                <p className="text-[11px] text-stone-500">
                  Request: {JSON.stringify(visibleJob.request_parameters)}
                </p>
              </div>
            </CardFooter>
          ) : null}
        </Card>

        {/* ---------------- window + charts ---------------- */}
        <div className="space-y-4">
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <CalendarRange className="h-4 w-4 text-emerald-700" aria-hidden />
                Loaded window
              </CardTitle>
              <CardDescription>
                Showing {observationsQuery.data ? `${observationsQuery.data.items.length} of ${observationsQuery.data.total}` : '…'}{' '}
                observations for <strong className="font-medium text-stone-700">{selectedField.name}</strong>.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="window-start">From</Label>
                <Input
                  id="window-start"
                  type="date"
                  min={COVERAGE_START}
                  max={COVERAGE_END}
                  value={windowStart}
                  onChange={(event) => setWindowStart(event.target.value)}
                />
              </div>
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="window-end">To</Label>
                <Input
                  id="window-end"
                  type="date"
                  min={COVERAGE_START}
                  max={COVERAGE_END}
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
                Load
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
                title="Air temperature (mean)"
                unit="°C"
                note={tempSeries.length === 0 ? 'No temperature_mean data in this window.' : undefined}
              >
                {tempSeries.length > 0 ? (
                  <ResponsiveContainer width="100%" height={190}>
                    <LineChart data={tempSeries} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="#e7e5e4" strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} minTickGap={36} />
                      <YAxis tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
                      <ReTooltip labelFormatter={(label) => `Date: ${label}`} />
                      <Line type="monotone" dataKey="value" stroke="#047857" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[190px] items-center justify-center rounded-md border border-dashed border-stone-200 text-xs text-stone-500">
                    Ingest air_temperature_mean to see the line chart.
                  </div>
                )}
              </ChartCard>
              <ChartCard
                title="Precipitation"
                unit="mm"
                note={precipSeries.length === 0 ? 'No precipitation data in this window.' : undefined}
              >
                {precipSeries.length > 0 ? (
                  <ResponsiveContainer width="100%" height={190}>
                    <BarChart data={precipSeries} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="#e7e5e4" strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} minTickGap={36} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <ReTooltip labelFormatter={(label) => `Date: ${label}`} />
                      <Bar dataKey="value" fill="#78716c" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-[190px] items-center justify-center rounded-md border border-dashed border-stone-200 text-xs text-stone-500">
                    Ingest precipitation to see the bar chart.
                  </div>
                )}
              </ChartCard>
            </div>
          )}
        </div>
      </div>

      {/* ---------------- observations table ---------------- */}
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <BarChart3 className="h-4 w-4 text-emerald-700" aria-hidden />
                Observations table
              </CardTitle>
              <CardDescription>
                Window {appliedWindow.start} → {appliedWindow.end}
                {observationsQuery.data && observationsQuery.data.total > observationsQuery.data.items.length
                  ? ` · showing the first ${observationsQuery.data.items.length} of ${observationsQuery.data.total} rows — narrow the window to see everything`
                  : ''}
              </CardDescription>
            </div>
            <div className="w-full sm:w-56">
              <Select value={tableVariable} onValueChange={setTableVariable}>
                <SelectTrigger aria-label="Filter by variable" className="w-full bg-white">
                  <SelectValue placeholder="All variables" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All variables</SelectItem>
                  {presentVariables.map((code) => (
                    <SelectItem key={code} value={code}>
                      {variableName(code)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              <AlertTitle>Could not load observations</AlertTitle>
              <AlertDescription>
                {observationsQuery.error instanceof Error ? observationsQuery.error.message : 'Try loading again.'}
              </AlertDescription>
            </Alert>
          ) : filteredItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-stone-300 p-6 text-center">
              <CheckCircle2 className="mx-auto h-6 w-6 text-stone-300" aria-hidden />
              <p className="mt-2 text-sm text-stone-600">
                No observations in this window{tableVariable !== 'all' ? ' for this variable' : ''} yet.
              </p>
              <p className="mt-1 text-xs text-stone-500">
                Run an ingestion job on the left, or widen the loaded window.
              </p>
              <div className="mt-3 flex justify-center">
                <GoToFarmsButton label="Manage fields" />
              </div>
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto rounded-md border scrollbar-thin">
              <Table>
                <TableHeader className="sticky top-0 z-10 bg-white shadow-[0_1px_0_0_var(--color-stone-200)]">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-28">Date</TableHead>
                    <TableHead>Variable</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                    <TableHead>Quality</TableHead>
                    <TableHead>Provenance</TableHead>
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
                          <Badge variant="outline" className="border-stone-300 text-[10px] text-stone-500">
                            external
                          </Badge>
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

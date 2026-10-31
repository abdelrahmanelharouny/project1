'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  ChevronRight,
  FlaskConical,
  GitCompareArrows,
  Info,
  Loader2,
  XCircle,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import { JobStatusBadge, QualityBadge, SyntheticBadge } from '@/components/fieldshift/badges'
import { useFeatureCatalog, useFeatureComparison, useFeatureRuns, useFeatureValues } from '@/hooks/use-fieldshift'
import { createFeatureRun, describeError } from '@/lib/api'
import { useFieldShiftUi, type SelectedField } from '@/lib/store'
import type { FeatureRun, FeatureValue } from '@/lib/types'
import { cn } from '@/lib/utils'

const AGGREGATION_LEVELS = [
  { value: 'monthly', label: 'Monthly', hint: 'Totals, means, indices, anomalies per calendar month' },
  { value: 'seasonal', label: 'Seasonal', hint: 'Meteorological seasons of the chosen hemisphere' },
  { value: 'crop_season', label: 'Crop seasons', hint: 'Explicit date windows you supply below' },
  { value: 'daily', label: 'Daily', hint: 'Per-day values — limited to ~3 years per run' },
] as const

const MAX_DAILY_DAYS = 1100

interface SeasonWindow {
  label: string
  start: string
  end: string
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function coveragePct(ratio: number | null): string {
  if (ratio === null || ratio === undefined) return '—'
  return `${Math.round(ratio * 100)}%`
}

function featureQualityTone(status: FeatureValue['quality_status']): string {
  switch (status) {
    case 'valid':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800'
    case 'partial':
      return 'border-amber-200 bg-amber-50 text-amber-900'
    case 'insufficient_coverage':
      return 'border-orange-200 bg-orange-50 text-orange-900'
    case 'missing':
      return 'border-stone-200 bg-stone-100 text-stone-600'
    default:
      return 'border-stone-300 bg-white text-stone-600'
  }
}

function CreateRunForm({
  selectedField,
  onCreated,
}: {
  selectedField: SelectedField
  onCreated: (run: FeatureRun) => void
}) {
  const [start, setStart] = useState('2023-01-01')
  const [end, setEnd] = useState('2023-12-31')
  const [levels, setLevels] = useState<string[]>(['monthly'])
  const [hemisphere, setHemisphere] = useState<'north' | 'south'>('north')
  const [seasons, setSeasons] = useState<SeasonWindow[]>([])
  const queryClient = useQueryClient()

  const toggleLevel = (level: string) => {
    setLevels((prev) => {
      const next = prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level]
      return next.length ? next : prev // never empty
    })
  }

  const validate = (): string | null => {
    const dateRe = /^\d{4}-\d{2}-\d{2}$/
    if (!dateRe.test(start) || !dateRe.test(end)) return 'Enter start and end as YYYY-MM-DD.'
    if (end < start) return 'The end date must be on or after the start date.'
    const years = (Date.parse(end) - Date.parse(start)) / (365.25 * 24 * 3600 * 1000)
    if (years > 31) return 'A run covers at most 31 years.'
    if (levels.includes('daily') && Date.parse(end) - Date.parse(start) > MAX_DAILY_DAYS * 86_400_000) {
      return 'Daily aggregation is limited to ~3 years per run — uncheck Daily or shorten the window.'
    }
    if (levels.includes('crop_season') && seasons.length === 0) {
      return 'Add at least one crop-season window or uncheck Crop seasons.'
    }
    for (const s of seasons) {
      if (!s.label.trim()) return 'Every crop season needs a label.'
      if (!dateRe.test(s.start) || !dateRe.test(s.end)) return `Season "${s.label}" needs YYYY-MM-DD dates.`
      if (s.end < s.start) return `Season "${s.label}" ends before it starts.`
    }
    return null
  }

  const mutation = useMutation({
    mutationFn: () =>
      createFeatureRun(selectedField.id, {
        start_date: start,
        end_date: end,
        aggregation_levels: levels,
        hemisphere,
        crop_seasons:
          levels.includes('crop_season') && seasons.length
            ? seasons.map((s) => ({ label: s.label.trim(), start_date: s.start, end_date: s.end }))
            : [],
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['feature-runs', selectedField.id] })
      if (run.status === 'succeeded') {
        toast.success('Feature run completed', {
          description: `${run.records_written} values written · engine ${run.feature_engine_version}`,
        })
        onCreated(run)
      } else if (run.status === 'failed') {
        toast.error('Feature run failed', { description: run.error_summary ?? undefined })
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarRange className="h-4 w-4 text-emerald-700" aria-hidden />
          Create feature run
        </CardTitle>
        <CardDescription>
          Derived features are computed from ONE source per variable (products are never blended).
          Coverage below a definition&apos;s minimum leaves the value explicitly empty — missing data
          is never treated as zero.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="feature-start">Period start</Label>
            <Input id="feature-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="feature-end">Period end</Label>
            <Input id="feature-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="feature-hemisphere">Season hemisphere</Label>
            <Select value={hemisphere} onValueChange={(v) => setHemisphere(v as 'north' | 'south')}>
              <SelectTrigger id="feature-hemisphere" aria-label="Season hemisphere">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="north">North (DJF · MAM · JJA · SON)</SelectItem>
                <SelectItem value="south">South (JJA · SON · DJF · MAM)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Aggregation levels</Label>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-1">
              {AGGREGATION_LEVELS.map((level) => (
                <label key={level.value} className="flex min-w-0 items-center gap-1.5 text-sm text-stone-700">
                  <Checkbox
                    checked={levels.includes(level.value)}
                    onCheckedChange={() => toggleLevel(level.value)}
                    aria-label={`Aggregation level ${level.label}`}
                  />
                  {level.label}
                </label>
              ))}
            </div>
          </div>
        </div>

        {levels.includes('crop_season') && (
          <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-stone-700">Crop-season windows</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setSeasons((prev) => [...prev, { label: '', start: '', end: '' }])}
              >
                Add window
              </Button>
            </div>
            <p className="text-xs text-stone-500">
              Windows are recorded verbatim in run provenance. Crop calendars from the sourced
              knowledge base arrive in a later milestone — nothing is invented here.
            </p>
            {seasons.map((season, index) => (
              <div key={index} className="grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
                <Input
                  placeholder="Label, e.g. maize_2024"
                  value={season.label}
                  onChange={(e) =>
                    setSeasons((prev) => prev.map((s, i) => (i === index ? { ...s, label: e.target.value } : s)))
                  }
                  aria-label={`Season ${index + 1} label`}
                />
                <Input
                  type="date"
                  value={season.start}
                  onChange={(e) =>
                    setSeasons((prev) => prev.map((s, i) => (i === index ? { ...s, start: e.target.value } : s)))
                  }
                  aria-label={`Season ${index + 1} start`}
                />
                <Input
                  type="date"
                  value={season.end}
                  onChange={(e) =>
                    setSeasons((prev) => prev.map((s, i) => (i === index ? { ...s, end: e.target.value } : s)))
                  }
                  aria-label={`Season ${index + 1} end`}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setSeasons((prev) => prev.filter((_, i) => i !== index))}
                  aria-label={`Remove season ${index + 1}`}
                >
                  <XCircle className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}

        {levels.includes('daily') && (
          <Alert>
            <Info className="h-4 w-4" aria-hidden />
            <AlertTitle>Daily values are voluminous</AlertTitle>
            <AlertDescription>
              Each requested day becomes one stored value per feature. Keep daily windows to about
              three years per run.
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-stone-500">
            Indices follow cited meteorological conventions (WMO dry day, ETCCDI temperature
            indices). Crop-specific stress thresholds remain unevaluated until the sourced crop
            knowledge base exists.
          </p>
          <Button
            onClick={() => {
              const problem = validate()
              if (problem) {
                toast.error('Check the run settings', { description: problem })
                return
              }
              mutation.mutate()
            }}
            disabled={mutation.isPending}
            className="bg-emerald-700 text-white hover:bg-emerald-800"
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <FlaskConical className="h-4 w-4" aria-hidden />
            )}
            Run features
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function RunDetail({ fieldId, run }: { fieldId: string; run: FeatureRun }) {
  const [level, setLevel] = useState<string>(run.aggregation_levels[0] ?? 'monthly')
  const runsQuery = useFeatureRuns(fieldId)
  const valuesQuery = useFeatureValues(run.run_id, { aggregationLevel: level })
  const [againstId, setAgainstId] = useState<string>('')
  const comparisonQuery = useFeatureComparison(run.run_id, againstId || null, Boolean(againstId))

  const otherRuns = useMemo(
    () => (runsQuery.data?.items ?? []).filter((r) => r.run_id !== run.run_id),
    [runsQuery.data, run.run_id],
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              Run {run.run_id.slice(0, 8)}
              <JobStatusBadge status={run.status} />
              {run.is_synthetic && <SyntheticBadge />}
            </CardTitle>
            <CardDescription className="mt-1">
              {run.period.start} → {run.period.end} · {run.calendar_timezone} ({run.hemisphere})
              · engine {run.feature_engine_version} · catalog {run.feature_catalog_version}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {run.aggregation_levels.map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLevel(l)}
                className={cn(
                  'rounded-md border px-2.5 py-1 text-xs font-medium transition',
                  level === l
                    ? 'border-emerald-700 bg-emerald-700 text-white'
                    : 'border-stone-300 bg-white text-stone-600 hover:bg-stone-50',
                )}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {run.is_synthetic && (
          <Alert className="border-amber-300 bg-amber-50">
            <AlertTriangle className="h-4 w-4 text-amber-700" aria-hidden />
            <AlertTitle className="text-amber-900">Synthetic fixture data</AlertTitle>
            <AlertDescription className="text-amber-900">
              This run is computed from SYNTHETIC fixture data — values demonstrate the pipeline
              and are never valid for real-world conclusions.
            </AlertDescription>
          </Alert>
        )}

        {run.warnings.length > 0 && (
          <div className="space-y-1.5 rounded-lg border border-stone-200 bg-stone-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Run warnings ({run.warnings.length})
            </p>
            <ul className="max-h-32 space-y-1 overflow-y-auto text-xs text-stone-600">
              {run.warnings.map((w, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden>•</span>
                  <span className="min-w-0 break-words">{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {Object.keys(run.not_evaluated_reasons).length > 0 && (
          <div className="space-y-1.5 rounded-lg border border-stone-200 bg-stone-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Not evaluated — with reasons
            </p>
            <ul className="max-h-32 space-y-1 overflow-y-auto text-xs text-stone-600">
              {Object.entries(run.not_evaluated_reasons).map(([code, reason]) => (
                <li key={code}>
                  <span className="font-medium">{code.replace('variable:', '')}</span> — {reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        {run.error_summary && (
          <Alert variant="destructive">
            <XCircle className="h-4 w-4" aria-hidden />
            <AlertTitle>Run failed</AlertTitle>
            <AlertDescription className="break-words">{run.error_summary}</AlertDescription>
          </Alert>
        )}

        {/* values */}
        {valuesQuery.isLoading ? (
          <div className="flex h-24 items-center justify-center text-sm text-stone-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Loading values…
          </div>
        ) : valuesQuery.data && valuesQuery.data.items.length > 0 ? (
          <div className="max-h-96 overflow-y-auto rounded-lg border border-stone-200">
            <Table>
              <TableHeader className="sticky top-0 bg-white">
                <TableRow>
                  <TableHead>Period</TableHead>
                  <TableHead>Feature</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right">Unit</TableHead>
                  <TableHead className="text-right">Coverage</TableHead>
                  <TableHead>Quality</TableHead>
                  <TableHead>Provenance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {valuesQuery.data.items.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="whitespace-nowrap font-mono text-xs">{v.period_label}</TableCell>
                    <TableCell className="max-w-56 truncate text-xs" title={v.feature_code}>
                      {v.feature_code}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{fmtNum(v.value, 3)}</TableCell>
                    <TableCell className="text-right text-xs text-stone-500">{v.unit}</TableCell>
                    <TableCell className="text-right text-xs text-stone-500">
                      {coveragePct(v.coverage_ratio)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn('px-1.5 py-0 text-[10px]', featureQualityTone(v.quality_status))}>
                        {v.quality_status.replace('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-stone-500">
                      {v.provenance.observation_count ?? v.provenance.inputs?.observation_count ?? 0} obs
                      {v.provenance.baseline
                        ? ` · baseline ${v.provenance.baseline.n_years}y`
                        : ''}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-stone-300 p-6 text-center text-sm text-stone-500">
            No stored values for level “{level}” in this run.
          </p>
        )}

        {/* comparison */}
        {otherRuns.length > 0 && (
          <div className="space-y-3 rounded-lg border border-stone-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <GitCompareArrows className="h-4 w-4 text-stone-500" aria-hidden />
              <p className="text-sm font-medium text-stone-700">Compare with another run</p>
              <Select value={againstId || undefined} onValueChange={setAgainstId}>
                <SelectTrigger className="h-8 w-56" aria-label="Select run to compare against">
                  <SelectValue placeholder="Choose a run…" />
                </SelectTrigger>
                <SelectContent>
                  {otherRuns.map((r) => (
                    <SelectItem key={r.run_id} value={r.run_id}>
                      {r.run_id.slice(0, 8)} · {r.period.start} → {r.period.end}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {comparisonQuery.data && comparisonQuery.data.deltas.length > 0 && (
              <div className="max-h-72 overflow-y-auto rounded-md border border-stone-200">
                <Table>
                  <TableHeader className="sticky top-0 bg-white">
                    <TableRow>
                      <TableHead>Period</TableHead>
                      <TableHead>Feature</TableHead>
                      <TableHead className="text-right">This run</TableHead>
                      <TableHead className="text-right">Against</TableHead>
                      <TableHead className="text-right">Δ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {comparisonQuery.data.deltas.map((d) => (
                      <TableRow key={`${d.feature_code}-${d.period_label}`}>
                        <TableCell className="whitespace-nowrap font-mono text-xs">{d.period_label}</TableCell>
                        <TableCell className="max-w-52 truncate text-xs" title={d.feature_code}>
                          {d.feature_code}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">{fmtNum(d.run_value, 3)}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{fmtNum(d.against_value, 3)}</TableCell>
                        <TableCell
                          className={cn(
                            'text-right font-mono text-xs font-semibold',
                            d.delta > 0 ? 'text-emerald-700' : d.delta < 0 ? 'text-red-700' : 'text-stone-500',
                          )}
                        >
                          {d.delta > 0 ? '+' : ''}
                          {fmtNum(d.delta, 3)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {comparisonQuery.data && comparisonQuery.data.deltas.length === 0 && (
              <p className="text-xs text-stone-500">
                No overlapping evaluated periods between these runs.
              </p>
            )}
            {againstId && (
              <p className="text-xs text-stone-500">{comparisonQuery.data?.note}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function Features() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const goToObservationsFor = useFieldShiftUi((s) => s.goToObservationsFor)
  const catalogQuery = useFeatureCatalog()
  const runsQuery = useFeatureRuns(selectedField?.id ?? null)
  const [openRunId, setOpenRunId] = useState<string | null>(null)

  const runs = runsQuery.data?.items ?? []
  const openRun = runs.find((r) => r.run_id === openRunId) ?? null

  if (!selectedField) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarRange className="h-4 w-4 text-emerald-700" aria-hidden />
            Features
          </CardTitle>
          <CardDescription>
            Pick a field to create reproducible feature runs: daily, monthly, seasonal and
            crop-season aggregations with baselines, anomalies and drought/heat indicators.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldPicker
            value={null}
            onValueChange={setSelectedField}
            emptyHint={
              <div className="flex flex-wrap items-center gap-2 text-sm text-stone-500">
                <span>Create a farm and field first.</span>
                <Button variant="outline" size="sm" onClick={() => goToObservationsFor({ id: '', name: '', farmId: '' })}>
                  Go to Farms & Fields <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            }
          />
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <CalendarRange className="h-4 w-4 text-emerald-700" aria-hidden />
                Features
              </CardTitle>
              <CardDescription>
                Versioned feature definitions · reproducible runs · full provenance to source
                observations
              </CardDescription>
            </div>
            <div className="min-w-0">
              <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
            </div>
          </div>
        </CardHeader>
      </Card>

      <CreateRunForm selectedField={selectedField} onCreated={(run) => setOpenRunId(run.run_id)} />

      {/* runs list */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Feature runs</CardTitle>
          <CardDescription>
            {runsQuery.isLoading
              ? 'Loading runs…'
              : runs.length === 0
                ? 'No runs yet for this field.'
                : `${runsQuery.data?.total ?? runs.length} run(s) — newest first`}
          </CardDescription>
        </CardHeader>
        {runs.length > 0 && (
          <CardContent className="space-y-2">
            {runs.map((run) => (
              <div
                key={run.run_id}
                className={cn(
                  'rounded-lg border p-3 transition',
                  openRunId === run.run_id ? 'border-emerald-300 bg-emerald-50/50' : 'border-stone-200 bg-white',
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <JobStatusBadge status={run.status} />
                    {run.is_synthetic && <SyntheticBadge />}
                    <span className="font-mono text-xs text-stone-700">{run.run_id.slice(0, 8)}</span>
                    <span className="text-xs text-stone-500">
                      {run.period.start} → {run.period.end} · {run.aggregation_levels.join(', ')} ·{' '}
                      {run.records_written} values
                    </span>
                  </div>
                  {openRunId === run.run_id ? (
                    <Button variant="ghost" size="sm" onClick={() => setOpenRunId(null)}>
                      Hide details
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setOpenRunId(run.run_id)
                        runsQuery.refetch()
                      }}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
                      Details
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        )}
      </Card>

      {openRun && <RunDetail fieldId={selectedField.id} run={openRun} />}

      {/* catalog */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Feature catalog{' '}
            {catalogQuery.data && (
              <Badge variant="outline" className="ml-2 border-stone-300 font-mono text-[10px] font-normal">
                {catalogQuery.data.feature_catalog_version}
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            Definitions are versioned data: every value records the catalog version and formula
            reference it was computed with.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {catalogQuery.data && (
            <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
              {catalogQuery.data.features.map((f) => (
                <div key={f.feature_code} className="rounded-lg border border-stone-200 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-stone-800">{f.name}</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline" className="border-stone-300 px-1.5 py-0 text-[10px] capitalize">
                        {f.category}
                      </Badge>
                      <Badge variant="outline" className="border-stone-300 px-1.5 py-0 text-[10px]">
                        {f.unit}
                      </Badge>
                      <Badge variant="outline" className="border-stone-300 px-1.5 py-0 text-[10px]">
                        coverage ≥ {Math.round(f.min_coverage_ratio * 100)}%
                      </Badge>
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-stone-600">{f.description}</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-stone-500">{f.formula_reference}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

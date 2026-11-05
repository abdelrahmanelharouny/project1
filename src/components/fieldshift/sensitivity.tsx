'use client'

/**
 * Sensitivity & Uncertainty Workspace (M7.4).
 *
 * Analyses ONE immutable M7.3 execution run: varies the run's configured
 * transformation parameters over user-supplied bounds, shows OAT responses,
 * the explored parameter-range envelope, the optional joint grid, and the
 * uncertainty registry — with complete provenance and honesty disclosures.
 *
 * Honesty rules rendered here (M7.4 spec §2/§4):
 * - The envelope is always labelled "explored parameter-range envelope" — a
 *   deterministic sensitivity result, NOT a confidence or probability interval.
 * - Parameters not configured in the source execution appear as not
 *   applicable with the API's reason — never hidden, never editable.
 * - Elasticity is only shown when the API reports it available; otherwise the
 *   structured unavailability reason is printed.
 * - The interaction contrast is always labelled "finite-grid interaction
 *   contrast" — never a Sobol index.
 * - No probabilities, forecasts, yield impact or climate projections anywhere.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import {
  createSensitivityAnalysis,
  getSensitivityAnalysis,
  getSensitivityGrid,
  getSensitivityUncertainty,
  listScenarioExecutions,
  listScenarios,
  listSensitivityAnalyses,
  listSensitivityResponses,
  ApiError,
  verifySensitivityAnalysis,
} from '@/lib/api'
import type {
  ScenarioExecutionRun,
  SensitivityAnalysis,
  SensitivityOatResponse,
  SensitivityVerifyResponse,
} from '@/lib/types'
import { useFieldShiftUi } from '@/lib/store'
import { Info, LineChart, Loader2, Play, ShieldAlert, ShieldCheck } from 'lucide-react'

function apiErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.details[0]
    const detailText = detail?.reason ? `${detail.field}: ${detail.reason}` : detail?.field
    return detailText ? `${err.message} (${detailText})` : err.message
  }
  return err instanceof Error ? err.message : 'Unexpected error'
}

function fmt(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined) return '—'
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(digits)
}

function shortHash(hash: string | null | undefined): string {
  return hash ? `${hash.slice(0, 12)}…` : '—'
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function AnalysisStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued: 'border-stone-300 bg-white text-stone-600',
    running: 'border-amber-200 bg-amber-50 text-amber-700',
    succeeded: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    completed_with_limitations: 'border-amber-300 bg-amber-50 text-amber-800',
    failed: 'border-red-300 bg-red-50 text-red-700',
  }
  return (
    <Badge variant="outline" className={`font-normal ${map[status] ?? ''}`}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}

function ClassificationBadge({ classification }: { classification: string }) {
  const map: Record<string, string> = {
    constant: 'border-stone-300 bg-stone-100 text-stone-600',
    monotonic_increasing: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    monotonic_decreasing: 'border-amber-300 bg-amber-50 text-amber-800',
    threshold_suspected: 'border-orange-300 bg-orange-50 text-orange-800',
    non_monotonic: 'border-purple-300 bg-purple-50 text-purple-800',
    insufficient_evaluated_points: 'border-stone-300 bg-stone-100 text-stone-500',
    not_evaluated: 'border-stone-300 bg-stone-100 text-stone-500',
  }
  return (
    <Badge variant="outline" className={`font-normal ${map[classification] ?? ''}`}>
      {classification.replace(/_/g, ' ')}
    </Badge>
  )
}

function UncertaintyStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    quantified: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    bounded_exploratory: 'border-sky-300 bg-sky-50 text-sky-800',
    qualitative_only: 'border-stone-300 bg-stone-100 text-stone-600',
    not_quantified: 'border-orange-300 bg-orange-50 text-orange-800',
    not_applicable: 'border-stone-300 bg-stone-100 text-stone-500',
    not_evaluated: 'border-stone-300 bg-stone-100 text-stone-500',
  }
  return (
    <Badge variant="outline" className={`font-normal ${map[status] ?? ''}`}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Envelope & response table
// ---------------------------------------------------------------------------

function ResponseRow({ row }: { row: SensitivityOatResponse }) {
  const envelope = row.explored_parameter_range_envelope
  return (
    <TableRow>
      <TableCell className="max-w-[220px] truncate font-mono text-xs" title={row.feature_code}>
        {row.feature_code}
      </TableCell>
      <TableCell className="text-xs text-stone-500">{row.period_label}</TableCell>
      <TableCell className="text-right font-mono text-xs">{fmt(row.reference_value)}</TableCell>
      <TableCell className="text-right font-mono text-xs">
        {envelope.lower === null ? '—' : `[${fmt(envelope.lower)}, ${fmt(envelope.upper)}]`}
      </TableCell>
      <TableCell className="text-right font-mono text-xs">{fmt(row.output_range)}</TableCell>
      <TableCell className="text-right font-mono text-xs" title={`${row.slope_units} (${row.slope_method})`}>
        {row.slope === null ? '—' : fmt(row.slope, 6)}
        <span className="ml-1 text-[10px] text-stone-400">{row.slope_units}</span>
        {row.slope_validity === 'invalid_across_suspected_discontinuity' && (
          <span className="ml-1 text-[10px] text-orange-700">slope invalid across jump</span>
        )}
      </TableCell>
      <TableCell className="text-xs">
        {row.elasticity.status === 'available' ? (
          <span className="font-mono text-xs">{fmt(row.elasticity.value)}</span>
        ) : (
          <span className="text-[11px] text-stone-500" title={row.elasticity.reason ?? ''}>
            unavailable: {row.elasticity.reason?.replace(/_/g, ' ')}
          </span>
        )}
      </TableCell>
      <TableCell className="text-xs">{row.direction.replace(/_/g, ' ')}</TableCell>
      <TableCell>
        <ClassificationBadge classification={row.response_classification} />
      </TableCell>
    </TableRow>
  )
}

function ResponsesCard({ analysisId, parameterCode }: { analysisId: string; parameterCode: string | null }) {
  const [classificationFilter, setClassificationFilter] = useState<string>('')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['sensitivity-responses', analysisId, parameterCode, classificationFilter],
    queryFn: () =>
      listSensitivityResponses(analysisId, {
        parameter_code: parameterCode ?? undefined,
        response_classification: classificationFilter || undefined,
      }),
    enabled: Boolean(analysisId),
  })
  // Unbounded feature sets would explode the DOM; render a capped window
  // behind the classification/parameter filters. Evaluated responses surface
  // first — the alphabetically-first rows are often honest not_evaluated ones.
  const MAX_ROWS = 100
  const rows = useMemo(() => {
    const items = data?.items ?? []
    const rank: Record<string, number> = {
      evaluated: 0,
      partially_evaluated: 1,
      not_evaluated: 2,
    }
    return [...items].sort((a, b) => {
      const r = (rank[a.response_status] ?? 3) - (rank[b.response_status] ?? 3)
      if (r !== 0) return r
      return `${a.feature_code}|${a.aggregation_level}|${a.period_label}`.localeCompare(
        `${b.feature_code}|${b.aggregation_level}|${b.period_label}`,
      )
    })
  }, [data])
  const visible = rows.slice(0, MAX_ROWS)

  if (isLoading)
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (isError) return <p className="text-sm text-red-700">{apiErrorText(error)}</p>
  if (!data) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">One-factor-at-a-time responses</CardTitle>
        <CardDescription>
          Each parameter varies over the explored bounds while every other configured
          parameter is held at its reference value. Slopes keep their units and are never
          compared across different units.
        </CardDescription>
        <div className="flex flex-wrap gap-1.5 pt-1">
          {['', 'monotonic_increasing', 'monotonic_decreasing', 'threshold_suspected', 'non_monotonic', 'constant'].map(
            (c) => (
              <button
                key={c || 'all'}
                onClick={() => setClassificationFilter(c)}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  classificationFilter === c
                    ? 'border-stone-800 bg-stone-800 text-white'
                    : 'border-stone-300 bg-white text-stone-600 hover:bg-stone-50'
                }`}
              >
                {c === '' ? 'all' : c.replace(/_/g, ' ')}
              </button>
            ),
          )}
        </div>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-stone-500">No responses for this filter.</p>
        ) : (
          <>
          <div className="max-h-96 overflow-y-auto rounded-md border">
            <Table>
              <TableHeader className="sticky top-0 bg-white">
                <TableRow>
                  <TableHead>Feature</TableHead>
                  <TableHead>Period</TableHead>
                  <TableHead className="text-right">Reference</TableHead>
                  <TableHead className="text-right">Explored envelope</TableHead>
                  <TableHead className="text-right">Output range</TableHead>
                  <TableHead className="text-right">Slope (units)</TableHead>
                  <TableHead>Elasticity</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Classification</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((row, i) => (
                  <ResponseRow key={`${row.parameter_code}-${row.feature_code}-${row.period_label}-${i}`} row={row} />
                ))}
              </TableBody>
            </Table>
          </div>
          {rows.length > visible.length && (
            <p className="mt-2 text-xs text-stone-500">
              Showing the first {visible.length} of {rows.length} responses — narrow with the
              classification filter or a specific feature to see more.
            </p>
          )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Grid card
// ---------------------------------------------------------------------------

function GridCard({ analysisId, hasGrid }: { analysisId: string; hasGrid: boolean }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['sensitivity-grid', analysisId],
    queryFn: () => getSensitivityGrid(analysisId),
    enabled: Boolean(analysisId) && hasGrid,
  })
  if (!hasGrid)
    return (
      <p className="text-sm text-stone-500">
        No joint parameter grid was requested for this analysis.
      </p>
    )
  if (isLoading) return <Skeleton className="h-40 w-full" />
  if (isError) return <p className="text-sm text-red-700">{apiErrorText(error)}</p>
  if (!data) return null

  // A full joint grid stores one summary per feature key (thousands); render a
  // capped window — the API's feature_code filter narrows on demand.
  const MAX_SUMMARIES = 50
  const summaries = data.summaries
  const visible = summaries.slice(0, MAX_SUMMARIES)

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Joint parameter grid</CardTitle>
        <CardDescription>{data.note}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="max-h-96 overflow-y-auto rounded-md border">
          <Table>
            <TableHeader className="sticky top-0 bg-white">
              <TableRow>
                <TableHead>Feature</TableHead>
                <TableHead>Period</TableHead>
                <TableHead className="text-right">Grid range</TableHead>
                <TableHead>Direction</TableHead>
                <TableHead>Non-monotonic</TableHead>
                <TableHead className="text-right">Threshold transitions</TableHead>
                <TableHead className="text-right">Finite-grid interaction contrast</TableHead>
                <TableHead>Interpretation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((s, i) => (
                <TableRow key={`${s.feature_code}-${s.period_label}-${i}`}>
                  <TableCell className="max-w-[200px] truncate font-mono text-xs" title={s.feature_code}>
                    {s.feature_code}
                  </TableCell>
                  <TableCell className="text-xs text-stone-500">{s.period_label}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {s.grid_min === null ? '—' : `[${fmt(s.grid_min)}, ${fmt(s.grid_max)}]`}
                  </TableCell>
                  <TableCell className="text-xs">{s.direction.replace(/_/g, ' ')}</TableCell>
                  <TableCell className="text-xs">{s.non_monotonic ? 'yes' : 'no'}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{s.threshold_transition_count}</TableCell>
                  <TableCell className="text-right font-mono text-xs" title="finite-grid interaction contrast — not a Sobol index">
                    {s.interaction_contrast === null ? '—' : fmt(s.interaction_contrast, 6)}
                  </TableCell>
                  <TableCell className="text-xs">{s.interaction_interpretation.replace(/_/g, ' ')}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {summaries.length > visible.length && (
          <p className="text-xs text-stone-500">
            Showing the first {visible.length} of {summaries.length} grid summaries —
            per-feature detail is available through the API&apos;s feature_code filter.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Uncertainty registry card
// ---------------------------------------------------------------------------

function UncertaintyCard({ analysisId }: { analysisId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['sensitivity-uncertainty', analysisId],
    queryFn: () => getSensitivityUncertainty(analysisId),
    enabled: Boolean(analysisId),
  })
  if (isLoading) return <Skeleton className="h-40 w-full" />
  if (isError) return <p className="text-sm text-red-700">{apiErrorText(error)}</p>
  if (!data) return null

  const grouped = data.items.reduce<Record<string, typeof data.items>>((acc, item) => {
    ;(acc[item.category] ??= []).push(item)
    return acc
  }, {})

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Uncertainty &amp; limitation registry</CardTitle>
        <CardDescription>{data.note}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <p className="mb-1.5 text-xs font-semibold text-stone-700">
              {category.replace(/_/g, ' ')}
            </p>
            <div className="space-y-2">
              {items.map((item) => (
                <div key={item.code} className="rounded-md border border-stone-200 bg-white p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <UncertaintyStatusBadge status={item.quantification_status} />
                    <Badge variant="outline" className="border-stone-200 font-normal text-stone-500">
                      {item.applicability}
                    </Badge>
                    <span className="font-mono text-[11px] text-stone-400">{item.code}</span>
                    {item.affects_current_analysis && (
                      <Badge variant="outline" className="border-amber-200 bg-amber-50 font-normal text-amber-700">
                        affects this analysis
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1.5 text-xs text-stone-600">{item.user_facing_explanation}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Analysis results (detail view)
// ---------------------------------------------------------------------------

function VerifyCard({ analysisId }: { analysisId: string }) {
  const queryClient = useQueryClient()
  const verify = useMutation({
    mutationFn: () => verifySensitivityAnalysis(analysisId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sensitivity-analysis', analysisId] }),
  })
  const result = verify.data
  const flags: Array<readonly [keyof SensitivityVerifyResponse, string]> = result
    ? [
        ['output_checksum_valid', 'output checksum'],
        ['source_run_intact', 'source run intact'],
        ['parent_snapshot_intact', 'parent snapshot intact'],
        ['manifest_checksum_matches', 'manifest checksum matches'],
        ['reference_reproduction_consistent', 'reference reproduction consistent'],
      ]
    : []
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Integrity verification</CardTitle>
        <CardDescription>
          Recomputes the analysis checksum from persisted artifacts and re-checks the
          source-run pins. Confirms the integrity of a hypothetical analysis — never that
          transformed values are observations.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : <ShieldCheck className="mr-1.5 h-3.5 w-3.5" aria-hidden />}
          Verify analysis
        </Button>
        {verify.isError && (
          <p className="mt-2 text-sm text-red-700">{apiErrorText(verify.error)}</p>
        )}
        {result && (
          <div className="mt-3 space-y-1.5">
            {flags.map(([flag, label]) => (
              <div key={flag} className="flex items-center gap-2 text-xs">
                {result[flag] ? (
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
                ) : (
                  <ShieldAlert className="h-3.5 w-3.5 text-red-600" aria-hidden />
                )}
                <span className="text-stone-600">{label}</span>
                <span className="ml-auto font-mono text-[10px] text-stone-400">{String(result[flag])}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function AnalysisResults({ analysis }: { analysis: SensitivityAnalysis }) {
  const parameters = useMemo(
    () => Object.keys(analysis.parameter_design ?? {}),
    [analysis.parameter_design],
  )
  const [selectedParameter, setSelectedParameter] = useState<string | null>(null)
  // Derived (no sync-effect): fall back to the first explored parameter when
  // the selection is absent or no longer part of the design.
  const activeParameter =
    selectedParameter && parameters.includes(selectedParameter) ? selectedParameter : (parameters[0] ?? null)

  const reproduction = analysis.reference_reproduction

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <AnalysisStatusBadge status={analysis.analysis_status} />
        <Badge variant="outline" className="border-stone-200 font-normal text-stone-500">
          {analysis.evaluation_count} evaluations · {analysis.evaluated_feature_count} features
        </Badge>
        <Badge variant="outline" className="border-stone-200 font-normal text-stone-500">
          checksum {shortHash(analysis.output_checksum)}
        </Badge>
        <Badge variant="outline" className="border-stone-200 font-normal text-stone-500">
          method {analysis.analysis_method_version}
        </Badge>
      </div>

      <Alert className="border-amber-200 bg-amber-50">
        <Info className="h-4 w-4 text-amber-700" aria-hidden />
        <AlertTitle className="text-amber-900">Deterministic sensitivity — not probability</AlertTitle>
        <AlertDescription className="text-amber-900">
          {analysis.evidence_note} All disclosures: {analysis.warnings.length > 0 ? 'see below.' : '—'}
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Reference reproduction</CardTitle>
          <CardDescription>
            The analysis first reproduced the source execution exactly before comparing
            anything. A failed reproduction aborts the analysis — no substitute baseline.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 text-xs">
            <span>
              reproduced:{' '}
              <strong className={reproduction.reproduced ? 'text-emerald-700' : 'text-red-700'}>
                {String(reproduction.reproduced)}
              </strong>
            </span>
            <span>
              rows: {reproduction.matched_rows}/{reproduction.compared_rows} matched
            </span>
            <span>
              observation count match: <strong>{String(reproduction.observation_count_match)}</strong>
            </span>
          </div>
        </CardContent>
      </Card>

      {analysis.analysis_status === 'failed' && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" aria-hidden />
          <AlertTitle>Analysis failed</AlertTitle>
          <AlertDescription>{analysis.error_summary}</AlertDescription>
        </Alert>
      )}

      {parameters.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {parameters.map((code) => (
            <button
              key={code}
              onClick={() => setSelectedParameter(code)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                activeParameter === code
                  ? 'border-stone-800 bg-stone-800 text-white'
                  : 'border-stone-300 bg-white text-stone-600 hover:bg-stone-50'
              }`}
            >
              {code.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      )}

      {activeParameter && (
        <ResponsesCard analysisId={analysis.analysis_id} parameterCode={activeParameter} />
      )}

      <GridCard analysisId={analysis.analysis_id} hasGrid={Boolean(analysis.grid_design)} />

      <UncertaintyCard analysisId={analysis.analysis_id} />

      {analysis.not_analysed_features &&
        Object.keys(analysis.not_analysed_features).length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Features outside the analysis scope</CardTitle>
              <CardDescription>
                Inherited verbatim from the source execution — reported, never fabricated.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="max-h-64 space-y-1.5 overflow-y-auto">
                {Object.entries(analysis.not_analysed_features).slice(0, 100).map(([code, reason]) => (
                  <div key={code} className="rounded-md border border-stone-200 p-2 text-xs">
                    <span className="font-mono text-stone-700">{code}</span>
                    <p className="mt-0.5 text-stone-500">{reason}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Disclosures</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-4 text-xs text-stone-600">
            {analysis.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <VerifyCard analysisId={analysis.analysis_id} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Definition form
// ---------------------------------------------------------------------------

interface BoundState {
  lower: string
  upper: string
  points: string
}

function DefinitionForm({
  run,
  referenceValues,
  explorableDetail,
  onCreated,
}: {
  run: ScenarioExecutionRun
  referenceValues: Record<string, number>
  explorableDetail: Record<string, { explorable: boolean; reference_value: number | null; reason: string | null }>
  onCreated: (analysis: SensitivityAnalysis) => void
}) {
  const queryClient = useQueryClient()
  const bothExplorable =
    explorableDetail.temperature_delta_c?.explorable && explorableDetail.precipitation_multiplier?.explorable

  const defaults: Record<string, BoundState> = {
    temperature_delta_c: { lower: '-2', upper: '6', points: '9' },
    precipitation_multiplier: { lower: '0.5', upper: '1.5', points: '9' },
  }
  const [bounds, setBounds] = useState<Record<string, BoundState>>({
    temperature_delta_c: defaults.temperature_delta_c,
    precipitation_multiplier: defaults.precipitation_multiplier,
  })
  const [includeGrid, setIncludeGrid] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const explorableCodes = Object.entries(explorableDetail)
    .filter(([, v]) => v.explorable)
    .map(([code]) => code)

  const create = useMutation({
    mutationFn: () => {
      const parameter_design: Record<string, { lower: number; upper: number; n_points: number }> = {}
      for (const code of explorableCodes) {
        const b = bounds[code]
        parameter_design[code] = {
          lower: Number(b.lower),
          upper: Number(b.upper),
          n_points: Number(b.points),
        }
      }
      return createSensitivityAnalysis(run.run_id, {
        parameter_design,
        grid: includeGrid && bothExplorable ? true : undefined,
      })
    },
    onSuccess: (analysis) => {
      queryClient.invalidateQueries({ queryKey: ['sensitivity-analyses', run.run_id] })
      onCreated(analysis)
    },
  })

  const refDelta = referenceValues.temperature_delta_c
  const refMult = referenceValues.precipitation_multiplier

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Define the exploration</CardTitle>
        <CardDescription>
          Bounds are user-supplied assumptions for a deterministic experiment — they
          contain the source execution&apos;s reference values and imply no probability
          distribution.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(explorableDetail).map(([code, detail]) => {
            const ref = code === 'temperature_delta_c' ? refDelta : refMult
            if (!detail.explorable) {
              return (
                <div key={code} className="rounded-md border border-stone-200 bg-stone-50 p-3">
                  <p className="text-xs font-medium text-stone-700">{code.replace(/_/g, ' ')}</p>
                  <p className="mt-1 text-xs text-stone-500">
                    Not applicable — {detail.reason}
                  </p>
                </div>
              )
            }
            const b = bounds[code]
            const set = (patch: Partial<BoundState>) =>
              setBounds((prev) => ({ ...prev, [code]: { ...prev[code], ...patch } }))
            return (
              <div key={code} className="rounded-md border border-stone-200 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-stone-700">{code.replace(/_/g, ' ')}</p>
                  <Badge variant="outline" className="border-stone-200 font-normal text-stone-500">
                    reference {fmt(ref)}
                  </Badge>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  <div>
                    <Label className="text-[11px] text-stone-500" htmlFor={`${code}-lower`}>
                      Lower
                    </Label>
                    <Input
                      id={`${code}-lower`}
                      className="h-8 text-xs"
                      inputMode="decimal"
                      value={b.lower}
                      onChange={(e) => set({ lower: e.target.value })}
                    />
                  </div>
                  <div>
                    <Label className="text-[11px] text-stone-500" htmlFor={`${code}-upper`}>
                      Upper
                    </Label>
                    <Input
                      id={`${code}-upper`}
                      className="h-8 text-xs"
                      inputMode="decimal"
                      value={b.upper}
                      onChange={(e) => set({ upper: e.target.value })}
                    />
                  </div>
                  <div>
                    <Label className="text-[11px] text-stone-500" htmlFor={`${code}-points`}>
                      Points (3–21)
                    </Label>
                    <Input
                      id={`${code}-points`}
                      className="h-8 text-xs"
                      inputMode="numeric"
                      value={b.points}
                      onChange={(e) => set({ points: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {bothExplorable && (
          <label className="flex items-center gap-2 text-xs text-stone-700">
            <input
              type="checkbox"
              checked={includeGrid}
              onChange={(e) => setIncludeGrid(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            Also evaluate the joint deterministic parameter grid (both axes reuse these bounds)
          </label>
        )}

        {formError && <p className="text-sm text-red-700">{formError}</p>}
        {create.isError && <p className="text-sm text-red-700">{apiErrorText(create.error)}</p>}

        <Button
          size="sm"
          onClick={() => {
            setFormError(null)
            create.mutate()
          }}
          disabled={create.isPending}
        >
          {create.isPending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Play className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          Run analysis
        </Button>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function SensitivitySection() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const selectedFieldId = selectedField?.id ?? null
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<SensitivityAnalysis | null>(null)

  // Scenarios of the selected field (finalized ones are analysis-eligible via
  // their result-bearing runs).
  const { data: scenarioList } = useQuery({
    queryKey: ['sensitivity-scenarios', selectedFieldId],
    queryFn: () => listScenarios(selectedFieldId as string),
    enabled: Boolean(selectedFieldId),
  })

  const finalizedScenarios = (scenarioList?.items ?? []).filter(
    (s) => s.scenario_status === 'finalized',
  )
  // Derived validity (no sync effects): a stale selection simply stops being
  // offered to the engine below.
  const effectiveScenarioId = finalizedScenarios.some((s) => s.id === scenarioId)
    ? scenarioId
    : null

  // Result-bearing runs of the chosen scenario.
  const { data: runList } = useQuery({
    queryKey: ['sensitivity-runs', effectiveScenarioId],
    queryFn: () => listScenarioExecutions(effectiveScenarioId as string),
    enabled: Boolean(effectiveScenarioId),
  })
  const resultRuns = (runList?.items ?? []).filter(
    (r) => r.run_status === 'succeeded' || r.run_status === 'completed_with_limitations',
  )
  const effectiveRunId = resultRuns.some((r) => r.run_id === runId) ? runId : null

  const { data: analysisList } = useQuery({
    queryKey: ['sensitivity-analyses', effectiveRunId],
    queryFn: () => listSensitivityAnalyses(effectiveRunId as string),
    enabled: Boolean(effectiveRunId) && !analysis,
  })

  const selectedRun = resultRuns.find((r) => r.run_id === effectiveRunId) ?? null
  // A created analysis belongs to the currently selected run; switching runs
  // (or a stale analysis) drops back to the definition view.
  const effectiveAnalysis =
    analysis && analysis.source_execution_run_id === effectiveRunId ? analysis : null

  const referenceValues = selectedRun?.execution_configuration.transformations.reduce<
    Record<string, number>
  >((acc, t) => {
    if (t.code === 'temperature_delta_c' && typeof t.delta_c === 'number') acc.temperature_delta_c = t.delta_c
    if (t.code === 'precipitation_multiplier' && typeof t.multiplier === 'number')
      acc.precipitation_multiplier = t.multiplier
    return acc
  }, {}) ?? {}

  const explorableDetail: Record<
    string,
    { explorable: boolean; reference_value: number | null; reason: string | null }
  > = {
    temperature_delta_c:
      'temperature_delta_c' in referenceValues
        ? { explorable: true, reference_value: referenceValues.temperature_delta_c, reason: null }
        : {
            explorable: false,
            reference_value: null,
            reason: 'parameter not configured in the source execution; no reference value exists',
          },
    precipitation_multiplier:
      'precipitation_multiplier' in referenceValues
        ? { explorable: true, reference_value: referenceValues.precipitation_multiplier, reason: null }
        : {
            explorable: false,
            reference_value: null,
            reason: 'parameter not configured in the source execution; no reference value exists',
          },
  }

  if (!selectedField) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LineChart className="h-4 w-4" aria-hidden />
            Sensitivity &amp; Uncertainty
          </CardTitle>
          <CardDescription>
            Pick a field to analyse how its scenario-derived environmental features
            respond to the executed transformation parameters.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldPicker
            value={null}
            onValueChange={(field) => {
              setSelectedField(field)
              setScenarioId(null)
              setRunId(null)
              setAnalysis(null)
            }}
          />
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <LineChart className="h-4 w-4" aria-hidden />
            Sensitivity &amp; Uncertainty — {selectedField.name}
          </CardTitle>
          <CardDescription>
            Deterministic one-factor-at-a-time analysis and optional joint parameter
            grids over an immutable scenario execution. The explored parameter-range
            envelope is a deterministic sensitivity result — not a confidence or
            probability interval. No yield, climate or rainfall predictions exist here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="mb-1.5 text-xs font-medium text-stone-600">Scenario (finalized)</p>
            <div className="flex flex-wrap gap-1.5">
              {finalizedScenarios.length === 0 && (
                <p className="text-xs text-stone-500">
                  No finalized scenarios for this field yet — create one in the Scenarios
                  tab.
                </p>
              )}
              {finalizedScenarios.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    setScenarioId(s.id)
                    setRunId(null)
                    setAnalysis(null)
                  }}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    scenarioId === s.id
                      ? 'border-stone-800 bg-stone-800 text-white'
                      : 'border-stone-300 bg-white text-stone-600 hover:bg-stone-50'
                  }`}
                >
                  {s.name}
                </button>
              ))}
            </div>
          </div>

          {scenarioId && (
            <div>
              <p className="mb-1.5 text-xs font-medium text-stone-600">
                Execution run (result-bearing)
              </p>
              <div className="flex flex-wrap gap-1.5">
                {resultRuns.length === 0 && (
                  <p className="text-xs text-stone-500">
                    No completed executions for this scenario — execute it in the
                    Scenarios tab first.
                  </p>
                )}
                {resultRuns.map((r) => (
                  <button
                    key={r.run_id}
                    onClick={() => {
                      setRunId(r.run_id)
                      setAnalysis(null)
                    }}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      runId === r.run_id
                        ? 'border-stone-800 bg-stone-800 text-white'
                        : 'border-stone-300 bg-white text-stone-600 hover:bg-stone-50'
                    }`}
                    title={`status: ${r.run_status}`}
                  >
                    run {r.run_id.slice(0, 8)}… · {r.run_status.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedRun && !effectiveAnalysis && (
        <>
          <DefinitionForm
            run={selectedRun}
            referenceValues={referenceValues}
            explorableDetail={explorableDetail}
            onCreated={(a) => setAnalysis(a)}
          />

          {(analysisList?.items ?? []).length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Previous analyses of this run</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {analysisList?.items.map((a) => (
                  <button
                    key={a.analysis_id}
                    onClick={() => setAnalysis(a)}
                    className="flex w-full flex-wrap items-center gap-2 rounded-md border border-stone-200 p-2 text-left text-xs hover:bg-stone-50"
                  >
                    <AnalysisStatusBadge status={a.analysis_status} />
                    <span className="font-mono text-stone-500">{shortHash(a.analysis_id)}</span>
                    <span className="text-stone-500">
                      {Object.keys(a.parameter_design).length} parameter(s)
                      {a.grid_design ? ' · joint grid' : ''}
                    </span>
                    <span className="ml-auto text-stone-400">
                      {a.completed_at ? a.completed_at.replace('T', ' ').slice(0, 16) : '—'}
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {effectiveAnalysis && (
        <div className="space-y-3">
          <Button size="sm" variant="ghost" onClick={() => setAnalysis(null)}>
            ← Back to run {runId ? `· ${runId.slice(0, 8)}…` : ''}
          </Button>
          <AnalysisResults analysis={effectiveAnalysis} />
        </div>
      )}
    </div>
  )
}

export default SensitivitySection

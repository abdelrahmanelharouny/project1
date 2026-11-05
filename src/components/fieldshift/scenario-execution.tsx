'use client'

/**
 * Scenario Execution Workspace (M7.3).
 *
 * Extension of the Scenarios tab: executes FINALIZED, executable scenario
 * definitions and presents the derived hypothetical results with complete
 * provenance, limitations and checksums.
 *
 * Honesty rules rendered here (M7.3 spec §13):
 * - Every transformed value is labelled a hypothetical assumption — never
 *   observed data (evidence badges on every row).
 * - Unsupported capabilities (climate projections, forecasts, soil and
 *   management scenario simulation, ET0 recalculation) are shown as explicit
 *   unavailable states — never simulated, never silently absent.
 * - Percentage difference is only shown where the API provided one (it is
 *   withheld when the baseline is zero or the comparison is invalid).
 * - No simulation charts and no yield/crop-impact visuals exist anywhere.
 */

import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  CircleAlert,
  FlaskConical,
  Info,
  Loader2,
  Play,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  compareScenarioExecution,
  executeScenario,
  listExecutionFeatures,
  listExecutionObservations,
  listScenarioExecutions,
  ApiError,
  verifyScenarioExecution,
} from '@/lib/api'
import type {
  Scenario,
  ScenarioDerivedFeature,
  ScenarioDerivedObservation,
  ScenarioExecutionCompareResponse,
  ScenarioExecutionRun,
  ScenarioExecutionVerifyResponse,
} from '@/lib/types'

function apiErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.details[0]
    const detailText = detail?.reason ? `${detail.field}: ${detail.reason}` : detail?.field
    return detailText ? `${err.message} (${detailText})` : err.message
  }
  return err instanceof Error ? err.message : 'Unexpected error'
}

function shortHash(hash: string | null | undefined): string {
  return hash ? `${hash.slice(0, 12)}…` : '—'
}

function shortIso(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

function fmt(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return '—'
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(digits)
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function RunStatusBadge({ status }: { status: string }) {
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

function EvidenceStatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    scenario_recalculated: { cls: 'border-sky-300 bg-sky-50 text-sky-800', label: 'scenario-derived' },
    not_affected: { cls: 'border-stone-300 bg-stone-100 text-stone-600', label: 'not affected' },
    not_evaluated: { cls: 'border-stone-400 bg-stone-100 text-stone-700', label: 'not evaluated' },
  }
  const entry = map[status] ?? { cls: '', label: status }
  return (
    <Badge variant="outline" className={`font-normal ${entry.cls}`}>
      {entry.label}
    </Badge>
  )
}

function ObsEvidenceBadge({ evidence, synthetic }: { evidence: string; synthetic: boolean }) {
  if (synthetic || evidence === 'synthetic_test') {
    return (
      <Badge variant="outline" className="border-fuchsia-300 bg-fuchsia-50 font-normal text-fuchsia-800">
        synthetic
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-amber-300 bg-amber-50 font-normal text-amber-800">
      <FlaskConical className="mr-1 h-3 w-3" aria-hidden />
      hypothetical
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Transformation preview (exact parameter disclosure before execution)
// ---------------------------------------------------------------------------

function TransformationPreview({ scenario }: { scenario: Scenario }) {
  const config = scenario.canonical_configuration as Record<string, unknown> | null
  const adjustments =
    (config?.adjustments as Record<string, number | null> | undefined) ?? {}
  const entries = useMemo(
    () =>
      Object.entries(adjustments).filter(([, v]) => v !== null && v !== undefined) as Array<
        [string, number]
      >,
    [adjustments],
  )
  if (entries.length === 0) return null
  const labels: Record<string, string> = {
    temperature_delta_c: 'Temperature',
    precipitation_multiplier: 'Precipitation',
    precipitation_delta_mm: 'Precipitation shift',
    water_allocation_multiplier: 'Irrigation allocation',
    seasonal_timing_shift_days: 'Seasonal timing shift',
    rainfall_period_shift_days: 'Rainfall period shift',
  }
  const fmtValue = (key: string, v: number) => {
    switch (key) {
      case 'temperature_delta_c':
        return `${v > 0 ? '+' : ''}${v} °C`
      case 'precipitation_multiplier':
        return `×${v}`
      case 'precipitation_delta_mm':
        return `${v > 0 ? '+' : ''}${v} mm`
      case 'water_allocation_multiplier':
        return `×${v}`
      default:
        return `${v > 0 ? '+' : ''}${v} days`
    }
  }
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
      <p className="text-xs font-medium text-amber-900">
        <FlaskConical className="mr-1 inline h-3.5 w-3.5" aria-hidden />
        Hypothetical assumptions to apply (never observed data)
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-amber-900">
        {entries.map(([key, value]) => (
          <li key={key} className="font-mono">
            {labels[key] ?? key}: <strong>{fmtValue(key, value)}</strong>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Comparison table (baseline vs scenario, definition-safe)
// ---------------------------------------------------------------------------

function ComparisonTable({ rows }: { rows: ScenarioDerivedFeature[] }) {
  const [filter, setFilter] = useState<'all' | 'scenario_recalculated' | 'not_evaluated' | 'not_affected'>('all')
  const filtered = useMemo(
    () => (filter === 'all' ? rows : rows.filter((r) => r.evidence_status === filter)),
    [rows, filter],
  )
  const filters: Array<{ key: typeof filter; label: string }> = [
    { key: 'all', label: `All (${rows.length})` },
    {
      key: 'scenario_recalculated',
      label: `Scenario-derived (${rows.filter((r) => r.evidence_status === 'scenario_recalculated').length})`,
    },
    {
      key: 'not_evaluated',
      label: `Not evaluated (${rows.filter((r) => r.evidence_status === 'not_evaluated').length})`,
    },
    {
      key: 'not_affected',
      label: `Not affected (${rows.filter((r) => r.evidence_status === 'not_affected').length})`,
    },
  ]
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {filters.map((f) => (
          <Button
            key={f.key}
            size="sm"
            variant={filter === f.key ? 'default' : 'outline'}
            className="min-h-8 px-2.5 text-xs"
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </Button>
        ))}
      </div>
      <div className="max-h-96 overflow-auto rounded-md border border-stone-200">
        <Table>
          <TableHeader className="sticky top-0 bg-white">
            <TableRow>
              <TableHead className="min-w-52">Feature</TableHead>
              <TableHead>Level / period</TableHead>
              <TableHead className="text-right">Baseline</TableHead>
              <TableHead className="text-right">Scenario</TableHead>
              <TableHead className="text-right">Δ</TableHead>
              <TableHead className="text-right">Δ %</TableHead>
              <TableHead>Evidence</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((r) => (
              <TableRow key={r.id} className={r.evidence_status !== 'scenario_recalculated' ? 'bg-stone-50/60' : ''}>
                <TableCell className="text-xs">
                  <span className="font-medium text-stone-800">{r.feature_name || r.feature_code}</span>
                  <span className="block font-mono text-[10px] text-stone-400">{r.feature_code}</span>
                  {r.uncertainty_metadata?.reason && (
                    <span className="mt-0.5 block max-w-72 text-[10px] leading-snug text-stone-500">
                      {r.uncertainty_metadata.reason}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-stone-600">
                  {r.aggregation_level}
                  <span className="block text-[10px] text-stone-400">{r.period_label}</span>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.evidence_status === 'scenario_recalculated' ? fmt(r.baseline_value) : '—'}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.evidence_status === 'scenario_recalculated' ? fmt(r.scenario_value) : '—'}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.difference_value === null ? '—' : fmt(r.difference_value)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.difference_percent === null ? '—' : `${fmt(r.difference_percent, 2)}%`}
                </TableCell>
                <TableCell>
                  <EvidenceStatusBadge status={r.evidence_status} />
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-6 text-center text-xs text-stone-500">
                  No rows for this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <p className="mt-1.5 text-[11px] text-stone-500">
        Δ% is shown only when the baseline is non-zero and the comparison is valid. Scenario values are
        hypothetical — never observations.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Evidence explorer (transformed observations)
// ---------------------------------------------------------------------------

function EvidenceExplorer({ runId }: { runId: string }) {
  const [observations, setObservations] = useState<ScenarioDerivedObservation[] | null>(null)
  const [total, setTotal] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listExecutionObservations(runId, { limit: 100 })
      setObservations(data.items)
      setTotal(data.total_transformed)
    } catch (err) {
      setError(apiErrorText(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-md border border-stone-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-stone-700">
          Evidence explorer — transformed observations{' '}
          {total !== null && <span className="font-normal text-stone-500">({total} total, first 100)</span>}
        </p>
        {observations === null ? (
          <Button size="sm" variant="outline" className="min-h-8 text-xs" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden /> : null}
            Load evidence
          </Button>
        ) : null}
      </div>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
      {observations && (
        <div className="mt-2 max-h-80 overflow-auto rounded border border-stone-100">
          <Table>
            <TableHeader className="sticky top-0 bg-white">
              <TableRow>
                <TableHead>Variable</TableHead>
                <TableHead className="text-right">Baseline</TableHead>
                <TableHead className="text-right">Transformed</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>Transformation</TableHead>
                <TableHead>Period</TableHead>
                <TableHead>Evidence</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {observations.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-mono text-[11px]">{o.variable_code}</TableCell>
                  <TableCell className="text-right font-mono text-[11px]">{fmt(o.baseline_value)}</TableCell>
                  <TableCell className="text-right font-mono text-[11px]">{fmt(o.transformed_value)}</TableCell>
                  <TableCell className="text-[11px]">{o.unit}</TableCell>
                  <TableCell className="font-mono text-[10px] text-stone-500">
                    {o.transformation_code} {JSON.stringify(o.transformation_parameter)}
                  </TableCell>
                  <TableCell className="text-[10px] text-stone-500">{shortIso(o.period_start)}</TableCell>
                  <TableCell>
                    <ObsEvidenceBadge evidence={o.evidence_class} synthetic={o.is_synthetic} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// One execution run row + expandable detail
// ---------------------------------------------------------------------------

function RunDetail({ run }: { run: ScenarioExecutionRun }) {
  const [comparison, setComparison] = useState<ScenarioExecutionCompareResponse | null>(null)
  const [verify, setVerify] = useState<ScenarioExecutionVerifyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const runAction = async (key: string, fn: () => Promise<void>) => {
    setBusy(key)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(apiErrorText(err))
    } finally {
      setBusy(null)
    }
  }

  const isResult = run.run_status === 'succeeded' || run.run_status === 'completed_with_limitations'

  return (
    <div className="mt-3 space-y-3 rounded-md border border-stone-200 bg-stone-50/60 p-3">
      {run.run_status === 'failed' && run.error_summary && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" aria-hidden />
          <AlertTitle>Execution failed</AlertTitle>
          <AlertDescription className="break-all">{run.error_summary}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-x-4 gap-y-1 text-xs text-stone-600 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <span className="text-stone-400">Output checksum: </span>
          <span className="break-all font-mono" title={run.output_checksum ?? ''}>
            {shortHash(run.output_checksum)}
          </span>
        </div>
        <div>
          <span className="text-stone-400">Input fingerprint: </span>
          <span className="break-all font-mono">{shortHash(run.input_fingerprint)}</span>
        </div>
        <div>
          <span className="text-stone-400">Engines: </span>
          {run.transformation_engine_version} · {run.feature_engine_version}
        </div>
        <div>
          <span className="text-stone-400">Feature spec: </span>
          {run.feature_catalog_version}
        </div>
        <div>
          <span className="text-stone-400">Window: </span>
          {shortIso(run.execution_configuration.period_start)} →{' '}
          {shortIso(run.execution_configuration.period_end)} ({run.calendar_timezone})
        </div>
        <div>
          <span className="text-stone-400">Parent snapshot: </span>
          <span className="break-all font-mono">{shortHash(run.parent_snapshot_checksum)}</span>
        </div>
      </div>

      {run.warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2.5">
          <p className="text-xs font-medium text-amber-900">Limitations &amp; disclosures</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-amber-900">
            {run.warnings.map((w, i) => (
              <li key={i} className="[overflow-wrap:anywhere]">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(run.not_evaluated_reasons).length > 0 && (
        <details className="rounded-md border border-stone-200 bg-white p-2.5">
          <summary className="cursor-pointer text-xs font-medium text-stone-700">
            Not evaluated ({Object.keys(run.not_evaluated_reasons).length}) — with reasons
          </summary>
          <ul className="mt-1.5 space-y-1 text-[11px] text-stone-600">
            {Object.entries(run.not_evaluated_reasons).map(([code, reason]) => (
              <li key={code} className="[overflow-wrap:anywhere]">
                <span className="font-mono text-stone-500">{code}</span> — {reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {error && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          className="min-h-8 text-xs"
          disabled={!isResult || busy !== null}
          onClick={() =>
            runAction('compare', async () => {
              const data = await compareScenarioExecution(run.run_id)
              setComparison(data)
            })
          }
        >
          Baseline vs scenario
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="min-h-8 text-xs"
          disabled={!isResult || busy !== null}
          onClick={() =>
            runAction('verify', async () => {
              const data = await verifyScenarioExecution(run.run_id)
              setVerify(data)
            })
          }
        >
          Verify checksums
        </Button>
      </div>

      {verify && (
        <div className="rounded-md border border-stone-200 bg-white p-2.5 text-xs">
          <p className="flex items-center gap-1.5 font-medium text-stone-700">
            {verify.output_checksum_valid ? (
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
            ) : (
              <ShieldAlert className="h-3.5 w-3.5 text-red-700" aria-hidden />
            )}
            Output checksum valid: {String(verify.output_checksum_valid)} · definition checksum valid:{' '}
            {String(verify.scenario_definition_checksum_valid)} · parent intact:{' '}
            {String(verify.parent_snapshot_intact)} · manifest pinned:{' '}
            {String(verify.manifest_checksum_matches_run)}
          </p>
          <p className="mt-1 text-[11px] text-stone-500">{verify.note}</p>
        </div>
      )}

      {comparison && (
        <div className="space-y-3">
          <p className="text-[11px] text-stone-500">{comparison.note}</p>
          <ComparisonTable rows={comparison.rows} />
          <EvidenceExplorer runId={run.run_id} />
        </div>
      )}
    </div>
  )
}

function ExecutionRunRow({ run }: { run: ScenarioExecutionRun }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-md border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          className="flex min-w-48 flex-1 items-center gap-2 text-left"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? (
            <ChevronUp className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
          )}
          <span className="min-w-0 flex-1">
            <span className="block break-all font-mono text-[11px] text-stone-500">
              {run.run_id}
            </span>
            <span className="text-xs text-stone-600">
              {shortIso(run.completed_at || run.started_at)} · {run.transformed_observation_count} transformed obs
              · {run.derived_feature_count} feature rows
            </span>
          </span>
        </button>
        <RunStatusBadge status={run.run_status} />
      </div>
      {open && <RunDetail run={run} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main section (per finalized scenario)
// ---------------------------------------------------------------------------

const EXECUTABLE_TYPES = new Set(['user_defined_stress', 'historical_perturbation'])

export function ScenarioExecutionSection({ scenario }: { scenario: Scenario }) {
  const [runs, setRuns] = useState<ScenarioExecutionRun[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isExecutable =
    scenario.scenario_status === 'finalized' && EXECUTABLE_TYPES.has(scenario.scenario_type)

  const loadRuns = async () => {
    setError(null)
    try {
      const data = await listScenarioExecutions(scenario.id)
      setRuns(data.items)
    } catch (err) {
      setError(apiErrorText(err))
    }
  }

  const execute = async () => {
    setBusy(true)
    setError(null)
    try {
      await executeScenario(scenario.id, {})
      const data = await listScenarioExecutions(scenario.id)
      setRuns(data.items)
    } catch (err) {
      setError(apiErrorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 space-y-2.5 rounded-md border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-stone-800">Execute scenario (M7.3)</p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="min-h-8 text-xs"
            onClick={loadRuns}
            disabled={busy}
          >
            Refresh executions
          </Button>
          <Button
            size="sm"
            className="min-h-8 text-xs"
            disabled={!isExecutable || busy}
            onClick={execute}
            title={
              isExecutable
                ? 'Execute the configured transformations against the parent Field State'
                : 'Only finalized stress/perturbation scenarios can execute'
            }
          >
            {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden /> : <Play className="mr-1 h-3 w-3" aria-hidden />}
            Execute
          </Button>
        </div>
      </div>

      <TransformationPreview scenario={scenario} />

      <Alert className="border-stone-200 bg-stone-50">
        <Info className="h-4 w-4 text-stone-500" aria-hidden />
        <AlertDescription className="text-[11px] leading-snug text-stone-600">
          Execution applies the hypothetical transformations to the parent Field State&apos;s pinned
          observations and recomputes affected environmental features. It is a{' '}
          <strong>derived hypothetical calculation</strong> — results never enter the observation
          record, parent artifacts stay immutable, and ET0-related features are never reused as
          scenario outputs.
        </AlertDescription>
      </Alert>

      {error && (
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {runs !== null && runs.length === 0 && (
        <p className="text-xs text-stone-500">No executions yet for this scenario.</p>
      )}
      {runs !== null && runs.length > 0 && (
        <div className="space-y-2">
          {runs.map((r) => (
            <ExecutionRunRow key={r.run_id} run={r} />
          ))}
        </div>
      )}
    </div>
  )
}

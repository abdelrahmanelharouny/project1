'use client'

/**
 * Robust Multi-Scenario Rotation workspace (M7.5).
 *
 * Evaluates ONE shared crop-rotation plan across multiple compatible M7.3
 * scenario executions. Honesty rules rendered here (M7.5 method §2/§5):
 *
 * - The shared plan is optimized ONCE over the cross-scenario admissible
 *   candidate pool — never per-scenario plans relabelled as robust.
 * - The worst-case objective is labelled "worst-case across selected
 *   scenarios" — a deterministic minimum, NOT a confidence interval and NOT
 *   a probability statement.
 * - Regret is a deterministic objective gap vs each scenario's solo optimum
 *   — never an expected value (no probabilities anywhere).
 * - Scenario ET0 / water feasibility are structurally unavailable; water
 *   criteria render as not evaluable, and water allocations are rejected.
 * - FEASIBLE is never shown as OPTIMAL.
 * - A plan is "robust" only across the explicitly selected scenarios and
 *   evaluated constraints — the label says so.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
  ApiError,
  createRobustRun,
  createScenarioSet,
  getRobustRun,
  listRobustEvaluations,
  listRobustRuns,
  listScenarioExecutions,
  listScenarioSets,
  listScenarios,
  verifyRobustRun,
  verifyScenarioSet,
} from '@/lib/api'
import type {
  RobustRotationRun,
  RobustScenarioEvaluation,
  Scenario,
  ScenarioExecutionRun,
  ScenarioSet,
} from '@/lib/types'
import { useFieldShiftUi } from '@/lib/store'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  Play,
  ShieldCheck,
  XCircle,
} from 'lucide-react'

// Season presets are typed by the user; the robust run validates month
// coverage against the selected executions and rejects uncovered seasons.
const SEASON_PRESETS = [
  { label: 'summer_2023', start_date: '2023-05-01', end_date: '2023-09-15' },
  { label: 'winter_2023', start_date: '2023-11-15', end_date: '2024-03-20' },
  { label: 'summer_2016', start_date: '2016-05-01', end_date: '2016-09-15' },
  { label: 'winter_2016', start_date: '2016-11-15', end_date: '2017-03-20' },
]

function FeasibilityBadge({ state }: { state: string }) {
  if (state === 'robust_feasible') {
    return (
      <Badge className="gap-1 border-emerald-200 bg-emerald-50 text-emerald-800">
        <CheckCircle2 className="h-3 w-3" aria-hidden />
        robust feasible
      </Badge>
    )
  }
  if (state === 'robust_infeasible') {
    return (
      <Badge className="gap-1 border-red-200 bg-red-50 text-red-800">
        <XCircle className="h-3 w-3" aria-hidden />
        infeasible in a scenario
      </Badge>
    )
  }
  return (
    <Badge className="gap-1 border-stone-300 bg-stone-50 text-stone-600">
      <AlertTriangle className="h-3 w-3" aria-hidden />
      not evaluable
    </Badge>
  )
}

function SolverBadge({ status }: { status: string | null }) {
  if (!status) return <Badge variant="outline">not attempted</Badge>
  if (status === 'optimal') {
    return (
      <Badge variant="outline" className="border-emerald-200 bg-white text-emerald-800">
        OPTIMAL (proven)
      </Badge>
    )
  }
  if (status === 'feasible') {
    return (
      <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-900">
        FEASIBLE (not proven optimal)
      </Badge>
    )
  }
  return <Badge variant="outline">{status}</Badge>
}

export default function RobustPlan() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const fieldId = selectedField?.id ?? null

  const sets = useQuery({
    queryKey: ['scenario-sets', fieldId],
    queryFn: () => listScenarioSets(fieldId as string),
    enabled: !!fieldId,
  })

  if (!fieldId) {
    return (
      <div className="space-y-4">
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            Select a field to build robust multi-scenario rotation plans.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <RobustPlanInner
      fieldId={fieldId}
      sets={{
        isLoading: sets.isLoading,
        data: sets.data ?? { items: [], count: 0, note: '' },
      }}
    />
  )
}

type ScenarioSetListData = { items: ScenarioSet[]; count: number; note: string }

function RobustPlanInner({
  fieldId,
  sets,
}: {
  fieldId: string
  sets: { isLoading: boolean; data: ScenarioSetListData }
}) {
  const queryClient = useQueryClient()
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null)
  const [builderOpen, setBuilderOpen] = useState(false)
  const [setLabel, setSetLabel] = useState('')
  const [memberChoices, setMemberChoices] = useState<Record<string, boolean>>({})
  const [seasonPreset, setSeasonPreset] = useState<string>(SEASON_PRESETS[0].label)
  const [seasonLabel, setSeasonLabel] = useState('')
  const [openRunId, setOpenRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const scenarios = useQuery({
    queryKey: ['scenarios', fieldId],
    queryFn: () => listScenarios(fieldId as string),
    enabled: !!fieldId && builderOpen,
  })

  const executionsByScenario = useQuery({
    queryKey: ['executions-for-sets', fieldId],
    queryFn: async () => {
      const list = (scenarios.data?.items ?? []) as Scenario[]
      const out: Record<string, ScenarioExecutionRun[]> = {}
      for (const s of list) {
        try {
          const resp = await listScenarioExecutions(s.id, 'succeeded')
          const limited = await listScenarioExecutions(s.id, 'completed_with_limitations')
          out[s.id] = [...(resp.items ?? []), ...(limited.items ?? [])]
        } catch {
          out[s.id] = []
        }
      }
      return out
    },
    enabled: !!fieldId && builderOpen && scenarios.isSuccess,
  })

  const selectedSet = useMemo(
    () => sets.data?.items.find((s) => s.id === selectedSetId) ?? null,
    [sets.data, selectedSetId],
  )

  const runs = useQuery({
    queryKey: ['robust-runs', selectedSetId],
    queryFn: () => listRobustRuns(selectedSetId as string),
    enabled: !!selectedSetId,
  })

  const createSet = useMutation({
    mutationFn: () =>
      createScenarioSet(fieldId as string, {
        label: setLabel,
        execution_run_ids: Object.entries(memberChoices)
          .filter(([, v]) => v)
          .map(([k]) => k),
      }),
    onSuccess: () => {
      setError(null)
      setBuilderOpen(false)
      setSetLabel('')
      setMemberChoices({})
      queryClient.invalidateQueries({ queryKey: ['scenario-sets'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to create scenario set'),
  })

  const startRun = useMutation({
    mutationFn: (setId: string) =>
      createRobustRun(setId, {
        seasons: [SEASON_PRESETS.find((s) => s.label === seasonPreset) ?? SEASON_PRESETS[0]],
        hemisphere: 'north',
        regret_analysis: true,
      }),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['robust-runs'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to start robust run'),
  })

  if (!fieldId) {
    return (
      <div className="space-y-4">
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            Select a field to build robust multi-scenario rotation plans.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header />

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>Request failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div className="min-w-0">
            <CardTitle className="text-base">Scenario sets</CardTitle>
            <CardDescription className="mt-1">
              Compatible M7.3 executions (same field, same parent Field State, distinct
              scenarios) — the environments one shared plan must hold up across.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => setBuilderOpen((v) => !v)}>
            <Layers className="mr-1 h-4 w-4" aria-hidden />
            {builderOpen ? 'Close builder' : 'New set'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {builderOpen && (
            <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="set-label">Set label</Label>
                  <Input
                    id="set-label"
                    value={setLabel}
                    onChange={(e) => setSetLabel(e.target.value)}
                    placeholder="e.g. Hot & dry vs Cool & wet"
                  />
                </div>
              </div>
              <div className="mt-3 max-h-64 space-y-1.5 overflow-y-auto pr-1">
                {(scenarios.data?.items ?? []).length === 0 && (
                  <p className="text-xs text-stone-500">
                    No scenarios on this field yet — create and execute scenarios first.
                  </p>
                )}
                {(scenarios.data?.items ?? []).map((s) => {
                  const execs = executionsByScenario.data?.[s.id] ?? []
                  return execs.map((run) => (
                    <label
                      key={run.run_id}
                      className="flex cursor-pointer items-center gap-2 rounded-md border border-stone-200 bg-white px-3 py-2 text-xs"
                    >
                      <Checkbox
                        checked={!!memberChoices[run.run_id]}
                        onCheckedChange={(v) =>
                          setMemberChoices((prev) => ({ ...prev, [run.run_id]: v === true }))
                        }
                        aria-label={`Select execution of ${s.name}`}
                      />
                      <span className="min-w-0 flex-1 truncate font-medium text-stone-800">
                        {s.name}
                      </span>
                      <span className="shrink-0 font-mono text-stone-500">
                        {run.run_id.slice(0, 8)}
                      </span>
                      <span className="shrink-0 text-stone-500">{run.run_status}</span>
                    </label>
                  ))
                })}
              </div>
              <div className="mt-3 flex items-center justify-end gap-2">
                <Button
                  size="sm"
                  onClick={() => createSet.mutate()}
                  disabled={!setLabel.trim() || Object.values(memberChoices).every((v) => !v) || createSet.isPending}
                >
                  {createSet.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />}
                  Create set
                </Button>
              </div>
            </div>
          )}

          {sets.isLoading && <Skeleton className="h-16 w-full" />}
          {sets.data && sets.data.items.length === 0 && (
            <p className="text-xs text-stone-500">No scenario sets yet.</p>
          )}
          <div className="grid gap-2">
            {(sets.data?.items ?? []).map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSelectedSetId(s.id === selectedSetId ? null : s.id)}
                className={`rounded-lg border p-3 text-left transition ${
                  selectedSetId === s.id ? 'border-emerald-300 bg-emerald-50/50' : 'border-stone-200 bg-white hover:border-stone-300'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-stone-800">{s.label}</span>
                  <Badge variant="outline" className="font-normal">
                    {s.member_count} execution{s.member_count === 1 ? '' : 's'}
                  </Badge>
                </div>
                <p className="mt-1 truncate text-xs text-stone-500">
                  checksum {s.set_checksum.slice(0, 12)}… · parent state pinned by value
                </p>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {selectedSet && (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0">
            <div className="min-w-0">
              <CardTitle className="text-base">Robust runs — {selectedSet.label}</CardTitle>
              <CardDescription className="mt-1">
                One shared plan per strategy profile; worst-case objective = minimum
                across the selected scenarios (deterministic — no confidence interval).
              </CardDescription>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <select
                value={seasonPreset}
                onChange={(e) => setSeasonPreset(e.target.value)}
                aria-label="Planning season"
                className="h-9 rounded-md border border-stone-300 bg-white px-2 text-xs"
              >
                {SEASON_PRESETS.map((s) => (
                  <option key={s.label} value={s.label}>
                    {s.label} ({s.start_date} → {s.end_date})
                  </option>
                ))}
              </select>
              <Button size="sm" onClick={() => startRun.mutate(selectedSet.id)} disabled={startRun.isPending}>
                {startRun.isPending ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Play className="mr-1 h-4 w-4" aria-hidden />
                )}
                Run robust plan
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {runs.isLoading && <Skeleton className="h-16 w-full" />}
            {runs.data && runs.data.items.length === 0 && (
              <p className="text-xs text-stone-500">No robust runs yet.</p>
            )}
            {(runs.data?.items ?? []).map((run) => (
              <RobustRunCard
                key={run.id}
                run={run}
                open={openRunId === run.id}
                onToggle={() => setOpenRunId(openRunId === run.id ? null : run.id)}
              />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Header() {
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-900">
        <ShieldCheck className="h-5 w-5 text-emerald-700" aria-hidden />
        Robust Rotation (multi-scenario)
      </h2>
      <p className="mt-1 text-sm text-stone-600">
        One shared crop-rotation plan evaluated across selected scenario executions.
        Scenario ET0 and water feasibility remain unavailable; unevaluated constraints
        are never treated as satisfied.
      </p>
    </div>
  )
}

function RobustRunCard({
  run,
  open,
  onToggle,
}: {
  run: RobustRotationRun
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center justify-between gap-2 p-3 text-left"
        aria-expanded={open}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {open ? (
            <ChevronUp className="h-4 w-4 text-stone-400" aria-hidden />
          ) : (
            <ChevronDown className="h-4 w-4 text-stone-400" aria-hidden />
          )}
          <span className="font-mono text-xs text-stone-700">{run.id.slice(0, 8)}</span>
          <Badge
            variant="outline"
            className={
              run.run_status === 'succeeded'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : run.run_status === 'failed'
                  ? 'border-red-200 bg-red-50 text-red-800'
                  : 'border-amber-200 bg-amber-50 text-amber-900'
            }
          >
            {run.run_status}
          </Badge>
          <SolverBadge status={run.solver_status} />
          <span className="text-xs text-stone-500">
            {run.member_count} scenarios · {run.seasons.map((s) => s.label).join(', ')}
          </span>
        </div>
        <span className="shrink-0 text-xs text-stone-500">
          {run.output_checksum ? `out ${run.output_checksum.slice(0, 10)}…` : '—'}
        </span>
      </button>
      {open && (
        <RobustRunDetail run={run} />
      )}
    </div>
  )
}

function RobustRunDetail({ run }: { run: RobustRotationRun }) {
  const evaluations = useQuery({
    queryKey: ['robust-evals', run.id],
    queryFn: () => listRobustEvaluations(run.id),
  })
  // the list payload is lean; the shared-plan table comes from the detail
  const detail = useQuery({
    queryKey: ['robust-run', run.id],
    queryFn: () => getRobustRun(run.id),
  })
  const strategies = detail.data?.strategies ?? run.strategies ?? []
  const verify = useMutation({ mutationFn: () => verifyRobustRun(run.id) })

  return (
    <div className="space-y-3 border-t border-stone-100 p-3">
      {run.warnings.length > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>Limitations and disclosures</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4">
              {run.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {Object.keys(run.not_evaluated ?? {}).length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900">
          <p className="font-semibold">Not evaluated (never treated as satisfied)</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {Object.entries(run.not_evaluated).flatMap(([group, entries]) =>
              Object.entries(entries ?? {}).map(([k, v]) => (
                <li key={`${group}-${k}`}>
                  <span className="font-mono">{group}/{k}</span>: {v}
                </li>
              )),
            )}
          </ul>
        </div>
      )}

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Shared plan</TableHead>
              <TableHead>Assignment</TableHead>
              <TableHead>Worst case (min across scenarios)</TableHead>
              <TableHead>Worst regret</TableHead>
              <TableHead>Robust feasibility</TableHead>
              <TableHead>Solver</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {strategies.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">
                  {s.strategy_key}
                  {s.is_baseline && (
                    <Badge variant="outline" className="ml-2 font-normal">
                      current rotation
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-xs text-stone-600">
                  {s.assignment.map((a) => `${a.season_label}: ${a.crop_code ?? '—'}`).join(' · ')}
                </TableCell>
                <TableCell>
                  {s.worst_case_objective ?? (
                    <span className="text-stone-400">not evaluable in every scenario</span>
                  )}
                </TableCell>
                <TableCell>
                  {s.worst_case_regret ?? <span className="text-stone-400">—</span>}
                </TableCell>
                <TableCell>
                  <FeasibilityBadge state={s.robust_feasibility} />
                </TableCell>
                <TableCell>
                  <SolverBadge status={s.solver_status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {run.infeasibility_details?.cross_scenario_exclusions &&
        run.infeasibility_details.cross_scenario_exclusions.length > 0 && (
          <div className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs">
            <p className="font-semibold text-stone-700">
              Crops excluded from the shared pool by at least one scenario
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-stone-600">
              {run.infeasibility_details.cross_scenario_exclusions.map((e, i) => (
                <li key={i}>
                  <span className="font-medium">{e.crop_code}</span> in {e.season_label} —{' '}
                  {e.excluded_by_scenarios[0]?.reason}
                </li>
              ))}
            </ul>
          </div>
        )}

      {evaluations.data && evaluations.data.items.length > 0 && (
        <details className="rounded-lg border border-stone-200 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-stone-700">
            Per-scenario evaluations ({evaluations.data.items.length})
          </summary>
          <div className="mt-2 max-h-96 space-y-2 overflow-y-auto pr-1">
            {evaluations.data.items.map((e: RobustScenarioEvaluation) => (
              <div key={e.id} className="rounded-md border border-stone-100 bg-stone-50/60 p-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-stone-500">scenario {e.scenario_id.slice(0, 8)}</span>
                  <span>objective: {e.weighted_objective ?? 'not evaluable'}</span>
                  {e.on_scenario_pareto_front && (
                    <Badge variant="outline" className="font-normal">
                      scenario Pareto front
                    </Badge>
                  )}
                  {e.regret_vs_solo !== null && (
                    <Badge variant="outline" className="font-normal">
                      regret vs solo optimum: {e.regret_vs_solo}
                    </Badge>
                  )}
                </div>
                {Object.entries(e.climate_evidence).map(([label, ev]) => (
                  <p key={label} className="mt-1 text-stone-500">
                    {label}: precip {ev.season_precipitation_mm ?? '—'} mm · tmean{' '}
                    {ev.season_mean_temp_degC ?? '—'} °C · ET0{' '}
                    {ev.season_et0_mm ?? 'not evaluable (scenario)'}
                  </p>
                ))}
                {e.crop_admissibility.some((a) => !a.admissible) && (
                  <p className="mt-1 text-red-700">
                    inadmissible here:{' '}
                    {e.crop_admissibility
                      .filter((a) => !a.admissible)
                      .map((a) => `${a.crop_code} (${a.hard_reason ?? a.status})`)
                      .join('; ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />}
          Verify checksums & pins
        </Button>
        {verify.data && (
          <Badge
            variant="outline"
            className={
              verify.data.verified
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-red-200 bg-red-50 text-red-800'
            }
          >
            {verify.data.verified ? 'verified' : `${verify.data.findings.length} finding(s)`}
          </Badge>
        )}
      </div>
    </div>
  )
}

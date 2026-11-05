'use client'

/**
 * Field Digital Twin (M7.7).
 *
 * A traceable field-level representation connecting Field States, observed
 * data, derived features, scenarios, executions, sensitivity analyses,
 * robust rotation runs and decision documents. Honesty rules:
 * - Every section links to artifact ids and checksums (verification is one
 *   click away) — this is not a decorative dashboard.
 * - Observed / transformed / calculated information classes are always
 *   distinguished.
 * - Maturity is classified from implemented capabilities and actual data
 *   presence only; no predictive, autonomous or forecasting claims.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { ApiError, getDigitalTwin, listTwinValidations, validateDigitalTwin } from '@/lib/api'
import type { DigitalTwinView, TwinValidationResponse } from '@/lib/types'
import { useFieldShiftUi } from '@/lib/store'
import { AlertTriangle, CheckCircle2, Loader2, Network, ShieldCheck } from 'lucide-react'

export default function DigitalTwin() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const fieldId = selectedField?.id ?? null
  const queryClient = useQueryClient()

  const twin = useQuery({
    queryKey: ['digital-twin', fieldId],
    queryFn: () => getDigitalTwin(fieldId as string),
    enabled: !!fieldId,
  })
  const validations = useQuery({
    queryKey: ['twin-validations', fieldId],
    queryFn: () => listTwinValidations(fieldId as string),
    enabled: !!fieldId,
  })
  const validate = useMutation({
    mutationFn: () => validateDigitalTwin(fieldId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['twin-validations'] })
    },
  })

  if (!fieldId) {
    return (
      <div className="space-y-4">
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            Select a field to inspect its digital twin.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header />

      {validate.isError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>Validation failed</AlertTitle>
          <AlertDescription>
            {validate.error instanceof ApiError ? validate.error.message : 'Unexpected error'}
          </AlertDescription>
        </Alert>
      )}

      {twin.isLoading && <Skeleton className="h-48 w-full" />}

      {twin.data && <TwinView twin={twin.data as DigitalTwinView} />}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div className="min-w-0">
            <CardTitle className="text-base">Integrity validation</CardTitle>
            <CardDescription>
              Bounded re-verification walk over the newest artifacts — checksums, parent
              pins and lineage consistency.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => validate.mutate()} disabled={validate.isPending}>
            {validate.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <ShieldCheck className="mr-1 h-4 w-4" aria-hidden />
            )}
            Validate now
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {validate.data && <ValidationResult result={validate.data as TwinValidationResponse} />}
          {validations.data && validations.data.items.length > 0 && (
            <div className="max-h-64 overflow-y-auto rounded-lg border border-stone-200">
              <Table>
                <TableHeader className="sticky top-0 bg-white">
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Checked</TableHead>
                    <TableHead>Failed</TableHead>
                    <TableHead>Report</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {validations.data.items.map((v) => (
                    <TableRow key={v.id}>
                      <TableCell className="text-xs">
                        {v.completed_at ? new Date(v.completed_at).toLocaleString() : '—'}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            v.overall_status === 'consistent'
                              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                              : v.overall_status === 'inconsistent'
                                ? 'border-red-200 bg-red-50 text-red-800'
                                : 'border-stone-300 bg-stone-50 text-stone-600'
                          }
                        >
                          {v.overall_status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">{v.artifacts_checked}</TableCell>
                      <TableCell className="text-xs">{v.artifacts_failed}</TableCell>
                      <TableCell className="font-mono text-xs">{v.report_checksum.slice(0, 10)}…</TableCell>
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

function Header() {
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-900">
        <Network className="h-5 w-5 text-emerald-700" aria-hidden />
        Field Digital Twin
      </h2>
      <p className="mt-1 text-sm text-stone-600">
        Field identity, immutable snapshots, observed and derived data, scenario lineage,
        analytical results and decisions — traceably connected. No predictive or
        autonomous capability is claimed.
      </p>
    </div>
  )
}

function TwinView({ twin }: { twin: DigitalTwinView }) {
  const ic = twin.information_classes
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Field" value={twin.field_identity.field_name} sub={`${twin.field_identity.area_ha ?? '—'} ha · v${twin.field_identity.latest_boundary_version ?? '—'} boundary`} />
        <StatCard label="Field States" value={String(twin.field_states.total)} sub="immutable snapshots" />
        <StatCard
          label="Observed / Transformed / Calculated"
          value={`${ic.observed_observations} / ${ic.scenario_derived_transformed_observations} / ${ic.calculated_feature_values}`}
          sub="information classes"
        />
        <StatCard label="Maturity" value={twin.maturity.classification} sub="honest classification" wide />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Data coverage & freshness</CardTitle>
          <CardDescription>{twin.observation_coverage.note}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Variable</TableHead>
                  <TableHead>Observations</TableHead>
                  <TableHead>First</TableHead>
                  <TableHead>Last</TableHead>
                  <TableHead>Age (days)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {twin.observation_coverage.variables.map((v) => (
                  <TableRow key={v.variable_code}>
                    <TableCell className="font-mono text-xs">{v.variable_code}</TableCell>
                    <TableCell className="text-xs">{v.observation_count}</TableCell>
                    <TableCell className="text-xs">{v.first_observed_at?.slice(0, 10) ?? '—'}</TableCell>
                    <TableCell className="text-xs">{v.last_observed_at?.slice(0, 10) ?? '—'}</TableCell>
                    <TableCell className="text-xs">{v.freshness_days ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Scenario & analytical lineage</CardTitle>
          <CardDescription>
            Scenarios → executions → sensitivity → robust runs → decision documents, with
            checksums at every link.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {twin.scenarios.length === 0 && (
            <p className="text-xs text-stone-500">No scenarios on this field yet.</p>
          )}
          {twin.scenarios.map((s) => (
            <div key={s.scenario_id} className="rounded-lg border border-stone-200 p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-stone-800">{s.name}</span>
                <Badge variant="outline" className="font-normal">
                  v{s.scenario_version} {s.scenario_status}
                </Badge>
                <Badge variant="outline" className="font-normal">
                  {s.evidence_classification}
                </Badge>
                <span className="font-mono text-stone-400">{s.configuration_checksum.slice(0, 10)}…</span>
              </div>
              {s.executions.map((e) => (
                <p key={e.execution_run_id} className="mt-1 text-stone-500">
                  execution {e.execution_run_id.slice(0, 8)} · {e.run_status} ·{' '}
                  {e.output_checksum ? `out ${e.output_checksum.slice(0, 10)}…` : '—'}
                </p>
              ))}
            </div>
          ))}
          {twin.robust_rotation.scenario_sets.map((s) => (
            <div key={s.scenario_set_id} className="rounded-lg border border-stone-200 p-3 text-xs">
              <span className="font-medium text-stone-800">{s.label}</span>
              <span className="ml-2 text-stone-500">({s.member_count} scenarios)</span>
              {s.robust_runs.map((r) => (
                <p key={r.robust_run_id} className="mt-1 text-stone-500">
                  robust run {r.robust_run_id.slice(0, 8)} · {r.run_status} · solver {r.solver_status ?? '—'}
                </p>
              ))}
            </div>
          ))}
          {twin.decision_documents.map((d) => (
            <p key={d.decision_comparison_id} className="text-xs text-stone-500">
              decision document “{d.title}” · {d.doc_status} ·{' '}
              {d.document_checksum.slice(0, 10)}…
            </p>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Capabilities & readiness</CardTitle>
          <CardDescription>{twin.maturity.note}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2">
            {twin.capabilities.map((c) => (
              <div key={c.capability} className="flex items-center justify-between rounded-md border border-stone-200 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <p className="truncate font-medium text-stone-800">{c.capability}</p>
                  <p className="text-stone-500">
                    {c.milestone}
                    {c.prerequisite && c.readiness === 'prerequisite_missing' ? ` · ${c.prerequisite}` : ''}
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className={
                    c.readiness === 'ready'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                      : c.readiness === 'prerequisite_missing'
                        ? 'border-amber-200 bg-amber-50 text-amber-900'
                        : 'border-stone-300 bg-stone-50 text-stone-500'
                  }
                >
                  {c.readiness}
                </Badge>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-stone-600">
            <p className="font-semibold text-stone-700">Not implemented (honest gap list)</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {twin.maturity.not_implemented.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ValidationResult({ result }: { result: TwinValidationResponse }) {
  return (
    <Alert>
      <CheckCircle2 className="h-4 w-4" aria-hidden />
      <AlertTitle>
        {result.overall_status === 'consistent'
          ? 'Twin consistent'
          : result.overall_status === 'inconsistent'
            ? 'Inconsistencies found'
            : 'No analytical artifacts yet'}
      </AlertTitle>
      <AlertDescription>
        <p>
          {result.report.summary.verified}/{result.report.summary.total_checked} artifacts verified ·{' '}
          report {result.report_checksum.slice(0, 10)}…
        </p>
        <p className="mt-1 text-stone-500">{result.report.bounds_note}</p>
        {result.report.artifact_checks.some((c) => !c.verified) && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {result.report.artifact_checks
              .filter((c) => !c.verified)
              .map((c) => (
                <li key={c.artifact_id}>
                  {c.artifact} {c.artifact_id.slice(0, 8)}: {c.findings.join('; ')}
                </li>
              ))}
          </ul>
        )}
      </AlertDescription>
    </Alert>
  )
}

function StatCard({
  label,
  value,
  sub,
  wide,
}: {
  label: string
  value: string
  sub?: string
  wide?: boolean
}) {
  return (
    <Card className={wide ? 'sm:col-span-2 lg:col-span-2' : ''}>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</p>
        <p className="mt-1 truncate text-sm font-semibold text-stone-900">{value}</p>
        {sub && <p className="truncate text-xs text-stone-500">{sub}</p>}
      </CardContent>
    </Card>
  )
}

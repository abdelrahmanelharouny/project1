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
import { useTranslations } from 'next-intl'
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
  const t = useTranslations('digitaltwin')
  const tCommon = useTranslations('common')
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
            {t('pickFieldDesc')}
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
          <AlertTitle>{t('validationFailed')}</AlertTitle>
          <AlertDescription>
            {validate.error instanceof ApiError ? validate.error.message : tCommon('unexpectedError')}
          </AlertDescription>
        </Alert>
      )}

      {twin.isLoading && <Skeleton className="h-48 w-full" />}

      {twin.data && <TwinView twin={twin.data as DigitalTwinView} />}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div className="min-w-0">
            <CardTitle className="text-base">{t('validationTitle')}</CardTitle>
            <CardDescription>{t('validationDesc')}</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => validate.mutate()} disabled={validate.isPending}>
            {validate.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <ShieldCheck className="mr-1 h-4 w-4" aria-hidden />
            )}
            {t('validateNow')}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {validate.data && <ValidationResult result={validate.data as TwinValidationResponse} />}
          {validations.data && validations.data.items.length > 0 && (
            <div className="max-h-64 overflow-y-auto rounded-lg border border-stone-200">
              <Table>
                <TableHeader className="sticky top-0 bg-white">
                  <TableRow>
                    <TableHead>{t('colWhen')}</TableHead>
                    <TableHead>{t('colStatus')}</TableHead>
                    <TableHead>{t('colChecked')}</TableHead>
                    <TableHead>{t('colFailed')}</TableHead>
                    <TableHead>{t('colReport')}</TableHead>
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
  const t = useTranslations('digitaltwin')
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-900">
        <Network className="h-5 w-5 text-emerald-700" aria-hidden />
        {t('title')}
      </h2>
      <p className="mt-1 text-sm text-stone-600">{t('desc')}</p>
    </div>
  )
}

function TwinView({ twin }: { twin: DigitalTwinView }) {
  const t = useTranslations('digitaltwin')
  const tCommon = useTranslations('common')
  const ic = twin.information_classes
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t('statField')}
          value={twin.field_identity.field_name}
          sub={t('statFieldSub', {
            area: twin.field_identity.area_ha ?? '—',
            unit: tCommon('ha'),
            version: twin.field_identity.latest_boundary_version ?? '—',
          })}
        />
        <StatCard label={t('statFieldStates')} value={String(twin.field_states.total)} sub={t('statSnapshots')} />
        <StatCard
          label={t('statClasses')}
          value={`${ic.observed_observations} / ${ic.scenario_derived_transformed_observations} / ${ic.calculated_feature_values}`}
          sub={t('statClassesSub')}
        />
        <StatCard label={t('statMaturity')} value={twin.maturity.classification} sub={t('statHonest')} wide />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('coverageTitle')}</CardTitle>
          <CardDescription>{twin.observation_coverage.note}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('colVariable')}</TableHead>
                  <TableHead>{t('colObservations')}</TableHead>
                  <TableHead>{t('colFirst')}</TableHead>
                  <TableHead>{t('colLast')}</TableHead>
                  <TableHead>{t('colAge')}</TableHead>
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
          <CardTitle className="text-base">{t('lineageTitle')}</CardTitle>
          <CardDescription>{t('lineageDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {twin.scenarios.length === 0 && (
            <p className="text-xs text-stone-500">{t('noScenariosYet')}</p>
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
                  {t('executionLine', {
                    id: e.execution_run_id.slice(0, 8),
                    status: e.run_status,
                    out: e.output_checksum ? t('outChecksum', { checksum: e.output_checksum.slice(0, 10) }) : '—',
                  })}
                </p>
              ))}
            </div>
          ))}
          {twin.robust_rotation.scenario_sets.map((s) => (
            <div key={s.scenario_set_id} className="rounded-lg border border-stone-200 p-3 text-xs">
              <span className="font-medium text-stone-800">{s.label}</span>
              <span className="ml-2 text-stone-500">({t('memberCount', { count: s.member_count })})</span>
              {s.robust_runs.map((r) => (
                <p key={r.robust_run_id} className="mt-1 text-stone-500">
                  {t('robustRunLine', { id: r.robust_run_id.slice(0, 8), status: r.run_status, solver: r.solver_status ?? '—' })}
                </p>
              ))}
            </div>
          ))}
          {twin.decision_documents.map((d) => (
            <p key={d.decision_comparison_id} className="text-xs text-stone-500">
              {t('decisionDocLine', {
                title: d.title,
                status: d.doc_status,
                checksum: d.document_checksum.slice(0, 10),
              })}
            </p>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('capabilitiesTitle')}</CardTitle>
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
            <p className="font-semibold text-stone-700">{t('notImplementedTitle')}</p>
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
  const t = useTranslations('digitaltwin')
  return (
    <Alert>
      <CheckCircle2 className="h-4 w-4" aria-hidden />
      <AlertTitle>
        {result.overall_status === 'consistent'
          ? t('consistent')
          : result.overall_status === 'inconsistent'
            ? t('inconsistent')
            : t('noArtifacts')}
      </AlertTitle>
      <AlertDescription>
        <p>
          {t('verificationSummary', {
            verified: result.report.summary.verified,
            total: result.report.summary.total_checked,
            checksum: result.report_checksum.slice(0, 10),
          })}
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

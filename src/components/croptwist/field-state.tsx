'use client'

import { useState } from 'react'
import {
  BadgeCheck,
  CircleAlert,
  Clock,
  Fingerprint,
  GitCompareArrows,
  Layers,
  MinusCircle,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { FieldPicker } from '@/components/croptwist/field-picker'
import { useFieldStates, useFieldStateVerify } from '@/hooks/use-croptwist'
import { createFieldState, describeError, verifyFieldState, compareFieldStates, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { useCropTwistUi } from '@/lib/store'
import type { FieldState, FieldStateDimension, FieldStateVerifyResponse, FieldStateCompareResponse } from '@/lib/types'

const DIMENSION_ORDER = ['environmental', 'water', 'rotation', 'crop_history', 'soil', 'management'] as const

const DIMENSION_LABEL_KEYS: Record<string, string> = {
  environmental: 'dimEnvironmental',
  water: 'dimWater',
  rotation: 'dimRotation',
  crop_history: 'dimCropHistory',
  soil: 'dimSoil',
  management: 'dimManagement',
}

function apiErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.details[0]
    const detailText = detail?.reason ? `${detail.field}: ${detail.reason}` : detail?.field
    return detailText ? `${err.message} (${detailText})` : err.message
  }
  return describeError(err).description ?? describeError(err).title
}

function DimensionBadge({ status }: { status: string }) {
  const t = useTranslations('fieldstate')
  const map: Record<string, { className: string; labelKey: string }> = {
    available: { className: 'border-emerald-300 bg-emerald-50 text-emerald-800', labelKey: 'dimAvailable' },
    missing: { className: 'border-stone-300 bg-stone-50 text-stone-600', labelKey: 'dimMissing' },
    period_mismatch: { className: 'border-amber-300 bg-amber-50 text-amber-800', labelKey: 'dimPeriodMismatch' },
    not_evaluated: { className: 'border-stone-300 bg-white text-stone-600', labelKey: 'dimNotEvaluated' },
    not_implemented: { className: 'border-stone-400 bg-stone-100 text-stone-700', labelKey: 'dimNotImplemented' },
  }
  const cfg = map[status]
  return (
    <Badge variant="outline" className={`font-normal ${cfg ? cfg.className : 'border-stone-300 bg-white text-stone-600'}`}>
      {cfg ? t(cfg.labelKey) : status}
    </Badge>
  )
}

function StateStatusBadge({ status }: { status: string }) {
  const t = useTranslations('fieldstate')
  if (status === 'succeeded')
    return (
      <Badge variant="outline" className="gap-1 border-emerald-300 bg-emerald-50 font-normal text-emerald-800">
        <BadgeCheck className="h-3 w-3" aria-hidden /> {t('statusSucceeded')}
      </Badge>
    )
  if (status === 'failed')
    return (
      <Badge variant="outline" className="gap-1 border-red-300 bg-red-50 font-normal text-red-700">
        <CircleAlert className="h-3 w-3" aria-hidden /> {t('statusFailed')}
      </Badge>
    )
  return (
    <Badge variant="outline" className="gap-1 border-stone-300 bg-white font-normal text-stone-600">
      <Clock className="h-3 w-3" aria-hidden /> {status}
    </Badge>
  )
}

function short(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 16) + ' UTC'
}

function shortHash(hash: string | null | undefined): string {
  return hash ? `${hash.slice(0, 12)}…` : '—'
}

function VerifyReport({ report }: { report: FieldStateVerifyResponse }) {
  const t = useTranslations('fieldstate')
  const rows: Array<{ label: string; ok: boolean }> = [
    { label: t('verifyChecksumValid'), ok: report.checksum_valid },
    { label: t('verifyManifestValid'), ok: report.manifest_checksum_valid },
    { label: t('verifyBoundaryExists'), ok: report.boundary_version_record_exists },
  ]
  for (const [name, ref] of Object.entries(report.referenced_artifacts)) {
    rows.push({ label: t('artifactExists', { name: name.replace('_', ' ') }), ok: ref.exists })
    rows.push({ label: t('artifactIntact', { name: name.replace('_', ' ') }), ok: ref.intact })
  }
  return (
    <ul className="space-y-1.5">
      {rows.map((row) => (
        <li key={row.label} className="flex items-center gap-2 text-xs">
          {row.ok ? (
            <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-700" aria-hidden />
          ) : (
            <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-red-600" aria-hidden />
          )}
          <span className={row.ok ? 'text-stone-700' : 'font-medium text-red-700'}>{row.label}</span>
        </li>
      ))}
      <li className="pt-1 text-[11px] text-stone-500">{t('verifiedAt', { time: short(report.verified_at) })}</li>
    </ul>
  )
}

function StateDetail({ state }: { state: FieldState }) {
  const t = useTranslations('fieldstate')
  const [verifyReport, setVerifyReport] = useState<FieldStateVerifyResponse | null>(null)
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const verifyMutation = useMutation({
    mutationFn: () => verifyFieldState(state.id),
    onSuccess: (data) => {
      setVerifyReport(data)
      setVerifyError(null)
    },
    onError: (err) => setVerifyError(describeError(err).title),
  })

  const evidence = state.evidence_summary as Record<string, Record<string, unknown>>

  return (
    <div className="space-y-4">
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">{state.label}</CardTitle>
              <StateStatusBadge status={state.status} />
              <Badge variant="outline" className="font-normal text-stone-600">
                {t('boundaryVersion', { version: state.boundary_version })}
              </Badge>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => verifyMutation.mutate()}
              disabled={verifyMutation.isPending}
            >
              <Fingerprint className="h-3.5 w-3.5" aria-hidden />
              {verifyMutation.isPending ? t('verifying') : t('verifyChecksums')}
            </Button>
          </div>
          <CardDescription>
            {t('asOfPeriod', {
              time: short(state.state_reference_time),
              start: short(state.period.start),
              end: short(state.period.end),
              timezone: state.timezone,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {verifyError && (
            <Alert variant="destructive">
              <ShieldAlert className="h-4 w-4" />
              <AlertTitle>{t('verificationFailed')}</AlertTitle>
              <AlertDescription>{verifyError}</AlertDescription>
            </Alert>
          )}
          {verifyReport && (
            <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500">
                {t('verificationReport')}
              </p>
              <VerifyReport report={verifyReport} />
            </div>
          )}

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500">
              {t('domainAvailability')}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {DIMENSION_ORDER.map((dim) => {
                const info: FieldStateDimension | undefined = state.domain_availability[dim]
                if (!info) return null
                return (
                  <div key={dim} className="rounded-lg border border-stone-200 bg-white p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-stone-800">
                        {DIMENSION_LABEL_KEYS[dim] ? t(DIMENSION_LABEL_KEYS[dim]) : dim}
                      </span>
                      <DimensionBadge status={info.status} />
                    </div>
                    {info.reason && <p className="mt-1 text-xs text-stone-500">{info.reason}</p>}
                    {info.snapshot_id && (
                      <p className="mt-1 font-mono text-[11px] text-stone-400">{info.snapshot_id}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-stone-200 bg-white p-3">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">{t('inputsPinned')}</p>
              <ul className="space-y-1 text-xs text-stone-600">
                <li>
                  {t('pinnedFeatureRun')}:{' '}
                  <span className="font-mono">{state.environmental_feature_run_id ?? '—'}</span>
                </li>
                <li>
                  {t('pinnedWaterPlan')}:{' '}
                  <span className="font-mono">{state.water_plan_id ?? '—'}</span>
                </li>
                <li>
                  {t('pinnedRotationRun')}:{' '}
                  <span className="font-mono">{state.rotation_run_id ?? '—'}</span>
                  {state.rotation_strategy_key ? ` (${state.rotation_strategy_key})` : ''}
                </li>
                <li>{t('pinnedCropHistory', { count: state.crop_history_ids.length })}</li>
                <li>{t('pinnedKnowledgePacks', { count: state.knowledge_pack_refs.length })}</li>
                <li>
                  {t('observationManifest')}:{' '}
                  {(() => {
                    const env = evidence.environmental ?? {}
                    return t('manifestRows', {
                      rows: String(env.observation_count ?? 0),
                      synthetic: String(env.synthetic_observation_count ?? 0),
                    })
                  })()}
                </li>
              </ul>
            </div>
            <div className="rounded-lg border border-stone-200 bg-white p-3">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">
                {t('reproducibility')}
              </p>
              <ul className="space-y-1 text-xs text-stone-600">
                <li>
                  {t('stateChecksum')}{' '}
                  <span className="font-mono">{shortHash(state.checksum_sha256)}</span>
                </li>
                <li>
                  {t('manifestSha')}{' '}
                  <span className="font-mono">{shortHash(state.observation_manifest_sha256)}</span>
                </li>
                <li>{t('manifestFormat', { version: state.manifest_format_version })}</li>
                <li>{t('assemblyVersion', { version: state.field_state_assembly_version ?? '—' })}</li>
                <li>{t('createdAt', { time: short(state.created_at) })}</li>
              </ul>
            </div>
          </div>

          {state.warnings.length > 0 && (
            <Alert>
              <MinusCircle className="h-4 w-4" />
              <AlertTitle>{t('assemblyWarnings')}</AlertTitle>
              <AlertDescription>
                <ul className="list-disc space-y-1 pl-4">
                  {state.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function FieldStateView() {
  const t = useTranslations('fieldstate')
  const tNav = useTranslations('nav')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const statesQuery = useFieldStates(selectedField?.id ?? null)
  const queryClient = useQueryClient()

  const [label, setLabel] = useState('')
  const [periodFrom, setPeriodFrom] = useState('')
  const [periodTo, setPeriodTo] = useState('')
  const [selectedStateId, setSelectedStateId] = useState<string | null>(null)
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [compareReport, setCompareReport] = useState<FieldStateCompareResponse | null>(null)
  const [assembleError, setAssembleError] = useState<string | null>(null)

  const assembleMutation = useMutation({
    mutationFn: () =>
      createFieldState(selectedField!.id, {
        label: label.trim() || undefined,
        // Period is optional in the API (it defaults to the pinned run's
        // window); required by the backend when no feature run exists.
        period_start: periodFrom || undefined,
        period_end: periodTo || undefined,
      }),
    onSuccess: (state) => {
      setLabel('')
      setPeriodFrom('')
      setPeriodTo('')
      setAssembleError(null)
      setSelectedStateId(state.id)
      queryClient.invalidateQueries({ queryKey: ['field-states', selectedField?.id] })
    },
    onError: (err) => setAssembleError(apiErrorText(err)),
  })

  const compareMutation = useMutation({
    mutationFn: () => compareFieldStates(compareIds),
    onSuccess: (data) => {
      setCompareReport(data)
    },
  })

  const states = statesQuery.data?.items ?? []
  const detailState = states.find((s) => s.id === selectedStateId) ?? null

  if (!selectedField) {
    return (
      <div className="space-y-4" aria-label={t('ariaFieldState')}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-stone-900">{tNav('fieldstate')}</h2>
            <p className="text-sm text-stone-500">{t('subtitle')}</p>
          </div>
          <FieldPicker value={null} onValueChange={setSelectedField} />
        </div>
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <Layers className="h-8 w-8 text-stone-400" aria-hidden />
            <p className="text-sm text-stone-500">
              {t('pickFieldHint')}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6" aria-label={t('ariaFieldState')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">{tNav('fieldstate')}</h2>
          <p className="text-sm text-stone-500">
            {t('forField', { name: selectedField.name })}
          </p>
        </div>
      </div>

      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('assembleTitle')}</CardTitle>
          <CardDescription>
            {t.rich('assembleDesc', {
              span: (chunks) => <span className="font-medium">{chunks}</span>,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {assembleError && (
            <Alert variant="destructive">
              <ShieldAlert className="h-4 w-4" />
              <AlertTitle>{t('assembleErrorTitle')}</AlertTitle>
              <AlertDescription>{assembleError}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="state-label">{t('labelOptional')}</Label>
              <Input
                id="state-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('defaultStateLabel', { name: selectedField.name })}
                maxLength={120}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="state-period-from" className="text-stone-600">
                {t('periodFrom')}
              </Label>
              <Input
                id="state-period-from"
                type="date"
                value={periodFrom}
                onChange={(e) => setPeriodFrom(e.target.value)}
                className="w-full sm:w-40"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="state-period-to" className="text-stone-600">
                {t('periodTo')}
              </Label>
              <Input
                id="state-period-to"
                type="date"
                value={periodTo}
                onChange={(e) => setPeriodTo(e.target.value)}
                className="w-full sm:w-40"
              />
            </div>
            <Button
              onClick={() => assembleMutation.mutate()}
              disabled={assembleMutation.isPending}
              className="shrink-0 gap-1.5"
            >
              <Layers className="h-4 w-4" aria-hidden />
              {assembleMutation.isPending ? t('assembling') : t('assembleState')}
            </Button>
          </div>
          <p className="text-xs text-stone-500">
            {t('periodHint')}
          </p>
        </CardContent>
      </Card>

      {statesQuery.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      ) : statesQuery.isError ? (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
          <AlertDescription>
            {statesQuery.error instanceof Error ? statesQuery.error.message : t('backendError')}
          </AlertDescription>
        </Alert>
      ) : states.length === 0 ? (
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="p-6 text-center text-sm text-stone-500">
            {t('noStatesYet')}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">{t('snapshotsCount', { count: states.length })}</CardTitle>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  disabled={compareIds.length !== 2 || compareMutation.isPending}
                  onClick={() => compareMutation.mutate()}
                >
                  <GitCompareArrows className="h-3.5 w-3.5" aria-hidden />
                  {compareMutation.isPending ? t('comparing') : t('compareSelected')}
                </Button>
              </div>
              <CardDescription>
                {t('compareHint')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {states.map((state) => {
                const checked = compareIds.includes(state.id)
                return (
                  <div
                    key={state.id}
                    className={`rounded-lg border p-3 transition-colors ${
                      selectedStateId === state.id ? 'border-emerald-400 bg-emerald-50/40' : 'border-stone-200 bg-white'
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="checkbox"
                        className="h-4 w-4 shrink-0 accent-emerald-700"
                        aria-label={t('selectForComparison', { label: state.label })}
                        checked={checked}
                        onChange={(e) =>
                          setCompareIds((prev) =>
                            e.target.checked
                              ? [...prev.filter((id) => id !== state.id), state.id].slice(-2)
                              : prev.filter((id) => id !== state.id),
                          )
                        }
                      />
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => setSelectedStateId(state.id === selectedStateId ? null : state.id)}
                      >
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-medium text-stone-800">{state.label}</span>
                          <StateStatusBadge status={state.status} />
                          <Badge variant="outline" className="font-normal text-stone-500">
                            {t('boundaryVersion', { version: state.boundary_version })}
                          </Badge>
                          <span className="text-[11px] text-stone-400">{short(state.created_at)}</span>
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[11px] text-stone-400">
                          {shortHash(state.checksum_sha256)}
                        </span>
                      </button>
                    </div>
                  </div>
                )
              })}
              {compareReport && (
                <div className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-stone-600">
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">
                    {t('comparison')}
                  </p>
                  <ul className="space-y-1">
                    <li>
                      {t('boundaryVersionsConsistent')}{' '}
                      <span className="font-medium">{String(compareReport.boundary_versions_consistent)}</span>
                    </li>
                    {Object.entries(compareReport.dimension_comparison).map(([dim, info]) => (
                      <li key={dim}>
                        {t('dimConsistent', { dim: dim.replace(/_/g, ' ') })}{' '}
                        <span className="font-medium">{String(info.consistent)}</span>
                      </li>
                    ))}
                    {compareReport.pairwise_period_overlap.map((pair) => (
                      <li key={`${pair.state_a}-${pair.state_b}`}>
                        {t('periodOverlapLabel')}:{' '}
                        {pair.period_overlap_fraction === null
                          ? t('overlapNa')
                          : `${Math.round((pair.period_overlap_fraction ?? 0) * 100)}%`}
                        {' · '}
                        {pair.compatible_periods ? t('overlapping') : t('nonOverlapping')}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[11px] text-stone-500">{compareReport.note}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {detailState && <StateDetail state={detailState} />}
        </>
      )}
    </div>
  )
}

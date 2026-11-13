'use client'

/**
 * P07 — Anomalies tab (Reports & Analytics → Anomalies).
 *
 * HONESTY IS NON-NEGOTIABLE here:
 *   - anomaly cards are SIGNALS (amber warning / stone info). The footer of
 *     every card repeats "NOT a diagnosis" and lists the claims that require
 *     independent evidence (requires_independent_evidence_for);
 *   - insufficient_evidence gates render as a visible amber panel — never
 *     hidden, never collapsed into "no anomalies";
 *   - the comparison panel shows mean_delta + zone deltas ONLY when
 *     `comparable: true`; incompatible acquisitions get the backend's own
 *     incompatibilities prominently and NO delta anywhere;
 *   - deltas are described side-by-side; the panel states that correlation
 *     is not causation and no attribution is claimed;
 *   - "Investigate on map" navigates to the canonical map destination while
 *     preserving the workspace URL contract (tab/sub/farm/field/fieldName).
 */

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { Map as MapIcon } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ComparisonDeltaChart, ScatterComparisonChart } from '@/components/croptwist/charts/p07-charts'
import { IndexSelectorChips, isP07Index } from '@/components/croptwist/p7/satellite-analytics-tab'
import { useCropTwistUi } from '@/lib/store'
import { comparisonSummary, severityBadgeVariant } from '@/lib/analytics/p07-utils'
import { humanizeCode, formatDay } from '@/lib/format'
import { useLayerCatalog, useFarmSatelliteOverview, useSpatialAnomalies, useSpatialComparison } from '@/hooks/use-p07'
import type {
  P07Anomaly,
  P07AnomalyResponse,
  P07Comparison,
  P07IndexCode,
} from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// Small honest helpers
// ---------------------------------------------------------------------------

function pct(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : `${(Number(value) * 100).toFixed(digits)}%`
}

/** Localized index label for KNOWN codes only — unknown codes stay verbatim. */
function indexLabel(t: ReturnType<typeof useTranslations>, code: string): string {
  return isP07Index(code) ? t(`index.${code}`) : code
}

function emDashNumber(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : Number(value).toFixed(digits)
}

function BasisRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-stone-100 py-1 last:border-b-0">
      <span className="text-[11px] text-stone-500">{label}</span>
      <span className="font-mono text-xs tabular-nums text-stone-700" dir="ltr">
        {value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Anomaly card
// ---------------------------------------------------------------------------

function AnomalyCard({ anomaly, requiresFor }: { anomaly: P07Anomaly; requiresFor: readonly string[] }) {
  const t = useTranslations('p07analytics')
  const severity = severityBadgeVariant(anomaly.severity)
  const severityLabel =
    anomaly.severity === 'warning'
      ? t('anomalies.severityWarning')
      : anomaly.severity === 'info'
        ? t('anomalies.severityInfo')
        : t('anomalies.severityUnknown')
  const measurements = Object.entries(anomaly.measurements ?? {})

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{humanizeCode(anomaly.type)}</CardTitle>
          <Badge variant={severity.variant} className={severity.className}>
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${severity.dot}`} aria-hidden />
            {severityLabel}
          </Badge>
        </div>
        <CardDescription className="text-sm text-stone-500">
          {t('anomalies.confidence', { pct: pct(anomaly.confidence) })} · {indexLabel(t, anomaly.index)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* provenance basis — the exact scene/processing the signal came from */}
        <div aria-label={t('anomalies.basis')}>
          <BasisRow label={t('anomalies.observedAt')} value={anomaly.observed_at ? formatDay(anomaly.observed_at) : '—'} />
          <BasisRow label={t('anomalies.scene')} value={anomaly.scene_id ?? '—'} />
          <BasisRow label={t('anomalies.processing')} value={anomaly.processing_version ?? '—'} />
          <BasisRow
            label={t('anomalies.resolution')}
            value={anomaly.spatial_resolution_m === null || anomaly.spatial_resolution_m === undefined ? '—' : `${anomaly.spatial_resolution_m} m`}
          />
          <BasisRow label={t('anomalies.validPixel')} value={pct(anomaly.valid_pixel_fraction, 1)} />
        </div>

        {anomaly.reasons.length > 0 ? (
          <div>
            <p className="text-xs font-semibold text-stone-700">{t('anomalies.reasons')}</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-sm text-stone-600">
              {anomaly.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {measurements.length > 0 ? (
          <div className="overflow-x-auto" dir="ltr">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-1/2">{t('anomalies.measurements')}</TableHead>
                  <TableHead className="text-end">{t('anomalies.measurementsValue')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {measurements.map(([key, value]) => (
                  <TableRow key={key}>
                    <TableCell className="text-xs text-stone-600">{humanizeCode(key)}</TableCell>
                    <TableCell className="text-end font-mono text-xs tabular-nums">
                      {emDashNumber(value)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}

        {anomaly.limitations.length > 0 ? (
          <div>
            <p className="text-xs font-semibold text-stone-700">{t('anomalies.limitations')}</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-stone-500">
              {anomaly.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <Separator />

        {/* honesty footer — repeated on EVERY card, never collapsible */}
        <Alert className="border-amber-200 bg-amber-50 text-amber-900">
          <AlertDescription className="text-xs font-medium">{t('anomalies.notDiagnosis')}</AlertDescription>
        </Alert>
        {requiresFor.length > 0 ? (
          <p className="text-[11px] text-stone-500">
            {t('anomalies.requiresFor', { items: requiresFor.map(humanizeCode).join(', ') })}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Comparison panel
// ---------------------------------------------------------------------------

function zoneLabelKey(zone: string): string {
  switch (zone) {
    case 'lowest_tercile':
      return 'field.zoneLow'
    case 'middle_tercile':
      return 'field.zoneMiddle'
    case 'highest_tercile':
      return 'field.zoneHigh'
    default:
      return zone
  }
}

function SideMeta({
  side,
  label,
}: {
  side: P07Comparison['side_a']
  label: string
}) {
  const t = useTranslations('p07analytics')
  if (!side) {
    return (
      <p className="text-sm text-stone-500">{label}: —</p>
    )
  }
  return (
    <div className="space-y-1 rounded-md border border-stone-200 bg-stone-50/60 p-3">
      <p className="text-xs font-semibold text-stone-700">{label}</p>
      <p className="font-mono text-[11px] tabular-nums text-stone-600" dir="ltr">
        {t('anomalies.sceneMeta', {
          date: side.acquired_at ? formatDay(side.acquired_at) : '—',
          scene: side.scene_id,
          version: side.processing_version,
        })}
      </p>
      <p className="font-mono text-[11px] tabular-nums text-stone-600" dir="ltr">
        {side.spatial_resolution_m ?? '—'} m · {pct(side.valid_pixel_fraction, 1)} · {emDashNumber(side.zonal?.mean ?? null)}
      </p>
    </div>
  )
}

function ComparisonPanel({ index }: { index: P07IndexCode }) {
  const t = useTranslations('p07analytics')
  const router = useRouter()
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const fieldId = selectedField?.id ?? null
  const farmId = selectedField?.farmId ?? null

  const [targetFieldId, setTargetFieldId] = useState('')
  const [dateA, setDateA] = useState('')
  const [dateB, setDateB] = useState('')

  const farmQuery = useFarmSatelliteOverview(farmId, index)
  const catalogQuery = useLayerCatalog(fieldId)

  const otherFields = useMemo(
    () =>
      (farmQuery.data?.fields ?? []).filter(
        (f) => f.field_id !== fieldId && f.available,
      ),
    [farmQuery.data, fieldId],
  )

  const datesAvailable = useMemo(() => {
    const layer = catalogQuery.data?.layers.vegetation.find((l) => l.code === index)
    return (layer?.dates_available ?? [])
      .filter((d) => typeof d.acquired_at === 'string' && d.acquired_at !== '')
      .map((d) => d.acquired_at as string)
      .sort((a, b) => (a < b ? 1 : -1)) // newest first
  }, [catalogQuery.data, index])

  const comparisonQuery = useSpatialComparison(fieldId, {
    index,
    targetFieldId: targetFieldId || undefined,
    acquiredAtA: dateA || undefined,
    acquiredAtB: dateB || undefined,
  })
  const comparison = comparisonQuery.data

  const zoneLabels = useMemo<Record<string, string>>(() => {
    const labels: Record<string, string> = {}
    for (const row of comparison?.zone_deltas ?? []) {
      const key = zoneLabelKey(row.zone)
      labels[row.zone] = key.includes('.') ? t(key) : key
    }
    return labels
  }, [comparison, t])

  const scatterPoints = useMemo(() => {
    if (!comparison?.comparable) return []
    return (comparison.zone_deltas ?? [])
      .filter((row) => row.mean_a !== null && row.mean_b !== null)
      .map((row) => ({
        x: row.mean_a as number,
        y: row.mean_b as number,
        label: zoneLabels[row.zone] ?? row.zone,
      }))
  }, [comparison, zoneLabels])

  const investigate = () => {
    if (!selectedField) return
    const target = targetFieldId
      ? otherFields.find((f) => f.field_id === targetFieldId)
      : null
    const params = new URLSearchParams()
    params.set('tab', 'geo')
    params.set('sub', 'map')
    // The investigation target is the field the user chose (or the current one).
    const investigateField = target
      ? { id: target.field_id, name: target.field_name, farmId: farmId ?? '' }
      : selectedField
    params.set('farm', investigateField.farmId)
    params.set('field', investigateField.id)
    params.set('fieldName', investigateField.name)
    // destination-specific params (analytics/index) intentionally dropped —
    // the workspace canonical sync re-canonicalizes on the next store write.
    router.push(`/?${params.toString()}`, { scroll: false })
  }

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('anomalies.compareTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('anomalies.compareDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p07-cmp-field">
              {t('anomalies.compareFieldLabel')}
            </Label>
            <Select
              value={targetFieldId || 'none'}
              onValueChange={(v) => setTargetFieldId(v === 'none' ? '' : v)}
            >
              <SelectTrigger id="p07-cmp-field" className="h-9 bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('anomalies.compareFieldNone')}</SelectItem>
                {otherFields.map((f) => (
                  <SelectItem key={f.field_id} value={f.field_id}>
                    {f.field_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p07-cmp-date-a">
              {t('anomalies.compareDateA')}
            </Label>
            <Select
              value={dateA || 'latest'}
              onValueChange={(v) => setDateA(v === 'latest' ? '' : v)}
            >
              <SelectTrigger id="p07-cmp-date-a" className="h-9 bg-white" dir="ltr">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="latest">{t('anomalies.compareLatest')}</SelectItem>
                {datesAvailable.map((d) => (
                  <SelectItem key={d} value={d}>
                    {d.slice(0, 10)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p07-cmp-date-b">
              {t('anomalies.compareDateB')}
            </Label>
            <Select
              value={dateB || 'latest'}
              onValueChange={(v) => setDateB(v === 'latest' ? '' : v)}
            >
              <SelectTrigger id="p07-cmp-date-b" className="h-9 bg-white" dir="ltr">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="latest">{t('anomalies.compareLatest')}</SelectItem>
                {datesAvailable.map((d) => (
                  <SelectItem key={d} value={d}>
                    {d.slice(0, 10)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {datesAvailable.length === 0 ? (
          <p className="text-sm text-stone-500">{t('anomalies.noDates')}</p>
        ) : null}

        {comparisonQuery.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : comparisonQuery.isError ? (
          <Alert className="border-red-200 bg-red-50 text-red-800">
            <AlertDescription className="text-sm">{String(comparisonQuery.error)}</AlertDescription>
          </Alert>
        ) : comparison ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={
                  comparison.comparable
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                    : 'border-amber-300 bg-amber-50 text-amber-800'
                }
              >
                {comparison.comparable ? t('anomalies.comparableBadge') : t('anomalies.notComparableBadge')}
              </Badge>
              <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
                {comparison.compatibility?.same_field
                  ? t('anomalies.sameFieldBadge')
                  : t('anomalies.differentFieldBadge')}
              </Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <SideMeta side={comparison.side_a} label={t('anomalies.sideALabel')} />
              <SideMeta side={comparison.side_b} label={t('anomalies.sideBLabel')} />
            </div>

            {!comparison.comparable ? (
              <Alert className="border-amber-300 bg-amber-50 text-amber-900">
                <AlertTitle className="text-sm font-semibold">{t('anomalies.incompatTitle')}</AlertTitle>
                <AlertDescription className="text-sm text-amber-800">
                  <p>{t('anomalies.incompatIntro')}</p>
                  <ul className="mt-1.5 list-inside list-disc space-y-0.5">
                    {(comparison.incompatibilities ?? []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  {comparisonSummary(comparison, 3) ? (
                    <p className="mt-2 font-mono text-[11px] tabular-nums" dir="ltr">
                      {comparisonSummary(comparison, 3)}
                    </p>
                  ) : null}
                </AlertDescription>
              </Alert>
            ) : null}

            {/* mean_delta + charts ONLY when comparable */}
            {comparison.comparable ? (
              <div className="space-y-4" dir="ltr">
                <div className="flex flex-wrap items-baseline gap-3">
                  <span className="text-sm text-stone-600">{t('anomalies.meanDelta')}</span>
                  <span className="font-mono text-2xl font-semibold tabular-nums text-stone-900">
                    {emDashNumber(comparison.mean_delta)}
                  </span>
                  {comparison.mean_delta_pct !== null && comparison.mean_delta_pct !== undefined ? (
                    <span className="text-xs text-stone-500">
                      {t('anomalies.meanDeltaPct', { pct: comparison.mean_delta_pct.toFixed(1) })}
                    </span>
                  ) : null}
                </div>
                {scatterPoints.length > 0 ? (
                  <ScatterComparisonChart
                    points={scatterPoints}
                    xLabel={t('anomalies.sideALabel')}
                    yLabel={t('anomalies.sideBLabel')}
                    unit={t(`index.${index}`)}
                    title={t('anomalies.scatterTitle')}
                    description={t('anomalies.scatterDesc')}
                    showDiagonal
                    emptyReason={t('charts.noDataForPeriod')}
                  />
                ) : null}
                <ComparisonDeltaChart
                  zoneDeltas={comparison.zone_deltas}
                  unit={t(`index.${index}`)}
                  title={t('anomalies.deltaChartTitle')}
                  description={t('anomalies.deltaChartDesc')}
                  zoneLabels={zoneLabels}
                  emptyReason={t('charts.noDataForPeriod')}
                />
              </div>
            ) : null}

            {(comparison.measurement_notes ?? []).length > 0 ? (
              <div>
                <p className="text-xs font-semibold text-stone-700">{t('anomalies.notesTitle')}</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-stone-500">
                  {comparison.measurement_notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Alert className="border-stone-200 bg-stone-50 text-stone-700">
              <AlertDescription className="text-xs">{t('anomalies.correlationNote')}</AlertDescription>
            </Alert>
          </div>
        ) : null}

        <Button
          variant="outline"
          className="gap-2 border-stone-300 bg-white text-stone-700 hover:bg-stone-50"
          onClick={investigate}
        >
          <MapIcon className="h-4 w-4" aria-hidden />
          {t('anomalies.investigate')}
        </Button>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function AnomaliesTab() {
  const t = useTranslations('p07analytics')
  const searchParams = useSearchParams()
  const rawIndex = searchParams.get('index')
  const index: P07IndexCode = isP07Index(rawIndex) ? rawIndex : 'ndvi'
  const router = useRouter()
  const setIndexParam = (next: P07IndexCode) => {
    const params = new URLSearchParams(searchParams.toString())
    if (next === 'ndvi') params.delete('index')
    else params.set('index', next)
    const qs = params.toString()
    router.replace(qs ? `/?${qs}` : '/', { scroll: false })
  }

  const selectedField = useCropTwistUi((s) => s.selectedField)
  const fieldId = selectedField?.id ?? null
  const query = useSpatialAnomalies(fieldId, index)
  const data: P07AnomalyResponse | undefined = query.data

  if (!selectedField) {
    return (
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('hub.noFieldTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('hub.noFieldHint')}</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('anomalies.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('anomalies.subtitle')}</p>
      </header>

      <div className="flex flex-col gap-2">
        <span id="p07-anomaly-index-label" className="text-xs font-medium text-stone-600">
          {t('index.label')}
        </span>
        <IndexSelectorChips value={index} onChange={setIndexParam} labelId="p07-anomaly-index-label" />
      </div>

      {query.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : query.isError ? (
        <Alert className="border-red-200 bg-red-50 text-red-800">
          <AlertDescription className="text-sm">{String(query.error)}</AlertDescription>
        </Alert>
      ) : (
        <>
          {/* evidence gates — ALWAYS visible, even when anomalies exist */}
          {data && data.insufficient_evidence.length > 0 ? (
            <Alert className="border-amber-300 bg-amber-50 text-amber-900">
              <AlertTitle className="text-sm font-semibold">{t('anomalies.gatesTitle')}</AlertTitle>
              <AlertDescription className="text-sm text-amber-800">
                <p>{t('anomalies.gatesIntro')}</p>
                <ul className="mt-1.5 list-inside list-disc space-y-0.5">
                  {data.insufficient_evidence.map((gate) => (
                    <li key={gate}>{gate}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}

          {data && data.anomalies.length === 0 ? (
            <Card className="border-stone-200 bg-white shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t('anomalies.noneTitle')}</CardTitle>
                <CardDescription className="text-sm text-stone-500">{t('anomalies.noneHint')}</CardDescription>
              </CardHeader>
            </Card>
          ) : null}

          {data && data.anomalies.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {data.anomalies.map((anomaly) => (
                <AnomalyCard
                  key={anomaly.id}
                  anomaly={anomaly}
                  requiresFor={data.requires_independent_evidence_for ?? []}
                />
              ))}
            </div>
          ) : null}

          {data ? (
            <p className="text-[11px] text-stone-400">
              {t('charts.source', {
                detail: t('anomalies.sourceLine', {
                  id: 'field',
                  version: data.version,
                  generatedFrom: data.generated_from,
                }),
              })}
            </p>
          ) : null}

          <ComparisonPanel index={index} />
        </>
      )}
    </div>
  )
}

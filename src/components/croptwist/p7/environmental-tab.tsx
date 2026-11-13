'use client'

/**
 * P07 — Environmental tab (Reports & Analytics → Environmental).
 *
 * REAL DATA ONLY. The series on this page come from the existing
 * GET /fields/{id}/observations endpoint (variable-filtered, monthly
 * aggregates computed client-side from the returned values — no values are
 * invented, interpolated or simulated). Availability per variable comes from
 * the P07 layer catalog (GET /fields/{id}/map/layers), which lists EVERY
 * declared environmental series with `available` + `unavailable_reason`.
 * Series the API does not expose yet (ECOSTRESS LST, terrain DEM) render an
 * explicit "not exposed by the API yet" panel — never a placeholder chart.
 *
 * Each chart carries: title, unit, source line (endpoint + variable),
 * the observation time range, and a monthly-gaps panel (missing months
 * between the first and latest observation of that variable).
 */

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { MultiLineChart, MonthlyBarChart } from '@/components/croptwist/charts/p07-charts'
import { useCropTwistUi } from '@/lib/store'
import { useObservations } from '@/hooks/use-croptwist'
import { useLayerCatalog } from '@/hooks/use-p07'
import type { Observation } from '@/lib/types'
import type { P07EnvironmentLayer, P07LayerCatalog } from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// Month helpers (ISO "YYYY-MM"; string compare is correct for zero-padded)
// ---------------------------------------------------------------------------

function monthKey(iso: string): string {
  return iso.slice(0, 7)
}

function addMonth(key: string, delta: number): string {
  const [y, m] = key.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + delta, 1))
  return d.toISOString().slice(0, 7)
}

/** Inclusive month list from `from` to `to` (empty when either is unusable). */
function monthRange(from: string, to: string): string[] {
  if (!/^\d{4}-\d{2}$/.test(from) || !/^\d{4}-\d{2}$/.test(to) || from > to) return []
  const months: string[] = []
  let cur = from
  let guard = 0
  while (cur <= to && guard < 600) {
    months.push(cur)
    cur = addMonth(cur, 1)
    guard += 1
  }
  return months
}

type RangePreset = '3m' | '6m' | '12m'

const RANGE_MONTHS: Record<RangePreset, number> = { '3m': 3, '6m': 6, '12m': 12 }

// ---------------------------------------------------------------------------
// Variable definitions (backend contract: app/data_platform/contracts/variables.py)
// ---------------------------------------------------------------------------

const TEMP_VARIABLES = ['air_temperature_min', 'air_temperature_mean', 'air_temperature_max'] as const

// ---------------------------------------------------------------------------
// Aggregation
// ---------------------------------------------------------------------------

interface MonthlyAggregate {
  /** Months that actually contain observations — absent months are gaps. */
  months: string[]
  /** value → null when the month has observations but none carried a value. */
  value: number | null
  observationCount: number
  excludedCount: number
  firstObservedAt: string | null
  lastObservedAt: string | null
}

function aggregateMonthly(
  items: Observation[],
  mode: 'sum' | 'mean',
): MonthlyAggregate[] {
  const byMonth = new Map<string, { values: number[]; total: number; excluded: number; first: string | null; last: string | null }>()
  for (const obs of items) {
    const key = monthKey(obs.observed_at)
    if (!/^\d{4}-\d{2}$/.test(key)) continue // never chart an unparseable date
    const bucket = byMonth.get(key) ?? {
      values: [],
      total: 0,
      excluded: 0,
      first: null as string | null,
      last: null as string | null,
    }
    if (obs.observed_at && (bucket.first === null || obs.observed_at < bucket.first)) {
      bucket.first = obs.observed_at
    }
    if (obs.observed_at && (bucket.last === null || obs.observed_at > bucket.last)) {
      bucket.last = obs.observed_at
    }
    if (obs.value !== null && Number.isFinite(Number(obs.value))) {
      bucket.values.push(Number(obs.value))
      bucket.total += Number(obs.value)
    } else {
      bucket.excluded += 1
    }
    byMonth.set(key, bucket)
  }
  return [...byMonth.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([month, bucket]) => ({
      months: [month],
      value:
        bucket.values.length > 0
          ? mode === 'sum'
            ? bucket.total
            : bucket.total / bucket.values.length
          : null,
      observationCount: bucket.values.length + bucket.excluded,
      excludedCount: bucket.excluded,
      firstObservedAt: bucket.first,
      lastObservedAt: bucket.last,
    }))
}

/** Months between the first and last observed month that have NO observations. */
function missingMonths(aggregates: MonthlyAggregate[]): string[] {
  const present = aggregates.map((a) => a.months[0]).filter((m) => typeof m === 'string')
  if (present.length < 2) return []
  const first = present[0]
  const last = present[present.length - 1]
  const set = new Set(present)
  return monthRange(first, last).filter((m) => !set.has(m))
}

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------

function ChartSkeletonCard() {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-56" />
        <Skeleton className="h-3 w-80" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-64 w-full" />
      </CardContent>
    </Card>
  )
}

function EnvironmentEmptyState() {
  const t = useTranslations('p07analytics')
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('environment.noSeriesTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">
          {t('environment.noSeriesHint')}
        </CardDescription>
      </CardHeader>
    </Card>
  )
}

function SeriesMeta({
  count,
  first,
  last,
  excluded,
}: {
  count: number
  first: string | null
  last: string | null
  excluded: number
}) {
  const t = useTranslations('p07analytics')
  return (
    <div className="flex flex-wrap items-center gap-2" dir="ltr">
      <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
        {t('environment.seriesCount', { count })}
      </Badge>
      {first ? (
        <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
          {t('environment.firstObs')}: {first.slice(0, 10)}
        </Badge>
      ) : null}
      {last ? (
        <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
          {t('environment.lastObs')}: {last.slice(0, 10)}
        </Badge>
      ) : null}
      {excluded > 0 ? (
        <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-800">
          {t('environment.excluded', { count: excluded })}
        </Badge>
      ) : null}
    </div>
  )
}

function GapsPanel({ gaps }: { gaps: string[] }) {
  const t = useTranslations('p07analytics')
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-stone-600">{t('environment.gapsTitle')}</p>
      {gaps.length === 0 ? (
        <p className="text-sm text-stone-500">{t('environment.gapsNone')}</p>
      ) : (
        <p className="font-mono text-xs tabular-nums text-stone-600" dir="ltr">
          {t('environment.gapsList', { months: gaps.join(' · ') })}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Series section (one variable family)
// ---------------------------------------------------------------------------

function SeriesSection({
  children,
  meta,
  gaps,
  source,
}: {
  children: React.ReactNode
  meta: React.ReactNode
  gaps: string[]
  source: string
}) {
  const t = useTranslations('p07analytics')
  return (
    <div className="space-y-3">
      {meta}
      {children}
      <GapsPanel gaps={gaps} />
      <p className="text-[11px] text-stone-400">{t('charts.source', { detail: source })}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function EnvironmentalTab() {
  const t = useTranslations('p07analytics')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const [range, setRange] = useState<RangePreset>('12m')

  const fieldId = selectedField?.id ?? null
  const catalogQuery = useLayerCatalog(fieldId)
  const catalog: P07LayerCatalog | undefined = catalogQuery.data

  const { start, end } = useMemo(() => {
    const endIso = new Date().toISOString().slice(0, 10)
    const startIso = new Date(Date.now() - RANGE_MONTHS[range] * 30 * 86400_000)
      .toISOString()
      .slice(0, 10)
    return { start: startIso, end: endIso }
  }, [range])

  const obsQuery = useObservations(fieldId, start, end, Boolean(fieldId))
  const observations = obsQuery.data?.items ?? []

  const envLayers: P07EnvironmentLayer[] = catalog?.layers.environment ?? []
  const unavailableSeries = envLayers.filter((l) => !l.available)

  const grouped = useMemo(() => {
    const map = new Map<string, Observation[]>()
    for (const obs of observations) {
      if (!obs?.variable_code) continue
      const list = map.get(obs.variable_code) ?? []
      list.push(obs)
      map.set(obs.variable_code, list)
    }
    return map
  }, [observations])

  const precipAgg = useMemo(
    () => aggregateMonthly(grouped.get('precipitation') ?? [], 'sum'),
    [grouped],
  )
  const et0Agg = useMemo(
    () => aggregateMonthly(grouped.get('reference_et0') ?? [], 'sum'),
    [grouped],
  )
  const moistureAgg = useMemo(
    () => aggregateMonthly(grouped.get('soil_moisture_surface') ?? [], 'mean'),
    [grouped],
  )
  const tempAggByCode = useMemo(() => {
    const out = new Map<string, MonthlyAggregate[]>()
    for (const code of TEMP_VARIABLES) out.set(code, aggregateMonthly(grouped.get(code) ?? [], 'mean'))
    return out
  }, [grouped])

  const countObservations = (code: string): { count: number; first: string | null; last: string | null; excluded: number } => {
    const items = grouped.get(code) ?? []
    const first = items.reduce<string | null>(
      (acc, o) => (!acc || o.observed_at < acc ? o.observed_at : acc),
      null,
    )
    const last = items.reduce<string | null>(
      (acc, o) => (!acc || o.observed_at > acc ? o.observed_at : acc),
      null,
    )
    const excluded = items.filter((o) => o.value === null || !Number.isFinite(Number(o.value))).length
    return { count: items.length, first, last, excluded }
  }

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

  const rangeLabel = t(`environment.range${range}`)

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('environment.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('environment.subtitle')}</p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-stone-600" htmlFor="p07-env-range">
            {t('environment.rangeLabel')}
          </Label>
          <Select value={range} onValueChange={(v) => setRange(v as RangePreset)}>
            <SelectTrigger id="p07-env-range" className="h-9 w-44 bg-white">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="3m">{t('environment.range3m')}</SelectItem>
              <SelectItem value="6m">{t('environment.range6m')}</SelectItem>
              <SelectItem value="12m">{t('environment.range12m')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Badge variant="outline" className="mt-4 border-stone-300 bg-stone-50 font-normal text-stone-600" dir="ltr">
          {start} → {end}
        </Badge>
      </div>

      {catalogQuery.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartSkeletonCard />
          <ChartSkeletonCard />
        </div>
      ) : envLayers.length === 0 && observations.length === 0 ? (
        <EnvironmentEmptyState />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Monthly precipitation (sums of the daily series) */}
          <div className="lg:col-span-2">
            {grouped.has('precipitation') && precipAgg.length > 0 ? (
              <SeriesSection
                meta={
                  <SeriesMeta
                    count={countObservations('precipitation').count}
                    first={countObservations('precipitation').first}
                    last={countObservations('precipitation').last}
                    excluded={countObservations('precipitation').excluded}
                  />
                }
                gaps={missingMonths(precipAgg)}
                source={`${t('environment.sourceLine', { id: 'field', variable: 'precipitation' })} · ${rangeLabel}`}
              >
                <MonthlyBarChart
                  points={precipAgg.map((a) => ({ month: a.months[0], value: a.value }))}
                  unit="mm"
                  title={t('environment.precipTitle')}
                  description={t('environment.precipDesc')}
                  barLabel={t('environment.precipBar')}
                  emptyReason={t('environment.noRangeData')}
                />
              </SeriesSection>
            ) : (
              <SeriesSection
                meta={<SeriesMeta count={0} first={null} last={null} excluded={0} />}
                gaps={[]}
                source={`${t('environment.sourceLine', { id: 'field', variable: 'precipitation' })} · ${rangeLabel}`}
              >
                <Card className="border-stone-200 bg-white shadow-sm">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">{t('environment.precipTitle')}</CardTitle>
                    <CardDescription className="text-sm text-stone-500">
                      {t('environment.precipDesc')}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-stone-500">{t('environment.noRangeData')}</p>
                  </CardContent>
                </Card>
              </SeriesSection>
            )}
          </div>

          {/* Temperature lines (min/mean/max monthly means) */}
          <div className="lg:col-span-2">
            {TEMP_VARIABLES.some((code) => (tempAggByCode.get(code) ?? []).length > 0) ? (
              <SeriesSection
                meta={
                  <SeriesMeta
                    count={TEMP_VARIABLES.reduce((acc, code) => acc + countObservations(code).count, 0)}
                    first={countObservations('air_temperature_mean').first}
                    last={countObservations('air_temperature_mean').last}
                    excluded={TEMP_VARIABLES.reduce((acc, code) => acc + countObservations(code).excluded, 0)}
                  />
                }
                gaps={missingMonths(tempAggByCode.get('air_temperature_mean') ?? [])}
                source={`${t('environment.sourceLine', { id: 'field', variable: 'air_temperature_*' })} · ${rangeLabel}`}
              >
                <MultiLineChart
                  series={[
                    { key: 'min', label: t('environment.tempMin') },
                    { key: 'mean', label: t('environment.tempMean') },
                    { key: 'max', label: t('environment.tempMax') },
                  ]}
                  points={mergeMonthly(tempAggByCode)}
                  unit="°C"
                  title={t('environment.tempTitle')}
                  description={t('environment.tempDesc')}
                  emptyReason={t('environment.noRangeData')}
                />
              </SeriesSection>
            ) : (
              <NotAvailableCard
                title={t('environment.tempTitle')}
                desc={t('environment.tempDesc')}
                reason={findReason(envLayers, 'air_temperature_mean')}
              />
            )}
          </div>

          {/* Soil moisture line (monthly means) */}
          <div className="lg:col-span-2">
            {moistureAgg.length > 0 ? (
              <SeriesSection
                meta={
                  <SeriesMeta
                    count={countObservations('soil_moisture_surface').count}
                    first={countObservations('soil_moisture_surface').first}
                    last={countObservations('soil_moisture_surface').last}
                    excluded={countObservations('soil_moisture_surface').excluded}
                  />
                }
                gaps={missingMonths(moistureAgg)}
                source={`${t('environment.sourceLine', { id: 'field', variable: 'soil_moisture_surface' })} · ${rangeLabel}`}
              >
                <MultiLineChart
                  series={[{ key: 'moisture', label: t('environment.moistureLine') }]}
                  points={moistureAgg.map((a) => ({
                    date: a.months[0],
                    values: { moisture: a.value },
                  }))}
                  unit="m³/m³"
                  title={t('environment.moistureTitle')}
                  description={t('environment.moistureDesc')}
                  emptyReason={t('environment.noRangeData')}
                />
              </SeriesSection>
            ) : (
              <NotAvailableCard
                title={t('environment.moistureTitle')}
                desc={t('environment.moistureDesc')}
                reason={findReason(envLayers, 'soil_moisture_surface')}
              />
            )}
          </div>

          {/* ET0 monthly sums */}
          <div className="lg:col-span-2">
            {et0Agg.length > 0 ? (
              <SeriesSection
                meta={
                  <SeriesMeta
                    count={countObservations('reference_et0').count}
                    first={countObservations('reference_et0').first}
                    last={countObservations('reference_et0').last}
                    excluded={countObservations('reference_et0').excluded}
                  />
                }
                gaps={missingMonths(et0Agg)}
                source={`${t('environment.sourceLine', { id: 'field', variable: 'reference_et0' })} · ${rangeLabel}`}
              >
                <MonthlyBarChart
                  points={et0Agg.map((a) => ({ month: a.months[0], value: a.value }))}
                  unit="mm"
                  title={t('environment.et0Title')}
                  description={t('environment.et0Desc')}
                  barLabel={t('environment.et0Bar')}
                  emptyReason={t('environment.noRangeData')}
                />
              </SeriesSection>
            ) : (
              <NotAvailableCard
                title={t('environment.et0Title')}
                desc={t('environment.et0Desc')}
                reason={findReason(envLayers, 'reference_et0')}
              />
            )}
          </div>

          {/* Declared-but-not-ingested series: honest "not exposed yet" panel */}
          {unavailableSeries.length > 0 ? (
            <Alert className="border-stone-200 bg-stone-50 text-stone-700 lg:col-span-2">
              <AlertTitle className="text-sm font-semibold">{t('environment.notExposedTitle')}</AlertTitle>
              <AlertDescription className="text-sm text-stone-600">
                <p>{t('environment.notExposedIntro')}</p>
                <ul className="mt-1.5 list-inside list-disc space-y-1">
                  {unavailableSeries.map((layer) => (
                    <li key={layer.id}>
                      <span className="font-medium text-stone-700">{layer.label}</span>
                      {layer.unavailable_reason ? (
                        <span className="text-stone-500"> — {layer.unavailable_reason}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}

          <p className="text-[11px] text-stone-400 lg:col-span-2">
            {t('charts.source', {
              detail: t('environment.catalogSource', { id: 'field', version: catalog?.catalog_version ?? '—' }),
            })}
          </p>
        </div>
      )}
    </div>
  )
}

/** Merge the three temperature aggregates into one MultiLine point list. */
function mergeMonthly(
  tempAggByCode: Map<string, MonthlyAggregate[]>,
): { date: string; values: Record<string, number | null> }[] {
  const dates = new Set<string>()
  for (const agg of tempAggByCode.values()) {
    for (const a of agg) dates.add(a.months[0])
  }
  const sorted = [...dates].sort()
  const lookup = (code: string, month: string): number | null =>
    tempAggByCode.get(code)?.find((a) => a.months[0] === month)?.value ?? null
  return sorted.map((month) => ({
    date: month,
    values: {
      min: lookup('air_temperature_min', month),
      mean: lookup('air_temperature_mean', month),
      max: lookup('air_temperature_max', month),
    },
  }))
}

function findReason(layers: P07EnvironmentLayer[], code: string): string | null {
  return layers.find((l) => l.code === code)?.unavailable_reason ?? null
}

function NotAvailableCard({ title, desc, reason }: { title: string; desc: string; reason: string | null }) {
  const t = useTranslations('p07analytics')
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{desc}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex h-32 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 px-4 text-center">
          <p className="text-sm text-stone-500">
            {reason ? `${t('charts.noDataForPeriod')} (${reason})` : t('charts.noDataForPeriod')}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

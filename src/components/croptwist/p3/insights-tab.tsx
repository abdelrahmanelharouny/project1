'use client'

/**
 * P3 — Insights tab (executive dashboard). Every metric is rendered exactly
 * as the analytics API returns it: value, unit, provenance badge
 * (observed / model_derived / simulated / missing) and period. Missing data
 * renders an explicit "No data" chip — never a zero, never a fabricated
 * financial figure.
 *
 * NOTE on filters: the executive-dashboard endpoint supports farm_id and
 * season ONLY (it 400s on crop/date filters, by design). The crop input is
 therefore rendered disabled with an explanation instead of being sent.
 */

import { useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { Info } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, describeError } from '@/lib/api'
import { formatDay, formatDateTime, humanizeCode, pct } from '@/lib/format'
import { useFarms } from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import {
  getBenchmarks,
  getCommercialMetrics,
  getExecutiveDashboard,
  getFarmPerformance,
  listMyOrganizations,
  type AnalyticsMetric,
  type Provenance,
} from '@/lib/api-p3-commercial'

type T = ReturnType<typeof useTranslations>

// --------------------------------------------------------------- helpers

function InlineError({ err, t }: { err: unknown; t: T }) {
  const forbidden = err instanceof ApiError && err.status === 403
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-semibold">{forbidden ? t('errors.forbiddenTitle') : t('common.loadError')}</p>
      <p className="mt-1 text-xs leading-relaxed">
        {forbidden ? t('errors.forbiddenBody') : describeError(err).title}
      </p>
    </div>
  )
}

function NoOrgEmptyState({ t }: { t: T }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <p className="text-base font-semibold text-stone-900">{t('common.noOrgTitle')}</p>
        <p className="max-w-md text-sm text-stone-500">{t('common.noOrgBody')}</p>
        <Button
          className="mt-2 bg-emerald-700 text-white hover:bg-emerald-800"
          onClick={() => useCropTwistUi.getState().setActiveTab('team')}
        >
          {t('common.noOrgCta')}
        </Button>
      </CardContent>
    </Card>
  )
}

function provenanceClass(p: Provenance): string {
  switch (p) {
    case 'observed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800'
    case 'model_derived':
      return 'border-stone-300 bg-stone-100 text-stone-600'
    case 'simulated':
      return 'border-amber-200 bg-amber-50 text-amber-800'
    default:
      return 'border-stone-200 bg-stone-50 text-stone-400'
  }
}

function provenanceLabel(t: T, p: Provenance): string {
  switch (p) {
    case 'observed':
      return t('provenance.observed')
    case 'model_derived':
      return t('provenance.modelDerived')
    case 'simulated':
      return t('provenance.simulated')
    default:
      return t('provenance.missing')
  }
}

function provenanceTip(t: T, p: Provenance): string {
  switch (p) {
    case 'observed':
      return t('provenance.observedTip')
    case 'model_derived':
      return t('provenance.modelDerivedTip')
    case 'simulated':
      return t('provenance.simulatedTip')
    default:
      return t('provenance.missingTip')
  }
}

function metricLabel(t: T, metric: AnalyticsMetric): string {
  const map: Record<string, string> = {
    total_area_ha: 'metricTotalAreaHa',
    farm_count: 'metricFarmCount',
    field_count: 'metricFieldCount',
    active_crop_cycles: 'metricActiveCropCycles',
    observations_in_period: 'metricObservationsInPeriod',
    data_coverage: 'metricDataCoverage',
    water_volume_m3: 'metricWaterVolumeM3',
    water_cost: 'metricWaterCost',
    cost_per_hectare: 'metricCostPerHectare',
    yield: 'metricYield',
  }
  const key = map[metric.key]
  return key ? t(`insights.${key}`) : metric.label
}

function formatMetricValue(value: number, unit: string, locale: string): string {
  if (unit === 'ratio') return pct(value)
  const decimals = unit === 'count' ? 0 : 2
  return value.toLocaleString(locale, { maximumFractionDigits: decimals })
}

function NoDataChip({ t }: { t: T }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className="cursor-help border-dashed border-stone-300 bg-stone-50 text-stone-400">
          {t('common.noData')}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>
        <p>{t('common.noDataTip')}</p>
      </TooltipContent>
    </Tooltip>
  )
}

function ProvenanceBadge({ t, p }: { t: T; p: Provenance }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className={`cursor-help ${provenanceClass(p)}`}>
          {provenanceLabel(t, p)}
        </Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">
        <p>{provenanceTip(t, p)}</p>
      </TooltipContent>
    </Tooltip>
  )
}

function MetricTile({ t, metric, locale }: { t: T; metric: AnalyticsMetric; locale: string }) {
  const missing = metric.value === null || metric.provenance === 'missing'
  const period =
    metric.period.from || metric.period.to
      ? `${metric.period.from ? formatDay(metric.period.from) : '…'} — ${metric.period.to ? formatDay(metric.period.to) : '…'}`
      : null
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-stone-600">{metricLabel(t, metric)}</p>
        {metric.note ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" aria-label={t('common.note')} className="text-stone-400 hover:text-stone-600">
                <Info className="h-3.5 w-3.5" aria-hidden />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              <p>{metric.note}</p>
            </TooltipContent>
          </Tooltip>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {missing ? (
          <NoDataChip t={t} />
        ) : (
          <span className="text-xl font-semibold tabular-nums text-stone-900">
            {formatMetricValue(metric.value as number, metric.unit, locale)}
          </span>
        )}
        {!missing && metric.unit !== 'count' && metric.unit !== 'ratio' ? (
          <span className="text-xs text-stone-500">{metric.unit}</span>
        ) : null}
        <ProvenanceBadge t={t} p={missing ? 'missing' : metric.provenance} />
      </div>
      {period ? <p className="mt-1 text-[11px] text-stone-400">{period}</p> : null}
    </div>
  )
}

function defaultFrom(): string {
  const d = new Date()
  d.setDate(d.getDate() - 89)
  return d.toISOString().slice(0, 10)
}

function defaultTo(): string {
  return new Date().toISOString().slice(0, 10)
}

// --------------------------------------------------------------- component

export default function InsightsTab() {
  const t = useTranslations('p3b')
  const locale = useLocale()

  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listMyOrganizations,
    staleTime: 60_000,
    retry: 1,
  })
  const org = orgsQuery.data?.items[0] ?? null
  const orgId = org?.id ?? null

  const farmsQuery = useFarms(Boolean(orgId))

  // Applied filters (draft → Apply) — dashboard uses applied values only.
  const [applied, setApplied] = useState<{ farm: string | null; season: string; from: string; to: string }>({
    farm: null,
    season: '',
    from: defaultFrom(),
    to: defaultTo(),
  })
  const [draftFarm, setDraftFarm] = useState<string>('all')
  const [draftSeason, setDraftSeason] = useState('')
  const [draftFrom, setDraftFrom] = useState(defaultFrom())
  const [draftTo, setDraftTo] = useState(defaultTo())

  const applyFilters = () => {
    setApplied({
      farm: draftFarm === 'all' ? null : draftFarm,
      season: draftSeason.trim(),
      from: draftFrom,
      to: draftTo,
    })
  }
  const resetFilters = () => {
    setDraftFarm('all')
    setDraftSeason('')
    setDraftFrom(defaultFrom())
    setDraftTo(defaultTo())
    setApplied({ farm: null, season: '', from: defaultFrom(), to: defaultTo() })
  }

  const dashboardQuery = useQuery({
    queryKey: ['p3-exec-dashboard', orgId, applied.farm, applied.season],
    queryFn: () =>
      getExecutiveDashboard({
        organization_id: orgId,
        farm_id: applied.farm,
        season: applied.season || null,
      }),
    enabled: Boolean(orgId),
    staleTime: 30_000,
    retry: 1,
  })

  const perfQuery = useQuery({
    queryKey: ['p3-farm-performance', applied.farm, applied.from, applied.to],
    queryFn: () =>
      getFarmPerformance(applied.farm as string, { date_from: applied.from, date_to: applied.to }),
    enabled: Boolean(applied.farm),
    staleTime: 30_000,
    retry: 1,
  })

  // Commercial assumptions are user-supplied; committed on blur (not per keystroke).
  const [waterPrice, setWaterPrice] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [waterPriceApplied, setWaterPriceApplied] = useState<number | null>(null)
  const [currencyApplied, setCurrencyApplied] = useState('USD')
  const commercialQuery = useQuery({
    queryKey: ['p3-commercial', applied.farm, applied.from, applied.to, waterPriceApplied, currencyApplied],
    queryFn: () =>
      getCommercialMetrics(applied.farm as string, {
        date_from: applied.from,
        date_to: applied.to,
        water_price_per_m3: waterPriceApplied,
        currency: currencyApplied,
      }),
    enabled: Boolean(applied.farm),
    staleTime: 30_000,
    retry: 1,
  })

  const [benchScope, setBenchScope] = useState<'farm' | 'field'>('farm')
  const benchQuery = useQuery({
    queryKey: ['p3-benchmarks', orgId, benchScope, applied.from, applied.to],
    queryFn: () =>
      getBenchmarks({ scope: benchScope, date_from: applied.from, date_to: applied.to, organization_id: orgId }),
    enabled: Boolean(orgId),
    staleTime: 30_000,
    retry: 1,
  })

  const cropRows = useMemo(
    () => (dashboardQuery.data?.crop_distribution ?? []).map((e) => ({ name: e.crop, cycles: e.cycles })),
    [dashboardQuery.data],
  )
  const chartConfig = { cycles: { label: t('insights.cycles'), color: '#047857' } } satisfies ChartConfig

  if (orgsQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!org) return <NoOrgEmptyState t={t} />

  const dash = dashboardQuery.data

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('insights.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('insights.intro')}</p>
      </header>

      {/* Filters */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-5 text-sm">
          <div className="flex min-w-40 flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p3-ins-farm">
              {t('insights.filtersFarm')}
            </Label>
            <Select value={draftFarm} onValueChange={setDraftFarm}>
              <SelectTrigger id="p3-ins-farm" className="h-9 w-full min-w-40 bg-white sm:w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('insights.filtersAllFarms')}</SelectItem>
                {(farmsQuery.data?.items ?? []).map((farm) => (
                  <SelectItem key={farm.id} value={farm.id}>
                    {farm.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p3-ins-season">
              {t('insights.filtersSeason')}
            </Label>
            <Input
              id="p3-ins-season"
              className="h-9 w-36"
              value={draftSeason}
              onChange={(e) => setDraftSeason(e.target.value)}
              placeholder={t('insights.filtersSeasonPh')}
            />
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex flex-col gap-1">
                <Label className="text-xs text-stone-400" htmlFor="p3-ins-crop">
                  {t('insights.filtersCrop')}
                </Label>
                <Input id="p3-ins-crop" className="h-9 w-36" disabled placeholder="—" />
              </div>
            </TooltipTrigger>
            <TooltipContent className="max-w-64">
              <p>{t('insights.filtersCropDisabled')}</p>
            </TooltipContent>
          </Tooltip>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p3-ins-from">
              {t('common.from')}
            </Label>
            <Input
              id="p3-ins-from"
              className="h-9 w-36"
              type="date"
              value={draftFrom}
              onChange={(e) => setDraftFrom(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-stone-600" htmlFor="p3-ins-to">
              {t('common.to')}
            </Label>
            <Input
              id="p3-ins-to"
              className="h-9 w-36"
              type="date"
              value={draftTo}
              onChange={(e) => setDraftTo(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" className="bg-emerald-700 text-white hover:bg-emerald-800" onClick={applyFilters}>
              {t('common.apply')}
            </Button>
            <Button size="sm" variant="ghost" onClick={resetFilters}>
              {t('common.reset')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {dashboardQuery.isError ? (
        <InlineError err={dashboardQuery.error} t={t} />
      ) : dashboardQuery.isLoading ? (
        <Skeleton className="h-56 w-full" />
      ) : dash ? (
        <>
          {/* KPI row */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t('insights.kpiTitle')}</CardTitle>
              <CardDescription className="text-xs text-stone-500">
                {t('insights.generatedAt', { time: formatDateTime(dash.generated_at) })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {dash.metrics.map((m) => (
                  <MetricTile key={m.key} t={t} metric={m} locale={locale} />
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Crop distribution */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t('insights.cropDistTitle')}</CardTitle>
                <CardDescription className="text-sm text-stone-500">{t('insights.cropDistDesc')}</CardDescription>
              </CardHeader>
              <CardContent>
                {dash.crop_distribution === null || cropRows.length === 0 ? (
                  <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
                    <NoDataChip t={t} />
                  </div>
                ) : (
                  <ChartContainer config={chartConfig} className="h-56 w-full">
                    <BarChart data={cropRows} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
                      <YAxis type="category" dataKey="name" width={140} tickLine={false} axisLine={false} />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar dataKey="cycles" fill="var(--color-cycles)" radius={[0, 4, 4, 0]} barSize={14} />
                    </BarChart>
                  </ChartContainer>
                )}
              </CardContent>
            </Card>

            {/* Recommendations + adoption */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t('insights.recsTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {dash.recommendations.total_ever === null && dash.recommendations.active === null ? (
                  <NoDataChip t={t} />
                ) : (
                  <div className="flex flex-wrap gap-x-6 gap-y-1">
                    <p className="text-stone-600">
                      {t('insights.recsTotal')}:{' '}
                      <span className="font-semibold text-stone-900">{dash.recommendations.total_ever ?? '—'}</span>
                    </p>
                    <p className="text-stone-600">
                      {t('insights.recsActive')}:{' '}
                      <span className="font-semibold text-stone-900">{dash.recommendations.active ?? '—'}</span>
                    </p>
                  </div>
                )}
                {dash.recommendations.active_by_domain ? (
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(dash.recommendations.active_by_domain).map(([domain, n]) => (
                      <Badge key={domain} variant="outline" className="border-stone-200 bg-stone-50 text-stone-600">
                        {humanizeCode(domain)}: {n}
                      </Badge>
                    ))}
                  </div>
                ) : null}

                <div className="border-t border-stone-100 pt-3">
                  <p className="mb-1.5 text-xs font-medium text-stone-600">{t('insights.adoptionTitle')}</p>
                  {dash.adoption.provenance === 'missing' ? (
                    <div className="space-y-1.5">
                      <NoDataChip t={t} />
                      {dash.adoption.note ? <p className="text-xs text-stone-400">{dash.adoption.note}</p> : null}
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-stone-600">{t('insights.adoptionRate')}:</span>
                        <span className="text-sm font-semibold text-stone-900">
                          {dash.adoption.acceptance_rate !== null && dash.adoption.acceptance_rate !== undefined
                            ? pct(dash.adoption.acceptance_rate)
                            : '—'}
                        </span>
                        <ProvenanceBadge t={t} p={dash.adoption.provenance} />
                      </div>
                      {dash.adoption.by_state ? (
                        <div className="flex flex-wrap gap-1.5">
                          <span className="text-xs text-stone-500">{t('insights.adoptionByState')}:</span>
                          {Object.entries(dash.adoption.by_state).map(([state, n]) => (
                            <Badge key={state} variant="outline" className="border-stone-200 bg-stone-50 text-stone-600">
                              {humanizeCode(state)}: {n}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                      {dash.adoption.note ? <p className="text-xs text-stone-400">{dash.adoption.note}</p> : null}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Data freshness */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t('insights.freshnessTitle')}</CardTitle>
            </CardHeader>
            <CardContent>
              {dash.data_freshness.variables.length === 0 ? (
                <NoDataChip t={t} />
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {dash.data_freshness.variables.map((v) => (
                    <li
                      key={v.variable}
                      className="flex items-center justify-between gap-2 rounded-md border border-stone-100 bg-stone-50/50 px-3 py-2 text-sm"
                    >
                      <span className="text-stone-700">{humanizeCode(v.variable)}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs tabular-nums text-stone-500">
                          {v.observations > 0 ? `${v.observations} · ${formatDay(v.last_observed_at)}` : '0'}
                        </span>
                        {v.status === 'fresh' ? (
                          <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-800">
                            {t('insights.statusFresh')}
                          </Badge>
                        ) : v.status === 'stale' ? (
                          <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">
                            {t('insights.statusStale')}
                          </Badge>
                        ) : v.status === 'very_stale' ? (
                          <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700">
                            {t('insights.statusVeryStale')}
                          </Badge>
                        ) : (
                          <NoDataChip t={t} />
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}

      {/* Farm performance */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('insights.perfTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('insights.perfDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!applied.farm ? (
            <p className="text-sm text-stone-500">{t('insights.selectFarmHint')}</p>
          ) : perfQuery.isLoading ? (
            <Skeleton className="h-48 w-full" />
          ) : perfQuery.isError ? (
            <InlineError err={perfQuery.error} t={t} />
          ) : perfQuery.data ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {perfQuery.data.metrics.map((m) => (
                  <MetricTile key={m.key} t={t} metric={m} locale={locale} />
                ))}
              </div>

              {/* Field comparison */}
              {perfQuery.data.fields.length > 0 ? (
                <>
                  <div className="hidden overflow-x-auto md:block">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t('insights.perfField')}</TableHead>
                          <TableHead>{t('insights.perfArea')}</TableHead>
                          <TableHead>{t('insights.perfObs')}</TableHead>
                          <TableHead>{t('insights.perfRecs')}</TableHead>
                          <TableHead>{t('insights.perfCycles')}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {perfQuery.data.fields.map((f) => (
                          <TableRow key={f.field_id}>
                            <TableCell className="text-sm font-medium text-stone-900">{f.name}</TableCell>
                            <TableCell className="text-xs tabular-nums">{f.area_ha}</TableCell>
                            <TableCell className="text-xs tabular-nums">{f.observations_in_period}</TableCell>
                            <TableCell className="text-xs tabular-nums">{f.active_recommendations}</TableCell>
                            <TableCell className="text-xs tabular-nums">{f.crop_cycles_started_in_period}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  <div className="space-y-2 md:hidden">
                    {perfQuery.data.fields.map((f) => (
                      <div key={f.field_id} className="rounded-lg border border-stone-200 bg-white p-3 text-sm">
                        <p className="font-medium text-stone-900">{f.name}</p>
                        <p className="mt-1 text-xs text-stone-600">
                          {t('insights.perfArea')}: {f.area_ha} · {t('insights.perfObs')}: {f.observations_in_period}
                        </p>
                        <p className="text-xs text-stone-600">
                          {t('insights.perfRecs')}: {f.active_recommendations} · {t('insights.perfCycles')}:{' '}
                          {f.crop_cycles_started_in_period}
                        </p>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}

              {/* Water volumes */}
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-stone-200 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-stone-600">{t('insights.waterPrecip')}</p>
                    <ProvenanceBadge t={t} p={perfQuery.data.water_usage.precipitation.provenance} />
                  </div>
                  {perfQuery.data.water_usage.precipitation.total_volume_m3 !== undefined ? (
                    <p className="mt-1 text-lg font-semibold tabular-nums text-stone-900">
                      {perfQuery.data.water_usage.precipitation.total_volume_m3.toLocaleString(locale, {
                        maximumFractionDigits: 1,
                      })}{' '}
                      <span className="text-xs font-normal text-stone-500">m³</span>
                    </p>
                  ) : (
                    <div className="mt-2">
                      <NoDataChip t={t} />
                    </div>
                  )}
                  {perfQuery.data.water_usage.precipitation.note ? (
                    <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
                      {perfQuery.data.water_usage.precipitation.note}
                    </p>
                  ) : null}
                </div>
                <div className="rounded-lg border border-stone-200 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-stone-600">{t('insights.waterIrrigation')}</p>
                    <ProvenanceBadge t={t} p={perfQuery.data.water_usage.irrigation.provenance} />
                  </div>
                  <div className="mt-2">
                    <NoDataChip t={t} />
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
                    {perfQuery.data.water_usage.irrigation.note}
                  </p>
                </div>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>

      {/* Commercial metrics */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('insights.commercialTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('insights.commercialDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!applied.farm ? (
            <p className="text-sm text-stone-500">{t('insights.selectFarmHint')}</p>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                  <Label className="text-xs text-stone-600" htmlFor="p3-ins-water-price">
                    {t('insights.waterPriceLabel')}
                  </Label>
                  <Input
                    id="p3-ins-water-price"
                    className="h-9 w-36"
                    type="number"
                    min="0"
                    step="0.01"
                    value={waterPrice}
                    onChange={(e) => setWaterPrice(e.target.value)}
                    onBlur={() => {
                      const n = Number(waterPrice)
                      setWaterPriceApplied(waterPrice.trim() !== '' && Number.isFinite(n) && n >= 0 ? n : null)
                    }}
                    placeholder={t('insights.waterPricePh')}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label className="text-xs text-stone-600" htmlFor="p3-ins-currency">
                    {t('insights.currencyLabel')}
                  </Label>
                  <Input
                    id="p3-ins-currency"
                    className="h-9 w-24"
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                    onBlur={() => setCurrencyApplied(currency.trim() || 'USD')}
                  />
                </div>
              </div>
              {commercialQuery.isLoading ? (
                <Skeleton className="h-40 w-full" />
              ) : commercialQuery.isError ? (
                <InlineError err={commercialQuery.error} t={t} />
              ) : commercialQuery.data ? (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {commercialQuery.data.metrics.map((m) => (
                      <MetricTile key={m.key} t={t} metric={m} locale={locale} />
                    ))}
                  </div>
                  <Collapsible>
                    <CollapsibleTrigger className="text-xs font-medium text-emerald-800 underline-offset-2 hover:underline">
                      {t('insights.assumptions')}
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="mt-2 space-y-1 rounded-md border border-stone-200 bg-stone-50/60 p-3">
                        <p className="text-[11px] text-stone-400">{t('insights.assumptionsHint')}</p>
                        {Object.entries(commercialQuery.data.assumptions).map(([k, v]) => (
                          <p key={k} className="font-mono text-xs text-stone-600" dir="ltr">
                            {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                          </p>
                        ))}
                        <p className="pt-1 text-xs leading-relaxed text-stone-500">
                          {commercialQuery.data.honesty_note}
                        </p>
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                </>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      {/* Benchmarks */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">{t('insights.benchmarksTitle')}</CardTitle>
              <CardDescription className="text-sm text-stone-500">{t('insights.benchmarksDesc')}</CardDescription>
            </div>
            <Select value={benchScope} onValueChange={(v) => setBenchScope(v as 'farm' | 'field')}>
              <SelectTrigger className="h-9 w-40 bg-white" aria-label={t('insights.benchmarksTitle')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="farm">{t('insights.scopeFarm')}</SelectItem>
                <SelectItem value="field">{t('insights.scopeField')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {benchQuery.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : benchQuery.isError ? (
            <InlineError err={benchQuery.error} t={t} />
          ) : benchQuery.data ? (
            <>
              <p className="text-[11px] text-stone-400">
                {formatDay(benchQuery.data.period.from)} — {formatDay(benchQuery.data.period.to)}
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('insights.benchName')}</TableHead>
                      {benchQuery.data.scope === 'field' ? <TableHead>{t('insights.benchFarm')}</TableHead> : null}
                      <TableHead>{t('insights.benchArea')}</TableHead>
                      {benchQuery.data.scope === 'farm' ? <TableHead>{t('insights.benchFields')}</TableHead> : null}
                      <TableHead>{t('insights.benchRecs')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {benchQuery.data.entries.map((e) => (
                      <TableRow key={e.id}>
                        <TableCell className="text-sm font-medium text-stone-900">{e.name}</TableCell>
                        {benchQuery.data?.scope === 'field' ? (
                          <TableCell className="text-xs">{e.farm ?? '—'}</TableCell>
                        ) : null}
                        <TableCell className="text-xs tabular-nums">{e.area_ha}</TableCell>
                        {benchQuery.data?.scope === 'farm' ? (
                          <TableCell className="text-xs tabular-nums">{e.field_count ?? '—'}</TableCell>
                        ) : null}
                        <TableCell className="text-xs tabular-nums">{e.active_recommendations}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {Object.keys(benchQuery.data.metric_definitions).length > 0 ? (
                <div>
                  <p className="text-xs font-medium text-stone-600">{t('insights.metricDefinitions')}</p>
                  <ul className="mt-1 space-y-0.5">
                    {Object.entries(benchQuery.data.metric_definitions).map(([k, v]) => (
                      <li key={k} className="text-[11px] text-stone-400">
                        {k}: {v}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {benchQuery.data.compatibility_note ? (
                <p className="text-[11px] leading-relaxed text-stone-400">{benchQuery.data.compatibility_note}</p>
              ) : null}
              <div className="rounded-md border border-stone-200 bg-stone-50/60 p-3">
                <p className="text-xs font-medium text-stone-600">{t('insights.crossOrgTitle')}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-stone-500">{t('insights.crossOrgBody')}</p>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

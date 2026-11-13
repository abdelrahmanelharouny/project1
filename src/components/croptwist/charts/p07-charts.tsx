'use client'

/**
 * P07 analytics chart kit — one visual language for every Reports & Analytics
 * chart. Every component:
 *   - renders a titled Card with an explicit unit chip and a source line
 *     (the API endpoint/processing version passed by the caller — never invented);
 *   - shows a shape-preserving skeleton while loading;
 *   - shows an honest empty state (`data-empty`) with a REASON when the
 *     backend returned nothing — never a fabricated series;
 *   - keeps a FIXED height (h-48/h-64) to avoid layout shift, mobile-first;
 *   - wraps numbers/axes in dir="ltr" so Arabic (RTL) charts stay readable.
 *
 * Colors come from the existing chart palette variables (--chart-1..5 mapped
 * through ChartConfig). No indigo/blue is introduced anywhere.
 */

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from 'recharts'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import {
  buildZoneHeatmapGrid,
  formatBinLabel,
  heatmapCellColors,
  type ZoneKey,
} from '@/lib/analytics/p07-utils'
import type {
  P07Comparison,
  P07HistogramBin,
  P07ZoneHistoryEntry,
} from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// Shared shell pieces
// ---------------------------------------------------------------------------

interface ChartShellProps {
  title: string
  description?: string
  unit?: string | null
  source?: string | null
  loading?: boolean
  footer?: React.ReactNode
  children: React.ReactNode
}

function ChartShell({ title, description, unit, source, loading, footer, children }: ChartShellProps) {
  const t = useTranslations('p07analytics')
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          {unit ? (
            <Badge variant="outline" className="border-stone-300 bg-stone-50 font-normal text-stone-600">
              {unit}
            </Badge>
          ) : null}
        </div>
        {description ? <CardDescription className="text-sm text-stone-500">{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>
        {loading ? (
          <ChartSkeleton />
        ) : (
          children
        )}
      </CardContent>
      {source || footer ? (
        <CardFooter className="justify-start border-t border-stone-100 py-2">
          <div className="w-full space-y-1">
            {source ? (
              <p className="text-[11px] leading-snug text-stone-400">{t('charts.source', { detail: source })}</p>
            ) : null}
            {footer}
          </div>
        </CardFooter>
      ) : null}
    </Card>
  )
}

function ChartSkeleton() {
  return (
    <div className="space-y-2" aria-hidden>
      <Skeleton className="h-64 w-full" />
    </div>
  )
}

/** Honest empty state — always carries the reason, marked data-empty. */
export function ChartEmpty({ reason, height = 'h-64' }: { reason: string; height?: string }) {
  return (
    <div
      data-empty="true"
      role="status"
      aria-live="polite"
      className={`flex ${height} items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 px-4 text-center`}
    >
      <p className="text-sm text-stone-500">{reason}</p>
    </div>
  )
}

/** Percent-formatted tooltip/axis helper for share-based series (0..1 → %). */
function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

/** Index-value formatting: stable decimals, never locale-dependent drift. */
function formatIndexValue(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

// ---------------------------------------------------------------------------
// HistogramChart — P07Distribution.histogram
// ---------------------------------------------------------------------------

export interface HistogramChartProps {
  bins: P07HistogramBin[] | null | undefined
  documentedRange?: readonly [number, number] | null
  proportionOutOfRange?: number | null
  title: string
  description?: string
  unit?: string | null
  source?: string | null
  loading?: boolean
  emptyReason?: string
}

export function HistogramChart({
  bins,
  documentedRange,
  proportionOutOfRange,
  title,
  description,
  unit,
  source,
  loading = false,
  emptyReason,
}: HistogramChartProps) {
  const t = useTranslations('p07analytics')
  const data = useMemo(
    () =>
      (bins ?? []).map((bin, i) => ({
        key: `${i}`,
        label: formatBinLabel(bin),
        share: bin.share,
        pixels: bin.pixels,
      })),
    [bins],
  )
  const empty = emptyReason ?? t('charts.noDataForPeriod')
  const footer = (
    <p className="text-[11px] leading-snug text-stone-500">
      {t('charts.histogramFooter', {
        range: documentedRange ? `${documentedRange[0]} … ${documentedRange[1]}` : '—',
        outOfRange: formatShare(proportionOutOfRange ?? null),
      })}
    </p>
  )

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading} footer={footer}>
      {data.length === 0 ? (
        <ChartEmpty reason={empty} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{
              share: { label: t('charts.pixelShare'), color: 'var(--chart-2)' },
            } satisfies ChartConfig}
            className="h-64 w-full"
          >
            <BarChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                minTickGap={4}
                interval="preserveStartEnd"
                fontSize={10}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={40}
                fontSize={10}
                tickFormatter={(value: number) => formatShare(value)}
              />
              <ChartTooltip
                cursor={{ fill: 'var(--color-stone-100, #f5f5f4)' }}
                content={
                  <ChartTooltipContent
                    labelKey="label"
                    formatter={(value, name, item) => {
                      const pixels = (item?.payload as { pixels?: number } | undefined)?.pixels
                      return (
                        <div className="grid w-full gap-1">
                          <span className="text-muted-foreground">{t('charts.pixelShare')}</span>
                          <span className="font-mono font-medium tabular-nums">{formatShare(Number(value))}</span>
                          <span className="text-muted-foreground">{t('charts.pixels')}</span>
                          <span className="font-mono font-medium tabular-nums">
                            {typeof pixels === 'number' ? pixels.toLocaleString() : '—'}
                          </span>
                        </div>
                      )
                    }}
                    // name is unused because the formatter renders labeled rows
                    hideIndicator
                    hideLabel
                  />
                }
              />
              <Bar dataKey="share" fill="var(--color-share)" radius={[3, 3, 0, 0]} name={t('charts.pixelShare')} />
            </BarChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// BoxPlotChart — percentiles rendered as a horizontal box + whiskers
// (stacked transparent/base/box/whisker segments; recharts has no native boxplot)
// ---------------------------------------------------------------------------

export interface BoxPlotPercentiles {
  p5: number | null
  p25?: number | null
  median: number | null
  p75?: number | null
  p95: number | null
  std?: number | null
  mean?: number | null
}

export interface BoxPlotChartProps {
  percentiles: BoxPlotPercentiles | null | undefined
  label?: string
  documentedRange?: readonly [number, number] | null
  title: string
  description?: string
  unit?: string | null
  source?: string | null
  loading?: boolean
  emptyReason?: string
}

export function BoxPlotChart({
  percentiles,
  label,
  documentedRange,
  title,
  description,
  unit,
  source,
  loading = false,
  emptyReason,
}: BoxPlotChartProps) {
  const t = useTranslations('p07analytics')
  const p = percentiles
  const usable =
    p &&
    Number.isFinite(Number(p.p5)) &&
    Number.isFinite(Number(p.p95)) &&
    Number(p.p95) >= Number(p.p5)

  const data = useMemo(() => {
    if (!p || !usable) return []
    const p5 = Number(p.p5)
    const p95 = Number(p.p95)
    const p25 = p.p25 !== null && p.p25 !== undefined && Number.isFinite(Number(p.p25)) ? Number(p.p25) : p5
    const p75 = p.p75 !== null && p.p75 !== undefined && Number.isFinite(Number(p.p75)) ? Number(p.p75) : p95
    const boxLow = Math.min(Math.max(p25, p5), p95)
    const boxHigh = Math.min(Math.max(p75, p5), p95)
    return [
      {
        name: label ?? t('charts.percentileDistribution'),
        base: p5,
        whiskerLow: Math.max(0, boxLow - p5),
        box: Math.max(0, boxHigh - boxLow),
        whiskerHigh: Math.max(0, p95 - boxHigh),
      },
    ]
  }, [p, usable, label, t])

  const domain = useMemo<[number, number] | undefined>(() => {
    if (documentedRange && Number.isFinite(documentedRange[0]) && Number.isFinite(documentedRange[1])) {
      return [documentedRange[0], documentedRange[1]]
    }
    return undefined // recharts auto-domain — never a hand-picked fake range
  }, [documentedRange])

  const tooltip = useMemo(() => {
    if (!p) return null
    return (
      <ChartTooltip
        content={
          <ChartTooltipContent
            hideIndicator
            hideLabel
            formatter={() => (
              <div className="grid w-full gap-0.5">
                {(
                  [
                    ['p95', p.p95],
                    ['p75', p.p75 ?? null],
                    ['median', p.median],
                    ['mean', p.mean ?? null],
                    ['p25', p.p25 ?? null],
                    ['p5', p.p5],
                    ['std', p.std ?? null],
                  ] as [string, number | null][]
                ).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-4">
                    <span className="text-muted-foreground">{t(`charts.percentile_${key}`)}</span>
                    <span className="font-mono font-medium tabular-nums">{formatIndexValue(value)}</span>
                  </div>
                ))}
              </div>
            )}
          />
        }
      />
    )
  }, [p, t])

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading}>
      {!usable ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{
              whisker: { label: t('charts.whisker'), color: 'var(--chart-3)' },
              box: { label: t('charts.iqr'), color: 'var(--chart-2)' },
            } satisfies ChartConfig}
            className="h-48 w-full"
          >
            <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis
                type="number"
                domain={domain}
                tickLine={false}
                axisLine={false}
                fontSize={10}
                tickFormatter={(value: number) => formatIndexValue(value, 2)}
              />
              <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} width={90} fontSize={11} />
              {tooltip}
              {/* base + whiskers transparent-stacked so the box reads as one bar */}
              <Bar dataKey="base" stackId="bp" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="whiskerLow" stackId="bp" fill="var(--chart-3)" fillOpacity={0.45} radius={[3, 0, 0, 3]} />
              <Bar dataKey="box" stackId="bp" fill="var(--chart-2)" fillOpacity={0.9} />
              <Bar
                dataKey="whiskerHigh"
                stackId="bp"
                fill="var(--chart-3)"
                fillOpacity={0.45}
                radius={[0, 3, 3, 0]}
              />
              {p?.median !== null && p?.median !== undefined && Number.isFinite(Number(p.median)) ? (
                <ReferenceLine
                  x={Number(p.median)}
                  stroke="var(--chart-1)"
                  strokeWidth={2}
                  label={{ value: t('charts.percentile_median'), position: 'top', fontSize: 10 }}
                />
              ) : null}
              {p?.mean !== null &&
              p?.mean !== undefined &&
              Number.isFinite(Number(p.mean)) &&
              Number(p.mean) !== Number(p.median) ? (
                <ReferenceLine
                  x={Number(p.mean)}
                  stroke="var(--chart-3)"
                  strokeDasharray="4 3"
                  label={{ value: t('charts.percentile_mean'), position: 'bottom', fontSize: 10 }}
                />
              ) : null}
            </BarChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// ScatterComparisonChart — index-vs-index / period-vs-period points
// ---------------------------------------------------------------------------

export interface ScatterPoint {
  x: number | null
  y: number | null
  label?: string
}

export interface ScatterComparisonChartProps {
  points: ScatterPoint[] | null | undefined
  xLabel: string
  yLabel: string
  unit?: string | null
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  /** Identity (y = x) reference — pass true ONLY when both axes share the same index + unit. */
  showDiagonal?: boolean
}

export function ScatterComparisonChart({
  points,
  xLabel,
  yLabel,
  unit,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  showDiagonal = false,
}: ScatterComparisonChartProps) {
  const t = useTranslations('p07analytics')
  const data = useMemo(
    () =>
      (points ?? []).filter(
        (pt) => pt && pt.x !== null && pt.y !== null && Number.isFinite(Number(pt.x)) && Number.isFinite(Number(pt.y)),
      ),
    [points],
  )

  const diagSegment = useMemo(() => {
    if (!showDiagonal || data.length === 0) return null
    let lo = Number.POSITIVE_INFINITY
    let hi = Number.NEGATIVE_INFINITY
    for (const pt of data) {
      lo = Math.min(lo, Number(pt.x), Number(pt.y))
      hi = Math.max(hi, Number(pt.x), Number(pt.y))
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
    return [
      { x: lo, y: lo },
      { x: hi, y: hi },
    ]
  }, [showDiagonal, data])

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading}>
      {data.length === 0 ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{
              point: { label: yLabel, color: 'var(--chart-2)' },
            } satisfies ChartConfig}
            className="h-64 w-full"
          >
            <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="x"
                name={xLabel}
                tickLine={false}
                axisLine={false}
                fontSize={10}
                tickFormatter={(value: number) => formatIndexValue(value, 2)}
                label={{ value: xLabel, position: 'insideBottom', offset: -2, fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name={yLabel}
                tickLine={false}
                axisLine={false}
                width={44}
                fontSize={10}
                tickFormatter={(value: number) => formatIndexValue(value, 2)}
              />
              <ChartTooltip
                cursor={{ strokeDasharray: '3 3' }}
                content={
                  <ChartTooltipContent
                    hideLabel
                    hideIndicator
                    formatter={(_, __, item) => {
                      const payload = (item?.payload as { x?: number; y?: number; label?: string } | undefined) ?? {}
                      return (
                        <div className="grid w-full gap-0.5">
                          {payload.label ? (
                            <span className="text-muted-foreground">{payload.label}</span>
                          ) : null}
                          <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">{xLabel}</span>
                            <span className="font-mono font-medium tabular-nums">
                              {formatIndexValue(payload.x ?? null)}
                            </span>
                          </div>
                          <div className="flex justify-between gap-4">
                            <span className="text-muted-foreground">{yLabel}</span>
                            <span className="font-mono font-medium tabular-nums">
                              {formatIndexValue(payload.y ?? null)}
                            </span>
                          </div>
                        </div>
                      )
                    }}
                  />
                }
              />
              {diagSegment ? (
                <ReferenceLine
                  segment={diagSegment}
                  stroke="var(--chart-3)"
                  strokeDasharray="4 4"
                  label={{ value: t('charts.identityLine'), position: 'insideBottomLeft', fontSize: 10 }}
                />
              ) : null}
              <Scatter data={data} fill="var(--color-point)" fillOpacity={0.75} />
            </ScatterChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// ZoneHeatmap — CSS grid heatmap over zone_history (NOT recharts)
// ---------------------------------------------------------------------------

export interface ZoneHeatmapProps {
  zoneHistory: P07ZoneHistoryEntry[] | null | undefined
  documentedRange?: readonly [number, number] | null
  zoneLabels: Record<ZoneKey, string>
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  /** Extra honesty note under the legend (e.g. statistical-not-agronomic). */
  note?: string
}

export function ZoneHeatmap({
  zoneHistory,
  documentedRange,
  zoneLabels,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  note,
}: ZoneHeatmapProps) {
  const t = useTranslations('p07analytics')
  const grid = useMemo(() => buildZoneHeatmapGrid(zoneHistory, documentedRange), [zoneHistory, documentedRange])
  const empty = emptyReason ?? t('charts.noDataForPeriod')

  return (
    <ChartShell title={title} description={description} source={source} loading={loading}>
      {grid.dates.length === 0 ? (
        <ChartEmpty reason={empty} height="h-48" />
      ) : (
        <div className="space-y-3">
          <div dir="ltr" className="overflow-x-auto pb-1">
            <table className="border-collapse text-xs">
              <caption className="sr-only">{title}</caption>
              <thead>
                <tr>
                  <th scope="col" className="pe-2 text-start font-medium text-stone-500" />
                  {grid.dates.map((date) => (
                    <th
                      key={date}
                      scope="col"
                      className="px-1 pb-1 text-start font-normal text-stone-400"
                    >
                      {date.slice(0, 10)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {grid.rows.map((row) => (
                  <tr key={row[0]?.zone}>
                    <th scope="row" className="pe-2 text-start font-medium text-stone-600">
                      {zoneLabels[row[0]?.zone] ?? row[0]?.zone}
                    </th>
                    {row.map((cell) => {
                      const colors = heatmapCellColors(cell.intensity)
                      return (
                        <td key={`${cell.zone}-${cell.date}`} className="p-0.5">
                          <div
                            className="flex h-10 min-w-14 items-center justify-center rounded-md border border-stone-200/70 px-1"
                            style={{ background: colors.background }}
                            title={`${zoneLabels[cell.zone]} · ${cell.date.slice(0, 10)}`}
                            aria-label={`${zoneLabels[cell.zone]} ${cell.date.slice(0, 10)}: ${
                              cell.value === null ? t('charts.noDataCell') : formatIndexValue(cell.value)
                            }`}
                          >
                            {/* value as text at md+ so color is never the only signal */}
                            <span
                              className="hidden font-mono text-[11px] tabular-nums md:inline"
                              style={{ color: colors.text }}
                            >
                              {cell.value === null ? '—' : formatIndexValue(cell.value, 2)}
                            </span>
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-stone-500">
            <span>{t('charts.legendLow')}</span>
            <span
              aria-hidden
              className="h-3 w-24 rounded-full"
              style={{
                background: `linear-gradient(to right, ${heatmapCellColors(0).background}, ${
                  heatmapCellColors(1).background
                })`,
              }}
            />
            <span>{t('charts.legendHigh')}</span>
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-3 w-3 rounded border border-stone-300"
                style={{ background: heatmapCellColors(null).background }}
              />
              {t('charts.noDataCell')}
            </span>
            <span>{t('charts.legendRange', {
              range: documentedRange ? `${documentedRange[0]} … ${documentedRange[1]}` : '—',
            })}</span>
          </div>
          {note ? <p className="text-[11px] leading-snug text-stone-500">{note}</p> : null}
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// ComparisonDeltaChart — zone mean deltas (side A vs side B + delta)
// ---------------------------------------------------------------------------

export interface ComparisonDeltaChartProps {
  zoneDeltas: P07Comparison['zone_deltas'] | null | undefined
  unit?: string | null
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  zoneLabels?: Record<string, string>
  labels?: { sideA: string; sideB: string; delta: string }
}

export function ComparisonDeltaChart({
  zoneDeltas,
  unit,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  zoneLabels,
  labels,
}: ComparisonDeltaChartProps) {
  const t = useTranslations('p07analytics')
  const sideA = labels?.sideA ?? t('charts.sideA')
  const sideB = labels?.sideB ?? t('charts.sideB')
  const deltaLabel = labels?.delta ?? t('charts.delta')
  const data = useMemo(
    () =>
      (zoneDeltas ?? []).map((row) => ({
        zone: zoneLabels?.[row.zone] ?? row.zone,
        a: row.mean_a,
        b: row.mean_b,
        delta: row.delta,
      })),
    [zoneDeltas, zoneLabels],
  )
  const hasAny = data.some((row) => row.a !== null || row.b !== null || row.delta !== null)

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading}>
      {!hasAny ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{
              a: { label: sideA, color: 'var(--chart-3)' },
              b: { label: sideB, color: 'var(--chart-2)' },
              delta: { label: deltaLabel, color: 'var(--chart-1)' },
            } satisfies ChartConfig}
            className="h-64 w-full"
          >
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="zone" tickLine={false} axisLine={false} fontSize={10} />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={44}
                fontSize={10}
                tickFormatter={(value: number) => formatIndexValue(value, 2)}
              />
              <ChartTooltip
                cursor={{ fill: 'var(--color-stone-100, #f5f5f4)' }}
                content={<ChartTooltipContent />}
              />
              <Bar dataKey="a" fill="var(--color-a)" radius={[3, 3, 0, 0]} name={sideA} />
              <Bar dataKey="b" fill="var(--color-b)" radius={[3, 3, 0, 0]} name={sideB} />
              <Bar dataKey="delta" fill="var(--color-delta)" radius={[3, 3, 0, 0]} name={deltaLabel} />
            </BarChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// TimeSeriesLineChart — index timelines (analytics + anomaly context)
// ---------------------------------------------------------------------------

export interface TimeSeriesPoint {
  date: string
  value: number | null
  /** Backend quality label when present (e.g. 'valid') — surfaced, never hidden. */
  quality_status?: string | null
}

export interface TimeSeriesLineChartProps {
  points: TimeSeriesPoint[] | null | undefined
  unit?: string | null
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  documentedRange?: readonly [number, number] | null
  /** Honest baseline mean drawn as a dashed reference line when provided by the API. */
  baselineMean?: number | null
  baselineLabel?: string
  trendNote?: string
}

export function TimeSeriesLineChart({
  points,
  unit,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  documentedRange,
  baselineMean,
  baselineLabel,
  trendNote,
}: TimeSeriesLineChartProps) {
  const t = useTranslations('p07analytics')
  const data = useMemo(
    () =>
      (points ?? [])
        .filter((pt) => pt && typeof pt.date === 'string')
        .map((pt) => ({
          date: pt.date,
          label: pt.date.slice(0, 10),
          value: pt.value !== null && Number.isFinite(Number(pt.value)) ? Number(pt.value) : null,
          quality_status: pt.quality_status ?? null,
        }))
        .sort((a, b) => (a.date < b.date ? -1 : 1)),
    [points],
  )

  // recharts AxisDomain does NOT accept a bare 'auto' string — omit the prop
  // instead so the axis falls back to its own auto-domain (never a fake range).
  const domain = useMemo<[number, number] | undefined>(() => {
    if (documentedRange && Number.isFinite(documentedRange[0]) && Number.isFinite(documentedRange[1])) {
      return [documentedRange[0], documentedRange[1]]
    }
    return undefined
  }, [documentedRange])

  const hasBaseline = baselineMean !== null && baselineMean !== undefined && Number.isFinite(Number(baselineMean))

  return (
    <ChartShell
      title={title}
      description={description}
      unit={unit}
      source={source}
      loading={loading}
      footer={trendNote ? <p className="text-[11px] leading-snug text-stone-500">{trendNote}</p> : undefined}
    >
      {data.length === 0 ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{
              value: { label: title, color: 'var(--chart-2)' },
            } satisfies ChartConfig}
            className="h-64 w-full"
          >
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                minTickGap={24}
                fontSize={10}
              />
              <YAxis
                domain={domain}
                tickLine={false}
                axisLine={false}
                width={44}
                fontSize={10}
                tickFormatter={(value: number) => formatIndexValue(value, 2)}
              />
              <ChartTooltip
                cursor={{ stroke: 'var(--chart-3)' }}
                content={
                  <ChartTooltipContent
                    labelKey="label"
                    formatter={(value, _name, item) => {
                      const quality = (item?.payload as { quality_status?: string | null } | undefined)
                        ?.quality_status
                      return (
                        <div className="grid w-full gap-1">
                          <span className="text-muted-foreground">{title}</span>
                          <span className="font-mono font-medium tabular-nums">
                            {formatIndexValue(Number(value))}
                          </span>
                          {quality ? (
                            <span className="text-muted-foreground">{t('charts.qualityStatus', { status: String(quality) })}</span>
                          ) : null}
                        </div>
                      )
                    }}
                    hideIndicator
                  />
                }
              />
              {hasBaseline ? (
                <ReferenceLine
                  y={Number(baselineMean)}
                  stroke="var(--chart-3)"
                  strokeDasharray="4 3"
                  label={{ value: baselineLabel ?? t('charts.baselineMean'), position: 'insideTopLeft', fontSize: 10 }}
                />
              ) : null}
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--color-value)"
                strokeWidth={2}
                dot={data.length <= 24 ? { r: 2, fill: 'var(--color-value)' } : false}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// MultiLineChart — named series over a shared date axis (environment tabs:
// temperature min/mean/max lines, soil-moisture line). Values that the API
// did not return stay null and the line simply skips them (connectNulls).
// ---------------------------------------------------------------------------

export interface MultiLineSeries {
  key: string
  label: string
}

export interface MultiLinePoint {
  date: string
  values: Record<string, number | null>
}

export interface MultiLineChartProps {
  series: MultiLineSeries[] | null | undefined
  points: MultiLinePoint[] | null | undefined
  unit?: string | null
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  /** Optional explicit numeric domain (documented range) — omitted when absent. */
  domain?: readonly [number, number] | null
}

export function MultiLineChart({
  series,
  points,
  unit,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  domain,
}: MultiLineChartProps) {
  const t = useTranslations('p07analytics')
  const keys = useMemo(() => (series ?? []).map((s) => s.key), [series])
  const data = useMemo(
    () =>
      (points ?? [])
        .filter((pt) => pt && typeof pt.date === 'string')
        .map((pt) => {
          const values: Record<string, number | null> = {}
          for (const key of keys) {
            const raw = pt.values?.[key]
            values[key] = raw !== null && raw !== undefined && Number.isFinite(Number(raw)) ? Number(raw) : null
          }
          return { date: pt.date, label: pt.date.slice(0, 10), ...values }
        })
        .sort((a, b) => (a.date < b.date ? -1 : 1)),
    [points, keys],
  )
  const hasAnyValue = useMemo(
    () =>
      data.some((row) =>
        keys.some((key) => row[key] !== null && row[key] !== undefined),
      ),
    [data, keys],
  )
  const axisDomain = useMemo<[number, number] | undefined>(() => {
    if (domain && Number.isFinite(domain[0]) && Number.isFinite(domain[1])) {
      return [domain[0], domain[1]]
    }
    return undefined
  }, [domain])
  const chartConfig = useMemo(() => {
    const config: ChartConfig = {}
    for (const [i, s] of (series ?? []).entries()) {
      config[s.key] = { label: s.label, color: `var(--chart-${(i % 4) + 1})` }
    }
    return config
  }, [series])

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading}>
      {!hasAnyValue ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer config={chartConfig} className="h-64 w-full">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={24} fontSize={10} />
              <YAxis
                domain={axisDomain}
                tickLine={false}
                axisLine={false}
                width={48}
                fontSize={10}
                tickFormatter={(value: number) => value.toFixed(1)}
              />
              <ChartTooltip cursor={{ stroke: 'var(--chart-3)' }} content={<ChartTooltipContent labelKey="label" />} />
              {keys.map((key) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={`var(--color-${key})`}
                  strokeWidth={2}
                  dot={data.length <= 24 ? { r: 2, fill: `var(--color-${key})` } : false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

// ---------------------------------------------------------------------------
// MonthlyBarChart — one bar per month (precipitation totals, ET0 totals).
// Months the API has no data for are NOT invented: absent months simply do
// not produce a bar, and the count of covered months stays visible.
// ---------------------------------------------------------------------------

export interface MonthlyBarPoint {
  /** ISO-ish month label, e.g. "2025-03" — rendered verbatim (never translated). */
  month: string
  value: number | null
}

export interface MonthlyBarChartProps {
  points: MonthlyBarPoint[] | null | undefined
  unit?: string | null
  title: string
  description?: string
  source?: string | null
  loading?: boolean
  emptyReason?: string
  barLabel?: string
}

export function MonthlyBarChart({
  points,
  unit,
  title,
  description,
  source,
  loading = false,
  emptyReason,
  barLabel,
}: MonthlyBarChartProps) {
  const t = useTranslations('p07analytics')
  const label = barLabel ?? title
  const data = useMemo(
    () =>
      (points ?? [])
        .filter((pt) => pt && typeof pt.month === 'string')
        .map((pt) => ({
          month: pt.month,
          value: pt.value !== null && Number.isFinite(Number(pt.value)) ? Number(pt.value) : null,
        }))
        .sort((a, b) => (a.month < b.month ? -1 : 1)),
    [points],
  )
  const hasAny = data.some((row) => row.value !== null)

  return (
    <ChartShell title={title} description={description} unit={unit} source={source} loading={loading}>
      {!hasAny ? (
        <ChartEmpty reason={emptyReason ?? t('charts.noDataForPeriod')} />
      ) : (
        <div dir="ltr">
          <ChartContainer
            config={{ value: { label, color: 'var(--chart-2)' } } satisfies ChartConfig}
            className="h-64 w-full"
          >
            <BarChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="month"
                tickLine={false}
                axisLine={false}
                minTickGap={8}
                interval="preserveStartEnd"
                fontSize={10}
              />
              <YAxis tickLine={false} axisLine={false} width={44} fontSize={10} />
              <ChartTooltip
                cursor={{ fill: 'var(--color-stone-100, #f5f5f4)' }}
                content={
                  <ChartTooltipContent
                    labelKey="month"
                    formatter={(value) => (
                      <div className="flex w-full justify-between gap-4">
                        <span className="text-muted-foreground">{label}</span>
                        <span className="font-mono font-medium tabular-nums">
                          {Number(value).toLocaleString()}
                        </span>
                      </div>
                    )}
                    hideIndicator
                  />
                }
              />
              <Bar dataKey="value" fill="var(--color-value)" radius={[3, 3, 0, 0]} name={label} />
            </BarChart>
          </ChartContainer>
        </div>
      )}
    </ChartShell>
  )
}

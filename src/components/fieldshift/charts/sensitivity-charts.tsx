'use client'

/**
 * Sensitivity visualizations — pure presentational sections rendered inside
 * the sensitivity tab's existing result cards:
 *
 * - SensitivityTornadoChart: horizontal bars of the output change at the
 *   lower vs upper explored parameter bound (one feature per row, sorted by
 *   responsiveness, capped for readability).
 * - SensitivityCurvesChart: response curves from the joint parameter grid —
 *   the first axis is the X axis, one line per value of the second axis,
 *   for a selectable feature (default: the most responsive one).
 *
 * Values are shown in each feature's own unit and are never normalized.
 */

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { humanizeCode } from '@/lib/format'
import type {
  SensitivityGridResponse,
  SensitivityOatResponse,
} from '@/lib/types'

const TORNADO_MAX_FEATURES = 12

const CURVE_COLORS = ['#059669', '#0ea5a4', '#d97706', '#65a30d', '#78716c', '#14b8a6']
const CURVE_MAX_LINES = 6

function compactNum(value: number): string {
  if (value === 0) return '0'
  const abs = Math.abs(value)
  if (abs >= 10_000 || abs < 0.01) return value.toExponential(1)
  return String(Math.round(value * 100) / 100)
}

function truncate(value: string, max = 22): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function NoData() {
  const t = useTranslations('charts')
  return (
    <div className="flex h-[200px] items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
      <p className="text-sm text-stone-500">{t('noData')}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tornado (one-factor-at-a-time envelope differences)
// ---------------------------------------------------------------------------

export function SensitivityTornadoChart({ rows }: { rows: SensitivityOatResponse[] }) {
  const t = useTranslations('charts')

  // One row per feature: keep the most responsive period for each feature code.
  const { data, total } = useMemo(() => {
    const byFeature = new Map<string, { feature: string; lower: number | null; upper: number | null; span: number }>()
    let evaluable = 0
    for (const row of rows) {
      const lower = row.difference_at_lower
      const upper = row.difference_at_upper
      if (lower === null && upper === null) continue
      evaluable += 1
      const span = Math.max(Math.abs(lower ?? 0), Math.abs(upper ?? 0))
      const prev = byFeature.get(row.feature_code)
      if (!prev || span > prev.span) {
        byFeature.set(row.feature_code, { feature: row.feature_code, lower, upper, span })
      }
    }
    const sorted = Array.from(byFeature.values())
      .sort((a, b) => b.span - a.span)
      .slice(0, TORNADO_MAX_FEATURES)
      .map(({ feature, lower, upper }) => ({ feature, lower, upper }))
    return { data: sorted, total: evaluable }
  }, [rows])

  if (rows.length === 0) return null
  if (data.length === 0) return <NoData />

  const chartConfig = {
    lower: { label: t('lowerBound'), color: '#65a30d' },
    upper: { label: t('upperBound'), color: '#0ea5a4' },
  } satisfies ChartConfig

  return (
    <div className="mb-4 space-y-2">
      <div>
        <p className="text-sm font-medium text-stone-800">{t('tornadoTitle')}</p>
        <p className="text-xs text-stone-500">{t('tornadoDesc')}</p>
      </div>
      <ChartContainer config={chartConfig} className="h-[300px] w-full">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tickLine={false}
            axisLine={false}
            tickFormatter={compactNum}
          />
          <YAxis
            type="category"
            dataKey="feature"
            width={150}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: string) => truncate(value)}
          />
          <ReferenceLine x={0} stroke="#a8a29e" />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="lower" fill="var(--color-lower)" radius={[0, 3, 3, 0]} barSize={10} />
          <Bar dataKey="upper" fill="var(--color-upper)" radius={[0, 3, 3, 0]} barSize={10} />
        </BarChart>
      </ChartContainer>
      {total > data.length ? (
        <p className="text-xs text-stone-500">
          {t('showingFeatures', { shown: data.length, total })}
        </p>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Response curves (joint parameter grid)
// ---------------------------------------------------------------------------

export function SensitivityCurvesChart({ grid }: { grid: SensitivityGridResponse | null }) {
  const t = useTranslations('charts')
  const [selectedFeature, setSelectedFeature] = useState<string | null>(null)

  const params = useMemo(() => Object.keys(grid?.axes ?? {}), [grid])

  const features = useMemo(() => {
    if (!grid) return [] as string[]
    const codes = new Set<string>()
    for (const cell of grid.cells) {
      const code = cell['feature_code']
      if (typeof code === 'string') codes.add(code)
    }
    const ranges = new Map<string, number>()
    for (const summary of grid.summaries) {
      if (summary.grid_output_range !== null) ranges.set(summary.feature_code, summary.grid_output_range)
    }
    return Array.from(codes).sort(
      (a, b) => (ranges.get(b) ?? -1) - (ranges.get(a) ?? -1),
    )
  }, [grid])

  const activeFeature =
    selectedFeature && features.includes(selectedFeature) ? selectedFeature : (features[0] ?? null)

  const { rows, curves } = useMemo(() => {
    if (!grid || !activeFeature || params.length === 0) return { rows: [], curves: [] }
    const xAxis = params[0]
    const other = params.length > 1 ? params[1] : null

    const otherValues = new Set<number>()
    type Point = { x: number }
    const byX = new Map<number, Point & Record<string, number>>()
    for (const cell of grid.cells) {
      if (cell['feature_code'] !== activeFeature) continue
      const x = numOrNull(cell[xAxis])
      const y = numOrNull(cell['cell_value'])
      if (x === null || y === null) continue
      const otherKey = other ? numOrNull(cell[other]) : null
      if (other) {
        if (otherKey === null) continue
        otherValues.add(otherKey)
      }
      const seriesKey = other ? `s${otherKey}` : 's0'
      const point = byX.get(x) ?? { x }
      point[seriesKey] = y
      byX.set(x, point)
    }

    const sortedOther = Array.from(otherValues).sort((a, b) => a - b).slice(0, CURVE_MAX_LINES)
    const curveDefs = sortedOther.map((value, index) => ({
      key: other ? `s${value}` : 's0',
      color: CURVE_COLORS[index % CURVE_COLORS.length],
      label: other
        ? `${truncate(humanizeCode(other), 18)} = ${compactNum(value)}`
        : activeFeature,
    }))
    const rowsSorted = Array.from(byX.values()).sort((a, b) => a.x - b.x)
    return { rows: rowsSorted, curves: curveDefs }
  }, [grid, activeFeature, params])

  if (!grid) return null
  if (params.length === 0 || grid.cells.length === 0) return null

  const chartConfig = Object.fromEntries(
    curves.map((curve) => [curve.key, { label: curve.label, color: curve.color }]),
  ) satisfies ChartConfig

  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-medium text-stone-800">{t('curvesTitle')}</p>
        <p className="text-xs text-stone-500">{t('curvesDesc')}</p>
      </div>
      <div className="flex items-center gap-2 text-xs text-stone-600">
        <label htmlFor="sensitivity-curve-feature">{t('featureLabel')}</label>
        <select
          id="sensitivity-curve-feature"
          value={activeFeature ?? ''}
          onChange={(event) => setSelectedFeature(event.target.value)}
          className="h-8 max-w-[260px] rounded-md border border-stone-300 bg-white px-2 text-xs"
        >
          {features.map((feature) => (
            <option key={feature} value={feature}>
              {feature}
            </option>
          ))}
        </select>
      </div>
      {rows.length === 0 || curves.length === 0 ? (
        <NoData />
      ) : (
        <ChartContainer config={chartConfig} className="h-[280px] w-full">
          <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="x"
              type="number"
              domain={['auto', 'auto']}
              tickLine={false}
              axisLine={false}
              tickFormatter={compactNum}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={60}
              tickFormatter={compactNum}
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            {curves.map((curve) => (
              <Line
                key={curve.key}
                type="linear"
                dataKey={curve.key}
                stroke={`var(--color-${curve.key})`}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ChartContainer>
      )}
    </div>
  )
}

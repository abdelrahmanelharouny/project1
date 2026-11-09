'use client'

/**
 * Climate snapshot card — daily precipitation (bars) and mean air temperature
 * (line) for a field over roughly the last 120 days. Pure visualization on top
 * of the existing observations hook: the most recent 120-day window is tried
 * first, and if it holds no observations the window anchored at the end of the
 * platform coverage period is used instead (so historical fixture data still
 * renders a snapshot instead of a permanent empty state).
 */

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useObservations } from '@/hooks/use-fieldshift'
import { COVERAGE_END, COVERAGE_START } from '@/lib/api'

const WINDOW_DAYS = 120

const DAY_MS = 86_400_000

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function windowEndingAt(end: Date): { start: string; end: string } {
  return {
    start: isoDate(new Date(end.getTime() - (WINDOW_DAYS - 1) * DAY_MS)),
    end: isoDate(end),
  }
}

export function ClimateOverview({ fieldId }: { fieldId: string | null }) {
  const t = useTranslations('charts')

  // Two candidate windows, both served by the existing observations hook.
  const recentWindow = useMemo(() => windowEndingAt(new Date()), [])
  // The fallback spans the platform's full coverage period (the synthetic
  // fixtures live in 2022/2023) and is trimmed to the last 120 days
  // client-side, so historical fixture data still renders a snapshot.
  const fallbackWindow = useMemo(() => ({ start: COVERAGE_START, end: COVERAGE_END }), [])

  const recentQuery = useObservations(fieldId, recentWindow.start, recentWindow.end, Boolean(fieldId))
  const recentItems = recentQuery.data?.items ?? []
  // The fallback only fires after the recent window resolved empty.
  const fallbackQuery = useObservations(
    fieldId,
    fallbackWindow.start,
    fallbackWindow.end,
    Boolean(fieldId) && recentQuery.isSuccess && recentItems.length === 0,
  )
  const fallbackItems = fallbackQuery.data?.items ?? []

  const items = recentItems.length > 0 ? recentItems : fallbackItems
  const isLoading = recentQuery.isLoading || fallbackQuery.isLoading
  const isError = recentQuery.isError || fallbackQuery.isError

  const series = useMemo(() => {
    const byDate = new Map<string, { date: string; precip: number | null; temp: number | null }>()
    for (const o of items) {
      if (o.value === null) continue
      if (o.variable_code !== 'precipitation' && o.variable_code !== 'air_temperature_mean') continue
      const date = o.observed_at.slice(0, 10)
      const row = byDate.get(date) ?? { date, precip: null, temp: null }
      if (o.variable_code === 'precipitation') row.precip = o.value
      else row.temp = o.value
      byDate.set(date, row)
    }
    const full = Array.from(byDate.values()).sort((a, b) => (a.date < b.date ? -1 : 1))
    // Keep the snapshot window: at most the trailing WINDOW_DAYS of data.
    return full.slice(-WINDOW_DAYS)
  }, [items])

  if (!fieldId) return null

  const chartConfig = {
    precip: { label: t('precipLabel'), color: '#0ea5a4' },
    temp: { label: t('tempLabel'), color: '#059669' },
  } satisfies ChartConfig

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('climateTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('climateDesc')}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[280px] w-full" aria-label={t('loading')} />
        ) : isError ? (
          <p className="text-sm text-red-700">{t('loadError')}</p>
        ) : series.length === 0 ? (
          <div className="flex h-[280px] items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
            <p className="text-sm text-stone-500">{t('noData')}</p>
          </div>
        ) : (
          <ChartContainer config={chartConfig} className="h-[280px] w-full">
            <ComposedChart data={series} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                minTickGap={28}
                tickFormatter={(value: string) => value.slice(5)}
              />
              <YAxis
                yAxisId="precip"
                tickLine={false}
                axisLine={false}
                width={34}
                tickFormatter={(value: number) => String(value)}
              />
              <YAxis
                yAxisId="temp"
                orientation="right"
                tickLine={false}
                axisLine={false}
                width={34}
                tickFormatter={(value: number) => String(value)}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar yAxisId="precip" dataKey="precip" fill="var(--color-precip)" radius={[3, 3, 0, 0]} />
              <Line
                yAxisId="temp"
                type="monotone"
                dataKey="temp"
                stroke="var(--color-temp)"
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </ComposedChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

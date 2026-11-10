'use client'

/**
 * Monthly water balance chart — pure presentational. Bars for precipitation
 * and effective rainfall, lines for ET0, ETc and root-zone drainage at month
 * end, straight from the loaded WaterPlanSeason months. Months without
 * precipitation evidence render an honest gap (no invented bar).
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
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import type { WaterPlanMonth } from '@/lib/types'

export function WaterMonthlyChart({ months }: { months: WaterPlanMonth[] }) {
  const t = useTranslations('charts')

  const data = useMemo(
    () =>
      months.map((m) => ({
        month: `${m.year}-${String(m.month).padStart(2, '0')}`,
        precip: m.precip_evidence_missing ? null : m.precip_mm,
        effRain: m.effective_rainfall_mm,
        et0: m.et0_mm,
        etc: m.etc_mm,
        drEnd: m.dr_end_mm,
      })),
    [months],
  )

  const chartConfig = {
    precip: { label: t('precip'), color: '#0ea5a4' },
    effRain: { label: t('effectiveRainfall'), color: '#84cc16' },
    et0: { label: t('et0'), color: '#d97706' },
    etc: { label: t('etc'), color: '#059669' },
    drEnd: { label: t('drainage'), color: '#78716c' },
  } satisfies ChartConfig

  if (months.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
        <p className="text-sm text-stone-500">{t('noData')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-medium text-stone-800">{t('waterTitle')}</p>
        <p className="text-xs text-stone-500">{t('waterDesc')}</p>
      </div>
      <ChartContainer config={chartConfig} className="h-[280px] w-full">
        <ComposedChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="month" tickLine={false} axisLine={false} />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={38}
            tickFormatter={(value: number) => String(value)}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="precip" fill="var(--color-precip)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="effRain" fill="var(--color-effRain)" radius={[3, 3, 0, 0]} />
          <Line type="linear" dataKey="et0" stroke="var(--color-et0)" strokeWidth={2} dot={false} />
          <Line type="linear" dataKey="etc" stroke="var(--color-etc)" strokeWidth={2} dot={false} />
          <Line type="linear" dataKey="drEnd" stroke="var(--color-drEnd)" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ChartContainer>
    </div>
  )
}

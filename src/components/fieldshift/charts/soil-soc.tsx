'use client'

/**
 * SOC stock by depth layer — vertical bars from the latest SOC stock run's
 * layer rows (pure presentational). Measured layers render emerald, predicted
 * layers lime; layers whose stock was refused (not evaluated) leave an honest
 * gap on the depth axis instead of a fabricated value.
 */

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import type { SocStockLayerRow } from '@/lib/types'

const MEASURED_COLOR = '#059669'
const PREDICTED_COLOR = '#65a30d'

export function SocStockChart({ layers }: { layers: SocStockLayerRow[] }) {
  const t = useTranslations('charts')

  const data = useMemo(
    () =>
      layers.map((layer) => ({
        depth: `${layer.top_cm}–${layer.bottom_cm}`,
        soc: layer.soc_stock_mg_ha,
        isPrediction: layer.is_prediction,
      })),
    [layers],
  )
  const hasEvaluated = data.some((row) => row.soc !== null)
  const hasPredicted = data.some((row) => row.isPrediction && row.soc !== null)

  const chartConfig = {
    soc: { label: t('socStock'), color: MEASURED_COLOR },
  } satisfies ChartConfig

  if (layers.length === 0 || !hasEvaluated) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
        <p className="text-sm text-stone-500">{t('noData')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-medium text-stone-800">{t('socTitle')}</p>
        <p className="text-xs text-stone-500">{t('socDesc')}</p>
      </div>
      <ChartContainer config={chartConfig} className="h-[260px] w-full">
        <BarChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="depth"
            tickLine={false}
            axisLine={false}
            interval={0}
            tickFormatter={(value: string) => value}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(value: number) => String(value)}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Bar dataKey="soc" radius={[4, 4, 0, 0]} barSize={30}>
            {data.map((row, index) => (
              <Cell
                key={row.depth + index}
                fill={row.isPrediction ? PREDICTED_COLOR : MEASURED_COLOR}
              />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      <div className="flex items-center justify-center gap-4 text-xs text-stone-600">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-[2px]" style={{ backgroundColor: MEASURED_COLOR }} aria-hidden />
          {t('measured')}
        </span>
        {hasPredicted ? (
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-[2px]" style={{ backgroundColor: PREDICTED_COLOR }} aria-hidden />
            {t('predicted')}
          </span>
        ) : null}
      </div>
    </div>
  )
}

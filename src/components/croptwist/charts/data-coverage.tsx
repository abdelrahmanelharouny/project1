'use client'

/**
 * Data coverage card — horizontal bars of valid observation counts per
 * variable for a field, from the data-coverage endpoint. Sorted by valid
 * count (descending) and capped so the plot stays readable.
 */

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'
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
import { useDataCoverage } from '@/hooks/use-croptwist'
import { ErrorState, SectionLoader } from '@/components/croptwist/state-views'
import { humanizeCode } from '@/lib/format'

const MAX_VARIABLES = 16

function truncate(value: string, max = 24): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

export function DataCoverage({ fieldId }: { fieldId: string | null }) {
  const t = useTranslations('charts')
  const coverageQuery = useDataCoverage(fieldId, Boolean(fieldId))

  const variables = coverageQuery.data?.variables ?? []
  const rows = useMemo(
    () =>
      variables
        .slice()
        .sort((a, b) => b.valid - a.valid)
        .slice(0, MAX_VARIABLES)
        .map((v) => ({ name: humanizeCode(v.variable_code), valid: v.valid })),
    [variables],
  )

  if (!fieldId) return null

  const chartConfig = {
    valid: { label: t('validCount'), color: '#0ea5a4' },
  } satisfies ChartConfig

  const heightClass =
    rows.length <= 6 ? 'h-[240px]' : rows.length <= 12 ? 'h-[330px]' : 'h-[420px]'

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('coverageTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('coverageDesc')}</CardDescription>
      </CardHeader>
      <CardContent>
        {coverageQuery.isLoading ? (
          <SectionLoader label={t('loading')} className="h-[330px]" />
        ) : coverageQuery.isError ? (
          <ErrorState message={t('loadError')} onRetry={() => coverageQuery.refetch()} className="shadow-none" />
        ) : rows.length === 0 ? (
          <div className="flex h-[240px] items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60">
            <p className="text-sm text-stone-500">{t('noData')}</p>
          </div>
        ) : (
          <>
            <ChartContainer config={chartConfig} className={`${heightClass} w-full`}>
              <BarChart
                data={rows}
                layout="vertical"
                margin={{ top: 4, right: 12, left: 4, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis
                  type="number"
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                  tickFormatter={(value: number) => String(value)}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={170}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(value: string) => truncate(value)}
                />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar
                  dataKey="valid"
                  fill="var(--color-valid)"
                  radius={[0, 4, 4, 0]}
                  barSize={14}
                />
              </BarChart>
            </ChartContainer>
            {variables.length > rows.length ? (
              <p className="mt-2 text-xs text-stone-500">
                {t('showingOf', { shown: rows.length, total: variables.length })}
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}

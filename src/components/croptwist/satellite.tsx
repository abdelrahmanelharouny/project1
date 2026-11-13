'use client'

/**
 * P2.A — Satellite Intelligence tab.
 *
 * Honesty contract surfaced in the UI:
 * - Vegetation indices are satellite-derived surface-reflectance estimates,
 *   not ground measurements.
 * - Findings compare the SAME calendar month across years; a low index in a
 *   documented dormant month is labelled, not treated as decline.
 * - Stress signals separate the observed statistical change from
 *   corroborating environmental context and explicitly state what is NOT
 *   supported (no disease/pest/nutrient diagnosis from NDVI alone).
 */

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldContextGate } from '@/components/croptwist/field-context'
import { ErrorState, SectionSkeleton } from '@/components/croptwist/state-views'
import { SyntheticBadge } from '@/components/croptwist/badges'
import { useVegetationScenes, useVegetationSummary } from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'

const INDEX_OPTIONS = ['ndvi', 'evi', 'savi', 'ndmi', 'ndwi'] as const

function severityVariant(severity: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (severity === 'recommended' || severity === 'required') return 'destructive'
  if (severity === 'advisory') return 'default'
  return 'secondary'
}

export function SatelliteIntelligence() {
  const t = useTranslations('satellite')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const setActiveSub = useCropTwistUi((s) => s.setActiveSub)
  const [index, setIndex] = useState<string>('ndvi')

  const summary = useVegetationSummary(selectedField?.id ?? null, index)
  const scenes = useVegetationScenes(selectedField?.id ?? null)

  const monthlyChart = useMemo(() => {
    const stats = summary.data?.monthly_stats ?? []
    return stats.map((s) => ({
      label: `${s.year}-${String(s.month).padStart(2, '0')}`,
      mean: Number(s.mean.toFixed(4)),
      valid: s.n_valid,
    }))
  }, [summary.data])

  if (!selectedField) return <FieldContextGate hint={t('pickFieldHint')} />

  return (
    <div className="space-y-4" dir="ltr">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>{t('title')}</CardTitle>
              <CardDescription>{t('description')}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <select
                aria-label={t('index')}
                className="h-9 rounded-md border border-stone-200 bg-white px-2 text-sm"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
              >
                {INDEX_OPTIONS.map((code) => (
                  <option key={code} value={code}>
                    {code.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {summary.isLoading && <SectionSkeleton lines={4} />}
          {summary.isError && (
            <ErrorState message={t('loadError')} onRetry={() => summary.refetch()} />
          )}
          {summary.data && (
            <>
              {summary.data.series_state.state === 'no_data' ? (
                <div className="flex h-32 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
                  {t('noData')}
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="flex items-baseline justify-between">
                    <h3 className="text-sm font-semibold">{t('monthlyMeans', { index: index.toUpperCase() })}</h3>
                    <span className="text-xs text-stone-500">{summary.data.formula}</span>
                  </div>
                  <div className="flex h-40 items-end gap-1 overflow-x-auto rounded-md border border-stone-100 bg-stone-50/60 p-2">
                    {monthlyChart.map((point) => {
                      const height = Math.max(4, Math.round(((point.mean + 1) / 2) * 100))
                      return (
                        <div key={point.label} className="flex w-6 flex-col items-center justify-end" title={`${point.label}: ${point.mean} (${point.valid})`}>
                          <div
                            className="w-full rounded-t bg-emerald-600/80"
                            style={{ height: `${height}%` }}
                            aria-hidden
                          />
                          <span className="mt-1 rotate-45 text-[9px] text-stone-400">{point.label.slice(2)}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">
                  {t('observations')}: {summary.data.observation_counts.total}
                </Badge>
                <Badge variant="outline">
                  {t('valid')}: {summary.data.observation_counts.valid}
                </Badge>
                <Badge variant="outline">
                  {t('missingOrCloudy')}: {summary.data.observation_counts.missing_or_cloudy}
                </Badge>
              </div>

              {summary.data.stress_signals.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">{t('stressSignals')}</h3>
                  {summary.data.stress_signals.slice(0, 4).map((signal, i) => (
                    <Alert key={i}>
                      <AlertTitle className="flex items-center gap-2">
                        <Badge variant={severityVariant(signal.severity)}>{signal.severity}</Badge>
                        {String((signal.observed_change as { detail?: string }).detail ?? signal.index)}
                      </AlertTitle>
                      <AlertDescription className="space-y-1 text-xs">
                        <p>
                          <span className="font-medium">{t('possibleContext')}: </span>
                          {signal.possible_context.length > 0
                            ? signal.possible_context.map((c) => c.detail ?? c.factor).join(' · ')
                            : t('causeUnknown')}
                        </p>
                        <p className="text-stone-500">
                          <span className="font-medium">{t('notSupported')}: </span>
                          {signal.not_supported.join(' · ')}
                        </p>
                      </AlertDescription>
                    </Alert>
                  ))}
                </div>
              )}

              {summary.data.findings.length > 0 && (
                <div className="space-y-1">
                  <h3 className="text-sm font-semibold">{t('findings')}</h3>
                  <ul className="space-y-1 text-xs text-stone-600">
                    {summary.data.findings.slice(0, 6).map((f, i) => {
                      const kind = String(f.kind ?? '')
                      const detail = String(f.detail ?? '')
                      const context = f.context === 'seasonal_dormancy_or_harvest' ? ` — ${t('dormancy')}` : ''
                      return (
                        <li key={i}>
                          <Badge variant="outline" className="me-1">
                            {kind}
                          </Badge>
                          {detail}
                          {context}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}

              {summary.data.data_gaps.length > 0 && (
                <div className="rounded-md border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900">
                  <p className="font-semibold">{t('dataGaps')}</p>
                  <ul className="mt-1 list-disc space-y-0.5 ps-4">
                    {summary.data.data_gaps.map((g, i) => (
                      <li key={i}>{g}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base">{t('scenes')}</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setActiveTab('datahub')
                setActiveSub('scenes')
              }}
            >
              {t('openCatalog')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {scenes.isLoading && <SectionSkeleton lines={2} />}
          {scenes.data && scenes.data.total === 0 && (
            <div className="flex h-20 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
              {t('noData')}
            </div>
          )}
          {scenes.data && scenes.data.total > 0 && (
            <div className="max-h-72 overflow-y-auto scrollbar-thin">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('sceneDate')}</TableHead>
                    <TableHead>{t('scene')}</TableHead>
                    <TableHead>{t('cloudCover')}</TableHead>
                    <TableHead>{t('resolution')}</TableHead>
                    <TableHead>{t('quality')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {scenes.data.scenes.slice(0, 50).map((scene) => (
                    <TableRow key={scene.id}>
                      <TableCell className="whitespace-nowrap text-xs">
                        {scene.acquired_at?.slice(0, 10) ?? '—'}
                      </TableCell>
                      <TableCell className="text-xs">
                        {scene.scene_id}
                        {scene.is_synthetic && <SyntheticBadge />}
                      </TableCell>
                      <TableCell className="text-xs">{scene.cloud_cover_pct != null ? `${scene.cloud_cover_pct}%` : '—'}</TableCell>
                      <TableCell className="text-xs">{scene.spatial_resolution_m != null ? `${scene.spatial_resolution_m} m` : '—'}</TableCell>
                      <TableCell className="text-xs">{scene.provider_code}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

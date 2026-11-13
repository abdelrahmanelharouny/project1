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
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
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
import {
  useSatelliteProfile,
  useVegetationScenes,
  useVegetationSummary,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import type { SatelliteProfileResponse } from '@/lib/types'

const INDEX_OPTIONS = ['ndvi', 'evi', 'savi', 'ndmi', 'ndwi'] as const

function severityVariant(severity: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (severity === 'recommended' || severity === 'required') return 'destructive'
  if (severity === 'advisory') return 'default'
  return 'secondary'
}

// --- P06 field satellite profile helpers -----------------------------------

function fmtNum(value: number | null | undefined, digits = 3): string {
  return value == null ? '—' : value.toFixed(digits)
}

function fmtSigned(value: number | null | undefined, digits = 3): string {
  if (value == null) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

const ZONE_LABEL_KEYS: Record<string, string> = {
  lowest_tercile: 'zoneLowestTercile',
  middle_tercile: 'zoneMiddleTercile',
  highest_tercile: 'zoneHighestTercile',
}

/**
 * P06 "Field satellite profile" — evidence-bounded temporal analysis for the
 * selected index. Honesty rules preserved from the backend contract:
 *   - insufficient_evidence replaces trend/comparison/zones as findings
 *   - weak-evidence comparisons are flagged, never interpreted
 *   - coverage gaps are surfaced, never interpolated
 *   - provenance (derived assets + checksums) is always visible
 */
function SatelliteProfileSection({ fieldId, index }: { fieldId: string; index: string }) {
  const t = useTranslations('satellite')
  const profile = useSatelliteProfile(fieldId, index)

  const timelineData = useMemo(() => {
    const timeline = profile.data?.timeline ?? []
    return timeline.map((obs) => ({
      date: obs.observed_at.slice(0, 10),
      value: Number(obs.value.toFixed(4)),
    }))
  }, [profile.data])

  if (profile.isLoading) return <SectionSkeleton lines={5} />
  if (profile.isError) {
    return <ErrorState message={t('profileLoadError')} onRetry={() => profile.refetch()} />
  }
  if (!profile.data) return null

  const data: SatelliteProfileResponse = profile.data
  const quality = data.quality_summary
  const insufficient = data.insufficient_evidence
  const comparison = data.comparison
  const baseline = data.baseline
  const trend = data.trend
  const zones = data.statistical_zones
  const gaps = data.coverage.gaps
  const derivedAssets = data.derived_assets
  const provenanceVersion =
    data.latest_valid_observation?.processing_version ?? derivedAssets[0]?.processing_version ?? '—'

  const chartConfig = {
    value: { label: index.toUpperCase(), color: '#059669' },
  } satisfies ChartConfig

  return (
    <div className="space-y-4">
      {/* Freshness + observation quality counts */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {quality.freshness_days_since_last != null ? (
          <Badge
            className={
              quality.fresh
                ? 'gap-1.5 border-transparent bg-emerald-100 text-emerald-900'
                : 'gap-1.5 border-amber-300 bg-amber-50 text-amber-900'
            }
          >
            {quality.fresh
              ? t('freshnessFresh', { days: quality.freshness_days_since_last })
              : t('freshnessStale', { days: quality.freshness_days_since_last })}
          </Badge>
        ) : (
          <Badge variant="outline">{t('noObservations')}</Badge>
        )}
        <Badge variant="outline">
          {t('validObservations')}: {quality.valid_observations}
        </Badge>
        <Badge variant="outline">
          {t('excludedObservations')}: {quality.excluded_no_value}
        </Badge>
        {quality.avg_valid_pixel_fraction != null && (
          <Badge variant="outline">
            {t('avgValidPixel')}: {Math.round(quality.avg_valid_pixel_fraction * 100)}%
          </Badge>
        )}
      </div>

      {/* Insufficient evidence — visible amber banner; replaces findings */}
      {insufficient && (
        <div className="rounded-md border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900" role="status">
          <p className="font-semibold">{t('insufficientTitle')}</p>
          <ul className="mt-1 list-disc space-y-0.5 ps-4">
            {insufficient.reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
          {insufficient.note && <p className="mt-1 text-[11px] text-amber-800">{insufficient.note}</p>}
        </div>
      )}

      {!insufficient && timelineData.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold">{t('profileTimeline')}</h3>
            <span className="text-xs text-stone-500">{data.index_formula}</span>
          </div>
          <div dir="ltr">
            <ChartContainer config={chartConfig} className="h-[200px] w-full">
              <LineChart data={timelineData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(value: string) => value.slice(5)}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={44}
                  domain={[data.documented_range[0], data.documented_range[1]]}
                  tickFormatter={(value: number) => value.toFixed(1)}
                />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#059669"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ChartContainer>
          </div>
        </div>
      )}

      {!insufficient && (
        <div className="grid gap-3 md:grid-cols-2">
          {/* Baseline comparison — observed statistics only */}
          {comparison && (
            <div className="rounded-md border border-stone-200 bg-white p-3">
              <p className="text-sm font-semibold text-stone-800">{t('baselineComparison')}</p>
              <dl className="mt-2 space-y-1 text-xs text-stone-600">
                <div className="flex justify-between gap-2">
                  <dt>{t('latestValue')}</dt>
                  <dd className="tabular-nums font-medium text-stone-900">{fmtNum(comparison.latest_value)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>{t('deltaVsBaseline')}</dt>
                  <dd className="tabular-nums">{fmtSigned(comparison.delta_vs_baseline_mean)}</dd>
                </div>
                {comparison.z_score_vs_baseline != null && (
                  <div className="flex justify-between gap-2">
                    <dt>{t('zScore')}</dt>
                    <dd className="tabular-nums">{fmtSigned(comparison.z_score_vs_baseline, 2)}</dd>
                  </div>
                )}
                {baseline && (
                  <div className="flex justify-between gap-2">
                    <dt>{t('baselineStats')}</dt>
                    <dd className="tabular-nums">
                      {t('baselineStatsValue', {
                        count: baseline.count,
                        mean: fmtNum(baseline.mean),
                        std: fmtNum(baseline.std),
                      })}
                    </dd>
                  </div>
                )}
              </dl>
              {comparison.weak_evidence && (
                <p className="mt-2 rounded bg-amber-50 p-2 text-[11px] text-amber-900">
                  {t('weakEvidenceNote')}
                  {comparison.uncertainty_note ? ` ${comparison.uncertainty_note}` : ''}
                </p>
              )}
            </div>
          )}

          {/* Trend — slope over 30 days, with method + point count */}
          {trend && (
            <div className="rounded-md border border-stone-200 bg-white p-3">
              <p className="text-sm font-semibold text-stone-800">{t('trendTitle')}</p>
              <dl className="mt-2 space-y-1 text-xs text-stone-600">
                <div className="flex justify-between gap-2">
                  <dt>{t('slopePer30d')}</dt>
                  <dd className="tabular-nums">{fmtSigned(trend.slope_per_30d)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>{t('trendPoints')}</dt>
                  <dd className="tabular-nums">{trend.points}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>{t('trendMethod')}</dt>
                  <dd>{trend.method}</dd>
                </div>
              </dl>
            </div>
          )}
        </div>
      )}

      {/* Statistical zones — data-description aid, not agronomic zonation */}
      {!insufficient && zones && zones.zones.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">{t('zonesTitle')}</h3>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('zonesZone')}</TableHead>
                  <TableHead>{t('zonesMean')}</TableHead>
                  <TableHead>{t('zonesPixelShare')}</TableHead>
                  <TableHead>{t('zonesValueRange')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...zones.zones]
                  .sort((a, b) => a.mean - b.mean)
                  .map((zone) => (
                    <TableRow key={zone.zone}>
                      <TableCell className="text-xs font-medium">
                        {ZONE_LABEL_KEYS[zone.zone] ? t(ZONE_LABEL_KEYS[zone.zone]) : zone.zone}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">{fmtNum(zone.mean)}</TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {Math.round(zone.pixel_share * 100)}%
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {fmtNum(zone.value_range[0], 2)} … {fmtNum(zone.value_range[1], 2)}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </div>
          {zones.description && (
            <p className="text-[11px] text-stone-500">{zones.description}</p>
          )}
        </div>
      )}

      {/* Coverage gaps — honest amber box, never interpolated */}
      {gaps.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900">
          <p className="font-semibold">{t('gapsTitle')}</p>
          <ul className="mt-1 list-disc space-y-0.5 ps-4">
            {gaps.map((gap, i) => (
              <li key={i} className="tabular-nums">
                {t('gapWindow', { from: gap.from.slice(0, 10), to: gap.to.slice(0, 10), days: gap.days })}
              </li>
            ))}
          </ul>
          {data.coverage.gaps_note && (
            <p className="mt-1 text-[11px] text-amber-800">{data.coverage.gaps_note}</p>
          )}
        </div>
      )}

      {/* Provenance — derived assets, processing version, checksum short forms */}
      {derivedAssets.length > 0 && (
        <p className="text-[11px] text-stone-400">
          {t('provenance', { count: derivedAssets.length, version: provenanceVersion })}
          {' · '}
          {t('checksumLabel')}: {derivedAssets.map((a) => a.checksum_sha256.slice(0, 8)).join(' · ')}
        </p>
      )}
    </div>
  )
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

      {/* P06 — field satellite profile (temporal analysis for the selected index) */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('profileTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('profileDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {selectedField && <SatelliteProfileSection fieldId={selectedField.id} index={index} />}
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

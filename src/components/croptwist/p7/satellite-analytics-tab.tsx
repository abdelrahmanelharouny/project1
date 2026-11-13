'use client'

/**
 * P07 — Field performance tab (Reports & Analytics → Field performance).
 *
 * Data honesty contract:
 *   - every number comes from the P07 spatial-analytics / satellite-profile
 *     responses; absent values render as an em dash, never a zero or an
 *     invented placeholder;
 *   - `available: false` / `insufficient_evidence` surfaces the backend's own
 *     reason instead of hiding the section;
 *   - statistical tercile zones are ALWAYS labeled "statistical — not
 *     agronomic" (the backend's not_zones_note is echoed too);
 *   - fixed chart heights (h-48/h-64) so nothing shifts while loading;
 *   - numbers/axes sit in dir="ltr" wrappers for RTL correctness.
 *
 * The only URL contract this tab owns is the `index` param — read once via
 * useSearchParams, written via router.replace PRESERVING every other param
 * (the workspace owns tab/sub/farm/field).
 */

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Download, FileJson, Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  BoxPlotChart,
  HistogramChart,
  TimeSeriesLineChart,
  ZoneHeatmap,
} from '@/components/croptwist/charts/p07-charts'
import { P07_DOCUMENTED_RANGES } from '@/components/croptwist/map/spatial-legend'
import { useCropTwistUi, type SelectedField } from '@/lib/store'
import {
  exportFieldBoundaryGeoJSON,
  exportSatelliteTimelineCSV,
  saveP07Blob,
} from '@/lib/api-p07'
import { formatGaps, gapsText, type P07GapLike } from '@/lib/analytics/p07-utils'
import { useSatelliteProfile } from '@/hooks/use-croptwist'
import { useSpatialAnalytics } from '@/hooks/use-p07'
import type { P07IndexCode, P07SpatialAnalytics } from '@/lib/types-p07'

// ---------------------------------------------------------------------------
// Index selector chips (shared with the anomalies tab)
// ---------------------------------------------------------------------------

export const P07_INDEX_CODES: readonly P07IndexCode[] = ['ndvi', 'evi', 'ndmi', 'ndwi', 'bsi']

export function isP07Index(value: string | null | undefined): value is P07IndexCode {
  return !!value && (P07_INDEX_CODES as readonly string[]).includes(value)
}

/**
 * Keyboard-accessible radio-chip group (native buttons: Enter/Space work).
 * Color is never the only signal — the selected chip also changes weight.
 */
export function IndexSelectorChips({
  value,
  onChange,
  labelId,
}: {
  value: P07IndexCode
  onChange: (next: P07IndexCode) => void
  labelId?: string
}) {
  const t = useTranslations('p07analytics')
  return (
    <div
      role="radiogroup"
      aria-labelledby={labelId}
      className="flex flex-wrap items-center gap-2"
      dir="ltr"
    >
      {P07_INDEX_CODES.map((code) => {
        const selected = code === value
        return (
          <button
            key={code}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(code)}
            className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
              selected
                ? 'border-emerald-700 bg-emerald-700 text-white'
                : 'border-stone-300 bg-white text-stone-600 hover:border-emerald-400 hover:text-emerald-800'
            }`}
          >
            {t(`index.${code}`)}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared small pieces
// ---------------------------------------------------------------------------

function emDash(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : Number(value).toFixed(digits)
}

function pctText(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : `${(Number(value) * 100).toFixed(digits)}%`
}

/** FileScope empty state when no field is selected in the store. */
function NoFieldSelected() {
  const t = useTranslations('p07analytics')
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('hub.noFieldTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('hub.noFieldHint')}</CardDescription>
      </CardHeader>
    </Card>
  )
}

function UnavailableAlert({ reason }: { reason: string | null | undefined }) {
  const t = useTranslations('p07analytics')
  return (
    <Alert className="border-amber-200 bg-amber-50 text-amber-900">
      <AlertTitle className="text-sm font-semibold">{t('field.unavailableTitle')}</AlertTitle>
      <AlertDescription className="text-sm text-amber-800">
        {reason ?? '—'}
      </AlertDescription>
    </Alert>
  )
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-stone-100 py-1.5 last:border-b-0">
      <span className="text-xs text-stone-500">{label}</span>
      <span className="font-mono text-sm tabular-nums text-stone-800" dir="ltr">
        {value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Variation card
// ---------------------------------------------------------------------------

function VariationCard({
  analytics,
  loading,
  index,
}: {
  analytics: P07SpatialAnalytics | undefined
  loading: boolean
  index: P07IndexCode
}) {
  const t = useTranslations('p07analytics')
  if (loading) {
    return (
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }
  if (analytics && analytics.available === false) {
    return <UnavailableAlert reason={analytics.unavailable_reason} />
  }
  const variation = analytics?.variation
  const documentedRange = analytics?.distribution?.documented_range ?? P07_DOCUMENTED_RANGES[index]
  return (
    <div className="space-y-4">
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('field.variationTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('field.variationDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {variation ? (
            <div className="space-y-3" dir="ltr">
              <MetricRow label={t('field.std')} value={emDash(variation.std)} />
              <MetricRow label="p5" value={emDash(variation.p5)} />
              <MetricRow label="p25" value={emDash(variation.p25)} />
              <MetricRow label="p75" value={emDash(variation.p75)} />
              <MetricRow label="p95" value={emDash(variation.p95)} />
              <MetricRow label={t('field.spread')} value={emDash(variation.spread_p95_p5)} />
              <MetricRow label={t('field.coverage')} value={pctText(variation.coverage_fraction)} />
              <MetricRow
                label={t('field.validPixels')}
                value={variation.valid_pixels === null || variation.valid_pixels === undefined ? '—' : variation.valid_pixels.toLocaleString()}
              />
              <Badge
                variant="outline"
                className={
                  variation.supports_subfield_claims
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                    : 'border-stone-300 bg-stone-50 text-stone-600'
                }
              >
                {variation.supports_subfield_claims
                  ? t('field.subfieldOk')
                  : t('field.subfieldNo')}
              </Badge>
            </div>
          ) : (
            <p className="text-sm text-stone-500">{t('field.noVariation')}</p>
          )}
        </CardContent>
      </Card>
      <BoxPlotChart
        percentiles={
          variation
            ? {
                p5: variation.p5,
                p25: variation.p25,
                median: null,
                p75: variation.p75,
                p95: variation.p95,
              }
            : null
        }
        documentedRange={documentedRange}
        title={t('charts.percentileDistribution')}
        unit={t(`index.${index}`)}
        source={t('field.sourceAnalytics', { id: 'field', version: analytics?.version ?? '—' })}
        emptyReason={t('field.noVariation')}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Zones table (latest zone_history entry; falls back to zone polygons)
// ---------------------------------------------------------------------------

interface ZoneRow {
  zone: string
  share: number | null
  mean: number | null
  range: [number, number] | null
}

function latestZoneRows(analytics: P07SpatialAnalytics | undefined): {
  rows: ZoneRow[]
  acquiredAt: string | null
  source: 'zone_history' | 'zone_polygons' | null
} {
  if (!analytics) return { rows: [], acquiredAt: null, source: null }
  const history = analytics.zone_history ?? []
  const dated = history
    .filter((e) => typeof e.acquired_at === 'string' && e.acquired_at !== '')
    .sort((a, b) => ((a.acquired_at as string) < (b.acquired_at as string) ? 1 : -1))
  if (dated.length > 0) {
    const latest = dated[0]
    return {
      rows: latest.zones.map((z) => ({
        zone: z.zone,
        share: z.pixel_share,
        mean: z.mean,
        range: z.value_range ?? null,
      })),
      acquiredAt: latest.acquired_at,
      source: 'zone_history',
    }
  }
  const features = analytics.zone_polygons?.features ?? []
  if (features.length > 0) {
    return {
      rows: features.map((f) => ({
        zone: f.properties.zone,
        share: f.properties.pixel_share,
        mean: f.properties.mean,
        range: f.properties.value_range ?? null,
      })),
      acquiredAt: null,
      source: 'zone_polygons',
    }
  }
  return { rows: [], acquiredAt: null, source: null }
}

function zoneLabelKey(zone: string): string | null {
  switch (zone) {
    case 'lowest_tercile':
      return 'field.zoneLow'
    case 'middle_tercile':
      return 'field.zoneMiddle'
    case 'highest_tercile':
      return 'field.zoneHigh'
    default:
      return null
  }
}

function ZonesTableCard({
  analytics,
  index,
}: {
  analytics: P07SpatialAnalytics | undefined
  index: P07IndexCode
}) {
  const t = useTranslations('p07analytics')
  const { rows, acquiredAt } = useMemo(() => latestZoneRows(analytics), [analytics])
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('field.zonesTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">
          {t('field.zonesDesc')}
          {acquiredAt ? ` · ${acquiredAt.slice(0, 10)}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.length === 0 ? (
          <p className="text-sm text-stone-500">{t('field.noZones')}</p>
        ) : (
          <div className="overflow-x-auto" dir="ltr">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('field.colZone')}</TableHead>
                  <TableHead className="text-end">{t('field.colShare')}</TableHead>
                  <TableHead className="text-end">{t('field.colMean')}</TableHead>
                  <TableHead className="text-end">{t('field.colRange')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.zone}>
                    <TableCell className="text-sm text-stone-800">
                      {zoneLabelKey(row.zone) ? t(zoneLabelKey(row.zone) as string) : row.zone}
                    </TableCell>
                    <TableCell className="text-end font-mono text-sm tabular-nums">
                      {pctText(row.share)}
                    </TableCell>
                    <TableCell className="text-end font-mono text-sm tabular-nums">
                      {emDash(row.mean)}
                    </TableCell>
                    <TableCell className="text-end font-mono text-xs tabular-nums text-stone-500">
                      {row.range ? `${row.range[0]} … ${row.range[1]}` : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <Alert className="border-stone-200 bg-stone-50 text-stone-700">
          <AlertDescription className="text-xs">
            {t('field.statisticalNote')}
            {analytics?.not_zones_note ? ` ${analytics.not_zones_note}` : ''}
          </AlertDescription>
        </Alert>
        <p className="text-[11px] text-stone-400">
          {t('field.sourceAnalytics', { id: 'field', version: analytics?.version ?? '—' })} · {t(`index.${index}`)}
        </p>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Coverage + gaps card
// ---------------------------------------------------------------------------

function CoverageCard({
  coverage,
  loading,
}: {
  coverage:
    | {
        first_scene_acquired: string | null
        last_scene_acquired: string | null
        scene_records: number
        gaps: P07GapLike[]
        gaps_note: string | null
      }
    | undefined
  loading: boolean
}) {
  const t = useTranslations('p07analytics')
  if (loading) {
    return (
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    )
  }
  if (!coverage) {
    return (
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('field.coverageTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-stone-500">{t('charts.noDataForPeriod')}</p>
        </CardContent>
      </Card>
    )
  }
  const summary = gapsText(coverage.gaps)
  const lines = formatGaps(coverage.gaps)
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('field.coverageTitle')}</CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('field.coverageDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3" dir="ltr">
        <MetricRow
          label={t('field.firstScene')}
          value={coverage.first_scene_acquired ? coverage.first_scene_acquired.slice(0, 10) : '—'}
        />
        <MetricRow
          label={t('field.lastScene')}
          value={coverage.last_scene_acquired ? coverage.last_scene_acquired.slice(0, 10) : '—'}
        />
        <MetricRow
          label={t('field.sceneRecords')}
          value={coverage.scene_records.toLocaleString()}
        />
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-stone-600">{t('field.gapsSummary')}</p>
          {lines.length === 0 ? (
            <p className="text-sm text-stone-500">{t('field.gapsNone')}</p>
          ) : (
            <>
              <p className="font-mono text-sm tabular-nums text-stone-800">{summary}</p>
              <ul className="list-inside list-disc space-y-0.5 text-xs text-stone-500">
                {lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
          {coverage.gaps_note ? (
            <p className="text-[11px] leading-snug text-stone-400">{coverage.gaps_note}</p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function SatelliteAnalyticsTab() {
  const t = useTranslations('p07analytics')
  const router = useRouter()
  const searchParams = useSearchParams()
  const selectedField = useCropTwistUi((s) => s.selectedField)

  // The `index` param is the ONLY URL contract this tab owns.
  const rawIndex = searchParams.get('index')
  const index: P07IndexCode = isP07Index(rawIndex) ? rawIndex : 'ndvi'

  const setIndexParam = (next: P07IndexCode) => {
    const params = new URLSearchParams(searchParams.toString())
    if (next === 'ndvi') {
      params.delete('index') // keep canonical URLs clean
    } else {
      params.set('index', next)
    }
    const qs = params.toString()
    router.replace(qs ? `/?${qs}` : '/', { scroll: false })
  }

  const field: SelectedField | null = selectedField
  const fieldId = field?.id ?? null

  const profileQuery = useSatelliteProfile(fieldId, index)
  const analyticsQuery = useSpatialAnalytics(fieldId, index)
  const profile = profileQuery.data
  const analytics = analyticsQuery.data

  const documentedRange: readonly [number, number] =
    analytics?.distribution?.documented_range ?? P07_DOCUMENTED_RANGES[index]

  // ------------------------------------------------------------- exports
  const timelineM = useMutation({
    mutationFn: async () => {
      const blob = await exportSatelliteTimelineCSV(fieldId as string, index)
      const name = `field-timeline-${index}.csv`
      saveP07Blob(blob, name)
      return name
    },
    onSuccess: (name) => toast.success(t('field.exportDone', { name })),
    onError: () => toast.error(t('field.exportFailed')),
  })
  const boundaryM = useMutation({
    mutationFn: async () => {
      const blob = await exportFieldBoundaryGeoJSON(fieldId as string)
      const name = 'field-boundary.geojson'
      saveP07Blob(blob, name)
      return name
    },
    onSuccess: (name) => toast.success(t('field.exportDone', { name })),
    onError: () => toast.error(t('field.exportFailed')),
  })

  if (!field) return <NoFieldSelected />

  const quality = profile?.quality_summary
  const timelinePoints = (profile?.timeline ?? []).map((o) => ({
    date: o.observed_at,
    value: o.value,
    quality_status: o.quality_status,
  }))
  const variation = analytics?.variation
  const distribution = analytics?.distribution
  const unavailable = analytics?.available === false

  return (
    <div className="space-y-4">
      {/* a) index chips */}
      <div className="flex flex-col gap-2">
        <span id="p07-index-label" className="text-xs font-medium text-stone-600">
          {t('index.label')}
        </span>
        <IndexSelectorChips value={index} onChange={setIndexParam} labelId="p07-index-label" />
        <p className="text-[11px] text-stone-400">{t('index.hint')}</p>
        {analytics?.index_formula ? (
          <p className="text-[11px] text-stone-400" dir="ltr">
            {t('index.formula', { formula: analytics.index_formula })}
          </p>
        ) : null}
      </div>

      {profile?.insufficient_evidence ? (
        <Alert className="border-amber-200 bg-amber-50 text-amber-900">
          <AlertTitle className="text-sm font-semibold">{t('field.insufficientTitle')}</AlertTitle>
          <AlertDescription className="text-sm text-amber-800">
            {t('field.insufficientIntro')}
            <ul className="mt-1.5 list-inside list-disc space-y-0.5">
              {profile.insufficient_evidence.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* b) vegetation history */}
      <TimeSeriesLineChart
        points={timelinePoints}
        unit={t(`index.${index}`)}
        title={t('field.historyTitle')}
        description={t('field.historyDesc')}
        source={t('field.sourceProfile', { id: 'field', version: profile?.profile_version ?? '—' })}
        loading={profileQuery.isLoading}
        emptyReason={profile?.insufficient_evidence?.reasons.join(' · ') ?? undefined}
        documentedRange={documentedRange}
        baselineMean={profile?.baseline?.mean ?? null}
        baselineLabel={t('charts.baselineMean')}
        trendNote={
          profile?.trend
            ? t('field.trendNote', {
                method: profile.trend.method,
                slope: profile.trend.slope_per_30d,
                points: profile.trend.points,
              })
            : undefined
        }
      />

      {/* freshness + quality badges */}
      {quality ? (
        <div className="flex flex-wrap items-center gap-2" dir="ltr">
          <Badge
            variant="outline"
            className={
              quality.fresh
                ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                : 'border-amber-300 bg-amber-50 text-amber-800'
            }
          >
            {quality.fresh
              ? t('field.freshFresh', { days: quality.freshness_days_since_last ?? 0 })
              : t('field.freshStale', { days: quality.freshness_days_since_last ?? 0 })}
          </Badge>
          <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
            {t('field.validObs', { count: quality.valid_observations })}
          </Badge>
          <Badge variant="outline" className="border-stone-300 bg-stone-50 text-stone-600">
            {t('field.avgCoverage', { pct: pctText(quality.avg_valid_pixel_fraction) })}
          </Badge>
        </div>
      ) : null}

      {unavailable ? <UnavailableAlert reason={analytics?.unavailable_reason} /> : null}

      {!unavailable ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* c) spatial variation */}
          <div className="lg:col-span-2">
            <VariationCard analytics={analytics} loading={analyticsQuery.isLoading} index={index} />
          </div>
          {/* d) distribution histogram */}
          <div className="lg:col-span-2">
            <HistogramChart
              bins={distribution?.histogram ?? null}
              documentedRange={distribution?.documented_range ?? null}
              proportionOutOfRange={distribution?.proportion_out_of_documented_range ?? null}
              title={t('field.distributionTitle')}
              description={distribution?.note ?? t('field.distributionDesc')}
              unit={t(`index.${index}`)}
              source={t('field.sourceAnalytics', { id: 'field', version: analytics?.version ?? '—' })}
              loading={analyticsQuery.isLoading && !distribution}
              emptyReason={
                distribution && distribution.available === false
                  ? distribution.reason
                  : distribution?.histogram?.length
                    ? undefined
                    : t('charts.noDataForPeriod')
              }
            />
          </div>
          {/* e) zone heatmap */}
          <div className="lg:col-span-2">
            <ZoneHeatmap
              zoneHistory={analytics?.zone_history ?? []}
              documentedRange={documentedRange}
              zoneLabels={{
                lowest_tercile: t('field.zoneLow'),
                middle_tercile: t('field.zoneMiddle'),
                highest_tercile: t('field.zoneHigh'),
              }}
              title={t('field.heatmapTitle')}
              description={t('field.heatmapDesc')}
              source={t('field.sourceAnalytics', { id: 'field', version: analytics?.version ?? '—' })}
              loading={analyticsQuery.isLoading}
              emptyReason={t('field.noZones')}
              note={t('field.statisticalNote')}
            />
          </div>
          {/* f) statistical zones table */}
          <div className="lg:col-span-2">
            <ZonesTableCard analytics={analytics} index={index} />
          </div>
        </div>
      ) : null}

      {/* g) coverage + gaps */}
      <CoverageCard coverage={profile?.coverage} loading={profileQuery.isLoading} />

      {/* h) exports */}
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('field.exportTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="gap-2 border-stone-300 bg-white text-stone-700 hover:bg-stone-50"
            disabled={timelineM.isPending || !fieldId}
            onClick={() => timelineM.mutate()}
            aria-busy={timelineM.isPending}
          >
            {timelineM.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Download className="h-4 w-4" aria-hidden />
            )}
            {timelineM.isPending ? t('field.exportPreparing') : t('field.exportTimeline')}
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-stone-300 bg-white text-stone-700 hover:bg-stone-50"
            disabled={boundaryM.isPending || !fieldId}
            onClick={() => boundaryM.mutate()}
            aria-busy={boundaryM.isPending}
          >
            {boundaryM.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <FileJson className="h-4 w-4" aria-hidden />
            )}
            {boundaryM.isPending ? t('field.exportPreparing') : t('field.exportBoundary')}
          </Button>
          <span className="text-[11px] text-stone-400">
            {t('field.validObs', { count: profile?.quality_summary?.valid_observations ?? 0 })}
          </span>
        </CardContent>
      </Card>
    </div>
  )
}

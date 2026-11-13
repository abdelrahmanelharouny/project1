'use client'

/**
 * P07 — field inspector.
 *
 * Shown for the selected field (clicked on the map or picked in the context
 * bar). Renders ONLY backend facts from the layer catalog's `latest` product
 * (index mean, acquisition day, valid-pixel fraction) and its tercile
 * `zone_summary`, which is explicitly labeled "statistical zones — not
 * agronomic". Actions: fit-to-field, clear selection, boundary GeoJSON export
 * and satellite timeline CSV export (real downloads via the P07 export
 * endpoints — never fabricated files).
 *
 * Mobile: renders as a collapsible bottom-sheet-style card under the map
 * (full width, stacked by the pane grid below `xl`).
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ChevronDown,
  Download,
  FileDown,
  MapPin,
  Maximize2,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { exportFieldBoundaryGeoJSON, exportSatelliteTimelineCSV, saveP07Blob } from '@/lib/api-p07'
import { cn } from '@/lib/utils'
import { formatArea, formatDay } from '@/lib/format'
import type { P07IndexCode, P07LatestProduct } from '@/lib/types-p07'

export interface FieldInspectorField {
  id: string
  name: string
  areaHa: number | null
  boundaryVersion: number | null
}

export interface FieldInspectorProps {
  field: FieldInspectorField | null
  /** Focus index (labels the latest value + scopes the timeline CSV export). */
  index: P07IndexCode
  /** Catalog `latest` product for the focus index; null = honestly none. */
  latest: P07LatestProduct | null
  onFit: () => void
  onClear: () => void
  className?: string
}

const ZONE_LABEL_KEYS: Record<string, string> = {
  lowest_tercile: 'zoneLowestTercile',
  middle_tercile: 'zoneMiddleTercile',
  highest_tercile: 'zoneHighestTercile',
}

function safeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9-_]+/g, '-').replace(/^-+|-+$/g, '') || 'field'
}

function fmtValue(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

export function FieldInspector({
  field,
  index,
  latest,
  onFit,
  onClear,
  className,
}: FieldInspectorProps) {
  const t = useTranslations('p07map')
  const tCommon = useTranslations('common')
  const [open, setOpen] = useState(true)
  const [exporting, setExporting] = useState<'geojson' | 'csv' | null>(null)
  const [exportFailed, setExportFailed] = useState(false)

  if (!field) return null

  const handleExport = async (kind: 'geojson' | 'csv') => {
    if (exporting) return
    setExporting(kind)
    setExportFailed(false)
    try {
      if (kind === 'geojson') {
        const blob = await exportFieldBoundaryGeoJSON(field.id)
        saveP07Blob(
          blob,
          `${safeFilename(field.name)}-boundary-v${field.boundaryVersion ?? 0}.geojson`,
        )
      } else {
        const blob = await exportSatelliteTimelineCSV(field.id, index)
        saveP07Blob(blob, `${safeFilename(field.name)}-${index}-timeline.csv`)
      }
    } catch {
      setExportFailed(true)
    } finally {
      setExporting(null)
    }
  }

  const zones = [...(latest?.zone_summary?.zones ?? [])].sort((a, b) => {
    const am = a.mean ?? Number.POSITIVE_INFINITY
    const bm = b.mean ?? Number.POSITIVE_INFINITY
    return am - bm
  })

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn(
        'rounded-xl border border-stone-200 bg-white shadow-sm',
        className,
      )}
      aria-label={t('inspectorAria')}
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-t-xl px-3 py-2 text-start hover:bg-stone-50"
        >
          <span className="flex min-w-0 items-center gap-2">
            <MapPin className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden />
            <span className="truncate text-sm font-semibold text-stone-800">
              {field.name}
            </span>
            <span className="hidden text-[11px] text-stone-500 sm:inline">
              {t('inspectorOpen')}
            </span>
          </span>
          <ChevronDown
            className={cn('h-4 w-4 shrink-0 text-stone-400 transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="border-t border-stone-100 px-3 pb-3 pt-2.5">
          {/* Field facts — from the fields list + the catalog latest product */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('labelArea')}</dt>
              <dd className="tabular-nums font-medium text-stone-900">
                {formatArea(field.areaHa)} {tCommon('ha')}
              </dd>
            </div>
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('labelBoundaryVersion')}</dt>
              <dd className="tabular-nums font-medium text-stone-900">
                {field.boundaryVersion != null ? `v${field.boundaryVersion}` : '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('latestValueTitle', { index: index.toUpperCase() })}</dt>
              <dd dir="ltr" className="tabular-nums font-medium text-stone-900">
                {latest?.zonal ? fmtValue(latest.zonal.mean ?? null) : '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('labelAcquired')}</dt>
              <dd dir="ltr" className="tabular-nums text-stone-800">
                {formatDay(latest?.acquired_at ?? null)}
              </dd>
            </div>
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('labelValidPixels')}</dt>
              <dd dir="ltr" className="tabular-nums text-stone-800">
                {latest?.valid_pixel_fraction != null
                  ? `${Math.round(latest.valid_pixel_fraction * 100)}%`
                  : '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2 sm:block">
              <dt className="text-stone-500">{t('labelResolution')}</dt>
              <dd dir="ltr" className="tabular-nums text-stone-800">
                {latest?.spatial_resolution_m != null ? `${latest.spatial_resolution_m} m` : '—'}
              </dd>
            </div>
          </dl>

          {!latest && (
            <p className="mt-2 rounded-md border border-amber-200 bg-amber-50/60 p-2 text-[11px] text-amber-900" role="status">
              {t('latestUnavailable')}
            </p>
          )}

          {/* Statistical tercile zones — labeled, never agronomic */}
          {zones.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-semibold text-stone-800">{t('zonesTitle')}</p>
              <div className="mt-1 overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="h-8 text-xs">{t('zoneColumn')}</TableHead>
                      <TableHead className="h-8 text-xs">{t('zoneMean')}</TableHead>
                      <TableHead className="h-8 text-xs">{t('zoneShare')}</TableHead>
                      <TableHead className="h-8 text-xs">{t('zoneRange')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {zones.map((zone) => (
                      <TableRow key={zone.zone}>
                        <TableCell className="py-1.5 text-xs font-medium">
                          {ZONE_LABEL_KEYS[zone.zone] ? t(ZONE_LABEL_KEYS[zone.zone]) : zone.zone}
                        </TableCell>
                        <TableCell dir="ltr" className="py-1.5 text-xs tabular-nums">
                          {fmtValue(zone.mean, 3)}
                        </TableCell>
                        <TableCell dir="ltr" className="py-1.5 text-xs tabular-nums">
                          {Math.round(zone.pixel_share * 100)}%
                        </TableCell>
                        <TableCell dir="ltr" className="py-1.5 text-xs tabular-nums">
                          {fmtValue(zone.value_range?.[0], 2)} … {fmtValue(zone.value_range?.[1], 2)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <p className="mt-1 text-[11px] font-medium text-amber-900" role="note">
                {t('zonesStatisticalNote')}
              </p>
              {latest?.zone_summary?.method && (
                <p className="mt-0.5 text-[10px] text-stone-400">
                  {t('labelVersion')}: {latest.zone_summary.method}
                </p>
              )}
            </div>
          )}

          {/* Actions — ≥44px touch targets on mobile */}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-11 sm:h-9"
              onClick={onFit}
              aria-label={t('fitAria')}
            >
              <Maximize2 className="h-4 w-4" aria-hidden />
              <span className="ms-1">{t('fitToField')}</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-11 sm:h-9"
              onClick={onClear}
              aria-label={t('clearAria')}
            >
              <X className="h-4 w-4" aria-hidden />
              <span className="ms-1">{t('clearSelection')}</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-11 sm:h-9"
              onClick={() => void handleExport('geojson')}
              disabled={exporting !== null}
              aria-label={t('exportGeojsonAria')}
            >
              <Download className="h-4 w-4" aria-hidden />
              <span className="ms-1">{exporting === 'geojson' ? t('exporting') : t('exportGeojson')}</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-11 sm:h-9"
              onClick={() => void handleExport('csv')}
              disabled={exporting !== null}
              aria-label={t('exportCsvAria')}
            >
              <FileDown className="h-4 w-4" aria-hidden />
              <span className="ms-1">{exporting === 'csv' ? t('exporting') : t('exportCsv')}</span>
            </Button>
          </div>
          {exportFailed && (
            <p className="mt-2 text-[11px] text-red-800" role="alert">
              {t('exportFailed')}
            </p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export default FieldInspector

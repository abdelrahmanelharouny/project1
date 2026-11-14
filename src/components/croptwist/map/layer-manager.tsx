'use client'

/**
 * P07 — unified layer manager (right panel of the Map & Satellite canvas).
 *
 * Groups the backend layer catalog into Vegetation / Environment /
 * Infrastructure collapsible sections:
 *   - Vegetation: raster index layers with visibility Switch, per-layer scene
 *     date, opacity Slider, draw-order up/down, colormap legend popover and a
 *     full provenance metadata row (source, latest acquisition, resolution,
 *     CRS, processing version, valid pixels, synthetic fixture badge).
 *   - Environment: FIELD SERIES (charts, NOT rasters) — rendered as
 *     contextual rows, never as map overlay controls.
 *   - Infrastructure: boundary / statistical zone vectors drawn by the map.
 *
 * HONESTY CONTRACT: unavailable layers stay VISIBLE in the list as disabled
 * rows carrying the backend `unavailable_reason`. Nothing is hidden, nothing
 * is faked; `is_synthetic` layers carry the synthetic fixture badge.
 */

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ChartLine,
  ChevronDown,
  ChevronUp,
  Layers,
  Palette,
  Shapes,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { ErrorState, SectionSkeleton } from '@/components/croptwist/state-views'
import { SyntheticBadge } from '@/components/croptwist/badges'
import { IndexColormapBar } from '@/components/croptwist/map/spatial-legend'
import { moveLayerOrder, sortDatesDescending } from '@/lib/map/temporal'
import { cn } from '@/lib/utils'
import { formatDay } from '@/lib/format'
import type {
  P07EnvironmentLayer,
  P07IndexCode,
  P07InfrastructureLayer,
  P07LayerCatalog,
  P07VegetationLayer,
  P07ZonePolygons,
} from '@/lib/types-p07'

/** Per-layer UI state owned by the pane; the manager renders it read-only. */
export interface P07LayerUiState {
  visible: boolean
  /** 0..100 UI percent (converted to a raster opacity fraction upstream). */
  opacityPct: number
  /** Selected scene_id from `dates_available`; null = latest acquisition. */
  selectedSceneId: string | null
}

export const DEFAULT_LAYER_UI: P07LayerUiState = {
  visible: false,
  opacityPct: 70,
  selectedSceneId: null,
}

export interface LayerManagerProps {
  catalog: P07LayerCatalog | null
  loading?: boolean
  error?: boolean
  onRetry?: () => void
  ui: Record<string, P07LayerUiState>
  onUiChange: (layerId: string, patch: Partial<P07LayerUiState>) => void
  /** Vegetation draw order (top of stack first); ids only. */
  order: string[]
  onOrderChange: (next: string[]) => void
  statisticalZonesVisible: boolean
  onStatisticalZonesVisibleChange: (visible: boolean) => void
  statisticalZonesOpacityPct: number
  onStatisticalZonesOpacityChange: (opacityPct: number) => void
  statisticalZonesLoading: boolean
  statisticalZonesError: boolean
  onRetryStatisticalZones: () => void
  statisticalZones: P07ZonePolygons | null
  hasFocusAsset: boolean
  statisticalZonesUnavailableReason?: string
  className?: string
}

const ENV_LABEL_KEYS: Record<string, string> = {
  soil_moisture: 'envSoilMoisture',
  rainfall: 'envRainfall',
  precipitation: 'envRainfall',
  evapotranspiration: 'envEvapotranspiration',
  lst: 'envLst',
  land_surface_temperature: 'envLst',
  terrain: 'envTerrain',
  elevation: 'envTerrain',
  wind: 'envWind',
  humidity: 'envHumidity',
  air_temperature: 'envAirTemperature',
}

const INFRA_LABEL_KEYS: Record<string, string> = {
  boundary: 'infraBoundary',
  statistical_zones: 'infraStatisticalZones',
}

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Math.round(value * 100)}%`
}

/** Draw-order position of a vegetation layer (top of stack = slot 0). */
function orderSlot(order: string[], id: string): number {
  const index = order.indexOf(id)
  return index < 0 ? order.length : index
}

// ------------------------------------------------------------ layer rows

function VegetationMetaRow({ layer }: { layer: P07VegetationLayer }) {
  const t = useTranslations('p07map')
  const latest = layer.latest
  const parts: string[] = []
  if (layer.source_attribution) parts.push(`${t('metaSource')}: ${layer.source_attribution}`)
  if (latest?.acquired_at) parts.push(`${t('metaAcquired')}: ${formatDay(latest.acquired_at)}`)
  if (latest?.spatial_resolution_m != null) {
    parts.push(`${t('metaResolution')}: ${latest.spatial_resolution_m} m`)
  }
  if (latest?.crs) parts.push(`${t('metaCrs')}: ${latest.crs}`)
  if (latest?.processing_version) parts.push(`${t('metaVersion')}: ${latest.processing_version}`)
  if (latest?.valid_pixel_fraction != null) {
    parts.push(`${t('metaValidPixels')}: ${formatPct(latest.valid_pixel_fraction)}`)
  }
  return (
    <p className="mt-0.5 text-[11px] leading-relaxed text-stone-500">
      {parts.join(' · ')}
    </p>
  )
}

function VegetationRow({
  layer,
  ui,
  onUiChange,
  order,
  onOrderChange,
  canReorder,
}: {
  layer: P07VegetationLayer
  ui: P07LayerUiState
  onUiChange: LayerManagerProps['onUiChange']
  order: string[]
  onOrderChange: LayerManagerProps['onOrderChange']
  canReorder: boolean
}) {
  const t = useTranslations('p07map')
  const sortedDates = useMemo(() => sortDatesDescending(layer.dates_available), [layer.dates_available])
  const slot = orderSlot(order, layer.id)
  const synthetic = layer.is_synthetic === true || layer.latest?.is_synthetic === true

  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex items-start gap-2.5">
        <Switch
          checked={ui.visible}
          onCheckedChange={(checked) => onUiChange(layer.id, { visible: checked === true })}
          aria-label={t('visibilityAria', { name: layer.label })}
          className="mt-1 h-11 w-[64px] sm:h-6 sm:w-11"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-stone-800">{layer.label}</span>
            {synthetic && <SyntheticBadge />}
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {t('metaProducts')}: {layer.product_count}
            </Badge>
          </div>
          <VegetationMetaRow layer={layer} />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {canReorder && (
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0 sm:h-8 sm:w-8"
                disabled={slot <= 0}
                onClick={() => onOrderChange(moveLayerOrder(order, layer.id, 'up'))}
                aria-label={t('moveUpAria', { name: layer.label })}
              >
                <ChevronUp className="h-4 w-4" aria-hidden />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0 sm:h-8 sm:w-8"
                disabled={slot >= order.length - 1}
                onClick={() => onOrderChange(moveLayerOrder(order, layer.id, 'down'))}
                aria-label={t('moveDownAria', { name: layer.label })}
              >
                <ChevronDown className="h-4 w-4" aria-hidden />
              </Button>
            </>
          )}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0 sm:h-8 sm:w-8"
                aria-label={t('legendTriggerAria', { name: layer.label })}
              >
                <Palette className="h-4 w-4 text-emerald-700" aria-hidden />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-60 p-3" align="end">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-stone-500">
                {t('legendTitle')}
              </p>
              <IndexColormapBar index={layer.code as P07IndexCode} />
              <p className="mt-1.5 text-[10px] text-stone-500">{t('legendNodata')}</p>
            </PopoverContent>
          </Popover>
        </div>
      </div>

      {/* Scene date + opacity — raster controls only */}
      <div className="mt-2.5 flex flex-wrap items-end gap-x-3 gap-y-2">
        <div className="flex flex-col gap-1">
          <label
            className="text-[10px] font-medium text-stone-500"
            htmlFor={`layer-date-${layer.id}`}
          >
            {t('dateSelectAria', { name: layer.label })}
          </label>
          <Select
            value={ui.selectedSceneId ?? sortedDates[0]?.scene_id ?? ''}
            onValueChange={(value) => onUiChange(layer.id, { selectedSceneId: value })}
          >
            <SelectTrigger
              id={`layer-date-${layer.id}`}
              className="h-11 w-[200px] bg-white sm:h-9"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-64">
              {sortedDates.map((entry) => (
                <SelectItem key={entry.scene_id} value={entry.scene_id}>
                  {entry.date ? formatDay(entry.date) : t('dateUnknown')}
                  <span className="ms-1 text-[10px] text-stone-400">
                    {formatPct(entry.valid_pixel_fraction)}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex min-w-[170px] flex-1 flex-col gap-1">
          <label
            className="flex items-center gap-2 text-xs font-medium text-stone-600"
            htmlFor={`layer-opacity-${layer.id}`}
          >
            <span className="shrink-0">{t('opacity')}</span>
            <span className="w-10 shrink-0 text-end tabular-nums text-stone-500">
              {ui.opacityPct}%
            </span>
          </label>
          <Slider
            id={`layer-opacity-${layer.id}`}
            min={0}
            max={100}
            step={5}
            value={[ui.opacityPct]}
            onValueChange={(values) => onUiChange(layer.id, { opacityPct: values[0] ?? 70 })}
            className="py-1"
            aria-valuetext={`${ui.opacityPct}%`}
          />
        </div>
      </div>
    </div>
  )
}

/** Visible-but-disabled row for an unavailable layer (honesty contract). */
function UnavailableRow({
  label,
  reason,
  badge,
}: {
  label: string
  reason: string | undefined
  badge?: React.ReactNode
}) {
  const t = useTranslations('p07map')
  return (
    <div className="rounded-lg border border-dashed border-stone-300 bg-stone-50/60 p-3">
      <div className="flex items-start gap-2.5">
        <Switch
          disabled
          checked={false}
          aria-label={t('visibilityAria', { name: label })}
          className="mt-1 h-11 w-[64px] sm:h-6 sm:w-11"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-stone-500">{label}</span>
            {badge}
            <Badge
              variant="outline"
              className="border-amber-300 bg-amber-50 px-1.5 py-0 text-[10px] text-amber-900"
            >
              {t('unavailable')}
            </Badge>
          </div>
          {reason && (
            <p className="mt-0.5 text-[11px] leading-relaxed text-amber-800" role="status">
              {reason}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

function EnvironmentRow({ layer }: { layer: P07EnvironmentLayer }) {
  const t = useTranslations('p07map')
  const label = ENV_LABEL_KEYS[layer.code] ? t(ENV_LABEL_KEYS[layer.code]) : layer.label
  if (!layer.available) {
    return <UnavailableRow label={label} reason={layer.unavailable_reason} />
  }
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <ChartLine className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
        <span className="text-sm font-medium text-stone-800">{label}</span>
        {layer.observation_count != null && (
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            {t('metaObservations')}: {layer.observation_count}
          </Badge>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-stone-500">
        {t('seriesNote')}
        {layer.latest_observed_at
          ? ` · ${t('metaLatestObs')}: ${formatDay(layer.latest_observed_at)}`
          : ''}
      </p>
    </div>
  )
}

function InfrastructureRow({ layer }: { layer: P07InfrastructureLayer }) {
  const t = useTranslations('p07map')
  const label = INFRA_LABEL_KEYS[layer.code] ? t(INFRA_LABEL_KEYS[layer.code]) : layer.label
  if (!layer.available) {
    return <UnavailableRow label={label} reason={layer.unavailable_reason} />
  }
  const isZones = layer.code === 'statistical_zones'
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Shapes className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
        <span className="text-sm font-medium text-stone-800">{label}</span>
        {layer.boundary_version != null && (
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            {t('metaBoundaryVersion')}: v{layer.boundary_version}
          </Badge>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-stone-500">{t('vectorNote')}</p>
      {isZones && layer.zone_note && (
        <p className="mt-1 rounded-md bg-stone-50 p-2 text-[11px] leading-relaxed text-amber-900">
          {t('zonesStatisticalNote')} {layer.zone_note}
        </p>
      )}
    </div>
  )
}

function StatisticalZonesControls({
  visible,
  onVisibleChange,
  opacityPct,
  onOpacityChange,
  loading,
  error,
  onRetry,
  polygons,
  hasFocusAsset,
  unavailableReason,
}: {
  visible: boolean
  onVisibleChange: (visible: boolean) => void
  opacityPct: number
  onOpacityChange: (opacityPct: number) => void
  loading: boolean
  error: boolean
  onRetry: () => void
  polygons: P07ZonePolygons | null
  hasFocusAsset: boolean
  unavailableReason?: string
}) {
  const t = useTranslations('p07map')
  const polygonCount = polygons?.features.filter((feature) => feature.geometry !== null).length ?? 0
  const disabled = !hasFocusAsset || Boolean(unavailableReason)

  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/30 p-3">
      <div className="flex items-start gap-2.5">
        <Switch
          checked={visible}
          disabled={disabled}
          onCheckedChange={(checked) => onVisibleChange(checked === true)}
          aria-label={t('zonesVisibilityAria')}
          className="mt-1 h-11 w-[64px] sm:h-6 sm:w-11"
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-stone-800">{t('zonesTitle')}</p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-amber-900">
            {t('zonesStatisticalNote')}
          </p>
        </div>
      </div>

      {unavailableReason && (
        <p className="mt-2 rounded-md bg-amber-50 p-2 text-[11px] text-amber-900" role="status">
          {unavailableReason}
        </p>
      )}
      {!hasFocusAsset && !unavailableReason && (
        <p className="mt-2 text-[11px] text-stone-500">{t('zonesNeedFocusProduct')}</p>
      )}

      {visible && !disabled && (
        <div className="mt-2 space-y-2 border-t border-emerald-100 pt-2">
          <div className="flex min-w-0 flex-col gap-1">
            <div
              className="flex items-center justify-between gap-2 text-xs font-medium text-stone-600"
            >
              <span id="p07-statistical-zones-opacity-label">{t('opacity')}</span>
              <span className="tabular-nums text-stone-500">{opacityPct}%</span>
            </div>
            <Slider
              min={0}
              max={100}
              step={5}
              value={[opacityPct]}
              onValueChange={(values) => onOpacityChange(values[0] ?? 60)}
              className="touch-none py-3"
              thumbProps={{
                'aria-labelledby': 'p07-statistical-zones-opacity-label',
                'aria-valuetext': `${opacityPct}%`,
              }}
            />
          </div>

          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-stone-600" aria-label={t('zonesLegendAria')}>
            <span className="inline-flex items-center gap-1">
              <i className="h-2.5 w-2.5 rounded-sm bg-amber-600" aria-hidden />
              {t('zoneLowestTercile')}
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="h-2.5 w-2.5 rounded-sm bg-lime-600" aria-hidden />
              {t('zoneMiddleTercile')}
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="h-2.5 w-2.5 rounded-sm bg-emerald-600" aria-hidden />
              {t('zoneHighestTercile')}
            </span>
          </div>

          {loading && <p className="text-[11px] text-stone-500" role="status">{t('zonesLoading')}</p>}
          {error && !loading && (
            <div className="flex flex-wrap items-center justify-between gap-2" role="alert">
              <p className="text-[11px] text-amber-900">{t('zonesLoadError')}</p>
              <Button type="button" variant="outline" className="h-11" onClick={onRetry}>
                {t('retry')}
              </Button>
            </div>
          )}
          {!loading && !error && !polygons && (
            <p className="text-[11px] text-stone-500">{t('zonesLoading')}</p>
          )}
          {!loading && !error && polygons?.available === false && (
            <p className="text-[11px] text-amber-900" role="status">
              {polygons.reason || t('zonesNoPolygons')}
            </p>
          )}
          {!loading && !error && polygons && polygons.available !== false && polygonCount === 0 && (
            <p className="text-[11px] text-stone-600" role="status">
              {t('zonesNoPolygons')}
              {polygons.zones_without_geometry.length > 0
                ? ` ${t('zonesWithoutGeometry', { count: polygons.zones_without_geometry.length })}`
                : ''}
            </p>
          )}
          {!loading && !error && polygons && polygons.available !== false && polygonCount > 0 && (
            <p className="text-[11px] text-stone-600" role="status">
              {t('zonesLoaded', { count: polygonCount })}
              {polygons.zone_note ? ` ${polygons.zone_note}` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- group

function LayerGroup({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-md px-1 text-start hover:bg-stone-50 sm:min-h-0"
        >
          <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-stone-600">
            {title}
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {count}
            </Badge>
          </span>
          <ChevronDown
            className={cn('h-4 w-4 text-stone-400 transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 pt-2">{children}</CollapsibleContent>
    </Collapsible>
  )
}

// ---------------------------------------------------------------- main

export function LayerManager({
  catalog,
  loading = false,
  error = false,
  onRetry,
  ui,
  onUiChange,
  order,
  onOrderChange,
  statisticalZonesVisible,
  onStatisticalZonesVisibleChange,
  statisticalZonesOpacityPct,
  onStatisticalZonesOpacityChange,
  statisticalZonesLoading,
  statisticalZonesError,
  onRetryStatisticalZones,
  statisticalZones,
  hasFocusAsset,
  statisticalZonesUnavailableReason,
  className,
}: LayerManagerProps) {
  const t = useTranslations('p07map')

  const vegetation = catalog?.layers.vegetation ?? []
  const environment = catalog?.layers.environment ?? []
  const infrastructure = catalog?.layers.infrastructure ?? []

  // Available vegetation layers in draw order (top of stack first), then
  // unavailable ones in backend order — always rendered, never hidden.
  const vegetationRows = useMemo(() => {
    const available = vegetation.filter((layer) => layer.available)
    const sorted = [...available].sort(
      (a, b) => orderSlot(order, a.id) - orderSlot(order, b.id),
    )
    const unavailable = vegetation.filter((layer) => !layer.available)
    return { available: sorted, unavailable }
  }, [vegetation, order])

  const vegetationLabel = (layer: P07VegetationLayer): string => {
    const key = `index${layer.code.charAt(0).toUpperCase()}${layer.code.slice(1)}`
    return t(key)
  }

  return (
    <Card className={cn('border-stone-200 bg-white shadow-sm', className)}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('managerTitle')}
        </CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('managerDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && <SectionSkeleton lines={6} />}
        {error && !loading && <ErrorState message={t('loadError')} onRetry={onRetry} />}
        {catalog && (
          <div className="space-y-4">
            <LayerGroup title={t('groupVegetation')} count={vegetation.length}>
              {vegetationRows.available.length === 0 &&
                vegetationRows.unavailable.length === 0 && (
                  <p className="rounded-lg border border-dashed border-stone-300 bg-stone-50/60 p-3 text-sm text-stone-500">
                    {t('noVegetationAvailable')}
                  </p>
                )}
              {vegetationRows.available.map((layer) => (
                <VegetationRow
                  key={layer.id}
                  layer={layer}
                  ui={ui[layer.id] ?? DEFAULT_LAYER_UI}
                  onUiChange={onUiChange}
                  order={order}
                  onOrderChange={onOrderChange}
                  canReorder={vegetationRows.available.length > 1}
                />
              ))}
              {vegetationRows.unavailable.map((layer) => (
                <UnavailableRow
                  key={layer.id}
                  label={vegetationLabel(layer)}
                  reason={layer.unavailable_reason}
                  badge={layer.is_synthetic === true ? <SyntheticBadge /> : undefined}
                />
              ))}
            </LayerGroup>

            {environment.length > 0 && (
              <>
                <Separator />
                <LayerGroup title={t('groupEnvironment')} count={environment.length}>
                  {environment.map((layer) => (
                    <EnvironmentRow key={layer.id} layer={layer} />
                  ))}
                </LayerGroup>
              </>
            )}

            <>
              <Separator />
              <LayerGroup title={t('groupInfrastructure')} count={infrastructure.length + 1}>
                {infrastructure.map((layer) => (
                  <InfrastructureRow key={layer.id} layer={layer} />
                ))}
                <StatisticalZonesControls
                  visible={statisticalZonesVisible}
                  onVisibleChange={onStatisticalZonesVisibleChange}
                  opacityPct={statisticalZonesOpacityPct}
                  onOpacityChange={onStatisticalZonesOpacityChange}
                  loading={statisticalZonesLoading}
                  error={statisticalZonesError}
                  onRetry={onRetryStatisticalZones}
                  polygons={statisticalZones}
                  hasFocusAsset={hasFocusAsset}
                  unavailableReason={statisticalZonesUnavailableReason}
                />
              </LayerGroup>
            </>
          </div>
        )}
        {catalog && (
          <p className="text-[10px] text-stone-400">
            {t('catalogVersion', { version: catalog.catalog_version })}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export default LayerManager

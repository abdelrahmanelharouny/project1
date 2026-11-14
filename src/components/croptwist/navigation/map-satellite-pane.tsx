'use client'

/**
 * P07 (task 2-a) — Map & Satellite destination canvas.
 *
 * Composition (keeps the P02 blueprint: FarmMap canvas + docked side panel):
 *   - `FarmMap` renders the farm's fields. Its instance is STABLE — every
 *     VISIBLE vegetation layer becomes one server-rendered XYZ raster overlay
 *     (`productTileUrlTemplate` → MapLibre raster source, same-origin cookies)
 *     applied incrementally, z-ordered by the layer manager's draw order.
 *   - `TemporalExplorer` sits above the map: date chips, prev/next stepping,
 *     honest coverage gaps and the temporal-compatibility warning.
 *   - `SpatialLegend` floats on the map (documented colormap + nodata note).
 *   - `FieldInspector` docks under the map for the selected field.
 *   - `SatelliteIntelligence` keeps every existing capability (unchanged).
 *   - The new `LayerManager` (backend layer catalog) replaces the former P05
 *     SatelliteLayersCard and preserves all of its capabilities: per-layer
 *     index visibility, scene-date select, opacity, provenance metadata and
 *     the documented colormap legend.
 *
 * State shape: per-layer UI state and the draw order are stored as
 * FIELD-SCOPED overrides (a `null` override falls back to catalog defaults —
 * first available vegetation layer visible at 70% opacity, backend draw
 * order). Nothing is synced through effects; everything is derived.
 *
 * Honesty contract: overlays exist ONLY for derived assets the backend
 * actually resolves (catalog `latest.asset_id`, or the processing ledger's
 * asset for the selected scene). When nothing resolves, nothing is drawn and
 * the pane says so. The processing ledger keeps its poll behavior untouched.
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { TriangleAlert } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  FarmMap,
  type FarmMapFitRequest,
  type FarmMapOverlay,
  type FarmMapStatisticalZone,
} from '@/components/croptwist/farm-map'
import { SatelliteIntelligence } from '@/components/croptwist/satellite'
import {
  DEFAULT_LAYER_UI,
  LayerManager,
  type P07LayerUiState,
} from '@/components/croptwist/map/layer-manager'
import { TemporalExplorer } from '@/components/croptwist/map/temporal-explorer'
import {
  FieldInspector,
  type FieldInspectorField,
} from '@/components/croptwist/map/field-inspector'
import { SpatialLegend } from '@/components/croptwist/map/spatial-legend'
import { useFields, useSatelliteProcessing } from '@/hooks/use-croptwist'
import { useLayerCatalog, useProductValueSample, useProductZones } from '@/hooks/use-p07'
import { formatDay } from '@/lib/format'
import { productTileUrlTemplate } from '@/lib/api-p07'
import {
  dayFromIso,
  opacityFraction,
  sortDatesDescending,
  zIndexForOrderSlot,
  type TemporalCompatibilityInput,
} from '@/lib/map/temporal'
import { useCropTwistUi } from '@/lib/store'
import type { Field, SatelliteProcessingScene } from '@/lib/types'
import type {
  P07IndexCode,
  P07LayerDates,
  P07VegetationLayer,
  P07ZonePolygons,
} from '@/lib/types-p07'

/** P07 vegetation indexes (backend catalog contract: exactly these five). */
const P07_INDEX_CODES: readonly P07IndexCode[] = ['ndvi', 'evi', 'ndmi', 'ndwi', 'bsi']

function resolveDerivedAssetId(
  layer: P07VegetationLayer,
  entry: P07LayerDates,
  sceneMap: Map<string, SatelliteProcessingScene>,
): string | null {
  if (
    layer.latest?.scene_id === entry.scene_id &&
    layer.latest.processing_version === entry.processing_version
  ) {
    return layer.latest.asset_id
  }
  const scene = sceneMap.get(entry.scene_id)
  if (!scene) return null
  return (
    scene.products.find(
      (product) =>
        product.index_code === layer.code &&
        product.processing_version === entry.processing_version,
    )?.asset_id ?? null
  )
}

function displayNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 5 }).format(value)
}

export function MapSatellitePane() {
  const t = useTranslations('p07map')
  const tMap = useTranslations('map')
  const tNav = useTranslations('nav')

  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)

  const fieldsQuery = useFields(selectedFarmId, Boolean(selectedFarmId))
  const fieldId = selectedField?.id ?? null
  const catalogQuery = useLayerCatalog(fieldId)
  const catalog = catalogQuery.data ?? null

  // Processing ledger — poll behavior untouched (5s while any scene is
  // mid-derivation); used here to map scene_id → derived asset id.
  const processingQuery = useSatelliteProcessing(fieldId)

  // ---------------------------------------------------------------- state
  // FIELD-SCOPED user overrides: null (or a different field) means "fall back
  // to catalog defaults". Switching fields therefore needs no reset effect —
  // the stale override is simply ignored.
  const [uiOverride, setUiOverride] = useState<{
    fieldId: string
    ui: Record<string, P07LayerUiState>
  } | null>(null)
  const [orderOverride, setOrderOverride] = useState<{
    fieldId: string
    ids: string[]
  } | null>(null)
  const [focusIndex, setFocusIndex] = useState<P07IndexCode>('ndvi')
  const [fitRequest, setFitRequest] = useState<FarmMapFitRequest | null>(null)
  const [zoneUiOverride, setZoneUiOverride] = useState<{
    fieldId: string
    visible: boolean
    opacityPct: number
  } | null>(null)
  const [sampleRequest, setSampleRequest] = useState<{
    fieldId: string
    lon: number
    lat: number
    requestId: number
  } | null>(null)
  const sampleRequestId = useRef(0)
  const [selectedZone, setSelectedZone] = useState<{
    fieldId: string
    assetId: string
    properties: FarmMapStatisticalZone
  } | null>(null)
  // Tile errors are stored per visible-overlay set (key = the id list), so
  // stale sets age out without any effect-driven state clearing.
  const [overlayErrorsBySet, setOverlayErrorsBySet] = useState<Record<string, string[]>>({})

  const zonesVisible =
    zoneUiOverride?.fieldId === fieldId ? zoneUiOverride.visible : false
  const zonesOpacityPct =
    zoneUiOverride?.fieldId === fieldId ? zoneUiOverride.opacityPct : 60

  const vegetation = useMemo(() => catalog?.layers.vegetation ?? [], [catalog])

  // Effective per-layer UI state: catalog defaults (first available vegetation
  // layer visible at 70% opacity) overridden by the user's explicit choices.
  const layerUi = useMemo<Record<string, P07LayerUiState>>(() => {
    const overrides = uiOverride && uiOverride.fieldId === fieldId ? uiOverride.ui : {}
    if (!catalog) return overrides
    const firstAvailableId =
      catalog.layers.vegetation.find((layer) => layer.available)?.id ?? null
    const out: Record<string, P07LayerUiState> = {}
    for (const layer of catalog.layers.vegetation) {
      out[layer.id] =
        overrides[layer.id] ?? { ...DEFAULT_LAYER_UI, visible: layer.id === firstAvailableId }
    }
    return out
  }, [catalog, uiOverride, fieldId])

  // Effective draw order: backend vegetation order unless the user reordered.
  const order = useMemo<string[]>(() => {
    if (orderOverride && orderOverride.fieldId === fieldId) return orderOverride.ids
    return vegetation.map((layer) => layer.id)
  }, [orderOverride, fieldId, vegetation])

  const handleUiChange = useCallback(
    (layerId: string, patch: Partial<P07LayerUiState>) => {
      setUiOverride((prev) => {
        const base = prev && prev.fieldId === fieldId ? { ...prev.ui } : {}
        base[layerId] = { ...(base[layerId] ?? DEFAULT_LAYER_UI), ...patch }
        return { fieldId: fieldId ?? '', ui: base }
      })
    },
    [fieldId],
  )

  const handleOrderChange = useCallback(
    (next: string[]) => setOrderOverride({ fieldId: fieldId ?? '', ids: next }),
    [fieldId],
  )

  // ------------------------------------------------------------ focus layer
  const focusLayer = useMemo<P07VegetationLayer | null>(() => {
    return vegetation.find((layer) => layer.code === focusIndex && layer.available) ?? null
  }, [vegetation, focusIndex])

  const focusUi = focusLayer ? (layerUi[focusLayer.id] ?? DEFAULT_LAYER_UI) : DEFAULT_LAYER_UI

  const focusEntry = useMemo(() => {
    if (!focusLayer) return null
    const sorted = sortDatesDescending(focusLayer.dates_available)
    if (focusUi.selectedSceneId) {
      const found = sorted.find((entry) => entry.scene_id === focusUi.selectedSceneId)
      if (found) return found
    }
    return sorted[0] ?? null
  }, [focusLayer, focusUi.selectedSceneId])

  const focusDay = focusEntry ? dayFromIso(focusEntry.date) : null

  const handleSelectDay = useCallback(
    (day: string) => {
      if (!focusLayer) return
      const entry = focusLayer.dates_available.find(
        (candidate) => dayFromIso(candidate.date) === day,
      )
      if (!entry) return
      handleUiChange(focusLayer.id, { selectedSceneId: entry.scene_id })
    },
    [focusLayer, handleUiChange],
  )

  // ------------------------------------------------------- scene → asset map
  const sceneMap = useMemo(() => {
    const map = new Map<string, SatelliteProcessingScene>()
    for (const scene of processingQuery.data?.scenes ?? []) map.set(scene.scene_id, scene)
    return map
  }, [processingQuery.data])

  const focusAssetId = useMemo(
    () =>
      focusLayer && focusEntry
        ? resolveDerivedAssetId(focusLayer, focusEntry, sceneMap)
        : null,
    [focusLayer, focusEntry, sceneMap],
  )
  const activeSamplePoint =
    sampleRequest?.fieldId === fieldId
      ? {
          lon: sampleRequest.lon,
          lat: sampleRequest.lat,
          requestId: sampleRequest.requestId,
        }
      : null
  const sampleQuery = useProductValueSample(fieldId, focusAssetId, activeSamplePoint)

  const statisticalZonesLayer = catalog?.layers.infrastructure.find(
    (layer) => layer.code === 'statistical_zones',
  )
  const zonesQuery = useProductZones(
    fieldId,
    focusAssetId,
    zonesVisible && statisticalZonesLayer?.available === true,
  )
  const zoneResponseMatchesFocus =
    !!zonesQuery.data &&
    zonesQuery.data.asset_id === focusAssetId &&
    zonesQuery.data.index === focusLayer?.code
  const statisticalZones: P07ZonePolygons | null = zoneResponseMatchesFocus
    ? zonesQuery.data ?? null
    : null
  const statisticalZonesError = zonesQuery.isError || (!!zonesQuery.data && !zoneResponseMatchesFocus)
  const statisticalZonesGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: 'FeatureCollection',
    features: (statisticalZones?.features ?? []).filter((feature) => feature.geometry !== null) as unknown as GeoJSON.Feature[],
  }), [statisticalZones])

  const handleZonesVisibleChange = useCallback(
    (visible: boolean) => {
      setZoneUiOverride((prev) => ({
        fieldId: fieldId ?? '',
        visible,
        opacityPct: prev?.fieldId === fieldId ? prev.opacityPct : 60,
      }))
    },
    [fieldId],
  )
  const handleZonesOpacityChange = useCallback(
    (opacityPct: number) => {
      setZoneUiOverride((prev) => ({
        fieldId: fieldId ?? '',
        visible: prev?.fieldId === fieldId ? prev.visible : false,
        opacityPct,
      }))
    },
    [fieldId],
  )
  const handleStatisticalZoneClick = useCallback(
    (properties: FarmMapStatisticalZone) => {
      if (!fieldId || !focusAssetId) return
      setSelectedZone({ fieldId, assetId: focusAssetId, properties })
    },
    [fieldId, focusAssetId],
  )
  const displayedZone =
    selectedZone?.fieldId === fieldId && selectedZone.assetId === focusAssetId
      ? selectedZone.properties
      : null

  // --------------------------------------------------------------- overlays
  // One overlay per VISIBLE vegetation layer with its own selected date.
  // Only real, backend-resolved assets become overlays — otherwise the layer
  // is reported as missing, never faked.
  const { overlays, missingTiles } = useMemo(() => {
    const out: FarmMapOverlay[] = []
    const missing: string[] = []
    if (!fieldId || !catalog) return { overlays: out, missingTiles: missing }

    for (const layer of vegetation) {
      if (!layer.available) continue
      const ui = layerUi[layer.id] ?? DEFAULT_LAYER_UI
      if (!ui.visible) continue
      const sorted = sortDatesDescending(layer.dates_available)
      const entry =
        (ui.selectedSceneId
          ? sorted.find((candidate) => candidate.scene_id === ui.selectedSceneId)
          : undefined) ?? sorted[0]
      if (!entry) {
        missing.push(layer.label)
        continue
      }
      const assetId = resolveDerivedAssetId(layer, entry, sceneMap)
      if (!assetId) {
        missing.push(layer.label)
        continue
      }
      out.push({
        id: layer.id,
        tileUrl: productTileUrlTemplate(fieldId, assetId),
        opacity: opacityFraction(ui.opacityPct),
        visible: true,
        zIndex: zIndexForOrderSlot(order, layer.id),
      })
    }
    return { overlays: out, missingTiles: missing }
  }, [catalog, fieldId, vegetation, layerUi, order, sceneMap])

  // Honest tile-error notes, scoped to the current visible-overlay set so
  // toggling a layer or switching fields starts a clean slate (no effects).
  const overlayIdKey = overlays.map((overlay) => overlay.id).join('|')
  const overlayErrors = overlayErrorsBySet[overlayIdKey] ?? []

  // FarmMap keeps handlers in a ref refreshed every render, so rebinding per
  // overlay-set is free — the callback always reports into its own set key.
  const handleOverlayError = useCallback(
    (id: string) => {
      setOverlayErrorsBySet((prev) => {
        const current = prev[overlayIdKey] ?? []
        if (current.includes(id)) return prev
        return { [overlayIdKey]: [...current, id] }
      })
    },
    [overlayIdKey],
  )

  // --------------------------------------- temporal compatibility inputs
  const visibleLayerDates = useMemo<TemporalCompatibilityInput[]>(() => {
    const inputs: TemporalCompatibilityInput[] = []
    for (const layer of vegetation) {
      if (!layer.available) continue
      const ui = layerUi[layer.id] ?? DEFAULT_LAYER_UI
      if (!ui.visible) continue
      const sorted = sortDatesDescending(layer.dates_available)
      const entry =
        (ui.selectedSceneId
          ? sorted.find((candidate) => candidate.scene_id === ui.selectedSceneId)
          : undefined) ?? sorted[0]
      inputs.push({ id: layer.id, date: entry ? dayFromIso(entry.date) : null })
    }
    return inputs
  }, [vegetation, layerUi])

  // ------------------------------------------------------- field selection
  const handleFieldSelect = useCallback(
    (field: Field) => {
      setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
    },
    [setSelectedField],
  )

  const handleBoundaryClick = useCallback(
    (field: Field, lngLat: { lng: number; lat: number }) => {
      handleFieldSelect(field)
      setSampleRequest({
        fieldId: field.id,
        lon: lngLat.lng,
        lat: lngLat.lat,
        requestId: ++sampleRequestId.current,
      })
    },
    [handleFieldSelect],
  )

  const handleClearSelection = useCallback(() => setSelectedField(null), [setSelectedField])

  const handleFit = useCallback(() => {
    if (!fieldId) return
    setFitRequest((prev) => ({ fieldId, seq: (prev?.seq ?? 0) + 1 }))
  }, [fieldId])

  const fields = useMemo(() => fieldsQuery.data?.items ?? [], [fieldsQuery.data])

  const inspectorField = useMemo<FieldInspectorField | null>(() => {
    if (!selectedField) return null
    const record = fields.find((entry) => entry.id === selectedField.id)
    if (!record) return null
    return {
      id: record.id,
      name: record.name,
      areaHa: record.postgis_geodesic_area_ha ?? record.area_ha ?? null,
      boundaryVersion: record.boundary_version ?? null,
    }
  }, [fields, selectedField])

  // ---------------------------------------------------------------- render
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px] [&>*]:min-w-0">
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{tMap('farmMapTitle')}</CardTitle>
          <CardDescription>
            {tMap('farmMapDesc')} {tMap('clickHint')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Focus index — drives the legend, timeline and inspector */}
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="p07-focus-index" className="text-xs font-medium text-stone-600">
              {t('focusIndex')}
            </label>
            <Select
              value={focusIndex}
              onValueChange={(value) => setFocusIndex(value as P07IndexCode)}
            >
              <SelectTrigger
                id="p07-focus-index"
                aria-label={t('focusIndexAria')}
                className="h-11 w-[210px] bg-white sm:h-9"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {P07_INDEX_CODES.map((code) => {
                  const layer = vegetation.find((entry) => entry.code === code)
                  const available = layer?.available === true
                  return (
                    <SelectItem key={code} value={code} disabled={!available}>
                      {code.toUpperCase()}
                      {!available && (
                        <span className="ms-1 text-[10px] text-stone-400">{t('unavailable')}</span>
                      )}
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
          </div>

          <TemporalExplorer
            index={focusLayer?.code ?? focusIndex}
            dates={focusLayer?.dates_available ?? []}
            selectedDay={focusDay}
            onSelectDay={handleSelectDay}
            visibleLayerDates={visibleLayerDates}
          />

          <div className="relative">
            <FarmMap
              fields={fields}
              selectedFieldId={selectedField?.id ?? null}
              onFieldSelect={handleFieldSelect}
              onFieldClick={handleBoundaryClick}
              overlays={overlays}
              statisticalZones={statisticalZonesGeoJSON}
              statisticalZonesVisible={
                zonesVisible && statisticalZonesGeoJSON.features.length > 0
              }
              statisticalZonesOpacity={zonesOpacityPct / 100}
              onStatisticalZoneClick={handleStatisticalZoneClick}
              onOverlayError={handleOverlayError}
              fitRequest={fitRequest}
            />
            {/* The legend floats on the LTR map canvas — PHYSICAL left/top on
                purpose: MapLibre's nav control sits at physical top-right, so
                a logical start-3 anchor would collide with it in RTL. */}
            <SpatialLegend
              index={focusLayer?.code ?? focusIndex}
              className="absolute left-3 top-3 z-10 w-56"
              defaultOpen={false}
            />
          </div>

          <section
            className="rounded-lg border border-stone-200 bg-stone-50/70 p-3"
            aria-live="polite"
          >
            <h3 className="text-sm font-semibold text-stone-800">{t('sampleTitle')}</h3>
            {!activeSamplePoint && (
              <p className="mt-1 text-xs text-stone-600">{t('samplePrompt')}</p>
            )}
            {activeSamplePoint && (
              <>
                <p className="mt-1 text-[11px] text-stone-500">{t('sampleCoordinates')}</p>
                <p dir="ltr" className="font-mono text-xs text-stone-700">
                  {String(activeSamplePoint.lon)}, {String(activeSamplePoint.lat)}
                </p>
              </>
            )}
            {activeSamplePoint && !focusAssetId && (
              <p className="mt-2 text-xs text-amber-900" role="status">
                {catalogQuery.isLoading || processingQuery.isLoading
                  ? t('sampleWaitingProduct')
                  : t('sampleNoProduct')}
              </p>
            )}
            {activeSamplePoint && focusAssetId && sampleQuery.isLoading && (
              <p className="mt-2 text-xs text-stone-600" role="status">{t('sampleLoading')}</p>
            )}
            {activeSamplePoint && focusAssetId && sampleQuery.isError && (
              <p className="mt-2 text-xs text-amber-900" role="alert">{t('sampleError')}</p>
            )}
            {activeSamplePoint && sampleQuery.data && (
              <div className="mt-2 space-y-2">
                <p
                  className={
                    sampleQuery.data.available && sampleQuery.data.value !== null
                      ? 'text-sm font-semibold text-stone-900'
                      : 'text-xs font-medium text-amber-900'
                  }
                  role="status"
                >
                  {sampleQuery.data.available && sampleQuery.data.value !== null
                    ? `${t('sampleValue')}: ${displayNumber(sampleQuery.data.value)}`
                    : t('sampleNoValidPixel')}
                </p>
                {sampleQuery.data.unavailable_reason && (
                  <p className="text-[11px] text-amber-900">
                    {t('sampleReason')}:{' '}
                    {t(
                      sampleQuery.data.unavailable_reason === 'point_outside_raster_extent'
                        ? 'sampleOutsideRaster'
                        : 'sampleMaskedPixel',
                    )}
                  </p>
                )}
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] text-stone-600">
                  <dt>{t('sampleIndex')}</dt><dd>{sampleQuery.data.index.toUpperCase()}</dd>
                  <dt>{t('sampleAcquired')}</dt>
                  <dd>{sampleQuery.data.acquired_at ? formatDay(sampleQuery.data.acquired_at) : t('sampleNotReported')}</dd>
                  <dt>{t('sampleScene')}</dt><dd className="break-all">{sampleQuery.data.scene_id}</dd>
                  <dt>{t('sampleVersion')}</dt><dd>{sampleQuery.data.processing_version}</dd>
                  <dt>{t('sampleResolution')}</dt>
                  <dd>{sampleQuery.data.spatial_resolution_m == null ? t('sampleNotReported') : `${displayNumber(sampleQuery.data.spatial_resolution_m)} m`}</dd>
                  <dt>{t('sampleSource')}</dt><dd>{sampleQuery.data.provider_code || t('sampleNotReported')}</dd>
                  <dt>{t('sampleCrs')}</dt><dd>{sampleQuery.data.crs || t('sampleNotReported')}</dd>
                  <dt>{t('sampleCloud')}</dt>
                  <dd>{sampleQuery.data.cloud_cover_pct == null ? t('sampleNotReported') : `${displayNumber(sampleQuery.data.cloud_cover_pct)}%`}</dd>
                  <dt>{t('sampleSynthetic')}</dt>
                  <dd>
                    {sampleQuery.data.is_synthetic == null
                      ? t('sampleNotReported')
                      : sampleQuery.data.is_synthetic
                        ? t('sampleYes')
                        : t('sampleNo')}
                  </dd>
                </dl>
              </div>
            )}
          </section>

          {zonesVisible && (
            <section className="rounded-lg border border-emerald-200 bg-white p-3" aria-live="polite">
              <h3 className="text-sm font-semibold text-stone-800">{t('zoneClickTitle')}</h3>
              <p className="mt-1 text-[11px] text-amber-900">{t('zonesStatisticalNote')}</p>
              {!displayedZone && (
                <p className="mt-1 text-[11px] text-stone-500">{t('zoneClickPrompt')}</p>
              )}
              {displayedZone && (
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] text-stone-600">
                  <dt>{t('zoneColumn')}</dt>
                  <dd>{t(displayedZone.zone === 'lowest_tercile'
                    ? 'zoneLowestTercile'
                    : displayedZone.zone === 'middle_tercile'
                      ? 'zoneMiddleTercile'
                      : displayedZone.zone === 'highest_tercile'
                        ? 'zoneHighestTercile'
                        : 'zoneColumn')}</dd>
                  <dt>{t('zoneClickMean')}</dt><dd>{displayNumber(displayedZone.mean)}</dd>
                  <dt>{t('zoneClickShare')}</dt><dd>{displayNumber(displayedZone.pixel_share * 100)}%</dd>
                  <dt>{t('zoneClickRange')}</dt>
                  <dd>{displayedZone.value_range
                    ? `${displayNumber(displayedZone.value_range[0])} – ${displayNumber(displayedZone.value_range[1])}`
                    : '—'}</dd>
                  <dt>{t('zoneClickPixels')}</dt><dd>{displayNumber(displayedZone.pixel_count)}</dd>
                </dl>
              )}
            </section>
          )}

          {/* Honest overlay status — tile failures and unresolved assets */}
          {(overlayErrors.length > 0 || missingTiles.length > 0) && (
            <div
              className="rounded-md border border-amber-200 bg-amber-50/60 p-2.5 text-[11px] text-amber-900"
              role="status"
            >
              <p className="flex items-center gap-1.5 font-semibold">
                <TriangleAlert className="h-3.5 w-3.5" aria-hidden />
                {t('overlayErrorsTitle')}
              </p>
              <ul className="mt-1 list-disc space-y-0.5 ps-4">
                {overlayErrors.map((id) => {
                  const label = vegetation.find((layer) => layer.id === id)?.label ?? id
                  return <li key={`tile-error-${id}`}>{t('overlayErrorItem', { name: label })}</li>
                })}
                {missingTiles.map((label, index) => (
                  <li key={`missing-${label}-${index}`}>{t('noTilesForDate', { name: label })}</li>
                ))}
              </ul>
            </div>
          )}

          <FieldInspector
            field={inspectorField}
            index={focusLayer?.code ?? focusIndex}
            latest={focusLayer?.latest ?? null}
            onFit={handleFit}
            onClear={handleClearSelection}
          />
        </CardContent>
      </Card>

      <div className="min-w-0 space-y-4" aria-label={tNav('satellite')}>
        <SatelliteIntelligence />
        <LayerManager
          catalog={catalog}
          loading={catalogQuery.isLoading}
          error={catalogQuery.isError}
          onRetry={() => void catalogQuery.refetch()}
          ui={layerUi}
          onUiChange={handleUiChange}
          order={order}
          onOrderChange={handleOrderChange}
          statisticalZonesVisible={zonesVisible}
          onStatisticalZonesVisibleChange={handleZonesVisibleChange}
          statisticalZonesOpacityPct={zonesOpacityPct}
          onStatisticalZonesOpacityChange={handleZonesOpacityChange}
          statisticalZonesLoading={zonesQuery.isLoading}
          statisticalZonesError={statisticalZonesError}
          onRetryStatisticalZones={() => void zonesQuery.refetch()}
          statisticalZones={statisticalZones}
          hasFocusAsset={Boolean(focusAssetId)}
          statisticalZonesUnavailableReason={
            !statisticalZonesLayer || statisticalZonesLayer.available === false
              ? statisticalZonesLayer?.unavailable_reason || t('zonesUnavailable')
              : undefined
          }
        />
      </div>
    </div>
  )
}

export default MapSatellitePane

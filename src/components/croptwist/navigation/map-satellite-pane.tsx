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

import { useCallback, useMemo, useState } from 'react'
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
import { useLayerCatalog } from '@/hooks/use-p07'
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
import type { P07IndexCode, P07VegetationLayer } from '@/lib/types-p07'

/** P07 vegetation indexes (backend catalog contract: exactly these five). */
const P07_INDEX_CODES: readonly P07IndexCode[] = ['ndvi', 'evi', 'ndmi', 'ndwi', 'bsi']

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
  // Tile errors are stored per visible-overlay set (key = the id list), so
  // stale sets age out without any effect-driven state clearing.
  const [overlayErrorsBySet, setOverlayErrorsBySet] = useState<Record<string, string[]>>({})

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
    return (
      vegetation.find((layer) => layer.code === focusIndex && layer.available) ??
      vegetation.find((layer) => layer.available) ??
      null
    )
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

  // --------------------------------------------------------------- overlays
  // One overlay per VISIBLE vegetation layer with its own selected date.
  // Only real, backend-resolved assets become overlays — otherwise the layer
  // is reported as missing, never faked.
  const { overlays, missingTiles } = useMemo(() => {
    const out: FarmMapOverlay[] = []
    const missing: string[] = []
    if (!fieldId || !catalog) return { overlays: out, missingTiles: missing }

    const resolveAssetId = (
      layer: P07VegetationLayer,
      sceneId: string,
      processingVersion: string | null,
    ): string | null => {
      if (layer.latest && layer.latest.scene_id === sceneId) return layer.latest.asset_id
      const scene = sceneMap.get(sceneId)
      if (!scene) return null
      const candidates = scene.products.filter((product) => product.index_code === layer.code)
      if (candidates.length === 0) return null
      if (processingVersion) {
        const exact = candidates.find(
          (product) => product.processing_version === processingVersion,
        )
        if (exact) return exact.asset_id
      }
      return candidates[candidates.length - 1]?.asset_id ?? null
    }

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
      const assetId = resolveAssetId(layer, entry.scene_id, entry.processing_version)
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
              onFieldClick={handleFieldSelect}
              overlays={overlays}
              onOverlayError={handleOverlayError}
              fitRequest={fitRequest}
            />
            {/* The legend floats on the LTR map canvas — PHYSICAL left/top on
                purpose: MapLibre's nav control sits at physical top-right, so
                a logical start-3 anchor would collide with it in RTL. */}
            <SpatialLegend
              index={focusIndex}
              className="absolute left-3 top-3 z-10 w-56"
              defaultOpen={false}
            />
          </div>

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
            index={focusIndex}
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
        />
      </div>
    </div>
  )
}

export default MapSatellitePane

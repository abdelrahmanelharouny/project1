'use client'

/**
 * P02 W1 — Map & Satellite destination canvas (blueprint C3).
 *
 * Composition ONLY — both components are mounted verbatim with their existing
 * props/contracts:
 *   - `FarmMap` becomes the destination canvas (fields of the context farm)
 *   - `SatelliteIntelligence` (the former full-width Satellite tab) docks as
 *     the side panel beside the map it decorates
 *
 * Honesty contract preserved: the base map introduces NO imagery — it
 * rearranges the existing offline map + vegetation index/scenes surfaces.
 * P05 adds ONE explicit raster surface: the "Satellite layers" card renders
 * the backend's own preview PNG of a derived index product, georeferenced to
 * the product's documented WGS84 bbox via a MapLibre image source. Every
 * layer carries its provenance (provider/product, synthetic fixture badge,
 * processing version, valid-pixel fraction) and the documented colormap is
 * described in the legend — nothing is invented client-side.
 *
 * FarmMap's worker setup stays a module-level singleton (farm-map.tsx) and
 * only one instance is mounted at a time (same as today). Field selection
 * writes the same store slice; clicking a field on the canvas selects it for
 * the satellite panel without navigating away.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Eye, EyeOff, Layers } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { FarmMap, type SatelliteMapOverlay } from '@/components/croptwist/farm-map'
import { SatelliteIntelligence } from '@/components/croptwist/satellite'
import { ErrorState, SectionSkeleton } from '@/components/croptwist/state-views'
import { SyntheticBadge } from '@/components/croptwist/badges'
import {
  useFields,
  useSatelliteProcessing,
} from '@/hooks/use-croptwist'
import { fetchSatelliteAssetBlob } from '@/lib/api'
import { useCropTwistUi } from '@/lib/store'
import type {
  SatelliteDerivedProduct,
  SatelliteProcessingScene,
} from '@/lib/types'

/**
 * Layer-card index options (P05 selector contract: ndvi/evi/ndmi/ndwi/bsi).
 * Documented ranges are the backend's own `documented_range` values
 * (live-verified): they drive the legend scale, never invented client-side.
 */
const LAYER_INDEX_CODES = ['ndvi', 'evi', 'ndmi', 'ndwi', 'bsi'] as const
type LayerIndexCode = (typeof LAYER_INDEX_CODES)[number]

const DOCUMENTED_RANGES: Record<LayerIndexCode, [number, number]> = {
  ndvi: [-1, 1],
  evi: [-1, 3],
  ndmi: [-1, 1],
  ndwi: [-1, 1],
  bsi: [-1, 1],
}

/** Documented colormap of the backend preview renderings: brown → white → green. */
const COLORMAP_GRADIENT = 'linear-gradient(to right, #8a5a2b, #f5f5f4 50%, #15803d)'

/** One scene + its derived product for a given index. */
interface LayerEntry {
  scene: SatelliteProcessingScene
  product: SatelliteDerivedProduct
}

interface SatelliteLayersState {
  query: ReturnType<typeof useSatelliteProcessing>
  /** scene+product entries per index code, most recent first. */
  entriesByIndex: Record<LayerIndexCode, LayerEntry[]>
  index: LayerIndexCode
  setIndex: (code: LayerIndexCode) => void
  sceneId: string | null
  setSceneId: (id: string | null) => void
  opacityPct: number
  setOpacityPct: (pct: number) => void
  visible: boolean
  setVisible: (visible: boolean) => void
  selectedEntry: LayerEntry | null
  /** Preview blob state for the currently selected asset. */
  preview: { url: string | null; loading: boolean; error: boolean }
  overlay: SatelliteMapOverlay | null
}

/**
 * Selection state + preview blob lifecycle for the satellite layers card.
 * The blob URL is owned here: revoked in cleanup when replaced or unmounted.
 * (FarmMap is a child — its map teardown runs before this cleanup, so the URL
 * is never revoked while a live map still references it.)
 */
function useSatelliteLayers(fieldId: string | null): SatelliteLayersState {
  const query = useSatelliteProcessing(fieldId)

  const [index, setIndexRaw] = useState<LayerIndexCode>('ndvi')
  const [sceneId, setSceneId] = useState<string | null>(null)
  const [opacityPct, setOpacityPct] = useState(70)
  const [visible, setVisible] = useState(true)
  // Preview fetch result, keyed to the asset it belongs to: while the fetch for
  // the currently selected asset is in flight, the derived `preview` below
  // reports loading — no synchronous setState inside the effect needed.
  const [previewState, setPreviewState] = useState<{
    assetId: string | null
    url: string | null
    error: boolean
  }>({ assetId: null, url: null, error: false })

  const scenes = query.data?.scenes ?? []

  const entriesByIndex = useMemo(() => {
    const byIndex = Object.fromEntries(
      LAYER_INDEX_CODES.map((code) => [code, [] as LayerEntry[]]),
    ) as Record<LayerIndexCode, LayerEntry[]>
    for (const scene of scenes) {
      for (const product of scene.products ?? []) {
        if ((LAYER_INDEX_CODES as readonly string[]).includes(product.index_code)) {
          byIndex[product.index_code as LayerIndexCode].push({ scene, product })
        }
      }
    }
    for (const code of LAYER_INDEX_CODES) {
      byIndex[code].sort(
        (a, b) => (b.scene.acquired_at ?? '').localeCompare(a.scene.acquired_at ?? ''),
      )
    }
    return byIndex
  }, [scenes])

  // Reset the explicit scene pick when the field or index changes; a null
  // sceneId means "latest acquisition for the chosen index".
  const setIndex = useCallback((code: LayerIndexCode) => {
    setIndexRaw(code)
    setSceneId(null)
  }, [])

  const selectedEntry = useMemo<LayerEntry | null>(() => {
    const entries = entriesByIndex[index]
    if (entries.length === 0) return null
    if (sceneId) {
      return entries.find((entry) => entry.scene.scene_id === sceneId) ?? entries[0]
    }
    return entries[0]
  }, [entriesByIndex, index, sceneId])

  const previewAssetId = selectedEntry?.product.preview_asset_id ?? null

  // Derived preview state for the CURRENTLY selected asset (never stale).
  const preview = useMemo(() => {
    if (!previewAssetId) return { url: null as string | null, loading: false, error: false }
    if (previewState.assetId === previewAssetId) {
      return { url: previewState.url, loading: false, error: previewState.error }
    }
    return { url: null as string | null, loading: true, error: false }
  }, [previewAssetId, previewState])

  // Fetch the preview PNG → object URL whenever the selected product changes.
  // setState only fires from the async callbacks (never synchronously here).
  useEffect(() => {
    if (!fieldId || !previewAssetId) return
    let alive = true
    fetchSatelliteAssetBlob(fieldId, previewAssetId)
      .then((blob) => {
        if (!alive) return
        setPreviewState({ assetId: previewAssetId, url: URL.createObjectURL(blob), error: false })
      })
      .catch(() => {
        if (!alive) return
        setPreviewState({ assetId: previewAssetId, url: null, error: true })
      })
    return () => {
      alive = false
    }
  }, [fieldId, previewAssetId])

  // Revoke each object URL when it is replaced by another one (or on unmount).
  // This cleanup runs after FarmMap's own cleanup removed the map, so a URL is
  // never revoked while a live map still references it.
  useEffect(() => {
    const url = previewState.url
    if (!url) return
    return () => {
      URL.revokeObjectURL(url)
    }
  }, [previewState.url])

  const overlay = useMemo<SatelliteMapOverlay | null>(() => {
    const product = selectedEntry?.product
    if (!preview.url || !product?.bbox_wgs84 || !visible) return null
    return {
      id: product.asset_id,
      imageUrl: preview.url,
      bbox: product.bbox_wgs84,
      opacity: opacityPct / 100,
      visible: true,
    }
  }, [preview, selectedEntry, opacityPct, visible])

  return {
    query,
    entriesByIndex,
    index,
    setIndex,
    sceneId,
    setSceneId,
    opacityPct,
    setOpacityPct,
    visible,
    setVisible,
    selectedEntry,
    preview,
    overlay,
  }
}

function legendLabelKey(index: LayerIndexCode, end: 'low' | 'high'): string {
  if (index === 'ndvi') return end === 'low' ? 'legendLowNdvi' : 'legendHighNdvi'
  return end === 'low' ? 'legendLow' : 'legendHigh'
}

function formatIndexValue(value: number): string {
  return `${value > 0 ? '+' : ''}${value}`
}

/** P05 "Satellite layers" card — index/date pickers, opacity, legend, provenance. */
function SatelliteLayersCard({ layers }: { layers: SatelliteLayersState }) {
  const t = useTranslations('satellite')
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const setActiveSub = useCropTwistUi((s) => s.setActiveSub)

  const { query, entriesByIndex, index, setIndex, sceneId, setSceneId } = layers
  const entries = entriesByIndex[index]
  const selectedEntry = layers.selectedEntry
  const product = selectedEntry?.product ?? null
  const scene = selectedEntry?.scene ?? null

  const hasAnyProduct = LAYER_INDEX_CODES.some((code) => entriesByIndex[code].length > 0)
  const unavailableCodes = LAYER_INDEX_CODES.filter(
    (code) => entriesByIndex[code].length === 0,
  )

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('layersTitle')}
        </CardTitle>
        <CardDescription className="text-sm text-stone-500">{t('layersDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {query.isLoading && <SectionSkeleton lines={4} />}
        {query.isError && (
          <ErrorState message={t('layersLoadError')} onRetry={() => query.refetch()} />
        )}
        {query.data && !hasAnyProduct && (
          <div className="flex flex-col items-start gap-2 rounded-md border border-dashed border-stone-300 bg-stone-50/60 p-4">
            <p className="text-sm font-medium text-stone-700">{t('noProductsTitle')}</p>
            <p className="text-xs leading-relaxed text-stone-500">{t('noProductsDesc')}</p>
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
        )}

        {query.data && hasAnyProduct && (
          <>
            {/* Index + date selectors */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-stone-600" htmlFor="sat-layer-index">
                  {t('index')}
                </label>
                <Select value={index} onValueChange={(value) => setIndex(value as LayerIndexCode)}>
                  <SelectTrigger id="sat-layer-index" className="h-9 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LAYER_INDEX_CODES.map((code) => {
                      const available = entriesByIndex[code].length > 0
                      return (
                        <SelectItem key={code} value={code} disabled={!available}>
                          {code.toUpperCase()}
                          {!available && (
                            <span className="ms-1 text-[10px] text-stone-400">
                              {t('notAvailableHint')}
                            </span>
                          )}
                        </SelectItem>
                      )
                    })}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-stone-500">{t(`indexDesc${index.toUpperCase()}`)}</p>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-stone-600" htmlFor="sat-layer-date">
                  {t('sceneDateLabel')}
                </label>
                <Select
                  value={sceneId ?? entries[0]?.scene.scene_id ?? ''}
                  onValueChange={(value) => setSceneId(value)}
                >
                  <SelectTrigger id="sat-layer-date" className="h-9 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {entries.map((entry) => (
                      <SelectItem key={entry.scene.scene_id} value={entry.scene.scene_id}>
                        {entry.scene.acquired_at?.slice(0, 10) ?? '—'}
                        <span className="ms-1 text-[10px] text-stone-400">
                          {entry.scene.scene_id}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {unavailableCodes.length > 0 && (
              <p className="text-[11px] text-amber-800">
                {t('unavailableHint', { codes: unavailableCodes.map((c) => c.toUpperCase()).join(', ') })}
              </p>
            )}

            {/* Opacity + visibility */}
            <div className="flex flex-wrap items-center gap-3">
              <label
                className="flex min-w-[180px] flex-1 items-center gap-2 text-xs font-medium text-stone-600"
                htmlFor="sat-layer-opacity"
              >
                <span className="shrink-0">{t('opacity')}</span>
                <Slider
                  id="sat-layer-opacity"
                  min={0}
                  max={100}
                  step={5}
                  value={[layers.opacityPct]}
                  onValueChange={(values) => layers.setOpacityPct(values[0] ?? 70)}
                  className="flex-1"
                  aria-valuetext={`${layers.opacityPct}%`}
                />
                <span className="w-10 shrink-0 text-end tabular-nums text-stone-500">
                  {layers.opacityPct}%
                </span>
              </label>
              <Button
                type="button"
                variant={layers.visible ? 'default' : 'outline'}
                size="sm"
                className="h-9"
                onClick={() => layers.setVisible(!layers.visible)}
                aria-pressed={layers.visible}
              >
                {layers.visible ? (
                  <Eye className="h-4 w-4" aria-hidden />
                ) : (
                  <EyeOff className="h-4 w-4" aria-hidden />
                )}
                <span className="ms-1">{layers.visible ? t('hideLayer') : t('showLayer')}</span>
              </Button>
            </div>

            {/* Legend — documented colormap over the documented range */}
            <div className="rounded-md border border-stone-200 bg-stone-50/60 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-stone-500">
                {t('legendTitle')}
              </p>
              <div dir="ltr" className="mt-2 space-y-1">
                <div
                  className="h-3 w-full rounded-full border border-stone-200"
                  style={{ background: COLORMAP_GRADIENT }}
                  aria-hidden
                />
                <div className="flex items-center justify-between text-[10px] text-stone-600">
                  <span>
                    <span className="font-semibold tabular-nums">
                      {formatIndexValue(DOCUMENTED_RANGES[index][0])}
                    </span>{' '}
                    {t(legendLabelKey(index, 'low'))}
                  </span>
                  <span>
                    {t(legendLabelKey(index, 'high'))}{' '}
                    <span className="font-semibold tabular-nums">
                      {formatIndexValue(DOCUMENTED_RANGES[index][1])}
                    </span>
                  </span>
                </div>
              </div>
              <p className="mt-1.5 text-[10px] text-stone-500">{t('legendMasked')}</p>
            </div>

            {/* Layer info / provenance line */}
            {product && scene ? (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-stone-600">
                <span className="font-medium text-stone-800">
                  {scene.product_code} · {scene.provider_code}
                </span>
                {scene.is_synthetic && <SyntheticBadge />}
                <span>
                  {t('infoAcquired')}: {scene.acquired_at?.slice(0, 10) ?? '—'}
                </span>
                <span>
                  {t('infoResolution')}: {product.spatial_resolution_m} m
                </span>
                <span>
                  {t('infoVersion')}: {product.processing_version}
                </span>
                <span>
                  {t('infoValidPixels')}: {Math.round(product.valid_pixel_fraction * 100)}%
                </span>
                <span>
                  {t('infoCloud')}: {scene.cloud_cover_pct != null ? `${Math.round(scene.cloud_cover_pct)}%` : '—'}
                </span>
              </div>
            ) : null}

            {/* Preview state honesty */}
            {layers.preview.loading && <p className="text-[11px] text-stone-500">{t('previewLoading')}</p>}
            {layers.preview.error && (
              <p className="text-[11px] text-amber-800" role="status">
                {t('previewError')}
              </p>
            )}
            {product && !layers.preview.loading && !layers.preview.error && !product.preview_asset_id && (
              <p className="text-[11px] text-stone-500">{t('noPreviewHint')}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function MapSatellitePane() {
  const tMap = useTranslations('map')
  const tNav = useTranslations('nav')
  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const fieldsQuery = useFields(selectedFarmId, Boolean(selectedFarmId))
  const layers = useSatelliteLayers(selectedField?.id ?? null)

  const handleFieldSelect = useCallback(
    (field: { id: string; name: string; farm_id: string }) => {
      setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
    },
    [setSelectedField],
  )

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px] [&>*]:min-w-0">
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{tMap('farmMapTitle')}</CardTitle>
          <CardDescription>
            {tMap('farmMapDesc')} {tMap('clickHint')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FarmMap
            fields={fieldsQuery.data?.items ?? []}
            selectedFieldId={selectedField?.id ?? null}
            onFieldSelect={handleFieldSelect}
            satelliteOverlay={layers.overlay}
          />
        </CardContent>
      </Card>
      <div className="min-w-0 space-y-4" aria-label={tNav('satellite')}>
        <SatelliteIntelligence />
        <SatelliteLayersCard layers={layers} />
      </div>
    </div>
  )
}

'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Marker,
  type ErrorEvent as MapLibreErrorEvent,
  type GeoJSONSource,
  type MapGeoJSONFeature,
  type MapMouseEvent,
} from 'maplibre-gl'
import { useTranslations } from 'next-intl'
import { createOfflineMap, disposeMap, type OfflineMap } from '@/lib/map/factory'
import { formatArea } from '@/lib/format'
import type { Field, GeoJSONGeometry } from '@/lib/types'

/**
 * P1/P07 farm map: shows EVERY field of a farm in one offline MapLibre map —
 * per-field categorical colors, name/area labels, a legend, hover highlight,
 * click-to-select and P07's multi-layer satellite raster overlays.
 *
 * P07 rewrite notes (the map instance is now STABLE):
 *   - The MapLibre bootstrap comes from the shared factory (lib/map/factory).
 *   - Overlays are applied INCREMENTALLY: addSource/addLayer once, opacity via
 *     setPaintProperty, visibility via setLayoutProperty, z-order via
 *     moveLayer, removal on cleanup. The map is NEVER recreated when overlays
 *     change (opacity drags no longer tear the canvas down).
 *   - Tile overlays use the server-rendered XYZ raster source (cookies ride
 *     along same-origin); bbox image overlays keep the MapLibre image source
 *     path for previews.
 *   - Z-order: overlays sit ABOVE the field fill and BELOW the field outline
 *     (inserted with beforeId 'farm-field-outline'), so boundaries stay
 *     legible through the rendered index.
 */

/** Categorical palette (emerald-forward, colorblind-safe-ish spread). */
const PALETTE = [
  '#059669', // emerald-600
  '#0d9488', // teal-600
  '#65a30d', // lime-600
  '#ca8a04', // yellow-600
  '#ea580c', // orange-600
  '#be123c', // rose-700
  '#7c3aed', // violet-600
  '#0369a1', // sky-700
  '#c026d3', // fuchsia-600
  '#4d7c0f', // lime-700
]

interface FieldFeatureProps {
  fieldId: string
  name: string
  area: number
  color: string
}

function isValidGeometry(geometry: GeoJSONGeometry | null | undefined): boolean {
  return (
    !!geometry &&
    (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') &&
    Array.isArray(geometry.coordinates) &&
    geometry.coordinates.length > 0
  )
}

/** Bbox of a Polygon/MultiPolygon position list, [minx, miny, maxx, maxy]. */
function geometryBbox(geometry: GeoJSONGeometry): [number, number, number, number] {
  let minx = Infinity
  let miny = Infinity
  let maxx = -Infinity
  let maxy = -Infinity
  const rings: unknown[] =
    geometry.type === 'Polygon'
      ? [geometry.coordinates]
      : (geometry.coordinates as unknown[])
  for (const poly of rings) {
    for (const ring of poly as number[][][]) {
      for (const [x, y] of ring) {
        if (x < minx) minx = x
        if (y < miny) miny = y
        if (x > maxx) maxx = x
        if (y > maxy) maxy = y
      }
    }
  }
  return [minx, miny, maxx, maxy]
}

const EMPTY_FEATURE_COLLECTION: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }

const BOUNDARY_FILL_LAYER = 'farm-field-fill'
const BOUNDARY_OUTLINE_LAYER = 'farm-field-outline'
const SELECTED_SOURCE = 'selected-field'
const SELECTED_OUTLINE_LAYER = 'selected-field-outline'
const OVERLAY_LAYER_PREFIX = 'croptwist-overlay-'

function overlayLayerId(overlayId: string): string {
  return `${OVERLAY_LAYER_PREFIX}${overlayId}`
}

/**
 * P07 satellite raster overlay. Exactly one of `tileUrl` (server-rendered
 * XYZ tiles, recommended) or `imageUrl` + `bbox` (blob preview PNG) must be
 * set for the overlay to render; overlays without a renderable payload are
 * reported through onOverlayError and skipped — nothing is faked.
 */
export interface FarmMapOverlay {
  /** Stable id used for the MapLibre source/layer (e.g. the layer id). */
  id: string
  /** XYZ template ({z}/{x}/{y} substituted by MapLibre, same-origin cookies). */
  tileUrl?: string
  /** Blob object URL of a preview PNG (owned + revoked by the parent). */
  imageUrl?: string
  /** [minLon, minLat, maxLon, maxLat] WGS84 footprint (image path or bounds). */
  bbox?: number[]
  /** 0..1 raster opacity. */
  opacity: number
  visible: boolean
  /** Higher renders on top among overlays (below the field outlines always). */
  zIndex: number
}

export interface FarmMapFitRequest {
  /** Field to fit; null fits the whole farm. */
  fieldId: string | null
  /** Monotonic counter — bump to request a fit even for the same field. */
  seq: number
}

/** Light graticule so the offline base reads as a map, not a void. */
function buildGraticule(bounds: [number, number, number, number]): GeoJSON.FeatureCollection {
  const [minx, miny, maxx, maxy] = bounds
  const padX = Math.max((maxx - minx) * 0.15, 0.02)
  const padY = Math.max((maxy - miny) * 0.15, 0.02)
  const x0 = minx - padX
  const x1 = maxx + padX
  const y0 = miny - padY
  const y1 = maxy + padY
  const step = Math.max((x1 - x0) / 12, (y1 - y0) / 8)
  const features: GeoJSON.Feature[] = []
  for (let x = Math.ceil(x0 / step) * step; x <= x1; x += step) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [[x, y0], [x, y1]] },
    })
  }
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [[x0, y], [x1, y]] },
    })
  }
  return { type: 'FeatureCollection', features }
}

/** What an overlay source was created with — used to detect payload changes. */
interface ManagedOverlay {
  sourceId: string
  tileUrl?: string
  imageUrl?: string
  bboxKey?: string
}

export function FarmMap({
  fields,
  selectedFieldId,
  onFieldSelect,
  onFieldClick,
  onMapClick,
  overlays = [],
  onOverlayError,
  fitRequest = null,
  className,
}: {
  fields: Field[]
  selectedFieldId?: string | null
  onFieldSelect?: (field: Field) => void
  /** Fires together with onFieldSelect on a boundary click (opens inspector). */
  onFieldClick?: (field: Field) => void
  /** Unfiltered map click (even outside boundaries). */
  onMapClick?: (lngLat: { lng: number; lat: number }) => void
  /** P07 multi-layer satellite raster overlays (applied incrementally). */
  overlays?: FarmMapOverlay[]
  /** Per-layer raster/tile errors, deduped; rendered honestly upstream. */
  onOverlayError?: (overlayId: string) => void
  /** Bump `seq` to fit the given field (or the whole farm when null). */
  fitRequest?: FarmMapFitRequest | null
  className?: string
}) {
  const tMap = useTranslations('map')
  const tCommon = useTranslations('common')
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<OfflineMap | null>(null)
  const baseAppliedRef = useRef(false)
  const managedOverlaysRef = useRef<Map<string, ManagedOverlay>>(new Map())
  const overlayErrorsRef = useRef<Set<string>>(new Set())
  const [mapEpoch, setMapEpoch] = useState(0)

  // Handlers live in a ref so identity changes never recreate the map.
  const handlersRef = useRef({ onFieldSelect, onFieldClick, onMapClick, onOverlayError })
  useEffect(() => {
    handlersRef.current = { onFieldSelect, onFieldClick, onMapClick, onOverlayError }
  })

  const drawable = useMemo(
    () => fields.filter((field) => isValidGeometry(field.boundary_geojson)),
    [fields],
  )

  const collection = useMemo<GeoJSON.FeatureCollection>(() => {
    return {
      type: 'FeatureCollection',
      features: drawable.map((field, index) => ({
        type: 'Feature',
        id: index,
        properties: {
          fieldId: field.id,
          name: field.name,
          area: field.area_ha ?? field.postgis_geodesic_area_ha ?? 0,
          color: PALETTE[index % PALETTE.length],
        } satisfies FieldFeatureProps,
        geometry: field.boundary_geojson as GeoJSON.Geometry,
      })),
    }
  }, [drawable])

  const flatBbox = useMemo<[number, number, number, number] | null>(() => {
    if (drawable.length === 0) return null
    let minx = Infinity
    let miny = Infinity
    let maxx = -Infinity
    let maxy = -Infinity
    for (const field of drawable) {
      const [bx0, by0, bx1, by1] = geometryBbox(field.boundary_geojson as GeoJSONGeometry)
      minx = Math.min(minx, bx0)
      miny = Math.min(miny, by0)
      maxx = Math.max(maxx, bx1)
      maxy = Math.max(maxy, by1)
    }
    return [minx, miny, maxx, maxy]
  }, [drawable])

  const overallBbox = useMemo<[[number, number], [number, number]] | null>(
    () => (flatBbox ? [[flatBbox[0], flatBbox[1]], [flatBbox[2], flatBbox[3]]] : null),
    [flatBbox],
  )

  // ------------------------------------------------------------- base map
  // Created ONCE per field-set/locale change. Overlays, selection and fit
  // requests never recreate it (P07 contract).
  useEffect(() => {
    const container = containerRef.current
    if (!container || drawable.length === 0 || !flatBbox || !overallBbox) return

    baseAppliedRef.current = false
    managedOverlaysRef.current = new Map()
    overlayErrorsRef.current = new Set()

    const map = createOfflineMap(container, {
      style: 'light',
      bounds: overallBbox,
      fitBoundsOptions: { padding: 42, maxZoom: 15 },
    })
    mapRef.current = map
    setMapEpoch((epoch) => epoch + 1)

    const applyBase = () => {
      try {
        map.addSource('graticule', { type: 'geojson', data: buildGraticule(flatBbox) })
        map.addLayer({
          id: 'graticule-lines',
          type: 'line',
          source: 'graticule',
          paint: { 'line-color': '#e7e5e4', 'line-width': 1 },
        })

        map.addSource('farm-fields', { type: 'geojson', data: collection })

        map.addLayer({
          id: BOUNDARY_FILL_LAYER,
          type: 'fill',
          source: 'farm-fields',
          paint: {
            'fill-color': ['get', 'color'],
            'fill-opacity': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              0.52,
              0.32,
            ],
          },
        })

        map.addLayer({
          id: BOUNDARY_OUTLINE_LAYER,
          type: 'line',
          source: 'farm-fields',
          paint: {
            'line-color': ['get', 'color'],
            'line-width': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              3.5,
              2,
            ],
          },
        })

        // Name/area labels as DOM markers at each field's bbox center.
        for (const feature of collection.features) {
          const geometry = feature.geometry as GeoJSONGeometry
          const [minx, miny, maxx, maxy] = geometryBbox(geometry)
          const el = document.createElement('div')
          el.className =
            'pointer-events-none -translate-y-1/2 -translate-x-1/2 rounded-md border border-stone-300 bg-white/92 px-1.5 py-0.5 text-[10px] font-medium leading-tight text-stone-700 shadow-sm'
          el.textContent = `${feature.properties?.name ?? ''} · ${formatArea(Number(feature.properties?.area ?? 0))} ${tCommon('ha')}`
          new Marker({ element: el, anchor: 'center' })
            .setLngLat([(minx + maxx) / 2, (miny + maxy) / 2])
            .addTo(map)
        }
      } catch (err) {
        // Base layers are essential but a failure must not wedge the page.
        console.warn('farm map base layers failed', err)
      } finally {
        baseAppliedRef.current = true
      }
    }

    if (map.loaded()) {
      applyBase()
    } else {
      map.once('load', applyBase)
    }

    // Hover highlight + click-to-select (delegated events; layers exist by
    // the time the user can interact).
    let hoveredId: number | string | null = null
    const onMove = (event: { features?: MapGeoJSONFeature[] }) => {
      map.getCanvas().style.cursor = event.features?.length ? 'pointer' : ''
      const next = event.features?.[0]?.id ?? null
      if (next === hoveredId) return
      if (hoveredId !== null) {
        map.setFeatureState({ source: 'farm-fields', id: hoveredId }, { hover: false })
      }
      hoveredId = next
      if (hoveredId !== null) {
        map.setFeatureState({ source: 'farm-fields', id: hoveredId }, { hover: true })
      }
    }
    const onLeave = () => {
      map.getCanvas().style.cursor = ''
      if (hoveredId !== null) {
        map.setFeatureState({ source: 'farm-fields', id: hoveredId }, { hover: false })
      }
      hoveredId = null
    }
    const onBoundaryClick = (event: { features?: MapGeoJSONFeature[] }) => {
      const fieldId = event.features?.[0]?.properties?.fieldId
      if (!fieldId) return
      const field = drawable.find((entry) => entry.id === fieldId)
      if (!field) return
      handlersRef.current.onFieldSelect?.(field)
      handlersRef.current.onFieldClick?.(field)
    }
    const onPlainClick = (event: MapMouseEvent) => {
      handlersRef.current.onMapClick?.({ lng: event.lngLat.lng, lat: event.lngLat.lat })
    }
    const onMapError = (
      event: MapLibreErrorEvent | { sourceId?: string; layerId?: string },
    ) => {
      const sourceId = (event as { sourceId?: string }).sourceId
      if (!sourceId || !sourceId.startsWith(OVERLAY_LAYER_PREFIX)) return
      const overlayId = sourceId.slice(OVERLAY_LAYER_PREFIX.length)
      if (overlayErrorsRef.current.has(overlayId)) return
      overlayErrorsRef.current.add(overlayId)
      handlersRef.current.onOverlayError?.(overlayId)
    }

    map.on('mousemove', BOUNDARY_FILL_LAYER, onMove)
    map.on('mouseleave', BOUNDARY_FILL_LAYER, onLeave)
    map.on('click', BOUNDARY_FILL_LAYER, onBoundaryClick)
    map.on('click', onPlainClick)
    map.on('error', onMapError as never)

    return () => {
      disposeMap(map)
      if (mapRef.current === map) mapRef.current = null
    }
    // Recreate ONLY when the field set or labels change — never on overlay/
    // selection/callback changes (P07 incremental contract).
  }, [collection, drawable, flatBbox, overallBbox, tCommon])

  // ---------------------------------------------------------- selection
  // Incremental: one source, setData + layer add/remove. No map rebuild.
  useEffect(() => {
    const map = mapRef.current
    if (!map || mapEpoch === 0) return
    const applySelection = () => {
      try {
        if (!map.getSource(SELECTED_SOURCE)) {
          map.addSource(SELECTED_SOURCE, { type: 'geojson', data: EMPTY_FEATURE_COLLECTION })
        }
        const source = map.getSource(SELECTED_SOURCE) as GeoJSONSource | undefined
        const features = selectedFieldId
          ? collection.features.filter((feature) => feature.properties?.fieldId === selectedFieldId)
          : []
        source?.setData(features.length > 0 ? { type: 'FeatureCollection', features } : EMPTY_FEATURE_COLLECTION)
        if (selectedFieldId && features.length > 0) {
          if (!map.getLayer(SELECTED_OUTLINE_LAYER)) {
            map.addLayer({
              id: SELECTED_OUTLINE_LAYER,
              type: 'line',
              source: SELECTED_SOURCE,
              paint: { 'line-color': '#1c1917', 'line-width': 3.5 },
            })
          }
        } else if (map.getLayer(SELECTED_OUTLINE_LAYER)) {
          map.removeLayer(SELECTED_OUTLINE_LAYER)
        }
      } catch {
        // selection overlay is cosmetic — ignore failures
      }
    }
    if (baseAppliedRef.current) {
      applySelection()
    } else {
      map.once('load', applySelection)
    }
  }, [selectedFieldId, collection, mapEpoch])

  // ------------------------------------------------------------ overlays
  // Incremental sync: add missing sources/layers, update paint/layout for
  // existing ones, re-create a source only when its payload changes, remove
  // stale ones, and keep the z-order (overlays ascending below the outline).
  useEffect(() => {
    const map = mapRef.current
    if (!map || mapEpoch === 0) return
    const sync = () => {
      if (!baseAppliedRef.current) return
      try {
        const wanted = new Set(overlays.map((overlay) => overlayLayerId(overlay.id)))

        // 1. Remove overlays that disappeared from the prop list.
        for (const [layerId, managed] of Array.from(managedOverlaysRef.current.entries())) {
          if (wanted.has(layerId)) continue
          if (map.getLayer(layerId)) map.removeLayer(layerId)
          if (map.getSource(managed.sourceId)) map.removeSource(managed.sourceId)
          managedOverlaysRef.current.delete(layerId)
          overlayErrorsRef.current.delete(layerId.slice(OVERLAY_LAYER_PREFIX.length))
        }

        // 2. Add/update every overlay.
        for (const overlay of overlays) {
          const layerId = overlayLayerId(overlay.id)
          const existing = managedOverlaysRef.current.get(layerId)
          const bboxKey = overlay.bbox ? overlay.bbox.join(',') : undefined
          const payloadChanged =
            !!existing &&
            (existing.tileUrl !== overlay.tileUrl ||
              existing.imageUrl !== overlay.imageUrl ||
              existing.bboxKey !== bboxKey)

          if (payloadChanged && existing) {
            if (map.getLayer(layerId)) map.removeLayer(layerId)
            if (map.getSource(existing.sourceId)) map.removeSource(existing.sourceId)
            managedOverlaysRef.current.delete(layerId)
            overlayErrorsRef.current.delete(overlay.id)
          }

          const current = managedOverlaysRef.current.get(layerId)
          if (!current) {
            if (overlay.tileUrl) {
              const sourceId = `${layerId}-src`
              map.addSource(sourceId, {
                type: 'raster',
                tiles: [overlay.tileUrl],
                tileSize: 256,
                ...(overlay.bbox && overlay.bbox.length === 4
                  ? {
                      bounds: [
                        overlay.bbox[0],
                        overlay.bbox[1],
                        overlay.bbox[2],
                        overlay.bbox[3],
                      ] as [number, number, number, number],
                    }
                  : {}),
              })
              map.addLayer(
                {
                  id: layerId,
                  type: 'raster',
                  source: sourceId,
                  paint: { 'raster-opacity': overlay.opacity, 'raster-fade-duration': 0 },
                  layout: { visibility: overlay.visible ? 'visible' : 'none' },
                },
                BOUNDARY_OUTLINE_LAYER,
              )
              managedOverlaysRef.current.set(layerId, {
                sourceId,
                tileUrl: overlay.tileUrl,
                bboxKey,
              })
            } else if (overlay.imageUrl && overlay.bbox && overlay.bbox.length === 4) {
              const sourceId = `${layerId}-src`
              const [minLon, minLat, maxLon, maxLat] = overlay.bbox
              map.addSource(sourceId, {
                type: 'image',
                url: overlay.imageUrl,
                coordinates: [
                  [minLon, maxLat],
                  [maxLon, maxLat],
                  [maxLon, minLat],
                  [minLon, minLat],
                ],
              })
              map.addLayer(
                {
                  id: layerId,
                  type: 'raster',
                  source: sourceId,
                  paint: { 'raster-opacity': overlay.opacity, 'raster-fade-duration': 0 },
                  layout: { visibility: overlay.visible ? 'visible' : 'none' },
                },
                BOUNDARY_OUTLINE_LAYER,
              )
              managedOverlaysRef.current.set(layerId, {
                sourceId,
                imageUrl: overlay.imageUrl,
                bboxKey,
              })
            } else {
              // No renderable payload — honest skip; the parent may surface it.
              if (!overlayErrorsRef.current.has(overlay.id)) {
                overlayErrorsRef.current.add(overlay.id)
                handlersRef.current.onOverlayError?.(overlay.id)
              }
            }
          } else {
            if (map.getLayer(layerId)) {
              map.setPaintProperty(layerId, 'raster-opacity', overlay.opacity)
              map.setLayoutProperty(layerId, 'visibility', overlay.visible ? 'visible' : 'none')
            }
          }
        }

        // 3. Z-order: re-stack overlays (ascending zIndex → drawn bottom-up,
        // each immediately below the field outlines).
        const stackable = overlays
          .filter((overlay) => managedOverlaysRef.current.has(overlayLayerId(overlay.id)))
          .sort((a, b) => a.zIndex - b.zIndex)
        if (map.getLayer(BOUNDARY_OUTLINE_LAYER)) {
          for (const overlay of stackable) {
            const layerId = overlayLayerId(overlay.id)
            if (map.getLayer(layerId)) map.moveLayer(layerId, BOUNDARY_OUTLINE_LAYER)
          }
        }
      } catch (err) {
        // The overlay pass is decorative — never take down the base map.
        console.warn('overlay sync skipped', err)
      }
    }
    if (baseAppliedRef.current) {
      sync()
    } else {
      // applyBase is registered before this effect's once('load') on the same
      // epoch, so by the time this fires the base layers exist.
      map.once('load', sync)
    }
  }, [overlays, mapEpoch])

  // -------------------------------------------------------------- fit
  useEffect(() => {
    const map = mapRef.current
    if (!map || mapEpoch === 0 || !fitRequest) return
    const applyFit = () => {
      try {
        if (fitRequest.fieldId) {
          const field = drawable.find((entry) => entry.id === fitRequest.fieldId)
          if (field && isValidGeometry(field.boundary_geojson)) {
            const [minx, miny, maxx, maxy] = geometryBbox(field.boundary_geojson as GeoJSONGeometry)
            map.fitBounds(
              [
                [minx, miny],
                [maxx, maxy],
              ],
              { padding: 48, maxZoom: 16, duration: 500 },
            )
            return
          }
        }
        if (flatBbox) {
          map.fitBounds(
            [
              [flatBbox[0], flatBbox[1]],
              [flatBbox[2], flatBbox[3]],
            ],
            { padding: 42, maxZoom: 15, duration: 500 },
          )
        }
      } catch {
        // fit is cosmetic — ignore failures
      }
    }
    if (baseAppliedRef.current) {
      applyFit()
    } else {
      map.once('load', applyFit)
    }
  }, [fitRequest, drawable, flatBbox, mapEpoch])

  if (drawable.length === 0) {
    return (
      <div className="flex h-[280px] w-full items-center justify-center rounded-lg border border-dashed border-stone-300 bg-stone-50 text-sm text-stone-500">
        {tMap('noFields')}
      </div>
    )
  }

  return (
    <div className={`relative ${className ?? ''}`}>
      {/* The map canvas itself stays LTR in Arabic — physical coordinates. */}
      <div
        ref={containerRef}
        className="croptwist-map h-[280px] w-full overflow-hidden rounded-lg border border-stone-300 md:h-[340px]"
        role="img"
        aria-label={tMap('mapAria', { count: drawable.length })}
      />
      <div
        className="absolute bottom-3 end-3 max-h-[70%] max-w-[45%] overflow-y-auto rounded-lg border border-stone-200 bg-white/95 p-2 shadow-md scrollbar-thin"
        aria-label={tMap('legend')}
      >
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-stone-400">
          {tMap('legend')}
        </p>
        <ul className="space-y-1">
          {drawable.map((field, index) => (
            <li key={field.id} className="flex items-center gap-1.5 text-[11px] text-stone-700">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: PALETTE[index % PALETTE.length] }}
                aria-hidden
              />
              <span className="max-w-[160px] truncate">{field.name}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default FarmMap

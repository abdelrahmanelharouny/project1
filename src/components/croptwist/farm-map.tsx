'use client'

import { useEffect, useMemo, useRef } from 'react'
import {
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type GeoJSONSource,
  type LngLatBoundsLike,
  type MapGeoJSONFeature,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useTranslations } from 'next-intl'
import { formatArea } from '@/lib/format'
import type { Field, GeoJSONGeometry } from '@/lib/types'

/**
 * P1 farm map: shows EVERY field of a farm in one offline MapLibre map —
 * per-field categorical colors, name/area labels, a legend, hover highlight
 * and click-to-select. Still fully offline (inline style, worker served from
 * /public), but now reads as an actual farm map rather than a dark
 * single-boundary preview.
 */
let workerConfigured = false
function ensureWorkerConfigured() {
  if (!workerConfigured) {
    setWorkerUrl('/maplibre-gl-worker.mjs')
    workerConfigured = true
  }
}

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

const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#f5f5f4' } }],
}

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

export function FarmMap({
  fields,
  selectedFieldId,
  onFieldSelect,
  className,
}: {
  fields: Field[]
  selectedFieldId?: string | null
  onFieldSelect?: (field: Field) => void
  className?: string
}) {
  const tMap = useTranslations('map')
  const tCommon = useTranslations('common')
  const containerRef = useRef<HTMLDivElement | null>(null)

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

  const overallBbox = useMemo<LngLatBoundsLike | null>(
    () => (flatBbox ? [[flatBbox[0], flatBbox[1]], [flatBbox[2], flatBbox[3]]] : null),
    [flatBbox],
  )

  useEffect(() => {
    const container = containerRef.current
    if (!container || drawable.length === 0 || !overallBbox) return

    ensureWorkerConfigured()

    const map = new MapLibreMap({
      container,
      style: OFFLINE_STYLE,
      bounds: overallBbox,
      fitBoundsOptions: { padding: 42, maxZoom: 15 },
      attributionControl: false,
    })
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')

    const selectedId = selectedFieldId ?? null

    const applyData = () => {
      const graticule = buildGraticule(flatBbox as [number, number, number, number])
      map.addSource('graticule', { type: 'geojson', data: graticule })
      map.addLayer({
        id: 'graticule-lines',
        type: 'line',
        source: 'graticule',
        paint: { 'line-color': '#e7e5e4', 'line-width': 1 },
      })

      map.addSource('farm-fields', { type: 'geojson', data: collection })
      if (selectedId) {
        try {
          map.addSource('selected-field', {
            type: 'geojson',
            data: {
              ...collection,
              features: collection.features.filter(
                (feature) => feature.properties?.fieldId === selectedId,
              ),
            },
          })
        } catch {
          // selection overlay is cosmetic — ignore failures
        }
      }

      map.addLayer({
        id: 'farm-field-fill',
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
        id: 'farm-field-outline',
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
      if (selectedId) {
        map.addLayer({
          id: 'selected-field-outline',
          type: 'line',
          source: 'selected-field',
          paint: { 'line-color': '#1c1917', 'line-width': 3.5 },
        })
      }

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
    }

    if (map.loaded()) {
      applyData()
    } else {
      map.once('load', applyData)
    }

    // Hover highlight + click-to-select.
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
    const onClick = (event: { features?: MapGeoJSONFeature[] }) => {
      const fieldId = event.features?.[0]?.properties?.fieldId
      if (!fieldId || !onFieldSelect) return
      const field = drawable.find((entry) => entry.id === fieldId)
      if (field) onFieldSelect(field)
    }

    map.on('mousemove', 'farm-field-fill', onMove)
    map.on('mouseleave', 'farm-field-fill', onLeave)
    map.on('click', 'farm-field-fill', onClick)

    return () => {
      map.remove()
    }
    // Rebuild only when the field set or the explicit selection changes.
  }, [collection, drawable, flatBbox, overallBbox, selectedFieldId, onFieldSelect, tCommon])

  if (drawable.length === 0) {
    return (
      <div className="flex h-[280px] w-full items-center justify-center rounded-lg border border-dashed border-stone-300 bg-stone-50 text-sm text-stone-500">
        {tMap('noFields')}
      </div>
    )
  }

  return (
    <div className={`relative ${className ?? ''}`}>
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

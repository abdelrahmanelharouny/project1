'use client'

import { useEffect, useRef } from 'react'
import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type GeoJSONSource,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { FieldMapResponse } from '@/lib/types'

/**
 * Fully offline MapLibre map: the style is an inline object with a plain dark
 * background — no external tile servers, works in the sandbox without network.
 * The field boundary is drawn from the GeoJSON payload of /fields/{id}/map.
 *
 * The MapLibre worker is served from /public so webpack/Turbopack never has to
 * resolve the worker URL from the bundled ESM graph (dev-mode bundlers often
 * break it — setWorkerUrl is the officially supported escape hatch).
 */
let workerConfigured = false
function ensureWorkerConfigured() {
  if (!workerConfigured) {
    setWorkerUrl('/maplibre-gl-worker.mjs')
    workerConfigured = true
  }
}
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#1c1917' } }],
}

const BOUNDARY_FILL = '#059669' // emerald-600
const BOUNDARY_LINE = '#6ee7b7' // emerald-300

export function FieldMap({ mapData, className }: { mapData: FieldMapResponse; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    ensureWorkerConfigured()

    const [minx, miny, maxx, maxy] = mapData.bbox
    const map = new MapLibreMap({
      container,
      style: OFFLINE_STYLE,
      center: [(minx + maxx) / 2, (miny + maxy) / 2],
      zoom: 10,
      attributionControl: false,
    })
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')

    const applyBoundary = () => {
      const source = map.getSource('field-boundary') as GeoJSONSource | undefined
      if (!source) {
        map.addSource('field-boundary', { type: 'geojson', data: mapData.boundary_geojson })
        map.addLayer({
          id: 'field-fill',
          type: 'fill',
          source: 'field-boundary',
          paint: { 'fill-color': BOUNDARY_FILL, 'fill-opacity': 0.3 },
        })
        map.addLayer({
          id: 'field-outline',
          type: 'line',
          source: 'field-boundary',
          paint: { 'line-color': BOUNDARY_LINE, 'line-width': 2 },
        })
      } else {
        source.setData(mapData.boundary_geojson)
      }
      map.fitBounds(
        [
          [minx, miny],
          [maxx, maxy],
        ],
        { padding: 32, maxZoom: 16, duration: 500 },
      )
    }

    if (map.loaded()) {
      applyBoundary()
    } else {
      map.once('load', applyBoundary)
    }

    return () => {
      map.remove()
    }
    // Recreate the map only when a different field (or fresh boundary) arrives.
  }, [mapData])

  return (
    <div
      ref={containerRef}
      className={`croptwist-map h-[300px] w-full overflow-hidden rounded-lg border border-stone-700/40 md:h-[360px] ${className ?? ''}`}
      role="img"
      aria-label={`Offline map preview of field ${mapData.field.name}, fitted to its boundary`}
    />
  )
}

export default FieldMap

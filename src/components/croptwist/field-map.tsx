'use client'

import { useEffect, useRef } from 'react'
import { type GeoJSONSource } from 'maplibre-gl'
import { createOfflineMap, disposeMap, type OfflineMap } from '@/lib/map/factory'
import type { FieldMapResponse } from '@/lib/types'

/**
 * Fully offline single-field preview map. The MapLibre bootstrap (inline
 * style, worker URL, controls, attribution off) now comes from the shared
 * factory (lib/map/factory) — behavior identical to the previous inline copy,
 * including the dark stone-900 canvas and the boundary add-or-update path.
 */
const BOUNDARY_FILL = '#059669' // emerald-600
const BOUNDARY_LINE = '#6ee7b7' // emerald-300

export function FieldMap({ mapData, className }: { mapData: FieldMapResponse; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const [minx, miny, maxx, maxy] = mapData.bbox
    const map: OfflineMap = createOfflineMap(container, {
      style: 'dark',
      center: [(minx + maxx) / 2, (miny + maxy) / 2],
      zoom: 10,
    })

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
      disposeMap(map)
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

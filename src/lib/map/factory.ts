/**
 * P07 — shared MapLibre bootstrap factory.
 *
 * Extracts the inline offline-map setup that was duplicated in farm-map.tsx
 * (light theme) and field-map.tsx (dark theme). Both maps are FULLY OFFLINE:
 * the style is an inline object with a plain background — no external tile
 * servers — and the MapLibre worker is served from /public
 * (setWorkerUrl is the officially supported escape hatch for bundlers).
 *
 * Every caller MUST go through ensureMapWorker() exactly once per session
 * (module-level flag below) before constructing a map.
 */

import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type LngLatBoundsLike,
  type MapOptions,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

let workerConfigured = false

/** Configure the offline worker once per session (idempotent, SSR-safe). */
export function ensureMapWorker(): void {
  if (!workerConfigured) {
    setWorkerUrl('/maplibre-gl-worker.mjs')
    workerConfigured = true
  }
}

const LIGHT_BACKGROUND = '#f5f5f4' // stone-100 — farm map canvas
const DARK_BACKGROUND = '#1c1917' // stone-900 — single-field preview canvas

export interface OfflineMapOptions {
  /** 'light' (farm canvas, stone-100) or 'dark' (field preview, stone-900). */
  style?: 'light' | 'dark'
  /** Initial center [lng, lat] (used by field-map). */
  center?: [number, number]
  /** Initial zoom (used by field-map). */
  zoom?: number
  /** Initial bounds (used by farm-map; wins over center/zoom). */
  bounds?: LngLatBoundsLike
  /** Options forwarded to the initial fitBounds when `bounds` is set. */
  fitBoundsOptions?: MapOptions['fitBoundsOptions']
}

/** MapLibre map type produced by the factory. */
export type OfflineMap = MapLibreMap

function offlineStyle(theme: 'light' | 'dark'): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'bg',
        type: 'background',
        paint: { 'background-color': theme === 'dark' ? DARK_BACKGROUND : LIGHT_BACKGROUND },
      },
    ],
  }
}

/**
 * Create the offline map with the shared control layout (navigation without
 * compass at top-right, metric scale at bottom-left) and attribution off —
 * the base map carries no external data, so there is nothing to attribute.
 */
export function createOfflineMap(container: HTMLElement, options: OfflineMapOptions = {}): OfflineMap {
  ensureMapWorker()
  const theme = options.style ?? 'light'
  const init: MapOptions = {
    container,
    style: offlineStyle(theme),
    attributionControl: false,
  }
  if (options.bounds) {
    init.bounds = options.bounds
    init.fitBoundsOptions = options.fitBoundsOptions ?? { padding: 42, maxZoom: 15 }
  } else {
    if (options.center) init.center = options.center
    if (options.zoom !== undefined) init.zoom = options.zoom
  }
  const map = new MapLibreMap(init)
  map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
  map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
  return map
}

/**
 * Tear down a map instance safely. Repeated/late teardowns (React 19 strict
 * double-invocation, race with removal) must never throw.
 */
export function disposeMap(map: OfflineMap | null | undefined): void {
  if (!map) return
  try {
    map.remove()
  } catch {
    // already disposed — nothing to do
  }
}

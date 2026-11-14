/**
 * P07 API client — advanced map experience, spatial analytics and exports.
 *
 * Follows the established api.ts conventions: relative paths only, Next.js
 * owns the server-side API rewrite, and session cookies ride along
 * (HttpOnly, never readable by JS), one 401 refresh retry, honest error
 * surfacing through ApiError-like messages. Binary endpoints (CSV export)
 * stream to a Blob; tile URLs are returned as TEMPLATE STRINGS for MapLibre
 * (the raster source sends same-origin cookies itself).
 */

import type {
  P07AnomalyResponse,
  P07Comparison,
  P07Distribution,
  P07FarmOverview,
  P07GeoJSONExport,
  P07LayerCatalog,
  P07ProductValueSample,
  P07SpatialAnalytics,
  P07ZonePolygons,
} from './types-p07'

export class ApiP07Error extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiP07Error'
    this.status = status
  }
}

async function p07Request<T>(path: string, init?: RequestInit): Promise<T> {
  let response = await fetch(path, {
    ...init,
    headers: { ...(init?.headers ?? {}) },
    credentials: 'same-origin',
    cache: 'no-store',
  })
  if (response.status === 401) {
    const { refreshSession } = await import('./api')
    await refreshSession()
    response = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      cache: 'no-store',
    })
  }
  if (!response.ok) {
    let detail = `HTTP_${response.status}`
    try {
      const body = (await response.json()) as { error?: { message?: string } }
      detail = body?.error?.message || detail
    } catch {
      /* binary or empty body — keep the HTTP code */
    }
    throw new ApiP07Error(response.status, detail)
  }
  return (await response.json()) as T
}

// ------------------------------------------------------------ layer catalog
export function getFieldLayerCatalog(fieldId: string): Promise<P07LayerCatalog> {
  return p07Request<P07LayerCatalog>(`/api/v1/fields/${fieldId}/map/layers`)
}

// ----------------------------------------------------------- spatial analytics
export function getFieldSpatialAnalytics(
  fieldId: string,
  index: string,
): Promise<P07SpatialAnalytics> {
  return p07Request<P07SpatialAnalytics>(
    `/api/v1/fields/${fieldId}/satellite/spatial-analytics?index=${encodeURIComponent(index)}`,
  )
}

export function getFieldAnomalies(fieldId: string, index = 'ndvi'): Promise<P07AnomalyResponse> {
  return p07Request<P07AnomalyResponse>(
    `/api/v1/fields/${fieldId}/satellite/anomalies?index=${encodeURIComponent(index)}`,
  )
}

export function getFieldComparison(
  fieldId: string,
  params: { index?: string; targetFieldId?: string; acquiredAtA?: string; acquiredAtB?: string },
): Promise<P07Comparison> {
  const qs = new URLSearchParams()
  qs.set('index', params.index ?? 'ndvi')
  if (params.targetFieldId) qs.set('target_field_id', params.targetFieldId)
  if (params.acquiredAtA) qs.set('acquired_at_a', params.acquiredAtA)
  if (params.acquiredAtB) qs.set('acquired_at_b', params.acquiredAtB)
  return p07Request<P07Comparison>(`/api/v1/fields/${fieldId}/satellite/comparison?${qs.toString()}`)
}

export function getFarmSatelliteOverview(farmId: string, index = 'ndvi'): Promise<P07FarmOverview> {
  return p07Request<P07FarmOverview>(
    `/api/v1/farms/${farmId}/satellite/overview?index=${encodeURIComponent(index)}`,
  )
}

// ---------------------------------------------------------- product renderings
export function getProductZones(fieldId: string, assetId: string): Promise<P07ZonePolygons> {
  return p07Request<P07ZonePolygons>(
    `/api/v1/fields/${fieldId}/satellite/products/${assetId}/zones`,
  )
}

export function getProductValueSample(
  fieldId: string,
  assetId: string,
  lon: number,
  lat: number,
): Promise<P07ProductValueSample> {
  const query = new URLSearchParams({ lon: String(lon), lat: String(lat) })
  return p07Request<P07ProductValueSample>(
    `/api/v1/fields/${fieldId}/satellite/products/${assetId}/value?${query.toString()}`,
  )
}

export function getProductDistribution(
  fieldId: string,
  assetId: string,
  bins = 10,
): Promise<P07Distribution> {
  return p07Request<P07Distribution>(
    `/api/v1/fields/${fieldId}/satellite/products/${assetId}/distribution?bins=${bins}`,
  )
}

/**
 * XYZ tile URL template for MapLibre raster sources. MapLibre substitutes
 * {z}/{x}/{y} and sends the session cookies itself (same-origin). Tiles are
 * rendered server-side from
 * the stored COG — the browser never sees object-store keys or signed URLs.
 */
export function productTileUrlTemplate(
  fieldId: string,
  assetId: string,
): string {
  return `/api/v1/fields/${fieldId}/satellite/products/${assetId}/tiles/{z}/{x}/{y}.png`
}

// ------------------------------------------------------------------ exports
export async function exportFieldBoundaryGeoJSON(fieldId: string): Promise<Blob> {
  const response = await fetch(
    `/api/v1/fields/${fieldId}/boundary.geojson`,
    { credentials: 'same-origin', cache: 'no-store' },
  )
  if (!response.ok) throw new ApiP07Error(response.status, `HTTP_${response.status}`)
  return response.blob()
}

export async function exportFarmFieldsGeoJSON(farmId: string): Promise<Blob> {
  const response = await fetch(
    `/api/v1/farms/${farmId}/fields.geojson`,
    { credentials: 'same-origin', cache: 'no-store' },
  )
  if (!response.ok) throw new ApiP07Error(response.status, `HTTP_${response.status}`)
  return response.blob()
}

export async function exportSatelliteTimelineCSV(
  fieldId: string,
  index?: string,
): Promise<Blob> {
  const qs = new URLSearchParams()
  if (index) qs.set('index', index)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const response = await fetch(
    `/api/v1/fields/${fieldId}/satellite/timeline.csv${suffix}`,
    { credentials: 'same-origin', cache: 'no-store' },
  )
  if (!response.ok) throw new ApiP07Error(response.status, `HTTP_${response.status}`)
  return response.blob()
}

/** Save a Blob with a filename (shared by every export control). */
export function saveP07Blob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
}

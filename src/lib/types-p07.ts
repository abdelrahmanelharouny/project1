/**
 * P07 shared types — advanced map experience, spatial analytics, exports.
 *
 * Mirror of the backend contracts in
 * mini-services/fieldshift-api/app/geospatial/{layer_catalog,spatial_analytics,
 * rendering,exports}.py. These describe EXACTLY what the API returns; no
 * field is invented client-side and every honest-availability payload keeps
 * its `unavailable_reason`.
 */

export type P07IndexCode = 'ndvi' | 'evi' | 'ndmi' | 'ndwi' | 'bsi'

export interface P07LayerDates {
  date: string | null
  acquired_at: string | null
  scene_id: string
  processing_version: string
  valid_pixel_fraction: number | null
}

export interface P07LatestProduct {
  asset_id: string
  preview_asset_id: string | null
  scene_id: string
  acquired_at: string | null
  processing_version: string
  spatial_resolution_m: number | null
  crs: string | null
  bbox_wgs84: number[] | null
  valid_pixel_fraction: number | null
  zonal: P07Zonal | null
  zone_summary: P07ZoneSummary | null
  storage_backend: string
  checksum_sha256: string | null
  is_synthetic: boolean | null
}

export interface P07Zonal {
  index?: string
  mean?: number | null
  median?: number | null
  p5?: number | null
  p25?: number | null
  p75?: number | null
  p95?: number | null
  std?: number | null
  valid_pixels?: number
  masked_pixels?: number
  coverage_fraction?: number | null
  flags?: string[]
  version?: string
}

export interface P07ZoneSummaryZone {
  zone: 'lowest_tercile' | 'middle_tercile' | 'highest_tercile'
  value_range: [number, number]
  pixel_share: number
  mean: number | null
}

export interface P07ZoneSummary {
  method: string
  description?: string
  zones: P07ZoneSummaryZone[]
  valid_pixels: number
  version?: string
}

export interface P07VegetationLayer {
  id: string
  group: 'vegetation'
  code: P07IndexCode
  kind: 'raster'
  label: string
  index_formula: string | null
  available: boolean
  product_count: number
  dates_available: P07LayerDates[]
  render?: { type: 'xyz_tiles'; tile_size: number }
  latest?: P07LatestProduct
  colormap?: string
  nodata_style?: string
  source_attribution?: string
  provider_code?: string
  is_synthetic?: boolean | null
  unavailable_reason?: string
}

export interface P07EnvironmentLayer {
  id: string
  group: 'environment'
  code: string
  kind: 'field_series' | 'raster'
  label: string
  unit?: string
  available: boolean
  observation_count?: number
  latest_observed_at?: string | null
  render?: { type: string } | null
  unavailable_reason?: string
}

export interface P07InfrastructureLayer {
  id: string
  group: 'infrastructure'
  code: string
  kind: 'vector'
  label: string
  available: boolean
  render?: { type: string } | null
  boundary_version?: number | null
  zone_note?: string
  unavailable_reason?: string
}

export interface P07LayerCatalog {
  catalog_version: string
  field_id: string
  layers: {
    vegetation: P07VegetationLayer[]
    environment: P07EnvironmentLayer[]
    infrastructure: P07InfrastructureLayer[]
  }
  notes: string[]
}

export interface P07HistogramBin {
  bin_start: number
  bin_end: number
  pixels: number
  share: number
}

export interface P07Distribution {
  index: string
  documented_range: [number, number]
  field_mask_pixels: number
  valid_pixels: number
  method: string
  version: string
  histogram: P07HistogramBin[]
  proportion_out_of_documented_range: number | null
  percentiles?: {
    p5: number
    p25: number
    median: number
    p75: number
    p95: number
    std: number
    mean: number
  }
  note?: string
  available?: false
  reason?: string
}

export interface P07ZoneFeature {
  type: 'Feature'
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon | null
  properties: {
    zone: string
    zone_kind: string
    pixel_count: number
    pixel_share: number
    mean: number | null
    value_range: [number, number] | null
    index: string
  }
}

export interface P07ZonePolygons {
  type: 'FeatureCollection'
  asset_id: string
  index: string
  zone_kind: string
  zone_note: string
  version: string
  crs: string
  features: P07ZoneFeature[]
  zones_without_geometry: { zone: string; reason: string }[]
  valid_pixels: number
  available?: false
  reason?: string
}

export interface P07ZoneHistoryEntry {
  acquired_at: string | null
  scene_id: string
  processing_version: string
  valid_pixel_fraction: number | null
  zones: P07ZoneSummaryZone[]
}

export interface P07SpatialAnalytics {
  version: string
  field_id: string
  index: string
  index_formula: string | null
  available: boolean
  unavailable_reason?: string
  latest_product?: P07LatestProduct
  variation?: {
    std: number | null
    p5: number | null
    p25: number | null
    p75: number | null
    p95: number | null
    spread_p95_p5: number | null
    valid_pixels: number | null
    coverage_fraction: number | null
    supports_subfield_claims: boolean
    flags: string[] | null
  }
  zone_polygons?: P07ZonePolygons
  distribution?: P07Distribution
  zone_history: P07ZoneHistoryEntry[]
  not_zones_note: string
}

export interface P07Anomaly {
  id: string
  type: string
  severity: 'info' | 'warning'
  index: string
  confidence: number
  reasons: string[]
  observed_at: string | null
  scene_id: string | null
  processing_version: string | null
  spatial_resolution_m: number | null
  valid_pixel_fraction: number | null
  measurements: Record<string, number | null>
  limitations: string[]
  not_a_diagnosis: true
}

export interface P07AnomalyResponse {
  version: string
  field_id: string
  index: string
  anomalies: P07Anomaly[]
  insufficient_evidence: string[]
  not_a_diagnosis: true
  requires_independent_evidence_for: string[]
  generated_from: string
  environmental_context?: Record<string, unknown>
}

export interface P07ComparisonSide {
  asset_id: string
  scene_id: string
  acquired_at: string | null
  processing_version: string
  spatial_resolution_m: number | null
  crs: string | null
  valid_pixel_fraction: number | null
  zonal: P07Zonal | null
  zone_summary: P07ZoneSummary | null
}

export interface P07Comparison {
  version: string
  index: string
  comparable: boolean
  incompatibilities: string[]
  side_a: P07ComparisonSide | null
  side_b: P07ComparisonSide | null
  unavailable_reason?: string
  compatibility?: {
    spatial_resolution_delta_m: number | null
    temporal_distance_days: number | null
    min_valid_pixel_fraction: number | null
    same_field: boolean
  }
  mean_delta?: number
  mean_delta_pct?: number | null
  zone_deltas?: {
    zone: string
    mean_a: number | null
    mean_b: number | null
    delta: number | null
  }[]
  measurement_notes: string[]
}

export interface P07FarmOverviewField {
  field_id: string
  field_name: string
  area_ha: number | null
  available: boolean
  acquired_at?: string | null
  mean?: number | null
  valid_pixel_fraction?: number | null
  processing_version?: string
  freshness_days?: number | null
  fresh?: boolean
  unavailable_reason?: string
}

export interface P07FarmOverview {
  version: string
  farm_id: string
  index: string
  fields: P07FarmOverviewField[]
  freshness_window_days: number
}

export interface P07GeoJSONExport {
  type: 'Feature' | 'FeatureCollection'
  properties?: Record<string, unknown>
  farm_id?: string
  field_count?: number
  crs: string
  export_version: string
  exported_at: string
  features?: GeoJSON.Feature[]
}

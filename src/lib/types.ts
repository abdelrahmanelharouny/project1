/**
 * FieldShift API contract types (frozen, verified against the FastAPI backend).
 * All endpoints live under /api/v1 and are reached through the gateway with
 * the `XTransformPort=3030` query parameter (see src/lib/api.ts).
 */

// ---------------------------------------------------------------------------
// Error envelope
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  field: string
  reason: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: ApiErrorDetail[]
    request_id: string
  }
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
  time: string
}

export interface HealthReadyResponse {
  status: string
  database: string
  server_version: string
  postgis_version: string
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface User {
  id: string
  email: string
  display_name: string
}

export interface OrganizationRef {
  id: string
  name: string
}

export interface MembershipRef {
  id: string
  role: string
  status: string
}

export interface AuthResponse {
  token: string
  token_type: string
  expires_at: string
  user: User
  organization: OrganizationRef
  organizations?: MembershipRef[]
}

export interface MeResponse {
  user: User
  organizations: MembershipRef[]
}

export interface SeedDemoResponse {
  token: string
  token_type: string
  expires_at: string
  demo_user: { email: string; password: string }
  note: string
  farm_id: string
  field_ids: string[]
  created: boolean
}

export interface LoginInput {
  email: string
  password: string
}

export interface RegisterInput {
  email: string
  password: string
  display_name: string
}

// ---------------------------------------------------------------------------
// GeoJSON geometry (only the shapes the API accepts/returns)
// ---------------------------------------------------------------------------

export interface GeoJSONPolygon {
  type: 'Polygon'
  coordinates: number[][][]
}

export interface GeoJSONMultiPolygon {
  type: 'MultiPolygon'
  coordinates: number[][][][]
}

export type GeoJSONGeometry = GeoJSONPolygon | GeoJSONMultiPolygon

// ---------------------------------------------------------------------------
// Farms
// ---------------------------------------------------------------------------

export type UnitSystem = 'metric' | 'imperial'

export interface Farm {
  id: string
  organization_id: string
  name: string
  country_code: string
  admin_region: string | null
  timezone: string
  currency_code: string
  unit_system: UnitSystem
  preferred_language: string
  field_count: number
  total_area_ha: number
  created_at: string
  updated_at: string
}

export interface FarmListResponse {
  items: Farm[]
  total: number
}

export interface FarmCreateInput {
  name: string
  country_code: string
  admin_region?: string
  timezone: string
  currency_code: string
  unit_system: UnitSystem
  preferred_language: string
}

export type FarmPatchInput = Partial<FarmCreateInput>

// ---------------------------------------------------------------------------
// Fields & boundary versions
// ---------------------------------------------------------------------------

export type FieldStatus = string
export type PassportOverallStatus = 'ready' | 'partial' | 'blocked'

export interface Field {
  id: string
  farm_id: string
  name: string
  area_ha: number
  boundary_geojson: GeoJSONGeometry
  boundary_version: number
  status: FieldStatus
  postgis_geodesic_area_ha: number | null
  observation_count: number
  data_passport_status: string
  created_at: string
  updated_at: string
}

export interface FieldListResponse {
  items: Field[]
  total: number
}

export interface FieldCreateInput {
  name: string
  geometry: GeoJSONGeometry
  change_reason?: string
}

/** Response of POST /fields (creation + boundary version responses share shape). */
export interface FieldCreateResponse {
  id: string
  farm_id: string
  name: string
  area_ha: number
  geometry_valid: boolean
  boundary_version: number
  data_passport_status: string
  geometry_warnings: string[]
  geometry_repaired: boolean
}

export interface BoundaryVersionCreateResponse {
  id: string
  boundary_version: number
  area_ha: number
  geometry_valid: boolean
  geometry_warnings: string[]
  geometry_repaired: boolean
}

export interface BoundaryVersionItem {
  id: string
  version_number: number
  area_ha: number
  change_reason: string | null
  created_at: string
  boundary_geojson: GeoJSONGeometry
}

export interface BoundaryVersionListResponse {
  items: BoundaryVersionItem[]
  total: number
}

export interface FieldPatchInput {
  name?: string
}

// ---------------------------------------------------------------------------
// Field map payload
// ---------------------------------------------------------------------------

export interface FieldMapResponse {
  field: {
    id: string
    name: string
    area_ha: number
    boundary_version: number
  }
  boundary_geojson: GeoJSONGeometry
  bbox: [number, number, number, number]
  crs: string
  area_method: string
}

// ---------------------------------------------------------------------------
// Data catalog & provider health
// ---------------------------------------------------------------------------

export interface CatalogVariable {
  code: string
  name: string
  unit: string
  typical_time_support: string
  description: string
  evidence_class_hint: string
}

export interface CatalogProduct {
  product_code: string
  product_version: string
  description: string
  temporal_resolution: string
  coverage: { start: string; end: string }
  metadata: Record<string, unknown>
}

export interface CatalogSource {
  provider_code: string
  provider_name: string
  license_name: string
  attribution_text: string
  documentation_url: string
  status: string
  known_limitations: string
  products: CatalogProduct[]
}

export interface CatalogResponse {
  data_dictionary_version: string
  variables: CatalogVariable[]
  sources: CatalogSource[]
}

export interface ProviderProfile {
  code: string
  description: string
}

export interface ProviderHealth {
  provider_code: string
  kind: string
  status: string
  details: {
    profiles: ProviderProfile[]
    is_synthetic: boolean
    note: string
  }
}

export interface ProvidersHealthResponse {
  providers: ProviderHealth[]
}

// ---------------------------------------------------------------------------
// Data ingestion jobs
// ---------------------------------------------------------------------------

export type SyntheticProfile =
  | 'temperate_seasonal'
  | 'mediterranean_dry_summer'
  | 'semi_arid'
  | 'tropical_seasonal'
  | 'arid_irrigated'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface DataJob {
  job_id: string
  job_type: string
  field_id: string
  provider_code: string
  status: JobStatus
  records_received: number
  records_rejected: number
  warnings: string[]
  error_summary: string | null
  request_parameters: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
  status_url: string
}

export interface DataJobCreateInput {
  provider_code: string
  variables: string[]
  start_date: string
  end_date: string
  profile: SyntheticProfile
  seed: number
}

// ---------------------------------------------------------------------------
// Observations
// ---------------------------------------------------------------------------

export interface ObservationMetadata {
  generator_version?: string
  seed?: number
  profile?: string
  purpose?: string
}

export interface Observation {
  id: string
  variable_code: string
  value: number | null
  unit: string
  observed_at: string
  period_start: string | null
  period_end: string | null
  time_support: string | null
  spatial_support_type: string | null
  spatial_resolution_m: number | null
  quality_status: string
  uncertainty_value: number | null
  uncertainty_type: string | null
  is_synthetic: boolean
  processing_version: string | null
  metadata: ObservationMetadata | null
}

export interface ObservationListResponse {
  items: Observation[]
  total: number
  limit: number
  offset: number
}

// ---------------------------------------------------------------------------
// Data passport
// ---------------------------------------------------------------------------

export interface PassportWarning {
  flag_code: string
  severity: string
  message: string
  observed_at: string | null
}

export interface PassportDatasetProduct {
  provider_code: string
  provider_name: string
  product_code: string
  product_version: string
  license_name: string
  attribution_text: string
  documentation_url: string
}

export interface PassportVariable {
  variable_code: string
  unit: string
  status: string
  observation_count: number
  valid_count: number
  missing_count: number
  valid_ratio: number
  is_synthetic: boolean
  evidence_class: string
  processing_version: string | null
  last_retrieved_at: string | null
  freshness_days: number | null
  period: { start: string; end: string } | null
  time_support: string | null
  spatial_support: { type: string; resolution_m: number | null } | null
  dataset_product: PassportDatasetProduct | null
  warnings: PassportWarning[]
}

export interface PassportMissingVariable {
  variable_code: string
  status: string
  unit: string
  reason: string
}

export interface PassportAnalysis {
  analysis_code: string
  name: string
  description: string
  status: 'available' | 'blocked'
  required_inputs: string[]
  missing_inputs: string[]
  reasons: string[]
}

export interface DataPassport {
  field_id: string
  generated_at: string
  overall_status: PassportOverallStatus
  variables: PassportVariable[]
  missing_variables: PassportMissingVariable[]
  warnings: PassportWarning[]
  analyses: PassportAnalysis[]
  notes: string[]
}

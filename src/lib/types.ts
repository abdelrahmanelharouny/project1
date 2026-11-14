/**
 * CropTwist API contract types (frozen, verified against the FastAPI backend).
 * All endpoints live under /api/v1 and are reached through the Next.js
 * same-origin rewrite (see src/lib/api.ts).
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
  /** Rotating refresh token (P0-2). Reuse of a superseded refresh token
   * revokes the whole session family server-side. */
  refresh_token?: string
  refresh_expires_at?: string
  user: User
  organization: OrganizationRef
  organizations?: MembershipRef[]
}

/**
 * P1 server-side session: what the /api/auth/* route handlers return AFTER
 * stripping the token material. The access/refresh tokens themselves live in
 * HttpOnly cookies and never reach JavaScript.
 */
export interface AuthSession {
  user: User
  organization: OrganizationRef | null
  organizations?: MembershipRef[]
  expires_at?: string
}

export interface DemoSession extends AuthSession {
  note: string
  farm_id: string
  field_ids: string[]
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

export interface ProviderProbe {
  status: string
  latency_ms: number | null
  detail: string
}

export interface ProviderModelInfo {
  code: string
  open_meteo_model_param: string
  description: string
  spatial_resolution_m: number
  land_only: boolean
  variables: string[]
}

export interface ProviderHealth {
  provider_code: string
  kind: string
  status: string
  details: {
    profiles?: ProviderProfile[]
    is_synthetic?: boolean
    note?: string
    models?: ProviderModelInfo[]
    default_model?: string
    workflow?: string
    rasterio_available?: boolean
    supported_variables?: string[]
    evidence_class?: string
    [key: string]: unknown
  }
  probe?: ProviderProbe
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

/** Mirrors ingestion-job status CHECK constraint (app/db/models.py):
 *  ('queued','running','succeeded','failed','cancelled','retrying'). */
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

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
  profile?: SyntheticProfile | null
  seed?: number
  model?: string | null
}

// ---------------------------------------------------------------------------
// Data coverage (Milestone 3)
// ---------------------------------------------------------------------------

export interface CoverageProviderEntry {
  provider_code: string
  provider_name: string
  product_code: string
  product_version: string
  count: number
  valid_count: number
  first: string | null
  last: string | null
  last_retrieval: string | null
}

export interface CoverageVariable {
  variable_code: string
  unit: string
  total: number
  valid: number
  providers: CoverageProviderEntry[]
}

export interface DataCoverageResponse {
  field_id: string
  variables: CoverageVariable[]
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
  /** Honesty flag (deepening F-01): synthetic entries never share a card with real ones. */
  is_synthetic?: boolean
  evidence_class?: string | null
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

// ---------------------------------------------------------------------------
// Feature engineering (Milestone 4)
// ---------------------------------------------------------------------------

export interface FeatureCatalogEntry {
  feature_code: string
  name: string
  description: string
  unit: string
  category: string
  aggregation_levels: string[]
  required_variables: string[]
  min_coverage_ratio: number
  formula_reference: string
  strategy: string
  definition_version: string
}

export interface FeatureCatalogResponse {
  feature_catalog_version: string
  features: FeatureCatalogEntry[]
  notes: string[]
}

export interface FeatureRunSourceSelection {
  dataset_product_id: string
  product_code: string
  product_version: string
  is_synthetic: boolean
}

export interface FeatureRun {
  run_id: string
  field_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  calendar_timezone: string
  hemisphere: string
  period: { start: string; end: string }
  aggregation_levels: string[]
  requested_variables: string[]
  source_selection: Record<string, FeatureRunSourceSelection>
  crop_seasons: { label: string; start_date: string; end_date: string }[]
  feature_engine_version: string
  feature_catalog_version: string
  is_synthetic: boolean
  warnings: string[]
  not_evaluated_reasons: Record<string, string>
  records_written: number
  error_summary: string | null
  started_at: string | null
  completed_at: string | null
  status_url: string
}

export interface FeatureRunListResponse {
  items: FeatureRun[]
  total: number
  limit: number
  offset: number
}

export interface FeatureRunCreateInput {
  start_date: string
  end_date: string
  aggregation_levels: string[]
  feature_codes?: string[]
  calendar_timezone?: string
  hemisphere?: string
  crop_seasons?: { label: string; start_date: string; end_date: string }[]
  source_overrides?: Record<string, string>
  idempotency_key?: string
}

export interface FeatureValueProvenance {
  engine_version?: string
  definition_version?: string
  calendar?: { timezone: string; hemisphere: string; assignment_rule: string }
  required_variables?: string[]
  inputs?: {
    observation_count: number
    dataset_products: string[]
    processing_versions: string[]
    evidence_classes: string[]
    is_synthetic: boolean
  }
  observation_ids?: string[]
  observation_count?: number
  checksum?: string
  baseline?: {
    calendar_month?: number
    season?: string
    window_years: number[]
    n_years: number
    mean: number
    sd: number
  }
  derived_from?: Record<string, { feature_code: string; value: number }>
  crop_season_window?: { label: string; start: string; end: string; source: string }
  reason?: string
  formula?: string
}

export interface FeatureValue {
  id: string
  feature_code: string
  aggregation_level: 'daily' | 'monthly' | 'seasonal' | 'crop_season'
  period_label: string
  period_start: string
  period_end: string
  value: number | null
  unit: string
  coverage_ratio: number | null
  n_input: number
  n_missing: number
  quality_status: 'valid' | 'partial' | 'insufficient_coverage' | 'missing' | 'not_evaluated'
  uncertainty_value: number | null
  uncertainty_type: string | null
  baseline_reference: Record<string, unknown> | null
  provenance: FeatureValueProvenance
}

export interface FeatureValueListResponse {
  run_id: string
  items: FeatureValue[]
  total: number
  limit: number
  offset: number
}

export interface FeatureRunComparisonDelta {
  feature_code: string
  aggregation_level: string
  period_label: string
  unit: string
  run_value: number
  against_value: number
  delta: number
  delta_pct: number | null
  quality_run: string
  quality_against: string
}

export interface FeatureRunComparison {
  run_id: string
  against_run_id: string
  matched_periods: number
  only_in_run: number
  deltas: FeatureRunComparisonDelta[]
  note: string
}

// =============================================================
// Milestone 5 — agricultural knowledge base & rotation intelligence
// =============================================================

export interface KnowledgePackRef {
  id: string
  pack_code: string
  pack_version: string
  name: string
  description: string
  region_scope: string
  status: string
  license_name: string
  attribution_text: string
  license_notes: string | null
  digitization_note: string | null
  checksum_sha256: string
  imported_at: string | null
  counts: { crops: number; traits: number; rotation_rules: number; sources: number }
}

export interface KnowledgePackListResponse {
  packs: KnowledgePackRef[]
  total: number
}

export interface KnowledgeSourceRef {
  source_key: string
  publisher: string
  title: string
  url: string | null
  publication_year: number | null
  license: string | null
  citation_text: string
}

export interface KnowledgePackSourcesResponse {
  pack: { id: string; pack_code: string; pack_version: string }
  sources: KnowledgeSourceRef[]
}

export interface CropCalendarWindowRef {
  region_code: string | null
  hemisphere: string
  planting_start: string
  planting_end: string
  harvest_start: string | null
  harvest_end: string | null
  evidence_class: string
  validation_status: string
  notes: string | null
}

export interface KnowledgeCropRef {
  id: string
  crop_code: string
  scientific_name: string | null
  common_names: string[]
  family_key: string | null
  family_scientific_name: string | null
  crop_category: string | null
  life_cycle_type: string | null
  is_legume: boolean
  is_cover_crop_capable: boolean
  trait_codes: string[]
  has_kc_parameters: boolean
  calendar_windows: CropCalendarWindowRef[]
}

export interface KnowledgeCropListResponse {
  crops: KnowledgeCropRef[]
  total: number
}

export interface CropTraitDetail {
  trait_code: string
  value_numeric: number | null
  value_text: string | null
  value_low: number | null
  value_high: number | null
  unit: string | null
  region_code: string | null
  evidence_class: string
  confidence: string
  validation_status: string
  notes: string | null
  source: {
    source_key: string | null
    citation_text: string | null
    publisher: string | null
    url: string | null
  }
}

export interface CropWaterParamDetail {
  growth_stage: string
  kc_value: number
  kc_method: string
  evidence_class: string
  validation_status: string
  notes: string | null
  source: { source_key: string | null; citation_text: string | null }
}

export interface CropDetailResponse {
  crop_code: string
  scientific_name: string | null
  common_names: string[]
  crop_category: string | null
  life_cycle_type: string | null
  is_legume: boolean
  is_cover_crop_capable: boolean
  pack: {
    pack_code: string | null
    pack_version: string | null
    status: string | null
    license_name: string | null
    attribution_text: string | null
    digitization_note: string | null
  }
  traits: CropTraitDetail[]
  calendar_windows: CropCalendarWindowRef[]
  water_parameters: CropWaterParamDetail[]
}

export interface RotationRuleRef {
  rule_code: string
  rule_type: string
  predecessor: { kind: string; key: string } | null
  successor: { kind: string; key: string } | null
  target: { kind: string; key: string } | null
  min_break_seasons: number
  mechanism: string | null
  scope_note: string | null
  applies_to_regions: string[]
  validation_status: string
  severity: string
  hard_enforceable: boolean
  source: { source_key: string | null; citation_text: string | null }
}

export interface RotationRulesResponse {
  rules: RotationRuleRef[]
  total: number
  confirmed_regional_count: number
  note: string
}

export interface KnowledgePackImportInput {
  pack: Record<string, unknown>
  activate?: boolean
}

export interface KnowledgePackImportResponse {
  created: boolean
  pack: { id: string; pack_code: string; pack_version: string; status: string; checksum_sha256: string }
  validation: { ok: boolean; errors: string[]; warnings: string[]; counts: Record<string, number> }
}

export interface CropHistoryItem {
  id: string
  crop_code: string | null
  crop_label: string
  sowing_date: string | null
  harvest_date: string | null
  season_label: string | null
  area_ha: number | null
  source: string
  evidence_class: string
}

export interface CropHistoryListResponse {
  field_id: string
  items: CropHistoryItem[]
}

export interface CropHistoryCreateInput {
  crop_code?: string | null
  crop_label: string
  sowing_date?: string | null
  harvest_date?: string | null
  season_label?: string | null
  area_ha?: number | null
  source?: string
  evidence_class?: string
}

export interface CandidateReason {
  kind: string
  code: string
  message: string
  severity: string
  source_refs?: Array<Record<string, unknown>>
}

export interface CandidateAssessment {
  crop_code: string
  status: 'eligible' | 'conditionally_eligible' | 'excluded' | 'unevaluated'
  reasons: CandidateReason[]
  unevaluated_dimensions: Array<{ code: string; message: string }>
  water_requirement_mm: number | null
  water_estimate_assumptions: string[]
  calendar_windows_matched: string[]
}

export interface CandidateSeason {
  season_label: string
  candidates: CandidateAssessment[]
}

export interface CropCandidatesResponse {
  field_id: string
  evidence_run_id: string | null
  hemisphere: string
  knowledge_pack_refs: Array<Record<string, unknown>>
  warnings: string[]
  seasons: CandidateSeason[]
  counts_by_season: Record<string, Record<string, number>>
}

export interface CropCandidatesInput {
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  hemisphere: string
  evidence_run_id?: string | null
}

export interface RotationSeasonInput {
  label: string
  start_date: string
  end_date: string
}

export interface RotationRunCreateInput {
  seasons: RotationSeasonInput[]
  hemisphere: string
  evidence_run_id?: string | null
  strategy_profiles?: string[]
  custom_weights?: Record<string, number>
  water_allocation_m3?: number | null
  idempotency_key?: string | null
}

export interface RotationCriterion {
  criterion_code: string
  raw_value: number | null
  unit: string
  direction: string
  normalized: number | null
  evaluable: boolean
  missing_evidence: string[]
  derivation: string
}

export interface RotationConstraintCheck {
  constraint_code: string
  status: string
  description: string
  detail: string | null
  rule_codes: string[]
  source_refs: Array<Record<string, unknown>>
}

export interface RotationStrategy {
  id: string
  strategy_key: string
  strategy_kind: string
  is_baseline: boolean
  profile_weights: Record<string, number>
  weights_effective: Record<string, number>
  skipped_weights: Record<string, string>
  assignment: Array<{ season_label: string; crop_code: string | null }>
  objective_value: number | null
  criteria: RotationCriterion[]
  constraints_checked: RotationConstraintCheck[]
  pareto: { on_front: boolean; dominated_by: string[]; dominates: string[] }
  explanations: {
    why_generated: string
    recommendation: { status: string; message: string }
    constraints_checked: RotationConstraintCheck[]
    criteria_evaluation: RotationCriterion[]
    evidence_references: Array<Record<string, unknown>>
    data_limitations: string[]
    expected_benefits: string[]
    risks_trade_offs: string[]
    local_expert_validation_required: string[]
  }
  evidence_coverage: number | null
  checksum_sha256: string | null
}

export interface RotationRun {
  id: string
  field_id: string
  status: string
  solver_status: string | null
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  strategy_profiles: string[]
  water_allocation_m3: number | null
  knowledge_pack_refs: Array<Record<string, unknown>>
  feature_run_ids: string[]
  crop_history_ids: string[]
  rotation_engine_version: string
  solver_name: string
  random_seed: number
  infeasibility_details: { profiles?: Array<{ strategy_key: string; conflicts: Array<{ constraint: string; detail: string }> }>; note?: string }
  warnings: string[]
  not_evaluated: Record<string, Record<string, string[]>>
  error_summary: string | null
  started_at: string | null
  completed_at: string | null
  strategies?: RotationStrategy[]
}

export interface RotationRunListResponse {
  field_id: string
  runs: Array<{
    id: string
    status: string
    solver_status: string | null
    seasons: Array<{ label: string }>
    strategy_profiles: string[]
    rotation_engine_version: string
    created_at: string | null
    completed_at: string | null
    n_strategies: number
  }>
}

export interface RotationStrategiesResponse {
  run_id: string
  solver_status: string | null
  infeasibility_details: RotationRun['infeasibility_details']
  strategies: RotationStrategy[]
}

export interface RotationComparisonResponse {
  run_id: string
  criterion_codes: string[]
  strategies: Array<{
    strategy_key: string
    is_baseline: boolean
    objective_value: number | null
    on_pareto_front: boolean
    dominated_by: string[]
    evidence_coverage: number | null
    criteria: Record<string, { raw_value: number | null; normalized: number | null; evaluable: boolean }>
  }>
  note: string
}

// Milestone 6A — water intelligence engine

export interface WaterMethodMeta {
  code: string
  scope: string
  formula: string
  conditions: string
  evidence_class: string
  citation_text: string
}

export interface WaterMethodsResponse {
  water_engine_version: string
  methods_version: string
  effective_rainfall_methods: WaterMethodMeta[]
  soil_sources: Array<{ code: string; detail: string }>
  irrigation_efficiency_classes: Array<{
    method_class: string
    efficiency: number
    applies_to: string
    evidence_class: string
    citation_text: string
  }>
  unit_identities: { mm_over_ha_to_m3: number; mm_over_m2_to_litres: number }
  not_implemented: Array<{ item: string; reason: string }>
}

export interface WaterReadinessDimension {
  status: 'complete' | 'partial' | 'missing' | 'not_locally_validated' | 'not_applicable'
  detail: string
  source?: Record<string, unknown> | null
}

export interface WaterReadinessCrop {
  crop_code: string
  overall: string
  etc_computable: boolean
  dimensions: Record<string, WaterReadinessDimension>
  notes: string[]
}

export interface WaterReadinessResponse {
  field_id: string
  crops: WaterReadinessCrop[]
  summary: { total_crops: number; by_overall: Record<string, number>; note: string }
}

export interface WaterPlanStage {
  stage: string
  day_window: [number, number]
  dates: [string, string]
  days_in_season: number
  days_in_crop?: number
  kc_mean: number | null
  kc_start: number | null
  kc_end: number | null
  etc_mm: number | null
  pe_mm: number | null
  dr_end_mm: number | null
  ks_mean: number | null
  stress_sensitivity?: { p_table: number | null; p_used: number | null; basis: string | null }
}

export interface WaterPlanMonth {
  year: number
  month: number
  days_in_season: number
  et0_mm: number | null
  kc_mean: number | null
  etc_mm: number | null
  precip_mm: number | null
  effective_rainfall_mm: number | null
  precip_evidence_missing: boolean
  net_irrigation_mm: number | null
  dr_end_mm: number | null
}

export interface WaterPlanLadderStep {
  quantity: string
  value_mm: number | null
  status: string
  basis: string
  detail: string | null
}

export interface WaterPlanSeason {
  season_label: string
  crop_code: string
  season: { start_date: string; end_date: string }
  sowing_date: string
  area_ha: number
  totals: {
    et0_mm: number | null
    etc_mm: number | null
    precip_mm: number | null
    effective_rainfall_mm: number | null
    soil_water_contribution_mm: number | null
    net_irrigation_requirement_mm: number | null
    gross_irrigation_requirement_mm: number | null
    volumes_m3: Record<string, number>
  }
  stages: WaterPlanStage[]
  months: WaterPlanMonth[]
  ladder: WaterPlanLadderStep[]
  volumes_m3: Record<string, number>
  allocation: {
    water_allocation_m3: number | null
    status: string
    detail: string
    net_requirement_m3?: number
    coverage_ratio?: number
    deficit_m3?: number
  }
  deficit_windows: Array<Record<string, unknown>>
  root_zone: {
    source_label: string
    taw_mm: number | null
    raw_mm: number | null
    p_table: number | null
    p_used: number | null
    dr_start_mm: number | null
    dr_end_mm: number | null
    soil_evidence_classes: Record<string, string | null>
  }
  effective_rainfall: {
    method: string
    info: Record<string, unknown>
    pe_by_month: Record<string, number>
  }
  assumptions: string[]
  missing_evidence: string[]
  sources: Array<Record<string, unknown>>
  checksum_sha256: string
}

export interface WaterPlanResult {
  engine_version: string
  methods_version: string
  seasons: WaterPlanSeason[]
  rotation_totals: {
    seasons_total: number
    seasons_evaluable: number
    net_irrigation_requirement_mm_sum: number | null
    net_irrigation_requirement_m3_sum: number | null
    note: string
  }
  area_ha: number
}

export interface WaterPlan {
  id: string
  field_id: string
  status: string
  label: string
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  crop_assignments: Array<Record<string, unknown>>
  methods: { effective_rainfall_method?: string } & Record<string, unknown>
  soil_inputs: Record<string, unknown>
  warnings: string[]
  not_evaluated: Record<string, string[]>
  water_engine_version: string
  methods_version: string
  feature_run_ids: string[]
  knowledge_pack_refs: Array<Record<string, unknown>>
  water_allocation_m3: number | null
  checksum_sha256: string | null
  error_summary: string | null
  created_at: string | null
  result?: WaterPlanResult
}

export interface WaterPlanListResponse {
  field_id: string
  items: WaterPlan[]
}

export interface WaterPlanCreateInput {
  label?: string
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  crop_assignments: Array<{ crop_code: string }>
  sowing_dates?: Record<string, string>
  soil_source?: 'none' | 'farmer_measured' | 'ptf_texture'
  farmer_soil?: { theta_fc: number; theta_wp: number; zr_m?: number; p_table?: number }
  effective_rainfall_method?: string
  pe_fraction?: number
  irrigation_efficiency?: { value?: number; method_class?: string }
  water_allocation_m3?: number | null
  evidence_run_id?: string | null
  idempotency_key?: string
}

// ---------------------------------------------------------------------------
// M7.1 — Field State foundation
// ---------------------------------------------------------------------------

export type FieldStateDimensionStatus =
  | 'available'
  | 'missing'
  | 'period_mismatch'
  | 'not_evaluated'
  | 'not_implemented'

export interface FieldStateDimension {
  status: FieldStateDimensionStatus
  reason: string | null
  snapshot_id: string | null
}

export interface FieldStatePeriodCompatRecord {
  status: 'covers_period' | 'partial_cover' | 'outside_period' | 'not_evaluated'
  reason?: string
  artifact_period?: { start: string | null; end: string | null }
  overlap_fraction?: number | null
}

export interface FieldState {
  id: string
  field_id: string
  status: 'running' | 'succeeded' | 'failed'
  label: string
  boundary_version: number
  state_reference_time: string
  period: { start: string; end: string }
  timezone: string
  calendar_context: Record<string, unknown>
  environmental_feature_run_id: string | null
  water_plan_id: string | null
  rotation_run_id: string | null
  rotation_strategy_key: string | null
  crop_history_ids: string[]
  knowledge_pack_refs: Array<Record<string, unknown>>
  observation_manifest_sha256: string | null
  manifest_format_version: string
  domain_availability: Record<string, FieldStateDimension>
  evidence_summary: Record<string, unknown>
  quality_summary: Record<string, unknown>
  period_compatibility: Record<string, FieldStatePeriodCompatRecord>
  source_versions: Record<string, unknown>
  warnings: string[]
  not_evaluated: Record<string, unknown>
  error_summary: string | null
  checksum_sha256: string | null
  created_by: string | null
  created_at: string | null
  completed_at: string | null
  field_state_assembly_version: string | null
  verify_url: string
  manifest_url: string
}

export interface FieldStateListResponse {
  items: FieldState[]
}

export interface FieldStateCreateInput {
  label?: string
  state_reference_time?: string
  period_start?: string
  period_end?: string
  environmental_feature_run_id?: string
  water_plan_id?: string
  rotation_run_id?: string
  rotation_strategy_key?: string
  idempotency_key?: string
}

export interface FieldStateVerifyResponse {
  state_id: string
  checksum_valid: boolean
  manifest_checksum_valid: boolean
  referenced_artifacts: Record<string, { exists: boolean; intact: boolean }>
  boundary_version_record_exists: boolean
  verified_at: string
}

export interface FieldStateCompareResponse {
  state_ids: string[]
  same_field: boolean
  field_id: string
  boundary_versions_consistent: boolean
  dimension_comparison: Record<
    string,
    { consistent: boolean; values: Array<string | number | null> }
  >
  pairwise_period_overlap: Array<{
    state_a: string
    state_b: string
    period_overlap_fraction: number | null
    compatible_periods: boolean
  }>
  note: string
}

export interface ObservationManifest {
  format_version: string
  context: Record<string, unknown>
  observation_count: number
  synthetic_observation_count: number
  observations: Array<Record<string, unknown>>
}

// ---------------------------------------------------------------------------
// Scenario domain (M7.2)
// ---------------------------------------------------------------------------

export type ScenarioType =
  | 'historical_observed'
  | 'historical_perturbation'
  | 'user_defined_stress'
  | 'climate_projection'
  | 'weather_forecast'

export type ScenarioStatus =
  | 'draft'
  | 'validation_pending'
  | 'valid'
  | 'conditionally_valid'
  | 'invalid'
  | 'finalized'
  | 'archived'
  | 'unsupported'

export type EvidenceClassification = 'observed' | 'hypothetical' | 'not_available'

export interface ScenarioUnavailableDimension {
  status: string
  reason: string
  dimension?: string
}

export interface Scenario {
  id: string
  field_id: string
  name: string
  description: string | null
  scenario_type: ScenarioType
  scenario_type_display: string
  scenario_status: ScenarioStatus
  lineage_kind: 'root' | 'revision' | 'branch'
  scenario_version: number
  parent_scenario_id: string | null
  parent_field_state_id: string
  parent_snapshot_checksum: string
  boundary_version: number
  configuration_schema_version: string
  canonical_configuration: Record<string, unknown>
  configuration_checksum: string
  period: { start: string; end: string }
  timezone: string
  evidence_classification: EvidenceClassification
  evidence_label: string
  assumption_metadata: Record<string, unknown>
  validation_summary: Record<string, unknown>
  unavailable_dimensions: Record<string, ScenarioUnavailableDimension>
  created_by: string | null
  created_at: string | null
  updated_at: string | null
  finalized_at: string | null
  verify_url: string
  versions_url: string
  lineage_url: string
  note: string
  validation_history?: Array<Record<string, unknown>>
}

export interface ScenarioListResponse {
  items: Scenario[]
}

export interface ScenarioAdjustments {
  temperature_delta_c?: number | null
  precipitation_multiplier?: number | null
  precipitation_delta_mm?: number | null
  water_allocation_multiplier?: number | null
  seasonal_timing_shift_days?: number | null
  rainfall_period_shift_days?: number | null
}

export interface ScenarioCreateInput {
  scenario_type: string
  name?: string
  description?: string
  configuration: {
    type: string
    parent_field_state_id: string
    period?: { start: string; end: string }
    adjustments?: ScenarioAdjustments
    assumption_metadata?: { origin?: string; status?: string; description?: string }
  }
  parent_scenario_id?: string
  idempotency_key?: string
}

export interface ScenarioValidationFinding {
  code: string
  severity: 'error' | 'warning' | 'info'
  message: string
  [key: string]: unknown
}

export interface ScenarioValidateResponse {
  scenario_id: string
  scenario_version: number
  scenario_status: ScenarioStatus
  validation_rule_version: string
  validation_status: string
  configuration_checksum: string
  validation_result: {
    validation_rule_version: string
    status: string
    findings: ScenarioValidationFinding[]
    missing_inputs: string[]
    unsupported_dimensions: ScenarioUnavailableDimension[]
    configuration_checksum: string
    validated_at?: string
    record_id?: string
  }
  record_id: string
  created_at: string | null
  note: string
}

export interface ScenarioVerifyResponse {
  scenario_id: string
  configuration_checksum_valid: boolean
  expected_checksum: string
  stored_checksum: string
  parent_state_exists: boolean
  parent_snapshot_checksum_matches: boolean
  boundary_version_record_exists: boolean
  latest_validation: {
    record_id: string
    validation_status: string
    configuration_checksum: string
    matches_current_configuration: boolean
  } | null
  verified_at: string | null
  note: string
}

export interface ScenarioTaxonomyType {
  scenario_type: ScenarioType
  display_name: string
  capability: 'implemented' | 'not_implemented'
  evidence_classification: EvidenceClassification
  evidence_label: string
  description: string
  unavailable_reason: string | null
}

export interface ScenarioTaxonomy {
  taxonomy_version: string
  configuration_schema_version: string
  validation_rules_version: string
  types: ScenarioTaxonomyType[]
  dimensions: Record<string, ScenarioUnavailableDimension>
  adjustment_bounds: Record<string, [number, number]>
  lifecycle: {
    statuses: ScenarioStatus[]
    legal_transitions: Record<string, string[]>
  }
  note: string
}

export interface ScenarioCapabilities {
  taxonomy_version: string
  capabilities: Array<{
    scenario_type: ScenarioType
    capability: 'implemented' | 'not_implemented'
    evidence_classification: EvidenceClassification
    unavailable_reason: string | null
  }>
  dimensions: Record<string, ScenarioUnavailableDimension>
  execution: { scenario_execution: string; reason: string }
  digital_twin_level: string
  note: string
}

export interface ScenarioVersionsResponse {
  scenario_id: string
  chain_length: number
  latest_version: number
  items: Array<{
    id: string
    scenario_version: number
    scenario_status: ScenarioStatus
    configuration_checksum: string
    configuration_schema_version: string
    name: string
    parent_scenario_id: string | null
    created_at: string | null
    finalized_at: string | null
  }>
}

export interface ScenarioLineageResponse {
  scenario_id: string
  lineage_kind: 'root' | 'revision' | 'branch'
  scenario_version: number
  ancestors: Array<{
    id: string
    name: string
    scenario_type: ScenarioType
    scenario_version: number
    lineage_kind: 'root' | 'revision' | 'branch'
    scenario_status: ScenarioStatus
    configuration_checksum: string
  }>
  children: Array<{
    id: string
    name: string
    scenario_type: ScenarioType
    scenario_version: number
    lineage_kind: 'root' | 'revision' | 'branch'
    scenario_status: ScenarioStatus
    configuration_checksum: string
  }>
  revision_chain_length: number
  note: string
}

export interface ScenarioConfigDiffEntry {
  path: string
  kind: 'added' | 'removed' | 'changed'
  left: unknown
  right: unknown
}

export interface ScenarioCompareResponse {
  scenario_a: {
    id: string
    name: string
    scenario_type: ScenarioType
    evidence_classification: EvidenceClassification
    evidence_label: string
    scenario_version: number
    scenario_status: ScenarioStatus
    configuration_checksum: string
    parent_field_state_id: string
    parent_snapshot_checksum: string
    boundary_version: number
    period: { start: string; end: string }
  }
  scenario_b: ScenarioCompareResponse['scenario_a']
  parents: {
    same_field: boolean
    same_parent_state: boolean
    parent_checksums_equal: boolean
    boundary_versions: [number, number]
    boundary_versions_equal: boolean
  }
  temporal_comparison: { period_overlap_fraction: number | null; compatible_periods: boolean }
  configuration_diff: ScenarioConfigDiffEntry[]
  changed_assumptions: string[]
  identical_configuration: boolean
  evidence_classes_differ: boolean
  unavailable_dimensions: Record<string, ScenarioUnavailableDimension>
  warnings: string[]
  compatibility: { parents_compatible: boolean; note: string }
  note: string
}

// =============================================================
// M6B — Soil intelligence (soil.tsx)
// Mirror of app.api.v1.soil / app.soil.* payload builders.
// =============================================================

export interface SoilMeasurement {
  id: string
  field_id: string
  layer_id: string | null
  variable_code: string
  value: number | null
  unit: string
  top_depth_cm: number | null
  bottom_depth_cm: number | null
  evidence_class: string
  spatial_support_type: string | null
  source_kind: string | null
  method_params: Record<string, unknown> | null
  detection_limit: number | null
  quantification_limit: number | null
  result_qualifier: string | null
  uncertainty_value: number | null
  uncertainty_type: string | null
  quality_status: string
  is_synthetic: boolean
  observed_at: string
  processing_version: string | null
}

export interface SoilDepthGap {
  from_cm: number | null
  to_cm: number | null
  gap_cm: number | null
}

export interface SoilProfileIntegrity {
  overlaps: Array<Record<string, unknown>>
  gaps: SoilDepthGap[]
  coverage_cm: [number, number] | null
  note: string
}

export interface SoilProfileLayer {
  top_cm: number
  bottom_cm: number
  source_kinds: string[]
  evidence_classes: string[]
  measurements: SoilMeasurement[]
  sample_id: string | null
}

export interface SoilProfileResponse {
  field_id: string
  engine_version: string
  layers: SoilProfileLayer[]
  integrity: SoilProfileIntegrity
}

/** USDA texture derivation (present when sand+clay were evaluable). */
export interface SoilTextureDerivation {
  class: string
  sand_pct: number | null
  silt_pct: number | null
  clay_pct: number | null
  silt_basis: string
  classifier_version: string
}

/** Layer available-water-capacity derivation (present when θFC+θWP exist). */
export interface SoilAwcDerivation {
  awc_m3_m3: number
  awc_mm: number
  fc_potential_kpa: number | null
  pwp_potential_kpa: number | null
}

/** Honest refusal for a derived indicator (never zero-filled). */
export interface SoilDerivationRefusal {
  status: 'not_evaluated'
  reason: string
}

export interface SoilIndicatorLayer {
  top_cm: number
  bottom_cm: number
  texture?: SoilTextureDerivation | SoilDerivationRefusal
  awc?: SoilAwcDerivation | SoilDerivationRefusal
}

export interface SoilIndicatorsResponse {
  engine_version: string
  layers: SoilIndicatorLayer[]
  note: string
}

export interface SoilTrend {
  status: 'measured_change' | 'not_comparable'
  reason?: string | null
  points?: number
  first?: { date: string; value: number | null; unit: string }
  last?: { date: string; value: number | null; unit: string }
  delta?: number | null
  caveat?: string
}

export interface SoilDomainIndicator {
  variable_code: string
  latest_value: number | null
  unit: string
  observed_at: string
  evidence_class: string
  source_kind: string | null
  quality_status: string | null
  method: string | null
  uncertainty: number | null
  depth: [number | null, number | null]
  interpretation_note: string | null
  local_applicability: string
  trend?: SoilTrend
}

export interface SoilDomainRow {
  domain: string
  available: SoilDomainIndicator[]
  missing: string[]
  available_count: number
  missing_count: number
  data_quality_note: string
  synthetic_flag: boolean
}

export interface SoilAssessmentResult {
  field_id: string
  assessment_version: string
  engine_version: string
  methods_version: string
  domains: SoilDomainRow[]
  composite_score: null
  composite_note: string
  missing_is_not_bad_note: string
}

/** GET /fields/{id}/soil-health — live computation or latest snapshot. */
export interface SoilHealthResponse {
  source: 'live' | 'snapshot'
  assessment_id?: string
  result: SoilAssessmentResult
}

export interface SoilDataReadinessPriority {
  variable_code: string
  trigger: string
  decision_unblocked: string
  priority_basis: string
}

export interface SoilDataReadinessResponse {
  priorities: SoilDataReadinessPriority[]
  collected_note: string
  policy: string
}

export interface SoilMethodsResponse {
  soil_engine_version: string
  methods_version: string
  texture_classifier: {
    version: string
    system: string
    source: string
    silt_derivation: string
    tolerance: string
  }
  conversions: Record<
    string,
    { factor?: number; derivation?: string; method?: string; version?: string }
  >
  salinity_classes: Array<{
    range_ds_m: [number, number | null]
    class: string
    citation: string
    applies_to: string
  }>
  assessment_policy: { version: string; composite_index: null; note: string }
  variables: Array<{ code: string; unit: string; family: string; description: string }>
}

// --- SOC stock runs -------------------------------------------------------

export interface SocStockProfileTotal {
  soc_stock_mg_ha: number | null
  coverage_cm: [number, number] | null
  covered_thickness_cm: number
  contiguous: boolean
  reason?: string
}

export interface SocStockLayerRow {
  top_cm: number
  bottom_cm: number
  thickness_cm: number
  soc_stock_mg_ha: number | null
  evidence_class: string
  is_prediction: boolean
  inputs_used: Record<string, unknown>
  status?: 'evaluated' | 'not_evaluated'
  reason?: string | null
}

export interface SocStockResult {
  formula: string
  layers: SocStockLayerRow[]
  profile_total: SocStockProfileTotal
  not_evaluated: Array<{ layer: string; reason: string | null }>
  warnings: string[]
  gaps: SoilDepthGap[]
  soc_stock_version: string
  methods_version: string
  comparison?: Record<string, unknown> | null
}

export interface SocStockRun {
  id: string
  field_id: string
  status: 'running' | 'succeeded' | 'failed'
  label: string
  comparison_mode: string
  engine_version: string
  methods_version: string
  warnings: string[]
  not_evaluated: Array<{ layer: string; reason: string | null }>
  checksum_sha256: string | null
  error_summary: string | null
  result?: SocStockResult
}

export interface SocStockRunListResponse {
  field_id: string
  items: SocStockRun[]
}

export interface SocStockRunCreateInput {
  label?: string
  layers: Array<{
    top_depth: number
    bottom_depth: number
    oc_g_kg?: number | null
    bulk_density_g_cm3?: number | null
    bd_basis?: 'fine_earth' | 'whole_soil' | null
    coarse_fragment_vol_fraction?: number | null
    depth_unit?: string
    evidence_class?: string
    is_prediction?: boolean
  }>
  sample_ids?: string[]
  comparison_mode?: string
  baseline_run_id?: string
  idempotency_key?: string
  request_parameters?: Record<string, unknown>
}

// --- N/P/K nutrient budget -------------------------------------------------

export interface NutrientBalance {
  inputs_kg_ha: number | null
  outputs_kg_ha: number | null
  balance_kg_ha: number | null
  status: 'evaluated' | 'not_evaluable'
}

export interface NutrientSeasonResult {
  season_label: string
  overall: 'partial' | 'not_evaluable'
  balance: Record<'N' | 'P' | 'K', NutrientBalance>
  nue: Record<string, { definition: string; value: number; note: string }>
  inputs: Array<Record<string, unknown>>
  outputs: Array<Record<string, unknown>>
  missing_flows: string[]
  warnings: string[]
  interpretation_note: string
  engine_version: string
  methods_version: string
}

export interface NutrientBudgetResult {
  seasons: NutrientSeasonResult[]
  cumulative: Record<string, unknown>
  engine_version: string
  methods_version: string
  reference_library_note: string
}

export interface NutrientBudgetRun {
  id: string
  field_id: string
  status: 'running' | 'succeeded' | 'failed'
  label: string
  seasons: string[]
  engine_version: string
  methods_version: string
  request_parameters: Record<string, unknown>
  idempotency_key: string | null
  error_summary: string | null
  result?: NutrientBudgetResult
}

export interface NutrientBudgetRunCreateInput {
  seasons: string[]
  area_ha?: number
  label?: string
  idempotency_key?: string
  request_parameters?: Record<string, unknown>
}

// --- laboratory CSV import --------------------------------------------------

export interface SoilImportReport {
  template: string
  file_sha256: string
  rows_total: number
  imported: number
  rejected: number
  warnings: number
  rows: Array<{
    row_number: number
    status: string
    sample_code: string | null
    message: string | null
    measurement_id: string | null
  }>
  idempotency_key: string | null
}

export interface SoilLabImportResponse {
  status: 'imported' | 'already_imported'
  report: SoilImportReport
  created_samples: number
  created_measurements: number
  errors: string[]
  import_job_id?: string
}

// --- assessment snapshots ----------------------------------------------------

export interface SoilAssessmentRun {
  id: string
  field_id: string
  status: 'running' | 'succeeded' | 'failed'
  label: string
  engine_version: string
  checksum_sha256: string | null
  result: SoilAssessmentResult
}

// =============================================================
// M6C — Field management (management.tsx)
// Mirror of app.api.v1.management / app.management.* payloads.
// =============================================================

export interface CoverObservation {
  id: string
  observed_date: string
  cover_state: string
  cover_fraction: number | null
  measurement_basis: string | null
  index_type: string | null
  index_value: number | null
  evidence_class: string
  notes: string | null
  metadata: Record<string, unknown> | null
}

export interface CoverObservationCreateInput {
  observed_date: string
  cover_state: string
  cover_fraction?: number | null
  measurement_basis?: string | null
  notes?: string | null
}

export interface CoverTimelineDay {
  date: string
  states: string[]
  classification: 'protective' | 'bare' | 'unknown'
}

export interface CoverMetrics {
  window_days: number
  days_protective_cover: number
  days_known_bare: number
  days_unknown: number
  protective_cover_fraction: number | null
  protective_fraction_basis: string
  longest_bare_interval_days: number
  longest_bare_interval: [string, string] | null
  state_day_counts: Record<string, number>
  month_breakdown: Array<Record<string, unknown>>
}

export interface CoverTimelineResponse {
  field_id: string
  window: { start: string; end: string }
  timeline: CoverTimelineDay[]
  metrics: CoverMetrics
  evidence_notes: Array<{ detail: string; [key: string]: unknown }>
  thresholds: { applicable: string[]; note: string }
  method: { engine: string; version: string; rules: string[] }
  inputs_summary: Record<string, number>
}

export interface CoverDimension {
  status: string
  message?: string
  [key: string]: unknown
}

export interface CoverCandidate {
  crop_code: string
  crop_label: string
  status: 'eligible' | 'conditional' | 'excluded' | 'not_evaluated'
  reasons: Array<Record<string, unknown>>
  conditions: Array<{ code: string; message: string; source_refs?: unknown[] }>
  functions: Array<{ function_code: string; [key: string]: unknown }>
  function_gaps: Array<Record<string, unknown>>
  dimensions: Record<string, CoverDimension>
  sowing_window: [string, string] | null
  missing_inputs: string[]
  trade_off_note: string
}

export interface CoverPlanEvaluation {
  candidates: CoverCandidate[]
  global_gaps: Record<string, unknown>
  knowledge_pack_refs: Array<Record<string, unknown>>
}

/** Cover-crop plan run (immutable evaluation snapshot; detail/create payloads). */
export interface CoverCropPlan {
  id: string
  field_id: string
  status: string
  label: string
  window: { start: string | null; end: string | null }
  next_crop_label: string | null
  engine_version: string
  methods_version: string
  knowledge_pack_refs: Array<Record<string, unknown>>
  feature_run_ids: string[]
  water_plan_ids: string[]
  warnings: string[]
  not_evaluated: Record<string, unknown>
  request_parameters: Record<string, unknown>
  checksum_sha256: string | null
  created_at: string | null
  error_summary: string | null
  result: CoverPlanEvaluation
}

/** List payloads return the plan WITHOUT the evaluation block. */
export type CoverCropPlanSummary = Omit<CoverCropPlan, 'result'>

export interface CoverCropPlanCreateInput {
  window_start: string
  window_end: string
  next_crop_label?: string
  next_crop_sowing_date?: string
  excluded_crop_codes?: string[]
  label?: string
  feature_run_id?: string
  idempotency_key?: string
}

export interface CoverCropPlanItem {
  id: string
  field_id: string
  crop_label: string
  is_mixture: boolean
  mixture_composition: Array<Record<string, unknown>>
  status: string
  season_label: string | null
  intended_sowing_start: string | null
  intended_sowing_end: string | null
  intended_termination_window_start: string | null
  intended_termination_window_end: string | null
  intended_termination_method: string | null
  intended_functions: string[]
  seeding_rate: number | null
  seeding_rate_unit: string | null
  plan_run_id: string | null
  evidence_class: string
}

export interface CoverCropPlanItemCreateInput {
  crop_label: string
  plan_run_id?: string | null
  is_mixture?: boolean
  mixture_composition?: Array<Record<string, unknown>>
  season_label?: string | null
  intended_sowing_start?: string | null
  intended_sowing_end?: string | null
  intended_termination_window_start?: string | null
  intended_termination_window_end?: string | null
  intended_termination_method?: string | null
  intended_functions?: string[]
  status?: string
  evidence_class?: string
  notes?: string | null
}

export interface CoverCropPlanItemListResponse {
  field_id: string
  items: CoverCropPlanItem[]
}

export interface CoverCropPlanListResponse {
  field_id: string
  items: CoverCropPlanSummary[]
  total: number
}

// --- residue ledger ----------------------------------------------------------

export interface ResidueRecord {
  id: string
  field_id: string
  crop_label: string
  season_label: string | null
  basis: string
  produced_dm_kg: number | null
  production_status: string
  coefficient_provenance: Record<string, unknown> | null
  harvested_product_dm_kg: number | null
  harvested_product_status: string | null
  notes: string | null
  metadata: Record<string, unknown> | null
}

export interface ResidueRecordCreateInput {
  crop_label: string
  production_status: string
  produced_dm_kg?: number | null
  basis?: string
  season_label?: string | null
  crop_id?: string
  coefficient_provenance?: Record<string, unknown>
  notes?: string | null
}

export interface ResidueFlowRow {
  id: string
  flow_type: string
  flow_date: string | null
  dm_kg: number | null
  dm_kg_status: string
  soil_management_event_id: string | null
  evidence_class: string
}

export interface ResidueFlowCreateInput {
  flow_type: string
  dm_kg?: number | null
  dm_kg_status?: string
  flow_date?: string | null
  evidence_class?: string
  notes?: string | null
}

export interface ResidueLedgerEntry {
  record: ResidueRecord
  flows: ResidueFlowRow[]
  balance: {
    status: 'balanced' | 'over_allocated' | 'production_unknown'
    total_flow_dm_kg: number
    unaccounted_dm_kg: number | null
    [key: string]: unknown
  }
  derived: {
    note?: string
    total_nitrogen_kg?: number
    [key: string]: unknown
  }
  surface_retained_dm_kg: number
  [key: string]: unknown
}

export interface ResidueLedgerResponse {
  field_id: string
  records: ResidueLedgerEntry[]
  totals: Record<string, unknown>
  warnings: string[]
  method: { engine: string; version: string; rules: string[] }
}

// --- erosion ------------------------------------------------------------------

export interface ErosionConcern {
  evidence: string
  processes: string[]
}

export interface ErosionScreening {
  concerns: ErosionConcern[]
  field_observed_signs: Array<{ description: string; [key: string]: unknown }>
  unknowns: string[]
  processes_assessed: string[]
  message: string
}

export interface ErosionRusle {
  status: 'computed' | 'not_evaluated'
  processes?: string[]
  annual_soil_loss_a?: number
  unit_convention?: string
  message: string
  factors?: Record<string, Record<string, unknown>>
  scope_disclosures?: string[]
}

export interface ErosionAlternative {
  practice_code: string
  name: string
  practice_family: string
  validation_status: string
  mechanisms: Array<{
    mechanism_code: string | null
    text: string | null
    citation: { citation_text?: string | null } | null
    confidence: string | null
  }>
  trade_offs: Array<Record<string, unknown>>
  quantitative_note: string
}

export interface ErosionResult {
  screening: ErosionScreening
  rusle: ErosionRusle
  alternatives: ErosionAlternative[]
  not_evaluated: { processes: Record<string, string> }
}

export interface ErosionRun {
  id: string
  field_id: string
  status: string
  label: string
  engine_version: string
  methods_version: string
  warnings: string[]
  not_evaluated: Record<string, unknown>
  request_parameters: Record<string, unknown>
  checksum_sha256: string | null
  created_at: string | null
  result: ErosionResult
}

/** List payloads return the run WITHOUT the result block. */
export type ErosionRunSummary = Omit<ErosionRun, 'result'>

export interface ErosionAssessmentCreateInput {
  window_start: string
  window_end: string
  slope_evidence?: { slope_class: string }
  rusle_factors?: Record<
    string,
    {
      value: number
      source_reference: string
      region_scope: string
      unit_convention: string
    }
  >
  observed_signs?: Array<Record<string, unknown>>
}

// --- farm resources / operations / scheduling ----------------------------------

export interface FarmResource {
  id: string
  resource_type: string
  name: string
  capacity_value: number | null
  capacity_unit: string | null
  working_width_m: number | null
  field_efficiency: number | null
  availability_calendar: Array<Record<string, unknown>>
  compatibility: Record<string, unknown>
  notes: string | null
}

export interface FarmResourceListResponse {
  farm_id: string
  items: FarmResource[]
  total: number
}

export interface FarmResourceCreateInput {
  resource_type: string
  name?: string
  capacity_value?: number | null
  capacity_unit?: string | null
  availability_calendar?: Array<{ from: string; to: string }>
  notes?: string | null
}

export interface FieldOperation {
  id: string
  field_id: string
  template_code: string | null
  operation_type: string
  title: string
  crop_label: string | null
  season_label: string | null
  earliest_start: string | null
  latest_finish: string | null
  preferred_start: string | null
  preferred_end: string | null
  duration_estimate_hours: number | null
  duration_basis: string | null
  area_ha: number | null
  resource_requirements: Record<string, unknown>
  restrictions: Record<string, unknown> | null
  priority: number
  status: string
  scheduled_start: string | null
  scheduled_end: string | null
  assigned_resource_ids: string[]
  schedule_run_id: string | null
  status_reason: string | null
  completion_date: string | null
  completed_soil_management_event_id: string | null
  template_source: Record<string, unknown> | null
}

export interface FieldOperationListResponse {
  field_id: string
  items: FieldOperation[]
  dependencies: Record<string, string[]>
  total: number
}

export interface FieldOperationPatchInput {
  status?: string
  status_reason?: string | null
  priority?: number
  completion_date?: string
  completion_notes?: string | null
  completed_soil_management_event_id?: string
}

export interface OperationTemplateSummary {
  operation_type?: string
  validation_status?: string
  [key: string]: unknown
}

export interface OperationTemplateListResponse {
  operation_templates: OperationTemplateSummary[]
  total: number
}

export interface ManagementPracticeSummary {
  practice_code: string
  name: string
  practice_family: string
  validation_status: string
  [key: string]: unknown
}

export interface ManagementPracticeListResponse {
  practices: ManagementPracticeSummary[]
  total: number
}

export interface ScheduleEntry {
  operation_id: string
  title: string | null
  status: 'scheduled' | 'unscheduled'
  scheduled_start: string | null
  scheduled_end: string | null
  assigned_resources: Record<string, string>
  weather_check?: string
  soil_readiness_check?: string
  reason: string | null
  reason_codes?: string[]
}

export interface ScheduleResult {
  solver: { status: string; [key: string]: unknown }
  entries: ScheduleEntry[]
  conflicts: Array<{ message: string; [key: string]: unknown }>
  [key: string]: unknown
}

export interface ScheduleRun {
  id: string
  field_id: string
  status: string
  label: string
  horizon: [string | null, string | null]
  engine_version: string
  methods_version: string
  result: ScheduleResult
  warnings: string[]
  not_evaluated: Record<string, string>
  request_parameters: Record<string, unknown>
  checksum_sha256: string | null
  created_at: string | null
}

// --- management plan ------------------------------------------------------------

export interface ManagementPlanCheck {
  code: string
  severity: string
  message: string
}

export interface ManagementPlanResult {
  season_context: {
    recent_crop_history: Array<{
      crop_label: string
      sowing_date: string | null
      harvest_date: string | null
      season_label: string | null
      evidence_class: string
    }>
    status: string
    message: string | null
  }
  soil_cover: {
    metrics: CoverMetrics
    thresholds: { applicable: string[]; note: string }
    window: { start: string; end: string }
  }
  cover_crop: {
    plan_items: Array<Record<string, unknown>>
    latest_plan: { id: string; created_at: string | null; candidate_statuses: Record<string, string> } | null
    status: string
    message: string | null
  }
  residue: {
    totals: Record<string, unknown>
    warnings: string[]
    status: string
    message: string | null
  }
  erosion: {
    latest_run_id?: string
    created_at?: string | null
    screening_concern_count?: number
    screening_processes?: string[]
    rusle_status?: string
    status: string
    message?: string | null
  }
  operations: {
    next_operations: Array<{
      id: string
      title: string
      operation_type: string
      status: string
      scheduled_start: string | null
      scheduled_end: string | null
      earliest_start: string | null
      latest_finish: string | null
      status_reason: string | null
    }>
    counts: Record<string, number>
    conflicts: Array<Record<string, unknown>>
    status: string
    message: string | null
  }
  practice_guidance: {
    practices: Array<{
      practice_code: string
      name: string
      practice_family: string
      validation_status: string
      mechanism_count: number
      trade_off_dimensions: string[]
    }>
    note: string
  }
  water: { latest_plan_id?: string; engine_version?: string; status: string; message?: string | null }
  checks: ManagementPlanCheck[]
}

export interface ManagementPlan {
  id: string
  field_id: string
  status: string
  label: string
  season_label: string | null
  engine_version: string
  methods_version: string
  warnings: string[]
  not_evaluated: Record<string, string>
  request_parameters: Record<string, unknown>
  knowledge_pack_refs: Array<Record<string, unknown>>
  checksum_sha256: string | null
  created_at: string | null
  result: ManagementPlanResult
}

/** List payloads return the plan WITHOUT the result block. */
export type ManagementPlanSummary = Omit<ManagementPlan, 'result'>

export interface ManagementPlanCreateInput {
  window_start?: string
  window_end?: string
  season_label?: string | null
  label?: string
  idempotency_key?: string
}

// =============================================================
// M7.3 — Scenario execution (scenario-execution.tsx)
// =============================================================

export interface ScenarioExecutionConfiguration {
  schema_version: string
  scenario_type: string
  scenario_configuration_checksum: string
  parent_field_state_id: string
  parent_snapshot_checksum: string
  boundary_version: number
  period_start: string
  period_end: string
  timezone: string
  hemisphere: string
  transformations: Array<{
    code?: string
    delta_c?: number | null
    multiplier?: number | null
    [key: string]: unknown
  }>
  resource_constraints: Record<string, unknown>
  aggregation_levels: string[]
  engine_versions: Record<string, string>
  [key: string]: unknown
}

export interface ScenarioExecutionRun {
  run_id: string
  scenario_id: string
  scenario_version: number
  field_id: string
  parent_field_state_id: string
  parent_snapshot_checksum: string | null
  scenario_configuration_checksum: string
  transformation_engine_version: string
  feature_engine_version: string
  feature_catalog_version: string
  input_fingerprint: string | null
  run_status: 'queued' | 'running' | 'succeeded' | 'completed_with_limitations' | 'failed'
  aggregation_levels: string[]
  hemisphere: string
  calendar_timezone: string
  output_checksum: string | null
  records_written: number
  transformed_observation_count: number
  derived_feature_count: number
  warnings: string[]
  not_evaluated_reasons: Record<string, string>
  resource_constraints: Record<string, unknown>
  execution_configuration: ScenarioExecutionConfiguration
  error_summary: string | null
  idempotency_key: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  evidence_note: string
}

export interface ScenarioExecutionListResponse {
  scenario_id: string
  items: ScenarioExecutionRun[]
  note: string
}

export interface ScenarioDerivedFeature {
  id: string
  execution_run_id: string
  feature_code: string
  feature_name: string | null
  unit: string
  aggregation_level: string
  period_label: string
  period_start: string | null
  period_end: string | null
  baseline_value: number | null
  scenario_value: number | null
  difference_value: number | null
  difference_percent: number | null
  feature_specification_version: string
  evidence_status: 'scenario_recalculated' | 'not_affected' | 'not_evaluated'
  quality_status: string
  coverage_ratio: number | null
  n_input: number
  n_missing: number
  uncertainty_metadata: { reason?: string | null } & Record<string, unknown>
  created_at: string | null
}

export interface ScenarioDerivedObservation {
  id: string
  execution_run_id: string
  source_observation_id: string
  dataset_product_id: string | null
  variable_code: string
  baseline_value: number | null
  transformed_value: number | null
  unit: string
  observed_at: string | null
  period_start: string | null
  period_end: string | null
  time_support: string | null
  spatial_support_type: string | null
  spatial_resolution_m: number | null
  transformation_code: string
  transformation_parameter: unknown
  evidence_class: string
  source_evidence_class: string | null
  is_synthetic: boolean
  quality_status: string
  source_metadata: Record<string, unknown>
  created_at: string | null
}

export interface ScenarioDerivedObservationListResponse {
  run_id: string
  items: ScenarioDerivedObservation[]
  count: number
  limit: number
  offset: number
  total_transformed: number
  note: string
}

export interface ScenarioDerivedFeatureListResponse {
  run_id: string
  items: ScenarioDerivedFeature[]
  count: number
}

export interface ScenarioExecutionCompareResponse {
  run_id: string
  run_status: string
  output_checksum: string | null
  summary: {
    recalculated_comparisons: number
    changed_values: number
    unchanged_values: number
    not_affected_features: number
    not_evaluated_features: number
  }
  rows: ScenarioDerivedFeature[]
  note: string
}

export interface ScenarioExecutionVerifyResponse {
  run_id: string
  run_status: string
  output_checksum_valid: boolean
  expected_output_checksum: string
  stored_output_checksum: string | null
  scenario_definition_checksum_valid: boolean
  parent_snapshot_intact: boolean
  manifest_checksum_matches_run: boolean
  verified_at: string
  note: string
}

// =============================================================
// M7.4 — Sensitivity & uncertainty (sensitivity.tsx)
// =============================================================

export interface SensitivityAnalysis {
  analysis_id: string
  source_execution_run_id: string
  scenario_id: string
  scenario_version: number
  field_id: string
  parent_field_state_id: string
  analysis_status: 'queued' | 'running' | 'succeeded' | 'completed_with_limitations' | 'failed'
  analysis_method_version: string
  response_classification_version: string
  uncertainty_registry_version: string
  transformation_engine_version: string
  feature_engine_version: string
  feature_catalog_version: string
  reference_parameter_values: Record<string, number | null>
  explorable_parameters: string[]
  parameter_design: Record<string, { lower: number; upper: number; n_points: number }>
  grid_design?: Record<string, { lower: number; upper: number; n_points: number }> | null
  analysis_fingerprint: string
  reference_reproduction: {
    reproduced: boolean
    matched_rows: number
    compared_rows: number
    observation_count_match: boolean
    [key: string]: unknown
  }
  evaluation_count: number
  evaluated_feature_count: number
  warnings: string[]
  not_analysed_features?: Record<string, string>
  output_checksum: string | null
  error_summary: string | null
  idempotency_key: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  evidence_note: string
  explorable_parameters_detail?: Record<
    string,
    { explorable: boolean; reference_value: number | null; reason: string | null }
  >
  evaluations?: Array<Record<string, unknown>>
}

export interface SensitivityAnalysisListResponse {
  run_id: string
  items: SensitivityAnalysis[]
  count: number
  note: string
}

export interface SensitivityAnalysisCreateInput {
  parameter_design: Record<string, { lower: number; upper: number; n_points: number }>
  grid?: true
  idempotency_key?: string
}

export interface SensitivityOatResponse {
  parameter_code: string
  feature_code: string
  unit: string
  aggregation_level: string
  period_label: string
  reference_value: number | null
  explored_parameter_range_envelope: {
    parameter_lower: number | null
    parameter_upper: number | null
    lower: number | null
    upper: number | null
  }
  output_range: number | null
  max_abs_difference: number | null
  difference_at_lower: number | null
  difference_at_upper: number | null
  slope: number | null
  slope_method: string
  slope_units: string
  slope_validity: string
  elasticity: { status: string; value: number | null; reason: string | null }
  direction: string
  response_classification: string
  classification_version: string
  n_evaluated_points: number
  response_status: string
  created_at: string | null
}

export interface SensitivityResponseListResponse {
  analysis_id: string
  items: SensitivityOatResponse[]
  count: number
  note: string
}

export interface SensitivityGridResponse {
  analysis_id: string
  grid_design: Record<string, { lower: number; upper: number; n_points: number }> | null
  axes: Record<string, number[]>
  cells: Array<Record<string, unknown>>
  summaries: Array<{
    feature_code: string
    unit: string
    aggregation_level: string
    period_label: string
    grid_min: number | null
    grid_max: number | null
    grid_output_range: number | null
    direction: string
    non_monotonic: boolean
    threshold_transition_count: number
    interaction_contrast: number | null
    interaction_interpretation: string
    variable_families: string[]
  }>
  count: number
  note: string
}

export interface SensitivityUncertaintyResponse {
  registry_version: string
  items: Array<{
    category: string
    code: string
    description: string
    evidence_source: string
    quantification_status: string
    quantification_method: string | null
    quantified_value: number | null
    affects_current_analysis: boolean
    affected_inputs: string[]
    affected_features: string[]
    applicability: string
    user_facing_explanation: string
  }>
  count: number
  note: string
}

export interface SensitivityVerifyResponse {
  analysis_id: string
  analysis_status: string
  output_checksum_valid: boolean
  expected_output_checksum: string
  stored_output_checksum: string | null
  source_run_intact: boolean
  parent_snapshot_intact: boolean
  manifest_checksum_matches: boolean
  reference_reproduction_consistent: boolean
  verified_at: string
  note: string
}

// =============================================================
// M7.5 — Robust rotation (robust-plan.tsx)
// =============================================================

export interface ScenarioSet {
  id: string
  field_id: string
  label: string
  description: string | null
  parent_field_state_id: string
  parent_snapshot_checksum: string
  members: Array<Record<string, unknown>>
  member_count: number
  compatibility_report: Record<string, unknown> | null
  set_checksum: string
  status: string
  created_at: string | null
}

export interface ScenarioSetListResponse {
  field_id: string
  items: ScenarioSet[]
  count: number
  note: string
}

export interface ScenarioSetCreateInput {
  label: string
  execution_run_ids: string[]
  description?: string
  idempotency_key?: string
}

export interface ScenarioSetVerifyResponse {
  scenario_set_id: string
  set_checksum: string
  verified_members: number
  drift: unknown
  findings: Array<Record<string, unknown>>
  usable_for_robust_runs: boolean
  note: string
}

export interface RobustStrategy {
  id: string
  run_id: string
  strategy_key: string
  strategy_kind: string
  is_baseline: boolean
  profile_weights: Record<string, number>
  assignment: Array<{ season_label: string; crop_code: string | null }>
  worst_case_objective: number | null
  worst_case_regret: number | null
  robust_feasibility: 'robust_feasible' | 'robust_infeasible' | 'not_evaluable'
  objective_evaluable_in_all_scenarios: boolean
  solver_status: string | null
  solver_wall_time_ms: number | null
  checksum_sha256: string | null
}

export interface RobustScenarioEvaluation {
  id: string
  run_id: string
  strategy_id: string
  scenario_id: string
  execution_run_id: string
  output_checksum_pin: string | null
  weighted_objective: number | null
  objective_evaluable: boolean
  on_scenario_pareto_front: boolean
  regret_vs_solo: number | null
  criteria: Array<Record<string, unknown>>
  constraint_checks: Array<Record<string, unknown>>
  crop_admissibility: Array<{
    season_label: string
    crop_code: string
    status: string
    admissible: boolean
    hard_reason: string | null
  }>
  climate_evidence: Record<
    string,
    {
      basis: string
      coverage_ratio: number | null
      season_precipitation_mm: number | null
      season_mean_temp_degC: number | null
      season_hot_days_35c: number | null
      season_et0_mm: number | null
      warnings: string[]
    }
  >
}

export interface RobustRotationRun {
  id: string
  field_id: string
  scenario_set_id: string
  scenario_set_checksum: string
  member_count: number
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  strategy_profiles: string[]
  regret_analysis: boolean
  run_status: 'queued' | 'running' | 'succeeded' | 'failed' | 'infeasible'
  solver_status: string | null
  robust_engine_version: string
  robust_method_version: string
  rotation_engine_version: string
  solver_name: string
  solver_version: string
  random_seed: number
  output_checksum: string | null
  warnings: string[]
  not_evaluated: Record<string, Record<string, string>>
  infeasibility_details: {
    cross_scenario_exclusions?: Array<{
      crop_code: string
      season_label: string
      excluded_by_scenarios: Array<{ reason: string; [key: string]: unknown }>
    }>
    [key: string]: unknown
  } | null
  error_summary: string | null
  started_at: string | null
  completed_at: string | null
  strategies?: RobustStrategy[]
}

export interface RobustRunListResponse {
  scenario_set_id: string
  items: RobustRotationRun[]
  count: number
  note: string
}

export interface RobustRunCreateInput {
  seasons: Array<{ label: string; start_date: string; end_date: string }>
  hemisphere: string
  regret_analysis?: boolean
  strategy_profiles?: string[]
  idempotency_key?: string
}

export interface RobustEvaluationListResponse {
  run_id: string
  items: RobustScenarioEvaluation[]
  count: number
  note: string
}

export interface RobustVerifyResponse {
  run_id: string
  verified: boolean
  member_check: Record<string, unknown>
  strategy_count: number
  findings: Array<Record<string, unknown>>
  note: string
}

// =============================================================
// M7.6 — Decision intelligence (decisions.tsx)
// =============================================================

export interface DecisionComparisonScope {
  executions: Array<{
    execution_run_id: string
    scenario_id: string
    scenario: string
    scenario_version: number
    output_checksum: string | null
    run_status: string
  }>
  robust_runs: Array<{
    robust_run_id: string
    solver_status: string | null
    output_checksum: string | null
    member_count: number
  }>
  sensitivity_analyses: Array<{
    analysis_id: string
    source_execution_run_id: string
    output_checksum: string | null
  }>
}

export interface DecisionBaselineChange {
  execution_run_id: string
  scenario: string
  feature_code: string
  unit: string
  aggregation_level: string
  period_label: string
  baseline_value: number | null
  scenario_value: number | null
  difference_value: number | null
  difference_percent: number | null
  evidence_status: string
  abs_percent: number
}

export interface DecisionDocument {
  generator_version: string
  method_version: string
  field_id: string
  title: string
  scope: DecisionComparisonScope
  baseline_vs_scenario: {
    per_execution: Array<Record<string, unknown>>
    largest_changes: DecisionBaselineChange[]
    ranking_note: string
  }
  scenario_pairs: { pairs: Array<Record<string, unknown>>; note: string }
  sensitivity_interpretation: { analyses: Array<Record<string, unknown>> }
  rotation_decisions: {
    runs: Array<{
      robust_run_id: string
      run_status: string
      solver_status: string | null
      robust_method_version: string
      scenario_set_id: string
      seasons: Array<{ label: string; start_date: string; end_date: string }>
      member_count: number
      plans: Array<{
        strategy_key: string
        strategy_kind: string
        is_baseline: boolean
        assignment: Array<{ season_label: string; crop_code: string | null }>
        worst_case_objective: number | null
        worst_case_regret: number | null
        robust_feasibility: string
        solver_status: string | null
        per_scenario: Array<Record<string, unknown>>
      }>
      not_evaluated: Record<string, Record<string, string>>
    }>
  }
  tradeoffs: {
    robust_run_id: string | null
    matrix: Array<{
      plan: string
      scenario_id: string
      criterion_code: string
      raw_value: number | null
      unit: string | null
      direction: string | null
      evaluable: boolean
      missing_evidence: string[]
    }>
    note: string
  }
  missing_evidence: {
    items: Array<{ kind: string; source: string; code: string; detail: string }>
    count: number
  }
  findings: Array<{
    kind: string
    text: string
    evidence: Array<Record<string, unknown>>
  }>
  not_available: Record<string, string>
  honesty_note: string
}

/** List/create payload (document body only included on detail endpoints). */
export interface DecisionComparisonSummary {
  id: string
  field_id: string
  title: string
  doc_status: string
  fingerprint: string
  document_checksum: string
  scope: DecisionComparisonScope
  warnings: string[]
  not_available: Record<string, string>
  created_at: string | null
  document?: DecisionDocument
}

export interface DecisionComparisonListResponse {
  field_id: string
  items: DecisionComparisonSummary[]
  count: number
  note: string
}

export interface DecisionComparisonCreateInput {
  title?: string
}

export interface DecisionVerifyResponse {
  id: string
  verified: boolean
  findings: Array<Record<string, unknown>>
  document_checksum: string
  note: string
}

// =============================================================
// M7.7 — Digital twin (digital-twin.tsx)
// =============================================================

export interface TwinFieldIdentity {
  field_id: string
  field_name: string
  area_ha: number | null
  farm_id: string
  farm_name: string | null
  country_code: string | null
  latest_boundary_version: number | null
  note: string
}

export interface DigitalTwinView {
  view_version: string
  generated_at: string
  field_identity: TwinFieldIdentity
  field_states: {
    total: number
    items: Array<Record<string, unknown>>
    note: string
  }
  observation_coverage: {
    variables: Array<{
      variable_code: string
      observation_count: number
      first_observed_at: string | null
      last_observed_at: string | null
      freshness_days: number | null
    }>
    note: string
  }
  feature_runs: Array<Record<string, unknown>>
  scenarios: Array<{
    scenario_id: string
    name: string
    scenario_type: string
    evidence_classification: string
    scenario_status: string
    scenario_version: number
    lineage_kind: string
    parent_scenario_id: string | null
    configuration_checksum: string
    period: { start: string; end: string }
    executions: Array<{
      execution_run_id: string
      run_status: string
      output_checksum: string | null
      input_fingerprint: string | null
    }>
  }>
  sensitivity_analyses: Array<{
    source_execution_run_id: string
    analysis_count: number
  }>
  robust_rotation: {
    scenario_sets: Array<{
      scenario_set_id: string
      label: string
      set_checksum: string
      member_count: number
      robust_runs: Array<{
        robust_run_id: string
        run_status: string
        solver_status: string | null
        output_checksum: string | null
      }>
    }>
  }
  decision_documents: Array<{
    decision_comparison_id: string
    title: string
    doc_status: string
    document_checksum: string
  }>
  information_classes: {
    observed_observations: number
    scenario_derived_transformed_observations: number
    calculated_feature_values: number
    note: string
  }
  capabilities: Array<{
    capability: string
    milestone: string
    implemented: boolean
    data_ready: boolean
    readiness: 'ready' | 'prerequisite_missing' | 'not_implemented'
    prerequisite: string | null
  }>
  maturity: {
    classification: string
    implemented_capabilities: string[]
    capabilities_with_data: string[]
    not_implemented: string[]
    note: string
  }
  prohibitions_note: string
}

export interface TwinValidationResponse {
  id: string
  field_id: string
  overall_status: 'consistent' | 'inconsistent' | 'no_artifacts'
  artifacts_checked: number
  artifacts_failed: number
  report_checksum: string
  report: {
    validation_version: string
    field_id: string
    overall_status: string
    artifact_checks: Array<{
      artifact: string
      artifact_id: string
      verified: boolean
      findings: string[]
    }>
    summary: { total_checked: number; verified: number; failed: number }
    bounds_note: string
    started_at: string
    completed_at: string
  }
  started_at: string | null
  completed_at: string | null
  created_at: string | null
}

export interface TwinValidationListResponse {
  field_id: string
  items: TwinValidationResponse[]
  count: number
  note: string
}

// =============================================================
// AI Insights — recommendations, field insights, advisor (ai-insights.tsx)
// =============================================================

export type RecommendationSeverity = 'info' | 'advisory' | 'recommended' | 'required'

export type RecommendationDomain =
  | 'climate'
  | 'vegetation' // P2 backend contract (app/recommendations/contracts.py DOMAINS) — frontend label added in P03 W2
  | 'water'
  | 'soil'
  | 'rotation'
  | 'management'

export interface AiEngineInfo {
  mode: string
  model: string | null
  /** A6: structured | text (advisor responses). */
  response_format?: string
  rejected_citations?: string[]
  numeric_validation?: { unsupported_count: number; supported_count: number }
  limitations?: string[]
  uncertainty_notes?: string[]
  follow_up_suggestions?: string[]
}

export interface RecommendationEvidence {
  type: string
  id: string
  label: string
  detail: string | null
}

/** A5: honest confidence semantics — the value's basis kind. */
export type ConfidenceKind = 'deterministic_rule' | 'evidence_quality'

/** A5: component-wise evidence-quality report attached to recommendations. */
export interface EvidenceQuality {
  score: number | null
  components: Record<string, { value: number | null; basis: string }>
  summary: string
}

/** A12: feedback lifecycle states (latest transition per recommendation). */
export type FeedbackState =
  | 'pending'
  | 'accepted'
  | 'dismissed'
  | 'implemented'
  | 'not_applicable'
  | 'deferred'

export interface Recommendation {
  id: string
  domain: RecommendationDomain
  severity: RecommendationSeverity
  title: string
  summary: string
  rationale: string | null
  evidence: RecommendationEvidence[]
  actions: string[]
  confidence: number | null
  confidence_kind: ConfidenceKind | null
  confidence_basis: string | null
  evidence_quality: EvidenceQuality | null
  generator: string | null
  status: string
  generated_by: string
  created_at: string
  narrative: string | null
  /** A4: stable material fingerprint (SHA-256 hex) — informational. */
  fingerprint?: string | null
  /** A12: latest feedback state (None = no feedback recorded yet). */
  feedback_state: FeedbackState | null
}

export interface RecommendationsResponse {
  field_id: string
  generated_at: string
  engine: AiEngineInfo
  domains: RecommendationDomain[]
  counts: {
    total: number
    by_severity: Partial<Record<RecommendationSeverity, number>>
  }
  recommendations: Recommendation[]
  /** A3: narrative cache outcome of the last refresh (hit | miss | null). */
  narrative_cache?: 'hit' | 'miss' | null
}

export interface FieldInsightItem {
  kind: string
  title: string
  detail: string
  metric: string | null
  value: number | null
  baseline_mean: number | null
  z: number | null
  direction: 'above' | 'below' | 'flat' | null
  severity: RecommendationSeverity
  /** A1: same-month baseline provenance (monthly findings only). */
  baseline?: {
    calendar_month: number
    window_years: number[]
    n_years: number
    mean: number
    sd: number
    class: string
    includes_evaluated_period: boolean
  } | null
}

export interface FieldInsightsResponse {
  field_id: string
  insights: FieldInsightItem[]
  summary: string | null
  engine: AiEngineInfo
}

export interface AdvisorEvidence {
  type: string
  id: string
  label: string
  detail?: string | null
}

export interface AdvisorQueryResponse {
  field_id: string
  /** A8: stable advisor session id (reuse for multi-turn context). */
  session_id: string
  question: string
  answer: string
  evidence_used: AdvisorEvidence[]
  engine: AiEngineInfo
  disclaimer: string
  created_at: string
}

export interface AdvisorHistoryMessage {
  role: 'user' | 'assistant'
  question: string | null
  answer: string | null
  session_id: string | null
  created_at: string
}

export interface AdvisorHistoryResponse {
  session_id: string | null
  messages: AdvisorHistoryMessage[]
}

// -------------------------------------------------------------
// A12: recommendation feedback
// -------------------------------------------------------------

export interface FeedbackTransitionResponse {
  id: string
  recommendation_id: string
  state: FeedbackState
  reason: string | null
  outcome: string | null
  created_at: string
}

export interface FeedbackHistoryResponse {
  recommendation_id: string
  state: FeedbackState
  history: Array<{
    id: string
    state: FeedbackState
    reason: string | null
    outcome: string | null
    user_id: string
    created_at: string
  }>
}

// -------------------------------------------------------------
// P2 — Satellite / Climate / Soil Memory / Failure Lab / Evidence / Portfolio
// -------------------------------------------------------------

export interface VegetationSummary {
  field_id: string
  index: string
  formula: string
  series_state: { state: string; detail: string; can_assess: boolean; years?: number[] }
  monthly_stats: Array<{ year: number; month: number; mean: number; n_valid: number; n_excluded_cloud: number }>
  findings: Array<Record<string, unknown>>
  stress_signals: Array<{
    index: string
    observed_change: Record<string, unknown>
    possible_context: Array<{ factor: string; detail?: string; [k: string]: unknown }>
    not_supported: string[]
    severity: string
  }>
  data_gaps: string[]
  observation_counts: { total: number; valid: number; missing_or_cloudy: number; cloud_excluded_from_stats: number }
  scenes: Array<{
    observed_at: string | null
    value: number | null
    quality_status: string | null
    cloud_cover_pct: number | null
    scene_id: string | null
    spatial_resolution_m: number | null
    platform: string | null
  }>
  dormancy_months_hint: number[] | null
  limitations: string[]
  generated_at: string
}

export interface SatelliteScenesResponse {
  field_id: string
  total: number
  limit: number
  offset: number
  scenes: Array<{
    id: string
    provider_code: string
    product_code: string
    scene_id: string
    acquired_at: string | null
    cloud_cover_pct: number | null
    spatial_resolution_m: number | null
    coverage_fraction: number | null
    is_synthetic: boolean
    asset_refs: Record<string, unknown> | null
  }>
}

// ------------------------------------------------------------- P04 satellite acquisition

/** Lifecycle status of a discovered/acquired satellite scene. */
export type SatelliteSceneStatus = 'discovered' | 'queued' | 'running' | 'ready' | 'failed'

export interface SatelliteCatalogScene {
  id: string
  provider_code: string
  product_code: string
  scene_id: string
  acquired_at: string | null
  cloud_cover_pct: number | null
  spatial_resolution_m: number | null
  platform: string | null
  coverage_fraction: number | null
  acquisition_status: SatelliteSceneStatus
  acquisition_detail: Record<string, unknown>
  is_synthetic: boolean
  processing_version: string | null
  asset_refs: Record<string, unknown> | null
  band_mapping: Record<string, string> | null
  discovered_at: string | null
  acquisition_updated_at: string | null
  created_at: string | null
}

export interface SatelliteCatalogResponse {
  field_id: string
  total: number
  limit: number
  offset: number
  scenes: SatelliteCatalogScene[]
}

export interface SatelliteDiscoveryInput {
  start_date: string
  end_date: string
  max_cloud_cover?: number | null
  limit?: number
}

export interface SatelliteDiscoveryResponse {
  field_id: string
  provider_code: string
  catalog: { base_url: string; collections: string[]; products: string[] }
  discovered: number
  new: number
  unchanged: number
  scenes: SatelliteCatalogScene[]
  warnings: string[]
}

export interface SatelliteAcquisitionInput {
  scene_ids: string[]
  variables: string[]
}

export interface SatelliteAcquisitionResponse {
  field_id: string
  provider_code: string
  jobs: Array<{
    job_id: string
    provider_code: string
    product_code: string
    status: string
    scene_ids: string[]
    status_url: string
    replayed?: boolean
  }>
  queued_scenes: string[]
  warnings: string[]
}

export interface SatelliteJobCancelResponse {
  job_id: string
  status: string
  scenes_released: string[]
}

export interface ClimateCapabilities {
  capability_matrix: Array<{
    provider_code: string
    products: string[]
    forecast_class: string
    temporal_horizon: string
    spatial_resolution_m: number | null
    update_frequency: string
    variables: string[]
    licensing: string
    authentication: string
    known_limitations: string
    status?: string
  }>
  classification_vocabulary: string[]
}

export interface ForecastFreshness {
  variable_code: string
  latest_issued_at: string | null
  age_hours: number | null
  max_age_hours: number
  fresh: boolean
  detail: string
}

export interface ForecastWindowResponse {
  field_id: string
  variable_code: string
  basis: string
  freshness: ForecastFreshness
  window: { start: string; end: string }
  values: Array<{
    valid_time: string
    issued_at: string
    horizon_hours: number
    value: number | null
    unit: string
    model_id: string | null
    is_synthetic: boolean
  }>
}

export interface ForecastRiskItem {
  risk_code: string
  severity: string
  title: string
  detail: string
  window_start: string | null
  window_end: string | null
  threshold: string
  threshold_source: string
  affected_days: number
  forecast_days_total: number
  basis: string
  crop_context: string | null
}

export interface ForecastRisksResponse {
  field_id: string
  basis: string
  window: { start: string; end: string }
  risks: ForecastRiskItem[]
  limitations: string[]
}

export interface ForecastVerificationResponse {
  verifications: Array<{ variable_code: string; horizon_bucket_hours: string; pair_count: number; bias: number | null; mae: number | null; rmse: number | null }>
  pairs_total: number
  persisted: number
  limitations: string[]
}

export interface ProjectionsResponse {
  field_id: string
  records: Array<Record<string, unknown>>
  adapter_status: string
  note: string
}

export interface SoilMemorySnapshot {
  id: string
  field_id: string
  as_of: string
  checksum_sha256: string
  missing_evidence: string[]
  variable_count: number
  engine_version: string
  created_at: string | null
}

export interface SoilSnapshotDetail extends SoilMemorySnapshot {
  snapshot: {
    variables: Array<{
      variable_code: string
      value: number | null
      unit: string
      top_depth_cm: number | null
      bottom_depth_cm: number | null
      evidence_class: string
      source_kind: string
      observed_at: string
    }>
    management_events: Array<Record<string, unknown>>
    crop_history: Array<Record<string, unknown>>
  }
  source_refs: Array<Record<string, unknown>>
  alerts: SoilAlert[]
}

export interface SoilAlert {
  code: string
  severity: string
  title: string
  detail: string
  basis: string
}

export interface SoilTimelineResponse {
  field_id: string
  events: Array<{ kind: string; date: string; [k: string]: unknown }>
  snapshots: SoilMemorySnapshot[]
  engine_version: string
  note: string
}

export interface SoilChangeEstimateResponse {
  id: string
  method: string
  model_version: string
  result: {
    soc_trajectory: { value: number | null; unit?: string; window?: { years?: number }; not_evaluated?: string; estimated?: boolean }
    window: { start: string; end: string }
    estimated: boolean
    note: string
  }
  assumptions: string[]
  uncertainty: Record<string, unknown> | null
  checksum_sha256: string
  alerts: SoilAlert[]
}

export interface StressPack {
  code: string
  label: string
  kind: string
  parameters: Record<string, number>
  assumption_note: string
  provenance: Record<string, unknown>
}

export interface RotationStressRun {
  id: string
  field_id: string
  status: 'running' | 'succeeded' | 'failed'
  request_parameters: Record<string, unknown>
  result: {
    evaluations: Array<{
      candidate_key: string
      pack_code: string
      feasible: boolean | null
      assignment?: Array<{ season_label: string; crop_code: string | null }>
      constraint_violations?: Array<Record<string, unknown>>
      explanations?: Array<Record<string, unknown>>
      criteria?: Record<string, unknown>
    }>
    robustness?: Record<string, { worst_case_score?: { value: number | null }; mean_score?: { value: number | null }; score_variance?: { value: number | null }; downside_risk?: { value: number | null }; feasibility_rate?: { value: number | null }; worst_case_regret?: { value: number | null }; [k: string]: unknown }>
    [k: string]: unknown
  } | null
  warnings: unknown[]
  not_evaluated: Array<{ code: string; reason: string }>
  checksum_sha256: string | null
  created_at: string | null
}

export interface EvidenceGap {
  gap_code: string
  importance: string
  affected_decisions: string[]
  required_evidence: string
  current_status: string
  freshness_requirement: string
  spatial_relevance: string
  potential_impact: string
  how_to_obtain: string
  urgent: boolean
  urgency: string
  collection_cost: { category: string; effort: string }
  decision_sensitivity: { level: string; detail: string }
  voi: {
    decision_sensitivity: { level: string; detail: string }
    expected_ranking_change: string[]
    honesty_note: string
  }
}

export interface EvidenceGapsResponse {
  field_id: string
  gaps: EvidenceGap[]
  completeness: { domains_ready: string[]; domains_with_gaps: string[]; critical_missing: string[]; gap_count: number }
  acquisition_plans: Array<{
    gap_code: string
    action_type: string
    title: string
    what_is_missing: string
    why_it_matters: string
    affected_decisions: string[]
    how_to_obtain: string
    urgent: boolean
    uncertainty_reduced: string | null
    collection_cost: { category: string; effort: string }
  }>
  checksum_sha256?: string
}

export interface EvidenceAction {
  id: string
  field_id: string
  gap_code: string
  action_type: string
  title: string
  status: 'suggested' | 'in_progress' | 'submitted' | 'resolved' | 'dismissed'
  submitted_ref_kind: string | null
  submitted_ref_id: string | null
  created_at: string | null
  resolved_at: string | null
  events?: Array<{ id: string; from_status: string | null; to_status: string; note: string | null; created_at: string | null }>
}

export interface EvidenceApplyReport {
  field_id: string
  evidence_ref: { kind: string; id: string | null; detail: string }
  resolved_action_id: string | null
  recomputed: Array<{ artifact: string; action: string; detail?: string; counts?: Record<string, unknown> }>
  changed_recommendation_fingerprints: string[]
  changed_count: number
  note: string
}

export interface StalenessReport {
  domains: Record<
    string,
    {
      latest_evidence_at: string | null
      downstream: Record<string, { artifact_updated_at: string | null; stale: boolean; status: string }>
    }
  >
}

export interface PortfolioConstraintsInfo {
  engine_version: string
  objective_keys: string[]
  objective_modes: string[]
  constraint_keys: string[]
  disclosures: string[]
}

export interface PortfolioRun {
  id: string
  farm_id: string
  status: 'running' | 'succeeded' | 'failed'
  request_parameters: Record<string, unknown>
  result: {
    status?: string
    objective_value?: number | null
    per_criterion_scores?: Record<string, { value: number | null; unit?: string; not_evaluated?: string; basis?: string }>
    binding_constraints?: Array<{ name: string; limit?: number; used?: number; slack?: number; unit?: string; [k: string]: unknown }>
    conflicts?: Array<Record<string, unknown>>
    independent_comparison?: {
      comparisons: Array<{ criterion: string; portfolio_value: number | null; independent_value: number | null; unit: string | null; verdict: string; detail: string }>
      explanations: string[]
    }
    scenario_evaluation?: { verdict: string; detail: string; allocation_deltas: Array<Record<string, unknown>>; [k: string]: unknown }
    weight_shares?: Record<string, number>
    notes?: string[]
    [k: string]: unknown
  } | null
  field_ids: string[]
  objective_weights: Record<string, number> | null
  scenario: Record<string, unknown> | null
  engine_version: string
  warnings: unknown[]
  not_evaluated: Array<{ code: string; reason: string }>
  checksum_sha256: string | null
  created_at: string | null
  allocations: Array<{
    field_id: string
    season_label: string
    season_index: number
    crop_code: string
    area_ha: number
    family_key: string | null
    status: string
  }>
}

// -------------------------------------------------------------
// P05/P06 — satellite derived products, processing ledger, field profile
// -------------------------------------------------------------

/** Server-side derivation state of an acquired scene (processing endpoint). */
export type SatelliteProcessingState = 'unprocessed' | 'processing' | 'processed' | 'failed'

/**
 * processing_detail is state-dependent (live-verified against the P05 API):
 *   - processing: { job_ids, indices, stage, progress }
 *   - failed:     { job_id, error }
 *   - processed / unprocessed: null
 */
export interface SatelliteProcessingDetail {
  job_ids?: string[]
  job_id?: string
  indices?: string[]
  stage?: string
  progress?: number
  error?: string
}

/** Zonal statistics block attached to a derived index raster. */
export interface SatelliteZonalStats {
  mean: number
  std: number
  p5: number
  p25?: number
  p75?: number
  p95: number
  median?: number
  valid_pixels: number
  masked_pixels?: number
  coverage_fraction: number
  flags: string[]
  index?: string
  version?: string
}

/** One tercile partition row (value_terciles_rank method). */
export interface SatelliteZonePartition {
  zone: string
  value_range: [number, number]
  pixel_share: number
  mean: number
}

export interface SatelliteZoneSummary {
  method: string
  description?: string
  version?: string
  valid_pixels?: number
  zones: SatelliteZonePartition[]
}

/** One derived index raster (P05) attached to a processed scene. */
export interface SatelliteDerivedProduct {
  index_code: string
  asset_id: string
  valid_pixel_fraction: number
  zonal: SatelliteZonalStats
  zone_summary: SatelliteZoneSummary | null
  preview_asset_id: string | null
  crs: string
  /** [minLon, minLat, maxLon, maxLat] — null when the scene has no WGS84 footprint. */
  bbox_wgs84: [number, number, number, number] | null
  spatial_resolution_m: number
  processing_version: string
  derived_at: string
}

export interface SatelliteProcessingScene {
  scene_id: string
  product_code: string
  provider_code: string
  is_synthetic: boolean
  acquired_at: string
  cloud_cover_pct: number | null
  acquisition_status: SatelliteSceneStatus
  processing_state: SatelliteProcessingState
  processing_detail: SatelliteProcessingDetail | null
  processing_version: string | null
  products: SatelliteDerivedProduct[]
}

export interface SatelliteProcessingResponse {
  field_id: string
  processing_version: string
  total: number
  scenes: SatelliteProcessingScene[]
}

export interface SatelliteProcessingInput {
  scene_ids: string[]
  /** Allowed: ndvi, evi, savi, ndmi, ndwi, bsi. */
  indices: string[]
}

export interface SatelliteProcessingJob {
  job_id: string
  background_job_id: string | null
  scene_id: string
  status: string
  status_url: string
  replayed?: boolean
}

/** 202 response of POST /fields/{id}/satellite/processing. */
export interface SatelliteProcessingJobResponse {
  field_id: string
  provider_code: string
  indices: string[]
  processing_version: string
  jobs: SatelliteProcessingJob[]
  skipped: Array<{ scene_id: string; reason: string }>
  queued_scenes: number
  warnings: string[]
}

export interface SatelliteProcessingCancelResponse {
  cancelled: boolean
  job_id?: string | null
  detail?: string | null
}

/** One timeline/observation entry of the field satellite profile (P06). */
export interface SatelliteProfileObservation {
  observed_at: string
  value: number
  quality_status: string
  processing_version: string | null
  scene_id: string | null
  cloud_cover_pct: number | null
  valid_pixel_fraction: number | null
  valid_pixels: number | null
  subfield_statistics_ok: boolean | null
  spatial_resolution_m: number | null
  evidence_class: string | null
  is_synthetic: boolean | null
}

export interface SatelliteProfileGap {
  from: string
  to: string
  days: number
  note: string | null
}

export interface SatelliteProfileCoverage {
  first_scene_acquired: string | null
  last_scene_acquired: string | null
  scene_records: number
  gaps: SatelliteProfileGap[]
  gaps_note: string | null
  expected_revisit_note: string | null
}

export interface SatelliteProfileQualitySummary {
  valid_observations: number
  excluded_no_value: number
  total_scene_records: number
  avg_valid_pixel_fraction: number | null
  min_valid_pixel_fraction: number | null
  freshness_days_since_last: number | null
  fresh: boolean
  freshness_window_days: number
}

export interface SatelliteProfileBaseline {
  kind: string
  count: number
  mean: number
  std: number | null
  min: number | null
  max: number | null
}

export interface SatelliteProfileComparison {
  latest_value: number
  delta_vs_baseline_mean: number | null
  z_score_vs_baseline: number | null
  uncertainty_note: string | null
  weak_evidence: boolean
}

export interface SatelliteProfileTrend {
  slope_per_day: number
  slope_per_30d: number
  points: number
  method: string
}

export interface SatelliteSpatialVariation {
  std: number
  p5: number
  p25: number
  p75: number
  p95: number
  valid_pixels: number
  coverage_fraction: number
  supports_subfield_claims: boolean
}

export interface SatelliteDerivedAssetRecord {
  asset_id: string
  scene_id: string
  processing_version: string
  acquired_at: string
  storage_backend: string
  valid_pixel_fraction: number
  checksum_sha256: string
}

export interface SatelliteInsufficientEvidence {
  status: 'insufficient_evidence'
  reasons: string[]
  note: string | null
}

/** GET /fields/{id}/satellite/profile?index=… — evidence-bounded temporal profile. */
export interface SatelliteProfileResponse {
  profile_version: string
  field_id: string
  index: string
  index_formula: string
  documented_range: [number, number]
  interpretation_levels: Record<string, string>
  latest_valid_observation: SatelliteProfileObservation | null
  timeline: SatelliteProfileObservation[]
  excluded_observations: SatelliteProfileObservation[]
  coverage: SatelliteProfileCoverage
  quality_summary: SatelliteProfileQualitySummary
  baseline: SatelliteProfileBaseline | null
  comparison: SatelliteProfileComparison | null
  trend: SatelliteProfileTrend | null
  spatial_variation: SatelliteSpatialVariation | null
  statistical_zones: SatelliteZoneSummary | null
  derived_assets: SatelliteDerivedAssetRecord[]
  insufficient_evidence: SatelliteInsufficientEvidence | null
}

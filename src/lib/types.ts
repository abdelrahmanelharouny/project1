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
  methods: Record<string, unknown>
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

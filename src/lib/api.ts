/**
 * Typed fetch wrapper for the FieldShift API.
 *
 * Gateway rule: every request goes to a RELATIVE path and carries the
 * `XTransformPort=3030` query parameter so the Caddy gateway forwards it to
 * the FastAPI mini-service. Absolute URLs are never used.
 */
import type {
  AdvisorEvidence,
  AdvisorHistoryResponse,
  AdvisorQueryResponse,
  AiEngineInfo,
  ApiErrorBody,
  ApiErrorDetail,
  AuthSession,
  BoundaryVersionCreateResponse,
  BoundaryVersionListResponse,
  CatalogResponse,
  DataCoverageResponse,
  DataJob,
  DataJobCreateInput,
  DataPassport,
  DemoSession,
  Farm,
  FarmCreateInput,
  FarmListResponse,
  FarmPatchInput,
  FeatureCatalogResponse,
  FeatureRun,
  FeatureRunComparison,
  FeatureRunCreateInput,
  FeatureRunListResponse,
  FeatureValueListResponse,
  Field,
  FieldCreateInput,
  FieldCreateResponse,
  FieldInsightsResponse,
  FieldListResponse,
  FieldMapResponse,
  FieldPatchInput,
  HealthReadyResponse,
  HealthResponse,
  LoginInput,
  MeResponse,
  ObservationListResponse,
  ProvidersHealthResponse,
  RecommendationsResponse,
  RegisterInput,
  FieldState,
  FieldStateCreateInput,
  FieldStateListResponse,
  FieldStateVerifyResponse,
  FieldStateCompareResponse,
  Scenario,
  ScenarioCapabilities,
  ScenarioCompareResponse,
  ScenarioCreateInput,
  ScenarioLineageResponse,
  ScenarioListResponse,
  ScenarioTaxonomy,
  ScenarioValidateResponse,
  ScenarioVerifyResponse,
  ScenarioVersionsResponse,
  ObservationManifest,
} from './types'

/**
 * P1 server-side sessions: the access and refresh tokens live in HttpOnly
 * cookies set by the Next.js /api/auth/* route handlers. JavaScript never
 * sees the token material — fetch() sends the cookies automatically for
 * same-origin /api/v1 requests (forwarded to the backend through the
 * gateway / rewrite), and the backend accepts the fs_token cookie as a
 * bearer credential.
 */
const PORT_QUERY = 'XTransformPort=3030'
/** Next.js route handlers that own the session cookies (no XTransformPort —
 * these are handled by Next itself, NOT the backend gateway). */
const AUTH_BASE = '/api/auth'

/** Coverage window enforced by the backend for ingestion jobs. */
export const COVERAGE_START = '2015-01-01'
export const COVERAGE_END = '2024-12-31'
/** Maximum span of a single ingestion job. */
export const MAX_JOB_YEARS = 4

/** Thrown for any non-2xx API response; carries the parsed error envelope. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ApiErrorDetail[]
  readonly requestId: string | undefined

  constructor(params: {
    status: number
    code: string
    message: string
    details?: ApiErrorDetail[]
    requestId?: string
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.status = params.status
    this.code = params.code
    this.details = params.details ?? []
    this.requestId = params.requestId
  }
}

/** Human-readable summary of any thrown error for toasts. */
export function describeError(err: unknown): { title: string; description?: string } {
  if (err instanceof ApiError) {
    const firstDetail = err.details[0]
    const description = firstDetail
      ? `${firstDetail.field}: ${firstDetail.reason}${err.requestId ? ` · request ${err.requestId.slice(0, 8)}` : ''}`
      : err.requestId
        ? `request ${err.requestId.slice(0, 8)}`
        : undefined
    return { title: err.message, description }
  }
  if (err instanceof Error) {
    return { title: 'Network error', description: err.message }
  }
  return { title: 'Unexpected error' }
}

function withPort(path: string): string {
  const joiner = path.includes('?') ? '&' : '?'
  return `${path}${joiner}${PORT_QUERY}`
}

/**
 * Exchange the HttpOnly refresh cookie for a fresh access+refresh cookie pair
 * (rotating refresh: the presented token is revoked server-side; reusing a
 * superseded token revokes the whole session family).
 *
 * Single-flight: several concurrent 401s share ONE rotation call — parallel
 * rotations would present already-rotated tokens and revoke the family.
 */
let refreshInFlight: Promise<boolean> | null = null

export async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = authRequest('/refresh')
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

/** POST to a Next.js /api/auth/* route handler (session cookies live here). */
async function authRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${AUTH_BASE}${path}`, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  })
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null
    const error =
      envelope && typeof envelope === 'object' && 'error' in envelope ? envelope.error : undefined
    throw new ApiError({
      status: response.status,
      code: error?.code ?? `HTTP_${response.status}`,
      message: error?.message ?? `Request failed with status ${response.status}.`,
      details: error?.details ?? [],
      requestId: error?.request_id,
    })
  }
  return payload as T
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Multipart form body (file uploads). Content-Type is set by the browser. */
  formData?: FormData
  /** Skip the 401→refresh retry (health checks, anonymous endpoints). */
  anonymous?: boolean
}

interface RequestInternals {
  /** Prevent recursive 401→refresh retries (used by refreshSession itself). */
  skipAuthRetry?: boolean
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  internals: RequestInternals = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(withPort(path), {
      method: options.method ?? 'GET',
      headers,
      body:
        options.formData !== undefined
          ? options.formData
          : options.body !== undefined
            ? JSON.stringify(options.body)
            : undefined,
      cache: 'no-store',
    })
  } catch (err) {
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the FieldShift API.',
      details: [],
    })
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null
    const error = envelope && typeof envelope === 'object' && 'error' in envelope ? envelope.error : undefined
    // Rotating-refresh retry (P0-2/P1): an access token may have simply
    // expired while the session is still valid. Try ONE cookie refresh, then
    // retry the original request once. Never recurse from the refresh call
    // itself (it goes through authRequest, not here).
    if (response.status === 401 && !options.anonymous && !internals.skipAuthRetry) {
      const refreshed = await refreshSession()
      if (refreshed) {
        return request<T>(path, options, { skipAuthRetry: true })
      }
    }
    throw new ApiError({
      status: response.status,
      code: error?.code ?? `HTTP_${response.status}`,
      message: error?.message ?? `Request failed with status ${response.status}.`,
      details: error?.details ?? [],
      requestId: error?.request_id,
    })
  }

  return payload as T
}

// ---------------------------------------------------------------------------
// Endpoint helpers
// ---------------------------------------------------------------------------

// --- health / dev -----------------------------------------------------------

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/v1/health', { anonymous: true })
}

export function getHealthReady(): Promise<HealthReadyResponse> {
  return request<HealthReadyResponse>('/api/v1/health/ready', { anonymous: true })
}

// --- auth (P1: cookie sessions via Next.js route handlers) -------------------

/** Login sets HttpOnly session cookies server-side; tokens never reach JS. */
export function login(input: LoginInput): Promise<AuthSession> {
  return authRequest<AuthSession>('/login', input)
}

export function register(input: RegisterInput): Promise<AuthSession> {
  return authRequest<AuthSession>('/register', input)
}

/** Seed the synthetic demo workspace and sign in as the demo user. */
export function demoLogin(): Promise<DemoSession> {
  return authRequest<DemoSession>('/demo')
}

/** Revoke the session server-side and clear both cookies. */
export async function logout(): Promise<void> {
  try {
    await authRequest('/logout')
  } catch {
    // Best-effort: the cookies are cleared by the handler's error path too.
  }
}

export function getMe(): Promise<MeResponse> {
  return request<MeResponse>('/api/v1/me')
}

// --- farms ------------------------------------------------------------------

export function listFarms(): Promise<FarmListResponse> {
  return request<FarmListResponse>('/api/v1/farms')
}

export function createFarm(input: FarmCreateInput): Promise<Farm> {
  return request<Farm>('/api/v1/farms', { method: 'POST', body: input })
}

export function patchFarm(farmId: string, input: FarmPatchInput): Promise<Farm> {
  return request<Farm>(`/api/v1/farms/${farmId}`, { method: 'PATCH', body: input })
}

// --- fields -----------------------------------------------------------------

export function listFields(farmId: string): Promise<FieldListResponse> {
  return request<FieldListResponse>(`/api/v1/farms/${farmId}/fields`)
}

export function getField(fieldId: string): Promise<Field> {
  return request<Field>(`/api/v1/fields/${fieldId}`)
}

export function createField(farmId: string, input: FieldCreateInput): Promise<FieldCreateResponse> {
  return request<FieldCreateResponse>(`/api/v1/farms/${farmId}/fields`, { method: 'POST', body: input })
}

export function patchField(fieldId: string, input: FieldPatchInput): Promise<Field> {
  return request<Field>(`/api/v1/fields/${fieldId}`, { method: 'PATCH', body: input })
}

export function getFieldMap(fieldId: string): Promise<FieldMapResponse> {
  return request<FieldMapResponse>(`/api/v1/fields/${fieldId}/map`)
}

export function listBoundaryVersions(fieldId: string): Promise<BoundaryVersionListResponse> {
  return request<BoundaryVersionListResponse>(`/api/v1/fields/${fieldId}/boundary-versions`)
}

export function createBoundaryVersion(
  fieldId: string,
  input: { geometry: FieldCreateInput['geometry']; change_reason?: string },
): Promise<BoundaryVersionCreateResponse> {
  return request<BoundaryVersionCreateResponse>(`/api/v1/fields/${fieldId}/boundary-versions`, {
    method: 'POST',
    body: input,
  })
}

// --- data catalog / providers -------------------------------------------------

export function getCatalog(): Promise<CatalogResponse> {
  return request<CatalogResponse>('/api/v1/data/catalog')
}

export function getProvidersHealth(): Promise<ProvidersHealthResponse> {
  return request<ProvidersHealthResponse>('/api/v1/data/providers/health')
}

// --- ingestion jobs / observations ---------------------------------------------

export function createDataJob(fieldId: string, input: DataJobCreateInput): Promise<DataJob> {
  return request<DataJob>(`/api/v1/fields/${fieldId}/data-jobs`, { method: 'POST', body: input })
}

export function fetchDataCoverage(fieldId: string): Promise<DataCoverageResponse> {
  return request<DataCoverageResponse>(`/api/v1/fields/${fieldId}/data-coverage`)
}

export function importObservationsCsv(fieldId: string, file: File): Promise<DataJob> {
  const formData = new FormData()
  formData.append('file', file)
  return request<DataJob>(`/api/v1/fields/${fieldId}/imports/observations-csv`, {
    method: 'POST',
    formData,
  })
}

export interface ChirpsExtractInput {
  observedAt: string
  periodKind: 'daily' | 'pentad' | 'monthly'
  productStatus: 'preliminary' | 'final'
}

export function extractChirps(fieldId: string, file: File, input: ChirpsExtractInput): Promise<DataJob> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('observed_at', input.observedAt)
  formData.append('period_kind', input.periodKind)
  formData.append('product_status', input.productStatus)
  return request<DataJob>(`/api/v1/fields/${fieldId}/chirps-extractions`, {
    method: 'POST',
    formData,
  })
}

/** Download URL for the farmer CSV template (relative, gateway-routed). */
export const CSV_TEMPLATE_URL = withPort('/api/v1/data/imports/observations-csv/template')

export function getJob(jobId: string): Promise<DataJob> {
  return request<DataJob>(`/api/v1/jobs/${jobId}`)
}

const JOB_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled'])

/**
 * Poll an ingestion/import job until it reaches a terminal state.
 *
 * The backend executes data jobs on a background worker pool (202 + status
 * 'queued'); when workers are disabled it still executes inline (the response
 * is already terminal, returned as-is). Progress callbacks receive every
 * intermediate snapshot (status/progress for UI feedback).
 */
export async function pollJobUntilDone(
  jobId: string,
  opts: { onProgress?: (job: DataJob) => void; intervalMs?: number; timeoutMs?: number } = {},
): Promise<DataJob> {
  const interval = opts.intervalMs ?? 1000
  const deadline = Date.now() + (opts.timeoutMs ?? 180_000)
  let current = await getJob(jobId)
  while (!JOB_TERMINAL_STATUSES.has(current.status)) {
    opts.onProgress?.(current)
    if (Date.now() > deadline) {
      throw new Error('Timed out waiting for the job to finish — check its status later.')
    }
    await new Promise((resolve) => setTimeout(resolve, interval))
    current = await getJob(jobId)
  }
  return current
}

export interface ObservationQuery {
  variableCode?: string
  start?: string
  end?: string
  limit?: number
  offset?: number
}

export function listObservations(fieldId: string, query: ObservationQuery = {}): Promise<ObservationListResponse> {
  const params = new URLSearchParams()
  if (query.variableCode) params.set('variable_code', query.variableCode)
  if (query.start) params.set('start', query.start)
  if (query.end) params.set('end', query.end)
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  if (query.offset !== undefined) params.set('offset', String(query.offset))
  const qs = params.toString()
  return request<ObservationListResponse>(`/api/v1/fields/${fieldId}/observations${qs ? `?${qs}` : ''}`)
}

// --- data passport ---------------------------------------------------------------

export function getDataPassport(fieldId: string): Promise<DataPassport> {
  return request<DataPassport>(`/api/v1/fields/${fieldId}/data-passport`)
}

// ---------------------------------------------------------------------------
// Client-side GeoJSON helpers (shared by add-field / update-boundary dialogs)
// ---------------------------------------------------------------------------

export type GeometryParseResult =
  | { ok: true; geometry: import('./types').GeoJSONGeometry }
  | { ok: false; error: string }

/** Parse + shallow-validate a GeoJSON Polygon / MultiPolygon from user input. */
export function parseGeometryInput(text: string): GeometryParseResult {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { ok: false, error: 'The text is not valid JSON. Check for missing quotes, brackets or trailing commas.' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'Expected a GeoJSON object like {"type":"Polygon","coordinates":[...]}' }
  }
  const obj = parsed as Record<string, unknown>
  if (obj.type === 'Polygon') {
    if (!Array.isArray(obj.coordinates) || obj.coordinates.length === 0) {
      return { ok: false, error: 'Polygon coordinates must be a non-empty array of rings.' }
    }
    return { ok: true, geometry: parsed as import('./types').GeoJSONPolygon }
  }
  if (obj.type === 'MultiPolygon') {
    if (!Array.isArray(obj.coordinates) || obj.coordinates.length === 0) {
      return { ok: false, error: 'MultiPolygon coordinates must be a non-empty array of polygons.' }
    }
    return { ok: true, geometry: parsed as import('./types').GeoJSONMultiPolygon }
  }
  return { ok: false, error: `Unsupported geometry type "${String(obj.type)}". Use Polygon or MultiPolygon.` }
}

export const EXAMPLE_GEOMETRY = JSON.stringify(
  {
    type: 'Polygon',
    coordinates: [
      [
        [31.4, 31.1],
        [31.42, 31.1],
        [31.42, 31.12],
        [31.4, 31.12],
        [31.4, 31.1],
      ],
    ],
  },
  null,
  2,
)

/** Client-side guard mirroring backend job validation. Returns an error message or null. */
export function validateJobWindow(
  start: string,
  end: string,
  bounds?: { min?: string; max?: string; maxYears?: number },
): string | null {
  const dateRe = /^\d{4}-\d{2}-\d{2}$/
  if (!dateRe.test(start) || !dateRe.test(end)) return 'Enter both dates as YYYY-MM-DD.'
  const min = bounds?.min ?? COVERAGE_START
  const max = bounds?.max ?? COVERAGE_END
  if (start < min || end > max) {
    return `Dates must fall inside the dataset coverage ${min} → ${max}.`
  }
  if (end < start) return 'The end date must be on or after the start date.'
  const years = (Date.parse(end) - Date.parse(start)) / (365.25 * 24 * 3600 * 1000)
  const maxYears = bounds?.maxYears ?? MAX_JOB_YEARS
  if (years > maxYears) return `A single job covers at most ${maxYears} years. Split the range.`
  return null
}

// ---------------------------------------------------------------------------
// Feature engineering (Milestone 4)
// ---------------------------------------------------------------------------

export function getFeatureCatalog(): Promise<FeatureCatalogResponse> {
  return request<FeatureCatalogResponse>('/api/v1/features/catalog')
}

export function createFeatureRun(fieldId: string, input: FeatureRunCreateInput): Promise<FeatureRun> {
  return request<FeatureRun>(`/api/v1/fields/${fieldId}/feature-runs`, { method: 'POST', body: input })
}

export function listFeatureRuns(fieldId: string, limit = 50, offset = 0): Promise<FeatureRunListResponse> {
  return request<FeatureRunListResponse>(`/api/v1/fields/${fieldId}/feature-runs?limit=${limit}&offset=${offset}`)
}

export interface FeatureValueQuery {
  aggregationLevel?: string
  featureCode?: string
  qualityStatus?: string
  limit?: number
  offset?: number
}

export function listFeatureValues(runId: string, query: FeatureValueQuery = {}): Promise<FeatureValueListResponse> {
  const params = new URLSearchParams()
  if (query.aggregationLevel) params.set('aggregation_level', query.aggregationLevel)
  if (query.featureCode) params.set('feature_code', query.featureCode)
  if (query.qualityStatus) params.set('quality_status', query.qualityStatus)
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  if (query.offset !== undefined) params.set('offset', String(query.offset))
  const qs = params.toString()
  return request<FeatureValueListResponse>(`/api/v1/feature-runs/${runId}/values${qs ? `?${qs}` : ''}`)
}

export function compareFeatureRuns(runId: string, againstRunId: string): Promise<FeatureRunComparison> {
  return request<FeatureRunComparison>(
    `/api/v1/feature-runs/${runId}/comparison?against_run_id=${againstRunId}`,
  )
}

// =============================================================
// Milestone 5 — knowledge base & rotation intelligence
// =============================================================

import type {
  CropCandidatesInput,
  CropCandidatesResponse,
  CropDetailResponse,
  CropHistoryCreateInput,
  CropHistoryListResponse,
  CropHistoryItem,
  KnowledgeCropListResponse,
  KnowledgePackImportInput,
  KnowledgePackImportResponse,
  KnowledgePackListResponse,
  KnowledgePackSourcesResponse,
  RotationRun,
  RotationRunCreateInput,
  RotationRunListResponse,
  RotationRulesResponse,
  RotationStrategiesResponse,
  RotationComparisonResponse,
  WaterMethodsResponse,
  WaterPlan,
  WaterPlanCreateInput,
  WaterPlanListResponse,
  WaterReadinessResponse,
} from './types'

export function getKnowledgePacks(): Promise<KnowledgePackListResponse> {
  return request<KnowledgePackListResponse>('/api/v1/knowledge/packs')
}

export function getKnowledgePackSources(packId: string): Promise<KnowledgePackSourcesResponse> {
  return request<KnowledgePackSourcesResponse>(`/api/v1/knowledge/packs/${packId}/sources`)
}

export function getKnowledgeCrops(): Promise<KnowledgeCropListResponse> {
  return request<KnowledgeCropListResponse>('/api/v1/knowledge/crops')
}

export function getCropDetail(cropCode: string): Promise<CropDetailResponse> {
  return request<CropDetailResponse>(`/api/v1/knowledge/crops/${encodeURIComponent(cropCode)}`)
}

export function getRotationRules(): Promise<RotationRulesResponse> {
  return request<RotationRulesResponse>('/api/v1/knowledge/rotation-rules')
}

export function importKnowledgePack(input: KnowledgePackImportInput): Promise<KnowledgePackImportResponse> {
  return request<KnowledgePackImportResponse>('/api/v1/knowledge/packs/import', {
    method: 'POST',
    body: input,
  })
}

export function listCropHistory(fieldId: string): Promise<CropHistoryListResponse> {
  return request<CropHistoryListResponse>(`/api/v1/fields/${fieldId}/crop-history`)
}

export function addCropHistory(fieldId: string, input: CropHistoryCreateInput): Promise<CropHistoryItem> {
  return request<CropHistoryItem>(`/api/v1/fields/${fieldId}/crop-history`, {
    method: 'POST',
    body: input,
  })
}

export function generateCropCandidates(
  fieldId: string,
  input: CropCandidatesInput,
): Promise<CropCandidatesResponse> {
  return request<CropCandidatesResponse>(`/api/v1/fields/${fieldId}/crop-candidates`, {
    method: 'POST',
    body: input,
  })
}

export function createRotationRun(fieldId: string, input: RotationRunCreateInput): Promise<RotationRun> {
  return request<RotationRun>(`/api/v1/fields/${fieldId}/rotation-runs`, {
    method: 'POST',
    body: input,
  })
}

export function listRotationRuns(fieldId: string): Promise<RotationRunListResponse> {
  return request<RotationRunListResponse>(`/api/v1/fields/${fieldId}/rotation-runs`)
}

export function getRotationRun(runId: string): Promise<RotationRun> {
  return request<RotationRun>(`/api/v1/rotation-runs/${runId}`)
}

export function getRotationStrategies(runId: string): Promise<RotationStrategiesResponse> {
  return request<RotationStrategiesResponse>(`/api/v1/rotation-runs/${runId}/strategies`)
}

export function getRotationComparison(runId: string): Promise<RotationComparisonResponse> {
  return request<RotationComparisonResponse>(`/api/v1/rotation-runs/${runId}/comparison`)
}

// =============================================================
// Milestone 6A — water intelligence
// =============================================================

export function getWaterMethods(): Promise<WaterMethodsResponse> {
  return request<WaterMethodsResponse>('/api/v1/water/methods', { anonymous: true })
}

export function getWaterReadiness(fieldId: string): Promise<WaterReadinessResponse> {
  return request<WaterReadinessResponse>(`/api/v1/fields/${fieldId}/water/knowledge-readiness`)
}

export function createWaterPlan(fieldId: string, input: WaterPlanCreateInput): Promise<WaterPlan> {
  return request<WaterPlan>(`/api/v1/fields/${fieldId}/water-plans`, {
    method: 'POST',
    body: input,
  })
}

export function listWaterPlans(fieldId: string): Promise<WaterPlanListResponse> {
  return request<WaterPlanListResponse>(`/api/v1/fields/${fieldId}/water-plans`)
}

export function getWaterPlan(planId: string): Promise<WaterPlan> {
  return request<WaterPlan>(`/api/v1/water-plans/${planId}`)
}

export function deleteWaterPlan(planId: string): Promise<void> {
  return request<void>(`/api/v1/water-plans/${planId}`, { method: 'DELETE' })
}

// =============================================================
// Milestone 7.1 — field state foundation
// =============================================================

export function createFieldState(fieldId: string, input: FieldStateCreateInput): Promise<FieldState> {
  return request<FieldState>(`/api/v1/fields/${fieldId}/field-states`, {
    method: 'POST',
    body: input,
  })
}

export function listFieldStates(fieldId: string): Promise<FieldStateListResponse> {
  return request<FieldStateListResponse>(`/api/v1/fields/${fieldId}/field-states`)
}

export function getFieldState(stateId: string, includeManifest = false): Promise<FieldState> {
  return request<FieldState>(
    `/api/v1/field-states/${stateId}${includeManifest ? '?include_manifest=true' : ''}`,
  )
}

export function verifyFieldState(stateId: string): Promise<FieldStateVerifyResponse> {
  return request<FieldStateVerifyResponse>(`/api/v1/field-states/${stateId}/verify`)
}

export function getFieldStateManifest(stateId: string): Promise<{
  state_id: string
  manifest_format_version: string
  observation_manifest_sha256: string | null
  observation_manifest: ObservationManifest
}> {
  return request(`/api/v1/field-states/${stateId}/manifest`)
}

export function compareFieldStates(stateIds: string[]): Promise<FieldStateCompareResponse> {
  return request<FieldStateCompareResponse>('/api/v1/field-states/compare', {
    method: 'POST',
    body: { state_ids: stateIds },
  })
}

// ---------------------------------------------------------------------------
// Scenarios (M7.2) — definitions only; no execution endpoint exists
// ---------------------------------------------------------------------------

export function getScenarioTypes(): Promise<ScenarioTaxonomy> {
  return request<ScenarioTaxonomy>('/api/v1/scenarios/types', { anonymous: true })
}

export function getScenarioCapabilities(): Promise<ScenarioCapabilities> {
  return request<ScenarioCapabilities>('/api/v1/scenarios/capabilities', { anonymous: true })
}

export function listScenarios(fieldId: string): Promise<ScenarioListResponse> {
  return request<ScenarioListResponse>(`/api/v1/fields/${fieldId}/scenarios`)
}

export function getScenario(
  scenarioId: string,
  includeValidationHistory = false
): Promise<Scenario> {
  return request<Scenario>(
    `/api/v1/scenarios/${scenarioId}${includeValidationHistory ? '?include_validation_history=true' : ''}`
  )
}

export function createScenario(fieldId: string, input: ScenarioCreateInput): Promise<Scenario> {
  return request<Scenario>(`/api/v1/fields/${fieldId}/scenarios`, {
    method: 'POST',
    body: input,
  })
}

export function patchScenario(scenarioId: string, input: Partial<ScenarioCreateInput> & { name?: string; description?: string }): Promise<Scenario> {
  return request<Scenario>(`/api/v1/scenarios/${scenarioId}`, {
    method: 'PATCH',
    body: input,
  })
}

export function deleteScenario(scenarioId: string): Promise<{ deleted: boolean; scenario_id: string }> {
  return request(`/api/v1/scenarios/${scenarioId}`, { method: 'DELETE' })
}

export function validateScenario(scenarioId: string): Promise<ScenarioValidateResponse> {
  return request<ScenarioValidateResponse>(`/api/v1/scenarios/${scenarioId}/validate`, {
    method: 'POST',
  })
}

export function finalizeScenario(scenarioId: string): Promise<Scenario> {
  return request<Scenario>(`/api/v1/scenarios/${scenarioId}/finalize`, { method: 'POST' })
}

export function archiveScenario(scenarioId: string): Promise<Scenario> {
  return request<Scenario>(`/api/v1/scenarios/${scenarioId}/archive`, { method: 'POST' })
}

export function createScenarioVersion(
  scenarioId: string,
  input: { scenario_type?: string; name?: string; configuration?: ScenarioCreateInput['configuration']; idempotency_key?: string }
): Promise<Scenario> {
  return request<Scenario>(`/api/v1/scenarios/${scenarioId}/versions`, {
    method: 'POST',
    body: input,
  })
}

export function listScenarioVersions(scenarioId: string): Promise<ScenarioVersionsResponse> {
  return request<ScenarioVersionsResponse>(`/api/v1/scenarios/${scenarioId}/versions`)
}

export function getScenarioLineage(scenarioId: string): Promise<ScenarioLineageResponse> {
  return request<ScenarioLineageResponse>(`/api/v1/scenarios/${scenarioId}/lineage`)
}

export function verifyScenario(scenarioId: string): Promise<ScenarioVerifyResponse> {
  return request<ScenarioVerifyResponse>(`/api/v1/scenarios/${scenarioId}/verify`)
}

export function compareScenarios(scenarioId: string, againstId: string): Promise<ScenarioCompareResponse> {
  return request<ScenarioCompareResponse>(
    `/api/v1/scenarios/${scenarioId}/compare?against=${encodeURIComponent(againstId)}`
  )
}

// =============================================================
// Milestone 6B — soil intelligence
// =============================================================

import type {
  CoverCropPlan,
  CoverCropPlanCreateInput,
  CoverCropPlanItem,
  CoverCropPlanItemCreateInput,
  CoverCropPlanItemListResponse,
  CoverCropPlanListResponse,
  CoverObservation,
  CoverObservationCreateInput,
  CoverTimelineResponse,
  DecisionComparisonCreateInput,
  DecisionComparisonListResponse,
  DecisionComparisonSummary,
  DecisionDocument,
  DecisionVerifyResponse,
  DigitalTwinView,
  ErosionAssessmentCreateInput,
  ErosionRun,
  FarmResource,
  FarmResourceCreateInput,
  FarmResourceListResponse,
  FieldOperation,
  FieldOperationListResponse,
  FieldOperationPatchInput,
  ManagementPlan,
  ManagementPlanCreateInput,
  ManagementPracticeListResponse,
  NutrientBudgetRun,
  NutrientBudgetRunCreateInput,
  OperationTemplateListResponse,
  ResidueFlowCreateInput,
  ResidueLedgerResponse,
  RobustEvaluationListResponse,
  RobustRotationRun,
  RobustRunCreateInput,
  RobustRunListResponse,
  RobustVerifyResponse,
  ScheduleRun,
  ScenarioDerivedFeatureListResponse,
  ScenarioDerivedObservationListResponse,
  ScenarioExecutionCompareResponse,
  ScenarioExecutionListResponse,
  ScenarioExecutionRun,
  ScenarioExecutionVerifyResponse,
  ScenarioSet,
  ScenarioSetCreateInput,
  ScenarioSetListResponse,
  ScenarioSetVerifyResponse,
  SensitivityAnalysis,
  SensitivityAnalysisCreateInput,
  SensitivityAnalysisListResponse,
  SensitivityGridResponse,
  SensitivityResponseListResponse,
  SensitivityUncertaintyResponse,
  SensitivityVerifyResponse,
  SoilAssessmentRun,
  SoilHealthResponse,
  SoilIndicatorsResponse,
  SoilLabImportResponse,
  SoilDataReadinessResponse,
  SoilMethodsResponse,
  SoilProfileResponse,
  SocStockRun,
  SocStockRunCreateInput,
  SocStockRunListResponse,
  TwinValidationListResponse,
  TwinValidationResponse,
} from './types'

// --- soil methods / read models ---------------------------------------------

export function getSoilMethods(): Promise<SoilMethodsResponse> {
  return request<SoilMethodsResponse>('/api/v1/soil/methods', { anonymous: true })
}

export function getSoilProfile(fieldId: string): Promise<SoilProfileResponse> {
  return request<SoilProfileResponse>(`/api/v1/fields/${fieldId}/soil-profile`)
}

export function getSoilIndicators(fieldId: string): Promise<SoilIndicatorsResponse> {
  return request<SoilIndicatorsResponse>(`/api/v1/fields/${fieldId}/soil-indicators`)
}

export function getSoilHealth(fieldId: string): Promise<SoilHealthResponse> {
  return request<SoilHealthResponse>(`/api/v1/fields/${fieldId}/soil-health`)
}

export function getSoilDataReadiness(fieldId: string): Promise<SoilDataReadinessResponse> {
  return request<SoilDataReadinessResponse>(`/api/v1/fields/${fieldId}/soil-data-readiness`)
}

// --- SOC stock runs ----------------------------------------------------------

export function createSocStockRun(
  fieldId: string,
  input: SocStockRunCreateInput,
): Promise<SocStockRun> {
  return request<SocStockRun>(`/api/v1/fields/${fieldId}/soc-stock-runs`, {
    method: 'POST',
    body: input,
  })
}

export function listSocRuns(fieldId: string): Promise<SocStockRunListResponse> {
  return request<SocStockRunListResponse>(`/api/v1/fields/${fieldId}/soc-stock-runs`)
}

export function getSocStockRun(runId: string): Promise<SocStockRun> {
  return request<SocStockRun>(`/api/v1/soc-stock-runs/${runId}`)
}

// --- nutrient budget ----------------------------------------------------------

export function createNutrientBudgetRun(
  fieldId: string,
  input: NutrientBudgetRunCreateInput,
): Promise<NutrientBudgetRun> {
  return request<NutrientBudgetRun>(`/api/v1/fields/${fieldId}/nutrient-budget-runs`, {
    method: 'POST',
    body: input,
  })
}

export function listNutrientBudgetRuns(fieldId: string): Promise<{ field_id: string; items: NutrientBudgetRun[] }> {
  return request(`/api/v1/fields/${fieldId}/nutrient-budget-runs`)
}

export function getNutrientBudgetRun(runId: string): Promise<NutrientBudgetRun> {
  return request<NutrientBudgetRun>(`/api/v1/nutrient-budget-runs/${runId}`)
}

// --- laboratory CSV import ------------------------------------------------------
// Backend contract: POST /soil-samples/import (org-level) requires a `mapping`
// form field whose JSON carries default_field_id — the field binding arrives
// there, so the component's (fieldId, file) signature is preserved.

export async function importSoilLabCsv(fieldId: string, file: File): Promise<SoilLabImportResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('mapping', JSON.stringify({ default_field_id: fieldId }))
  const data = await request<SoilLabImportResponse>('/api/v1/soil-samples/import', {
    method: 'POST',
    formData,
  })
  // The backend's idempotent "already_imported" reply omits the counters;
  // normalize so callers always see numbers (re-import of identical content
  // creates nothing — 0 is the truthful value there).
  return {
    ...data,
    created_samples: data.created_samples ?? 0,
    created_measurements: data.created_measurements ?? 0,
    errors: data.errors ?? [],
  }
}

// --- assessment snapshots -------------------------------------------------------

export function runSoilAssessment(fieldId: string): Promise<SoilAssessmentRun> {
  return request<SoilAssessmentRun>(`/api/v1/fields/${fieldId}/soil-assessments`, {
    method: 'POST',
    body: {},
  })
}

export function getSoilAssessment(assessmentId: string): Promise<SoilAssessmentRun> {
  return request<SoilAssessmentRun>(`/api/v1/soil-assessments/${assessmentId}`)
}

// =============================================================
// Milestone 6C — field management
// =============================================================

// --- soil cover -----------------------------------------------------------------

export function createCoverObservation(
  fieldId: string,
  input: CoverObservationCreateInput,
): Promise<CoverObservation> {
  return request<CoverObservation>(`/api/v1/fields/${fieldId}/soil-cover/observations`, {
    method: 'POST',
    body: input,
  })
}

export function getCoverTimeline(fieldId: string, start: string, end: string): Promise<CoverTimelineResponse> {
  return request<CoverTimelineResponse>(
    `/api/v1/fields/${fieldId}/soil-cover/timeline?window_start=${encodeURIComponent(start)}&window_end=${encodeURIComponent(end)}`,
  )
}

// --- cover-crop plans -------------------------------------------------------------

export function createCoverCropPlan(
  fieldId: string,
  input: CoverCropPlanCreateInput,
): Promise<CoverCropPlan> {
  return request<CoverCropPlan>(`/api/v1/fields/${fieldId}/cover-crop-plans`, {
    method: 'POST',
    body: input,
  })
}

export function listCoverCropPlans(fieldId: string): Promise<CoverCropPlanListResponse> {
  return request<CoverCropPlanListResponse>(`/api/v1/fields/${fieldId}/cover-crop-plans`)
}

export function getCoverCropPlan(planId: string): Promise<CoverCropPlan> {
  return request<CoverCropPlan>(`/api/v1/cover-crop-plans/${planId}`)
}

export function createCoverCropPlanItem(
  fieldId: string,
  input: CoverCropPlanItemCreateInput,
): Promise<CoverCropPlanItem> {
  return request<CoverCropPlanItem>(`/api/v1/fields/${fieldId}/cover-crop-plan-items`, {
    method: 'POST',
    body: input,
  })
}

export function listCoverCropPlanItems(fieldId: string): Promise<CoverCropPlanItemListResponse> {
  return request<CoverCropPlanItemListResponse>(`/api/v1/fields/${fieldId}/cover-crop-plan-items`)
}

// --- residue ledger ---------------------------------------------------------------

export function createResidueRecord(fieldId: string, input: Record<string, unknown>): Promise<import('./types').ResidueRecord> {
  return request(`/api/v1/fields/${fieldId}/residue-records`, { method: 'POST', body: input })
}

export function createResidueFlow(recordId: string, input: ResidueFlowCreateInput): Promise<{ id: string; [key: string]: unknown }> {
  return request(`/api/v1/residue-records/${recordId}/flows`, { method: 'POST', body: input })
}

export function getResidueLedger(fieldId: string): Promise<ResidueLedgerResponse> {
  return request<ResidueLedgerResponse>(`/api/v1/fields/${fieldId}/residue-ledger`)
}

// --- erosion ----------------------------------------------------------------------

export function createErosionAssessment(
  fieldId: string,
  input: ErosionAssessmentCreateInput,
): Promise<ErosionRun> {
  return request<ErosionRun>(`/api/v1/fields/${fieldId}/erosion-assessments`, {
    method: 'POST',
    body: input,
  })
}

export function getErosionRun(runId: string): Promise<ErosionRun> {
  return request<ErosionRun>(`/api/v1/erosion-assessments/${runId}`)
}

// --- farm resources -----------------------------------------------------------------

export function createFarmResource(farmId: string, input: FarmResourceCreateInput): Promise<FarmResource> {
  return request<FarmResource>(`/api/v1/farms/${farmId}/resources`, { method: 'POST', body: input })
}

export function listFarmResources(farmId: string): Promise<FarmResourceListResponse> {
  return request<FarmResourceListResponse>(`/api/v1/farms/${farmId}/resources`)
}

// --- operations & scheduling -----------------------------------------------------------

export function createFieldOperation(fieldId: string, input: Record<string, unknown>): Promise<FieldOperation> {
  return request<FieldOperation>(`/api/v1/fields/${fieldId}/operations`, { method: 'POST', body: input })
}

export function generateOperations(
  fieldId: string,
  input: { crop_label: string; window_year: number; season_label?: string },
): Promise<{ created: number; items: FieldOperation[]; [key: string]: unknown }> {
  return request(`/api/v1/fields/${fieldId}/operations/generate`, { method: 'POST', body: input })
}

export function listFieldOperations(fieldId: string): Promise<FieldOperationListResponse> {
  return request<FieldOperationListResponse>(`/api/v1/fields/${fieldId}/operations`)
}

export function patchOperation(opId: string, patch: FieldOperationPatchInput): Promise<FieldOperation> {
  return request<FieldOperation>(`/api/v1/operations/${opId}`, { method: 'PATCH', body: patch })
}

export function createScheduleRun(
  fieldId: string,
  input: { hours_per_workday?: number; horizon_start?: string; horizon_end?: string; label?: string; idempotency_key?: string },
): Promise<ScheduleRun> {
  return request<ScheduleRun>(`/api/v1/fields/${fieldId}/operation-schedule-runs`, {
    method: 'POST',
    body: input,
  })
}

export function getResourceConflicts(fieldId: string): Promise<{
  field_id: string
  conflicts: Array<{ message: string; [key: string]: unknown }>
  total: number
}> {
  return request(`/api/v1/fields/${fieldId}/resource-conflicts`)
}

// --- knowledge-backed practices & operation templates (M6C) -----------------------------

export function listManagementPractices(): Promise<ManagementPracticeListResponse> {
  return request<ManagementPracticeListResponse>('/api/v1/knowledge/practices')
}

export function listOperationTemplates(): Promise<OperationTemplateListResponse> {
  return request<OperationTemplateListResponse>('/api/v1/knowledge/operation-templates')
}

// --- management plan -----------------------------------------------------------------------

export function createManagementPlan(fieldId: string, input: ManagementPlanCreateInput): Promise<ManagementPlan> {
  return request<ManagementPlan>(`/api/v1/fields/${fieldId}/management-plans`, {
    method: 'POST',
    body: input,
  })
}

export function listManagementPlans(fieldId: string): Promise<{ field_id: string; items: import('./types').ManagementPlanSummary[]; total: number }> {
  return request(`/api/v1/fields/${fieldId}/management-plans`)
}

export function getManagementPlan(planId: string): Promise<ManagementPlan> {
  return request<ManagementPlan>(`/api/v1/management-plans/${planId}`)
}

// =============================================================
// Milestone 7.3 — scenario execution
// =============================================================

export function executeScenario(
  scenarioId: string,
  input: { idempotency_key?: string } = {},
): Promise<ScenarioExecutionRun> {
  return request<ScenarioExecutionRun>(`/api/v1/scenarios/${scenarioId}/executions`, {
    method: 'POST',
    body: input,
  })
}

export function listScenarioExecutions(
  scenarioId: string,
  status?: string,
): Promise<ScenarioExecutionListResponse> {
  const qs = status ? `?run_status=${encodeURIComponent(status)}` : ''
  return request<ScenarioExecutionListResponse>(`/api/v1/scenarios/${scenarioId}/executions${qs}`)
}

export function getScenarioExecution(runId: string): Promise<ScenarioExecutionRun> {
  return request<ScenarioExecutionRun>(`/api/v1/scenario-executions/${runId}`)
}

export function listExecutionFeatures(
  runId: string,
  query: { evidenceStatus?: string; featureCode?: string } = {},
): Promise<ScenarioDerivedFeatureListResponse> {
  const params = new URLSearchParams()
  if (query.evidenceStatus) params.set('evidence_status', query.evidenceStatus)
  if (query.featureCode) params.set('feature_code', query.featureCode)
  const qs = params.toString()
  return request<ScenarioDerivedFeatureListResponse>(
    `/api/v1/scenario-executions/${runId}/features${qs ? `?${qs}` : ''}`,
  )
}

export function listExecutionObservations(
  runId: string,
  query: { variableCode?: string; limit?: number; offset?: number } = {},
): Promise<ScenarioDerivedObservationListResponse> {
  const params = new URLSearchParams()
  if (query.variableCode) params.set('variable_code', query.variableCode)
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  if (query.offset !== undefined) params.set('offset', String(query.offset))
  const qs = params.toString()
  return request<ScenarioDerivedObservationListResponse>(
    `/api/v1/scenario-executions/${runId}/observations${qs ? `?${qs}` : ''}`,
  )
}

export function compareScenarioExecution(runId: string): Promise<ScenarioExecutionCompareResponse> {
  return request<ScenarioExecutionCompareResponse>(`/api/v1/scenario-executions/${runId}/compare`)
}

export function verifyScenarioExecution(runId: string): Promise<ScenarioExecutionVerifyResponse> {
  return request<ScenarioExecutionVerifyResponse>(`/api/v1/scenario-executions/${runId}/verify`, {
    method: 'POST',
  })
}

// =============================================================
// Milestone 7.4 — sensitivity & uncertainty
// =============================================================

export function createSensitivityAnalysis(
  runId: string,
  input: SensitivityAnalysisCreateInput,
): Promise<SensitivityAnalysis> {
  return request<SensitivityAnalysis>(`/api/v1/scenario-executions/${runId}/sensitivity-analyses`, {
    method: 'POST',
    body: input,
  })
}

export function listSensitivityAnalyses(runId: string): Promise<SensitivityAnalysisListResponse> {
  return request<SensitivityAnalysisListResponse>(
    `/api/v1/scenario-executions/${runId}/sensitivity-analyses`,
  )
}

export function getSensitivityAnalysis(analysisId: string): Promise<SensitivityAnalysis> {
  return request<SensitivityAnalysis>(`/api/v1/sensitivity-analyses/${analysisId}`)
}

export function listSensitivityResponses(
  analysisId: string,
  query: { parameter_code?: string; feature_code?: string; aggregation_level?: string; response_classification?: string } = {},
): Promise<SensitivityResponseListResponse> {
  const params = new URLSearchParams()
  if (query.parameter_code) params.set('parameter_code', query.parameter_code)
  if (query.feature_code) params.set('feature_code', query.feature_code)
  if (query.aggregation_level) params.set('aggregation_level', query.aggregation_level)
  if (query.response_classification) params.set('response_classification', query.response_classification)
  const qs = params.toString()
  return request<SensitivityResponseListResponse>(
    `/api/v1/sensitivity-analyses/${analysisId}/responses${qs ? `?${qs}` : ''}`,
  )
}

export function getSensitivityGrid(analysisId: string): Promise<SensitivityGridResponse> {
  return request<SensitivityGridResponse>(`/api/v1/sensitivity-analyses/${analysisId}/grid`)
}

export function getSensitivityUncertainty(analysisId: string): Promise<SensitivityUncertaintyResponse> {
  return request<SensitivityUncertaintyResponse>(`/api/v1/sensitivity-analyses/${analysisId}/uncertainty`)
}

export function verifySensitivityAnalysis(analysisId: string): Promise<SensitivityVerifyResponse> {
  return request<SensitivityVerifyResponse>(`/api/v1/sensitivity-analyses/${analysisId}/verify`, {
    method: 'POST',
  })
}

// =============================================================
// Milestone 7.5 — robust rotation
// =============================================================

export function createScenarioSet(fieldId: string, input: ScenarioSetCreateInput): Promise<ScenarioSet> {
  return request<ScenarioSet>(`/api/v1/fields/${fieldId}/scenario-sets`, { method: 'POST', body: input })
}

export function listScenarioSets(fieldId: string): Promise<ScenarioSetListResponse> {
  return request<ScenarioSetListResponse>(`/api/v1/fields/${fieldId}/scenario-sets`)
}

export function getScenarioSet(setId: string): Promise<ScenarioSet> {
  return request<ScenarioSet>(`/api/v1/scenario-sets/${setId}`)
}

export function deleteScenarioSet(setId: string): Promise<{ deleted: string }> {
  return request(`/api/v1/scenario-sets/${setId}`, { method: 'DELETE' })
}

export function verifyScenarioSet(setId: string): Promise<ScenarioSetVerifyResponse> {
  return request<ScenarioSetVerifyResponse>(`/api/v1/scenario-sets/${setId}/verify`, { method: 'POST' })
}

export function createRobustRun(setId: string, input: RobustRunCreateInput): Promise<RobustRotationRun> {
  return request<RobustRotationRun>(`/api/v1/scenario-sets/${setId}/robust-runs`, {
    method: 'POST',
    body: input,
  })
}

export function listRobustRuns(setId: string): Promise<RobustRunListResponse> {
  return request<RobustRunListResponse>(`/api/v1/scenario-sets/${setId}/robust-runs`)
}

export function getRobustRun(runId: string): Promise<RobustRotationRun> {
  return request<RobustRotationRun>(`/api/v1/robust-runs/${runId}`)
}

export function listRobustEvaluations(runId: string): Promise<RobustEvaluationListResponse> {
  return request<RobustEvaluationListResponse>(`/api/v1/robust-runs/${runId}/evaluations`)
}

export function verifyRobustRun(runId: string): Promise<RobustVerifyResponse> {
  return request<RobustVerifyResponse>(`/api/v1/robust-runs/${runId}/verify`, { method: 'POST' })
}

// =============================================================
// Milestone 7.6 — decision intelligence
// =============================================================

export function createDecisionComparison(
  fieldId: string,
  input: DecisionComparisonCreateInput = {},
): Promise<DecisionComparisonSummary> {
  return request<DecisionComparisonSummary>(`/api/v1/fields/${fieldId}/decision-comparisons`, {
    method: 'POST',
    body: input,
  })
}

export function listDecisionComparisons(fieldId: string): Promise<DecisionComparisonListResponse> {
  return request<DecisionComparisonListResponse>(`/api/v1/fields/${fieldId}/decision-comparisons`)
}

export function getDecisionComparison(comparisonId: string): Promise<DecisionComparisonSummary & { document?: DecisionDocument }> {
  return request(`/api/v1/decision-comparisons/${comparisonId}`)
}

export function verifyDecisionComparison(comparisonId: string): Promise<DecisionVerifyResponse> {
  return request<DecisionVerifyResponse>(`/api/v1/decision-comparisons/${comparisonId}/verify`, {
    method: 'POST',
  })
}

// =============================================================
// Milestone 7.7 — digital twin
// =============================================================

export function getDigitalTwin(fieldId: string): Promise<DigitalTwinView> {
  return request<DigitalTwinView>(`/api/v1/fields/${fieldId}/digital-twin`)
}

export function validateDigitalTwin(fieldId: string): Promise<TwinValidationResponse> {
  return request<TwinValidationResponse>(`/api/v1/fields/${fieldId}/digital-twin/validate`, {
    method: 'POST',
    body: {},
  })
}

export function listTwinValidations(fieldId: string): Promise<TwinValidationListResponse> {
  return request<TwinValidationListResponse>(`/api/v1/fields/${fieldId}/digital-twin/validations`)
}

// =============================================================
// AI Insights — recommendations, field insights, advisor
// =============================================================

/** Stored recommendations for a field. `refresh=true` also regenerates inline. */
export function getRecommendations(fieldId: string, refresh = false): Promise<RecommendationsResponse> {
  return request<RecommendationsResponse>(
    `/api/v1/fields/${fieldId}/recommendations${refresh ? '?refresh=true' : ''}`,
  )
}

/** Regenerate recommendations through the AI pipeline (same shape as GET). */
export function refreshRecommendations(fieldId: string): Promise<RecommendationsResponse> {
  return request<RecommendationsResponse>(`/api/v1/fields/${fieldId}/recommendations/refresh`, {
    method: 'POST',
    body: {},
  })
}

/** Anomaly/trend insights plus the short AI field brief. */
export function getFieldInsights(fieldId: string): Promise<FieldInsightsResponse> {
  return request<FieldInsightsResponse>(`/api/v1/fields/${fieldId}/insights`)
}

/** Ask the AI agronomist a question grounded in FieldShift engine outputs. */
export function queryAdvisor(fieldId: string, question: string): Promise<AdvisorQueryResponse> {
  return request<AdvisorQueryResponse>(`/api/v1/fields/${fieldId}/advisor/query`, {
    method: 'POST',
    body: { question },
  })
}

/** Recent advisor conversation, oldest first (user/assistant pairs). */
export function getAdvisorHistory(fieldId: string, limit = 20): Promise<AdvisorHistoryResponse> {
  return request<AdvisorHistoryResponse>(
    `/api/v1/fields/${fieldId}/advisor/history?limit=${limit}`,
  )
}

/**
 * Typed fetch wrapper for the FieldShift API.
 *
 * Gateway rule: every request goes to a RELATIVE path and carries the
 * `XTransformPort=3030` query parameter so the Caddy gateway forwards it to
 * the FastAPI mini-service. Absolute URLs are never used.
 */
import type {
  ApiErrorBody,
  ApiErrorDetail,
  AuthResponse,
  BoundaryVersionCreateResponse,
  BoundaryVersionListResponse,
  CatalogResponse,
  DataCoverageResponse,
  DataJob,
  DataJobCreateInput,
  DataPassport,
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
  FieldListResponse,
  FieldMapResponse,
  FieldPatchInput,
  HealthReadyResponse,
  HealthResponse,
  LoginInput,
  MeResponse,
  ObservationListResponse,
  ProvidersHealthResponse,
  RegisterInput,
  SeedDemoResponse,
} from './types'

export const TOKEN_STORAGE_KEY = 'fieldshift_token'
const PORT_QUERY = 'XTransformPort=3030'

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

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setToken(token: string | null): void {
  if (typeof window === 'undefined') return
  if (token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Multipart form body (file uploads). Content-Type is set by the browser. */
  formData?: FormData
  /** Skip attaching the bearer token (health, dev/seed-demo). */
  anonymous?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (!options.anonymous) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

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

export function seedDemo(): Promise<SeedDemoResponse> {
  return request<SeedDemoResponse>('/api/v1/dev/seed-demo', { method: 'POST', anonymous: true })
}

// --- auth -------------------------------------------------------------------

export function register(input: RegisterInput): Promise<AuthResponse> {
  return request<AuthResponse>('/api/v1/auth/register', { method: 'POST', body: input, anonymous: true })
}

export function login(input: LoginInput): Promise<AuthResponse> {
  return request<AuthResponse>('/api/v1/auth/login', { method: 'POST', body: input, anonymous: true })
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

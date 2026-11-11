/**
 * P3 Commercial sphere — typed fetch functions for Billing, Analytics
 * (insights), Reports and the Developer console.
 *
 * Mirrors the conventions of `src/lib/api.ts`: every request uses a RELATIVE
 * path plus the `XTransformPort=3030` gateway parameter, HttpOnly session
 * cookies carry authentication automatically, and non-2xx responses throw the
 * shared `ApiError` (same class identity, so `describeError` keeps working).
 *
 * Endpoints implemented here (contracts read from
 * `mini-services/fieldshift-api/app/api/v1/{billing,analytics,reports,developer}.py`):
 * - GET  /orgs (existing — resolves the caller's active organizations)
 * - /billing/plans, /billing/subscription (+ start/change/cancel/resume),
 *   /billing/usage, /billing/entitlements, /billing/invoices, /billing/sandbox/pay
 * - /analytics/executive-dashboard, /analytics/farm-performance/{id},
 *   /analytics/commercial-metrics, /analytics/benchmarks
 * - /reports (create/list/get/download/delete/regenerate/schedule)
 * - /developer/keys (+create/revoke/rotate), /developer/webhooks
 *   (+create/patch/delete/rotate-secret/deliveries/redeliver),
 *   /developer/usage, /developer/events
 */
import { ApiError, refreshSession } from './api'
import type { ApiErrorBody } from './types'

const PORT_QUERY = 'XTransformPort=3030'

function withPort(path: string): string {
  const joiner = path.includes('?') ? '&' : '?'
  return `${path}${joiner}${PORT_QUERY}`
}

/** URL query string from a params object; null/undefined/'' values are skipped. */
function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const out = search.toString()
  return out ? `?${out}` : ''
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /** Skip the 401→refresh retry (public catalog endpoints). */
  anonymous?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(withPort(path), {
      method: options.method ?? 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: 'no-store',
    })
  } catch {
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the CropTwist API.',
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
    const error =
      envelope && typeof envelope === 'object' && 'error' in envelope ? envelope.error : undefined
    if (response.status === 401 && !options.anonymous) {
      // Delegate to the shared session refresher (single-flight inside api.ts).
      const refreshed = await refreshSession().catch(() => false)
      if (refreshed) return request<T>(path, options)
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
// Shared shapes
// ---------------------------------------------------------------------------

export interface MyOrganization {
  id: string
  name: string
  organization_type: string
  country_code: string | null
  created_at: string
  updated_at: string
  my_role: string | null
}

export interface MyOrganizationsResponse {
  items: MyOrganization[]
  total: number
}

/** GET /api/v1/orgs — organizations the caller actively belongs to. */
export function listMyOrganizations(): Promise<MyOrganizationsResponse> {
  return request<MyOrganizationsResponse>('/api/v1/orgs')
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------

export type BillingPeriod = 'monthly' | 'yearly'

export interface PlanPriceInfo {
  billing_period: string
  /** Cents. null = not self-serve ("contact sales"). */
  amount_cents: number | null
  currency_code: string
}

export type PlanEntitlementMap = Record<string, number | boolean>

export interface PlanCatalogItem {
  id: string
  code: string
  name: string
  description: string | null
  trial_days: number | null
  prices: PlanPriceInfo[]
  entitlements: PlanEntitlementMap
}

export interface BillingPlansResponse {
  items: PlanCatalogItem[]
}

/** Public pricing catalog — no authentication required. */
export function listBillingPlans(): Promise<BillingPlansResponse> {
  return request<BillingPlansResponse>('/api/v1/billing/plans', { anonymous: true })
}

export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'grace'
  | 'canceled'
  | (string & {})

export interface BillingSubscriptionInfo {
  id: string
  organization_id: string
  status: SubscriptionStatus
  billing_period: BillingPeriod
  provider: string
  provider_mode: string
  current_period_start: string
  current_period_end: string
  trial_ends_at: string | null
  cancel_at_period_end: boolean
  grace_ends_at: string | null
  plan: { id: string; code: string; name: string } | null
}

export interface BillingCheckoutInfo {
  session_id: string
  provider: string
  url: string | null
  mode: string
}

export interface BillingSubscriptionStartResult {
  subscription: BillingSubscriptionInfo
  checkout: BillingCheckoutInfo
}

export interface BillingEventInfo {
  id: string
  event_type: string
  from_status: string | null
  to_status: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface BillingInvoice {
  id: string
  number: string
  status: 'open' | 'paid' | 'void' | (string & {})
  amount_cents: number
  currency_code: string
  period_start: string
  period_end: string
  issued_at: string
  paid_at: string | null
}

export interface BillingUsageItem {
  key: string
  limit: number
  unlimited: boolean
  used: number
  plan_code: string | null
}

export interface BillingEntitlementEntry {
  value: number | boolean
  kind: 'int' | 'bool'
  unlimited: boolean
  plan_code: string | null
}

export interface BillingEntitlementsResponse {
  organization_id: string
  entitlements: Record<string, BillingEntitlementEntry>
}

export interface BillingSubscriptionSnapshot {
  subscription: BillingSubscriptionInfo | null
  usage: BillingUsageItem[]
  resource_counts: { farms: number; fields: number; members: number }
  invoices: BillingInvoice[]
  events: BillingEventInfo[]
}

/** Billing dashboard snapshot: subscription, usage, resource counts, invoices, events. */
export function getBillingSubscription(organizationId: string): Promise<BillingSubscriptionSnapshot> {
  return request<BillingSubscriptionSnapshot>(
    `/api/v1/billing/subscription${qs({ organization_id: organizationId })}`,
  )
}

export interface BillingSubscriptionStartInput {
  organization_id: string
  plan_code: string
  billing_period: BillingPeriod
}

/** Start a subscription (trial or paid). Returns the checkout session (sandbox has no hosted URL). */
export function startBillingSubscription(
  input: BillingSubscriptionStartInput,
): Promise<BillingSubscriptionStartResult> {
  return request<BillingSubscriptionStartResult>('/api/v1/billing/subscription', {
    method: 'POST',
    body: input,
  })
}

export interface BillingSubscriptionChangeInput {
  organization_id: string
  new_plan_code: string
  billing_period?: BillingPeriod | null
}

/** Upgrade/downgrade, effective immediately (sandbox semantics). */
export function changeBillingSubscription(
  input: BillingSubscriptionChangeInput,
): Promise<BillingSubscriptionInfo> {
  return request<BillingSubscriptionInfo>('/api/v1/billing/subscription/change', {
    method: 'POST',
    body: input,
  })
}

export interface BillingSubscriptionCancelInput {
  organization_id: string
  at_period_end?: boolean
}

/** Cancel at period end (default) or immediately. */
export function cancelBillingSubscription(
  input: BillingSubscriptionCancelInput,
): Promise<BillingSubscriptionInfo> {
  return request<BillingSubscriptionInfo>('/api/v1/billing/subscription/cancel', {
    method: 'POST',
    body: input,
  })
}

/** Undo a scheduled period-end cancellation. */
export function resumeBillingSubscription(organizationId: string): Promise<BillingSubscriptionInfo> {
  return request<BillingSubscriptionInfo>('/api/v1/billing/subscription/resume', {
    method: 'POST',
    body: { organization_id: organizationId },
  })
}

/** Usage counters vs entitlements for the current billing period. */
export function getBillingUsage(organizationId: string): Promise<{ items: BillingUsageItem[] }> {
  return request<{ items: BillingUsageItem[] }>(
    `/api/v1/billing/usage${qs({ organization_id: organizationId })}`,
  )
}

/** Effective entitlements resolved from the live subscription. */
export function getBillingEntitlements(
  organizationId: string,
): Promise<BillingEntitlementsResponse> {
  return request<BillingEntitlementsResponse>(
    `/api/v1/billing/entitlements${qs({ organization_id: organizationId })}`,
  )
}

export function listBillingInvoices(
  organizationId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<{ items: BillingInvoice[]; limit: number; offset: number }> {
  return request(`/api/v1/billing/invoices${qs({ organization_id: organizationId, ...params })}`)
}

export type SandboxPayOutcome = 'succeeded' | 'declined'

export interface SandboxPayResult {
  billing_event_id: string
  status: string
  outcome: SandboxPayOutcome
}

/** TEST-MODE ONLY: simulate a provider payment webhook (succeed/decline). */
export function sandboxBillingPay(input: {
  organization_id: string
  outcome: SandboxPayOutcome
}): Promise<SandboxPayResult> {
  return request<SandboxPayResult>('/api/v1/billing/sandbox/pay', { method: 'POST', body: input })
}

// ---------------------------------------------------------------------------
// Analytics (Insights)
// ---------------------------------------------------------------------------

export type Provenance = 'observed' | 'model_derived' | 'simulated' | 'missing' | (string & {})

export interface AnalyticsMetric {
  key: string
  label: string
  value: number | null
  unit: string
  provenance: Provenance
  source: string
  period: { from: string | null; to: string | null }
  note: string | null
}

export interface CropDistributionEntry {
  crop: string
  cycles: number
}

export interface ExecutiveDashboardResponse {
  organization_id: string
  filters: { farm_id: string | null; season: string | null }
  generated_at: string
  metrics: AnalyticsMetric[]
  crop_distribution: CropDistributionEntry[] | null
  recommendations: {
    total_ever: number | null
    active: number | null
    active_by_domain: Record<string, number> | null
    provenance: Provenance
  }
  adoption: {
    provenance: Provenance
    by_state?: Record<string, number>
    acceptance_rate?: number | null
    note?: string
  }
  data_freshness: {
    provenance?: Provenance
    variables: Array<{
      variable: string
      observations: number
      last_observed_at: string | null
      age_days: number | null
      status: string
      provenance: Provenance
      note?: string
    }>
  }
  farm_ids: string[]
  farm_count_total: number
}

export interface ExecutiveDashboardParams {
  organization_id?: string | null
  farm_id?: string | null
  season?: string | null
}

/**
 * Organization-level executive dashboard. NOTE: the endpoint supports
 * organization_id / farm_id / season ONLY — field_id, crop and date filters
 * are rejected with 400 by the API (declared-but-unsupported filters are
 * refused instead of silently ignored).
 */
export function getExecutiveDashboard(params: ExecutiveDashboardParams): Promise<ExecutiveDashboardResponse> {
  return request<ExecutiveDashboardResponse>(
    `/api/v1/analytics/executive-dashboard${qs({
      organization_id: params.organization_id,
      farm_id: params.farm_id,
      season: params.season,
    })}`,
  )
}

export interface FarmPerformanceFieldRow {
  field_id: string
  name: string
  area_ha: number
  observations_in_period: number
  active_recommendations: number
  crop_cycles_started_in_period: number
}

export interface FarmPerformanceWaterBlock {
  precipitation: {
    provenance: Provenance
    total_volume_m3?: number
    per_field?: Array<{ field_id: string; precip_mm: number; volume_m3: number }>
    source?: string
    note?: string
  }
  irrigation: { provenance: Provenance; note: string }
}

export interface FarmPerformanceResponse {
  farm_id: string
  farm_name: string
  period: { from: string; to: string }
  fields: FarmPerformanceFieldRow[]
  metrics: AnalyticsMetric[]
  water_usage: FarmPerformanceWaterBlock
}

/** Per-farm analytics over a period; date_from and date_to are REQUIRED. */
export function getFarmPerformance(
  farmId: string,
  params: { date_from: string; date_to: string },
): Promise<FarmPerformanceResponse> {
  return request<FarmPerformanceResponse>(
    `/api/v1/analytics/farm-performance/${farmId}${qs(params)}`,
  )
}

export interface CommercialMetricsResponse {
  farm_id: string
  period: { from: string; to: string }
  metrics: AnalyticsMetric[]
  assumptions: Record<string, unknown>
  honesty_note: string
}

/**
 * Financial metrics ONLY where defensible. Water cost requires a
 * USER-SUPPLIED water price; cost/ha and yield are always reported missing
 * by the API (never fabricated).
 */
export function getCommercialMetrics(
  farmId: string,
  params: {
    date_from: string
    date_to: string
    water_price_per_m3?: number | null
    currency?: string | null
  },
): Promise<CommercialMetricsResponse> {
  return request<CommercialMetricsResponse>(
    `/api/v1/analytics/commercial-metrics${qs({
      farm_id: farmId,
      date_from: params.date_from,
      date_to: params.date_to,
      water_price_per_m3: params.water_price_per_m3,
      currency: params.currency,
    })}`,
  )
}

export interface BenchmarkEntry {
  id: string
  name: string
  farm?: string
  area_ha: number
  field_count?: number
  active_recommendations: number
}

export interface BenchmarksResponse {
  scope: string
  period: { from: string; to: string }
  metric_definitions: Record<string, string>
  compatibility_note?: string
  entries: BenchmarkEntry[]
  cross_org_anonymized: { provenance: Provenance; note: string }
}

/** Within-organization comparison only (farm or field scope). */
export function getBenchmarks(params: {
  scope: 'farm' | 'field'
  date_from: string
  date_to: string
  organization_id?: string | null
}): Promise<BenchmarksResponse> {
  return request<BenchmarksResponse>(
    `/api/v1/analytics/benchmarks${qs({
      scope: params.scope,
      date_from: params.date_from,
      date_to: params.date_to,
      organization_id: params.organization_id,
    })}`,
  )
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export type ReportStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'expired'

export interface ReportJob {
  id: string
  organization_id: string
  farm_id: string | null
  requested_by: string | null
  report_type: string
  output_format: string
  locale: string
  date_from: string
  date_to: string
  status: ReportStatus
  file_size_bytes: number | null
  error: string | null
  retention_until: string | null
  interval_days: number | null
  next_run_at: string | null
  background_job_id: string | null
  created_at: string | null
  updated_at: string | null
  _links?: Record<string, string>
}

export interface ReportCreateInput {
  report_type: string
  /** Wire alias of `output_format` on the backend model. */
  format: 'pdf' | 'xlsx' | 'csv' | (string & {})
  locale: 'en' | 'ar' | (string & {})
  farm_id?: string | null
  field_id?: string | null
  date_from?: string | null
  date_to?: string | null
  title?: string | null
  /** Inline execution — csv/xlsx only; pdf always queues. */
  sync?: boolean
}

/** Queue (or, with sync=true for csv/xlsx, render immediately). */
export function createReport(input: ReportCreateInput): Promise<ReportJob> {
  return request<ReportJob>('/api/v1/reports', { method: 'POST', body: input })
}

export interface ReportListParams {
  status?: string | null
  report_type?: string | null
  farm_id?: string | null
  limit?: number
  offset?: number
}

export interface ReportListResponse {
  items: ReportJob[]
  total: number
}

export function listReports(params: ReportListParams = {}): Promise<ReportListResponse> {
  return request<ReportListResponse>(`/api/v1/reports${qs({ ...params })}`)
}

export function getReport(jobId: string): Promise<ReportJob> {
  return request<ReportJob>(`/api/v1/reports/${jobId}`)
}

export interface ReportDownload {
  blob: Blob
  filename: string
}

/**
 * Download a succeeded report as a binary blob. The filename is taken from
 * the server's Content-Disposition header (never invented client-side).
 */
export async function downloadReport(jobId: string): Promise<ReportDownload> {
  let response: Response
  try {
    response = await fetch(withPort(`/api/v1/reports/${jobId}/download`), {
      method: 'GET',
      headers: { Accept: 'application/octet-stream' },
      cache: 'no-store',
    })
  } catch {
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the CropTwist API.',
      details: [],
    })
  }
  if (!response.ok) {
    // Error responses are JSON envelopes — surface the structured error.
    let message = `Request failed with status ${response.status}.`
    let code = `HTTP_${response.status}`
    try {
      const envelope = (await response.json()) as ApiErrorBody | null
      if (envelope && typeof envelope === 'object' && 'error' in envelope && envelope.error) {
        message = envelope.error.message ?? message
        code = envelope.error.code ?? code
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError({ status: response.status, code, message, details: [] })
  }
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const asciiMatch = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : asciiMatch
      ? asciiMatch[1]
      : `report_${jobId}`
  return { blob, filename }
}

export function deleteReport(jobId: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/api/v1/reports/${jobId}`, { method: 'DELETE' })
}

/** Re-render an existing job inline (execution errors land on the job row). */
export function regenerateReport(jobId: string): Promise<ReportJob> {
  return request<ReportJob>(`/api/v1/reports/${jobId}/regenerate`, { method: 'POST' })
}

/** Set recurrence in days; null clears the schedule. */
export function scheduleReport(
  jobId: string,
  intervalDays: number | null,
): Promise<ReportJob> {
  return request<ReportJob>(`/api/v1/reports/${jobId}/schedule`, {
    method: 'POST',
    body: { interval_days: intervalDays },
  })
}

// ---------------------------------------------------------------------------
// Developer console
// ---------------------------------------------------------------------------

export interface ApiKeyInfo {
  id: string
  organization_id: string
  name: string
  prefix: string
  scopes: string[]
  status: string
  rate_limit_per_minute: number
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  expires_at: string | null
}

export interface DeveloperKeysResponse {
  items: ApiKeyInfo[]
  total: number
}

export function listDeveloperKeys(
  organizationId?: string | null,
): Promise<DeveloperKeysResponse> {
  return request<DeveloperKeysResponse>(`/api/v1/developer/keys${qs({ organization_id: organizationId })}`)
}

export interface ApiKeySecretResponse {
  key: ApiKeyInfo
  /** Plaintext — returned ONCE by the API; never retrievable again. */
  secret: string
}

export function createDeveloperKey(input: {
  name: string
  scopes: string[]
  organization_id?: string | null
}): Promise<ApiKeySecretResponse> {
  return request<ApiKeySecretResponse>('/api/v1/developer/keys', {
    method: 'POST',
    body: input,
  })
}

export function revokeDeveloperKey(
  keyId: string,
  organizationId?: string | null,
): Promise<{ key: ApiKeyInfo }> {
  return request(`/api/v1/developer/keys/${keyId}${qs({ organization_id: organizationId })}`, {
    method: 'DELETE',
  })
}

export function rotateDeveloperKey(
  keyId: string,
  organizationId?: string | null,
): Promise<ApiKeySecretResponse> {
  return request<ApiKeySecretResponse>(`/api/v1/developer/keys/${keyId}/rotate${qs({ organization_id: organizationId })}`, {
    method: 'POST',
  })
}

export interface WebhookEndpointInfo {
  id: string
  organization_id: string
  url: string
  event_types: string[]
  status: string
  description: string
  consecutive_failures: number
  disabled_reason: string | null
  created_at: string | null
  updated_at: string | null
}

export interface WebhooksResponse {
  items: WebhookEndpointInfo[]
  total: number
}

export function listWebhooks(organizationId?: string | null): Promise<WebhooksResponse> {
  return request<WebhooksResponse>(`/api/v1/developer/webhooks${qs({ organization_id: organizationId })}`)
}

export interface WebhookSecretResponse {
  endpoint: WebhookEndpointInfo
  /** Signing secret — returned ONCE by the API. */
  secret: string
}

export function createWebhook(input: {
  url: string
  events: string[]
  description?: string
  organization_id?: string | null
}): Promise<WebhookSecretResponse> {
  return request<WebhookSecretResponse>('/api/v1/developer/webhooks', {
    method: 'POST',
    body: input,
  })
}

export interface WebhookPatchInput {
  enabled?: boolean | null
  events?: string[] | null
  description?: string | null
  url?: string | null
}

export function patchWebhook(
  endpointId: string,
  patch: WebhookPatchInput,
  organizationId?: string | null,
): Promise<{ endpoint: WebhookEndpointInfo }> {
  return request(`/api/v1/developer/webhooks/${endpointId}${qs({ organization_id: organizationId })}`, {
    method: 'PATCH',
    body: patch,
  })
}

export function deleteWebhook(
  endpointId: string,
  organizationId?: string | null,
): Promise<{ deleted: boolean; id: string }> {
  return request(`/api/v1/developer/webhooks/${endpointId}${qs({ organization_id: organizationId })}`, {
    method: 'DELETE',
  })
}

export function rotateWebhookSecret(
  endpointId: string,
  organizationId?: string | null,
): Promise<WebhookSecretResponse> {
  return request<WebhookSecretResponse>(
    `/api/v1/developer/webhooks/${endpointId}/rotate-secret${qs({ organization_id: organizationId })}`,
    { method: 'POST' },
  )
}

export interface WebhookDelivery {
  id: string
  endpoint_id: string
  event_type: string
  event_id: string
  status: 'pending' | 'delivered' | 'failed' | 'dead' | (string & {})
  attempt: number
  next_retry_at: string | null
  delivered_at: string | null
  last_status_code: number | null
  last_error: string | null
  created_at: string | null
}

export interface WebhookDeliveriesResponse {
  items: WebhookDelivery[]
  total: number
  limit: number
  offset: number
}

export function listWebhookDeliveries(
  endpointId: string,
  organizationId?: string | null,
  params: { status?: string | null; limit?: number; offset?: number } = {},
): Promise<WebhookDeliveriesResponse> {
  return request<WebhookDeliveriesResponse>(
    `/api/v1/developer/webhooks/${endpointId}/deliveries${qs({
      organization_id: organizationId,
      ...params,
    })}`,
  )
}

export function redeliverWebhookDelivery(
  endpointId: string,
  deliveryId: string,
  organizationId?: string | null,
): Promise<{ delivery: WebhookDelivery }> {
  return request(
    `/api/v1/developer/webhooks/${endpointId}/deliveries/${deliveryId}/redeliver${qs({
      organization_id: organizationId,
    })}`,
    { method: 'POST' },
  )
}

export interface DeveloperUsageKey {
  id: string
  name: string
  prefix: string
  status: string
  scopes: string[]
  rate_limit_per_minute: number
  usage: Array<{ day: string; request_count: number }>
}

export interface DeveloperUsageResponse {
  organization_id: string
  window_days: number
  rate_limit: {
    api_rate_limit_per_minute: number
    unlimited: boolean
    api_enabled: boolean
    plan_code: string | null
    note: string
  }
  keys: DeveloperUsageKey[]
}

/** Per-key daily request counters + rate-limit entitlement info. */
export function getDeveloperUsage(
  organizationId?: string | null,
  days?: number | null,
): Promise<DeveloperUsageResponse> {
  return request<DeveloperUsageResponse>(`/api/v1/developer/usage${qs({ organization_id: organizationId, days })}`)
}

export interface DeveloperEventsResponse {
  events: string[]
  scopes: string[]
}

/** Catalog of supported webhook event types + API key scopes. */
export function getDeveloperEvents(): Promise<DeveloperEventsResponse> {
  return request<DeveloperEventsResponse>('/api/v1/developer/events', { anonymous: true })
}

/**
 * P3 Workstream A (Account sphere) — typed fetch functions for organizations,
 * members, invitations, activity, onboarding, notifications and preferences.
 *
 * Mirrors the fetch pattern in src/lib/api.ts: RELATIVE paths carrying the
 * `XTransformPort=3030` gateway parameter, cookies attached automatically
 * (HttpOnly session cookies), one transparent 401 -> cookie-refresh retry,
 * and structured error envelopes surfaced through the shared ApiError class.
 *
 * Contract source (read-only):
 *   mini-services/fieldshift-api/app/api/v1/{orgs,onboarding,notifications,preferences,activity}.py
 *   mini-services/fieldshift-api/app/{orgs,onboarding,notifications,preferences}/service.py
 */
import { ApiError, refreshSession } from './api'
import type { ApiErrorBody } from './types'

// ---------------------------------------------------------------------------
// Shared request plumbing (mirrors src/lib/api.ts — do not duplicate tokens
// here; authentication is HttpOnly-cookie based)
// ---------------------------------------------------------------------------

const PORT_QUERY = 'XTransformPort=3030'

function withPort(path: string): string {
  const joiner = path.includes('?') ? '&' : '?'
  return `${path}${joiner}${PORT_QUERY}`
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  skipAuthRetry = false,
): Promise<T> {
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
    // Rotating-refresh retry: same policy as src/lib/api.ts (one transparent
    // cookie refresh, then a single retry of the original request).
    if (response.status === 401 && !skipAuthRetry) {
      const refreshed = await refreshSession()
      if (refreshed) return request<T>(path, options, true)
    }
    const code = error?.code ?? `HTTP_${response.status}`
    const message = error?.message ?? `Request failed with status ${response.status}.`
    void notifyPaymentRequired(response.status, code, message)
    throw new ApiError({
      status: response.status,
      code,
      message,
      details: error?.details ?? [],
      requestId: error?.request_id,
    })
  }

  return payload as T
}

/**
 * P3 entitlement guard: fan 402 PAYMENT_REQUIRED out to the global
 * listener (workspace). Same contract as api-p3-commercial.ts.
 */
async function notifyPaymentRequired(status: number, code: string, message: string): Promise<void> {
  if (status !== 402 && code !== 'PAYMENT_REQUIRED') return
  const match = /'([a-z_]+)'/.exec(message)
  const { emitPaymentRequired } = await import('./entitlement-guard')
  emitPaymentRequired({ entitlement: match?.[1], message })
}

/** Append defined query parameters (skips undefined/null/empty values). */
function withQuery(
  path: string,
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    qs.set(key, String(value))
  }
  const encoded = qs.toString()
  return encoded ? `${path}?${encoded}` : path
}

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------

export type OrganizationType = 'individual' | 'business' | 'farm_org'

/** 7-role RBAC set (migration 0020; app/domains/identity/service.py ROLE_ORDER). */
export type OrgRoleCode =
  | 'viewer'
  | 'analyst'
  | 'agronomist'
  | 'operator'
  | 'manager'
  | 'org_admin'
  | 'owner'

/** Rank of each role — "at least as privileged as" comparisons (frontend UX
 * gating only; the server is the authority). */
export const ORG_ROLE_RANK: Record<OrgRoleCode, number> = {
  viewer: 0,
  analyst: 1,
  agronomist: 1,
  operator: 2,
  manager: 2,
  org_admin: 3,
  owner: 3,
}

export function roleAtLeast(role: OrgRoleCode | null | undefined, minimum: OrgRoleCode): boolean {
  if (!role) return false
  return ORG_ROLE_RANK[role] >= ORG_ROLE_RANK[minimum]
}

export interface Organization {
  id: string
  name: string
  organization_type: OrganizationType
  country_code: string | null
  created_at: string
  updated_at: string
  my_role: OrgRoleCode | null
}

export interface OrganizationListResponse {
  items: Organization[]
  total: number
}

export interface OrganizationCreateInput {
  name: string
  organization_type: OrganizationType
  country_code?: string | null
}

export interface OrganizationPatchInput {
  name?: string
  organization_type?: OrganizationType
  country_code?: string | null
}

export async function listOrganizations(): Promise<OrganizationListResponse> {
  return request<OrganizationListResponse>('/api/v1/orgs')
}

export async function createOrganization(input: OrganizationCreateInput): Promise<Organization> {
  return request<Organization>('/api/v1/orgs', { method: 'POST', body: input })
}

export async function getOrganization(orgId: string): Promise<Organization> {
  return request<Organization>(`/api/v1/orgs/${orgId}`)
}

export async function patchOrganization(
  orgId: string,
  input: OrganizationPatchInput,
): Promise<Organization> {
  return request<Organization>(`/api/v1/orgs/${orgId}`, { method: 'PATCH', body: input })
}

// ---------------------------------------------------------------------------
// Organization members + ownership transfer
// ---------------------------------------------------------------------------

export interface OrganizationMember {
  id: string
  user_id: string
  email: string | null
  display_name: string | null
  role_code: OrgRoleCode
  joined_at: string
}

export interface OrganizationMemberListResponse {
  items: OrganizationMember[]
  total: number
}

export async function listOrganizationMembers(
  orgId: string,
): Promise<OrganizationMemberListResponse> {
  return request<OrganizationMemberListResponse>(`/api/v1/orgs/${orgId}/members`)
}

/** Body key is `role_code` (MemberRolePatch in app/api/v1/orgs.py). */
export async function patchOrganizationMemberRole(
  orgId: string,
  userId: string,
  roleCode: OrgRoleCode,
): Promise<OrganizationMember> {
  return request<OrganizationMember>(`/api/v1/orgs/${orgId}/members/${userId}`, {
    method: 'PATCH',
    body: { role_code: roleCode },
  })
}

/** 204 No Content on success. */
export async function removeOrganizationMember(orgId: string, userId: string): Promise<void> {
  await request<null>(`/api/v1/orgs/${orgId}/members/${userId}`, { method: 'DELETE' })
}

export interface OwnershipTransferResponse {
  organization_id: string
  new_owner_membership_id: string
  new_owner_user_id: string
  new_owner_email: string | null
  previous_owner_role: OrgRoleCode
}

/** Body key is `target_user_id` (OwnershipTransfer in app/api/v1/orgs.py). */
export async function transferOrganizationOwnership(
  orgId: string,
  targetUserId: string,
): Promise<OwnershipTransferResponse> {
  return request<OwnershipTransferResponse>(`/api/v1/orgs/${orgId}/ownership-transfer`, {
    method: 'POST',
    body: { target_user_id: targetUserId },
  })
}

// ---------------------------------------------------------------------------
// Invitations
// ---------------------------------------------------------------------------

export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired'

export interface OrganizationInvitation {
  id: string
  organization_id: string
  email: string
  role_code: OrgRoleCode
  status: InvitationStatus
  invited_by: string | null
  expires_at: string | null
  accepted_at: string | null
  revoked_at: string | null
  created_at: string
  /** Plaintext token — returned ONCE on creation only (out-of-band delivery). */
  token?: string
  note?: string
}

export interface InvitationListResponse {
  items: OrganizationInvitation[]
  total: number
}

export interface InvitationCreateInput {
  email: string
  role_code: OrgRoleCode
}

export async function listOrganizationInvitations(
  orgId: string,
  status?: InvitationStatus,
): Promise<InvitationListResponse> {
  return request<InvitationListResponse>(
    withQuery(`/api/v1/orgs/${orgId}/invitations`, { invitation_status: status }),
  )
}

export async function createInvitation(
  orgId: string,
  input: InvitationCreateInput,
): Promise<OrganizationInvitation> {
  return request<OrganizationInvitation>(`/api/v1/orgs/${orgId}/invitations`, {
    method: 'POST',
    body: input,
  })
}

/** 204 No Content on success (pending invitations only). */
export async function revokeInvitation(orgId: string, invitationId: string): Promise<void> {
  await request<null>(`/api/v1/orgs/${orgId}/invitations/${invitationId}`, { method: 'DELETE' })
}

export interface InvitationAcceptResponse {
  id: string
  organization_id: string
  user_id: string
  role_code: OrgRoleCode
  status: string
  joined_at: string
}

export async function acceptInvitation(token: string): Promise<InvitationAcceptResponse> {
  return request<InvitationAcceptResponse>('/api/v1/invitations/accept', {
    method: 'POST',
    body: { token },
  })
}

// ---------------------------------------------------------------------------
// Organization activity timeline
// ---------------------------------------------------------------------------

export interface OrganizationActivityEvent {
  id: string
  event_type: string
  entity_kind: string
  entity_id: string | null
  summary: string
  details: Record<string, unknown> | null
  farm_id: string | null
  actor_user_id: string | null
  created_at: string
}

export interface OrganizationActivityListResponse {
  items: OrganizationActivityEvent[]
  total: number
  limit: number
  offset: number
}

export async function listOrganizationActivity(
  orgId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<OrganizationActivityListResponse> {
  return request<OrganizationActivityListResponse>(
    withQuery(`/api/v1/orgs/${orgId}/activity`, {
      limit: params.limit,
      offset: params.offset,
    }),
  )
}

// ---------------------------------------------------------------------------
// Onboarding (user-scoped, resumable state machine)
// ---------------------------------------------------------------------------

export type OnboardingStepId =
  | 'account'
  | 'account_type'
  | 'organization'
  | 'org_profile'
  | 'first_farm'
  | 'first_field'
  | 'crops_priorities'
  | 'review'
  | 'tour'

export interface OnboardingStepState {
  id: OnboardingStepId
  required: boolean
  done: boolean
  skipped: boolean
  at: string | null
}

export interface OnboardingProgress {
  account_type: OrganizationType | null
  current_step: OnboardingStepId
  completed_at: string | null
  dismissed: boolean
  steps: OnboardingStepState[]
}

export async function getOnboardingProgress(): Promise<OnboardingProgress> {
  return request<OnboardingProgress>('/api/v1/onboarding/progress')
}

export async function completeOnboardingStep(
  step: OnboardingStepId,
  data?: Record<string, unknown>,
): Promise<OnboardingProgress> {
  return request<OnboardingProgress>(`/api/v1/onboarding/steps/${step}/complete`, {
    method: 'POST',
    body: data ? { data } : undefined,
  })
}

export async function skipOnboardingStep(step: OnboardingStepId): Promise<OnboardingProgress> {
  return request<OnboardingProgress>(`/api/v1/onboarding/skip/${step}`, { method: 'POST' })
}

export async function setOnboardingAccountType(
  accountType: OrganizationType,
): Promise<OnboardingProgress> {
  return request<OnboardingProgress>('/api/v1/onboarding/account-type', {
    method: 'POST',
    body: { account_type: accountType },
  })
}

export async function dismissOnboarding(): Promise<OnboardingProgress> {
  return request<OnboardingProgress>('/api/v1/onboarding/dismiss', { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Notifications (org-scoped or user-addressed; org defaults to the oldest
// active organization server-side)
// ---------------------------------------------------------------------------

export type NotificationSeverity = 'info' | 'advisory' | 'warning' | 'critical'
export type NotificationCategory =
  | 'agronomic_alert'
  | 'data_freshness'
  | 'recommendation_update'
  | 'report_ready'
  | 'invitation'
  | 'subscription'
  | 'billing'
  | 'system'

export const NOTIFICATION_CATEGORIES: NotificationCategory[] = [
  'agronomic_alert',
  'data_freshness',
  'recommendation_update',
  'report_ready',
  'invitation',
  'subscription',
  'billing',
  'system',
]

export interface NotificationItem {
  id: string
  category: NotificationCategory
  severity: NotificationSeverity
  title: string
  body: string
  link_kind: string | null
  link_id: string | null
  read: boolean
  read_at: string | null
  expires_at: string | null
  created_at: string
}

export interface NotificationListResponse {
  items: NotificationItem[]
  total: number
  unread: number
  limit: number
  offset: number
  organization_id: string
}

export interface NotificationListParams {
  unread_only?: boolean
  severity?: NotificationSeverity
  category?: NotificationCategory
  limit?: number
  offset?: number
  organization_id?: string
}

export async function listNotifications(
  params: NotificationListParams = {},
): Promise<NotificationListResponse> {
  return request<NotificationListResponse>(
    withQuery('/api/v1/notifications', {
      unread_only: params.unread_only,
      severity: params.severity,
      category: params.category,
      limit: params.limit,
      offset: params.offset,
      organization_id: params.organization_id,
    }),
  )
}

export async function markNotificationRead(
  notificationId: string,
  read = true,
): Promise<NotificationItem> {
  return request<NotificationItem>(`/api/v1/notifications/${notificationId}/read`, {
    method: 'POST',
    body: { read },
  })
}

export interface MarkAllReadResponse {
  marked: number
  organization_id: string
}

export async function markAllNotificationsRead(): Promise<MarkAllReadResponse> {
  return request<MarkAllReadResponse>('/api/v1/notifications/read-all', { method: 'POST' })
}

export interface NotificationUnreadCount {
  unread: number
  organization_id: string
}

export async function getUnreadNotificationCount(): Promise<NotificationUnreadCount> {
  return request<NotificationUnreadCount>('/api/v1/notifications/unread-count')
}

export interface NotificationPreferenceItem {
  category: NotificationCategory
  in_app_enabled: boolean
  email_enabled: boolean
}

export interface NotificationPreferenceListResponse {
  items: NotificationPreferenceItem[]
}

export async function getNotificationPreferences(): Promise<NotificationPreferenceListResponse> {
  return request<NotificationPreferenceListResponse>('/api/v1/notifications/preferences')
}

export interface NotificationPreferenceUpdateInput {
  category: NotificationCategory
  in_app_enabled?: boolean | null
  email_enabled?: boolean | null
}

export async function putNotificationPreference(
  input: NotificationPreferenceUpdateInput,
): Promise<NotificationPreferenceItem> {
  return request<NotificationPreferenceItem>('/api/v1/notifications/preferences', {
    method: 'PUT',
    body: input,
  })
}

// ---------------------------------------------------------------------------
// User preferences (global product configuration, P3 §9.2)
// ---------------------------------------------------------------------------

export type UnitSystem = 'metric' | 'imperial'
export type WeekStart = 'monday' | 'sunday' | 'saturday'

export interface UserPreferences {
  locale: string
  timezone: string
  unit_system: UnitSystem
  currency_code: string
  country_code: string | null
  week_start: WeekStart
  agricultural_calendar: string | null
  notifications: { in_app: boolean; email: boolean }
}

export interface PreferencesUpdateInput {
  locale?: string
  timezone?: string
  unit_system?: UnitSystem
  currency_code?: string
  country_code?: string | null
  week_start?: WeekStart
  agricultural_calendar?: string | null
  notify_in_app?: boolean
  notify_email?: boolean
}

export async function getPreferences(): Promise<UserPreferences> {
  return request<UserPreferences>('/api/v1/preferences')
}

export async function updatePreferences(
  input: PreferencesUpdateInput,
): Promise<UserPreferences> {
  return request<UserPreferences>('/api/v1/preferences', { method: 'PUT', body: input })
}

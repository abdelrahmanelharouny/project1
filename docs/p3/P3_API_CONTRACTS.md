# P3 API Contracts — SaaS platform routers

Concise endpoint reference for the 10 P3 routers registered in
`app/api/v1/router.py` (all mounted under the global prefix `/api/v1`).
Derived from the route decorators + Pydantic models + service gates.

Auth shorthand:
- **public** — no authentication.
- **user** — `get_principal` (Bearer token or `fs_token` HttpOnly cookie).
- **viewer+ / manager+ / org_admin+** — user + `principal.require_org_role(org_id, role)` enforced inside the service; "member" = any active membership.
- **key(scope)** — public API key (`Authorization: Bearer ctk_…` or `X-API-Key`) with the required scope; per-key 60 s sliding-window throttle; tenant = key's organization.

Errors everywhere: `{"error":{code,message,details,request_id}}`. `402 PAYMENT_REQUIRED` = entitlement paywall. Unknown error semantics are not repeated per row.

## 1. orgs — `app/api/v1/orgs.py` (tags `orgs`)

| METHOD /path | Auth | Request → Response |
|---|---|---|
| POST `/orgs` | user | `{name, organization_type: individual\|business\|farm_org, country_code?}` → 201 `{id,name,organization_type,country_code,created_at,updated_at,my_role:"owner"}` |
| GET `/orgs` | user | — → `{items:[Organization…], total}` (`my_role` per org) |
| GET `/orgs/{org_id}` | member | — → Organization |
| PATCH `/orgs/{org_id}` | org_admin+ | `{name?, organization_type?, country_code?}` → Organization |
| GET `/orgs/{org_id}/members` | member | — → `{items:[{user_id,email,display_name,role_code,joined_at}…], total}` |
| PATCH `/orgs/{org_id}/members/{user_id}` | org_admin+ (owner grants owner/org_admin) | `{role_code}` (one of the 7 roles) → member dict |
| DELETE `/orgs/{org_id}/members/{user_id}` | org_admin+ (owner removes owner) | — → 204 |
| POST `/orgs/{org_id}/ownership-transfer` | owner | `{target_user_id}` → `{organization_id, previous_owner, new_owner, new_owner_role:"owner"}` (previous owner → org_admin) |
| POST `/orgs/{org_id}/invitations` | org_admin+ | `{email, role_code}` → 201 Invitation + `token` (plaintext, shown once) + `note` |
| GET `/orgs/{org_id}/invitations` | org_admin+ | `?status=` → `{items:[Invitation…], total}` (≤200, newest first) |
| DELETE `/orgs/{org_id}/invitations/{invitation_id}` | org_admin+ | — → Invitation (status `revoked`) |
| POST `/invitations/accept` | user (email must match invite) | `{token}` → Membership payload |

## 2. billing — `app/api/v1/billing.py` (prefix `/billing`, tags `billing`)

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/billing/plans` | public | — → `{items:[{code,name,description,sort_order,trial_days,prices:{monthly:{amount_cents,currency_code}\|null, yearly…}, entitlements:{key:value}}]}` (`amount_cents null` = contact sales) |
| GET `/billing/subscription` | org_admin+ | `?organization_id` → snapshot `{subscription(+plan,provider_mode), usage[], resource_counts{farms,fields,members}, invoices[], events[]}` |
| POST `/billing/subscription` | org_admin+ | `{organization_id, plan_code, billing_period: monthly\|yearly}` → `{subscription, checkout{session_id,provider,url(null in sandbox),mode:"test"}}` (409 if a live subscription exists) |
| POST `/billing/subscription/change` | org_admin+ | `{organization_id, new_plan_code, billing_period?}` → Subscription (immediate; no proration) |
| POST `/billing/subscription/cancel` | org_admin+ | `{organization_id, at_period_end=true}` → Subscription |
| POST `/billing/subscription/resume` | org_admin+ | `{organization_id}` → Subscription |
| GET `/billing/invoices` | org_admin+ | `?organization_id&limit≤200&offset` → `{items:[Invoice…], limit, offset}` |
| GET `/billing/usage` | org_admin+ | `?organization_id` → `{items:[{key,limit,unlimited,used,plan_code}]}` |
| GET `/billing/entitlements` | org_admin+ | `?organization_id` → `{organization_id, entitlements:{key:{value,kind,unlimited,plan_code}}}` |
| POST `/billing/sandbox/pay` | org_admin+ **and** active provider is sandbox (else 403) | `{organization_id, outcome: succeeded\|declined}` → `{billing_event_id, status, outcome}` |
| POST `/billing/webhook` | public + HMAC signature (`x-croptwist-signature: "<ts>.<hmac_hex>"`) | raw JSON `{event_type\|type, event_id\|id, …}` (≤256 KiB) → `{received:true,id,status}` (status `received/processed/failed/duplicate`; bad signature 403) |

## 3. onboarding — `app/api/v1/onboarding.py` (prefix `/onboarding`) — all user-scoped

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/onboarding/progress` | user | — → `{current_step, completed_at, dismissed, steps:[{id,required,done,skipped,at}]}` (row created on first access) |
| POST `/onboarding/steps/{step}/complete` | user | `{data?}` (body optional) → progress (unknown step → 422) |
| POST `/onboarding/skip/{step}` | user | — → progress (required steps refused) |
| POST `/onboarding/account-type` | user | `{account_type: individual\|business\|farm_org}` → progress |
| POST `/onboarding/dismiss` | user | — → progress (`dismissed=true`) |

Steps (service truth): `account`(auto) → `account_type`* → `organization`* → `org_profile` → `first_farm`* → `first_field` → `crops_priorities` → `review`* → `tour` (* required).

## 4. notifications — `app/api/v1/notifications.py` (prefix `/notifications`) — user; org defaults to oldest active membership

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/notifications` | member | `?organization_id&unread_only&category&severity&limit&offset` → `{items:[Notification…], total, unread}` (categories: agronomic_alert, data_freshness, recommendation_update, report_ready, invitation, subscription, billing, system; severities: info, advisory, warning, critical) |
| POST `/notifications/{notification_id}/read` | member | `{read=true}` → Notification |
| POST `/notifications/read-all` | member | — → `{updated: n}` |
| GET `/notifications/unread-count` | member | — → `{unread: n}` (403 when the caller has no org) |
| GET `/notifications/preferences` | user | — → `{items:[{category, in_app_enabled, email_enabled}]}` (all 8 categories) |
| PUT `/notifications/preferences` | user | `{category, in_app_enabled?, email_enabled?}` → preference item |

## 5. analytics — `app/api/v1/analytics.py` (prefix `/analytics`) — membership-gated in the service; every metric carries `provenance` (observed/model_derived/simulated/missing)

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/analytics/executive-dashboard` | member | `?organization_id?&farm_id?&season?` (passing `field_id`/`crop`/`date_from`/`date_to` → 400) → dashboard `{period, metrics[], crop_distribution[], recommendations{…}, data_freshness[], rendering_notes[]}` |
| GET `/analytics/farm-performance/{farm_id}` | member (farm) | `?date_from&date_to` (both **required**, ISO dates) → `{farm, period, metrics[], fields[], water{…}}` |
| GET `/analytics/commercial-metrics` | member | `?farm_id&date_from&date_to&water_price_per_m3?&currency?` → `{metrics[], assumptions{}, honesty_note}` (cost_per_hectare & yield always `missing`) |
| GET `/analytics/benchmarks` | member | `?scope=farm\|field&date_from&date_to&organization_id?` → `{scope, entries[], metric_definitions, cross_org_anonymized:{provenance:"missing"}}` |

## 6. preferences — `app/api/v1/preferences.py` (prefix `/preferences`) — user-scoped

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/preferences` | user | — → `{locale, timezone, currency_code, country_code, unit_system, week_start, agricultural_calendar, notifications:{in_app,email}, updated_at}` |
| PUT `/preferences` | user | any subset of `{locale(en/ar), timezone, unit_system(metric/imperial), currency_code, country_code, week_start(monday/sunday/saturday), agricultural_calendar\|null, notify_in_app, notify_email}` → same shape (explicit nulls clear nullable fields) |

## 7. activity — `app/api/v1/activity.py` (tags `activity`)

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/orgs/{org_id}/activity` | member | `?farm_id?&event_type?&limit(1..200)&offset` → `{items:[{id,event_type,summary,actor_user_id,farm_id,entity_kind,entity_id,details,created_at}…], total, limit, offset}` (append-only; newest first) |

## 8. reports — `app/api/v1/reports.py` (prefix `/reports`) — viewer+ to read/create, delete/schedule gated in the service (manager+)

| METHOD /path | Auth | Request → Response |
|---|---|---|
| POST `/reports` | member (viewer+; org resolved from farm/field/org or single membership) | `{report_type(10 types), format: pdf\|xlsx\|csv (wire alias), locale en/ar, farm_id?, field_id?, date_from?, date_to?, title?, sync?}` → 201 job payload + `_links{self,download,status}`. `sync=true` (csv/xlsx only; pdf → 422) renders inline — failures still 201 with `status:"failed"` + `error` |
| GET `/reports` | member | `?status?&report_type?&farm_id?&limit&offset` → `{items:[job…], total}` |
| GET `/reports/{job_id}` | member | — → job payload (`status`, `error`, `file_size_bytes`, `retention_until`, `next_run_at`, …) |
| GET `/reports/{job_id}/status` | member | — → `{id,status,error,file_size_bytes,retention_until,next_run_at}` |
| GET `/reports/{job_id}/download` | member | — → binary stream (`Content-Disposition` attachment; 410 once `expired`) |
| DELETE `/reports/{job_id}` | manager+ (service gate) | — → `{deleted:true,id}` |
| POST `/reports/{job_id}/regenerate` | member | — → job payload + `rendered: bool` (inline re-render) |
| POST `/reports/{job_id}/schedule` | manager+ (service gate) | `{interval_days: 7\|30\|null}` → job payload (`null` clears recurrence) |

Report types: `farm_performance, field_analysis, soil_health, water, rotation, seasonal, environmental_risk, recommendations, org_executive, custom_range`.

## 9. developer — `app/api/v1/developer.py` (prefix `/developer`) — user; mutations gated org_admin+ in the services; org defaults/ambiguity resolved via `resolve_org_id`

| METHOD /path | Auth | Request → Response |
|---|---|---|
| POST `/developer/keys` | org_admin+ | `{name, scopes[≥1], organization_id?}` → 201 `{key:{…no hash…}, secret:"ctk_…"}` (plaintext once) |
| GET `/developer/keys` | member | `?organization_id?` → `{items:[key…], total}` |
| DELETE `/developer/keys/{key_id}` | org_admin+ | `?organization_id?` → `{key}` (status `revoked`, idempotent) |
| POST `/developer/keys/{key_id}/rotate` | org_admin+ | `?organization_id?` → `{key, secret}` (new plaintext once; old key revoked immediately) |
| POST `/developer/webhooks` | org_admin+ | `{url(https), events[≥1 of 7 catalog events], description?, organization_id?}` → 201 `{endpoint, secret:"whsec_…"}` |
| GET `/developer/webhooks` | member | `?organization_id?` → `{items:[endpoint…], total}` |
| PATCH `/developer/webhooks/{endpoint_id}` | org_admin+ | `?organization_id?` + `{enabled?, events?, description?, url?}` → `{endpoint}` (re-enable clears `disabled_reason`) |
| DELETE `/developer/webhooks/{endpoint_id}` | org_admin+ | `?organization_id?` → `{deleted:true,id}` |
| POST `/developer/webhooks/{endpoint_id}/rotate-secret` | org_admin+ | `?organization_id?` → `{endpoint, secret}` |
| GET `/developer/webhooks/{endpoint_id}/deliveries` | member | `?status?&limit&offset` → `{items:[delivery…], total, limit, offset}` |
| POST `/developer/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver` | org_admin+ | `?organization_id?` → `{delivery}` |
| GET `/developer/usage` | member | `?organization_id?&days(1..90, default 30)` → `{organization_id, window_days, rate_limit{api_rate_limit_per_minute, unlimited, api_enabled, plan_code, note}, keys:[{id,name,prefix,status,scopes,rate_limit_per_minute,usage:[{day,request_count}]}]}` |
| GET `/developer/events` | public (no deps) | — → `{events:[7 webhook event types], scopes:[8 API key scopes]}` |

Webhook event catalog: `farm.updated, field.created, crop_cycle.updated, recommendation.generated, report.ready, alert.raised, subscription.updated` — **emitted today: only `report.ready` and `subscription.updated`**.

## 10. public_v1 — `app/api/v1/public_v1.py` (prefix `/public/v1`, tags `public-api`) — key(scope), read-only

| METHOD /path | Auth | Request → Response |
|---|---|---|
| GET `/public/v1/org` | key(org:read) | — → `{id,name,type,country_code}` |
| GET `/public/v1/farms` | key(farms:read) | `?limit≤100&offset` → `{items:[farm…],total,limit,offset}` |
| GET `/public/v1/farms/{farm_id}` | key(farms:read) | — → farm detail (+`preferred_language`) |
| GET `/public/v1/fields` | key(fields:read) | `?farm_id?&limit&offset` → page of `{id,farm_id,name,area_ha,status,created_at}` |
| GET `/public/v1/crop-cycles` | key(crops:read) | `?field_id?&active?&limit&offset` → page of CropHistory rows |
| GET `/public/v1/recommendations` | key(recommendations:read) | `?farm_id?&field_id?&limit&offset` → page of active `AIRecommendation` rows |
| GET `/public/v1/analytics/executive` | key(analytics:read) | `?farm_id?&season?` → executive dashboard (same payload as the session-auth route) |
| GET `/public/v1/reports` | key(reports:read) | `?limit&offset` → page of **succeeded** report metadata (no file paths) |
| GET `/public/v1/environmental-metrics` | key(environment:read) | `?field_id&from?&to?` (window ≤ 366 d) → `{field_id,from,to,variables:[{variable_code,unit,samples,min,mean,max,first_observed_at,last_observed_at}]}` |

Tenant isolation: every query filters by the key's `organization_id`; cross-tenant ids are **404** (never 403). Rate limiting is per key (429 + `Retry-After`).

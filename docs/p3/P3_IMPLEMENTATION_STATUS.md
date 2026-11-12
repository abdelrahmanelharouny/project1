# P3 Implementation Status — Commercial SaaS Platform

Scope: P3 backend (`mini-services/fieldshift-api`) + P3 frontend (`src/`). Every claim below is
traceable to a file path in this repo or to an agent note under `agent-ctx/`. Unverified items are
marked **TBD**; nothing here is a test result (see `P3_TEST_AND_VERIFICATION.md` for the
verification structure, which the integrator fills).

Companion docs: `docs/p3/P3_API_CONTRACTS.md` (endpoint reference) ·
`docs/p3/P3_TEST_AND_VERIFICATION.md` (verification plan) ·
`agent-ctx/p3-foundation-contracts.md` (backend contract snapshot) ·
`agent-ctx/P3-6a-notes.md` / `agent-ctx/P3-6b-notes.md` (frontend build notes).

Legend per feature: **DONE** (implemented, file path given) · **PARTIAL** (implemented with the
stated gap) · **NOT IMPLEMENTED** (honest absence).

---

## W1 — Commercial SaaS Foundation

| Feature | Status | Where / Notes |
|---|---|---|
| P3 DB models (16 tables) | DONE | `app/db/models_p3.py` (584 lines): plans, plan_prices, plan_entitlements, subscriptions, subscription_events, invoices, billing_events, usage_counters, invitations, activity_events, notifications, notification_preferences, report_jobs, api_keys (+api_key_usage), webhook_endpoints, webhook_deliveries, onboarding_progress, user_preferences. Tenant tables carry `organization_id` FK+index; money = integer minor units + ISO currency; no raw card data anywhere |
| Migration | DONE | `migrations/versions/0020_p3_saas_platform.py` — alembic head. Additive: `users.is_platform_admin` (server_default false), membership role check widened to the 7-role superset (old 4-role codes stay valid); creates the 16 tables; `downgrade()` restores the original check |
| Plan catalog as DB data | DONE | Migration `_seed_default_plans()` seeds 5 public plans: `free` (0), `starter` (1900¢/mo, 14-day trial), `professional` (4900¢/mo, 14-day trial), `business` (14900¢/mo, 14-day trial), `enterprise` (no price rows ⇒ "contact sales"). Yearly price = monthly×10. Enforcement reads current DB rows, never code constants. **Runtime parity seeder** `app/billing/catalog.py` (insert-missing-only, values identical to the migration) covers databases built via `create_all`+stamp — wired into app lifespan and conftest |
| Entitlement keys (13) | DONE | `app/billing/entitlements.py` — 8 int keys (max_farms, max_fields, max_org_members, history_retention_years, scenario_runs_per_month, reports_per_month, api_rate_limit_per_minute, ai_messages_per_day; -1 = unlimited) + 5 bool keys (advanced_analysis, satellite_access, api_enabled, exports_enabled, analytics_access). Full per-plan matrix in the migration seed |
| Structured error for paywalls | DONE | `app/core/errors.py`: `PaymentRequired` → HTTP 402, code `PAYMENT_REQUIRED`; error envelope unchanged |
| Platform-admin flag | PARTIAL | Column + migration exist (`users.is_platform_admin`) but **no platform-admin surface uses it** (no plans admin API, no self-service grant path) |
| Teams / seats model | NOT IMPLEMENTED | No team/team_member or seat tables anywhere (explicit absence, see limitations) |

## W2 — Subscription / Billing / Entitlements

| Feature | Status | Where / Notes |
|---|---|---|
| Billing service | DONE | `app/billing/service.py` (792 lines): start/change/cancel/resume subscription (org_admin gates inside the service), one live subscription per org (partial unique index `uq_subscription_live_per_org`), subscription events audit trail, invoices (`CT-YYYYMM-XXXXXXXX`; $0 invoices auto-`paid`), idempotent webhook ingestion (replay of (provider, event_id) → status `duplicate`) |
| Provider adapter seam | DONE | `app/billing/provider.py`: abstract `BillingProvider` + `SandboxBillingProvider` (name `sandbox`, mode `test`). Registry `get_provider()` — **only "sandbox" is wired**; any other name raises ValidationFailed |
| **Sandbox billing reality** | DONE (as sandbox) | **No real payments exist.** The sandbox provider returns test-mode checkouts with `url=None` (nothing to redirect to), and `/billing/sandbox/pay` simulates success/decline by running the payment through the *same* idempotent webhook pipeline a real provider callback would use. HMAC webhook verification IS implemented (`verify_webhook` recomputes HMAC-SHA256 over exact bytes; signature format `"<timestamp>.<hmac_hex>"`, header `x-croptwist-signature`, stale-timestamp helper, 256 KiB payload cap). Honesty contract is stated in `app/api/v1/billing.py` docstring |
| Billing webhook receiver | DONE | `POST /api/v1/billing/webhook` (`app/api/v1/billing.py`): raw-body read, signature verified over exact bytes, size cap, handles `payment.succeeded` / `payment.declined` / `subscription.renewal_due` / `subscription.ended`, records every event (including rejected ones) in `billing_events` |
| Entitlement engine | DONE | `app/billing/entitlements.py` (282 lines): `resolve_entitlements` (free-plan floor without a live subscription; deny-by-default without a catalog), `require_flag`, `limit_for`, `check_quota` (402), `assert_within_limit` (402), `require_active_billing`, `increment_usage`, `usage_snapshot`, `resource_counts` (farms/fields/members). Usage periods: monthly → calendar month, yearly → calendar year |
| Subscription lifecycle webhooks | DONE | `subscription.updated` emitted on every direct lifecycle transition and on provider-webhook-driven transitions (`app/billing/service.py`, 2 emission sites) |
| Grace / dunning | PARTIAL | `past_due` → `grace` states modeled with `billing_grace_seconds` (default 3 days) and the scheduler sweep expires lapsed subscriptions, but no real dunning emails/ret-invoices exist (there is no email transport) |
| Proration | NOT IMPLEMENTED | Plan changes are immediate; the next invoice reflects the new price. No proration simulation (stated in the route docstring) |
| Invoice line items / tax / VAT | NOT IMPLEMENTED | Invoices carry a single `amount_cents` — no line items, no tax/billing-address fields |

**Entitlement enforcement points (the actual gates in domain code):**

| Gate | Enforced at | Rule |
|---|---|---|
| `max_farms` | `app/domains/farms_fields/service.py` (farm creation) | `assert_within_limit` **only when the org has a live subscription** — org-less/legacy personal accounts pass through untouched (comment in code: P1/P2 golden flows preserved) |
| `max_fields` | `app/domains/farms_fields/service.py` (field creation) | Same live-subscription-only rule |
| `exports_enabled` + `reports_per_month` | `app/reports/service.py` (`create_report_job`) | `require_flag` + `check_quota`; usage incremented on successful render; same pass-through rule |
| `scenario_runs_per_month` | `app/scenarios/service.py` (quota check) + `app/scenario_execution/service.py` (usage increment) | Same pass-through rule |
| `api_rate_limit_per_minute` | `app/publicapi/api_keys.py` — snapshotted into the key's `rate_limit_per_minute` at creation; per-key sliding-window limiter (60 s) returns 429 with Retry-After. Fallback 60/min when no live subscription |
| `max_api_keys` (optional) | `app/publicapi/api_keys.py` | Passes through unless a plan actually defines the key — it is **not** in the seeded catalog |
| `max_org_members` | **NOT ENFORCED** — key defined, never referenced by org member routes | |
| `advanced_analysis`, `satellite_access`, `analytics_access`, `ai_messages_per_day`, `api_enabled` | **NOT ENFORCED** — defined/seeded only (`api_enabled` is surfaced informationally in `GET /developer/usage`) | |

## W3 — Organizations / Teams / Farm Management

| Feature | Status | Where / Notes |
|---|---|---|
| Org service | DONE | `app/orgs/service.py` (575 lines): create org (+owner membership), update (name/type/country), member directory, role change (only owner grants owner/org_admin; last-owner guard), remove member (self-removal refused; only owner removes owner), ownership transfer (previous owner → org_admin) — all audited to `audit_events` + activity timeline |
| Org routes | DONE | `app/api/v1/orgs.py`: POST/GET `/orgs`, GET/PATCH `/orgs/{id}`, members list/patch/delete, ownership-transfer, invitations create/list/revoke, `POST /invitations/accept`. Payloads carry `my_role`; members addressed by **user_id** at the API and membership id in the service |
| Invitations | DONE | SHA-256-hashed tokens, 7-day TTL, plaintext returned **once** with an explicit "deliver out-of-band" note (no email is sent); statuses pending/accepted/revoked/expired |
| RBAC (7 roles) | DONE | `ROLE_ORDER` in `app/domains/identity/service.py`: viewer/analyst/agronomist (1) < operator/manager (2) < org_admin/owner (3); checks happen inside services. **Gap:** farm-scoped `app/api/v1/members.py` still validates the old 4-role set in its Pydantic models |
| Activity timeline | DONE | `app/activity/service.py` + `GET /api/v1/orgs/{org_id}/activity` (membership-gated, append-only, newest-first, limit clamp 1..200). Event-type constants for farm/field/member/recommendation/report/billing/developer/crop_cycle/setting events |
| Teams (sub-groups within orgs) | NOT IMPLEMENTED | No team tables/routes — membership is org-level only |
| Multi-org UX | DONE (convention) | Deterministic "oldest active org" fallback used by analytics/notifications/reports when no explicit `organization_id` is given |

## W4 — Commercial Intelligence & Business Analytics

| Feature | Status | Where / Notes |
|---|---|---|
| Analytics service | DONE | `app/analytics/service.py` (622 lines): `executive_dashboard` (farm/field counts, total area, active crop cycles, crop distribution, recommendations summary + adoption, data freshness), `farm_performance` (per-field rows, coverage heuristic, water usage), `commercial_metrics`, `benchmark` |
| Provenance discipline | DONE | Every metric carries `provenance`: `observed` / `model_derived` / `simulated` / `missing`; `_metric()` auto-downgrades to `missing` when the value is None. No invented yield/profit numbers anywhere |
| Commercial metrics | PARTIAL | Water volume + water cost are `model_derived` **from the user-supplied water price** (echoed back in `assumptions` with an `honesty_note`). `cost_per_hectare` and `yield` are **always `missing`** — no price/yield estimation exists |
| Benchmarks | PARTIAL | **Within-org only** (farm-vs-farm / field-vs-field, scopes `farm` and `field`). `cross_org_anonymized` is returned with `provenance: "missing"` and an explanatory note — cross-org anonymous benchmarking is a future capability |
| Dashboard filter honesty | DONE | `GET /analytics/executive-dashboard` **refuses** unsupported filters (`field_id`, `crop`, `date_from`, `date_to`) with 400 (`_reject_unsupported`) instead of silently ignoring them; the frontend renders the crop filter disabled with a tooltip |
| Analytics routes | DONE | `app/api/v1/analytics.py`: executive-dashboard, farm-performance/{farm_id} (dates required), commercial-metrics, benchmarks |
| Analytics entitlement (`analytics_access`) | NOT ENFORCED | Dashboard/metrics are gated by membership only; the seeded bool key is not consulted |

## W5 — Reports / Exports / Notifications

| Feature | Status | Where / Notes |
|---|---|---|
| Report type catalog | DONE | `app/reports/contracts.py` (314 lines): 10 report types (farm_performance, field_analysis, soil_health, water, rotation, seasonal, environmental_risk, recommendations, org_executive, custom_range), each with en/ar titles, required inputs, default sections; formats pdf/xlsx/csv; locales en/ar |
| Report lifecycle | DONE | `app/reports/service.py` (1168 lines): create (validate → entitlement gate → queue), execute (render → atomic artifact write under `settings.reports_dir` → succeeded/failed on the job row), list/get/status/delete, regenerate (inline), schedule (`interval_days` 7/30 or null; recurring copies enqueued by the scheduler), retention (30 days default; expired jobs refuse download until regenerated) |
| Inline execution | DONE | `POST /reports` accepts `sync=true` for **csv/xlsx only** (pdf always queues — rendering cost unbounded); failures land on the job row as `status=failed` + `error`, never raised raw |
| Renderers | DONE | `app/reports/renderers.py` (802 lines): pdf (reportlab), xlsx, csv from a shared normalized payload; missing sections render with `provenance: "missing"` and a note instead of failing; PDF table rows capped at 300 |
| **Arabic RTL PDF** | DONE (with fallback) | `render_pdf(locale="ar")` shapes + bidi-reorders Arabic via `arabic_reshaper` + `bidi.algorithm.get_display`; embeds a verified Arabic-capable TTF (searches Noto Naskh Arabic paths and verifies glyph coverage before use); if no Arabic-capable font exists on the host it degrades to a documented Latin transliteration rather than rendering tofu. XLSX/CSV rely on native shaping (no cell-level RTL transform) |
| Notification center | DONE | `app/notifications/service.py` (298 lines): 8 categories, 4 severities (info/advisory/warning/critical), DB-level dedupe (partial unique `(organization_id, dedupe_key)`), read/unread + mark-all, per-category expiry (14/30/90 d) + purge sweep |
| Notification routes | DONE | `app/api/v1/notifications.py`: list (unread_only/category/severity filters; severity filtering pages through the service so totals stay exact), mark read, read-all, unread-count, per-category preferences GET/PUT |
| **Email channel reality** | PARTIAL (seam only) | `app/notifications/channels.py`: `NotificationChannel` protocol + registry; the **only** wired channel is `LoggingEmailChannel`, which logs the message and returns `sent=False` with an explicit reason. **No SMTP/real email delivery exists.** `NotificationPreference.email_enabled` is recorded but produces no outbound mail; the `email_channel` setting is intentionally absent from `config.py` (defaults to `log`) |
| SMS / push | NOT IMPLEMENTED | No channel, model, or route exists |

## W6 — Public API / Integrations / Developer Platform

| Feature | Status | Where / Notes |
|---|---|---|
| API keys | DONE | `app/publicapi/api_keys.py` (583 lines): `ctk_`-prefixed 256-bit keys, SHA-256 hash is the only persisted secret, plaintext shown once (create/rotate), 8 scopes (`org:read farms:read fields:read crops:read analytics:read recommendations:read reports:read environment:read`), revoke + rotate (old key revoked immediately, no grace), `last_used_at`, daily per-key usage counters (SAVEPOINT-safe upsert) |
| Key authentication | DONE | `require_api_key(*scopes)` dependency: Bearer or `X-API-Key`; check order format → hash → revoked/expired (401) → scopes (403) → rate limit (429). Returns an `ApiKeyPrincipal` (org_id, key_id, scopes) — never a user principal |
| Outgoing webhooks | DONE | `app/publicapi/webhooks.py` (764 lines): endpoint CRUD (https required; localhost tolerated outside production), `whsec_` secrets shown once, HMAC-signed deliveries (`X-FieldShift-Signature`, `X-FieldShift-Event-Id`, `X-FieldShift-Event`), retry with backoff 30 s→6 h, max 5 attempts then `dead`, auto-disable after 5 consecutive failures (manual re-enable), delivery list + redeliver |
| Emission surface | DONE (2 events) | `app/publicapi/emitters.py` → `emit_event()` creates pending delivery rows only; the scheduler dispatches. **Events actually emitted today: `report.ready`** (report success) **and `subscription.updated`** (lifecycle transitions + provider-webhook intake). The other 5 catalog event types (`farm.updated`, `field.created`, `crop_cycle.updated`, `recommendation.generated`, `alert.raised`) have **no emitters** yet |
| Public versioned API | DONE | `app/api/v1/public_v1.py`: 9 read-only endpoints under `/api/v1/public/v1` (org, farms, farm, fields, crop-cycles, recommendations, analytics/executive, reports, environmental-metrics). Every query is scoped by the key's organization (cross-tenant ids are 404, never 403); pagination `{items,total,limit,offset}` (limit ≤ 100, default 25); environmental window ≤ 366 days |
| Developer console API | DONE | `app/api/v1/developer.py`: keys create/list/revoke/rotate, webhooks create/list/patch/delete/rotate-secret/deliveries/redeliver, usage (per-key daily counters + plan rate-limit info), events+scopes catalog. Mutations gated org_admin+ inside the services |
| Egress control | PARTIAL | Webhook URLs validated (https, no embedded credentials, length cap); there is **no SSRF/private-IP blocklist** beyond the localhost rule |
| OpenAPI/SDK/docs for external consumers | NOT IMPLEMENTED | No public developer documentation site or SDK generation |

## W7 — Global Product Experience & Enterprise Readiness

| Feature | Status | Where / Notes |
|---|---|---|
| Onboarding | DONE | `app/onboarding/service.py` + `app/api/v1/onboarding.py`: 9 resumable steps (`account` auto → account_type → organization → org_profile → first_farm → first_field → crops_priorities → review → tour; 5 required / 4 optional), JSONB step state, account types individual/business/farm_org, required steps refuse skip, dismiss-tour. Non-blocking — completion never requires external integrations |
| User preferences | DONE | `app/preferences/service.py` + `app/api/v1/preferences.py`: 9 fields (locale en/ar, timezone, currency, country, unit_system metric/imperial, week_start, agricultural_calendar, notify_in_app/email), partial updates, validation in the service. Presentation-only — internal units stay SI/metric |
| Frontend account sphere | DONE | `src/lib/api-p3-account.ts`, `src/components/croptwist/p3/{team-tab,onboarding-wizard,notifications-bell}.tsx`; workspace wired in `src/components/croptwist/workspace.tsx` (tabs team/billing/insights/reports/developer + bell + wizard) |
| Frontend commercial sphere | DONE | `src/lib/api-p3-commercial.ts` (binary download handles `Content-Disposition`), `src/components/croptwist/p3/{billing-tab,insights-tab,reports-tab,developer-tab}.tsx`. Billing tab shows an amber **Test mode** badge when the subscription payload says sandbox/test; the sandbox pay panel renders only when the provider actually is sandbox |
| i18n | DONE | `messages/en/p3.json` + `messages/ar/p3.json` (198 keys), `messages/en/p3b.json` + `messages/ar/p3b.json` (324 keys); en/ar key sets verified identical at build time by the frontend agent; RTL-safe logical utilities (`ms-/me-`, `text-start/end`, `rtl:rotate-180`); machine values pinned `dir="ltr"` |
| Enterprise SSO/SCIM | NOT IMPLEMENTED | No SAML/OIDC/SCIM anywhere in P3 |
| MFA | NOT IMPLEMENTED | No MFA UI or backend factor model (auth remains password + bearer/cookie token) |

## W8 — Production Infrastructure / Security / Operations

| Feature | Status | Where / Notes |
|---|---|---|
| Periodic scheduler | DONE | `app/core/scheduler.py`: dependency-free single-process interval loop, **6 tasks**: `reports.execute_queued` (15 s), `webhooks.retry_due` (30 s), `billing.expire_stale` (300 s), `notifications.purge_expired` (300 s), `reports.recurring_and_retention` (300 s), `activity.prune` (900 s). Each task opens its own session, is error-isolated and idempotent; `LAST_RUNS` history surfaced via `scheduler_status()`; started from `app/main.py` when `settings.scheduler_enabled` (default True) and `job_workers > 0` (default 2) |
| Background one-shot jobs | PRE-EXISTING | `app/core/jobs.py` (202-shaped job rows) — P3 report/webhook work rides the scheduler instead of the job queue |
| Rate limiting | PARTIAL | Per-key sliding-window limiter for the public API only (`app/publicapi/api_keys.py`); the session-authenticated surface still has no rate limiting (pre-existing limitation) |
| Audit trail | DONE | `audit_events` via `record_auth_audit` for invitations/membership/ownership/org/api-key actions; append-only `activity_events` for the tenant timeline |
| Secrets handling | DONE (within scope) | API keys + webhook secrets + invitation tokens stored hashed; plaintext shown once; `api_key_payload` never exposes the hash |
| Health/ops surface for scheduler | DONE | `scheduler_status()` exposed via **`GET /api/v1/ops/health`** (`app/api/v1/ops.py`): DB latency + PostGIS, scheduler last-runs, background/report queue depths, webhook backlog (dead-letter count), billing provider name+mode. Aggregate-only (no tenant data, no secrets); authenticated users (every user owns a personal org, so an org-role gate would be vacuous) |
| Real email/SMS transport | NOT IMPLEMENTED | Logging adapter only (see W5) |
| Multi-replica safety | PARTIAL | Scheduler/rate-limiter/usage counters are single-process by design (documented trade-offs in module docstrings); a lost race between replicas costs at most a no-op pass |

---

## Cross-cutting honest statements (summary)

1. **Sandbox billing provider is the only provider.** No real payment processing, no live checkout
   URLs, no real money — the sandbox simulates outcomes through the same signed, idempotent
   webhook pipeline a real provider would use, and the UI labels it "Test mode".
2. **Entitlement enforcement is live-subscription-gated and partial.** Farms/fields creation,
   report quota + exports flag, scenario-run quota and per-key API rate limits are enforced; org
   member caps ARE enforced on invitation acceptance (2026-11-12 session, same live-subscription
   conditionality as farms/fields); the bool keys (analytics/satellite/advanced_analysis/
   api_enabled) are surfaced through entitlements/API status but not all have a hard backend gate yet.
3. **Scheduler is single-process** with 6 periodic tasks; safe to lose a race, not horizontally
   scalable coordination.
4. **Email is a seam, not a channel**: `LoggingEmailChannel` logs and reports `sent=False`. No
   SMTP, no SMS, no push. Invitation tokens and all "email" preferences are recorded, never sent.
5. **Arabic RTL PDF** is implemented via reportlab + arabic_reshaper + python-bidi with a
   verified-font requirement and a documented transliteration fallback when no Arabic font exists.
6. **Benchmarking is within-org only**; cross-org anonymized aggregates return
   `provenance: "missing"`.
7. **Not implemented list** (explicit): MFA (UI or backend), teams tables, invoice line items /
   tax fields, usage-based billing beyond counters (no metered invoicing), real email/SMS
   delivery, external webhook events for farm/field edits (only `report.ready` and
   `subscription.updated` are emitted today), plans admin API, platform-admin surface, SSO/SCIM,
   proration, public developer docs/SDK.

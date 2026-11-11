# P3 Test & Verification — structure and plan

**Status: TEMPLATE.** Result cells marked **TBD** are to be filled by the integrator after the
verification pass. This file deliberately contains **no fabricated results** — only the test
structure, the static facts that are verifiable in the repo today, and the checklist of what must
be exercised before P3 can be called verified.

Suggested command preamble (match the existing house workflow in
`docs/implementation/TEST_MATRIX.md`): backend `cd mini-services/fieldshift-api && pytest …`;
frontend `bunx tsc --noEmit`, `bun run lint` at repo root.

---

## 1. Unit tests (backend, `tests/unit/`)

Static facts (verifiable in the tree today):

| File | Covers | `def test_` count (static) |
|---|---|---|
| `tests/unit/test_publicapi_keys.py` | API key generation/hashing, scopes, rotation, throttling, auth dependency | 23 |
| `tests/unit/test_report_renderers.py` | pdf/xlsx/csv renderers incl. Arabic shaping/fallback paths | 17 |
| `tests/unit/test_webhooks_signing.py` | webhook HMAC signing/verification, backoff, delivery state machine | 28 |

Total existing P3 unit coverage: **68 tests in 3 files**. Everything else in this section is TBD.

| Area | Tests exist? | Result | Notes |
|---|---|---|---|
| API keys (hashing, scopes, rotate, throttle) | ✅ (above) | TBD | |
| Webhook signing + retry/dead-letter | ✅ (above) | TBD | |
| Report renderers (pdf/xlsx/csv, en/ar) | ✅ (above) | TBD | |
| Billing service (start/change/cancel/resume, webhook pipeline idempotency, invoice numbering) | ❌ none yet | TBD | e.g. `test_billing_service.py` |
| Entitlement resolution + quota/flag gates (incl. pass-through without live subscription) | ❌ none yet | TBD | e.g. `test_entitlements.py` |
| Sandbox provider (checkout, HMAC verify, stale timestamp) | ❌ none yet | TBD | |
| Orgs service (roles, last-owner guard, ownership transfer, invitations) | ❌ none yet | TBD | |
| Onboarding state machine (required-step skip refusal) | ❌ none yet | TBD | |
| Notifications service (dedupe, preferences, expiry) | ❌ none yet | TBD | |
| Analytics service (provenance downgrades, missing metrics) | ❌ none yet | TBD | |
| Scheduler task bodies (direct invocation, as designed for tests) | ❌ none yet | TBD | |
| Preferences service (validation allowlist) | ❌ none yet | TBD | |

## 2. Integration tests (backend, `tests/integration/`, real PG+PostGIS)

No P3 integration test file exists today (`tests/integration/` contains none matching
p3/billing/org/notifications/reports/analytics/webhooks). Planned coverage:

| Scenario | File (suggested) | Result |
|---|---|---|
| Migration 0020 up/down/up from clean DB; seeded plan catalog + 13 entitlement keys per plan present | `test_p3_migrations.py` | TBD |
| Full subscription lifecycle via API: start (trial) → sandbox pay succeeded → change plan → cancel at period end → resume → expire sweep | `test_p3_billing_flow.py` | TBD |
| Billing webhook: valid HMAC signature processed; bad signature 403; replay → `duplicate`; malformed payload recorded + rejected | `test_p3_billing_flow.py` | TBD |
| 402 paywalls: farm/field creation over `max_farms`/`max_fields` with a subscribed org; reports quota; scenario quota — and pass-through for org-less users (P1/P2 flows unchanged) | `test_p3_entitlements_flow.py` | TBD |
| Org lifecycle: create → invite (token once) → accept → role change → ownership transfer → remove; 403 matrix for insufficient roles | `test_p3_orgs_flow.py` | TBD |
| Reports end-to-end: create csv sync (succeeded + download round-trip), pdf queued → scheduler executes → download; Arabic locale PDF; regenerate; schedule recurrence; retention expiry | `test_p3_reports_flow.py` | TBD |
| Notifications: create/dedupe (unique key), read/read-all, preferences PUT, purge sweep | `test_p3_notifications_flow.py` | TBD |
| Public API: key auth (Bearer + X-API-Key), scope 403s, 429 with Retry-After, cross-tenant 404 isolation, all 9 `/public/v1` endpoints | `test_p3_public_api_flow.py` | TBD |
| Outgoing webhooks: signed delivery to a local receiver, retry/backoff on failure, dead after 5 attempts, auto-disable, redeliver | `test_p3_webhooks_flow.py` | TBD |
| Scheduler: all 6 tasks run cleanly against a live DB (`LAST_RUNS.ok == True`) | `test_p3_scheduler.py` | TBD |
| Analytics endpoints over seeded data (dashboard, farm-performance date validation, commercial metrics assumptions echo, benchmarks scope validation) | `test_p3_analytics_flow.py` | TBD |

## 3. E2E browser verification (frontend, dev stack pg :5433 / api :3030 / web :3000)

Frontend components under test: `src/components/croptwist/p3/{team-tab, onboarding-wizard,
notifications-bell, billing-tab, insights-tab, reports-tab, developer-tab}.tsx` wired into
`src/components/croptwist/workspace.tsx`; typed clients `src/lib/api-p3-account.ts`,
`src/lib/api-p3-commercial.ts`.

| Flow | Checks | Result |
|---|---|---|
| Onboarding wizard | progress persists/resumes; account-type radio; org create or invitation join; required steps not skippable; dismiss confirm | TBD |
| Team tab | create/rename org; member table + role select (grant policy); ownership transfer typed-email confirm; activity "Load more"; invitation token shown once + copy | TBD |
| Notifications bell | 60 s unread polling; severity dots; mark read on click + navigation only for known `link_kind`s; mark-all; per-category preferences PUT | TBD |
| Billing tab | plans grid monthly/yearly toggle; enterprise "Contact sales" (mailto, no fake price); start/change/cancel/resume; usage bars (unlimited label path); **Test mode** badge + sandbox pay panel visible only for sandbox provider; invoices table | TBD |
| Insights tab | KPI tiles with provenance badges; missing → "No data" chips (never zeros); crop filter disabled with tooltip; farm performance (dates required); commercial metrics committed on blur + verbatim assumptions; benchmarks + "cross-org is future" note | TBD |
| Reports tab | generate (10 types × formats × en/ar); sync auto-download for csv/xlsx; pdf queues; 3 s list polling while queued/running; download/regenerate/schedule/delete; failed rows show API error | TBD |
| Developer tab | key create → secret shown once; scope badges; rotate/revoke; webhook create (https validation); deliveries panel 5 s polling while pending; redeliver; usage card; events reference | TBD |
| Arabic / RTL | switch locale to ar across all P3 tabs; logical-utility spacing; machine values pinned `dir="ltr"`; en/ar key parity (`p3.json` 198 keys, `p3b.json` 324 keys) | TBD |
| Console hygiene | zero console errors on each tab; no horizontal overflow at 390 px | TBD |

## 4. Performance measurements

No performance numbers exist yet — **all TBD**; nothing may be invented. Suggested measurement
points (sandbox hardware only; re-run before any production claim):

| Measurement | Method (suggested) | Result |
|---|---|---|
| Report render time by format (csv/xlsx/pdf) and locale (en/ar PDF incl. font/shaping cost) | time `execute_report_job` over a fixed seeded scope | TBD |
| Scheduler task duration | `LAST_RUNS[…]["took_ms"]` after a full cycle | TBD |
| Webhook delivery latency + backoff profile against a local receiver | instrument `deliver_webhook` | TBD |
| Public API key-auth overhead (hash lookup + limiter + usage upsert) | time `authenticate_api_key` | TBD |
| Analytics endpoints response time on a realistic seed (dashboard / farm-performance / benchmarks) | request timing | TBD |
| Billing webhook ingestion (signature verify + idempotent processing) | request timing | TBD |

Known structural performance caveats (static, from code): per-key rate limiter and usage counters
are in-process; the notifications severity filter pages through the service (≤ 20k rows scanned);
PDF rows capped at 300.

## 5. Security checks

| Check | Expected (from code) | Result |
|---|---|---|
| API key storage | only SHA-256 hash persisted; plaintext returned once (create/rotate responses) | TBD |
| Webhook secret storage | `whsec_` plaintext shown once on create/rotate only | TBD |
| Invitation token storage | SHA-256 hash (`uq_invitations_token_hash`); plaintext once | TBD |
| Billing webhook verification | HMAC-SHA256 over exact raw bytes (`<ts>.<hmac_hex>` in `x-croptwist-signature`); stale-timestamp helper exists; bad signature → 403 + recorded event | TBD |
| Outgoing webhook signing | `X-FieldShift-Signature` over canonical body; receivers can verify with the endpoint secret | TBD |
| Cross-tenant isolation | public API: cross-org ids → 404 (no existence leak); session routes: `require_member_of`/`require_org_role` in services | TBD |
| Scope enforcement | 403 lists missing scopes; key cannot act on another org (shim raises Forbidden) | TBD |
| Rate limiting | 429 + `Retry-After` per key over 60 s window; limit snapshotted per key | TBD |
| Secrets in payloads | `api_key_payload` never exposes `key_hash`; scheduler status has "no secrets" | TBD |
| Webhook URL validation | https required (localhost exception only outside production); no embedded credentials; ≤1000 chars | TBD |
| Known gaps to re-flag after the pass | no rate limiting on session-auth routes; password hashing iterations lowered for sandbox (pre-existing items 8/9 in KNOWN_LIMITATIONS); no MFA; no SSRF blocklist for webhook egress beyond localhost rule | TBD |

## 6. Sign-off checklist (integrator)

- [ ] Full backend pytest run green (record exact counts here: TBD)
- [ ] `bunx tsc --noEmit` + `bun run lint` clean (record: TBD)
- [ ] All E2E flows above executed once in en and once in ar (record: TBD)
- [ ] Scheduler observed running with 6 tasks and clean `LAST_RUNS` (record: TBD)
- [ ] Sandbox billing lifecycle (pay succeeded + declined) exercised through the UI (record: TBD)
- [ ] Any deviations/bugs found filed and referenced here (TBD)

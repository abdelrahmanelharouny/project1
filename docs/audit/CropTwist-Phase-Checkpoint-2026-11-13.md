# CropTwist — Phase Checkpoint Report (2026-11-13)

**Purpose:** standing reference for the completed phase (P0 → P3). When we need to
look back at what exists, what was verified, what broke, and what remains open,
this file is the entry point. It supersedes nothing — it complements
`docs/audit/CropTwist-Engineering-Audit-2026-11-10.md` (the audit that defined the
P0/P1 roadmap) and the per-phase docs under `docs/p3/`.

**Baseline:** branch `main`, HEAD `579079e` · 53 commits · 22 migrations
(head `0020_p3_saas_platform`) · 1,455 backend test functions (853 unit /
72 contract / 530 integration) · 41 API router modules · 33 workspace components
(+7 P3 tab components) · i18n en+ar across 22+ namespaces.

**Governing contract (unchanged since inception):**
"Agronomic engines calculate. Evidence validates. AI explains. Farmers decide."
The LLM never computes numbers, never invents evidence, never bypasses the
recommendation registry.

---

## 1. Executive summary

CropTwist is a global agriculture decision-intelligence platform delivered in
four phases, all now implemented and measured-verified:

| Phase | Theme | State |
|---|---|---|
| P0 | Production hardening (recovery, backup, CI) | DONE — commits `1455f34` `ce35150` `fc8efe1` |
| P1 | AI Intelligence & Trust (A1–A12) | DONE — migration `0018`, golden eval **62/62** |
| P2 | Advanced Agricultural Intelligence | DONE — migration `0019`, eval **20/20**, browser-verified |
| P3 | Commercial SaaS Platform | DONE (core W1–W8) — migration `0020`, P3 suites **138 passed**, E2E smoke **ALL PASS**, browser-verified |

The stack is live and self-healing: pg :5433 · api :3030 · bridge :3035 ·
web :3000, recovered end-to-end **three times** from full sandbox wipes via the
one-command `rebuild_stack.sh` (each rebuild ≈ 2–3 minutes, demo workspace
re-seeded automatically).

The honest center of gravity has shifted from **"features missing"** to
**"hardening gaps"**: un-enforced entitlement keys, seam-only email, unmeasured
performance targets, and no current backup artifacts (Section 7).

---

## 2. System structure

### 2.1 Runtime topology

| Service | Tech | Port | Role |
|---|---|---|---|
| PostgreSQL | 16.10 + PostGIS 3.5.0 (micromamba user-space build) | 5433 (socket /tmp) | all persistent state; single DB `croptwist` |
| FastAPI backend | Python 3.12, SQLAlchemy + Alembic | 3030 | ~181+ routes under `/api/v1` across 41 router modules |
| LLM bridge | Bun + `z-ai-web-dev-sdk` (GLM) | 3035 | the ONLY outbound LLM surface; auth/budget/caps/metrics |
| Frontend | Next.js 16 App Router, Tailwind 4, shadcn/ui, TanStack Query + Zustand | 3000 | 33-tab workspace (26 P0–P2 + 5 P3 tabs + bell + wizard) |
| Gateway | Caddy | 3000 (public) | single external port; `XTransformPort` for other services |

### 2.2 The five-layer architecture

```
L5  Presentation      src/ (Next.js) — 33 tabs, en/ar RTL, entitlement guard
L4  Recommendations   app/recommendations/ — central registry, 7 generators
L3  Intelligence      app/intelligence/ — evidence packs, anomalies, advisor,
                      narrative + 8 trust engines (P1)
L2  Domain engines    water / soil / rotation (CP-SAT) / management /
                      vegetation / climate / failure_lab / portfolio / …
L1  Data platform     app/data_platform/ — providers, ingestion, QA,
                      feature engine (~24 versioned features)
```

Providers (L1): Open-Meteo ERA5 reanalysis, CHIRPS GeoTIFF extraction, ISRIC
SoilGrids (labeled model predictions), Sentinel-2-style satellite simulation
(P2), synthetic deterministic provider (flagged `is_synthetic` end to end).

### 2.3 The AI stack in one view (detail: chat 2026-11-13 "what ai engines")

- **Grounding:** `intelligence/evidence.py` builds a <4k-char provenance-labeled
  evidence pack per field; missing domains become explicit `data_gaps`.
- **LLM surfaces (3):** advisor Q&A (`advisor.py`), recommendation narratives
  (`narrative.py`), field briefs — all ONE bridge call each, JSON response
  contract (`response_contract.py`), citations validated against the same
  request's evidence pack (fabricated labels rejected).
- **Trust engines (P1, A1–A12 all implemented):** anomaly baselining fix (A1),
  circuit breaker (A2), narrative cache SHA-256 (A3), recommendation
  fingerprinting/diffing (A4), evidence-quality components (A5),
  structured responses + citation validation (A6), prompt-injection guard +
  numeric-consistency guard (A7), multi-turn sessions (A8), bridge hardening —
  token auth, budgets, caps (A9), en/ar narrative locales (A10), golden-case
  evaluation (A11), append-only farmer feedback (A12).
- **Recommendation layer:** `@registry.generator` per domain (climate, water,
  soil, rotation, management, vegetation); severity ladder
  `info < advisory < recommended < required`; deterministic confidence with
  `confidence_basis`; one honest INFO data-gap recommendation when a domain
  has no data.
- **Degradation policy:** bridge down/disabled/open → `rules` mode everywhere;
  endpoints never fail because of the LLM. Response `engine` field always
  records `llm` vs `rules`.

---

## 3. Phase history with evidence

### P0 — Production hardening (DONE)

- `rebuild_stack.sh` — 9-step idempotent, non-destructive recovery playbook
  (pgenv install → initdb → start/ensure DB → venv → alembic → seed →
  daemonize api/bridge/web). Verified from a fully wiped sandbox.
- Backup/restore system: `backup_db.sh` (custom-format dumps + checksums) and
  `restore_db.sh` with restore gates — docs `docs/operations/BACKUP_AND_RESTORE.md`.
- CI: blocking typecheck, type-checked production build, lint fixes; E2E smoke
  suite `scripts/e2e_smoke.py`.
- Runbooks: `STACK_BOOTSTRAP.md`, `CI_AND_TESTING.md`.

### P1 — AI Intelligence & Trust (DONE, migration `0018`)

All 12 items from the 2026-11-10 audit (A1–A12) implemented and verified.
Golden evaluation **62/62 passed** (deterministic fixtures per generator domain,
running the real generator code paths — no mocks).

### P2 — Advanced Agricultural Intelligence (DONE, migration `0019`)

Satellite/vegetation intelligence (same-month baselines, dormancy, stress
signals with explicit not-supported lists), climate forecasting (ETCCDI/WMO
risk thresholds, verification math, capability-matrix honesty), soil memory
(SOC trajectories, refuses <2 measurements), failure lab (stress packs,
robustness metrics), adaptive evidence (VoI scoring — never monetary), farm
portfolio optimizer. Eval **20/20**; DB integration golden path green.

### P3 — Commercial SaaS Platform (DONE core, migration `0020`)

Five commits on `main` (`867e1a9` billing catalog seeder, `37fefb8` exact
owner gate, `05c046a` ops health + e2e, `75198ca` entitlement guard UX,
`97c1b3f` verification record). 16 new tables; tenant tables carry
`organization_id` FK+index; money = integer minor units + ISO currency; no
raw card data anywhere.

Workstream status (full detail: `docs/p3/P3_IMPLEMENTATION_STATUS.md`):

| W | Scope | Highlights |
|---|---|---|
| W1 | SaaS foundation | 5-plan DB catalog (free/starter/professional/business/enterprise), 13 entitlement keys, HTTP 402 `PAYMENT_REQUIRED` |
| W2 | Billing | subscription lifecycle, invoices `CT-YYYYMM-XXXXXXXX`, idempotent HMAC-signed webhook pipeline, sandbox provider honestly labeled "Test mode" |
| W3 | Orgs | 7-role RBAC server-side, hashed invitations (7-day TTL, shown once), last-owner guard, ownership transfer, activity timeline |
| W4 | Analytics | executive dashboard, farm performance, commercial metrics; every metric carries `provenance: observed/model_derived/simulated/missing`; no invented yield/profit |
| W5 | Reports/Notifications | 10 report types × pdf/xlsx/csv × en/ar, Arabic RTL PDF (arabic_reshaper + bidi + verified font, transliteration fallback), async queue, schedules, retention, notification center with dedupe |
| W6 | Developer platform | 9 read-only `/public/v1` endpoints, `ctk_` scoped keys (rotation, 429 + Retry-After), signed outgoing webhooks (backoff → dead-letter → auto-disable) |
| W7 | Global UX | 9-step resumable onboarding, preferences, full en/ar i18n (p3 198 + p3b 324 keys), RTL-safe utilities |
| W8 | Ops | 6-task scheduler, audit trail, `GET /api/v1/ops/health` (DB latency, PostGIS, scheduler, queue depths, provider name+mode) |

**Verification session 2026-11-12** (`docs/p3/P3_TEST_AND_VERIFICATION.md §7`):

| Check | Result |
|---|---|
| `tests/unit` | 144 passed, 0 failed |
| `tests/contract` | 72 passed |
| `tests/integration` (sliced) | all green (1 pre-existing conditional skip) |
| P3 suites | 138 passed (was 12 failing before fixes) |
| `bun run lint` / `tsc --noEmit` | clean |
| E2E smoke vs :3030 | ALL PASS — incl. 402 paywall naming the limit, duplicate-subscription 409, cross-tenant farm 404, key auth, ops health |
| Browser (Agent Browser) | 26 tabs render; PDF pipeline UI→scheduler→download verified (`file(1)`: PDF 1.4, 2 pages); RTL flip verified; entitlement-guard toast verified; mobile 390×844 no overflow |

**Defects found and fixed during that pass** (root causes documented):

1. Test DB missing plan catalog → runtime parity seeder `app/billing/catalog.py`.
2. org_admin passed the rank-based "owner" gate → exact `require_owner()` check.
3. Membership-existence leak (404 before authorize) → authorize-then-resolve.
4. `/billing/invoices` missing `total` → true COUNT added.
5. Stale provider-set assertion → subset assertion.
6. Missing i18n key `p3b.common.unlimited` → added en+ar.

---

## 4. What is working well (verified)

1. **Recovery discipline.** Three full sandbox wipes (2026-11-12 → 11-13)
   recovered end-to-end each time by one command; final verify line
   `CropTwist stack OK: pg :5433, api :3030, bridge :3035, web :3000`.
2. **Honesty architecture.** Provenance on every metric/number
   (`observed/model_derived/simulated/missing`); analytics refuse unsupported
   filters with 400 instead of silently ignoring them; cross-org benchmarking
   returns `provenance: "missing"` rather than fabricated percentiles; sandbox
   billing is labeled Test mode in API and UI; no real-money claims anywhere.
3. **AI trust layer.** Citations validated per-request; numeric guard with
   unit/rounding tolerances; deterministic fallback always available; evaluation
   harness (62/62 + 20/20) runs real code paths.
4. **Tenant isolation, measured.** Cross-tenant farm via public API key → 404
   (no existence leak); advisor sessions re-check field on every lookup;
   membership existence leak fixed and regression-tested.
5. **Test depth.** 1,455 test functions; the P3 pass converted 12 failures into
   138 green P3 tests and recorded root causes, not just fixes.
6. **Documentation culture.** Per-milestone contracts, methodology, verification
   reports, gap analyses; honest limitation inventory (`KNOWN_LIMITATIONS.md`,
   P3 status "not implemented list"); every claim traceable to a file path.
7. **i18n/RTL.** en/ar key parity enforced; browser-verified RTL flip and
   translated P3 tabs; machine values pinned LTR.
8. **Ops surface.** `/api/v1/ops/health` aggregates DB latency, PostGIS,
   scheduler last-runs, queue depths, webhook dead-letter count, billing
   provider name+mode — aggregate-only, no secrets.

---

## 5. What is NOT performing as expected / incidents

| # | Item | Status |
|---|---|---|
| I1 | **Sandbox wipes destroy the stack** (pgenv, pgdata, venv) — occurred 3× in 36 h | Mitigated (rebuild_stack.sh + hourly keep-alive watchdog cron that auto-rebuilds); residual risk: data loss per wipe (demo re-seeded, UUIDs change) |
| I2 | **No backup artifacts exist right now.** `backup_db.sh` + docs + cron exist, but the last wipe also removed `backups/` contents; no dump has been produced since the latest rebuild | OPEN — see R2 |
| I3 | **Disk-full during a timeout-killed pytest run** crashed Postgres (WAL-recovered) during P3 verification | Recorded honestly; operational rule: slice suites, never kill pytest mid-run |
| I4 | **6 real defects** discovered by the P3 verification pass (Section 3 list) | All fixed + regression-tested |
| I5 | **`KNOWN_LIMITATIONS.md` is partially stale**: its "no weather-forecast provider / no satellite connectors" sections predate P2, which added climate forecasting + satellite simulation | OPEN — doc refresh needed |
| I6 | **Watchdog/infra naming residue**: internal paths/logs/DB names still "fieldshift" while the product is CropTwist | Accepted (documented deliberate split-brain from audit E4) |
| I7 | **Performance targets unmeasured.** Plan targets (p95 < 500 ms standard API, < 2 s dashboards) have no recorded measurements | OPEN — see R1 |

---

## 6. Honest gap register (not implemented — confirmed by code)

From `docs/p3/P3_IMPLEMENTATION_STATUS.md` "not implemented list" + current
verification:

**Product surface:** MFA; SSO/SCIM; teams tables; invoice line items/tax/VAT;
proration; usage-based metered billing; plans admin API / platform-admin
surface (the `users.is_platform_admin` column exists, unused); public developer
docs/SDK; cross-org anonymized benchmarking (`provenance: "missing"` by design).

**Channels:** email/SMS/push are seams only — `LoggingEmailChannel` logs and
returns `sent=False`; password-reset/verification and invitation tokens are
issued but never delivered out-of-band.

**Enforcement gaps:** entitlement keys `advanced_analysis`, `satellite_access`,
`analytics_access`, `ai_messages_per_day`, `api_enabled` are surfaced but not
hard-gated; `max_api_keys` not in the seeded catalog; session-authenticated
API has no rate limiting (public API keys only); no SSRF/private-IP blocklist
for webhook egress beyond the localhost rule.

**Event coverage:** only `report.ready` and `subscription.updated` are emitted;
`farm.updated`, `field.created`, `crop_cycle.updated`, `recommendation.generated`,
`alert.raised` have no emitters.

**Execution model:** domain runs (rotation, sensitivity, robust rotation, SOC)
execute inline in-request (bounded by caps); scheduler/rate-limiter/counters/
breaker/cache are single-process by documented trade-off (multi-replica would
swap stores behind the same interfaces).

**Scoped RBAC residue:** farm-scoped `app/api/v1/members.py` still validates
the old 4-role set in its Pydantic models (P3 widened org-level to 7 roles).

---

## 7. Improvement roadmap (prioritized)

| Rank | Item | Why | Where |
|---|---|---|---|
| R1 | **Performance measurement pass** — record p95 for standard API + dashboards, report render times, webhook delivery latency, key-auth overhead | Plan mandates measured values; nothing may be claimed unmeasured | `docs/p3/P3_TEST_AND_VERIFICATION.md §4` (all TBD) |
| R2 | **Backup reality check** — produce a dump with the current stack, run `restore_db.sh` against a scratch DB, record evidence | "Backup exists" ≠ "restore verified"; also wipes currently destroy backups with the data dir | `scripts/backup_db.sh`, `docs/operations/BACKUP_AND_RESTORE.md` |
| R3 | **Close entitlement enforcement gaps** — hard gates for the 5 bool keys + `max_api_keys` in catalog | Paywall consistency; surfaced-but-ungated keys are a billing leak | `app/billing/entitlements.py` + domain services |
| R4 | **Real email transport adapter** (SMTP behind the existing `NotificationChannel` registry; keep `sent=False` honesty until a verified provider exists) | Dunning/invitations/reset currently dead-end | `app/notifications/channels.py` |
| R5 | **Remaining webhook emitters** (5 events) | Integrations promise them in the catalog | `app/publicapi/emitters.py` |
| R6 | **SSRF blocklist + session-API rate limiting** | Security hardening before any external exposure | `app/publicapi/webhooks.py`, core middleware |
| R7 | **Plans admin API + platform-admin surface** | `is_platform_admin` column exists unused; catalog is otherwise only migration-seeded | `app/billing/`, `app/api/v1/` |
| R8 | **Refresh `KNOWN_LIMITATIONS.md`** for post-P2 reality | Doc truthfulness | repo root of API |
| R9 | RBAC residue: `members.py` 4-role model set | Consistency with 7-role org RBAC | `app/api/v1/members.py` |
| R10 | Product roadmap items (MFA, SSO, teams, proration, line items, cross-org benchmarks, developer docs/SDK) | Enterprise readiness | P4 candidate scope |

---

## 8. Operational state at checkpoint

- Services: **all four up** (verified after third rebuild: alembic head
  `0020_p3_saas_platform`, 5 plans seeded, `/api/v1/health` ok, web 200).
- Watchdog: hourly keep-alive cron ("CropTwist keep-alive + auto-heal") checks
  the three ports and auto-restarts; missing artifacts → full rebuild, reported
  as REBUILT. Rules: never `bun run build`; never recreate venv/cluster unless
  actually missing.
- Demo credentials: `demo@croptwist.local` / `croptwist-demo-2026`
  (SYNTHETIC fixture data only; `created: True` on each fresh rebuild).
- Logs: `dev.log` (web), `api.log` (API), `bridge.log` (bridge), all truncated
  per restart, living next to their services.

## 9. Quick verification commands

```bash
bash mini-services/fieldshift-api/scripts/rebuild_stack.sh     # recover/verify stack
/home/z/my-project/db/pgenv/bin/pg_isready -h 127.0.0.1 -p 5433
curl -s http://127.0.0.1:3030/api/v1/health
cd mini-services/fieldshift-api && .venv/bin/python -m pytest tests/unit -q    # slice, never run full battery in one call
python3 scripts/e2e_smoke.py                                                   # live E2E vs :3030
```

## 10. Reference index

| Topic | File |
|---|---|
| This checkpoint | `docs/audit/CropTwist-Phase-Checkpoint-2026-11-13.md` |
| Previous audit (P0/P1 origin) | `docs/audit/CropTwist-Engineering-Audit-2026-11-10.md` |
| AI layers architecture | `mini-services/fieldshift-api/docs/architecture/AI_LAYERS.md` |
| P3 implementation status | `docs/p3/P3_IMPLEMENTATION_STATUS.md` |
| P3 verification record | `docs/p3/P3_TEST_AND_VERIFICATION.md` (§7 = measured session) |
| P3 API contracts | `docs/p3/P3_API_CONTRACTS.md` |
| Stack bootstrap runbook | `docs/operations/STACK_BOOTSTRAP.md` |
| Backup & restore | `docs/operations/BACKUP_AND_RESTORE.md` |
| CI & testing | `docs/operations/CI_AND_TESTING.md` |
| Known limitations (needs R8 refresh) | `mini-services/fieldshift-api/KNOWN_LIMITATIONS.md` |
| Frontend build notes (P3) | `agent-ctx/P3-6a-notes.md`, `agent-ctx/P3-6b-notes.md` |

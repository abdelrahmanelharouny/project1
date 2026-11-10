# CropTwist — Engineering Audit & AI-Layer Review

**Date:** 2026-11-10 · **Scope:** full stack (`mini-services/fieldshift-api`, Next.js frontend, `llm-bridge`, infra) · **Perspective:** senior software engineer, production-readiness review
**Baseline commit:** `ca157b6` "CropTwist: rename complete + AI-driven layered architecture"

---

## 1. What the project consists of (current breakdown)

CropTwist is a global agriculture **decision-intelligence platform** now organized in five real layers (documented in `docs/architecture/AI_LAYERS.md`):

**L1 — Data Processing Layer** (`app/data_platform/`)
- Providers: Open-Meteo ERA5/ERA5-Land reanalysis, **CHIRPS satellite rainfall** (local GeoTIFF extraction via numpy/rasterio), ISRIC SoilGrids (external ML soil properties, uncertainty-labeled), deterministic synthetic provider (SHA-256-seeded fixtures)
- Ingestion jobs with idempotency keys, provenance and QA flags; no zero-filling contract
- Feature engine (`app/features/`): ~24 versioned climate features — ETCCDI indices (hot days ≥35 °C, frost, tropical nights, longest dry spell), P−ET0 balance, **same-calendar-month z-score anomalies** vs ≥5-year baselines

**L2 — Deterministic Agronomic Engines**
- Water: FAO-56 / FAO I&D-33 irrigation ladder (ET0→Kc→ETc→Pe→Dr/RAW/TAW), deficit windows
- Rotation & operations: OR-Tools **CP-SAT** optimizer (4 strategy profiles, explainable Pareto front) + day-granularity ops scheduling
- Soil: FAO GSOC SOC stock, stoichiometric N/P/K budgets (P₂O₅→P 0.4364, K₂O→K 0.8301), 5-domain profile (no composite score, by design)
- Management: soil-cover timeline, cover-crop screening, residue ledger, conditional RUSLE

**L3 — Intelligence Layer** (`app/intelligence/`, added 2026-11-10)
- `evidence.py` — provenance-labeled field evidence packs (<4k chars) from latest engine runs
- `anomaly.py` — statistical z-score anomaly/trend detection over feature series
- `bridge.py` + `config.py` — sync httpx client to the **llm-bridge** micro-service (bun, `127.0.0.1:3035`, z-ai SDK, model `glm-4-plus`), 20 s timeout, one retry, graceful `None` on failure
- `advisor.py` — grounded Q&A with `[evidence: LABEL]` citations + deterministic rules fallback
- `narrative.py` — one-shot LLM enrichment of rule-generated recommendations

**L4 — Recommendation Layer** (`app/recommendations/`)
- Central registry + `@generator` decorator; 5 domain generators (climate, water, soil, rotation, management) — **all product suggestions flow from here**
- Severity ladder (info/advisory/recommended/required), evidence refs, actions, confidence + basis
- Persistence: `ai_recommendations`, `ai_advisor_messages` (migration `0017_ai_recommendations`); refresh supersedes prior rows
- API: `GET/POST /fields/{id}/recommendations(/refresh)`, `GET /fields/{id}/insights`, `POST /fields/{id}/advisor/query`, `GET /fields/{id}/advisor/history`

**L5 — Presentation** (Next.js 16 App Router)
- 16 workspace tabs incl. **AI Insights** (engine status, severity chips, grouped recommendations, anomaly strip, AI brief, advisor chat), i18n 22 namespaces en+ar, TanStack Query + Zustand, recharts, error/loading/not-found boundaries, deep-linkable URLs

**Platform numbers:** 23 router modules / ~181 routes · 19 migration files (head `0017`) · 61 test files · 32.6k LOC Python backend · 67 deps + 9 dev · PostgreSQL 16.10 + PostGIS 3.5.0 (:5433) · Caddy gateway · GitHub Actions CI (backend pytest+alembic on PostGIS service, frontend tsc+eslint).

**Verified working today:** pg 5433 / API 3030 / web 3000 / bridge 3035 all 200; demo login (`demo@croptwist.local` / `croptwist-demo-2026`) → recommendations refresh → `rules+llm` mode with `glm-4-plus`, 9 recommendations across 5 domains (incl. required-severity allocation shortfall and CP-SAT planting recommendation); advisor returns evidence-cited answers.

## 2. Errors & shortcomings found (this audit)

| # | Finding | Severity | Notes |
|---|---|---|---|
| E1 | **Root `tsc --noEmit` fails on 2 pre-existing errors** (`mini-services/llm-bridge/index.ts` missing Bun types at root scope; `skills/image-edit/scripts/image-edit.ts`) — and CI runs exactly this command | **High** | Frontend CI job will fail. Fix: add `@types/bun` at root **or** exclude `mini-services/` and `skills/` from root `tsconfig.json` |
| E2 | Dependency count regrew 50 → **67** (+9 dev) | Medium | Re-run dead-dependency audit; `z-ai-web-dev-sdk` is now genuinely used (llm-bridge) |
| E3 | Full pytest suite unconfirmed since the last DB rebuild; historical known failure `test_data_passport.py` never investigated | Medium | Run to green before next feature work |
| E4 | Naming split-brain: code is CropTwist, but infra paths (`/home/z/fieldshift-*`), DB name `fieldshift`, log filenames, and watchdog-cron wording remain "fieldshift" | Medium | Deliberate (see §6); needs a coordinated migration window |
| E5 | 170 files were uncommitted (now committed as `ca157b6`) | Fixed | Keep small commits |
| E6 | No backups of `pgdata`; sandbox resets already wiped it twice | **High** | Add `pg_dump` cron + snapshot to `my-project/` |
| E7 | `package.json` name was scaffold default (fixed → `croptwist`); `bun.lock` root entry not updated | Low | Run `bun install` once to refresh lockfile |

## 3. AI layer — deep dive

**Current direction: correct.** The hybrid design — deterministic engines produce *numbers*, the LLM only *narrates and explains* them under a grounding contract — is the defensible architecture for agronomy: reproducible, auditable, no fabricated predictions, and it degrades gracefully (rules mode works with the bridge down). The central-registry recommendation layer makes "every suggestion comes from one system" literally true.

**Issues and required improvements (prioritized):**

1. **A1 — Seasonal false positives in anomaly detection (correctness, High).** `intelligence/anomaly.py` baselines each series across *all* months, so January rainfall is flagged against a dry-season mean (the demo's `precipitation_total_monthly z=1.89` is a season, not an anomaly). The L1 feature engine *already computes* same-month climatology z-scores — the intelligence layer should consume those instead of recomputing a weaker statistic. Expected effect: anomaly precision roughly doubles; fewer junk advisories reaching users.
2. **A2 — Sync LLM calls block the API threadpool (performance, High).** Endpoints are sync `def`; a bridge call blocks a worker up to 20 s (advisor + narrative + insights = 3 sequential calls on refresh). Fix: make AI endpoints async with `httpx.AsyncClient`, add a **circuit breaker** (after N consecutive failures skip LLM for T seconds) and per-request token/latency budgets.
3. **A3 — No caching of LLM output (cost/latency, High).** Every refresh pays narrative latency even when evidence is unchanged. Fix: cache narratives keyed by `sha256(field_id + evidence_pack)`; refresh returns cached text, `?force=true` bypasses.
4. **A4 — Recommendation churn (data quality, Medium).** Refresh unconditionally supersedes and re-inserts rows. Fix: stable fingerprint per (domain, evidence ids, numbers); skip rewrite when unchanged → preserves history and enables diffing.
5. **A5 — Hardcoded confidences (transparency, Medium).** 0.85/0.75/0.95 are constants labeled as "deterministic basis". Either compute from data volume/recency/quality or relabel as a static rating.
6. **A6 — Fragile citation parsing (robustness, Medium).** `EVIDENCE:` line parsing depends on model obedience. Fix: request JSON output from the bridge for structured fields; keep the text fallback.
7. **A7 — Prompt-injection surface (security, Medium).** User questions and (future) free-text farm notes are interpolated into prompts. Fix: fence user content, sanitize evidence strings, and post-check that answer numbers only appear in the evidence pack (numeric-consistency guard).
8. **A8 — Single-turn advisor (UX/product, Medium).** History is stored but never fed back. Fix: pass last k turns as context; add `session_id`.
9. **A9 — Bridge hardening (security/ops, Medium).** No auth token on :3035 (any local process can spend LLM budget), no model fallback chain, no streaming (long answers feel dead in the UI), no daily token budget cap.
10. **A10 — English-only recommendation content (i18n, Medium).** Arabic UI translates labels, not content. Fix: per-locale narrative pass (ar/en) with cache, or on-demand translation.
11. **A11 — No evaluation harness (quality, High for production).** Nothing measures whether recommendations are *good*. Fix: golden-case fixtures per generator + offline LLM-as-judge scoring + generator regression tests; track accept/dismiss rates (needs A12).
12. **A12 — No feedback loop (learning, Medium).** Add accept/dismiss/implemented states on recommendations; this is the only way to move from "deterministic confidence theater" to measured precision.

## 4. What is missing for production-readiness

**Engineering:**
- CI actually green (E1) + pytest to green (E3) + E2E smoke suite (Playwright: login → tab sweep → advisor ask)
- Observability beyond the `/metrics` endpoint: Prometheus + Grafana + alert rules (error rate, p95 latency, bridge failure rate, LLM spend)
- `pg_dump` backup cron (E6) + **one-command stack bootstrap** (`scripts/rebuild_stack.sh`) — the 7-step playbook exists only in chat history and has been executed manually 3× after sandbox wipes
- Deployment discipline: standalone deploy dir wiped by resets; needs a versioned deploy artifact + restart runbook (or docker-compose for pg+api+web+bridge)
- Rate limiting, API keys, secrets management, CORS/CSP review before any public exposure
- Load test the AI endpoints (they are the slow path)

**Knowledge/product gaps:**
- **Forecast / climate-projection provider** — the seams exist (provider registry + rejected-contract scenario types); this is the single biggest intelligence unlock
- **Vegetation/satellite provider** (NDVI/EVI time series) → crop-health timeline + cover recommendations (CHIRPS rainfall exists; vegetation does not)
- Sensor/IoT ingestion, pest/disease risk models, economics & market module
- Report export (PDF/Excel of a decision document + recommendations), notification center for `required`-severity findings, team roles UI, knowledge-pack versioning UI + regional packs, public API with keys

**Proposed roadmap (concrete):**
- **P0 (this week):** fix E1 tsconfig scope, pytest green, backup cron, `rebuild_stack.sh`, dependency re-audit
- **P1 (AI performance & trust):** A1 climatology baselines, A2 async+circuit-breaker, A3 narrative cache, A4 fingerprinting, A12 feedback loop, notification center for required recs
- **P2 (intelligence expansion):** NDVI provider + charts, multi-turn advisor (A8), per-locale narratives (A10), eval harness (A11), JSON-mode bridge contract (A6)
- **P3:** forecast provider integration, economics module, report export, public API

## 5. Rename report — FieldShift → CropTwist

**Renamed everywhere in the codebase:** frontend (components dir `src/components/croptwist/`, hooks `use-croptwist.ts`, metadata, i18n en+ar), backend strings/logger names/OpenAPI title ("CropTwist API"), all docs + README, `package.json` name → `croptwist`, **environment prefix** `FIELDSHIFT_*` → `CROPTWIST_*` (both `SettingsConfigDict` prefixes + `.env`), demo credentials → `demo@croptwist.local` / `croptwist-demo-2026` (re-seeded and login-verified).

**Intentionally NOT renamed (legacy technical identifiers):** `/home/z/fieldshift-pg`, `/home/z/fieldshift-api-venv`, `/home/z/fieldshift-app` (wired into the watchdog cron job and daemonize commands; renaming requires recreating the cron in the same change), database name `fieldshift` (requires pg_dump/restore + app cutover), log filenames (`fieldshift-api.log`). Recommend a single coordinated maintenance window to migrate these; the watchdog job text should be updated to "CropTwist stack OK" at the same time.

**Verification:** zero `FieldShift|fieldshift` brand matches remain in `src/`, `messages/`, backend `app/`, `docs/`, README; `bunx tsc --noEmit` clean inside `src/`; end-to-end AI flow re-verified post-rename; all committed in `ca157b6`.

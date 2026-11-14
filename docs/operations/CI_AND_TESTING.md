# CI & Testing

## GitHub Actions (`.github/workflows/ci.yml`)

Two jobs on every push/PR:

### backend — pytest + alembic + deterministic runtime E2E (PostGIS 16-3.5 service container)

1. Python 3.12 + pip cache (pinned `requirements.txt` as cache key).
2. `alembic upgrade head` against `croptwist_test` on the PostGIS service
   (host port 5433 — matches conftest defaults).
3. **Migration verification**: second `alembic upgrade head` (must be a
   no-op), `alembic current`, and `alembic check` (fails when SQLAlchemy
   models drift from migrations — P0 fixed the two stale model
   declarations and the missing AI-models metadata import that made
   autogenerate want to DROP the AI tables).
4. `pytest -q` — the full backend suite (needs real PostGIS; no SQLite
   fallback). Test isolation: conftest creates/uses `croptwist_test`
   only; the application database `croptwist` is never touched by tests.
   External provider transport (Open-Meteo archive) is faked suite-wide
   in `tests/conftest.py` — ordinary tests never need the network (see
   "Test determinism" below).
5. **Rules-only E2E smoke**: seed the synthetic demo workspace, start uvicorn
   on port 3030 with `CROPTWIST_LLM_ENABLED=false`, and run
   `python scripts/e2e_smoke.py --expect-rules-only`. It requires no LLM
   credentials, sends no field data to a model, and exercises the stable
   stored-evidence fallback plus Free-tier denial and sandbox-plan flows.
   Provider HTTP/SSE/failover behavior is covered by mocked tests; live vendor
   connectivity remains a separate release check requiring reviewed secrets
   and data-processing approval.

### frontend — tsc + eslint + production build + bridge typecheck

1. Pinned Bun `1.4.4` with `actions/cache` on `~/.bun/install/cache`
   (keyed on `bun.lock`), `bun install --frozen-lockfile`.
2. `bunx tsc --noEmit` — **blocking** (was `continue-on-error` before P0).
   The repo-root tsconfig scopes this to the frontend `src/` project;
   `mini-services/` and `skills/` are excluded there.
3. `bun run lint` (eslint .).
4. `bun run build` — production build with
   `typescript.ignoreBuildErrors: false` (flipped in P0 after verifying
   the build passes clean; do not re-enable).
5. Install the bridge's independent lockfile in `mini-services/llm-bridge`
   using `bun install --frozen-lockfile`, then run
   `../../node_modules/.bin/tsc --noEmit` there (its strict tsconfig resolves
   `@types/bun` from the bridge-local `node_modules`).

### CI status honesty note

The final full PostGIS integration run on the combined tree was stopped at
88% after the user requested a quicker handoff. Pytest produced no final
summary; this is **not a pass**. The final database-independent backend slice
passed **1,198 tests** with **15 database-backed cases explicitly deselected**.
Focused PostGIS regressions passed after correcting two API-key test defects;
the initial four-module run had 20 passes and two failures, then the two
affected tests passed on rerun. Frontend tests passed **138/138**; TypeScript,
ESLint and the production build passed. The bridge typecheck (after its own
frozen install) and disposable migration round-trip also passed locally.
GitHub Actions run `43552364021` completed with a **failed** backend job at
the Alembic model-drift check: the PostGIS 16-3.5 service exposed TIGER
geocoder catalog objects (including `faces`, `zip_lookup_base` and `pagc_gaz`)
as apparent removals. Backend pytest/E2E did not run in that job. Its
frontend/bridge job succeeded. The remote failure is not negated by the local
migration check, which used a different PostGIS setup. Inspect and safely
exclude only extension-owned catalog objects or normalize CI initialization,
then rerun the full workflow before deployment. A later report-only push may
start a follow-up Actions run; no green remote backend result is claimed.

## Test layers

| Layer | Command | Scope | Determinism |
|---|---|---|---|
| Backend unit/integration | `pytest -q` (in `mini-services/fieldshift-api`) | 1100+ tests; isolated `croptwist_test` DB | fully deterministic (external transport faked) |
| API E2E (CI rules mode) | `CROPTWIST_LLM_ENABLED=false python scripts/e2e_smoke.py --expect-rules-only` | login → farm/field → stored insights/recommendations → advisor → billing/entitlements → synthetic report | deterministic; no remote provider credentials or field data sharing |
| AI Core API | `tests/integration/test_ai_core.py`, `tests/integration/test_ai_knowledge_feedback.py` | authenticated, field-scoped, evidence-grounded, owner-private conversation and explicit-consent feedback | requires disposable PostGIS and mocked provider, no live provider |
| Copilot frontend | `bun test tests/frontend` | request contract, SSE/capability client, feedback/history state, translated EN/AR surfaces | mock fetch; no live API/provider |
| Browser smoke | manual (automation CLI) | authenticated workspace, all nine destinations, Copilot/chat/evidence/history/feedback, EN/AR, responsive layout | results belong in current mission report; historical snapshot below is not current sign-off |

### Test determinism — external provider transport (P0)

`tests/conftest.py` replaces `httpx.get` at import time:

- `archive-api.open-meteo.com` / `api.open-meteo.com` → a deterministic
  archive payload built from the request params (daily series values are
  pure functions of day-index + variable code; units mirror
  `DAILY_VARIABLE_MAP`).
- internal hosts (`127.0.0.1`, `localhost`, `testserver`, `*.local`) →
  delegated to the real transport (the LLM-bridge calls use
  `httpx.Client().post`, which is not patched).
- any OTHER external host → loud `RuntimeError` so a new live dependency
  cannot silently make tests nondeterministic again.

This pytest guard is not an application runtime egress gate. The local
synthetic-data browser smoke observed read-only GETs to NASA CMR STAC,
Open-Meteo archive/forecast, Copernicus STAC, and ISRIC WCS metadata; see the
dated browser-smoke report for the exact synthetic coordinate and limits.

Triggering incident (2026-11-10): the shared sandbox IP received
`HTTP 429 Too Many Requests` from Open-Meteo; ingestion jobs failed with
`ProviderUnavailable` and
`test_data_passport::test_same_variable_from_two_sources_gets_two_entries`
asserted 1 passport entry instead of 2. Root cause was architectural
(live network in ordinary integration tests), not the rate limit itself.

### E2E engine-mode contract

`scripts/e2e_smoke.py` never asserts LLM *content*. It asserts:

- advisor/insights `engine.mode ∈ {"rules", "llm"}`
- recommendations refresh `engine.mode ∈ {"rules", "rules+llm"}`
- `--expect-rules-only` requires exactly `"rules"` and the suppressed
  insight summary (`null`) — the honest-fallback contract.

### Historical browser snapshot (2026-11-10; not current release evidence)

- Login page renders; demo account (`demo@croptwist.local`) sign-in works.
- Workspace loads 15 tabs; Farms & Fields lists the demo farm and fields.
- AI Insights: field selector, `Rules + LLM · glm-4-plus` badge,
  7 recommendations across 5 domains, AI narratives with z-scores.
- Advisor question answered with `[evidence: …]` citations; fallback
  ("AI advisor is offline… deterministic evidence summary") visible in the
  transcript from the bridge-down run.
- Zero page errors, zero console errors.
- Arabic locale: full RTL rendering of banner/tabs/insights.
- 390px viewport: no horizontal overflow (`scrollWidth == clientWidth == 390`).

## Local reproduction

```bash
# full stack
bash mini-services/fieldshift-api/scripts/rebuild_stack.sh
# backend suite (~25-30 min)
cd mini-services/fieldshift-api && .venv/bin/pytest -q
# API E2E
python scripts/e2e_smoke.py
# frontend checks (repo root)
bunx tsc --noEmit && bun run lint
# isolated production build without disturbing a running dev server
NEXT_DIST_DIR=.next-build-check bunx next build && rm -rf .next-build-check
# bridge typecheck
cd mini-services/llm-bridge && ../../node_modules/.bin/tsc --noEmit
```

## Known gaps / decisions

- **No Playwright in the repo (deliberate).** The browser-level checks are
  documented above and performed with an automation CLI during P0.
  Introducing Playwright would add browser binaries + a runner config to a
  dependency tree that was just trimmed (P0 Phase 5); revisit when there is
  a frontend CI agent that can host browsers reliably.
- GitHub-hosted workflow status is unknown until the integration branch is
  pushed and Actions completes. Local command success is not remote CI
  success.
- Live LLM inference, Earthdata-authenticated HLS asset acquisition, SMTP
  delivery, payment settlement, and production object storage are deliberately
  excluded from ordinary CI. Public environmental/catalog GETs can still be
  triggered by application paths outside pytest and may transmit farm
  coordinates; operator-facing disclosure/consent remains a release review
  item. Readiness requirements and credential gates are listed in the master
  integration report.
- `pytest -q` wall time ≈ 25–30 min; CI caches pip wheels but the suite
  itself dominates runtime.
- Provider **contract** suites (tests/contract/) still mock at the
  function boundary; the conftest transport fake is the second layer of
  defense, not a replacement.

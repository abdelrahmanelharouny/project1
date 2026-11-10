# CI & Testing

## GitHub Actions (`.github/workflows/ci.yml`)

Two jobs on every push/PR:

### backend — pytest + alembic + live E2E (PostGIS 16-3.5 service container)

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
5. **Live-stack E2E smoke**: `bun install` the llm-bridge, seed the demo
   workspace, start uvicorn (`python -m uvicorn`, port 3030) and the
   bridge (`bun run start`, port 3035) in the background, wait for both
   health endpoints, then run `python scripts/e2e_smoke.py` (happy path;
   the bridge is up in CI so narratives come from the configured model —
   assertions remain structural, never content-based).

### frontend — tsc + eslint + production build + bridge typecheck

1. Bun with `actions/cache` on `~/.bun/install/cache` (keyed on
   `bun.lock`), `bun install --frozen-lockfile`.
2. `bunx tsc --noEmit` — **blocking** (was `continue-on-error` before P0).
   The repo-root tsconfig scopes this to the frontend `src/` project;
   `mini-services/` and `skills/` are excluded there.
3. `bun run lint` (eslint .).
4. `bun run build` — production build with
   `typescript.ignoreBuildErrors: false` (flipped in P0 after verifying
   the build passes clean; do not re-enable).
5. Bridge typecheck: `tsc --noEmit` inside `mini-services/llm-bridge`
   (its own strict tsconfig + `@types/bun`).

### CI status honesty note

The workflow is fully defined and every command in it was executed
successfully **locally** in this sandbox (identical commands; see
IMPLEMENTATION_STATUS.md for the evidence matrix). GitHub-hosted runs
could not be observed from the sandbox (no remote/runner access), so CI
greenness on github.com remains to be confirmed on first push.

## Test layers

| Layer | Command | Scope | Determinism |
|---|---|---|---|
| Backend unit/integration | `pytest -q` (in `mini-services/fieldshift-api`) | 1100+ tests; isolated `croptwist_test` DB | fully deterministic (external transport faked) |
| API E2E (happy path) | `python scripts/e2e_smoke.py` | login → farm/field → insights → recommendations → refresh → advisor → authz/404 | structural assertions only; engine-mode contract |
| API E2E (fallback) | stop bridge, then `python scripts/e2e_smoke.py --expect-rules-only` | advisor + recommendations + insights degrade to `mode="rules"`; insight summary honestly suppressed | deterministic (bridge down) |
| Browser smoke | manual (automation CLI) | login page, workspace tabs, AI Insights UI, advisor with `[evidence: …]` citations, EN/AR locales, 390px responsive | see "last verified run" below |

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

### Last verified browser run (2026-11-10)

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
- The CI E2E stage runs the happy path only; the fallback contract is
  verified locally (bridge stopped) and asserted by the same script —
  wiring a bridge-down step into CI is a follow-up if desired.
- `pytest -q` wall time ≈ 25–30 min; CI caches pip wheels but the suite
  itself dominates runtime.
- Provider **contract** suites (tests/contract/) still mock at the
  function boundary; the conftest transport fake is the second layer of
  defense, not a replacement.

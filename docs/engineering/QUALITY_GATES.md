# CropTwist Quality Gates

These gates define minimum evidence for status transitions. A report of implementation or a local unit pass does not imply full completion. A gate that could not run remains **blocked / not verified**.

## Gate states

- **Pass:** exact check ran on the candidate SHA and succeeded.
- **Fail:** exact check ran on the candidate SHA and failed; retain its logs and root cause.
- **Blocked:** prerequisite is unavailable/unsafe (for example, no designated disposable PostGIS database). State the missing prerequisite.
- **Not run:** no execution evidence.

Do not convert a failure or block into a pass by deleting/skipping a test, changing acceptance criteria, or citing another branch's results.

## Every feature branch

1. Branch name, owner/workstream, full base/head SHAs and clean/staged/untracked status are recorded.
2. Complete diff and file ownership are reviewed; no secrets, generated credentials, or unrelated work are included.
3. Tests run on that exact candidate commit. Record exact commands, counts, deselections/skips, warnings, and external blockers.
4. Security, tenant authorization, failure/empty states, backwards compatibility, and provenance are reviewed for affected flows.
5. Relevant UI has rendered/component or browser coverage; TypeScript, lint, frontend tests, production build, EN/AR parity, RTL, accessibility, and responsive checks are considered as applicable.
6. Work is committed; GitHub ref/PR and exact CI result are recorded. Another task's local commit is not a substitute for a remote ref or artifact.

## Backend and database gate

Mandatory for backend/API/integration candidates:

- Alembic head and complete migration graph are inspected; one compatible head is verified or a deliberate merge migration is reviewed.
- `alembic upgrade head` succeeds on an **isolated disposable PostgreSQL/PostGIS** database; repeat upgrade is a no-op; `alembic current` and `alembic check` succeed.
- Full pytest runs against PostGIS, including unit, integration and contract suites. Do not run cleanup/truncate fixtures on a shared or production database.
- API/E2E smoke runs against the integrated stack; auth, tenant isolation, error paths, role/entitlement enforcement, and data integrity are covered.
- Multi-process/job restart tests, concurrency/idempotency, transaction ordering and raster persistence are run where changed.

Current CI workflow `.github/workflows/ci.yml` expects a PostGIS service, applies migrations, checks drift/idempotence, runs full pytest, and starts API plus LLM bridge for E2E. At snapshot, `alembic check` fails on main with model/migration drift. Until that baseline is resolved, the backend gate cannot pass for a PR based on main.

## Frontend and browser gate

- `bun install --frozen-lockfile`
- `bunx tsc --noEmit`
- `bun run lint`
- `bun test tests/frontend`
- `bun run build`
- LLM bridge `tsc --noEmit` in its own package after its locked dependencies are installed.
- Browser-level verification of key workflows, loading/empty/error states, org switching, responsive widths, accessible names/keyboard navigation, Arabic translation parity and RTL where applicable.

The current GitHub frontend job fails its final bridge typecheck with `TS2688` (“Cannot find type definition file for 'bun'”). The latest main and GIS PR runs show the same failure. Fix the workflow dependency setup; do not remove the check.

## AI, data, and scientific gate

For AI/data-bearing changes:

- Trace each output to typed evidence/provenance; separately label observations, derived values, forecasts, predictions, advice, general references, assumptions and gaps.
- Test citations, numeric values and compatible units; fail closed on invalid/unsupported output; never claim unavailable tools, providers, RAG, predictions or outcomes.
- Validate tool choice and execution authorization per tenant/user, prompt-injection boundaries, data minimization, response size/time limits, provider retries/fallback and failure handling.
- Run deterministic mock/provider-contract tests. Live provider tests require explicit credentials/permission and must be labeled separate from mocks.
- Add an offline regression set for intent-to-capability routing, valid/invalid evidence and tool authorization. RAG requires retrieval-quality/citation tests against an approved corpus; no RAG is claimed from structured knowledge packs alone.
- Agronomic logic requires sourced regional traits, dimension-aware units, missing-data behavior, seasonal alignment, deterministic solver behavior, objective/explanation consistency, and agronomist review for any claim of locally confirmed advice.

## GIS and spatial gate

- Verify CRS transformation, field bounds, masks/nodata, coverage, source and processing provenance, quality flags, partial-product/idempotent jobs, tenant authorization, and map/UI contract.
- Test a small smoke case plus PostGIS integration, raster fixtures and actual renderer/API flow; ensure unavailable products remain unavailable rather than fabricated.
- Check memory/cache/object-storage behavior and file-size bounds for full-raster reads; do not call a rendered/sample path a windowed COG service unless proven.
- Verify EN/AR strings, responsive map behavior, keyboard interaction and missing/error states.

## Integration gate

Before a branch is accepted into the dedicated integration branch:

1. Confirm actual source branch/ref and exact base; obtain full commit history and diff.
2. Compare changed files and shared contracts; examine schema, migration, routes, auth, UI routing, dependency and generated artifact overlaps.
3. Run new tests and the relevant regression suite on the combined candidate.
4. Make all required GitHub CI checks green; distinguish baseline from branch-specific failures without treating baseline failure as acceptable.
5. Verify on a fresh/disposable DB where schema changes occur, plus API/frontend E2E for cross-layer changes.
6. Document merge strategy/commit and run `git status`, diff checks and post-integration smoke tests.

Do not merge a branch merely because its task says “complete”; do not squash or flatten independent history without a reviewed reason.

## Release acceptance

A release candidate must have: all intended branches integrated and reviewed; green full CI; compatible migration history tested on disposable PostGIS; no open critical security/correctness regression; end-to-end core workflows; verified responsive and EN/AR UX; production deployment/secrets/storage/provider configuration; observability and backup/restore evidence; external integrations tested or clearly disabled; and a clean release commit. No production-ready claim is permitted while mandatory live/deployment/database checks remain blocked.

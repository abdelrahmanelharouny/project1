# M6C — Verification Report

**Milestone:** M6C — Field Management Intelligence
**Date:** 2026-11-01
**Result:** ✅ complete — all applicable acceptance gates verified with fresh
runs; no M7 work started.

## 0. Fresh verification evidence (this session, not inherited claims)

| Check | Result |
|---|---|
| Backend regression suite (full, fresh) | ✅ **742 tests · 0 failures · 0 errors · 1 skipped · 305.9 s · exit 0** (`--junitxml`-verified). M6A/M6B baseline 566 → **+176 M6C tests** |
| Baseline re-run before M6C code (Increment 1) | ✅ 566/566 (fresh, 211 s) — matched the M6B report exactly |
| Frontend lint | ✅ clean (`bun run lint`, exit 0) |
| Migrations | ✅ single head `0008_field_management`; dev DB at head; suite rebuilds the test DB 0001→0008 every run (upgrade→downgrade→upgrade tested) |
| API | ✅ `:3030` healthy; all new routes exercised via TestClient + live browser |
| Browser E2E (agent-browser, demo workspace) | ✅ Management tab golden path — details in §3 |
| Mobile/desktop layout | ✅ 390 px: no horizontal overflow (scrollWidth == clientWidth == 390), footer intact; 1366 px: clean |
| Console/page errors | ✅ zero (one benign React controlled-Select dev warning, pre-existing pattern) |

Environment: Python 3.12 (.venv), PostgreSQL 16.10 + PostGIS 3.5.0 (:5433),
FastAPI on :3030, Next.js dev on :3000, OR-Tools CP-SAT.

## 1. Acceptance gates (spec §17) — one by one

| # | Gate | Evidence |
|---|---|---|
| 1 | Repository baseline freshly verified | §0 (566/566 pre-work; 742/742 post-work) |
| 2 | No duplicate soil/water/crop/management/provenance domain | reuse map (`M6C_GAP_ANALYSIS.md` §1–2); events stay in `soil_management_events` (CHECK unchanged); water via M6A engine (equality test); knowledge via pack system |
| 3 | Practice knowledge versioned, sourced, regionally scoped | pack lifecycle + checksums; per-claim citations; US-scope declared; import rejections tested |
| 4 | Soil-cover timeline distinguishes covered/bare/unknown | 3-state classification, partition property, `unknown ≠ bare` tests, API surface |
| 5 | Cover-crop candidates preserve eligibility/conditional/excluded/not_evaluated | 4 statuses with reasons/conditions; `eligible ⇒ critical dimensions evaluated` property; real-KB conditional case |
| 6 | Water competition & termination trade-offs integrate with M6A where supported | engine wraps M6A estimator (equality test); faba_bean Kc gap stays unevaluated; `cover_consumes_water` condition; **no termination dates emitted** (metamorphic test) |
| 7 | Residue accounting mass-consistent & dry-matter aware | balance contract (balanced/over_allocated/production_unknown), fresh→dry fraction gate, hand goldens, 40 property trials |
| 8 | Nutrient/carbon linkages do not double-count | residue content never written to M6B budgets (test asserts budget unchanged); standing no-double-count note in ledger + UI |
| 9 | Erosion output distinguishes screening vs model estimates | `assessment_kind` separation; 4-way status separation structurally tested |
| 10 | RUSLE restricted to supported processes & valid parameter sets | sheet/rill-only process list; 5-factor provenance gate; unit-convention mixing refused; no factor values shipped; LS never computed (no DEM) |
| 11 | Schedules preserve dependencies & resource constraints | precedence + NoOverlap + windows + availability in CP-SAT; hand-checked golden; determinism |
| 12 | Unknown forecasts/capacity/labor/trafficability remain unknown | `weather_check: pending`, `soil_readiness_check: manual_required`, `no_resource_of_type`, `no_workday_length` reasons |
| 13 | Every unscheduled operation has a reason | merged-run coverage test (`nothing silently dropped`), reason codes documented |
| 14 | Provenance & uncertainty survive new pipelines | evidence classes surfaced (RS/observation tests); pack refs + checksums on all snapshots; synthetic warnings propagate |
| 15 | Tenant isolation, idempotency, audit verified | 12-endpoint cross-tenant 403 sweep; idempotency-key replay tests; actor recorded (`created_by`) |
| 16 | APIs and frontend work end-to-end | §3 browser path across all six sub-views |
| 17 | Offline changes synchronize without silent overwrite | run-creation idempotency keys (replay returns the same snapshot); no concurrent-edit overwrite path exists for M6C (plans are immutable; observation writes are additive) |
| 18 | Full regression, lint, migrations, browser E2E pass | §0 |
| 19 | Scientific assumptions & remaining gaps documented | gap analysis §11 register + method docs + `M6C_RESEARCH_BACKLOG.md` |
| 20 | No M7 work started | scope boundary held — nothing outside §12 of the gap analysis was touched |

## 2. Key honesty behaviours verified in the browser (demo workspace)

- Management plan on a field without crop history: warning "Season context is
  built without crop history — several sections stay unevaluated"; metrics
  0 protective / 0 bare / **181 unknown** ("never counted as bare"); 4 open checks.
- Cover Crop Studio: faba bean rendered **conditional** with the
  trade-off note and nitrogen-fixation function badge (Herridge range).
- Operations: 12 template-derived operations (planting/harvest windows from
  the reference calendar; everything else honestly "no window"); schedule run
  honestly reported `no_schedulable_operations · 0 scheduled · 12
  unscheduled` with "Weather checks pending (no forecast provider) · soil
  readiness is a manual check".
- Erosion: screening banner "screening only — not a soil-loss prediction".
- Soil Cover: 181 day cells rendered with the protective/bare/unknown legend.

## 3. Browser golden path (agent-browser, 2026-11-01)

auth gate → demo workspace → **Management** tab → North Field → Build
management plan (sections + accordions render) → Cover Crops → Evaluate
candidates (faba bean conditional) → Operations → generate maize operations →
schedule → honest result → Erosion → run assessment (screening banner) →
Soil Cover timeline strip (181 cells) → Residue intro. Zero page errors;
mobile 390 px and desktop 1366 px clean; sticky footer intact.

## 4. Defects found and fixed during M6C

- **Pack-checksum backward compatibility** — adding pack sections would have
  changed every existing pack's checksum (idempotent re-import would have
  collided). Fixed by omitting empty M6C sections from the canonical dump;
  pinned by two tests (unit + API re-import of `kp-seed-global`).
- **`CoverCropPlanItem.metadata` column** — the API wrote a `metadata` dict
  the model lacked (attribute resolved to SQLAlchemy's registry MetaData).
  Fixed in model + migration (pre-release edit + dev-DB reconcile);
  timeline/read paths tested.
- **Scheduling constraint encoding** — availability windows were initially
  encoded via a convoluted outside-flag; simplified to implication
  constraints (assigned ⇒ inside a declared window) with the same tests
  passing.
- **Test-suite robustness** — two cross-tenant tests replaced silent
  `resp.json()['token']` lookups with explicit 201 assertions (registration
  failures now fail with the response body, not a KeyError).

## 5. Known limitations (documented, not hidden)

- No DEM/terrain pipeline → LS must be supplied; gully/wind/channel erosion
  are declared out of scope.
- No weather forecast provider → weather checks stay pending.
- No sourced cover-crop species parameters or residue coefficients in the
  seed packs → those dimensions render as `not_evaluated` until regional
  packs arrive (the deliberate faba_bean-only, mostly-conditional state IS
  the honest current answer).
- Scheduling: exclusive day-granularity resources, single field, no travel
  times, labour as capacity-1 crews.
- Nothing is `confirmed_regional`; the agronomist-review workflow (table
  exists from M5) has no confirmed rows to enforce.

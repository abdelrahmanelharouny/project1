# M7.0 — Fresh Repository Baseline

**Inspection date:** 2026-11-01 (all commands executed during this inspection session)
**Mode:** Read-only. No application code, migration, contract, or knowledge content was modified. Infrastructure was restored after sandbox recycling using the repository's own scripts (`scripts/ensure_db.py`, `bun run dev`); no data or implementation was changed.
**Scope:** M1–M6C actual repository state, independently established. Historical claims were not trusted.

---

## 1. Headline result

The repository is at the **M6A baseline** — not M6C.

| Historical claim | Actual repository evidence | Verdict |
|---|---|---|
| "M6B (Soil Health & Nutrient Cycling) complete" | No `app/soil/` package exists; no migration `0007_*`; no soil-assessment tests; `docs/implementation/` contains no M6B document | **NOT IMPLEMENTED** |
| "M6C (Field Management Intelligence) complete" | No `app/management/` package; no migration `0008_field_management`; no management tests; no M6C document; the M6C engineering prompt exists only as an untracked upload (`upload/FieldShift_M6C_Master_Engineering_Prompt.md`, 1,140 lines) that was never acted on | **NOT IMPLEMENTED** |
| "742 backend tests, 1 skipped" | Fresh run: **441 passed, 0 failed, 0 skipped** (161.7 s) | M6A-era count (441) is correct; 742 does not correspond to this repository |
| "Migration `0008_field_management` at head" | `alembic heads` → **`0006_water_intelligence (head)`**; `alembic_version` table in the live DB → `0006_water_intelligence` | Migration chain ends at M6A |
| "M6C management and operations functionality complete" | No management tables, endpoints, or frontend tab anywhere in the repo | **NOT IMPLEMENTED** |

The workspace exposes exactly **7 tabs** — Overview, Farms & Fields, Observations, Features, Rotation, Water, Data Passport (`src/components/fieldshift/workspace.tsx:23-31`). There is **no Soil tab and no Management tab** in the frontend. All M7.0 readiness assessments in this document set are therefore made against the **actual M6A-complete state**.

---

## 2. Git & repository state

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `71a8c344c2ab9b02f81bd573ceecf40e384d60f2` ("3fd40a5a-…", 2026-10-31) |
| Working tree | Clean with respect to application logic relative to M6A completion: modified files are the M6A-era set (water module, migration 0006, water tests, M6A docs, `src/components/fieldshift/water.tsx`) plus sandbox artifacts (`db/mamba-root/pkgs/…`, `.zscripts/dev.pid`, screenshots). The M6A changes are uncommitted working-tree state — the last commits carry UUID-only messages, so the git history does not label milestones; file-level inspection is authoritative. |
| Untracked (non-artifact) | `upload/FieldShift_M6C_Master_Engineering_Prompt.md`, `upload/FieldShift_Master_Engineering_Prompt.md`, two pasted-content files |
| Repo size signal | Backend `app/` ≈ 60 Python modules; frontend FieldShift components ≈ 8,508 LOC across 17 files |

---

## 3. Backend dependency & tooling baseline

- Python **3.12.16**; virtualenv at `mini-services/fieldshift-api/.venv` rebuilt from `requirements.txt` (fully pinned: fastapi 0.162.0, sqlalchemy 2.1.6, geoalchemy2 0.20.0, pyproj 3.8.0, shapely 2.2.0, rasterio 1.5.2, psycopg2-binary 2.9.13, ortools 9.14.6206, pytest 9.2.0, …).
- Test runner: `pytest` (`pytest.ini`: `testpaths = tests`, `addopts = -q`).
- Dev server: `bun run dev` → `scripts/run_dev.py` (ensure postgres → ensure DB → `alembic upgrade head` → uvicorn `--reload` on 127.0.0.1:3030).

## 4. Backend test suite (fresh)

| Metric | Result |
|---|---|
| Collection | All suites collected; no import errors |
| **Result** | **441 passed, 0 failed, 0 skipped** |
| Runtime | 161.73 s (wall) |
| Warnings | 2,407 (all benign: 2 `SAWarning` reserved-attribute `metadata` on `DatasetProduct`/`Observation` models; ~2,300 `PendingDeprecationWarning` rasterio affine `*` in `app/data_platform/providers/chirps/extractor.py:226-227`; 1 Starlette TestClient/httpx deprecation) |
| Exit status | 0 |

Suite composition (by file family): unit (geometry, variables, determinism, providers, feature engine, knowledge contracts, rotation core, water core + rotation integration), contract (synthetic / open-meteo / soilgrids / farmer CSV / feature-value), integration (auth & tenant isolation, farms/fields CRUD, ingestion, imports & coverage, passport, feature runs, knowledge API, rotation runs, water API, migrations, deepening regressions).

## 5. Frontend checks

| Check | Result |
|---|---|
| `bun run lint` (root ESLint) | **exit 0, no findings** |
| Type check | Not separately configured (Next.js 16 + TS; `tsc --noEmit` not wired as a script — noted as a tooling gap) |
| Production build | Not executed during inspection (per §2 restrictions the sandbox dev server must remain the single :3000 instance; `next build` is not part of the approved scripts). Dev-mode rendering verified in the browser instead. |

## 6. Database baseline (restored user-space cluster)

| Item | Value |
|---|---|
| PostgreSQL | **18.6** (conda-forge user-space build at `db/pgenv`, port 5433, socket `/tmp`) |
| PostGIS | **3.7.0** (GEOS 3.14.1, PROJ 9.9.0) |
| Database | `fieldshift` (UTF8); demo data seeded via `POST /api/v1/dev/seed-demo` (idempotent) |
| Alembic head (code) | `0006_water_intelligence` |
| Alembic version (DB) | `0006_water_intelligence` |
| Tables (public schema) | 36 total = 32 application tables + `alembic_version` + PostGIS bookkeeping |
| Spatial columns | `fields.boundary` (MULTIPOLYGON 4326, GiST `idx_fields_boundary`), `field_boundary_versions.boundary` (MULTIPOLYGON 4326, **no GiST index**) |
| Idempotency indexes | `uq_ingestion_idempotency` (key-only, legacy), `uq_feature_run_idempotency` (field_id+key), `uq_rotation_run_idempotency` (field_id+key), `uq_water_plan_idempotency` (field_id+key) |
| Tenant isolation | **Application-layer only** (membership guards); no RLS, no grants, no triggers |

## 7. Browser smoke test (agent-browser, 2026-11-01)

Environment: Next.js dev server :3000; API :3030; demo workspace (SYNTHETIC fixtures).

| Check | Result |
|---|---|
| Application opens (`/`) | ✅ Title "FieldShift — Agricultural decision support" |
| Auth gate | ✅ Sign in / Create account / **Enter demo workspace** rendered |
| Demo workspace entry | ✅ Seeded SYNTHETIC fixtures, landed in workspace with token |
| Tab set | ✅ **Overview, Farms & Fields, Observations, Features, Rotation, Water, Data Passport** — no Soil, no Management tab (confirms §1) |
| Overview | ✅ Welcome, stat cards, quick actions |
| Farms & Fields | ✅ Farm selector, field table ("North Field (synthetic)"), field detail with offline map |
| Observations | ✅ Header renders; ingestion form, charts, imports, coverage table present |
| Features | ✅ Tab renders run-creation form, catalog, values |
| Rotation | ✅ Field picker prompt + Knowledge packs section rendered |
| Water | ✅ Methods catalog headings render: "Effective-rainfall methods (3)", "Soil water-holding sources", "Application-efficiency classes (FAO TM1 Annex I, Table 8)", "Deliberately not implemented (4)" |
| Data Passport | ✅ Header + status card |
| Console errors | ✅ **Zero** (only React DevTools info + HMR connected) |
| Page errors | ✅ **Zero** |
| Desktop layout | ✅ (verified across tab navigation) |
| Mobile 390×844 | ✅ `document.documentElement.scrollWidth ≤ 391` (no horizontal overflow); footer bottom ≤ viewport (`mt-auto` sticky-footer behavior intact) |

Screenshots: `tool-results/m70-desktop-features.png`, `tool-results/m70-mobile-390.png`.

---

## 8. Milestone status as actually present in the repository

| Milestone | Status | Evidence |
|---|---|---|
| M1–M2 Platform foundation (auth, orgs, farms/fields, PostGIS, migrations 0001) | **PRESENT** | `app/domains/identity`, `app/domains/farms_fields`, migration `0001_initial` |
| M3 Alternative environmental data integrations | **PRESENT** | `app/data_platform/` (open_meteo, chirps, soilgrids, farmer_csv, synthetic), migration `0002` |
| M4 Environmental processing & feature engineering | **PRESENT** | `app/features/` (catalog 29 features, engine, calendar), migration `0003` |
| Pre-M6 scientific deepening (hardening) | **PRESENT** | migration `0005_deepening_hardening`, 21 findings fixed per `docs/deepening/`, `tests/unit/test_deepening_regressions.py` |
| M5 Knowledge & crop rotation optimization | **PRESENT** | `app/knowledge/`, `app/rotation/`, migration `0004` |
| M6A Advanced water intelligence | **PRESENT** | `app/water/` (8 modules), migration `0006_water_intelligence`, Water tab, 441-test suite |
| M6B Soil health & nutrient cycling | **NOT IMPLEMENTED** | no code, no migration, no tests, no docs |
| M6C Field management intelligence | **NOT IMPLEMENTED** | no code, no migration, no tests, no docs (spec uploaded but never executed) |
| M7+ | **NOT STARTED** (correct per inspection mandate) | — |

The repo's own status ledger agrees: `docs/implementation/IMPLEMENTATION_STATUS.md` ("Not implemented (next milestones — deliberately)" lists "Rotation optimizer water-scheduling refinements + soil ledger (Milestones 6B–7)").

## 9. Consequences for the M7.0 audit

1. All readiness verdicts (Field State, Scenario, Robust Optimization, Digital Twin) are assessed against **M6A**, i.e. five working domains (identity/tenancy, field & geometry, environmental data, features, knowledge, rotation, water) — **without** soil-health/nutrient-cycling (M6B) and **without** management/operations (M6C) engines.
2. Where the M7.0 inspection mandate asks about "Soil Domain — M6B" and "Management Domain — M6C" (§4.6, §4.7), the honest finding is **NOT_IMPLEMENTED**, with partial proxies noted where M6A/M5 already consume soil-adjacent evidence (SoilGrids predictions, soil pH traits, root-zone water balance) — detailed in `M7_0_CROSS_DOMAIN_MAP.md`.
3. The reported "742 tests / migration 0008" state would have to come from a different (unavailable) repository; this repository is the single source of truth for M7 planning.

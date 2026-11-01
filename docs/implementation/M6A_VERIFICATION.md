# M6A — Verification Report

**Milestone:** M6A Advanced Water Intelligence Engine
**Date:** 2026-10-31
**Result:** ✅ complete — all acceptance criteria verified

| Gate | Result |
|---|---|
| Backend regression suite | ✅ **441/441 passed** (343 baseline + 98 new M6A tests), exit 0 |
| Frontend lint | ✅ clean (`bun run lint`, 0 errors) |
| Database migration tests | ✅ `0006_water_intelligence` upgrade/downgrade exercised; conftest migrates the test DB to head on every run |
| Browser E2E (golden path) | ✅ plan create → results → scenario experiment → history; zero page errors |
| Rotation integration | ✅ CP-SAT allocation uses the net irrigation requirement with named infeasibility conflicts |
| Honesty boundaries | ✅ enforced in UI and API (see below) |

## 1. What was verified in the repository (Phase 0)

- Baseline **343/343** tests re-run from scratch before implementation.
- All 15 `docs/deepening/` documents reviewed; deepening constraints extracted
  (see `M6A_READINESS_MATRIX.md` §5 and `M6A_DESIGN.md` §10).
- Seed-pack Kc records cross-verified against the FAO-56 chapter 6/8 primary
  sources **fetched during the phase** (not from memory): three root-depth
  transcription errors found (barley, dry bean, cotton) and corrected in pack
  `kp-seed-2026.11.1`; Table 22 depletion fractions (p) added for all 11 crops
  (faba bean keeps its deliberate Kc gap).
- The M5 semantic fixes verified in code: F-05 anchor vocabulary/complete sets,
  F-07 partial-ET0 refusal, F-18 NULLS NOT DISTINCT.

## 2. Independent golden numerical benchmarks (all in `tests/unit/test_water_core.py`)

| Benchmark | Expected | Source |
|---|---|---|
| FAO-33 effective rainfall: P=35/90/116/5/260/75 mm | Pe = 11 / 47 / 67.8 / 0 / 183 / 35 | FAO I&D Paper 33 §4.2 worked examples (primary source fetched; 67.8 printed as 68) |
| FAO-33 irrigation need chain: ETc 69/123/180/234/180, P 20/38/40/80/16 | IN = 67 / 110.2 / 166 / 195 / 180 | FAO I&D 33 §4.3 worked example |
| Continuity of Pe at the 75 mm threshold | both branches = 35 | FAO I&D 33 |
| Unit identities | 1 mm·ha = 10 m³; 1 mm·m² = 1 L | data dictionary + solver identity |
| FAO-56 Example 36 TAW ratios | 90 / 170 / 120 mm per metre | FAO-56 ch. 8 |
| p adjustment `p + 0.04·(5−ETc)` | 0.55→0.59 (ETc 4), →0.43 (ETc 8), →0.55 (ETc 5) | FAO-56 Table 22 footnote 2 |
| Saxton-Rawls PTF (sand 0.29, clay 0.32, OM 3.51) | θFC 0.3536, θWP 0.2054 | verified equation transcription, hand-checked twice |
| PTF validity domain | sand > 0.80 / clay > 0.60 / OM > 8% refused | Saxton & Rawls 2006 |
| M5 separation anchor preserved | ETc for the standard fixture unchanged — **200 randomized equivalence trials old-vs-new estimator, max diff 0.0** | refactor safety |
| Deficit windows / Dr recurrence | hand-computed trajectories (cap at TAW, floor 0, refill by rain) | FAO-56 ch. 8 recurrence |

## 3. Property tests

- Pe monotone in P, never negative, unknown method rejected, `none` → not
  evaluated.
- NIR ≤ ETc always (rainfall credit ≥ 0); wet season → NIR 0.
- Dr recurrence capped/floored; missing ETc raises (missing ≠ zero).
- Ks = 1 until RAW then linear to 0 at TAW.
- Plan checksum reproducible for identical inputs, changes with inputs.
- Readiness matrix: faba_bean stays `missing`/`etc_computable=false`;
  regional applicability `not_locally_validated` everywhere.
- Tenant isolation on every water endpoint (403 cross-tenant).

## 4. Rotation integration (Phase 6) — verified live

- Candidate payloads now carry `net_irrigation_requirement_mm` +
  `water_demand_basis` (verified via `POST /crop-candidates`).
- With allocation 45,000 m³ on the demo field: run **infeasible** with named
  `water_allocation` conflicts whose detail states the
  "demand basis: net irrigation requirement" (honest conflict identification).
- With allocation 90,000,000 m³: run **optimal**.
- Without precipitation evidence the constraint falls back to the ETc
  screening with the conservative-upper-bound note (golden M5 behavior
  preserved — `test_water_allocation_respected` still passes bit-exactly).

## 5. Browser E2E (agent-browser, desktop 1280px + mobile 390px)

- **No-evidence path:** plan on a field without a feature run renders every
  water quantity as "—" with the warning list; allocation badge
  "not evaluated"; nothing zero-filled.
- **Synthetic-evidence path** (demo field, synthetic run): SYNTHETIC banner;
  ET0 819.0 mm; ETc 664.0 mm; Pe 0.0 mm (genuinely floored); NIR 664.0 mm ≈
  2,809,252 m³; stage demand 35.4 / 192.2 / 323.4 / 113.0 mm with Kc means
  0.30 / 0.74 / 1.20 / 0.93 (FAO-56 maize curve visible); allocation deficit
  2,764,252 m³ = 2,809,252 − 45,000 **exact**.
- **Root-zone scenario** (expert mode, farmer θFC 0.32 / θWP 0.15 / Zr 1.35 /
  p 0.55): TAW = 229.5 mm (exact), p adjusted to 0.5575 (exact per
  Table-22 footnote), RAW = 127.9462 mm, ΔSW = 229.5 mm, NIR = 434.5 mm
  (exact, "full water balance" basis), stress window 2026-06-15 → 2026-09-15
  (93 days, Dr hits TAW), allocation shortfall 1,793,329 m³ (exact).
- Water ladder renders all seven quantities with "(not evaluated)" for gross
  requirement (no efficiency) and actual applied (no records).
- Methodology accordion lists the verified methods and the four deliberately
  not-implemented items (local ET0, USDA-SCS, dual-Kc, scheduling).
- Plan history: immutable snapshots with checksums; delete works.
- Mobile 390px: `scrollWidth == clientWidth` (grid `min-w-0` fix applied and
  verified); footer pushed naturally on long pages.
- Zero console errors / page errors during the whole session.

## 6. Environment note

The sandbox was recycled between milestones: the API virtualenv, the
PostgreSQL 16.10 + PostGIS cluster (`db/pgenv`, port 5433) and both dev
servers were rebuilt during Phase 0 and re-verified (health endpoints, 343
baseline tests) before any M6A code was written.

## 7. Known limitations carried forward (documented, not hidden)

- Screening-level seasonal planning, not irrigation scheduling (W-7).
- No local ET0 computation (W-6); provider ET0 only.
- No dual-Kc (no Kcb rows), no USDA-SCS Pe (W-5, unverified coefficients).
- Soil PTF is texture-based with the single-layer (0–5 cm) disclosure; no
  density correction; no gravimetric ingestion path yet.
- Actual irrigation applied is "unknown" until farmer irrigation records
  ingestion exists (W-8).
- Capillary rise / groundwater not modelled (disclosed in every plan).

# M6B — Verification Report

**Milestone:** M6B — Soil Health, Soil Profile Intelligence & Nutrient Cycling Engine
**Date:** 2026-10-31
**Result:** ✅ complete — all acceptance criteria verified

| Gate | Result |
|---|---|
| Backend regression suite | ✅ **566/566 passed** (441 M6A baseline + 125 new M6B tests), fresh run 3m12s, exit 0 |
| Frontend lint | ✅ clean (`bun run lint`, 0 errors) |
| Database migration | ✅ `0007_soil_intelligence` applied to the dev DB (13 new tables); migration tests exercise upgrade/downgrade inside the suite |
| Browser E2E (golden path) | ✅ field select → assessment → profile → SOC run → NPK budget → lab import → readiness; zero console errors |
| M6A/M5 regression | ✅ water, rotation, knowledge, passport suites unchanged and green |
| Honesty boundaries | ✅ enforced in engine, API and UI (details below) |

## 1. Phase 0 — what was inspected (not trusted)

- Baseline **441/441** re-run from scratch before any M6B code.
- `M6A` implementation, water DB models, migration 0006 and the rotation
  consumers re-inspected; `docs/deepening/` backlog items S-1…S-5 mapped to
  M6B scope. Deliverable: `docs/m6b/M6B_GAP_ANALYSIS.md`.
- SoilGrids multi-depth conventions **verified against the live WCS**
  (`soc_5-15cm_mean`, `soc_100-200cm_Q0.05`, `silt_0-5cm_mean`,
  `cfvo_0-5cm_mean` all answered DescribeCoverage); the docs.isric.org FAQ
  and api.isric.org were unreachable (502/TLS) and were not relied upon.
- USDA texture polygons transcribed from the **soiltexture R package
  USDA.TT table** (CRAN tarball fetched and read), not from memory.

## 2. Independent golden numerical benchmarks (all in `tests/unit/test_soil_core.py`)

| Benchmark | Expected | Independent basis |
|---|---|---|
| SOC layer stock | 20×1.3×0.9×20×0.1 = **46.8 Mg C/ha**; fine-earth 15×1.25×10×0.1 = **18.75** | dimensional analysis (g/kg · g/cm³ · cm × 0.1), derived in the test comments |
| Double correction | fine-earth BD + vCF → **hard refusal** | single-correction rule (ADR-0024) |
| Missing OC/BD/basis | stock **refused with reason**, never zero/assumed | honesty contract |
| Profile aggregation | contiguous 24+26 = **50.0**; gap case **63.0** with non-contiguity disclosed; overlap → **refused** | hand arithmetic |
| Fixed-depth vs ESM | FD Δ **−4.0** with BD-change caveat; ESM same inputs Δ **0.0**; two-layer ESM Δ **−2.0** (51.0 vs 49.0) | cumulative-mass hand computation |
| USDA texture | corners; 70/20/10 → **sandy loam** (Wikipedia worked example); 33/34/33 → **clay loam**; boundary determinism | soiltexture USDA.TT polygons + published examples |
| Porosity | 1 − 1.33/2.65 labelled **estimated**; measured PD not labelled | formula with disclosed assumption |
| AWC | (0.32−0.15)×30×10 = **51.0 mm**; gaps never interpolated | FAO-56 identity |
| Oxide conversions | P₂O₅→P **×0.43642712**, K₂O→K **×0.83015130** | stoichiometry from IUPAC 2021 atomic weights, computed independently in the test (disclosure string corrected to match after the benchmark report flagged it) |
| Nutrient budget | 46 kg N on 2 ha → **23.0 kg/ha**; oxide DAP grade converted at budget time; manure without availability fraction **excluded + listed**; 5 loss flows always "NOT assumed zero"; NUE labelled partial-factor | hand arithmetic + contract |
| Comparability gate | water-pH vs CaCl₂-pH trend **blocked**; depth-mismatched trend **blocked** | ADR-0023/0027 |

## 3. Property/integration coverage highlights

- Profile read model reports **gaps** (10 cm uncovered) and refuses merges;
  field-attached measurements at equal intervals group into one layer.
- pH **without method metadata is rejected over HTTP** (ADR-0023 enforced).
- `soilgrids_profile` source requires `global_soil_prediction` evidence
  (mapped ≠ measured enforced structurally).
- SOC run over HTTP returns the **46.8 golden value** with sha256 checksum;
  idempotency key returns the same run.
- Nutrient budget over HTTP: urea 46 + DAP 18-46-0 → N inputs **55.0**,
  P via oxide conversion ≈ **10.0378**, removal from concentration **14.0**,
  overall **partial** with missing-flow list.
- Lab import: `<3.0` mg/kg P stored as **NULL + qualifier '<'** (never zero);
  `%` → g/kg declared conversion; duplicate natural keys rejected;
  idempotent by file sha256.
- Tenant isolation **403** on profile, SOC-run detail and all field-scoped
  routes; GPS range and event-type validation return structured 422s.
- Suite totals: 566 passed (M1–M2: 157 · M3: +27 · M4: +59 · M5: +71 ·
  deepening: +29 · M6A: +98 · M6B: +125).

## 4. Browser E2E (agent-browser, desktop 1280 px + mobile 390 px)

- Soil tab renders: engine version line, multi-domain assessment cards
  (Physical/Chemical/Biological/Hydrological/Organic-matter) with
  per-indicator evidence badges, SYNTHETIC flags, and trend-comparability
  badges ("trend not comparable" where the gate blocks).
- Profile explorer: 0–30 and 30–60 cm layers, **USDA clay loam** badges,
  **AWC 51.0 mm** per layer, per-measurement synthetic badges.
- SOC stock run through the UI: **49.9 Mg C/ha** for the demo layer
  (12.5 g/kg × 1.33 g/cm³ × 30 cm × 0.1 = 49.875 — exact to the displayed
  rounding), checksummed snapshot, "(not evaluated)" paths preserved when
  inputs are blank.
- N/P/K budget through the UI: N **−57.0** (in 69.0 · out 126.0), P −27.0,
  K −81.0; **missing-flows panel** listing all five loss flows as "NOT
  assumed zero"; interpretation disclaims stock change.
- Laboratory import through the UI: **4 imported · 0 rejected · 1 warning**
  ("value below detection limit — recorded with qualifier, not zero");
  DB verified NULL+qualifier storage.
- Data-collection priorities: decision-linked qualitative ranking rendered.
- Mobile 390 px: `scrollWidth == clientWidth` (no horizontal overflow);
  desktop all-tabs pass with **zero console errors / page errors**.
- Fixed during verification: toast `describeError` object rendering
  (React crash), FieldPicker prop wiring, list-payload `result` inclusion,
  mapping-spec fallback to the built-in template, import savepoints
  (per-row rollback) and layer de-duplication.

## 5. Acceptance criteria mapping (spec §22)

1. Samples & depth layers stored correctly → migration 0007 + E2E ✅
2. Lab methods/analytical metadata traceable → method registry + mandatory metadata ✅
3. Measured distinct from mapped → source_kind/evidence_class CHECKs ✅
4. SOC stock passes independent benchmarks → §2 ✅
5. FD vs ESM distinguished → method-aware implementations + refusals ✅
6. Budgets distinguish complete/partial → partial-by-default with missing-flow lists ✅
7. N/P/K correct units/bases → versioned stoichiometric conversions + basis columns ✅
8. Transparent multi-dimensional assessment → 5-domain profile, no score ✅
9. Missing evidence never zero → refusal-reason pattern end-to-end ✅
10. Uncertainty & provenance propagate → per-row uncertainty, evidence classes, checksums ✅
11. History comparisons reject incompatible methods/depths → comparability gate ✅
12. APIs & frontend work end to end → browser E2E ✅
13. M1–M6A remain operational → 441 pre-existing tests green ✅
14. Full regression + browser verification pass → §gate table ✅
15. Limitations documented → `M6B_RESEARCH_BACKLOG.md` (20+ items) ✅

## 6. Known limitations carried forward (documented, not hidden)

- Nutrient-removal concentrations come from farmer/lab records only — the
  reference library is deliberately EMPTY pending verified sources.
- SOC uncertainty is recorded per layer but not yet propagated (documented).
- No EC cross-ratio conversion (needs texture-specific calibration).
- SoilGrids field-level prediction interval remains unavailable (S-1).
- No composite soil-health index (requires validated methodology).
- PDF/OCR lab reports deliberately not accepted.
- BNF values are order-of-magnitude pack estimates (low confidence).

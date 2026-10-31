# DEEPENING_EXIT_REPORT.md — Pre-M6 Scientific & Technical Deepening Program

Date: 2026-10-31 · Directive: SCIENTIFIC & TECHNICAL DEEPENING PROGRAM (M1–M5)
Baseline reproduced before changes: **314 passed**. Final state: **343 passed**
(+27 deepening regression tests), frontend lint clean, browser re-verified.

## 1. What this program did

1. **Stage 1** — full repository inspection (backend 12k LOC, frontend, 31
   tables, 5 migrations, 50 routes, all tests) + baseline reproduction.
2. **Stage 2–3** — audit producing 21 classified findings (1 Critical,
   7 High, 11 Medium, 2 Low): `SCIENTIFIC_AUDIT.md`.
3. **Stage 4** — all Critical and High findings corrected in code with
   additive migration 0005; per-finding regression tests
   (`REMEDIATION_REPORT.md`).
4. **Stage 5** — knowledge enrichment REVIEWED and deliberately limited to the
   existing sourced evidence; candidate enrichments that could not be
   transcribed from verifiable sources (salinity ECe table, GDD base
   temperatures, cultivar records) were **not** added from memory and are
   assigned in `KNOWLEDGE_GAPS_AND_RESEARCH_BACKLOG.md` — scientific accuracy
   over apparent completeness.
5. **Stage 6** — benchmark suite: golden numerical tests, property tests,
   metamorphic tests, cross-component provenance validation
   (`SCIENTIFIC_BENCHMARKS.md`).
6. **Stage 7** — browser verification of corrected semantics (§7 below).
7. **Stage 8** — this report set (15 documents in `docs/deepening/`).

## 2. Exit criteria scorecard (directive §16)

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | All Critical findings resolved | ✅ | F-01 fixed + browser-verified (1 honest badge on the synthetic card, none on real products) |
| 2 | High-priority issues resolved or explicitly blocked | ✅ | F-02..F-08 all fixed (none blocked on external evidence) |
| 3 | All 26 features documented + tested semantics | ✅ | `FEATURE_SCIENTIFIC_SPECIFICATIONS.md` generated from the versioned catalog; engine tests (M4 + F-02/F-11) |
| 4 | All crop traits traceable or documented-missing | ✅ | provenance tests; deliberate gaps documented (faba bean Kc; backlog K-series) |
| 5 | Every knowledge rule has applicability/validation metadata | ✅ | rules carry regions, mechanism, severity, source, validation status; zero-confirmed honesty invariant tested |
| 6 | Constraints distinguish unknown/unevaluated/not-configured/satisfied/violated | ✅ | constraint statuses + candidate dimensions + rule gating (§2 of ROTATION spec); absent rule never reads as satisfied (count surfaced) |
| 7 | Pareto calculations have independent dominance tests | ✅ | `TestParetoProperties` (front membership, duplicates, non-comparable pairs) independent of the solver |
| 8 | Reproducibility demonstrated | ✅ | solver determinism tests + API checksum equality + pack checksums + feature checksums |
| 9 | Scientific benchmark cases pass | ✅ | `SCIENTIFIC_BENCHMARKS.md` §1 (golden cases incl. area-weighting, unit conversions, water separation) |
| 10 | Provenance survives all processing/optimization paths | ✅ | benchmark §4 chain table (observation → feature → rotation → strategy checksum) |
| 11 | Frontend status/confidence language scientifically honest | ✅ | F-17 corrections verified in browser; 8-dimension separation (UNCERTAINTY policy) |
| 12 | Full regression suite passes | ✅ | 343/343 |
| 13 | Browser verification completed | ✅ | §7 below |
| 14 | Remaining limitations documented + assigned | ✅ | `KNOWLEDGE_GAPS_AND_RESEARCH_BACKLOG.md` (K/C/S/M/B/G series) |

**External agronomic validation is NOT claimed**: every seed value remains
`validation_status="reference"`; zero `confirmed_regional` rules ship.

## 3. Documents produced (deliverable §13)

`AS_BUILT_ARCHITECTURE.md` · `SCIENTIFIC_AUDIT.md` ·
`ENVIRONMENTAL_SOURCE_AUDIT.md` · `FEATURE_SCIENTIFIC_SPECIFICATIONS.md` ·
`AGRONOMIC_KNOWLEDGE_AUDIT.md` · `SOIL_SCIENCE_METHODOLOGY.md` ·
`CLIMATE_METHODOLOGY.md` · `ROTATION_MATHEMATICAL_SPECIFICATION.md` ·
`OPTIMIZATION_VALIDATION.md` · `UNCERTAINTY_AND_EVIDENCE_POLICY.md` ·
`GLOBAL_SPATIAL_AND_CALENDAR_AUDIT.md` · `SCIENTIFIC_BENCHMARKS.md` ·
`KNOWLEDGE_GAPS_AND_RESEARCH_BACKLOG.md` · `REMEDIATION_REPORT.md` · this file.
Standing docs updated: `TEST_MATRIX.md`, `IMPLEMENTATION_STATUS.md`,
`DECISIONS_AND_ASSUMPTIONS.md` (ADRs 0019–0021), `KNOWN_LIMITATIONS.md`, `README.md`.

## 4. Explicitly NOT done (per directive §17)

No M6 work: no water-intelligence expansion, no soil-health engine expansion,
no climate simulation expansion, no new product modules. SPI/SPEI were
evaluated and rejected for this stage on statistical grounds (C-2), not
deferred casually.

## 5. Version changes introduced (explicit, additive)

| Artifact | Change |
|---|---|
| Feature catalog | `featurespec-2026.11.0-m4` → `featurespec-2026.11.1-d1` (baseline classification + wording) |
| CHIRPS extractor | `chirps-extractor-v1` → `-v2` (area weighting) |
| SoilGrids normalizer | `-v2` → `-v3` (honest uncertainty label) |
| Database | migration `0005_deepening_hardening` (indexes, composite idempotency, NULLS NOT DISTINCT) |
| Rotation engine | unchanged version (`rotation-engine-1.0.0`) — semantics of existing outputs did not change; the fixes strictly narrow false claims (no historical result is rewritten) |

## 6. Risk acknowledged

The frontend "Rotation" run payloads produced before this program carry the
old `uncertainty`/baseline fields where applicable; engine-semantic outputs
(criteria, statuses) changed only in the honest direction (fewer false
claims). No stored result was deleted or rewritten.

## 7. Browser verification (agent-browser, 2026-10-31)

- Auth gate → demo workspace → all tabs render; zero page errors; zero
  console errors (only the pre-existing benign Radix Select notice).
- **Data Passport**: attribution & licensing section shows EXACTLY ONE
  "SYNTHETIC" badge — on the synthetic fixture product card only (previously
  every product card was falsely badged). Variables keep per-row SYNTHETIC
  badges; evidence classes shown.
- **Rotation**: planning card states "month-of-year baseline — a short-record
  historical proxy (not a WMO climatological normal, never a forecast)";
  strategy cards render "evidence-backed criteria 14% / 86%" (old bare
  "evidence NN%" gone); Pareto badges, honest baseline, constraints block
  intact; optimizer run succeeded end-to-end from the UI.
- **Features**: catalog shows `featurespec-2026.11.1-d1`; run detail renders
  `— obs` where provenance counts are absent (the "0 obs" defect is gone)
  and real counts where they exist; 38 "not evaluated" mentions with reasons.
- Mobile 390×844: `scrollWidth == clientWidth` (no horizontal overflow);
  footer present/flush; desktop 1366×900 footer flush.
- Screenshot: `tool-results/deepening-e2e.png`.

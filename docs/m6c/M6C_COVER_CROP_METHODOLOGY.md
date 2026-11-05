# M6C — Cover-Crop Planning Methodology (as-built, Increment 4)

**Status:** implemented and tested (`test_cover_crop_engine.py` — 18 unit tests
with a hand-computed water golden; `test_cover_crop_api.py` — 11 integration
tests including the cross-module timeline link).

## 1. Scope and stance

The engine is a **transparent candidate evaluation** over the ACTIVE knowledge
packs — not a species ranking. It only evaluates species the knowledge base
explicitly marks `is_cover_crop_capable`; with the bundled seed pack that is
exactly `faba_bean`, whose evaluation honestly reports large knowledge gaps.
"No evaluable candidates" is an honest outcome, surfaced as a global gap —
never padded with fabricated candidates.

## 2. Reused engines (no parallel models)

| Concern | Reused from | Notes |
|---|---|---|
| Knowledge loading | `app.knowledge.service.load_knowledge` | active packs only |
| Climate evidence | rotation service feature-run bridge (`_pick_evidence_run`, `_season_climate`) | month-of-year climatology labelled "historical proxy, NOT a forecast"; synthetic flag propagated into a run warning |
| Cover water demand | `app.rotation.candidates.estimate_water_requirement_mm` / `estimate_net_irrigation_mm` (wrapping the versioned `app.water.curve` + FAO-33) | the M6A engine computes it; faba_bean's deliberate Kc gap keeps the dimension unevaluated |
| Following-crop compatibility | `rotation_rules` (`cover_crop_suitability`, `host_pathogen`, `host_pest`) | crop- or family-scoped, region-gated; reference rules are advisory conditions, only `confirmed_regional` rules are hard (seed pack ships zero) |
| Soil context | rotation `_soil_evidence` | pH vs sourced EcoCrop optimum with evidence class |

## 3. Candidate dimensions and statuses

Every candidate reports a per-dimension status
(`evaluated | conditional | not_evaluated`), conditions with codes, reasons
with source refs, functions with citations, and `missing_inputs`:

| Dimension | Basis | Without evidence |
|---|---|---|
| `sowing_window` | crop calendar windows (hemisphere/region), largest overlap with the available window | candidate = **not_evaluated** (no recommendation without a regional calendar — spec §4.4) |
| `growth_duration` | `duration_days_total` vs days available | not_evaluated; shorter window ⇒ condition `window_shorter_than_duration` explicitly stating early-termination suitability is NOT evaluated |
| `climate_temperature` | EcoCrop range vs window mean temperature | not_evaluated |
| `soil_ph` | EcoCrop pH optimum vs measured/mapped soil pH (evidence classed) | not_evaluated |
| `water_trade_off` | M6A ETc screening estimate + NIR (ETc − Pe) | not_evaluated with the concrete why (no Kc / no ET0 / no precip) |
| `termination` | `cover_termination_methods` trait | not_evaluated — "termination window and method must be planned with local agronomist input (never a default lead time)" |
| `following_crop_compatibility` | rotation rules | not_evaluated without next-crop context |
| `establishment_requirements` | — | not_evaluated (points at the cover_cropping practice for qualitative requirements) |

**Classification rule (spec §4.2):** `eligible` requires sowing_window +
water_trade_off + termination ALL evaluated (`CRITICAL_DIMENSIONS`); any
critical gap ⇒ `conditional` with the unmet conditions named; farmer
exclusions ⇒ `excluded`; calendar absent/no overlap ⇒ `not_evaluated`.
Property-tested: `status == eligible ⇒ all critical dimensions evaluated`.

## 4. Honesty behaviours (each pinned by a test)

- **Missing evidence ≠ eligibility** — the bundled-KB candidate is
  `conditional` (water: no Kc; termination: no knowledge).
- **Functions never inferred from family** — `is_legume=True` without a
  sourced `n_fixation_capacity_kg_ha` trait claims nothing; with the trait
  (faba_bean: 60–200 kg N/ha range, Herridge et al. 2008, confidence low) the
  function is listed with its range and conditions.
- **No universal termination lead time** — the engine emits NO termination
  date whatsoever (`termination_window` appears nowhere in output); sourced
  methods are surfaced as options, timing stays a decision.
- **Water is a trade-off, not a benefit** — an evaluated demand produces the
  explicit `cover_consumes_water` condition; no automatic benefit is claimed.
- **Reference windows flagged** — `reference_synthesized` calendar evidence
  produces a warning-severity reason.
- **Synthetic climate** — propagates a "SYNTHETIC test fixture" run warning.

## 5. Golden water case (hand-computed, independent)

Uniform curve (Kc ≡ 1.0, stages 30/30/30/30 = 120 days) with 4 mm/day ET0
(monthly totals = 4 × calendar days) over 2026-09-01..2026-12-29 →
**ETc = 480.0 mm** exactly. (The estimator treats `monthly_et0` as calendar-
month totals scaled by the in-season day fraction — December contributes
124 × 29/31.) The arithmetic identity lives in the M6A engine; this test
pins the cover engine's *integration* with it.

## 6. API and plan snapshots

- `POST /fields/{id}/cover-crop-plans` — evaluates and snapshots (immutable;
  `engine_version`/`methods_version` = management-engine/methods-1.0.0;
  sha256 checksum over inputs+versions+results; same parameters → identical
  checksum (reproducibility-tested); `idempotency_key` returns the same row).
- `GET /fields/{id}/cover-crop-plans` · `GET /cover-crop-plans/{plan_id}`
  (cross-tenant 403, tested).
- `POST /fields/{id}/cover-crop-plan-items` — the farmer's adopted decision
  (durable; references the originating plan run for provenance; mixture
  fractions must sum ≤ 1 — the remainder is declared unknown, never
  renormalized).
- Plan items feed the soil-cover timeline as `living_cover_crop` intervals
  (cross-module test: Oct 1 → Jan 15 intended window = 107 timeline days).

## 7. Water-allocation note

Cover-crop water demand is reported per candidate; it does NOT enter the
rotation CP-SAT water allocation (that constraint covers the planned main
crops of M5/M6A). If a farmer wants covers constrained against the same
allocation, that is a plan-level decision surfaced through the management
plan (Increment 8) — never silently merged into the optimizer coefficients.

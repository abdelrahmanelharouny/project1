# UNCERTAINTY_AND_EVIDENCE_POLICY.md — Phase I (trust, explainability, user-facing semantics)

## 1. The eight separable dimensions (never compressed into one score)

| # | Dimension | Where it lives | Example value |
|---|---|---|---|
| 1 | Data completeness | `coverage_ratio`, `n_input/n_missing`, passport counts | "97% coverage, 1 missing day" |
| 2 | Data quality | `quality_status` (valid/partial/insufficient_coverage/missing/not_evaluated), quality flags | "partial — 1 gap flagged" |
| 3 | Evidence coverage | rotation `evidence_coverage` = fraction of criteria evaluable from evidence | "evidence-backed criteria 86%" (label corrected in F-17) |
| 4 | Measurement uncertainty | `uncertainty_value` + `uncertainty_type` (SEM; SoilGrids honest half-width label) | "±4.0 g/kg (mean of per-pixel Q05–Q95 half-width)" |
| 5 | Model uncertainty | evidence class + method notes (reanalysis vs measurement; SoilGrids prediction; screening ETc assumptions) | "reanalysis_model_estimate, grid_cell 11132 m" |
| 6 | Agronomic validation status | `validation_status` (reference / locally_validated / confirmed_regional) on every trait, window, Kc row and rule | "reference — pending regional validation" |
| 7 | Solver status | run/strategy `solver_status` per ROTATION_MATHEMATICAL_SPECIFICATION §5 | "optimal" / "infeasible + conflicts" / "solver failure" |
| 8 | Recommendation feasibility | constraint checks + recommendation block | "violates a hard constraint — must not be adopted" |

Master rule enforced: **no composite confidence score exists anywhere** (the
Data Passport states this in its notes; the rotation UI shows the eight
dimensions separately).

## 2. What a user can always see (verified surfaces)

- Which data was used, from which product/version, with license + attribution
  (passport attribution cards, now correctly flagged real vs synthetic — F-01).
- Native resolution (spatial support type + resolution in metres per entry).
- Which calculations were applied (feature catalog with formula references;
  criterion `derivation` strings; water-estimate assumptions per candidate).
- Which evidence was unavailable (missing-variable lists, unevaluated
  dimensions with reasons, `not_evaluated` run map, skipped weights with
  reasons).
- Why a candidate was excluded (cited reasons with severity).
- Which constraints remain unevaluated (constraint statuses incl.
  `not_applicable` with "never invented" text; zero-confirmed-rules note).
- Why one strategy differs from another (expected benefits / risks-trade-offs
  vs every other strategy, per criterion).
- What requires local expert confirmation (`local_expert_validation_required`
  block + reference-validation badges in the knowledge browser).

## 3. Simple Mode vs Expert Mode

Simple Mode (default tabs) must not hide material limitations — enforced by:
synthetic banners on every affected surface (run cards, charts after F-17,
candidate reasons, strategy evidence blocks); "(not evaluated)" cells instead
of blanks or zeros; blocked analyses with explicit missing-input lists.
Expert Mode (catalog browser, constraints accordion, provenance strings,
checksums) exposes technical detail — post-deepening it also carries the
baseline classification (F-11), the honest uncertainty-type label (F-08) and
criterion-level source citations (F-10).

## 4. Language rules (audit-derived)

1. A short-record baseline is "a short-record historical proxy", never
   "climatology" (F-11).
2. "evidence NN%" is rendered "evidence-backed criteria NN%" — a coverage
   metric, not confidence (F-17).
3. Water figures keep the "≈" and their assumptions block; the screening
   estimate is labelled as superseded by the M7 daily water balance.
4. Solver "optimal" appears only when every profile proved optimality (F-4).
5. Missing values render "—" / "(not evaluated)" / "unknown" — never 0
   (F-17; "0 obs" defect removed).

# M6B — Research Backlog (Honest Open Items)

**Status:** living document at M6B completion
**Principle:** every item below is a boundary the implementation deliberately
respects — none is hidden behind a default, a guess or a fabricated reference.
IDs (W-*, S-*) continue the M6A/deepening backlog numbering.

---

## 1. Verified-source gaps (highest priority)

| Item | State today | What would unlock it |
|---|---|---|
| **Nutrient-removal reference library** | Intentionally EMPTY — no per-crop N/P/K removal coefficients ship; every budget run result carries the note that concentrations come from farmer/lab records only; demo data is SYNTHETIC-labelled | A verified, cited per-crop removal table (harvested product + residue, dry-matter and as-harvested basis) curated from primary literature; until then the engine refuses yield-only removal estimates |
| **USDA-SCS effective rainfall** (W-5, inherited) | Not implemented — coefficients could not be verified verbatim from the primary source in M6A | Verified coefficient table; FAO-33 `fao_aglw_1986` remains the only shipped Pe method |
| **BNF per-crop values** | Pack trait `n_fixation_capacity_kg_ha` (Herridge, Peoples & Boddey 2008) covers three legumes at confidence **low**, declared order-of-magnitude; BNF enters budgets only as a recorded, labelled estimate | Local/variety-verified fixation ranges per crop and management context; until then the estimate label and farmer override stay mandatory |

## 2. Method-conversion gaps (refusals by design)

| Item | State today | What would unlock it |
|---|---|---|
| **EC cross-ratio conversion** (W-9) | ECe vs EC1:1 vs EC1:2.5 vs EC1:5 are distinct method-qualified measurements; cross-ratio comparison is refused (`check_ec_method_compatibility`); salinity classes apply to ECe only (FAO Soils Bulletin 62 (Abrol, Yadav & Massoud 1988), Table 4, indicative) | A texture-/dilution-specific calibration model verified from primary sources; conversions are known to be texture- and dilution-dependent, so a generic factor would be wrong |
| **pH local calibration** (S-3) | Media (water/CaCl₂/KCl/saturation paste) never merged or converted; EcoCrop optima comparisons are labelled screening, confidence low; a CaCl₂ measurement carries a "not directly comparable to water-pH optima" note | Region-verified medium-adjustment relationships (or medium-specific optima) — no endorsed global conversion exists |
| **pH screening thresholds generally** | No universal pH/suitability thresholds adopted anywhere in M6B | Validated, region-anchored interpretation ranges reviewed by an agronomist (`local_applicability` stays "reference-grade" until then) |

## 3. Spatial/mapped-data gaps

| Item | State today | What would unlock it |
|---|---|---|
| **SoilGrids field-level prediction interval** (S-1, F-8) | The shipped uncertainty figure is the mean of per-pixel Q05–Q95 half-widths, explicitly NOT a field-level 90% PI; SOC runs fed by mapped layers warn "prediction, not a field measurement" | A spatial error-covariance / within-field variability model before pixel quantiles may be aggregated into a field PI; until then such aggregation is reported as unavailable |
| **SoilGrids multi-depth ingestion depth** | The soil schema stores any depth (`soilgrids_profile` rows land in `soil_measurements`); provider wiring and QC for the six standard intervals beyond 0–5 cm remains incremental work | Provider extension with per-depth natural keys (the schema collision ADR-0022 removed is gone) |

## 4. Water-engine interfaces (inherited M6A backlog)

| Item | State today | What would unlock it |
|---|---|---|
| **Local ET0 computation** (W-6) | Provider ET0 only (ERA5, FAO-56 reference surface); no radiation/humidity-based local ET0 | Verified local method (e.g. Hargreaves) + quality-gated radiation/humidity evidence |
| **Irrigation scheduling** (W-7) | M6B/M6A deliver screening-level seasonal planning, not event-level scheduling | Daily water-balance scheduling layer (separate decision product) |
| **Dual-Kc** | Single-Kc only (no Kcb rows in the pack) | Verified dual crop-coefficient tables + ground-cover evidence |
| **Saxton–Rawls density correction (DF)** (S-5) | The PTF runs without a bulk-density correction; no gravimetric ingestion path | Verified density-correction term and bulk-density ingestion into the water soil-input ladder |
| **PTF single-layer extrapolation** (S-6) | Texture assumed representative of the root zone from the 0–5 cm layer (disclosed) | Multi-depth measured texture (M6B profile data feeding the water ladder) |

## 5. Engine capabilities deliberately not shipped

| Item | State today | What would unlock it |
|---|---|---|
| **Composite soil-health index** (ADR-0026) | No score computed anywhere; transparent five-domain profile is the decision surface | A validated weighting/scoring methodology with published local validation — until then any score would be an unsupported claim |
| **SOC uncertainty propagation** | `LayerStockInput` carries 1σ OC/BD uncertainty fields; `soc-stock-1.0.0` records them but produces point estimates only (documented in `M6B_UNCERTAINTY_POLICY.md`) | Independent-input propagation arithmetic + a policy for correlated BD/OC errors, benchmarked against hand computations |
| **`complete` nutrient-budget mode** | Classification is `partial` by construction (loss flows never known); `complete` is reserved in code | A full-accounting mode in which the farmer documents every flow including measured losses — realistic only with on-farm measurement records |
| **PDF/OCR laboratory-report import** | Deliberately rejected: unverified OCR is never accepted as a validated laboratory measurement | A verified extraction pipeline with per-field confidence and human confirmation before rows enter the measurement store |
| **Multi-field laboratory templates** | The import endpoint requires a single `default_field_id`; per-sample field binding "arrives with multi-field templates" (API note) | A field-binding column in the mapping contract + per-row tenant checks |
| **Cross-system texture mapping** | WRB/national texture labels pass through uninterpreted (ADR-0023) | Verified cross-system correspondence tables; not attempted in M6B |
| **Gridded SOILGRIDS_SUBCELL handling improvements** | Small fields flag the all-touched-cells warning; no downscaling is attempted | Higher-resolution evidence or a verified upscaling method |

## 6. Explicit non-goals (not backlog — red lines)

- Never simulate biological indicators from missingness or generic traits.
- Never merge method-incompatible measurements to manufacture a longer series.
- Never zero-fill missing flows, gaps or unevaluated seasons.
- Never label a mapped prediction as a measurement, in any UI or API surface.
- Never fabricate page numbers, DOIs or thresholds not present in verified code
  or cited sources — this document included.

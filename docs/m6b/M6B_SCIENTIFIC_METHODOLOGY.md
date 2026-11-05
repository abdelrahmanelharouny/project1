# M6B — Scientific Methodology (Soil Health, Soil Profile Intelligence & Nutrient Cycling)

**Status:** implemented (as-built specification)
**Engine versions:** `soil-engine-1.0.0` · `soil-methods-1.0.0` · `soc-stock-1.0.0` ·
`nutrient-budget-1.0.0` · `usda-texture-1.0.0` · `oxide-conversion-1.0.0` ·
assessment `soil-health-profile-1.0.0`
**Related ADRs:** extends ADR-0014 (knowledge honesty), ADR-0015 (pure decision core),
ADR-0019/0020/0021 (water methodology); introduces ADR-0022…0028
(see `M6B_AS_BUILT_DESIGN.md` §12).
**Code:** `mini-services/fieldshift-api/app/soil/` (pure decision core — no ORM, no HTTP, no I/O).

---

## 1. Position in the architecture

M6B adds a **soil intelligence layer** beside the M6A water layer. It consumes the
field/tenant model, the evidence-class vocabulary, the SoilGrids provider, the CSV
import patterns and the knowledge-pack traits (EcoCrop pH optima, BNF ranges); it
produces depth-explicit soil profiles, method-aware indicators, SOC stocks, N/P/K
budgets, a multi-domain soil-health profile and a qualitative data-readiness ranking.
It does **not** replace the water balance (M6B supplies measured θFC/θWP/BD/vCF
*into* the M6A `TAW = 1000·(θFC−θWP)·Zr` identity), the rotation optimizer, or the
existing 0–5 cm `observations` rows (kept untouched for backward compatibility,
ADR-0022).

## 2. Method layering (mirrors the ADR-0019 water ladder)

| Layer | Content | Honesty rule |
|---|---|---|
| **Measured** | Lab/farmer measurements with full method metadata (medium, extractant, ratio, basis, limits) | Every row keeps its evidence class; method metadata is mandatory for the chemical families (ADR-0023) |
| **Derived** | Versioned calculations over measurements: USDA texture class, porosity, layer AWC, SOC stock | Each derived value records inputs used, method + version, disclosed assumptions, and the refusal reason when inputs are missing |
| **Mapped** | SoilGrids predictions (multi-depth), `source_kind=soilgrids_profile` | Always labelled `global_soil_prediction`; never mixed into a measured series; never silently averaged into a stronger uncertainty claim |
| **Reference** | Knowledge-pack traits (EcoCrop pH optima, Herridge et al. 2008 BNF ranges) | Used ONLY in labelled screening comparisons (confidence low); never a verdict |

Derived indicators **never upgrade evidence class**: a texture class derived from
measured sand/clay is not a new measurement, and mapped inputs stay predictions
through every downstream number (a SoilGrids-fed SOC stock is flagged as a
prediction in the run result).

## 3. Honesty contract (inherits all M6A/deepening rules)

- **Missing ≠ zero.** A missing SOC input makes that layer's stock `not_evaluated`
  with a reason; a missing nutrient flow is listed, never zero-filled.
- **Method-incompatible data are never merged.** pH media (water/CaCl₂/KCl/
  saturation paste) are distinct identities; EC extraction ratios are never
  converted cross-ratio; bulk-density bases (whole-soil vs fine-earth) never mix.
- **Mapped ≠ measured**, structurally enforced (a `soilgrids_profile` row MUST
  carry `evidence_class='global_soil_prediction'` or the write is refused).
- **Refusal over guessing.** Unknown depth units, inconsistent fractions, overlaps,
  double coarse-fragment corrections — all hard errors, never silent fixes.
- **Synthetic data are labelled end-to-end** (`is_synthetic`, `synthetic_fixture`,
  `synthetic_test_data`) and never validate an agronomic claim.
- **Every number traceable** to a cited method or a recorded measurement; unknown
  stays unknown; no agronomic validation is claimed beyond the arithmetic.

## 4. Per-domain methodology summary

| Domain / engine | Method (as built) | Citation recorded in code | Refusals |
|---|---|---|---|
| Texture classification (`usda-texture-1.0.0`) | Point-in-polygon (ray casting, inclusive edges) over the 12 USDA class polygons (26 vertices), transcribed from the `soiltexture` R package `USDA.TT` triangle; sand+clay required, silt may be derived (`silt = 100 − sand − clay`, disclosed per result); fraction sum must be 100 ± 0.5 when all three are supplied | Moeys, J., soiltexture R package (CRAN), USDA.TT triangle | fractions outside [0,100]; negative derived silt; sums outside tolerance; point outside every polygon |
| Porosity | `n = 1 − BD/PD`; PD measured or the disclosed 2.65 g/cm³ mineral-soil assumption (output labelled `assumed_pd`/`estimated`); BD must lie in (0, 2.65) | documented mineral-soil assumption (disclosure string shipped with the result) | BD out of range; PD ≤ BD; unknown BD basis |
| Layer AWC | `AWC = θFC − θWP` (m³/m³); mm = AWC × thickness_cm × 10; matric potentials recorded when supplied (standard −33/−1500 kPa); profile total over disjoint measured intervals only | FAO-56 identities (same as the M6A water engine) | θWP ≥ θFC; overlapping intervals refuse aggregation; gaps listed, never interpolated |
| pH | Measurement identity = value + medium (`water`/`cacl2`/`kcl`/`saturation_paste`/`other`) + soil:solution ratio; range (0, 14]; comparisons against EcoCrop optima are labelled screening | FAO EcoCrop database (confidence low, screening label) | missing medium; value outside (0,14] |
| EC / salinity | ECe (saturated paste) is the standard salinity measure; salinity classes offered for ECe only, labelled indicative; EC at other ratios is a different measurement — cross-ratio comparison refused (`check_ec_method_compatibility` requires identical ratio, temperature note and EC type) | FAO Soils Bulletin 62 (Abrol, Yadav & Massoud 1988), Table 4 | cross-ratio comparison; negative EC |
| SOC stock (`soc-stock-1.0.0`) | Layer-wise FAO/IPCC formula `SOC = OC × BD_fine × (1 − vCF) × d × 0.1` [Mg C/ha]; single coarse-fragment correction (double correction is a hard error); profile total over contiguous complete coverage | FAO GSOC MRV protocol convention (dimensional identity verified analytically, gap analysis §8) | missing OC/BD/basis; whole-soil BD without vCF; fine-earth BD with vCF; overlapping layers |
| SOC comparisons | Fixed-depth over the common depth support (BD-change caveat disclosed); equivalent-soil-mass via cumulative fine-earth mass matching, linear-within-layer interpolation on the baseline stock curve | FAO/IPCC stock-change practice; ESM concept (CCAFS/FAO smallholder soil-carbon measurement guidance) | no common support; incomplete inputs; follow-up mass exceeding baseline coverage |
| Oxide conversions (`oxide-conversion-1.0.0`) | Exact stoichiometry: P = P₂O₅ × 0.43642712 (= 61.9476/141.9426), K = K₂O × 0.83015130 (= 78.1966/94.1956); reverse factors are reciprocals; derivation recorded with the function | IUPAC 2021 standard atomic weights (P 30.9738, K 39.0983, O 15.999 g/mol) | negative masses |
| Nutrient budget (`nutrient-budget-1.0.0`) | Per-season N/P/K accounting over documented flows; availability fraction mandatory for manure/compost/organic amendments; BNF only as a recorded estimate; removals need concentrations; loss flows always listed as unknown | budget structure follows FAOSTAT-style cropland nutrient accounting (flows, partial balances) | missing availability fraction (flow excluded + warning); removal without concentration |
| Assessment (`soil-health-profile-1.0.0`) | Transparent five-domain profile (physical, chemical, biological, hydrological, organic-matter & nutrient cycling); trends only through the comparability gate (method identity + depth); **no composite score** | USDA NRCS soil-health assessment framing (domains; no universal thresholds adopted) | incomparable history reported as not-comparable with the reason |
| VOI (`data_readiness`) | Qualitative, decision-linked ranking of missing measurements; each entry states the decision it unblocks | ADR-0028 policy (no invented costs/benefits/confidences) | present variables are never suggested |

## 5. Versioned surfaces

| Constant | Value | Covers |
|---|---|---|
| `SOIL_ENGINE_VERSION` | `soil-engine-1.0.0` | the calculation package |
| `SOIL_METHODS_VERSION` | `soil-methods-1.0.0` | methodology catalog (classification systems, conversion functions, interpretation policies, citations) |
| `SOC_STOCK_VERSION` | `soc-stock-1.0.0` | SOC stock + FD/ESM comparisons |
| `NUTRIENT_BUDGET_VERSION` | `nutrient-budget-1.0.0` | N/P/K budget engine |
| `TEXTURE_CLASSIFIER_VERSION` | `usda-texture-1.0.0` | USDA triangle implementation |
| `OXIDE_CONVERSION_VERSION` | `oxide-conversion-1.0.0` | P₂O₅/K₂O stoichiometric functions |
| `ASSESSMENT_VERSION` | `soil-health-profile-1.0.0` | multi-domain assessment |

Every run snapshot (`soc_stock_runs`, `nutrient_budget_runs`, `soil_assessment_runs`)
stores `engine_version`, `methods_version`, the full result, warnings, the
not-evaluated list and a `checksum_sha256` over the canonical JSON of the result —
the M6A water-plan reproducibility pattern.

## 6. Deliberately absent (honest boundaries)

- No composite soil-health index (ADR-0026 — no validated weighting methodology).
- No pH scale conversion, no EC cross-ratio conversion, no cross-system texture
  mapping (WRB labels pass through uninterpreted).
- No nutrient-removal reference library (intentionally EMPTY pending verified
  sources — see `M6B_RESEARCH_BACKLOG.md`); concentrations come from farmer/lab
  records only.
- No BNF inference from `is_legume`; no simulation of biological indicators.
- No PDF/OCR laboratory-report extraction (unverified OCR is never accepted as a
  validated measurement).
- No local ET0, no irrigation scheduling (M6A backlog W-6/W-7, inherited).

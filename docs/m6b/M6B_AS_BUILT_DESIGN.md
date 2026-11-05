# M6B — Soil Health, Soil Profile Intelligence & Nutrient Cycling Engine: Design Specification

**Status:** as-built (implementation complete; verification in `M6B_VERIFICATION_REPORT.md`)
**Engine versions (planned):** `soil-engine-1.0.0` · `soil-methods-1.0.0` ·
`soc-stock-1.0.0` · `nutrient-budget-1.0.0` · `usda-texture-1.0.0`
**Related ADRs:** extends ADR-0014 (knowledge honesty), ADR-0015 (pure decision
core), ADR-0021 (raster means). Introduces ADR-0022…0028 (see §12).
**Gap analysis:** `docs/m6b/M6B_GAP_ANALYSIS.md` (Phase 0, baseline 441/441 verified).

---

## 1. Position in the architecture

M6B adds a **soil intelligence layer** beside the M6A water layer:

- consumes: field/tenant model, evidence-class vocabulary, SoilGrids provider,
  CSV import patterns, knowledge-pack crop traits (EcoCrop pH optima, BNF
  ranges), the water engine's soil inputs;
- produces: soil profiles (depth-explicit), method-aware chemical/physical/
  biological indicators, SOC stocks, N/P/K budgets, a multi-domain soil-health
  profile, a management ledger, and soil-aware decision-support explanations;
- never replaces: the water balance (M6A keeps `TAW = 1000·(θFC−θWP)·Zr`; M6B
  supplies measured θFC/θWP/BD/vCF evidence INTO it), the rotation optimizer
  (M6B adds explanations and indicators; constraint semantics stay M5's), or
  the observation store (0–5 cm SoilGrids rows stay where they are).

### Method layering (mirrors ADR-0019 water ladder)

1. **Measured layer** — lab/farmer measurements with full method metadata.
2. **Derived layer** — versioned calculations over measurements (texture
   classification, porosity, AWC per layer, SOC stock). Each derived value
   records: inputs used, method + version, disclosed assumptions, refusal
   reason when inputs are missing.
3. **Mapped layer** — SoilGrids predictions (multi-depth), always labelled
   `global_soil_prediction`, never mixed into measured series.
4. **Reference layer** — knowledge-pack traits (EcoCrop pH optima, BNF
   ranges) used ONLY in labelled screening comparisons.

## 2. Units (hard rules, property-tested)

| Quantity | Unit | Notes |
|---|---|---|
| texture fractions | % or g/kg | recorded basis; sand+silt+clay = 100 ± 0.5 validated |
| bulk density | g/cm³ (kg/dm³) | basis (whole-soil vs fine-earth) recorded; SoilGrids bdod cg/cm³ ÷ 100 |
| coarse fragments | vol% or vol‰ | basis recorded; SoilGrids cfvo is vol‰ (wire unit verified live at ingestion) |
| pH | pH (scale-free) | medium (water/CaCl₂/…) + ratio recorded; **no scale conversion ever** |
| EC | dS/m (preferred) | extraction ratio + temperature reference recorded; **no cross-ratio conversion in M6B** |
| OC / OM | g/kg (OC), % (OM) | OM ≈ OC × 1.724 (van Bemmelen) via the M6A function only, disclosed |
| SOC stock | Mg C/ha | FAO/IPCC formula; see §5 |
| nutrients (elements) | kg/ha (stocks), g/kg or mg/kg (concentrations) | P₂O₅→P ×0.4364, K₂O→K ×0.8301 via versioned functions; reporting basis (elemental/oxide) mandatory on every row |
| application mass | kg (product) | grade/concentration + moisture basis recorded |
| porosity | m³/m³ | n = 1 − BD/PD; PD measured or the disclosed 2.65 g/cm³ mineral assumption (output labelled `estimated`) |
| depth | cm (canonical) | original unit + value preserved; cm conversion explicit |

## 3. Soil profile & sampling model (M6B.1)

### 3.1 Depth handling

- Canonical depth unit: cm; original unit+value preserved on every row.
- Layer = [top_cm, bottom_cm); standard SoilGrids intervals
  (0–5, 5–15, 15–30, 30–60, 60–100, 100–200 cm) are supported but NEVER
  assumed — lab depths are preserved verbatim.
- Cross-depth aggregation exists ONLY where the profile assembler can prove
  coverage (no gaps, no overlaps, same measurement basis); otherwise the
  profile lists the gap/overlap explicitly. A 0–5 cm sample is never
  silently promoted to a 0–30 cm claim.

### 3.2 Entities

- `soil_sampling_events` — field FK, sampling_date, purpose, method
  (e.g. composite_core, profile_pit, single_core), composite flag,
  subsample count, equipment, handling/prep notes, GPS + management-zone
  label (free text; no spatial assumption), collector, quality status, notes.
- `soil_samples` — event FK, sample_code (unique per tenant), composite
  parent link (individual cores of a composite), lab FK nullable,
  report_reference, received/reported dates.
- `soil_sample_layers` — sample FK, top/bottom depth + unit, layer label,
  is the canonical depth-interval carrier.
- `soil_measurements` — layer FK (nullable for field-attached gridded rows),
  field FK (always), variable_code (canonical dictionary), value, unit,
  evidence_class, spatial_support_type, method FK + inline method params
  (extractant, ratio, temperature), detection/quantification limits,
  result qualifier, uncertainty value+type, source_kind
  (`lab_analysis` | `farmer_report` | `soilgrids_profile` | `synthetic_fixture`),
  processing_version, metadata JSONB (provenance extras).
- `soil_laboratories` / `soil_analytical_methods` — normalized registries
  (tenant-scoped rows created on demand by the importer/API).
- `soil_profiles` / `soil_indicators` — **computed read-models** (not tables);
  assembly is deterministic and engine-version-pinned.

### 3.3 Laboratory CSV import (extensible mapping contract)

- A **mapping spec** (JSON) declares: column → canonical variable, unit,
  method descriptor, depth columns, qualifier/limit columns, date format,
  sample-id column, lab identity. Ship one built-in template
  (`canonical_lab_v1`) + accept client-supplied mappings; unknown columns
  are warnings, not failures.
- Validation per row: depth sanity (0 ≤ top < bottom ≤ 300 cm), fraction
  sums, numeric parse, detection-limit forms (`<0.05` → qualifier `<`,
  value None + limit 0.05 — recorded, never silently zero), duplicate
  detection (natural key sample+layer+variable+method), unit normalization
  with declared conversions only.
- Output: import run record with per-row status (imported/rejected/warning),
  rejected-row report, file sha256, idempotency key; re-import of the same
  file is a no-op by checksum.

## 4. Physical & chemical indicator engines (M6B.2/3)

- **Texture classification (USDA-1.0.0):** standard USDA triangle from
  sand/clay/silt %; works from sand+clay+silt, or sand+clay with
  silt = 100 − sand − clay **when declared**; refuses fractions outside
  [0,100] or sums outside 100 ± 0.5 (when all three given). Output includes
  class + basis + which inputs were used. Other systems (WRB etc.) are
  pass-through labels only — no cross-system mapping is attempted.
- **Porosity:** `n = 1 − BD/PD`; PD from measurement or 2.65 g/cm³ disclosed
  assumption; whole-soil BD with vCF available may compute fine-earth
  porosity with the correction disclosed; label `estimated` vs `measured`.
- **AWC per layer:** θFC − θWP (same potentials recorded, e.g. −33/−1500 kPa);
  profile AWC uses depth-weighted integration ONLY over contiguous measured
  coverage; gaps listed. Compatible with M6A TAW identity.
- **Penetration resistance / infiltration / aggregate stability:** stored
  with full method context; **no cross-procedure comparison or scoring**
  (interpretation refused with reason).
- **pH:** stored with medium + ratio + method; comparisons against crop
  optima are labelled screening (EcoCrop optima are confidence-low
  references); no universal thresholds.
- **EC/salinity:** ECe vs EC1:2.5 vs EC1:5 kept as distinct method-qualified
  measurements; no conversion across ratios in M6B (no verified
  texture-calibrated model); salinity class interpretation only for ECe,
  cited, and labelled indicative.
- **Nutrient measurements:** total vs extractable vs available distinguished
  by variable + method; concentration vs stock distinct (stock needs BD+depth
  — computed only via §5 discipline); P/K reporting form mandatory; oxide→
  elemental conversions only via `soil-engine` versioned constants.

## 5. SOC stock engine (M6B.4) — `soc-stock-1.0.0`

**Formula (FAO GSOC MRV convention, dimensionally verified in the gap
analysis §8):**

```
SOC_layer (Mg C/ha) = OC[g/kg] × BD_fine[g/cm³] × (1 − vCF[m³/m³]) × d[cm] × 0.1
```

Rules:
1. Per-layer computation; profile total = Σ layers over **contiguous,
   non-overlapping** coverage; gaps/overlaps are validated and reported —
   overlapping intervals are refused, never deduplicated silently.
2. Inputs per layer: OC concentration, fine-earth (or whole-soil BD + vCF —
   the fine-earth correction is applied ONCE; double correction is a hard
   error), thickness. **Any missing input ⇒ that layer's stock is
   `not_evaluated`; the profile total is only computed over complete
   contiguous coverage** (partial totals are labelled by covered depth).
3. BD basis handling: `whole_soil` + vCF → fine-earth correction inside the
   formula; `fine_earth` → vCF term uses layer coarse-fragment volume only;
   basis mixing in one profile is a validation error unless reconciled
   explicitly and disclosed.
4. **Fixed-depth comparison:** two sampling events compared over the common
   depth support, with a BD-change caveat emitted when layer BD differs
   (mass vs depth ambiguity, disclosed).
5. **Equivalent-soil-mass comparison:** implemented only when both events
   carry cumulative-mass capability (BD per layer + shared depth support);
   ESM without required inputs is refused with the reason (no partial ESM).
6. **Uncertainty:** lab measurement uncertainty propagates where provided
   (layer stocks via independent-input propagation, method documented);
   SoilGrids-derived stocks carry the F-8 prediction label, and field-level
   PI aggregation from pixel quantiles stays **unavailable** (reported as
   such, never averaged-and-relabeled).
7. Every run persists an immutable snapshot (inputs, methods+versions,
   per-layer results, checksum sha256) — the water-plan pattern.

## 6. Nutrient budget engine (M6B.5) — `nutrient-budget-1.0.0`

- **Inputs:** fertilizer products (grade N-P₂O₅-K₂O or elemental; conversions
  versioned), manure/compost (N/P/K concentrations + dry-matter basis +
  availability fraction REQUIRED — default refusal, never 100% available),
  BNF (pack trait range midpoint, low-confidence labelled, farmer override,
  only when the crop carries the sourced trait — never from `is_legume`
  alone), irrigation-water nutrients & deposition (recorded when supplied;
  otherwise missing flows).
- **Outputs:** harvest removal = exported biomass × concentration (concentration
  from farmer/lab entry or synthetic-labelled demo data; the reference
  library is EMPTY pending verified sources — backlog). Residue removal same
  discipline. Dry-matter vs as-harvest basis explicit on both sides.
- **Balance:** `balance = Σ documented inputs − Σ documented outputs` per
  nutrient per season; **classification:** `complete` (all planned flows
  supplied — realistically only when the farmer records them),
  `partial` (some flows supplied; missing flows LISTED, never zero),
  `not_evaluable` (no usable side). Leaching/denitrification/volatilization
  are NEVER assumed zero — when absent, the balance is labelled partial and
  the interpretation states which loss terms are unknown.
- **Multi-season:** per-season budgets + cumulative sum over the rotation
  window; unevaluable seasons listed, not zero-filled (the water-engine
  rotation-total pattern).
- **NUE:** only the explicit output/input ratio (PFP-style) is computed,
  labelled with its definition; agronomic/recovery efficiency need controls
  that M6B does not have — refused with reason rather than faked.

## 7. Biological indicators & management ledger (M6B.6/8)

- Biological measurements (MBC, MBN, respiration, PMN, earthworms, enzymes,
  POM): stored with protocol metadata (handling, incubation, temperature,
  unit, reference). No simulation, no inference from missingness (missing
  biological data is NOT poor health — it is unknown).
- Management ledger: chronological events (planting, harvest, fertilization,
  manure/compost, residue retention/removal, tillage, cover-crop termination,
  irrigation, amendments) with links to nutrient applications where
  applicable. The assessment may present temporal ASSOCIATIONS (event before
  measurement) with the explicit caveat "association, not causation", and
  always separates measured changes from expected mechanisms.

## 8. Multi-domain assessment (M6B.7) — `soil-health-profile-1.0.0`

Domains: Physical · Chemical · Biological · Hydrological · Organic-matter &
nutrient cycling. Per domain the assessment lists: available indicators
(with value, unit, method, evidence class, date), missing indicators,
trend (only through the comparability gate), data-quality flags, reference
methodology, local-applicability status (`reference` — no regional
confirmation exists), uncertainty, and a plain-language interpretation that
never upgrades beyond the evidence. **No overall score** — the composite
index is deliberately absent (no validated weighting methodology; ADR-0026).

## 9. Decision support & VOI (M6B.9/10)

- Soil-aware candidate explanations REUSE the rotation pH-screening trait
  path (EcoCrop, low confidence, screening label) and add: salinity concern
  flags only when ECe evidence exists (cited indicative classes), SOC/OM
  context (descriptive, from measured values), root-zone AWC context fed to
  the water narrative. Missing indicators are named with the measurement
  that would materially improve the decision (that IS the VOI basis).
- **VOI (qualitative):** a decision-linked ranking of missing measurements
  (e.g. ECe when salinity risk exists; BD+OC for SOC stock; θFC/θWP for the
  water balance). No invented costs/benefits/confidences; the ranking text
  states the decision each measurement would unblock. Collected measurements
  are recorded back through the sampling domain (closing the loop).

## 10. API surface (`/api/v1/`, existing conventions)

```
POST   /fields/{fid}/soil-sampling-events          (+ GET list)
POST   /fields/{fid}/soil-samples                  (+ GET list, GET /soil-samples/{id})
POST   /soil-samples/import                        (multipart CSV + mapping spec)
GET    /fields/{fid}/soil-profile                  (?as_of=&engine_version pinned)
GET    /fields/{fid}/soil-profile/history
GET    /fields/{fid}/soil-indicators               (method-aware read model)
POST   /fields/{fid}/soc-stock-runs                (+ GET list, GET /soc-stock-runs/{id})
POST   /fields/{fid}/nutrient-products             (+ GET)
POST   /fields/{fid}/nutrient-applications         (+ GET)
POST   /fields/{fid}/nutrient-removals             (+ GET)
POST   /fields/{fid}/nutrient-budget-runs          (+ GET list, GET /nutrient-budget-runs/{id})
POST   /fields/{fid}/soil-assessments              (+ GET /soil-assessments/{id})
GET    /fields/{fid}/soil-health                   (latest assessment, read model)
GET    /fields/{fid}/soil-data-readiness           (VOI ranking)
GET    /soil/methods                               (versioned methodology catalog)
POST   /fields/{fid}/soil-management-events        (+ GET)
```

All list/detail endpoints tenant-isolated (403 cross-tenant), idempotency-key
support on run creation, immutable run snapshots with checksums, honest
statuses (`evaluated | not_evaluated | not_supplied | refused`) everywhere.

## 11. Frontend — Soil tab

- **Overview:** domain cards (available/missing indicators), SYNTHETIC/labelling
  banners, no score.
- **Profile explorer:** depth-bar layout (actual sampled depths), per-layer
  properties with method + source badges, gap/overlap indicators.
- **Sampling map:** field polygon + GPS sample markers (distinct markers for
  measured vs gridded); management-zone labels.
- **Laboratory import workspace:** upload → mapping preview → validation →
  per-row report (imported/rejected/warnings) → history.
- **SOC & nutrient dashboard:** SOC concentration/stock by depth; N/P/K
  budget bars with missing-flow warnings; season switcher.
- **Timeline:** measurement history with comparability warnings between
  method-incompatible points.
- **Simple/Expert modes:** Expert exposes methods, extraction details, units,
  equations, quality flags, versions, checksums; Simple uses plain language
  without hiding limitations. Responsive (390px), sticky footer, a11y.

## 12. ADR register (M6B)

- **ADR-0022** — Soil measurement history is a dedicated depth-explicit
  relational domain; `observations` stays untouched for backward compatibility.
- **ADR-0023** — Analytical method metadata is mandatory; measurements are
  never merged/compared across incompatible methods (pH media, EC ratios,
  BD bases, infiltration procedures).
- **ADR-0024** — SOC stocks are layer-wise FAO/IPCC calculations refused when
  layer inputs are missing; FD vs ESM comparisons are method-aware and
  version-pinned; coarse-fragment correction is applied exactly once.
- **ADR-0025** — Nutrient budgets are partial by default; missing flows are
  enumerated, never zero-filled; oxide↔elemental conversions are versioned
  stoichiometric functions.
- **ADR-0026** — Soil health is a transparent multi-domain profile with no
  composite index (no validated methodology exists in M6B).
- **ADR-0027** — Temporal comparisons pass a comparability gate (depth,
  method, basis, spatial support) or are refused with reasons.
- **ADR-0028** — Data-collection priorities are qualitative, decision-linked,
  and never fabricate costs, benefits, or confidence.

## 13. Honesty contract (inherits all M6A/deepening rules)

Missing ≠ zero · partial evidence never upgraded · method-incompatible data
never merged · mapped ≠ measured (structurally distinct) · synthetic data
labelled end-to-end · every number traceable to a cited method or a recorded
measurement · unknown stays unknown (unknown allocation, unknown flow,
unknown stock) · no agronomic validation claimed beyond the arithmetic.

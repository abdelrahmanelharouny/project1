# M6B — Gap Analysis & Readiness Report (Phase 0)

**Milestone:** M6B — Soil Health, Soil Profile Intelligence & Nutrient Cycling Engine
**Date:** 2026-10-31
**Method:** actual repository inspection; full regression suite re-run from scratch during
this phase; every claim below checked against code, not prior reports.

**Baseline verified:** **441/441 backend tests passing** (fresh run, 2m27s,
`pytest tests/` exit 0). API `:3030` healthy (`/api/v1/health`), Next.js `:3000`
serving. PostgreSQL 16 + PostGIS on :5433, migrations 0001–0006 applied
(`water_plans`, `crop_water_parameters` present). Knowledge pack
`kp-seed-2026.11.1` active (11 crops; faba_bean keeps its deliberate Kc gap).

---

## 1. Existing reusable components (verified in code)

| Component | Location | Reuse for M6B |
|---|---|---|
| Canonical observation container | `app/db/models.py` `Observation` | measurement container pattern: evidence_class per row, uncertainty_value/uncertainty_type, quality flags, processing_version, metadata JSONB, natural-key dedupe, `lab_sample` spatial-support value **already exists** in the CHECK constraint |
| Evidence class vocabulary | `app/data_platform/contracts/observations.py` | 8 classes incl. `direct_field_measurement`, `farmer_reported_record`, `global_soil_prediction` — measured/estimated/farmer/mapped separation is already first-class |
| SoilGrids WCS provider | `app/data_platform/providers/soilgrids/provider.py` | verified live (unit conversions phh2o÷10, soc dg/kg÷10, bdod cg/cm³÷100; mean/Q0.05/Q0.95; field-cell masking; F-8 honest uncertainty label). **Ingests the 0–5 cm depth only** — the docstring itself defers the six standard depths to "the soil measurement history milestone" (= M6B) |
| Saxton–Rawls 2006 PTF | `app/water/soil.py` | verified coefficients + validity-domain enforcement; reuse for AWC/porosity cross-checks; **do not duplicate** |
| van Bemmelen OC→OM (1.724) | `app/water/soil.py` | the only sanctioned conversion; already disclosed wherever used |
| Soil input assembly for water | `app/water/service.py` `build_soil_water_inputs` | farmer_measured / ptf_texture / none ladder with per-item evidence classes — M6B AWC outputs must feed this, not fork it |
| Knowledge pack traits | `app/knowledge/packs/seed_pack_v1.py` | `n_fixation_capacity_kg_ha` (Herridge et al. 2008, confidence **low**, declared order-of-magnitude) on soybean/dry_bean/faba_bean; EcoCrop `ph_opt_min/max` (confidence low); `is_legume` flag |
| Rotation soil consumption | `app/rotation/service.py` `SOIL_VARIABLES` | latest 0–5 cm obs of ph/soc/sand/clay/bdod; pH screening vs EcoCrop optimum with evidence class in reason text; missing ⇒ "not evaluated" |
| CSV import pattern | `app/data_platform/imports/csv_service.py` | template validation, sha256 provenance, idempotency; soil-lab importer follows the pattern but needs a **mapping contract** (lab templates differ) |
| Water methods catalog | `app/water/contracts.py` | versioned method registry + citation pattern to replicate (`WATER_METHODS_VERSION`) |
| Passport honest gating | `app/passport/service.py` | `soil_analysis` already declared blocked with "requires field soil samples" — M6B supplies the data surface |
| Migration discipline | `migrations/versions/0001–0006` + `test_migrations.py` | upgrade/downgrade exercised every test run |

## 2. Missing scientific concepts (must be built in M6B)

1. **Depth-explicit soil domain.** No table stores a top/bottom depth. `Observation`
   carries depth only inside `metadata` JSONB (SoilGrids rows: `"depth": "0-5cm"`).
   No profile model, no layer identity, no overlap/gap validation anywhere.
2. **Sampling events as first-class objects.** Nothing represents a sampling
   event (date, method, purpose, locations, composite structure, subsample
   count, handling). Composite→subsample relationships are unrepresentable.
3. **Laboratory analysis metadata.** Lab identity, analytical method, extractant,
   soil:solution ratio, detection/quantification limits, result qualifiers,
   measurement uncertainty, QC status — no storage at all. Backlog S-3/S-4
   (deepening) explicitly reserved this.
4. **Texture completeness.** Sand + clay are ingested; **silt is not** (SoilGrids
   `silt` coverage exists but is not wired). No texture-classification code
   (USDA triangle) exists. Fractions-sum-100% validation does not exist.
5. **Bulk-density bases & coarse fragments.** SoilGrids `bdod` is stored, but
   whole-soil vs fine-earth basis is undistinguished, and **coarse fragments
   (`coarsefragments` coverage) are not ingested** — the `(1 − vCF)` term of the
   SOC equation therefore has no data surface today (deepening S-2 blocker).
6. **SOC stock engine.** Concentration (g/kg) is stored; no stock (Mg C/ha)
   computation exists (deepening S-2: "NO stock is computed or displayed
   anywhere"). Layer-wise stock, profile aggregation with gap/overlap checks,
   fixed-depth vs equivalent-soil-mass comparison — all absent.
7. **EC / salinity.** No EC ingestion (deepening S-4: procedure metadata is a
   hard requirement before any EC row is accepted). ECe vs EC1:5 distinction,
   temperature reference, and the refusal to convert across textures must be
   enforced from day one.
8. **Nutrient domain.** No nutrient products, applications, removals, or budget
   entities. N/P/K oxide↔elemental versioned converters absent. Manure
   availability fractions, dry-matter vs as-fed basis — absent.
9. **Biological indicators.** Storage only (MBC, MBN, respiration, PMN,
   earthworms, enzymes, POM) — no simulation (red line: never simulate from
   generic characteristics).
10. **Multi-domain assessment.** No assessment entity, no domain profile, no
    comparability gate for temporal comparison.
11. **Management ledger.** No management-event entity (tillage, residue,
    amendments…) though the rotation run stores crop assignments (partial reuse
    possible for planting/harvest rows).
12. **SoilGrids multi-depth ingestion.** Six standard depths (0–5, 5–15, 15–30,
    30–60, 60–100, 100–200 cm) — provider is 0–5-only today (natural-key
    collision if naively extended; see §3).

## 3. Existing schema limitations & migration plan

- `observations` natural key = (field, product, variable, observed_at,
  time_support, spatial_support). Six SoilGrids depths share one snapshot
  timestamp ⇒ multi-depth ingestion into `observations` would collide and
  would silently overload `metadata->depth`. **Decision (ADR-0022):** soil
  measurement history lives in NEW relational tables
  (`soil_sampling_events` → `soil_samples` → `soil_sample_layers` →
  `soil_measurements`, plus `soil_laboratories`, `soil_analytical_methods`);
  the existing 0–5 cm `observations` rows remain untouched for backward
  compatibility (rotation/water keep reading them). Gridded SoilGrids
  multi-depth values enter `soil_measurements` with `evidence_class=
  'global_soil_prediction'`, `spatial_support_type='grid_cell'`,
  `source_kind='soilgrids_profile'` — measured vs mapped stays structurally
  distinct (exit criterion 3).
- New tables (migration `0007_soil_intelligence`, all FK→fields/tenants,
  UUID PKs, temporal columns, JSONB only for genuine metadata):
  `soil_laboratories`, `soil_analytical_methods`, `soil_sampling_events`,
  `soil_samples`, `soil_sample_layers`, `soil_measurements`,
  `soil_management_events`, `nutrient_products`, `nutrient_applications`,
  `nutrient_budget_runs`, `soc_stock_runs`, `soil_assessments`.
  Methodology registry + evidence references stay **code-versioned constants
  + run snapshots** (the established water-engine pattern) instead of extra
  tables — documented in M6B_DATABASE_DESIGN.md.
- `soil_profiles` and `soil_indicators` are computed read-models (API-level),
  not persisted snapshots — profile assembly is deterministic from
  measurements; persisting a copy would duplicate truth. Documented, with the
  derivation pinned by engine version in every response.

## 4. Duplicate-functionality risks (avoided)

- θFC/θWP: M6A water service takes them as request inputs. M6B will **feed**
  that path from measured samples (evidence class `direct_field_measurement`)
  rather than create a second water-holding store. AWC layer values must use
  the same FAO-56 TAW identity (`TAW = 1000·(θFC − θWP)·Zr`).
- OC→OM: only `app/water/soil.organic_carbon_to_om_percent` (van Bemmelen,
  disclosed) is sanctioned; soil module imports it.
- CSV ingestion: one import framework, one canonical soil schema; lab-specific
  column mapping is data (a mapping spec), not a fork of the importer.
- Unit conversions: P₂O₅→P and K₂O→K are stoichiometric constants
  (P = P₂O₅ × 0.4364; K = K₂O × 0.8301) implemented once as **versioned
  functions** with the molecular-weight derivation recorded; never ad-hoc.

## 5. Integration risks with M6A / M5

1. `SOIL_VARIABLES` consumers pick "latest observation per variable" — they
   read `observations`, which M6B does not restructure. Backward compatible;
   verified by existing suite.
2. Water plans snapshot `soil_inputs` with evidence classes; M6B sample data
   must map to the same vocabulary (`farmer_reported_record` →
   `direct_field_measurement` distinction preserved; water service accepts
   explicit values, so the mapping layer supplies them with provenance).
3. Rotation pH screening uses EcoCrop optima (confidence low) — M6B.9
   candidate soil evaluation must reuse the same pack traits and keep the
   "screening comparison, pending local calibration" label (deepening S-3),
   and must not invent thresholds.
4. SoilGrids provider changes must not break `uq_observation_natural_key`:
   multi-depth values go to the new tables; the 0–5 cm ingestion path is
   frozen (only additive variable support: silt + coarsefragments rows follow
   the SAME natural key shape, one row per variable — safe).
5. Passport: after M6B, `soil_analysis` readiness flips from "requires soil
   samples" to available when samples exist — gating code must be updated
   without weakening the climate/water gates.

## 6. Knowledge gaps (honest boundaries inherited)

- **No verified nutrient-removal concentration library.** Fabricating per-crop
  N/P/K removal coefficients is forbidden. M6B ships the engine + farmer/lab
  supplied concentrations (evidence class recorded) + explicit reference
  library = EMPTY pending verified sources (M6B_RESEARCH_BACKLOG.md). Demo
  seed uses SYNTHETIC-labelled farmer records.
- **BNF:** pack trait is order-of-magnitude (low confidence) and only for three
  legumes; BNF enters budgets only as the sourced range midpoint **disclosed as
  an estimate**, with farmer override, never from `is_legume` alone.
- **Atmospheric N deposition, irrigation-water nutrients:** no data surface —
  budget flows stay "not supplied", listed as missing flows (never zero).
- **Composite index:** no validated weighting methodology exists → default is
  the transparent multi-domain profile; no composite score in M6B.
- **Salinity thresholds, pH suitability:** no universal thresholds; any
  interpretation is labelled screening against cited context or left to the
  farmer.

## 7. Required references (to verify before use — fetched, not from memory)

1. FAO GSOC MRV Protocol v2 (SOC stock equation, layer protocol, bulk-density
   guidance) — formula `SOCstock = OC × BDfine × (1 − vCF) × d × 0.1` with OC
   in g/kg (= mg C/g), BD in g/cm³, d in cm, result Mg C/ha; dimensional check
   performed and unit-tested against hand-computed values.
2. SoilGrids FAQ / WCS docs (six standard depth intervals 0–5/5–15/15–30/30–60/
   60–100/100–200 cm; native units per property incl. `silt` g/kg and
   `coarsefragments` vol‰ conventions — to re-verify live before wiring).
3. USDA NRCS Soil Health Assessment (indicator domains; explicitly no
   universal thresholds adopted).
4. FAO Soils Bulletin 62 (x2002e) — salinity methodology: ECe as the standard
   salinity measure; EC of other soil:water ratios not interchangeable.
5. FAOSTAT cropland nutrient budgets (ESSD 16, 525–2024) — budget structure
   (inputs/outputs flows; partial vs full balances; the leaching/volatilization
   honesty requirements mirror this structure).
6. CCAFS/FAO smallholder soil-carbon measurement chapter — equivalent soil mass
   concept and fixed-depth caveat.

## 8. Critical assumptions (declared up front)

- FAO/IPCC SOC formula dimensional identity verified analytically (see §7.1);
  golden tests use hand-computed independent values, never the implementation.
- Porosity uses `n = 1 − BD/PD` with PD = 2.65 g/cm³ ONLY as a documented
  mineral-soil assumption, output labelled `estimated`; a measured PD wins.
- EC conversions across extraction ratios are REFUSED by default (no
  texture-calibrated model shipped in M6B).
- pH scales/methods are never merged or converted.
- Equivalent-soil-mass comparison requires measured layer masses; otherwise
  the comparison is refused with the reason (no partial ESM claims).
- SoilGrids field-level uncertainty stays the honest F-8 label; per-field 90%
  PI from pixel quantiles remains unavailable (S-1) and is reported as such.
- All M6B numeric outputs carry engine/method version strings and sha256
  checksums (the M6A reproducibility pattern).

## 9. Execution order (increments, each ending green)

Step 2 design/ADRs → Step 3 sampling/profile/lab models + CSV import →
Step 4 physical/chemical indicator engines → Step 5 SOC stock engine →
Step 6 nutrient budget engine → Step 7 assessment → Step 8 ledger + decision
support → Step 9 UI/APIs → Step 10 benchmarks + E2E + documentation. After
every increment: affected tests + regression run + docs touch.

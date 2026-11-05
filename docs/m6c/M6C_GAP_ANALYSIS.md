# M6C — Gap Analysis & Readiness Report (Increment 1)

**Milestone:** M6C — Field Management Intelligence (cover crops, residue management,
soil cover, erosion screening & operations planning)
**Date:** 2026-10-31
**Method:** actual repository inspection; full regression suite re-run from scratch during
this phase; every claim below checked against code, not prior reports.

---

## 0. Baseline verified (fresh runs, this session)

| Check | Result |
|---|---|
| Backend regression suite | ✅ **566/566 passed** (fresh `pytest tests/`, 211 s, exit 0) — matches the M6B verification report exactly |
| Frontend lint | ✅ clean (`bun run lint`, exit 0) |
| Migrations | ✅ single head `0007_soil_intelligence`, applied; `alembic current == heads` |
| API | ✅ `:3030` `/api/v1/health` → `{"status":"ok"}` (uvicorn) |
| Next.js | ✅ `:3000` HTTP 200, "FieldShift — Agricultural decision support" |
| Browser smoke | ✅ auth gate → "Enter demo workspace" → 8 tabs render (Overview, Farms & Fields, Observations, Features, Rotation, Water, Soil, Data Passport); zero page errors |
| Database | ✅ PostgreSQL 16 + PostGIS on :5433 (`db/pgenv`, `db/pgdata`); demo data present (1 farm / 2 fields / 11 crops / 153 crop traits / 4 water plans / 0 soil-management events) |
| Environment | ✅ `mini-services/fieldshift-api/.venv` present; both dev servers running |

Environment versions recorded: Python 3.12 (.venv), PostgreSQL 16.10, PostGIS 3.5.0,
Next.js (dev server, canary line per package.json), Node/bun workspace, OR-Tools 9.x
(rotation optimizer).

---

## 1. Existing reusable components (verified in code)

| Component | Location | Reuse for M6C |
|---|---|---|
| **Farm / field domain** | `app/db/models.py` `Farm` (timezone, country_code, unit_system), `Field` (area_ha, PostGIS MULTIPOLYGON boundary, boundary versioning) | every M6C entity scopes to field + tenant through these; farm timezone drives all calendar math |
| **Geodesic & geometry validation** | `app/geospatial/validation.py`, `farms_fields/service.py` | reuse as-is; no new geometry code in M6C |
| **Canonical observation container** | `Observation` model (evidence_class per row, uncertainty, quality flags, processing_version, metadata JSONB, natural-key dedupe) | pattern for cover observations; NDVI-style remote-sensing rows already carry evidence classes |
| **Evidence-class vocabulary** | `app/data_platform/contracts/observations.py` — 8 classes incl. `direct_field_measurement`, `farmer_reported_record`, `model_estimate`, `global_soil_prediction`, `synthetic_test_data` | M6C §3.2 mapping is nearly 1:1; M6C adds **no new evidence classes**, it maps its needs onto the existing set (see §5.2) |
| **Knowledge pack system** | `knowledge_packs` (+checksum, draft/active/retired lifecycle), `knowledge_sources` (license/attribution/citation), `crop_families`, `crops`, `crop_varieties`, `crop_traits` (row-per-context, value range, confidence, validation status, validity interval) | M6C practice/cover-crop knowledge extends this pack family — a **new pack code** carrying practice definitions and cover-crop traits; the import/validate/activate workflow is reused, not forked |
| **Crop calendar windows** | `crop_calendar_windows` (MM-DD recurring, hemisphere, region, wrap-around) | sowing windows for cover crops reuse this structure verbatim (new rows for cover-crop species, only with sources) |
| **Rotation rules** | `rotation_rules` with `rule_type IN (… 'cover_crop_suitability','residue_management','soil_cover' …)` — the M6C-relevant rule types **already exist** in the CHECK constraint and one seed-pack rule (`cover_crop_suitability`) is loaded | cover-crop following-crop compatibility & residue rules are *data*, not new machinery; hard enforcement stays gated at `confirmed_regional` exactly as in M5 |
| **Crop history** | `crop_history` (field-scoped, sowing/harvest dates, evidence_class) | supplies the actual main-crop calendar context for cover windows and bare-soil intervals |
| **M6A water engine** | `app/water/*` (`water-engine-1.0.0`, `water-methods-1.0.0`), `WaterPlan` immutable snapshots, FAO-56 Kc curve, FAO-33 effective rainfall, root-zone balance, 7-quantity ladder | cover-crop water use **must call the M6A stack** (curve + ET0 climatology + Pe) — never a parallel model; cover-crop Kc rows live in `crop_water_parameters` (new sourced rows) or stay missing |
| **Rotation water integration** | `app/rotation/constraints.py` `check_water_allocation` (NIR-based per-season allocation) | the pattern to copy for "cover crop must fit the same allocation" honesty (with explicit ETc-fallback disclosure) |
| **M6B soil domain** | `soil_sampling_events/samples/layers/measurements`, texture triangle, AWC, method-aware pH/EC | soil-condition inputs for cover-crop eligibility (pH, texture, drainage evidence) read from M6B measurements; no duplication |
| **M6B management ledger** | `SoilManagementEvent` — 12 event types incl. `planting`, `harvest`, `residue_retention`, `residue_removal`, `tillage`, `cover_crop_termination`, `irrigation`, `soil_amendment` | **this is the existing management event store.** M6C operations map onto it (see §2) — no second ledger |
| **M6B nutrient budget** | `nutrient_products/applications/removals/budget_runs`, versioned P₂O₅/K₂O converters | residue nutrient content links here (Increment 5); residue events must be *consumable* by the budget without double counting |
| **Feature engine** | `feature_runs/values`, catalog `featurespec-2026.11.x`, calendar helpers (`app/features/calendar.py`: timezone resolution, day/month/season bounds, hemisphere seasons) | cover-window season logic and any cover metrics reuse these calendar primitives |
| **Run-snapshot pattern** | `WaterPlan` / `RotationRun` / `SoilAssessmentRun`: status enum, immutable result JSONB, engine+methods version columns, knowledge pack refs, idempotency key (partial unique), sha256 checksum, created_by | M6C runs (cover-crop plans, erosion assessments, schedule runs, management plans) replicate this pattern |
| **Passport honest gating** | `app/passport/service.py` readiness rules with explicit missing-input lists | management-plan readiness follows the same "blocked with reasons" shape |
| **API conventions** | `/api/v1/` prefix, error envelope (`error.code/message/details/request_id`), 202 job pattern, idempotency keys, tenant-scoped 403s | M6C routes follow exactly (see §8) |
| **Optimizer** | `app/rotation/optimizer.py` OR-Tools CP-SAT adapter with named-assumption infeasibility reporting | operations scheduling reuses CP-SAT via a **new** scheduling-specific formulation in `app/management/` (not by touching the rotation optimizer) |
| **Frontend design system** | `src/components/fieldshift/*`: workspace tabs, `badges.tsx` (SyntheticBadge, QualityBadge…), field picker, Simple/Expert disclosure patterns, sticky footer (`mt-auto`), offline map worker | new **Management** tab follows the same structure (see §9) |
| **Dev seed** | `app/dev/seed.py` idempotent demo seed | extended additively with M6C demo fixtures, clearly labelled synthetic |

## 2. Existing management event types vs proposed M6C operations

`soil_management_events.event_type` CHECK (migration 0007):
`planting, harvest, fertilizer_application, manure_application, compost_application,
residue_retention, residue_removal, tillage, cover_crop_termination, irrigation,
soil_amendment, other`.

| M6C operation concept (spec §8.1) | Covered today? | Decision |
|---|---|---|
| Main-crop planting / harvest | ✅ `planting` / `harvest` | reuse; M6C *reads* these for the cover timeline |
| Cover-crop seeding | ✅ `planting` (with `details.crop_role='cover'`) | reuse via details; a **structured** cover-crop plan row (new `cover_crop_plan_items`) remains the analytical object |
| Cover-crop termination | ✅ `cover_crop_termination` | reuse; method/equipment recorded in `details` |
| Residue retention / removal | ✅ `residue_retention` / `residue_removal` | reuse as the *event* surface; quantities live in the new residue ledger (dry-matter) — the ledger **references** the event id, never redefines it |
| Tillage / seedbed prep | ✅ `tillage` | reuse |
| Irrigation events | ✅ `irrigation` | reuse |
| Fertilizer / manure / compost | ✅ (M6B nutrient tables are the quantitative surface) | reuse |
| Mulching | ⚠️ only via `soil_amendment`/`other` | map to `soil_amendment` with `details.mulch=true`; **no new event type** (additive JSONB payload, CHECK unchanged) |
| Baling / grazing / burning | ⚠️ partial (`residue_removal` w/ details) | residue ledger records the flow *fate* with provenance; the event ledger keeps its 12 types |
| Machinery/labor tasks with dependencies | ❌ no scheduling domain | new M6C `field_operations` + `farm_resources` (see §6) — distinct purpose from the agronomic event ledger |

**Conclusion (red-line 1):** no second `management_events` table. M6C adds
`field_operations` for *planned/scheduled work* (a planning artefact with windows,
dependencies, resources and completion states) and uses `soil_management_events`
for *what actually happened agronomically*. The two reference each other
(`field_operations.completed_event_id → soil_management_events.id`) but never duplicate.

## 3. Missing domain concepts M6C must build (verified absent in code)

1. **Practice registry.** No `practice_definitions`, no practice knowledge records,
   no practice–evidence links. `rotation_rules` covers pairwise crop relations only.
2. **Soil-cover timeline.** Nothing computes cover status over time. Crop
   history has sowing/harvest dates; soil management events exist but nothing
   assembles them into an interval timeline, and there is **no cover-observation
   container** (farmer % cover, residue cover) nor bare/unknown interval logic.
3. **Cover-crop planning engine.** No candidate evaluation beyond the M5
   `cover_crop_opportunity` objective (a descriptor-weighted screening proxy)
   and the single `cover_crop_suitability` seed rule. No sowing-window →
   following-crop window reasoning, no termination decision object, no
   water-competition integration for covers.
4. **Cover-crop species knowledge.** Seed pack has 11 crops; only `faba_bean`
   carries `is_cover_crop_capable=true`; **no cover-crop functional traits**
   (establishment speed, termination methods, seeding rates, frost sensitivity)
   exist anywhere — and per the red lines M6C will **not invent them**; the
   engine must honestly report `not_evaluated` dimensions until sourced packs
   arrive (Increment 2 ships the schema + the honest empty state, not fabricated values).
5. **Residue ledger.** No residue mass accounting, no dry-matter flows, no
   residue-quality storage, no mass-balance checks. M6B nutrient budget covers
   *nutrients* only (and has no residue-production coefficients either).
6. **Erosion screening.** No erosion domain at all. The only artifact is the M5
   `erosion_reduction_index` objective — a *duration-coverage screening proxy*
   inside rotation scoring, explicitly not a soil-loss estimate. No RUSLE
   anything, no slope/LS inputs, no erosivity data. There is also **no DEM
   ingestion** in the platform; fields carry polygons only (area/centroid),
   so any terrain-based screening is data-blocked today (see §7).
7. **Operations & resources.** No `field_operations`, no machinery/labor
   registry, no availability calendars, no precedence graph, no scheduler.
8. **Management plan aggregation.** No entity ties practices + cover crops +
   residues + operations into one seasonal, explainable, versioned plan.
9. **Weather forecasts.** Provider registry has historical/reanalysis products
   only. M6C must treat forecasts as **absent** (pending manual checks) — no
   climate-normals-as-forecast anywhere.

## 4. Practice ontology (Increment 1 design contract)

A **practice** is a versioned management concept with evidence, operating
conditions, mechanisms, risks and regional applicability — never a universal switch.

```
PracticeDefinition (knowledge-pack row, versioned by pack checksum)
  practice_code        e.g. "cover_cropping", "residue_retention", "no_till"
  practice_family      cover_crop | residue | tillage | soil_cover | erosion_control | traffic
  name, description
  mechanisms[]         {mechanism_code, claim_text, source_key, evidence_class,
                        confidence, conditions}        # e.g. "reduces raindrop detachment"
  requirements[]       {requirement_code, kind: seed|equipment|labor|knowledge|window,
                        description, source_key, evidence_class}  # what must exist to adopt
  trade_offs[]         {dimension: water|nutrients|labor|machinery|pest|cost|forage,
                        direction: positive|negative|context_dependent,
                        text, source_key, evidence_class}          # NO universal positives
  risks[]              {risk_code, text, source_key, evidence_class, conditions}
  regional_applicability[] {region_code | agroecological_zone, basis, source_key,
                        validation_status}                          # never latitude-only
  lifecycle            draft | active | retired  (pack lifecycle, reused)
```

**Decision ADR-M6C-1:** practices are knowledge-pack data (JSONB payload validated by
a strict Pydantic schema, imported through the existing pack import/activate workflow),
*not* a new top-level table family. Rationale: the pack system already provides
versioning, checksums, licensing, conflict detection, activation lifecycle and audit —
duplicating it for practices would violate red-line 1.

**Decision ADR-M6C-2:** cover-crop *candidate species traits* reuse `crop_traits`
(new trait codes documented in the data dictionary) — the engine reads them with
per-trait evidence classes. A missing trait is a missing dimension, never a default.

## 5. Soil-cover temporal model (Increment 1 design contract)

### 5.1 Cover states

`living_main_crop | living_cover_crop | surface_residue | mulch | bare | unknown`

Overlapping sources resolve by explicit precedence **within an interval**, but the
timeline stores the evidence, not just the winner: an interval may be "residue + bare
fraction unknown". NDVI never converts to % cover (no validated regional model exists
in the repo; red line).

### 5.2 Inputs (all existing or additive)

- `crop_history` sowing/harvest (farmer_reported_record) → living-main-crop intervals
- `cover_crop_plan_items` establishment/termination (Increment 4) → cover-crop intervals
- `soil_management_events` residue_retention / removal / tillage → residue interval edges
- NEW `soil_cover_observations` (farmer % cover with method + photos hash, or
  remote-sensing index values with provider+product) — evidence-class per row
- Unknown where nothing is observed: **unknown ≠ bare** (hard rule, property-tested)

### 5.3 Metrics (transparent, threshold-free by default)

days_living_cover, days_residue_cover, days_bare_known, days_unknown,
longest_bare_interval, protective_cover_fraction (= covered / (covered+bare+unknown)
reported with the denominator decomposition), seasonal series.
Pass/fail only when a **sourced, region-scoped threshold** exists (none ship in the
seed pack; the field stays "no applicable threshold — metrics only").

## 6. Residue flow model (Increment 1 design contract)

```
ResidueRecord  (per field, season, crop; dry-matter basis mandatory)
  produced_dm_tonnes         (status: measured | estimated_from_coefficient | farmer_reported | missing)
  coefficient_ref            (residue-to-product ratio / harvest index source, if used)
  flows[]                    RetainedSurface | Incorporated | RemovedBaled | Grazed |
                             Burned | Other  ×  {dm_tonnes, date, event_id?, evidence_class}
  unaccounted_dm_tonnes      computed; negative availability = hard error (never clamped)
ResidueQualityMeasurement     C fraction, N concentration, C:N, lignin — per sample,
                             evidence class + method; NO universal decomposition constants
```

Mass-balance identity (property-tested): `produced ≥ Σ(flows)` per record;
`unaccounted = produced − Σ(flows) − unknown_loss` never negative. Nutrient linkage:
N/P/K content × dry matter feeds M6B `nutrient_budget_runs` as an *input row with
provenance* — the budget engine owns aggregation; M6C never writes nutrient totals
directly (no double counting). Residue carbon input is recorded as *input*, never as
SOC stock change (M6B separation preserved).

## 7. Erosion & conservation screening (Increment 1 design contract)

- **Process taxonomy stored explicitly:** sheet_rill | rill | ephemeral_gully |
  classical_gully | wind | streambank | sediment_delivery — a result declares which
  processes it speaks to; RUSLE-type outputs declare sheet_rill/rill only.
- **RUSLE-family adapter (Increment 6) is conditional by construction:**
  `A = R·K·LS·C·P` computed **only** when all five factors arrive with source +
  region + unit-system provenance; factors are farmer/sourced inputs, never invented;
  US NRCS factor databases are not global defaults. Missing factor ⇒ `not_evaluated`
  (never a numeric answer). Result labelled `screening_only` unless a documented local
  parameter set justifies more. No DEM exists in-platform ⇒ LS must be farmer/sourced
  or the run is data-blocked; **no naive slope-length from polygons** (a polygon has no
  elevation).
- **Qualitative screening** (evidence-of-concern flags from slope class, soil
  erodibility evidence, rainfall aggressiveness evidence, cover metrics, management
  records) is separate from any modeled quantity, and says "screening" everywhere.
- Field-observed erosion signs (farmer-reported) and unknown status are first-class
  outputs (4-way separation per spec §7.4).

## 8. API integration points (spec §11 mapped onto existing conventions)

All routes under `/api/v1/`, existing error envelope, tenant scoping via
membership-checked field resolution (`_field_for_principal` pattern), 202+job or
201-run patterns, idempotency keys on run creation, pagination on lists.

| Group | Routes (new) | Notes |
|---|---|---|
| Soil cover | `GET /fields/{id}/soil-cover/timeline`, `POST /fields/{id}/soil-cover/observations`, `GET /fields/{id}/soil-cover/metrics` | timeline & metrics computed from stored inputs (deterministic function, no run row needed); observations are plain CRUD |
| Cover crops | `GET /fields/{id}/cover-crop-candidates` (POST evaluate), `POST /fields/{id}/cover-crop-plans`, `GET /cover-crop-plans/{plan_id}` | plans are immutable snapshots (WaterPlan pattern) |
| Residues | `POST /fields/{id}/residue-records`, `POST /fields/{id}/residue-flows`, `GET /fields/{id}/residue-ledger` | ledger endpoint returns records + balance checks |
| Erosion | `POST /fields/{id}/erosion-assessments`, `GET /erosion-assessments/{run_id}`, `GET /fields/{id}/erosion-readiness` | assessment = run snapshot |
| Operations | `GET /fields/{id}/operation-templates`, `POST /fields/{id}/operations`, `GET /fields/{id}/operations`, `POST /fields/{id}/operation-schedule-runs`, `GET /operation-schedule-runs/{run_id}`, `GET/POST /farms/{farm_id}/resources` | schedule run = CP-SAT snapshot with named conflicts |
| Management plan | `POST /fields/{id}/management-plans`, `GET /fields/{id}/management-plans`, `GET /management-plans/{plan_id}`, `POST /management-plans/{plan_id}/feedback` | feedback is additive audit (farmer/agronomist) |

## 9. UI integration points

- New **Management** tab in `workspace.tsx` between Water and Soil (order: the
  workspace renders tab list from a config array — additive change).
- Sub-views (simple/expert aware): Overview · Cover Crop Studio · Soil Cover
  Timeline · Residue Ledger · Erosion & Conservation · Operations Calendar.
- Reuse: `badges.tsx` (add `EligibilityBadge`, `ProcessBadge`), field picker,
  SYNTHETIC banner, disclosure accordions, `max-h-96 overflow-y-auto` lists,
  sticky-footer workspace layout, existing offline PWA pattern for viewing cached
  plans and queueing operation completions (idempotent sync).

## 10. Backward-compatibility risks & mitigations

| Risk | Mitigation |
|---|---|
| New pack import breaks M5 consumers | new pack code `kp-m6c-*` is additive; import validator extended, not modified; existing packs unaffected; activation is per-pack |
| `soil_management_events` CHECK change would be breaking | **CHECK stays unchanged**; operation payloads extend `details` JSONB; M6C-specific structured data lives in new tables referencing events |
| Rotation/water readers assume no new event types | no new event types added |
| Migration 0008 must downgrade cleanly | additive-only tables + indexes; downgrade drops them; migration test extended (suite runs upgrade/downgrade) |
| Tenant leakage through new tables | every table carries organization/field FK path used by existing auth helper; integration tests mirror `test_auth_tenant_isolation.py` |
| CP-SAT scheduling regression into rotation optimizer | separate module `app/management/scheduling.py`; rotation optimizer untouched |
| Frontend tab growth on mobile | existing horizontal-scroll tab strip handles the 9th tab (verified pattern) |

## 11. Scientific references & applicability (Increment 1 register)

| # | Reference | Use in M6C | Applicability limits recorded |
|---|---|---|---|
| 1 | FAO — Conservation Agriculture principles & soil organic cover pages (fao.org/conservation-agriculture) | qualitative mechanisms for residue/cover practices; CA principle framing (minimum disturbance, permanent cover, species diversity) | qualitative; no numeric thresholds taken |
| 2 | USDA NRCS Cover Crop Conservation Practice Standard (Code 340, AC-340) | practice definition structure (purpose list, establishment/termination considerations); seeding/termination decision *dimensions* | US standard — structure borrowed, **values not globalized**; any numeric criterion stays region-scoped |
| 3 | USDA NRCS Cover Crop Termination technical sheet (2025) | termination decision dimensions (method, timing vs following crop, soil moisture context) | US guidance; no universal lead time encoded (red line) |
| 4 | USDA NRCS — Harvesting Crop Residue (2016) | residue removal trade-off framing (nutrient export, SOC, erosion exposure) | US agronomic context; qualitative use |
| 5 | USDA NRCS National Agronomy Manual (Water Management / water erosion chapters) | residue effects on runoff/erosion; water-erosion process descriptions | US manual; process taxonomy + qualitative mechanisms only |
| 6 | USDA ARS / NRCS RUSLE2 definitions & Handbook; FAO land-resources RUSLE page | RUSLE adapter scope control: A=R·K·LS·C·P, factor definitions, sheet/rill domain | model-specific; missing factors ⇒ not_evaluated; no US factor DB as defaults |
| 7 | ASABE 2024 review — Scheduling of Robotics or Machinery Operations in Agricultural Fields | scheduling model classes (precedence, resource-constrained project scheduling) for the CP-SAT formulation | methodology citation; no capacity numbers invented |
| 8 | (existing, reused) FAO-56 1998; FAO EcoCrop; Herridge et al. 2008; Saxton–Rawls 2006 | already in packs/code; cover-crop water reuses FAO-56 curves | unchanged |

Every encoded value in later increments cites a row of this register with source
version + applicable section; anything without a citable basis stays a declared gap.

## 12. Scope boundaries & deferred items (Increment 1)

**In scope (M6C):** practice knowledge registry; soil-cover timeline + metrics;
cover-crop candidate/plan engine (honest, evidence-gated); residue ledger with mass
balance; erosion screening + conditional RUSLE-family adapter; operations templates +
resources + CP-SAT scheduling with conflict explanations; aggregated management plan +
frontend workspace; cross-module integration (M5/M6A/M6B).

**Out of scope (deferred, documented in M6C_RESEARCH_BACKLOG.md):** DEM ingestion and
terrain analytics (no elevation data pipeline exists); remote-sensing fractional-cover
conversion models (no validated regional model); weather forecast provider integration
(forecasts stay "pending manual check"); wind-erosion quantitative models (WEQ/RWEQ —
out of M6C modeling scope; taxonomy slot reserved); economic optimization of machinery
fleet investment; pest/disease simulation; multi-field route optimization; external
field validation claims (none will be made).

## 13. Red-line compliance map (spec §19 → design decisions)

| Red line | Where enforced |
|---|---|
| No invented species parameters/windows | candidate engine reads only sourced pack rows; missing ⇒ `not_evaluated` (Increment 4 tests) |
| No universal termination lead times | termination window comes from sourced rows or farmer input; engine never synthesizes a day-count |
| No residue-to-grain ratios / harvest indices invented | residue production requires sourced coefficient or measured/farmer mass; else `missing` (Increment 5 tests) |
| Residue ≠ SOC sequestration | ledger records input only; SOC stays in M6B SOC engine (§6) |
| Cover crops not always water-positive | water dimension shows M6A-computed demand vs benefit with explicit trade-off status; missing Kc ⇒ `not_evaluated` (Increment 4) |
| NDVI ≠ % cover | observations store index values with evidence class; no conversion model exists ⇒ no conversion (§5.1) |
| RUSLE scope | process-declared outputs; factor-provenance gate; `screening_only` semantics (§7) |
| Climate normals ≠ forecast | no forecast pathway exists; weather checks stay `pending` (§3.9, Increment 7) |
| No assumed machinery/labor | resources are farmer-entered; absent ⇒ operations unscheduled with that reason |
| No silent removal of unscheduled work | schedule run persists every operation with a status + reason (Increment 7 property tests) |
| Missing evidence ≠ zero/false/safe/eligible | enforced per-engine + property tests across Increments 2–7 |
| No causal claims | association-only wording everywhere (M6B ledger convention carried into M6C) |
| No M7 | nothing outside §12 scope will be started |

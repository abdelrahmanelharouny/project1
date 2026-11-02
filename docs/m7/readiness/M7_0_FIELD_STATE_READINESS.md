# M7.0 — Unified Field State Model Readiness

**Inspection date:** 2026-11-01 · **Question:** can the existing data be assembled into a coherent, versioned Field State at a point/period in time — without duplicating data that already exists?
**Verdict up front:** **READY_WITH_LIMITATIONS for a v1 "assembled state" built from existing snapshots** (boundary version + feature-run refs + knowledge pack refs + water plan refs + rotation run refs), **PARTIAL for temporal alignment** (periods are comparable but recorded in heterogeneous fields), **BLOCKED for soil and management dimensions** (M6B/M6C absent). Nothing today *assembles* these pieces — the assembly layer does not exist; but every ingredient it needs, except two (below), is already produced and versioned somewhere.

---

## 1. Proposed conceptual structure vs. what exists

Proposed `FieldStateSnapshot` fields mapped to existing producers:

| Proposed field | Existing producer | Table/column | Reusable without duplication? | Gap |
|---|---|---|---|---|
| `field_id`, `farm_id` | `fields.id`, `fields.farm_id` | `models.py:151-176` | ✅ direct | — |
| `boundary_version` | `fields.boundary_version` + `field_boundary_versions` (append-only, `change_reason`) | `models.py:179-199` | ✅ direct | **No result ever records which boundary version it used** (F-01) |
| `state_reference_time` / `state_period_start/end` | *no single notion* — every domain records its own period | see §2 | ⚠️ derivable | snapshot must define its own semantics (F-02) |
| `timezone` / `calendar_context` | `farms.timezone` + `feature_runs.calendar_timezone/hemisphere` + `CALENDAR_ASSIGNMENT_RULE` | `models.py:472`, `features/calendar.py:23` | ✅ direct | — |
| `environmental_snapshot_id` | `feature_runs.id` (+ `source_selection`, engine/catalog versions, is_synthetic) | `models.py:455-511` | ✅ **strongest building block** | observation set not fully pinned; no run-level checksum (F-03) |
| `soil_assessment_snapshot_id` | **none** (M6B NOT_IMPLEMENTED). Raw inputs only: SoilGrids/farmer-CSV observations | — | ❌ | F-04 |
| `water_snapshot_id` | `water_plans.id` (checksummed, immutable-by-convention) | `models.py:1051-1097` | ✅ direct | plan must exist for the season+assignments; plans are not auto-generated (F-05) |
| `crop_history_snapshot_id` | `crop_history` rows (immutable, farmer-reported) | `models.py:911-936` | ✅ (as of-date filter) | no snapshot object; "history as of T" is derivable by query (sowing/harvest dates) |
| `rotation_snapshot_id` | `rotation_runs.id` + strategies checksummed | `models.py:958-1048` | ✅ direct | run is optimization-specific, not a general state (F-06) |
| `management_snapshot_id` | **none** (M6C NOT_IMPLEMENTED) | — | ❌ | F-07 |
| `knowledge_pack_versions` | `knowledge_pack_refs` idiom (`pack_id, code, version, status, checksum`) on rotation/water; `knowledge_packs.content` JSONB survives retirement | `knowledge/service.py:35-44` | ✅ **platform idiom to copy** | state must capture the *resolved* pack set at T, not "current active" (F-08) |
| `evidence_summary` / `quality_summary` | per-domain: passport readiness, feature quality enums, water ladder statuses, rotation evidence_coverage | — | ⚠️ derivable | needs a vocabulary union (§4) — no generic score |
| `snapshot_checksum` | idiom exists (`water_plans.checksum_sha256`, `rotation_strategies.checksum_sha256`, per-value feature checksums) | — | ✅ idiom to copy | — |
| `created_at`, `created_by` | `TimestampMixin`, `created_by` columns | — | ✅ | payloads should surface created_by (currently omitted everywhere — F-09) |

**Conclusion:** 10 of 14 conceptual fields can be satisfied **by reference** to existing tables; the two absent domains (soil, management) and the missing boundary-pinning are the only structural holes. No existing table needs to be duplicated.

## 2. Temporal consistency

Period semantics actually recorded per domain:

| Domain | Time field(s) | Semantics | Time support |
|---|---|---|---|
| Observations | `observed_at`, `period_start/end`, `time_support` (8 values) | instant vs aggregated, UTC-enforced | explicit ✅ |
| Feature values | `period_start/end`, `period_label`, aggregation level, `baseline_reference` (window years) | daily/monthly/seasonal/crop_season | explicit ✅ |
| Crop history | `sowing_date`, `harvest_date`, `season_label` | farmer-reported events | explicit ✅ |
| Crop calendar windows | MM-DD strings + hemisphere | climatological windows (year-wrapping) | month-day only, no year ✅ by design |
| Rotation runs | `seasons` JSONB (label/start/end) | planning seasons | explicit ✅ |
| Water plans | `seasons` JSONB (same idiom) | planning seasons | explicit ✅ |
| Boundary versions | `created_at` only | valid-from implicit (append order) | ⚠️ validity period not first-class (F-01 related) |
| Knowledge traits | `valid_from`/`valid_to` dates | temporal validity on knowledge rows | explicit ✅ |
| SoilGrids / farmer CSV | observation timestamps (`instant`/daily) | as ingested | explicit ✅ |

**Can different domains represent the same planning period?** Mostly yes: the `seasons` idiom (label + start/end dates) is shared by rotation runs and water plans; feature runs take explicit `crop_seasons[{label,start_date,end_date}]`; crop history has real dates. A state assembled for "season summer_2026" can therefore quote each domain against the same interval — **but nothing enforces that the quoted artifacts actually cover it** (a feature run might cover 2023 while the state targets 2026; the water plan might have been built for different crop assignments). Period-compatibility checking is an assembly-layer responsibility that does not exist yet (F-02).

**Time concepts the spec requires vs. presence today:**

| Required concept | Present? | Evidence |
|---|---|---|
| Observation time | ✅ | `observations.observed_at` (UTC enforced) |
| Measurement time | ✅ (partial) | soil vars carry `observed_at` + `time_support=instant`; no separate lab-result date (no M6B) |
| Calculation time | ✅ | `feature_runs.completed_at`, run `created_at` everywhere (except water plans have only `created_at` — no started/completed) |
| Validity period | ⚠️ | knowledge rows only; boundary versions implicit |
| Forecast issue time | ❌ | no forecast provider; nothing to record |
| Scenario evaluation time | ❌ | no scenario concept |

## 3. Spatial consistency

| Concern | Status | Evidence |
|---|---|---|
| Boundary versions | append-only history exists; **unreferenced by results** | F-01 |
| Environmental grid coverage | products record `spatial_resolution_m` (ERA5-Land ~11 km, ERA5 ~28 km, SoilGrids 250 m); support types `grid_cell`, `field_intersection`, `polygon_average`, `point` | per-provider seeds; `observations.spatial_support_type` |
| Soil sampling locations | SoilGrids = field centroid cell (or all-touched flags for sub-grid fields); farmer CSV = `point`; no geo-located sampling events | soilgrids provider; csv_service |
| Soil profile support | none (no layers; SoilGrids slice depth 0-5 cm only) | soilgrids provider DEPTH |
| Management zones | none | F-07 domain |
| Raster resolution & aggregation method | CHIRPS field-mean: fractional pixel-area weighting v2 (`extractor.py`, golden-tested); SoilGrids: sub-cell all-touched fallback flagged; aggregation method recorded in metadata | F-13 fixed in deepening |
| False-precision risk | honest naming exists ("a 0-5 cm model prediction is not a lab measurement", PTF opt-in disclosure, grid_cell support labels) | candidates.py:505-540; water/service.py:270-277 |

**Safe contribution to one field state:** each domain already carries its own spatial-support + resolution metadata, so a state can express spatial precision per dimension instead of implying uniform precision. The missing piece is again boundary-version pinning: the *geometry against which* rasters/polygons were extracted is only the current boundary at ingestion time (INT-12).

## 4. Completeness & partial-state vocabulary

Existing per-domain vocabularies that a Field State can union **without inventing a generic score**:

| Proposed dimension | Existing carrier |
|---|---|
| Available | `quality_status='valid'` (features), passport AVAILABLE, ladder `evaluated` |
| Missing | `quality_status='missing'`, passport missing-variable reasons, water `missing_evidence` |
| Insufficient coverage | `insufficient_coverage` (features), ≥90% month coverage rule (climate bridge), baseline <5 years → `not_evaluated` |
| Stale | **no direct carrier** — freshness only as display info in passport; a state would need its own staleness policy (F-10) |
| Not applicable | ladder `not_supplied`/`not_applicable` statuses; allocation `not_applicable` (rotation constraints) |
| Not evaluated | `not_evaluated` (+reasons) on feature runs, rotation, water; "(not evaluated)" rendering |
| Conflicting | knowledge import conflict rejection (import-time only); **no runtime conflict dimension** (F-11) |
| Synthetic | `is_synthetic` end-to-end + SYNTHETIC banner |
| Farmer-reported | `evidence_class='farmer_reported_record'`, `source='farmer'` |
| Expert-validated | `validation_status` (`locally_validated`/`confirmed_regional`) on knowledge; `agronomist_reviews` table (workflow barely used) |

The union is **expressible**; the spec's warning is correct — these are orthogonal dimensions and must remain per-dimension, not collapsed into one score. Today nothing aggregates them; the passport is the closest existing analog (per-variable, per-source) and should be the model for a state-level evidence summary.

## 5. Findings register

| ID | Severity | Domain | Affected code/schema | Current behavior | Expected (for M7) | Evidence | Impact on M7 | Blocks M7? |
|---|---|---|---|---|---|---|---|---|
| F-01 | **High** | Farm/Field ↔ all domains | no column anywhere referencing `field_boundary_versions` | results reference `field_id` only; boundary history dangling | Field State (and ideally ingestion/feature runs) record `boundary_version` used | `M7_0_CROSS_DOMAIN_MAP.md` INT-12; grep boundary_version | historical states cannot be geometrically reconstructed with certainty; silent boundary change confounds comparisons | **No** (state can record current version going forward) but degrades historical states |
| F-02 | High | Assembly (new) | — | periods recorded per-domain; no compatibility check | state assembly validates period coverage/compatibility and records mismatches | §2 table | wrong-period assembly would silently mix 2023 climatology with 2026 plans | **No** (implementable in M7.1) |
| F-03 | High | Features | `feature_runs` (no run-level checksum; obs ids capped 400 in `engine.py:34`) | bit-reproducibility holds only while observation set static | environmental snapshot pinning (id set hash or full obs reference manifest) | INT-03 | scenario replays / state re-assembly not bit-stable under new ingestions | **No** (workaround: pin by run id + document) but weakens Level-2 twin claims |
| F-04 | High | Soil (M6B) | — | no soil assessment tables | soil dimension of state must degrade honestly to raw observations + `NOT_IMPLEMENTED` | §4.6 of as-built | "soil_assessment_snapshot_id" has no producer | **Conditional** — blocks *soil-rich* field states, not the core state |
| F-05 | Medium | Water | `water_plans` (plans are per explicit request) | no auto-plan for a season+assignment | state assembly may need "plan for these assignments exists?" query + triggered calculation | service.py:327-605 | state's water dimension may be legitimately absent — must be expressed, not fabricated | No |
| F-06 | Medium | Rotation | `rotation_runs` are optimization experiments | not a general state object | state should reference run + chosen strategy id explicitly | INT-10 | strategy-level state linkage undefined | No |
| F-07 | High | Management (M6C) | — | no tables | management dimension must be `NOT_IMPLEMENTED` until M6C | §4.7 as-built | management scenario axis impossible | **Conditional** — blocks management scenarios, not core state |
| F-08 | Medium | Knowledge | `knowledge_pack_refs` idiom exists but "active set at T" is only reconstructable for runs that stored it | state must store resolved pack set + checksums (copy idiom) | pack refs snapshot | knowledge/service.py:35-44 | straightforward to copy | No |
| F-09 | Low | All runs | `created_by` persisted, never surfaced in payloads | audit ambiguity in UI/API | surface in run payloads (4 sites) | run-contract table (API/DB doc) | minor | No |
| F-10 | Medium | Assembly (new) | — | no staleness policy anywhere | state needs explicit staleness semantics per dimension (e.g., SoilGrids static 2020) | §4 | stale data could read as current | No (design decision in M7.1) |
| F-11 | Medium | Knowledge | conflicts rejected at import only | runtime conflict detection absent | state may need "conflicting" dimension (e.g., two packs both active with different trait values — F-9 determinism picks winner silently) | knowledge/service.py:66-80 | silently resolved conflicts are invisible to a state consumer | No |

## 6. Readiness verdict

| Capability | Status |
|---|---|
| Assembling a v1 Field State from existing artifacts (by reference, no duplication) | **READY_WITH_LIMITATIONS** (F-01/F-02/F-03 must be addressed in the design; soil & management dimensions degrade honestly) |
| Reusing existing tables/snapshots without duplication | **READY** (10/14 fields map to existing producers) |
| Temporal alignment machinery | **PARTIAL** (semantics exist everywhere; compatibility validation does not) |
| Spatial consistency | **PARTIAL** (per-dimension support metadata exists; boundary pinning missing) |
| Completeness vocabulary | **READY** (10-dimension union already carried by existing enums; no generic score needed) |
| Soil dimension | **BLOCKED** on M6B (or honest NOT_IMPLEMENTED dimension) |
| Management dimension | **BLOCKED** on M6C (or honest NOT_IMPLEMENTED dimension) |

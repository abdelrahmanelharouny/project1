# M7.0 — Scenario Engine Readiness

**Inspection date:** 2026-11-01 · **Question:** can the existing architecture support multiple, honestly-labelled scenario types without mutating adopted plans, ledgers, or historical results?
**Verdict up front:** **READY_WITH_LIMITATIONS for historical-observed, historical-perturbation, user-defined stress, and management-deferred scenarios built on the existing immutable-run idiom; PARTIAL for climate projections and forecasts (no sourced data pipeline exists — by design); BLOCKED for management scenarios until M6C exists.** No scenario concept exists in code today (`rg -i "scenario" app/` → zero functional matches) — this is greenfield *orchestration*, but it can reuse proven contracts: versioned engine runs, checksums, idempotency keys, pack refs, evidence classes, and honesty vocabularies.

---

## 1. Scenario taxonomy vs. existing data foundations

| Scenario type (spec §6.1) | Data foundation present? | Engine foundation present? | Evidence-class treatment needed | Verdict |
|---|---|---|---|---|
| **Historical observed** | ✅ observations + feature runs (real products: ERA5(-Land), CHIRPS final, farmer CSV) | ✅ feature engine + water + rotation already consume these | `direct/station/satellite/reanalysis` classes already distinguish sources | **READY_WITH_LIMITATIONS** (coverage gaps are real & must gate) |
| **Historical perturbation** | ✅ same base data; monthly/daily values accessible via feature values or observations | ⚠️ transforms must be injected **upstream of** water/rotation engines; today engines read the feature run's climatology — a perturbation layer would either (a) create a synthetic-derived feature run (bad: synthetic flag would lie), or (b) an explicit perturbation context passed to engines (new, clean) | must NOT reuse `synthetic_test_data`; needs a new evidence class or explicit `perturbation` provenance | **READY_WITH_LIMITATIONS** with design decision F-12 |
| **User-defined stress** | ✅ user supplies deltas/allocations (e.g. lower `water_allocation_m3`) | ✅ water allocation constraint + ladder already handle arbitrary allocations; `unknown ≠ unlimited` semantics exist | must be labelled **assumptions**, never observations — platform already labels farmer-supplied economics "never invented" | **READY** (contract-wise) |
| **Climate projection** | ❌ no projection dataset, no ingestion path (open_meteo archive ≠ projections; CHIRPS is observational) | ❌ no bias-adjustment/downscaling pipeline | would need a sourced product row + new evidence class + processing documentation | **NOT_IMPLEMENTED** (deliberately) |
| **Weather forecast** | ❌ no forecast provider; code only *disclaims* forecasts ("historical proxy, NOT a forecast" — `water/service.py:114`, `rotation/service.py:264`) | ❌ no issue-time / horizon model | needs provider + `forecast_issue_time` + horizon metadata | **NOT_IMPLEMENTED** |
| **Management** | ❌ M6C not implemented — no practices, operations, scheduler, or ledger | ❌ no engine to re-evaluate | — | **BLOCKED** on M6C |

The taxonomy requirement "these scenario types must never be presented as equivalent evidence" maps directly onto the platform's existing evidence-class discipline — the mechanism to honour it already exists (8-value `EvidenceClass`, per-value provenance, SYNTHETIC banner). New scenario types must add their own classes/labels rather than reuse `synthetic_test_data`.

## 2. Scenario contract investigation (proposed schema)

Field-by-field feasibility against existing contracts:

| Proposed field | Existing support | Notes |
|---|---|---|
| `id`, `field_id` | trivial | tenant scoping via field→farm→membership (guard idiom) |
| `scenario_type` | new enum required | the 6 types of §1; never interchangeable evidence |
| `name`, `description` | trivial | — |
| `parent_state_snapshot_id` | **depends on M7.1 Field State existing** | this is the strongest argument for sequencing M7.1 → M7.2; alternatively v1 scenarios can parent directly on `feature_run_ids` + `boundary_version` + pack refs (the state's ingredients) |
| `baseline_reference` | run-id references (`feature_run_ids` idiom) | "baseline = run X under no adjustment" |
| `adjustment_configuration` | JSONB idiom everywhere (`request_parameters`, `methods`, `source_selection`) | must be checksummed, structured, validated (negative precipitation must be rejected at config level, §3) |
| `validity_period` | seasons idiom (label/start/end) | shared by rotation/water runs |
| `spatial_scope` | field_id + boundary_version (**after F-01 fix**) | per-dimension spatial support already recorded |
| `source_references` | `knowledge_pack_refs` + dataset product refs idiom | plus adjustment provenance |
| `model_versions` | per-engine version strings already exist (`water-engine-1.0.0`, `rotation-engine-1.0.0`, `feature-engine-1.0.0`, `featurespec-…`) | scenario adds which engines it invokes |
| `uncertainty_metadata` | partial: observation `uncertainty_value/type`, SoilGrids PI, feature SE-of-mean | scenario-level uncertainty (ensemble spread) has no carrier yet — needed only for projection ensembles |
| `status` | run-status idiom (5-state) | align with the run-contract harmonization finding (API/DB doc §3) |
| `checksum` | `_plan_snapshot_checksum` / `_solution_checksum` / per-value checksum idiom | scenario checksum = hash(type, config, parent refs, model versions) |
| `created_by/at` | `created_by` columns exist | surface in payload (F-09) |

**Conclusion:** the proposed schema is supportable **without new abstractions** beyond one scenario table + FK-free refs, by copying three existing idioms: JSONB configs + checksums, field-scoped idempotency keys, and by-value pack/run refs.

**Immutability precedent:** reruns of water plans are already implemented as immutable new rows with checksums and field-scoped idempotent replay (`water/service.py:335-344,423-474,608-626`; test `test_plan_reproducibility_same_inputs_same_checksum` asserts *two distinct persisted rows*). Scenario evaluation can adopt this exact pattern. Caveat to fix or constrain: `DELETE /water-plans/{id}` exists (F-13) — a scenario referencing a deleted plan would dangle; scenario tables should RESTRICT-delete or soft-archive referenced runs.

## 3. Environmental perturbation semantics

What the current data model can safely support:

| Transformation | Physical-consistency handling possible today? | Evidence / constraints |
|---|---|---|
| Temperature Δ (additive, °C) | ✅ daily & monthly values exist (`air_temperature_mean/min/max`); unit is explicit (degC); ET0 **cannot** be derived locally (no radiation/humidity — ADR: provider-ET0 only, backlog W-6) → temperature-perturbed scenarios must **not** recompute ET0 without a sourced method | variables.py; ET0 refusal precedent |
| Precipitation Δ | ✅ but must clamp ≥ 0 and preserve aggregation semantics; **monthly-uniform scaling changes seasonality/event structure** — daily-series perturbations are defensible, monthly scalars are coarse approximations and must be labelled as such | daily `precipitation`; CHIRPS daily/pentad/monthly; feature engine monthly aggregation |
| Irrigation allocation change | ✅ first-class today: `water_allocation_m3` on runs/plans; constraint names infeasibility; unknown ≠ unlimited | optimizer.py:363-406; planner.py:362-393 |
| Seasonal timing shift | ⚠️ crop calendar windows are MM-DD climatological (`reference_synthesized`); shifting seasons is expressible (season start/end are inputs) but window evidence stays unchanged → shifts must be flagged as user assumptions vs unvalidated calendar | crop_calendar_windows; seed pack honesty |
| Soil-water initial condition | ✅ M6A root-zone balance starts from a defined initial Dr (sowing) — a scenario can set initial Dr/TAW inputs; PTF domain enforcement still applies | water/soil.py:196-247 |
| What a perturbation must never do | silently become a forecast/projection; flip evidence class to `synthetic_test_data` (that class means *test fixtures*); blend products; zero-fill missing months | F-07 refusal precedent (`season_etc_mm` refuses missing month) |

**Key design fork (F-12):** perturbed sequences need a home. Options: (a) virtual — perturbation context travels with the scenario and engines accept it as an input contract (no new observations; cleanest provenance); (b) materialized derived observations (dangerous: pollutes the observation store with derived rows). Option (a) is recommended and consistent with the platform's refusal to blend or fabricate evidence; it requires extending water/rotation input contracts to accept an explicit climate-context override — a contained, versionable engine-contract change.

## 4. Missing scenario inputs — behavior audit

| Missing input | Current system behavior (verified) | Required scenario behavior |
|---|---|---|
| Forecast provider unavailable | no provider exists; forecasts only appear as disclaimers | scenario type unavailable; must not fabricate |
| DEM/terrain missing | no DEM pipeline anywhere; FAO-33 slope condition disclosed as assumption | terrain-dependent analyses remain not-implemented; scenario must not claim them |
| Crop response thresholds missing | heat/drought scores deliberately absent ("no defensible source"); hot-days index labelled generic, "NOT crop-specific" | crop-response dimensions stay `not_evaluated` with reasons |
| Soil hydraulic measurements missing | PTF opt-in with domain enforcement + disclosure; farmer measurements precedence; PTF out-of-domain → FAO-33 fallback + warning | scenario inherits honest fallback chain; must not present PTF as measurement |
| Kc values incomplete | incomplete anchor sets rejected at import; faba_bean plans honestly unevaluated; "never guessed" reasons | scenario for Kc-less crops = `not_evaluated`, never interpolated |
| Historical coverage insufficient | baselines require ≥5 distinct years (`BASELINE_MIN_YEARS`); climate bridge requires ≥90% month coverage else unevaluated; missing month refuses ETc estimate (F-07) | scenario generation must refuse (not degrade silently) when its baseline window is insufficient |
| No regional crop calendar validated | all 13 windows `reference_synthesized`; zero `confirmed_regional`; hard rules "bind on nothing" | scenario outputs must repeat the local-validation disclaimer (explain.py already emits `local_expert_validation_required`) |

The general rule is already institutionalized: **generation must not create evidence where no evidence exists.** Every engine in the chain has refusal paths with named reasons; a scenario layer that reuses the engines inherits these refusals — the audit found no code path that silently zero-fills or interpolates across the listed gaps.

## 5. Findings register

| ID | Severity | Domain | Affected code/schema | Current behavior | Expected for M7 | Evidence | Impact | Blocks M7? |
|---|---|---|---|---|---|---|---|---|
| F-12 | High | Scenario↔Engines | engine input contracts | engines read climatology from a feature run | engines need an explicit, versioned climate-context override (virtual perturbation) | §3 fork | without it, perturbation would have to pollute the observation store or hack feature runs | **No** (M7.3 design task) |
| F-13 | Medium | Water | `DELETE /water-plans/{id}` | snapshots deletable | restrict/archive deletion for plans referenced by scenarios/states | api/v1/water.py:155-167 | dangling references possible | No |
| F-14 | Medium | Scenario | — | no scenario evidence classes | new evidence classes (e.g. `perturbed_sequence`, `projection_ensemble`, `forecast`) with "never equivalent to observed" semantics | §1 | labels are the core honesty requirement | No |
| F-15 | Medium | Data platform | `dataset_products` | only observational products registered | projection/forecast products would need issue-time & horizon metadata extensions | §1 | future work, gated on data availability | No |
| F-16 | Low | Rotation | `_pick_evidence_run` default | latest-succeeded run silently chosen | scenario should always pin explicit run ids (already supported via request param) | rotation/service.py:108-124 | avoid silent baseline drift | No |
| F-17 | Low | All runs | run payload | `created_by` not surfaced | scenario provenance needs actor visibility | API/DB doc §2 | minor | No |

## 6. Readiness verdict

| Scenario capability | Status |
|---|---|
| Immutable scenario definitions (contract) | **READY_WITH_LIMITATIONS** (all idioms exist; depends on M7.1 state or its ingredients) |
| Historical observed scenario | **READY_WITH_LIMITATIONS** (real-data coverage is user-dependent; refusals already honest) |
| Historical perturbation scenario | **READY_WITH_LIMITATIONS** (needs F-12 engine-contract decision; physical-consistency rules expressible today) |
| User-defined stress scenario | **READY** (allocation + assumption-labelling machinery exists) |
| Climate projection scenario | **NOT_IMPLEMENTED** (no sourced data; no pipeline; correctly so) |
| Weather forecast scenario | **NOT_IMPLEMENTED** (no provider; issue-time/horizon model missing) |
| Management scenario | **BLOCKED** on M6C |
| "Never present scenario types as equivalent evidence" | **READY** (evidence-class discipline exists platform-wide and extends naturally) |

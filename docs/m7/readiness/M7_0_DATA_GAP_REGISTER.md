# M7.0 — Data & Integration Gap Register

**Inspection date:** 2026-11-01 · **Method:** every gap below was verified against the repository (searches + code reads), not copied from prior claims. Classification: **Blocking / Non-blocking / Conditional / Future optional enhancement** — relative to the M7 increments (M7.1–M7.8) evaluated in `M7_0_IMPLEMENTATION_SEQUENCE.md`.

---

## 1. The eight previously documented limitations — re-verified

| # | Gap | Repository evidence | Classification | M7 components that can operate WITHOUT it | Capabilities that remain unavailable |
|---|---|---|---|---|---|
| G-1 | **No forecast provider** | `rg -i "forecast" app/` → only disclaimers ("historical proxy, NOT a forecast" — `water/service.py:114`, `rotation/service.py:264`) | **Non-blocking** for M7.1–M7.7 · **Conditional** for forecast scenarios | Field State assembly; scenario definitions; historical perturbation & user-stress scenarios; multi-scenario rotation evaluation; sensitivity analysis; twin timeline | Weather-forecast scenario type stays NOT_IMPLEMENTED; no operational nowcasting |
| G-2 | **No DEM/terrain pipeline** | no elevation/terrain code (only FAO-33 slope-condition *text* disclosure and p-adjustment slope constant) | **Non-blocking** for M7.1–M7.7 · **Conditional** for terrain-dependent environmental scenarios | All core M7 increments; FAO-33 Pe already works with its slope assumption disclosed | Terrain-informed screening (runoff/erosion beyond duration proxy); high-resolution orographic precip adjustments |
| G-3 | **No fully sourced regional cover-crop parameter packs** | seed pack has `cover_crop_suitability` rules (reference status) + `is_cover_crop_capable` flags; zero `confirmed_regional` rows by design (`test_seed_pack_has_no_confirmed_regional_rules`) | **Non-blocking** (honest unevaluated states exist) · **Conditional** on agronomic validation program | Rotation evaluation continues with reference-status rules labelled; management scenario design (M6C-dependent anyway) | Confirmed hard enforcement of cover-crop rules; region-quantified cover-crop benefits |
| G-4 | **No globally validated crop calendars** | all 13 calendar windows `evidence_class="reference_synthesized"` (`seed_pack_v1.py:69-91`) | **Non-blocking** (honest labelling + local-expert-validation blocks already emitted) | All M7 increments — calendar windows are already used with the disclaimer | Hard calendar-based exclusions; validated planting-window scenario shifts |
| G-5 | **No confirmed regional agronomic rules** | 6 rotation rules, all `validation_status="reference"`; hard enforcement "binds on nothing" (documented + tested) | **Non-blocking** by explicit design decision | Rotation/scenario evaluation (rules remain conditional, explanations show "local expert validation required") | Named hard rotation-break enforcement in production deployments |
| G-6 | **Incomplete real-farm soil & nutrient observations** | no M6B tables; only SoilGrids 0–5 cm predictions + optional farmer CSV soil vars; no sampling events/lab methods/layering | **Blocking** for soil-health scenario dimensions & twin soil lane · **Non-blocking** for M7.1 core state (renders as NOT_IMPLEMENTED dimension) | Field State (soil dimension degraded honestly); water PTF path (PTF/farmer precedence exists); rotation soil_health criterion (trait-based) | Soil assessment snapshots; nutrient budgets; soil-health scenario evaluation; L1 twin soil history |
| G-7 | **Incomplete operation durations & resource capacities** | M6C absent — no operations/resources/scheduler at all | **Blocking** for management scenarios (M6C prerequisite) | Everything except management scenarios | Operation scheduling realism; resource-constrained planning |
| G-8 | **No demonstrated real-farm calibration dataset** | no calibration code/tables anywhere; engines are uncalibrated reference methods (disclosed) | **Non-blocking for M7** · **Blocking for L4 twin claims** | All M7 increments — *provided* no predictive/calibrated claims are made | Calibrated predictive twin (L4); validation of model behavior against outcomes |

**Cross-cutting rule confirmed by evidence:** absence of forecasts (G-1) does **not** prevent historical sensitivity analysis (historical perturbations + user stress scenarios are fully supported by existing engines); absence of DEM (G-2) does **not** prevent environmental scenario functionality (all current environmental transforms are DEM-independent).

## 2. Additional data opportunities (evaluated, not implemented)

Per the Master rule 8 precedent (NASA connectors deliberately out of scope), the following are recorded as future adapters, with the architectural hooks that already exist for them:

| Opportunity | Would feed | Existing hook it would plug into | Note |
|---|---|---|---|
| NASA Earth observations (e.g., SMAP soil moisture, GPM precipitation) | observations via a new provider | `EnvironmentalDataProvider` protocol + registry + product rows with license/attribution | **outside current implementation scope** (unchanged decision) |
| DEM products (e.g., Copernicus DEM, SRTM) | terrain features | feature-definition catalog (versioned, new definitions would be additive); FAO-33 slope condition could become measured | new provider + feature definitions; not started |
| Climate projection ensembles (e.g., CMIP6 downscaled) | projection scenarios | dataset_products + new evidence class + F-15 issue/horizon metadata; robust-optimization "expected performance" becomes possible only here | requires license review + bias-adjustment methodology doc |
| Weather forecast providers | forecast scenarios | same as above + `forecast_issue_time`/horizon fields | provider contract tests already define the quality bar (UTC, missing≠zero) |
| Local weather stations | highest-evidence-class observations (`station_observation`) | farmer CSV import today; a station adapter would fit the provider protocol | would upgrade evidence class for ET0 inputs |
| Soil sensors / soil lab imports | M6B soil measurements | no M6B schema yet — blocked until M6B defines it | sequencing dependency |
| Field-level management records | M6C operations | none yet — M6C absent | sequencing dependency |

## 3. Infrastructure gaps (verified during this inspection)

| Gap | Evidence | Classification |
|---|---|---|
| Inline job execution only (no queue/worker) | all four run types execute inside the request (`ingestion/service.py:75-111` docstring says a worker "can take over without contract changes") | **Non-blocking for M7.1–M7.6**; **Conditional for M7.5** if multi-scenario runs exceed interactive latency; a design constraint for UX (API/DB doc) |
| No cancellation/progress % | `cancelled` status unreachable; only record counters | **Non-blocking** for current increments; UX feedback debt (F-29) |
| Sandbox-only postgres (user-space conda cluster) | restored during this inspection per repo scripts | Non-blocking (documented deployment path: `docs/architecture/deployment.md`) |
| No production build verification in sandbox | `next build` not runnable under single-port dev constraint | Non-blocking (lint + dev-mode browser verification used) |

## 4. Gap → M7 increment impact matrix

| Increment | G-1 forecast | G-2 DEM | G-3 cover-crop packs | G-4 calendars | G-5 rules | G-6 soil obs | G-7 ops data | G-8 calibration |
|---|---|---|---|---|---|---|---|---|
| M7.1 Field State | ok | ok | ok | ok | ok | degraded-dimension | n/a | ok |
| M7.2 Scenario domain | ok | ok | ok | ok | ok | ok | n/a | ok |
| M7.3 Historical/stress transforms | ok | ok | ok | ok | ok | ok | n/a | ok |
| M7.4 Sensitivity & uncertainty | ok | ok | ok | ok | ok | ok | n/a | ok |
| M7.5 Multi-scenario rotation | ok | ok | ok | ok | ok | ok | n/a | ok |
| M7.6 Robustness & decision stability | ok | ok | ok | ok | ok | ok | n/a | ok |
| M7.7 Twin timeline & visualization | ok | ok | ok | ok | ok | **soil lane empty (M6B)** | **management lane empty (M6C)** | ok (no predictive claims) |
| M7.8 External projections & forecasts | **requires it** | partial | ok | ok | ok | ok | n/a | requires real data |

No M7.1–M7.6 increment is blocked by any of the eight gaps — provided the platform's existing honesty vocabulary continues to degrade missing inputs visibly rather than silently.

# M7.0 — Robust Optimization Readiness

**Inspection date:** 2026-11-01 · **Question:** can the existing rotation optimizer be evaluated across multiple scenarios — without modifying its implementation during this inspection?
**Verdict up front:** **READY_WITH_LIMITATIONS for post-hoc multi-scenario evaluation** (the constraint validators and criteria evaluators are deliberately solver-free pure functions and can score any assignment against any scenario evidence set), **PARTIAL for true robust optimization formulations** (no scenario-aware solver model exists; none is needed for v1), **READY for determinism/reproducibility prerequisites**. No implementation was changed; this document only records what exists and what future approaches would require.

---

## 1. As-built optimizer facts (evidence)

| Aspect | Current state | Evidence |
|---|---|---|
| Solver | OR-Tools CP-SAT via `app/rotation/optimizer.py` (only module importing ortools) | optimizer.py:25 |
| Determinism | `num_search_workers=1`, `random_seed=problem.seed` (default 0), `max_time_in_seconds=10.0`; identical inputs → identical assignment proven by unit + integration tests | optimizer.py:451-454; `test_rotation_core.py:306-314`; `test_rotation_runs.py:242-253` |
| Hard constraints | exactly-one per season; admissible pool (eligible/conditionally_eligible); pairwise + history-boundary rotation breaks (confirmed_regional only, deepest-lookback); per-season water allocation in exact litres (NIR basis, ETc-conservative fallback disclosed) | constraints.py:36-261; optimizer.py:286-406 |
| Named infeasibility | every constraint registered as CP-SAT assumption → `SufficientAssumptionsForInfeasibility()` → labeled conflicts; only `INFEASIBLE` is ever reported infeasible; MODEL_INVALID/UNKNOWN never repainted | optimizer.py:292-302,456-500; service.py:591-605,668-694 |
| Objective | solver-steering score from per-crop scores + family alternation (integer-scaled); **reported criteria always recomputed post-hoc** | optimizer.py:12-14,127-244,424-443; service.py:609-651 |
| Soft criteria | 7 criteria, each `evaluable` flag + `missing_evidence`, never zero-filled: water_requirement_mm, soil_health_index, economic_margin_index (farmer-only), crop_family_diversity, climate_resilience_index, erosion_reduction_index, cover_crop_opportunity | objectives.py:63-411 |
| Normalization & Pareto | min-max within the run's strategy set over evaluable criteria; dominance over the **shared** evaluable set; non-comparable pairs recorded; <2 values or span≤1e-12 → neutral 0.5 | objectives.py:420-592 |
| Crop eligibility | per-season candidate statuses (eligible/conditionally_eligible/excluded/unevaluated) with cited reasons; admissible = eligible+conditional; water-unevaluable crops held OUT of allocation runs (never partial compliance) | candidates.py:237-655; constraints.py:86-100 |
| Missing criterion semantics | skipped weights reported ("criterion not evaluable from available evidence: …"); weights renormalized over evaluable set | objectives.py:495-524 |
| Water integration | NIR coefficients shared with the water planner arithmetic (cannot drift); allocation shortfall/deficit windows computed in water plans | optimizer.py:363-406; candidates.py:115-117; planner.py:455-467 |
| Soil integration | soil pH eligibility (evidence-class-labelled SoilGrids); soil_health_index criterion (legume/cover/root-depth/N-fixation traits). **No M6B soil-health engine.** | candidates.py:505-540; objectives.py:100-164 |
| Management integration | **none** (M6C absent); only proxies: cover-crop capability flag + opportunity criterion + erosion duration proxy | objectives.py:300-380 |
| Reproducibility contracts | field-scoped idempotency keys; `RotationProblem.checksum()` (candidate **codes**, not assessment values); per-strategy checksums | problem.py:271-288; service.py:429-443 |

## 2. The decisive architectural fact for M7

`app/rotation/constraints.py` declares every hard constraint **twice by design**: as solver-free validator functions (`check_one_crop_per_season`, `check_candidate_admissibility`, `check_rotation_breaks`, `check_water_allocation`) and as CP-SAT constraints kept 1:1 (module docstring: "declared once, checked solver-free; CP-SAT mirrors 1:1"). Likewise `objectives.py` criteria are pure post-hoc functions of (assignment, evidence), and `candidates.assess_crop` is deterministic given inputs.

**Consequence:** a future multi-scenario evaluator can, without touching the optimizer, take any fixed strategy assignment and check it against per-scenario inputs (allocation, NIR coefficients, candidate pools, rule sets) using the existing validators, then recompute all criteria per scenario using the existing evaluators. Scenario feasibility, worst-case, regret, feasibility-robustness fractions, and sensitivity analysis are all **post-hoc computable today**. What does *not* exist is a solver model that optimizes jointly across scenarios (true robust optimization) — that would be new solver work, not required for first versions.

## 3. Future approaches — requirements assessment

### 3.1 Scenario feasibility ("does strategy S remain feasible under scenarios {A,B,C}?")
- **Data requirements:** per-scenario water allocations + per-scenario climate evidence (→ water plans per scenario) + per-scenario candidate pools (climate shifts could exclude crops) + unchanged rule set.
- **Mathematical assumptions:** scenarios are explicit, discrete, non-probabilistic; feasibility means all hard constraints satisfied in each scenario; scenario set is *not* a probability space.
- **Computational:** one validator pass per (strategy × season × scenario) — trivially cheap; water evidence per scenario requires one water-plan computation per scenario (inline, seconds).
- **Interpretability:** high — "holds in 4 of 5 defined scenarios, fails scenario B on water_allocation for maize 2026 with named deficit."
- **Limitations:** feasibility under user-defined scenarios is conditional on the honesty of those scenarios (must stay assumption-labelled).
- **Reuse:** **full** — validators + water planner reused as-is.

### 3.2 Expected performance
- **Data requirements:** a *justified* probability model over scenarios (sourced projection ensemble with documented likelihoods, or statistically validated historical resampling). **Neither exists**; no ensemble data is ingested, and the platform has no probability machinery.
- **Mathematical assumptions:** probabilities must come from a sourced, citable model — the platform's honesty rules (never invent evidence) forbid ad-hoc equal weights presented as probabilities.
- **Computational:** N scenario evaluations + expectation.
- **Interpretability:** deceptively high; scientifically dangerous without real probabilities.
- **Reuse:** evaluation side reusable; **probability side missing by design**.
- Verdict: **NOT READY — blocked on sourced ensemble data** (matches the sequencing proposal that places external climate projections last, M7.8).

### 3.3 Worst-case performance (min-max)
- **Data requirements:** a documented scenario bound set (e.g., allocations [P50, P90-dry]; ΔT ∈ [0, +2 °C]); bounds must be user/sourced, explicit, and labelled.
- **Mathematical assumptions:** bounded uncertainty; the worst case within bounds is meaningful; criteria comparable across scenarios (normalization must then be defined across the union set, not per-run set — an extension to `normalize_within_set`).
- **Computational:** per-scenario evaluation then max (post-hoc) — cheap; a solver-in-the-loop min-max (optimize the worst case) would need a new CP-SAT model per scenario inside an outer loop (feasible: 10 s budget × N scenarios, but needs engineering).
- **Interpretability:** high when bounds are documented ("worst observed criterion across the declared bounds").
- **Limitations:** worst case over *user-declared* bounds is conditional, not stochastic.
- **Reuse:** post-hoc version fully reusable; solver-in-loop version reuses the model builder (`build_model` internals) but needs new orchestration.

### 3.4 Regret-based evaluation
- **Data requirements:** same as scenario feasibility + a defined strategy set to optimize per scenario.
- **Mathematical assumptions:** regret = criterion(best strategy in scenario s) − criterion(strategy S in s); requires per-scenario re-optimization to find each best (one CP-SAT run per scenario — existing budget allows); normalization across scenarios must be consistent.
- **Computational:** N × optimization (each ≤10 s) + evaluation — practical for N ≲ 10.
- **Interpretability:** high ("strategy S gives up ≤ X of the best achievable soil-health index in any declared scenario").
- **Limitations:** regret on normalized indices inherits the shared-evaluable-set caveats (non-comparable pairs).
- **Reuse:** full — optimizer re-run per scenario with existing determinism guarantees.

### 3.5 Feasibility robustness (fraction/set of scenarios with constraints satisfied)
- **Data requirements:** scenario set (as 3.1).
- **Mathematical assumptions:** the fraction describes **only the declared scenario set**; it must never be presented as a real-world probability (spec's explicit warning; platform language already has the discipline to say this).
- **Computational:** trivial post-hoc.
- **Interpretability:** high with correct wording ("3 of 5 declared scenarios").
- **Reuse:** full.

### 3.6 Sensitivity analysis (ranking stability under input/weight perturbation)
- **Data requirements:** supported perturbation ranges — criterion weights (already user-parametrizable via custom weights), allocation values, evaluation-window shifts; *input coefficient* perturbation requires the F-12 climate-context override to exist.
- **Mathematical assumptions:** perturbations stay within documented ranges; ranking changes reported, not hidden.
- **Computational:** k re-runs (deterministic, seeded) + rank-agreement statistic.
- **Interpretability:** high ("water_priority vs balanced swap ranks when allocation < X m³").
- **Reuse:** full for weight/allocation perturbation (no engine change); partial for climate perturbation (needs F-12).

## 4. Findings register

| ID | Severity | Domain | Affected code/schema | Current behavior | Expected for M7 | Evidence | Impact | Blocks M7? |
|---|---|---|---|---|---|---|---|---|
| F-18 | High | Rotation | no scenario-aware run linkage | one run = one evidence set | multi-scenario evaluation needs run/strategy × scenario result tables (post-hoc, by-ref) | §2 | new tables required, no engine change | No (M7.5 scope) |
| F-19 | Medium | Rotation | `RotationProblem.checksum()` covers candidate codes, not assessment values | evidence-value changes only caught via strategy checksums | scenario comparisons should hash assessment payloads too | problem.py:277-280 | weaker reproducibility diagnostics | No |
| F-20 | Medium | Rotation | `solver_version` column never populated | provenance gap | record ortools version per run | models.py:982; grep — no writer | minor provenance hole | No |
| F-21 | Medium | Objectives | normalization is per-run-set | cross-scenario criteria need a defined union-set normalization | extend or explicitly re-normalize across scenario set | objectives.py:438-446 | affects worst-case/regret comparability | No (M7.6 design) |
| F-22 | Low | Optimizer | single global 10 s solve budget | fine per-scenario; outer-loop min-max multiplies | acceptable for v1; note in design | optimizer.py:34 | compute only | No |
| F-23 | Medium | Engine contract | engines read climatology from feature runs | climate-perturbed sensitivity needs F-12 override | implement virtual climate context (same finding as scenario F-12) | scenario doc §3 | shared dependency with M7.3 | No |

## 5. Readiness verdict

| Capability | Status |
|---|---|
| Determinism & reproducibility prerequisites | **READY** (seeded, single-worker, checksums, tests) |
| Post-hoc multi-scenario evaluation of a fixed strategy | **READY** (solver-free validators + pure criteria evaluators — by design) |
| Scenario feasibility & feasibility-robustness fractions | **READY** (given M7.2 scenario definitions exist) |
| Regret-based evaluation | **READY_WITH_LIMITATIONS** (N re-optimizations; normalization caveat F-21) |
| Worst-case (min-max) evaluation | **READY_WITH_LIMITATIONS** (post-hoc version; bounds must be declared & labelled) |
| Sensitivity analysis (weights/allocation) | **READY**; (climate inputs) **PARTIAL** → F-12/F-23 |
| Expected performance over probabilities | **NOT_IMPLEMENTED / NOT_APPLICABLE today** — blocked on a sourced, justified probability model (no ensemble data ingested) |
| Solver-level robust optimization (joint model) | **NOT_IMPLEMENTED** — not required for v1; feasible later by reusing the model builder |
| Honest status semantics under new evaluation modes | **READY** (infeasible/model_invalid/unknown discipline is already institutionalized) |

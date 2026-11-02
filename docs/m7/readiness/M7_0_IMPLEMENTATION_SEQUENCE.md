# M7.0 — M7 Dependency & Implementation Sequencing

**Inspection date:** 2026-11-01 · **Basis:** repository evidence only (`M7_0_*` document set). The proposed structure M7.1→M7.8 is evaluated below; two adjustments are recommended based on findings (§2). No M7 code exists or was written.

---

## 1. Verdict on the proposed sequence

| Proposed | Verdict | Evidence-based rationale |
|---|---|---|
| M7.1 Unified Field State & Snapshot Contracts | **KEEP — first** | everything depends on a stable parent object; all ingredients exist (Field State doc §1); boundary-pinning (F-01) and observation-manifest hashing (F-31) belong here |
| M7.2 Scenario domain & immutable definitions | **KEEP — second** | scenarios parent on states; contract is supportable today (Scenario doc §2); harmonized run envelope should land with it (API doc §5) |
| M7.3 Historical & user-defined stress transformations | **KEEP — third** | needs the F-12 engine climate-context override; historical + stress types are the only scientifically available scenario engines today |
| M7.4 Sensitivity & uncertainty analysis | **KEEP — fourth** | consumes M7.3 transforms; pure post-hoc computation; no new data dependencies |
| M7.5 Multi-scenario rotation evaluation | **KEEP — fifth** | composes M7.3 scenarios with the existing optimizer/validators; likely first consumer of worker/progress infrastructure (F-29) |
| M7.6 Robustness & decision-stability analysis | **KEEP — sixth** | regret/worst-case/stability layers on M7.5 outputs; normalization-across-scenarios design (F-21) |
| M7.7 Field Digital Twin timeline & visualization | **KEEP — seventh** | visualizes states + scenarios; soil/management lanes honestly empty; no predictive claims |
| M7.8 External climate projections & forecast integrations | **KEEP — LAST, conditional** | correctly gated on sourced data (gap register G-1, §2 opportunities); must not start without a licensed, documented dataset + methodology |

**Recommended adjustments:**
- **A1 (sequencing):** pull the **run-envelope harmonization + ingestion idempotency fix (F-30) + water-plan DELETE policy (F-13) + boundary-version pinning (F-01)** into M7.1 as explicit sub-tasks — they are prerequisites for honest state checksums, and doing them later would force state re-creation.
- **A2 (scope guard):** M6B (soil) and M6C (management) remain **out of M7 scope** (per M7.0 mandate M6C is unimplemented; M6B likewise). M7 must ship with soil/management as explicit `NOT_IMPLEMENTED` dimensions/lane. If the program later wants soil/management scenario axes, that is an M6B/M6C completion effort *before* extending M7.3/M7.5.

## 2. Increment specifications

### M7.1 — Unified Field State & Snapshot Contracts
- **Dependencies:** none (first). Existing: feature runs, water plans, rotation runs, pack refs, boundary versions.
- **Required existing modules:** `app/domains/farms_fields` (boundary versions), `app/features/service` (run refs), `app/water/service` (snapshot/checksum idiom), `app/knowledge/service.pack_ref`.
- **New capabilities:** `field_states` table (by-reference composition; per-dimension refs; evidence/quality dimension maps — no generic score); state assembly service; as-of queries; staleness policy.
- **Schema changes:** +`field_states`; +`boundary_version` pinning columns on new/derived artifacts (additive); observation-manifest hash column on `feature_runs` (additive).
- **API:** `POST/GET /fields/{id}/field-states`, `GET /field-states/{id}` (+ refs expansion); state payload surfaces `created_by`.
- **Scientific references:** none new required (assembly layer); cite FAO-56/FAO-33 method versions already embedded.
- **Data requirements:** none beyond existing.
- **Computational complexity:** O(refs) assembly; checksum hashing only.
- **Risks:** period-compatibility mistakes (F-02) → implement explicit compatibility checks with recorded mismatches; temptation to duplicate data → forbidden by design (refs only).
- **Acceptance criteria:** state reproducible from refs alone (checksum test); boundary version recorded; missing dimensions rendered as `not_implemented`/`not_evaluated` with reasons; tenant-isolated; browser-verified state view.

### M7.2 — Scenario Domain & Immutable Scenario Definitions
- **Dependencies:** M7.1 (parent states, or state ingredients), run-envelope harmonization.
- **Required existing modules:** run lifecycle idioms (202 pattern, idempotency), evidence-class vocabulary, pack refs.
- **New capabilities:** `scenarios` table (type, config, parent state, checksums, status); scenario-type evidence classes; validation of adjustment configs.
- **Schema changes:** +`scenarios`; deletion policy for referenced runs (F-13).
- **API:** scenario CRUD + `POST /scenarios/{id}/execute` (job pattern).
- **Scientific references:** scenario-type definitions with evidence-semantics citations (e.g., perturbation ≠ projection distinction; observed vs assumption-labelled inputs).
- **Data requirements:** none new.
- **Computational:** definition-time only.
- **Risks:** type/label confusion → enforce per-type badges + non-interchangeability tests; dangling refs → RESTRICT/archive.
- **Acceptance criteria:** scenario immutable after creation (update refused); checksum stable; type-evidence discipline tested; tenant isolation.

### M7.3 — Historical & User-defined Environmental Stress Transformations
- **Dependencies:** M7.2; F-12 engine contract decision.
- **Required existing modules:** `app/water/*` (curve, effective_rainfall, soil, requirements, planner), `app/rotation/candidates` (shared arithmetic), feature engine.
- **New capabilities:** versioned `climate_context` override accepted by water planner + candidate water estimates (virtual, non-materialized); transformation library (ΔT, ΔP with ≥0 clamp, allocation change, initial Dr) with per-transformation assumption records.
- **Schema changes:** none required beyond scenario config JSONB (engines accept context as input contract).
- **API:** transformations applied at scenario execution; results labelled with transformation provenance.
- **Scientific references:** FAO-56 (ET0 input requirements; why local ET0 recomputation is refused without radiation/humidity), FAO-33; physical-consistency rules (non-negative precip; unit-explicit temperature deltas; monthly-scaling seasonality caveat).
- **Data requirements:** historical observations (exist); none for stress type.
- **Computational:** one water-plan-equivalent run per scenario — seconds.
- **Risks:** derived-data leakage into observation store (forbidden: virtual context only); mislabelled scenario classes.
- **Acceptance criteria:** perturbed scenario results carry transformation metadata + assumption labels; negative precip rejected; unmodified engines produce bit-identical results when no override given (regression).

### M7.4 — Sensitivity & Uncertainty Analysis
- **Dependencies:** M7.3.
- **New capabilities:** parameter/weight perturbation sweeps over declared ranges; rank-stability statistics; per-criterion sensitivity summaries.
- **Schema changes:** +`sensitivity_analyses` (or results JSONB on scenario runs — decide by size).
- **API:** `POST /scenarios/{id}/sensitivity` (job), results endpoint.
- **Scientific references:** local sensitivity analysis (one-at-a-time) conventions; explicit non-probabilistic framing (no pseudo-probabilities).
- **Data requirements:** none beyond M7.3.
- **Computational:** k × (water-plan-equivalent) — bounded by declared ranges.
- **Risks:** presenting scenario counts as probabilities (spec warning) → wording enforced in payload + UI.
- **Acceptance criteria:** deterministic (seeded) sweeps; ranges recorded; rank flips reported explicitly.

### M7.5 — Multi-scenario Rotation Evaluation
- **Dependencies:** M7.2–M7.4; worker/progress (F-29) recommended here.
- **Required existing modules:** `app/rotation/optimizer` (unchanged model), `constraints` validators (solver-free reuse), `objectives` evaluators, water planner via M7.3 context.
- **New capabilities:** strategy × scenario evaluation matrix; feasibility-robustness fractions (declared-set wording); per-scenario named infeasibility surfacing.
- **Schema changes:** +`scenario_evaluations` (strategy × scenario results, checksums, refs).
- **API:** `POST /scenarios/{id}/evaluate-rotation` (batch job + progress), comparison endpoint (also fills frontend F-39).
- **Scientific references:** scenario-feasibility framing (non-probabilistic); Pareto/normalization citations already in `objectives.py`.
- **Data requirements:** none new.
- **Computational:** validators cheap; N × water computation; re-optimization only for regret (M7.6).
- **Risks:** inline latency → worker; cross-scenario normalization semantics (F-21 design note).
- **Acceptance criteria:** identical strategy+scenario → identical checksum; feasibility fraction labelled "of declared scenarios"; no modification of optimizer behavior (regression suite green).

### M7.6 — Robustness & Decision-Stability Analysis
- **Dependencies:** M7.5.
- **New capabilities:** worst-case (declared bounds), regret (per-scenario re-optimization), decision-stability under weight/allocation perturbation; union-set normalization design (F-21).
- **Schema changes:** results tables or JSONB extensions.
- **API:** analysis endpoints on evaluation sets.
- **Scientific references:** min-max/regret decision criteria (Savage regret; distributionally-robust framing *not* claimed without probabilities); explicit assumption registers.
- **Computational:** N × CP-SAT (10 s budget each) — practical for N ≲ 10.
- **Risks:** over-interpretation; compute scaling.
- **Acceptance criteria:** every analysis output states its scenario set + bounds; regret baseline reproducible.

### M7.7 — Field Digital Twin Timeline & Visualization
- **Dependencies:** M7.1 (states), M7.2+ (scenarios).
- **New capabilities:** StateTimeline lanes (environmental/soil/water/crops/management), as-of state view, EvidencePanel drill-down (consumes `input_refs`), scenario compare panel; twin-maturity labelling ("Historical profile — not a calibrated twin").
- **Schema changes:** none (read-only surfaces).
- **API:** composition of existing + M7.1/7.2 endpoints.
- **Scientific references:** none new; reuse embedded method citations.
- **Computational:** read-only.
- **Risks:** twin overclaim (L4/5) → labelling tests; empty soil/management lanes must be explicit NOT_IMPLEMENTED states.
- **Acceptance criteria:** timeline values trace to artifacts (checksums visible); mobile 390 px verified; zero console errors.

### M7.8 — External Climate Projections & Forecast Integrations (conditional)
- **Dependencies:** M7.2 (scenario types), sourced dataset + license review, methodology doc (bias adjustment), F-15 metadata.
- **New capabilities:** new providers (projection ensemble, forecast) under the existing `EnvironmentalDataProvider` protocol; issue-time/horizon metadata; ensemble-aware scenario type.
- **Scientific references:** projection/forecast evidence semantics; ensemble probability framing (only here do expected-performance metrics become defensible).
- **Risks:** data licensing; downscaling validity; the platform must refuse to present projections as observations (evidence-class enforcement).
- **Acceptance criteria:** provider contract tests pass (UTC, missing≠zero, license/attribution); scenario outputs carry projection-specific disclaimers; no blending with observational products.

## 3. Dependency graph

```
M7.1 Field State ──► M7.2 Scenarios ──► M7.3 Transforms ──► M7.4 Sensitivity ──┐
        │                       │                                              ├──► M7.5 Multi-scenario rotation ──► M7.6 Robustness
        │                       └──────────────────────────────────────────────┘                                        │
        └──────────────────────────────────────────────────────────────────────────────────► M7.7 Twin timeline ◄──────┘
                                                        (M7.8 conditional, after M7.2; data-gated)
```

Prerequisite hygiene sub-tasks inside M7.1 (adjustment A1): F-01 boundary pinning · F-13 deletion policy · F-30 ingestion idempotency · F-31 observation manifest hash · run-envelope alignment (§ API doc 5) · F-09/F-17/F-20 created_by & solver_version surfacing.

## 4. Cross-cutting acceptance criteria (all increments)

1. Every artifact carries: type/evidence label, model versions, input refs with checksums, created_by/at.
2. Missing inputs → `not_evaluated`/`not_implemented`/`not_applicable` with reasons — never zeros, never fabricated evidence.
3. Determinism: identical inputs → identical checksums, regression-tested.
4. Tenant isolation preserved (membership-guard paths for every new route).
5. Mobile 390 px + desktop verified in browser; zero console errors; sticky footer intact.
6. No M6B/M6C scope creep; no predictive/calibration claims (twin stays honestly labelled).

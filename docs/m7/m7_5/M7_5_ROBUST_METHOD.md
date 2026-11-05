# M7.5 — Robust Multi-Scenario Rotation Optimization

Status: **IMPLEMENTED & VERIFIED** (commit `91dab742`, browser E2E verified).
Engine: `robust-rotation-engine-1.0.0` · Method: `robust-worst-case-1.0` · Migration: `0011_robust_rotation`.

## 1. What it does

Evaluates **one shared crop-rotation plan** across **multiple compatible M7.3
scenario executions**. The plan is optimized ONCE, not per scenario:

1. **Scenario sets** — 1–5 result-bearing M7.3 executions of the same field,
   same parent Field State (identical parent pin + checksum), distinct
   scenarios. Members are copied **BY VALUE** (output checksums, parent pins,
   engine versions); re-verification compares live rows against the pins and
   refuses to run over drift.
2. **Per-scenario problems** — each member's derived features (monthly) become
   the scenario's season climate evidence by REUSING M5's `_season_climate`
   through a read-only view adapter (no duplicated aggregation math):
   - `scenario_recalculated` rows contribute their `scenario_value`;
   - `not_affected` rows contribute the stored `baseline_value` (identity — the
     transformation provably does not touch the variable; recorded, never assumed);
   - `not_evaluated` rows stay missing (ET0 above all — never approximated).
   Month-coverage validation rejects runs whose seasons are not covered by every
   member's window.
3. **Cross-scenario candidate pool** — a crop enters a season's pool only if it
   is admissible (M5 `generate_candidates`) in EVERY scenario. Exclusions are
   first-class records (`cross_scenario_exclusions`) naming the failing scenario
   and the hard reason (e.g. temperature below absolute minimum, planting window).
4. **ONE CP-SAT model per strategy profile** (M5 infra: `num_search_workers=1`,
   seed 0, assumption-based infeasibility mapping): shared assignment variables;
   rotation-break constraints enforced once on the shared variables; steering
   objective = **maximin** — `maximize W subject to W ≤ objective_s(x) for every
   scenario s`, with per-scenario score tables from M5's `_per_crop_scores`
   (scenario-dependent via temperature-screening reasons and water estimates).
   A scenario with no evaluable steering criteria contributes NO maximin
   constraint (recorded — a zero floor would silently dominate the worst case).
5. **Post-hoc evaluation per scenario** — M5's `evaluate_criteria`,
   `check_all`, `normalize_within_set`, `weighted_objective`, `compute_pareto`
   are reused verbatim. Normalization set per scenario = shared plans +
   baseline + (optional) solo optima of that scenario. Reported values are
   scenario-normalized; comparable within a run, not across runs.
6. **Aggregates**
   - **Worst-case objective** = min over scenarios of the per-scenario weighted
     normalized objective; reported ONLY when evaluable in every scenario
     (a partial minimum would overstate robustness). Deterministic minimum —
     NOT a confidence or probability interval.
   - **Minimax regret** (optional, default on): per (scenario, profile) solo
     M5 optimum on that scenario's own problem; regret = solo − shared
     objective on the same normalization basis; worst-case regret = max over
     scenarios; reported only when complete. Deterministic objective gap —
     NOT an expected value.
   - **Robust feasibility** per plan: `robust_feasible` (every evaluated
     constraint satisfied and every assigned crop admissible in every
     scenario), `robust_infeasible` (any violation or exclusion), 
     `not_evaluable`. Unevaluated checks are never treated as satisfied.

## 2. Structural unavailability (by design)

- **Scenario ET0 is never recalculated by M7.3** → scenario water requirements
  are structurally unavailable → water-requirement criteria render not
  evaluable per scenario.
- **`water_allocation_m3` is rejected** for robust runs
  (`WATER_ALLOCATION_UNSUPPORTED`, HTTP 422): an allocation would make the
  water constraint unevaluated in every scenario, and unevaluated constraints
  are never treated as satisfied. This is a documented unavailable capability,
  not a silent drop.

## 3. Solver status discipline

`optimal` is claimed only when EVERY shared-profile solve proved optimality
(time-limited FEASIBLE is reported as `feasible`); solver breakdowns
(`model_invalid` / `unknown`) never read as agronomic infeasibility.
Solver diagnostics store status, wall time, maximin value, proven objective
bound, and per-scenario steering score tables used/skipped.

## 4. Persistence (migration 0011)

- `scenario_sets` — members by value; `set_checksum` UNIQUE per field;
  content-addressed replay; FK RESTRICT from runs (delete blocked while used).
- `robust_rotation_runs` — BY-VALUE `member_pins`, seasons/profiles/regret
  design, engine versions, `run_fingerprint` UNIQUE `(scenario_set_id,
  fingerprint)` (deterministic replay; changed design ⇒ new run), output
  checksum CHECK on success, **BEFORE UPDATE immutability trigger + BEFORE
  DELETE protection** for result-bearing runs.
- `robust_rotation_strategies` — one shared plan per profile + the labelled
  `baseline` (current rotation); worst-case aggregates; strategy checksums.
- `robust_scenario_evaluations` — one row per (plan, scenario): criteria with
  units/directions/missing evidence, constraint checks, per-season crop
  admissibility, scenario-normalized objective, Pareto flag, per-scenario
  regret; each row pins the source execution run (FK RESTRICT) + output
  checksum.

## 5. API (tenant-scoped via field ownership; client claims never trusted)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/fields/{field_id}/scenario-sets` | create + compatibility validation (idempotent) |
| GET | `/api/v1/fields/{field_id}/scenario-sets` | list |
| GET/DELETE | `/api/v1/scenario-sets/{set_id}` | detail / delete (blocked when runs exist) |
| POST | `/api/v1/scenario-sets/{set_id}/verify` | BY-VALUE pin verification (drift = data, not error) |
| POST | `/api/v1/scenario-sets/{set_id}/robust-runs` | create + run (fingerprint/idempotency replay) |
| GET | `/api/v1/scenario-sets/{set_id}/robust-runs` | list (filter `run_status`) |
| GET | `/api/v1/robust-runs/{run_id}` | detail incl. strategies |
| GET | `/api/v1/robust-runs/{run_id}/evaluations` | per-scenario rows (filters: `scenario_id`, `strategy_key`) |
| POST | `/api/v1/robust-runs/{run_id}/verify` | strategy checksums + member pins |

## 6. Tests & verification evidence

- `tests/unit/test_robust_rotation_core.py` (10): value-source rules
  (recalculated / not_affected / not_evaluated), month coverage incl.
  year-wrapping seasons, window intersection, per-scenario verdict honesty
  (unevaluated ≠ satisfied), by-value member documents.
- `tests/integration/test_robust_rotation.py` (26): golden path, per-scenario
  evaluations, worst-case = min across scenarios, single-scenario consistency
  (shared plan never beats its scenario's solo optimum), idempotent replay,
  changed-design ⇒ new run, water-allocation rejection with
  `WATER_ALLOCATION_UNSUPPORTED`, month-coverage rejection, extreme-cold
  scenario invalidating the baseline (evidence-driven), cross-scenario
  exclusion records, trigger immutability (update/delete), tenant isolation
  (403), verification endpoint, migration head.
- Browser E2E: scenario set → robust run (`OPTIMAL (proven)`, 2 scenarios,
  summer_2023), shared-plan table (soybean assignment, worst-case 0.55–0.625,
  regret 0), ET0-not-evaluable disclosures, 5 cross-scenario exclusions with
  reasons, verify → `verified`; desktop + 390 px.

## 7. Known limitations

- Steering score tables are scenario-dependent only through
  `climate_resilience_index` (temperature screening) and water estimates; with
  no ET0 under scenarios the maximin objective is effectively
  climate-insensitive except for admissibility-driven candidate restriction —
  the reported per-scenario criteria carry the scenario differences.
- Worst-case objective/regret compare scenario-normalized values; they are
  meaningful within one run, not across runs.
- Minimax regret anchors use each scenario's own admissible candidates (the
  scenario-specific optimum); the shared plan's opportunity set is the
  cross-scenario intersection — both are documented in the response.

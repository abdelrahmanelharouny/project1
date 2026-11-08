# M7.5 Robust Rotation Method

The robust multi-scenario rotation method. Implementation:
`app/robust_rotation/contracts.py` (versioned constants and caps),
`engine.py` (shared-plan CP-SAT optimizer), `climate.py` (scenario climate
evidence), `service.py` (orchestration and persistence).

## What a robust evaluation is

ONE shared crop-rotation plan evaluated across MULTIPLE compatible M7.3
scenario executions. It is a derived analytical artifact: it never mutates
observations, feature runs, Field States, scenario definitions or M7.3
execution results.

## Method

```
Scenario Set (compatible, result-bearing M7.3 executions)
    ↓  verify member pins against live rows
Resolve Seasons + Profiles             (water allocations rejected)
    ↓  per-scenario FarmContext        (climate from derived features)
Per-scenario candidate assessments     (M5 generate_candidates, reused)
    ↓  cross-scenario admissible pool  (intersection + exclusions)
ONE shared-plan solve per profile      (maximin steering, CP-SAT)
    ↓  per-scenario post-hoc evaluation (M5 code, reused)
Worst-case objective / regret / robust feasibility
    ↓
Persist Immutable Results              (trigger-frozen rows)
```

- **One solve, shared variables.** NOT "optimize every scenario separately
  and relabel": assignment variables are shared, and the hard constraints
  that are genuinely evaluable in every scenario are enforced once on the
  shared variables. The steering objective is the worst case (maximin):
  `maximize W subject to W <= objective_s(x)` for every scenario s.
- **Post-hoc evaluation.** Per-scenario criteria are recomputed by the
  EXISTING M5 evaluation code (`objectives.evaluate_criteria`,
  `constraints.check_all`, `normalize_within_set`, `weighted_objective`,
  `compute_pareto`). The solver's internal maximin value is a steering
  device, never the reported evidence.
- **Determinism.** `num_search_workers=1`, recorded seed, sorted iteration
  order — identical inputs yield identical assignments (tested).
- **Assumption-based infeasibility.** As in M5, hard constraints register
  as solver assumptions; an infeasible model maps back to named
  constraints, never a silent relaxation.
- **Honest maximin.** A scenario whose steering criteria are entirely
  unevaluable contributes NO maximin constraint (it would silently zero
  the worst case); the omission is recorded per scenario.

## Interpretation contract

- The reported worst-case objective is the minimum over scenarios of the
  per-scenario weighted normalized objective. It is NOT a confidence
  interval and NOT a probability statement.
- **Minimax regret** (optional) compares the shared plan against
  per-scenario solo optima on the same normalization basis. It is a
  deterministic objective-gap measure, NOT a probability-weighted expected
  regret. Regret anchors are bounded (`MAX_SOLO_SOLVES = 25`,
  scenarios × profiles).
- **Robust feasibility verdicts** (`robust_feasible`,
  `robust_infeasible`, `not_evaluable`) are per shared plan across the
  selected scenarios.

## Climate evidence rules

`climate.py` reuses `app.rotation.service._season_climate` verbatim through
a read-only view adapter — the month-of-year aggregation arithmetic exists
exactly once. Value sources:

- `scenario_recalculated` rows contribute their real M7.3 scenario values;
- `not_affected` rows contribute their stored baseline values (the
  transformation provably does not touch that variable — the identity is
  recorded, never silently assumed);
- `not_evaluated` rows are excluded: missing stays missing. Reference ET0
  is never recalculated by M7.3, so scenario water estimates are
  structurally unavailable — **farmer water allocations are rejected
  upstream** instead of silently dropping the constraint.

## Caps

Documented, validated before any solve: `MAX_SCENARIO_SET_SIZE = 5`,
`MAX_ROBUST_PROFILES = 5` (including `custom`), `MAX_SOLO_SOLVES = 25`.

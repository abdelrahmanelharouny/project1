# M7.3 Scenario Execution — Architecture

Authoritative description of how scenario definitions become immutable
execution runs. Implementation: `app/scenario_execution/service.py`
(orchestration), `transformations.py` (pure math), `dependency_graph.py`
(feature roles), persisted by trigger-frozen tables.

## Pipeline

```
Finalized Scenario Definition
    ↓  verify lifecycle + configuration checksum + parent pins
Resolve Observation Manifest          (BY VALUE — never a live query)
    ↓  variable / temporal compatibility (blocking findings)
Apply Environmental Transformations   (pure functions)
    ↓
Recalculate Supported Features        (M4 engine, two passes)
    ↓  baseline pass = original values, scenario pass = transformed
Propagate Quality and Uncertainty
    ↓
Generate Execution Checksum           (canonical JSON, SHA-256)
    ↓
Persist Immutable Results             (trigger-frozen result rows)
```

## Rules

- **Nothing mutates parent artifacts.** Observations, feature runs, Field
  States and finalized scenario definitions are read-only inputs; all
  outputs land in the `scenario_execution_*` derived layer.
- **The manifest is by value.** The run pins the exact observation set from
  its parent Field State manifest (ids + checksums), so a run is replayable
  even if new observations arrive later.
- **Only `finalized` scenarios execute.** Configurations carrying
  unsupported adjustment dimensions are refused with structured findings;
  `water_allocation_multiplier` is allowed as context but does not conjure
  water data. A scenario with no supported transformation is refused —
  no-op runs would masquerade as the baseline.
- **Determinism.** Every step is a pure recomputation; the output checksum
  (canonical JSON, SHA-256) makes identical inputs verifiable.

## Feature dependency roles

Derived from the versioned M4 feature catalog (no formulas here — the
catalog is the single source of scientific truth):

- `recalculate` — all required variables transformed; feature recomputed
  from the transformed observation set by the M4 engine.
- `exclude_et0` — requires observed reference ET0; baseline ET0 is never
  valid as scenario-derived value and M7.3 does not recalculate
  evaporative demand → `not_evaluated`.
- `not_affected` — required variables untouched by the configured
  transformations → not computed, reported with a reason.
- `exclude_mixed_inputs` — requires both transformed and untouched non-ET0
  variables (incoherent to recompute) → `not_evaluated`. Fail-closed for
  future catalog entries.

## Immutability and verification

Result rows are frozen by database triggers after completion; the run
carries method and engine versions; `POST /api/v1/scenario-executions/
{id}/verify` re-checks pins, checksums and row integrity and persists the
verification outcome. Downstream consumers (M7.4 sensitivity, M7.5 robust
rotation, M7.6 decisions, M7.7 twin) accept only result-bearing,
verification-clean runs.

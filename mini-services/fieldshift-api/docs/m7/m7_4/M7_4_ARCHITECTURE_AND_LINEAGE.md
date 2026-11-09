# M7.4 Sensitivity Analysis — Architecture and Lineage

How sensitivity analyses relate to the artifacts they analyze and what the
platform guarantees about them. Implementation:
`app/sensitivity/service.py` (orchestration), `math.py` (pure method),
`registry.py` (uncertainty registry), `contracts.py` (versioned
vocabularies).

## Position in the artifact chain

```
Field State → finalized scenario → M7.3 execution run (immutable)
                                        ↓
                        M7.4 sensitivity analysis (this module)
                                        ↓
              M7.5 robust rotation · M7.6 decision documents · M7.7 twin
```

A sensitivity analysis analyzes **ONE immutable M7.3 execution run**. It
varies the run's configured transformation parameters over user-supplied
bounds and recomputes the affected environmental features with the existing
M4 engine through the SAME code paths M7.3 uses
(`_manifest_observations`, `apply_transformations`, `plan_scenario_features`,
`recalculate_specs`, `compute_feature_drafts`) — no transformation or
feature-engineering logic is duplicated.

## Analysis flow

```
Result-bearing M7.3 Execution Run
    ↓  verify integrity gates (pins, checksums, run verification)
Resolve Exploration Design      (bounds validated against references)
    ↓  canonical input document + fingerprint (idempotent replay)
Reproduce Reference Evaluation  (exact gate against stored rows)
    ↓  mismatch ⇒ analysis FAILS, nothing substituted
Evaluate OAT Sweeps + Joint Grid (unique parameter tuples, deduped)
    ↓
Compute Response Metrics        (envelope, slopes, classification)
    ↓
Build Uncertainty Registry      (dynamic evidence binding)
    ↓
Persist Immutable Results       (trigger-frozen analysis rows)
```

## Lineage guarantees

- **Read-only parents.** Observations, feature runs, Field States,
  finalized scenarios and M7.3 results are never mutated; outputs land in
  the `sensitivity_*` analytical layer with full source references.
- **Reproduction gate.** Before sweeping, the analysis reproduces the run's
  reference evaluation and compares it to the stored rows; any mismatch
  fails the analysis — nothing is silently recomputed or substituted.
- **Idempotent replay.** The analysis input document is canonicalized and
  fingerprinted; re-submitting an identical request returns the same
  analysis.
- **Determinism.** Sweeps, metrics and rankings are pure functions of the
  pinned inputs (see `M7_4_SENSITIVITY_METHOD.md`); results are
  checksummed and exposed to `/verify`.

## What an analysis is not

It is not a statistical inference over uncertain distributions: no priors,
no Monte Carlo, no probability statements. Bounds are explicit user
assumptions; the uncertainty registry records exactly that (see
`M7_4_UNCERTAINTY_REGISTRY.md`).

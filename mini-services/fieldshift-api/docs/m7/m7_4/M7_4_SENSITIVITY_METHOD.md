# M7.4 Sensitivity Method

The deterministic mathematics behind sensitivity analyses. Implementation:
`app/sensitivity/math.py` (pure, side-effect-free), contracts in
`app/sensitivity/contracts.py` (versioned rubric and tolerances).

## Method components

1. **Sweep design.** Evenly spaced (`linspace`) parameter sweeps over
   user-supplied bounds, including both endpoints, with structured
   validation findings for degenerate designs (fewer than two points,
   inverted bounds). An optional joint grid covers multi-parameter
   interaction contrasts.
2. **Finite-difference slopes.** Central differences preferred; one-sided
   fallback at the sweep boundary. Slopes carry explicit units (feature
   unit per parameter unit) and a validity flag — a slope across a gap or
   an invalid point is reported invalid, never silently averaged.
3. **Normalized elasticity.** Percentage-response measure with structured
   unavailability: division by zero (zero baseline or zero delta) yields an
   explicit `unavailable` record, never an epsilon fudge.
4. **Response-behaviour classification.** Each response is classified under
   a versioned rubric (flat / linear-like / monotone non-linear /
   non-monotone / threshold-like) using tolerances fixed in the contracts
   module. The rubric version travels with every result.
5. **Interaction contrast.** For joint grids, a finite-grid interaction
   contrast quantifies deviation from additivity, plus per-parameter grid
   summaries (envelope, endpoints, monotonicity checks).

## Guarantees

- **Deterministic.** No randomness, no clock, no I/O. Identical inputs
  produce identical outputs — enforced by unit tests.
- **No numeric fudges.** Undefined quantities (0/0, empty windows) are
  structured `unavailable` records, not zero or NaN silently propagated.
- **Bounded.** Sweep sizes and grid dimensions respect documented caps;
  pathological bounds are rejected at design time.

## Interpretation contract

Results say how a feature responds **within the swept bounds**, under the
same transformation machinery M7.3 used. They do not extrapolate beyond the
bounds, do not assign probabilities, and do not rank features across units.
Cross-unit summaries live in the M7.6 decision layer, which ranks only
within the same unit.

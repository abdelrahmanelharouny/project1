# ROTATION_MATHEMATICAL_SPECIFICATION.md — Phase F (as-built + audited)

Engine: `rotation-engine-1.0.0` · Solver: CP-SAT (OR-Tools 9.14.6206) ·
Seed: 0 recorded on every run · `num_search_workers=1` for determinism.

## 1. Decision model

- **Decision variables**: binary `x[i,c]` — crop c occupies season i.
  Domain {0,1}. Exactly one crop per season (`AddExactlyOne`).
- **Admissible pool (ADR-0016)**: only `eligible`/`conditionally_eligible`
  candidates per season enter; with a hard water allocation, crops without an
  estimable requirement are held OUT (never partially compliant).
- **Planning horizon**: 1–4 user-defined seasons (labels + dates validated;
  ≤400 d per season). Baseline = reconstruction from crop history by season
  label, then by date overlap — evaluated, never repaired to look feasible.
- **Objective**: integer-scaled weighted sum of per-crop, per-criterion score
  tables (×1e6) + family-alternation Boolean terms between consecutive seasons.
  Reported criteria are ALWAYS recomputed post-hoc on the final assignment —
  the solver objective is a steering device only.
- **Solver configuration**: max 10 s; assumptions pattern for conflicts.

## 2. Hard constraints (registered as ASSUMPTIONS; never silently relaxed)

| Constraint | Solver encoding | Pure-layer check (solver-independent) |
|---|---|---|
| one_crop_per_season | `AddExactlyOne` | missing season → violated |
| candidate_admissibility | pool restriction (+ water-estimability under allocation) | assigned crop must be admissible for THAT season |
| rotation_break (confirmed_regional only) | pairwise `x[j,p]+x[i,c] ≤ 1` when gap ≤ k; history boundary `x[i,c] = 0` when (i+1) ≤ k | same gap semantics: binds when `gap < k` (gap = seasons strictly between; history crop = virtual season −1) |
| water_allocation (per season) | `Σ x[i,c]·(mm_c·area_m2) ≤ alloc_m3·1000` — litres exactly (1 mm·m² = 1 L); integer-scaled | recomputed need vs allocation with 1e-9 tolerance |

Deepening F-06: the pairwise lookback and the history window are DERIVED from
the deepest confirmed rule (`max min_break_seasons`), removing the old caps
(4 / 3) that under-enforced deep rules; checker and optimizer provably agree.
Constraint statuses distinguish **satisfied / violated / not_applicable** at
runtime; `not_evaluated` and `not_configured` are produced by candidate
generation and knowledge gating respectively (an absent rule never becomes a
satisfied biological constraint — the rotation-break check reports the loaded
confirmed-rule count in its detail text).

## 3. Mathematical treatment of missing information (all tested)

- Missing economics → criterion not evaluable, weight skipped with reason
  (never zero profit; never invented).
- Unknown water requirement → crop held out of allocation-constrained runs;
  criterion reports missing evidence per season.
- Absent traits → sub-indicators skipped inside composites, listed in
  `missing_evidence` (never zero-filled).
- Incomplete baselines → not evaluated, never ranked as equivalent to fully
  evaluated candidates (`evidence_coverage` is a transparency metric, not a
  confidence score).

## 4. Multi-objective evaluation (ADR-0018)

1. Strategies = baseline + one per requested profile (+ optional custom
   weights; every weight ≥ 0, sum > 0).
2. Criteria evaluated on the FINAL assignment (7 criteria; per-criterion
   derivations + source citations since F-10).
3. Min-max normalisation WITHIN the generated strategy set, per criterion over
   the solutions where it is evaluable; single/identical values → neutral 0.5
   (documented, tested).
4. Weighted objective renormalizes weights over evaluable criteria; skipped
   weights carry reasons (never silently dropped).
5. **Pareto dominance over the SHARED evaluable set of each pair** — disjoint
   evaluable sets are mutually non-comparable (recorded, not hidden);
   duplicates both stay on the front (tested).

**Weighted-sum limitation (documented, §8.4 of the directive)**: the steering
objective is a weighted sum, which cannot reach non-convex Pareto regions for
a fixed profile set. Two mitigations: (a) the recommended set is the PARETO
FRONT of the GENERATED set — dominance is computed exactly on final criteria,
so no dominated point is ever recommended; (b) the on-front claim is always
scoped ("of the generated strategy set", shown verbatim in UI and payload).
A repeated epsilon-constraint sweep over criteria is the correct upgrade path
for guaranteed front coverage and is backlog M-1 (it changes strategy counts
and UI contracts, so it ships with the next engine version).

## 5. Solver status semantics (deepening F-4)

| CP-SAT status | Reported as | Meaning |
|---|---|---|
| OPTIMAL | `optimal` (strategy) / run `optimal` iff EVERY optimized profile OPTIMAL | proven optimum |
| FEASIBLE | `feasible` | time-limited solution — never labelled optimal |
| INFEASIBLE | `infeasible` profile + named conflicts (`SufficientAssumptionsForInfeasibility`) | constraints contradictory — the only state that may be reported as agronomic infeasibility |
| MODEL_INVALID | `model_invalid` solver failure | malformed model — a bug, not an agronomic statement |
| UNKNOWN | `unknown` solver failure | solver gave up; infeasibility NOT proven |

Conflict-set limitation: CP-SAT's assumption-based conflicts are sufficient
subsets, not minimal ones; the payload states the assumptions that sufficed.

## 6. Economic evaluation (honest scope)

The platform computes NO prices, yields or margins. `economic_margin_index`
is a farmer-supplied RELATIVE index (0..100) per crop, held with provenance
`source="farmer"`; absent economics skip the criterion. Gross revenue vs
variable/fixed costs vs gross margin separation, currency and valuation year
metadata require a proper farm-economics input surface (backlog M-2) — until
then no "economically optimized rotation" is claimed anywhere.

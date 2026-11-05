# M7.6 — Scenario Comparison & Decision Intelligence

Status: **IMPLEMENTED & VERIFIED** (commit `aec0a0f5`, browser E2E verified).
Engine: `decision-comparison-engine-1.0.0` · Method: `decision-comparison-1.0` · Migration: `0012_decision_comparisons`.

## 1. What it does

Assembles stored, immutable artifacts — M7.3 scenario executions, M7.4
sensitivity analyses, M7.5 robust rotation runs — into **ONE traceable,
checksummed decision document** per field. Generation **reads aggregates
only**: no engine is re-run and no agronomic calculation is duplicated.

## 2. Document sections

1. **`scope`** — every source artifact pinned BY VALUE (execution run ids +
   output checksums, robust run ids, analysis ids). Explicit scope or
   auto-selection (newest result-bearing artifacts; bounded caps: 8
   executions, 3 robust runs, 8 sensitivity analyses).
2. **`baseline_vs_scenario`** — per execution: summary counts (recalculated /
   changed / not_affected / not_evaluated) + rows (monthly + seasonal only,
   capped at 200 ordered by |percent difference|) + `largest_changes` ranking.
   Ranking is per-row percent difference; **different units are never compared
   directly**.
3. **`scenario_pairs`** — scenario-to-scenario deltas over shared
   `(feature_code, period)` rows where BOTH sides are `scenario_recalculated`
   and units match; both sides are transformed hypothetical outputs (neither
   is observed weather). Bounded to 6 pairs, top 15 deltas each.
4. **`sensitivity_interpretation`** — per analysis: top response per
   (parameter, slope-units group) with slope, units, direction, classification
   and evaluated-point count; classification counts; uncertainty-registry
   status counts; reference-reproduction status. Cross-unit or cross-parameter
   rankings are never produced.
5. **`rotation_decisions`** — per robust run: shared plans with assignment,
   worst-case objective, worst-case regret, robust feasibility, solver status;
   per-scenario weighted objectives, Pareto flags, inadmissible crops (with
   the scenario's hard reason) and violated constraints — i.e. *which
   rotation decisions remain feasible and which scenario changes the decision
   and why*.
6. **`tradeoffs`** — plan × scenario × criterion matrix of RAW values with
   units and directions (one robust run, bounded rows). No composite score.
7. **`missing_evidence`** — aggregated first-class section: execution
   `not_evaluated_reasons`, sensitivity `not_analysed_features`, robust
   `not_evaluated`, plus structural items (scenario ET0 / water feasibility;
   no climate projection or forecast scenario exists — M7.8 blocked).
8. **`findings`** — deterministic, evidence-linked statements (≤ 40), each
   with `{kind, text, evidence[]}` referencing execution runs / robust runs /
   analyses. Kinds: `largest_scenario_change`, `plan_feasibility`,
   `sensitivity_response`, `missing_evidence`.

## 3. Scientific discipline (enforced and tested)

- **No composite scores, no probabilities, no yield predictions, no universal
  recommendations.** The integration test asserts NO pseudo-statistical
  JSON keys exist (`composite_score`, `probability`, `confidence`,
  `expected_yield`, `p_value`, `likelihood`, …).
- Rankings only within the same unit; ties broken deterministically by
  identifiers (identical inputs ⇒ identical document + checksum).
- Objective units, evidence quality, missing values and applicability states
  stay visible in every section.
- Unavailable sections are declared in `not_available` with reasons — never
  hidden, never fabricated.

## 4. Persistence (migration 0012)

`decision_comparisons` — append-only: UNIQUE `(field_id, fingerprint)`
(deterministic regeneration returns the SAME row; changed scope or generator
version ⇒ NEW row), document checksum CHECK on success, partial UNIQUE on
idempotency key, **BEFORE UPDATE immutability trigger + BEFORE DELETE
protection** for result-bearing documents.

## 5. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/fields/{field_id}/decision-comparisons` | generate (idempotent; optional scope) |
| GET | `/api/v1/fields/{field_id}/decision-comparisons` | list (lean — no document body) |
| GET | `/api/v1/decision-comparisons/{id}` | detail (full document) |
| POST | `/api/v1/decision-comparisons/{id}/verify` | recompute document checksum + re-compare every scoped source's output checksum |

## 6. Tests & verification evidence

- `tests/integration/test_decision_comparisons.py` (13): golden path with
  full scope, auto-scope, deterministic regeneration (same row + checksum),
  changed scope ⇒ new document, empty-field rejection, structural honesty
  (ET0 + no-forecast items), evidence-linked findings, verify endpoint,
  trigger immutability (update/delete), tenant isolation, migration head,
  no pseudo-statistical keys.
- Browser E2E: generate + open "M7 closure E2E review" — findings (scenario
  changes with units, plan feasibility with worst-case objectives, sensitivity
  slopes with units/classifications), plan table, raw trade-off matrix, verify
  → `verified`; desktop + 390 px.

## 7. Known limitations

- The document is an assembly of stored results; it inherits every upstream
  limitation (M7.3 ΔT/M_p-only transformations, no ET0 under scenarios; M7.4
  OAT/grid determinism; M7.5 worst-case semantics).
- `baseline_vs_scenario` rows are capped (200/execution, monthly+seasonal);
  daily aggregates remain in the execution run itself (noted in the payload).

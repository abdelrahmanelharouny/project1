# M7.4 — Limitations & Backlog

---

## 1. Implemented and verified (recap)

Deterministic one-factor-at-a-time analysis and opt-in joint parameter grids over
ONE immutable M7.3 execution run; reference reproduction gate; versioned response
classification; explored parameter-range envelopes; finite-grid interaction
contrasts; a 7-category uncertainty/limitation registry; 8 tenant-scoped APIs;
Sensitivity workspace tab; migration 0010 with trigger-frozen analyses; 742/742
tests; browser E2E verified.

## 2. Scientific limitations (inherent to the method)

| Limitation | Consequence | Where disclosed |
|---|---|---|
| The envelope is deterministic, not probabilistic | a user-supplied parameter range implies NO distribution; no confidence/prediction intervals exist anywhere | envelope field naming; `parameter_range_bounds` registry item; UI disclosure on every surface |
| Explorable set = configured set | a parameter the source execution never configured cannot be analysed (no reference value); users create a new scenario instead | API `explorable_parameters_detail`; UI not-applicable card; method §1.2 |
| Uniform ΔT / multiplicative M_p semantics inherited | responses inherit M7.3's structural limits (variance/DTR preserved; event timing preserved) | registry items `uniform_delta_t`, `transformation_preserves_timing` |
| Threshold classification is heuristic | jump-factor/step-share rubric flags *suspected* discontinuities; it is not a change-point estimator; slope annotated invalid across the jump, never hidden | method §5.2; `slope_validity`; classification_version column |
| Finite-grid interaction contrast ≠ Sobol | corner contrast over user-defined bounds; additive-by-construction for single-family features (negative control) | field naming; grid note; method §6.3; tested |
| No source measurement-error distributions | observation uncertainty stays `not_quantified`; coverage stats are data-quality descriptors, not error bars | registry items; no numerics invented |
| Single-parameter ranking is trivial | "largest effect" ranking only among same-unit parameters; single-parameter analyses state that explicitly | method §5.3 |
| Per-evaluation transformed observations are not persisted | evaluations are reproducible pure functions; the checksum + reproduction gate anchor them; revisit only with a concrete audit requirement | method §3.5; database doc §2 |

## 3. Engine scope limitations (M7.4 boundaries)

| Item | Status | Reason / path forward |
|---|---|---|
| Probabilistic methods (Monte Carlo, LHS, Sobol, Morris, bootstrap, Bayesian) | not implemented, no stub interfaces | require input distributions/evidence that do not exist here; prerequisites documented in method §9 |
| Confidence intervals from deterministic grids | never (methodologically unsound) | replaced by the envelope vocabulary |
| Crop/yield/irrigation/rainfall-probability claims | out of scope entirely | M7.0 C2 discipline; registry + disclosures |
| Scenario ET0 sensitivity | impossible | ET0 features are not recalculated by M7.3 (C5 lineage); registry `no_et0_recalculation` |
| Synchronous analysis execution | current behavior, like M7.3 | budget guard (≤100 unique evaluations) keeps latency bounded; async job integration deferred |
| Grid restricted to both-parameters-configured sources | by design | a 1-D "grid" is an OAT sweep; enforced with 422 `grid` finding |
| Client-side table caps (100 OAT rows / 50 grid summaries) | UI ergonomics | full data always available via the APIs' filters; noted in the UI |

## 4. Backlog (explicitly deferred — do NOT confuse with commitments)

1. **Async analysis execution** — reuse the job-status vocabulary; cancellation semantics.
2. **Per-analysis response charts** — pure-SVG response curves per feature (the data is already served).
3. **Server-side pagination for responses/grid** — when analyses grow beyond the current caps' comfort.
4. **Second-order classification rubric** — curvature metrics (finite-second-difference sign) as a versioned rubric bump.
5. **Cross-run comparative sensitivity** — comparing two analyses of DIFFERENT runs (requires a careful definition-diff surface; M7.5 territory).
6. **Multi-scenario robustness** — M7.5 (multi-scenario rotation evaluation), M7.6 (robust optimization), M7.7 (Digital Twin evolution) — all explicitly out of M7.4 scope.
7. **Probabilistic layer** — only after sourced measurement-error distributions exist (method §9 prerequisites).

## 5. Environmental notes

- No network-dependent tests were added; the known Open-Meteo-dependent ingestion
  test (M7.3 §5) is unchanged and passed at final verification.
- The sandbox reaps user-spawned dev servers within minutes; browser verification
  was performed with per-step server guards. One real client-side defect (unbounded
  DOM tables wedging the tab) was found and fixed during browser verification and
  re-verified — see `M7_4_VERIFICATION_REPORT.md` §3.

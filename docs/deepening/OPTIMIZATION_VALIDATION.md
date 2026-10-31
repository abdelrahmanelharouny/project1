# OPTIMIZATION_VALIDATION.md — independent validation evidence (Phase F + H)

All items below were EXECUTED (test names cited; suite 341 passed 2026-10-31).

## 1. Constraint verification (solver-independent layer)

| Property | Test |
|---|---|
| Exactly-one per season; admissibility (incl. water-estimability) | `test_no_silent_hard_constraint_relaxation`, `TestOptimizerConstraints` |
| Water allocation respected when feasible | `test_water_allocation_respected` (recalibrated: 45,000 m³ separates thirsty ≈49,780 m³ from frugal ≈38,659 m³ on 10 ha with FULL ET0 coverage) |
| Infeasible when allocation too small; named conflict | `test_infeasible_when_allocation_too_small`, `test_infeasible_reported_with_conflict` (API) |
| Confirmed rotation breaks: pairwise, across history boundary, min_break_seasons | `test_confirmed_rotation_break_enforced_pairwise`, `..._across_history_boundary`, `test_break_rule_requires_min_break_seasons` |
| Deep rules (k=5) enforced beyond the old caps | `TestF06DeepBreakRules` (checker + optimizer) |
| Reference rules NEVER bind the solver; family scoping only where cited mechanism justifies; region gating | `test_reference_rules_never_bind_the_solver`, `test_family_scoped_confirmed_rule`, `test_regional_rule_does_not_apply_to_other_regions` |
| Baseline violation detected WITHOUT the solver | `test_baseline_violation_detected_without_solver` |

## 2. Pareto validation (independent of the optimizer)

| Property | Test |
|---|---|
| Dominated never on front; front membership exact | `TestParetoProperties::test_dominated_solution_never_on_front` |
| Duplicate solutions: both on front, no mutual dominance | `test_identical_solutions_both_on_front` |
| Disjoint evaluable sets → mutually non-comparable (recorded) | `test_disjoint_evaluable_sets_non_comparable` |
| Weight change changes ranking (preference sensitivity) | `test_weight_change_changes_ranking` (API) |
| Weighted objective renormalization + skipped weights | `test_weighted_objective_renormalizes_and_reports_skipped` |
| Neutral normalisation for single/identical values | `test_normalization_within_set_neutral_for_single_solution` |
| Legume strategy wins the soil-health profile (domain sanity) | `test_legume_strategy_wins_soil_health` |

## 3. Status semantics

| Property | Test |
|---|---|
| MODEL_INVALID/UNKNOWN never reported as infeasible | `TestF04SolverSemantics::test_infeasible_result_carries_explicit_status`; service mapping covered by run-level statuses |
| Baseline never claims solver status | `test_baseline_never_claims_solver_status` (`not_attempted`) |
| Feasibility-only solve (no evaluable criteria) still returns a solution | `test_no_evaluable_criteria_yields_feasibility_only_solution` |

## 4. Reproducibility

| Property | Test |
|---|---|
| Same inputs → same assignment + objective (workers=1, seed=0) | `TestReproducibility::test_same_inputs_same_solution`, `test_deterministic_reproducibility` |
| API re-run → identical strategy checksums | `test_reproducible_runs_same_checksums` (integration) |
| Feature values: identical inputs → identical checksums | M4-U16, `test_checksum_stable_and_value_sensitive` |

## 5. Missing-information treatment (hard property tests)

| Property | Test |
|---|---|
| Partial ET0 refuses the water estimate (never under-reports) | `TestF07WaterRefusal` |
| Missing economics never zero | `test_missing_economics_never_zero` |
| Missing climate evidence → unevaluated (not zero, not exclusion) | `test_missing_climate_evidence_is_unevaluated_not_zero` |
| Deliberate knowledge gaps stay gaps (faba bean has no Kc) | `test_deliberate_gaps_stay_gaps`, `test_seed_pack_has_no_confirmed_regional_rules` |
| Unevaluated candidates cannot enter optimization | `test_unevaluated_candidate_rejected_by_validator` |

## 6. Integer scaling verification

Water constraint arithmetic: coefficient `mm × area_m2` is litres
(1 mm over 1 m² = 1 L); RHS `m³ × 1000` is litres; equality of units verified
by construction and by the 45,000 m³ separation test above (38,659 < 45,000 <
49,780 produces exactly the intended feasibility split).

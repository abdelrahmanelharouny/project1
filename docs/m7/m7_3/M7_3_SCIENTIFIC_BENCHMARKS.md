# M7.3 — Scientific Benchmarks & Reference Review

---

## 1. Methodological references (reviewed before implementation)

| Source | Use in M7.3 |
|---|---|
| **IPCC TG-GCIA (1994)** Technical Guidelines for Assessing Climate Change Impacts and Adaptations | establishes the delta-change/perturbation family for impact assessment: apply change factors to an observed baseline to test system sensitivity. M7.3's temperature delta + precipitation ratio are the two canonical members. |
| **IPCC AR6 WGI, Chapter 10** (linking global to regional climate change) | grounds the disclosure that a uniform, variable-independent shift cannot reproduce changed variability, extremes structure, or circulation — the basis of the "preserved vs not representable" list in TRANSFORMATION_METHODOLOGY §4. |
| **Climate Change in Australia — delta change / sensitivity testing** (CCiA learning support) | practical formulation used by impact practitioners: future scenario = observed + ΔT (temperature) / observed × ratio (precipitation); explicitly a sensitivity technique, not a projection. |
| **Canada's Climate Change Scenarios — delta method** | same family; documents the additive (°C) / multiplicative (ratio) convention adopted verbatim in the contracts and docs. |

All four sources frame the technique; **none** legitimizes presenting a user-defined perturbation as a climate
projection. Every M7.3 surface (API note fields, run warnings, UI badges) labels outputs as user-defined
hypothetical sensitivity experiments. The worked distinction:

- **Preserved by uniform ΔT:** day-to-day sequencing, temporal variance around the shifted mean, diurnal
  range (Tmin & Tmax shifted equally).
- **Preserved by multiplier:** temporal occurrence of recorded events (wet/dry pattern), event rank order.
- **Not representable (disclosed, never generated):** new events, new dry days, changed storm
  timing/structure, changed variance, asymmetric Tmin/Tmax warming, circulation changes, feedbacks.
- **Dry-environment caveat:** near-zero baseline × multiplier stays near zero — multiplicative dryness
  experiments cannot create water; documented in methodology §4 and surfaced as disclosures.

## 2. Golden numeric benchmarks (implemented as automated tests)

### 2.1 Temperature (`tests/unit/test_scenario_transformations.py`)

| Benchmark | Expected | Test |
|---|---|---|
| ΔT = 0 | exact reproduction | `test_zero_delta_reproduces_original` |
| ΔT = +2.5 on 10.0 | 12.5 (exact) | `test_positive_delta_exact` |
| ΔT = −3.25 on 10.0 | 6.75 (exact) | `test_negative_delta_exact` |
| Tmin 5.0 / Tmax 20.0, ΔT=2 | DTR preserved (15.0) | `test_diurnal_range_preserved_on_paired_shift` |
| missing input | missing output (never manufactured) | `test_missing_stays_missing`, `test_missing_observation_value_stays_missing`, `test_quality_missing_not_zeroed` |
| unit gate | refusal, never conversion | `test_incompatible_unit_refused`, `test_targeted_but_bad_unit_reported` |
| overflow | TransformationError | contract test via `math.isfinite` gate |

### 2.2 Precipitation

| Benchmark | Expected | Test |
|---|---|---|
| M_p = 1.0 on 7.3 | 7.3 exact (IEEE-754 identity) | `test_multiplier_one_reproduces_original` |
| M_p = 0.0 on 4.2 | 0.0 (explicit hypothetical zeroing) | `test_multiplier_zero_zeroes_valid_rain` |
| M_p = 0.0 on missing | missing (never zero) | `test_multiplier_zero_missing_stays_missing` |
| M_p = 0.8 on 10.0 | 8.0 | `test_fractional_multiplier` |
| M_p = −0.5 | rejected | `test_negative_multiplier_rejected` |
| negative source | rejected (never clamped) | `test_negative_source_rejected` |
| all outputs | ≥ 0 | `test_no_negative_outputs` |
| dates | preserved verbatim | `test_derived_row_preserves_support_and_lineage` |

### 2.3 Feature recalculation (integration, synthetic temperate_seasonal profile)

| Benchmark | Expected | Test |
|---|---|---|
| monthly mean temperature, ΔT=2 | every month `difference_value == 2.0` | `test_comparison_math` |
| monthly mean temperature, ΔT=2 | anomaly feature unchanged (Δ cancels) | smoke-verified; property of uniform shift |
| ET0 family | `not_evaluated` with ET0 reason, scenario_value NULL | `test_et0_never_reused_as_scenario_output` |
| wind / soil-moisture features | `not_affected` with reason, no fabricated values | `test_unaffected_features_reported_not_fabricated` |
| seasonal totals | recomputed from transformed daily values (engine coverage rules intact) | engine pass tests |
| temporal support | non-daily supports disclosed; daily features never built from monthly data | engine exclusion machinery + `non_daily_supports` warning |

### 2.4 Water safety

| Benchmark | Expected | Test |
|---|---|---|
| modified temperature ≠ recalculated ET0 | `reference_et0_*` excluded everywhere; baseline ET0 never copied | `test_et0_never_reused_as_scenario_output` |
| water balance under mixed inputs | excluded with reason | same |
| no irrigation/yield claims | no water-plan or rotation invocation in the execution path | architecture (module imports) |

## 3. Reproducibility benchmarks (integration)

| Benchmark | Expected | Test |
|---|---|---|
| two scenarios, identical inputs | identical `output_checksum` | `test_identical_inputs_identical_checksum` |
| changed assumption | different checksum | `test_changed_assumption_changes_checksum` |
| same scenario re-POST | same run (fingerprint replay) | `test_same_scenario_replay_returns_same_run` |
| client idempotency key | same run | `test_idempotency_key_replay` |
| verify endpoint | recomputed == stored; parent + definition + manifest intact | `test_verify_endpoint_confirms_integrity` |
| canonical float stability | 6-decimal rounding in checksum documents | `contracts.canonical_value` + verify tests |

## 4. Immutability benchmarks (integration + DB-level)

| Benchmark | Test |
|---|---|
| observations count/sum unchanged after execution | `test_parent_artifacts_unchanged` |
| parent feature values unchanged | same |
| field-state checksum unchanged | same |
| finalized scenario definition unchanged | `test_scenario_definition_unchanged_after_execution` |
| UPDATE tamper on result-bearing run rejected by trigger (3 attempts) | `test_execution_triggers_freeze_result_rows` (migration) + `test_result_bearing_run_frozen_at_db_level` |
| DELETE of result-bearing run rejected by trigger | same |
| scenario deletion blocked by FK RESTRICT while runs exist | same |
| failed runs deletable (retry path) | same |

## 5. Security benchmarks

| Benchmark | Test |
|---|---|
| second tenant: execute/read/verify all 403/404 | `test_other_tenant_cannot_execute_or_read` |
| unknown ids never leak existence | `test_scenario_of_other_tenant_not_executable` |
| eligibility enforcement (draft / observed / unsupported) | `TestExecutionEligibility` |

## 6. Benchmark status

All benchmarks above are executable tests in the repository (not manual procedures) and pass as part of the
full backend regression (see `M7_3_TEST_AND_VERIFICATION.md` for the exact counts and identity of the run
that produced them).

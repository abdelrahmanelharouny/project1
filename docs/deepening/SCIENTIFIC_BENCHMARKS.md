# SCIENTIFIC_BENCHMARKS.md — Phase H benchmark suite (results 2026-10-31)

Suite location: `tests/unit/test_deepening_regressions.py` (21 tests),
`tests/integration/test_deepening_api.py` (6 tests), plus updated contract
tests. Full suite: **343 passed**.

## 1. Golden numerical tests (independently derived expected values)

| Benchmark | Expected | Derivation | Test |
|---|---|---|---|
| CHIRPS area-weighted field mean | 8.5714 mm | 2-cell raster: 0 mm over 100% of field weight, 20 mm over 75% → (0·1.0+20·0.75)/1.75 | `TestAreaWeightedMean` |
| CHIRPS single-cell unweighted mean | 7.0 mm | identity | `TestAreaWeightedMean` |
| SoilGrids soc unit conversion | 120 dg/kg → 12.0 g/kg | ÷10 (live-verified wire unit) | contract `test_wire_units...` |
| SoilGrids interval half-width | (16−8)/2 = 4.0 g/kg | Q0.05=80, Q0.95=160 dg/kg → ÷10 | `test_prediction_interval_from_q005_q095` |
| Water-estimate separation on 10 ha | thirsty 49,780 m³ > 45,000 > frugal 38,659 m³ | FAO-56 Kc curve × monthly ET0 (150+140+130+120+90 mm), 10 ha | `test_water_allocation_respected` |
| Wind unit conversion (km/h → m/s) | 10 km/h = 2.7778 m/s | ÷3.6 | M3-U2 (retained) |
| Anomaly arithmetic | value − baseline_mean; z = (x−μ)/σ (sd>0 else not evaluated) | definition | M4-U12 + F-11 tests |
| Geodesic area of 1°×1° equator square | 12,000–12,600 km² | WGS84 | U14 (retained) |
| Pentad 26–end-of-month bounds | variable length, leap-correct | CHC calendar | M3-U16 (retained) |

Boundary conditions and tolerances: pytest.approx with explicit abs; engine
values rounded to 4 dp consistently (checksum-stable).

## 2. Property-based tests (invariants)

| Property | Test |
|---|---|
| Suspect/invalid observations never shift an aggregate | `TestF02QualityFilter` (mean stays 10.0 with a 999 °C suspect row present) |
| Dominance is antisymmetric on shared sets; dominated ⇒ never on front | `TestParetoProperties` |
| Identical solutions both on front (no spurious dominance) | `test_identical_solutions_both_on_front` |
| Non-comparable pairs (disjoint evaluable sets) never dominate | `test_disjoint_evaluable_sets_non_comparable` |
| Weight renormalization preserves relative preference; skipped weights reported | `test_weighted_objective_renormalizes_and_reports_skipped` |
| Determinism: same inputs → same assignment + objective | `TestReproducibility` (+ API checksum equality) |
| Missing ET0 month ⇒ estimate refused (monotone honesty: partial data cannot lower a reported requirement) | `TestF07WaterRefusal` |
| Missing economics/traits never become zeros (skipped with reasons) | retained M5 tests + F-10 (margin carries no fabricated citation) |
| DB rejects duplicate species-level Kc anchors | `TestF18KcDbUniqueness` (NULLS NOT DISTINCT) |

Qualified assumptions: normalisation neutral-0.5 rule applies when <2
evaluable values exist (documented in ADR-0018); the determinism property
holds for `num_search_workers=1` with recorded seed (multi-worker CP-SAT is
not guaranteed deterministic and is deliberately not used).

## 3. Metamorphic tests

| Transformation | Invariant | Status |
|---|---|---|
| Reorder equivalent observations (sorted by (period_start, observed_at)) | aggregates unchanged (first-wins determinism) | covered by engine sorting + `test_duplicate_local_day_collapsed_deterministically` |
| Add irrelevant observations (other variables) | existing feature values unchanged | `test_missing_variable_drops_dependent_features_with_reason` + filter-by-variable construction |
| Introduce missing intervals | coverage drops; values NULL below policy — never scaled/zero-filled | M4-U7/U8 |
| Switch data products | one product per variable; selection recorded; no blending | `test_real_product_preferred_and_never_blended` |
| Knowledge pack version change | pack_refs + checksums change; candidate citations point at the new version | `test_import_and_idempotent_reimport`, F-09 winner determinism |
| Optimization weights change | ranking may change; skipped-weight reporting updates | `test_weight_change_changes_ranking`, `test_custom_weights` |
| Unit change with equal physical quantity | canonical units enforced at ingestion (km/h→m/s, dg/kg→g/kg); mixed-unit rows rejected | contract suite |

## 4. Cross-component integration validation

| Chain | Evidence |
|---|---|
| Observation → feature value provenance | M4-C1 (ids, products, versions, evidence classes, calendar basis, checksum) |
| Feature run → rotation climate evidence | `climate_run_refs` per season + `feature_run_ids` on the run + warnings for synthetic/incomplete months |
| Knowledge versions → evaluations | `knowledge_pack_refs` (code, version, checksum, license) on every rotation run; trait-level pack versions in citations |
| Provenance survives optimization | strategy checksums over (problem checksum + assignment + criteria); problem checksum covers seasons/candidates/allocation/packs/seed/engine |
| Frontend labels match backend meanings | F-17 corrections; SYNTHETIC surfaces re-audited (E2E) |
| Synthetic never masquerades | per-row badges, run banners, candidate reason labels, passport flag (F-01) |
| Tenant isolation end-to-end | I7–I10, M4-I7, K13.1–K13.3, F-03 tests |

## 5. Performance & operational notes (observed, single-node sandbox)

- Full suite 3.7 min incl. DB roundtrips; rotation solve times « 100 ms for
  4 seasons × 11 crops (well under the 10 s cap → UNKNOWN status practically
  unreachable today, but semantically handled).
- Indexed hot paths post-0005 (farm_constraints, observations natural key,
  feature values, audit). Known heavy paths: knowledge list endpoints N+1
  (crops list) and `compare_runs` full-value loads — bounded today by pack
  and window sizes; pagination backlog B-2.

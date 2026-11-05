# M7.3 — Limitations & Backlog

---

## 1. Implemented and verified (recap)

Uniform additive temperature shifts (`temperature_delta_c`) and multiplicative precipitation scaling
(`precipitation_multiplier`) execute against finalized, executable scenario definitions; affected features
are recomputed by the existing M4 engine from the transformed values; results are checksummed, immutable,
tenant-isolated, and disclosed end-to-end.

## 2. Scientific limitations (inherent to the method)

| Limitation | Consequence | Where disclosed |
|---|---|---|
| Uniform ΔT preserves baseline variance and diurnal range | changed variability / asymmetric Tmin-Tmax warming / changed extremes structure are NOT representable | methodology §4; run warnings; UI |
| Multiplier preserves event occurrence pattern | no new rain events, no new dry days, no changed storm timing | methodology §4 |
| Multiplicative adjustment near zero baseline behaves poorly in physical terms | dry-environment sensitivity tests only | methodology §4; UI footnotes |
| A perturbation is not a climate trajectory | outputs are never forecasts/projections | every surface (C2 discipline) |
| No scenario ET0 | ET0 family excluded with reason; no irrigation-demand claims | VARIABLE_COMPATIBILITY §4 |

## 3. Engine scope limitations (M7.3 boundaries)

| Item | Status | Reason / path forward |
|---|---|---|
| `precipitation_delta_mm` | blocks execution | not a supported M7.3 transformation; an additive-shift implementation would need its own scientific note and tests |
| `seasonal_timing_shift_days`, `rainfall_period_shift_days` | blocks execution | re-dating observations would falsify the historical record; a timing experiment needs a redesign that moves scenario periods, never observation dates |
| Non-daily source aggregation recalculation | transformed values stored; aggregation-based features `not_evaluated` | the M4 engine is daily-first by design; extending monthly/pentad-source aggregation is an engine change, deliberately out of M7.3 scope |
| `instant` / `hourly` / `annual` supports | excluded from transformation, reported | no scientific use case in this milestone |
| Spatial scope | scenario is pinned to the parent field's boundary version | spatial re-mapping (grid shifting) is not defined for point perturbations |
| Synchronous execution | large windows could exceed comfortable HTTP latencies | background job integration is a deliberate non-goal in M7.3 (statuses already model the async vocabulary) |

## 4. Backlog (explicitly deferred — do NOT confuse with commitments)

1. **Additive precipitation transformation** — requires a scientific note (sublimation/wetting-loss effects
   of adding water, threshold behavior) + golden tests before implementation.
2. **Scenario ET0 recalculation** — only after a validated, sourced method with humidity/radiation/wind
   scenario semantics exists (M7.0 condition C5 lineage).
3. **Monthly/pentad-source feature recalculation** — extend the M4 engine's aggregation paths with explicit
   version bump; keep daily-first defaults.
4. **Asymmetric temperature adjustments** (separate Tmin/Tmax deltas, DTR change) — natural follow-up for
   extremes research; requires its own dependency-graph entries.
5. **Background/async execution** — reuse the existing job-status vocabulary; add cancellation semantics.
6. **Execution cost guards** — per-tenant concurrency limits and long-window warnings (window cap exists:
   3 years).
7. **Multi-scenario comparison views** — M7.4/M7.5 territory; the definition-level comparison (M7.2) and
   single-run comparison (M7.3) are the current supported surfaces.
8. **Downstream robustness** — sensitivity analysis (M7.4), multi-scenario rotation evaluation (M7.5),
   robust optimization (M7.6), Digital Twin evolution (M7.7) — all explicitly out of M7.3 scope.

## 5. Environmental note

`test_data_passport.py::test_same_variable_from_two_sources_gets_two_entries` ingests from the real
Open-Meteo archive API. During the implementation session the upstream answered "The service is
overloaded" and the test failed environmentally (identical failure on the pristine M7.2 baseline in
this sandbox). At final verification the upstream was healthy and the complete suite passed **657/657**
(see TEST_AND_VERIFICATION §2). The test is network-dependent by design; the recommendation stands to
point the second-source assertion at a mocked provider contract in a future hardening pass so the
regression suite is fully hermetic. M7.3 did not modify that test (baseline-preserving discipline).

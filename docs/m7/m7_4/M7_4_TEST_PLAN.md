# M7.4 — Test Plan & Golden Mathematics

All new tests live beside their M7.3 predecessors. No existing test is weakened;
the full suite must remain green (baseline at Phase 0: **657 passed**).

---

## 1. New test files

| File | Suite | Covers |
|---|---|---|
| `tests/unit/test_sensitivity_math.py` | unit | linspace design + validation, dedupe plan, finite-difference slopes (central/one-sided), elasticity rules incl. structured unavailability, direction, classification rubric (constant/monotonic/non-monotonic/threshold/insufficient), envelope bounds, grid summaries + interaction contrast (single-family ⇒ exactly 0), guardrail checks |
| `tests/unit/test_sensitivity_contracts.py` | unit | canonical analysis configuration + fingerprint determinism, checksum document stability (key insertion order / float rounding), registry rubric statuses & applicability values, version constants |
| `tests/integration/test_sensitivity_analyses.py` | integration | full API lifecycle over the synthetic fixture: eligibility gates (draft scenario? result-bearing run? tampered pins?), reference reproduction, OAT golden math, envelope, grid interaction, uncertainty registry content, idempotent replay (fingerprint + idempotency key), immutability via trigger, tenant isolation, verify endpoint, migration up/down of 0010 |

## 2. Golden expectations (asserted numerically)

Fixture: synthetic `temperate_seasonal` 2015-2017, scenario
`user_defined_stress` with `temperature_delta_c=2.0`,
`precipitation_multiplier=0.8`, period 2016, executed (M7.3 golden path).

1. **Reproduction gate**: analysis `reference_reproduction.reproduced == true`,
   `mismatched_rows == []`, `observation_count_match == true`.
2. **ΔT slope linearity**: `air_temperature_mean_monthly` OAT response vs
   `temperature_delta_c` — slope **exactly 1.0** (`degC / degC`),
   `monotonic_increasing`, `n_evaluated_points == n_points`,
   envelope = `[ref + lower, ref + upper]` within 1e-9,
   classification ≠ `threshold_suspected`.
3. **M_p elasticity**: `precipitation_total_monthly` OAT vs
   `precipitation_multiplier` — elasticity **exactly 1.0** (when the reference
   monthly baseline ≠ 0), slope == baseline total (`mm / multiplier`).
4. **Envelope naming**: every response exposes
   `explored_parameter_range_envelope` with `parameter_lower/parameter_upper/
   lower/upper`; no field is named like a confidence interval.
5. **Threshold detection**: `hot_days_35c_count_monthly` under a wide ΔT
   sweep crossing 35 °C shows a step (`threshold_suspected`) or monotonic
   counts — the response never claims a smooth linear slope across the jump
   without the invalidity annotation.
6. **Grid interaction**: joint grid (both parameters configured) —
   `interaction_contrast == 0.0` (exactly) for every single-family feature;
   `interaction_interpretation == "approximately_additive"`.
7. **Zero-baseline elasticity**: a feature row whose reference value is 0
   (e.g. a dry month's precipitation total under the fixture, if present)
   carries `elasticity.status == "unavailable"` with
   `reference_value_is_zero` — never a division.
8. **Determinism**: two identical POSTs (different idempotency keys, same
   design) → same `output_checksum`, second POST returns the first analysis.
9. **Immutability**: result-bearing analysis UPDATE of any content column via
   raw SQL raises; DELETE of the analysis cascades only through its own tables
   and leaves the run untouched.
10. **Tenant isolation**: second tenant gets 404 on every analysis endpoint.
11. **Registry**: ≥ 7 categories present; `parameter_range_bounds` is
    `bounded_exploratory`; `source_measurement_error` is `not_quantified`;
    no item carries a fabricated numeric confidence.
12. **Verify endpoint**: all five flags true on a healthy analysis.

## 3. Negative gates

- Bounds not containing the reference → 422 with the exact reason.
- `n_points` out of 3..21 → 422; negative multiplier lower bound → 422;
  |ΔT| > 25 or M_p > 10 → 422.
- Grid on a single-parameter source → 422 (`grid_not_available`).
- Unique-evaluation budget exceeded → 422.
- Analysis against a non-result-bearing run → 409.
- Tampered parent checksum (SQL-updated Field State checksum) → 409
  `PARENT_STATE_CHECKSUM_MISMATCH` and no analysis created.

## 4. Migration tests

Extend the migration test class pattern: scratch DB `upgrade head` →
`sensitivity_*` tables present with trigger; `downgrade -1` → absent;
re-upgrade clean.

## 5. Definition of done

- All new tests green; full suite ≥ 657 + new, 0 failures.
- `bun run lint` clean; no new tsc errors in M7.4 files.
- Browser journey verified (see `M7_4_FRONTEND_WORKSPACE.md` §3).

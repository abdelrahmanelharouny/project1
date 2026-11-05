# M7 — Scientific Limitations & Unavailable Capabilities

Scope: M7.5 (robust rotation), M7.6 (decision intelligence), M7.7 (digital
twin), plus the M7.8 readiness gate. This is the authoritative
unavailability list for the completed M7 roadmap; the underlying M7.3/M7.4
limitations apply unchanged.

## 1. Structural unavailability (cannot be produced by the system)

| Capability | Status | Reason |
|---|---|---|
| Scenario ET0 | **UNAVAILABLE** (M7.3, unchanged) | Reference ET0 depends on radiation/humidity/wind; a ΔT/M_p transformation cannot derive it. M7.3 refuses to approximate; robust runs clear ET0 fields explicitly. |
| Scenario water requirement / irrigation demand | **UNAVAILABLE** | Follows from scenario ET0 (FAO-56 needs ET0). Water criteria render not evaluable per scenario. |
| Water allocation under scenarios | **REJECTED** (`WATER_ALLOCATION_UNSUPPORTED`) | An allocation would make the water constraint unevaluated everywhere; unevaluated constraints are never treated as satisfied. Rejection is a documented error, not a silent drop. |
| Climate projections (CMIP/SSP/RCP-type) | **BLOCKED — M7.8 gate failed** | No real, documented, compatible projection provider exists in the repository. Providers implemented: synthetic, ERA5(-Land), CHIRPS v3, Open-Meteo **Historical archive** only, SoilGrids, farmer records. Scenario types `climate_projection` / `weather_forecast` are contract-only and rejected at creation (M7.2 condition C5). M7.8 prerequisites: a licensed, sourced, versioned provider adapter with a validation protocol (contract test + golden comparison), provenance mapping to observations, and a documented license/attribution path. |
| Weather forecasts | **BLOCKED — M7.8 gate failed** | Same as above (the implemented Open-Meteo adapter calls the historical archive API only). |
| Crop yield prediction | **PROHIBITED** | No yield evidence basis exists anywhere in the stack; the platform's charter excludes yield prediction. Decision documents and twin maturity explicitly forbid it. |
| Composite scores / probabilities / confidence intervals | **PROHIBITED** | M7.6 documents contain no pseudo-statistical keys (integration-tested); M7.5 worst-case values are labelled deterministic minima, never intervals. |
| Universal recommendations | **PROHIBITED** | Findings are evidence-linked statements scoped to the selected scenarios; no global advice. |

## 2. Semantics that must not be misread

- **Worst-case objective (M7.5)** = deterministic minimum across the
  explicitly selected scenarios of the per-scenario weighted *normalized*
  objective. NOT a confidence, prediction or probability interval.
- **Minimax regret (M7.5)** = deterministic objective gap against per-scenario
  solo optima. NOT an expected value; no probabilities anywhere.
- **"Robust"** always means: across the explicitly selected scenarios and the
  evaluated constraints only. The UI and API state this on every surface.
- **Explored parameter-range envelopes (M7.4, referenced by M7.6)** remain
  deterministic sensitivity results, not intervals.
- **Scenario-derived values (M7.3)** are hypothetical calculations over
  transformed observations — never observations; the twin's
  information-class census keeps observed / transformed / calculated apart.
- **FEASIBLE vs OPTIMAL (M5/M7.5)** — a time-limited solver result is never
  displayed or stored as optimal.

## 3. Honesty mechanics carried into M7.5–M7.7

- Missing evidence never becomes zero and never becomes an exclusion
  (unevaluated is a first-class state with reasons, surfaced in APIs, UI and
  documents).
- Cross-scenario candidate restrictions are reported per crop with the
  failing scenario and hard reason.
- Not-affected variables under scenarios contribute their stored baseline
  value as an explicit identity (recorded in `value_sources`), never a silent
  assumption.
- Deterministic regeneration: scenario sets (content checksum), robust runs
  (fingerprint), decision documents (fingerprint) and twin validations are
  append-only, trigger-frozen, and checksum-verified on demand.

# M6C — Uncertainty & Evidence Policy

M6C inherits the platform's evidence classes (8-class vocabulary in
`app/data_platform/contracts/observations.py`) and adds **where each class
may flow** inside field-management intelligence. The policy is enforced in
engines, APIs and UI (and pinned by tests where noted).

## 1. Class → M6C surface matrix

| Evidence class | Enters M6C as | Never becomes |
|---|---|---|
| `direct_field_measurement` / `laboratory_measured` | measured cover fractions, residue masses, quality values | — (highest trust) |
| `farmer_reported_record` | crop history, observations, residue figures, resources, durations, slope classes | a measured value (label kept on every surface) |
| `remote_sensing_estimate` | index readings (NDVI etc.) with provider metadata | a percentage-cover claim (no validated conversion model exists — red line) |
| `model_estimate` | M6A screening water estimates; rainfall climatology amounts | an erosivity (R) factor; a field measurement |
| `reanalysis_estimate` | climate features feeding candidate climatology | a forecast |
| `published_reference` | practice mechanisms/trade-offs, EcoCrop ranges, calendar windows | a locally confirmed rule (hard enforcement stays at confirmed_regional) |
| `confirmed_regional` | (none bundled — zero shipped) hard constraints only | never assumed |
| `synthetic_test_data` | demo evidence, clearly flagged | any real-farm recommendation (SYNTHETIC warnings propagate into cover plans, erosion runs, management plans) |

## 2. Uncertainty representation rules

1. **Missing ≠ zero ≠ false ≠ safe ≠ eligible.** Absent evidence yields
   `not_evaluated` dimensions, `—` in the UI, and named missing-input lists.
2. **Ranges stay ranges.** A sourced trait with low/high (e.g. faba_bean
   60–200 kg N/ha) is displayed as a range with its confidence; nothing is
   averaged into a point.
3. **Confidence is carried, never invented.** Claim confidence comes from the
   pack; `evidence_coverage` in the practice API is a *transparency metric*
   (share of claims with citations), never a confidence score.
4. **Screening vs model.** Erosion screening is qualitative forever unless a
   complete sourced factor set enables the labelled `screening_only`
   RUSLE-family computation — itself never presented as a validated local
   prediction nor as sediment yield.
5. **Provisional scheduler output.** Every scheduled operation carries
   `weather_check: pending` and `soil_readiness_check: manual_required`; the
   schedule is a proposal, never a guarantee (no forecast provider exists;
   climate normals are never used as forecasts).
6. **Association, not causation.** Management-plan text and practice claims
   describe mechanisms and trade-offs; no causal soil/yield impact is claimed
   from temporal association anywhere in M6C.
7. **Immutability + reproducibility.** Run snapshots (cover plans, erosion
   runs, schedule runs, management plans) are immutable; identical inputs →
   identical checksums (tested); recomputation creates a new row.
8. **Conflict handling.** Trait conflicts are rejected at pack import
   (M5 mechanism reused); practice packs cannot average incompatible
   recommendations because every claim is stored with its own source.

## 3. Honest-state guarantees surfaced to the farmer

- `unknown` cover days are reported separately and *never* counted as bare
  (property-tested).
- Unscheduled operations keep a human-readable reason
  (`reason_codes` + message) in the run and the UI.
- `over_allocated` residue balances are shown as errors to correct, never
  absorbed.
- The thresholds section of cover metrics ships empty with an explanation
  until a sourced, region-scoped threshold arrives.
- The seed packs contain **zero** confirmed-regional rows; the UI shows the
  validation status of every practice and rule.

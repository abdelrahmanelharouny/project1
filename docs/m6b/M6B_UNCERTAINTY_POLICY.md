# M6B — Uncertainty & Provenance Policy

**Status:** implemented (as-built)
**Scope:** how uncertainty, evidence quality and provenance are represented,
carried and (where applicable) propagated across the soil engines.
**Inherits:** M6A/deepening honesty rules; ADR-0028 (no invented confidence).

---

## 1. Evidence classes — the primary quality signal

Every measurement row carries one of the platform evidence classes (DB CHECK,
8 values; the soil write path accepts 5):

| Class | Treatment downstream |
|---|---|
| `direct_field_measurement` | highest authority; feeds comparisons and stocks |
| `farmer_reported_record` | valid evidence, flagged as reported; default for farmer-entered flows |
| `global_soil_prediction` | mapped prediction; never merged into measured series; SOC runs warn per prediction layer |
| `synthetic_test_data` | labelled synthetic; never validates an agronomic claim |
| `curated_agronomic_reference` | reference-table value (screening context) |

Structural enforcement: `source_kind='soilgrids_profile'` requires
`evidence_class='global_soil_prediction'` (write refused otherwise); `station_`,
`satellite_` and `reanalysis_` classes remain in the vocabulary for platform
compatibility. Evidence class never changes as data flows: derived indicators
"never upgrade evidence class" (service-layer note shipped with every
`/soil-indicators` response).

## 2. Per-row uncertainty storage

`soil_measurements` stores `uncertainty_value` (float) + `uncertainty_type`
(free text, e.g. the SoilGrids half-width semantics). The assessment passes
`uncertainty` through on every available-indicator row. There is deliberately no
composite confidence number anywhere in M6B.

## 3. Engine-by-engine treatment

| Engine | Uncertainty handling as built |
|---|---|
| Texture classification | deterministic; errors are refusals (fractions inconsistent → error, no fuzzy class). Silt derivation disclosed per result. |
| Porosity | basis labelling: `measured_pd` vs `assumed_pd` with the 2.65 g/cm³ disclosure — an explicit estimate label instead of a CI. |
| AWC | point values with matric potentials recorded; profile totals labelled by covered depth when gaps exist. |
| SOC stock | `LayerStockInput` accepts `oc_uncertainty_g_kg` / `bd_uncertainty_g_cm3` (1σ); `soc-stock-1.0.0` records them but does NOT propagate them into stock CIs (point estimates; honest gap, see backlog). The comparison machinery (refusals, BD-change caveat, ESM) is the shipped guard against over-claiming. |
| Nutrient budget | `is_estimate` flags (BNF), `evidence_class` per flow, availability-fraction notes on each scaled flow, moisture-basis warnings — provenance instead of pseudo-precision. No CI is produced. |
| Assessment | per-indicator `uncertainty` passthrough; quality flags; no score to which uncertainty could attach (ADR-0026). |

## 4. SoilGrids semantics (F-8)

The SoilGrids provider's uncertainty figure is the **mean of per-pixel Q05–Q95
half-widths** — explicitly NOT a field-level 90% prediction interval: averaging
per-pixel intervals ignores spatial error correlation and within-field
variability (deepening F-8, verified in the provider code and docs). The
`uncertainty_type` on ingested rows states exactly what the number is. A true
field-level PI needs a spatial covariance model (backlog S-1); SOC runs fed by
mapped layers carry per-layer "prediction, not a field measurement" warnings and
such aggregation is reported as unavailable — never averaged-and-relabeled.

## 5. Synthetic data labelling (end-to-end)

- Rows: `is_synthetic` column, `source_kind='synthetic_fixture'`,
  `evidence_class='synthetic_test_data'`.
- Engine: the assessment computes a per-domain `synthetic_flag`.
- Frontend: synthetic badges on measurement chips and domain banners.
- Rule: synthetic evidence never validates an agronomic claim; demo seed data
  (e.g. nutrient removals) is SYNTHETIC-labelled farmer-record data.

## 6. Quality flags

- `soil_sampling_events.quality_status`: `valid | suspect | invalid | not_assessed`.
- `soil_measurements.quality_status`: `valid | suspect | invalid | missing |
  estimated | not_assessed`.
- Detection-limit rows are recorded with `result_qualifier` (`<`/`>`),
  `detection_limit` and `value = None` — the value is unknown, never zero; the
  importer counts them as warning rows, and the profile renders them as
  "`< limit (unit)`" rather than a number.

## 7. Reproducibility: immutable snapshots + checksums

All three run engines persist immutable snapshots with:

- `engine_version` + `methods_version` (the exact code that produced the result);
- the full `result` JSONB (inputs used per layer/flow, refusals with reasons,
  warnings, not-evaluated lists);
- `request_parameters` and `idempotency_key` (partial-unique per field —
  resubmission returns the original run);
- `checksum_sha256` over a canonical JSON payload:
  - SOC: `{engine, methods, profile_total, layers}`;
  - nutrient budget: `{engine, methods, balance, inputs, outputs}`;
  - assessment: `{engine, assessment, domains}`;

canonicalization = `json.dumps(payload, sort_keys=True, separators=(",", ":"))`.
Identical inputs re-run produce identical checksums (property-tested); the
frontend surfaces checksums in Expert mode.

## 8. Statements M6B never makes

- No composite confidence/score; no cost/benefit/confidence figures in VOI.
- No uncertainty that was not measured or structurally disclosed (assumed PD is
  labelled; estimates are flagged; predictions stay predictions).
- No upgrade of a partial result: totals are labelled by covered depth, balances
  stay `partial`, unevaluated seasons are listed rather than zero-filled.
